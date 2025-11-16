# -*- coding: utf-8 -*-
"""
Module pour charger les fichiers SQL depuis le dossier /sql.
Permet également d'injecter des variables dans les requêtes SQL.
"""

import os


def load_sql(filename, variables=None):
    """
    Charge un fichier SQL du dossier /sql.
    variables = dict optionnel pour remplacer des tags dans le SQL.

    Exemple dans le SQL :
        SELECT * FROM table WHERE id = {{ID}}

    Appel :
        load_sql("ma_requete.sql", {"ID": 123})

    """
    base_path = os.path.dirname(__file__)
    sql_path = os.path.join(base_path, "sql", filename)

    if not os.path.isfile(sql_path):
        raise FileNotFoundError(f"Fichier SQL introuvable : {sql_path}")

    with open(sql_path, "r", encoding="utf-8") as f:
        content = f.read()

    # remplacement de variables éventuelles
    if variables:
        for key, value in variables.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))

    return content
