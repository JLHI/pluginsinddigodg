# Algorithme spécifique vélo : utiliser les options vélo d'itineraire_valhalla et
# appliquer le même traitement que pour le piéton (expansion -> union -> buffer -> suppression des trous)

def run_voiture(    self,
    pt_4326,
    value,
    isochrone_type,
    server_url,
    context,
    feedback):
    from qgis.core import (
        QgsGeometry, QgsPointXY, QgsCoordinateTransform,
        QgsCoordinateReferenceSystem, 
    )
    from qgis.PyQt.QtCore import QEventLoop, QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest, QNetworkReply, QNetworkAccessManager
    import json

   

    if isochrone_type == 0:   # temps
        contours = [{"time": int(value)}]
    else:                    # distance
        contours = [{"distance": float(value) / 1000.0}]

    # ------------------------------------------------------------
    # Payload Valhalla (bicycle, options inspirées d'itineraire_valhalla)
    # ------------------------------------------------------------
    payload = {
        "locations": [{"lat": pt_4326.y(), "lon": pt_4326.x(), "search_radius": 1000, "minimum_reachability": 1}],
        "costing": "auto",
        "polygons": True,
        "contours": contours,
        "generalize":10
      
    }

    json_param = json.dumps(payload, ensure_ascii=False)
    encoded = QUrl.toPercentEncoding(json_param)
    url = QUrl(f"{server_url.rstrip('/')}/isochrone?json={encoded.data().decode()}")

    request = QNetworkRequest(url)
    request.setRawHeader(b"Accept", b"application/json")

    # utiliser le manager partagé si présent sur self (comme dans run_pieton)
    try:
        reply = self.manager.get(request)
    except Exception:
        mgr = QNetworkAccessManager()
        reply = mgr.get(request)

    loop = QEventLoop()
    reply.finished.connect(loop.quit)
    loop.exec_()

    if reply.error() != QNetworkReply.NoError:
        feedback.reportError(reply.readAll().data().decode())
        return []

    result = json.loads(reply.readAll().data().decode())
    feedback.pushInfo(f"Réponse reçue de l'API Valhalla pour vélo : {result}")

    # ------------------------------------------------------------
    # Récupérer les polygones retournés par l'API isochrone,
    # reprojeter et appliquer un buffer de 25 m
    # ------------------------------------------------------------
    polygons = []
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), QgsCoordinateReferenceSystem("EPSG:2154"), context.transformContext())

    for feat in result.get("features", []):
        geom_obj = feat.get("geometry")
        if not geom_obj:
            continue
        gtype = geom_obj.get("type")
        coords = geom_obj.get("coordinates", [])

        try:
            if gtype == "Polygon":
                poly = QgsGeometry.fromPolygonXY([[QgsPointXY(c[0], c[1]) for c in ring] for ring in coords])
            elif gtype == "MultiPolygon":
                mp = []
                for polycoords in coords:
                    mp.append([[QgsPointXY(c[0], c[1]) for c in ring] for ring in polycoords])
                poly = QgsGeometry.fromMultiPolygonXY(mp)
            else:
                continue
        except Exception:
            continue

        try:
            poly.transform(tr)
        except Exception:
            pass

        if poly.isEmpty():
            continue

        buf = poly.buffer(25, 24)
        if buf.isEmpty():
            continue
        polygons.append(buf)

    return polygons
