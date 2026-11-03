WITH persons AS (
  SELECT
    source_system,
    COUNT(*) AS person_count,
    AVG(CASE WHEN birth_date IS NOT NULL THEN 1.0 ELSE 0.0 END) AS dob_rate,
    AVG(CASE WHEN gender IN ('M', 'F', 'O') THEN 1.0 ELSE 0.0 END) AS gender_rate,
    AVG(CASE WHEN address_line IS NOT NULL AND LENGTH(TRIM(address_line)) > 0 THEN 1.0 ELSE 0.0 END) AS address_rate
  FROM interpret_person
  GROUP BY source_system
),
observations AS (
  SELECT
    source_system,
    COUNT(*) AS observation_count,
    AVG(CASE WHEN loinc IS NOT NULL THEN 1.0 ELSE 0.0 END) AS loinc_map_rate
  FROM interpret_observation
  GROUP BY source_system
),
encounters AS (
  SELECT source_system, COUNT(*) AS encounter_count
  FROM interpret_encounter
  GROUP BY source_system
)
SELECT
  p.source_system,
  p.person_count,
  ROUND(p.dob_rate, 4) AS dob_rate,
  ROUND(p.gender_rate, 4) AS gender_rate,
  ROUND(p.address_rate, 4) AS address_rate,
  COALESCE(o.observation_count, 0) AS observation_count,
  ROUND(COALESCE(o.loinc_map_rate, 0.0), 4) AS loinc_map_rate,
  COALESCE(e.encounter_count, 0) AS encounter_count
FROM persons p
LEFT JOIN observations o ON p.source_system = o.source_system
LEFT JOIN encounters e ON p.source_system = e.source_system
