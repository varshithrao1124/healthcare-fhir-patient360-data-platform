"""Row-level clinical data-quality rules.

Hard rules keep a row out of the conformed model. Soft rules stay on the
scorecard and still flow forward.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

KNOWN_GENDER = {"M", "F", "O", "U"}
PLAUSIBLE = {
    "2345-7": (20, 2000),
    "2823-3": (1, 10),
    "4548-4": (3, 20),
    "718-7": (3, 25),
    "8480-6": (50, 300),
    "8462-4": (30, 200),
    "2160-0": (0.1, 30),
    "1742-6": (0, 5000),
}

HARD_RULES = {
    "PER-NAME",
    "PER-DOB-FUTURE",
    "PER-DOB-INVALID",
    "PER-GENDER-INVALID",
    "ENC-ADMIT-MISSING",
    "ENC-DISCHARGE-ORDER",
    "ENC-PERSON-MISSING",
    "OBS-CODE-MISSING",
    "OBS-IMPLAUSIBLE",
    "OBS-PERSON-MISSING",
}


def _violation(rule_id: str, domain: str, source: str, record_key: str, detail: str) -> dict:
    return {
        "rule_id": rule_id,
        "domain": domain,
        "source_system": source,
        "record_key": record_key,
        "detail": detail,
        "severity": "hard" if rule_id in HARD_RULES else "soft",
    }


def person_violations(row: dict, as_of: date) -> list[dict]:
    key = f"{row.get('source_system')}|{row.get('source_person_id')}"
    source = row.get("source_system") or "UNKNOWN"
    found = []
    if not row.get("family_name") or not row.get("given_name"):
        found.append(_violation("PER-NAME", "person", source, key, "family and given name are required"))
    raw = row.get("birth_date_raw")
    parsed = row.get("birth_date")
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if not raw:
        found.append(_violation("PER-DOB-MISSING", "person", source, key, "birth date is absent"))
    elif len(digits) == 4:
        found.append(_violation("PER-DOB-PRECISION", "person", source, key, "birth date has year precision only"))
    elif parsed is None:
        found.append(_violation("PER-DOB-INVALID", "person", source, key, f"birth date {raw} is not a full date"))
    elif parsed > as_of:
        found.append(_violation("PER-DOB-FUTURE", "person", source, key, "birth date is after the as-of date"))
    gender = (row.get("gender") or "").upper()
    if gender not in KNOWN_GENDER:
        found.append(_violation("PER-GENDER-INVALID", "person", source, key, f"gender {gender} is outside M/F/O/U"))
    if not row.get("address_line"):
        found.append(_violation("PER-ADDRESS-MISSING", "person", source, key, "street address is absent"))
    ssn = "".join(ch for ch in str(row.get("ssn") or "") if ch.isdigit())
    if row.get("ssn") and not (len(ssn) == 9 and ssn.startswith("9")):
        found.append(_violation("PER-SSN-NOT-SYNTHETIC", "person", source, key, "identifier is not in the synthetic 900 range"))
    return found


def encounter_violations(row: dict) -> list[dict]:
    key = f"{row.get('source_system')}|{row.get('source_encounter_id')}"
    source = row.get("source_system") or "UNKNOWN"
    found = []
    if row.get("admit_time") is None:
        found.append(_violation("ENC-ADMIT-MISSING", "encounter", source, key, "admit time is absent"))
    admit, discharge = row.get("admit_time"), row.get("discharge_time")
    if isinstance(admit, datetime) and isinstance(discharge, datetime) and discharge < admit:
        found.append(_violation("ENC-DISCHARGE-ORDER", "encounter", source, key, "discharge precedes admit"))
    if not row.get("source_person_id"):
        found.append(_violation("ENC-PERSON-MISSING", "encounter", source, key, "encounter has no person key"))
    return found


def observation_violations(row: dict) -> list[dict]:
    key = f"{row.get('source_system')}|{row.get('source_observation_id')}"
    source = row.get("source_system") or "UNKNOWN"
    found = []
    if not row.get("local_code"):
        found.append(_violation("OBS-CODE-MISSING", "observation", source, key, "observation code is absent"))
    if not row.get("source_person_id"):
        found.append(_violation("OBS-PERSON-MISSING", "observation", source, key, "observation has no person key"))
    bounds = PLAUSIBLE.get(row.get("loinc") or "")
    value = row.get("value_numeric")
    if bounds and value is not None and not (bounds[0] <= float(value) <= bounds[1]):
        found.append(
            _violation("OBS-IMPLAUSIBLE", "observation", source, key, f"value {value} outside {bounds}")
        )
    return found


def is_hard(violations: list[dict]) -> bool:
    return any(item["severity"] == "hard" for item in violations)


def scorecard(violations: list[dict], totals: dict[tuple[str, str], int]) -> list[dict]:
    """`totals` maps (source_system, domain) to the number of rows evaluated."""
    grouped: dict[tuple[str, str, str], int] = defaultdict(int)
    for item in violations:
        grouped[(item["source_system"], item["domain"], item["rule_id"])] += 1
    rules_by_domain: dict[str, set[str]] = defaultdict(set)
    for item in violations:
        rules_by_domain[item["domain"]].add(item["rule_id"])
    rows = []
    seen = set(grouped)
    for (source, domain), total in sorted(totals.items()):
        rule_ids = {rule for (src, dom, rule) in seen if src == source and dom == domain}
        rule_ids.update(rules_by_domain.get(domain, set()))
        if not rule_ids:
            rows.append(
                {
                    "source_system": source,
                    "domain": domain,
                    "rule_id": "NONE",
                    "failed": 0,
                    "passed": total,
                    "evaluated": total,
                    "pass_rate": 1.0,
                }
            )
            continue
        for rule_id in sorted(rule_ids):
            failed = grouped.get((source, domain, rule_id), 0)
            passed = max(total - failed, 0)
            rows.append(
                {
                    "source_system": source,
                    "domain": domain,
                    "rule_id": rule_id,
                    "failed": failed,
                    "passed": passed,
                    "evaluated": total,
                    "pass_rate": round(passed / total, 4) if total else 1.0,
                }
            )
    return rows
