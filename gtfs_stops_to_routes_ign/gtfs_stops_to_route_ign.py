from qgis.PyQt.QtCore import QCoreApplication, QVariant

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterFeatureSink,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsProcessingException,
    QgsWkbTypes,
    QgsCoordinateReferenceSystem,
    QgsFeatureSink,QgsPointXY
)
from PyQt5.QtCore import QVariant
import pandas as pd
import requests
from collections import defaultdict


class GtfsRouteIgn(QgsProcessingAlgorithm):
    """Génère une couche d'itinéraires à partir de deux fichiers GTFS."""

    # Déclaration des paramètres
    INPUT_TRIP_FILE = "INPUT_TRIP_FILE"
    INPUT_STOP_FILE = "INPUT_STOP_FILE"
    OUTPUT_LAYER = "OUTPUT_LAYER"

    def initAlgorithm(self, config=None):
        # Paramètre pour le fichier stops_time
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_TRIP_FILE,
                self.tr("Fichier stops_time (trip_id et stop_sequence)"),
                extension="txt",
            )
        )
        # Paramètre pour le fichier stops
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_STOP_FILE,
                self.tr("Fichier stops (stop_id, stop_lat, stop_lon)"),
                extension="txt",
            )
        )
        # Paramètre de sortie
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER, self.tr("Couche de sortie (itinéraires)")
            )
        )

    def detect_field(self, columns, candidates):
        """Détecte automatiquement un champ parmi les colonnes disponibles."""
        for candidate in candidates:
            if candidate in columns:
                return candidate
        raise QgsProcessingException(
            f"Impossible de détecter un champ parmi : {', '.join(candidates)}"
        )

    def processAlgorithm(self, parameters, context, feedback):
        
        # Récupération des fichiers d'entrée

        trip_file = self.parameterAsSource(parameters, self.INPUT_TRIP_FILE, context)
        stop_file = self.parameterAsSource(parameters, self.INPUT_STOP_FILE, context)
     
        if not trip_file or not stop_file:
            raise QgsProcessingException("Les fichiers d'entrée sont requis.")

        feedback.pushInfo(f"Fichier stops_time : {trip_file}")
        feedback.pushInfo(f"Fichier stops : {stop_file}")

        # Charger les fichiers dans des DataFrames pandas
        feedback.pushInfo("Chargement des données...")
        try:
            trip_df = pd.read_csv(trip_file)
            stop_df = pd.read_csv(stop_file)
        except Exception as e:
            raise QgsProcessingException(f"Erreur lors du chargement des fichiers : {e}")

        # Détection automatique des champs
        feedback.pushInfo("Détection des champs...")
        trip_id_field = self.detect_field(trip_df.columns, ["trip_id", "id_trip"])
        stop_sequence_field = self.detect_field(trip_df.columns, ["stop_sequence", "sequence"])
        stop_id_field = self.detect_field(trip_df.columns, ["stop_id"])
        stop_lat_field = self.detect_field(stop_df.columns, ["stop_lat", "latitude"])
        stop_lon_field = self.detect_field(stop_df.columns, ["stop_lon", "longitude"])
        stop_id_in_stop_file = self.detect_field(stop_df.columns, ["stop_id"])

        feedback.pushInfo(
            f"Champs détectés : trip_id={trip_id_field}, stop_sequence={stop_sequence_field}, "
            f"stop_id={stop_id_field}, stop_lat={stop_lat_field}, stop_lon={stop_lon_field}"
        )

        # Fusion des deux DataFrames
        feedback.pushInfo("Fusion des fichiers...")
        merged_df = trip_df.merge(stop_df, left_on=stop_id_field, right_on=stop_id_in_stop_file)

        trip_segments = defaultdict(list)

        # Génération des segments d'itinéraires
        feedback.pushInfo("Génération des segments d'itinéraires...")
        for i in range(len(merged_df) - 1):
            if merged_df.iloc[i][trip_id_field] == merged_df.iloc[i + 1][trip_id_field]:
                xy_depart = (merged_df.iloc[i][stop_lat_field], merged_df.iloc[i][stop_lon_field])
                xy_arrivee = (merged_df.iloc[i + 1][stop_lat_field], merged_df.iloc[i + 1][stop_lon_field])
                api_url = (
                    f"https://data.geopf.fr/navigation/itineraire?"
                    f"resource=bdtopo-osrm&profile=car&optimization=fastest"
                    f"&start={xy_depart[1]},{xy_depart[0]}"
                    f"&end={xy_arrivee[1]},{xy_arrivee[0]}"
                    f"&geometryFormat=geojson"
                )
                try:
                    response = requests.get(api_url)
                    if response.status_code == 200:
                        route_data = response.json()
                        coordinates = route_data["geometry"]["coordinates"]
                        trip_segments[merged_df.iloc[i][trip_id_field]].append(coordinates)
                except Exception as e:
                    feedback.reportError(f"Erreur pour {api_url}: {e}")

        # Création de la couche de sortie
        fields = QgsFields()
        fields.append(QgsField("trip_id", QVariant.String))

        (sink, sink_id) = self.parameterAsSink(
            parameters, self.OUTPUT_LAYER, context, fields, QgsWkbTypes.MultiLineString, QgsCoordinateReferenceSystem("EPSG:4326")
        )

        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT_LAYER))

        for trip_id, segments in trip_segments.items():
            feature = QgsFeature(fields)
            geometry = QgsGeometry.fromMultiPolylineXY(
                [[QgsPointXY(pt[0], pt[1]) for pt in segment] for segment in segments]
            )
            feature.setGeometry(geometry)
            feature.setAttribute("trip_id", trip_id)
            sink.addFeature(feature, QgsFeatureSink.FastInsert)

        return {self.OUTPUT_LAYER: sink_id}



    def name(self):
        return 'GTFS to Route IGN'

    def displayName(self):
        return self.tr('GTFS to Route IGN')

    def group(self):
        return 'Les plugins non restreint du pôle DG d\'Inddigo'

    def groupId(self):
        return 'Les plugins non restreint du pôle DG d\'Inddigo'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

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
    # def icon(self):
    #     """
    #     Retourne une icône personnalisée pour cet algorithme.
    #     """
    #     icon_path = os.path.join(os.path.dirname(__file__), "icon_arbre.png")
    #     if os.path.exists(icon_path):
    #         return QIcon(icon_path)  # Utilisez QIcon pour charger l'image
    #     else:
    #         print(f"Erreur : L'icône est introuvable à {icon_path}")
    #         return QIcon()  # Retourne une icône vide par défaut