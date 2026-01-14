from .iso_pieton_algo import run_pieton
from .iso_voiture_algo import run_voiture
from .iso_velo_algo import run_velo

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterField,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingException,
    QgsProcessing,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsWkbTypes,
    QgsFeatureSink,
    QgsGraduatedSymbolRenderer,
    QgsRendererRange,
    QgsSymbol
)
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from PyQt5.QtGui import QColor
from qgis.PyQt.QtNetwork import QNetworkAccessManager


class IsochroneValhallaAlgorithm(QgsProcessingAlgorithm):

    INPUT_POINT = "INPUT_POINT"
    ID_FIELD = "ID_FIELD"
    MODE = "MODE"
    ISOCHRONE_TYPE = "ISOCHRONE_TYPE"
    ISOCHRONE_VALUE = "ISOCHRONE_VALUE"
    SERVER_URL = "SERVER_URL"
    OUTPUT = "OUTPUT"

    # ------------------------------------------------------------------
    # INIT
    # ------------------------------------------------------------------

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_POINT,
                self.tr("Points de départ"),
                [QgsProcessing.TypeVectorPoint]
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                self.ID_FIELD,
                self.tr("Champ ID"),
                parentLayerParameterName=self.INPUT_POINT
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.MODE,
                self.tr("Modes de déplacement"),
                options=["Voiture", "Piéton", "Vélo"],
                allowMultiple=True,
                defaultValue=[1]
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.ISOCHRONE_TYPE,
                self.tr("Type d'isochrone"),
                options=["minutes", "mètres"],
                defaultValue=1
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.ISOCHRONE_VALUE,
                self.tr("Valeurs (ex : 5,10,15 ou 300,600)"),
                defaultValue="5,10,15"
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.SERVER_URL,
                self.tr("URL serveur Valhalla"),
                defaultValue="http://localhost:8003"
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr("Isochrones réseau (polygones)")
            )
        )

    # ------------------------------------------------------------------
    # PROCESS
    # ------------------------------------------------------------------

    def processAlgorithm(self, parameters, context, feedback):

        # ------------------------------------------------------------------
        # Lecture paramètres
        # ------------------------------------------------------------------

        source = self.parameterAsSource(parameters, self.INPUT_POINT, context)
        id_field = self.parameterAsString(parameters, self.ID_FIELD, context)
        isochrone_type = self.parameterAsEnum(parameters, self.ISOCHRONE_TYPE, context)
        values_str = self.parameterAsString(parameters, self.ISOCHRONE_VALUE, context)
        server_url = self.parameterAsString(parameters, self.SERVER_URL, context)

        values = [int(v.strip()) for v in values_str.split(",") if v.strip().isdigit()]
        if not values:
            raise QgsProcessingException("Aucune valeur d'isochrone valide.")

        MODE_MAP = {0: "auto", 1: "pedestrian", 2: "bicycle"}
        mode_indices = self.parameterAsEnums(parameters, self.MODE, context)
        modes = [MODE_MAP[i] for i in mode_indices]

        unit_label = "min" if isochrone_type == 0 else "m"

        # ------------------------------------------------------------------
        # CRS & transformations
        # ------------------------------------------------------------------

        src_crs = source.sourceCrs()
        crs_2154 = QgsCoordinateReferenceSystem("EPSG:2154")
        crs_4326 = QgsCoordinateReferenceSystem("EPSG:4326")

        to_2154 = QgsCoordinateTransform(src_crs, crs_2154, context.transformContext())
        to_4326 = QgsCoordinateTransform(src_crs, crs_4326, context.transformContext())

        # ------------------------------------------------------------------
        # Sortie
        # ------------------------------------------------------------------

        fields = QgsFields()
        fields.append(QgsField("id", QVariant.String))
        fields.append(QgsField("mode", QVariant.String))
        fields.append(QgsField("unit", QVariant.String))
        fields.append(QgsField("value", QVariant.Double))

        sink, dest_id = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            QgsWkbTypes.Polygon,
            crs_2154
        )

        features = list(source.getFeatures())
        total_steps = len(features) * len(values) * len(modes)
        step = 0

        feedback.pushInfo(f"Traitement démarré ({total_steps} étapes).")

        # ------------------------------------------------------------------
        # Boucle principale
        # ------------------------------------------------------------------
        self.manager = QNetworkAccessManager()

        for f in features:

            geom_src = QgsGeometry(f.geometry())

            # --- point en 4326 (API Valhalla) ---
            if src_crs.authid() == "EPSG:4326":
                geom_4326 = QgsGeometry(geom_src)
            else:
                geom_4326 = QgsGeometry(geom_src)
                geom_4326.transform(to_4326)

            pt_4326 = geom_4326.asPoint()

            fid = str(f[id_field])

            for mode in modes:
                for value in values:

                    if feedback.isCanceled():
                        break

                    step += 1
                    feedback.setProgress(int(step / total_steps * 100))
                    feedback.pushInfo(f"Point {fid} – {mode} – {value}")
                    feedback.pushInfo("isochrone_type : "+str(isochrone_type))

                    # --------------------------------------------------
                    # Appel des fonctions spécialisées (à implémenter)
                    # --------------------------------------------------

                    if mode == "pedestrian":
                        polygons = run_pieton(
                            self,
                            pt_4326,
                            value,
                            isochrone_type,
                            server_url,
                            context,
                            feedback
                        )

                    elif mode == "auto":
                        polygons = run_voiture(
                            self,
                            pt_4326,
                            value,
                            isochrone_type,
                            server_url,
                            context,
                            feedback
                        )

                    elif mode == "bicycle":
                        polygons = run_velo(
                            self,
                            pt_4326,
                            value,
                            isochrone_type,
                            server_url,
                            context,
                            feedback
                        )

                    else:
                        polygons = []

                    # --------------------------------------------------
                    # Écriture sortie
                    # --------------------------------------------------

                    for poly in polygons:
                        out = QgsFeature(fields)
                        out.setGeometry(poly)
                        out.setAttributes([fid, mode, unit_label, float(value)])
                        sink.addFeature(out, QgsFeatureSink.FastInsert)

        # ------------------------------------------------------------------
        # Style (dégradé jaune → orange)
        # ------------------------------------------------------------------

        layer = context.getMapLayer(dest_id)
        if layer:
            vals = sorted({f["value"] for f in layer.getFeatures()})
            if vals:
                ranges = []
                min_v, max_v = min(vals), max(vals)

                for v in vals:
                    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
                    symbol.setOpacity(0.5)

                    ratio = 0 if min_v == max_v else (v - min_v) / (max_v - min_v)
                    color = QColor.fromHsv(45 - int(15 * ratio), 255, 255)
                    symbol.setColor(color)

                    ranges.append(QgsRendererRange(v, v, symbol, str(v)))

                renderer = QgsGraduatedSymbolRenderer("value", ranges)
                renderer.setMode(QgsGraduatedSymbolRenderer.Custom)
                layer.setRenderer(renderer)
                layer.triggerRepaint()

        feedback.setProgress(100)
        feedback.pushInfo("Traitement terminé.")

        return {self.OUTPUT: dest_id}

    # ------------------------------------------------------------------
    # Métadonnées
    # ------------------------------------------------------------------

    def name(self):
        return "valhalla_isochrone"

    def displayName(self):
        return self.tr("Valhalla – Isochrones")

    def group(self):
        return "Valhalla"

    def groupId(self):
        return "valhalla"

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        return IsochroneValhallaAlgorithm()
