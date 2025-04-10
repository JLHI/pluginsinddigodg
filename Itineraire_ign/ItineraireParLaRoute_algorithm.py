from qgis.PyQt.QtCore import QCoreApplication, QEventLoop
from qgis.core import (
    QgsProcessing,
    QgsFeatureSink,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingException,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsProcessingParameterField,
    QgsProcessingParameterEnum,
    QgsWkbTypes,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDefinition
)
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt5.QtCore import QVariant, QUrl
import json
import time  

class ItineraireParLaRouteAlgorithm(QgsProcessingAlgorithm):
    """
    Plugin QGIS pour calculer des itinéraires entre points avec options de buffer,
    reprojection, choix de champs d'identifiants, et filtrage par champs communs.
    """

    INPUT1 = 'INPUT1'
    INPUT2 = 'INPUT2'
    BUFFER_SIZE = 'BUFFER_SIZE'
    ID_FIELD1 = 'ID_FIELD1'
    ID_FIELD2 = 'ID_FIELD2'
    CKB_MODE = 'CKB_MODE'
    CKB_OPTI = 'CKB_OPTI'
    COMMON_FIELD1 = 'COMMON_FIELD1'
    COMMON_FIELD2 = 'COMMON_FIELD2'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config):
        """
        Définit les entrées et sorties de l'algorithme.
        """
        # Couche de départ
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT1,
                self.tr('Couche d’entrée 1 (Points de départ)'),
                [QgsProcessing.TypeVectorPoint]
            )
        )
        # Champ d’ID dans la couche de départ
        self.addParameter(
            QgsProcessingParameterField(
                self.ID_FIELD1,
                self.tr('Champ d’ID dans la couche 1'),
                parentLayerParameterName=self.INPUT1
            )
        )
        # Couche d’arrivée
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT2,
                self.tr('Couche d’entrée 2 (Points d’arrivée)'),
                [QgsProcessing.TypeVectorPoint]
            )
        )
        # Champ d’ID dans la couche d’arrivée
        self.addParameter(
            QgsProcessingParameterField(
                self.ID_FIELD2,
                self.tr('Champ d’ID dans la couche 2'),
                parentLayerParameterName=self.INPUT2
            )
        )
        # Taille du buffer optionnel
        advanced_param_buffer = QgsProcessingParameterNumber(
            self.BUFFER_SIZE,
            self.tr('Taille du buffer (optionnel, en mètre)'),
            defaultValue=0,
            optional=True
        )
        # Champs communs pour filtrer les entités
        advanced_param_communfield_1 = QgsProcessingParameterField(
            self.COMMON_FIELD1,
            self.tr('Champ commun dans la couche 1'),
            parentLayerParameterName=self.INPUT1,
            optional=True
        )
        advanced_param_communfield_2 = QgsProcessingParameterField(
            self.COMMON_FIELD2,
            self.tr('Champ commun dans la couche 2'),
            parentLayerParameterName=self.INPUT2,
            optional=True
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                'FILTER_MIN_DISTANCE',
                self.tr('Conserver uniquement la ligne avec la distance minimale pour chaque point de départ'),
                defaultValue=False
            )
        )
          # Choix de l'optimisation
        self.addParameter(
            QgsProcessingParameterEnum(
                self.CKB_OPTI,
                self.tr("Selectionnez l'optimisation"),
                options=["Le plus rapide", "Le plus court"],
                allowMultiple=False,  
                defaultValue= 1    
            )
        )
        # Choix du mode
        self.addParameter(
            QgsProcessingParameterEnum(
                self.CKB_MODE,
                self.tr("Selectionnez le mode"),
                options=["pieton", "Voiture"],
                allowMultiple=False,  
                defaultValue= 1    
            )
        )
        # Couche de sortie
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Couche de sortie (Itinéraires)')
            )
        )

        advanced_param_buffer.setFlags(advanced_param_buffer.flags() | QgsProcessingParameterDefinition.FlagOptional | QgsProcessingParameterDefinition.FlagAdvanced)
        advanced_param_communfield_1.setFlags(advanced_param_communfield_1.flags() | QgsProcessingParameterDefinition.FlagOptional | QgsProcessingParameterDefinition.FlagAdvanced)
        advanced_param_communfield_2.setFlags(advanced_param_communfield_2.flags() | QgsProcessingParameterDefinition.FlagOptional | QgsProcessingParameterDefinition.FlagAdvanced)

        self.addParameter(advanced_param_buffer)
        self.addParameter(advanced_param_communfield_1)
        self.addParameter(advanced_param_communfield_2)

    def processAlgorithm(self, parameters, context, feedback):
        """
        Logique principale du traitement.
        """
        # Chargement des sources et des paramètres
        source1 = self.parameterAsSource(parameters, self.INPUT1, context)
        source2 = self.parameterAsSource(parameters, self.INPUT2, context)
        buffer_size = self.parameterAsDouble(parameters, self.BUFFER_SIZE, context)
        id_field1 = self.parameterAsString(parameters, self.ID_FIELD1, context)
        id_field2 = self.parameterAsString(parameters, self.ID_FIELD2, context)
        mode = self.parameterAsString(parameters, self.CKB_MODE, context)
        opti = self.parameterAsString(parameters, self.CKB_OPTI, context)
        common_field1 = self.parameterAsString(parameters, self.COMMON_FIELD1, context)
        common_field2 = self.parameterAsString(parameters, self.COMMON_FIELD2, context)
        filter_min_distance = self.parameterAsBoolean(parameters, 'FILTER_MIN_DISTANCE', context)

        if source1 is None or source2 is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT1 or self.INPUT2))

        # Définir les systèmes de coordonnées
        crs_projected = QgsCoordinateReferenceSystem("EPSG:2154")  # Lambert 93
        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")  # WGS 84
        transform_to_projected = QgsCoordinateTransform(source1.sourceCrs(), crs_projected, context.transformContext())
        transform_to_projected2 = QgsCoordinateTransform(source2.sourceCrs(), crs_projected, context.transformContext())
        transform_to_wgs84 = QgsCoordinateTransform(crs_projected, crs_wgs84, context.transformContext())

        # Transformer les entités dans un système de coordonnées projeté
        features1 = [self.transformFeature(feature, transform_to_projected) for feature in source1.getFeatures()]
        features2 = [self.transformFeature(feature, transform_to_projected2) for feature in source2.getFeatures()]

        # Si les champs communs sont renseignés, on ne garde que les entités avec une valeur non nulle
        if common_field1 and common_field2:
            feedback.pushInfo("Filtrage par champ en commun")
            features1 = [feature for feature in features1 if feature[common_field1] is not None]
            features2 = [feature for feature in features2 if feature[common_field2] is not None]
        feedback.pushInfo(f"Avant association : {len(features1)} points de départ et {len(features2)} points d’arrivée.")

        # Calcul du nombre total d'itérations en fonction du filtrage par champ commun
        if common_field1 and common_field2:
            total_iterations = 0
            for f1 in features1:
                # Pour chaque point de départ, on ne garde que les points d’arrivée ayant le même id
                matches = [f for f in features2 if f[common_field2] == f1[common_field1]]
                # Si un buffer est défini, on applique en plus le test spatial
                if buffer_size > 0:
                    buffer_geom = f1.geometry().buffer(buffer_size, 10)
                    matches = [f for f in matches if buffer_geom.intersects(f.geometry())]
                total_iterations += len(matches)
        else:
            total_iterations = sum(
                len(features2) if buffer_size == 0 else len(
                    [f for f in features2 if feature.geometry().buffer(buffer_size, 10).intersects(f.geometry())]
                )
                for feature in features1
            )
        current_iteration = 0

        feedback.pushInfo(f"Le calcul démarre pour {total_iterations} itinéraires.")

        # Définir les champs de sortie
        fields = QgsFields()
        fields.append(QgsField('id_input1', QVariant.String))
        fields.append(QgsField('id_input2', QVariant.String))
        fields.append(QgsField('distance', QVariant.Double))
        fields.append(QgsField('duration', QVariant.Double))

        # Créer la couche de sortie
        sink, dest_id = self.parameterAsSink(parameters, self.OUTPUT, context, fields, QgsWkbTypes.LineString)

        output_features = []  # Liste temporaire pour stocker les entités
        mode = 'car' if mode == '1' else 'pedestrian'
        opti = 'shortest' if opti == '1' else 'fastest'

        last_progress = 0 
        # Boucle principale
        for i, feature1 in enumerate(features1):
            id1 = feature1[id_field1]
            # Détermination des points d’arrivée à traiter pour ce point de départ
            if common_field1 and common_field2:
                # Sélectionner uniquement les points d’arrivée avec le même id
                matches = [f for f in features2 if f[common_field2] == feature1[common_field1]]
                if buffer_size > 0:
                    buffer_geom = feature1.geometry().buffer(buffer_size, 10)
                    matches = [f for f in matches if buffer_geom.intersects(f.geometry())]
                intersecting_features2 = matches
            else:
                # Si pas de champ commun, appliquer éventuellement le filtre spatial
                if buffer_size > 0:
                    buffer_geom = feature1.geometry().buffer(buffer_size, 10)
                    intersecting_features2 = [f for f in features2 if buffer_geom.intersects(f.geometry())]
                else:
                    intersecting_features2 = features2

            # Pour chaque correspondance trouvée, calculer l'itinéraire
            for j, feature2 in enumerate(intersecting_features2):
                if feedback.isCanceled():
                    break
                time.sleep(0.222)
                id2 = feature2[id_field2]
                # Transformation des coordonnées pour l'API
                point1 = transform_to_wgs84.transform(feature1.geometry().asPoint())
                point2 = transform_to_wgs84.transform(feature2.geometry().asPoint())
             
                url = QUrl(f"https://data.geopf.fr/navigation/itineraire?resource=bdtopo-pgr&profile={mode}&start={point1.x()},{point1.y()}&end={point2.x()},{point2.y()}&optimization={opti}")
                request = QNetworkRequest(url)

                try:
                    response = self.makeRequest(request)
                    route_info = json.loads(response)
                    coordinates = route_info.get("geometry", {}).get("coordinates", [])
                    if coordinates:
                        route_points = [QgsPointXY(coord[0], coord[1]) for coord in coordinates]
                        line_geometry = QgsGeometry.fromPolylineXY(route_points)
                    else:
                        feedback.reportError(f"Aucune géométrie valide pour l'itinéraire entre {id1} et {id2}")
                        continue
                except Exception as e:
                    feedback.reportError(f"Échec de la récupération de l'itinéraire entre {id1} et {id2} : {e}")
                    continue

                new_feature = QgsFeature()
                new_feature.setGeometry(line_geometry)
                new_feature.setAttributes([
                    id1,
                    id2,
                    route_info.get("distance", 0),
                    route_info.get("duration", 0) / 60
                ])
                output_features.append(new_feature)

                # Mettre à jour la progression
                current_iteration += 1
                progress = int((current_iteration / total_iterations) * 100)
                if progress > last_progress:
                    feedback.setProgress(progress)
                    feedback.pushInfo(f"Progression : {progress}% - {current_iteration}/{total_iterations} itérations effectuées")
                    last_progress = progress

        # Optionnel : filtrer pour ne garder que l'itinéraire de distance minimale par point de départ
        if filter_min_distance:
            feedback.pushInfo("Filtrage des résultats pour conserver uniquement les distances minimales par id_input1...")
            min_distance_map = {}
            for feature in output_features:
                id1 = feature[0]
                distance = feature[2]
                if id1 not in min_distance_map or distance < min_distance_map[id1]['distance']:
                    min_distance_map[id1] = {'feature': feature, 'distance': distance}
            output_features = [data['feature'] for data in min_distance_map.values()]

        # Écrire les entités dans le sink
        for feature in output_features:
            sink.addFeature(feature, QgsFeatureSink.FastInsert)

        feedback.pushInfo("Traitement terminé.")
        return {self.OUTPUT: dest_id}

    def makeRequest(self, request):
        """
        Fonction pour effectuer des requêtes HTTP synchrones.
        """
        manager = QNetworkAccessManager()
        reply = manager.get(request)
        loop = QEventLoop()
        reply.finished.connect(loop.quit)
        loop.exec_()

        if reply.error() == QNetworkReply.NoError:
            return reply.readAll().data().decode()
        else:
            raise Exception(reply.errorString())

    def transformFeature(self, feature, transform):
        """
        Transformer la géométrie d’une entité avec QgsCoordinateTransform.
        """
        transformed_feature = QgsFeature(feature)
        geometry = feature.geometry()
        geometry.transform(transform)
        transformed_feature.setGeometry(geometry)
        return transformed_feature

    def name(self):
        return 'itineraireparlaroute'

    def displayName(self):
        return self.tr('Itinéraire')

    def group(self):
        return 'IGN'

    def groupId(self):
        return 'IGN'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ItineraireParLaRouteAlgorithm()
    
    def shortHelpString(self):
        return """
            <h3>Outil Inddigo : Itinéraire par la route</h3>
            <p>Ce plugin permet de calculer des itinéraires routiers entre des points de départ et d'arrivée provenant de deux couches de points distinctes.</p>
            <h4>Fonctionnalités principales :</h4>
            <ul>
                <li>Calcul des itinéraires entre deux couches de points via l'API IGN.</li>
                <li>Option de filtrage par champs communs (pour ne traiter que les itinéraires entre points ayant le même identifiant).</li>
                <li>Ajout d'un buffer optionnel pour limiter les calculs d'itinéraires aux entités proches.</li>
                <li>Choix de conserver uniquement l'itinéraire avec la distance minimale pour chaque point de départ.</li>
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
