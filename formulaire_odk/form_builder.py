# -*- coding: utf-8 -*-

"""Logique liée à la checkbox CREATE_FORM :
- lecture des groupes ODK
- construction d'un formulaire par glisser-déposer avec onglets par groupe
"""

from qgis.core import (
    QgsEditFormConfig,
    QgsAttributeEditorContainer,
    QgsAttributeEditorField,
)

from .utils import PREFERRED_LABEL_LANG, read_odk_groups


def run_create_form(layer, xls_path, feedback):
    """Construit un formulaire par glisser-déposer basé sur les groupes ODK."""
    field_groups = read_odk_groups(xls_path, PREFERRED_LABEL_LANG) or {}

    if field_groups:
        grp_labels = sorted({v for v in field_groups.values() if v})
        feedback.pushInfo(
            f"Groupes ODK détectés pour {len(field_groups)} champs : "
            + ", ".join(grp_labels[:10])
            + (" ..." if len(grp_labels) > 10 else "")
        )
    else:
        feedback.pushInfo(
            "Aucun groupe ODK détecté dans la feuille 'survey' : les champs seront tous au même niveau."
        )

    cfg = layer.editFormConfig()

    root = None
    if hasattr(cfg, "invisibleRootContainer"):
        root = cfg.invisibleRootContainer()

    if root is None:
        feedback.pushInfo(
            "Impossible d'accéder au conteneur racine du formulaire, création automatique annulée."
        )
        return

    # Nettoyer les onglets existants
    try:
        feedback.pushInfo("Formulaire existant : effacement des onglets (clearTabs).")
        cfg.clearTabs()
    except Exception as e_clear:
        feedback.pushInfo(f"Impossible d'effacer les onglets existants : {e_clear}")

    # Désactiver tout .ui externe et forcer TabLayout
    try:
        cfg.setUiForm("")
        feedback.pushInfo("Chemin de formulaire .ui réinitialisé (vide).")
    except Exception:
        pass

    cfg.setLayout(QgsEditFormConfig.TabLayout)
    feedback.pushInfo(f"Layout du formulaire défini sur TabLayout (valeur interne={cfg.layout()}).")

    # Onglets par groupe + onglet "Général" pour les champs sans groupe
    tabs = {}
    general_tab = None

    fields_layer = layer.fields()
    feedback.pushInfo(f"Nombre de champs dans la couche QGIS : {len(fields_layer)}")

    for idx in range(len(fields_layer)):
        f = fields_layer[idx]
        fname = f.name()
        # On ne touche pas au champ id
        if fname.lower() == "id":
            feedback.pushInfo(f"Champ ignoré pour le formulaire (id) : {fname}")
            continue

        grp_label = field_groups.get(fname) or field_groups.get(fname.lower()) or ""

        if grp_label:
            if grp_label not in tabs:
                feedback.pushInfo(f"Création d'un onglet pour le groupe ODK : {grp_label}")
                tab = QgsAttributeEditorContainer(grp_label, root)
                tab.setIsGroupBox(False)
                cfg.addTab(tab)
                tabs[grp_label] = tab
            parent_container = tabs[grp_label]
            feedback.pushInfo(f"Champ {fname} affecté à l'onglet de groupe : {grp_label}")
        else:
            if general_tab is None:
                feedback.pushInfo(
                    "Création de l'onglet 'Général' pour les champs sans groupe."
                )
                general_tab = QgsAttributeEditorContainer("Général", root)
                general_tab.setIsGroupBox(False)
                cfg.addTab(general_tab)
            parent_container = general_tab
            feedback.pushInfo(f"Champ {fname} affecté à l'onglet : Général")

        elem = QgsAttributeEditorField(fname, idx, parent_container)
        parent_container.addChildElement(elem)

    # Log de la structure finale
    try:
        children = root.children()
        feedback.pushInfo(
            f"Nombre de conteneurs au niveau racine (root.children) : {len(children)}"
        )
        for c in children:
            try:
                cname = c.name() if hasattr(c, "name") else str(c)
                is_group = c.isGroupBox() if hasattr(c, "isGroupBox") else None
                sub = c.children() if hasattr(c, "children") else []
                feedback.pushInfo(
                    f" - Conteneur '{cname}' (groupBox={is_group}), nombre d'enfants : {len(sub)}"
                )
            except Exception:
                continue
    except Exception:
        pass

    layer.setEditFormConfig(cfg)
    feedback.pushInfo(
        "Formulaire par glisser-déposer créé à partir des groupes ODK (onglets par groupe)."
    )
