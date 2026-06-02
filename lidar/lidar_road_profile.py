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


