# -*- coding: utf-8 -*-
"""
Lecture d'un fichier SIG (shapefile, gpkg, etc.) basé sur des observations naturalistes
(avifaune, chiroptère, faune) afin de générer en sortie un fichier Excel (.xlsx) au format
attendu par la SINP (Système d’Information de l’iNventaire du Patrimoine naturel)

Intégré comme algorithme Processing pour pouvoir l'exécuter depuis la boîte à
outils Processing ou via un modèle.

"""

# ------------------------------------------------------------------------------------
# Import des bibliothèques
# ------------------------------------------------------------------------------------

import os, csv, uuid, datetime, re, unicodedata
import xlsxwriter

from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterField,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingException,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsField,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsProject,
    QgsProcessing,
    QgsWkbTypes,
    NULL
)
from PyQt5.QtCore import QVariant

# ------------------------------------------------------------------------------------
# Fonctions utilitaires
# ------------------------------------------------------------------------------------
def strip_accents(s: str) -> str:
    """Supprime les diacritiques (accents) en conservant les lettres de base."""
    if s is None:
        return ""
    s = str(s)
    # Normalisation : NFKD + suppression des marks (Mn)
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")

def is_qgis_null(v):
    """
    Détecte toutes les formes de NULL QGIS (LTR-safe)
    """
    if v is None:
        return True
    if v is NULL:
        return True
    # QVariant NULL (selon versions)
    try:
        if isinstance(v, QVariant) and v.isNull():
            return True
    except Exception:
        pass
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("", "null", "none", "nan"):
            return True
    return False

# Normalise un nom ou valeur
"""Convertit en minuscule, supprime espaces superflus."""
def normalise(value):
    return (str(value or "").strip().lower())

def normalize_for_match(s: str) -> str:
    """
    Normalise une chaîne pour la comparaison :
    - harmonise apostrophes/tirets,
    - supprime accents,
    - lower + compressions d'espaces.
    """
    if s is None:
        return ""
    s = str(s).strip()
    s = s.replace("’", "'").replace("–", "-").replace("—", "-")
    s = strip_accents(s)
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    return s

def normalize_wkt_type(wkt: str) -> str:
    """
    Force le type WKT en MAJUSCULE (Polygon -> POLYGON, etc.)
    Compatible SINP / DEPOBIO.
    """
    if not wkt:
        return ""
    return re.sub(
        r"^\s*([A-Za-z]+)",
        lambda m: m.group(1).upper(),
        wkt,
        count=1
    )

# Convertir une chaine de txt en date
def parse_date_time(value):
    """
    Convertit vers 'DD/MM/YYYY' en supprimant ' (UTC)' et tout contenu entre parenthèses.
    """
    if value is None:
        return "", ""
    if isinstance(value, datetime.datetime):
        return value.date().strftime("%d/%m/%Y"), value.time().strftime("%H:%M:%S")
    if isinstance(value, datetime.date):
        return value.strftime("%d/%m/%Y"), ""
    s = str(value).strip()
    # nettoyer suffixes comme " (UTC)" ou autres entre parenthèses
    s = re.sub(r"\s*\(.*?\)\s*", " ", s).strip()
    # essais de formats usuels
    fmts = [
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"
    ]
    for fmt in fmts:
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return dt.strftime("%d/%m/%Y"), dt.strftime("%H:%M:%S")
        except Exception:
            pass
    # essais date seule
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            d = datetime.datetime.strptime(s, fmt).date()
            return d.strftime("%d/%m/%Y"), ""
        except Exception:
            pass
    # ISO
    try:
        dt = datetime.datetime.fromisoformat(s)
        return dt.date().strftime("%d/%m/%Y"), dt.time().strftime("%H:%M:%S")
    except Exception:
        return "", ""
    

# Convertion de la valeur effectif en nombre entier

def parse_effectif(value):
    """
    Convertit un effectif potentiellement texte vers (min_int, max_int).
    Exemples acceptés:
      "3" -> (3, 3)
      "2-3" / "2 – 3" / "2 à 3" -> (2, 3)
      ">5" / ">=5" / "≥ 5" -> (5, None)
      "<10" / "<=10" / "≤ 10" -> (None, 10)
      "≈5" / "~5" / "ca. 12" -> (5, 5) ou (12, 12)
      "2,0" / "2.5" -> (2, 2) (arrondi à l'entier)
    Retourne (None, None) si non interprétable.
    """

    if value is None:
        return (None, None)

    # Si déjà numérique
    if isinstance(value, (int, float)):
        try:
            n = int(round(float(value)))
            return (n, n)
        except Exception:
            return (None, None)

    s = str(value).strip()
    if not s:
        return (None, None)

    # Normalisations courantes
    s = s.lower()
    s = s.replace(",", ".")                   # décimales avec virgule
    s = s.replace("≈", "~").replace("∼", "~") # approx
    s = s.replace("ca.", "").replace("~", "") # on considère l'approx comme une valeur simple
    s = s.replace("entre", "").replace("et", "-")  # "entre 2 et 3" -> " 2 - 3"
    s = s.replace("à", "-").replace("–", "-").replace("—", "-")  # tirets

    # Retirer espaces inutiles
    s = re.sub(r"\s+", " ", s)

    # Cas des comparateurs
    m_ge = re.match(r"^[>]=?\s*(\d+(?:\.\d+)?)$", s) or re.match(r"^≥\s*(\d+(?:\.\d+)?)$", s)
    m_le = re.match(r"^[<]=?\s*(\d+(?:\.\d+)?)$", s) or re.match(r"^≤\s*(\d+(?:\.\d+)?)$", s)
    if m_ge:
        n = int(round(float(m_ge.group(1))))
        return (n, None) # au moins n
    if m_le:
        n = int(round(float(m_le.group(1))))
        return (None, n) # au plus n

    # Intervalles "a-b"
    m_int = re.match(r"^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$", s)
    if m_int:
        a = int(round(float(m_int.group(1))))
        b = int(round(float(m_int.group(2))))
        # s'assurer min <= max
        a, b = (a, b) if a <= b else (b, a)
        return (a, b)

    # Extraire le premier nombre si présent
    m_num = re.search(r"(\d+(?:\.\d+)?)", s)
    if m_num:
        n = int(round(float(m_num.group(1))))
        return (n, n)

    # Rien d'exploitable
    return (None, None)



# Génrère un UUID V4
def generate_perm_id():
    return str(uuid.uuid4()).replace("{", "").replace("}", "")

# Récuperer les en-tête d'un fichier CSV
def read_model_csv_template(csv_path, feedback):
    """
    Lit le Modèle CSV officiel (si fourni) :
    - retourne (headers, second_row) où second_row est la ligne d'astérisques.
    """
    if not csv_path or not os.path.isfile(csv_path):
        return None, None
    with open(csv_path, "r", encoding="utf-8") as f:
        # Lecture des 4096 premiers caractères
        sample = f.read(4096)
        # Détection auto du séparateur du fichier .CSV
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,")
            sep = dialect.delimiter
        except Exception:
            sep = ";"
    # Lecture complète du CSV avec le séparateur qui a été deviné
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=sep)
        rows = list(reader)
    if not rows:
        return None, None
    # Extraction et nettoyage de la première ligne (celle des en-têtes)
    headers = [h.strip() for h in rows[0]]
    second = rows[1] if len(rows) > 1 else None
    return headers, second

# Lecture d'un fichier CSV avec infos TAXREF pour conversion en dictionnaire python
def load_taxref_lookup(csv_path, feedback):
    """
    Charge TAXREF; détecte la colonne clé parmi : nomCite, nomCite_Fr, nomCite_SINP, libelle, espece, taxon
    et la colonne 'cdNom'.
    Construit un lookup double : (clé originale normalisée) et (clé sans accents) -> dict.
    """
    lookup = {}
    # Contrôle existence fichier
    if not csv_path or not os.path.isfile(csv_path):
        feedback.pushWarning("CSV TAXREF non trouvé. On tentera d'utiliser les colonnes de la couche.")
        return lookup
    
    encodings_to_try = ["utf-8", "latin-1", "utf-8-sig"]
    sep = ";"
    rows = None
    for enc in encodings_to_try:
        try:
            # Détection auto séparateur CSV
            with open(csv_path, "r", encoding=enc) as f:
                sample = f.read(4096)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=";,")
                    sep = dialect.delimiter
                except Exception:
                    sep = ";"
            #Lecture du fichier en mode dictionnaire
            with open(csv_path, "r", encoding=enc) as f:
                reader = csv.DictReader(f, delimiter=sep)
                rows = list(reader)
            feedback.pushInfo(f"Lecture TAXREF avec encodage: {enc} / sep: '{sep}' / lignes: {len(rows)}")
            break
        except Exception as e:
            feedback.pushWarning(f"Echec lecture TAXREF avec encodage {enc}: {e}")
            continue

    if not rows:
        feedback.pushWarning("Impossible de lire le CSV TAXREF (encodage inconnu).")
        return lookup

    cols = rows[0].keys()
    candidates_nom = [c for c in cols if normalise(c) in ("nomcite", "nomcite_fr", "nomcite_sinp", "libelle", "espece", "taxon")]
    col_nom = candidates_nom[0] if candidates_nom else None
    col_cd  = next((c for c in cols if normalise(c) == "cdnom"), None)

    if not col_cd or not col_nom:
        feedback.pushWarning("Colonnes TAXREF non détectées ('cdNom' et 'nomCite/nomCite_Fr').")
        return lookup

    # Construction: double clé (originale normalisée + clé de match sans accents)
    for row in rows:
        nom_raw = row.get(col_nom)
        cd = row.get(col_cd)
        if not nom_raw or not cd:
            continue
        key_orig  = normalise(nom_raw)             # ex. 'mésange charbonnière'
        key_match = normalize_for_match(nom_raw)   # ex. 'mesange charbonniere'
        lookup[key_orig]  = {"cdNom": cd, "nomCite": row.get("nomCite") or nom_raw}
        lookup[key_match] = {"cdNom": cd, "nomCite": row.get("nomCite") or nom_raw}

    feedback.pushInfo(f"{len(lookup)} clés TAXREF chargées (accent + normalisé).")
    return lookup

# mapping ocStade selon le guide SINP
OCSTADE_MAP = {
    "adulte": "2",
    "juvénile": "3",
    "juvenile": "3",
    "immature": "4",
}


# ------------------------------------------------------------------------------------
# Algorithme processing
# ------------------------------------------------------------------------------------


class MappingNaturalistDataToSinpAlgorithm(QgsProcessingAlgorithm):
    """SIG naturaliste -> CSV/Excel DEPOBIO V2"""

    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    TAXREF_CSV = "TAXREF_CSV"
    MODEL_CSV = "MODEL_CSV"
    INCLUDE_TIME     = "INCLUDE_TIME_COLUMNS"
    ADD_TO_PROJECT = "ADD_TO_PROJECT"
    ENCODING = "ENCODING"

    EFFECTIF_DUP_MIN_TO_MAX = "EFFECTIF_DUPLICATE_MIN_TO_MAX"  # option UX pour >n

    SPECIES_FIELD = "SPECIES_FIELD"
    DATE_FIELD = "DATE_FIELD"
    EFFECTIF_FIELD = "EFFECTIF_FIELD"
    OCSTADE_FIELD = "OCSTADE_FIELD"
    OCSEX_FIELD = "OCSEX_FIELD"
    COMMENT1_FIELD = "COMMENT1_FIELD"
    COMMENT2_FIELD = "COMMENT2_FIELD"
    PERMID_FIELD = "PERMID_FIELD"

    SIMPLIFY_TOL = "SIMPLIFY_TOL"
    DROP_ZERO_AUTRE = "DROP_ZERO_AUTRE"    

    OBSERVER_DEFAULT = "OBSERVER_DEFAULT"
    PRECISGEO_DEFAULT = "PRECISGEO_DEFAULT"
    OBJDENBR_DEFAULT = "OBJDENBR_DEFAULT"
    TYPDENBR_DEFAULT = "TYPDENBR_DEFAULT"
    OCETATBIO_DEFAULT = "OCETATBIO_DEFAULT"
    NATOBJGEO_DEFAULT = "NATOBJGEO_DEFAULT"
    STATOBS_DEFAULT = "STATOBS_DEFAULT"
    STATSOURCE_DEFAULT = "STATSOURCE_DEFAULT"
    TYPINFGEO_DEFAULT = "TYPINFGEO_DEFAULT"

    # -------------------- Reprojeter la couche ------------------------
    def reproject_to_2154(self, layer, context, feedback):
        target_crs = QgsCoordinateReferenceSystem("EPSG:2154")
        try:
            if layer.crs().authid() == "EPSG:2154":
                feedback.pushInfo("La couche est déjà en EPSG:2154.")
                return layer
        except Exception:
            pass
        feedback.pushInfo(f"Reprojection de {layer.name()} vers EPSG:2154...")
        transform_context = context.transformContext()
        transform = QgsCoordinateTransform(layer.crs(), target_crs, transform_context)
        wkb = layer.wkbType()
        geom_type = QgsWkbTypes.geometryType(wkb)
        if geom_type == QgsWkbTypes.PointGeometry:
            uri = "Point?crs=EPSG:2154"
        elif geom_type == QgsWkbTypes.LineGeometry:
            uri = "LineString?crs=EPSG:2154"
        elif geom_type == QgsWkbTypes.PolygonGeometry:
            uri = "Polygon?crs=EPSG:2154"
        else:
            uri = "GeometryCollection?crs=EPSG:2154"
        new_layer = QgsVectorLayer(uri, f"{layer.name()}_2154", "memory")
        new_layer.dataProvider().addAttributes(layer.fields()); new_layer.updateFields()
        dp = new_layer.dataProvider()
        for feat in layer.getFeatures():
            new_feat = QgsFeature(new_layer.fields())
            new_feat.setAttributes(feat.attributes())
            geom = feat.geometry()
            if geom and not geom.isNull():
                g = QgsGeometry(geom)
                try: g.transform(transform)
                except Exception: pass
                new_feat.setGeometry(g)
            dp.addFeature(new_feat)
        new_layer.updateExtents()
        feedback.pushInfo("Reprojection terminée.")
        return new_layer

    # -------------------- Paramètres ------------------------
    def initAlgorithm(self, config):

        self.addParameter(
            QgsProcessingParameterVectorLayer(
                "INPUT",
                self.tr("Couche ou fichier SIG"),
                [QgsProcessing.TypeVectorAnyGeometry],  # accepte point/ligne/polygone
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.MODEL_CSV,
                self.tr("Modèle CSV DEPOBIO V2 (optionnel, pour obtenir toutes les colonnes)"),
                behavior=QgsProcessingParameterFile.File,
                fileFilter="CSV (*.csv)",
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.TAXREF_CSV,
                self.tr("CSV TAXREF"),
                behavior=QgsProcessingParameterFile.File,
                fileFilter="CSV (*.csv)"
            )
        )

        self.addParameter(QgsProcessingParameterField(self.SPECIES_FIELD, self.tr("Champ espèce"), parentLayerParameterName=self.INPUT, type=QgsProcessingParameterField.Any, defaultValue="Espece"))
        self.addParameter(QgsProcessingParameterField(self.DATE_FIELD, self.tr("Champ date/heure"), parentLayerParameterName=self.INPUT, type=QgsProcessingParameterField.Any, defaultValue="Date_heure"))
        self.addParameter(QgsProcessingParameterField(self.EFFECTIF_FIELD, self.tr("Champ effectif (denbrMax)"), parentLayerParameterName=self.INPUT, type=QgsProcessingParameterField.Any, defaultValue="denbrMax"))
        self.addParameter(QgsProcessingParameterField(self.OCSTADE_FIELD, self.tr("Champ statut (ocStade)"), parentLayerParameterName=self.INPUT, type=QgsProcessingParameterField.Any, defaultValue="OcStatut", optional=True))
        self.addParameter(QgsProcessingParameterField(self.OCSEX_FIELD, self.tr("Champ sexe (ocSex)"), parentLayerParameterName=self.INPUT, type=QgsProcessingParameterField.Any, defaultValue="OcSexe", optional=True))
        self.addParameter(QgsProcessingParameterField(self.COMMENT1_FIELD, self.tr("Champ commentaire 1"), parentLayerParameterName=self.INPUT, type=QgsProcessingParameterField.Any, defaultValue="Remarque1", optional=True))
        self.addParameter(QgsProcessingParameterField(self.COMMENT2_FIELD, self.tr("Champ commentaire 2"), parentLayerParameterName=self.INPUT, type=QgsProcessingParameterField.Any, defaultValue="Remarque2", optional=True))
        self.addParameter(QgsProcessingParameterField(self.PERMID_FIELD, self.tr("Champ identifiant permanent (permId)"), parentLayerParameterName=self.INPUT, type=QgsProcessingParameterField.Any, defaultValue="permId", optional=True))
        
        self.addParameter(QgsProcessingParameterBoolean(self.INCLUDE_TIME, self.tr("Inclure heureDebut/heureFin si une heure est présente"), defaultValue=True))

        self.addParameter(QgsProcessingParameterNumber(self.SIMPLIFY_TOL, self.tr("Tolérance de simplification (m) – lignes/polygones"),
                                                       type=QgsProcessingParameterNumber.Double, defaultValue=15.0))
        self.addParameter(QgsProcessingParameterBoolean(self.DROP_ZERO_AUTRE, self.tr("Supprimer les observations '0_autre'"), defaultValue=True))
        
        self.addParameter(QgsProcessingParameterBoolean(self.EFFECTIF_DUP_MIN_TO_MAX,self.tr("Si seule une borne min est connue (>n), dupliquer min vers max"),defaultValue=True))

        # valeurs par défaut
        self.addParameter(QgsProcessingParameterString(self.OBSERVER_DEFAULT, self.tr("observer (défaut)"), defaultValue="ANONYME (INDDIGO)"))
        self.addParameter(QgsProcessingParameterNumber(self.PRECISGEO_DEFAULT, self.tr("precisGeo (m) – défaut"),
                                                       type=QgsProcessingParameterNumber.Integer, defaultValue=10))
        self.addParameter(QgsProcessingParameterString(self.OBJDENBR_DEFAULT, self.tr("objDenbr – défaut"), defaultValue="IND"))
        self.addParameter(QgsProcessingParameterString(self.TYPDENBR_DEFAULT, self.tr("typDenbr – défaut"), defaultValue="Co"))
        self.addParameter(QgsProcessingParameterString(self.OCETATBIO_DEFAULT, self.tr("ocEtatBio – défaut"), defaultValue="2"))
        self.addParameter(QgsProcessingParameterString(self.NATOBJGEO_DEFAULT, self.tr("natObjGeo – défaut"), defaultValue="In"))
        self.addParameter(QgsProcessingParameterString(self.STATOBS_DEFAULT, self.tr("statObs – défaut"), defaultValue="Pr"))
        self.addParameter(QgsProcessingParameterString(self.STATSOURCE_DEFAULT, self.tr("statSource – défaut"), defaultValue="Te"))
        self.addParameter(QgsProcessingParameterString(self.TYPINFGEO_DEFAULT, self.tr("typInfGeo – défaut"), defaultValue="2"))

        self.addParameter(QgsProcessingParameterString(
            "ENCODING",
            self.tr("Encodage pour lecture dans QGIS"),
            defaultValue="UTF-8"
        ))

        # Ajout de la sortie dans le projet, on choisit le format par l'extension (.csv ou .xlsx)
        self.addParameter(QgsProcessingParameterBoolean(self.ADD_TO_PROJECT,
                                                        self.tr("Ouvrir le fichier en sortie après l'exécution de l'algorithme"), defaultValue=True))
        
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT,
                self.tr("Fichier de sortie (.csv ou .xlsx)"),
                fileFilter="CSV (*.csv);;Excel (*.xlsx)"
            )
        )

    # -------------------- Exécution ------------------------
    def processAlgorithm(self, parameters, context, feedback):
        # Entrée : couche (ou fichier via le bouton parcourir)
        layer_obj = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        if not layer_obj or not layer_obj.isValid():
            raise QgsProcessingException(self.tr("La couche/fichier d'entrée n'est pas valide."))
        
        output_path = self.parameterAsFileOutput(parameters, self.OUTPUT, context)
        model_csv_path = self.parameterAsFile(parameters, self.MODEL_CSV, context)
        taxref_csv_path = self.parameterAsFile(parameters, self.TAXREF_CSV, context)
        add_to_project = self.parameterAsBoolean(parameters, self.ADD_TO_PROJECT, context)
        include_time = self.parameterAsBoolean(parameters, self.INCLUDE_TIME, context)
        drop_zero_autre  = self.parameterAsBoolean(parameters, self.DROP_ZERO_AUTRE, context)
        dup_min_to_max = self.parameterAsBoolean(parameters, self.EFFECTIF_DUP_MIN_TO_MAX, context)

        # Paramètres champs
        encoding_for_qgis = self.parameterAsString(parameters, self.ENCODING, context) or "UTF-8"
        species_field  = self.parameterAsString(parameters, self.SPECIES_FIELD, context)
        date_field     = self.parameterAsString(parameters, self.DATE_FIELD, context)
        eff_field      = self.parameterAsString(parameters, self.EFFECTIF_FIELD, context)
        ocstade_field  = self.parameterAsString(parameters, self.OCSTADE_FIELD, context)
        ocsex_field    = self.parameterAsString(parameters, self.OCSEX_FIELD, context)
        comment1_field = self.parameterAsString(parameters, self.COMMENT1_FIELD, context)
        comment2_field = self.parameterAsString(parameters, self.COMMENT2_FIELD, context)
        permid_field   = self.parameterAsString(parameters, self.PERMID_FIELD, context)
        observer_def   = self.parameterAsString(parameters, self.OBSERVER_DEFAULT, context)
        precisgeo_def  = int(self.parameterAsInt(parameters, self.PRECISGEO_DEFAULT, context))
        objdenbr_def   = self.parameterAsString(parameters, self.OBJDENBR_DEFAULT, context)
        typdenbr_def   = self.parameterAsString(parameters, self.TYPDENBR_DEFAULT, context)
        ocetatbio_def  = self.parameterAsString(parameters, self.OCETATBIO_DEFAULT, context)
        natobjgeo_def  = self.parameterAsString(parameters, self.NATOBJGEO_DEFAULT, context)
        statobs_def    = self.parameterAsString(parameters, self.STATOBS_DEFAULT, context)
        statsource_def = self.parameterAsString(parameters, self.STATSOURCE_DEFAULT, context)
        typinfgeo_def  = self.parameterAsString(parameters, self.TYPINFGEO_DEFAULT, context)


        simplify_tol = float(self.parameterAsDouble(parameters, self.SIMPLIFY_TOL, context))

        # Reprojection -> EPSG:2154
        layer = self.reproject_to_2154(layer_obj, context, feedback)

        if not layer.isEditable():
            layer.startEditing()

        
        # ---------------------------------------------------------
        # Gestion du champ permId (création si absent)
        # ---------------------------------------------------------

        permid_field = permid_field or "permId"
        field_names = layer.fields().names()

        if permid_field not in field_names:
            feedback.pushInfo(f"Création du champ '{permid_field}' (UUID permanent).")
            layer.dataProvider().addAttributes([QgsField(permid_field, QVariant.String)])
            layer.updateFields()
            field_names = layer.fields().names()  # rafraîchir


        taxref_lookup = load_taxref_lookup(taxref_csv_path, feedback)
        headers, second_row = read_model_csv_template(model_csv_path, feedback)

        feedback.pushInfo(f"Lecture du fichier : {layer.source()}")
        feedback.pushInfo(f"Nombre d'entités : {layer.featureCount()}")

        processed_rows = []

        field_names = layer.fields().names()

        # Savoir si 'heureDebut' / 'heureFin' existent dans le modèle
        model_has_heure_debut = headers and ("heureDebut" in [h.strip() for h in headers])
        model_has_heure_fin   = headers and ("heureFin"   in [h.strip() for h in headers])
        
        matched = 0
        unmatched_examples = []

        for f in layer.getFeatures():
            species_val = f[species_field] if species_field in field_names else None
            if drop_zero_autre and str(species_val).strip() == "0_autre":
                continue

            # Jointure TAXREF
            cdNom, nomCite = None, None
            if species_val:
                key_orig = normalise(species_val)
                key_match = normalize_for_match(species_val)
                lk = (taxref_lookup.get(key_orig) or taxref_lookup.get(key_match))
                if lk:
                    cdNom = lk.get("cdNom")
                    nomCite = lk.get("nomCite")
            if cdNom:
                matched += 1
            else:
                if len(unmatched_examples) < 10:
                    unmatched_examples.append(str(species_val))

            if not nomCite:
                nomCite = species_val or ""

            # Dates + heure
            date_src = f[date_field] if date_field in field_names else None
            dd, hh = parse_date_time(date_src)
            df, hf = dd, hh  # dateFin/heureFin = identiques au début (cf.tuto)


            # Effectif
            eff_val = f[eff_field] if eff_field in field_names else None
            min_eff, max_eff = parse_effectif(eff_val)
            if min_eff is None and max_eff is None:
                feedback.pushWarning(f"Effectif non interprétable pour l'entité {f.id()}: '{eff_val}'")

            # UX : si seule borne min connue (>n), dupliquer min->max si param activé
            if min_eff is not None and max_eff is None and dup_min_to_max:
                max_eff = min_eff

            # ocStade / ocSex
            ocStade_val = f[ocstade_field] if ocstade_field in field_names else None
            ocStade = OCSTADE_MAP.get(normalise(ocStade_val), "") if ocStade_val else ""
            ocSex = "" # on laisse vide par défaut pour éviter un code erroné
            
            # Gestion des commentaires
            comment_parts = []
            if comment1_field in field_names:
                v1 = f[comment1_field]
                if v1: comment_parts.append(str(v1))
            if comment2_field in field_names:
                v2 = f[comment2_field]
                if v2: comment_parts.append(str(v2))
            comment = " | ".join(comment_parts)

            # PermID
            permId_updates = {}  # {fid: permId}

            # Lire la valeur brute
            raw_val = f[permid_field] if permid_field in field_names else None

            # Si NULL QGIS ou vide → générer un UUID
            if is_qgis_null(raw_val):
                permId = generate_perm_id()
                permId_updates[f.id()] = permId
            else:
                permId = str(raw_val).strip()

            # Géométrie WKT
            geom = f.geometry()
            wkb = layer.wkbType()
            is_point = QgsWkbTypes.geometryType(wkb) == QgsWkbTypes.PointGeometry

            if geom and not geom.isNull() and not is_point and simplify_tol > 0:
                try:
                    wkt = geom.simplify(simplify_tol).asWkt(3)
                except Exception:
                    wkt = geom.asWkt(3)
            else:
                wkt = geom.asWkt() if geom and not geom.isNull() else ""

            # 🔧 NORMALISATION WKT (Polygon -> POLYGON, etc.)
            wkt = normalize_wkt_type(wkt)

            row = {
                "cdNom": cdNom or "",
                "nomCite": nomCite or (species_val or ""),
                "dateDebut": dd,
                "dateFin": df,
                "denbrMin": min_eff,
                "denbrMax": max_eff,
                "objDenbr": objdenbr_def,
                "typDenbr": typdenbr_def,
                "ocEtatBio": ocetatbio_def,
                "ocSex": ocSex,
                "ocStade": ocStade,
                "comment": comment,
                "statObs": statobs_def,
                "statSource": statsource_def,
                "geometrie": wkt,
                "natObjGeo": natobjgeo_def,
                "precisGeo": precisgeo_def,
                "permId": permId,
                "observer": observer_def,
                "typInfGeo": typinfgeo_def
            }
            
            # Ajouter les heures si le modèle les attend OU si include_time=True (et heure présente)
            if model_has_heure_debut or (include_time and hh):
                row["heureDebut"] = hh
            if model_has_heure_fin or (include_time and hh):
                row["heureFin"]   = hh

            processed_rows.append(row)
        
        # Appliquer les changements de permId dans la couche
        if permId_updates:
            idx = layer.fields().indexFromName(permid_field)
            for fid, permId in permId_updates.items():
                layer.changeAttributeValue(fid, idx, permId)
    
        # Mettre à jour la couche en mémoire avec les permId générés:
        if layer.isEditable():
            layer.commitChanges()
            
        feedback.pushInfo(f"Jointure TAXREF : {matched} correspondances / {layer.featureCount()} entités.")
        if unmatched_examples:
            feedback.pushWarning("Exemples non joints (10 max) : " + ", ".join(unmatched_examples))

        # En-têtes : modèle CSV (si fourni) ou jeu minimal (avec heures si demandé)
        if headers:
            final_headers = headers
        else:
            final_headers = [
                "cdNom", "nomCite",
                "dateDebut", "dateFin",
                "denbrMin", "denbrMax",
                "objDenbr", "typDenbr",
                "ocEtatBio", "ocSex", "ocStade",
                "comment",
                "statObs", "statSource",
                "geometrie", "natObjGeo", "precisGeo",
                "permId", "observer", "typInfGeo"
            ]
            # insertion des heures après les dates si demandé
            if include_time:
                if "heureDebut" not in final_headers:
                    final_headers.insert(final_headers.index("dateDebut")+1, "heureDebut")
                if "heureFin" not in final_headers:
                    final_headers.insert(final_headers.index("dateFin")+1, "heureFin")

        # Choix du format en fonction de l'extension
        ext = os.path.splitext(output_path)[1].lower()

        # si le modèle contient heureDebut/heureFin, les insérer à la bonne place (déjà dans headers)
        if ext == ".csv":
            self.write_csv(output_path, processed_rows, final_headers, second_row, feedback)
            if add_to_project:
                file_url = QUrl.fromLocalFile(output_path).toString() #Cherche le chemin en local
                uri = f"{file_url}?encoding={encoding_for_qgis}&delimiter=;&quote=\""
                # charger CSV comme table via OGR
                layer_out = QgsVectorLayer(uri, os.path.basename(output_path), "delimitedtext")
                if layer_out and layer_out.isValid():
                    QgsProject.instance().addMapLayer(layer_out)
        else:
            self.write_excel(output_path, processed_rows, final_headers, feedback)
            if add_to_project:
                # charger la feuille Excel (DEPOBIO_V2) via OGR
                uri = f"{output_path}|layername=DEPOBIO_V2"
                layer_out = QgsVectorLayer(uri, os.path.basename(output_path), "ogr")
                if layer_out and layer_out.isValid():
                    QgsProject.instance().addMapLayer(layer_out)

        feedback.pushInfo(self.tr("Traitement terminé."))
        return {self.OUTPUT: output_path}


    # ------------------------------------------------------------------------------------
    # --- Écrit fichier CSV
    # ------------------------------------------------------------------------------------
    def write_csv(self, output_path, processed_rows, headers, second_row, feedback):
        folder = os.path.dirname(output_path)
        if folder: os.makedirs(folder, exist_ok=True)
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            # ligne 1 : champs
            writer.writerow(headers)
            # ligne 2 : astérisques si modèle fourni
            if second_row: writer.writerow(second_row)
            for row in processed_rows:
                out = []
                for h in headers:
                    val = row.get(h, "")
                    out.append("" if val is None else str(val))
                writer.writerow(out)
        feedback.pushInfo(f"CSV écrit : {output_path}")
    
    # ------------------------------------------------------------------------------------
    # --- Écrit fichier Excel
    # ------------------------------------------------------------------------------------
    def write_excel(self, output_path, processed_rows, headers, feedback):
        folder = os.path.dirname(output_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        workbook = xlsxwriter.Workbook(output_path)
        ws = workbook.add_worksheet("DEPOBIO_V2")
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#D9D9D9"})
        date_fmt = workbook.add_format({"num_format": "dd/mm/yyyy"})
        time_fmt = workbook.add_format({"num_format": "hh:mm:ss"})
        for col, h in enumerate(headers):
            ws.write(0, col, h, header_fmt)
        for r, row in enumerate(processed_rows, start=1):
            for c, h in enumerate(headers):
                val = row.get(h, "")
                if h in ("dateDebut", "dateFin") and isinstance(val, str) and val:
                    try:
                        dd = datetime.datetime.strptime(val, "%d/%m/%Y")
                        ws.write_datetime(r, c, dd, date_fmt)
                    except Exception:
                        ws.write(r, c, val)
                elif h in ("heureDebut", "heureFin") and isinstance(val, str) and val:
                    try:
                        t = datetime.datetime.strptime(val, "%H:%M:%S")
                        fake = datetime.datetime(1900, 1, 1, t.hour, t.minute, t.second)
                        ws.write_datetime(r, c, fake, time_fmt)
                    except Exception:
                        ws.write(r, c, val)
                else:
                    ws.write(r, c, val)
        workbook.close()
        feedback.pushInfo(f"Excel écrit : {output_path}")

    # ------------------------------------------------------------------------------------
    # ---Métadonnées
    # ------------------------------------------------------------------------------------

    def name(self):
        return "traitement_donnees_naturaliste_vers_sinp"

    def displayName(self):
        return self.tr("SINP - Conversion fichier naturaliste SIG vers SINP")

    def group(self):
        return self.tr("SINP")

    def groupId(self):
        return "sinp"

    def shortHelpString(self):
        return self.tr(
            "<h3>SINP – Conversion d’une couche SIG naturaliste vers le format DEPOBIO</h3>"

            "<p>"
            "Ce géotraitement permet de convertir une couche SIG (shapefile, GeoPackage, etc.) "
            "contenant des observations naturalistes (faune, avifaune, chiroptères…) "
            "en un fichier conforme au format <b>DEPOBIO V2</b> attendu par la "
            "<b>SINP (Système d’Information de l’Inventaire du Patrimoine Naturel)</b>."
            "</p>"

            "<h4>Principe général</h4>"
            "<ul>"
            "<li>Lecture d’une couche vectorielle (points, lignes ou polygones)</li>"
            "<li>Jointure avec un fichier <b>TAXREF</b> pour récupérer le <code>cdNom</code></li>"
            "<li>Normalisation des dates, heures et effectifs</li>"
            "<li>Export au format <b>CSV</b> ou <b>Excel (.xlsx)</b></li>"
            "</ul>"

            "<h4>Données en entrée</h4>"
            "<ul>"
            "<li><b>Couche SIG</b> : couche vectorielle contenant les observations</li>"
            "<li><b>CSV TAXREF</b> : fichier officiel TAXREF pour la correspondance taxonomique</li>"
            "<li><b>Modèle CSV DEPOBIO (optionnel)</b> : permet de garantir l’ordre et la complétude des colonnes</li>"
            "</ul>"

            "<h4>Champs attendus dans la couche</h4>"
            "<p>Les champs suivants doivent être sélectionnés dans la couche d’entrée :</p>"
            "<ul>"
            "<li><b>Espèce</b> (nom vernaculaire ou scientifique)</li>"
            "<li><b>Date / heure</b> de l’observation</li>"
            "<li><b>Effectif</b> (valeur simple, intervalle, comparateur, texte)</li>"
            "<li><b>Stade biologique</b> (ocStade)</li>"
            "</ul>"
            "<p>Les champs <b>sexe</b>, <b>commentaires</b> et <b>identifiant permanent (permId)</b> sont optionnels.</p>"

            "<h4>Gestion des géométries</h4>"
            "<ul>"
            "<li>Les géométries sont exportées au format <b>WKT</b></li>"
            "<li>Les lignes et polygones peuvent être <b>simplifiés</b> selon une tolérance en mètres</li>"
            "<li>Les coordonnées sont exprimées en Lambert-93 (EPSG:2154)</li>"
            "</ul>"

            "<h4>Effectifs</h4>"
            "<p>"
            "Le champ effectif accepte des valeurs variées : "
            "<code>3</code>, <code>2-4</code>, <code>>5</code>, <code><10</code>, "
            "<code>≈3</code>, etc. "
            "Les valeurs sont converties automatiquement en <code>denbrMin</code> et <code>denbrMax</code>."
            "</p>"

            "<h4>Paramètres par défaut</h4>"
            "<p>"
            "Plusieurs champs SINP peuvent être renseignés via des valeurs par défaut "
            "(statObs, statSource, typDenbr, etc.). "
            "Ces valeurs seront appliquées à toutes les observations si elles sont définies."
            "</p>"

            "<h4>Sortie</h4>"
            "<ul>"
            "<li>Fichier <b>.csv</b> compatible avec l’import officiel SINP</li>"
            "<li>Ou fichier <b>.xlsx</b> (feuille <code>DEPOBIO_V2</code>)</li>"
            "</ul>"

            "<h4>Remarques importantes</h4>"
            "<ul>"
            "<li>Les identifiants permanents (<code>permId</code>) manquants sont générés automatiquement</li>"
            "<li>Les observations non jointes au TAXREF sont conservées mais signalées</li>"
            "</ul>"
        )

    def createInstance(self):
        return MappingNaturalistDataToSinpAlgorithm()

    def tr(self, s):
        return QCoreApplication.translate("Processing", s)