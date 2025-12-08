# -*- coding: utf-8 -*-
"""
Dialogue simple pour sélectionner les couches/groupes à exporter.

Affiche un arbre des groupes et couches avec checkbox. Retourne la liste
des IDs de couches cochées et permet de lancer l'export en choisissant un
fichier de sortie .xlsx.
"""

from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QLabel,
)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject

from .metaddigo import MetaddigoExportMetadataAlgorithm
from qgis.core import QgsProcessingContext, QgsProcessingFeedback


class MetaddigoDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Export métadonnées - Metaddigo')
        self.resize(700, 500)

        layout = QVBoxLayout()
        self.setLayout(layout)

        lbl = QLabel('Sélectionnez les couches à exporter :')
        layout.addWidget(lbl)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['', 'Nom', 'Groupe / chemin', 'Type'])
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(2, 300)
        self.table.setColumnWidth(3, 100)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        layout.addLayout(btn_layout)

        self.btn_select_output = QPushButton('Choisir fichier de sortie...')
        btn_layout.addWidget(self.btn_select_output)

        self.btn_check_all = QPushButton('Cocher tout')
        btn_layout.addWidget(self.btn_check_all)

        self.btn_uncheck_all = QPushButton('Décocher tout')
        btn_layout.addWidget(self.btn_uncheck_all)

        self.btn_invert = QPushButton('Inverser sélection')
        btn_layout.addWidget(self.btn_invert)

        self.btn_run = QPushButton('Exporter')
        btn_layout.addWidget(self.btn_run)

        self.btn_cancel = QPushButton('Annuler')
        btn_layout.addWidget(self.btn_cancel)

        self.btn_select_output.clicked.connect(self.choose_output)
        self.btn_run.clicked.connect(self.run_export)
        self.btn_cancel.clicked.connect(self.reject)

        self.output_path = ''

        self._populate_table()

    def _layer_group_path(self, layer):
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer.id())
        if not node:
            return 'RACINE'
        names = []
        parent = node.parent()
        from qgis.core import QgsLayerTreeGroup
        while parent and isinstance(parent, QgsLayerTreeGroup):
            names.insert(0, parent.name())
            parent = parent.parent()
        return ' > '.join(names) if names else 'RACINE'

    def _populate_table(self):
        layers = list(QgsProject.instance().mapLayers().values())
        self.table.setRowCount(len(layers))
        for r, layer in enumerate(layers):
            # Checkbox item
            item_check = QTableWidgetItem()
            item_check.setFlags(item_check.flags() | Qt.ItemIsUserCheckable)
            item_check.setCheckState(Qt.Unchecked)
            item_check.setData(Qt.UserRole, layer.id())
            self.table.setItem(r, 0, item_check)

            item_name = QTableWidgetItem(layer.name())
            item_name.setFlags(item_name.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 1, item_name)

            gp = self._layer_group_path(layer)
            item_group = QTableWidgetItem(gp)
            item_group.setFlags(item_group.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 2, item_group)

            ltype = 'Vecteur' if layer.type() == layer.VectorLayer else 'Raster'
            item_type = QTableWidgetItem(ltype)
            item_type.setFlags(item_type.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 3, item_type)

        self.table.resizeRowsToContents()

        # Connect buttons
        self.btn_check_all.clicked.connect(self.check_all)
        self.btn_uncheck_all.clicked.connect(self.uncheck_all)
        self.btn_invert.clicked.connect(self.invert_selection)

    def _on_item_changed(self, item, column):
        # if group toggled, apply to children
        state = item.checkState(0)
        for i in range(item.childCount()):
            child = item.child(i)
            child.setCheckState(0, state)

    def choose_output(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Fichier Excel de sortie', '', 'Excel files (*.xlsx)')
        if path:
            if not path.lower().endswith('.xlsx'):
                path += '.xlsx'
            self.output_path = path

    def _gather_checked_layer_ids(self):
        ids = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.checkState() == Qt.Checked:
                lid = it.data(Qt.UserRole)
                if lid:
                    ids.append(lid)
        return ids

    def check_all(self):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(Qt.Checked)

    def uncheck_all(self):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(Qt.Unchecked)

    def invert_selection(self):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it:
                it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def run_export(self):
        if not self.output_path:
            QMessageBox.warning(self, 'Sortie manquante', 'Veuillez choisir un fichier de sortie .xlsx')
            return

        ids = self._gather_checked_layer_ids()

        # Préparer et exécuter l'algorithme
        alg = MetaddigoExportMetadataAlgorithm()
        fb = QgsProcessingFeedback()

        try:
            alg.export_layers(self.output_path, ids, fb)
            QMessageBox.information(self, 'Export', f'Export terminé : {self.output_path}')
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, 'Erreur', f"Erreur lors de l'export : {e}")
    
    def selected_layer_ids(self):
        """Retourne la liste des IDs des couches cochées (API publique)."""
        return self._gather_checked_layer_ids()
