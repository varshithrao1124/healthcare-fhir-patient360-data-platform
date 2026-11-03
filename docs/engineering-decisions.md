# Engineering decisions

## Lanes, not a medallion nickname

The hard problems in this feed are message interpretation, person identity, and vocabulary. Naming the storage tiers after those jobs makes the contracts obvious: capture is immutable, interpret is source-shaped, conform is mastered, insight is measured, and the de-identified mart is a separate grant. A generic three-layer nickname would hide which of those jobs a change belongs to.

## File layout

Code is split by that work (`capture`, `interpret`, `resolve`, `vocab`, `assure`, `shield`, `synthesize`) rather than by a layer package that imports its neighbors in a stack. Measure definitions live in `sql/insight` and are the statements the local job executes. Unity Catalog DDL is separate because it cannot run here.

## Streaming semantics

- Exactly-once for the bus means a merge on the transport `event_id`, plus a checkpoint.
- Clinical dedupe is a different key: source plus HL7 control id, or source plus FHIR type, id, and version.
- The watermark tracks the maximum event time committed by a previous micro-batch. The current batch cannot mark itself late.
- Late rows are retained and flagged. Dropping a late lab would be the wrong clinical default.
- Interpretation is a batch reconstruction of capture. It is replayable without another read of Event Hubs.

The local source is a directory of JSON envelopes. The Kafka reader for Event Hubs is a separate function so the security options are tested as data, not by opening a socket that does not exist here.

## Identity

Deterministic SSN and deterministic demographics outrank the probabilistic score. The SSN path accepts only the 900 range so a non-synthetic number cannot glue two charts together in this project.

Blocking is Soundex plus birth year, and Soundex plus ZIP3. On the demo population that reduced comparisons from 741 pairs to 8. The known miss is two people who share a family name and neither a year nor a ZIP3. Helen Cho is the opposite case: the year is wrong and the ZIP3 block still produces a review at 0.78.

The link step runs in the driver after blocking. The synthetic population is a few dozen charts. A regional production load should replace the driver union-find with a partitioned connected-components job. The scoring function and the thresholds would stay.

Survivorship is attribute-specific. Facility trust orders the legal name. The latest authoritative phone wins. Null does not overwrite a present value. ORU demographics are not authoritative because interface engines echo a stale PID.

Enterprise ids hash the sorted source keys. Rerunning the job, or listing members in another order, yields the same id. The salt is not part of that hash.

## Vocabulary

Crosswalks are tiny, so the join is broadcast. The physical plan in the local run contained a broadcast join; `broadcast_join_observed` in the demo metrics is true. A source-specific row wins over the generic `*` row. ICD-10 values are dotted (`E119` becomes `E11.9`) before the lookup.

Unmapped codes are a vocabulary queue. They are not forced into a hard clinical rule that would also drop a plausible result whose code we simply have not mapped yet. Trends require a LOINC, so the unmapped row cannot affect them.

## Measures before de-identification

Readmission and care gaps are computed on the conformed clocks. The de-identified mart keeps the flags, the length of stay, the admission year, an age band, and a ZIP3. It does not keep a date an analyst could use to recompute the window, because shifting dates and then re-measuring them would change who counts as a readmission. Year is the Safe Harbor-shaped compromise used here. This is not a certification of HIPAA compliance.

## Files and layout on disk

Conform tables are written partitioned by `source_system` so a facility replay can prune. The encounter table is then `OPTIMIZE ... ZORDER BY (enterprise_person_id)`. On the demo run that command took 1.525 seconds and left the file count at 3, because the table was already three small files. The command is still the right one once micro-batches create many files; this volume does not show a reduction, and the metrics say so.

Shuffle partitions are 4 in the local session. A Databricks job in the bundle turns on optimize-write and auto-compaction and sizes a small cluster. Liquid clustering is declared in `sql/unity/catalog.sql` for the warehouse form of the same person-scoped access. It was not executed.

## Reference ranges and abnormal flags

An HL7 reference range wins when the message carries one. Otherwise the LOINC default from `vocab/codes.py` is joined in. A missing abnormal flag is filled from that range. The plausible-bounds rule is a separate, wider gate so a unit error (glucose 4000) quarantines even when the lab's own reference range already says high.

## Clock

The as-of date is 2026-11-01 in configuration, not `today()`. Care-gap windows would move under a developer if the clock were the wall clock. The generator is seeded. Smoke and demo share the scripted story; demo only adds single-source filler charts.
