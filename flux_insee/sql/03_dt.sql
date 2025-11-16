-- ==========================================================
-- TRAITEMENT COMPLET DT
-- ==========================================================

CREATE TEMP TABLE flux_insee_dt_flux AS
SELECT
    fd.commune || fd.dclt AS id_concatener,
    fd.commune AS commune_origine,
    fd.dcflt AS c_etrangere,
    ce.libelle AS nom_com_etrangere,
    fd.dclt AS commune_destination,
    age.libelle AS age,
    tr.libelle AS mode_de_transport,
    cs.libelle AS csp,
    SUM(fd.ipondi) AS flux
FROM flux_insee_temp_territoire t
JOIN flux_insee.fd_mobpro_2015 fd
    ON t.insee = fd.commune OR t.insee = fd.dclt
LEFT JOIN flux_insee.comm_etrangere ce
    ON ce.code_com_etranger = fd.dcflt
LEFT JOIN flux_insee.trans tr
    ON tr.code_trans = fd.trans
LEFT JOIN flux_insee.cs1 cs
    ON cs.code_cs1 = fd.cs1
LEFT JOIN flux_insee.agerevq age
    ON age.code_agerevq = fd.agerevq
GROUP BY
    fd.commune, fd.dclt,
    ce.libelle, fd.dcflt,
    age.libelle, tr.libelle, cs.libelle;

ALTER TABLE flux_insee_dt_flux
ADD COLUMN type_flux VARCHAR(20),
ADD COLUMN nom_commune_origine VARCHAR(150),
ADD COLUMN nom_commune_destination VARCHAR(150),
ADD COLUMN temp_origine_flux VARCHAR(3),
ADD COLUMN temp_destination_flux VARCHAR(3);

UPDATE flux_insee_dt_flux f
SET nom_commune_origine = c.libelle
FROM flux_insee.communes_2018 c
WHERE f.commune_origine = c.code_commune;

UPDATE flux_insee_dt_flux f
SET nom_commune_destination = c.libelle
FROM flux_insee.communes_2018 c
WHERE f.commune_destination = c.code_commune;

UPDATE flux_insee_dt_flux
SET commune_origine = c_etrangere
WHERE commune_origine = '99999';

UPDATE flux_insee_dt_flux
SET commune_destination = c_etrangere
WHERE commune_destination = '99999';

UPDATE flux_insee_dt_flux
SET nom_commune_origine = nom_com_etrangere
WHERE commune_origine = c_etrangere;

UPDATE flux_insee_dt_flux
SET nom_commune_destination = nom_com_etrangere
WHERE commune_destination = c_etrangere;

UPDATE flux_insee_dt_flux
SET nom_commune_destination = 'Lyon'
WHERE commune_destination IN ('69381','69382','69383','69384','69385','69386','69387','69388','69389');

UPDATE flux_insee_dt_flux
SET nom_commune_destination = 'Paris'
WHERE commune_destination IN ('75101','75102','75103','75104','75105','75106','75107','75108',
                              '75109','75110','75111','75112','75113','75114','75115','75116',
                              '75117','75118','75119','75120');

UPDATE flux_insee_dt_flux
SET nom_commune_destination = 'Marseille'
WHERE commune_destination IN ('13201','13202','13203','13204','13205','13206','13207','13208',
                              '13209','13210','13211','13212','13213','13214','13215','13216');

UPDATE flux_insee_dt_flux SET commune_destination = '69123' WHERE nom_commune_destination = 'Lyon';
UPDATE flux_insee_dt_flux SET commune_destination = '75056' WHERE nom_commune_destination = 'Paris';
UPDATE flux_insee_dt_flux SET commune_destination = '13055' WHERE nom_commune_destination = 'Marseille';

UPDATE flux_insee_dt_flux f
SET temp_origine_flux = 'Oui'
FROM flux_insee_temp_territoire t
WHERE t.insee = f.commune_origine;

UPDATE flux_insee_dt_flux f
SET temp_destination_flux = 'Oui'
FROM flux_insee_temp_territoire t
WHERE t.insee = f.commune_destination;

UPDATE flux_insee_dt_flux
SET type_flux = 'Sortant'
WHERE temp_origine_flux = 'Oui' AND temp_destination_flux IS NULL;

UPDATE flux_insee_dt_flux
SET type_flux = 'Entrant'
WHERE temp_origine_flux IS NULL AND temp_destination_flux = 'Oui';

UPDATE flux_insee_dt_flux
SET type_flux = 'Interne'
WHERE temp_origine_flux = 'Oui' AND temp_destination_flux = 'Oui';

UPDATE flux_insee_dt_flux
SET type_flux = 'Intra'
WHERE commune_origine = commune_destination;

UPDATE flux_insee_dt_flux
SET id_concatener = commune_origine || commune_destination;

UPDATE flux_insee_dt_flux
SET flux = flux / 2
WHERE type_flux = 'Interne';

CREATE TEMP TABLE flux_insee_dt_flux_v2 AS
SELECT
    id_concatener, commune_origine, nom_commune_origine,
    commune_destination, nom_commune_destination,
    age, mode_de_transport, csp, SUM(flux) AS flux, type_flux
FROM flux_insee_dt_flux
GROUP BY 1,2,3,4,5,6,7,8,10;

CREATE TEMP TABLE flux_insee_dt_flux_v3 AS
SELECT
    id_concatener, commune_origine, nom_commune_origine,
    commune_destination, nom_commune_destination,
    SUM(flux) AS flux, type_flux
FROM flux_insee_dt_flux
GROUP BY 1,2,3,4,5,7;