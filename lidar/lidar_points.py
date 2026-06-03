# -*- coding: utf-8 -*-
import os
import sys
import json
import math
import hashlib
import tempfile
import datetime
import urllib.request
import urllib.parse

_GPS_EPOCH = datetime.datetime(1980, 1, 6, tzinfo=datetime.timezone.utc)
_GPS_LEAP_SECONDS = 18  # valeur stable depuis 2017


def _gps_time_to_utc(adjusted_gps_time):
    """Convertit le GPS time ajusté LAS (GPS sec − 1e9) en chaîne UTC lisible."""
    try:
        gps_sec = float(adjusted_gps_time) + 1_000_000_000.0
        dt = _GPS_EPOCH + datetime.timedelta(seconds=gps_sec - _GPS_LEAP_SECONDS)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ''

# Lib path + DLL copclib (import différé pour ne pas verrouiller le .pyd au démarrage)
_plugin_dir = os.path.dirname(os.path.dirname(__file__))
_lib_dir = os.path.join(_plugin_dir, 'lib')
if _lib_dir not in sys.path:
    sys.path.insert(0, _lib_dir)
_copclib_bin = os.path.join(_lib_dir, 'copclib', 'bin')
if os.path.isdir(_copclib_bin) and hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(_copclib_bin)

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFile,
    QgsProcessingParameterFeatureSink,
    QgsFeature,
    QgsGeometry,
    QgsPoint,
    QgsWkbTypes,
    QgsFields,
    QgsField,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant

WFS_URL = 'https://data.geopf.fr/wfs/ows'
WFS_LAYER = 'IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle'
DEFAULT_CACHE = os.path.join(tempfile.gettempdir(), 'lidar_ign_cache')


def _wfs_get_tile_urls(xmin, ymin, xmax, ymax):
    params = urllib.parse.urlencode({
        'SERVICE': 'WFS',
        'VERSION': '2.0.0',
        'REQUEST': 'GetFeature',
        'TYPENAMES': WFS_LAYER,
        'BBOX': f'{xmin},{ymin},{xmax},{ymax},EPSG:2154',
        'OUTPUTFORMAT': 'application/json',
        'COUNT': '50',
    })
    req = urllib.request.Request(WFS_URL + '?' + params, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    return [
        f['properties']['url']
        for f in data.get('features', [])
        if f.get('properties', {}).get('url')
    ]


_HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; QGIS LiDAR plugin)'}


def _get_local_tile(url, cache_dir, feedback):
    """Retourne le chemin local de la dalle, en la téléchargeant si nécessaire."""
    os.makedirs(cache_dir, exist_ok=True)
    filename = hashlib.md5(url.encode()).hexdigest() + '.copc.laz'
    local = os.path.join(cache_dir, filename)
    if os.path.exists(local):
        feedback.pushInfo(f'    Cache hit : {url.split("/")[-1]}')
        return local
    feedback.pushInfo(f'    Téléchargement : {url.split("/")[-1]}')
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=120) as resp:
        with open(local, 'wb') as f:
            f.write(resp.read())
    size_mb = os.path.getsize(local) / 1_048_576
    feedback.pushInfo(f'    OK ({size_mb:.1f} Mo)')
    return local


def _mask_buffer(px, py, x1, y1, x2, y2, buf):
    """Masque numpy : points à moins de buf mètres du segment (x1,y1)-(x2,y2)."""
    import numpy as np
    dx, dy = x2 - x1, y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq == 0:
        return np.sqrt((px - x1) ** 2 + (py - y1) ** 2) <= buf
    t = np.clip(((px - x1) * dx + (py - y1) * dy) / len_sq, 0.0, 1.0)
    return np.sqrt((px - x1 - t * dx) ** 2 + (py - y1 - t * dy) ** 2) <= buf


ORTHO_WMS_URL = 'https://data.geopf.fr/wms-r'
ORTHO_LAYER   = 'ORTHOIMAGERY.ORTHOPHOTOS'


def _decode_png_rgb(data):
    """Décodeur PNG minimal (stdlib pure) — retourne rows[y][x] = (r, g, b) 8 bits."""
    import zlib, struct
    pos, idat, w, h, ct = 8, b'', 0, 0, 2
    while pos < len(data):
        n    = struct.unpack('>I', data[pos:pos+4])[0]
        kind = data[pos+4:pos+8]
        cd   = data[pos+8:pos+8+n]
        if kind == b'IHDR':
            w, h, _, ct = struct.unpack('>IIBB', cd[:10])
        elif kind == b'IDAT':
            idat += cd
        elif kind == b'IEND':
            break
        pos += 12 + n
    raw = zlib.decompress(idat)
    ch  = 4 if ct == 6 else 3
    st  = w * ch
    rows, prev = [], bytes(st)
    for y in range(h):
        i0   = y * (st + 1)
        f, r = raw[i0], bytearray(raw[i0+1:i0+1+st])
        if f == 1:
            for i in range(ch, st): r[i] = (r[i] + r[i-ch]) & 0xFF
        elif f == 2:
            for i in range(st):     r[i] = (r[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(st):
                a = r[i-ch] if i >= ch else 0
                r[i] = (r[i] + (a + prev[i]) // 2) & 0xFF
        elif f == 4:
            for i in range(st):
                a = r[i-ch] if i >= ch else 0
                b = prev[i]; c = prev[i-ch] if i >= ch else 0; p = a + b - c
                pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                r[i] = (r[i] + pr) & 0xFF
        rows.append([(r[i], r[i+1], r[i+2]) for i in range(0, st, ch)])
        prev = bytes(r)
    return rows


def _wms_ortho(xmin, ymin, xmax, ymax):
    """Télécharge l'orthophoto IGN à 20 cm/pixel sur le bbox EPSG:2154.
    Retourne (ox, oy, pw, ph, rows) pour un échantillonnage rapide."""
    pw = ph = 0.2
    imgw = max(1, min(2000, round((xmax - xmin) / pw)))
    imgh = max(1, min(2000, round((ymax - ymin) / ph)))
    params = urllib.parse.urlencode({
        'SERVICE': 'WMS', 'VERSION': '1.3.0', 'REQUEST': 'GetMap',
        'LAYERS': ORTHO_LAYER, 'STYLES': '',
        'CRS': 'EPSG:2154',
        'BBOX': f'{xmin},{ymin},{xmax},{ymax}',
        'WIDTH': imgw, 'HEIGHT': imgh,
        'FORMAT': 'image/png',
    })
    url = ORTHO_WMS_URL + '?' + params
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            rows = _decode_png_rgb(resp.read())
    except Exception as e:
        raise Exception(f'{e} — URL: {url}') from e
    return xmin, ymax, (xmax - xmin) / imgw, (ymax - ymin) / imgh, rows


def _sample_rgb(img, x, y):
    """Retourne (r, g, b) 0-255 à la coordonnée EPSG:2154 dans une image ortho."""
    ox, oy, pw, ph, rows = img
    h = len(rows)
    w = len(rows[0]) if h else 0
    col = max(0, min(w - 1, int((x - ox) / pw)))
    row = max(0, min(h - 1, int((oy - y) / ph)))
    return rows[row][col]


class LidarTransectPointsAlgorithm(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    BUFFER = 'BUFFER'
    CACHE_DIR = 'CACHE_DIR'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                self.tr('Couche de transects'),
                [QgsProcessing.TypeVectorLine]
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.BUFFER,
                self.tr('Buffer autour du transect (m)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.5,
                minValue=0.1,
                maxValue=2.0
            )
        )
        param_cache = QgsProcessingParameterFile(
            self.CACHE_DIR,
            self.tr('Dossier cache dalles LiDAR'),
            behavior=QgsProcessingParameterFile.Folder,
            optional=True,
            defaultValue=DEFAULT_CACHE,
        )
        self.addParameter(param_cache)
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Points LiDAR'),
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        import numpy as np
        import copclib

        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        buf = self.parameterAsDouble(parameters, self.BUFFER, context)
        cache_dir = self.parameterAsString(parameters, self.CACHE_DIR, context) or DEFAULT_CACHE

        crs_2154 = QgsCoordinateReferenceSystem('EPSG:2154')
        transform = None
        if layer.sourceCrs() != crs_2154:
            transform = QgsCoordinateTransform(
                layer.sourceCrs(), crs_2154, context.transformContext()
            )
            feedback.pushInfo(self.tr(
                f'Reprojection {layer.sourceCrs().authid()} → EPSG:2154'
            ))

        fields = QgsFields()
        fields.append(QgsField('id_transect', QVariant.Int))
        fields.append(QgsField('d_along',     QVariant.Double))  # distance projetée depuis P1 du transect (m)
        fields.append(QgsField('x', QVariant.Double))
        fields.append(QgsField('y', QVariant.Double))
        fields.append(QgsField('z', QVariant.Double))
        fields.append(QgsField('intensity', QVariant.Int))
        fields.append(QgsField('classification', QVariant.Int))
        fields.append(QgsField('return_num', QVariant.Int))
        fields.append(QgsField('num_returns', QVariant.Int))
        fields.append(QgsField('scan_angle', QVariant.Int))
        fields.append(QgsField('gps_time', QVariant.Double))
        fields.append(QgsField('gps_date', QVariant.String))
        fields.append(QgsField('red', QVariant.Int))
        fields.append(QgsField('green', QVariant.Int))
        fields.append(QgsField('blue', QVariant.Int))
        fields.append(QgsField('nir', QVariant.Int))
        fields.append(QgsField('point_source_id', QVariant.Int))
        fields.append(QgsField('user_data', QVariant.Int))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context,
            fields, QgsWkbTypes.PointZ, crs_2154
        )

        features = list(layer.getFeatures())
        total = len(features)
        # Garde les readers ouverts pour réutiliser la même dalle sur plusieurs transects
        readers = {}

        for i, feat in enumerate(features):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(i / total * 100))

            geom = feat.geometry()
            if transform:
                geom.transform(transform)

            line = geom.asPolyline()
            if len(line) < 2:
                continue

            x1, y1 = line[0].x(), line[0].y()
            x2, y2 = line[-1].x(), line[-1].y()

            # Vecteur directeur unitaire du transect (P1 → P2)
            _dx = x2 - x1
            _dy = y2 - y1
            _len = math.sqrt(_dx * _dx + _dy * _dy)
            ux_t = _dx / _len if _len > 0 else 0.0
            uy_t = _dy / _len if _len > 0 else 0.0

            xmin = min(x1, x2) - buf
            ymin = min(y1, y2) - buf
            xmax = max(x1, x2) + buf
            ymax = max(y1, y2) + buf

            feedback.pushInfo(self.tr(f'Transect {feat.id()}'))

            try:
                ortho_img = _wms_ortho(xmin, ymin, xmax, ymax)
                feedback.pushInfo('  Ortho OK')
            except Exception as e:
                ortho_img = None
                feedback.pushWarning(f'  Ortho WMS erreur : {e}')

            try:
                urls = _wfs_get_tile_urls(xmin, ymin, xmax, ymax)
            except Exception as e:
                feedback.pushWarning(f'  WFS erreur : {e}')
                continue

            if not urls:
                feedback.pushInfo('  Aucune dalle LiDAR disponible sur cette zone')
                continue

            feedback.pushInfo(f'  {len(urls)} dalle(s)')

            for url in urls:
                if feedback.isCanceled():
                    break
                try:
                    local = _get_local_tile(url, cache_dir, feedback)

                    if url not in readers:
                        readers[url] = copclib.FileReader(local)
                    reader = readers[url]

                    try:
                        pdrf = reader.copc_config.las_header.point_format_id
                    except Exception:
                        pdrf = 0
                    has_rgb = pdrf in (2, 3, 5, 7, 8)
                    has_nir = pdrf == 8

                    box = copclib.Box(xmin, ymin, xmax, ymax)
                    points = reader.GetPointsWithinBox(box)

                    if len(points) == 0:
                        feedback.pushInfo('    0 point dans le bbox COPC')
                        continue

                    feedback.pushInfo(f'    PDRF {pdrf} — RGB:{"oui" if has_rgb else "non"} NIR:{"oui" if has_nir else "non"}')

                    xs = np.array([pt.x for pt in points])
                    ys = np.array([pt.y for pt in points])
                    zs = np.array([pt.z for pt in points])
                    intens   = [getattr(pt, 'intensity', 0) for pt in points]
                    classifs = [getattr(pt, 'classification', 0) for pt in points]
                    rets     = [getattr(pt, 'return_number', 0) for pt in points]
                    nrets    = [getattr(pt, 'number_of_returns', 0) for pt in points]
                    angles   = [getattr(pt, 'scan_angle', 0) for pt in points]
                    times    = [getattr(pt, 'gps_time', 0.0) for pt in points]
                    n = len(points)
                    reds     = [pt.red   for pt in points] if has_rgb else [0] * n
                    greens   = [pt.green for pt in points] if has_rgb else [0] * n
                    blues    = [pt.blue  for pt in points] if has_rgb else [0] * n
                    nirs     = [pt.nir   for pt in points] if has_nir else [0] * n
                    src_ids  = [getattr(pt, 'point_source_id', 0) for pt in points]
                    udatas   = [getattr(pt, 'user_data', 0) for pt in points]

                    mask = _mask_buffer(
                        np.array(xs), np.array(ys),
                        x1, y1, x2, y2, buf
                    )
                    idxs = np.where(mask)[0]
                    feedback.pushInfo(f'    {len(idxs)}/{len(xs)} points dans le buffer')

                    for idx in idxs:
                        f = QgsFeature(fields)
                        fx, fy, fz = float(xs[idx]), float(ys[idx]), float(zs[idx])
                        f.setGeometry(QgsGeometry(QgsPoint(fx, fy, fz)))
                        if has_rgb:
                            rv, gv, bv = int(reds[idx]), int(greens[idx]), int(blues[idx])
                        elif ortho_img is not None:
                            rv, gv, bv = _sample_rgb(ortho_img, fx, fy)
                        else:
                            rv = gv = bv = 0
                        nv = int(nirs[idx]) if has_nir else 0
                        # Projection du point sur l'axe du transect (équivalent de
                        # line_locate_point dans QGIS) : distance depuis P1 en mètres.
                        d_along = round((fx - x1) * ux_t + (fy - y1) * uy_t, 3)
                        f.setAttributes([
                            feat.id(),
                            d_along,
                            round(fx, 3),
                            round(fy, 3),
                            round(fz, 3),
                            int(intens[idx]),
                            int(classifs[idx]),
                            int(rets[idx]),
                            int(nrets[idx]),
                            int(angles[idx]),
                            float(times[idx]),
                            _gps_time_to_utc(times[idx]),
                            rv,
                            gv,
                            bv,
                            nv,
                            int(src_ids[idx]),
                            int(udatas[idx]),
                        ])
                        sink.addFeature(f)

                except Exception as e:
                    feedback.pushWarning(f'  Erreur dalle : {e}')
                    import traceback
                    feedback.pushWarning(traceback.format_exc())

        return {self.OUTPUT: dest_id}

    def name(self):
        return 'lidar_points_transects'

    def displayName(self):
        return self.tr('Points LiDAR sur transects (IGN)')

    def group(self):
        return self.tr('LiDAR')

    def groupId(self):
        return 'lidar'

    def shortHelpString(self):
        return self.tr(
            'Télécharge les points LiDAR HD IGN dans un buffer autour de chaque transect.\n\n'
            'Paramètres :\n'
            '- Buffer : 0,5 m à 2 m de chaque côté du transect\n'
            '- Dossier cache : les dalles téléchargées sont conservées pour éviter\n'
            '  de les re-télécharger (dalles de ~50 Mo chacune)\n\n'
            'Attributs en sortie : x, y, z, intensity, classification ASPRS,\n'
            'return_num, num_returns, scan_angle, gps_time.\n\n'
            'Données : IGN LiDAR HD via Géoplateforme (COPC, accès public, EPSG:2154).\n'
            'La couche d\'entrée est automatiquement reprojetée si nécessaire.'
        )

    def createInstance(self):
        return LidarTransectPointsAlgorithm()

    def tr(self, string):
        return QCoreApplication.translate('LidarTransectPointsAlgorithm', string)
