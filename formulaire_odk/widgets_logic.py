# -*- coding: utf-8 -*-

"""Logique liée à la checkbox CHECK_FIELDS :
- lecture des métadonnées ODK (select_one, images, types simples)
- prévisualisation des widgets
- application des widgets QGIS sur la couche cible
"""

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
from qgis.core import QgsEditorWidgetSetup

from .utils import (
    PREFERRED_LABEL_LANG,
    read_odk_select_one,
    read_odk_images,
    read_odk_basic_types,
)


class _RelValueDialog(QDialog):
    """Tableau de prévisualisation des widgets (valeur relationnelle, image, etc.)."""

    COL_FIELD = 0
    COL_WIDGET = 1
    COL_LAYER = 2
    COL_KEY = 3
    COL_VALUE = 4
    COL_ALLOWNULL = 5
    COL_FILTER = 6
    COL_DEFAULT_PATH = 7
    COL_RELATIVE = 8

    def __init__(self, layer, list_layer, field_list_name, field_name, field_label,
                 select_one_info, image_fields, basic_types, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("ODK → QGIS : Widgets valeur relationnelle (select_one)")
        self.resize(1000, 600)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Configuration proposée pour les champs de type 'select_one'"))

        self.tbl = QTableWidget(self)
        self.tbl.setColumnCount(9)
        self.tbl.setHorizontalHeaderLabels([
            "Champ QGIS",
            "Type de widget",
            "Couche de listes",
            "Clé (champ name)",
            "Valeur (champ label)",
            "Autoriser NULL",
            "Filtre (list_name)",
            "Chemin par défaut",
            "Chemin relatif",
        ])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setEditTriggers(self.tbl.EditTrigger.NoEditTriggers)

        fields = layer.fields()
        rows = []
        for i in range(len(fields)):
            field_def = fields[i]
            fname = field_def.name()

            # On laisse le champ id tranquille : pas de widget forcé
            if fname.lower() == "id":
                rows.append((fname, "", "", "", "", "", "", "", ""))
                continue

            info = select_one_info.get(fname)
            is_select_one = bool(info and info.get("list_name"))
            is_image = fname in image_fields

            # Type de base issu du XLSForm, éventuellement complété par le type QGIS
            base_type = (basic_types.get(fname) or basic_types.get(fname.lower()) or "").lower()
            if not base_type:
                type_name = (field_def.typeName() or "").lower()
                if any(k in type_name for k in ("int", "integer", "smallint", "bigint")):
                    base_type = "integer"
                elif any(k in type_name for k in ("double", "real", "float", "numeric", "decimal")):
                    base_type = "decimal"
                elif type_name:
                    base_type = "text"

            list_name = info.get("list_name") if info else ""
            filter_expr = ""
            widget_type = ""
            layer_name = ""
            key_name = ""
            value_name = ""
            allow_null = ""
            default_path = ""
            relative_txt = ""

            if is_select_one:
                widget_type = "Valeur relationnelle"
                layer_name = list_layer.name()
                # La clé stockée dans la couche = code (name), valeur affichée = label
                key_name = field_name
                value_name = field_label
                allow_null = "Oui"
                if list_name:
                    ln_escaped = list_name.replace("'", "''")
                    filter_expr = f'"{field_list_name}" = \'{ln_escaped}\''
            elif is_image:
                widget_type = "Ressource externe (image)"
                # Expression pour le chemin par défaut
                default_path = (
                    f"if(left(\"{fname}\", 4) = 'http', "
                    f"'https://geo.inddigo.com/odkimages/', 'media/')"
                )
                relative_txt = "Oui"
            else:
                # Widgets simples en fonction du type ODK de base
                if base_type in ("integer", "int"):
                    widget_type = "Nombre entier (0-10000)"
                elif base_type in ("decimal", "double", "real", "float"):
                    widget_type = "Nombre réel (0-10000)"
                elif base_type == "text":
                    widget_type = "Texte"

            rows.append((fname, widget_type, layer_name, key_name, value_name,
                         allow_null, filter_expr, default_path, relative_txt))

        self.tbl.setRowCount(len(rows))

        for r, (fname, widget_type, layer_name, key_name, value_name,
                allow_null, filter_expr, default_path, relative_txt) in enumerate(rows):
            it_field = QTableWidgetItem(fname)
            it_widget = QTableWidgetItem(widget_type)
            it_layer = QTableWidgetItem(layer_name)
            it_key = QTableWidgetItem(key_name)
            it_value = QTableWidgetItem(value_name)
            it_allownull = QTableWidgetItem(allow_null)
            it_filter = QTableWidgetItem(filter_expr)
            it_default = QTableWidgetItem(default_path)
            it_relative = QTableWidgetItem(relative_txt)

            for it in (it_field, it_widget, it_layer, it_key, it_value,
                       it_allownull, it_filter, it_default, it_relative):
                it.setFlags(it.flags() ^ Qt.ItemIsEditable)

            self.tbl.setItem(r, self.COL_FIELD, it_field)
            self.tbl.setItem(r, self.COL_WIDGET, it_widget)
            self.tbl.setItem(r, self.COL_LAYER, it_layer)
            self.tbl.setItem(r, self.COL_KEY, it_key)
            self.tbl.setItem(r, self.COL_VALUE, it_value)
            self.tbl.setItem(r, self.COL_ALLOWNULL, it_allownull)
            self.tbl.setItem(r, self.COL_FILTER, it_filter)
            self.tbl.setItem(r, self.COL_DEFAULT_PATH, it_default)
            self.tbl.setItem(r, self.COL_RELATIVE, it_relative)

        layout.addWidget(self.tbl, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, Qt.Horizontal, self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def configs(self):
        """Retourne une liste de dicts décrivant la config de widget par champ."""
        out = []
        for r in range(self.tbl.rowCount()):
            it_field = self.tbl.item(r, self.COL_FIELD)
            it_widget = self.tbl.item(r, self.COL_WIDGET)
            it_filter = self.tbl.item(r, self.COL_FILTER)
            it_default = self.tbl.item(r, self.COL_DEFAULT_PATH)
            fname = it_field.text() if it_field else ""
            widget_type = it_widget.text() if it_widget else ""
            filter_expr = it_filter.text() if it_filter else ""
            default_path = it_default.text() if it_default else ""
            if not fname:
                continue
            if widget_type == "Valeur relationnelle":
                out.append({"field": fname, "kind": "relation", "filter": filter_expr})
            elif widget_type.startswith("Ressource externe"):
                out.append({"field": fname, "kind": "image", "default_path": default_path})
            elif widget_type.startswith("Nombre entier"):
                out.append({"field": fname, "kind": "int_range", "min": 0, "max": 10000})
            elif widget_type.startswith("Nombre réel"):
                out.append({"field": fname, "kind": "real_range", "min": 0, "max": 10000})
            elif widget_type == "Texte":
                out.append({"field": fname, "kind": "text"})
        return out


def run_check_fields(layer, list_layer, field_list_name, field_name, field_label, xls_path, feedback, parent=None):
    """Exécute la logique de la checkbox CHECK_FIELDS :
    - lit le XLSForm pour récupérer select_one, images, types simples
    - ouvre la boîte de dialogue de prévisualisation
    - applique les widgets à la couche
    """
    select_one_info = read_odk_select_one(xls_path, PREFERRED_LABEL_LANG)
    image_fields = read_odk_images(xls_path)
    basic_types = read_odk_basic_types(xls_path)

    if not select_one_info and not image_fields and not basic_types:
        feedback.pushInfo(
            "Aucun champ exploitable (select_one / image / text / integer / real) trouvé dans le XLSForm."
        )
        return

    rel_dlg = _RelValueDialog(
        layer,
        list_layer,
        field_list_name,
        field_name,
        field_label,
        select_one_info,
        image_fields,
        basic_types,
        parent=parent,
    )

    if rel_dlg.tbl.rowCount() == 0:
        feedback.pushInfo(
            "Aucun champ de la couche QGIS n'est concerné (select_one / image / types simples)."
        )
        return

    if rel_dlg.exec_() != QDialog.Accepted:
        feedback.pushInfo("Configuration des widgets annulée par l'utilisateur.")
        return

    configs = rel_dlg.configs()
    applied_rel = applied_img = applied_int = applied_real = applied_text = 0

    for cfg in configs:
        fname = cfg.get("field")
        kind = cfg.get("kind")
        if not fname or not kind:
            continue
        idx = layer.fields().indexFromName(fname)
        if idx < 0:
            continue

        if kind == "relation":
            filter_expr = cfg.get("filter") or ""
            config = {
                "Layer": list_layer.id(),
                # Stocker le code (name) et afficher le label
                "Key": field_name,
                "Value": field_label,
                "AllowNull": True,
                "FilterExpression": filter_expr,
            }
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("ValueRelation", config))
            applied_rel += 1
        elif kind == "image":
            default_path = cfg.get("default_path") or ""
            img_config = {
                "DocumentViewer": 1,  # QgsExternalResourceWidget::Image
                "DefaultRoot": default_path,
                "RelativeStorage": 1,
            }
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("ExternalResource", img_config))
            applied_img += 1
        elif kind == "int_range":
            cfg_min = cfg.get("min", 0)
            cfg_max = cfg.get("max", 10000)
            int_cfg = {
                "Style": 0,
                "Min": cfg_min,
                "Max": cfg_max,
                "Step": 1,
            }
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("Range", int_cfg))
            applied_int += 1
        elif kind == "real_range":
            cfg_min = cfg.get("min", 0.0)
            cfg_max = cfg.get("max", 10000.0)
            real_cfg = {
                "Style": 0,
                "Min": cfg_min,
                "Max": cfg_max,
                "Step": 1.0,
                "Decimals": 2,
            }
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("Range", real_cfg))
            applied_real += 1
        elif kind == "text":
            text_cfg = {}
            layer.setEditorWidgetSetup(idx, QgsEditorWidgetSetup("TextEdit", text_cfg))
            applied_text += 1

    feedback.pushInfo(f"{applied_rel} widgets 'valeur relationnelle' appliqués.")
    if applied_img:
        feedback.pushInfo(f"{applied_img} widgets 'ressource externe (image)' appliqués.")
    if applied_int:
        feedback.pushInfo(f"{applied_int} widgets 'entier (0-10000)' appliqués.")
    if applied_real:
        feedback.pushInfo(f"{applied_real} widgets 'réel (0-10000)' appliqués.")
    if applied_text:
        feedback.pushInfo(f"{applied_text} widgets 'texte' appliqués.")
