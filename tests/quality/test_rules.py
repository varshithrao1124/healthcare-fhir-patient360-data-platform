from datetime import date, datetime

from acn_interop.assure.checks import (
    HARD_RULES,
    encounter_violations,
    is_hard,
    observation_violations,
    person_violations,
    scorecard,
)
from acn_interop.platform.config import repo_root


def test_hard_rules_match_the_contract_catalog():
    import yaml

    catalog = yaml.safe_load((repo_root() / "contracts" / "dq_rules.yml").read_text())
    documented = {rule["id"] for rule in catalog["rules"] if rule["severity"] == "hard"}
    assert documented == HARD_RULES | {"VOC-UNMAPPED"}


def test_person_and_encounter_rules_separate_hard_and_soft_failures():
    as_of = date(2026, 11, 1)
    missing = person_violations(
        {"source_system": "AMC", "source_person_id": "1", "gender": "F", "address_line": "1 Main"},
        as_of,
    )
    assert "PER-NAME" in {item["rule_id"] for item in missing}
    assert is_hard(missing)
    future = person_violations(
        {
            "source_system": "AMC",
            "source_person_id": "2",
            "family_name": "Future",
            "given_name": "Pat",
            "birth_date_raw": "20310101",
            "birth_date": date(2031, 1, 1),
            "gender": "M",
            "address_line": "2 Later",
        },
        as_of,
    )
    assert any(item["rule_id"] == "PER-DOB-FUTURE" and item["severity"] == "hard" for item in future)
    year_only = person_violations(
        {
            "source_system": "CHO",
            "source_person_id": "3",
            "family_name": "Nash",
            "given_name": "Yuri",
            "birth_date_raw": "1984",
            "birth_date": None,
            "gender": "M",
        },
        as_of,
    )
    assert any(item["rule_id"] == "PER-DOB-PRECISION" and item["severity"] == "soft" for item in year_only)
    assert not is_hard(year_only)
    inverted = encounter_violations(
        {
            "source_system": "AMC",
            "source_encounter_id": "V",
            "source_person_id": "2",
            "admit_time": datetime(2026, 5, 6, 5, 8),
            "discharge_time": datetime(2026, 5, 5, 5, 8),
        }
    )
    assert inverted[0]["rule_id"] == "ENC-DISCHARGE-ORDER"
    implausible = observation_violations(
        {
            "source_system": "AMC",
            "source_observation_id": "spike",
            "source_person_id": "AMC19994",
            "local_code": "2345-7",
            "loinc": "2345-7",
            "value_numeric": 4000,
        }
    )
    assert implausible[0]["rule_id"] == "OBS-IMPLAUSIBLE"


def test_scorecard_pass_rate_uses_evaluated_rows():
    violations = [
        {
            "rule_id": "PER-NAME",
            "domain": "person",
            "source_system": "AMC",
            "record_key": "AMC|1",
            "detail": "name",
            "severity": "hard",
        }
    ]
    rows = scorecard(violations, {("AMC", "person"): 4, ("CHO", "person"): 2})
    amc = next(row for row in rows if row["source_system"] == "AMC" and row["rule_id"] == "PER-NAME")
    assert amc["failed"] == 1
    assert amc["passed"] == 3
    assert amc["pass_rate"] == 0.75
    cho = next(row for row in rows if row["source_system"] == "CHO" and row["rule_id"] == "PER-NAME")
    assert cho["failed"] == 0
    assert cho["pass_rate"] == 1.0
