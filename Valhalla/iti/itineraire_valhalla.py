from qgis.PyQt.QtCore import QCoreApplication, QEventLoop, QSettings
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterField,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingParameterDateTime,
    QgsProcessingException,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsWkbTypes,
    QgsFeatureSink,
    QgsProcessingParameterBoolean
)
from PyQt5.QtCore import QVariant, QUrl, QDateTime
import json


class ItineraireValhallaAlgorithm(QgsProcessingAlgorithm):
    DETAIL_BY_SEGMENT = 'DETAIL_BY_SEGMENT'

    INPUT_START = 'INPUT_START'
    INPUT_END = 'INPUT_END'
    ID_FIELD_START = 'ID_FIELD_START'
    ID_FIELD_END = 'ID_FIELD_END'
    MODE = 'MODE'
    SERVER_URL = 'SERVER_URL'
    DATE_TIME = 'DATE_TIME'
    OUTPUT = 'OUTPUT'

    # ---------------------------------------------------------------------
    # INIT
    # ---------------------------------------------------------------------

    def initAlgorithm(self, config=None):
        # Paramètres avancés pour le transit
        from qgis.core import QgsProcessingParameterNumber, QgsProcessingParameterDefinition

        advanced_param_use_bus = QgsProcessingParameterNumber(
            'USE_BUS',
            self.tr('Préférence bus (0-1)'),
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1,
            minValue=0,
            maxValue=1,
            optional=True
        )
        advanced_param_use_bus.setFlags(advanced_param_use_bus.flags() | QgsProcessingParameterDefinition.FlagOptional | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(advanced_param_use_bus)

        advanced_param_use_rail = QgsProcessingParameterNumber(
            'USE_RAIL',
            self.tr('Préférence rail/métro (0-1)'),
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1,
            minValue=0,
            maxValue=1,
            optional=True
        )
        advanced_param_use_rail.setFlags(advanced_param_use_rail.flags() | QgsProcessingParameterDefinition.FlagOptional | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(advanced_param_use_rail)

        advanced_param_use_transfers = QgsProcessingParameterNumber(
            'USE_TRANSFERS',
            self.tr('Préférence pour les correspondances (0-1)'),
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1,
            minValue=0,
            maxValue=1,
            optional=True
        )
        advanced_param_use_transfers.setFlags(advanced_param_use_transfers.flags() | QgsProcessingParameterDefinition.FlagOptional | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(advanced_param_use_transfers)

        advanced_param_transfer_cost = QgsProcessingParameterNumber(
            'TRANSFER_COST',
            self.tr('Coût fixe de correspondance (secondes)'),
            type=QgsProcessingParameterNumber.Double,
            defaultValue=15.0,
            minValue=0,
            optional=True
        )
        advanced_param_transfer_cost.setFlags(advanced_param_transfer_cost.flags() | QgsProcessingParameterDefinition.FlagOptional | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(advanced_param_transfer_cost)

        advanced_param_transfer_penalty = QgsProcessingParameterNumber(
            'TRANSFER_PENALTY',
            self.tr('Pénalité de correspondance (secondes)'),
            type=QgsProcessingParameterNumber.Double,
            defaultValue=600.0,
            minValue=0,
            optional=True
        )
        advanced_param_transfer_penalty.setFlags(advanced_param_transfer_penalty.flags() | QgsProcessingParameterDefinition.FlagOptional | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(advanced_param_transfer_penalty)

        advanced_param_max_walk_distance = QgsProcessingParameterNumber(
            'MAX_WALK_DISTANCE',
            self.tr('Distance maximale à pied (mètres)'),
            type=QgsProcessingParameterNumber.Double,
            defaultValue=250,
            minValue=0,
            optional=True
        )
        advanced_param_max_walk_distance.setFlags(advanced_param_max_walk_distance.flags() | QgsProcessingParameterDefinition.FlagOptional | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(advanced_param_max_walk_distance)

        # Paramètre de sortie avancé pour la couche détail par tronçon
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT + "_DETAIL",
                self.tr("Itinéraires Valhalla - détail par tronçon"),
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_START,
                self.tr("Couche de points de départ"),
                [QgsProcessing.TypeVectorPoint]
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.ID_FIELD_START,
                self.tr("Champ ID départ"),
                parentLayerParameterName=self.INPUT_START
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_END,
                self.tr("Couche de points d'arrivée"),
                [QgsProcessing.TypeVectorPoint]
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.ID_FIELD_END,
                self.tr("Champ ID arrivée"),
                parentLayerParameterName=self.INPUT_END
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.MODE,
                self.tr("Mode de déplacement"),
                options=["Voiture", "Piéton", "Vélo", "Transport en commun"],
                defaultValue=0
            )
        )

        self.addParameter(
            QgsProcessingParameterDateTime(
                self.DATE_TIME,
                self.tr("Date et heure (heure:minute)"),
                defaultValue=QDateTime.currentDateTime(),
                # Ensure the widget allows time selection (hours/minutes)
                type=QgsProcessingParameterDateTime.Type.DateTime
            )
        )

        settings = QSettings()
        default_server = settings.value("valhalla/server_url", "http://localhost:8003")

        self.addParameter(
            QgsProcessingParameterString(
                self.SERVER_URL,
                self.tr("URL du serveur Valhalla"),
                defaultValue=default_server
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr("Itinéraires Valhalla")
            )
        )


        # Paramètre avancé : détail par tronçon
        from qgis.core import QgsProcessingParameterDefinition
        advanced_param_detail = QgsProcessingParameterBoolean(
            self.DETAIL_BY_SEGMENT,
            self.tr("Créer une couche détail par tronçon (mode, temps, distance, mode de transport), uniquement pour le mode \"Transport en commun\""),
            defaultValue=False,
            optional=True
        )
        advanced_param_detail.setFlags(advanced_param_detail.flags() | QgsProcessingParameterDefinition.FlagOptional | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(advanced_param_detail)

        # Paramètre avancé : walking speed
        advanced_param_walking_speed = QgsProcessingParameterNumber(
            'WALKING_SPEED',
            self.tr('Vitesse de marche (km/h)'),
            type=QgsProcessingParameterNumber.Double,
            defaultValue=5.0,
            minValue=0.5,
            maxValue=25.0,
            optional=True
        )
        advanced_param_walking_speed.setFlags(advanced_param_walking_speed.flags() | QgsProcessingParameterDefinition.FlagOptional | QgsProcessingParameterDefinition.FlagAdvanced)
        self.addParameter(advanced_param_walking_speed)

    # ---------------------------------------------------------------------
    # PROCESS
    # ---------------------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):
        walking_speed = self.parameterAsDouble(parameters, 'WALKING_SPEED', context)
        # Récupérer les paramètres avancés de transit
        use_bus = self.parameterAsDouble(parameters, 'USE_BUS', context)
        use_rail = self.parameterAsDouble(parameters, 'USE_RAIL', context)
        use_transfers = self.parameterAsDouble(parameters, 'USE_TRANSFERS', context)
        transfer_cost = self.parameterAsDouble(parameters, 'TRANSFER_COST', context)
        transfer_penalty = self.parameterAsDouble(parameters, 'TRANSFER_PENALTY', context)
        max_walk_distance = self.parameterAsDouble(parameters, 'MAX_WALK_DISTANCE', context)

        detail_by_segment = self.parameterAsBool(parameters, self.DETAIL_BY_SEGMENT, context)

        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

        if detail_by_segment:
            detail_fields = QgsFields()
            detail_fields.append(QgsField("id_start", QVariant.String))
            detail_fields.append(QgsField("id_end", QVariant.String))
            detail_fields.append(QgsField("segment_idx", QVariant.Int))
            detail_fields.append(QgsField("distance_km", QVariant.Double))
            detail_fields.append(QgsField("duration_min", QVariant.Double))
            detail_fields.append(QgsField("mode", QVariant.String))
            detail_fields.append(QgsField("instruction", QVariant.String))
            detail_sink, detail_dest_id = self.parameterAsSink(
                parameters,
                self.OUTPUT + "_DETAIL",  # nom technique, pas visible
                context,
                detail_fields,
                QgsWkbTypes.LineString,
                crs_wgs84
            )

        source_start = self.parameterAsSource(parameters, self.INPUT_START, context)
        source_end = self.parameterAsSource(parameters, self.INPUT_END, context)

        id_start_field = self.parameterAsString(parameters, self.ID_FIELD_START, context)
        id_end_field = self.parameterAsString(parameters, self.ID_FIELD_END, context)

        mode_index = self.parameterAsEnum(parameters, self.MODE, context)
        server_url = self.parameterAsString(parameters, self.SERVER_URL, context)
        date_time_dt = self.parameterAsDateTime(parameters, self.DATE_TIME, context)

        QSettings().setValue("valhalla/server_url", server_url)

        MODE_MAPPING = {
            0: "auto",
            1: "pedestrian",
            2: "bicycle",
            3: "multimodal" 
        }

        costing = MODE_MAPPING.get(mode_index, "auto")

        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform_start = QgsCoordinateTransform(
            source_start.sourceCrs(), crs_wgs84, context.transformContext()
        )
        transform_end = QgsCoordinateTransform(
            source_end.sourceCrs(), crs_wgs84, context.transformContext()
        )

        fields = QgsFields()
        fields.append(QgsField("id_start", QVariant.String))
        fields.append(QgsField("id_end", QVariant.String))
        fields.append(QgsField("distance_km", QVariant.Double))
        fields.append(QgsField("duration_min", QVariant.Double))
        fields.append(QgsField("mode", QVariant.String))

        sink, dest_id = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.LineString,
            crs_wgs84
        )

        starts = list(source_start.getFeatures())
        ends = list(source_end.getFeatures())

        for f_start in starts:
            p_start = transform_start.transform(f_start.geometry().asPoint())
            id_start = f_start[id_start_field]

            for f_end in ends:
                if feedback.isCanceled():
                    break

                p_end = transform_end.transform(f_end.geometry().asPoint())
                id_end = f_end[id_end_field]
                

                payload = {
                    "locations": [
                        {"lat": p_start.y(), "lon": p_start.x(),"search_radius": 100},
                        {"lat": p_end.y(), "lon": p_end.x(),"search_radius": 100}
                    ],
                    "costing": costing,
                    "directions_options": {
                        "units": "kilometers",
                        "language": "fr-FR"
                    }
                }

                # ---------------------------------------------------
                # 🚍 TRANSIT / MULTIMODAL
                # ---------------------------------------------------
                if costing == "multimodal":

                    if (date_time_dt is None) or (not date_time_dt.isValid()):
                        raise QgsProcessingException(
                            "Le mode transport en commun nécessite une date/heure."
                        )

                    # Format to ISO-like string used by Valhalla, e.g. 2025-01-15T08:30
                    date_time = date_time_dt.toString("yyyy-MM-ddThh:mm")

                    payload["date_time"] = {
                        "type": 1,
                        "value": date_time
                    }

                    transit_options = {}
                    if use_bus is not None:
                        transit_options["use_bus"] = float(use_bus)
                    if use_rail is not None:
                        transit_options["use_rail"] = float(use_rail)
                    if use_transfers is not None:
                        transit_options["use_transfers"] = float(use_transfers)
                    if transfer_cost is not None:
                        transit_options["transfer_cost"] = float(transfer_cost)
                    if transfer_penalty is not None:
                        transit_options["transfer_penalty"] = float(transfer_penalty)
                    if max_walk_distance is not None:
                        transit_options["max_walk_distance"] = float(max_walk_distance)

                    pedestrian_options = {
                        "max_walk_distance": float(max_walk_distance) if max_walk_distance is not None else 2000,
                        "walking_speed": float(walking_speed) if walking_speed is not None else 5.0,
                        "walk_factor": 1.5
                    }

                    payload["costing_options"] = {
                        "transit": transit_options,
                        "pedestrian": pedestrian_options
                    }
                elif costing == "bicycle":
                    # Default bicycle options: relaxed snapping for better edge matching
                    payload["costing_options"] = {
                        "bicycle": {
                            "bicycle_type": "hybrid",
                            "cycling_speed": 18,
                            "use_roads": 0.5,
                            "use_hills": 0.5,
                            # Avoid filtering candidates due to bad surfaces by default
                            "avoid_bad_surfaces": 0
                        }
                    }

                    # Increase search radius and allow minimal reachability by default
                    for i in range(len(payload["locations"])):
                        payload["locations"][i]["search_radius"] = 1000
                        payload["locations"][i]["minimum_reachability"] = 1
                elif costing == "pedestrian":
                    pedestrian_options = {
                        "walking_speed": float(walking_speed) if walking_speed is not None else 5.0,
                        "walk_factor": 1.5
                    }
                    payload["costing_options"] = {"pedestrian": pedestrian_options}

                try:
                    result = self.callValhalla(server_url, payload,feedback)
                except Exception as e:
                    # Fallback for bicycle: relax snapping if no suitable edges
                    err = str(e)
                    if costing == "bicycle" and ("No suitable edges" in err or "no suitable edge" in err or "no edge" in err):
                        feedback.pushInfo("Bicycle: retry with relaxed search parameters (radius/reachability).")
                        # Increase search radius and allow minimal reachability to improve snapping
                        payload_relaxed = dict(payload)
                        payload_relaxed["locations"] = [
                            {"lat": p_start.y(), "lon": p_start.x(), "search_radius": 1000, "minimum_reachability": 1},
                            {"lat": p_end.y(), "lon": p_end.x(), "search_radius": 1000, "minimum_reachability": 1}
                        ]
                        # Optionally relax bad surface avoidance to avoid filtering out candidates
                        co = payload_relaxed.get("costing_options", {})
                        bike = co.get("bicycle", {})
                        if "avoid_bad_surfaces" in bike and bike["avoid_bad_surfaces"] > 0:
                            bike["avoid_bad_surfaces"] = 0
                            co["bicycle"] = bike
                            payload_relaxed["costing_options"] = co

                        try:
                            result = self.callValhalla(server_url, payload_relaxed, feedback)
                        except Exception as e2:
                            feedback.reportError(str(e2))
                            continue
                    else:
                        feedback.reportError(str(e))
                        continue

                trip = result.get("trip", {})
                shape = trip.get("legs", [{}])[0].get("shape")
                if not shape:
                    continue

                points = self.decodePolyline(shape)
                geom = QgsGeometry.fromPolylineXY(points)

                feat = QgsFeature(fields)
                feat.setGeometry(geom)
                feat.setAttributes([
                    str(id_start),
                    str(id_end),
                    trip.get("summary", {}).get("length", 0),
                    trip.get("summary", {}).get("time", 0) / 60,
                    costing
                ])

                sink.addFeature(feat, QgsFeatureSink.FastInsert)

                # Si option détail cochée, créer une entité par tronçon (maneuver)
                if detail_by_segment and 'legs' in trip and trip['legs']:
                    maneuvers = trip['legs'][0].get('maneuvers', [])
                    main_points = self.decodePolyline(trip['legs'][0].get('shape', ''))
                    for idx, maneuver in enumerate(maneuvers):
                        begin_idx = maneuver.get('begin_shape_index', 0)
                        end_idx = maneuver.get('end_shape_index', 0)
                        # Extraire le tronçon de la polyline principale
                        seg_points = main_points[begin_idx:end_idx+1] if end_idx >= begin_idx else []
                        if len(seg_points) < 2:
                            continue
                        seg_geom = QgsGeometry.fromPolylineXY(seg_points)
                        seg_distance = maneuver.get('length', 0)
                        seg_duration = maneuver.get('time', 0) / 60
                        seg_mode = maneuver.get('travel_mode', '')
                        seg_instruction = maneuver.get('instruction', '')
                        detail_feat = QgsFeature(detail_fields)
                        detail_feat.setGeometry(seg_geom)
                        detail_feat.setAttributes([
                            str(id_start),
                            str(id_end),
                            idx,
                            seg_distance,
                            seg_duration,
                            seg_mode,
                            seg_instruction
                        ])
                        detail_sink.addFeature(detail_feat, QgsFeatureSink.FastInsert)
        return {self.OUTPUT: dest_id}
        if detail_by_segment:
            return {self.OUTPUT: dest_id, self.OUTPUT + "_DETAIL": detail_dest_id}

    # ---------------------------------------------------------------------
    # VALHALLA CLIENT
    # ---------------------------------------------------------------------

    def callValhalla(self, server_url, payload, feedback):

        json_param = json.dumps(payload, ensure_ascii=False)
        encoded = QUrl.toPercentEncoding(json_param)

        url = QUrl(f"{server_url.rstrip('/')}/route?json={encoded.data().decode()}")

        feedback.pushInfo("=== Valhalla GET request ===")
        feedback.pushInfo(url.toString())
        feedback.pushInfo("=== End request ===")

        request = QNetworkRequest(url)
        request.setRawHeader(b"Accept", b"application/json")

        manager = QNetworkAccessManager()
        reply = manager.get(request)

        loop = QEventLoop()
        reply.finished.connect(loop.quit)
        loop.exec_()

        response_data = reply.readAll().data().decode()

        if reply.error() != QNetworkReply.NoError:
            raise Exception(response_data)

        return json.loads(response_data)

    # ---------------------------------------------------------------------
    # POLYLINE DECODER
    # ---------------------------------------------------------------------

    def decodePolyline(self, polyline):

        coords = []
        index = lat = lon = 0

        while index < len(polyline):
            for is_lat in (True, False):
                shift = result = 0
                while True:
                    b = ord(polyline[index]) - 63
                    index += 1
                    result |= (b & 0x1f) << shift
                    shift += 5
                    if b < 0x20:
                        break
                delta = ~(result >> 1) if result & 1 else (result >> 1)
                if is_lat:
                    lat += delta
                else:
                    lon += delta

            coords.append(QgsPointXY(lon / 1e6, lat / 1e6))

        return coords

    # ---------------------------------------------------------------------

    def name(self):
        return "itineraire_valhalla"

    def displayName(self):
        return self.tr("Itinéraires Valhalla")

    def group(self):
        return "Valhalla"

    def groupId(self):
        return "valhalla"

    def shortHelpString(self):
        return """
        <h3>Itinéraires Valhalla</h3>
        <ul>
            <li>Voiture, piéton, vélo, transport en commun</li>
            <li>Date/heure supportée pour le transit</li>
            <li>Serveur Valhalla configurable</li>
        </ul>
        """

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        return ItineraireValhallaAlgorithm()