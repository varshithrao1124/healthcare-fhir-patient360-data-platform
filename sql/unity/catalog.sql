-- Unity Catalog layout for Alderbrook Interop.
-- Apply in a Databricks workspace with a metastore. Not executed by the local Spark run.

CREATE CATALOG IF NOT EXISTS acn_prod;

CREATE SCHEMA IF NOT EXISTS acn_prod.capture
COMMENT 'Immutable HL7 and FHIR envelopes from Event Hubs and bulk export';

CREATE SCHEMA IF NOT EXISTS acn_prod.interpret
COMMENT 'Parsed segments and flattened resources, still source-shaped';

CREATE SCHEMA IF NOT EXISTS acn_prod.restricted
COMMENT 'Enterprise person and conformed clinical rows. Direct identifiers allowed for care coordination.';

CREATE SCHEMA IF NOT EXISTS acn_prod.insight
COMMENT 'Patient 360 measures computed before de-identification';

CREATE SCHEMA IF NOT EXISTS acn_prod.deidentified
COMMENT 'Analytics projection without direct identifiers';

CREATE SCHEMA IF NOT EXISTS acn_prod.assure
COMMENT 'Quarantine and source scorecards';

-- Liquid clustering matches the local ZORDER choice: person-scoped clinical access.
CREATE TABLE IF NOT EXISTS acn_prod.restricted.encounter (
  enterprise_person_id STRING,
  source_system STRING,
  source_encounter_id STRING,
  class_code STRING,
  status STRING,
  admit_time TIMESTAMP,
  discharge_time TIMESTAMP,
  facility_id STRING
)
CLUSTER BY (enterprise_person_id, admit_time);

CREATE TABLE IF NOT EXISTS acn_prod.insight.lab_trend (
  enterprise_person_id STRING,
  loinc STRING,
  effective_time TIMESTAMP,
  value_numeric DOUBLE,
  is_abnormal BOOLEAN,
  persistent_abnormal BOOLEAN,
  source_system STRING
)
CLUSTER BY (enterprise_person_id, loinc);
