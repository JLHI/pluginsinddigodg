# -*- coding: utf-8 -*-
DEFAULT_CONFIG = {
    "groups": {
        "Communs": {
            "sources": [
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
        "Paysage": {
            "sources": [
                {
                    "id": "bdtopo_bati",
                    "name": "Bâti",
                    "type": "postgis",
                    "nomenclature": "bdtopo_bati",
                    "conn": {
                        "service": "referentiels",
                        "schema": "ign",
                        "table": "bati",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "bdtopo_route",
                    "name": "Routes",
                    "type": "postgis",
                    "nomenclature": "bdtopo_route",
                    "conn": {
                        "service": "referentiels",
                        "schema": "ign",
                        "table": "route",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "bdtopo_vegetation",
                    "name": "Végétation",
                    "type": "postgis",
                    "nomenclature": "bdtopo_vegetation",
                    "conn": {
                        "service": "referentiels",
                        "schema": "ign",
                        "table": "vegetation",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "sncf_reseau_ferre",
                    "name": "Réseau ferré",
                    "type": "postgis",
                    "nomenclature": "sncf_reseau_ferre",
                    "conn": {
                        "service": "referentiels",
                        "schema": "sncf",
                        "table": "reseau_ferre",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "ign_rgealt_5m",
                    "name": "Altimétrie (raster – non géré automatiquement)",
                    "type": "raster",
                    "nomenclature": "ign_rgealt_5m",
                    "target": {"folder": "3-DATA RASTER"}
                },
                {
                    "id": "bdtopage_troncon",
                    "name": "Tronçons cours d'eau",
                    "type": "postgis",
                    "nomenclature": "bdtopage_troncon",
                    "conn": {
                        "service": "referentiels",
                        "schema": "ign",
                        "table": "troncon_cours_eau",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_naturel"}
                },
                {
                    "id": "adp_bien_unesco",
                    "name": "Bien Unesco",
                    "type": "wfs",
                    "nomenclature": "adp_bien_unesco",
                    "conn": {
                        "base_url": "https://atlas.patrimoines.culture.fr/geoserver/wfs",
                        "typename": "atlas_patrimoines:UNESCO_PATRIMOINE_MONDIAL"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },
                {
                    "id": "adp_spr",
                    "name": "Site Patrimonial Remarquable (SPR)",
                    "type": "wfs",
                    "nomenclature": "adp_spr",
                    "conn": {
                        "base_url": "https://atlas.patrimoines.culture.fr/geoserver/wfs",
                        "typename": "atlas_patrimoines:SITE_PATRIMONIAL_REMARQUABLE"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },
                {
                    "id": "adp_site_classe_inscrit",
                    "name": "Site classé et inscrit",
                    "type": "wfs",
                    "nomenclature": "adp_site_classe_inscrit",
                    "conn": {
                        "base_url": "https://atlas.patrimoines.culture.fr/geoserver/wfs",
                        "typename": "atlas_patrimoines:SITES_CLASSES_ET_INSCRITS"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },
                {
                    "id": "adp_mh",
                    "name": "Monument historique (MH)",
                    "type": "wfs",
                    "nomenclature": "adp_mh",
                    "conn": {
                        "base_url": "https://atlas.patrimoines.culture.fr/geoserver/wfs",
                        "typename": "atlas_patrimoines:MONUMENTS_HISTORIQUES"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },
                {
                    "id": "adp_perimetre_mh",
                    "name": "Périmètre de protection autour du MH",
                    "type": "wfs",
                    "nomenclature": "adp_perimetre_mh",
                    "conn": {
                        "base_url": "https://atlas.patrimoines.culture.fr/geoserver/wfs",
                        "typename": "atlas_patrimoines:PERIMETRE_PROTECTION_MH"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },
                {
                    "id": "adp_zppa",
                    "name": "Patrimoine archéologique (ZPPA)",
                    "type": "wfs",
                    "nomenclature": "adp_zppa",
                    "conn": {
                        "base_url": "https://atlas.patrimoines.culture.fr/geoserver/wfs",
                        "typename": "atlas_patrimoines:ZONE_PROTECTION_PATRIMOINE_ARCHEO"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Patrimoine"}
                },
                {
                    "id": "on3v_vv",
                    "name": "Véloroutes Voies Vertes",
                    "type": "postgis",
                    "nomenclature": "on3v_vv",
                    "conn": {
                        "service": "referentiels",
                        "schema": "on3v",
                        "table": "voies_vertes",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "grande_randonnee",
                    "name": "Sentiers de randonnées",
                    "type": "postgis",
                    "nomenclature": "grande_randonnee",
                    "conn": {
                        "service": "referentiels",
                        "schema": "ign",
                        "table": "itineraire_randonnee",
                        "geom_column": "geom",
                        "srid": 2154
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "dt_tourisme",
                    "name": "Tourisme",
                    "type": "api_geojson",
                    "nomenclature": "dt_tourisme",
                    "conn": {
                        "url": "https://diffusionv2.datatourisme.fr/onTour/touristic-objects?lat={lat}&lon={lon}&dist={dist_km}&format=geojson"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
                {
                    "id": "unites_paysageres",
                    "name": "Unités paysagères",
                    "type": "wfs",
                    "nomenclature": "unites_paysageres",
                    "conn": {
                        "base_url": "https://wxs.ign.fr/paysage/geoportail/wfs",
                        "typename": "UNITE_PAYSAGERE"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Paysage"}
                }
            ]
        },
        "EIE": {
            "sources": [
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
                },
                {
                    "id": "ign_servitude_aero",
                    "name": "Servitudes aéronautiques",
                    "type": "wfs",
                    "nomenclature": "ign_servitude_aero",
                    "conn": {
                        "base_url": "https://ogc.geo-ide.developpement-durable.gouv.fr/wfs",
                        "typename": "ms:SDA_CAT"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
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
                    "id": "georisques_casias",
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
                    "id": "enedis_reseau",
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
                    "id": "enedis_reseau",
                    "name": "Enedis - Ligne aérienne HTA",
                    "type": "postgis",
                    "nomenclature": "ligne_aerienne_hta",
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
                    "id": "enedis_reseau",
                    "name": "Enedis - Ligne souterraine BTA",
                    "type": "postgis",
                    "nomenclature": "ligne_souterraine_bta",
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
                    "id": "enedis_reseau",
                    "name": "Enedis - Ligne souterraine HTA",
                    "type": "postgis",
                    "nomenclature": "ligne_souterraine_hta",
                    "conn": {
                        "service": "referentiels",
                        "schema": "enedis",
                        "table": "ligne_souterraine_hta",
                        "geom_column": "geom",
                        "srid": 4326
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
                    "id": "rte_ligne_aerienne",
                    "name": "RTE - Lignes aériennes",
                    "type": "wfs",
                    "nomenclature": "rte_ligne_aerienne",
                    "conn": {
                        "base_url": "https://ogc.geo-ide.developpement-durable.gouv.fr/wxs?map=/opt/data/stack/mapfiles/1.4/org_37992/67a174b6-b49a-4aa3-8f1b-07a92c82b911.internet.map&VERSION=2.0.0",
                        "typename": "ms:N_RESEAU_ELECTRIQUE_AERIEN_L_027"
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
                        "typename": "ms:L_RESEAU_ELECTRIQUE_SOUTERRAIN_RTE"
                    },
                    "target": {"folder": "4-DATA VECTEUR/Milieu_humain"}
                },
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
                }
            ]
        }
    }
}
