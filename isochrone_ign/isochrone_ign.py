import requests
from qgis.PyQt.QtCore import QCoreApplication,QVariant
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
    QgsProcessingParameterString,QgsField
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
            QgsProcessingParameterString(
                self.VALEUR,
                "Tranches de durée (en minutes,ou en mètre, séparées par des virgules, ex: 5,10,15)",
                defaultValue="20"
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
        duration_ranges = self.parameterAsString(parameters, self.VALEUR, context)
        buffer_size = self.parameterAsDouble(parameters, self.BUFFER, context)

        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
                    
        feedback.pushInfo(f'type {cost_type}')

        #transformer les valeur string en int, et multiplier par 60 quand le type de cout est le temps
        try:
            cost_value_list = [int(x.strip()) for x in duration_ranges.split(",")]
            cost_value_list.sort()
        except ValueError:
            raise QgsProcessingException("Les tranches de durée doivent être des nombres entiers séparés par des virgules.")
        if cost_type == 0 : 
            cost_value_list = [x * 60 for x in cost_value_list]
            cost_value_list.sort()

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

       
        fields = source.fields()
        fields.append(QgsField("mode", QVariant.String))
        fields.append(QgsField("cost_type", QVariant.String))
        fields.append(QgsField("cost_value", QVariant.Int))

        # Définir la couche de sortie avec les champs dynamiques
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,  # Liste des champs sans géométrie
            QgsWkbTypes.Polygon,  # Géométrie de type Polygone
            crs_wgs84  # CRS pour la couche de sortie
        )        # Vérifier si la couche source est correctement définie
        if sink is None:
            raise QgsProcessingException("Erreur lors de la création de la couche de sortie.")

        # Traiter chaque entité
        for feature in source.getFeatures():
            for cost_value in cost_value_list : 
                geom = feature.geometry()

                # Vérification : la géométrie doit être non vide et un Point
                if geom.isEmpty() or QgsWkbTypes.flatType(geom.wkbType()) != QgsWkbTypes.Point:
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
                new_feature = QgsFeature(fields)
                new_attributes = [feature[field.name()] for field in source.fields()]  # Copier les attributs existants
                new_attributes.extend([modes[mode], types[cost_type], cost_value])  # Ajouter mode, cost_type et cost_value
                new_feature.setAttributes(new_attributes)
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
            <h3>Outil Isochrone</h3>
            <p>Ce plugin calcule des isochrones.</p>
            
            <h4>Fonctionnalités principales :</h4>
            <ul>
                <li>Mode de transport : voiture ou piéton.</li>
                <li>Type de coût : temps (minutes) ou distance (mètres).</li>
                <li>Possibilité d'ajouter un buffer (tampon) autour des isochrones générés.</li>
                <li>Les isochrones sont calculés via l'API IGN et exportés sous forme de polygones géographiques.</li>
            </ul>
            
            <h4>Paramètres :</h4>
            <ul>
                <li><b>Couche d’entrée (Points de départ) :</b> Les points utilisés comme centres pour les calculs d’isochrones.</li>
                <li><b>Mode de transport :</b> Choisissez entre voiture et piéton.</li>
                <li><b>Type de coût :</b> Temps (en minutes) ou distance (en mètres).</li>
                <li><b>Valeur du coût :</b> Durée ou distance maximale pour générer l'isochrone.</li>
                <li><b>Taille du buffer :</b> Option pour ajouter un tampon autour des isochrones générés.</li>
            </ul>
            
            <h4>Résultats :</h4>
            <p>L'outil génère une couche de polygones représentant les isochrones autour des points de départ.</p>
            <ul>
                <li><b>Zones accessibles :</b> Chaque polygone représente la zone atteignable en fonction du coût choisi.</li>
                <li><b>Attributs copiés :</b> Les attributs des entités sources sont conservés dans la couche de sortie.</li>
            </ul>
            
            
        """
