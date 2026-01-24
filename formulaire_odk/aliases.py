# -*- coding: utf-8 -*-

"""Logique liée à la checkbox CHANGE_ALIASES :
- lecture et édition des alias via une boîte de dialogue
- application des alias à la couche QGIS
"""

import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

from .utils import read_odk_mapping, PREFERRED_LABEL_LANG


class _AliasEditorDialog(QDialog):
    """Tableau : Champ (RO) | Alias proposé (RO) | Alias à appliquer (éditable)"""

    COL_FIELD = 0
    COL_PROPOSED = 1
    COL_TO_APPLY = 2

    def __init__(self, layer, odk_mapping, parent=None, used_label_col=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("ODK → QGIS : Préparer les alias")
        self.resize(860, 580)

        layout = QVBoxLayout(self)

        t = f"Colonne de label utilisée : {used_label_col or 'label'} — repeats/groupes ignorés."
        layout.addWidget(QLabel(t))

        self.tbl = QTableWidget(self)
        self.tbl.setColumnCount(3)
        self.tbl.setHorizontalHeaderLabels(["Champ", "Alias proposé (ODK)", "Alias à appliquer"])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(self.tbl.EditTrigger.AllEditTriggers)

        fields = layer.fields()
        self.tbl.setRowCount(len(fields))
        for i in range(len(fields)):
            fname = fields[i].name()
            proposed = (odk_mapping.get(fname) or odk_mapping.get(fname.lower()) or "")
            # CHAMP (RO)
            it_field = QTableWidgetItem(fname)
            it_field.setFlags(it_field.flags() ^ Qt.ItemIsEditable)
            # PROPOSÉ (RO)
            it_prop = QTableWidgetItem(proposed)
            it_prop.setFlags(it_prop.flags() ^ Qt.ItemIsEditable)
            # À APPLIQUER (éditable) : par défaut alias proposé, sinon alias courant QGIS
            default_apply = proposed or layer.attributeDisplayName(i) or ""
            it_apply = QTableWidgetItem(default_apply)

            self.tbl.setItem(i, self.COL_FIELD, it_field)
            self.tbl.setItem(i, self.COL_PROPOSED, it_prop)
            self.tbl.setItem(i, self.COL_TO_APPLY, it_apply)

        layout.addWidget(self.tbl, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def field_mapping(self):
        """Retourne une liste de dicts style FieldMapping pour l'application des alias."""
        out = []
        for r in range(self.tbl.rowCount()):
            it_field = self.tbl.item(r, self.COL_FIELD)
            it_apply = self.tbl.item(r, self.COL_TO_APPLY)
            fname = it_field.text() if it_field else ""
            alias = it_apply.text().strip() if it_apply else ""
            if not fname:
                continue
            out.append({"name": alias, "expression": f'"{fname}"'})
        return out


def run_change_aliases(layer, xls_path, feedback, parent=None):
    """Exécute la logique de mise à jour des alias pour la couche donnée.

    - Lit le mapping ODK (name -> label)
    - Ouvre la boîte de dialogue d'édition
    - Applique les alias choisis par l'utilisateur
    """
    odk_mapping, used_label = read_odk_mapping(xls_path, PREFERRED_LABEL_LANG)

    feedback.pushInfo(f"XLS lu : {xls_path}")
    feedback.pushInfo(f"Colonne de label utilisée : {used_label or 'label'}")
    feedback.pushInfo(f"Paires ODK name->label : {len(odk_mapping)}")
    if not odk_mapping:
        feedback.reportError(
            "Aucune paire extraite depuis 'survey'. "
            "Vérifie la présence de 'type', 'name' et 'label'/'label::fr'. "
            "Pour les .xls, installe 'xlrd>=2.0' ou convertis en .xlsx."
        )

    dlg = _AliasEditorDialog(layer, odk_mapping, parent=parent, used_label_col=used_label)
    if dlg.exec_() != QDialog.Accepted:
        feedback.pushInfo("Alias : action annulée par l'utilisateur, aucun alias appliqué.")
        return

    field_mapping = dlg.field_mapping()

    applied, missing = 0, []
    for row in field_mapping:
        alias = (row.get("name") or "").strip()
        expr = (row.get("expression") or "").strip()

        # Extraire le nom de champ depuis l'expression
        m = re.fullmatch(r'\s*"([^"]+)"\s*', expr) or re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*", expr)
        src_field = m.group(1) if m else None
        if not src_field:
            continue

        idx = layer.fields().indexFromName(src_field)
        if idx < 0:
            missing.append(src_field)
            continue

        if alias:
            layer.setFieldAlias(idx, alias)
            applied += 1

    layer.updateFields()

    feedback.pushInfo(f"{applied} alias appliqués.")
    if missing:
        feedback.pushInfo("Champs introuvables pour les alias : " + ", ".join(sorted(set(missing))))
