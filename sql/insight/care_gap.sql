SELECT
  c.enterprise_person_id,
  'DM_NO_A1C_180D' AS gap_code,
  'diabetes' AS cohort,
  'No HbA1c (LOINC 4548-4) with an effective time in the 180 days before the as-of date' AS detail
FROM conform_cohort c
WHERE c.diabetes = 1
  AND NOT EXISTS (
    SELECT 1
    FROM conform_observation o
    WHERE o.enterprise_person_id = c.enterprise_person_id
      AND o.loinc = '4548-4'
      AND o.effective_time >= timestamp '${as_of}' - INTERVAL 180 DAYS
      AND o.effective_time < timestamp '${as_of}'
  )
UNION ALL
SELECT
  c.enterprise_person_id,
  'HTN_NO_SBP_365D' AS gap_code,
  'hypertension' AS cohort,
  'No systolic blood pressure (LOINC 8480-6) in the 365 days before the as-of date' AS detail
FROM conform_cohort c
WHERE c.hypertension = 1
  AND NOT EXISTS (
    SELECT 1
    FROM conform_observation o
    WHERE o.enterprise_person_id = c.enterprise_person_id
      AND o.loinc = '8480-6'
      AND o.effective_time >= timestamp '${as_of}' - INTERVAL 365 DAYS
      AND o.effective_time < timestamp '${as_of}'
  )
