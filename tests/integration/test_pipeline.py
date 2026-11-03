"""End-to-end local run of the scripted Alderbrook population."""

from pyspark.sql import functions as F

from acn_interop.capture.streaming import run_file_stream
from acn_interop.jobs.pipeline import run_pipeline
from acn_interop.platform.config import load_settings
from acn_interop.shield.token import person_token
from acn_interop.synthesize.population import build_feeds


def _table(spark, settings, relative):
    return spark.read.format("delta").load(str(settings.lake / relative))


def test_smoke_patient_360(spark, tmp_path):
    settings = load_settings(profile="smoke", lake=tmp_path / "lake", evidence=tmp_path / "evidence")
    report = run_pipeline(spark, settings, build_feeds("smoke"))

    assert report["late_events"] == 1
    assert report["dead_letters"] == 4
    assert report["duplicate_transport_replays"] == 1
    assert report["review_queue"] == 1
    assert report["auto_edges"] == 5
    assert report["pairs_compared"] < report["possible_pairs"]
    assert report["broadcast_join_observed"] is True
    assert report["deid_identifier_columns"] == []
    assert report["optimize"]["ran"] is True
    assert report["readmission_summary"]["readmissions"] == 2
    assert report["readmission_summary"]["transfers"] == 1
    assert report["care_gap_counts"] == {"DM_NO_A1C_180D": 2, "HTN_NO_SBP_365D": 1}
    assert report["chronic_counts"]["diabetes"] == 3
    assert report["chronic_counts"]["hypertension"] == 2
    assert report["source_persons"] > report["golden_persons"]

    events = _table(spark, settings, "capture/events")
    assert events.count() == events.select("event_id").distinct().count()
    before = events.count()
    run_file_stream(
        spark,
        settings.work / "inbox",
        settings.lake,
        settings.checkpoint / "capture",
        allowed_lateness_hours=settings.allowed_lateness_hours,
    )
    assert _table(spark, settings, "capture/events").count() == before

    golden = _table(spark, settings, "conform/golden_person")
    assert "ssn" not in golden.columns
    elena = golden.filter(F.col("family_name") == "Voss").collect()[0]
    assert elena.given_name == "Elena"
    assert elena.phone == "5035550199"
    assert elena.member_count == 2
    crosswalk = _table(spark, settings, "conform/person_crosswalk")
    elena_rows = crosswalk.filter(F.col("enterprise_person_id") == elena.enterprise_person_id).collect()
    assert {row.source_person_id for row in elena_rows} == {"AMC10001", "CHO10001"}
    assert {row.match_type for row in elena_rows} == {"deterministic_ssn"}

    def enterprise_ids(mrns):
        rows = crosswalk.filter(F.col("source_person_id").isin(mrns)).collect()
        return {row.source_person_id: row.enterprise_person_id for row in rows}

    robert = enterprise_ids(["AMC10002", "RGH10002"])
    assert robert["AMC10002"] == robert["RGH10002"]
    sofia = enterprise_ids(["AMC10003", "CHO10003"])
    assert sofia["AMC10003"] == sofia["CHO10003"]
    millers = enterprise_ids(["AMC10005", "CHO10006"])
    assert millers["AMC10005"] != millers["CHO10006"]
    review = _table(spark, settings, "conform/review_queue").collect()[0]
    assert {review.left_person_id, review.right_person_id} == {"AMC10004", "RGH10004"}
    assert abs(review.score - 0.78) < 0.001

    facts = _table(spark, settings, "insight/encounter_fact")
    readmits = {row.source_encounter_id for row in facts.filter("is_30day_readmission").collect()}
    assert readmits == {"V-ELENA-2", "V-JUNE-2"}
    transfers = {row.source_encounter_id for row in facts.filter("is_transfer").collect()}
    assert transfers == {"V-LUIS-RGH"}
    persistent = _table(spark, settings, "insight/lab_trend").filter("persistent_abnormal").collect()
    assert {(row.loinc, row.value_numeric) for row in persistent} == {("2823-3", 6.1)}
    assert _table(spark, settings, "conform/observation").filter("local_code = 'ZZZ-NOT-A-CODE'").count() == 1
    assert _table(spark, settings, "insight/lab_trend").filter("loinc = 'ZZZ-NOT-A-CODE'").count() == 0
    willa = golden.filter(F.col("family_name") == "Brooks").collect()[0]
    assert willa.address_line == "12 Pine & Oak St"

    expected_token = person_token(elena.enterprise_person_id, settings.salt)
    deid = _table(spark, settings, "deidentified/encounter_fact")
    assert deid.filter(F.col("person_token") == expected_token).count() > 0
    elena_deid = deid.filter(F.col("person_token") == expected_token).collect()[0]
    assert elena_deid.age_band == "45-64"
    assert elena_deid.postal3 == "977"
