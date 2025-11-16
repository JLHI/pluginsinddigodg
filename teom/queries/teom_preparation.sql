-- ============================================================================
-- TEOM — PRÉPARATION COMPLÈTE
-- VERSION : TABLES TEMPORAIRES (pg_temp)
-- Tables sources : {schema}
-- Données externes : teom_data.*
-- ============================================================================

-- ============================================================================
-- CLEAN
-- ============================================================================
DROP TABLE IF EXISTS request7;
DROP TABLE IF EXISTS request6;
DROP TABLE IF EXISTS request5;
DROP TABLE IF EXISTS request4;
DROP TABLE IF EXISTS request3;
DROP TABLE IF EXISTS request2;
DROP TABLE IF EXISTS request1;

DROP TABLE IF EXISTS tp_local10;
DROP TABLE IF EXISTS tp_local00;
DROP TABLE IF EXISTS tp_parcelle;
DROP TABLE IF EXISTS tp_prop;
DROP TABLE IF EXISTS tp_pev;
DROP TABLE IF EXISTS tp_pevprincipale;
DROP TABLE IF EXISTS tp_pevtaxation;
DROP TABLE IF EXISTS tp_pevdependances;
DROP TABLE IF EXISTS type_locaux;

-- ============================================================================
-- 1) TABLES TEMPORAIRES – normalisation MAJIC
-- ============================================================================

-- LOCAL10
CREATE TEMP TABLE tp_local10 AS
SELECT 
    ccodep || ccocom AS code_insee,
    invar,
    parcelle AS l_parcelle,
    dnupro,
    comptecommunal AS l_comptecommunal,
    dteloc,
    gtauom,
    dcomrd,
    cconlc,
    dnatlc,
    hlmsem,
    gimtom,
    dnbniv,
    jannat
FROM {schema}.local10;

UPDATE tp_local10 SET dteloc = d.dteloc_lib
FROM {schema}.dteloc d
WHERE tp_local10.dteloc = d.dteloc;

UPDATE tp_local10 SET cconlc = c.cconlc_lib
FROM {schema}.cconlc c
WHERE tp_local10.cconlc = c.cconlc;

UPDATE tp_local10 SET dnatlc = n.dnatlc_lib
FROM {schema}.dnatlc n
WHERE tp_local10.dnatlc = n.dnatlc;

-- PROPRIÉTAIRE
CREATE TEMP TABLE tp_prop AS
SELECT 
    comptecommunal,
    ccodro,
    gdesip,
    dnatpr,
    ccogrm,
    dforme,
    ddenom,
    dlign3,
    dlign4,
    dlign5,
    dlign6,
    ccovoi AS pr_ccovoi,
    ccoriv AS pr_ccoriv,
    dnvoiri AS pr_dnvoiri,
    dindic AS pr_dindic,
    ccopos,
    dnomlp,
    dprnlp,
    dsiren,
    dformjur
FROM {schema}.proprietaire;

UPDATE tp_prop SET ccodro = c.ccodro_lib
FROM {schema}.ccodro c
WHERE tp_prop.ccodro = c.ccodro;

-- PARCELLE
CREATE TEMP TABLE tp_parcelle AS
SELECT 
    parcelle AS p_parcelle,
    ccovoi AS pa_ccovoi,
    ccoriv AS pa_ccoriv,
    dnvoiri AS pa_dnvoiri,
    dindic AS pa_dindic,
    cconvo,
    dvoilib
FROM {schema}.parcelle;

-- LOCAL00
CREATE TEMP TABLE tp_local00 AS
SELECT 
    invar AS l_invar,
    ccopre,
    ccosec,
    dnupla,
    dnubat,
    descr,
    dniv,
    dpor
FROM {schema}.local00;

-- PEV
CREATE TEMP TABLE tp_pev AS
SELECT 
    invar AS p_invar,
    pev,
    dnupev,
    ccoaff,
    ccthp,
    topcn,
    tpevtieom
FROM {schema}.pev;

UPDATE tp_pev SET ccoaff = c.ccoaff_lib
FROM {schema}.ccoaff c
WHERE tp_pev.ccoaff = c.ccoaff;

-- PEV PRINCIPALE
CREATE TEMP TABLE tp_pevprincipale AS
SELECT 
    pev AS pp_pev,
    ggazlc,
    gelelc,
    geaulc,
    dnbpdc,
    dsupdc,
    dmatgm,
    dmatto,
    detent
FROM {schema}.pevprincipale;

-- PEV TAXATION
CREATE TEMP TABLE tp_pevtaxation AS
SELECT 
    pev AS pt_pev,
    bateom,
    baomec,
    mvltieomx,
    pvltieom
FROM {schema}.pevtaxation;

-- DÉPENDANCES
UPDATE {schema}.pevdependances
SET cconad = d.cconad_lib
FROM {schema}.cconad d
WHERE pevdependances.cconad = d.cconad;

CREATE TEMP TABLE tp_pevdependances AS
SELECT 
    pev AS pd_pev,
    array_agg(cconad) AS cconad
FROM {schema}.pevdependances
GROUP BY pev;

ALTER TABLE tp_pevdependances
ALTER COLUMN cconad TYPE varchar;

UPDATE tp_pevdependances SET cconad = REPLACE(cconad,'}','');
UPDATE tp_pevdependances SET cconad = REPLACE(cconad,'{','');

-- ============================================================================
-- 2) CHAÎNE DE REQUESTS
-- ============================================================================

CREATE TEMP TABLE request1 AS
SELECT * FROM tp_prop
LEFT JOIN tp_local10 ON tp_local10.l_comptecommunal = tp_prop.comptecommunal;

CREATE TEMP TABLE request2 AS
SELECT * FROM request1
LEFT JOIN tp_parcelle ON tp_parcelle.p_parcelle = request1.l_parcelle;

CREATE TEMP TABLE request3 AS
SELECT * FROM request2
LEFT JOIN tp_local00 ON tp_local00.l_invar = request2.invar;

CREATE TEMP TABLE request4 AS
SELECT * FROM request3
LEFT JOIN tp_pev ON tp_pev.p_invar = request3.invar;

CREATE TEMP TABLE request5 AS
SELECT * FROM request4
LEFT JOIN tp_pevprincipale ON tp_pevprincipale.pp_pev = request4.pev;

CREATE TEMP TABLE request6 AS
SELECT * FROM request5
LEFT JOIN tp_pevtaxation ON tp_pevtaxation.pt_pev = request5.pev;

CREATE TEMP TABLE request7 AS
SELECT * FROM request6
LEFT JOIN tp_pevdependances ON tp_pevdependances.pd_pev = request6.pev;

-- ============================================================================
-- 3) ENRICHISSEMENTS
-- ============================================================================

ALTER TABLE request7
ADD COLUMN commune text,
ADD COLUMN epci text,
ADD COLUMN code_naf text,
ADD COLUMN section_naf text,
ADD COLUMN tx_teom double precision,
ADD COLUMN mt_teom_ssfg numeric(10,2),
ADD COLUMN mt_teom_fg numeric(10,2);

UPDATE request7 r
SET epci = e.siren_epci
FROM teom_data.adminexpres_commune e
WHERE e.insee_com = r.code_insee;

UPDATE request7 r
SET commune = c.nom
FROM teom_data.communes c
WHERE c.insee = r.code_insee;

UPDATE request7 r
SET code_naf = s.activiteprincipaleetablissement
FROM teom_data.siren_data s
WHERE s.siren = r.dsiren;

UPDATE request7 r
SET section_naf = n.section
FROM teom_data.siren_naf n
WHERE n.code = r.code_naf;

-- ============================================================================
-- 4) CALCULS TEOM  (REVENU DU VIEUX CODE)
-- ============================================================================

UPDATE request7
SET tx_teom = 0.1224;  -- taux fixe (modifiable si besoin)

UPDATE request7
SET mt_teom_ssfg = COALESCE(bateom,0) * COALESCE(tx_teom,0);

UPDATE request7
SET mt_teom_fg = mt_teom_ssfg * 1.08;

-- ============================================================================
-- 5) NETTOYAGE
-- ============================================================================

ALTER TABLE request7
DROP COLUMN l_parcelle,
DROP COLUMN l_comptecommunal,
DROP COLUMN p_invar,
DROP COLUMN pev,
DROP COLUMN pt_pev,
DROP COLUMN pd_pev;

DELETE FROM request7 WHERE code_insee IS NULL;