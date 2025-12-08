# -*- coding: utf-8 -*-
"""
Export des métadonnées des couches d'un projet QGIS vers Excel (.xlsx)

Intégré comme algorithme Processing pour pouvoir l'exécuter depuis la boîte à
outils Processing ou via un modèle.

Feuille 1 : COUCHES (infos générales)
Feuille 2 : CHAMPS (infos des attributs des couches vecteur)
"""

import os
#import .xlsxwriter


from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFileDestination,
    QgsProcessingException,
    QgsProject,
    QgsLayerTreeGroup,
    QgsMapLayer,
)

class MetaddigoExportMetadataAlgorithm(QgsProcessingAlgorithm):
    """Algorithme Processing : export métadonnées -> .xlsx"""

    OUTPUT = 'OUTPUT'
    def initAlgorithm(self, config):
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                self.tr('Fichier Excel de sortie (.xlsx)'),
                fileFilter='Excel files (*.xlsx)'
            )
        )


    

    # ------------------------- helpers -------------------------
    def get_layer_group(self, layer_id):
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer_id)
        if not node:
            return self.tr('AUCUN GROUPE')
        group_names = []
        parent = node.parent()
        while parent and isinstance(parent, QgsLayerTreeGroup):
            group_names.insert(0, parent.name())
            parent = parent.parent()
        return ' > '.join(group_names) if group_names else self.tr('RACINE')

    def extract_metadata(self, layer):
        name = layer.name()
        group_path = self.get_layer_group(layer.id())
        geom_type_str = self.tr('AUTRE')
        # provider and source (useful to detect VRT / special providers)
        try:
            provider_name = layer.dataProvider().name()
        except Exception:
            try:
                provider_name = getattr(layer, 'providerType', '') or ''
            except Exception:
                provider_name = ''
        try:
            source_uri = layer.dataProvider().dataSourceUri()
        except Exception:
            try:
                source_uri = getattr(layer, 'source', '') or getattr(layer, 'dataSourceUri', '') or ''
                if callable(source_uri):
                    try:
                        source_uri = source_uri()
                    except Exception:
                        source_uri = ''
            except Exception:
                source_uri = ''

        # determine geometry type / presence
        has_geometry = False
        try:
            if hasattr(layer, 'geometryType'):
                try:
                    geom_type = layer.geometryType()
                    if geom_type in (0, 1, 2):
                        has_geometry = True
                        geom_type_str = {0: self.tr('POINT'), 1: self.tr('LIGNE'), 2: self.tr('POLYGONE')}.get(geom_type, self.tr('INCONNU'))
                    else:
                        geom_type_str = self.tr('TABLE / NON-SPATIAL')
                except Exception:
                    geom_type_str = self.tr('TABLE / NON-SPATIAL')
            else:
                # fallback to raster detection
                try:
                    if layer.type() == QgsMapLayer.RasterLayer:
                        has_geometry = True
                        geom_type_str = self.tr('RASTER')
                except Exception:
                    geom_type_str = self.tr('AUTRE')
        except Exception:
            geom_type_str = self.tr('VECTEUR (INCONNU)')

        # Detect VRT by provider name or source uri
        is_vrt = False
        try:
            if provider_name and 'vrt' in provider_name.lower():
                is_vrt = True
            if source_uri and '.vrt' in source_uri.lower():
                is_vrt = True
            # Some OGR-based VRT have XML content in the source; check for that too
            if source_uri and '<ogrvrtdatasource' in source_uri.lower():
                is_vrt = True
        except Exception:
            is_vrt = False

        # extent: do not fill for non-spatial layers; otherwise try to compute
        # - sanitize invalid extents (very large DBL_MAX placeholders)
        # - round coordinates: 6 decimals for geographic CRS (e.g. EPSG:4326), 2 decimals otherwise
        bbox = ''
        try:
            if not has_geometry:
                # non-spatial layers (tables, etc.) must not have an extent
                bbox = ''
            else:
                extent = layer.extent()
                minx = extent.xMinimum()
                miny = extent.yMinimum()
                maxx = extent.xMaximum()
                maxy = extent.yMaximum()

                # detect obviously invalid numeric extents (DBL_MAX placeholders)
                if any(abs(v) > 1e200 for v in (minx, miny, maxx, maxy)):
                    bbox = self.tr('NON DISPONIBLE')
                else:
                    # choose precision based on CRS
                    try:
                        crs = layer.crs()
                        is_geo = False
                        try:
                            is_geo = crs.isGeographic()
                        except Exception:
                            auth = getattr(crs, 'authid', lambda: '')()
                            is_geo = '4326' in str(auth)
                    except Exception:
                        is_geo = False

                    decimals = 6 if is_geo else 2
                    fmt = f"{{:.{decimals}f}}"
                    bbox = f"{fmt.format(minx)}, {fmt.format(miny)}, {fmt.format(maxx)}, {fmt.format(maxy)}"
        except Exception:
            bbox = self.tr('NON DISPONIBLE')

        try:
            crs_name = layer.crs().description() or layer.crs().authid()
        except Exception:
            crs_name = self.tr('SCR NON DISPONIBLE')
        try:
            rights = layer.metadata().rights() or self.tr('NON SPÉCIFIÉ')
            if isinstance(rights, list):
                rights = ', '.join(rights)
        except Exception:
            rights = self.tr('NON SPÉCIFIÉ')
        # Return metadata without provider/source (user requested no provider/source columns)
        return [name, group_path, geom_type_str, bbox, crs_name, rights]

    def extract_fields(self, layer):
        fields_info = []
        # Support vector layers and table-like layers (VRT / delimited text).
        if hasattr(layer, 'fields'):
            try:
                fields = layer.fields()
            except Exception:
                fields = []
            for idx, field in enumerate(fields):
                # Safely get attributes (some providers may not implement alias/comment)
                try:
                    fname = field.name()
                except Exception:
                    fname = ''
                try:
                    falias = field.alias()
                except Exception:
                    falias = ''
                try:
                    ftype = field.typeName()
                except Exception:
                    ftype = ''
                try:
                    flen = field.length()
                except Exception:
                    flen = ''
                try:
                    fprec = field.precision()
                except Exception:
                    fprec = ''
                try:
                    fcomment = field.comment()
                except Exception:
                    fcomment = ''

                fields_info.append([
                    layer.name(),  # NOM COUCHE
                    idx,           # ID
                    fname,         # NOM
                    falias,        # ALIAS
                    ftype,         # TYPE
                    flen,          # LONGUEUR
                    fprec,         # PRECISION
                    fcomment       # COMMENTAIRE
                ])
        return fields_info

    # ------------------------- process -------------------------
    def processAlgorithm(self, parameters, context, feedback):
        if xlsxwriter is None:
            feedback.reportError(self.tr("Module 'xlsxwriter' non installé dans l'environnement QGIS."))
            raise QgsProcessingException(self.tr("Module 'xlsxwriter' non installé."))

        # Récupérer le chemin de sortie choisi dans la boîte de dialogue Processing
        output = self.parameterAsFileOutput(parameters, self.OUTPUT, context)
        if not output:
            raise QgsProcessingException(self.tr('Aucun fichier de sortie renseigné.'))

        # Exporter toutes les couches ouvertes du projet (ordre de layer tree)
        self.export_layers(output, [], feedback)

        return {self.OUTPUT: output}

    # custom parameters widget removed: algorithm exports all open layers

    def export_layers(self, output, layer_ids, feedback):
        """
        Export the metadata to `output`. If `layer_ids` is empty, export all project layers.
        This method is intended to be called programmatically (from the dialog).
        """
        if xlsxwriter is None:
            feedback.reportError(self.tr("Module 'xlsxwriter' non installé dans l'environnement QGIS."))
            raise QgsProcessingException(self.tr("Module 'xlsxwriter' non installé."))

        out_dir = os.path.dirname(output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        project = QgsProject.instance()
        # Respecter l'ordre de l'explorateur de couches : parcourir layerTreeRoot().findLayers()
        root = project.layerTreeRoot()
        nodes = root.findLayers()
        layers = []
        for node in nodes:
            try:
                lyr = node.layer()
                if lyr is not None:
                    layers.append(lyr)
            except Exception:
                pass

        # Si une liste d'IDs est fournie, filtrer les couches exportées
        if layer_ids:
            wanted = set(layer_ids)
            layers = [lyr for lyr in layers if lyr.id() in wanted]

        headers_couches = [self.tr('ORDRE'), self.tr('NOM'), self.tr('GROUPE'), self.tr('TYPE'), self.tr('EMPRISE'), self.tr('SCR'), self.tr('DROITS')]
        headers_champs = [self.tr('NOM COUCHE'), self.tr('ID'), self.tr('NOM'), self.tr('ALIAS'), self.tr('TYPE'), self.tr('LONGUEUR'), self.tr('PRECISION'), self.tr('COMMENTAIRE')]

        workbook = xlsxwriter.Workbook(output)
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#D9D9D9'})

        # Feuille COUCHES
        ws_couches = workbook.add_worksheet('COUCHES')
        for col, h in enumerate(headers_couches):
            ws_couches.write(0, col, h, header_fmt)

        row = 1
        for idx, lyr in enumerate(layers):
            if feedback.isCanceled():
                workbook.close()
                raise QgsProcessingException(self.tr('Opération annulée par l\'utilisateur'))
            data = self.extract_metadata(lyr)
            # write order as first column (1-based)
            ws_couches.write(row, 0, idx + 1)
            for col, val in enumerate(data, start=1):
                ws_couches.write(row, col, str(val))
            row += 1
            if idx % 50 == 0:
                feedback.setProgress(int(50 * idx / max(1, len(layers))))

        ws_couches.set_column(0, 0, 8)
        ws_couches.set_column(1, 1, 30)
        ws_couches.set_column(2, 2, 40)
        ws_couches.set_column(3, 3, 15)
        ws_couches.set_column(4, 4, 45)
        ws_couches.set_column(5, 5, 30)
        ws_couches.set_column(6, 6, 25)

        # Feuille CHAMPS
        ws_champs = workbook.add_worksheet('CHAMPS')
        for col, h in enumerate(headers_champs):
            ws_champs.write(0, col, h, header_fmt)

        row = 1
        for idx, lyr in enumerate(layers):
            if feedback.isCanceled():
                workbook.close()
                raise QgsProcessingException(self.tr('Opération annulée par l\'utilisateur'))
            fields_data = self.extract_fields(lyr)
            for field_info in fields_data:
                for col, val in enumerate(field_info):
                    ws_champs.write(row, col, str(val))
                row += 1
            if idx % 50 == 0:
                feedback.setProgress(50 + int(50 * idx / max(1, len(layers))))

        ws_champs.set_column(0, 0, 30)
        ws_champs.set_column(1, 1, 5)
        ws_champs.set_column(2, 2, 20)
        ws_champs.set_column(3, 3, 20)
        ws_champs.set_column(4, 4, 15)
        ws_champs.set_column(5, 5, 10)
        ws_champs.set_column(6, 6, 10)
        ws_champs.set_column(7, 7, 30)

        workbook.close()
        feedback.pushInfo(self.tr(f'Export Excel terminé : {output}'))

        return {self.OUTPUT: output}
    
    def name(self):
        return 'export_metadonnees'

    def displayName(self):
        return self.tr('Export métadonnées vers Excel')

    def group(self):
        return self.tr('Metaddigo')

    def groupId(self):
        return 'metaddigo'

    def shortHelpString(self):
        return self.tr(
            'Exporte les métadonnées des couches du projet courant vers un fichier Excel (.xlsx).\n'
            'Feuille COUCHES : nom, groupe, type, emprise, SCR, droits.\n'
            'Feuille CHAMPS : liste des champs pour les couches vecteur.'
        )

    def createInstance(self):
        return MetaddigoExportMetadataAlgorithm()

    def tr(self, s):
        return QCoreApplication.translate('Processing', s)