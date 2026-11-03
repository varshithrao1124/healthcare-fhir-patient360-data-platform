WITH base AS (
  SELECT
    enterprise_person_id,
    loinc,
    loinc_display,
    effective_time,
    value_numeric,
    value_unit,
    abnormal_flag,
    source_system,
    CASE
      WHEN abnormal_flag IN ('H', 'L', 'A', 'HH', 'LL') THEN TRUE
      WHEN value_numeric IS NOT NULL AND ref_low IS NOT NULL AND value_numeric < ref_low THEN TRUE
      WHEN value_numeric IS NOT NULL AND ref_high IS NOT NULL AND value_numeric > ref_high THEN TRUE
      ELSE FALSE
    END AS is_abnormal
  FROM conform_observation
  WHERE loinc IS NOT NULL
),
sequenced AS (
  SELECT
    *,
    LAG(CASE WHEN is_abnormal THEN 1 ELSE 0 END) OVER (
      PARTITION BY enterprise_person_id, loinc
      ORDER BY effective_time, loinc
    ) AS prev_abnormal
  FROM base
)
SELECT
  enterprise_person_id,
  loinc,
  loinc_display,
  effective_time,
  value_numeric,
  value_unit,
  abnormal_flag,
  source_system,
  is_abnormal,
  CASE WHEN is_abnormal AND prev_abnormal = 1 THEN TRUE ELSE FALSE END AS persistent_abnormal
FROM sequenced
