WITH flags AS (
  SELECT
    enterprise_person_id,
    MAX(CASE WHEN icd10 LIKE 'E10%' OR icd10 LIKE 'E11%' OR snomed = '44054006' THEN 1 ELSE 0 END) AS diabetes,
    MAX(CASE WHEN icd10 LIKE 'I10%' OR icd10 LIKE 'I11%' OR icd10 LIKE 'I12%' OR icd10 LIKE 'I13%' OR snomed = '38341003' THEN 1 ELSE 0 END) AS hypertension,
    MAX(CASE WHEN icd10 LIKE 'I50%' OR snomed = '84114007' THEN 1 ELSE 0 END) AS heart_failure,
    MAX(CASE WHEN icd10 LIKE 'J44%' OR snomed = '13645005' THEN 1 ELSE 0 END) AS copd,
    MAX(CASE WHEN icd10 LIKE 'J45%' OR snomed = '195967001' THEN 1 ELSE 0 END) AS asthma
  FROM conform_condition
  GROUP BY enterprise_person_id
)
SELECT
  g.enterprise_person_id,
  COALESCE(f.diabetes, 0) AS diabetes,
  COALESCE(f.hypertension, 0) AS hypertension,
  COALESCE(f.heart_failure, 0) AS heart_failure,
  COALESCE(f.copd, 0) AS copd,
  COALESCE(f.asthma, 0) AS asthma
FROM conform_golden g
LEFT JOIN flags f
  ON g.enterprise_person_id = f.enterprise_person_id
