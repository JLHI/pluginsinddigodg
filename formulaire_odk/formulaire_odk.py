
# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFile,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterField,
    QgsProcessingParameterMapLayer,
    QgsProcessing,
)

import os

from .aliases import run_change_aliases
from .widgets_logic import run_check_fields
from .form_builder import run_create_form
from .list_fill import run_fill_list

# ----------------------------------------------------------------------
# Algorithme Processing — même structure et même nom de classe
# ----------------------------------------------------------------------
class OdkFormToQgis(QgsProcessingAlgorithm):
    """
    Applique les alias d’une couche QGIS à partir d’un XLSForm (ODK),
    avec édition préalable des alias dans une modale (compatible QGIS 3.28).
    """

    INPUT_LAYER = "INPUT_LAYER"
    INPUT_XLS = "INPUT_XLS"
    LIST_LAYER = "LIST_LAYER"
    CHANGE_ALIASES = "CHANGE_ALIASES"
    CHECK_FIELDS = "CHECK_FIELDS"
    CREATE_FORM = "CREATE_FORM"
    FILL_LIST = "FILL_LIST"
    LIST_FIELD_LISTNAME = "LIST_FIELD_LISTNAME"
    LIST_FIELD_NAME = "LIST_FIELD_NAME"
    LIST_FIELD_LABEL = "LIST_FIELD_LABEL"

    # IMPORTANT : exécuter dans le thread GUI (sinon crash à l'édition de la modale)
    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    # ------------------------------------------------------------------
    def initAlgorithm(self, config=None):
        # Couche cible
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                self.tr("Couche QGIS à mettre à jour")
            )
        )
        # Fichier XLS/XLSX
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_XLS,
                self.tr("Fichier XLSForm (xls / xlsx)"),
                behavior=QgsProcessingParameterFile.File,
                fileFilter="Excel (*.xls *.xlsx)"
            )
        )

        # Checkbox 1 : contrôle la mise à jour des alias
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CHANGE_ALIASES,
                self.tr("Mettre à jour les alias depuis le XLSForm"),
                defaultValue=True
            )
        )

        # Checkbox 2 : Ajouter les Widgets
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CHECK_FIELDS,
                self.tr("Ajouter les Widgets"),
                defaultValue=False
            )
        )

        # Checkbox 3 : créer un formulaire par glisser-déposer (groupes ODK) s'il n'existe pas
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CREATE_FORM,
                self.tr("Créer un formulaire par glisser-déposer à partir des groupes ODK (si aucun n'existe)"),
                defaultValue=True,
            )
        )

        # Checkbox 4 : remplir automatiquement la couche de listes depuis la feuille 'choices'
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.FILL_LIST,
                self.tr("Remplir automatiquement la couche de listes depuis la feuille 'choices' du XLSForm"),
                defaultValue=False,
            )
        )


        # Couche/table QGIS des listes, utilisée quand CHECK_FIELDS est coché
        # On passe par un paramètre "map layer" filtré sur les couches/vector tables
        param_list_layer = QgsProcessingParameterMapLayer(
            self.LIST_LAYER,
            self.tr("Couche/table QGIS contenant les listes"),
            types=[QgsProcessing.TypeVector],
            optional=True
        )
        self.addParameter(param_list_layer)

        # Champs de la couche de listes : list_name, name, label
        self.addParameter(
            QgsProcessingParameterField(
                self.LIST_FIELD_LISTNAME,
                self.tr("Champ jouant le rôle de list_name"),
                parentLayerParameterName=self.LIST_LAYER,
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.LIST_FIELD_NAME,
                self.tr("Champ jouant le rôle de name"),
                parentLayerParameterName=self.LIST_LAYER,
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.LIST_FIELD_LABEL,
                self.tr("Champ jouant le rôle de label"),
                parentLayerParameterName=self.LIST_LAYER,
                optional=True
            )
        )

    # ------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        xls_path = self.parameterAsFile(parameters, self.INPUT_XLS, context)

        # Lecture des checkboxes
        do_change_aliases = self.parameterAsBool(parameters, self.CHANGE_ALIASES, context)
        do_check_fields = self.parameterAsBool(parameters, self.CHECK_FIELDS, context)
        do_create_form = self.parameterAsBool(parameters, self.CREATE_FORM, context)
        do_fill_list = self.parameterAsBool(parameters, self.FILL_LIST, context)

        if layer is None:
            raise QgsProcessingException("Couche invalide.")
        if not xls_path or not os.path.exists(xls_path):
            raise QgsProcessingException("Fichier XLSForm introuvable.")

        # Si rien n'est coché, on ne fait rien
        if not (do_change_aliases or do_check_fields or do_create_form or do_fill_list):
            feedback.pushInfo("Aucune option cochée : aucun traitement effectué.")
            return {}

        # 1) Mise à jour des alias (si demandé)
        if do_change_aliases:
            run_change_aliases(layer, xls_path, feedback)

        # 2) Couche de listes : utilisée pour les contrôles et/ou le remplissage automatique
        if do_check_fields or do_fill_list:
            # Couche/table de listes obligatoire si l'une des options la nécessite
            list_layer = self.parameterAsLayer(parameters, self.LIST_LAYER, context)
            if list_layer is None:
                raise QgsProcessingException(
                    "Une option utilisant la couche de listes est cochée, "
                    "mais aucune couche/table de listes n'est renseignée."
                )

            # Récupérer les choix de l'utilisateur pour list_name, name, label
            field_list_name = self.parameterAsString(parameters, self.LIST_FIELD_LISTNAME, context)
            field_name = self.parameterAsString(parameters, self.LIST_FIELD_NAME, context)
            field_label = self.parameterAsString(parameters, self.LIST_FIELD_LABEL, context)

            missing_choice = []
            if not field_list_name:
                missing_choice.append("champ list_name")
            if not field_name:
                missing_choice.append("champ name")
            if not field_label:
                missing_choice.append("champ label")

            if missing_choice:
                raise QgsProcessingException(
                    "Veuillez renseigner dans les paramètres : "
                    + ", ".join(missing_choice)
                    + " pour la couche de listes."
                )

            # Vérifier que ces champs existent réellement dans la couche de listes
            fields = list_layer.fields()
            for fname in (field_list_name, field_name, field_label):
                if fields.indexFromName(fname) < 0:
                    raise QgsProcessingException(
                        f"Le champ '{fname}' n'existe pas dans la couche de listes."
                    )

            feedback.pushInfo(
                f"Couche de listes OK ({list_layer.featureCount()} enregistrements) avec : "
                f"list_name = {field_list_name}, name = {field_name}, label = {field_label}."
            )

            # 2.a) Optionnel : remplir automatiquement la couche de listes depuis 'choices'
            if do_fill_list:
                run_fill_list(list_layer, xls_path, field_list_name, field_name, field_label, feedback)
        # 3) Contrôle des champs / contraintes (widgets)
        if do_check_fields:
            run_check_fields(layer, list_layer, field_list_name, field_name, field_label, xls_path, feedback)

        # 4) Création automatique d'un formulaire par glisser-déposer (un seul onglet, groupes ODK)
        if do_create_form:
            run_create_form(layer, xls_path, feedback)
        return {}

    # ------------------------------------------------------------------
    def name(self):
        return "odk_alias_from_xlsform_processing"

    def displayName(self):
        return self.tr("ODK - Construire le formulaire Qgis")

    def group(self):
        return self.tr("ODK")

    def groupId(self):
        return "odk"

    def shortHelpString(self):
        return self.tr(
            "Lit un XLS/XLSX (XLSForm), propose les alias (label::fr prioritaire), "
            "ignore repeats/groupes, ouvre une fenêtre d’édition, puis applique les alias."
            "Crée le bon Widget selon le type ( Valeur relationnel, Photo) et génère les contraintes (Filtre des valeurs relationnelles et chemin des photos)."
            "Ne fonctionne pas pour le choix multiple"

        )

    def createInstance(self):
        return OdkFormToQgis()

    def tr(self, s):
        return QCoreApplication.translate("Processing", s)
