CREATE TEMP TABLE type_locaux AS
WITH total AS (
    SELECT commune AS com,
           COUNT(bateom) AS nb_total,
           SUM(bateom) AS base_total,
           SUM(mt_teom_ssfg) AS mt_total
    FROM request7
    WHERE gdesip = '1'
    GROUP BY commune
),
maison AS (
    SELECT commune AS com,
           COUNT(*) AS nb_maison,
           SUM(bateom) AS base_maison,
           SUM(mt_teom_ssfg) AS mt_maison
    FROM request7
    WHERE gdesip='1' AND dteloc='Maison'
    GROUP BY commune
),
appartement AS (
    SELECT commune AS com,
           COUNT(*) AS nb_appartement,
           SUM(bateom) AS base_appartement,
           SUM(mt_teom_ssfg) AS mt_appartement
    FROM request7
    WHERE gdesip='1' AND dteloc='Appartement'
    GROUP BY commune
),
dependance AS (
    SELECT commune AS com,
           COUNT(*) AS nb_dependance,
           SUM(bateom) AS base_dependance,
           SUM(mt_teom_ssfg) AS mt_dependance
    FROM request7
    WHERE gdesip='1' AND dteloc='Dépendances'
    GROUP BY commune
),
comind AS (
    SELECT commune AS com,
           COUNT(*) AS nb_comind,
           SUM(bateom) AS base_comind,
           SUM(mt_teom_ssfg) AS mt_comind
    FROM request7
    WHERE gdesip='1' AND dteloc='Local commercial ou industriel'
    GROUP BY commune
)
SELECT *
FROM total t
LEFT JOIN maison m USING(com)
LEFT JOIN appartement a USING(com)
LEFT JOIN dependance d USING(com)
LEFT JOIN comind c USING(com);

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
    ggazlc, gelelc, geaulc, dnbpdc, dsupdc, dmatgm, dmatto, detent
FROM request7;
select com, nb_total, base_total, mt_total, nb_maison, base_maison, mt_maison,
    nb_appartement, base_appartement, mt_appartement,
    nb_dependance, base_dependance, mt_dependance,
    nb_comind, base_comind, mt_comind
FROM type_locaux;