from datetime import datetime

from acn_interop.interpret.hl7_extract import extract_hl7
from acn_interop.interpret.hl7_parser import parse_message
from acn_interop.interpret.hl7_validate import validate_hl7

ADT = "\r".join(
    [
        "MSH|^~\\&|VISTARA|AMC|NORTHLINE|ALDERBROOK|20260801150000||ADT^A01|MSG100|P|2.5",
        "EVN|A01|20260801150000",
        "PID|1||AMC10001^^^AMC^MR~900551001^^^USSSA^SS||VOSS^ELENA^M||19790412|F|||"
        + "12 Pine \\T\\ Oak St^^Alderbrook^OR^97702||5035550101",
        "PV1|1|I|MED^101^A||||SYNTH-PRAC-AMC^Okonkwo^Ada||||||||||||V-ELENA-1"
        + "|||||||||||||||||||||||||20260801150000",
        "NTE|1||Room request\\.br\\near window",
        "OBX|1|NM|GLU^Glucose \\F\\ serum^L||186|mg/dL|70-99|H|||F",
    ]
) + "\r"


def test_parser_reads_repetitions_components_and_escapes():
    message = parse_message(ADT)
    assert message.get("MSH", 9, 1) == "ADT"
    assert message.get("MSH", 9, 2) == "A01"
    assert message.get("MSH", 10) == "MSG100"
    pid = message.seg("PID")
    assert pid is not None
    assert len(pid.fields[3]) == 2
    assert message.get("PID", 3, 1, repetition=1) == "AMC10001"
    assert message.get("PID", 3, 5, repetition=1) == "MR"
    assert message.get("PID", 3, 5, repetition=2) == "SS"
    assert message.get("PID", 11, 1) == "12 Pine & Oak St"
    assert message.get("NTE", 3) == "Room request\nnear window"
    assert message.get("OBX", 3, 2) == "Glucose | serum"
    assert validate_hl7(message) == []


def test_newline_delimited_message_matches_carriage_return():
    cr = parse_message(ADT)
    lf = parse_message(ADT.replace("\r", "\n"))
    assert lf.get("PID", 5, 1) == cr.get("PID", 5, 1) == "VOSS"


def test_missing_msh_and_batched_messages_fail():
    try:
        parse_message("PID|1||ABC")
        raised = False
    except Exception as exc:
        raised = True
        assert "MSH" in str(exc)
    assert raised
    batched = ADT + "MSH|^~\\&|VISTARA|AMC|NORTHLINE|ALDERBROOK|20260801150000||ADT^A08|MSG2|P|2.5\r"
    try:
        parse_message(batched)
        raised = False
    except Exception as exc:
        raised = True
        assert "batched" in str(exc)
    assert raised


def test_extract_projects_encounter_and_mrn():
    message = parse_message(ADT)
    meta = {
        "event_id": "e1",
        "source_system": "AMC",
        "event_time": datetime(2026, 8, 1, 15, 0, 0),
        "ingest_time": datetime(2026, 8, 1, 15, 0, 1),
    }
    fragments = extract_hl7(message, meta)
    person = fragments["persons"][0]
    assert person["source_person_id"] == "AMC10001"
    assert person["ssn"] == "900551001"
    assert person["demographic_authority"] is True
    encounter = fragments["encounters"][0]
    assert encounter["class_code"] == "IMP"
    assert encounter["source_encounter_id"] == "V-ELENA-1"
    assert fragments["observations"][0]["value_numeric"] == 186.0
    assert fragments["observations"][0]["ref_high"] == 99.0
