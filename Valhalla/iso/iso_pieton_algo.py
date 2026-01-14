def run_pieton(
        self,
    pt_4326,
    value,
    isochrone_type,
    server_url,
    context,
    feedback
):
    """
    Algorithme piéton :
    - appel Valhalla expansion (temps)
    - récupération lignes réseau
    - reprojection en EPSG:2154
    - union
    - buffer métrique
    - suppression des trous
    """

    from qgis.core import (
        QgsGeometry,
        QgsPointXY,
        QgsVectorLayer,
        QgsFeature,
        QgsCoordinateTransform,
        QgsCoordinateReferenceSystem,
        QgsWkbTypes
    )
    from qgis.PyQt.QtCore import QEventLoop, QUrl
    from qgis.PyQt.QtNetwork import QNetworkRequest, QNetworkReply
    from qgis import processing
    import json

    # ------------------------------------------------------------
    # CRS
    # ------------------------------------------------------------

    crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")
    crs_2154 = QgsCoordinateReferenceSystem("EPSG:2154")

    to2154 = QgsCoordinateTransform(crs_4326, crs_2154, context.transformContext())
    print(isochrone_type)
    feedback.pushInfo("isochrone_type : "+str(isochrone_type))

    if isochrone_type == 0:   # temps
        contours = [{"time": int(value)}]
    else:                    # distance
        contours = [{"distance": float(value) / 1000.0}]

    # ------------------------------------------------------------
    # Payload Valhalla (temps uniquement)
    # ------------------------------------------------------------

    payload = {
        "locations": [{"lat": pt_4326.y(), "lon": pt_4326.x()}],
        "costing": "pedestrian",
        "action": "isochrone",
        "dedupe": True,
        "contours": contours
    }

    json_param = json.dumps(payload, ensure_ascii=False)
    encoded = QUrl.toPercentEncoding(json_param)
    url = QUrl(f"{server_url.rstrip('/')}/expansion?json={encoded.data().decode()}")

    request = QNetworkRequest(url)

    reply = self.manager.get(request)

    loop = QEventLoop()
    reply.finished.connect(loop.quit)
    loop.exec_()

    if reply.error() != QNetworkReply.NoError:
        feedback.reportError(reply.readAll().data().decode())
        return []

    result = json.loads(reply.readAll().data().decode())
    feedback.pushInfo(f"Réponse reçue de l'API Valhalla pour la marche : {result}")

    # ------------------------------------------------------------
    # Extraction + reprojection des lignes
    # ------------------------------------------------------------

    line_geoms_2154 = []

    for feat in result.get("features", []):
        geom_obj = feat.get("geometry")
        if not geom_obj or geom_obj.get("type") != "LineString":
            continue

        coords = geom_obj.get("coordinates", [])
        if len(coords) < 2:
            continue

        geom_4326 = QgsGeometry.fromPolylineXY(
            [QgsPointXY(c[0], c[1]) for c in coords]
        )

        # TRANSFORMATION EXPLICITE
        geom_4326.transform(to2154)

        if geom_4326.isEmpty():
            continue

        line_geoms_2154.append(geom_4326)

    if not line_geoms_2154:
        return []

    # ------------------------------------------------------------
    # Union rapide (beaucoup plus rapide que combine())
    # ------------------------------------------------------------

    merged = QgsGeometry.unaryUnion(line_geoms_2154)

    if merged.isEmpty():
        return []
    
    # ------------------------------------------------------------
    # Si le mode est Distance, on découpe les lignes par un tampon rond égale a la valeur de la distance
    # ------------------------------------------------------------

    if isochrone_type == 1:   # distance

        origin_geom = QgsGeometry.fromPointXY(QgsPointXY(pt_4326.x(), pt_4326.y()))
        origin_geom.transform(to2154)

        radius_m = float(value)  # value = distance en mètres
        circle = origin_geom.buffer(radius_m, 64)  # 64 segments => cercle assez "rond"

        if circle.isEmpty():
            return []

        clipped = merged.intersection(circle)
        if clipped.isEmpty():
            return []

        # L'intersection peut renvoyer une GeometryCollection -> on ne garde que les lignes
        if QgsWkbTypes.geometryType(clipped.wkbType()) != QgsWkbTypes.LineGeometry:
            parts = []
            for g in clipped.asGeometryCollection():
                if not g.isEmpty() and QgsWkbTypes.geometryType(g.wkbType()) == QgsWkbTypes.LineGeometry:
                    parts.append(g)

            if not parts:
                return []

            merged = QgsGeometry.unaryUnion(parts)
        else:
            merged = clipped

        if merged.isEmpty():
            return []
    # ------------------------------------------------------------
    # Buffer réseau (EPSG:2154)
    # ------------------------------------------------------------

    buffer_distance = 25      # mètres
    polygon = merged.buffer(buffer_distance, 4)

    if polygon.isEmpty():
        return []

    # ------------------------------------------------------------
    # Suppression des trous < 150 000 m²
    # ------------------------------------------------------------

    tmp_layer = QgsVectorLayer("Polygon?crs=EPSG:2154", "tmp", "memory")
    tmp_feat = QgsFeature()
    tmp_feat.setGeometry(polygon)
    tmp_layer.dataProvider().addFeatures([tmp_feat])

    res = processing.run(
        "native:deleteholes",
        {
            "INPUT": tmp_layer,
            "MIN_AREA": 150000,
            "OUTPUT": "memory:"
        },
        context=context,
        feedback=feedback
    )

    return [f.geometry() for f in res["OUTPUT"].getFeatures()]
