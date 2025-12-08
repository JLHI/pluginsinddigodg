# -*- coding: utf-8 -*-

"""
PluginsInddigoDG – Provider Processing
"""

__author__ = 'JLHI'
__date__ = '2024-11-22'
__revision__ = '$Format:%H$'

from qgis.core import QgsProcessingProvider, QgsMessageLog, Qgis

# Import des autres algorithmes
from .Arbre_de_rabattement.Arbre_de_rabattement_algorithm import ArbreDeRabattementAlgorithm
from .gtfs_stops_to_routes_ign.gtfs_stops_to_route_ign import GtfsRouteIgn
from .Itineraire_ign.ItineraireParLaRoute_algorithm import ItineraireParLaRouteAlgorithm
from .isochrone_ign.isochrone_ign import IsochroneIgnAlgorithm
from .flux_insee.flux_insee import FluxInseeAlgorithm
from .teom.teom import CalculTEOMAlgorithm


class PluginsInddigoDGProvider(QgsProcessingProvider):

    # --------------------------
    #  INITIALISATION
    # --------------------------
    def __init__(self):
        super().__init__()

    def unload(self):
        pass

    # --------------------------
    #  GROUPES DU PROVIDER
    # --------------------------
    def groups(self):
        """
        Déclare les groupes visibles dans la boîte Processing.
        IMPORTANT : doit inclure TOUS les groupes utilisés par les algorithmes.
        """
        return ["Metaddigo"]

    def groupId(self, name):
        """
        Retourne l'ID interne du groupe.
        """
        if name == "Metaddigo":
            return "metaddigo"
        return ""

    # --------------------------
    #  ALGORITHMES DU PROVIDER
    # --------------------------
    def loadAlgorithms(self):

        # Ajout des autres algorithmes du plugin
        self.addAlgorithm(ArbreDeRabattementAlgorithm())
        self.addAlgorithm(GtfsRouteIgn())
        self.addAlgorithm(ItineraireParLaRouteAlgorithm())
        self.addAlgorithm(IsochroneIgnAlgorithm())
        self.addAlgorithm(CalculTEOMAlgorithm())
        self.addAlgorithm(FluxInseeAlgorithm())

        # ---- Ajout de Metaddigo ----
        try:
            from .metaddigo.metaddigo import MetaddigoExportMetadataAlgorithm
            self.addAlgorithm(MetaddigoExportMetadataAlgorithm())
            QgsMessageLog.logMessage(
                "MetaddigoExportMetadataAlgorithm chargé avec succès.",
                'PluginsInddigoDG', Qgis.Info
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Erreur lors du chargement de Metaddigo : {e}",
                'PluginsInddigoDG', Qgis.Warning
            )

    # --------------------------
    #  INFORMATIONS DU PROVIDER
    # --------------------------
    def id(self):
        return 'PluginsInddigoDG'

    def name(self):
        return self.tr('PluginsInddigoDG')

    def icon(self):
        return super().icon()

    def longName(self):
        return self.name()
