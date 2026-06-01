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

# Helpers WFS partagés avec lidar_road_profile
from .lidar_road_profile import _difference_parcels


class GenerateTransectsAlgorithm(QgsProcessingAlgorithm):

    INPUT         = 'INPUT'
    LENGTH        = 'LENGTH'
    SPACING       = 'SPACING'
    SELECTED_ONLY = 'SELECTED_ONLY'
    CLIP_CADASTRE = 'CLIP_CADASTRE'
    OUTPUT        = 'OUTPUT'

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
            QgsProcessingParameterBoolean(
                self.CLIP_CADASTRE,
                self.tr(
                    'Clipper les transects sur les limites de parcelles IGN\n'
                    '(WFS Géoplateforme – nécessite une connexion internet)\n'
                    'Ajoute les champs largeur_parcelle et parcel_found.'
                ),
                defaultValue=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Transects')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        layer         = self.parameterAsVectorLayer(parameters, self.INPUT,         context)
        length        = self.parameterAsDouble(parameters,      self.LENGTH,        context)
        spacing       = self.parameterAsDouble(parameters,      self.SPACING,       context)
        selected_only = self.parameterAsBool(parameters,        self.SELECTED_ONLY, context)
        clip_cadastre = self.parameterAsBool(parameters,        self.CLIP_CADASTRE, context)

        crs_2154 = QgsCoordinateReferenceSystem('EPSG:2154')
        src_crs  = layer.sourceCrs()
        if src_crs != crs_2154:
            transform = QgsCoordinateTransform(src_crs, crs_2154, context.transformContext())
            feedback.pushInfo(self.tr(f'Reprojection de {src_crs.authid()} vers EPSG:2154'))
        else:
            transform = None

        fields = QgsFields()
        fields.append(QgsField('id_ligne',         QVariant.Int))
        fields.append(QgsField('distance',          QVariant.Double))
        fields.append(QgsField('largeur_parcelle',  QVariant.Double))  # −1 si indispo
        fields.append(QgsField('parcel_found',      QVariant.Int))     # 1 = clippé

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context,
            fields, QgsWkbTypes.LineString, crs_2154
        )

        features = list(layer.selectedFeatures() if selected_only else layer.getFeatures())
        total    = len(features)
        n_clipped, n_fallback = 0, 0

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
                    if feedback.isCanceled():
                        break

                    pt = part.interpolate(d).asPoint()

                    eps       = min(0.1, line_length / 100.0)
                    pt_before = part.interpolate(max(0.0,         d - eps)).asPoint()
                    pt_after  = part.interpolate(min(line_length, d + eps)).asPoint()

                    dx   = pt_after.x() - pt_before.x()
                    dy   = pt_after.y() - pt_before.y()
                    norm = math.sqrt(dx * dx + dy * dy)

                    if norm > 0:
                        # Vecteur perpendiculaire unitaire (rotation 90°)
                        px = -dy / norm
                        py =  dx / norm

                        half = length / 2.0
                        # Extrémités du transect brut (avant clip)
                        raw_p1 = QgsPointXY(pt.x() + px * half, pt.y() + py * half)
                        raw_p2 = QgsPointXY(pt.x() - px * half, pt.y() - py * half)

                        out_p1           = raw_p1
                        out_p2           = raw_p2
                        largeur_parcelle = float(-1.0)
                        parcel_found     = int(0)

                        # ── Clip cadastral ───────────────────────────────────
                        if clip_cadastre:
                            buf  = max(5.0, length * 0.10)
                            xmin = min(raw_p1.x(), raw_p2.x()) - buf
                            ymin = min(raw_p1.y(), raw_p2.y()) - buf
                            xmax = max(raw_p1.x(), raw_p2.x()) + buf
                            ymax = max(raw_p1.y(), raw_p2.y()) + buf

                            raw_geom = QgsGeometry.fromPolylineXY([raw_p1, raw_p2])
                            clipped  = _difference_parcels(
                                raw_geom, xmin, ymin, xmax, ymax
                            )

                            if clipped is not None and not clipped.isEmpty():
                                # Prendre le segment le plus long si multipart
                                if clipped.isMultipart():
                                    parts = clipped.asMultiPolyline()
                                    best  = max(
                                        parts,
                                        key=lambda pts: QgsGeometry.fromPolylineXY(pts).length()
                                    )
                                else:
                                    best = clipped.asPolyline()

                                out_p1           = best[0]
                                out_p2           = best[-1]
                                road_geom        = QgsGeometry.fromPolylineXY(best)
                                largeur_parcelle = float(round(road_geom.length(), 3))
                                parcel_found     = int(1)
                                n_clipped       += 1
                            else:
                                n_fallback += 1

                        transect = QgsFeature(fields)
                        transect.setGeometry(QgsGeometry.fromPolylineXY([out_p1, out_p2]))
                        transect.setAttributes([
                            int(feature.id()),
                            float(round(d, 3)),
                            largeur_parcelle,
                            parcel_found,
                        ])
                        sink.addFeature(transect)

                    d += spacing

        if clip_cadastre:
            feedback.pushInfo(
                f'Clip cadastral : {n_clipped} transect(s) clippé(s), '
                f'{n_fallback} en fallback (longueur brute conservée)'
            )

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
            'Génère des transects perpendiculaires le long d\'une couche de lignes.\n\n'
            'Paramètres :\n'
            '- Longueur : longueur maximale du transect brut (10–50 m)\n'
            '- Espacement : pas entre deux transects (défaut 10 m)\n'
            '- Clip cadastral : interroge le WFS cadastre IGN pour trouver les\n'
            '  limites de parcelles sur chaque transect et clippe la géométrie\n'
            '  en sortie. Le transect clippé = largeur parcelle à parcelle réelle.\n'
            '  Si aucun croisement n\'est trouvé, la longueur brute est conservée.\n\n'
            'Champs en sortie :\n'
            '- id_ligne : identifiant de la ligne source\n'
            '- distance : position le long de la ligne (m)\n'
            '- largeur_parcelle : largeur après clip cadastral (−1 si non clippé)\n'
            '- parcel_found : 1 = transect clippé, 0 = longueur brute\n\n'
            'Note : avec le clip cadastral actif, l\'algorithme "Profil de chaussée"\n'
            'peut désactiver son propre appel WFS cadastre (USE_CADASTRE = Non),\n'
            'car les transects sont déjà à la bonne longueur.'
        )

    def createInstance(self):
        return GenerateTransectsAlgorithm()

    def tr(self, string):
        return QCoreApplication.translate('GenerateTransectsAlgorithm', string)
