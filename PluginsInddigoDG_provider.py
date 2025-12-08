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
from .metaddigo.metaddigo import MetaddigoExportMetadataAlgorithm


class PluginsInddigoDGProvider(QgsProcessingProvider):

    # --------------------------
    #  INITIALISATION
    # --------------------------
    def __init__(self):
        super().__init__()

    def unload(self):
        pass

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
        self.addAlgorithm(MetaddigoExportMetadataAlgorithm())


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
