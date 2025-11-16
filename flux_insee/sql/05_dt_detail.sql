SELECT
    id_concatener,
    commune_origine,
    nom_commune_origine,
    commune_destination,
    nom_commune_destination,
    age,
    mode_de_transport,
    csp,
    flux,
    type_flux
FROM flux_insee_dt_flux_v2
ORDER BY id_concatener;