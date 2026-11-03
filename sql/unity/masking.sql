-- Column masks and a row filter for the restricted zone.
-- These functions require Unity Catalog. They are not created by the local runtime.

CREATE SCHEMA IF NOT EXISTS acn_prod.governance;

CREATE OR REPLACE FUNCTION acn_prod.governance.mask_name(value STRING)
RETURN CASE
  WHEN is_account_group_member('acn-privacy-office') THEN value
  ELSE 'REDACTED'
END;

CREATE OR REPLACE FUNCTION acn_prod.governance.mask_address(value STRING)
RETURN CASE
  WHEN is_account_group_member('acn-privacy-office') THEN value
  ELSE 'REDACTED'
END;

CREATE OR REPLACE FUNCTION acn_prod.governance.facility_scope(facility_id STRING)
RETURN is_account_group_member('acn-privacy-office')
  OR is_account_group_member(concat('acn-facility-', lower(facility_id)));

ALTER TABLE acn_prod.restricted.golden_person ALTER COLUMN family_name SET MASK acn_prod.governance.mask_name;
ALTER TABLE acn_prod.restricted.golden_person ALTER COLUMN given_name SET MASK acn_prod.governance.mask_name;
ALTER TABLE acn_prod.restricted.golden_person ALTER COLUMN address_line SET MASK acn_prod.governance.mask_address;
ALTER TABLE acn_prod.restricted.golden_person ALTER COLUMN phone SET MASK acn_prod.governance.mask_name;

ALTER TABLE acn_prod.restricted.encounter SET ROW FILTER acn_prod.governance.facility_scope ON (facility_id);

GRANT USE CATALOG ON CATALOG acn_prod TO `acn-analysts`;
GRANT USE SCHEMA, SELECT ON SCHEMA acn_prod.deidentified TO `acn-analysts`;
GRANT USE SCHEMA, SELECT ON SCHEMA acn_prod.insight TO `acn-analysts`;
-- Analysts do not receive SELECT on acn_prod.restricted or acn_prod.capture.
