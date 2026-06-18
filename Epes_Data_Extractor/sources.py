# -*- coding: utf-8 -*-
DEFAULT_CONFIG = {
    "groups": {

        # ------------------------------------------------------------------ #
        #  COMMUNS                                                             #
        # ------------------------------------------------------------------ #
        "Communs": {
            "sources": [
                # -- IGN / PostGIS schema : ign --
                {
                    "id": "ign_chef_lieux",
                    "name": "Chef-lieux",
                    "type": "postgis",
                    "nomenclature": "ign_chef_lieux",
                    "conn": {
                        "service": "referentiels",
                        "schema": "ign",
                        "table": "admin_express_cheflieu_commune",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Administratif"}
                },
                {
                    "id": "ign_commune",
                    "name": "Communes",
                    "type": "postgis",
                    "nomenclature": "ign_commune",
                    "conn": {
                        "service": "referentiels",
                        "schema": "ign",
                        "table": "adminexpres_commune",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Administratif"}
                },
                {
                    "id": "ign_departement",
                    "name": "Départements",
                    "type": "postgis",
                    "nomenclature": "ign_departement",
                    "conn": {
                        "service": "referentiels",
                        "schema": "ign",
                        "table": "adminexpres_departement",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Administratif"}
                }
            ]
        },

        # ------------------------------------------------------------------ #
        #  PAYSAGE                                                             #
        # ------------------------------------------------------------------ #
        "Paysage": {
            "sources": [

                # -- atlas.patrimoines.culture.fr --
                {
                    "id": "adp_bien_unesco",
                    "name": "Bien Unesco",
                    "type": "wfs",
                    "nomenclature": "adp_bien_unesco",
                    "conn": {
                        "base_url": "http://atlas.patrimoines.culture.fr/cgi-bin/mapserv?MAP=/home/atlas-mapserver/production/var/data/MD_2556/MD_2556.map",
                        "typename": "MD_2556",
                        "version": "1.1.0",
                        "skip_native": True,
                        "skip_geojson": True,
                        "bbox_param": "boundedBy"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },
                {
                    "id": "adp_mh",
                    "name": "Monument historique (MH) – Emprise",
                    "type": "api_adp_dynamic",
                    "nomenclature": "adp_mh",
                    "conn": {
                        "category_filter": [
                            "Monument historique",
                            "Immeuble classé ou inscrit"
                        ]
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },
                {
                    "id": "adp_perimetre_mh",
                    "name": "Périmètre de protection autour des MH",
                    "type": "api_adp_dynamic",
                    "nomenclature": "adp_perimetre_mh",
                    "conn": {
                        "category_filter": [
                            "Périmètre de protection d'un monument historique"
                        ]
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },
                {
                    "id": "adp_site_classe_inscrit",
                    "name": "Site classé et inscrit",
                    "type": "api_adp_dynamic",
                    "nomenclature": "adp_site_classe_inscrit",
                    "conn": {
                        "category_filter": ["Site classé ou inscrit"]
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },
                {
                    "id": "adp_spr",
                    "name": "Site Patrimonial Remarquable (SPR)",
                    "type": "api_adp_dynamic",
                    "nomenclature": "adp_spr",
                    "conn": {
                        "category_filter": [
                            "Site Patrimonial Remarquable",
                            "Sites patrimoniaux remarquables",
                            "Aire de mise en valeur de l'architecture et du patrimoine",
                            "Aires de Mise en Valeur de l'Architecture et du Patrimoine",
                            "Zone de Protection du Patrimoine Architectural, Urbain et Paysager"
                        ]
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },
                {
                    "id": "adp_zppa",
                    "name": "Zone de présomption de prescription archéologique (ZPPA)",
                    "type": "api_adp_dynamic",
                    "nomenclature": "adp_zppa",
                    "conn": {
                        "category_filter": [
                            "Zone de présomption de prescription archéologique"
                        ]
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },

                # -- FFRandonnée / ArcGIS --
                {
                    "id": "ffr_gr",
                    "name": "Tourisme - Grandes Randonnées (GR)",
                    "type": "api_arcgis",
                    "nomenclature": "ffr_gr",
                    "conn": {
                        "url": "https://services5.arcgis.com/c1QgYL9mDxHt7MzO/ArcGIS/rest/services/PRO_ME_ITINERAIRES_MonGR/FeatureServer/0",
                        "where": "Type_Iti=1",
                        "out_sr": 4326,
                        "page_size": 2000
                    },
                    "target": {"folder": "4-DATA VECTEUR/Tourisme"}
                },
                {
                    "id": "ffr_grp",
                    "name": "Tourisme - Grandes Randonnées de Pays (GRP)",
                    "type": "api_arcgis",
                    "nomenclature": "ffr_grp",
                    "conn": {
                        "url": "https://services5.arcgis.com/c1QgYL9mDxHt7MzO/ArcGIS/rest/services/PRO_ME_ITINERAIRES_MonGR/FeatureServer/0",
                        "where": "Type_Iti=2",
                        "out_sr": 4326,
                        "page_size": 2000
                    },
                    "target": {"folder": "4-DATA VECTEUR/Tourisme"}
                },

                # -- DATAtourisme --
                {
                    "id": "dt_tourisme",
                    "name": "Tourisme - Points d'intérêt",
                    "type": "api_datatourisme",
                    "nomenclature": "dt_tourisme",
                    "conn": {
                        "base_url": "https://api.datatourisme.fr/v1/catalog",
                        "api_key_var": "data_tourisme",
                        "layer_geometry": "point"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Tourisme"}
                },

                # -- IGN / data.geopf.fr – BD TOPO (WFS) + WMS raster --
                {
                    "id": "ign_rgealt_5m",
                    "name": "Altimétrie MNT 5m (RGE Alti)",
                    "type": "raster_ign",
                    "nomenclature": "ign_rgealti_5m",
                    "conn": {
                        "wms_url": "https://data.geopf.fr/wms-r",
                        "layer": "ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES",
                        "resolution": 5
                    },
                    "target": {"folder": "3-DATA RASTER"}
                },
                # {
                #     "id": "ign_pente",
                #     "name": "Pente (degrés)",
                #     "type": "raster_slope",
                #     "nomenclature": "ign_pente",
                #     "conn": {
                #         "dem_nomenclature": "ign_rgealti_5m",
                #         "dem_folder": "3-DATA RASTER",
                #         "dem_wms_url": "https://data.geopf.fr/wms-r",
                #         "dem_layer": "ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES",
                #         "dem_resolution": 5
                #     },
                #     "target": {"folder": "3-DATA RASTER"}
                # },
                {
                    "id": "bdtopo_bati",
                    "name": "Bâti",
                    "type": "wfs",
                    "nomenclature": "bdtopo_bati",
                    "conn": {
                        "base_url": "https://data.geopf.fr/wfs/ows",
                        "typename": "BDTOPO_V3:batiment",
                        "geom_field": "geometrie",
                        "version": "auto"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "bdtopo_route",
                    "name": "Routes",
                    "type": "wfs",
                    "nomenclature": "bdtopo_route",
                    "conn": {
                        "base_url": "https://data.geopf.fr/wfs/ows",
                        "typename": "BDTOPO_V3:troncon_de_route",
                        "geom_field": "geometrie",
                        "version": "auto"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "itineraires_randonnees",
                    "name": "Tourisme - Randonnée pédestre",
                    "type": "wfs",
                    "nomenclature": "itineraires_randonnees",
                    "conn": {
                        "base_url": "https://data.geopf.fr/wfs/ows",
                        "typename": "BDTOPO_V3:itineraire_autre",
                        "geom_field": "geometrie",
                        "version": "auto"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Tourisme"}
                },
                {
                    "id": "bdtopo_vegetation",
                    "name": "Végétation",
                    "type": "wfs",
                    "nomenclature": "bdtopo_vegetation",
                    "conn": {
                        "base_url": "https://data.geopf.fr/wfs/ows",
                        "typename": "BDTOPO_V3:zone_de_vegetation",
                        "geom_field": "geometrie",
                        "version": "auto"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_naturel"}
                },

                # -- PostGIS schema : on3v --
                {
                    "id": "on3v_vv",
                    "name": "Véloroutes Voies Vertes",
                    "type": "postgis",
                    "nomenclature": "on3v_vv",
                    "conn": {
                        "service": "referentiels",
                        "schema": "on3v",
                        "table": "mv_voie_cyclable",
                        "geom_column": "geometry",
                        "srid": 2154,
                        "key_column": "fid"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Tourisme"}
                },

                # -- PostGIS schema : sandre --
                {
                    "id": "bdtopage_plan_deau",
                    "name": "Plans d'eau",
                    "type": "postgis",
                    "nomenclature": "bdtopage_plan_deau",
                    "conn": {
                        "service": "referentiels",
                        "schema": "sandre",
                        "table": "bd_topage_plan_eau",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_naturel"}
                },
                {
                    "id": "bdtopage_troncon",
                    "name": "Tronçons cours d'eau",
                    "type": "postgis",
                    "nomenclature": "bdtopage_troncon",
                    "conn": {
                        "service": "referentiels",
                        "schema": "sandre",
                        "table": "bd_topage_troncon_hydrographique",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_naturel"}
                },

                # -- PostGIS schema : sncf --
                {
                    "id": "sncf_reseau_ferre",
                    "name": "Réseau ferré",
                    "type": "postgis",
                    "nomenclature": "sncf_reseau_ferre",
                    "conn": {
                        "service": "referentiels",
                        "schema": "sncf",
                        "table": "lignes_du_rfn",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                }
            ]
        },

        # ------------------------------------------------------------------ #
        #  EIE                                                                 #
        # ------------------------------------------------------------------ #
        "EIE": {
            "sources": [

                # -- Atlasanté --
                {
                    "id": "atlasante_captages",
                    "name": "Captages eau potable (Atlasanté)",
                    "type": "api_geojson",
                    "nomenclature": "atlasante_captages",
                    "conn": {
                        "url": "https://catalogue.atlasante.fr/api/data/4d28cca8-fa80-49d7-bee2-8a2326b86f29?srs=EPSG:4326",
                        "login_url": "https://cas.atlasante.fr/login",
                        "credentials_var": "atlasante"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "atlasante_captages_ppe",
                    "name": "Périmètres de Protection Eloignée (PPE) (Atlasanté)",
                    "type": "api_geojson",
                    "nomenclature": "atlasante_captages_ppe",
                    "conn": {
                        "url": "https://catalogue.atlasante.fr/api/data/ce42e88d-3bff-4807-95e6-1a6b626afd37?srs=EPSG:4326",
                        "login_url": "https://cas.atlasante.fr/login",
                        "credentials_var": "atlasante"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "atlasante_captages_ppr",
                    "name": "Périmètres de Protection Rapprochée (PPR) (Atlasanté)",
                    "type": "api_geojson",
                    "nomenclature": "atlasante_captages_ppr",
                    "conn": {
                        "url": "https://catalogue.atlasante.fr/api/data/141fb799-1561-4e58-97c6-3b081bd23e0f?srs=EPSG:4326",
                        "login_url": "https://cas.atlasante.fr/login",
                        "credentials_var": "atlasante"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },

                # -- Enedis / PostGIS schema : enedis --
                {
                    "id": "enedis_ligne_aerienne_bt",
                    "name": "Enedis - Ligne aérienne BT",
                    "type": "postgis",
                    "nomenclature": "enedis_ligne_aerienne_bt",
                    "conn": {
                        "service": "referentiels",
                        "schema": "enedis",
                        "table": "ligne_aerienne_bt",
                        "geom_column": "geom",
                        "srid": 4326
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "enedis_ligne_aerienne_hta",
                    "name": "Enedis - Ligne aérienne HTA",
                    "type": "postgis",
                    "nomenclature": "enedis_ligne_aerienne_hta",
                    "conn": {
                        "service": "referentiels",
                        "schema": "enedis",
                        "table": "ligne_aerienne_hta",
                        "geom_column": "geom",
                        "srid": 4326
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "enedis_ligne_souterraine_bta",
                    "name": "Enedis - Ligne souterraine BTA",
                    "type": "postgis",
                    "nomenclature": "enedis_ligne_souterraine_bta",
                    "conn": {
                        "service": "referentiels",
                        "schema": "enedis",
                        "table": "ligne_souterraine_bta",
                        "geom_column": "geom",
                        "srid": 4326
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "enedis_ligne_souterraine_hta",
                    "name": "Enedis - Ligne souterraine HTA",
                    "type": "postgis",
                    "nomenclature": "enedis_ligne_souterraine_hta",
                    "conn": {
                        "service": "referentiels",
                        "schema": "enedis",
                        "table": "ligne_souterraine_hta",
                        "geom_column": "geom",
                        "srid": 4326
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },

                # -- Géorisques / PostGIS schema : georisques --
                {
                    "id": "georisques_old",
                    "name": "Aléa feu de forêt et obligation légale de débroussaillement",
                    "type": "postgis",
                    "nomenclature": "georisques_old",
                    "conn": {
                        "service": "referentiels",
                        "schema": "georisques",
                        "table": "obligation_legale_de_debroussaillement",
                        "geom_column": "wkb_geometry",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "georisques_alea_nappes",
                    "name": "Aléa remontées de nappes",
                    "type": "postgis",
                    "nomenclature": "georisques_alea_nappes",
                    "conn": {
                        "service": "referentiels",
                        "schema": "georisques",
                        "table": "alea_remontee_de_nappe",
                        "geom_column": "wkb_geometry",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_physique"}
                },
                {
                    "id": "georisques_alea_mvt_terrain",
                    "name": "Aléas mouvement de terrain",
                    "type": "postgis",
                    "nomenclature": "georisques_alea_mvt_terrain",
                    "conn": {
                        "service": "referentiels",
                        "schema": "georisques",
                        "table": "alea_mouvement_de_terrain",
                        "geom_column": "wkb_geometry",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_physique"}
                },
                {
                    "id": "georisques_alea_argiles",
                    "name": "Aléas retrait et gonflement des argiles",
                    "type": "postgis",
                    "nomenclature": "georisques_alea_argiles",
                    "conn": {
                        "service": "referentiels",
                        "schema": "georisques",
                        "table": "alea_retrait_gonflement_argile",
                        "geom_column": "wkb_geometry",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_physique"}
                },
                {
                    "id": "georisques_casias",
                    "name": "Site industriel (CASIAS / ICP)",
                    "type": "postgis",
                    "nomenclature": "georisques_casias",
                    "conn": {
                        "service": "referentiels",
                        "schema": "georisques",
                        "table": "casias",
                        "geom_column": "wkb_geometry",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "georisques_icpe",
                    "name": "Site industriel (ICPE)",
                    "type": "postgis",
                    "nomenclature": "georisques_icpe",
                    "conn": {
                        "service": "referentiels",
                        "schema": "georisques",
                        "table": "icpe",
                        "geom_column": "wkb_geometry",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },

                # -- GRDF --
                {
                    "id": "grdf_reseau_gaz",
                    "name": "GRDF - Réseau de distribution gaz",
                    "type": "api_geojson",
                    "nomenclature": "grdf_reseau_gaz",
                    "conn": {
                        "url": "https://opendata.grdf.fr/api/explore/v2.1/catalog/datasets/cartographie-du-reseau-grdf-en-service/exports/geojson",
                        "ods_where_geo_field": "geo_shape"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },

                # -- IGN / PostGIS schema : ign --
                {
                    "id": "bdtopo_bassin_versant",
                    "name": "Bassins versants",
                    "type": "postgis",
                    "nomenclature": "bdtopo_bassin_versant",
                    "conn": {
                        "service": "referentiels",
                        "schema": "ign",
                        "table": "bdtopo_bassin_versant",
                        "geom_column": "wkb_geometry",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_physique"}
                },
                {
                    "id": "bdforet_sylviculture",
                    "name": "Sylviculture",
                    "type": "postgis",
                    "nomenclature": "bdforet_sylviculture",
                    "conn": {
                        "service": "referentiels",
                        "schema": "ign",
                        "table": "bdforet_v2",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "ign_rpg_agricole",
                    "name": "Terre à usage agricole",
                    "type": "postgis",
                    "nomenclature": "ign_rpg_agricole",
                    "conn": {
                        "service": "referentiels",
                        "schema": "ign",
                        "table": "rpg_parcelle",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },

                # -- IGN / data.geopf.fr – Documents d'urbanisme (WFS) --
                {
                    "id": "ign_prescription_lineaire",
                    "name": "PLU – Prescriptions linéaires",
                    "type": "wfs",
                    "nomenclature": "ign_prescription_lineaire",
                    "conn": {
                        "base_url": "https://data.geopf.fr/wfs/ows?VERSION=2.0.0",
                        "typename": "wfs_du:prescription_lin"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "ign_prescription_ponctuel",
                    "name": "PLU – Prescriptions ponctuelles",
                    "type": "wfs",
                    "nomenclature": "ign_prescription_ponctuel",
                    "conn": {
                        "base_url": "https://data.geopf.fr/wfs/ows?VERSION=2.0.0",
                        "typename": "wfs_du:prescription_pct"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "ign_prescription_surfacique",
                    "name": "PLU – Prescriptions surfaciques",
                    "type": "wfs",
                    "nomenclature": "ign_prescription_surfacique",
                    "conn": {
                        "base_url": "https://data.geopf.fr/wfs/ows?VERSION=2.0.0",
                        "typename": "wfs_du:prescription_surf"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "ign_zonages_urbanisme",
                    "name": "PLU – Zonages",
                    "type": "wfs",
                    "nomenclature": "ign_zonages_urbanisme",
                    "conn": {
                        "base_url": "https://data.geopf.fr/wfs/ows?VERSION=2.0.0",
                        "typename": "wfs_du:zone_urba"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },

                # -- INRAE / PostGIS schema : etat --
                {
                    "id": "inra_pedologie",
                    "name": "Pédologie",
                    "type": "postgis",
                    "nomenclature": "inra_pedologie",
                    "conn": {
                        "service": "referentiels",
                        "schema": "etat",
                        "table": "inra_carte_sols_geoportail_vf",
                        "geom_column": "geom",
                        "srid": 2154,
                        "key_column": "id"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },

                # -- La Fibre / PostGIS schema : fh_lafibre --
                {
                    "id": "fh_reseau_hertzien",
                    "name": "Communication radio-électriques",
                    "type": "postgis",
                    "nomenclature": "fh_reseau_hertzien",
                    "conn": {
                        "service": "referentiels",
                        "schema": "fh_lafibre",
                        "table": "reseau_hertzien",
                        "geom_column": "wkb_geometry",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },

                # -- ONF / PostGIS schema : onf --
                {
                    "id": "onf_forets_publiques",
                    "name": "ONF - Forêts Publiques",
                    "type": "postgis",
                    "nomenclature": "onf_forets_publiques",
                    "conn": {
                        "service": "referentiels",
                        "schema": "onf",
                        "table": "foret_publique",
                        "geom_column": "wkb_geometry",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_naturel"}
                },

                # -- RTE / WFS geo-ide --
                {
                    "id": "rte_ligne_aerienne",
                    "name": "RTE - Lignes aériennes",
                    "type": "wfs",
                    "nomenclature": "rte_ligne_aerienne",
                    "conn": {
                        "base_url": "https://ogc.geo-ide.developpement-durable.gouv.fr/wxs?map=/opt/data/stack/mapfiles/1.4/org_37992/67a174b6-b49a-4aa3-8f1b-07a92c82b911.internet.map&VERSION=2.0.0",
                        "typename": "ms:N_RESEAU_ELECTRIQUE_AERIEN_L_027",
                        "skip_native": True
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "rte_ligne_souterraine",
                    "name": "RTE - Lignes souterraines",
                    "type": "wfs",
                    "nomenclature": "rte_ligne_souterraine",
                    "conn": {
                        "base_url": "https://ogc.geo-ide.developpement-durable.gouv.fr/wxs?map=/opt/data/stack/mapfiles/1.4/org_37970/d0c8ee1d-dcaa-4acb-a584-845b2910edd3.internet.map&VERSION=2.0.0",
                        "typename": "ms:L_RESEAU_ELECTRIQUE_SOUTERRAIN_RTE",
                        "skip_native": True
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },

                # -- SANDRE / WFS --
                {
                    "id": "brgm_masse_deau_souterraine",
                    "name": "Masses d'eau souterraines",
                    "type": "wfs",
                    "nomenclature": "brgm_masse_deau_souterraine",
                    "conn": {
                        "base_url": "https://services.sandre.eaufrance.fr/geo/MasseDEau_VRAP2022",
                        "typename": "sa:MasseDEauSouterraine_VRAP2022",
                        "version": "1.1.0",
                        "srsname": "EPSG:2154"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_physique"}
                },
                {
                    "id": "sage_perimetre",
                    "name": "SAGE",
                    "type": "wfs",
                    "nomenclature": "sage_perimetre",
                    "conn": {
                        "base_url": "https://services.sandre.eaufrance.fr/geo/zpl",
                        "typename": "Sage",
                        "srsname": "EPSG:2154"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                }
            ]
        },

        # ------------------------------------------------------------------ #
        #  MNB – Milieu Naturel et Biodiversité                               #
        # ------------------------------------------------------------------ #
        "MNB": {
            "sources": [

                # -- INPN / PostGIS schema : inpn --
                {
                    "id": "inpn_pn",
                    "name": "INPN - Parcs Naturels Nationaux",
                    "type": "postgis",
                    "nomenclature": "inpn_pn",
                    "conn": {
                        "service": "referentiels",
                        "schema": "inpn",
                        "table": "parcs_nationaux",
                        "geom_column": "geom",
                        "srid": 3857,
                        "key_column": "fid"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_naturel"}
                },
                {
                    "id": "inpn_pnr",
                    "name": "INPN - Parcs Naturels Régionaux",
                    "type": "postgis",
                    "nomenclature": "inpn_pnr",
                    "conn": {
                        "service": "referentiels",
                        "schema": "inpn",
                        "table": "parcs_naturels_regionaux",
                        "geom_column": "geom",
                        "srid": 3857,
                        "key_column": "fid"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_naturel"}
                },
                {
                    "id": "inpn_rnn",
                    "name": "INPN - Réserves Naturelles Nationales",
                    "type": "postgis",
                    "nomenclature": "inpn_rnn",
                    "conn": {
                        "service": "referentiels",
                        "schema": "inpn",
                        "table": "reserves_naturelles_nationales",
                        "geom_column": "geom",
                        "srid": 3857,
                        "key_column": "fid"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_naturel"}
                },
                {
                    "id": "inpn_rnr",
                    "name": "INPN - Réserves Naturelles Régionales",
                    "type": "postgis",
                    "nomenclature": "inpn_rnr",
                    "conn": {
                        "service": "referentiels",
                        "schema": "inpn",
                        "table": "reserves_naturelles_regionales",
                        "geom_column": "geom",
                        "srid": 3857,
                        "key_column": "fid"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_naturel"}
                },
                {
                    "id": "inpn_znieff1",
                    "name": "INPN - ZNIEFF de type 1",
                    "type": "postgis",
                    "nomenclature": "inpn_znieff1",
                    "conn": {
                        "service": "referentiels",
                        "schema": "inpn",
                        "table": "znieff1",
                        "geom_column": "geom",
                        "srid": 3857,
                        "key_column": "fid"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_naturel"}
                },
                {
                    "id": "inpn_znieff2",
                    "name": "INPN - ZNIEFF de type 2",
                    "type": "postgis",
                    "nomenclature": "inpn_znieff2",
                    "conn": {
                        "service": "referentiels",
                        "schema": "inpn",
                        "table": "znieff2",
                        "geom_column": "geom",
                        "srid": 3857,
                        "key_column": "fid"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_naturel"}
                }
            ]
        }
    }
}
