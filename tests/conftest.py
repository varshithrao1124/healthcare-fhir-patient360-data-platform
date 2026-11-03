"""Shared fixtures. Spark starts once for the integration test."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from acn_interop.platform.spark_session import build_spark


@pytest.fixture(scope="session")
def spark():
    warehouse = Path(tempfile.mkdtemp(prefix="northline-wh-"))
    session = build_spark("northline-tests", warehouse)
    yield session
    session.stop()
    shutil.rmtree(warehouse, ignore_errors=True)
