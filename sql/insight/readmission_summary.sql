SELECT
  COUNT(*) AS encounters,
  SUM(CASE WHEN class_code = 'IMP' THEN 1 ELSE 0 END) AS inpatient_encounters,
  SUM(CASE WHEN is_30day_readmission THEN 1 ELSE 0 END) AS readmissions,
  SUM(CASE WHEN is_transfer THEN 1 ELSE 0 END) AS transfers,
  CASE
    WHEN SUM(CASE WHEN class_code = 'IMP' THEN 1 ELSE 0 END) = 0 THEN 0.0
    ELSE CAST(SUM(CASE WHEN is_30day_readmission THEN 1 ELSE 0 END) AS DOUBLE)
      / CAST(SUM(CASE WHEN class_code = 'IMP' THEN 1 ELSE 0 END) AS DOUBLE)
  END AS readmission_rate
FROM insight_encounter_fact
