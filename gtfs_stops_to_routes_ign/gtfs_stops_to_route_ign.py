import pandas as pd
import requests
from collections import defaultdict
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
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
        # Couche stop_times
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_TRIP_FILE,
                self.tr("Couche stop_times (trip_id, stop_id, stop_sequence)"),
                types=[QgsProcessing.TypeVector],
            )
        )
        # Couche stops
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_STOP_FILE,
                self.tr("Couche stops (stop_id, stop_lat, stop_lon)"),
                types=[QgsProcessing.TypeVector],
            )
        )
        # Paramètre de sortie
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER, self.tr("Couche de sortie (itinéraires)")
            )
        )

    def source_to_dataframe(self, source):
        """Convertit une couche QGIS en un DataFrame pandas."""
        fields = [field.name() for field in source.fields()]
        data = []
        for feature in source.getFeatures():
            data.append(feature.attributes())
        return pd.DataFrame(data, columns=fields)

    def processAlgorithm(self, parameters, context, feedback):
        # Récupération des couches
        trip_source = self.parameterAsSource(parameters, self.INPUT_TRIP_FILE, context)
        stop_source = self.parameterAsSource(parameters, self.INPUT_STOP_FILE, context)

        if not trip_source or not stop_source:
            raise QgsProcessingException("Les couches d'entrée sont requises.")

        # Convertir les couches en DataFrame
        feedback.pushInfo("Conversion des couches en DataFrame...")
        trip_df = self.source_to_dataframe(trip_source)
        stop_df = self.source_to_dataframe(stop_source)

        feedback.pushInfo(f"stop_times contient {len(trip_df)} lignes.")
        feedback.pushInfo(f"stops contient {len(stop_df)} lignes.")

        # Validation des colonnes
        required_trip_cols = ["trip_id", "stop_id", "stop_sequence"]
        required_stop_cols = ["stop_id", "stop_lat", "stop_lon"]

        if not all(col in trip_df.columns for col in required_trip_cols):
            raise QgsProcessingException(
                f"La couche stop_times manque des colonnes nécessaires : {required_trip_cols}"
            )

        if not all(col in stop_df.columns for col in required_stop_cols):
            raise QgsProcessingException(
                f"La couche stops manque des colonnes nécessaires : {required_stop_cols}"
            )

        # Fusion des fichiers pour obtenir les coordonnées
        feedback.pushInfo("Fusion des couches stop_times et stops...")
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
        # Ajout des segments à la couche de sortie
        for trip_id, segments in trip_segments.items():
            trip_id = str(trip_id)
            # Vérification que trip_id n'est pas vide
            if not trip_id or trip_id.strip() == "":
                feedback.reportError(f"⚠️ trip_id vide détecté, remplacement par 'UNKNOWN'")
                trip_id = "UNKNOWN"

            # Vérification que segments contient bien des données
            if not segments or len(segments) == 0:
                feedback.reportError(f"⚠️ Aucun segment trouvé pour trip_id={trip_id}, ignoré.")
                continue  # Ignore cette entrée si aucun segment n'est disponible

            # Vérification supplémentaire : au moins un segment doit contenir au moins 2 points
            valid_segments = [
                [QgsPointXY(pt[0], pt[1]) for pt in segment] for segment in segments if len(segment) > 1
            ]

            if not valid_segments:
                feedback.reportError(f"⚠️ trip_id={trip_id} a des segments vides ou invalides, ignoré.")
                continue  # Ignore cette entrée si aucun segment n'est valide

            try:
                # Création de l'entité
                feature = QgsFeature(fields)
                
                # Création de la géométrie MultiLineString
                multiline = QgsGeometry.fromMultiPolylineXY(valid_segments)

                # Vérification que la géométrie est bien créée
                if not multiline or multiline.isEmpty():
                    feedback.reportError(f"⚠️ Géométrie invalide pour trip_id={trip_id}, ignorée.")
                    continue  # Ignore cette entité si la géométrie est invalide

                # Affectation des attributs
                feature.setGeometry(multiline)
                feature.setAttribute("trip_id", trip_id)

                # Ajout de l'entité à la couche de sortie
                sink.addFeature(feature, QgsFeatureSink.FastInsert)

            except Exception as e:
                feedback.reportError(f"❌ Erreur lors du traitement de trip_id={trip_id}: {e}")

        return {self.OUTPUT_LAYER: sink_id}

    def name(self):
        return "gtfs_route_ign"

    def displayName(self):
        return self.tr("GTFS to Route IGN")

    def group(self):
        return 'GTFS'

    def groupId(self):
        return 'GTFS'
    
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
            <p>Il est nécessaire d'ajouter les couches avec ""Ajouter une couche de texte délimité, afin de filtrer les trip_id si nécessaire</p>

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