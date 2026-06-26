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
from .flux_insee.modelisation_flux import ModelisationFluxAlgorithm
from .teom.teom import CalculTEOMAlgorithm
from .metaddigo.metaddigo import MetaddigoExportMetadataAlgorithm

from .sinp.sinp import MappingNaturalistDataToSinpAlgorithm
from .formulaire_odk.formulaire_odk import OdkFormToQgis
# NB : les géotraitements LiDAR ont été extraits dans le plugin distinct « LidarDG ».
from .Epes_Data_Extractor.epes_data_extractor import AutoDataPrepAlgorithm
from .compression_images.compression_images import CompressionImagesAlgorithm
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
        self.addAlgorithm(CalculTEOMAlgorithm())
        self.addAlgorithm(FluxInseeAlgorithm())
        # Enregistré pour apparaître dans la boîte à outils : son formulaire
        # standard est remplacé par la fenêtre custom (createCustomParametersWidget).
        self.addAlgorithm(ModelisationFluxAlgorithm())
        self.addAlgorithm(MetaddigoExportMetadataAlgorithm())
        self.addAlgorithm(MappingNaturalistDataToSinpAlgorithm())
        #self.addAlgorithm(OdkFormToQgis())
        # Les géotraitements LiDAR ont été déplacés dans le plugin distinct « LidarDG ».
        self.addAlgorithm(AutoDataPrepAlgorithm())
        self.addAlgorithm(CompressionImagesAlgorithm())
        self._check_epes_credentials()

    def _check_epes_credentials(self):
        try:
            from .Epes_Data_Extractor.connectors import check_required_credentials
            missing = check_required_credentials()
            for msg in missing:
                QgsMessageLog.logMessage(msg, 'PluginsInddigoDG', Qgis.Warning)
            if missing:
                try:
                    from qgis.utils import iface
                    if iface:
                        iface.messageBar().pushMessage(
                            'PluginsInddigoDG – EPES',
                            'Variables QGIS manquantes pour certaines sources (voir Journal des messages)',
                            level=Qgis.Warning,
                            duration=15
                        )
                except Exception:
                    pass
        except Exception as e:
            QgsMessageLog.logMessage(f'Erreur vérification credentials EPES : {e}', 'PluginsInddigoDG', Qgis.Warning)


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
