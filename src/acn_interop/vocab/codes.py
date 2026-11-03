"""Lookup helpers and ICD-10 display normalization."""

from __future__ import annotations

import csv
import re
from pathlib import Path

RANGES = {
    "2345-7": (70.0, 99.0, "mg/dL"),
    "4548-4": (4.0, 5.6, "%"),
    "718-7": (12.0, 17.5, "g/dL"),
    "2823-3": (3.5, 5.1, "mmol/L"),
    "8480-6": (90.0, 120.0, "mm[Hg]"),
    "8462-4": (60.0, 80.0, "mm[Hg]"),
    "2160-0": (0.6, 1.3, "mg/dL"),
    "1742-6": (7.0, 56.0, "U/L"),
}

COHORTS = {
    "diabetes": {"icd_prefixes": ("E10", "E11"), "snomed": {"44054006"}},
    "hypertension": {"icd_prefixes": ("I10", "I11", "I12", "I13"), "snomed": {"38341003"}},
    "heart_failure": {"icd_prefixes": ("I50",), "snomed": {"84114007"}},
    "copd": {"icd_prefixes": ("J44",), "snomed": {"13645005"}},
    "asthma": {"icd_prefixes": ("J45",), "snomed": {"195967001"}},
}


def load_map(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def normalize_icd10(code: str | None) -> str | None:
    if not code:
        return None
    compact = code.strip().upper().replace(".", "")
    if re.fullmatch(r"[A-Z][0-9]{2}", compact):
        return compact
    if re.fullmatch(r"[A-Z][0-9][0-9A-Z][0-9A-Z]+", compact):
        return compact[:3] + "." + compact[3:]
    return code.strip().upper()


def lookup(rows: list[dict], source_system: str, local_code: str | None, value_field: str) -> str | None:
    if not local_code:
        return None
    specific = None
    generic = None
    for row in rows:
        if row.get("local_code") != local_code:
            continue
        if row.get("source_system") == source_system and row.get(value_field):
            specific = row[value_field]
        if row.get("source_system") == "*" and row.get(value_field):
            generic = row[value_field]
    return specific or generic
