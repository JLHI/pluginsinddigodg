# -*- coding: utf-8 -*-
import os
import json
import tempfile
import urllib.parse

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsGeometry,
    QgsDataSourceUri,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsVectorFileWriter,
    QgsFeatureRequest,
    QgsWkbTypes,
)

from .network import http_get_sync, http_get_cas_auth


# ---------- Credentials ----------

def resolve_credentials(conn):
    """Lit user/password depuis les variables globales QGIS (credentials_var) ou la config directe."""
    key = conn.get('credentials_var')
    if key:
        from qgis.core import QgsExpressionContextUtils
        scope = QgsExpressionContextUtils.globalScope()
        user = scope.variable(f'{key}_user') or ''
        password = scope.variable(f'{key}_password') or ''
        return user, password
    return conn.get('user', ''), conn.get('password', '')


def check_required_credentials():
    """Retourne la liste des messages d'avertissement pour les credentials manquantes."""
    from qgis.core import QgsExpressionContextUtils
    from .sources import DEFAULT_CONFIG
    missing = []
    seen = set()
    for group in DEFAULT_CONFIG.get('groups', {}).values():
        for src in group.get('sources', []):
            conn = src.get('conn', {})
            key = conn.get('credentials_var')
            if key and key not in seen:
                seen.add(key)
                scope = QgsExpressionContextUtils.globalScope()
                user = scope.variable(f'{key}_user')
                pwd = scope.variable(f'{key}_password')
                if not user or not pwd:
                    missing.append(
                        f'Variables QGIS manquantes : "{key}_user" et/ou "{key}_password" '
                        f'(requis pour : {src["name"]}). '
                        f'Configurer via Réglages → Options → Variables.'
                    )
    return missing


# ---------- PostGIS ----------

def fetch_from_postgis(src, bbox_2154, feedback=None):
    """Charge une couche PostGIS et filtre par bbox via QgsFeatureRequest.

    On ne met PAS de filtre SQL dans l'URI : quand le résultat est vide,
    QGIS ne peut pas détecter le type géométrique et renvoie isValid()=False
    sans message d'erreur. Avec setFilterRect, la détection utilise les
    métadonnées de la table complète, et la requête spatiale est pushdown
    côté PostgreSQL via l'index spatial.
    """
    conn = src['conn']
    uri = QgsDataSourceUri()
    if conn.get('service'):
        uri.setParam('service', conn['service'])
    else:
        uri.setConnection(
            conn.get('host', ''), conn.get('port', '5432'),
            conn.get('dbname', ''), conn.get('user', ''), conn.get('password', '')
        )
    schema = conn.get('schema', 'public')
    table = conn.get('table')
    geom_col = conn.get('geom_column', 'geom')
    key_col = conn.get('key_column', '')

    def _make_layer(uri_obj):
        uri_obj.setUseEstimatedMetadata(True)
        return QgsVectorLayer(uri_obj.uri(), src['name'], 'postgres')

    def _build_uri():
        u = QgsDataSourceUri()
        if conn.get('service'):
            u.setParam('service', conn['service'])
        else:
            u.setConnection(
                conn.get('host', ''), conn.get('port', '5432'),
                conn.get('dbname', ''), conn.get('user', ''), conn.get('password', '')
            )
        return u

    if key_col:
        uri.setDataSource(schema, table, geom_col, '', key_col)
    else:
        uri.setDataSource(schema, table, geom_col)
    layer = _make_layer(uri)

    # Fallback ROW_NUMBER pour vues / vues matérialisées sans PK
    if not layer.isValid() and not key_col:
        if feedback:
            feedback.pushInfo('    Retry avec ROW_NUMBER (vue/mat. view ?)')
        uri2 = _build_uri()
        fq = f'"{schema}"."{table}"' if schema else f'"{table}"'
        sub = f'(SELECT *, ROW_NUMBER() OVER () AS _pk FROM {fq}) AS _src'
        uri2.setDataSource('', sub, geom_col, '', '_pk')
        layer = _make_layer(uri2)

    if not layer.isValid():
        provider_err = ''
        try:
            if layer.dataProvider():
                provider_err = layer.dataProvider().error().message()
        except Exception:
            pass
        msg = f"PostGIS invalide : {schema}.{table}"
        if feedback:
            feedback.pushWarning(msg)
            if provider_err:
                feedback.pushInfo(f"    Erreur provider : {provider_err}")
            feedback.pushInfo(f"    Service : {conn.get('service', '(host)')}")
        raise IOError(f"{msg} | {provider_err}" if provider_err else msg)

    lambert = QgsCoordinateReferenceSystem('EPSG:2154')
    layer_crs = layer.crs()
    if layer_crs.authid() != 'EPSG:2154':
        tr = QgsCoordinateTransform(lambert, layer_crs, QgsProject.instance())
        filter_bbox = tr.transformBoundingBox(bbox_2154)
        if feedback:
            feedback.pushInfo(f'    CRS couche : {layer_crs.authid()} → bbox reprojeté')
    else:
        filter_bbox = bbox_2154
    request = QgsFeatureRequest().setFilterRect(filter_bbox)
    feats = list(layer.getFeatures(request))
    if feedback:
        feedback.pushInfo(f'    PostGIS : {len(feats)} entités')

    return _build_memory(layer, feats, src['name'])


# ---------- WFS ----------

def fetch_from_wfs(src, bbox_2154, feedback=None, temp_files=None):
    """Charge un WFS avec 3 tentatives : provider QGIS → HTTP GeoJSON → HTTP GML.

    Le provider QGIS natif échoue sur certains services qui retournent du GML 3.2
    avec des namespaces non standard (ex. SANDRE/sa:). Les fallbacks HTTP téléchargent
    la couche complète et filtrent localement par bbox.
    """
    conn = src['conn']
    base_url = conn['base_url']
    typename = conn['typename']
    version = conn.get('version', 'auto')
    srsname = conn.get('srsname', 'EPSG:2154')
    ver_str = '2.0.0' if version == 'auto' else version

    # Séparateur pour les fallbacks HTTP : '&' si la base_url contient déjà '?'
    sep = '&' if '?' in base_url else '?'

    # Bbox en chaîne pour le filtre BBOX côté serveur (WFS 2.0 : minx,miny,maxx,maxy,CRS)
    bbox_param = (
        f"{bbox_2154.xMinimum()},{bbox_2154.yMinimum()},"
        f"{bbox_2154.xMaximum()},{bbox_2154.yMaximum()},{srsname}"
    )

    uri = f"url='{base_url}' typename='{typename}' version='{version}' srsname='{srsname}'"
    layer = QgsVectorLayer(uri, src['name'], 'WFS')
    if layer.isValid():
        feats = _wfs_filter_bbox(layer, bbox_2154, feedback)
        if feedback:
            feedback.pushInfo(f'    WFS natif : {len(feats)} entités ({typename})')
        return _build_memory(layer, feats, src['name'])

    if feedback:
        feedback.pushInfo('    WFS provider natif KO → essai HTTP GeoJSON…')

    geojson_url = (
        f"{base_url}{sep}SERVICE=WFS&VERSION={ver_str}&REQUEST=GetFeature"
        f"&TYPENAME={typename}&SRSNAME={srsname}&outputFormat=application/json"
        f"&BBOX={bbox_param}"
    )
    try:
        txt = http_get_sync(geojson_url, feedback=feedback)
        geojson = json.loads(txt)
        if geojson.get('type') in ('FeatureCollection', 'Feature'):
            n = len(geojson.get('features', []))
            if feedback:
                feedback.pushInfo(f'    WFS GeoJSON : {n} entités')
            layer = _geojson_to_layer(geojson, src['name'], temp_files)
            feats = _wfs_filter_bbox(layer, bbox_2154, feedback)
            return _build_memory(layer, feats, src['name'])
    except Exception as e_geojson:
        if feedback:
            feedback.pushInfo(f'    HTTP GeoJSON KO : {e_geojson}')

    if feedback:
        feedback.pushInfo('    Essai HTTP GML brut…')

    gml_url = (
        f"{base_url}{sep}SERVICE=WFS&VERSION={ver_str}&REQUEST=GetFeature"
        f"&TYPENAME={typename}&SRSNAME={srsname}&BBOX={bbox_param}"
    )
    txt_gml = http_get_sync(gml_url, feedback=feedback)
    fd, tmp_path = tempfile.mkstemp(suffix='.gml')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(txt_gml)
    except Exception:
        os.unlink(tmp_path)
        raise
    if temp_files is not None:
        temp_files.append(tmp_path)

    layer = QgsVectorLayer(tmp_path, src['name'], 'ogr')
    if not layer.isValid():
        raise IOError(f"WFS invalide (GML) : {typename} sur {base_url}")

    feats = _wfs_filter_bbox(layer, bbox_2154, feedback)
    if feedback:
        feedback.pushInfo(f'    WFS GML : {len(feats)} entités ({typename})')
    return _build_memory(layer, feats, src['name'])


# ---------- API GeoJSON ----------

def fetch_from_api(src, centroid_pt_wgs84, dist_km, feedback=None, temp_files=None, bbox_2154=None):
    conn = src['conn']
    url_tpl = conn['url']

    _bb_wgs84 = None
    _la = _lo = _La = _Lo = None
    if bbox_2154 is not None:
        _wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        _tr = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem('EPSG:2154'), _wgs84, QgsProject.instance()
        )
        _bb_wgs84 = _tr.transformBoundingBox(bbox_2154)
        _la, _lo = _bb_wgs84.yMinimum(), _bb_wgs84.xMinimum()
        _La, _Lo = _bb_wgs84.yMaximum(), _bb_wgs84.xMaximum()

    bbox_wgs84_ods_polygon = (
        f"({_la:.6f},{_lo:.6f}),({_La:.6f},{_lo:.6f}),"
        f"({_La:.6f},{_Lo:.6f}),({_la:.6f},{_Lo:.6f}),({_la:.6f},{_lo:.6f})"
    ) if _la is not None else ''

    url = url_tpl.format(
        lat=centroid_pt_wgs84.y(), lon=centroid_pt_wgs84.x(), dist_km=dist_km,
        bbox_wgs84_ods_polygon=bbox_wgs84_ods_polygon,
    )

    # Filtre géographique opendatasoft v2.1 : where=geometry(`field`, geom'POLYGON((lon lat, ...))')
    if _bb_wgs84 is not None and conn.get('ods_where_geo_field'):
        field = conn['ods_where_geo_field']
        wkt_inner = (
            f"{_lo:.6f} {_la:.6f}, {_lo:.6f} {_La:.6f}, "
            f"{_Lo:.6f} {_La:.6f}, {_Lo:.6f} {_la:.6f}, {_lo:.6f} {_la:.6f}"
        )
        where_val = f"geometry(`{field}`, geom'POLYGON(({wkt_inner}))')"
        sep = '&' if '?' in url else '?'
        url = url + sep + 'where=' + urllib.parse.quote(where_val, safe='')

    if feedback:
        feedback.pushInfo(f'    URL : {url}')

    if conn.get('login_url'):
        user, password = resolve_credentials(conn)
        if not user or not password:
            key = conn.get('credentials_var', '?')
            raise IOError(
                f"Identifiants manquants pour '{src['name']}'. "
                f"Définir les variables QGIS \"{key}_user\" et \"{key}_password\" "
                f"(Réglages → Options → Variables)."
            )
        txt = http_get_cas_auth(
            url, user=user, password=password,
            cas_login_url=conn['login_url'], timeout_s=120, feedback=feedback,
        )
    else:
        txt = http_get_sync(url, feedback=feedback)

    geojson = json.loads(txt)
    n = len(geojson.get('features', []))
    if feedback:
        feedback.pushInfo(f'    API : {n} entités')
    layer = _geojson_to_layer(geojson, src['name'], temp_files)

    if bbox_2154 is None:
        return layer

    layer_crs = layer.crs()
    if not layer_crs.isValid() or not layer_crs.authid():
        layer_crs = QgsCoordinateReferenceSystem('EPSG:4326')

    if layer_crs.authid() in ('EPSG:4326', 'OGC:CRS84') and _bb_wgs84 is not None:
        filter_bbox = _bb_wgs84
    elif layer_crs.authid() == 'EPSG:2154':
        filter_bbox = bbox_2154
    else:
        tr = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem('EPSG:2154'), layer_crs, QgsProject.instance()
        )
        filter_bbox = tr.transformBoundingBox(bbox_2154)

    bbox_geom = QgsGeometry.fromRect(filter_bbox)
    feats = [
        f for f in layer.getFeatures()
        if not f.geometry().isNull() and f.geometry().intersects(bbox_geom)
    ]
    if feedback:
        feedback.pushInfo(f'    API après filtre bbox ({layer_crs.authid()}) : {len(feats)} entités')
    crs = layer_crs.authid() or 'EPSG:4326'
    return _build_memory(layer, feats, src['name'], crs=crs)


# ---------- Sauvegarde ----------

def save_layer_as_gpkg(layer, output_path, layer_name, feedback=None):
    output_path = os.path.normpath(output_path)
    folder = os.path.dirname(output_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = 'GPKG'
    opts.fileEncoding = 'UTF-8'
    opts.layerName = layer_name
    # Si le fichier existe déjà (ouvert dans QGIS), on écrase la couche en place
    # plutôt que de recréer le fichier — évite le verrou Windows (ErrCreateDataSource)
    if os.path.exists(output_path):
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    ctx = QgsProject.instance().transformContext()
    result = QgsVectorFileWriter.writeAsVectorFormatV2(layer, output_path, ctx, opts)
    err = result[0] if isinstance(result, (list, tuple)) else result
    if err != QgsVectorFileWriter.NoError:
        msg = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else ''
        raise IOError(f"Erreur écriture {output_path} (code {err}) {msg}")


# ---------- Dispatch ----------

def fetch_source(src, buffer_bbox, dist_km, centroid_wgs, feedback, temp_files):
    typ = src.get('type', '')
    if typ == 'manual':
        if feedback:
            feedback.pushInfo('    Source manuelle – ignorée')
        return None
    if typ == 'raster':
        if feedback:
            feedback.pushInfo('    Source raster – non gérée ici')
        return None
    if typ == 'postgis':
        return fetch_from_postgis(src, buffer_bbox, feedback)
    if typ == 'wfs':
        return fetch_from_wfs(src, buffer_bbox, feedback, temp_files)
    if typ == 'api_geojson':
        return fetch_from_api(src, centroid_wgs, dist_km, feedback, temp_files, buffer_bbox)
    if feedback:
        feedback.pushWarning(f'    Type non supporté : {typ}')
    return None


# ---------- Helpers privés ----------

def _build_memory(layer, feats, name, crs=None):
    geom_type = QgsWkbTypes.displayString(layer.wkbType())
    crs = crs or layer.crs().authid() or 'EPSG:4326'
    mem = QgsVectorLayer(f"{geom_type}?crs={crs}", name, 'memory')
    prov = mem.dataProvider()
    prov.addAttributes(layer.fields())
    mem.updateFields()
    if feats:
        prov.addFeatures(feats)
    return mem


def _wfs_filter_bbox(layer, bbox_2154, feedback=None):
    lambert = QgsCoordinateReferenceSystem('EPSG:2154')
    layer_crs = layer.crs()
    if layer_crs.authid() != 'EPSG:2154':
        tr = QgsCoordinateTransform(lambert, layer_crs, QgsProject.instance())
        filter_bbox = tr.transformBoundingBox(bbox_2154)
        if feedback:
            feedback.pushInfo(f'    CRS WFS : {layer_crs.authid()} → bbox reprojeté')
    else:
        filter_bbox = bbox_2154
    return list(layer.getFeatures(QgsFeatureRequest().setFilterRect(filter_bbox)))


def _geojson_to_layer(geojson_dict, name, temp_files):
    fd, tmp_path = tempfile.mkstemp(suffix='.geojson')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(geojson_dict, f)
    except Exception:
        os.unlink(tmp_path)
        raise
    if temp_files is not None:
        temp_files.append(tmp_path)
    layer = QgsVectorLayer(tmp_path, name, 'ogr')
    if not layer.isValid():
        raise IOError(f'GeoJSON invalide pour {name}')
    return layer
