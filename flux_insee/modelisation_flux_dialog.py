# -*- coding: utf-8 -*-
"""Fenetre personnalisee du plugin Modelisation flux INSEE."""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel,
    QPushButton, QDoubleSpinBox, QComboBox, QDialogButtonBox, QMessageBox,
    QWidget, QScrollArea,
)
from qgis.core import QgsVectorLayer, QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox, QgsFieldComboBox, QgsFileWidget

from .modelisation_flux import match_type, parse_flux, TYPES_FLUX

ALG_ID = "PluginsInddigoDG:modeliser_flux_fleches"


def _spin(maxi=1e9, dec=2, val=0.0, step=1.0, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(0.0, maxi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    return s


class FluxDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.setWindowTitle("Modelisation flux INSEE")
        self.setMinimumWidth(560)
        self.type_widgets = {}

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)

        root.addWidget(self._bloc_excel())
        root.addWidget(self._bloc_sig())
        root.addWidget(self._bloc_taille())
        root.addWidget(self._bloc_types())
        root.addWidget(self._bloc_sortie())

        outer = QVBoxLayout(self)
        outer.addWidget(scroll)

        self.buttons = QDialogButtonBox()
        self.run_btn = self.buttons.addButton("Modeliser les flux", QDialogButtonBox.AcceptRole)
        self.close_btn = self.buttons.addButton("Fermer", QDialogButtonBox.RejectRole)
        self.run_btn.clicked.connect(self.run)
        self.close_btn.clicked.connect(self.close)
        outer.addWidget(self.buttons)

    # ------------------------------------------------------------------ #
    def _bloc_excel(self):
        box = QGroupBox("Fichier Excel et champs")
        lay = QGridLayout(box)

        self.excel_widget = QgsFileWidget()
        self.excel_widget.setStorageMode(QgsFileWidget.GetFile)
        self.excel_widget.setFilter("Fichiers Excel (*.xlsx *.xls);;Tous les fichiers (*.*)")
        lay.addWidget(QLabel("Fichier :"), 0, 0)
        lay.addWidget(self.excel_widget, 0, 1, 1, 3)

        self.load_btn = QPushButton("Charger les donnees")
        self.load_btn.setToolTip("Lit le fichier, remplit les champs et calcule "
                                 "les min/max de flux par type.")
        self.load_btn.clicked.connect(self.load_data)
        lay.addWidget(self.load_btn, 1, 1, 1, 3)

        self.cmb_origin = QComboBox()
        self.cmb_dest = QComboBox()
        self.cmb_flux = QComboBox()
        self.cmb_type = QComboBox()
        for c in (self.cmb_origin, self.cmb_dest, self.cmb_flux, self.cmb_type):
            c.setEditable(True)
        lay.addWidget(QLabel("Commune d'origine :"), 2, 0)
        lay.addWidget(self.cmb_origin, 2, 1)
        lay.addWidget(QLabel("Commune de destination :"), 2, 2)
        lay.addWidget(self.cmb_dest, 2, 3)
        lay.addWidget(QLabel("Flux :"), 3, 0)
        lay.addWidget(self.cmb_flux, 3, 1)
        lay.addWidget(QLabel("Type flux :"), 3, 2)
        lay.addWidget(self.cmb_type, 3, 3)
        return box

    def _bloc_sig(self):
        box = QGroupBox("Couche des chefs-lieux")
        lay = QGridLayout(box)
        self.cmb_sig = QgsMapLayerComboBox()
        self.cmb_sig.setFilters(QgsMapLayerProxyModel.VectorLayer)
        self.cmb_insee = QgsFieldComboBox()
        self.cmb_sig.layerChanged.connect(self.cmb_insee.setLayer)
        if self.cmb_sig.currentLayer():
            self.cmb_insee.setLayer(self.cmb_sig.currentLayer())
            self._select_field(self.cmb_insee, "insee_com")
        lay.addWidget(QLabel("Couche :"), 0, 0)
        lay.addWidget(self.cmb_sig, 0, 1)
        lay.addWidget(QLabel("Champ INSEE :"), 0, 2)
        lay.addWidget(self.cmb_insee, 0, 3)
        return box

    def _bloc_taille(self):
        box = QGroupBox("Taille et courbure des fleches")
        lay = QHBoxLayout(box)
        self.sp_min = _spin(maxi=200, dec=2, val=0.5, step=0.5, suffix=" mm")
        self.sp_max = _spin(maxi=200, dec=2, val=6.0, step=0.5, suffix=" mm")
        self.sp_curv = _spin(maxi=1.0, dec=2, val=0.15, step=0.05)
        self.sp_gap = _spin(maxi=45, dec=0, val=8, step=1, suffix=" %")
        self.sp_head = _spin(maxi=3.0, dec=2, val=1.0, step=0.1)
        for label, w in (("Taille min", self.sp_min), ("Taille max", self.sp_max),
                         ("Courbure", self.sp_curv), ("Ecart", self.sp_gap),
                         ("Tete", self.sp_head)):
            lay.addWidget(QLabel(label + " :"))
            lay.addWidget(w)
        lay.addStretch()
        return box

    def _bloc_types(self):
        box = QGroupBox("Bornes de flux par type")
        lay = QVBoxLayout(box)
        for type_flux, (_o, _s, _mn, _mx, color) in TYPES_FLUX.items():
            sub = QGroupBox(type_flux)
            c = QColor(color)
            sub.setStyleSheet("QGroupBox::title { color: %s; font-weight: bold; }" % c.name())
            vbox = QVBoxLayout(sub)
            row = QHBoxLayout()
            sp_min = _spin(dec=2, val=0.0)
            sp_max = _spin(dec=2, val=0.0)
            row.addWidget(QLabel("Flux min :"))
            row.addWidget(sp_min)
            row.addWidget(QLabel("Flux max :"))
            row.addWidget(sp_max)
            row.addStretch()
            vbox.addLayout(row)
            self.type_widgets[type_flux] = (sp_min, sp_max)

            if type_flux == "Intra":
                row2 = QHBoxLayout()
                self.intra_size_min = _spin(maxi=200, dec=1, val=2.0, step=0.5, suffix=" mm")
                self.intra_size_max = _spin(maxi=200, dec=1, val=14.0, step=0.5, suffix=" mm")
                row2.addWidget(QLabel("Taille rond min :"))
                row2.addWidget(self.intra_size_min)
                row2.addWidget(QLabel("max :"))
                row2.addWidget(self.intra_size_max)
                row2.addStretch()
                vbox.addLayout(row2)
                row3 = QHBoxLayout()
                self.intra_contour = _spin(maxi=20, dec=2, val=0.4, step=0.1, suffix=" mm")
                row3.addWidget(QLabel("Epaisseur du contour :"))
                row3.addWidget(self.intra_contour)
                row3.addStretch()
                vbox.addLayout(row3)

            lay.addWidget(sub)
        hint = QLabel("0 = pas de borne (et taille auto pour l'Intra). "
                      "Le bouton 'Charger les donnees' pre-remplit les min/max reels.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return box

    def _bloc_sortie(self):
        box = QGroupBox("Dossier de sortie")
        lay = QHBoxLayout(box)
        self.out_widget = QgsFileWidget()
        self.out_widget.setStorageMode(QgsFileWidget.GetDirectory)
        lay.addWidget(QLabel("Dossier :"))
        lay.addWidget(self.out_widget)
        return box

    # ------------------------------------------------------------------ #
    @staticmethod
    def _select_field(combo, name):
        idx = combo.findText(name)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    @staticmethod
    def _select_combo(combo, name):
        idx = combo.findText(name)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setEditText(name)

    def _open_excel(self):
        path = self.excel_widget.filePath()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Fichier manquant",
                                "Choisissez d'abord un fichier Excel valide.")
            return None
        layer = QgsVectorLayer(path, "flux_tmp", "ogr")
        if not layer.isValid():
            QMessageBox.warning(self, "Lecture impossible",
                                "QGIS n'a pas pu lire ce fichier.")
            return None
        return layer

    def load_data(self):
        layer = self._open_excel()
        if layer is None:
            return
        names = [f.name() for f in layer.fields()]
        for combo, default in ((self.cmb_origin, "Commune d'origine"),
                               (self.cmb_dest, "Commune de destination"),
                               (self.cmb_flux, "Flux"),
                               (self.cmb_type, "Type flux")):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            self._select_combo(combo, default)
            combo.blockSignals(False)

        flux_name = self.cmb_flux.currentText()
        type_name = self.cmb_type.currentText()
        if flux_name not in names or type_name not in names:
            QMessageBox.information(self, "Champs",
                                    "Verifiez les champs Flux et Type flux, "
                                    "puis relancez 'Charger les donnees'.")
            return

        stats = {t: [None, None, 0] for t in TYPES_FLUX}  # min, max, nb
        for feat in layer.getFeatures():
            t = match_type(feat[type_name])
            if t is None:
                continue
            v = parse_flux(feat[flux_name])
            if v is None:
                continue
            lo, hi, n = stats[t]
            stats[t][0] = v if lo is None else min(lo, v)
            stats[t][1] = v if hi is None else max(hi, v)
            stats[t][2] = n + 1

        lignes = []
        for t, (lo, hi, n) in stats.items():
            sp_min, sp_max = self.type_widgets[t]
            if lo is not None:
                sp_min.setValue(lo)
                sp_max.setValue(hi)
            lignes.append("%s : %d flux, min %.2f, max %.2f"
                          % (t, n, lo or 0, hi or 0))
        QMessageBox.information(self, "Donnees chargees", "\n".join(lignes))

    def run(self):
        import processing

        layer = self.cmb_sig.currentLayer()
        path = self.excel_widget.filePath()
        folder = self.out_widget.filePath()
        if not path:
            QMessageBox.warning(self, "Entree", "Choisissez un fichier Excel.")
            return
        if layer is None:
            QMessageBox.warning(self, "Entree", "Choisissez une couche de chefs-lieux.")
            return
        if not folder:
            QMessageBox.warning(self, "Sortie", "Choisissez un dossier de sortie.")
            return

        params = {
            "EXCEL": path,
            "ORIGIN_FIELD": self.cmb_origin.currentText() or "Commune d'origine",
            "DEST_FIELD": self.cmb_dest.currentText() or "Commune de destination",
            "FLUX_FIELD": self.cmb_flux.currentText() or "Flux",
            "TYPE_FIELD": self.cmb_type.currentText() or "Type flux",
            "SIG": layer,
            "INSEE_FIELD": self.cmb_insee.currentField() or "insee_com",
            "MIN_SIZE": self.sp_min.value(),
            "MAX_SIZE": self.sp_max.value(),
            "CURVATURE": self.sp_curv.value(),
            "GAP": self.sp_gap.value(),
            "HEAD_SCALE": self.sp_head.value(),
            "INTRA_SIZE_MIN": self.intra_size_min.value(),
            "INTRA_SIZE_MAX": self.intra_size_max.value(),
            "INTRA_CONTOUR": self.intra_contour.value(),
            "OUTPUT_FOLDER": folder,
        }
        for type_flux, (_o, _s, min_key, max_key, _c) in TYPES_FLUX.items():
            sp_min, sp_max = self.type_widgets[type_flux]
            params[min_key] = sp_min.value() if sp_min.value() > 0 else None
            params[max_key] = sp_max.value() if sp_max.value() > 0 else None

        try:
            processing.runAndLoadResults(ALG_ID, params)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Erreur", str(exc))
            return
        self.iface.messageBar().pushSuccess(
            "Modelisation flux INSEE", "Traitement termine.")
