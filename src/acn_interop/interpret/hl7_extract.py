"""Project a validated HL7 message into relational fragments."""

from __future__ import annotations

from datetime import datetime

from acn_interop.interpret.dates import parse_date_only, parse_hl7_datetime
from acn_interop.interpret.hl7_parser import Message

CLASS_MAP = {
    "I": "IMP",
    "O": "AMB",
    "E": "EMER",
    "B": "OBS",
    "P": "PRENC",
    "R": "REC",
}


def extract_hl7(message: Message, meta: dict) -> dict[str, list[dict]]:
    source = meta["source_system"]
    control = message.get("MSH", 10)
    message_type = message.get("MSH", 9, 1)
    trigger = message.get("MSH", 9, 2)
    effective = parse_hl7_datetime(message.get("EVN", 2)) or parse_hl7_datetime(message.get("MSH", 7))
    effective = effective or meta["event_time"]
    person = _person(message, meta, source, control, effective, message_type == "ADT")
    encounters = _encounters(message, meta, source, control, effective, trigger, person["source_person_id"])
    observations = _observations(message, meta, source, control, person["source_person_id"], encounters)
    conditions = _conditions(message, meta, source, control, effective, person["source_person_id"])
    allergies = _allergies(message, meta, source, control, effective, person["source_person_id"])
    practitioners = _practitioners(message, source, encounters)
    fragments = {
        "persons": [person] if person["source_person_id"] else [],
        "encounters": encounters,
        "observations": observations,
        "conditions": conditions,
        "medications": [],
        "allergies": allergies,
        "practitioners": practitioners,
        "organizations": [],
    }
    return fragments


def _identifiers(message: Message) -> list[dict]:
    segment = message.seg("PID")
    found = []
    if segment is None or len(segment.fields) <= 3:
        return found
    for repetition in segment.fields[3]:
        if not repetition:
            continue
        found.append(
            {
                "id": repetition[0][0] if repetition[0] else "",
                "authority": repetition[3][0] if len(repetition) > 3 and repetition[3] else "",
                "type": repetition[4][0] if len(repetition) > 4 and repetition[4] else "",
            }
        )
    return found


def _person(message: Message, meta: dict, source: str, control: str, effective: datetime, authority: bool) -> dict:
    mrn = ""
    ssn = ""
    for identifier in _identifiers(message):
        if identifier["type"] in {"MR", "MRN"} and not mrn:
            mrn = identifier["id"]
        if identifier["type"] in {"SS", "SSN"} and not ssn:
            ssn = "".join(ch for ch in identifier["id"] if ch.isdigit())
    dob_raw = message.get("PID", 7)
    return {
        "source_system": source,
        "source_person_id": mrn,
        "vendor_record_id": message.get("PID", 3, 1),
        "family_name": message.get("PID", 5, 1) or None,
        "given_name": message.get("PID", 5, 2) or None,
        "middle_name": message.get("PID", 5, 3) or None,
        "birth_date": parse_date_only(dob_raw),
        "birth_date_raw": dob_raw or None,
        "gender": (message.get("PID", 8) or "U").upper(),
        "address_line": message.get("PID", 11, 1) or None,
        "city": message.get("PID", 11, 3) or None,
        "state": message.get("PID", 11, 4) or None,
        "postal_code": message.get("PID", 11, 5) or None,
        "phone": message.get("PID", 13, 1) or None,
        "ssn": ssn or None,
        "facility_id": message.get("MSH", 4) or source,
        "ehr_product": message.get("MSH", 3) or None,
        "fhir_patient_id": None,
        "demographic_authority": authority,
        "source_format": "HL7_V2",
        "message_key": f"{source}|{control}|PID",
        "effective_time": effective,
        "event_id": meta["event_id"],
        "ingest_time": meta["ingest_time"],
    }


def _encounters(message, meta, source, control, effective, trigger, mrn) -> list[dict]:
    # ORU carries PV1 only as a visit pointer. Registration events own the encounter.
    if message.get("MSH", 9, 1) != "ADT" or message.seg("PV1") is None:
        return []
    visit = message.get("PV1", 19, 1) or control
    patient_class = CLASS_MAP.get(message.get("PV1", 2), message.get("PV1", 2) or "AMB")
    admit = parse_hl7_datetime(message.get("PV1", 44))
    discharge = parse_hl7_datetime(message.get("PV1", 45))
    if trigger == "A03":
        status = "finished"
    elif discharge:
        status = "finished"
    else:
        status = "in-progress"
    return [
        {
            "source_system": source,
            "source_encounter_id": visit,
            "source_person_id": mrn,
            "fhir_patient_id": None,
            "class_code": patient_class,
            "status": status,
            "admit_time": admit or effective,
            "discharge_time": discharge,
            "facility_id": message.get("MSH", 4) or source,
            "attending_id": message.get("PV1", 7, 1) or None,
            "attending_family": message.get("PV1", 7, 2) or None,
            "attending_given": message.get("PV1", 7, 3) or None,
            "reason_text": message.get("PV1", 3, 1) or None,
            "source_format": "HL7_V2",
            "message_key": f"{source}|{control}|PV1",
            "effective_time": effective,
            "event_id": meta["event_id"],
            "ingest_time": meta["ingest_time"],
        }
    ]


def _observations(message, meta, source, control, mrn, encounters) -> list[dict]:
    visit = message.get("PV1", 19, 1) or (encounters[0]["source_encounter_id"] if encounters else None)
    rows = []
    for index, segment in enumerate(message.segs("OBX"), start=1):
        code = segment.value(3, 1)
        low, high = _range(segment.value(7, 1))
        value_text = segment.value(5, 1)
        numeric = _float(value_text)
        observed = parse_hl7_datetime(segment.value(14, 1)) or parse_hl7_datetime(message.get("OBR", 7))
        set_id = segment.value(1, 1) or str(index)
        rows.append(
            {
                "source_system": source,
                "source_observation_id": f"{control}-{set_id}-{code or index}",
                "source_person_id": mrn,
                "fhir_patient_id": None,
                "source_encounter_id": visit,
                "local_code": code or None,
                "local_system": segment.value(3, 3) or None,
                "display": segment.value(3, 2) or None,
                "value_numeric": numeric,
                "value_text": None if numeric is not None else (value_text or None),
                "value_unit": segment.value(6, 1) or None,
                "ref_low": low,
                "ref_high": high,
                "abnormal_flag": segment.value(8, 1) or None,
                "effective_time": observed or meta["event_time"],
                "status": segment.value(11, 1) or "F",
                "source_format": "HL7_V2",
                "message_key": f"{source}|{control}|OBX|{set_id}|{code}",
                "event_id": meta["event_id"],
                "ingest_time": meta["ingest_time"],
            }
        )
    return rows


def _conditions(message, meta, source, control, effective, mrn) -> list[dict]:
    rows = []
    for index, segment in enumerate(message.segs("DG1"), start=1):
        code = segment.value(3, 1)
        set_id = segment.value(1, 1) or str(index)
        rows.append(
            {
                "source_system": source,
                "source_condition_id": f"{control}-{set_id}-{code or index}",
                "source_person_id": mrn,
                "fhir_patient_id": None,
                "local_code": code or None,
                "local_system": segment.value(3, 3) or "I10",
                "display": segment.value(3, 2) or None,
                "clinical_status": "active",
                "onset_time": effective,
                "source_format": "HL7_V2",
                "message_key": f"{source}|{mrn}|DX|{code}",
                "event_id": meta["event_id"],
                "ingest_time": meta["ingest_time"],
            }
        )
    return rows


def _allergies(message, meta, source, control, effective, mrn) -> list[dict]:
    rows = []
    for index, segment in enumerate(message.segs("AL1"), start=1):
        code = segment.value(3, 1)
        rows.append(
            {
                "source_system": source,
                "source_allergy_id": f"{control}-{index}-{code or 'text'}",
                "source_person_id": mrn,
                "fhir_patient_id": None,
                "substance": segment.value(3, 2) or code or None,
                "criticality": segment.value(4, 1) or None,
                "clinical_status": "active",
                "source_format": "HL7_V2",
                "message_key": f"{source}|{mrn}|AL1|{code or index}",
                "effective_time": effective,
                "event_id": meta["event_id"],
                "ingest_time": meta["ingest_time"],
            }
        )
    return rows


def _practitioners(message, source, encounters) -> list[dict]:
    if not encounters or not encounters[0].get("attending_id"):
        return []
    row = encounters[0]
    return [
        {
            "source_system": source,
            "practitioner_id": row["attending_id"],
            "family_name": row["attending_family"],
            "given_name": row["attending_given"],
            "source_format": "HL7_V2",
        }
    ]


def _range(text: str) -> tuple[float | None, float | None]:
    if not text or "-" not in text:
        return None, None
    left, right = text.split("-", 1)
    return _float(left), _float(right)


def _float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None
