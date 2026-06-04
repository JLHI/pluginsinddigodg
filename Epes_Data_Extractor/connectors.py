# -*- coding: utf-8 -*-
import csv
import io
import os
import re
import json
import tempfile
import threading
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

from .network import http_get_sync, http_get_bytes, http_get_cas_auth


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
            api_var = conn.get('api_key_var')
            if api_var and api_var not in seen:
                seen.add(api_var)
                scope = QgsExpressionContextUtils.globalScope()
                if not scope.variable(api_var):
                    missing.append(
                        f'Variable QGIS manquante : "{api_var}" '
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
    msg = 'PostGIS invalide'
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
        msg = f"PostGIS invalide"
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

    Si 'geom_field' est défini dans conn, utilise une URI SQL avec ST_Intersects
    (approche BD TOPO Extractor) qui génère un filtre OGC fes:Intersects + pagination
    automatique COUNT=5000 côté provider QGIS — plus rapide et complet que BBOX.

    Le provider QGIS natif échoue sur certains services qui retournent du GML 3.2
    avec des namespaces non standard (ex. SANDRE/sa:). Les fallbacks HTTP téléchargent
    la couche complète et filtrent localement par bbox.
    """
    conn = src['conn']
    base_url = conn['base_url']
    typename = conn['typename']
    version = conn.get('version', 'auto')
    srsname = conn.get('srsname', 'EPSG:2154')
    cql_filter = conn.get('cql_filter', '')
    skip_native = conn.get('skip_native', False)
    skip_geojson = conn.get('skip_geojson', False)
    bbox_param_name = conn.get('bbox_param', 'BBOX')   # MapServer WFS 1.1.0 → 'boundedBy'
    geom_field = conn.get('geom_field', '')
    ver_str = '2.0.0' if version == 'auto' else version

    # --- Chemin SQL ST_Intersects (BD TOPO Extractor style) ---
    # Génère fes:Intersects + pagination COUNT=5000 via le provider QGIS natif.
    if geom_field and not skip_native:
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        tr = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem('EPSG:2154'), wgs84, QgsProject.instance()
        )
        bb = tr.transformBoundingBox(bbox_2154)
        sql = (
            f'SELECT * FROM "{typename}" as t1 '
            f'WHERE ST_Intersects(t1.{geom_field}, '
            f"ST_GeometryFromText('Polygon (("
            f"{bb.xMinimum()} {bb.yMinimum()}, "
            f"{bb.xMaximum()} {bb.yMinimum()}, "
            f"{bb.xMaximum()} {bb.yMaximum()}, "
            f"{bb.xMinimum()} {bb.yMaximum()}, "
            f"{bb.xMinimum()} {bb.yMinimum()}"
            f"))', 4326))"
        )
        wfs_uri = QgsDataSourceUri()
        wfs_uri.setParam('url', base_url)
        wfs_uri.setParam('version', version)
        wfs_uri.setParam('typename', typename)
        wfs_uri.setParam('table', '')
        wfs_uri.setParam('srsname', 'EPSG:4326')
        wfs_uri.setSql(sql)
        layer = QgsVectorLayer(wfs_uri.uri(False), src['name'], 'WFS')
        if layer.isValid():
            n = layer.featureCount()
            if feedback:
                feedback.pushInfo(f'    WFS SQL ST_Intersects : {n} entités ({typename})')
            if n == 0:
                return None
            return _build_memory(layer, list(layer.getFeatures()), src['name'])
        if feedback:
            feedback.pushInfo('    WFS SQL KO → essai HTTP GeoJSON…')

    # Nettoyer base_url des params WFS standards pour éviter les doublons dans les URLs HTTP
    _wfs_std = {'VERSION', 'SERVICE', 'REQUEST', 'version', 'service', 'request'}
    if '?' in base_url:
        _base, _qs = base_url.split('?', 1)
        _kept = '&'.join(p for p in _qs.split('&') if p.split('=')[0] not in _wfs_std)
        base_url_clean = f"{_base}?{_kept}" if _kept else _base
    else:
        base_url_clean = base_url

    sep = '&' if '?' in base_url_clean else '?'

    bbox_param = (
        f"{bbox_2154.xMinimum()},{bbox_2154.yMinimum()},"
        f"{bbox_2154.xMaximum()},{bbox_2154.yMaximum()},{srsname}"
    )

    cql_param = ''
    if cql_filter:
        bbox_cql = (
            f"{bbox_2154.xMinimum()},{bbox_2154.yMinimum()},"
            f"{bbox_2154.xMaximum()},{bbox_2154.yMaximum()}"
        )
        combined = f"({cql_filter}) AND BBOX(geom,{bbox_cql},'{srsname}')"
        cql_param = f"&CQL_FILTER={urllib.parse.quote(combined, safe='')}"

    bbox_native = (
        f"{bbox_2154.xMinimum()},{bbox_2154.yMinimum()},"
        f"{bbox_2154.xMaximum()},{bbox_2154.yMaximum()}"
    )
    if not skip_native and not geom_field:
        uri = (
            f"url='{base_url}' typename='{typename}' version='{version}' srsname='{srsname}'"
            f" restrictToRequestBBOX=1"
        )
        if cql_filter:
            uri += (
                f" sql=SELECT * FROM \"{typename}\""
                f" WHERE ({cql_filter})"
                f" AND BBOX(geom,{bbox_native},'{srsname}')"
            )
        layer = QgsVectorLayer(uri, src['name'], 'WFS')
        if layer.isValid():
            feats = _wfs_filter_bbox(layer, bbox_2154, feedback)
            if feedback:
                feedback.pushInfo(f'    WFS natif : {len(feats)} entités ({typename})')
            return _build_memory(layer, feats, src['name'])
        if feedback:
            feedback.pushInfo('    WFS provider natif KO → essai HTTP GeoJSON…')
    else:
        if feedback:
            feedback.pushInfo('    Natif ignoré (skip_native) → HTTP GeoJSON…')

    if not skip_geojson:
        geojson_base = (
            f"{base_url_clean}{sep}SERVICE=WFS&VERSION={ver_str}&REQUEST=GetFeature"
            f"&TYPENAME={typename}&SRSNAME={srsname}&outputFormat=application/json"
            + (f"&{bbox_param_name}={bbox_param}" if not cql_filter else '')
            + cql_param
        )
        try:
            all_features = []
            start = 0
            page_size = None
            while True:
                url_page = geojson_base + (f"&STARTINDEX={start}" if start > 0 else '')
                txt = http_get_sync(url_page, feedback=feedback)
                geojson = json.loads(txt)
                if geojson.get('type') not in ('FeatureCollection', 'Feature'):
                    break
                page_feats = geojson.get('features', [])
                all_features.extend(page_feats)
                n_returned = len(page_feats)
                if page_size is None:
                    page_size = n_returned
                n_matched = geojson.get('numberMatched', None)
                if n_matched is not None and n_matched != 'unknown':
                    if len(all_features) >= int(n_matched):
                        break
                if n_returned < page_size or n_returned == 0:
                    break
                start += n_returned
            if feedback:
                feedback.pushInfo(f'    WFS GeoJSON : {len(all_features)} entités')
            merged = {'type': 'FeatureCollection', 'features': all_features}
            layer = _geojson_to_layer(merged, src['name'], temp_files)
            feats = _wfs_filter_bbox(layer, bbox_2154, feedback)
            return _build_memory(layer, feats, src['name'])
        except Exception as e_geojson:
            if feedback:
                feedback.pushInfo(f'    HTTP GeoJSON KO : {e_geojson}')

    if feedback:
        feedback.pushInfo('    Essai HTTP GML brut…')
        feedback.pushInfo(
            f'    Emprise : x={bbox_2154.xMinimum():.0f}–{bbox_2154.xMaximum():.0f} '
            f'y={bbox_2154.yMinimum():.0f}–{bbox_2154.yMaximum():.0f} ({srsname})'
        )

    gml_url = (
        f"{base_url_clean}{sep}SERVICE=WFS&VERSION={ver_str}&REQUEST=GetFeature"
        f"&TYPENAME={typename}&SRSNAME={srsname}"
        + (f"&{bbox_param_name}={bbox_param}" if not cql_filter else '')
        + cql_param
    )
    # Bytes bruts : préserve l'encodage d'origine (MapServer sert souvent ISO-8859-1).
    # OGR/libxml2 lit la déclaration XML encoding= et décode correctement.
    raw_gml = http_get_bytes(gml_url, feedback=feedback)
    # Supprimer schemaLocation (bytes) pour éviter qu'OGR contacte des serveurs internes
    raw_gml = re.sub(rb'\s*xsi:schemaLocation=["\'][^"\']*["\']', b'', raw_gml)

    fd, tmp_path = tempfile.mkstemp(suffix='.gml')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw_gml)
    except Exception:
        os.unlink(tmp_path)
        raise
    if temp_files is not None:
        temp_files.append(tmp_path)

    # Décoder pour analyse (détection namespace, champs, featureMember)
    enc_match = re.search(rb'encoding=["\']([^"\']+)["\']', raw_gml[:500])
    xml_encoding = enc_match.group(1).decode('ascii') if enc_match else 'utf-8'
    txt_gml = raw_gml.decode(xml_encoding, errors='replace')

    # Pour les GML MapServer (xmlns:ms), créer un fichier .gfs décrivant géométrie ET champs
    # attributaires. Sans PropertyDefn explicites, OGR ignore les champs namespaced.
    if 'xmlns:ms="http://mapserver.gis.umn.edu/mapserver"' in txt_gml:
        import xml.etree.ElementTree as ET
        attr_fields = []
        try:
            root_gml = ET.fromstring(txt_gml.encode('utf-8'))
            # Chercher le premier élément feature (local name = typename)
            for elem in root_gml.iter():
                local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
                if local == typename:
                    for child in elem:
                        child_local = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                        if child_local not in ('msGeometry', 'boundedBy', 'location'):
                            attr_fields.append(child_local)
                    break
        except Exception:
            pass

        prop_defns = ''.join(
            f'    <PropertyDefn>\n'
            f'      <Name>{f}</Name>\n'
            f'      <ElementPath>{f}</ElementPath>\n'
            f'      <Type>String</Type>\n'
            f'    </PropertyDefn>\n'
            for f in attr_fields
        )
        gfs_content = (
            '<GMLFeatureClassList>\n'
            '  <GMLFeatureClass>\n'
            f'    <Name>{typename}</Name>\n'
            f'    <ElementPath>{typename}</ElementPath>\n'
            f'    <SRSName>{srsname}</SRSName>\n'
            '    <GeomPropertyDefn>\n'
            '      <Name>msGeometry</Name>\n'
            '      <ElementPath>msGeometry</ElementPath>\n'
            '    </GeomPropertyDefn>\n'
            + prop_defns +
            '  </GMLFeatureClass>\n'
            '</GMLFeatureClassList>\n'
        )
        gfs_path = tmp_path[:-4] + '.gfs'
        try:
            with open(gfs_path, 'w', encoding='utf-8') as gf:
                gf.write(gfs_content)
            if temp_files is not None:
                temp_files.append(gfs_path)
        except Exception:
            pass

    layer = QgsVectorLayer(tmp_path, src['name'], 'ogr')
    if not layer.isValid():
        # FeatureCollection vide (0 entité dans la zone) : OGR ne peut pas déduire
        # le schema sans feature ni XSD → pas une erreur, juste aucune donnée ici
        if 'featureMember' not in txt_gml:
            if feedback:
                feedback.pushInfo(f'    WFS GML : 0 entité dans la zone ({typename})')
            return None
        raise IOError(f"WFS invalide (GML) : {typename} sur {base_url}")

    feats = _wfs_filter_bbox(layer, bbox_2154, feedback)
    if feedback:
        feedback.pushInfo(f'    WFS GML : {len(feats)} entités ({typename})')

    # Layer valide mais vide avec type géométrique inconnu (GML sans entité + .gfs)
    if not feats and layer.wkbType() in (QgsWkbTypes.Unknown, QgsWkbTypes.NoGeometry):
        return None

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

    extra_headers = {}
    api_key_var = conn.get('api_key_var')
    if api_key_var:
        from qgis.core import QgsExpressionContextUtils
        api_key = QgsExpressionContextUtils.globalScope().variable(api_key_var) or ''
        if not api_key:
            raise IOError(
                f"Clé API manquante pour '{src['name']}'. "
                f"Définir la variable QGIS \"{api_key_var}\" "
                f"(Réglages → Options → Variables)."
            )
        extra_headers['Authorization'] = f'Bearer {api_key}'

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
        txt = http_get_sync(url, feedback=feedback, headers=extra_headers or None)

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


# ---------- API DATAtourisme v1 ----------

def fetch_from_datatourisme(src, centroid_pt_wgs84, dist_km, feedback=None, temp_files=None, bbox_2154=None):
    """Récupère des objets depuis l'API DATAtourisme v1 avec pagination.

    layer_geometry='point' (défaut) → Point depuis isLocatedAt.geo.
    layer_geometry='line'           → LineString/MultiLineString depuis geoJson (itinéraires).
    """
    conn = src['conn']
    base_url = conn.get('base_url', 'https://api.datatourisme.fr/v1/catalog')
    layer_geometry = conn.get('layer_geometry', 'point')

    api_key_var = conn.get('api_key_var', '')
    from qgis.core import QgsExpressionContextUtils
    api_key = QgsExpressionContextUtils.globalScope().variable(api_key_var) or '' if api_key_var else ''
    if not api_key:
        raise IOError(
            f"Clé API manquante pour '{src['name']}'. "
            f"Définir la variable QGIS \"{api_key_var}\" "
            f"(Réglages → Options → Variables)."
        )
    headers = {'X-API-Key': api_key}

    geo_param = f"{centroid_pt_wgs84.y():.6f},{centroid_pt_wgs84.x():.6f},{dist_km:.1f}km"
    sep = '&' if '?' in base_url else '?'
    page_size = 250
    all_objects = []
    page = 1

    type_filter = conn.get('type_filter') or []
    filter_param = ''
    if type_filter:
        types_str = ','.join(type_filter) if isinstance(type_filter, list) else type_filter
        filter_param = f'&filters=type[in]={urllib.parse.quote(types_str, safe="")}'

    fields = (
        'uuid,label,type,geoJson,isLocatedAt'
        if layer_geometry == 'line'
        else 'uuid,label,type,isLocatedAt,hasDescription,contact'
    )

    while True:
        url = (
            f"{base_url}{sep}geo_distance={geo_param}"
            f"&page_size={page_size}&page={page}"
            f"&fields={fields}"
            f"{filter_param}"
        )
        if feedback:
            feedback.pushInfo(f'    DATAtourisme page {page} : {url}')
        txt = http_get_sync(url, feedback=feedback, headers=headers)
        data = json.loads(txt)
        objects = data.get('objects', [])
        all_objects.extend(objects)
        total = data.get('meta', {}).get('total', len(all_objects))
        if feedback:
            feedback.pushInfo(f'    Page {page} : {len(objects)} objets (total serveur : {total})')
        if len(objects) < page_size or len(all_objects) >= total:
            break
        page += 1

    if feedback:
        feedback.pushInfo(f'    DATAtourisme : {len(all_objects)} objets récupérés')
        all_types = set()
        for obj in all_objects:
            t = obj.get('type') or []
            all_types.update(t if isinstance(t, list) else [t])
        if all_types:
            feedback.pushInfo(f'    Types distincts : {", ".join(sorted(all_types))}')

    features = []
    skipped = 0
    for obj in all_objects:
        label = obj.get('label') or {}
        name = (
            label.get('fr') or label.get('en') or next(iter(label.values()), '')
            if isinstance(label, dict) else str(label)
        )
        types = obj.get('type') or []
        props = {
            'uuid': obj.get('uuid', ''),
            'nom': name,
            'type': ', '.join(types) if isinstance(types, list) else str(types),
        }

        if layer_geometry == 'line':
            geom = _extract_line_geometry(obj.get('geoJson'))
            if geom is None:
                skipped += 1
                continue
            features.append({'type': 'Feature', 'geometry': geom, 'properties': props})
        else:
            lat = lon = None
            located = obj.get('isLocatedAt') or []
            if isinstance(located, dict):
                located = [located]
            for loc in located:
                geo = loc.get('geo') or {}
                lat = geo.get('latitude') or geo.get('lat')
                lon = geo.get('longitude') or geo.get('lon') or geo.get('lng')
                if lat is not None and lon is not None:
                    break
            if lat is None or lon is None:
                skipped += 1
                continue
            features.append({
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [float(lon), float(lat)]},
                'properties': props,
            })

    if feedback:
        feedback.pushInfo(f'    DATAtourisme : {len(features)} objets géolocalisés, {skipped} sans géométrie ignorés')

    geojson = {'type': 'FeatureCollection', 'features': features}
    layer = _geojson_to_layer(geojson, src['name'], temp_files)

    if bbox_2154 is None:
        return layer

    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:2154'), wgs84, QgsProject.instance())
    bb_wgs84 = tr.transformBoundingBox(bbox_2154)
    bbox_geom = QgsGeometry.fromRect(bb_wgs84)
    feats = [f for f in layer.getFeatures() if not f.geometry().isNull() and f.geometry().intersects(bbox_geom)]
    if feedback:
        feedback.pushInfo(f'    DATAtourisme après filtre bbox : {len(feats)} objets')
    return _build_memory(layer, feats, src['name'], crs='EPSG:4326')


def _extract_line_geometry(raw):
    """Extrait une géométrie GeoJSON linéaire depuis le champ geoJson d'un objet DATAtourisme."""
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None
    gtype = raw.get('type', '')
    if gtype in ('LineString', 'MultiLineString'):
        return raw
    if gtype == 'Feature':
        g = raw.get('geometry') or {}
        if g.get('type') in ('LineString', 'MultiLineString'):
            return g
    if gtype == 'FeatureCollection':
        for feat in raw.get('features', []):
            g = feat.get('geometry') or {}
            if g.get('type') in ('LineString', 'MultiLineString'):
                return g
    return None


# ---------- Overpass simple (UNESCO, zones patrimoniales) ----------

def fetch_from_overpass(src, bbox_2154, feedback=None, temp_files=None):
    """Source Overpass autonome : retourne une couche de polygones ou de lignes.

    conn attendu :
      overpass_query  : ex. 'relation["heritage"="1"]["heritage:operator"="whc"]'
      geom_type       : 'polygon' (defaut) ou 'line'
    """
    conn = src['conn']
    query = conn['overpass_query']
    geom_type = conn.get('geom_type', 'polygon')

    feats = _fetch_overpass_features(query, bbox_2154, feedback, geom_type=geom_type)
    if feedback:
        feedback.pushInfo(f'    {len(feats)} entites recuperees')

    geojson = {'type': 'FeatureCollection', 'features': feats}
    layer = _geojson_to_layer(geojson, src['name'], temp_files)

    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:2154'), wgs84, QgsProject.instance())
    bb_wgs84 = tr.transformBoundingBox(bbox_2154)
    bbox_geom = QgsGeometry.fromRect(bb_wgs84)
    filtered = [f for f in layer.getFeatures() if not f.geometry().isNull() and f.geometry().intersects(bbox_geom)]
    if feedback:
        feedback.pushInfo(f'    Apres filtre bbox : {len(filtered)} entites')
    return _build_memory(layer, filtered, src['name'], crs='EPSG:4326')


# ---------- Itinéraires fusionnés (OSM Overpass + WFS IGN) ----------

def _fetch_overpass_features(query, bbox_2154, feedback=None, geom_type='line'):
    """Interroge Overpass et retourne des features GeoJSON depuis des relations OSM.

    geom_type='line'    -> MultiLineString (itineraires)
    geom_type='polygon' -> MultiPolygon (sites, zones patrimoniales...)
    """
    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:2154'), wgs84, QgsProject.instance())
    bb = tr.transformBoundingBox(bbox_2154)
    bbox_str = f"{bb.yMinimum():.6f},{bb.xMinimum():.6f},{bb.yMaximum():.6f},{bb.xMaximum():.6f}"
    full_query = f'[out:json][bbox:{bbox_str}];({query};);out geom;'
    url = 'https://overpass-api.de/api/interpreter?data=' + urllib.parse.quote(full_query, safe='')
    if feedback:
        feedback.pushInfo(f'    Overpass query : {full_query[:120]}...')
    txt = http_get_sync(url, timeout_ms=120000, feedback=feedback)
    data = json.loads(txt)
    features = []
    for element in data.get('elements', []):
        if element.get('type') != 'relation':
            continue
        tags = element.get('tags', {})
        props = {
            'osm_id': str(element.get('id', '')),
            'nom': tags.get('name', ''),
            'ref': tags.get('ref', ''),
            'network': tags.get('network', ''),
            'route': tags.get('route', ''),
            'source': 'osm',
            'route_type': '',
        }
        if geom_type == 'polygon':
            outer_rings, inner_rings = [], []
            for member in element.get('members', []):
                if member.get('type') != 'way' or 'geometry' not in member:
                    continue
                coords = [[pt['lon'], pt['lat']] for pt in member['geometry']]
                if len(coords) < 3:
                    continue
                if coords[0] != coords[-1]:
                    coords.append(coords[0])
                (inner_rings if member.get('role') == 'inner' else outer_rings).append(coords)
            if not outer_rings:
                continue
            polygons = [[ring] for ring in outer_rings]
            for inner in inner_rings:
                polygons[0].append(inner)
            geom = {'type': 'MultiPolygon', 'coordinates': polygons}
        else:
            coords_list = []
            for member in element.get('members', []):
                if member.get('type') == 'way' and 'geometry' in member:
                    coords = [[pt['lon'], pt['lat']] for pt in member['geometry']]
                    if len(coords) >= 2:
                        coords_list.append(coords)
            if not coords_list:
                continue
            geom = {'type': 'MultiLineString', 'coordinates': coords_list}
        features.append({'type': 'Feature', 'geometry': geom, 'properties': props})
    if feedback:
        feedback.pushInfo(f'    Overpass : {len(features)} relations ({geom_type})')
    return features


def fetch_itineraires_merged(src, bbox_2154, feedback=None, temp_files=None):
    """Fusionne des itinéraires depuis WFS IGN et/ou Overpass OSM.

    Déduplication par ref normalisée : IGN prime sur OSM.
    Config conn attendue :
      wfs_typename    (optionnel) : ex. 'BDTOPO_V3:itineraire_autre'
      wfs_base_url    (optionnel) : défaut data.geopf.fr
      overpass_query  (optionnel) : ex. 'relation["route"~"hiking|foot"]'
    """
    conn = src['conn']
    features_by_ref = {}   # ref_normalisée → feature (PostGIS > WFS > OSM)
    features_no_ref = []

    # 1. PostGIS (optionnel, prioritaire)
    postgis_conn = conn.get('postgis')
    if postgis_conn:
        pg_src = {'name': src['name'], 'conn': postgis_conn}
        try:
            pg_layer = fetch_from_postgis(pg_src, bbox_2154, feedback)
            field_names = [f.name().lower() for f in pg_layer.fields()]
            ref_field = next((f for f in field_names if 'ref' in f), None)
            nom_field = next((f for f in field_names if 'nom' in f or 'name' in f), None)
            n_pg = 0
            for feat in pg_layer.getFeatures():
                ref = str(feat[ref_field] or '') if ref_field else ''
                nom = str(feat[nom_field] or '') if nom_field else ''
                key = (ref or nom).strip().upper()
                geom = feat.geometry()
                if geom.isNull():
                    continue
                props = {'source': 'ign_postgis', 'ref': ref, 'nom': nom, 'route_type': '', 'network': '', 'route': '', 'osm_id': ''}
                f = {'type': 'Feature', 'geometry': json.loads(geom.asJson()), 'properties': props}
                if key:
                    features_by_ref[key] = f
                else:
                    features_no_ref.append(f)
                n_pg += 1
            if feedback:
                feedback.pushInfo(f'    PostGIS : {n_pg} entités')
        except Exception as e:
            if feedback:
                feedback.pushInfo(f'    PostGIS non disponible : {e}')

    # 2. WFS IGN
    wfs_typename = conn.get('wfs_typename')
    if wfs_typename:
        wfs_src = {
            'name': src['name'],
            'conn': {
                'base_url': conn.get('wfs_base_url', 'https://data.geopf.fr/wfs/ows?VERSION=2.0.0'),
                'typename': wfs_typename,
                'srsname': 'EPSG:2154',
            }
        }
        try:
            wfs_layer = fetch_from_wfs(wfs_src, bbox_2154, feedback, temp_files)
            field_names = [f.name().lower() for f in wfs_layer.fields()]
            if feedback:
                feedback.pushInfo(f'    IGN champs disponibles : {field_names}')
            ref_field = next((f for f in field_names if 'ref' in f), None)
            nom_field = next((f for f in field_names if 'nom' in f or 'name' in f), None)
            nature_field = 'nature' if 'nature' in field_names else None
            n_ign = 0
            for feat in wfs_layer.getFeatures():
                ref = str(feat[ref_field] or '') if ref_field else ''
                nom = str(feat[nom_field] or '') if nom_field else ''
                key = (ref or nom).strip().upper()
                geom = feat.geometry()
                if geom.isNull():
                    continue
                props = {
                    'source': 'ign',
                    'ref': ref,
                    'nom': nom,
                    'route_type': str(feat[nature_field] or '') if nature_field else '',
                    'network': '',
                    'route': '',
                    'osm_id': '',
                }
                f = {'type': 'Feature', 'geometry': json.loads(geom.asJson()), 'properties': props}
                if key:
                    features_by_ref[key] = f
                else:
                    features_no_ref.append(f)
                n_ign += 1
            if feedback:
                feedback.pushInfo(f'    IGN WFS : {n_ign} entités')
        except Exception as e:
            if feedback:
                feedback.pushWarning(f'    IGN WFS KO : {e}')

    # 2. Overpass OSM
    overpass_query = conn.get('overpass_query', '')
    if overpass_query:
        osm_feats = _fetch_overpass_features(overpass_query, bbox_2154, feedback)
        n_added = n_dedup = 0
        for feat in osm_feats:
            ref = feat['properties'].get('ref', '').strip().upper()
            nom = feat['properties'].get('nom', '').strip().upper()
            key = ref or nom
            if key and key in features_by_ref:
                n_dedup += 1
                continue
            if key:
                features_by_ref[key] = feat
            else:
                features_no_ref.append(feat)
            n_added += 1
        if feedback:
            feedback.pushInfo(f'    OSM : {n_added} ajoutés, {n_dedup} doublons ignorés (ref/nom identique IGN)')

    all_features = list(features_by_ref.values()) + features_no_ref
    if feedback:
        feedback.pushInfo(f'    Total fusionné : {len(all_features)} itinéraires')

    geojson = {'type': 'FeatureCollection', 'features': all_features}
    layer = _geojson_to_layer(geojson, src['name'], temp_files)

    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:2154'), wgs84, QgsProject.instance())
    bb_wgs84 = tr.transformBoundingBox(bbox_2154)
    bbox_geom = QgsGeometry.fromRect(bb_wgs84)
    feats = [f for f in layer.getFeatures() if not f.geometry().isNull() and f.geometry().intersects(bbox_geom)]
    if feedback:
        feedback.pushInfo(f'    Après filtre bbox : {len(feats)} itinéraires')
    return _build_memory(layer, feats, src['name'], crs='EPSG:4326')


# ---------- Reprojection ----------

def reproject_layer(layer, target_authid='EPSG:2154'):
    """Reprojecte une couche mémoire vers la CRS cible. Retourne la couche inchangée si déjà dans cette CRS."""
    if not layer or not layer.isValid():
        return layer
    src_crs = layer.crs()
    if not src_crs.isValid() or src_crs.authid() == target_authid:
        return layer
    target_crs = QgsCoordinateReferenceSystem(target_authid)
    tr = QgsCoordinateTransform(src_crs, target_crs, QgsProject.instance())
    geom_type = QgsWkbTypes.displayString(layer.wkbType())
    mem = QgsVectorLayer(f"{geom_type}?crs={target_authid}", layer.name(), 'memory')
    prov = mem.dataProvider()
    prov.addAttributes(layer.fields())
    mem.updateFields()
    feats = []
    for feat in layer.getFeatures():
        if feat.geometry().isNull():
            feats.append(feat)
            continue
        f = feat.__class__()
        f.setFields(feat.fields())
        f.setAttributes(feat.attributes())
        geom = QgsGeometry(feat.geometry())
        geom.transform(tr)
        f.setGeometry(geom)
        feats.append(f)
    if feats:
        prov.addFeatures(feats)
    return mem


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


# ---------- ArcGIS Feature Service ----------

def fetch_from_arcgis(src, bbox_2154, feedback=None, temp_files=None):
    """Interroge un ArcGIS FeatureServer avec filtre spatial BBOX et pagination.

    conn attendu :
      url          : URL de la couche  (ex. .../FeatureServer/0)
      where        : filtre attributaire optionnel (ex. "Type_Iti=1")
      out_sr       : EPSG de sortie (défaut 4326)
      page_size    : nb entités par page (défaut 2000)
    """
    conn = src['conn']
    layer_url = conn['url'].rstrip('/')
    where = conn.get('where', '1=1')
    out_sr = conn.get('out_sr', 4326)
    page_size = int(conn.get('page_size', 2000))

    xmin = bbox_2154.xMinimum()
    xmax = bbox_2154.xMaximum()
    ymin = bbox_2154.yMinimum()
    ymax = bbox_2154.yMaximum()

    geometry_param = (
        f'{{"xmin":{xmin},"ymin":{ymin},"xmax":{xmax},"ymax":{ymax},'
        f'"spatialReference":{{"wkid":2154}}}}'
    )

    base_params = (
        f"where={urllib.parse.quote(where)}"
        f"&geometry={urllib.parse.quote(geometry_param)}"
        f"&geometryType=esriGeometryEnvelope"
        f"&spatialRel=esriSpatialRelIntersects"
        f"&inSR=2154"
        f"&outSR={out_sr}"
        f"&outFields=*"
        f"&f=geojson"
        f"&resultRecordCount={page_size}"
    )

    all_features = []
    offset = 0
    while True:
        url = f"{layer_url}/query?{base_params}&resultOffset={offset}"
        txt = http_get_sync(url, feedback=feedback)
        geojson = json.loads(txt)
        if geojson.get('type') not in ('FeatureCollection', 'Feature'):
            break
        page_feats = geojson.get('features', [])
        all_features.extend(page_feats)
        if feedback:
            feedback.pushInfo(f'    ArcGIS page offset={offset} : {len(page_feats)} entités')
        if len(page_feats) < page_size:
            break
        offset += page_size

    if feedback:
        feedback.pushInfo(f'    ArcGIS : {len(all_features)} entités au total')

    merged = {'type': 'FeatureCollection', 'features': all_features}
    layer = _geojson_to_layer(merged, src['name'], temp_files)

    crs_str = f'EPSG:{out_sr}'
    if out_sr == 4326:
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:2154'), wgs84, QgsProject.instance())
        bb = tr.transformBoundingBox(bbox_2154)
        bbox_geom = QgsGeometry.fromRect(bb)
    else:
        bbox_geom = QgsGeometry.fromRect(bbox_2154)

    feats = [f for f in layer.getFeatures() if not f.geometry().isNull() and f.geometry().intersects(bbox_geom)]
    if feedback:
        feedback.pushInfo(f'    ArcGIS après filtre bbox : {len(feats)} entités')
    return _build_memory(layer, feats, src['name'], crs=crs_str)


# ---------- CSV avec colonnes lat/lon ----------

def fetch_from_csv_point(src, bbox_2154, feedback=None, temp_files=None):
    """Télécharge un CSV avec colonnes lat et lon séparées, retourne une couche Point filtrée par bbox."""
    conn = src['conn']
    url = conn['url']
    lat_field = conn['lat_field']
    lon_field = conn['lon_field']
    sep = conn.get('sep', ',')

    txt = http_get_sync(url, feedback=feedback)
    reader = csv.DictReader(io.StringIO(txt), delimiter=sep)
    features = []
    skipped = 0
    for row in reader:
        try:
            lat = float(row[lat_field].replace(',', '.'))
            lon = float(row[lon_field].replace(',', '.'))
        except (ValueError, KeyError, TypeError):
            skipped += 1
            continue
        props = {k: v for k, v in row.items() if k not in (lat_field, lon_field)}
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
            'properties': props,
        })

    if feedback:
        feedback.pushInfo(f'    CSV : {len(features)} points ({skipped} sans coordonnées ignorés)')

    geojson = {'type': 'FeatureCollection', 'features': features}
    layer = _geojson_to_layer(geojson, src['name'], temp_files)

    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:2154'), wgs84, QgsProject.instance())
    bb_wgs84 = tr.transformBoundingBox(bbox_2154)
    bbox_geom = QgsGeometry.fromRect(bb_wgs84)
    feats = [f for f in layer.getFeatures() if not f.geometry().isNull() and f.geometry().intersects(bbox_geom)]

    if feedback:
        feedback.pushInfo(f'    CSV après filtre bbox : {len(feats)} entités')

    return _build_memory(layer, feats, src['name'], crs='EPSG:4326')


# ---------- Atlas du Patrimoine – découverte dynamique par BBOX ----------

_adp_rss_cache = {}  # (xmin,ymin,xmax,ymax) → liste d'items {map_path, typename, title, categories}


def _adp_rss_items(bbox_2154, feedback=None):
    """Retourne la liste des items du RSS GeoSource pour la BBOX donnée, avec cache par run."""
    import xml.etree.ElementTree as ET
    global _adp_rss_cache

    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:2154'), wgs84, QgsProject.instance())
    bb = tr.transformBoundingBox(bbox_2154)
    cache_key = (round(bb.xMinimum(), 4), round(bb.yMinimum(), 4),
                 round(bb.xMaximum(), 4), round(bb.yMaximum(), 4))

    if cache_key in _adp_rss_cache:
        return _adp_rss_cache[cache_key]

    rss_url = (
        'http://atlas.patrimoines.culture.fr/geosource/srv/fr/rss.search'
        f'?from=1&to=50&sortby=MCC&pertinentScaleLevel=1&georss=simple'
        f'&westBL={bb.xMinimum():.6f}&eastBL={bb.xMaximum():.6f}'
        f'&southBL={bb.yMinimum():.6f}&northBL={bb.yMaximum():.6f}'
        f'&geoForm=BBOX&themekeywords=Protection'
    )
    if feedback:
        feedback.pushInfo(f'    ADP GeoSource RSS → {rss_url}')

    try:
        txt = http_get_sync(rss_url, feedback=feedback)
        root = ET.fromstring(txt.encode('utf-8'))
    except Exception as e:
        if feedback:
            feedback.pushWarning(f'    ADP GeoSource KO : {e}')
        _adp_rss_cache[cache_key] = []
        return []

    items = []
    for item in root.findall('.//item'):
        cats = [c.text or '' for c in item.findall('category')]
        enclosure = item.find('enclosure')
        if enclosure is None:
            continue
        wms_url = enclosure.get('url', '')
        parsed = urllib.parse.urlparse(wms_url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        map_path = params.get('map') or params.get('MAP')
        if not map_path:
            continue
        md_id = map_path.rstrip('/').split('/')[-1].replace('.map', '')
        title = (item.findtext('title') or '').strip()
        items.append({'map_path': map_path, 'typename': md_id, 'title': title, 'categories': cats})

    _adp_rss_cache[cache_key] = items
    return items


def fetch_from_adp_dynamic(src, bbox_2154, feedback=None, temp_files=None):
    """Découvre dynamiquement les MAP files atlas.patrimoines via GeoSource RSS (avec cache),
    filtre par catégorie, appelle les WFS correspondants et fusionne les résultats.
    """
    conn = src['conn']
    category_filter = conn.get('category_filter', [])

    all_items = _adp_rss_items(bbox_2154, feedback)
    matched = [m for m in all_items if any(f in m['categories'] for f in category_filter)]

    if not matched:
        if feedback:
            feedback.pushInfo('    ADP dynamique : aucun service trouvé dans la zone')
        return None

    if feedback:
        titles = ', '.join(m['title'] for m in matched)
        feedback.pushInfo(f'    ADP dynamique : {len(matched)} service(s) trouvé(s) — {titles}')

    all_feats = []
    ref_layer = None
    for m in matched:
        wfs_src = {
            'name': src['name'],
            'conn': {
                'base_url': f"http://atlas.patrimoines.culture.fr/cgi-bin/mapserv?MAP={m['map_path']}",
                'typename': m['typename'],
                'version': '1.1.0',
                'skip_native': True,
                'skip_geojson': True,
                'bbox_param': 'boundedBy',
            }
        }
        try:
            layer = fetch_from_wfs(wfs_src, bbox_2154, feedback, temp_files)
            if layer is None:
                continue
            feats = list(layer.getFeatures())
            if feats:
                all_feats.extend(feats)
                if ref_layer is None:
                    ref_layer = layer
        except Exception as e:
            if feedback:
                feedback.pushWarning(f'    ADP WFS KO ({m["typename"]}) : {e}')

    if ref_layer is None or not all_feats:
        return None

    poly_layer = _build_memory(ref_layer, all_feats, src['name'])

    if not conn.get('centroid', False):
        return poly_layer

    # Convertir les polygones en centroïdes
    crs = poly_layer.crs().authid() or 'EPSG:2154'
    pt_layer = QgsVectorLayer(f'Point?crs={crs}', src['name'], 'memory')
    prov = pt_layer.dataProvider()
    prov.addAttributes(poly_layer.fields())
    pt_layer.updateFields()
    pt_feats = []
    for feat in poly_layer.getFeatures():
        if feat.geometry().isNull():
            continue
        f = feat.__class__()
        f.setFields(feat.fields())
        f.setAttributes(feat.attributes())
        f.setGeometry(feat.geometry().centroid())
        pt_feats.append(f)
    if pt_feats:
        prov.addFeatures(pt_feats)
    if feedback:
        feedback.pushInfo(f'    Centroïdes : {len(pt_feats)} points générés')
    return pt_layer


# ---------- Cache MNT partagé (évite de télécharger 2 fois si MNT + pente cochés) ----------

_mnt_cache: dict = {}        # key → {'event': Event, 'path': str|None}
_mnt_cache_lock = threading.Lock()
_mnt_cache_files: list = []  # chemins gérés par le cache (nettoyés par clear_mnt_cache)


def clear_mnt_cache():
    """Vide le cache MNT et supprime les fichiers temporaires associés.
    À appeler en début et en fin de chaque run dans processAlgorithm.
    """
    global _mnt_cache, _mnt_cache_files
    with _mnt_cache_lock:
        for p in _mnt_cache_files:
            try:
                os.unlink(p)
            except Exception:
                pass
        _mnt_cache.clear()
        _mnt_cache_files.clear()


def _get_mnt_cached(conn, bbox_2154, feedback=None):
    """Retourne le chemin du MNT téléchargé pour cette BBOX+params.

    - Premier appel : télécharge, met en cache, retourne le chemin.
    - Appels suivants (même BBOX) : attend si download en cours, retourne le cache.
    Le fichier est géré par _mnt_cache_files (pas par thread_temp du caller).
    """
    key = (
        round(bbox_2154.xMinimum()), round(bbox_2154.yMinimum()),
        round(bbox_2154.xMaximum()), round(bbox_2154.yMaximum()),
        conn.get('wms_url', ''), conn.get('layer', ''), conn.get('resolution', 5)
    )

    with _mnt_cache_lock:
        if key in _mnt_cache:
            entry = _mnt_cache[key]
            need_download = False
        else:
            entry = {'event': threading.Event(), 'path': None}
            _mnt_cache[key] = entry
            need_download = True

    if need_download:
        # Ce thread télécharge
        raster_src = {'name': 'MNT (cache)', 'conn': conn}
        layer = fetch_raster_ign(raster_src, bbox_2154, feedback, None)
        path = layer.dataProvider().dataSourceUri()
        with _mnt_cache_lock:
            entry['path'] = path
            _mnt_cache_files.append(path)
        entry['event'].set()
        if feedback:
            feedback.pushInfo('    MNT téléchargé et mis en cache')
        return path
    else:
        # Attendre que le thread qui télécharge ait terminé (max 5 min)
        entry['event'].wait(timeout=300)
        path = entry['path']
        if path:
            if feedback:
                feedback.pushInfo('    MNT réutilisé depuis cache (pas de second téléchargement)')
            return path
        raise IOError('Timeout en attendant le MNT du cache')


# ---------- Pente > seuil (slope vectorisé depuis MNT WMS) ----------

def fetch_raster_slope(src, bbox_2154, feedback=None, temp_files=None, output_folder=None):
    """Calcule la carte de pente (degrés) depuis le MNT 5m sauvegardé (phase 2),
    ou le télécharge si non disponible (sélection pente seule sans alti).
    Retourne un QgsRasterLayer sur fichier .tif temporaire.

    conn attendu :
      dem_nomenclature : nom du fichier .tif MNT (défaut ign_rgealti_5m)
      dem_folder       : sous-dossier export du MNT (défaut 3-DATA RASTER)
      dem_wms_url      : URL WMS de secours
      dem_layer        : couche WMS de secours
      dem_resolution   : résolution de secours en m (défaut 5)
    """
    try:
        from osgeo import gdal
    except ImportError as e:
        raise IOError(f"GDAL Python non disponible pour le calcul de pente : {e}")

    conn = src['conn']

    # 1. Chercher le MNT sauvegardé sur disque (par la source alti de la phase 1)
    dem_path = None
    if output_folder:
        dem_folder = conn.get('dem_folder', '3-DATA RASTER')
        dem_nomenclature = conn.get('dem_nomenclature', 'ign_rgealti_5m')
        candidate = os.path.join(output_folder, dem_folder, f'{dem_nomenclature}.tif')
        if os.path.exists(candidate):
            dem_path = candidate
            if feedback:
                feedback.pushInfo(f'    MNT depuis fichier sauvegardé : {os.path.basename(candidate)}')

    if dem_path is None:
        mnt_conn = {
            'wms_url':    conn.get('dem_wms_url', 'https://data.geopf.fr/wms-r'),
            'layer':      conn.get('dem_layer', 'ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES'),
            'resolution': conn.get('dem_resolution', 5),
        }
        dem_path = _get_mnt_cached(mnt_conn, bbox_2154, feedback)

    # 2. Calculer la pente (degrés) avec GDAL DEMProcessing
    fd, slope_path = tempfile.mkstemp(suffix='_slope.tif')
    os.close(fd)
    if temp_files is not None:
        temp_files.append(slope_path)

    opts = gdal.DEMProcessingOptions(slopeFormat='degree', computeEdges=True)
    result_ds = gdal.DEMProcessing(slope_path, dem_path, 'slope', options=opts)
    result_ds = None  # flush et fermeture

    if feedback:
        feedback.pushInfo('    Carte de pente calculée (degrés)')

    from qgis.core import QgsRasterLayer
    layer = QgsRasterLayer(slope_path, src['name'])
    if not layer.isValid():
        raise IOError(f"Raster de pente invalide : {slope_path}")

    if feedback:
        feedback.pushInfo(f'    Raster pente : {layer.width()}×{layer.height()} px — OK')

    return layer


# ---------- Raster IGN WMS ----------

def fetch_raster_ign(src, bbox_2154, feedback=None, temp_files=None):
    """Télécharge un raster IGN via WMS GetMap (data.geopf.fr/wms-r).

    Utilise WMS 1.3.0 avec EPSG:4326 (lat,lon) comme confirmé par IGN.
    WIDTH/HEIGHT calculés depuis l'emprise EPSG:2154 pour respecter la résolution voulue.
    Cap à 8192 px par dimension (limite serveur IGN).
    Alimente le cache MNT partagé (_get_mnt_cached) pour éviter un double téléchargement
    si la source pente est aussi cochée.
    Retourne un QgsRasterLayer sur fichier temporaire .tif.
    """
    conn = src['conn']
    wms_url = conn.get('wms_url', 'https://data.geopf.fr/wms-r')
    layer_name = conn.get('layer', 'ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES')
    resolution = float(conn.get('resolution', 5))

    # Si le MNT est déjà en cache (téléchargé par la source pente en parallèle), le réutiliser
    cache_key = (
        round(bbox_2154.xMinimum()), round(bbox_2154.yMinimum()),
        round(bbox_2154.xMaximum()), round(bbox_2154.yMaximum()),
        wms_url, layer_name, resolution
    )
    with _mnt_cache_lock:
        cached_entry = _mnt_cache.get(cache_key)
    if cached_entry is not None:
        cached_entry['event'].wait(timeout=300)
        if cached_entry['path']:
            if feedback:
                feedback.pushInfo('    MNT réutilisé depuis cache (pas de second téléchargement)')
            from qgis.core import QgsRasterLayer
            return QgsRasterLayer(cached_entry['path'], src['name'])

    # Dimensions en pixels depuis l'emprise Lambert (mètres) → résolution exacte
    w_m = bbox_2154.xMaximum() - bbox_2154.xMinimum()
    h_m = bbox_2154.yMaximum() - bbox_2154.yMinimum()
    width  = max(1, int(round(w_m / resolution)))
    height = max(1, int(round(h_m / resolution)))

    # Convertir BBOX en WGS84 — WMS 1.3.0 + EPSG:4326 → ordre lat,lon
    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:2154'), wgs84, QgsProject.instance())
    bb = tr.transformBoundingBox(bbox_2154)

    def _wms_url(lat_min, lon_min, lat_max, lon_max, px_w, px_h):
        return (
            f"{wms_url}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap"
            f"&LAYERS={layer_name}&STYLES="
            f"&FORMAT=image/geotiff&CRS=EPSG:4326"
            f"&BBOX={lat_min},{lon_min},{lat_max},{lon_max}"
            f"&WIDTH={px_w}&HEIGHT={px_h}&EXCEPTIONS=text/xml"
        )

    def _download_tile(lat_min, lon_min, lat_max, lon_max, px_w, px_h, label=''):
        url = _wms_url(lat_min, lon_min, lat_max, lon_max, px_w, px_h)
        if feedback:
            feedback.pushInfo(f'    WMS {label}| {px_w}×{px_h} px (~{resolution}m)')
        raw = http_get_bytes(url, timeout_ms=900_000, feedback=feedback)
        if len(raw) < 4 or raw[:2] not in (b'II', b'MM'):
            preview = raw[:300].decode('utf-8', errors='replace')
            raise IOError(f"WMS : réponse non-TIFF ({len(raw)} o). Début : {preview}")
        fd, path = tempfile.mkstemp(suffix='.tif')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(raw)
        except Exception:
            os.unlink(path)
            raise
        if temp_files is not None:
            temp_files.append(path)
        return path

    # Tentative en une pièce ; si HTTP 400 (emprise trop grande), découpage 2×2
    lat_min, lon_min = bb.yMinimum(), bb.xMinimum()
    lat_max, lon_max = bb.yMaximum(), bb.xMaximum()
    try:
        tmp_path = _download_tile(lat_min, lon_min, lat_max, lon_max, width, height)
    except IOError as e:
        if 'HTTP 400' not in str(e):
            raise
        if feedback:
            feedback.pushWarning('    ⚠ HTTP 400 → découpage 2×2 tuiles (résolution conservée)')
        try:
            from osgeo import gdal
        except ImportError as ie:
            raise IOError(f"GDAL Python requis pour le tuilage : {ie}")

        mid_lat = (lat_min + lat_max) / 2
        mid_lon = (lon_min + lon_max) / 2
        hw, hh = max(1, width // 2), max(1, height // 2)
        # Ajuster la moitié haute pour absorber le pixel impair
        hw2, hh2 = width - hw, height - hh
        tile_specs = [
            (lat_min, lon_min, mid_lat, mid_lon, hw,  hh,  'SW '),
            (lat_min, mid_lon, mid_lat, lon_max, hw2, hh,  'SE '),
            (mid_lat, lon_min, lat_max, mid_lon, hw,  hh2, 'NW '),
            (mid_lat, mid_lon, lat_max, lon_max, hw2, hh2, 'NE '),
        ]
        tile_paths = [_download_tile(*spec) for spec in tile_specs]

        fd, tmp_path = tempfile.mkstemp(suffix='_merged.tif')
        os.close(fd)
        if temp_files is not None:
            temp_files.append(tmp_path)

        vrt = gdal.BuildVRT('/vsimem/ign_merge.vrt', tile_paths)
        if vrt is None:
            raise IOError("Échec BuildVRT pour la fusion des tuiles IGN")
        out_ds = gdal.Translate(tmp_path, vrt, format='GTiff')
        vrt = None          # fermer le VRT
        if out_ds is None:
            raise IOError("Échec Translate GDAL pour la fusion des tuiles IGN")
        out_ds = None       # flush et fermeture
        gdal.Unlink('/vsimem/ign_merge.vrt')
        if feedback:
            feedback.pushInfo(f'    4 tuiles fusionnées → {width}×{height} px')

    from qgis.core import QgsRasterLayer
    layer = QgsRasterLayer(tmp_path, src['name'])
    if not layer.isValid():
        raise IOError(f"Raster WMS invalide : {tmp_path}")

    if feedback:
        feedback.pushInfo(f'    Raster : {layer.width()}×{layer.height()} px — OK')

    # Enregistrer dans le cache MNT partagé pour la source pente (si elle tourne en parallèle)
    with _mnt_cache_lock:
        if cache_key not in _mnt_cache:
            event = threading.Event()
            event.set()
            _mnt_cache[cache_key] = {'event': event, 'path': tmp_path}
            _mnt_cache_files.append(tmp_path)
            # Le fichier est maintenant géré par le cache ET temp_files → double nettoyage
            # possible mais sans conséquence (os.unlink échoue silencieusement si déjà supprimé)

    return layer


# ---------- Dispatch ----------

def fetch_source(src, buffer_bbox, dist_km, centroid_wgs, feedback, temp_files, output_folder=None):
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
    if typ == 'api_datatourisme':
        return fetch_from_datatourisme(src, centroid_wgs, dist_km, feedback, temp_files, buffer_bbox)
    if typ == 'itineraires_merged':
        return fetch_itineraires_merged(src, buffer_bbox, feedback, temp_files)
    if typ == 'api_overpass':
        return fetch_from_overpass(src, buffer_bbox, feedback, temp_files)
    if typ == 'api_csv_point':
        return fetch_from_csv_point(src, buffer_bbox, feedback, temp_files)
    if typ == 'api_arcgis':
        return fetch_from_arcgis(src, buffer_bbox, feedback, temp_files)
    if typ == 'api_adp_dynamic':
        return fetch_from_adp_dynamic(src, buffer_bbox, feedback, temp_files)
    if typ == 'raster_ign':
        return fetch_raster_ign(src, buffer_bbox, feedback, temp_files)
    if typ == 'raster_slope':
        return fetch_raster_slope(src, buffer_bbox, feedback, temp_files, output_folder=output_folder)
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
