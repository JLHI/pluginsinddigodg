# -*- coding: utf-8 -*-
"""Algorithme Processing : modélisation de flux INSEE en flèches courbées."""

import math
import os

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterFolderDestination,
    QgsProcessingOutputVectorLayer,
    QgsProcessingException,
    QgsProcessingContext,
    QgsProcessing,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsVectorFileWriter,
    QgsProcessingLayerPostProcessorInterface,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsFillSymbol,
    QgsArrowSymbolLayer,
    QgsSymbolLayer,
    QgsProperty,
    QgsSingleSymbolRenderer,
)

# Conserve les post-processeurs vivants (sinon le style n'est pas appliqué).
_STYLERS = []

# type de flux -> (clé sortie, suffixe nom couche, clé min, clé max, couleur)
TYPES_FLUX = {
    "Entrant": ("OUTPUT_ENTRANT", "entrant", "MIN_FLUX_ENTRANT", "MAX_FLUX_ENTRANT", QColor(31, 120, 180)),
    "Sortant": ("OUTPUT_SORTANT", "sortant", "MIN_FLUX_SORTANT", "MAX_FLUX_SORTANT", QColor(227, 26, 28)),
    "Interne": ("OUTPUT_INTERNE", "interne", "MIN_FLUX_INTERNE", "MAX_FLUX_INTERNE", QColor(51, 160, 44)),
    "Intra": ("OUTPUT_INTRA", "intra", "MIN_FLUX_INTRA", "MAX_FLUX_INTRA", QColor(255, 127, 0)),
}


def normalize_insee(value):
    """Normalise un code INSEE pour fiabiliser la jointure."""
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            value = int(value)
    s = str(value).strip()
    if s == "" or s.upper() in ("NULL", "NONE", "NAN"):
        return None
    if s.endswith(".0"):
        s = s[:-2]
    if s.isdigit() and len(s) < 5:
        s = s.zfill(5)
    return s


def parse_flux(value):
    """Convertit une valeur de flux en float (gère la virgule décimale)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    s = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def match_type(value):
    """Associe la valeur de la colonne 'Type flux' a une cle canonique."""
    if value is None:
        return None
    s = str(value).strip().lower()
    table = {"entrant": "Entrant", "sortant": "Sortant",
             "interne": "Interne", "intra": "Intra"}
    return table.get(s)


def _seglen(a, b):
    return math.hypot(b.x() - a.x(), b.y() - a.y())


def _advance(points, dist):
    if dist <= 0:
        return list(points)
    acc = 0.0
    for i in range(len(points) - 1):
        d = _seglen(points[i], points[i + 1])
        if d == 0:
            continue
        if acc + d >= dist:
            t = (dist - acc) / d
            x = points[i].x() + t * (points[i + 1].x() - points[i].x())
            y = points[i].y() + t * (points[i + 1].y() - points[i].y())
            return [QgsPointXY(x, y)] + points[i + 1:]
        acc += d
    return None


def trim_polyline(pts, gap):
    total = sum(_seglen(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    if total <= 2 * gap:
        return None
    a = _advance(pts, gap)
    if not a:
        return None
    a = list(reversed(a))
    b = _advance(a, gap)
    if not b:
        return None
    return list(reversed(b))


def courbe_bezier(p_orig, p_dest, courbure, gap_frac=0.0, n=24):
    """Courbe de Bezier quadratique decalee, rognee aux extremites."""
    dx = p_dest.x() - p_orig.x()
    dy = p_dest.y() - p_orig.y()
    dist = math.hypot(dx, dy)
    if dist == 0:
        return None
    mx = (p_orig.x() + p_dest.x()) / 2.0
    my = (p_orig.y() + p_dest.y()) / 2.0
    nx = -dy / dist
    ny = dx / dist
    offset = dist * courbure
    cx = mx + nx * offset
    cy = my + ny * offset
    pts = []
    for i in range(n + 1):
        t = i / float(n)
        u = 1.0 - t
        x = u * u * p_orig.x() + 2.0 * u * t * cx + t * t * p_dest.x()
        y = u * u * p_orig.y() + 2.0 * u * t * cy + t * t * p_dest.y()
        pts.append(QgsPointXY(x, y))
    if gap_frac > 0:
        trimmed = trim_polyline(pts, dist * gap_frac)
        if trimmed and len(trimmed) >= 2:
            pts = trimmed
    return QgsGeometry.fromPolylineXY(pts)


def _free_path(path, project):
    """Supprime les couches chargees pointant vers `path` puis efface le fichier."""
    if project is not None:
        npath = os.path.normpath(path)
        ids = []
        for lid, lyr in project.mapLayers().items():
            base = (lyr.source() or "").split("|")[0]
            if base and os.path.normpath(base) == npath:
                ids.append(lid)
        if ids:
            project.removeMapLayers(ids)
    for ext in ("", "-wal", "-shm", "-journal"):
        p = path + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


class ArrowStyler(QgsProcessingLayerPostProcessorInterface):
    """Symbole fleche courbe, sans contour.

    fixed_width None -> largeur pilotee par le champ 'largeur'.
    fixed_width defini -> largeur constante (cas Intra).
    """

    def __init__(self, color, fixed_width=None, head_scale=1.0):
        super().__init__()
        self.color = color
        self.fixed_width = fixed_width
        self.head_scale = head_scale

    def postProcessLayer(self, layer, context, feedback):
        if layer is None or not layer.isValid():
            return
        symbol = QgsLineSymbol()
        arrow = QgsArrowSymbolLayer()
        arrow.setIsCurved(True)
        arrow.setIsRepeated(False)
        try:
            arrow.setArrowType(QgsArrowSymbolLayer.ArrowPlain)
            arrow.setHeadType(QgsArrowSymbolLayer.HeadSingle)
        except Exception:
            pass

        hs = float(self.head_scale)
        if self.fixed_width is not None:
            w = float(self.fixed_width)
            arrow.setArrowWidth(w)
            arrow.setArrowStartWidth(w)
            arrow.setHeadLength(w * 2.0 * hs)
            arrow.setHeadThickness(w * 1.4 * hs)
        else:
            arrow.setArrowWidth(1.0)
            arrow.setArrowStartWidth(0.3)
            arrow.setHeadLength(2.0)
            arrow.setHeadThickness(1.4)
            arrow.setDataDefinedProperty(
                QgsSymbolLayer.PropertyArrowWidth, QgsProperty.fromField("largeur"))
            arrow.setDataDefinedProperty(
                QgsSymbolLayer.PropertyArrowStartWidth, QgsProperty.fromExpression('"largeur" * 0.25'))
            # Tete a croissance sous-lineaire (sqrt) -> ne domine plus les traits epais
            arrow.setDataDefinedProperty(
                QgsSymbolLayer.PropertyArrowHeadLength,
                QgsProperty.fromExpression('{:.4f} * 2.2 * sqrt("largeur")'.format(hs)))
            arrow.setDataDefinedProperty(
                QgsSymbolLayer.PropertyArrowHeadThickness,
                QgsProperty.fromExpression('{:.4f} * 1.5 * sqrt("largeur")'.format(hs)))

        fill = QgsFillSymbol.createSimple({
            "color": self.color.name(), "style": "solid", "outline_style": "no"})
        arrow.setSubSymbol(fill)
        symbol.changeSymbolLayer(0, arrow)
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.setOpacity(0.9)
        layer.triggerRepaint()


class PointStyler(QgsProcessingLayerPostProcessorInterface):
    """Symbole rond (flux Intra) : taille pilotee par 'largeur', contour fixe."""

    def __init__(self, color, contour_width):
        super().__init__()
        self.color = color
        self.contour_width = contour_width

    def postProcessLayer(self, layer, context, feedback):
        if layer is None or not layer.isValid():
            return
        symbol = QgsMarkerSymbol.createSimple({
            "name": "circle",
            "color": "0,0,0,0",          # remplissage transparent
            "outline_color": self.color.name(),
            "outline_width": "{:.3f}".format(float(self.contour_width)),
            "size": "4",
        })
        sl = symbol.symbolLayer(0)
        sl.setDataDefinedProperty(
            QgsSymbolLayer.PropertySize, QgsProperty.fromField("largeur"))
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.setOpacity(0.9)
        layer.triggerRepaint()


class ModelisationFluxAlgorithm(QgsProcessingAlgorithm):

    EXCEL = "EXCEL"
    ORIGIN_FIELD = "ORIGIN_FIELD"
    DEST_FIELD = "DEST_FIELD"
    FLUX_FIELD = "FLUX_FIELD"
    TYPE_FIELD = "TYPE_FIELD"
    SIG = "SIG"
    INSEE_FIELD = "INSEE_FIELD"
    MIN_SIZE = "MIN_SIZE"
    MAX_SIZE = "MAX_SIZE"
    CURVATURE = "CURVATURE"
    GAP = "GAP"
    HEAD_SCALE = "HEAD_SCALE"
    INTRA_SIZE_MIN = "INTRA_SIZE_MIN"
    INTRA_SIZE_MAX = "INTRA_SIZE_MAX"
    INTRA_CONTOUR = "INTRA_CONTOUR"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"

    def tr(self, string):
        return QCoreApplication.translate("ModelisationFlux", string)

    def createInstance(self):
        return ModelisationFluxAlgorithm()

    def createCustomParametersWidget(self, parent=None):
        """Remplace le formulaire Processing standard par la fenêtre custom.

        Quand l'algorithme est lancé depuis la boîte à outils Processing, QGIS
        appelle cette méthode ; si elle renvoie un widget, c'est lui qui est
        affiché à la place du formulaire auto-généré. La fenêtre exécute
        ensuite l'algorithme via processing.runAndLoadResults().
        """
        from qgis.utils import iface
        from .modelisation_flux_dialog import FluxDialog
        return FluxDialog(iface, parent)

    def name(self):
        return "modeliser_flux_fleches"

    def displayName(self):
        return self.tr("Modeliser des flux en fleches courbees")

    def group(self):
        return self.tr("Flux INSEE")

    def groupId(self):
        return "flux_insee"

    def icon(self):
        path = os.path.join(os.path.dirname(__file__), "modelisation_flux_icon.png")
        if os.path.exists(path):
            return QIcon(path)
        return super().icon()

    def shortHelpString(self):
        return self.tr(
            "Modelise des flux sous forme de fleches courbees (Entrant, "
            "Sortant, Interne) et de ronds proportionnels (Intra, flux d'une "
            "commune sur elle-meme : couche de points).\n\n"
            "Le journal d'execution affiche, pour chaque type, la plage de "
            "flux observee : utile pour choisir ensuite les bornes.\n\n"
            "Sortie : un dossier ou sont (re)ecrits jusqu'a 4 GeoPackages "
            "(flux_insee_entrant/_sortant/_interne/_intra). Les couches "
            "existantes du meme nom sont ecrasees."
        )

    # ------------------------------------------------------------------ #
    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.EXCEL, self.tr("Fichier Excel des flux (.xlsx)"),
            types=[QgsProcessing.TypeVector]))
        self.addParameter(QgsProcessingParameterField(
            self.ORIGIN_FIELD, self.tr("Champ Commune d'origine"),
            parentLayerParameterName=self.EXCEL, defaultValue="Commune d'origine"))
        self.addParameter(QgsProcessingParameterField(
            self.DEST_FIELD, self.tr("Champ Commune de destination"),
            parentLayerParameterName=self.EXCEL, defaultValue="Commune de destination"))
        self.addParameter(QgsProcessingParameterField(
            self.FLUX_FIELD, self.tr("Champ Flux"),
            parentLayerParameterName=self.EXCEL, defaultValue="Flux"))
        self.addParameter(QgsProcessingParameterField(
            self.TYPE_FIELD, self.tr("Champ Type flux"),
            parentLayerParameterName=self.EXCEL, defaultValue="Type flux"))

        self.addParameter(QgsProcessingParameterFeatureSource(
            self.SIG, self.tr("Couche des chefs-lieux"),
            types=[QgsProcessing.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.INSEE_FIELD, self.tr("Champ code INSEE de la couche"),
            parentLayerParameterName=self.SIG, defaultValue="insee_com"))

        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_SIZE, self.tr("Taille minimale des fleches (mm)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.5, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_SIZE, self.tr("Taille maximale des fleches (mm)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=6.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.CURVATURE, self.tr("Courbure (0 = droite, 0.15 conseille)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.15,
            minValue=0.0, maxValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.GAP, self.tr("Ecart aux points origine/destination (%)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=8.0,
            minValue=0.0, maxValue=45.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.HEAD_SCALE, self.tr("Taille de la tete des fleches (facteur, 1 = defaut)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=1.0,
            minValue=0.2, maxValue=3.0))

        # Parametres specifiques Intra (points / ronds)
        self.addParameter(QgsProcessingParameterNumber(
            self.INTRA_SIZE_MIN, self.tr("Intra : taille min du rond (mm)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=2.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.INTRA_SIZE_MAX, self.tr("Intra : taille max du rond (mm)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=14.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.INTRA_CONTOUR, self.tr("Intra : epaisseur du contour (mm)"),
            type=QgsProcessingParameterNumber.Double, defaultValue=0.4, minValue=0.0))

        for type_flux, (_o, _s, min_key, max_key, _c) in TYPES_FLUX.items():
            self.addParameter(QgsProcessingParameterNumber(
                min_key, self.tr("Flux min a representer - {}").format(type_flux),
                type=QgsProcessingParameterNumber.Double, optional=True, defaultValue=None))
            self.addParameter(QgsProcessingParameterNumber(
                max_key, self.tr("Flux max a representer - {}").format(type_flux),
                type=QgsProcessingParameterNumber.Double, optional=True, defaultValue=None))

        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_FOLDER, self.tr("Dossier de sortie")))

        for type_flux, (out_key, _s, _mn, _mx, _c) in TYPES_FLUX.items():
            self.addOutput(QgsProcessingOutputVectorLayer(
                out_key, self.tr("Fleches - {}").format(type_flux)))

    # ------------------------------------------------------------------ #
    def _opt_double(self, parameters, name, context):
        if name not in parameters or parameters[name] is None:
            return None
        return self.parameterAsDouble(parameters, name, context)

    def processAlgorithm(self, parameters, context, feedback):
        excel_layer = self.parameterAsVectorLayer(parameters, self.EXCEL, context)
        if excel_layer is None:
            raise QgsProcessingException(self.tr("Impossible de lire le fichier Excel."))
        sig_source = self.parameterAsSource(parameters, self.SIG, context)
        if sig_source is None:
            raise QgsProcessingException(self.tr("Couche des chefs-lieux invalide."))

        origin_field = self.parameterAsString(parameters, self.ORIGIN_FIELD, context)
        dest_field = self.parameterAsString(parameters, self.DEST_FIELD, context)
        flux_field = self.parameterAsString(parameters, self.FLUX_FIELD, context)
        type_field = self.parameterAsString(parameters, self.TYPE_FIELD, context)
        insee_field = self.parameterAsString(parameters, self.INSEE_FIELD, context)

        min_size = self.parameterAsDouble(parameters, self.MIN_SIZE, context)
        max_size = self.parameterAsDouble(parameters, self.MAX_SIZE, context)
        if max_size < min_size:
            min_size, max_size = max_size, min_size
        curvature = self.parameterAsDouble(parameters, self.CURVATURE, context)
        gap_frac = self.parameterAsDouble(parameters, self.GAP, context) / 100.0
        head_scale = self.parameterAsDouble(parameters, self.HEAD_SCALE, context)

        intra_size_min = self.parameterAsDouble(parameters, self.INTRA_SIZE_MIN, context)
        intra_size_max = self.parameterAsDouble(parameters, self.INTRA_SIZE_MAX, context)
        intra_contour = self.parameterAsDouble(parameters, self.INTRA_CONTOUR, context)

        bornes_min, bornes_max = {}, {}
        for type_flux, (_o, _s, min_key, max_key, _c) in TYPES_FLUX.items():
            bornes_min[type_flux] = self._opt_double(parameters, min_key, context)
            bornes_max[type_flux] = self._opt_double(parameters, max_key, context)

        folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        if not folder:
            raise QgsProcessingException(self.tr("Aucun dossier de sortie defini."))
        os.makedirs(folder, exist_ok=True)

        # --- 1. Dictionnaire code INSEE -> point ---
        feedback.pushInfo(self.tr("Lecture de la couche des chefs-lieux..."))
        if insee_field not in sig_source.fields().names():
            raise QgsProcessingException(
                self.tr("Le champ '{}' est absent de la couche.").format(insee_field))
        points = {}
        for feat in sig_source.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            code = normalize_insee(feat[insee_field])
            if code is None:
                continue
            points[code] = QgsPointXY(geom.centroid().asPoint())
        if not points:
            raise QgsProcessingException(self.tr("Aucun point exploitable dans la couche."))

        if intra_size_max < intra_size_min:
            intra_size_min, intra_size_max = intra_size_max, intra_size_min

        # --- 2. Lecture du tableur ---
        excel_names = excel_layer.fields().names()
        for needed in (origin_field, dest_field, flux_field, type_field):
            if needed not in excel_names:
                raise QgsProcessingException(
                    self.tr("Le champ '{}' est absent du tableur.").format(needed))
        nom_o_f = "Nom commune origine" if "Nom commune origine" in excel_names else None
        nom_d_f = "Nom commune destination" if "Nom commune destination" in excel_names else None

        collected = {t: [] for t in TYPES_FLUX}
        fmin = {t: None for t in TYPES_FLUX}
        fmax = {t: None for t in TYPES_FLUX}
        plage = {t: [None, None, 0] for t in TYPES_FLUX}  # min,max,count avant bornes
        non_apparies = 0
        total = excel_layer.featureCount() or 0
        feedback.pushInfo(self.tr("Analyse du tableur ({} lignes)...").format(total))

        for current, feat in enumerate(excel_layer.getFeatures()):
            if feedback.isCanceled():
                break
            if total:
                feedback.setProgress(int(current / total * 40))
            type_key = match_type(feat[type_field])
            if type_key is None:
                continue
            flux = parse_flux(feat[flux_field])
            if flux is None:
                continue
            pl = plage[type_key]
            pl[0] = flux if pl[0] is None else min(pl[0], flux)
            pl[1] = flux if pl[1] is None else max(pl[1], flux)
            pl[2] += 1

            code_o = normalize_insee(feat[origin_field])
            code_d = normalize_insee(feat[dest_field])
            if code_o is None or code_d is None:
                continue
            # Intra : flux sur la commune elle-meme -> seul le point d'origine compte
            if type_key == "Intra":
                if code_o not in points:
                    non_apparies += 1
                    continue
            else:
                if code_o not in points or code_d not in points:
                    non_apparies += 1
                    continue
            bmin, bmax = bornes_min[type_key], bornes_max[type_key]
            if bmin is not None and flux < bmin:
                continue
            if bmax is not None and flux > bmax:
                continue
            nom_o = str(feat[nom_o_f]) if nom_o_f else ""
            nom_d = str(feat[nom_d_f]) if nom_d_f else ""
            collected[type_key].append((code_o, nom_o, code_d, nom_d, flux))
            if fmin[type_key] is None or flux < fmin[type_key]:
                fmin[type_key] = flux
            if fmax[type_key] is None or flux > fmax[type_key]:
                fmax[type_key] = flux

        feedback.pushInfo(self.tr("--- Plages de flux observees (avant bornes) ---"))
        for t in TYPES_FLUX:
            lo, hi, nb = plage[t]
            if nb:
                feedback.pushInfo("  {} : {} flux, min {:.2f}, max {:.2f}".format(t, nb, lo, hi))
            else:
                feedback.pushInfo("  {} : aucun flux".format(t))
        if non_apparies:
            feedback.pushWarning(
                self.tr("{} ligne(s) ignoree(s) : code INSEE absent de la couche.")
                .format(non_apparies))

        # --- 3. Champs de sortie ---
        out_fields = QgsFields()
        out_fields.append(QgsField("origine", QVariant.String))
        out_fields.append(QgsField("nom_orig", QVariant.String))
        out_fields.append(QgsField("destination", QVariant.String))
        out_fields.append(QgsField("nom_dest", QVariant.String))
        out_fields.append(QgsField("flux", QVariant.Double))
        out_fields.append(QgsField("type_flux", QVariant.String))
        out_fields.append(QgsField("largeur", QVariant.Double))
        sig_crs = sig_source.sourceCrs()

        results = {}
        types_list = list(TYPES_FLUX.items())
        for idx, (type_key, (out_key, suffixe, _mn, _mx, color)) in enumerate(types_list):
            if feedback.isCanceled():
                break
            rows = collected[type_key]
            if not rows:
                feedback.pushInfo(self.tr("{} : aucun flux retenu.").format(type_key))
                results[out_key] = None
                continue

            layer_name = "flux_insee_" + suffixe
            path = os.path.join(folder, layer_name + ".gpkg")
            _free_path(path, context.project())  # ecrasement

            is_intra = (type_key == "Intra")
            wkb = QgsWkbTypes.Point if is_intra else QgsWkbTypes.LineString

            opts = QgsVectorFileWriter.SaveVectorOptions()
            opts.driverName = "GPKG"
            opts.layerName = layer_name
            opts.fileEncoding = "UTF-8"
            opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
            writer = QgsVectorFileWriter.create(
                path, out_fields, wkb, sig_crs,
                context.transformContext(), opts)
            if writer.hasError() != QgsVectorFileWriter.NoError:
                raise QgsProcessingException(
                    self.tr("Erreur ecriture {} : {}").format(path, writer.errorMessage()))

            lo, hi = fmin[type_key], fmax[type_key]
            n_ecrites = 0
            for (code_o, nom_o, code_d, nom_d, flux) in rows:
                if is_intra:
                    # rond sur le chef-lieu, taille interpolee selon le flux
                    if lo is None or hi is None or hi == lo:
                        largeur = (intra_size_min + intra_size_max) / 2.0
                    else:
                        largeur = intra_size_min + (flux - lo) / (hi - lo) * (intra_size_max - intra_size_min)
                    geom = QgsGeometry.fromPointXY(points[code_o])
                else:
                    if lo is None or hi is None or hi == lo:
                        largeur = (min_size + max_size) / 2.0
                    else:
                        largeur = min_size + (flux - lo) / (hi - lo) * (max_size - min_size)
                    p_o, p_d = points[code_o], points[code_d]
                    same = (abs(p_o.x() - p_d.x()) < 1e-9 and abs(p_o.y() - p_d.y()) < 1e-9)
                    if same:
                        continue  # flux non-Intra degenere (origine = destination) : ignore
                    geom = courbe_bezier(p_o, p_d, curvature, gap_frac)
                if geom is None or geom.isEmpty():
                    continue
                f = QgsFeature(out_fields)
                f.setGeometry(geom)
                f.setAttributes([code_o, nom_o, code_d, nom_d, float(flux), type_key, float(largeur)])
                writer.addFeature(f)
                n_ecrites += 1
            del writer

            feedback.pushInfo(self.tr("{} : {} objet(s) -> {}").format(type_key, n_ecrites, path))
            feedback.setProgress(40 + int((idx + 1) / len(types_list) * 60))

            if context.project() is not None:
                if is_intra:
                    styler = PointStyler(color, intra_contour)
                else:
                    styler = ArrowStyler(color, head_scale=head_scale)
                _STYLERS.append(styler)
                details = QgsProcessingContext.LayerDetails(layer_name, context.project(), out_key)
                details.setPostProcessor(styler)
                context.addLayerToLoadOnCompletion(path, details)
            results[out_key] = path

        return results
