# -*- coding: utf-8 -*-
from qgis.core import (
    QgsProviderRegistry,
    QgsProcessingException
)

from .sql import load_sql
import time


def run_full_processing(connection_name, territoires, feedback):

    # ------------------------------------------------------------
    # Connexion PostgreSQL
    # ------------------------------------------------------------
    provider = QgsProviderRegistry.instance().providerMetadata("postgres")
    conn = provider.createConnection(connection_name)

    if conn is None:
        raise QgsProcessingException(f"Connexion PostgreSQL introuvable : {connection_name}")

    feedback.pushInfo("Connexion PostgreSQL OK (Provider QGIS).")
    feedback.setProgress(0)

    # ------------------------------------------------------------
    # Liste des étapes SQL
    # ------------------------------------------------------------
    steps = [
        ("01_setup.sql",        "Nettoyage / création des tables temporaires"),
        ("02_insert.sql",       f"Insertion des {len(territoires)} territoires"),
        ("03_dt.sql",           "Traitement des flux DT"),
        ("04_de.sql",           "Traitement des flux DE"),
        ("05_dt_detail.sql",    "Extraction DT détaillée"),
        ("06_dt_synthese.sql",  "Extraction DT synthèse"),
        ("07_de_detail.sql",    "Extraction DE détaillée"),
        ("08_de_synthese.sql",  "Extraction DE synthèse")
    ]

    total_steps = len(steps)
    current_step = 0

    # ------------------------------------------------------------
    # 1) SETUP (01_setup.sql)
    # ------------------------------------------------------------
    filename, label = steps[current_step]
    feedback.pushInfo(f"[{current_step+1}/{total_steps}] {label}… ({filename})")
    conn.executeSql(load_sql(filename))
    current_step += 1
    feedback.setProgress(int(current_step / total_steps * 100))

    # ------------------------------------------------------------
    # 2) INSERT TERRITOIRES (02_insert.sql)
    # ------------------------------------------------------------
    filename, label = steps[current_step]
    feedback.pushInfo(f"[{current_step+1}/{total_steps}] {label}… ({filename})")

    insert_tpl = load_sql(filename)

    for terr in territoires:
        q = (
            insert_tpl
            .replace("{{INSEE}}", terr["insee"])
            .replace("{{NOM}}", terr["nom"].replace("'", "''"))
        )
        conn.executeSql(q)

    current_step += 1
    feedback.setProgress(int(current_step / total_steps * 100))

    # ------------------------------------------------------------
    # 3 et 4) Exécution des gros scripts SQL (03_dt + 04_de)
    # ------------------------------------------------------------
    for step_index in [2, 3]:
        filename, label = steps[step_index]
        feedback.pushInfo(f"[{step_index+1}/{total_steps}] {label}… ({filename})")
        conn.executeSql(load_sql(filename))

        current_step += 1
        feedback.setProgress(int(current_step / total_steps * 100))

    # ------------------------------------------------------------
    # 5) EXTRACT – exécution ET récupération des données
    # ------------------------------------------------------------
    results = {}

    for step_index in [4, 5, 6, 7]:
        filename, label = steps[step_index]

        feedback.pushInfo(f"[{step_index+1}/{total_steps}] {label}… ({filename})")

        sql = load_sql(filename)
        res = conn.executeSql(sql)

        results[filename] = res

        current_step += 1
        feedback.setProgress(int(current_step / total_steps * 100))

    feedback.pushInfo("Toutes les requêtes SQL ont été exécutées.")

    # ------------------------------------------------------------
    # Construction du retour propre
    # ------------------------------------------------------------
    queries_dt = {
        "detail":   results["05_dt_detail.sql"],
        "synthese": results["06_dt_synthese.sql"]
    }

    queries_de = {
        "detail":   results["07_de_detail.sql"],
        "synthese": results["08_de_synthese.sql"]
    }

    feedback.pushInfo("Traitement SQL terminé.")
    feedback.setProgress(100)

    return queries_dt, queries_de
