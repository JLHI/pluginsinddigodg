# -*- coding: utf-8 -*-
"""
Module utilitaire :
 - chargement + découpe fichiers SQL
 - exécution séquentielle avec logs détaillés
 - intégration du paramètre {schema}
"""

from qgis.core import QgsProcessingException
# ------------------------------------------------------------
# LECTURE + DÉCOUPE DES FICHIERS SQL
# ------------------------------------------------------------
def load_sql_file(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    return [q.strip() for q in content.split(";") if q.strip()]
# ------------------------------------------------------------
# EXECUTION DES REQUETES SQL
# ------------------------------------------------------------
def execute_sql_list(conn, sql_list, schema, feedback, verbose=True):
    """
    Exécute une liste SQL et retourne :
        results_base  = données SELECT * FROM request7
        results_locaux = données SELECT * FROM type_locaux
    """

    total = len(sql_list)
    feedback.pushInfo(f"{total} requêtes SQL à exécuter…")

    results_base = None
    results_locaux = None

    for i, raw_sql in enumerate(sql_list, start=1):

        sql = raw_sql.replace("{schema}", schema).strip()

        feedback.setProgress(int(i / total * 100))

        if verbose:
            feedback.pushInfo(f"[SQL {i}/{total}]")
            feedback.pushInfo(sql)

        try:
            # Cas particulier : SELECT final
            if "select code_insee, epci, commune," in sql.lower():
                results_base = conn.executeSql(sql)
                feedback.pushInfo("→ Résultat request7 chargé en mémoire.")
                continue

            if "select com, nb_total, base_total, mt_total" in sql.lower():
                results_locaux = conn.executeSql(sql)
                feedback.pushInfo("→ Résultat type_locaux chargé en mémoire.")
                continue

            # Requête normale
            conn.executeSql(sql)
            feedback.pushInfo("Exécution OK.")

        except Exception as e:
            feedback.reportError(sql)
            raise QgsProcessingException(
                f"Erreur SQL dans la requête {i}/{total} : {e}"
            )

    feedback.pushInfo("Toutes les requêtes SQL ont été exécutées avec succès.")

    return results_base, results_locaux

