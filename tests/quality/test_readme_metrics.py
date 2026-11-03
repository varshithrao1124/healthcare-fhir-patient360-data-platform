import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_quotes_the_demo_run():
    metrics = json.loads((ROOT / "evidence" / "run_metrics.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert metrics["profile"] == "demo"
    assert str(metrics["capture_events"]) in readme
    assert str(metrics["source_persons"]) in readme
    assert str(metrics["golden_persons"]) in readme
    assert str(metrics["pairs_compared"]) in readme
    assert str(metrics["possible_pairs"]) in readme
    assert str(metrics["readmission_summary"]["readmission_rate"]) in readme
    assert metrics["deid_identifier_columns"] == []
