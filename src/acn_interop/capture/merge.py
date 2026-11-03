"""Idempotent Delta merges used by streaming micro-batches and bulk replay."""

from __future__ import annotations

from pathlib import Path

from delta.tables import DeltaTable
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.window import Window

from acn_interop.platform.retry import with_retry


def merge_by_key(spark: SparkSession, frame: DataFrame, path: str | Path, key: str = "event_id") -> int:
    destination = str(path)
    incoming = _dedupe(frame, key)
    count = incoming.count()
    if count == 0:
        return 0

    def _write() -> None:
        if not DeltaTable.isDeltaTable(spark, destination):
            incoming.write.format("delta").mode("overwrite").option("overwriteSchema", "true").save(destination)
            return
        target = DeltaTable.forPath(spark, destination)
        (
            target.alias("t")
            .merge(incoming.alias("s"), f"t.{key} = s.{key}")
            .whenMatchedUpdateAll()
            .whenNotMatchedInsertAll()
            .execute()
        )

    with_retry(_write, attempts=3, base_seconds=0.1, exceptions=(OSError, TimeoutError))
    return count


def _dedupe(frame: DataFrame, key: str) -> DataFrame:
    if "ingest_time" in frame.columns:
        order = F.col("ingest_time").desc()
    else:
        order = F.lit(1)
    window = Window.partitionBy(key).orderBy(order)
    return frame.withColumn("_rn", F.row_number().over(window)).filter(F.col("_rn") == 1).drop("_rn")
