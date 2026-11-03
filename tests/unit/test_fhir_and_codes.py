import json

import jsonschema

from acn_interop.interpret.fhir_extract import extension_map, extract_fhir
from acn_interop.interpret.fhir_validate import validate_fhir
from acn_interop.platform.config import repo_root
from acn_interop.vocab.codes import load_map, lookup, normalize_icd10

ROOT = repo_root()


def _meta():
    from datetime import datetime

    return {
        "event_id": "f1",
        "source_system": "CHO",
        "event_time": datetime(2026, 9, 15, 16, 0, 0),
        "ingest_time": datetime(2026, 9, 15, 16, 0, 1),
    }


def test_fhir_patient_flattens_extension_identifier_and_name():
    resource = json.loads((ROOT / "samples" / "fhir" / "patient_elena.ndjson").read_text().splitlines()[0]) if False else {
        "resourceType": "Patient",
        "id": "cho-elena",
        "meta": {"versionId": "2", "lastUpdated": "2026-09-15T16:00:00Z"},
        "identifier": [
            {"system": "http://alderbrook.example/mrn/CHO", "value": "CHO10001", "type": {"coding": [{"code": "MR"}]}},
            {"system": "http://hl7.org/fhir/sid/us-ssn", "value": "900-55-1001"},
        ],
        "name": [{"family": "Voss", "given": ["Elaina", "M"]}],
        "gender": "female",
        "birthDate": "1979-04-12",
        "address": [{"line": ["100 Main St"], "city": "Alderbrook", "state": "OR", "postalCode": "97701"}],
        "extension": [
            {"url": "http://alderbrook.example/fhir/StructureDefinition/source-ehr", "valueString": "LumenClinic"}
        ],
    }
    assert validate_fhir(resource) == []
    assert extension_map(resource)["source-ehr"] == "LumenClinic"
    row = extract_fhir(resource, _meta())["persons"][0]
    assert row["source_person_id"] == "CHO10001"
    assert row["given_name"] == "Elaina"
    assert row["middle_name"] == "M"
    assert row["gender"] == "F"
    assert row["ssn"] == "900551001"
    assert row["ehr_product"] == "LumenClinic"
    assert str(row["birth_date"]) == "1979-04-12"


def test_observation_prefers_loinc_coding():
    resource = {
        "resourceType": "Observation",
        "id": "obs-1",
        "status": "final",
        "code": {
            "coding": [
                {"system": "http://acn.example/local", "code": "AMCGLU", "display": "Local glucose"},
                {"system": "http://loinc.org", "code": "2345-7", "display": "Glucose"},
            ]
        },
        "subject": {"reference": "Patient/cho-elena"},
        "effectiveDateTime": "2026-08-01T16:00:00Z",
        "valueQuantity": {"value": 186, "unit": "mg/dL"},
    }
    row = extract_fhir(resource, _meta())["observations"][0]
    assert row["local_code"] == "2345-7"
    assert row["fhir_patient_id"] == "cho-elena"
    assert validate_fhir({"resourceType": "Observation", "id": "bad", "status": "final"})


def test_icd_normalization_and_crosswalk_fallback():
    assert normalize_icd10("E119") == "E11.9"
    assert normalize_icd10("E11.9") == "E11.9"
    assert normalize_icd10("I10") == "I10"
    assert normalize_icd10("ZZZ-NOT-A-CODE") == "ZZZ-NOT-A-CODE"
    rows = load_map(ROOT / "reference" / "terminology" / "lab_crosswalk.csv")
    assert lookup(rows, "AMC", "AMCGLU", "loinc") == "2345-7"
    assert lookup(rows, "CHO", "2345-7", "loinc") == "2345-7"
    assert lookup(rows, "AMC", "ZZZ-NOT-A-CODE", "loinc") is None


def test_envelope_contract_rejects_a_partial_event():
    schema = json.loads((ROOT / "contracts" / "envelope.schema.json").read_text())
    jsonschema.validate(
        {
            "event_id": "strm-1",
            "source_system": "AMC",
            "payload_type": "HL7_V2",
            "event_time": "2026-08-01 15:00:00",
            "partition": 0,
            "offset": 1,
            "body": "MSH|",
        },
        schema,
    )
    try:
        jsonschema.validate({"payload_type": "HL7_V2"}, schema)
        raised = False
    except jsonschema.ValidationError:
        raised = True
    assert raised
