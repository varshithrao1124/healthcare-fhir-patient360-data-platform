"""Paths and thresholds for a local run or an Azure job."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

from acn_interop.platform.errors import ConfigError


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass
class Settings:
    profile: str
    as_of: date
    lake: Path
    work: Path
    checkpoint: Path
    evidence: Path | None
    reference_dir: Path
    salt: str
    allowed_lateness_hours: int
    auto_threshold: float
    review_threshold: float
    transport: str
    catalog: str | None = None

    @property
    def as_of_stamp(self) -> str:
        return datetime(self.as_of.year, self.as_of.month, self.as_of.day).strftime(
            "%Y-%m-%d %H:%M:%S"
        )


def load_settings(
    *,
    profile: str = "demo",
    lake: str | Path = "data/lake",
    evidence: str | Path | None = "evidence",
    config_path: str | Path | None = None,
) -> Settings:
    path = Path(config_path) if config_path else repo_root() / "configs" / "local.yml"
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    mpi = raw.get("mpi", {})
    salt_env = raw.get("token_salt_env", "ACN_TOKEN_SALT")
    salt = os.environ.get(salt_env) or raw.get("local_dev_salt")
    if not salt:
        raise ConfigError(
            f"Set {salt_env}. The local default lives in .env.example and is not a production secret."
        )
    as_of_text = os.environ.get("ACN_AS_OF") or raw.get("as_of", "2026-11-01")
    as_of = date.fromisoformat(str(as_of_text))
    lake_path = Path(lake)
    evidence_path = Path(evidence) if evidence else None
    return Settings(
        profile=profile,
        as_of=as_of,
        lake=lake_path,
        work=lake_path.parent / f"{lake_path.name}-work",
        checkpoint=lake_path.parent / f"{lake_path.name}-checkpoints",
        evidence=evidence_path,
        reference_dir=repo_root() / "reference" / "terminology",
        salt=salt,
        allowed_lateness_hours=int(raw.get("allowed_lateness_hours", 2)),
        auto_threshold=float(mpi.get("auto_threshold", 0.86)),
        review_threshold=float(mpi.get("review_threshold", 0.70)),
        transport=str(raw.get("transport", "file")),
        catalog=raw.get("catalog"),
    )
