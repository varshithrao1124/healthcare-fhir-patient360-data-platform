SELECT
  enterprise_person_id,
  admit_time AS event_time,
  'encounter' AS event_type,
  CONCAT(class_code, ' ', COALESCE(status, '')) AS summary,
  facility_id,
  source_system
FROM conform_encounter
UNION ALL
SELECT
  enterprise_person_id,
  effective_time AS event_time,
  'laboratory' AS event_type,
  CONCAT(COALESCE(loinc_display, display, local_code, 'lab'), ' ', COALESCE(CAST(value_numeric AS STRING), '')) AS summary,
  source_system AS facility_id,
  source_system
FROM conform_observation
UNION ALL
SELECT
  enterprise_person_id,
  onset_time AS event_time,
  'condition' AS event_type,
  COALESCE(display, icd10, snomed, local_code) AS summary,
  source_system AS facility_id,
  source_system
FROM conform_condition
UNION ALL
SELECT
  enterprise_person_id,
  authored_time AS event_time,
  'medication' AS event_type,
  COALESCE(display, rxnorm, local_code) AS summary,
  source_system AS facility_id,
  source_system
FROM conform_medication
