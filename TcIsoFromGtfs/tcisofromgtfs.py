from qgis.PyQt.QtCore import QCoreApplication
from datetime import datetime, timedelta
import os, numpy as np
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterString,
    QgsProcessingParameterEnum,
    QgsProcessingParameterVectorLayer,
    QgsProcessingException,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsField,QgsFields,QgsProcessing,QgsProcessingParameterFeatureSink,QgsFeatureSink,QgsWkbTypes,QgsCoordinateReferenceSystem
)
from qgis.PyQt.QtCore import QVariant


from .gtfs_isochrone.main import compute_isochrone,compute_isochrone_arrival
import datetime

# Obtenir la date et l'heure de demain
tomorrow = datetime.datetime.now() + datetime.timedelta(days=1)

# Formater dans le format souhaité
formatted_tomorrow = tomorrow.strftime("%Y-%m-%d %H:%M:%S")

# Résultat
class GtfsIsochrone(QgsProcessingAlgorithm):
    INPUT_LAYER = "INPUT_LAYER"
    INPUT_GTFS_FOLDER = "INPUT_GTFS_FOLDER"
    START_DATETIME = "START_DATETIME"
    TYPE_HEURE = "TYPE_HEURE"
    DURATION_RANGES = "DURATION_RANGES"
    OUTPUT_LAYER = "OUTPUT_LAYER"

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                "Couche des points d'entrée",
                [QgsProcessing.TypeVectorPoint],
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_GTFS_FOLDER,
                "Dossier contenant les fichiers GTFS",
                behavior=QgsProcessingParameterFile.Folder,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.START_DATETIME,
                "Date et heure de départ - ATTENTION au format(YYYY-MM-DD HH:MM:SS)",
                defaultValue=formatted_tomorrow,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                'TYPE_HEURE',
                self.tr("Type d'heure"),
                options=["Heure de départ", "Heure d'arrivée"],
                defaultValue=1  # Par défaut : "Heure de départ"
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                "DURATION_RANGES",
                "Tranches de durée (en minutes, séparées par des virgules, ex: 5,10,15)",
                defaultValue="10,20,30,40,50,60"
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER,
                "Couche de sortie des isochrones",
            )
        )
        self.output_fields = ["duration", "distance", "mode"]  # Champs à inclure
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER,
                "Couche de sortie des isochrones",
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # Charger les paramètres
        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        gtfs_folder = self.parameterAsFile(parameters, self.INPUT_GTFS_FOLDER, context)
        start_datetime_str = self.parameterAsString(parameters, self.START_DATETIME, context)
        duration_ranges = self.parameterAsString(parameters, "DURATION_RANGES", context)
        type_heure = parameters['TYPE_HEURE']  # 0 pour "Heure de départ", 1 pour "Heure d'arrivée"
        # Convertir la date et l'heure
        try:
            start_datetime = datetime.datetime.strptime(start_datetime_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise QgsProcessingException(f"Format invalide pour la date/heure : {start_datetime_str}")
        
        # Convertir les durées en liste d'entiers
        try:
            duration_list = [int(x.strip()) for x in duration_ranges.split(",")]
            duration_list.sort()
        except ValueError:
            raise QgsProcessingException("Les tranches de durée doivent être des nombres entiers séparés par des virgules.")

        # Initialisation de la couche de sortie
        feedback.pushInfo("Initialisation de la couche de sortie...")
        fields = QgsFields()
        fields.append(QgsField("input_id", QVariant.Int))  # ID de l'entité d'entrée
        fields.append(QgsField("max_duration", QVariant.Int))  # Durée maximale
        fields.append(QgsField("geometry_type", QVariant.String))  # Type de géométrie (facultatif)

        # Créer la couche de sortie
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT_LAYER,
            context,
            fields,
            QgsWkbTypes.Polygon,  # Type de géométrie
            QgsCoordinateReferenceSystem("EPSG:4326")  # CRS
        )

        # Calcul des isochrones
        feedback.pushInfo("Calcul des isochrones...")
        # Parcourir les entités d'entrée
        for feature in input_layer.getFeatures():
            input_id = feature.id()
            geom = feature.geometry()
            point = geom.asPoint()
            lat, lon = point.y(), point.x()

            for max_duration in duration_list:
                feedback.pushInfo(f"Calcul de l'isochrone pour lat={lat}, lon={lon}, durée={max_duration} minutes")

               

                if type_heure == 0:
                    feedback.pushInfo("Calcul des isochrones avec heure de départ")
                    geojson = compute_isochrone(gtfs_folder, lat, lon, start_datetime, max_duration * 60)
                elif type_heure == 1:
                    feedback.pushInfo("Calcul des isochrones avec heure d\'arrivée")
                    geojson = compute_isochrone_arrival(gtfs_folder, lat, lon, start_datetime, max_duration * 60)

                # Ajouter les isochrones à la couche de sortie
                for feature_geojson in geojson["features"]:
                    if feature_geojson["geometry"]["type"] == "Polygon":
                        coordinates = feature_geojson["geometry"]["coordinates"][0]
                        wkt_string = "POLYGON ((" + ", ".join(f"{x} {y}" for x, y in coordinates) + "))"
                        geometry = QgsGeometry.fromWkt(wkt_string)

                    elif feature_geojson["geometry"]["type"] == "MultiPolygon":
                        polygons = []
                        for polygon in feature_geojson["geometry"]["coordinates"]:
                            coordinates = polygon[0]
                            polygons.append("((" + ", ".join(f"{x} {y}" for x, y in coordinates) + "))")
                        wkt_string = "MULTIPOLYGON (" + ", ".join(polygons) + ")"
                        geometry = QgsGeometry.fromWkt(wkt_string)

                    else:
                        raise QgsProcessingException("Type de géométrie non supporté : " + feature_geojson["geometry"]["type"])

                    # Créer une entité pour chaque géométrie
                    output_feature = QgsFeature(fields)
                    output_feature.setGeometry(geometry)
                    output_feature.setAttributes([input_id, max_duration, feature_geojson["geometry"]["type"]])

                    # Ajouter à la couche de sortie
                    sink.addFeature(output_feature, QgsFeatureSink.FastInsert)

        feedback.pushInfo("Isochrones calculés avec succès.")
        return {self.OUTPUT_LAYER: dest_id}

    def name(self):
        return "GtfsIsochrone"

    def displayName(self):
        return "Isochrones TC à partir de GTFS"
    
    def group(self):
        return 'GTFS'

    def groupId(self):
        return 'GTFS'

    def createInstance(self):
        return GtfsIsochrone()
    def tr(self, string):
        return QCoreApplication.translate('Processing', string)