-- ============================================================================
-- TEOM — PRÉPARATION COMPLÈTE
-- VERSION : TABLES TEMPORAIRES (pg_temp)
-- Tables sources : {schema}
-- Données externes : teom_data.*
--
-- Deux indicateurs RS sont produits :
--   proba_rprs      = estimation MAJIC brute (logique commune propriétaire)
--   proba_rprs_cal  = version CALÉE sur l'INSEE (totaux communaux = recensement)
--
-- PRÉREQUIS :
--   CREATE EXTENSION IF NOT EXISTS unaccent;
--   Table teom_data.insee_rs(insee text, nb_rs int)  -- voir section 3ter
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS unaccent SCHEMA teom;

-- ============================================================================
-- CLEAN
-- ============================================================================
DROP TABLE IF EXISTS request7;
DROP TABLE IF EXISTS request1;
DROP SCHEMA IF EXISTS teom_export CASCADE;
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
DROP TABLE IF EXISTS tp_nb_logt_proprio;
DROP TABLE IF EXISTS tp_classif;

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
    jannat,
    jdatat
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
ADD COLUMN mt_teom_fg numeric(10,2),
ADD COLUMN proba_rprs text,
ADD COLUMN proba_rprs_cal text;

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
-- 3bis) CLASSIFICATION MAJIC (logique commune propriétaire)
--       -> proba_rprs : estimation brute. Sur-estime structurellement les RS
--          (locatif + vacance non identifiables sans ccthp). À comparer, pas
--          à publier en absolu.
-- ============================================================================

-- Normalisation toponymique (accents, casse, ponctuation, ST/STE).
-- unaccent est qualifié (teom.unaccent) et le search_path est figé sur la
-- fonction : la résolution ne dépend plus du search_path de la session.
CREATE OR REPLACE FUNCTION teom_norm(t text) RETURNS text
LANGUAGE sql STABLE
SET search_path = teom, pg_temp
AS $$
  SELECT ' ' || btrim(regexp_replace(regexp_replace(
           regexp_replace(upper(teom.unaccent(coalesce(t,''))), '[^A-Z0-9]+', ' ', 'g'),
           '\mSTE\M', 'SAINTE', 'g'),
           '\mST\M', 'SAINT', 'g')) || ' '
$$;

-- Base dédoublonnée : un seul local par invar (destinataire de l'avis).
DROP TABLE IF EXISTS tp_classif;
CREATE TEMP TABLE tp_classif AS
SELECT DISTINCT ON (invar)
    invar, code_insee, comptecommunal, commune, dteloc, dnatpr, jdatat,
    ccopos, dlign6,
    NULL::text    AS proba_rprs,
    NULL::numeric AS score,
    NULL::text    AS proba_rprs_cal
FROM request7
WHERE invar IS NOT NULL
ORDER BY invar, (gdesip = '1') DESC NULLS LAST;

-- Cascade
UPDATE tp_classif SET proba_rprs = 'NC'
WHERE dteloc NOT IN ('Maison', 'Appartement');

UPDATE tp_classif SET proba_rprs = 'PM'
WHERE proba_rprs IS NULL AND dnatpr IS NOT NULL;

UPDATE tp_classif SET proba_rprs = 'INCONNU'
WHERE proba_rprs IS NULL AND (jdatat IS NULL OR jdatat !~ '^\d{8}$');

UPDATE tp_classif SET proba_rprs = 'AC'
WHERE proba_rprs IS NULL
  AND to_date(jdatat, 'DDMMYYYY') > CURRENT_DATE - INTERVAL '2 years';

-- Cœur : propriétaire hors commune -> RS, dans la commune -> RP.
-- PAS de comparaison voie/numéro (référentiels ccovoi non alignés -> faux RS).
UPDATE tp_classif SET proba_rprs = 'RS'
WHERE proba_rprs IS NULL
  AND teom_norm(dlign6) NOT LIKE ('%' || teom_norm(commune) || '%');

UPDATE tp_classif SET proba_rprs = 'RP'
WHERE proba_rprs IS NULL;

-- ============================================================================
-- 3ter) CALAGE INSEE -> proba_rprs_cal
--       Le NOMBRE de RS par commune vient de l'INSEE . le MAJIC ne sert
--       qu'à choisir QUELLES parcelles. Totaux communaux = recensement.
--
--       Table attendue : teom_data.insee_rs(insee text, nb_rs int)
--       Source : INSEE, recensement, "Logements par catégorie" (base-cc-logement) :
--         nb_rs = nombre de "Résidences secondaires et logements occasionnels".
--       Le code commune INSEE doit correspondre à request7.code_insee.
-- ============================================================================

-- Non-logements : on conserve le verdict de base (jamais RS).
UPDATE tp_classif SET proba_rprs_cal = proba_rprs
WHERE dteloc NOT IN ('Maison', 'Appartement');

-- Score d'appétence RS (plus haut = plus probablement résidence secondaire).
UPDATE tp_classif SET score =
      (CASE WHEN proba_rprs = 'RS' THEN 100 ELSE 0 END)                       -- hors commune
    + (CASE WHEN left(coalesce(ccopos::text,''),2) <> left(code_insee,2)
            THEN 10 ELSE 0 END)                                              -- hors département
WHERE dteloc IN ('Maison', 'Appartement');

-- Attribution des N premiers par commune (N = compte INSEE).
UPDATE tp_classif c
SET proba_rprs_cal = sub.verdict
FROM (
    SELECT invar,
           CASE WHEN row_number() OVER (PARTITION BY code_insee
                                        ORDER BY score DESC NULLS LAST, invar)
                     <= COALESCE(nb_rs, 0)
                THEN 'RS' ELSE 'RP' END AS verdict
    FROM (
        SELECT t.invar, t.code_insee, t.score, i.nb_rs
        FROM tp_classif t
        LEFT JOIN teom_data.insee_rs i ON i.insee = t.code_insee
        WHERE t.dteloc IN ('Maison', 'Appartement')
    ) z
) sub
WHERE c.invar = sub.invar;

-- Propagation des deux indicateurs vers le request7 complet
UPDATE request7 r
SET proba_rprs     = c.proba_rprs,
    proba_rprs_cal = c.proba_rprs_cal
FROM tp_classif c
WHERE r.invar = c.invar;

-- ============================================================================
-- 4) CALCULS TEOM
-- ============================================================================

UPDATE request7 SET tx_teom = 0;  -- taux fixe (modifiable si besoin)
UPDATE request7 SET mt_teom_ssfg = COALESCE(bateom,0) * COALESCE(tx_teom,0);
UPDATE request7 SET mt_teom_fg   = mt_teom_ssfg * 1.08;

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

-- ============================================================================
-- 5bis) MATÉRIALISATION PERSISTANTE POUR EXPORT
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS teom_export;
DROP TABLE IF EXISTS teom_export.request7_export;
CREATE TABLE teom_export.request7_export AS SELECT * FROM request7;

-- ============================================================================
-- 6) EXPORT FINAL - détail par commune (RS brute MAJIC ET RS calée INSEE)
-- ============================================================================
CREATE TABLE teom_export.type_locaux AS
WITH total AS (
    SELECT commune AS com, COUNT(DISTINCT invar) AS nb_total,
           SUM(bateom) AS base_total, SUM(mt_teom_ssfg) AS mt_total
    FROM request7 WHERE gdesip='1' GROUP BY commune
),
maison AS (
    SELECT commune AS com, COUNT(DISTINCT invar) AS nb_maison,
           SUM(bateom) AS base_maison, SUM(mt_teom_ssfg) AS mt_maison
    FROM request7 WHERE gdesip='1' AND dteloc='Maison' GROUP BY commune
),
appartement AS (
    SELECT commune AS com, COUNT(DISTINCT invar) AS nb_appartement,
           SUM(bateom) AS base_appartement, SUM(mt_teom_ssfg) AS mt_appartement
    FROM request7 WHERE gdesip='1' AND dteloc='Appartement' GROUP BY commune
),
dependance AS (
    SELECT commune AS com, COUNT(DISTINCT invar) AS nb_dependance,
           SUM(bateom) AS base_dependance, SUM(mt_teom_ssfg) AS mt_dependance
    FROM request7 WHERE gdesip='1' AND dteloc='Dépendances' GROUP BY commune
),
comind AS (
    SELECT commune AS com, COUNT(DISTINCT invar) AS nb_comind,
           SUM(bateom) AS base_comind, SUM(mt_teom_ssfg) AS mt_comind
    FROM request7 WHERE gdesip='1' AND dteloc='Local commercial ou industriel' GROUP BY commune
),
res_secondaire AS (   -- RS estimation MAJIC brute
    SELECT commune AS com, COUNT(DISTINCT invar) AS nb_res_secondaire,
           SUM(bateom) AS base_res_secondaire, SUM(mt_teom_ssfg) AS mt_res_secondaire
    FROM request7
    WHERE gdesip='1' AND proba_rprs='RS' AND dteloc IN ('Maison','Appartement')
    GROUP BY commune
),
res_secondaire_cal AS (   -- RS calée INSEE
    SELECT commune AS com, COUNT(DISTINCT invar) AS nb_res_secondaire_cal,
           SUM(bateom) AS base_res_secondaire_cal, SUM(mt_teom_ssfg) AS mt_res_secondaire_cal
    FROM request7
    WHERE gdesip='1' AND proba_rprs_cal='RS' AND dteloc IN ('Maison','Appartement')
    GROUP BY commune
)
SELECT *
FROM total t
LEFT JOIN maison m USING(com)
LEFT JOIN appartement a USING(com)
LEFT JOIN dependance d USING(com)
LEFT JOIN comind c USING(com)
LEFT JOIN res_secondaire rs USING(com)
LEFT JOIN res_secondaire_cal rsc USING(com);

-- ============================================================================
-- 7) EXPORT FINAL
-- ============================================================================
select code_insee, epci, commune, invar, p_parcelle, ccopre, ccosec, dnupla, dnubat, descr, dniv, dpor,
    pa_ccovoi, pa_ccoriv, pa_dnvoiri, pa_dindic, cconvo, dvoilib,
    comptecommunal, dteloc, cconlc, dnatlc, hlmsem, gimtom, gtauom, dcomrd,
    dnupev, ccoaff, ccthp, topcn, tpevtieom,
    bateom, baomec, mvltieomx,
    tx_teom, mt_teom_ssfg, mt_teom_fg,
    cconad, ccodro, gdesip, dnatpr, ccogrm, dforme,
    code_naf, section_naf,
    ddenom, dlign3, dlign4, dlign5, dlign6,
    pr_ccovoi, pr_ccoriv, pr_dnvoiri, pr_dindic, ccopos,
    dnomlp, dprnlp, dsiren, dformjur,
    dnbniv, jannat,
    ggazlc, gelelc, geaulc, dnbpdc, dsupdc, dmatgm, dmatto, detent,
    proba_rprs, proba_rprs_cal
FROM teom_export.request7_export;

select com, nb_total, base_total, mt_total, nb_maison, base_maison, mt_maison,
    nb_appartement, base_appartement, mt_appartement,
    nb_dependance, base_dependance, mt_dependance,
    nb_comind, base_comind, mt_comind,
    nb_res_secondaire, base_res_secondaire, mt_res_secondaire, nb_res_secondaire_cal, base_res_secondaire_cal, mt_res_secondaire_cal
FROM teom_export.type_locaux;

-- ============================================================================
-- CONTRÔLE QUALITÉ — MAJIC brut vs calé INSEE, par commune.
-- ============================================================================
-- SELECT commune,
--   COUNT(DISTINCT invar) FILTER (WHERE dteloc IN ('Maison','Appartement')
--                                   AND proba_rprs IN ('RP','RS'))      AS nb_logt,
--   COUNT(DISTINCT invar) FILTER (WHERE proba_rprs = 'RS')              AS rs_majic,
--   COUNT(DISTINCT invar) FILTER (WHERE proba_rprs_cal = 'RS')          AS rs_cale,
--   round(100.0*COUNT(DISTINCT invar) FILTER (WHERE proba_rprs='RS')
--         /NULLIF(COUNT(DISTINCT invar) FILTER (WHERE dteloc IN ('Maison','Appartement')),0),1) AS tx_majic,
--   round(100.0*COUNT(DISTINCT invar) FILTER (WHERE proba_rprs_cal='RS')
--         /NULLIF(COUNT(DISTINCT invar) FILTER (WHERE dteloc IN ('Maison','Appartement')),0),1) AS tx_cale
-- FROM teom_export.request7_export
-- WHERE gdesip='1'
-- GROUP BY commune
-- ORDER BY commune;

-- ============================================================================
-- 8) NETTOYAGE
-- ============================================================================
DROP FUNCTION IF EXISTS teom_norm(text);
DROP TABLE IF EXISTS tp_classif;
DROP TABLE IF EXISTS tp_nb_logt_proprio;
DROP SCHEMA IF EXISTS teom_export CASCADE;