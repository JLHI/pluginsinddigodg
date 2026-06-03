# -*- coding: utf-8 -*-
"""
Profil de chaussée LiDAR — détection multi-critères stratifiée par CLC.

CORRECTIFS (canopée / sursol) :
  • Le profil (z, intensité, RGB) est construit sur le SOL STRICT (classe 2
    ASPRS). Sous couvert dense, la médiane tous-points remonte vers la canopée
    et fausse tout : le filtre sol garde un profil propre (Δz ~1 m vs ~6 m).
  • À l'étiquetage, un point dont z dépasse le profil sol du bin de plus de
    SURSOL_TOL est rangé en 'sursol' (canopée, bâti, fils) au lieu d'hériter
    du label de chaussée.
  • La largeur parcelle à parcelle (cadastre, si disponible) sert de PLAFOND
    à max_rw : si la chaussée détectée dépasse le corridor non bâti + marge,
    l'expansion est re-tentée bridée. Robuste au décalage du cadastre (on ne
    s'en sert que pour la LARGEUR, jamais pour positionner les bords).

Régimes par classe CLC niveau 1 (champ clc_n1 / clc_code sur le transect) :
  1 ville · 2 champ · 3 forêt (ortho OFF) · 0 repli · 4/5 eau/humide → ignoré.

Score par bin : s_z (montée), s_drop (fossé), s_int, s_lum/s_vert (ortho only).
Bord confirmé quand score >= K (effectif) sur N bins consécutifs.
Seuils par classe VERROUILLÉS dans CLC_PROFILES (seul endroit à éditer).
"""

import math
import json
import numpy as np

from osgeo import ogr

from qgis.core import (
    QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
    QgsProcessingParameterVectorLayer, QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean, QgsProcessingParameterString,
    QgsProcessingParameterFeatureSink,
    QgsFeature, QgsGeometry, QgsPointXY,
    QgsWkbTypes, QgsFields, QgsField, QgsSpatialIndex, QgsRectangle,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from .lidar_road_profile import _strip_polygon, _wfs_json, _CADASTRE_LYR
# Signature attendue : _strip_polygon(p1x, p1y, ux, uy, t0, t1, half_w=0.5) -> QgsGeometry

LABELS = ('chaussee', 'accot_g', 'accot_d', 'fosse_g', 'fosse_d',
          'abord_g', 'abord_d', 'sursol', 'non_classe')
REQUIRED_PT = {'id_transect', 'd_along', 'z', 'intensity',
               'red', 'green', 'blue', 'classification'}
GROUND_CLASS = 2   # ASPRS : sol

# ── Profils de détection par classe CLC niveau 1 (VERROUILLÉS) ─────────────────
CLC_PROFILES = {
    1: dict(label='ville',  dz_thr=0.06, drop_thr=0.12, int_thr=0.45,
            lum_thr=0.30, vert_thr=18.0, use_ortho=True,  K=2,
            min_rw=2.5, max_rw=15.0),
    2: dict(label='champ',  dz_thr=0.07, drop_thr=0.15, int_thr=0.45,
            lum_thr=0.30, vert_thr=12.0, use_ortho=True,  K=2,
            min_rw=2.5, max_rw=12.0),
    3: dict(label='foret',  dz_thr=0.06, drop_thr=0.15, int_thr=0.55,
            lum_thr=None, vert_thr=None, use_ortho=False, K=1,
            min_rw=2.5, max_rw=10.0),
    0: dict(label='inconnu', dz_thr=0.07, drop_thr=0.15, int_thr=0.45,
            lum_thr=0.30, vert_thr=18.0, use_ortho=True,  K=2,
            min_rw=2.0, max_rw=15.0),
}
SKIP_CLC = frozenset({4, 5})   # zones humides / eau : pas de chaussée


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe(feat, name, cast, default=None):
    try:
        v = feat[name]
        return default if v is None else cast(v)
    except Exception:
        return default


def _check_fields(layer, required, label):
    names = {layer.fields().field(k).name()
             for k in range(layer.fields().count())}
    missing = required - names
    if missing:
        raise QgsProcessingException(
            f'{label} — champs requis manquants : {", ".join(sorted(missing))}')


def _smooth(arr, half_win=2):
    win = 2 * half_win + 1
    k = np.ones(win) / win
    return np.convolve(np.pad(arr, half_win, mode='edge'), k, mode='valid')[:len(arr)]


def _decode(bitmask):
    parts = []
    if bitmask & 1:   parts.append('z')
    if bitmask & 2:   parts.append('intens')
    if bitmask & 4:   parts.append('lum')
    if bitmask & 8:   parts.append('vert')
    if bitmask & 16:  parts.append('drop')
    return '+'.join(parts) if parts else ''


def _resolve_clc(val):
    """clc_n1 (entier) ou clc_code (texte '112') → classe niveau 1, ou 0."""
    if val is None:
        return 0
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        iv = int(val)
        return iv if 0 <= iv <= 5 else (int(str(iv)[0]) if str(iv)[0].isdigit() else 0)
    s = str(val).strip()
    return int(s[0]) if s and s[0].isdigit() else 0


# ── Profil binné (SOL STRICT) ───────────────────────────────────────────────────

def _build_profile(pts, bin_size, d0, n):
    """
    4 arrays lissés (z, intensity, lum, vert) construits sur les SEULS points
    sol (classification == GROUND_CLASS). Bins sans sol → NaN → interpolés.
    Retourne aussi le nb de points sol par bin (diagnostic densité).
    """
    raw = [[[], [], [], []] for _ in range(n)]
    for p in pts:
        if p['cls'] != GROUND_CLASS:
            continue
        bi = min(n - 1, max(0, int((p['d'] - d0) / bin_size)))
        raw[bi][0].append(p['z'])
        raw[bi][1].append(p['intensity'])
        raw[bi][2].append((p['r'] + p['g'] + p['b']) / 3.0)
        raw[bi][3].append(2.0 * p['g'] - p['r'] - p['b'])

    idx = np.arange(n, dtype=float)
    n_ground = np.array([len(raw[i][0]) for i in range(n)], dtype=int)

    def _col(c):
        arr = np.array([
            float(np.median(raw[i][c])) if raw[i][c] else float('nan')
            for i in range(n)])
        valid = ~np.isnan(arr)
        if valid.sum() >= 2:
            arr = np.interp(idx, idx[valid], arr[valid])
        elif valid.sum() == 1:
            arr[:] = arr[valid][0]
        else:
            arr[:] = 0.0
        return _smooth(arr)

    return _col(0), _col(1), _col(2), _col(3), n_ground


def _compute_ref(zs, its, ls, vs, ci, half_ref):
    i0 = max(0, ci - half_ref)
    i1 = min(len(zs), ci + half_ref + 1)
    return {
        'z_ref':    float(np.median(zs[i0:i1])),
        'int_ref':  float(np.median(its[i0:i1])),
        'lum_ref':  float(np.median(ls[i0:i1])),
        'vert_ref': float(np.median(vs[i0:i1])),
    }


# ── Expansion (pilotée par le profil CLC, plafond optionnel) ───────────────────

def _expand(zs, its, ls, vs, ci, direction, ref, prof, N, max_steps=None):
    """
    Expansion depuis ci vers direction (-1 gauche / +1 droite).
    s_z = montée, s_drop = descente (vs dernier bin chaussée).
    s_int/s_lum/s_vert vs référence centrale (lum/vert seulement si use_ortho).
    max_steps : nb max de bins d'éloignement (plafond parcellaire). None = libre.
    Retourne (boundary_idx, bitmasks_array).
    """
    n = len(zs)
    bitmasks = np.zeros(n, dtype=np.int32)

    use_ortho = prof['use_ortho']
    dz_thr, drop_thr, int_thr = prof['dz_thr'], prof['drop_thr'], prof['int_thr']
    lum_thr, vert_thr = prof['lum_thr'], prof['vert_thr']

    n_active = 3 + (2 if use_ortho else 0)        # z, drop, int (+ lum, vert)
    K_eff = max(1, min(int(prof['K']), n_active))

    consec = 0
    last = ci
    i = ci + direction
    while 0 <= i < n:
        if max_steps is not None and abs(i - ci) > max_steps:
            return last, bitmasks
        d_up   = zs[i] - zs[last]
        d_down = zs[last] - zs[i]
        s_z    = int(d_up   > dz_thr)
        s_drop = int(d_down > drop_thr)
        s_int  = int(abs(its[i] - ref['int_ref']) / max(ref['int_ref'], 1.0) > int_thr)
        if use_ortho:
            s_lum  = int(abs(ls[i] - ref['lum_ref']) / max(ref['lum_ref'], 1.0) > lum_thr)
            s_vert = int((vs[i] - ref['vert_ref']) > vert_thr)
        else:
            s_lum = s_vert = 0

        bitmasks[i] = s_z | (s_int << 1) | (s_lum << 2) | (s_vert << 3) | (s_drop << 4)
        score = s_z + s_drop + s_int + s_lum + s_vert

        if score >= K_eff:
            consec += 1
            if consec >= N:
                return last, bitmasks
        else:
            consec = 0
            last = i
        i += direction

    return last, bitmasks


# ── Ancrage sur axe ────────────────────────────────────────────────────────────

def _center_on_axis(p1x, p1y, ux, uy, seg_len, axis_geoms):
    if not axis_geoms:
        return seg_len / 2.0, 'geometrique'
    mid = QgsPointXY(p1x + ux * seg_len / 2.0, p1y + uy * seg_len / 2.0)
    best_d2, best_pt = float('inf'), None
    for g in axis_geoms:
        try:
            res = g.closestSegmentWithContext(mid)
            if res[0] < best_d2:
                best_d2, best_pt = res[0], res[1]
        except Exception:
            continue
    if best_pt is None:
        return seg_len / 2.0, 'geometrique'
    cd = (best_pt.x() - p1x) * ux + (best_pt.y() - p1y) * uy
    return float(max(0.0, min(seg_len, cd))), 'axe'


# ── Largeur parcelle à parcelle ────────────────────────────────────────────────

def _parcel_width(tinfo, center_d, parcel_index, parcel_store):
    """
    Corridor non cadastré = transect − union des parcelles proches, partie
    contenant le centre. Retourne largeur (m) ou None.
    """
    if parcel_index is None:
        return None
    p1x, p1y, ux, uy, L = (tinfo['p1x'], tinfo['p1y'],
                           tinfo['ux'], tinfo['uy'], tinfo['seg_len'])
    p1 = QgsPointXY(p1x, p1y)
    p2 = QgsPointXY(p1x + ux * L, p1y + uy * L)
    line = QgsGeometry.fromPolylineXY([p1, p2])
    cand = parcel_index.intersects(line.boundingBox())
    if not cand:
        return None
    try:
        union = QgsGeometry.unaryUnion([parcel_store[fid] for fid in cand])
        diff = line.difference(union)
    except Exception:
        return None
    if diff is None or diff.isEmpty():
        return None

    cx, cy = p1x + ux * center_d, p1y + uy * center_d
    center_pt = QgsGeometry.fromPointXY(QgsPointXY(cx, cy))
    parts = diff.asGeometryCollection() if diff.isMultipart() else [diff]
    for part in parts:
        if part.distance(center_pt) <= 0.05:
            verts = part.asPolyline()
            if len(verts) >= 2:
                ds = [(v.x() - p1x) * ux + (v.y() - p1y) * uy for v in verts]
                return float(max(ds) - min(ds))
    return None


# ── Pipeline complet (un transect) ──────────────────────────────────────────────

def _analyze(pts, tinfo, axis_geoms, prof, bin_size, accot_drop, half_ref, N,
             parcel_index, parcel_store, parcel_margin):
    if len(pts) < 4:
        return None

    pts_s = sorted(pts, key=lambda p: p['d'])
    d0, d1 = pts_s[0]['d'], pts_s[-1]['d']
    if d1 - d0 < prof['min_rw']:
        return None

    n = max(4, int(math.ceil((d1 - d0) / bin_size)) + 1)
    zs, its, ls, vs, n_ground = _build_profile(pts_s, bin_size, d0, n)

    cd, ancrage = _center_on_axis(
        tinfo['p1x'], tinfo['p1y'], tinfo['ux'], tinfo['uy'],
        tinfo['seg_len'], axis_geoms)
    ci = max(0, min(n - 1, round((cd - d0) / bin_size)))

    ref = _compute_ref(zs, its, ls, vs, ci, half_ref)

    # 1ʳᵉ passe : expansion libre
    lb, bm_l = _expand(zs, its, ls, vs, ci, -1, ref, prof, N)
    rb, bm_r = _expand(zs, its, ls, vs, ci, +1, ref, prof, N)
    road_w = (rb - lb + 1) * bin_size

    # Plafond parcellaire : re-tentative bridée si la chaussée déborde le corridor
    larg_parc = _parcel_width(tinfo, cd, parcel_index, parcel_store)
    capped = False
    if larg_parc and road_w > larg_parc + parcel_margin:
        max_half = max(1, int(((larg_parc + parcel_margin) / bin_size) / 2.0))
        lb, bm_l = _expand(zs, its, ls, vs, ci, -1, ref, prof, N, max_steps=max_half)
        rb, bm_r = _expand(zs, its, ls, vs, ci, +1, ref, prof, N, max_steps=max_half)
        road_w = (rb - lb + 1) * bin_size
        capped = True

    bitmasks = bm_l | bm_r
    if road_w < prof['min_rw'] or road_w > prof['max_rw']:
        return None

    # Labels par bin (sol) : chaussée, puis fossé / accotement
    search_n = max(1, int(3.0 / bin_size))
    drop_thr = prof['drop_thr']
    z_lb, z_rb = float(zs[lb]), float(zs[rb])
    labels = []
    for i in range(n):
        if lb <= i <= rb:
            labels.append('chaussee')
        elif i < lb:
            within = (lb - i) <= search_n
            if within and zs[i] < z_lb - drop_thr:
                labels.append('fosse_g')
            elif within and zs[i] < z_lb - accot_drop:
                labels.append('accot_g')
            else:
                labels.append('abord_g')
        else:
            within = (i - rb) <= search_n
            if within and zs[i] < z_rb - drop_thr:
                labels.append('fosse_d')
            elif within and zs[i] < z_rb - accot_drop:
                labels.append('accot_d')
            else:
                labels.append('abord_d')

    segs = []
    i = 0
    while i < n:
        lbl = labels[i]
        j = i
        while j + 1 < n and labels[j + 1] == lbl:
            j += 1
        segs.append({
            'd_start': d0 + i * bin_size,
            'd_end':   d0 + (j + 1) * bin_size,
            'width':   (j - i + 1) * bin_size,
            'z_mean':  float(np.mean(zs[i:j + 1])),
            'label':   lbl,
        })
        i = j + 1

    w = {lbl: 0.0 for lbl in LABELS}
    for s in segs:
        if s['label'] in w:
            w[s['label']] += s['width']

    return {
        'n': n, 'd0': d0, 'ci': ci, 'cd': cd, 'ancrage': ancrage, 'ref': ref,
        'zs': zs, 'its': its, 'ls': ls, 'vs': vs,
        'labels': labels, 'bitmasks': bitmasks,
        'segments': segs, 'widths': w, 'road_width': road_w,
        'larg_parc': larg_parc, 'capped': capped,
        'road_d_start': d0 + lb * bin_size,
        'road_d_end':   d0 + (rb + 1) * bin_size,
    }


def _label_pt(d, z, d0, bin_size, zs, labels, sursol_tol):
    """Étiquette un point. 'sursol' si z dépasse le profil sol du bin."""
    bi = max(0, min(len(labels) - 1, int((d - d0) / bin_size)))
    if z > zs[bi] + sursol_tol:
        return 'sursol'
    return labels[bi]


# ── Chargement cadastre (emprise globale) ──────────────────────────────────────

def _load_parcel_index(xmin, ymin, xmax, ymax, feedback):
    try:
        data = _wfs_json(_CADASTRE_LYR, xmin, ymin, xmax, ymax, count=2000)
    except Exception as exc:
        feedback.pushWarning(f'WFS cadastre inaccessible ({exc}) — largeur parcelle ignorée.')
        return None, None
    feats = data.get('features', [])
    if not feats:
        return None, None
    index = QgsSpatialIndex()
    store = {}
    for i, f in enumerate(feats):
        raw_geom = f.get('geometry')
        if not raw_geom:
            continue
        ogr_geom = ogr.CreateGeometryFromJson(json.dumps(raw_geom))
        if ogr_geom is None:
            continue
        geom = QgsGeometry.fromWkt(ogr_geom.ExportToWkt())
        if geom is None or geom.isEmpty():
            continue
        ff = QgsFeature(i)
        ff.setGeometry(geom)
        index.addFeature(ff)
        store[i] = geom
    feedback.pushInfo(f'Cadastre : {len(store)} parcelle(s) indexée(s).')
    return index, store


# ── Algorithme QGIS ───────────────────────────────────────────────────────────

class LidarRoadProfileAlgorithm(QgsProcessingAlgorithm):

    POINTS    = 'POINTS'
    TRANSECTS = 'TRANSECTS'
    AXIS      = 'AXIS'
    CLC_FIELD = 'CLC_FIELD'
    USE_CADASTRE = 'USE_CADASTRE'

    BIN_SIZE      = 'BIN_SIZE'
    ACCOT_DROP    = 'ACCOT_DROP'
    SURSOL_TOL    = 'SURSOL_TOL'
    PARCEL_MARGIN = 'PARCEL_MARGIN'
    HALF_STRIP    = 'HALF_STRIP'
    N_VALID       = 'N_VALID'
    HALF_REF      = 'HALF_REF'

    OUT_POINTS   = 'OUT_POINTS'
    OUT_POLYGONS = 'OUT_POLYGONS'
    OUT_PROFILE  = 'OUT_PROFILE'
    OUT_DIAG     = 'OUT_DIAG'

    def initAlgorithm(self, config=None):
        del config

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.POINTS,
            self.tr('Points LiDAR (id_transect, d_along, z, intensity, red, green, blue, classification)'),
            [QgsProcessing.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.TRANSECTS,
            self.tr('Transects (FID = id_transect ; champ CLC requis)'),
            [QgsProcessing.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.AXIS, self.tr('Axe routier (optionnel — ancrage du centre)'),
            [QgsProcessing.TypeVectorLine], optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.CLC_FIELD,
            self.tr('Champ CLC sur les transects (clc_n1 ou clc_code)'),
            defaultValue='clc_n1'))
        self.addParameter(QgsProcessingParameterBoolean(
            self.USE_CADASTRE,
            self.tr('Plafond largeur parcelle à parcelle (WFS cadastre)'),
            defaultValue=False))

        _D = QgsProcessingParameterNumber.Double
        _I = QgsProcessingParameterNumber.Integer
        for pname, label, default, lo, hi, t in [
            (self.BIN_SIZE,      'Résolution du profil (m)',                    0.25, 0.05, 2.0, _D),
            (self.ACCOT_DROP,    'Décrochement accotement bas (m)',             0.05, 0.0,  0.5, _D),
            (self.SURSOL_TOL,    'Tolérance sursol : z au-dessus du sol (m)',   0.50, 0.10, 3.0, _D),
            (self.PARCEL_MARGIN, 'Marge plafond parcellaire (m)',               1.0,  0.0,  5.0, _D),
            (self.HALF_STRIP,    'Demi-largeur des polygones (m)',              0.4,  0.1,  2.0, _D),
            (self.N_VALID,       'N — bins consécutifs pour confirmer le bord', 2,    1,    10,  _I),
            (self.HALF_REF,      'half_ref — demi-largeur zone référence (bins)', 3,  1,    10,  _I),
        ]:
            self.addParameter(QgsProcessingParameterNumber(
                pname, self.tr(label), t,
                defaultValue=default, minValue=lo, maxValue=hi))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_POINTS, self.tr('Points classifiés'),
            optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_POLYGONS, self.tr('Polygones de segments'),
            optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_PROFILE, self.tr('Profil par transect'),
            optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_DIAG, self.tr('Diagnostic par bin'),
            optional=True, createByDefault=True))

    # ─────────────────────────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):

        pts_layer   = self.parameterAsVectorLayer(parameters, self.POINTS,    context)
        trans_layer = self.parameterAsVectorLayer(parameters, self.TRANSECTS, context)
        axis_layer  = self.parameterAsVectorLayer(parameters, self.AXIS,      context)
        clc_field   = self.parameterAsString(parameters, self.CLC_FIELD, context).strip()
        use_cad     = self.parameterAsBool(parameters, self.USE_CADASTRE, context)

        bs   = self.parameterAsDouble(parameters, self.BIN_SIZE,      context)
        ad   = self.parameterAsDouble(parameters, self.ACCOT_DROP,    context)
        stol = self.parameterAsDouble(parameters, self.SURSOL_TOL,    context)
        pmar = self.parameterAsDouble(parameters, self.PARCEL_MARGIN, context)
        hs   = self.parameterAsDouble(parameters, self.HALF_STRIP,    context)
        N    = self.parameterAsInt(parameters,    self.N_VALID,       context)
        hr   = self.parameterAsInt(parameters,    self.HALF_REF,      context)

        _check_fields(pts_layer, REQUIRED_PT, 'Couche points')

        tr_names = {trans_layer.fields().field(k).name()
                    for k in range(trans_layer.fields().count())}
        has_clc = clc_field in tr_names
        if not has_clc:
            feedback.pushWarning(self.tr(
                'Champ CLC "{}" absent des transects — profil de repli (CLC 0) partout.'
            ).format(clc_field))
        has_il = 'id_ligne' in tr_names
        has_di = 'distance' in tr_names

        pts_crs = pts_layer.sourceCrs()
        if not pts_crs.isValid():
            pts_crs = QgsCoordinateReferenceSystem('EPSG:2154')

        axis_geoms = []
        if axis_layer:
            ax_crs = axis_layer.sourceCrs()
            tr_ax = (QgsCoordinateTransform(ax_crs, pts_crs, context.transformContext())
                     if ax_crs != pts_crs else None)
            for f in axis_layer.getFeatures():
                g = QgsGeometry(f.geometry())
                if tr_ax:
                    g.transform(tr_ax)
                if not g.isEmpty():
                    axis_geoms.append(g)
            feedback.pushInfo(self.tr('Axe routier : {} géométrie(s).').format(len(axis_geoms)))

        parcel_index = parcel_store = None
        if use_cad:
            ext = trans_layer.extent()
            parcel_index, parcel_store = _load_parcel_index(
                ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum(), feedback)

        # ── Index transects (avec CLC) ────────────────────────────────────────
        trans = {}
        clc_counts = {}
        for f in trans_layer.getFeatures():
            line = f.geometry().asPolyline()
            if len(line) < 2:
                continue
            p1, p2 = line[0], line[-1]
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
            L = math.sqrt(dx * dx + dy * dy)
            if L == 0:
                continue
            clc_n1 = _resolve_clc(f[clc_field]) if has_clc else 0
            clc_counts[clc_n1] = clc_counts.get(clc_n1, 0) + 1
            trans[f.id()] = {
                'p1x': p1.x(), 'p1y': p1.y(),
                'ux': dx / L, 'uy': dy / L, 'seg_len': L,
                'id_ligne': int(f['id_ligne']) if has_il else f.id(),
                'distance': float(f['distance']) if has_di else 0.0,
                'clc_n1': clc_n1,
            }
        feedback.pushInfo(self.tr('Répartition CLC : {}').format(
            ', '.join(f'{k}:{v}' for k, v in sorted(clc_counts.items()))))

        # ── Regroupement points (avec classification) ─────────────────────────
        n_null = 0
        by_tid = {}
        for f in pts_layer.getFeatures():
            tid = _safe(f, 'id_transect', int)
            d = _safe(f, 'd_along', float)
            z = _safe(f, 'z', float)
            if tid is None or d is None or z is None:
                n_null += 1
                continue
            by_tid.setdefault(tid, []).append({
                'fid': f.id(), 'd': d, 'z': z,
                'intensity': _safe(f, 'intensity', float, 0.0),
                'r': _safe(f, 'red', float, 0.0),
                'g': _safe(f, 'green', float, 0.0),
                'b': _safe(f, 'blue', float, 0.0),
                'cls': _safe(f, 'classification', int, 0),
            })
        if n_null:
            feedback.pushWarning(f'{n_null} point(s) ignoré(s) (champs NULL)')

        # ── Sinks ─────────────────────────────────────────────────────────────
        pts_f = QgsFields()
        for i in range(pts_layer.fields().count()):
            pts_f.append(pts_layer.fields().field(i))
        pts_f.append(QgsField('segment', QVariant.String))
        sink_pts, dest_pts = self.parameterAsSink(
            parameters, self.OUT_POINTS, context, pts_f, QgsWkbTypes.PointZ, pts_crs)

        poly_f = QgsFields()
        for nm, vt_ in [
            ('id_transect', QVariant.Int),   ('id_ligne', QVariant.Int),
            ('clc_n1', QVariant.Int),        ('distance', QVariant.Double),
            ('segment', QVariant.String),    ('d_debut', QVariant.Double),
            ('d_fin', QVariant.Double),      ('largeur', QVariant.Double),
            ('z_moy', QVariant.Double),
        ]:
            poly_f.append(QgsField(nm, vt_))
        sink_poly, dest_poly = self.parameterAsSink(
            parameters, self.OUT_POLYGONS, context, poly_f, QgsWkbTypes.Polygon, pts_crs)

        prof_f = QgsFields()
        for nm, vt_ in [
            ('id_transect', QVariant.Int),    ('id_ligne', QVariant.Int),
            ('clc_n1', QVariant.Int),         ('regime', QVariant.String),
            ('distance', QVariant.Double),    ('ancrage', QVariant.String),
            ('larg_chaussee', QVariant.Double),
            ('larg_accot_g', QVariant.Double), ('larg_accot_d', QVariant.Double),
            ('larg_fosse_g', QVariant.Double), ('larg_fosse_d', QVariant.Double),
            ('larg_parcelle', QVariant.Double), ('ratio_parc', QVariant.Double),
            ('plafonne', QVariant.Int),
            ('z_ref', QVariant.Double),       ('int_ref', QVariant.Double),
            ('lum_ref', QVariant.Double),     ('vert_ref', QVariant.Double),
        ]:
            prof_f.append(QgsField(nm, vt_))
        sink_prof, dest_prof = self.parameterAsSink(
            parameters, self.OUT_PROFILE, context, prof_f, QgsWkbTypes.Point, pts_crs)

        diag_f = QgsFields()
        for nm, vt_ in [
            ('id_transect', QVariant.Int),  ('clc_n1', QVariant.Int),
            ('bin_idx', QVariant.Int),      ('d_along', QVariant.Double),
            ('segment', QVariant.String),   ('z', QVariant.Double),
            ('intensity', QVariant.Double), ('lum', QVariant.Double),
            ('vert', QVariant.Double),      ('score', QVariant.Int),
            ('criteres', QVariant.String),  ('is_center', QVariant.Int),
        ]:
            diag_f.append(QgsField(nm, vt_))
        sink_diag, dest_diag = self.parameterAsSink(
            parameters, self.OUT_DIAG, context, diag_f, QgsWkbTypes.Point, pts_crs)

        # ── Traitement ────────────────────────────────────────────────────────
        fid_label = {}
        total = max(1, len(by_tid))
        n_ok = n_skip = n_anchor = n_water = n_capped = 0

        for step, (tid, raw) in enumerate(sorted(by_tid.items())):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(step / total * 100))

            ti = trans.get(tid)
            if ti is None:
                feedback.pushWarning(f'T{tid} : absent de la couche transects')
                for p in raw:
                    fid_label[p['fid']] = 'non_classe'
                n_skip += 1
                continue

            clc_n1 = ti['clc_n1']
            if clc_n1 in SKIP_CLC:
                for p in raw:
                    fid_label[p['fid']] = 'non_classe'
                n_water += 1
                continue

            prof = CLC_PROFILES.get(clc_n1, CLC_PROFILES[0])
            res = _analyze(raw, ti, axis_geoms, prof, bs, ad, hr, N,
                           parcel_index, parcel_store, pmar)

            if res is None:
                feedback.pushWarning(f'T{tid} [{prof["label"]}] : détection échouée')
                for p in raw:
                    fid_label[p['fid']] = 'non_classe'
                n_skip += 1
                continue

            n_ok += 1
            if res['ancrage'] == 'axe':
                n_anchor += 1
            if res['capped']:
                n_capped += 1

            w = res['widths']
            larg_parc = res['larg_parc']
            ratio_parc = (round(w['chaussee'] / larg_parc, 3)
                          if larg_parc and larg_parc > 0 else None)

            feedback.pushInfo(
                f'T{tid} [{prof["label"]}/{res["ancrage"]}'
                f'{"/plafonné" if res["capped"] else ""}] — chaussée '
                f'{w["chaussee"]:.2f} m | accot {w["accot_g"]:.2f}/{w["accot_d"]:.2f} '
                f'| fossé {w["fosse_g"]:.2f}/{w["fosse_d"]:.2f}')

            for p in raw:
                fid_label[p['fid']] = _label_pt(
                    p['d'], p['z'], res['d0'], bs, res['zs'], res['labels'], stol)

            il, di, ref = ti['id_ligne'], ti['distance'], res['ref']

            if sink_poly:
                for seg in res['segments']:
                    pf = QgsFeature(poly_f)
                    pf.setGeometry(_strip_polygon(
                        ti['p1x'], ti['p1y'], ti['ux'], ti['uy'],
                        seg['d_start'], seg['d_end'], half_w=hs))
                    pf.setAttributes([
                        int(tid), int(il), int(clc_n1), round(di, 3), seg['label'],
                        round(seg['d_start'], 3), round(seg['d_end'], 3),
                        round(seg['width'], 3), round(seg['z_mean'], 3),
                    ])
                    sink_poly.addFeature(pf)

            if sink_prof:
                dc = (res['road_d_start'] + res['road_d_end']) / 2.0
                pf = QgsFeature(prof_f)
                pf.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(
                    ti['p1x'] + ti['ux'] * dc, ti['p1y'] + ti['uy'] * dc)))
                pf.setAttributes([
                    int(tid), int(il), int(clc_n1), prof['label'],
                    round(di, 3), res['ancrage'],
                    round(w['chaussee'], 3),
                    round(w['accot_g'], 3), round(w['accot_d'], 3),
                    round(w['fosse_g'], 3), round(w['fosse_d'], 3),
                    round(larg_parc, 3) if larg_parc else None, ratio_parc,
                    int(res['capped']),
                    round(ref['z_ref'], 3), round(ref['int_ref'], 3),
                    round(ref['lum_ref'], 3), round(ref['vert_ref'], 3),
                ])
                sink_prof.addFeature(pf)

            if sink_diag:
                d0 = res['d0']
                for i in range(res['n']):
                    d_bin = d0 + (i + 0.5) * bs
                    bm = int(res['bitmasks'][i])
                    df = QgsFeature(diag_f)
                    df.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(
                        ti['p1x'] + ti['ux'] * d_bin, ti['p1y'] + ti['uy'] * d_bin)))
                    df.setAttributes([
                        int(tid), int(clc_n1), i, round(d_bin, 3), res['labels'][i],
                        round(float(res['zs'][i]), 3), round(float(res['its'][i]), 3),
                        round(float(res['ls'][i]), 3), round(float(res['vs'][i]), 3),
                        bin(bm).count('1'), _decode(bm), int(i == res['ci']),
                    ])
                    sink_diag.addFeature(df)

        if sink_pts:
            for f in pts_layer.getFeatures():
                nf = QgsFeature(pts_f)
                nf.setGeometry(f.geometry())
                nf.setAttributes(
                    list(f.attributes()) + [fid_label.get(f.id(), 'non_classe')])
                sink_pts.addFeature(nf)

        feedback.pushInfo(
            f'Terminé — OK:{n_ok}  ignorés:{n_skip}  eau/humide:{n_water}  '
            f'plafonnés:{n_capped}  ancrés sur axe:{n_anchor}/{n_ok}')

        out = {}
        if dest_pts:  out[self.OUT_POINTS]   = dest_pts
        if dest_poly: out[self.OUT_POLYGONS] = dest_poly
        if dest_prof: out[self.OUT_PROFILE]  = dest_prof
        if dest_diag: out[self.OUT_DIAG]     = dest_diag
        return out

    # ── Métadonnées ───────────────────────────────────────────────────────────

    def name(self):        return 'lidar_road_profile'
    def displayName(self): return self.tr('Profil de chaussée LiDAR (stratifié CLC)')
    def group(self):       return self.tr('LiDAR')
    def groupId(self):     return 'lidar'

    def shortHelpString(self):
        return self.tr(
            'Détection de chaussée multi-critères, stratifiée par classe CLC, '
            'ancrée sur l\'axe.\n\n'
            'CORRECTIFS : profil et étiquetage sur le SOL (classe 2) ; points '
            'au-dessus du sol → "sursol" (canopée, bâti) ; largeur parcellaire '
            '(cadastre) utilisée comme plafond de max_rw.\n\n'
            'CLC 1 ville · 2 champ · 3 forêt (ortho OFF) · 0 repli · 4/5 → ignoré.\n'
            'Critères : s_z (montée), s_drop (fossé), s_int, s_lum/s_vert (ortho).\n'
            'Seuils par classe VERROUILLÉS dans CLC_PROFILES (en tête de module).\n\n'
            'Sorties : Points classifiés - Polygones - Profil/transect '
            'Diagnostic/bin. Labels : chaussee | accot_g/d | fosse_g/d | '
            'abord_g/d | sursol | non_classe.')

    def createInstance(self):
        return LidarRoadProfileAlgorithm()

    def tr(self, s):
        return QCoreApplication.translate('LidarRoadProfileAlgorithm', s)