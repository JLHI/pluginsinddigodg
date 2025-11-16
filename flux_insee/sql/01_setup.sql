DROP TABLE IF EXISTS flux_insee_temp_territoire;
DROP TABLE IF EXISTS flux_insee_dt_flux;
DROP TABLE IF EXISTS flux_insee_dt_flux_v2;
DROP TABLE IF EXISTS flux_insee_dt_flux_v3;
DROP TABLE IF EXISTS flux_insee_de_flux;
DROP TABLE IF EXISTS flux_insee_de_flux_v2;
DROP TABLE IF EXISTS flux_insee_de_flux_v3;

CREATE TEMP TABLE flux_insee_temp_territoire (
    insee varchar(10),
    nom varchar(255)
) ;