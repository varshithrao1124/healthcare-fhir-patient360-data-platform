from acn_interop.interpret.hl7_parser import parse_message
from acn_interop.interpret.hl7_validate import validate_hl7
from acn_interop.platform.config import repo_root
from acn_interop.synthesize.population import build_feeds, write_sample_files


def test_committed_samples_match_the_generator(tmp_path):
    write_sample_files(tmp_path)
    root = repo_root() / "samples"
    for path in tmp_path.rglob("*"):
        if path.is_dir():
            continue
        committed = root / path.relative_to(tmp_path)
        assert committed.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


def test_sample_messages_parse():
    root = repo_root() / "samples"
    for path in (root / "hl7").glob("*.hl7"):
        message = parse_message(path.read_text(encoding="utf-8"))
        assert validate_hl7(message) == []
        assert message.get("MSH", 10)


def test_smoke_feed_is_seeded_and_contains_the_story():
    feeds = build_feeds("smoke")
    hl7_bodies = "\n".join(row.get("body", "") for row in feeds["backfill"] if row.get("payload_type") == "HL7_V2")
    fhir_bodies = [row["body"] for row in feeds["backfill"] if row.get("payload_type") == "FHIR_R4"]
    assert "Voss" in hl7_bodies
    assert "Alvares" not in hl7_bodies
    assert any("Alvares" in body for body in fhir_bodies)
    assert feeds["delayed"][0]["event_time"] == "2026-10-28 08:00:00"
    assert build_feeds("smoke")["backfill"][0]["event_id"] == feeds["backfill"][0]["event_id"]
