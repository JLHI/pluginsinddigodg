SELECT
    id_concatener,
    commune_origine,
    nom_commune_origine,
    commune_destination,
    nom_commune_destination,
    flux,
    type_flux
FROM flux_insee_de_flux_v3
ORDER BY id_concatener;
