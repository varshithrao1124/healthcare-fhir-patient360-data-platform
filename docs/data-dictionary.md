# Data dictionary

Classifications: **operational** (pipeline metadata), **restricted** (direct or quasi-identifiers, synthetic in this repo), **deidentified** (analytics projection).

## capture.events

Immutable ingress. Partition recommendation for a warehouse reload is `event_date, source_system`. The local merge table is compacted with OPTIMIZE rather than created as a partitioned sink, because the first writer is a streaming merge.

| Column | Type | Class | Description |
| --- | --- | --- | --- |
| event_id | string | operational | Transport id. Merge key. |
| source_system | string | operational | AMC, RGH, or CHO. Stamped by the sender. |
| payload_type | string | operational | HL7_V2, FHIR_R4, or FHIR_BULK |
| event_time | timestamp | operational | When the source emitted the envelope |
| event_date | date | operational | Date of event_time |
| ingest_time | timestamp | operational | When this process wrote the row |
| partition_id | int | operational | Event Hubs partition, or 0 for bulk |
| source_offset | long | operational | Offset within the partition |
| body | string | restricted | Raw HL7 or FHIR JSON |
| late | boolean | operational | True when the event time fell behind the prior watermark |
| source_file | string | operational | Landing file or `bulk-export` |

`capture.late_events` is the late subset, same columns. `capture.dead_letter` holds `event_id`, `source_system`, `payload_type`, `stage`, `reason`, `body_excerpt`, `ingest_time`. `capture.stream_state` holds the watermark (`query_name`, `max_event_time`, `updated_at`).

## interpret.person_snapshot

Latest authoritative registration per source person. Lab PID rows are kept in the revision stream and lose to ADT and FHIR Patient rows.

Restricted columns include `family_name`, `given_name`, `middle_name`, `birth_date`, `birth_date_raw`, `address_line`, `city`, `state`, `postal_code`, `phone`, and `ssn` (synthetic). Operational columns include `source_system`, `source_person_id` (MRN), `vendor_record_id`, `gender`, `facility_id`, `ehr_product`, `fhir_patient_id`, `demographic_authority`, `source_format`, `message_key`, `effective_time`, `event_id`, `ingest_time`.

## interpret.encounter

One row per source visit after A01 and A03 are folded together. `admit_time` is the earliest fragment. `discharge_time` is the latest. Status is finished when any fragment says so. `class_code` is IMP, AMB, or EMER.

## interpret.observation

Source-shaped result plus the crosswalk output: `loinc`, `loinc_display`, `map_status`, reference range, `abnormal_flag`, `value_numeric`.

## interpret.condition / medication / allergy

Source code, mapped `icd10` and `snomed` or `rxnorm`, display, status, and the person key. Conditions that do not map are not written to conform.

## interpret.practitioner / organization

`practitioner_id` values are synthetic (`SYNTH-PRAC-AMC` and kin), not national provider identifiers. Organizations are the three Alderbrook facilities.

## conform.person_crosswalk

| Column | Type | Description |
| --- | --- | --- |
| enterprise_person_id | string | Stable `EID-` plus 10 hex characters of the sorted member keys |
| source_system, source_person_id | string | Source chart |
| match_type | string | `deterministic_ssn`, `deterministic_demographic`, `probabilistic`, or `unmatched` |
| match_score | double | 1.0 for SSN, otherwise the pair score |
| cluster_size | long | Charts in the enterprise person |

## conform.review_queue

Pairs between 0.70 and 0.86, and SSN conflicts. Columns: `left_source`, `left_person_id`, `right_source`, `right_person_id`, `score`, `reason`.

## conform.golden_person

Restricted attributes after survivorship, plus `ssn_token` and `member_count`. There is no `ssn` column.

## conform.encounter / observation / condition / medication / allergy

The interpret columns that passed hard rules, plus `enterprise_person_id`. Observations also carry `map_status`. Unmapped labs remain here and are excluded from trends by a null LOINC.

## assure.quarantine

`rule_id`, `domain`, `source_system`, `record_key`, `detail`, `severity`.

## assure.scorecard

`source_system`, `domain`, `rule_id`, `failed`, `passed`, `evaluated`, `pass_rate`.

## insight.encounter_fact

`enterprise_person_id`, `source_system`, `source_encounter_id`, `class_code`, `status`, `admit_time`, `discharge_time`, `facility_id`, `los_days`, `is_30day_readmission`, `is_transfer`, `prior_encounter_id`.

A readmission is a later inpatient admission at least 24 hours and at most 720 hours after the previous inpatient discharge. Under 24 hours is `is_transfer`. The flag sits on the later stay.

## insight.lab_trend

LOINC-mapped results with `is_abnormal` and `persistent_abnormal` (this result and the prior result for the same person and LOINC are both abnormal).

## insight.chronic_cohort

`diabetes`, `hypertension`, `heart_failure`, `copd`, `asthma` as 0 or 1 per enterprise person. ICD-10 prefix or SNOMED concept.

## insight.care_gap

`gap_code` is `DM_NO_A1C_180D` (LOINC 4548-4) or `HTN_NO_SBP_365D` (LOINC 8480-6), plus `cohort` and `detail`.

## insight.timeline

`event_time`, `event_type` (`encounter`, `laboratory`, `condition`, `medication`), `summary`, `facility_id`, `source_system`.

## insight.source_completeness

Per source: `person_count`, `dob_rate`, `gender_rate`, `address_rate`, `observation_count`, `loinc_map_rate`, `encounter_count`. Computed on interpret rows, including rows that later fail a hard rule.

## insight.readmission_summary

`encounters`, `inpatient_encounters`, `readmissions`, `transfers`, `readmission_rate`.

## deidentified.encounter_fact

`person_token`, `age_band`, `gender`, `postal3`, `facility_id`, `class_code`, `admit_year`, `los_days`, `is_30day_readmission`, `is_transfer`.

`person_token` is the first 16 hex characters of SHA-256 over `salt|deid|enterprise_person_id`. Age band is 0-17, 18-44, 45-64, or 65+ at the as-of date. Full dates, names, street, phone, MRN, and the enterprise id are absent.

## deidentified.care_gap

`person_token`, `gap_code`, `cohort`.
