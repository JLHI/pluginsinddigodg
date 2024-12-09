import requests
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterEnum,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFeatureSink,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsProcessingException,
    QgsFeatureSink,
    QgsProcessing,
    QgsFields
)

class IsochroneIgnAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    MODE = "MODE"
    TYPE = "TYPE"
    VALEUR = "VALEUR"
    BUFFER = "BUFFER"
    OUTPUT = "OUTPUT"

    def initAlgorithm(self, config):
        """
        Définit les paramètres de l'algorithme.
        """
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr("Couche d’entrée (Points de départ)"),
                [QgsProcessing.TypeVectorPoint]
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.MODE,
                self.tr("Mode de transport"),
                options=["Voiture", "Piéton"],
                defaultValue=0
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.TYPE,
                self.tr("Type de coût (Temps ou distance)"),
                options=["Temps", "Distance"],
                defaultValue=0
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.VALEUR,
                self.tr("Valeur du coût (minutes ou mètres)"),
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=20
            )
        )
   

        self.addParameter(
            QgsProcessingParameterNumber(
                self.BUFFER,
                self.tr("Taille du buffer (en mètres)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0,
                optional=True
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr("Isochrone de sortie")
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """
        Logique principale du traitement.
        """
        source = self.parameterAsSource(parameters, self.INPUT, context)
        mode = self.parameterAsEnum(parameters, self.MODE, context)
        cost_type = self.parameterAsEnum(parameters, self.TYPE, context)
        cost_value = self.parameterAsInt(parameters, self.VALEUR, context) 
        buffer_size = self.parameterAsDouble(parameters, self.BUFFER, context)

        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
                    
        feedback.pushInfo(f'type {cost_type}')

        if cost_type == 0 : 
            cost_value = cost_value *60

        # Vérification du CRS de la couche
        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        source_crs = source.sourceCrs()
        transform_to_wgs84 = None

        if source_crs != crs_wgs84:
            feedback.pushInfo("La couche n'est pas en WGS84. Transformation en cours...")
            transform_to_wgs84 = QgsCoordinateTransform(source_crs, crs_wgs84, context.transformContext())
        else:
            transform_to_wgs84 = None
            feedback.pushInfo("La couche est déjà en WGS84.")

        # Définir la couche de sortie avec les champs dynamiques
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            source.fields(),  # Liste des champs sans géométrie
            QgsWkbTypes.Polygon,  # Géométrie de type Polygone
            crs_wgs84  # CRS pour la couche de sortie
        )

        # Vérifier si la couche source est correctement définie
        if sink is None:
            raise QgsProcessingException("Erreur lors de la création de la couche de sortie.")

        # Traiter chaque entité
        for feature in source.getFeatures():
            geom = feature.geometry()

            # Vérification : la géométrie doit être non vide et un Point
            if geom.isEmpty() or geom.wkbType() != QgsWkbTypes.Point:
                feedback.reportError(f"Entité {feature.id()} ignorée : géométrie invalide ou non ponctuelle.")
                continue

            # Transformer la géométrie en WGS84 si nécessaire
            if transform_to_wgs84:
                geom.transform(transform_to_wgs84)

            # Récupérer les coordonnées pour la requête API
            point = geom.asPoint()
            lon, lat = point.x(), point.y()

            # Construire l'URL pour la requête
            modes = ["car", "pedestrian"]
            types = ["time", "distance"]

            url = (
                f"https://data.geopf.fr/navigation/isochrone?"
                f"resource=bdtopo-valhalla&profile={modes[mode]}&costType={types[cost_type]}&"
                f"point={lon},{lat}&costValue={cost_value}"
            )
            feedback.pushInfo(f"Requête URL : {url}")

            # Envoyer la requête
            try:
                response = requests.get(url)
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as e:
                feedback.reportError(f"Erreur lors de la requête pour l'entité {feature.id()} : {e}")
                continue

            # Extraire le polygone de la réponse
            try:
                coordinates = data["geometry"]["coordinates"][0]
                polygon = QgsGeometry.fromPolygonXY([[QgsPointXY(*coord) for coord in coordinates]])
            except KeyError as e:
                feedback.reportError(f"Données de géométrie manquantes dans la réponse pour l'entité {feature.id()} : {e}")
                continue

            # Vérifier si un buffer doit être appliqué
            if buffer_size > 0:
                # Transformer en CRS métrique (par exemple EPSG:2154 pour Lambert 93)
                crs_projected = QgsCoordinateReferenceSystem("EPSG:2154")
                transform_to_projected = QgsCoordinateTransform(crs_wgs84, crs_projected, context.transformContext())
                transform_to_wgs84_back = QgsCoordinateTransform(crs_projected, crs_wgs84, context.transformContext())

                # Appliquer la transformation pour buffer
                polygon.transform(transform_to_projected)
                polygon = polygon.buffer(buffer_size, segments=360)

                # Revenir au CRS WGS84
                polygon.transform(transform_to_wgs84_back)

            # Ajouter l'entité dans la couche de sortie
            new_feature = QgsFeature(source.fields())  # Créer une nouvelle entité avec les champs définis
            new_feature.setAttributes([feature[field.name()] for field in source.fields()])  # Copier les attributs filtrés
            new_feature.setGeometry(polygon)  # Ajouter la géométrie résultante
            sink.addFeature(new_feature, QgsFeatureSink.FastInsert)

        feedback.pushInfo("Traitement terminé avec succès.")
        return {self.OUTPUT: dest_id}

    def name(self):
        return 'isochrone'

    def displayName(self):
        return self.tr('Isochrone')

    def group(self):
        return 'IGN'

    def groupId(self):
        return 'IGN'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return IsochroneIgnAlgorithm()
    
    def shortHelpString(self):
        """
        Retourne le texte d'aide pour l'outil.
        """
        return """
            <h3>Outil Inddigo : Itinéraire par la route</h3>
            <p>Ce plugin permet de calculer des itinéraires routiers entre des points de départ et d'arrivée provenant de deux couches de points distinctes.</p>
            <h4>Fonctionnalités principales :</h4>
            <ul>
                <li>Calcul des itinéraires entre deux couches de points via l'API IGN.</li>
                <li>Option de filtrage par champs communs entre les deux couches.</li>
                <li>Ajout d'un buffer optionnel pour limiter les calculs d'itinéraires aux entités proches.</li>
                <li>Choix de conserver uniquement l'itinéraire avec la distance minimale pour chaque point de départ.</li>
            </ul>
            <h4>Paramètres :</h4>
            <ul>
                <li><b>Couche d’entrée 1 (Points de départ) :</b> La première couche de points utilisée comme points de départ.</li>
                <li><b>Champ d’ID dans la couche 1 :</b> Champ identifiant les entités de la première couche.</li>
                <li><b>Couche d’entrée 2 (Points d’arrivée) :</b> La deuxième couche de points utilisée comme points d’arrivée.</li>
                <li><b>Champ d’ID dans la couche 2 :</b> Champ identifiant les entités de la deuxième couche.</li>
                <li><b>Choix du mode :</b> Pieton ou voiture.</li>
                <li><b>Taille du buffer (optionnel) :</b> Taille du buffer pour limiter les calculs d’itinéraires.</li>
                <li><b>Champs communs (optionnels) :</b> Champs à utiliser pour filtrer les points des deux couches.</li>
                <li><b>Conserver uniquement la ligne avec la distance minimale :</b> Permet de n’exporter que l’itinéraire le plus court pour chaque point de départ.</li>
                <li><b>Couche de sortie (Itinéraires) :</b> La couche résultante contenant les itinéraires calculés.</li>
            </ul>
            <h4>Résultats :</h4>
            <p>Le plugin génère une couche contenant les itinéraires sous forme de lignes, avec les attributs suivants :</p>
            <ul>
                <li><b>id_input1 :</b> Identifiant de la couche 1 (point de départ).</li>
                <li><b>id_input2 :</b> Identifiant de la couche 2 (point d’arrivée).</li>
                <li><b>distance :</b> Distance de l’itinéraire en mètres.</li>
                <li><b>duration :</b> Durée de l’itinéraire en secondes.</li>
            </ul>
        """
