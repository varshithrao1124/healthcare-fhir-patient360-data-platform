"""Source connectors for the capture stream.

Local runs read JSON envelopes from a directory, which stands in for Event Hubs.
The Kafka options match the Event Hubs Kafka endpoint and are executed only when
transport is `kafka` and the connection settings are present.
"""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import IntegerType, LongType, StringType, StructField, StructType

from acn_interop.platform.errors import ConfigError

ENVELOPE_SCHEMA = StructType(
    [
        StructField("event_id", StringType(), True),
        StructField("source_system", StringType(), True),
        StructField("payload_type", StringType(), True),
        StructField("event_time", StringType(), True),
        StructField("partition", IntegerType(), True),
        StructField("offset", LongType(), True),
        StructField("body", StringType(), True),
    ]
)


def file_stream(spark: SparkSession, inbox: str) -> DataFrame:
    return spark.readStream.schema(ENVELOPE_SCHEMA).option("maxFilesPerTrigger", 8).json(inbox)


def event_hubs_kafka_options(bootstrap: str, topic: str, connection_string: str) -> dict[str, str]:
    if not bootstrap or not topic or not connection_string:
        raise ConfigError(
            "Kafka transport needs EVENT_HUBS_BOOTSTRAP, EVENT_HUB_NAME, and EVENT_HUBS_CONNECTION_STRING"
        )
    jaas = (
        "kafkashaded.org.apache.kafka.common.security.plain.PlainLoginModule required "
        f'username="$ConnectionString" password="{connection_string}";'
    )
    return {
        "kafka.bootstrap.servers": bootstrap,
        "subscribe": topic,
        "startingOffsets": "earliest",
        "failOnDataLoss": "false",
        "kafka.security.protocol": "SASL_SSL",
        "kafka.sasl.mechanism": "PLAIN",
        "kafka.sasl.jaas.config": jaas,
    }


def kafka_stream(spark: SparkSession, options: dict[str, str]) -> DataFrame:
    """Build the Event Hubs source. The query is not started here."""
    return spark.readStream.format("kafka").options(**options).load()
