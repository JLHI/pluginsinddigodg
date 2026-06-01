# -*- coding: utf-8 -*-
"""
Profil de chaussée LiDAR – approche en deux étapes :

  Étape 1 – Délimitation du domaine routier
    Interroge le cadastre IGN (WFS) pour trouver les points où les limites
    de parcelles coupent le transect. Ces deux extrémités définissent la
    « largeur parcelle à parcelle » = emprise maximale de la voie.

  Étape 2 – Détection de la chaussée par plus longue suite bas-Z
    Sur la portion clippée, on construit le profil z des points sol.
    La chaussée est la plus longue séquence contiguë de bins dont
    l'altitude est proche du plancher du profil (≤ z_ref + seuil_bordure).
    Ce critère est purement altimétrique et robuste au dévers.

  Contexte :
    Le code CLC 2018 (WFS) indique si on est en zone urbaine ou rurale
    et ajuste légèrement le seuil de détection.
"""

import math
import json
import urllib.request
import urllib.parse

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFeatureSink,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsFields,
    QgsField,
    QgsCoordinateReferenceSystem,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant

# ── WFS endpoints ─────────────────────────────────────────────────────────────
_WFS_URL      = 'https://data.geopf.fr/wfs/ows'
_CADASTRE_LYR = 'CADASTRALPARCELS.PARCELLAIRE_EXPRESS:parcelle'
_CLC_LYR      = 'LANDCOVER.CLC18_FR:clc18_fr'
_HEADERS      = {'User-Agent': 'Mozilla/5.0 (compatible; QGIS LiDAR plugin)'}

_URBAN_CLC = frozenset({
    '111', '112',
    '121', '122', '123', '124',
    '131', '132', '133',
    '141', '142',
})


# ── WFS helpers ───────────────────────────────────────────────────────────────

def _wfs_json(typename, xmin, ymin, xmax, ymax, count=50, timeout=15):
    params = urllib.parse.urlencode({
        'SERVICE': 'WFS', 'VERSION': '2.0.0', 'REQUEST': 'GetFeature',
        'TYPENAMES': typename,
        'SRSNAME': 'EPSG:2154',
        'BBOX': f'{xmin},{ymin},{xmax},{ymax},EPSG:2154',
        'OUTPUTFORMAT': 'application/json',
        'COUNT': str(count),
    })
    req = urllib.request.Request(_WFS_URL + '?' + params, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _point_in_ring(cx, cy, ring):
    """Ray-casting : True si le point (cx,cy) est à l'intérieur du ring GeoJSON."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > cy) != (yj > cy)) and (cx < (xj - xi) * (cy - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _fetch_clc_code(xmin, ymin, xmax, ymax, cx=None, cy=None):
    """
    Retourne le code CLC 2018 du polygone qui contient le point (cx, cy).
    Si cx/cy absent, renvoie le code du premier polygone (comportement legacy).
    """
    try:
        data = _wfs_json(_CLC_LYR, xmin, ymin, xmax, ymax, count=20)
        feats = data.get('features', [])
        if not feats:
            return None

        if cx is None or cy is None:
            return str(feats[0]['properties'].get('code_18', '') or '').strip()

        for feat in feats:
            code = str(feat['properties'].get('code_18', '') or '').strip()
            geom = feat.get('geometry') or {}
            gtype = geom.get('type', '')
            polys = [geom.get('coordinates', [])] if gtype == 'Polygon' else geom.get('coordinates', [])
            for poly in polys:
                if poly and _point_in_ring(cx, cy, poly[0]):  # test sur le ring extérieur
                    return code

        # Aucun polygone ne contient le point : prendre le plus petit (le plus précis)
        best_code, best_area = None, float('inf')
        for feat in feats:
            code = str(feat['properties'].get('code_18', '') or '').strip()
            geom = feat.get('geometry') or {}
            gtype = geom.get('type', '')
            polys = [geom.get('coordinates', [])] if gtype == 'Polygon' else geom.get('coordinates', [])
            for poly in polys:
                if not poly:
                    continue
                ring = poly[0]
                xs = [c[0] for c in ring]
                ys = [c[1] for c in ring]
                area = (max(xs) - min(xs)) * (max(ys) - min(ys))
                if area < best_area:
                    best_area, best_code = area, code
        return best_code

    except Exception:
        pass
    return None


def _seg_ray_t(p1x, p1y, ux, uy, ax, ay, bx, by):
    """t sur la droite P1+t·u où elle coupe le segment [A,B]. None si aucun."""
    dx, dy = bx - ax, by - ay
    denom  = ux * dy - uy * dx
    if abs(denom) < 1e-10:
        return None
    t = ((ax - p1x) * dy - (ay - p1y) * dx) / denom
    s = ((ax - p1x) * uy - (ay - p1y) * ux) / denom
    return t if 0.0 <= s <= 1.0 else None


def _difference_parcels(transect_geom, xmin, ymin, xmax, ymax, feedback=None):
    """
    Retourne la partie du transect qui NE se superpose PAS aux parcelles
    cadastrales (différence géométrique transect − union des parcelles).
    Retourne QgsGeometry ou None (si erreur, aucune parcelle, ou aucun
    chevauchement détecté → le caller doit utiliser le transect brut).
    """
    def _log(msg):
        if feedback:
            feedback.pushInfo(f'    [Cadastre] {msg}')

    try:
        data = _wfs_json(_CADASTRE_LYR, xmin, ymin, xmax, ymax, count=40)
    except Exception as exc:
        _log(f'Erreur WFS : {exc}')
        return None

    feats = data.get('features', [])
    _log(f'{len(feats)} parcelle(s) reçue(s)')
    if not feats:
        return None

    # Contrôle CRS
    first_ring = (feats[0].get('geometry') or {}).get('coordinates', [[]])[0]
    if first_ring and len(first_ring) > 0:
        sample_x = first_ring[0][0] if isinstance(first_ring[0], (list, tuple)) else first_ring[0]
        if isinstance(sample_x, (int, float)) and abs(sample_x) < 180:
            _log('⚠ Coordonnées en degrés malgré SRSNAME=EPSG:2154 — cadastre ignoré')
            return None

    result = transect_geom
    original_len = transect_geom.length()
    any_overlap = False

    for feat in feats:
        geom_data = feat.get('geometry') or {}
        gtype = geom_data.get('type', '')
        polys = []
        if gtype == 'Polygon':
            polys = [geom_data.get('coordinates', [])]
        elif gtype == 'MultiPolygon':
            polys = geom_data.get('coordinates', [])

        for poly_coords in polys:
            rings = [[QgsPointXY(c[0], c[1]) for c in ring] for ring in poly_coords]
            parcel_geom = QgsGeometry.fromPolygonXY(rings)
            if parcel_geom is None or parcel_geom.isEmpty():
                continue
            if not result.intersects(parcel_geom):
                continue
            any_overlap = True
            try:
                diff = result.difference(parcel_geom)
            except Exception:
                continue
            if diff is None or diff.isEmpty():
                return None  # transect entièrement dans la parcelle
            result = diff

    if not any_overlap:
        return None
    if result.length() >= original_len - 0.01:
        return None  # aucune différence effective
    return result


def _fetch_parcel_crossings(p1x, p1y, ux, uy, seg_len,
                             xmin, ymin, xmax, ymax, feedback=None):
    """
    Retourne la liste triée des t ∈ [0, seg_len] où les contours de parcelles
    IGN croisent le transect.
    Loggue le diagnostic complet via feedback.
    """
    def _log(msg):
        if feedback:
            feedback.pushInfo(f'    [Cadastre] {msg}')

    try:
        data = _wfs_json(_CADASTRE_LYR, xmin, ymin, xmax, ymax, count=40)
    except Exception as exc:
        _log(f'Erreur WFS : {exc}')
        return []

    feats = data.get('features', [])
    _log(f'{len(feats)} parcelle(s) reçue(s)')
    if not feats:
        return []

    # Contrôle CRS : en EPSG:2154 les X sont > 100 000
    first_ring = (feats[0].get('geometry') or {}).get('coordinates', [[]])[0]
    if first_ring and len(first_ring) > 0:
        sample_x = first_ring[0][0] if isinstance(first_ring[0], (list, tuple)) else first_ring[0]
        if isinstance(sample_x, (int, float)) and abs(sample_x) < 180:
            _log('⚠ Coordonnées reçues en degrés (WGS84) malgré SRSNAME=EPSG:2154 — '
                 'intersection impossible, cadastre ignoré.')
            return []

    ts_all, ts_ok = [], []
    for feat in feats:
        geom  = feat.get('geometry') or {}
        gtype = geom.get('type', '')
        rings = []
        if gtype == 'Polygon':
            rings = geom.get('coordinates', [])
        elif gtype == 'MultiPolygon':
            for poly in geom.get('coordinates', []):
                rings.extend(poly)
        for ring in rings:
            for j in range(len(ring) - 1):
                ax, ay = ring[j][0], ring[j][1]
                bx, by = ring[j+1][0], ring[j+1][1]
                t = _seg_ray_t(p1x, p1y, ux, uy, ax, ay, bx, by)
                if t is not None:
                    ts_all.append(t)
                    if 0.0 <= t <= seg_len:
                        ts_ok.append(t)

    _log(f'{len(ts_all)} intersection(s) calculée(s), '
         f'{len(ts_ok)} dans [0, {seg_len:.1f} m]')
    if ts_all and not ts_ok:
        sample = sorted({round(v, 1) for v in ts_all})[:8]
        _log(f'Valeurs t hors plage : {sample}  '
             f'→ vérifier la longueur du transect vs emprise parcellaire')

    return sorted(ts_ok)


# ── profil altimétrique ────────────────────────────────────────────────────────

def _moving_average(arr, win):
    import numpy as np
    if win <= 1 or len(arr) <= win:
        return arr.copy()
    kernel = np.ones(win) / win
    padded = np.pad(arr, win // 2, mode='edge')
    return np.convolve(padded, kernel, mode='valid')[:len(arr)]


def _build_profile(ground_pts, bin_size):
    """
    ground_pts : list of (t, z, intensity, r, g, b)
    Retourne dict {t, z, n, t_min, t_max} ou None.
      z  : min z par bin, interpolé puis lissé (~0.75 m)
      n  : nombre de points LiDAR bruts par bin (avant interpolation)
           → utilisé pour le filtre de densité dans _find_road
    """
    import numpy as np

    if not ground_pts:
        return None

    ts  = [p[0] for p in ground_pts]
    t_min, t_max = min(ts), max(ts)
    span = t_max - t_min
    if span < bin_size:
        return None

    n     = max(2, int(math.ceil(span / bin_size)) + 1)
    bin_z = [[] for _ in range(n)]

    for (t, z, *_) in ground_pts:
        bi = min(n - 1, int((t - t_min) / bin_size))
        bin_z[bi].append(z)

    # Densité brute (avant interpolation) — conservée telle quelle
    prof_n = np.array([len(v) for v in bin_z], dtype=int)

    idx   = np.arange(n, dtype=float)
    z_raw = np.array([min(v) if v else float('nan') for v in bin_z])
    valid = ~np.isnan(z_raw)

    if valid.sum() < 2:
        z_raw[:] = z_raw[valid][0] if valid.sum() else 0.0
    else:
        z_raw = np.interp(idx, idx[valid], z_raw[valid])

    win    = max(1, int(0.75 / bin_size))
    prof_z = _moving_average(z_raw, 2 * win + 1)
    prof_t = t_min + (idx + 0.5) * bin_size

    return {'t': prof_t, 'z': prof_z, 'n': prof_n, 't_min': t_min, 't_max': t_max}


# ── détection de la chaussée ──────────────────────────────────────────────────

def _find_road(prof, bin_size, curb_height, min_angle_deg=20.0, min_pts_seg=5):
    """
    Détecte la chaussée par segmentation sur les cassures altimétriques.

    Deux améliorations issues de la littérature (PMC10820060) :

    1. Critère d'angle de pente (min_angle_deg)
       Une cassure doit être suffisamment ABRUPTE (bordure de trottoir physique)
       et pas juste un talus naturel en pente douce.
       Condition : atan(|dz| / bin_size) ≥ min_angle_deg
       ↔         |dz| ≥ bin_size × tan(min_angle_deg)
       Combiné avec curb_height : seuil_effectif = max(curb_height, dz_angle)
       → une vraie bordure doit être HAUTE (curb_height) ET ABRUPTE (angle).

    2. Filtre de densité (min_pts_seg)
       Un segment n'est candidat chaussée que s'il contient au moins
       min_pts_seg points LiDAR bruts (avant interpolation).
       Évite de retenir un segment reconstruit par interpolation pure.

    Retourne un dict ou None si aucun segment qualifiant.
    """
    import numpy as np

    prof_z = prof['z']
    prof_n = prof.get('n', np.ones(len(prof_z), dtype=int))
    t_min  = prof['t_min']
    n      = len(prof_z)

    # Référence altimétrique robuste (5e percentile)
    z_ref = float(np.percentile(prof_z, 5))

    # ── Seuil de cassure combiné : hauteur ET angle ──────────────────────────
    # atan(dz/bin_size) ≥ min_angle_deg  ↔  dz ≥ bin_size × tan(min_angle_rad)
    min_dz_angle    = bin_size * math.tan(math.radians(min_angle_deg))
    break_threshold = max(curb_height, min_dz_angle)

    dz        = np.abs(np.diff(prof_z))
    break_pos = [int(b) for b in np.where(dz >= break_threshold)[0]]

    boundaries = [-1] + break_pos + [n - 1]

    best = None

    for j in range(len(boundaries) - 1):
        i0 = int(boundaries[j]) + 1
        i1 = int(boundaries[j + 1])
        if i0 > i1:
            continue

        seg_z     = prof_z[i0:i1 + 1]
        seg_n     = prof_n[i0:i1 + 1]
        total_pts = int(seg_n.sum())
        width     = float((i1 - i0 + 1) * bin_size)
        z_min_seg = float(seg_z.min())
        flatness  = float(seg_z.max() - seg_z.min())

        # Filtre densité : segment doit avoir assez de points LiDAR réels
        if min_pts_seg > 0 and total_pts < min_pts_seg:
            continue

        # Critère de niveau : plancher du segment proche du niveau de référence
        if z_min_seg - z_ref > curb_height:
            continue

        if best is None or width > best['road_width']:
            best = {
                'road_t_start': float(t_min + i0 * bin_size),
                'road_t_end':   float(t_min + (i1 + 1) * bin_size),
                'road_width':   width,
                'z_ref':        float(z_ref),
                'z_road_mean':  float(seg_z.mean()),
                'flatness':     round(flatness, 3),
                'n_breaks':     int(len(break_pos)),
                'n_pts_road':   total_pts,
            }

    return best


# ── géométrie des bandeaux ────────────────────────────────────────────────────

def _strip_polygon(p1x, p1y, ux, uy, t0, t1, half_w=0.5):
    px, py = -uy, ux
    return QgsGeometry.fromPolygonXY([[
        QgsPointXY(p1x + ux * t0 + px * half_w, p1y + uy * t0 + py * half_w),
        QgsPointXY(p1x + ux * t1 + px * half_w, p1y + uy * t1 + py * half_w),
        QgsPointXY(p1x + ux * t1 - px * half_w, p1y + uy * t1 - py * half_w),
        QgsPointXY(p1x + ux * t0 - px * half_w, p1y + uy * t0 - py * half_w),
    ]])


# ── algorithme QGIS ───────────────────────────────────────────────────────────

class LidarRoadProfileAlgorithm(QgsProcessingAlgorithm):

    POINTS        = 'POINTS'
    TRANSECTS     = 'TRANSECTS'
    BIN_SIZE      = 'BIN_SIZE'
    CURB_HEIGHT   = 'CURB_HEIGHT'
    MIN_ANGLE     = 'MIN_ANGLE'
    MIN_PTS_SEG   = 'MIN_PTS_SEG'
    USE_CADASTRE  = 'USE_CADASTRE'
    USE_CLC       = 'USE_CLC'
    OUTPUT_MEAS   = 'OUTPUT_MEAS'
    OUTPUT_ZONES  = 'OUTPUT_ZONES'

    def initAlgorithm(self, config=None):

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.POINTS,
            self.tr('Points LiDAR (couche avec champ id_transect)'),
            [QgsProcessing.TypeVectorPoint],
        ))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.TRANSECTS,
            self.tr('Transects perpendiculaires'),
            [QgsProcessing.TypeVectorLine],
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.BIN_SIZE,
            self.tr('Résolution du profil (m)'),
            QgsProcessingParameterNumber.Double,
            defaultValue=0.25, minValue=0.05, maxValue=1.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.CURB_HEIGHT,
            self.tr('Hauteur minimale de bordure (m)'),
            QgsProcessingParameterNumber.Double,
            defaultValue=0.15, minValue=0.02, maxValue=0.80,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_ANGLE,
            self.tr('Angle minimal de cassure (°) — 0 = désactiver'),
            QgsProcessingParameterNumber.Double,
            defaultValue=20.0, minValue=0.0, maxValue=80.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_PTS_SEG,
            self.tr('Points LiDAR min. dans le segment chaussée — 0 = désactiver'),
            QgsProcessingParameterNumber.Integer,
            defaultValue=5, minValue=0, maxValue=500,
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.USE_CADASTRE,
            self.tr('Interroger le cadastre IGN (clip parcelle à parcelle)'),
            defaultValue=True,
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.USE_CLC,
            self.tr('Interroger CLC 2018 IGN (contexte urbain/rural)'),
            defaultValue=True,
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_MEAS,
            self.tr('Mesures par transect'),
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_ZONES,
            self.tr('Zones détectées (bandeaux)'),
        ))

    # ─────────────────────────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        import numpy as np

        pts_layer   = self.parameterAsVectorLayer(parameters, self.POINTS,       context)
        trans_layer = self.parameterAsVectorLayer(parameters, self.TRANSECTS,    context)
        bin_size    = self.parameterAsDouble(parameters,      self.BIN_SIZE,      context)
        curb_height = self.parameterAsDouble(parameters,      self.CURB_HEIGHT,   context)
        min_angle   = self.parameterAsDouble(parameters,      self.MIN_ANGLE,     context)
        min_pts_seg = self.parameterAsInt(parameters,         self.MIN_PTS_SEG,   context)
        use_cad     = self.parameterAsBool(parameters,        self.USE_CADASTRE,  context)
        use_clc     = self.parameterAsBool(parameters,        self.USE_CLC,       context)

        crs_2154 = QgsCoordinateReferenceSystem('EPSG:2154')

        # ── sink mesures ──────────────────────────────────────────────────────
        meas_fields = QgsFields()
        for nm, vt in [
            ('id_transect',      QVariant.Int),
            ('largeur_parcelle', QVariant.Double),  # cadastre ; −1 si indispo
            ('parcel_found',     QVariant.Int),      # 1 = cadastre utilisé
            ('largeur_chaussee', QVariant.Double),   # segment le plus large entre cassures
            ('z_ref',            QVariant.Double),   # 5e pct du profil (référence)
            ('z_chaussee_moy',   QVariant.Double),
            ('flatness',         QVariant.Double),   # variation z interne chaussée (dévers)
            ('n_breaks',         QVariant.Int),      # nombre de cassures dans le domaine
            ('n_pts_road',       QVariant.Int),      # pts LiDAR réels dans la chaussée
            ('n_pts_sol',        QVariant.Int),
            ('clc_code',         QVariant.String),
            ('clc_urbain',       QVariant.Int),
        ]:
            meas_fields.append(QgsField(nm, vt))

        (sink_meas, dest_meas) = self.parameterAsSink(
            parameters, self.OUTPUT_MEAS, context,
            meas_fields, QgsWkbTypes.LineString, crs_2154,
        )

        # ── sink zones ─────────────────────────────────────────────────────────
        zone_fields = QgsFields()
        for nm, vt in [
            ('id_transect', QVariant.Int),
            ('type_zone',   QVariant.String),   # domaine_route | chaussee
            ('largeur',     QVariant.Double),
            ('z_moy',       QVariant.Double),
            ('d_debut',     QVariant.Double),
            ('d_fin',       QVariant.Double),
        ]:
            zone_fields.append(QgsField(nm, vt))

        (sink_zones, dest_zones) = self.parameterAsSink(
            parameters, self.OUTPUT_ZONES, context,
            zone_fields, QgsWkbTypes.Polygon, crs_2154,
        )

        # ── index transects ────────────────────────────────────────────────────
        trans_geoms = {}
        trans_parcel_found = {}   # {feature_id: parcel_found value}

        trans_field_names = [
            trans_layer.fields().field(k).name()
            for k in range(trans_layer.fields().count())
        ]
        # Les transects ont été pré-clippés si le champ parcel_found existe
        trans_preclipped = 'parcel_found' in trans_field_names

        for feat in trans_layer.getFeatures():
            trans_geoms[feat.id()] = feat.geometry()
            if trans_preclipped:
                trans_parcel_found[feat.id()] = int(feat['parcel_found'])

        if trans_preclipped:
            n_pre = sum(1 for v in trans_parcel_found.values() if v == 1)
            feedback.pushInfo(
                f'Transects pré-clippés détectés : {n_pre}/{len(trans_geoms)} '
                f'ont parcel_found=1 → appel WFS cadastre désactivé pour ceux-ci'
            )

        # ── groupement points par id_transect ──────────────────────────────────
        pts_by_tid = {}
        for feat in pts_layer.getFeatures():
            tid = int(feat['id_transect'])
            pts_by_tid.setdefault(tid, []).append((
                float(feat['x']),   float(feat['y']),  float(feat['z']),
                int(feat['classification']),
                int(feat['return_num']), int(feat['num_returns']),
                int(feat['intensity']),
                int(feat['red']),   int(feat['green']), int(feat['blue']),
            ))

        total = len(pts_by_tid)

        for step, (tid, raw_pts) in enumerate(sorted(pts_by_tid.items())):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(step / total * 100))
            feedback.pushInfo(f'── Transect {tid} ({len(raw_pts)} pts bruts) ──')

            geom = trans_geoms.get(tid)
            if geom is None:
                feedback.pushWarning(f'  Transect {tid} absent de la couche transects')
                continue

            line = geom.asPolyline()
            if len(line) < 2:
                continue

            p1, p2 = line[0], line[-1]
            dx, dy  = p2.x() - p1.x(), p2.y() - p1.y()
            seg_len = math.sqrt(dx * dx + dy * dy)
            if seg_len == 0:
                continue
            ux, uy = dx / seg_len, dy / seg_len

            # Bbox WFS (marge = 10 % de la longueur du transect, min 5 m)
            _buf = max(5.0, seg_len * 0.10)
            xmin = min(p1.x(), p2.x()) - _buf
            ymin = min(p1.y(), p2.y()) - _buf
            xmax = max(p1.x(), p2.x()) + _buf
            ymax = max(p1.y(), p2.y()) + _buf

            # ── CLC ──────────────────────────────────────────────────────────
            cx = (p1.x() + p2.x()) / 2.0
            cy = (p1.y() + p2.y()) / 2.0
            clc_code  = None
            clc_urban = -1
            if use_clc:
                clc_code = _fetch_clc_code(xmin, ymin, xmax, ymax, cx=cx, cy=cy)
                if clc_code:
                    clc_urban = 1 if clc_code in _URBAN_CLC else 0
                feedback.pushInfo(
                    f'  CLC: {clc_code or "inconnu"} → '
                    f'{"urbain" if clc_urban == 1 else ("rural" if clc_urban == 0 else "inconnu")}'
                )

            # Ajustement seuil selon contexte (rural = bordures plus basses)
            curb = curb_height * (0.7 if clc_urban == 0 else 1.0)

            # ── filtrage points sol + projection sur axe du transect ──────────
            ground = []
            for (x, y, z, classif, ret, nret, intensity, r, g, b) in raw_pts:
                if classif == 2 or (nret > 0 and ret == nret):
                    t = (x - p1.x()) * ux + (y - p1.y()) * uy
                    ground.append((t, z, intensity, r, g, b))

            if len(ground) < 4:
                feedback.pushInfo(f'  {len(ground)} pts sol — ignoré')
                continue

            # ────────────────────────────────────────────────────────────────
            # ÉTAPE 1 : clip aux limites de parcelles
            #
            # Priorité 1 : transects pré-clippés par "Générer des transects"
            #   (trans_preclipped=True) → la géométrie EST le domaine.
            # Priorité 2 : USE_CADASTRE actif → appel WFS ici.
            # Fallback   : étendue des points sol.
            # ────────────────────────────────────────────────────────────────
            parcel_found   = 0
            t_domain_left  = min(g[0] for g in ground)
            t_domain_right = max(g[0] for g in ground)

            if trans_preclipped and trans_parcel_found.get(tid, 0) == 1:
                # Toute la géométrie du transect = domaine parcellaire
                parcel_found   = 1
                t_domain_left  = 0.0
                t_domain_right = seg_len
                feedback.pushInfo(
                    f'  Transect pré-clippé : domaine = {seg_len:.2f} m'
                )
            elif use_cad:
                crossings = _fetch_parcel_crossings(
                    p1.x(), p1.y(), ux, uy, seg_len,
                    xmin, ymin, xmax, ymax, feedback=feedback,
                )
                if len(crossings) >= 2:
                    parcel_found   = 1
                    t_domain_left  = crossings[0]
                    t_domain_right = crossings[-1]
                    feedback.pushInfo(
                        f'  Domaine parcellaire WFS : {t_domain_left:.2f} → '
                        f'{t_domain_right:.2f} m '
                        f'(largeur = {t_domain_right - t_domain_left:.2f} m)'
                    )
                else:
                    feedback.pushInfo(
                        '  Cadastre sans croisement exploitable → '
                        'domaine = étendue des points sol'
                    )

            largeur_parcelle = round(t_domain_right - t_domain_left, 3)

            # Clip des points sol au domaine
            ground_clip = [
                g for g in ground
                if t_domain_left <= g[0] <= t_domain_right
            ]

            if len(ground_clip) < 4:
                feedback.pushInfo(
                    f'  Seulement {len(ground_clip)} pts sol dans le domaine — ignoré'
                )
                continue

            feedback.pushInfo(
                f'  {len(ground_clip)} pts sol dans le domaine '
                f'[{t_domain_left:.1f}, {t_domain_right:.1f}] m'
            )

            # ────────────────────────────────────────────────────────────────
            # ÉTAPE 2 : profil Z + plus longue suite bas-Z = chaussée
            # ────────────────────────────────────────────────────────────────
            prof = _build_profile(ground_clip, bin_size)
            if prof is None:
                continue

            road = _find_road(prof, bin_size, curb,
                              min_angle_deg=min_angle,
                              min_pts_seg=min_pts_seg)

            if road is None:
                feedback.pushInfo('  Aucune suite bas-Z trouvée')
                largeur_chaussee = 0.0
                z_ref            = float(np.percentile(prof['z'], 5))
                z_road_mean      = z_ref
            else:
                largeur_chaussee = round(road['road_width'], 3)
                z_ref            = round(road['z_ref'], 3)
                z_road_mean      = round(road['z_road_mean'], 3)
                feedback.pushInfo(
                    f'  Chaussée : {road["road_t_start"]:.2f} → '
                    f'{road["road_t_end"]:.2f} m '
                    f'(largeur = {largeur_chaussee:.2f} m, '
                    f'z_moy = {z_road_mean:.3f} m)'
                )

            # ── écriture mesures ──────────────────────────────────────────────
            mf = QgsFeature(meas_fields)
            mf.setGeometry(geom)
            mf.setAttributes([
                int(tid),
                float(largeur_parcelle),
                int(parcel_found),
                float(largeur_chaussee),
                float(round(z_ref, 3)),
                float(z_road_mean),
                float(road['flatness'])   if road else float(-1.0),
                int(road['n_breaks'])     if road else int(0),
                int(road['n_pts_road'])   if road else int(0),
                int(len(ground_clip)),
                str(clc_code or ''),
                int(clc_urban),
            ])
            sink_meas.addFeature(mf)

            # ── écriture zones ────────────────────────────────────────────────
            # Zone 1 : domaine routier (parcelle à parcelle)
            zf_dom = QgsFeature(zone_fields)
            zf_dom.setGeometry(
                _strip_polygon(p1.x(), p1.y(), ux, uy,
                               t_domain_left, t_domain_right, half_w=0.5)
            )
            zf_dom.setAttributes([
                int(tid), 'domaine_route',
                float(largeur_parcelle),
                float(np.mean([g[1] for g in ground_clip])),
                float(t_domain_left),
                float(t_domain_right),
            ])
            sink_zones.addFeature(zf_dom)

            # Zone 2 : chaussée (plus longue suite bas-Z)
            if road is not None:
                zf_road = QgsFeature(zone_fields)
                zf_road.setGeometry(
                    _strip_polygon(p1.x(), p1.y(), ux, uy,
                                   road['road_t_start'], road['road_t_end'],
                                   half_w=0.5)
                )
                zf_road.setAttributes([
                    int(tid), 'chaussee',
                    float(largeur_chaussee),
                    float(z_road_mean),
                    float(road['road_t_start']),
                    float(road['road_t_end']),
                ])
                sink_zones.addFeature(zf_road)

        return {self.OUTPUT_MEAS: dest_meas, self.OUTPUT_ZONES: dest_zones}

    # ── metadata ──────────────────────────────────────────────────────────────

    def name(self):         return 'lidar_road_profile'
    def displayName(self):  return self.tr('Profil de chaussée LiDAR')
    def group(self):        return self.tr('LiDAR')
    def groupId(self):      return 'lidar'

    def shortHelpString(self):
        return self.tr(
            'Détecte la largeur de chaussée en deux étapes :\n\n'
            '① Clip cadastral (WFS IGN)\n'
            '   Les limites de parcelles qui croisent le transect définissent\n'
            '   l\'emprise routière (largeur_parcelle). Si le cadastre est\n'
            '   indisponible, l\'étendue des points sol est utilisée.\n\n'
            '② Plus longue suite bas-Z\n'
            '   Sur la portion clippée, on cherche la séquence contiguë la plus\n'
            '   longue dont l\'altitude est ≤ 5e-percentile + seuil_bordure.\n'
            '   C\'est la chaussée (largeur_chaussee).\n\n'
            'Paramètre clé :\n'
            '- Tolérance z chaussée : marge altimétrique au-dessus du plancher\n'
            '  pour qu\'un bin soit considéré "au niveau de la route".\n'
            '  En zone rurale, ce seuil est réduit à ×0.7.\n\n'
            'Sorties :\n'
            '- Mesures : une ligne par transect\n'
            '  (largeur_parcelle, parcel_found, largeur_chaussee, z_ref…)\n'
            '- Zones : deux bandeaux par transect\n'
            '  · domaine_route = emprise parcelle à parcelle\n'
            '  · chaussee      = plus longue suite bas-Z'
        )

    def createInstance(self):
        return LidarRoadProfileAlgorithm()

    def tr(self, s):
        return QCoreApplication.translate('LidarRoadProfileAlgorithm', s)
