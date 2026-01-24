# -*- coding: utf-8 -*-

"""Logique liée à la checkbox FILL_LIST :
- lecture de la feuille 'choices'
- remplissage automatique de la couche de listes QGIS
"""

from qgis.core import QgsFeature

from .utils import PREFERRED_LABEL_LANG, read_odk_choices


def run_fill_list(list_layer, xls_path, field_list_name, field_name, field_label, feedback):
    """Remplit automatiquement la couche de listes depuis la feuille 'choices'."""
    choices = read_odk_choices(xls_path, PREFERRED_LABEL_LANG)
    if not choices:
        feedback.pushInfo(
            "Aucune entrée trouvée dans la feuille 'choices' du XLSForm : remplissage de la couche de listes ignoré."
        )
        return

    fields = list_layer.fields()
    prov = list_layer.dataProvider()

    idx_list_name = fields.indexFromName(field_list_name)
    idx_name = fields.indexFromName(field_name)
    idx_label = fields.indexFromName(field_label)

    if idx_list_name < 0 or idx_name < 0 or idx_label < 0:
        feedback.reportError(
            "Les champs de rôle (list_name, name, label) n'existent pas dans la couche de listes."
        )
        return

    if not list_layer.isEditable():
        list_layer.startEditing()

    # Supprimer les enregistrements existants
    all_ids = [f.id() for f in list_layer.getFeatures()]
    if all_ids:
        prov.deleteFeatures(all_ids)

    # Insérer les nouveaux enregistrements
    feats = []
    for c in choices:
        feat = QgsFeature(fields)
        feat.setAttribute(idx_list_name, c.get("list_name"))
        feat.setAttribute(idx_name, c.get("name"))
        feat.setAttribute(idx_label, c.get("label"))
        feats.append(feat)

    if feats:
        prov.addFeatures(feats)

    if not list_layer.commitChanges():
        list_layer.rollBack()
        feedback.reportError(
            "Échec du remplissage automatique de la couche de listes (commit)."
        )
    else:
        feedback.pushInfo(
            f"Couche de listes remplie automatiquement depuis 'choices' ({len(choices)} lignes)."
        )
