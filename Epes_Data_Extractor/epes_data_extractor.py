# -*- coding: utf-8 -*-
__author__ = 'JL HUMBERT'
__date__ = '2022-11-25'
__copyright__ = '(C) 2022 by JL HUMBERT'

import os
import traceback

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFile,
    QgsProcessingException,
    QgsProcessing,
    QgsProject,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
)

from .sources import DEFAULT_CONFIG
from .connectors import fetch_source, save_layer_as_gpkg


# ---------- Géométrie ----------

def make_buffer_lambert(geom, input_crs, distance_m):
    """Retourne le buffer en EPSG:2154 (mètres)."""
    lambert = QgsCoordinateReferenceSystem('EPSG:2154')
    from qgis.core import QgsGeometry as _QgsGeometry
    g = _QgsGeometry(geom)
    if input_crs.authid() != 'EPSG:2154':
        tr = QgsCoordinateTransform(input_crs, lambert, QgsProject.instance())
        g.transform(tr)
    return g.buffer(distance_m, 64)


def centroid_wgs84(geom_lambert):
    """Retourne le centroïde du buffer (lambert) en WGS84."""
    lambert = QgsCoordinateReferenceSystem('EPSG:2154')
    wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
    tr = QgsCoordinateTransform(lambert, wgs84, QgsProject.instance())
    return tr.transform(geom_lambert.centroid().asPoint())


# ---------- Algorithme ----------

class AutoDataPrepAlgorithm(QgsProcessingAlgorithm):

    INPUT_POLYGON = 'INPUT_POLYGON'
    BUFFER_DISTANCE = 'BUFFER_DISTANCE'
    GROUP_COMMUNS = 'GROUP_COMMUNS'
    LAYERS_COMMUNS = 'LAYERS_COMMUNS'
    GROUP_PAYSAGE = 'GROUP_PAYSAGE'
    LAYERS_PAYSAGE = 'LAYERS_PAYSAGE'
    GROUP_EIE = 'GROUP_EIE'
    LAYERS_EIE = 'LAYERS_EIE'
    OUTPUT_FOLDER = 'OUTPUT_FOLDER'

    def initAlgorithm(self, config=None):  # noqa: ARG002
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_POLYGON,
                'Couche de polygone (emprise)',
                [QgsProcessing.TypeVectorPolygon]
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.BUFFER_DISTANCE,
                'Distance de buffer (m)',
                type=QgsProcessingParameterNumber.Double,
                defaultValue=25000.0,
                minValue=0.0
            )
        )

        # --- Communs ---
        self.addParameter(QgsProcessingParameterBoolean(self.GROUP_COMMUNS, 'Groupe : Communs', defaultValue=True))
        communs = [s['name'] for s in DEFAULT_CONFIG['groups']['Communs']['sources']]
        self.addParameter(QgsProcessingParameterEnum(
            self.LAYERS_COMMUNS, '  Couches Communs à extraire',
            options=communs, allowMultiple=True, defaultValue=list(range(len(communs)))
        ))

        # --- Paysage ---
        self.addParameter(QgsProcessingParameterBoolean(self.GROUP_PAYSAGE, 'Groupe : Paysage', defaultValue=False))
        paysage = [s['name'] for s in DEFAULT_CONFIG['groups']['Paysage']['sources']]
        self.addParameter(QgsProcessingParameterEnum(
            self.LAYERS_PAYSAGE, '  Couches Paysage à extraire',
            options=paysage, allowMultiple=True, defaultValue=list(range(len(paysage)))
        ))

        # --- EIE ---
        self.addParameter(QgsProcessingParameterBoolean(self.GROUP_EIE, 'Groupe : EIE', defaultValue=True))
        eie = [s['name'] for s in DEFAULT_CONFIG['groups']['EIE']['sources']]
        self.addParameter(QgsProcessingParameterEnum(
            self.LAYERS_EIE, '  Couches EIE à extraire',
            options=eie, allowMultiple=True, defaultValue=list(range(len(eie)))
        ))

        # --- Dossier export ---
        project_path = QgsProject.instance().absoluteFilePath()
        default_folder = os.path.dirname(project_path) if project_path else ''
        self.addParameter(QgsProcessingParameterFile(
            self.OUTPUT_FOLDER, "Dossier d'export",
            behavior=QgsProcessingParameterFile.Folder,
            defaultValue=default_folder
        ))

    # ------------------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):
        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT_POLYGON, context)
        buffer_dist = self.parameterAsDouble(parameters, self.BUFFER_DISTANCE, context)
        output_folder = self.parameterAsFile(parameters, self.OUTPUT_FOLDER, context)

        feats = list(input_layer.getFeatures())
        if not feats:
            raise QgsProcessingException("La couche d'emprise est vide")

        geom = (QgsGeometry.unaryUnion([f.geometry() for f in feats])
                if len(feats) > 1 else feats[0].geometry())

        buffer_geom = make_buffer_lambert(geom, input_layer.crs(), buffer_dist)
        buffer_bbox = buffer_geom.boundingBox()
        centroid_pt = centroid_wgs84(buffer_geom)
        dist_km = buffer_dist / 1000.0

        groups_config = [
            (self.GROUP_COMMUNS, self.LAYERS_COMMUNS, 'Communs'),
            (self.GROUP_PAYSAGE, self.LAYERS_PAYSAGE, 'Paysage'),
            (self.GROUP_EIE,     self.LAYERS_EIE,     'EIE'),
        ]

        temp_files = []
        try:
            for group_param, layers_param, group_key in groups_config:
                if feedback.isCanceled():
                    break
                if not self.parameterAsBool(parameters, group_param, context):
                    feedback.pushInfo(f'Groupe {group_key} : ignoré (décoché)')
                    continue

                selected = self.parameterAsEnums(parameters, layers_param, context)
                if not selected:
                    feedback.pushInfo(f'Groupe {group_key} : aucune couche sélectionnée')
                    continue

                sources = DEFAULT_CONFIG['groups'][group_key]['sources']
                feedback.pushInfo(f'\n=== Groupe {group_key} – {len(selected)} couche(s) ===')

                for idx in selected:
                    if feedback.isCanceled():
                        break
                    if idx >= len(sources):
                        continue
                    src = sources[idx]
                    name = src.get('name', src['id'])
                    feedback.pushInfo(f'\n  ====== {name}======')
                    try:
                        layer = fetch_source(
                            src, buffer_bbox, dist_km, centroid_pt, feedback, temp_files
                        )
                        if layer is None:
                            continue
                        target_folder = src.get('target', {}).get('folder', '')
                        nomenclature = src.get('nomenclature', src['id'])
                        save_path = os.path.join(output_folder, target_folder, f'{nomenclature}.gpkg')
                        save_layer_as_gpkg(layer, save_path, nomenclature, feedback)
                        feedback.pushInfo(f'    ✓ {os.path.normpath(save_path)}')
                    except Exception as e:
                        feedback.reportError(f'    ✗ Erreur : {e}', fatalError=False)
                        feedback.reportError(traceback.format_exc(), fatalError=False)
        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except Exception:
                    pass

        return {}

    def name(self):
        return 'autodataprep'

    def groupId(self):
        return 'EPES'

    def group(self):
        return 'EPES'

    def displayName(self):
        return 'Extraction de données'

    def shortHelpString(self):
        return (
            'Récupère et exporte les données référentielles depuis PostGIS, WFS et API '
            'pour un périmètre tamponné autour d\'une emprise polygone.\n\n'
            'Cochez les groupes souhaités (Communs / Paysage / EIE) puis sélectionnez '
            'les couches individuelles dans chaque groupe.\n\n'
            'Les fichiers sont exportés en GeoPackage (.gpkg) dans le dossier choisi, '
            'en respectant l\'arborescence définie.\n\n'
            '─── Identifiants requis ───\n'
            'Certaines sources nécessitent des identifiants configurés dans les variables '
            'globales QGIS (Réglages → Options → Variables) :\n\n'
            '• atlasante_user / atlasante_password\n'
            '  → Accès Atlasanté (captages eau potable)\n'
            '  → Compte à demander sur https://www.atlasante.fr\n\n'
            'Sans ces variables, la source concernée échouera avec un message explicite.'
        )

    def createInstance(self):
        return AutoDataPrepAlgorithm()
