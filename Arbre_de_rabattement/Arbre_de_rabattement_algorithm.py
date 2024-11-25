# -*- coding: utf-8 -*-

import hashlib
import processing

# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProcessing, QgsFeatureSink, QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer, QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink, QgsWkbTypes, QgsProcessingProvider
)
from qgis.PyQt.QtGui import QIcon

import processing,os

class ArbreDeRabattementAlgorithm(QgsProcessingAlgorithm):
    """Aglo arbre de rabattement
    """
    # Déclaration des paramètres
    ROUTES_LAYER = 'ROUTES_LAYER'
    COUNT_FIELD = 'COUNT_FIELD'
    SUM_FIELD = 'SUM_FIELD'
    OUTPUT_LAYER = 'OUTPUT_LAYER'

    def initAlgorithm(self, config=None):
        # Paramètre pour la sélection de la couche itinéraires
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.ROUTES_LAYER,
                self.tr('Couche Itinéraires (Projet)'),
                [QgsProcessing.TypeVectorLine],
                optional=False
            )
        )
        # Paramètre pour le champ à utiliser pour le `count`
        self.addParameter(
            QgsProcessingParameterField(
                self.COUNT_FIELD,
                self.tr('Champ pour Count (Couche Itinéraires)'),
                parentLayerParameterName=self.ROUTES_LAYER,
                type=QgsProcessingParameterField.Numeric,
                optional=False
            )
        )
        # Paramètre pour le champ à utiliser pour la somme
        self.addParameter(
            QgsProcessingParameterField(
                self.SUM_FIELD,
                self.tr('Champ pour la Somme (optionnel, Couche Itinéraires)'),
                parentLayerParameterName=self.ROUTES_LAYER,
                type=QgsProcessingParameterField.Numeric,
                optional=True
            )
        )
        # Paramètre de la couche de sortie
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_LAYER,
                self.tr('Couche de sortie après découpage et agrégation')
            )
        )
      
    def processAlgorithm(self, parameters, context, feedback):
        # Récupérer les couches et champs
        routes_layer = self.parameterAsVectorLayer(parameters, self.ROUTES_LAYER, context)
        count_field_name = self.parameterAsString(parameters, self.COUNT_FIELD, context)
        sum_field_name = self.parameterAsString(parameters, self.SUM_FIELD, context) if self.parameterAsString(parameters, self.SUM_FIELD, context) else None

        feedback.pushInfo(f"Couche itinéraires sélectionnée : {routes_layer.name()}")
        feedback.pushInfo(f"Champ de comptage utilisé : {count_field_name}")
        if sum_field_name:
            feedback.pushInfo(f"Champ pour la somme : {sum_field_name}")

        # Étape 1 : Exploser les lignes
        feedback.pushInfo("Étape 1 : Exploser les lignes...")
        exploded_params = {
            'INPUT': routes_layer,
            'OUTPUT': 'memory:exploded_lines'
        }
        exploded_layer = processing.run('native:explodelines', exploded_params, context=context, feedback=feedback)['OUTPUT']

        # Étape 2 : Agrégation par concat(x_min($geometry), '-', y_max($geometry))
        feedback.pushInfo("Étape 2 : Agrégation des lignes...")
        aggregate_params = {
            'INPUT': exploded_layer,
            'GROUP_BY': 'concat(x_min($geometry),\'-\',y_max($geometry))',
            'AGGREGATES': [
                {'aggregate': 'count', 'input': count_field_name, 'name': 'count_field', 'type': QVariant.Int},
                {'aggregate': 'sum', 'input': sum_field_name, 'name': 'sum_field', 'type': QVariant.Double} if sum_field_name else None
            ],
            'OUTPUT': 'memory:aggregated_layer'
        }
        # Filtrer les agrégats pour éviter None
        aggregate_params['AGGREGATES'] = [agg for agg in aggregate_params['AGGREGATES'] if agg is not None]
        aggregated_layer = processing.run('native:aggregate', aggregate_params, context=context, feedback=feedback)['OUTPUT']

        # Étape 3 : Créer la couche de sortie
        feedback.pushInfo("Étape 3 : Création de la couche de sortie...")
        (sink, dest_id) = self.parameterAsSink(parameters, self.OUTPUT_LAYER, context, aggregated_layer.fields(), QgsWkbTypes.LineString, aggregated_layer.crs())

        # Ajouter les entités agrégées à la couche de sortie
        for feature in aggregated_layer.getFeatures():
            sink.addFeature(feature, QgsFeatureSink.FastInsert)

        feedback.pushInfo("Traitement terminé. Couche de sortie créée avec les segments d'itinéraires agrégés.")

       


   

    def name(self):
        return 'split_itineraries_with_aggregation'

    def displayName(self):
        return self.tr('Arbre de rabattement')

    def group(self):
        return "Les plugins non restreint du pôle DG d\'Inddigo" 

    def groupId(self):
        return 'Les plugins non restreint du pôle DG d\'Inddigo'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ArbreDeRabattementAlgorithm()
    def shortHelpString(self):
        """
        Retourne le texte d'aide pour l'outil.
        """
        return """
            <h3>Outil Arbre de Rabattement</h3>
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
    def icon(self):
        """
        Retourne une icône personnalisée pour cet algorithme.
        """
        icon_path = os.path.join(os.path.dirname(__file__), "icon_arbre.png")
        if os.path.exists(icon_path):
            return QIcon(icon_path)  # Utilisez QIcon pour charger l'image
        else:
            print(f"Erreur : L'icône est introuvable à {icon_path}")
            return QIcon()  # Retourne une icône vide par défaut