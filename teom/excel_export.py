# -*- coding: utf-8 -*-
"""
Export Excel — version stable avec XlsxWriter
Reproduit EXACTEMENT les couleurs et le rendu de l'ancienne version openpyxl.
"""

import os
import shutil
import tempfile
from ..lib import xlsxwriter
from qgis.core import QgsProcessingException
from qgis.PyQt.QtCore import QVariant


def clean_value(v):
    """Convertit proprement tous les types QGIS → types Python compatibles Excel."""

    # 1) QVariant (QGIS >= 3.16)
    if isinstance(v, QVariant):
        v = v if v != QVariant() else None

    # 2) None → ""
    if v is None:
        return ""

    # 3) bool, int, float → OK
    if isinstance(v, (bool, int, float)):
        return v

    # 4) tuples / listes → conversion récursive
    if isinstance(v, (list, tuple)):
        return [clean_value(x) for x in v]

    # 5) bytes → str
    if isinstance(v, (bytes, bytearray, memoryview)):
        try:
            return v.decode("utf-8", errors="ignore")
        except Exception:
            return str(v)

    # 6) géométries QGIS → WKT (ou texte vide)
    if hasattr(v, "asWkt"):
        try:
            return v.asWkt()
        except:
            return ""

    # 7) Tout le reste → string safe
    return str(v)


def _safe(v):
    return clean_value(v)


def export_to_excel(rows_base, headings_base, rows_locaux, headings_locaux, filepath, feedback):

    feedback.pushInfo("Début de l'export Excel…")

    # ------------------------------------------
    # Fichier temporaire
    # ------------------------------------------
    tmpfile = os.path.join(tempfile.gettempdir(), "teom_export_tmp.xlsx")

    try:
        wb = xlsxwriter.Workbook(tmpfile, {'constant_memory': True})
    except Exception as e:
        raise QgsProcessingException(f"Impossible de créer le fichier Excel : {e}")

    # ============================================================
    # FORMATS
    # ============================================================
    bold = wb.add_format({'bold': True})

    base_header = wb.add_format({
        "bold": True,
        "bg_color": "#B6D4B4"
    })

    fmt_A9A6A1 = wb.add_format({"bold": True, "bg_color": "#A9A6A1"})
    fmt_BF8F00 = wb.add_format({"bold": True, "bg_color": "#BF8F00"})
    fmt_70368A = wb.add_format({"bold": True, "bg_color": "#70368A"})
    fmt_B5B846 = wb.add_format({"bold": True, "bg_color": "#B5B846"})
    fmt_4D9FD7 = wb.add_format({"bold": True, "bg_color": "#4D9FD7"})

    block_formats = {
        range(1, 5): fmt_A9A6A1,      # 1–4  (4 colonnes)
        range(5, 8): fmt_BF8F00,      # 5–7  (3 colonnes)
        range(8, 11): fmt_70368A,     # 8–10 (3 colonnes)
        range(11, 14): fmt_B5B846,    # 11–13 (3 colonnes)
        range(14, 17): fmt_4D9FD7,    # 14–16 (3 colonnes)
    }

    # ============================================================
    # FEUILLE BASE
    # ============================================================
    sheet = wb.add_worksheet("Base")
    feedback.pushInfo(f"Feuille Base : {len(rows_base)} lignes.")

    for col, title in enumerate(headings_base):
        sheet.write(0, col, title, base_header)

    for row_idx, row in enumerate(rows_base, start=1):
        for col_idx, value in enumerate(row):
            sheet.write(row_idx, col_idx, _safe(value))

        if row_idx % 1000 == 0:
            feedback.pushInfo(f"  → {row_idx} lignes écrites")

    # ============================================================
    # FEUILLE TYPE LOCAUX
    # ============================================================
    sheet2 = wb.add_worksheet("Type de locaux")
    feedback.pushInfo(f"Feuille Locaux : {len(rows_locaux)} lignes.")

    for col, title in enumerate(headings_locaux, start=1):
        fmt = bold
        for rng, style in block_formats.items():
            if col in rng:
                fmt = style
                break
        sheet2.write(0, col - 1, title, fmt)

    for row_idx, row in enumerate(rows_locaux, start=1):
        for col_idx, value in enumerate(row):
            sheet2.write(row_idx, col_idx, _safe(value))

    # ============================================================
    # SAUVEGARDE
    # ============================================================
    try:
        wb.close()
    except Exception as e:
        raise QgsProcessingException(f"Erreur Excel : {e}")

    try:
        shutil.copy(tmpfile, filepath)
    except Exception as e:
        raise QgsProcessingException(f"Impossible d'écrire le fichier final : {e}")

    feedback.pushInfo("Export terminé.")