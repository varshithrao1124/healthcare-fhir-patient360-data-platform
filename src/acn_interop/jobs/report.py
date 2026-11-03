"""Charts and an HTML scorecard drawn from a finished local run."""

from __future__ import annotations

import json
from pathlib import Path


def write_evidence(report: dict, evidence: Path) -> None:
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "run_metrics.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    _charts(report, evidence / "charts")
    (evidence / "dashboard.html").write_text(_html(report), encoding="utf-8")


def _charts(report: dict, directory: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    directory.mkdir(parents=True, exist_ok=True)
    completeness = report.get("completeness") or []
    if completeness:
        labels = [row["source_system"] for row in completeness]
        values = [row["dob_rate"] for row in completeness]
        _bar(plt, labels, values, "Birth-date completeness by source", directory / "dob_completeness.png")
    gaps = report.get("care_gap_counts") or {}
    if gaps:
        _bar(plt, list(gaps.keys()), list(gaps.values()), "Open care gaps", directory / "care_gaps.png")
    matches = report.get("match_type_counts") or {}
    if matches:
        _bar(plt, list(matches.keys()), list(matches.values()), "Crosswalk match types", directory / "match_types.png")


def _bar(plt, labels, values, title, path: Path) -> None:
    figure, axis = plt.subplots(figsize=(8, 4.2))
    axis.bar(labels, values, color="#1f4e79")
    axis.set_title(title)
    axis.tick_params(axis="x", rotation=25)
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def _html(report: dict) -> str:
    gaps = report.get("care_gap_counts") or {}
    gap_rows = "".join(f"<tr><td>{code}</td><td>{count}</td></tr>" for code, count in gaps.items())
    summary = report.get("readmission_summary") or {}
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Alderbrook Interop local scorecard</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 2rem; color: #1c2833; background: #f7f4ef; }}
    h1 {{ font-weight: normal; }}
    table {{ border-collapse: collapse; background: white; }}
    td, th {{ border: 1px solid #d5d0c8; padding: 0.4rem 0.7rem; }}
    .note {{ max-width: 42rem; }}
  </style>
</head>
<body>
  <h1>Alderbrook Interop local Patient 360 scorecard</h1>
  <p class="note">Synthetic Alderbrook Care Network data. This page is rendered from the local
  Spark run that wrote <code>run_metrics.json</code>. It is not a Power BI or Azure screenshot.</p>
  <table>
    <tr><th>Profile</th><td>{report.get("profile")}</td></tr>
    <tr><th>As of</th><td>{report.get("as_of")}</td></tr>
    <tr><th>Source persons</th><td>{report.get("source_persons")}</td></tr>
    <tr><th>Enterprise persons</th><td>{report.get("golden_persons")}</td></tr>
    <tr><th>Capture events</th><td>{report.get("capture_events")}</td></tr>
    <tr><th>Late events kept</th><td>{report.get("late_events")}</td></tr>
    <tr><th>Dead letters</th><td>{report.get("dead_letters")}</td></tr>
    <tr><th>Review queue</th><td>{report.get("review_queue")}</td></tr>
    <tr><th>Inpatient encounters</th><td>{summary.get("inpatient_encounters")}</td></tr>
    <tr><th>30-day readmissions</th><td>{summary.get("readmissions")}</td></tr>
    <tr><th>Transfers under 24h</th><td>{summary.get("transfers")}</td></tr>
    <tr><th>Pairs compared / possible</th><td>{report.get("pairs_compared")} / {report.get("possible_pairs")}</td></tr>
  </table>
  <h2>Care gaps</h2>
  <table><tr><th>Gap</th><th>People</th></tr>{gap_rows}</table>
</body>
</html>
"""
