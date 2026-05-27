# -*- coding: utf-8 -*-

__author__ = 'JLHI'
__date__ = '2026-05-22'

import math

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFeatureSink,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsFields,
    QgsField,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant


class GenerateTransectsAlgorithm(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    LENGTH = 'LENGTH'
    SPACING = 'SPACING'
    SELECTED_ONLY = 'SELECTED_ONLY'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                self.tr('Couche de lignes'),
                [QgsProcessing.TypeVectorLine]
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.SELECTED_ONLY,
                self.tr('Entités sélectionnées uniquement'),
                defaultValue=False
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.LENGTH,
                self.tr('Longueur des transects (m)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=30.0,
                minValue=10.0,
                maxValue=50.0
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SPACING,
                self.tr('Espacement entre transects (m)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=10.0,
                minValue=1.0
            )
        )
       
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Transects')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        length = self.parameterAsDouble(parameters, self.LENGTH, context)
        spacing = self.parameterAsDouble(parameters, self.SPACING, context)
        selected_only = self.parameterAsBool(parameters, self.SELECTED_ONLY, context)

        crs_2154 = QgsCoordinateReferenceSystem('EPSG:2154')
        src_crs = layer.sourceCrs()
        if src_crs != crs_2154:
            transform = QgsCoordinateTransform(src_crs, crs_2154, context.transformContext())
            feedback.pushInfo(self.tr(f'Reprojection de {src_crs.authid()} vers EPSG:2154'))
        else:
            transform = None

        fields = QgsFields()
        fields.append(QgsField('id_ligne', QVariant.Int))
        fields.append(QgsField('distance', QVariant.Double))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context,
            fields, QgsWkbTypes.LineString, crs_2154
        )

        features = list(layer.selectedFeatures() if selected_only else layer.getFeatures())
        total = len(features)

        for i, feature in enumerate(features):
            if feedback.isCanceled():
                break
            feedback.setProgress(int(i / total * 100))

            geom = feature.geometry()
            if transform is not None:
                geom.transform(transform)
            if geom is None or geom.isEmpty():
                continue

            if geom.isMultipart():
                parts = [QgsGeometry.fromPolylineXY(p) for p in geom.asMultiPolyline()]
            else:
                parts = [QgsGeometry.fromPolylineXY(geom.asPolyline())]

            for part in parts:
                line_length = part.length()
                if line_length == 0:
                    continue

                d = 0.0
                while d <= line_length:
                    pt = part.interpolate(d).asPoint()

                    eps = min(0.1, line_length / 100.0)
                    pt_before = part.interpolate(max(0.0, d - eps)).asPoint()
                    pt_after = part.interpolate(min(line_length, d + eps)).asPoint()

                    dx = pt_after.x() - pt_before.x()
                    dy = pt_after.y() - pt_before.y()
                    norm = math.sqrt(dx * dx + dy * dy)

                    if norm > 0:
                        # Vecteur perpendiculaire unitaire (rotation 90°)
                        px = -dy / norm
                        py = dx / norm

                        half = length / 2.0
                        p1 = QgsPointXY(pt.x() + px * half, pt.y() + py * half)
                        p2 = QgsPointXY(pt.x() - px * half, pt.y() - py * half)

                        transect = QgsFeature(fields)
                        transect.setGeometry(QgsGeometry.fromPolylineXY([p1, p2]))
                        transect.setAttributes([feature.id(), round(d, 3)])
                        sink.addFeature(transect)

                    d += spacing

        return {self.OUTPUT: dest_id}

    def name(self):
        return 'generer_transects'

    def displayName(self):
        return self.tr('Générer des transects perpendiculaires')

    def group(self):
        return self.tr('LiDAR')

    def groupId(self):
        return 'lidar'

    def shortHelpString(self):
        return self.tr(
            'Génère des transects perpendiculaires le long d\'une couche de lignes ou multilignes.\n\n'
            'Paramètres :\n'
            '- Couche de lignes : lignes ou multilignes en entrée\n'
            '- Longueur des transects : longueur totale en mètres (10–50 m, défaut 30 m)\n'
            '- Espacement : distance entre deux transects consécutifs le long de la ligne (défaut 10 m)\n\n'
            'Chaque transect est centré sur le point d\'échantillonnage et orienté perpendiculairement '
            'à la direction locale de la ligne.\n\n'
            'Note : la couche d\'entrée doit être dans un SCR projeté (mètres).'
        )

    def createInstance(self):
        return GenerateTransectsAlgorithm()

    def tr(self, string):
        return QCoreApplication.translate('GenerateTransectsAlgorithm', string)
