import pandas as pd
import requests
from collections import defaultdict
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterFeatureSink,
    QgsProcessingException,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsWkbTypes,
    QgsCoordinateReferenceSystem,
    QgsFeatureSink,
    QgsPointXY,
)


class GtfsRouteIgn(QgsProcessingAlgorithm):
    """Génère une couche d'itinéraires à partir de deux fichiers GTFS."""

    INPUT_TRIP_FILE = "INPUT_TRIP_FILE"
    INPUT_STOP_FILE = "INPUT_STOP_FILE"
    OUTPUT_LAYER = "OUTPUT_LAYER"

    def initAlgorithm(self, config=None):
        # Fichier stop_times
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_TRIP_FILE,
                self.tr("Fichier stop_times (trip_id, stop_id, stop_sequence)"),
                extension="txt",  # Extension attendue
            )
        )
        # Fichier stops
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_STOP_FILE,
                self.tr("Fichier stops (stop_id, stop_lat, stop_lon)"),
                extension="txt",  # Extension attendue
            )
        )
        # Paramètre de sortie
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER, self.tr("Couche de sortie (itinéraires)")
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        # Récupération des fichiers
        trip_file = self.parameterAsFile(parameters, self.INPUT_TRIP_FILE, context)
        stop_file = self.parameterAsFile(parameters, self.INPUT_STOP_FILE, context)

        if not trip_file or not stop_file:
            raise QgsProcessingException("Les fichiers d'entrée sont requis.")

        # Charger les fichiers dans des DataFrames pandas
        feedback.pushInfo("Chargement des fichiers...")
        try:
            trip_df = pd.read_csv(trip_file, delimiter=",")
            stop_df = pd.read_csv(stop_file, delimiter=",")
            feedback.pushInfo(f"Fichier stop_times chargé avec {len(trip_df)} lignes.")
            feedback.pushInfo(f"Fichier stops chargé avec {len(stop_df)} lignes.")
        except Exception as e:
            raise QgsProcessingException(f"Erreur lors du chargement des fichiers : {e}")

        # Fusion des fichiers pour obtenir les coordonnées
        feedback.pushInfo("Fusion des fichiers stop_times et stops...")
        merged_df = trip_df.merge(stop_df, on="stop_id", how="inner")
        feedback.pushInfo(f"Fusion terminée avec {len(merged_df)} lignes.")

        # Trier par trip_id et stop_sequence
        merged_df = merged_df.sort_values(by=["trip_id", "stop_sequence"])

        # Préparation des segments pour chaque trip_id
        trip_segments = defaultdict(list)
        result = []

        # Génération des segments d'itinéraires
        for i in range(len(merged_df)):
            trip_id = merged_df.iloc[i]["trip_id"]
            stop_sequence = merged_df.iloc[i]["stop_sequence"]
            xy_depart = (merged_df.iloc[i]["stop_lat"], merged_df.iloc[i]["stop_lon"])

            if (
                i + 1 < len(merged_df)
                and merged_df.iloc[i + 1]["trip_id"] == trip_id
            ):
                xy_arrivee = (
                    merged_df.iloc[i + 1]["stop_lat"],
                    merged_df.iloc[i + 1]["stop_lon"],
                )
            else:
                xy_arrivee = None

            result.append([trip_id, stop_sequence, xy_depart, xy_arrivee])

        # Requêtes à l'API IGN pour les itinéraires
        for trip_id, stop_sequence, xy_depart, xy_arrivee in result:
            if xy_arrivee:
                try:
                    api_url = (
                        f"https://wxs.ign.fr/calcul/geoportail/itineraire/rest/1.0.0/route?"
                        f"resource=bdtopo-osrm&profile=car&optimization=fastest"
                        f"&start={xy_depart[1]},{xy_depart[0]}"
                        f"&end={xy_arrivee[1]},{xy_arrivee[0]}"
                        f"&geometryFormat=geojson"
                    )
                    response = requests.get(api_url)
                    if response.status_code == 200:
                        route_data = response.json()
                        coordinates = route_data["geometry"]["coordinates"]
                        trip_segments[trip_id].append(coordinates)
                except Exception as e:
                    feedback.reportError(f"Erreur pour trip_id={trip_id}: {e}")

        # Création de la couche de sortie
        feedback.pushInfo("Création de la couche de sortie...")
        fields = QgsFields()
        fields.append(QgsField("trip_id", QVariant.String))

        (sink, sink_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT_LAYER,
            context,
            fields,
            QgsWkbTypes.MultiLineString,
            QgsCoordinateReferenceSystem("EPSG:4326"),
        )

        if sink is None:
            raise QgsProcessingException(
                self.invalidSinkError(parameters, self.OUTPUT_LAYER)
            )

        # Ajout des segments dans la couche de sortie
        for trip_id, segments in trip_segments.items():
            feature = QgsFeature(fields)
            multiline = QgsGeometry.fromMultiPolylineXY(
                [[QgsPointXY(pt[0], pt[1]) for pt in segment] for segment in segments]
            )
            feature.setGeometry(multiline)
            feature.setAttribute("trip_id", trip_id)
            sink.addFeature(feature, QgsFeatureSink.FastInsert)

        return {self.OUTPUT_LAYER: sink_id}

    def name(self):
        return "gtfs_route_ign"

    def displayName(self):
        return self.tr("GTFS to Route IGN")

    def group(self):
        return "GTFS Tools"

    def groupId(self):
        return "gtfs_tools"

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        return GtfsRouteIgn()

    def shortHelpString(self):
        """
        Retourne le texte d'aide pour l'outil.
        """
        return """
            <h3>Outil Inddigo : GTFS to Route IGN</h3>
            <p>Ce plugin permet de générer des itinéraires détaillés à partir de fichiers GTFS, en utilisant une API externe pour obtenir les tracés géographiques précis.</p>
            
            <h4>Fonctionnalités principales :</h4>
            <ul>
                <li>Fusion des données de fichiers GTFS (<b>stops_time</b> et <b>stops</b>).</li>
                <li>Génération automatique des segments d'itinéraires entre les arrêts, basés sur les coordonnées des arrêts.</li>
                <li>Requête à une API de routage (IGN) pour obtenir des itinéraires optimisés et précis entre les points.</li>
                <li>Création d'une couche de sortie au format <b>MultiLineString</b>, avec les segments regroupés par identifiant de trajet (<b>trip_id</b>).</li>
            </ul>
            
            <h4>Paramètres :</h4>
            <ul>
                <li><b>Fichier stops_time :</b> Fichier GTFS contenant les informations sur les trajets (trip_id, stop_sequence, stop_id).</li>
                <li><b>Fichier stops :</b> Fichier GTFS contenant les coordonnées des arrêts (stop_id, stop_lat, stop_lon).</li>
                <li><b>Couche de sortie :</b> La couche générée contenant les itinéraires avec des géométries détaillées.</li>
            </ul>
            
            <h4>Résultat :</h4>
            <p>Une couche de polylignes représentant les itinéraires, où chaque trajet (<b>trip_id</b>) est associé à un ensemble de segments géographiques détaillés.</p>
            
            <h4>Prérequis :</h4>
            <ul>
                <li>Deux fichiers GTFS valides (stops_time et stops).</li>
                <li>Accès à Internet pour interagir avec l'API IGN.</li>
            </ul>
            
            <p><i>Note :</i> Vérifiez les champs disponibles dans vos fichiers d'entrée. Les champs requis (trip_id, stop_sequence, stop_id, stop_lat, stop_lon) sont détectés automatiquement.</p>
        """