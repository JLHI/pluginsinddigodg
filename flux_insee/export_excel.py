# -*- coding: utf-8 -*-
"""
Export Excel du plugin flux_insee.
Utilise xlsxwriter.
"""
import xlsxwriter
from PyQt5.QtCore import QVariant


def to_python(value):
    """Convertit QVariant et tout autre type Qt en type Python natif utilisable par xlsxwriter."""

    # 1. Si c'est déjà un type Python standard → OK
    if isinstance(value, (int, float, str)):
        return value
    
    # 2. Si None → chaîne vide (Excel n'aime pas None)
    if value is None:
        return ""

    # 3. Si QVariant
    if isinstance(value, QVariant):
        py = value
        # Conversion QVariant → Python
        if value.type() == QVariant.Int:
            return int(value)
        if value.type() == QVariant.Double:
            return float(value)
        if value.type() == QVariant.String:
            return str(value)
        if value.isNull():
            return ""
        # fallback
        return str(value)

    # 4. Fallback final : tout convertir en texte
    return str(value)


def _write_sheet(workbook, sheet_name, headings, data):
    """Crée une feuille, écrit les en-têtes et les données."""

    worksheet = workbook.add_worksheet(sheet_name)

    # formats
    header_fmt = workbook.add_format({
        "bold": True,
        "bg_color": "#B6D4B4",
        "border": 1
    })

    cell_fmt = workbook.add_format({
        "border": 1
    })

    # Écriture des en-têtes
    for col, head in enumerate(headings):
        worksheet.write(0, col, head, header_fmt)

    # Écriture des données
    for row_idx, row in enumerate(data, start=1):
        for col_idx, value in enumerate(row):

            #conversion QVariant → Python
            val = to_python(value)

            worksheet.write(row_idx, col_idx, val, cell_fmt)


    # Ajustement automatique des colonnes
    for col in range(len(headings)):
        worksheet.set_column(col, col, 18)


# ======================================================================
# EXPORT DETAIL
# ======================================================================
def export_detail_excel(data_dt, data_de, output_path):
    workbook = xlsxwriter.Workbook(output_path)

    # DT
    headings_dt = (
        "Id", "Commune d'origine", "Nom commune origine",
        "Commune de destination", "Nom commune destination",
        "Age", "Mode de transport", "CSP", "Flux", "Type flux"
    )
    _write_sheet(workbook, "DT", headings_dt, data_dt)

    # DE
    headings_de = (
        "Id", "Commune d'origine", "Nom commune origine",
        "Commune de destination", "Nom commune destination",
        "Age", "CSP", "Flux", "Type flux"
    )
    _write_sheet(workbook, "DE", headings_de, data_de)

    workbook.close()


# ======================================================================
# EXPORT SYNTHÈSE
# ======================================================================
def export_synthese_excel(data_dt, data_de, output_path):
    workbook = xlsxwriter.Workbook(output_path)

    # DT synthèse
    headings_dt = (
        "Id", "Commune d'origine", "Nom commune origine",
        "Commune de destination", "Nom commune destination",
        "Flux", "Type flux"
    )
    _write_sheet(workbook, "DT", headings_dt, data_dt)

    # DE synthèse
    headings_de = (
        "Id", "Commune d'origine", "Nom commune origine",
        "Commune de destination", "Nom commune destination",
        "Flux", "Type flux"
    )
    _write_sheet(workbook, "DE", headings_de, data_de)

    workbook.close()
