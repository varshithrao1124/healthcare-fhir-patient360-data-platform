"""Local metric sink plus a no-op hook for Azure Monitor."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path


class MetricSink:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.records: list[dict] = []
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, name: str, value: float, **tags: object) -> None:
        record = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "name": name,
            "value": value,
            "tags": {k: str(v) for k, v in tags.items()},
        }
        self.records.append(record)
        if self.path:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        _azure_monitor_hook(record)


def _azure_monitor_hook(record: dict) -> None:
    """Azure-only path. Local runs keep metrics in the JSONL sink.

    When APPLICATIONINSIGHTS_CONNECTION_STRING is set, a hosted job would
    forward `record` through the Azure Monitor OpenTelemetry exporter. This
    process does not open that connection.
    """
    if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return
