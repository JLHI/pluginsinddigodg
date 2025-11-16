-- ==========================================================
-- TRAITEMENT COMPLET DE (Déplacements scolaires)
-- ==========================================================

CREATE TEMP TABLE flux_insee_de_flux AS
SELECT
    fd.commune || fd.dcetuf AS id_concatener,
    fd.commune AS commune_origine,
    fd.dcetue AS c_etrangere,
    ce.libelle AS nom_com_etrangere,
    fd.dcetuf AS commune_destination,
    age.libelle AS age,
    cs.libelle AS csp,
    SUM(fd.ipondi) AS flux
FROM flux_insee_temp_territoire t
JOIN flux_insee.fd_mobsco_2015 fd
    ON t.insee = fd.commune OR t.insee = fd.dcetuf
LEFT JOIN flux_insee.comm_etrangere ce
    ON ce.code_com_etranger = fd.dcetue
LEFT JOIN flux_insee.cs1 cs
    ON cs.code_cs1 = fd.csm
LEFT JOIN flux_insee.agerev10 age
    ON age.code_agerev10 = fd.agerev10
GROUP BY
    fd.commune, fd.dcetuf,
    ce.libelle, fd.dcetue,
    age.libelle, cs.libelle;


ALTER TABLE flux_insee_de_flux
ADD COLUMN type_flux VARCHAR(20),
ADD COLUMN nom_commune_origine VARCHAR(150),
ADD COLUMN nom_commune_destination VARCHAR(150),
ADD COLUMN temp_origine_flux VARCHAR(3),
ADD COLUMN temp_destination_flux VARCHAR(3);


-- =============================
--   NOMS DES COMMUNES
-- =============================
UPDATE flux_insee_de_flux f
SET nom_commune_origine = c.libelle
FROM flux_insee.communes_2018 c
WHERE f.commune_origine = c.code_commune;

UPDATE flux_insee_de_flux f
SET nom_commune_destination = c.libelle
FROM flux_insee.communes_2018 c
WHERE f.commune_destination = c.code_commune;


-- =============================
--   COMMUNES ÉTRANGÈRES
-- =============================
UPDATE flux_insee_de_flux
SET commune_origine = c_etrangere
WHERE commune_origine = '99999';

UPDATE flux_insee_de_flux
SET commune_destination = c_etrangere
WHERE commune_destination = '99999';

UPDATE flux_insee_de_flux
SET nom_commune_origine = nom_com_etrangere
WHERE commune_origine = c_etrangere;

UPDATE flux_insee_de_flux
SET nom_commune_destination = nom_com_etrangere
WHERE commune_destination = c_etrangere;


-- =============================
--   REGROUPEMENTS LYON / PARIS / MARSEILLE
-- =============================
UPDATE flux_insee_de_flux
SET nom_commune_destination = 'Lyon'
WHERE commune_destination IN ('69381','69382','69383','69384','69385','69386','69387','69388','69389');

UPDATE flux_insee_de_flux
SET nom_commune_destination = 'Paris'
WHERE commune_destination IN ('75101','75102','75103','75104','75105','75106','75107','75108',
                              '75109','75110','75111','75112','75113','75114','75115','75116',
                              '75117','75118','75119','75120');

UPDATE flux_insee_de_flux
SET nom_commune_destination = 'Marseille'
WHERE commune_destination IN ('13201','13202','13203','13204','13205','13206','13207','13208',
                              '13209','13210','13211','13212','13213','13214','13215','13216');


UPDATE flux_insee_de_flux SET commune_destination = '69123' WHERE nom_commune_destination = 'Lyon';
UPDATE flux_insee_de_flux SET commune_destination = '75056' WHERE nom_commune_destination = 'Paris';
UPDATE flux_insee_de_flux SET commune_destination = '13055' WHERE nom_commune_destination = 'Marseille';


-- =============================
--   DÉTECTION TYPE FLUX
-- =============================
UPDATE flux_insee_de_flux f
SET temp_origine_flux = 'Oui'
FROM flux_insee_temp_territoire t
WHERE t.insee = f.commune_origine;

UPDATE flux_insee_de_flux f
SET temp_destination_flux = 'Oui'
FROM flux_insee_temp_territoire t
WHERE t.insee = f.commune_destination;

UPDATE flux_insee_de_flux
SET type_flux = 'Sortant'
WHERE temp_origine_flux = 'Oui' AND temp_destination_flux IS NULL;

UPDATE flux_insee_de_flux
SET type_flux = 'Entrant'
WHERE temp_origine_flux IS NULL AND temp_destination_flux = 'Oui';

UPDATE flux_insee_de_flux
SET type_flux = 'Interne'
WHERE temp_origine_flux = 'Oui' AND temp_destination_flux = 'Oui';

UPDATE flux_insee_de_flux
SET type_flux = 'Intra'
WHERE commune_origine = commune_destination;


-- =============================
--   CORRECTION ID + FLUX INTERNE
-- =============================
UPDATE flux_insee_de_flux
SET id_concatener = commune_origine || commune_destination;

UPDATE flux_insee_de_flux
SET flux = flux / 2
WHERE type_flux = 'Interne';


-- =============================
--   TABLES V2 (Détail) et V3 (Synthèse)
-- =============================
CREATE TEMP TABLE flux_insee_de_flux_v2 AS
SELECT
    id_concatener, commune_origine, nom_commune_origine,
    commune_destination, nom_commune_destination,
    age, csp, SUM(flux) AS flux, type_flux
FROM flux_insee_de_flux
GROUP BY 1,2,3,4,5,6,7,9;

CREATE TEMP TABLE flux_insee_de_flux_v3 AS
SELECT
    id_concatener, commune_origine, nom_commune_origine,
    commune_destination, nom_commune_destination,
    SUM(flux) AS flux, type_flux
FROM flux_insee_de_flux
GROUP BY 1,2,3,4,5,7;
