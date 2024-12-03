from qgis.PyQt.QtCore import QCoreApplication, QVariant

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
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
    INPUT_TRIP_FILE = 'INPUT_TRIP_FILE'
    INPUT_STOP_FILE = 'INPUT_STOP_FILE'
    OUTPUT_LAYER = 'OUTPUT_LAYER'

    def initAlgorithm(self, config=None):
        # Paramètre pour le fichier stops_time (trip_id et stop_sequence)
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_TRIP_FILE,
                self.tr("Fichier stops_time (trip_id et stop_sequence)"),
                types=[QgsProcessing.TypeVector]
            )
        )
        # Paramètre pour le fichier stops (stop_id, stop_lat, stop_lon)
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_STOP_FILE,
                self.tr("Fichier stops (stop_id, stop_lat, stop_lon)"),
                types=[QgsProcessing.TypeVector]
            )
        )
        # Paramètre de sortie
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER,
                self.tr("Couche de sortie (itinéraires)")
            )
        )

    def detect_fields(self, columns, field_candidates):
        """Détecte automatiquement un champ donné parmi les colonnes disponibles."""
        for candidate in field_candidates:
            if candidate in columns:
                return candidate
        raise QgsProcessingException(f"Impossible de détecter un champ parmi : {', '.join(field_candidates)}")

    def processAlgorithm(self, parameters, context, feedback):
        # Récupération des sources d'entrée
        trip_source = self.parameterAsSource(parameters, self.INPUT_TRIP_FILE, context)
        stop_source = self.parameterAsSource(parameters, self.INPUT_STOP_FILE, context)

        if not trip_source or not stop_source:
            raise QgsProcessingException(self.tr("Les fichiers d'entrée sont requis."))

        # Convertir les sources en DataFrame
        feedback.pushInfo("Chargement des données...")
        trip_df = self.source_to_dataframe(trip_source)
        stop_df = self.source_to_dataframe(stop_source)

        # Détection automatique des champs
        feedback.pushInfo("Détection des champs...")
        trip_id_field = self.detect_fields(trip_df.columns, ['trip_id', 'id_trip'])
        stop_sequence_field = self.detect_fields(trip_df.columns, ['stop_sequence', 'sequence'])
        stop_id_field = self.detect_fields(trip_df.columns, ['stop_id'])

        stop_lat_field = self.detect_fields(stop_df.columns, ['stop_lat', 'latitude'])
        stop_lon_field = self.detect_fields(stop_df.columns, ['stop_lon', 'longitude'])
        stop_id_in_stop_file = self.detect_fields(stop_df.columns, ['stop_id'])

        feedback.pushInfo(f"Champs détectés : trip_id={trip_id_field}, stop_sequence={stop_sequence_field}, "
                          f"stop_id={stop_id_field}, stop_lat={stop_lat_field}, stop_lon={stop_lon_field}")

        # Fusion des deux DataFrames
        feedback.pushInfo("Fusion des fichiers...")
        merged_df = trip_df.merge(stop_df, left_on=stop_id_field, right_on=stop_id_in_stop_file)

        trip_segments = defaultdict(list)
        result = []

        # Génération des segments d'itinéraires
        for i in range(len(merged_df)):
            trip_id = merged_df.loc[i, trip_id_field]
            stop_sequence = merged_df.loc[i, stop_sequence_field]
            xy_depart = (merged_df.loc[i, stop_lat_field], merged_df.loc[i, stop_lon_field])

            if i + 1 < len(merged_df) and merged_df.loc[i + 1, trip_id_field] == trip_id:
                xy_arrivee = (merged_df.loc[i + 1, stop_lat_field], merged_df.loc[i + 1, stop_lon_field])
            else:
                xy_arrivee = None

            result.append([trip_id, stop_sequence, xy_depart, xy_arrivee])

        for trip_id, stop_sequence, xy_depart, xy_arrivee in result:
            if xy_arrivee:
                try:
                    api_url = (
                        f"https://data.geopf.fr/navigation/itineraire?"
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
                    feedback.reportError(f"Erreur sur le segment {trip_id}: {e}")

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
            multiline = QgsGeometry.fromMultiPolylineXY(
                [[QgsPointXY(pt[0], pt[1]) for pt in segment] for segment in segments]
            )
            feature.setGeometry(multiline)
            feature.setAttribute("trip_id", trip_id)
            sink.addFeature(feature, QgsFeatureSink.FastInsert)

        return {self.OUTPUT_LAYER: sink_id}

    def source_to_dataframe(self, source):
        """Convert a QGIS vector source to a Pandas DataFrame."""
        fields = [field.name() for field in source.fields()]
        data = []
        for feature in source.getFeatures():
            data.append(feature.attributes())
        return pd.DataFrame(data, columns=fields)



    def name(self):
        return 'GTFS to Route IGN'

    def displayName(self):
        return self.tr('GTFS to Route IGN')

    def group(self):
        return "Les plugins non restreint du pôle DG d\'Inddigo" 

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
            <h3>Outil Inddigo : GTFS to Route IGN'</h3>
            <p>Ce plugin permet de :</p>
            <ul>
                <li>Exploser des lignes en segments individuels</li>
                <li>Agréger les segments en utilisant un champ de comptage et, éventuellement, un champ de somme</li>
                <li>Regrouper les données géographiques en fonction de leurs coordonnées</li>
            </ul>
            <h4>Paramètres</h4>
            <ul>
                <li><b>Couche Itinéraires :</b> La couche contenant les lignes à traiter.</li>
                <li><b>Champ pour Count :</b> Champ utilisé pour compter les occurrences.</li>
                <li><b>Champ pour la Somme :</b> (Optionnel) Champ utilisé pour sommer les valeurs.</li>
            </ul>
            <p>Le résultat est une couche contenant les lignes agrégées avec les statistiques calculées.</p>
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