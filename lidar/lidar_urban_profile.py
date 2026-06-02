# -*- coding: utf-8 -*-
"""
Profil de chaussée LiDAR — détection multi-critères par expansion depuis l'axe.

Score par bin (4 indicateurs) :
  s_z    : rupture altimétrique vs DERNIER bin dans la chaussée  (marche locale)
  s_int  : rupture d'intensité LiDAR vs référence centrale
  s_lum  : rupture de luminance RGB vs référence centrale
  s_vert : excès de vert vs référence centrale                   (végétation)

Bord confirmé quand score ≥ K sur N bins consécutifs.
"""

import math
import numpy as np

from qgis.core import (
    QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
    QgsProcessingParameterVectorLayer, QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsFeature, QgsGeometry, QgsPointXY,
    QgsWkbTypes, QgsFields, QgsField,
    QgsCoordinateReferenceSystem, QgsCoordinateTransform,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from .lidar_road_profile import _strip_polygon
# Signature : _strip_polygon(p1x, p1y, ux, uy, t0, t1, half_w=0.5) → QgsGeometry

LABELS = ('chaussee', 'accot_g', 'accot_d', 'abord_g', 'abord_d', 'non_classe')
REQUIRED_PT = {'id_transect', 'd_along', 'z', 'intensity', 'red', 'green', 'blue'}
REQUIRED_TR = {'id_transect'}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe(feat, name, cast, default=None):
    """Lecture tolérante aux NULL."""
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
    if bitmask & 1:  parts.append('z')
    if bitmask & 2:  parts.append('intens')
    if bitmask & 4:  parts.append('lum')
    if bitmask & 8:  parts.append('vert')
    return '+'.join(parts) if parts else ''


# ── Profil binné ───────────────────────────────────────────────────────────────

def _build_profile(pts, bin_size, d0, n):
    """
    Construit 4 arrays lissés (z, intensity, lum, vert).
    Bins vides → NaN, interpolation linéaire, puis lissage ±2 bins.
    """
    raw = [[[], [], [], []] for _ in range(n)]
    for p in pts:
        bi = min(n - 1, max(0, int((p['d'] - d0) / bin_size)))
        lum  = (p['r'] + p['g'] + p['b']) / 3.0
        vert = 2.0 * p['g'] - p['r'] - p['b']
        raw[bi][0].append(p['z'])
        raw[bi][1].append(p['intensity'])
        raw[bi][2].append(lum)
        raw[bi][3].append(vert)

    idx = np.arange(n, dtype=float)

    def _col(c):
        arr = np.array([
            float(np.median(raw[i][c])) if raw[i][c] else float('nan')
            for i in range(n)])
        valid = ~np.isnan(arr)
        if valid.sum() >= 2:
            arr = np.interp(idx, idx[valid], arr[valid])
        elif valid.sum() == 1:
            arr[:] = arr[valid][0]
        return _smooth(arr)

    return _col(0), _col(1), _col(2), _col(3)


def _compute_ref(zs, its, ls, vs, ci, half_ref):
    i0 = max(0, ci - half_ref)
    i1 = min(len(zs), ci + half_ref + 1)
    return {
        'z_ref':    float(np.median(zs[i0:i1])),
        'int_ref':  float(np.median(its[i0:i1])),
        'lum_ref':  float(np.median(ls[i0:i1])),
        'vert_ref': float(np.median(vs[i0:i1])),
    }


# ── Expansion ─────────────────────────────────────────────────────────────────

def _expand(zs, its, ls, vs, ci, direction, ref,
            dz_thr, int_thr, lum_thr, vert_thr, K, N):
    """
    Expansion depuis ci vers direction (-1 gauche / +1 droite).
    s_z compare au DERNIER bin dans la chaussée (marche locale).
    s_int, s_lum, s_vert comparent à la référence centrale.
    Retourne (boundary_idx, bitmasks_array).
    """
    n = len(zs)
    bitmasks = np.zeros(n, dtype=np.int32)
    consec = 0
    last = ci

    i = ci + direction
    while 0 <= i < n:
        s_z    = int(abs(zs[i] - zs[last]) > dz_thr)
        s_int  = int(abs(its[i] - ref['int_ref']) / max(ref['int_ref'], 1) > int_thr)
        s_lum  = int(abs(ls[i]  - ref['lum_ref']) / max(ref['lum_ref'], 1) > lum_thr)
        s_vert = int((vs[i] - ref['vert_ref']) > vert_thr)

        bitmasks[i] = s_z | (s_int << 1) | (s_lum << 2) | (s_vert << 3)
        score = s_z + s_int + s_lum + s_vert

        if score >= K:
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
    """
    Projette le milieu géométrique du transect sur l'axe le plus proche.
    Retourne (center_d, 'axe') ou (seg_len/2, 'geometrique').
    """
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


# ── Pipeline complet ───────────────────────────────────────────────────────────

def _analyze(pts, tinfo, axis_geoms,
             bin_size, dz_thr, int_thr, lum_thr, vert_thr,
             accot_drop, min_rw, max_rw, half_ref, K, N):
    """Retourne dict de résultats ou None."""
    if len(pts) < 4:
        return None

    pts_s = sorted(pts, key=lambda p: p['d'])
    d0, d1 = pts_s[0]['d'], pts_s[-1]['d']
    if d1 - d0 < min_rw:
        return None

    n = max(4, int(math.ceil((d1 - d0) / bin_size)) + 1)
    zs, its, ls, vs = _build_profile(pts_s, bin_size, d0, n)

    p1x, p1y = tinfo['p1x'], tinfo['p1y']
    ux, uy   = tinfo['ux'],  tinfo['uy']
    seg_len  = tinfo['seg_len']

    cd, ancrage = _center_on_axis(p1x, p1y, ux, uy, seg_len, axis_geoms)
    ci = max(0, min(n - 1, round((cd - d0) / bin_size)))

    ref = _compute_ref(zs, its, ls, vs, ci, half_ref)

    lb, bm_l = _expand(zs, its, ls, vs, ci, -1, ref,
                        dz_thr, int_thr, lum_thr, vert_thr, K, N)
    rb, bm_r = _expand(zs, its, ls, vs, ci, +1, ref,
                        dz_thr, int_thr, lum_thr, vert_thr, K, N)
    bitmasks = bm_l | bm_r

    road_w = (rb - lb + 1) * bin_size
    if road_w < min_rw or road_w > max_rw:
        return None

    # Labels par bin
    cani_n = max(1, int(3.0 / bin_size))
    z_lb, z_rb = float(zs[lb]), float(zs[rb])
    labels = []
    for i in range(n):
        if lb <= i <= rb:
            lbl = 'chaussee'
        elif i < lb:
            lbl = 'accot_g' if (zs[i] < z_lb - accot_drop and lb - i <= cani_n) \
                  else 'abord_g'
        else:
            lbl = 'accot_d' if (zs[i] < z_rb - accot_drop and i - rb <= cani_n) \
                  else 'abord_d'
        labels.append(lbl)

    # Segments contigus
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
        'n': n, 'd0': d0, 'ci': ci, 'ancrage': ancrage, 'ref': ref,
        'zs': zs, 'its': its, 'ls': ls, 'vs': vs,
        'labels': labels, 'bitmasks': bitmasks,
        'segments': segs, 'widths': w,
        'road_d_start': d0 + lb * bin_size,
        'road_d_end':   d0 + (rb + 1) * bin_size,
    }


def _label_pt(d, d0, bin_size, labels):
    bi = int((d - d0) / bin_size)
    n = len(labels)
    return labels[max(0, min(n - 1, bi))]


# ── Algorithme QGIS ───────────────────────────────────────────────────────────

class LidarUrbanRoadProfileAlgorithm(QgsProcessingAlgorithm):

    POINTS    = 'POINTS'
    TRANSECTS = 'TRANSECTS'
    AXIS      = 'AXIS'

    BIN_SIZE   = 'BIN_SIZE'
    DZ_THR     = 'DZ_THR'
    INT_THR    = 'INT_THR'
    LUM_THR    = 'LUM_THR'
    VERT_THR   = 'VERT_THR'
    ACCOT_DROP = 'ACCOT_DROP'
    MIN_ROAD_W = 'MIN_ROAD_W'
    MAX_ROAD_W = 'MAX_ROAD_W'
    HALF_STRIP = 'HALF_STRIP'
    K_SCORE    = 'K_SCORE'
    N_VALID    = 'N_VALID'
    HALF_REF   = 'HALF_REF'

    OUT_POINTS   = 'OUT_POINTS'
    OUT_POLYGONS = 'OUT_POLYGONS'
    OUT_PROFILE  = 'OUT_PROFILE'
    OUT_DIAG     = 'OUT_DIAG'

    def initAlgorithm(self, config=None):
        del config  # requis par l'API QGIS, non utilisé

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.POINTS,
            self.tr('Points LiDAR (id_transect, d_along, z, intensity, red, green, blue)'),
            [QgsProcessing.TypeVectorPoint]))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.TRANSECTS,
            self.tr('Transects (id_transect, id_ligne, distance)'),
            [QgsProcessing.TypeVectorLine]))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.AXIS,
            self.tr('Axe routier (optionnel — ancrage du centre)'),
            [QgsProcessing.TypeVectorLine],
            optional=True))

        _D = QgsProcessingParameterNumber.Double
        _I = QgsProcessingParameterNumber.Integer
        for pname, label, default, lo, hi, t in [
            (self.BIN_SIZE,   'Résolution du profil (m)',                   0.25,  0.05, 2.0,   _D),
            (self.DZ_THR,     'Seuil rupture altimétrique dz_thr (m)',      0.07,  0.01, 1.0,   _D),
            (self.INT_THR,    'Seuil rupture intensité int_thr (relatif)',   0.45,  0.05, 2.0,   _D),
            (self.LUM_THR,    'Seuil rupture luminance lum_thr (relatif)',   0.30,  0.05, 2.0,   _D),
            (self.VERT_THR,   'Seuil excès de vert vert_thr (valeur brute)', 18.0,  0.0, 100.0, _D),
            (self.ACCOT_DROP, 'Profondeur accotement bas accot_drop (m)',    0.05,  0.0, 0.50,  _D),
            (self.MIN_ROAD_W, 'Largeur min chaussée (m)',                    2.0,   0.5, 10.0,  _D),
            (self.MAX_ROAD_W, 'Largeur max chaussée (m)',                   15.0,   3.0, 50.0,  _D),
            (self.HALF_STRIP, 'Demi-largeur des polygones (m)',              0.4,   0.1,  2.0,  _D),
            (self.K_SCORE,    'K — nb critères pour « hors chaussée »',      2,     1,    4,    _I),
            (self.N_VALID,    'N — bins consécutifs pour confirmer le bord', 2,     1,   10,    _I),
            (self.HALF_REF,   'half_ref — demi-largeur zone référence (bins)',3,    1,   10,    _I),
        ]:
            self.addParameter(QgsProcessingParameterNumber(
                pname, self.tr(label), t,
                defaultValue=default, minValue=lo, maxValue=hi))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_POINTS,   self.tr('① Points classifiés'),
            optional=True, createByDefault=False))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_POLYGONS, self.tr('② Polygones de segments'),
            optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_PROFILE,  self.tr('③ Profil par transect (1 point / transect)'),
            optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUT_DIAG,     self.tr('④ Diagnostic par bin (calage des seuils)'),
            optional=True, createByDefault=False))

    # ─────────────────────────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):

        pts_layer   = self.parameterAsVectorLayer(parameters, self.POINTS,    context)
        trans_layer = self.parameterAsVectorLayer(parameters, self.TRANSECTS, context)
        axis_layer  = self.parameterAsVectorLayer(parameters, self.AXIS,      context)

        bs   = self.parameterAsDouble(parameters, self.BIN_SIZE,   context)
        dz   = self.parameterAsDouble(parameters, self.DZ_THR,     context)
        it   = self.parameterAsDouble(parameters, self.INT_THR,    context)
        lt   = self.parameterAsDouble(parameters, self.LUM_THR,    context)
        vt   = self.parameterAsDouble(parameters, self.VERT_THR,   context)
        ad   = self.parameterAsDouble(parameters, self.ACCOT_DROP, context)
        minw = self.parameterAsDouble(parameters, self.MIN_ROAD_W, context)
        maxw = self.parameterAsDouble(parameters, self.MAX_ROAD_W, context)
        hs   = self.parameterAsDouble(parameters, self.HALF_STRIP, context)
        K    = self.parameterAsInt(parameters,    self.K_SCORE,    context)
        N    = self.parameterAsInt(parameters,    self.N_VALID,    context)
        hr   = self.parameterAsInt(parameters,    self.HALF_REF,   context)

        # ── CRS & validation ──────────────────────────────────────────────────
        _check_fields(pts_layer,   REQUIRED_PT, 'Couche points')
        _check_fields(trans_layer, REQUIRED_TR, 'Couche transects')

        pts_crs = pts_layer.sourceCrs()
        if not pts_crs.isValid():
            pts_crs = QgsCoordinateReferenceSystem('EPSG:2154')

        # ── Axe routier ───────────────────────────────────────────────────────
        axis_geoms = []
        if axis_layer:
            ax_crs = axis_layer.sourceCrs()
            tr_ax  = (QgsCoordinateTransform(ax_crs, pts_crs, context.transformContext())
                      if ax_crs != pts_crs else None)
            for f in axis_layer.getFeatures():
                g = QgsGeometry(f.geometry())
                if tr_ax:
                    g.transform(tr_ax)
                if not g.isEmpty():
                    axis_geoms.append(g)
            feedback.pushInfo(
                f'Axe routier : {len(axis_geoms)} géométrie(s), '
                f'{"reprojection " + ax_crs.authid() + " → " + pts_crs.authid() if tr_ax else "même CRS"}')

        # ── Index transects ───────────────────────────────────────────────────
        tr_fnames = {trans_layer.fields().field(k).name()
                     for k in range(trans_layer.fields().count())}
        has_il = 'id_ligne' in tr_fnames
        has_di = 'distance' in tr_fnames

        trans = {}
        for f in trans_layer.getFeatures():
            line = f.geometry().asPolyline()
            if len(line) < 2:
                continue
            p1, p2 = line[0], line[-1]
            dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
            L = math.sqrt(dx * dx + dy * dy)
            if L == 0:
                continue
            trans[f.id()] = {
                'geom':     f.geometry(),
                'p1x': p1.x(), 'p1y': p1.y(),
                'ux': dx / L,  'uy': dy / L,
                'seg_len':   L,
                'id_ligne':  int(f['id_ligne']) if has_il else f.id(),
                'distance':  float(f['distance']) if has_di else 0.0,
            }

        # ── Regroupement points ───────────────────────────────────────────────
        n_null = 0
        by_tid = {}
        for f in pts_layer.getFeatures():
            tid = _safe(f, 'id_transect', int)
            if tid is None:
                n_null += 1
                continue
            d = _safe(f, 'd_along',   float)
            z = _safe(f, 'z',         float)
            ii = _safe(f, 'intensity', float, 0.0)
            r  = _safe(f, 'red',       float, 0.0)
            g  = _safe(f, 'green',     float, 0.0)
            b  = _safe(f, 'blue',      float, 0.0)
            if d is None or z is None:
                n_null += 1
                continue
            by_tid.setdefault(tid, []).append({
                'fid': f.id(), 'd': d, 'z': z,
                'intensity': ii, 'r': r, 'g': g, 'b': b,
                'geom': f.geometry(),
            })
        if n_null:
            feedback.pushWarning(f'{n_null} point(s) ignoré(s) (champs NULL)')

        # ── Sinks ─────────────────────────────────────────────────────────────

        # ① Points
        pts_f = QgsFields()
        for i in range(pts_layer.fields().count()):
            pts_f.append(pts_layer.fields().field(i))
        pts_f.append(QgsField('segment', QVariant.String))
        sink_pts, dest_pts = self.parameterAsSink(
            parameters, self.OUT_POINTS, context, pts_f, QgsWkbTypes.PointZ, pts_crs)

        # ② Polygones
        poly_f = QgsFields()
        for nm, vt_ in [
            ('id_transect', QVariant.Int),    ('id_ligne',  QVariant.Int),
            ('distance',    QVariant.Double),  ('segment',   QVariant.String),
            ('d_debut',     QVariant.Double),  ('d_fin',     QVariant.Double),
            ('largeur',     QVariant.Double),  ('z_moy',     QVariant.Double),
        ]:
            poly_f.append(QgsField(nm, vt_))
        sink_poly, dest_poly = self.parameterAsSink(
            parameters, self.OUT_POLYGONS, context, poly_f, QgsWkbTypes.Polygon, pts_crs)

        # ③ Profil
        prof_f = QgsFields()
        for nm, vt_ in [
            ('id_transect',   QVariant.Int),
            ('id_ligne',      QVariant.Int),
            ('distance',      QVariant.Double),
            ('ancrage',       QVariant.String),
            ('larg_chaussee', QVariant.Double),
            ('larg_accot_g',  QVariant.Double),
            ('larg_accot_d',  QVariant.Double),
            ('z_ref',         QVariant.Double),
            ('int_ref',       QVariant.Double),
            ('lum_ref',       QVariant.Double),
            ('vert_ref',      QVariant.Double),
        ]:
            prof_f.append(QgsField(nm, vt_))
        sink_prof, dest_prof = self.parameterAsSink(
            parameters, self.OUT_PROFILE, context, prof_f, QgsWkbTypes.Point, pts_crs)

        # ④ Diagnostic
        diag_f = QgsFields()
        for nm, vt_ in [
            ('id_transect', QVariant.Int),
            ('bin_idx',     QVariant.Int),
            ('d_along',     QVariant.Double),
            ('segment',     QVariant.String),
            ('z',           QVariant.Double),
            ('intensity',   QVariant.Double),
            ('lum',         QVariant.Double),
            ('vert',        QVariant.Double),
            ('score',       QVariant.Int),
            ('criteres',    QVariant.String),
            ('is_center',   QVariant.Int),
        ]:
            diag_f.append(QgsField(nm, vt_))
        sink_diag, dest_diag = self.parameterAsSink(
            parameters, self.OUT_DIAG, context, diag_f, QgsWkbTypes.Point, pts_crs)

        # ── Traitement ────────────────────────────────────────────────────────
        fid_label = {}
        total = max(1, len(by_tid))
        n_ok = n_skip = n_anchor = 0

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

            res = _analyze(raw, ti, axis_geoms,
                           bs, dz, it, lt, vt, ad, minw, maxw, hr, K, N)

            if res is None:
                feedback.pushWarning(f'T{tid} : détection échouée')
                for p in raw:
                    fid_label[p['fid']] = 'non_classe'
                n_skip += 1
                continue

            n_ok += 1
            if res['ancrage'] == 'axe':
                n_anchor += 1

            w = res['widths']
            feedback.pushInfo(
                f'T{tid} [{res["ancrage"]}] — chaussée {w["chaussee"]:.2f} m '
                f'| accot_g {w["accot_g"]:.2f} | accot_d {w["accot_d"]:.2f}')

            # Labels points
            for p in raw:
                fid_label[p['fid']] = _label_pt(
                    p['d'], res['d0'], bs, res['labels'])

            il = ti['id_ligne']
            di = ti['distance']
            ref = res['ref']

            # ② Polygones ─────────────────────────────────────────────────────
            if sink_poly:
                for seg in res['segments']:
                    pf = QgsFeature(poly_f)
                    pf.setGeometry(_strip_polygon(
                        ti['p1x'], ti['p1y'], ti['ux'], ti['uy'],
                        seg['d_start'], seg['d_end'], half_w=hs))
                    pf.setAttributes([
                        int(tid), int(il), round(di, 3), seg['label'],
                        round(seg['d_start'], 3), round(seg['d_end'], 3),
                        round(seg['width'],   3), round(seg['z_mean'],  3),
                    ])
                    sink_poly.addFeature(pf)

            # ③ Profil ────────────────────────────────────────────────────────
            if sink_prof:
                dc = (res['road_d_start'] + res['road_d_end']) / 2.0
                pf = QgsFeature(prof_f)
                pf.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(
                    ti['p1x'] + ti['ux'] * dc,
                    ti['p1y'] + ti['uy'] * dc)))
                pf.setAttributes([
                    int(tid), int(il), round(di, 3), res['ancrage'],
                    round(w['chaussee'], 3),
                    round(w['accot_g'],  3),
                    round(w['accot_d'],  3),
                    round(ref['z_ref'],   3),
                    round(ref['int_ref'], 3),
                    round(ref['lum_ref'], 3),
                    round(ref['vert_ref'],3),
                ])
                sink_prof.addFeature(pf)

            # ④ Diagnostic ────────────────────────────────────────────────────
            if sink_diag:
                n  = res['n']
                d0 = res['d0']
                for i in range(n):
                    d_bin = d0 + (i + 0.5) * bs
                    bm    = int(res['bitmasks'][i])
                    sc    = bin(bm).count('1')
                    lbl   = res['labels'][i]
                    df = QgsFeature(diag_f)
                    df.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(
                        ti['p1x'] + ti['ux'] * d_bin,
                        ti['p1y'] + ti['uy'] * d_bin)))
                    df.setAttributes([
                        int(tid), i, round(d_bin, 3), lbl,
                        round(float(res['zs'][i]),  3),
                        round(float(res['its'][i]), 3),
                        round(float(res['ls'][i]),  3),
                        round(float(res['vs'][i]),  3),
                        sc, _decode(bm),
                        int(i == res['ci']),
                    ])
                    sink_diag.addFeature(df)

        # ① Points classifiés ─────────────────────────────────────────────────
        if sink_pts:
            for f in pts_layer.getFeatures():
                nf = QgsFeature(pts_f)
                nf.setGeometry(f.geometry())
                nf.setAttributes(
                    list(f.attributes()) + [fid_label.get(f.id(), 'non_classe')])
                sink_pts.addFeature(nf)

        feedback.pushInfo(
            f'Terminé — OK:{n_ok}  ignorés:{n_skip}  '
            f'ancrés sur axe:{n_anchor}/{n_ok}')

        out = {}
        if dest_pts:  out[self.OUT_POINTS]   = dest_pts
        if dest_poly: out[self.OUT_POLYGONS]  = dest_poly
        if dest_prof: out[self.OUT_PROFILE]   = dest_prof
        if dest_diag: out[self.OUT_DIAG]      = dest_diag
        return out

    # ── Métadonnées ───────────────────────────────────────────────────────────

    def name(self):        return 'lidar_road_profile'
    def displayName(self): return self.tr('Profil de chaussée LiDAR')
    def group(self):       return self.tr('LiDAR')
    def groupId(self):     return 'lidar'

    def shortHelpString(self):
        return self.tr(
            'Détecte la largeur de chaussée par expansion multi-critères depuis l\'axe.\n\n'
            'Pour chaque bin de bin_size m :\n'
            '  s_z    — rupture altimétrique vs dernier bin dans la chaussée\n'
            '  s_int  — rupture d\'intensité LiDAR vs référence centrale\n'
            '  s_lum  — rupture de luminance RGB vs référence centrale\n'
            '  s_vert — excès de vert vs référence centrale\n'
            'Bord confirmé quand score ≥ K sur N bins consécutifs.\n\n'
            'Entrées :\n'
            '- Points : id_transect, d_along, z, intensity, red, green, blue (requis)\n'
            '- Transects : id_transect (+ id_ligne, distance si dispo)\n'
            '- Axe routier (optionnel) : ancrage du centre sur l\'axe géométrique\n\n'
            'Sorties (laisser vide = désactivée) :\n'
            '① Points classifiés — champ segment\n'
            '② Polygones de segments\n'
            '③ Profil par transect — larg_chaussee, accot_g/d, refs z/int/lum/vert\n'
            '④ Diagnostic par bin — score + criteres déclenchés → sert au calage\n\n'
            'Labels : chaussee | accot_g/d | abord_g/d | non_classe'
        )

    def createInstance(self):
        return LidarUrbanRoadProfileAlgorithm()

    def tr(self, s):
        return QCoreApplication.translate('LidarUrbanRoadProfileAlgorithm', s)
