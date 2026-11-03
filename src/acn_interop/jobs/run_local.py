"""Command line entry for a local Alderbrook Interop run."""

from __future__ import annotations

import argparse
import json
import sys

from acn_interop.jobs.pipeline import run_pipeline
from acn_interop.platform.config import load_settings, repo_root
from acn_interop.platform.log import configure_logging
from acn_interop.platform.spark_session import build_spark
from acn_interop.synthesize.population import build_feeds, write_sample_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Alderbrook Interop clinical pipeline locally")
    parser.add_argument("--profile", choices=["smoke", "demo"], default="demo")
    parser.add_argument("--lake", default="data/lake")
    parser.add_argument("--evidence", default="evidence")
    parser.add_argument("--write-samples", action="store_true")
    args = parser.parse_args(argv)
    settings = load_settings(profile=args.profile, lake=args.lake, evidence=args.evidence)
    if settings.evidence:
        settings.evidence.mkdir(parents=True, exist_ok=True)
        configure_logging("INFO", str(settings.evidence / "pipeline.log"))
    else:
        configure_logging("INFO")
    if args.write_samples:
        write_sample_files(repo_root() / "samples")
    feeds = build_feeds(args.profile)
    spark = build_spark(f"alderbrook-{args.profile}")
    try:
        report = run_pipeline(spark, settings, feeds)
    finally:
        spark.stop()
    print(json.dumps({key: report[key] for key in (
        "profile", "capture_events", "late_events", "dead_letters", "source_persons",
        "golden_persons", "review_queue", "readmission_summary", "care_gap_counts",
        "broadcast_join_observed", "deid_identifier_columns", "optimize", "timings_seconds",
    )}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
