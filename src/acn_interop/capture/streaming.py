"""Structured Streaming capture with a watermark, late flags, and checkpointing.

Late clinical messages are retained. A lab that sat on an interface engine is
still a lab; it is flagged so operational dashboards can see delay without
dropping the result from Patient 360.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from acn_interop.capture.merge import merge_by_key
from acn_interop.capture.transports import ENVELOPE_SCHEMA, file_stream
from acn_interop.platform.log import get_logger

logger = get_logger("capture")

EVENT_COLUMNS = [
    "event_id",
    "source_system",
    "payload_type",
    "event_time",
    "event_date",
    "ingest_time",
    "partition_id",
    "source_offset",
    "body",
    "late",
    "source_file",
]


def run_file_stream(
    spark: SparkSession,
    inbox: Path,
    lake: Path,
    checkpoint: Path,
    *,
    allowed_lateness_hours: int,
) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    source = file_stream(spark, str(inbox))
    state_path = lake / "capture" / "stream_state"
    events_path = lake / "capture" / "events"
    late_path = lake / "capture" / "late_events"
    dead_path = lake / "capture" / "dead_letter"

    def handle(batch: DataFrame, epoch: int) -> None:
        if not batch.head(1):
            logger.info("capture epoch %s empty", epoch)
            return
        prepared = batch.withColumn("event_time_ts", F.to_timestamp("event_time", "yyyy-MM-dd HH:mm:ss"))
        prepared = prepared.withColumn("ingest_time", F.current_timestamp())
        prepared = prepared.withColumn("source_file", F.input_file_name())
        valid_predicate = (
            F.col("event_id").isNotNull()
            & F.col("event_time_ts").isNotNull()
            & F.col("body").isNotNull()
            & F.col("payload_type").isin("HL7_V2", "FHIR_R4")
        )
        invalid = prepared.filter(~valid_predicate)
        valid = prepared.filter(valid_predicate)
        _write_dead_letters(spark, invalid, dead_path, "capture-contract")
        if not valid.head(1):
            return
        watermark = _read_watermark(spark, state_path)
        flagged = _flag_late(valid, watermark, allowed_lateness_hours)
        events = flagged.select(
            F.col("event_id"),
            F.col("source_system"),
            F.col("payload_type"),
            F.col("event_time_ts").alias("event_time"),
            F.to_date("event_time_ts").alias("event_date"),
            F.col("ingest_time"),
            F.col("partition").cast("int").alias("partition_id"),
            F.col("offset").cast("long").alias("source_offset"),
            F.col("body"),
            F.col("late"),
            F.col("source_file"),
        )
        merge_by_key(spark, events, events_path, "event_id")
        late_rows = events.filter(F.col("late") == True)  # noqa: E712
        merge_by_key(spark, late_rows, late_path, "event_id")
        batch_max = events.agg(F.max("event_time")).collect()[0][0]
        _write_watermark(spark, state_path, batch_max, watermark)
        logger.info("capture epoch %s accepted rows with max event_time %s", epoch, batch_max)

    query = (
        source.writeStream.option("checkpointLocation", str(checkpoint))
        .foreachBatch(handle)
        .trigger(availableNow=True)
        .start()
    )
    query.awaitTermination()


def merge_bulk_events(spark: SparkSession, frame: DataFrame, lake: Path) -> int:
    return merge_by_key(spark, frame, lake / "capture" / "events", "event_id")


def _flag_late(frame: DataFrame, watermark: datetime | None, hours: int) -> DataFrame:
    if watermark is None:
        return frame.withColumn("late", F.lit(False))
    stamp = watermark.strftime("%Y-%m-%d %H:%M:%S")
    return frame.withColumn(
        "late",
        F.expr(f"event_time_ts < TIMESTAMP '{stamp}' - INTERVAL {int(hours)} HOURS"),
    )


def _read_watermark(spark: SparkSession, path: Path) -> datetime | None:
    if not path.exists():
        return None
    rows = spark.read.format("delta").load(str(path)).collect()
    if not rows:
        return None
    return rows[0]["max_event_time"]


def _write_watermark(spark: SparkSession, path: Path, batch_max: datetime, previous: datetime | None) -> None:
    if batch_max is None:
        return
    chosen = batch_max if previous is None or batch_max > previous else previous
    frame = spark.createDataFrame(
        [("clinical-ingress", chosen)],
        "query_name string, max_event_time timestamp",
    ).withColumn("updated_at", F.current_timestamp())
    frame.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(str(path))


def _write_dead_letters(spark: SparkSession, frame: DataFrame, path: Path, stage: str) -> None:
    if not frame.head(1):
        return
    letters = frame.select(
        F.coalesce(F.col("event_id"), F.lit("missing")).alias("event_id"),
        F.coalesce(F.col("source_system"), F.lit("UNKNOWN")).alias("source_system"),
        F.coalesce(F.col("payload_type"), F.lit("UNKNOWN")).alias("payload_type"),
        F.lit(stage).alias("stage"),
        F.lit("envelope failed the capture contract").alias("reason"),
        F.substring(F.coalesce(F.col("body"), F.lit("")), 1, 240).alias("body_excerpt"),
        F.col("ingest_time"),
    )
    letters.write.format("delta").mode("append").option("mergeSchema", "true").save(str(path))


def empty_events(spark: SparkSession) -> DataFrame:
    return spark.createDataFrame([], ENVELOPE_SCHEMA)
