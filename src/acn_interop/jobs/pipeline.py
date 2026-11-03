"""Local Alderbrook Interop run: capture, interpret, resolve, conform, insight.

Streaming capture is incremental and idempotent. Interpretation is a batch
reconstruction from that immutable capture lane, so a checkpoint replay does
not mint a second clinical row.
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.functions import broadcast
from pyspark.sql.window import Window

from acn_interop.assure.checks import (
    encounter_violations,
    is_hard,
    observation_violations,
    person_violations,
    scorecard,
)
from acn_interop.capture.streaming import merge_bulk_events, run_file_stream
from acn_interop.interpret.fhir_extract import extract_fhir
from acn_interop.interpret.fhir_validate import validate_fhir
from acn_interop.interpret.hl7_extract import extract_hl7
from acn_interop.interpret.hl7_parser import parse_message
from acn_interop.interpret.hl7_validate import validate_hl7
from acn_interop.jobs.frames import align, count_delta, read_delta, to_frame, write_delta
from acn_interop.jobs.report import write_evidence
from acn_interop.platform.config import Settings, repo_root
from acn_interop.platform.errors import ParseError, PipelineError
from acn_interop.platform.log import get_logger
from acn_interop.platform.telemetry import MetricSink
from acn_interop.resolve.mpi import link_records
from acn_interop.shield.deid import identifier_columns
from acn_interop.shield.token import token
from acn_interop.synthesize.population import write_delayed, write_feeds
from acn_interop.vocab.codes import RANGES, load_map, normalize_icd10

logger = get_logger("pipeline")

PERSON_COLUMNS = [
    "source_system", "source_person_id", "vendor_record_id", "family_name", "given_name",
    "middle_name", "birth_date", "birth_date_raw", "gender", "address_line", "city", "state",
    "postal_code", "phone", "ssn", "facility_id", "ehr_product", "fhir_patient_id",
    "demographic_authority", "source_format", "message_key", "effective_time", "event_id", "ingest_time",
]
ENCOUNTER_COLUMNS = [
    "source_system", "source_encounter_id", "source_person_id", "fhir_patient_id", "class_code",
    "status", "admit_time", "discharge_time", "facility_id", "attending_id", "attending_family",
    "attending_given", "reason_text", "source_format", "message_key", "effective_time", "event_id",
    "ingest_time",
]
OBSERVATION_COLUMNS = [
    "source_system", "source_observation_id", "source_person_id", "fhir_patient_id",
    "source_encounter_id", "local_code", "local_system", "display", "value_numeric", "value_text",
    "value_unit", "ref_low", "ref_high", "abnormal_flag", "effective_time", "status", "source_format",
    "message_key", "event_id", "ingest_time",
]
CONDITION_COLUMNS = [
    "source_system", "source_condition_id", "source_person_id", "fhir_patient_id", "local_code",
    "local_system", "display", "clinical_status", "onset_time", "source_format", "message_key",
    "event_id", "ingest_time",
]
MEDICATION_COLUMNS = [
    "source_system", "source_medication_id", "source_person_id", "fhir_patient_id", "local_code",
    "local_system", "display", "status", "authored_time", "source_format", "message_key", "event_id",
    "ingest_time",
]
ALLERGY_COLUMNS = [
    "source_system", "source_allergy_id", "source_person_id", "fhir_patient_id", "substance",
    "criticality", "clinical_status", "source_format", "message_key", "effective_time", "event_id",
    "ingest_time",
]


def run_pipeline(spark: SparkSession, settings: Settings, feeds: dict) -> dict:
    started = time.perf_counter()
    GLOBAL_STATE.clear()
    BROADCAST_SEEN["value"] = False
    _reset(settings)
    sink = MetricSink(settings.evidence / "metrics.jsonl" if settings.evidence else None)
    timings: dict[str, float] = {}
    try:
        timings["land"] = _timed(lambda: _land(settings, feeds))
        timings["bulk"] = _timed(lambda: _load_bulk(spark, settings, feeds))
        timings["stream_backfill"] = _timed(lambda: _stream(spark, settings))
        write_delayed(feeds, settings.work / "inbox")
        timings["stream_delayed"] = _timed(lambda: _stream(spark, settings))
        interpreted = _timed_value(lambda: _interpret(spark, settings))
        timings["interpret"] = interpreted[0]
        fragments, dead_letters = interpreted[1]
        timings["conform"] = _timed(lambda: _conform(spark, settings, fragments, sink))
        timings["insight"] = _timed(lambda: _insight(spark, settings))
        optimize = _optimize(spark, settings)
        timings["optimize"] = optimize.get("seconds", 0.0)
        report = _report(spark, settings, feeds, timings, dead_letters, optimize, time.perf_counter() - started)
        sink.emit("alderbrook.capture.events", report["capture_events"])
        sink.emit("alderbrook.capture.late", report["late_events"])
        sink.emit("alderbrook.mpi.review_queue", report["review_queue"])
        sink.emit("alderbrook.assure.quarantine", report["quarantine_rows"])
        if settings.evidence:
            write_evidence(report, settings.evidence)
        return report
    except Exception as exc:
        raise PipelineError("alderbrook", str(exc)) from exc


def _reset(settings: Settings) -> None:
    for path in (settings.lake, settings.work, settings.checkpoint):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)


def _land(settings: Settings, feeds: dict) -> None:
    write_feeds(feeds, settings.work / "inbox", settings.work / "bulk")


def _stream(spark: SparkSession, settings: Settings) -> None:
    run_file_stream(
        spark,
        settings.work / "inbox",
        settings.lake,
        settings.checkpoint / "capture",
        allowed_lateness_hours=settings.allowed_lateness_hours,
    )


def _load_bulk(spark: SparkSession, settings: Settings, feeds: dict) -> None:
    rows = []
    for index, item in enumerate(feeds.get("bulk_index") or [], start=1):
        resource = item["resource"]
        version = ((resource.get("meta") or {}).get("versionId")) or "1"
        rows.append(
            {
                "event_id": f"bulk-{resource.get('resourceType')}-{resource.get('id')}-v{version}",
                "source_system": item["source_system"],
                "payload_type": "FHIR_BULK",
                "event_time": datetime.strptime(item["event_time"], "%Y-%m-%d %H:%M:%S"),
                "event_date": datetime.strptime(item["event_time"], "%Y-%m-%d %H:%M:%S").date(),
                "ingest_time": datetime.now(UTC).replace(tzinfo=None),
                "partition_id": 0,
                "source_offset": index,
                "body": json.dumps(resource),
                "late": False,
                "source_file": "bulk-export",
            }
        )
    frame = to_frame(spark, rows)
    if frame is not None:
        frame = frame.withColumn("partition_id", F.col("partition_id").cast("int")).withColumn(
            "source_offset", F.col("source_offset").cast("long")
        )
        merge_bulk_events(spark, frame, settings.lake)


def _interpret(spark: SparkSession, settings: Settings):
    events = read_delta(spark, settings.lake / "capture" / "events")
    if events is None:
        raise PipelineError("interpret", "capture lane is empty")
    buckets = {name: [] for name in (
        "persons", "encounters", "observations", "conditions", "medications", "allergies",
        "practitioners", "organizations",
    )}
    dead = []
    for row in events.collect():
        fragments, errors = _one_event(row.asDict(recursive=True))
        if errors:
            dead.append(
                {
                    "event_id": row.event_id,
                    "source_system": row.source_system or "UNKNOWN",
                    "payload_type": row.payload_type or "UNKNOWN",
                    "stage": "interpret",
                    "reason": "; ".join(errors)[:500],
                    "body_excerpt": (row.body or "")[:240],
                    "ingest_time": row.ingest_time,
                }
            )
            continue
        for name, items in fragments.items():
            buckets[name].extend(items)
    if dead:
        dead_frame = to_frame(spark, dead)
        if dead_frame is not None:
            dead_frame.write.format("delta").mode("append").option("mergeSchema", "true").save(
                str(settings.lake / "capture" / "dead_letter")
            )
    return _spark_fragments(spark, buckets), dead


def _one_event(row: dict):
    meta = {
        "event_id": row["event_id"],
        "source_system": row["source_system"],
        "event_time": row["event_time"],
        "ingest_time": row["ingest_time"],
    }
    try:
        if row["payload_type"] == "HL7_V2":
            message = parse_message(row["body"])
            errors = validate_hl7(message)
            facility = message.get("MSH", 4)
            if facility and facility != row["source_system"]:
                errors.append("MSH-4 does not match the envelope source")
            if errors:
                return None, errors
            return extract_hl7(message, meta), []
        resource = json.loads(row["body"])
        errors = validate_fhir(resource)
        if errors:
            return None, errors
        return extract_fhir(resource, meta), []
    except (ParseError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return None, [str(exc)]


def _spark_fragments(spark: SparkSession, buckets: dict) -> dict[str, DataFrame]:
    columns = {
        "persons": PERSON_COLUMNS,
        "encounters": ENCOUNTER_COLUMNS,
        "observations": OBSERVATION_COLUMNS,
        "conditions": CONDITION_COLUMNS,
        "medications": MEDICATION_COLUMNS,
        "allergies": ALLERGY_COLUMNS,
    }
    frames = {}
    for name, cols in columns.items():
        frame = to_frame(spark, align(buckets[name], cols))
        if frame is None:
            continue
        frames[name] = _dedupe(frame, "message_key")
    if "practitioners" in buckets and buckets["practitioners"]:
        frame = to_frame(spark, buckets["practitioners"])
        if frame is not None:
            frames["practitioners"] = frame.dropDuplicates(["source_system", "practitioner_id"])
    if buckets["organizations"]:
        frame = to_frame(spark, buckets["organizations"])
        if frame is not None:
            frames["organizations"] = frame.dropDuplicates(["organization_id"])
    if "persons" in frames:
        frames["person_index"] = _person_index(frames["persons"])
        frames["person_snapshot"] = _snapshot(frames["persons"])
    if "encounters" in frames and "person_index" in frames:
        frames["encounters"] = _aggregate_encounters(_resolve(frames["encounters"], frames["person_index"]))
    for name in ("observations", "conditions", "medications", "allergies"):
        if name in frames and "person_index" in frames:
            frames[name] = _resolve(frames[name], frames["person_index"])
    return frames


def _dedupe(frame: DataFrame, key: str) -> DataFrame:
    if "effective_time" in frame.columns:
        order = [F.col("effective_time").desc(), F.col("ingest_time").desc()]
    elif "onset_time" in frame.columns:
        order = [F.col("onset_time").desc(), F.col("ingest_time").desc()]
    elif "authored_time" in frame.columns:
        order = [F.col("authored_time").desc(), F.col("ingest_time").desc()]
    else:
        order = [F.col("ingest_time").desc()]
    window = Window.partitionBy(key).orderBy(*order)
    return frame.withColumn("_rn", F.row_number().over(window)).filter(F.col("_rn") == 1).drop("_rn")


def _snapshot(persons: DataFrame) -> DataFrame:
    window = Window.partitionBy("source_system", "source_person_id").orderBy(
        F.col("demographic_authority").desc(),
        F.col("effective_time").desc(),
        F.col("ingest_time").desc(),
    )
    return persons.withColumn("_rn", F.row_number().over(window)).filter(F.col("_rn") == 1).drop("_rn")


def _person_index(persons: DataFrame) -> DataFrame:
    indexed = persons.filter(F.col("fhir_patient_id").isNotNull()).select(
        F.col("source_system").alias("idx_source"),
        F.col("fhir_patient_id").alias("idx_fhir"),
        F.col("source_person_id").alias("idx_mrn"),
        F.col("effective_time").alias("idx_time"),
    )
    window = Window.partitionBy("idx_source", "idx_fhir").orderBy(F.col("idx_time").desc())
    return indexed.withColumn("_rn", F.row_number().over(window)).filter(F.col("_rn") == 1).drop("_rn", "idx_time")


def _resolve(frame: DataFrame, index: DataFrame) -> DataFrame:
    joined = frame.join(
        index,
        (frame["source_system"] == index["idx_source"]) & (frame["fhir_patient_id"] == index["idx_fhir"]),
        "left",
    )
    resolved = F.coalesce(frame["source_person_id"], F.col("idx_mrn"))
    return joined.withColumn("source_person_id", resolved).drop("idx_source", "idx_fhir", "idx_mrn")


def _aggregate_encounters(frame: DataFrame) -> DataFrame:
    window = Window.partitionBy("source_system", "source_encounter_id").orderBy(F.col("effective_time").desc())
    latest = frame.withColumn("_rn", F.row_number().over(window)).filter(F.col("_rn") == 1)
    aggregated = frame.groupBy("source_system", "source_encounter_id").agg(
        F.min("admit_time").alias("_admit"),
        F.max("discharge_time").alias("_discharge"),
        F.max(F.when(F.col("status") == "finished", F.lit(1)).otherwise(F.lit(0))).alias("_finished"),
    )
    latest = latest.drop("admit_time", "discharge_time", "status", "_rn")
    combined = latest.join(aggregated, ["source_system", "source_encounter_id"], "inner")
    return (
        combined.withColumn("admit_time", F.col("_admit"))
        .withColumn("discharge_time", F.col("_discharge"))
        .withColumn("status", F.when(F.col("_finished") == 1, F.lit("finished")).otherwise(F.lit("in-progress")))
        .drop("_admit", "_discharge", "_finished")
    )


def _conform(spark: SparkSession, settings: Settings, frames: dict, sink: MetricSink) -> None:
    lake = settings.lake
    persons = _dicts(frames.get("person_snapshot"))
    encounters = _dicts(frames.get("encounters"))
    observations = _map_vocabulary(spark, frames.get("observations"), settings, "lab")
    conditions = _map_vocabulary(spark, frames.get("conditions"), settings, "condition")
    medications = _map_vocabulary(spark, frames.get("medications"), settings, "medication")
    allergies = _dicts(frames.get("allergies"))
    violations = []
    quarantine = []
    clean_persons = []
    for row in persons:
        found = person_violations(row, settings.as_of)
        violations.extend(found)
        if is_hard(found):
            quarantine.extend(found)
        else:
            clean_persons.append(row)
    clean_encounters = []
    for row in encounters:
        found = encounter_violations(row)
        violations.extend(found)
        if is_hard(found):
            quarantine.extend(found)
        else:
            clean_encounters.append(row)
    clean_observations = []
    for row in observations:
        found = observation_violations(row)
        violations.extend(found)
        if row.get("map_status") == "unmapped":
            extra = {
                "rule_id": "VOC-UNMAPPED",
                "domain": "vocabulary",
                "source_system": row.get("source_system"),
                "record_key": f"{row.get('source_system')}|{row.get('source_observation_id')}",
                "detail": f"lab code {row.get('local_code')} is not on the LOINC crosswalk",
                "severity": "hard",
            }
            violations.append(extra)
            quarantine.append(extra)
        if is_hard(found):
            quarantine.extend(found)
        else:
            clean_observations.append(row)
    for row in conditions + medications:
        if row.get("map_status") == "unmapped":
            extra = {
                "rule_id": "VOC-UNMAPPED",
                "domain": "vocabulary",
                "source_system": row.get("source_system"),
                "record_key": row.get("local_code"),
                "detail": f"code {row.get('local_code')} is not on the standard crosswalk",
                "severity": "hard",
            }
            violations.append(extra)
            quarantine.append(extra)
    totals = {}
    for row in persons:
        totals[(row["source_system"], "person")] = totals.get((row["source_system"], "person"), 0) + 1
    for row in encounters:
        totals[(row["source_system"], "encounter")] = totals.get((row["source_system"], "encounter"), 0) + 1
    for row in observations:
        totals[(row["source_system"], "observation")] = totals.get((row["source_system"], "observation"), 0) + 1
        totals[(row["source_system"], "vocabulary")] = totals.get((row["source_system"], "vocabulary"), 0) + 1
    card = scorecard(violations, totals)
    linked = link_records(
        clean_persons,
        auto_threshold=settings.auto_threshold,
        review_threshold=settings.review_threshold,
    )
    golden = []
    for row in linked["golden"]:
        ssn_value = row.pop("ssn", None)
        row["ssn_token"] = token(ssn_value, settings.salt)
        golden.append(row)
    _write_rows(spark, golden, lake / "conform" / "golden_person")
    _write_rows(spark, linked["crosswalk"], lake / "conform" / "person_crosswalk")
    _write_rows(spark, linked["reviews"], lake / "conform" / "review_queue")
    crosswalk = to_frame(spark, linked["crosswalk"])
    _write_linked(spark, clean_encounters, crosswalk, lake / "conform" / "encounter", "source_encounter_id", quarantine)
    _write_linked(spark, clean_observations, crosswalk, lake / "conform" / "observation", "source_observation_id", quarantine)
    _write_linked(spark, [row for row in conditions if row.get("map_status") == "mapped"], crosswalk, lake / "conform" / "condition", "source_condition_id", quarantine)
    _write_linked(spark, [row for row in medications if row.get("map_status") == "mapped"], crosswalk, lake / "conform" / "medication", "source_medication_id", quarantine)
    _write_linked(spark, allergies, crosswalk, lake / "conform" / "allergy", "source_allergy_id", quarantine)
    _write_rows(spark, quarantine, lake / "assure" / "quarantine")
    _write_rows(spark, card, lake / "assure" / "scorecard")
    if frames.get("person_snapshot") is not None:
        write_delta(frames["person_snapshot"], lake / "interpret" / "person_snapshot", ("source_system",))
    if "observations" in frames:
        write_delta(_dicts_frame(spark, observations), lake / "interpret" / "observation", ("source_system",))
    if frames.get("encounters") is not None:
        write_delta(frames["encounters"], lake / "interpret" / "encounter", ("source_system",))
    if frames.get("practitioners") is not None:
        write_delta(frames["practitioners"], lake / "interpret" / "practitioner")
    if frames.get("organizations") is not None:
        write_delta(frames["organizations"], lake / "interpret" / "organization")
    spark.sparkContext.parallelize([1]).count()
    sink.emit("alderbrook.mpi.golden", linked["stats"]["golden_persons"])
    _conform_state(spark, linked, observations, card)


def _conform_state(spark, linked, observations, card) -> None:
    spark.sparkContext.setLocalProperty("alderbrook.crosswalk", str(len(linked["crosswalk"])))
    # Stored on the job object via a module global so the report can read MPI stats
    # without recomputing the match.
    GLOBAL_STATE["linked"] = linked
    GLOBAL_STATE["observations"] = observations
    GLOBAL_STATE["scorecard"] = card
    GLOBAL_STATE["broadcast"] = BROADCAST_SEEN["value"]


GLOBAL_STATE: dict = {}
BROADCAST_SEEN = {"value": False}


def _map_vocabulary(spark: SparkSession, frame: DataFrame | None, settings: Settings, kind: str) -> list[dict]:
    if frame is None:
        return []
    if kind == "lab":
        table = load_map(settings.reference_dir / "lab_crosswalk.csv")
        coded = _apply_lab_map(spark, frame, table)
    elif kind == "condition":
        table = load_map(settings.reference_dir / "condition_crosswalk.csv")
        coded = _apply_condition_map(spark, frame, table)
    else:
        table = load_map(settings.reference_dir / "medication_crosswalk.csv")
        coded = _apply_medication_map(spark, frame, table)
    return _dicts(coded)


def _apply_lab_map(spark: SparkSession, frame: DataFrame, rows: list[dict]) -> DataFrame:
    specific, generic = _map_frames(spark, rows, "loinc")
    joined = (
        frame.alias("o")
        .join(
            broadcast(specific.alias("s")),
            (F.col("o.source_system") == F.col("s.map_source")) & (F.col("o.local_code") == F.col("s.map_code")),
            "left",
        )
        .join(broadcast(generic.alias("g")), F.col("o.local_code") == F.col("g.map_code"), "left")
    )
    plan = joined._jdf.queryExecution().executedPlan().toString()
    BROADCAST_SEEN["value"] = BROADCAST_SEEN["value"] or ("Broadcast" in plan)
    ranges = spark.createDataFrame(
        [(code, low, high, unit) for code, (low, high, unit) in RANGES.items()],
        "range_loinc string, range_low double, range_high double, range_unit string",
    )
    coded = joined.select(
        *[F.col(f"o.{column}") for column in frame.columns],
        F.coalesce(F.col("s.loinc"), F.col("g.loinc")).alias("loinc"),
        F.coalesce(F.col("s.display"), F.col("g.display")).alias("loinc_display"),
    )
    coded = coded.join(broadcast(ranges), coded.loinc == ranges.range_loinc, "left")
    return (
        coded.withColumn("ref_low", F.coalesce(F.col("ref_low"), F.col("range_low")))
        .withColumn("ref_high", F.coalesce(F.col("ref_high"), F.col("range_high")))
        .withColumn("value_unit", F.coalesce(F.col("value_unit"), F.col("range_unit")))
        .withColumn(
            "abnormal_flag",
            F.when(F.col("abnormal_flag").isNotNull() & (F.length(F.col("abnormal_flag")) > 0), F.col("abnormal_flag"))
            .when(F.col("value_numeric") > F.col("ref_high"), F.lit("H"))
            .when(F.col("value_numeric") < F.col("ref_low"), F.lit("L"))
            .otherwise(F.col("abnormal_flag")),
        )
        .withColumn("map_status", F.when(F.col("loinc").isNull(), F.lit("unmapped")).otherwise(F.lit("mapped")))
        .drop("range_loinc", "range_low", "range_high", "range_unit")
    )


def _apply_condition_map(spark: SparkSession, frame: DataFrame, rows: list[dict]) -> DataFrame:
    normalized = frame.withColumn("lookup_code", F.udf(normalize_icd10, "string")(F.col("local_code")))
    specific, generic = _map_frames(spark, rows, "icd10", extra=["snomed"])
    joined = (
        normalized.alias("o")
        .join(
            broadcast(specific.alias("s")),
            (F.col("o.source_system") == F.col("s.map_source")) & (F.col("o.lookup_code") == F.col("s.map_code")),
            "left",
        )
        .join(broadcast(generic.alias("g")), F.col("o.lookup_code") == F.col("g.map_code"), "left")
    )
    plan = joined._jdf.queryExecution().executedPlan().toString()
    BROADCAST_SEEN["value"] = BROADCAST_SEEN["value"] or ("Broadcast" in plan)
    return joined.select(
        *[F.col(f"o.{column}") for column in normalized.columns if column != "lookup_code"],
        F.coalesce(F.col("s.icd10"), F.col("g.icd10")).alias("icd10"),
        F.coalesce(F.col("s.snomed"), F.col("g.snomed")).alias("snomed"),
        F.coalesce(F.col("s.display"), F.col("g.display"), F.col("o.display")).alias("standard_display"),
    ).withColumn(
        "map_status",
        F.when(F.col("icd10").isNull() & F.col("snomed").isNull(), F.lit("unmapped")).otherwise(F.lit("mapped")),
    ).withColumn("display", F.coalesce(F.col("standard_display"), F.col("display"))).drop("standard_display")


def _apply_medication_map(spark: SparkSession, frame: DataFrame, rows: list[dict]) -> DataFrame:
    specific, generic = _map_frames(spark, rows, "rxnorm")
    joined = (
        frame.alias("o")
        .join(
            broadcast(specific.alias("s")),
            (F.col("o.source_system") == F.col("s.map_source")) & (F.col("o.local_code") == F.col("s.map_code")),
            "left",
        )
        .join(broadcast(generic.alias("g")), F.col("o.local_code") == F.col("g.map_code"), "left")
    )
    return joined.select(
        *[F.col(f"o.{column}") for column in frame.columns],
        F.coalesce(F.col("s.rxnorm"), F.col("g.rxnorm")).alias("rxnorm"),
        F.coalesce(F.col("s.display"), F.col("g.display"), F.col("o.display")).alias("standard_display"),
    ).withColumn(
        "map_status",
        F.when(F.col("rxnorm").isNull(), F.lit("unmapped")).otherwise(F.lit("mapped")),
    ).withColumn("display", F.coalesce(F.col("standard_display"), F.col("display"))).drop("standard_display")


def _map_frames(spark: SparkSession, rows: list[dict], value_field: str, extra: list[str] | None = None):
    extra = extra or []
    specific_rows = []
    generic_rows = []
    for row in rows:
        if not row.get(value_field) and not any(row.get(column) for column in extra):
            continue
        payload = {
            "map_source": row["source_system"],
            "map_code": row["local_code"],
            value_field: row.get(value_field) or None,
            "display": row.get("display") or None,
        }
        for column in extra:
            payload[column] = row.get(column) or None
        if row["source_system"] == "*":
            generic_rows.append(payload)
        else:
            specific_rows.append(payload)
    return _nonempty_map(spark, specific_rows, value_field, extra), _nonempty_map(spark, generic_rows, value_field, extra)


def _nonempty_map(spark, rows, value_field, extra):
    columns = ["map_source", "map_code", value_field, "display", *extra]
    if not rows:
        rows = [{column: None for column in columns}]
    return to_frame(spark, [{column: row.get(column) for column in columns} for row in rows])


def _write_linked(spark, rows, crosswalk, path, key_name, quarantine) -> None:
    frame = to_frame(spark, rows)
    if frame is None or crosswalk is None:
        return
    keys = crosswalk.select("source_system", "source_person_id", "enterprise_person_id")
    joined = frame.join(keys, ["source_system", "source_person_id"], "left")
    kept = joined.filter(F.col("enterprise_person_id").isNotNull())
    missing = joined.filter(F.col("enterprise_person_id").isNull())
    for row in missing.select("source_system", key_name).collect():
        quarantine.append(
            {
                "rule_id": "ID-UNLINKED",
                "domain": "identity",
                "source_system": row["source_system"],
                "record_key": f"{row['source_system']}|{row[key_name]}",
                "detail": "clinical row has no enterprise person",
                "severity": "hard",
            }
        )
    if kept.head(1):
        write_delta(kept, path, ("source_system",))


def _insight(spark: SparkSession, settings: Settings) -> None:
    lake = settings.lake
    _view(spark, lake / "conform" / "encounter", "conform_encounter")
    _view(spark, lake / "conform" / "observation", "conform_observation")
    _view(spark, lake / "conform" / "condition", "conform_condition")
    _view(spark, lake / "conform" / "medication", "conform_medication")
    _view(spark, lake / "conform" / "golden_person", "conform_golden")
    _view(spark, lake / "interpret" / "person_snapshot", "interpret_person")
    _view(spark, lake / "interpret" / "observation", "interpret_observation")
    _view(spark, lake / "interpret" / "encounter", "interpret_encounter")
    encounter_fact = _sql(spark, "encounter_fact.sql", settings)
    write_delta(encounter_fact, lake / "insight" / "encounter_fact")
    encounter_fact.createOrReplaceTempView("insight_encounter_fact")
    write_delta(_sql(spark, "lab_trend.sql", settings), lake / "insight" / "lab_trend")
    cohort = _sql(spark, "chronic_cohort.sql", settings)
    write_delta(cohort, lake / "insight" / "chronic_cohort")
    cohort.createOrReplaceTempView("conform_cohort")
    write_delta(_sql(spark, "care_gap.sql", settings), lake / "insight" / "care_gap")
    write_delta(_sql(spark, "timeline.sql", settings), lake / "insight" / "timeline")
    write_delta(_sql(spark, "source_completeness.sql", settings), lake / "insight" / "source_completeness")
    summary = _sql(spark, "readmission_summary.sql", settings)
    write_delta(summary, lake / "insight" / "readmission_summary")
    _write_deid(spark, settings)


def _write_deid(spark: SparkSession, settings: Settings) -> None:
    as_of = settings.as_of_stamp
    salt = settings.salt.replace("'", "")
    frame = spark.sql(
        f"""
        SELECT
          lower(substring(sha2(concat('{salt}', '|deid|', f.enterprise_person_id), 256), 1, 16)) AS person_token,
          CASE
            WHEN g.birth_date IS NULL THEN 'unknown'
            WHEN timestampdiff(YEAR, g.birth_date, timestamp '{as_of}') < 18 THEN '0-17'
            WHEN timestampdiff(YEAR, g.birth_date, timestamp '{as_of}') < 45 THEN '18-44'
            WHEN timestampdiff(YEAR, g.birth_date, timestamp '{as_of}') < 65 THEN '45-64'
            ELSE '65+'
          END AS age_band,
          g.gender,
          substring(regexp_replace(coalesce(g.postal_code, ''), '[^0-9]', ''), 1, 3) AS postal3,
          f.facility_id,
          f.class_code,
          year(f.admit_time) AS admit_year,
          f.los_days,
          f.is_30day_readmission,
          f.is_transfer
        FROM insight_encounter_fact f
        JOIN conform_golden g ON f.enterprise_person_id = g.enterprise_person_id
        """
    )
    write_delta(frame, settings.lake / "deidentified" / "encounter_fact")
    gaps = spark.sql(
        f"""
        SELECT
          lower(substring(sha2(concat('{salt}', '|deid|', c.enterprise_person_id), 256), 1, 16)) AS person_token,
          c.gap_code,
          c.cohort
        FROM delta.`{settings.lake / "insight" / "care_gap"}` c
        """
    )
    write_delta(gaps, settings.lake / "deidentified" / "care_gap")


def _report(spark, settings, feeds, timings, dead_letters, optimize, elapsed) -> dict:
    linked = GLOBAL_STATE.get("linked", {})
    stats = linked.get("stats", {})
    crosswalk = linked.get("crosswalk", [])
    match_counts: dict[str, int] = {}
    for row in crosswalk:
        match_counts[row["match_type"]] = match_counts.get(row["match_type"], 0) + 1
    summary_frame = read_delta(spark, settings.lake / "insight" / "readmission_summary")
    summary = summary_frame.collect()[0].asDict() if summary_frame is not None and summary_frame.head(1) else {}
    summary = {key: _plain(value) for key, value in summary.items()}
    gaps = read_delta(spark, settings.lake / "insight" / "care_gap")
    gap_counts: dict[str, int] = {}
    if gaps is not None:
        for row in gaps.groupBy("gap_code").count().collect():
            gap_counts[row["gap_code"]] = int(row["count"])
    completeness = read_delta(spark, settings.lake / "insight" / "source_completeness")
    completeness_rows = [row.asDict() for row in completeness.collect()] if completeness is not None else []
    completeness_rows = [{key: _plain(value) for key, value in row.items()} for row in completeness_rows]
    deid = read_delta(spark, settings.lake / "deidentified" / "encounter_fact")
    leaked = identifier_columns(deid.columns) if deid is not None else ["missing"]
    card = GLOBAL_STATE.get("scorecard", [])
    by_source: dict[str, list[float]] = {}
    for row in card:
        by_source.setdefault(row["source_system"], []).append(row["pass_rate"])
    pass_rates = {source: round(sum(values) / len(values), 4) for source, values in by_source.items()}
    cohort = read_delta(spark, settings.lake / "insight" / "chronic_cohort")
    chronic = {}
    if cohort is not None:
        chronic = cohort.agg(
            F.sum("diabetes").alias("diabetes"),
            F.sum("hypertension").alias("hypertension"),
            F.sum("heart_failure").alias("heart_failure"),
            F.sum("copd").alias("copd"),
            F.sum("asthma").alias("asthma"),
        ).collect()[0].asDict()
        chronic = {key: int(value or 0) for key, value in chronic.items()}
    replay_ids = [row.get("event_id") for row in feeds["backfill"] if row.get("event_id")]
    duplicate_replays = len(replay_ids) - len(set(replay_ids))
    return {
        "profile": settings.profile,
        "as_of": settings.as_of.isoformat(),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spark_version": spark.version,
        "timings_seconds": {key: round(value, 3) for key, value in timings.items()} | {"total": round(elapsed, 3)},
        "capture_events": count_delta(spark, settings.lake / "capture" / "events"),
        "late_events": count_delta(spark, settings.lake / "capture" / "late_events"),
        "dead_letters": count_delta(spark, settings.lake / "capture" / "dead_letter"),
        "interpret_dead_letters": len(dead_letters),
        "duplicate_transport_replays": duplicate_replays,
        "source_persons": stats.get("source_persons", 0),
        "golden_persons": stats.get("golden_persons", 0),
        "pairs_compared": stats.get("pairs_compared", 0),
        "possible_pairs": stats.get("possible_pairs", 0),
        "auto_edges": stats.get("auto_edges", 0),
        "review_queue": stats.get("review_edges", 0),
        "match_type_counts": match_counts,
        "quarantine_rows": count_delta(spark, settings.lake / "assure" / "quarantine"),
        "scorecard_mean_pass_rate_by_source": pass_rates,
        "care_gap_counts": gap_counts,
        "chronic_counts": chronic,
        "readmission_summary": summary,
        "completeness": completeness_rows,
        "broadcast_join_observed": GLOBAL_STATE.get("broadcast", False),
        "deid_identifier_columns": leaked,
        "optimize": optimize,
        "insight_counts": {
            "encounter_fact": count_delta(spark, settings.lake / "insight" / "encounter_fact"),
            "lab_trend": count_delta(spark, settings.lake / "insight" / "lab_trend"),
            "timeline": count_delta(spark, settings.lake / "insight" / "timeline"),
            "care_gap": count_delta(spark, settings.lake / "insight" / "care_gap"),
        },
    }


def _optimize(spark: SparkSession, settings: Settings) -> dict:
    path = settings.lake / "conform" / "encounter"
    if not path.exists():
        return {"ran": False, "reason": "encounter table missing"}
    detail = spark.sql(f"DESCRIBE DETAIL delta.`{path}`").collect()[0]
    started = time.perf_counter()
    try:
        spark.sql(f"OPTIMIZE delta.`{path}` ZORDER BY (enterprise_person_id)")
    except Exception as exc:
        return {"ran": False, "reason": str(exc), "before_files": int(detail["numFiles"])}
    after = spark.sql(f"DESCRIBE DETAIL delta.`{path}`").collect()[0]
    return {
        "ran": True,
        "table": "conform/encounter",
        "zorder": ["enterprise_person_id"],
        "before_files": int(detail["numFiles"]),
        "after_files": int(after["numFiles"]),
        "before_bytes": int(detail["sizeInBytes"]),
        "after_bytes": int(after["sizeInBytes"]),
        "seconds": round(time.perf_counter() - started, 3),
    }


def _view(spark, path: Path, name: str) -> None:
    frame = read_delta(spark, path)
    if frame is None:
        raise PipelineError(name, f"required table {path} was not written")
    frame.createOrReplaceTempView(name)


def _sql(spark, name: str, settings: Settings):
    text = (repo_root() / "sql" / "insight" / name).read_text(encoding="utf-8")
    text = text.replace("${as_of}", settings.as_of_stamp)
    return spark.sql(text)


def _dicts(frame: DataFrame | None) -> list[dict]:
    if frame is None:
        return []
    return [row.asDict(recursive=True) for row in frame.collect()]


def _dicts_frame(spark, rows: list[dict]) -> DataFrame:
    frame = to_frame(spark, rows)
    if frame is None:
        raise PipelineError("interpret", "observation frame disappeared")
    return frame


def _write_rows(spark, rows: list[dict], path: Path) -> None:
    frame = to_frame(spark, rows)
    if frame is not None:
        write_delta(frame, path)


def _plain(value):
    if isinstance(value, Decimal):
        return round(float(value), 4)
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    return value


def _timed(fn) -> float:
    started = time.perf_counter()
    fn()
    return time.perf_counter() - started


def _timed_value(fn):
    started = time.perf_counter()
    value = fn()
    return time.perf_counter() - started, value
