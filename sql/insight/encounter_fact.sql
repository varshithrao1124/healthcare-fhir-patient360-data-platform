WITH ip AS (
  SELECT *
  FROM conform_encounter
  WHERE class_code = 'IMP' AND admit_time IS NOT NULL
),
ordered AS (
  SELECT
    enterprise_person_id,
    source_system,
    source_encounter_id,
    class_code,
    admit_time,
    discharge_time,
    facility_id,
    status,
    LAG(discharge_time) OVER (
      PARTITION BY enterprise_person_id
      ORDER BY admit_time, source_encounter_id
    ) AS prev_discharge,
    LAG(source_encounter_id) OVER (
      PARTITION BY enterprise_person_id
      ORDER BY admit_time, source_encounter_id
    ) AS prev_encounter_id
  FROM ip
),
classified AS (
  SELECT
    enterprise_person_id,
    source_system,
    source_encounter_id,
    class_code,
    status,
    admit_time,
    discharge_time,
    facility_id,
    CASE
      WHEN discharge_time IS NOT NULL
      THEN CAST(timestampdiff(SECOND, admit_time, discharge_time) AS DOUBLE) / 86400.0
    END AS los_days,
    CASE
      WHEN prev_discharge IS NOT NULL
       AND timestampdiff(HOUR, prev_discharge, admit_time) >= 24
       AND timestampdiff(HOUR, prev_discharge, admit_time) <= 720
      THEN TRUE ELSE FALSE
    END AS is_30day_readmission,
    CASE
      WHEN prev_discharge IS NOT NULL
       AND timestampdiff(HOUR, prev_discharge, admit_time) >= 0
       AND timestampdiff(HOUR, prev_discharge, admit_time) < 24
      THEN TRUE ELSE FALSE
    END AS is_transfer,
    CASE
      WHEN prev_discharge IS NOT NULL
       AND timestampdiff(HOUR, prev_discharge, admit_time) >= 24
       AND timestampdiff(HOUR, prev_discharge, admit_time) <= 720
      THEN prev_encounter_id
    END AS prior_encounter_id
  FROM ordered
)
SELECT * FROM classified
UNION ALL
SELECT
  enterprise_person_id,
  source_system,
  source_encounter_id,
  class_code,
  status,
  admit_time,
  discharge_time,
  facility_id,
  CASE
    WHEN discharge_time IS NOT NULL
    THEN CAST(timestampdiff(SECOND, admit_time, discharge_time) AS DOUBLE) / 86400.0
  END AS los_days,
  FALSE AS is_30day_readmission,
  FALSE AS is_transfer,
  CAST(NULL AS STRING) AS prior_encounter_id
FROM conform_encounter
WHERE class_code <> 'IMP'
