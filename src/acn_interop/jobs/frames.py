"""Small dataframe helpers shared by the local job."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import (
    BooleanType,
    DateType,
    DoubleType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


def align(rows: list[dict], columns: list[str]) -> list[dict]:
    return [{column: row.get(column) for column in columns} for row in rows]


def infer_schema(rows: list[dict]) -> StructType:
    if not rows:
        raise ValueError("cannot infer a schema from an empty row set")
    fields = []
    for key in rows[0]:
        sample = next((row[key] for row in rows if row.get(key) is not None), None)
        if isinstance(sample, bool):
            spark_type = BooleanType()
        elif isinstance(sample, int):
            spark_type = LongType()
        elif isinstance(sample, float):
            spark_type = DoubleType()
        elif isinstance(sample, datetime):
            spark_type = TimestampType()
        elif isinstance(sample, date):
            spark_type = DateType()
        else:
            spark_type = StringType()
        fields.append(StructField(key, spark_type, True))
    return StructType(fields)


def to_frame(spark: SparkSession, rows: list[dict]) -> DataFrame | None:
    if not rows:
        return None
    tuples = [tuple(row[field.name] for field in infer_schema(rows).fields) for row in rows]
    return spark.createDataFrame(tuples, infer_schema(rows))


def write_delta(frame: DataFrame, path: Path, partitions: tuple[str, ...] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = frame.write.format("delta").mode("overwrite").option("overwriteSchema", "true")
    if partitions:
        writer = writer.partitionBy(*partitions)
    writer.save(str(path))


def read_delta(spark: SparkSession, path: Path) -> DataFrame | None:
    if not path.exists():
        return None
    return spark.read.format("delta").load(str(path))


def count_delta(spark: SparkSession, path: Path) -> int:
    frame = read_delta(spark, path)
    return 0 if frame is None else frame.count()
