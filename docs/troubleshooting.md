# Troubleshooting

## Spark cannot find a Delta table after a crash

The local job deletes `data/lake`, `data/lake-work`, and `data/lake-checkpoints` at the start of a full run. If you interrupt a run, delete those three directories before retrying. A checkpoint without the Delta log, or a Delta log without the checkpoint, will disagree about what has been read.

## The second stream adds no rows

That is the intended checkpoint behavior. New files in the inbox are picked up. Files already committed in the checkpoint are not. To force a logical replay, delete the checkpoint and run again. Capture merges on `event_id`, so the row count stays stable.

## Everything in a backfill looks late

Lateness is measured against the watermark from the previous micro-batch, not against the oldest date inside the current file. A multi-month file is one batch. Only a later file whose event time is more than two hours behind that watermark is late. The delayed ALT in the demo is `2026-10-28 08:00:00` against a watermark of `2026-10-28 18:00:00`.

## Java and Ivy

PySpark 3.5.6 was run here on OpenJDK 21. CI uses Temurin 17. If the session fails before any Python log, set `JAVA_HOME` and `SPARK_LOCAL_IP=127.0.0.1`. If the error mentions `delta-spark_2.12`, the machine could not reach Maven. The jars land in `~/.ivy2`.

## `overwriteSchema` and dynamic partition overwrite

Delta refuses `overwriteSchema` together with dynamic partition overwrite. The local session does not enable dynamic partition overwrite. Do not turn that session flag on for this job.

## A golden name looks wrong

Survivorship prefers Alderbrook Medical Center for the legal name and the latest authoritative phone. An ORU PID is not authoritative. If you expected the lab message to rename someone, that is intentional.

## An SSN did not link two charts

Only 9-digit values starting with 9 are match keys. `123-45-6789` is stored as a soft failure and is not a deterministic key. Two different 900-series numbers are a review item (`ssn_conflict`), not a merge.

## Tokens do not match a teammate's lake

Tokens use `ACN_TOKEN_SALT`. The published demo salt is `local-dev-salt-not-for-production`. A different salt produces different `ssn_token` and `person_token` values. The enterprise id does not use the salt; it is a hash of the source keys.

## Birth-year typos never become a review

Blocking on Soundex plus birth year misses them. They are caught only when Soundex plus ZIP3 also matches. Two people who share a family name and nothing else will not be compared. That is a recall tradeoff, documented in `docs/engineering-decisions.md`.

## Bicep

`infra/bicep/main.bicep` compiled with Bicep 0.38.33. A warning about a hardcoded login host was removed by using `environment().authentication.loginEndpoint`. Deployment still needs a real tenant id, a unique suffix, and an Azure login. The CD workflow skips cleanly when those secrets are absent.

## Tests hang on Spark

Set `SPARK_LOCAL_IP=127.0.0.1` before pytest. One session-scoped Spark context is shared by the integration test. Do not call `spark.stop()` inside a test.
