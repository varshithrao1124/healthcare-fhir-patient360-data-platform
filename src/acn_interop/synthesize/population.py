"""Build a reproducible HL7 and FHIR feed for the Northline local run.

The scripted patients are the clinical story: duplicate charts, a review-band
pair, a 30-day readmission, a transfer, care gaps, and intentional defects.
Demo mode adds extra single-source patients so the lake is not only the story.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from acn_interop.synthesize.render import (
    fhir_condition,
    fhir_encounter,
    fhir_medication,
    fhir_observation,
    fhir_patient,
    reference_resources,
    render_adt,
    render_oru,
)

ANCHOR = "2026-10-28 18:00:00"
LATE = "2026-10-28 08:00:00"
FOLLOWING = "2026-10-28 19:30:00"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"


def stamp(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


class _Builder:
    def __init__(self):
        self.backfill: list[dict] = []
        self.delayed: list[dict] = []
        self.bulk: dict[str, list[dict]] = defaultdict(list)
        self.bulk_index: list[dict] = []
        self.seq = 0
        self.offset = 0

    def hl7(self, source: str, when: str, body: str, wave: str = "backfill", event_id: str | None = None) -> dict:
        return self._env(source, "HL7_V2", when, body, wave, event_id)

    def fhir(self, source: str, when: str, resource: dict, *, stream: bool = True, bulk: bool = False, wave: str = "backfill") -> None:
        if bulk:
            self.bulk[resource["resourceType"]].append(resource)
            self.bulk_index.append({"source_system": source, "event_time": when, "resource": resource})
        if stream:
            self._env(source, "FHIR_R4", when, json.dumps(resource), wave)

    def _env(self, source, payload, when, body, wave, event_id=None) -> dict:
        self.seq += 1
        self.offset += 1
        row = {
            "event_id": event_id or f"strm-{self.seq:05d}",
            "source_system": source,
            "payload_type": payload,
            "event_time": when,
            "partition": {"AMC": 0, "RGH": 1, "CHO": 2}[source],
            "offset": self.offset,
            "body": body,
        }
        target = self.delayed if wave == "delayed" else self.backfill
        target.append(row)
        return row

    def control(self) -> str:
        self.seq += 1
        return f"MSG{self.seq:06d}"


def build_feeds(profile: str = "demo") -> dict:
    builder = _Builder()
    _story(builder)
    if profile == "demo":
        _fillers(builder, count=12)
    _defects(builder)
    _anchor_and_delay(builder)
    for resource_type, rows in reference_resources().items():
        builder.bulk[resource_type].extend(rows)
        for row in rows:
            if resource_type == "Organization":
                source = row["identifier"][0]["value"]
            elif "RGH" in row["id"]:
                source = "RGH"
            elif "CHO" in row["id"]:
                source = "CHO"
            else:
                source = "AMC"
            builder.bulk_index.append(
                {"source_system": source, "event_time": "2026-01-01 00:00:00", "resource": row}
            )
    _guard_clock(builder)
    return {
        "profile": profile,
        "backfill": builder.backfill,
        "delayed": builder.delayed,
        "bulk": {key: value for key, value in builder.bulk.items()},
        "bulk_index": builder.bulk_index,
    }


def write_feeds(feeds: dict, inbox: Path, bulk_dir: Path) -> None:
    inbox.mkdir(parents=True, exist_ok=True)
    bulk_dir.mkdir(parents=True, exist_ok=True)
    _dump(inbox / "01-backfill.json", feeds["backfill"])
    for resource_type, rows in feeds["bulk"].items():
        _dump(bulk_dir / f"{resource_type}.ndjson", rows)


def write_delayed(feeds: dict, inbox: Path) -> None:
    _dump(inbox / "02-delayed.json", feeds["delayed"])


def write_sample_files(directory: Path) -> None:
    """Small committed excerpts produced by the same renderers as the full feed."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "hl7").mkdir(exist_ok=True)
    (directory / "fhir").mkdir(exist_ok=True)
    elena_a01 = render_adt(
        source="AMC",
        trigger="A01",
        control="MSG-SAMPLE-A01",
        event_time=stamp("2026-08-01 15:00:00"),
        mrn="AMC10001",
        family="Voss",
        given="Elena",
        middle="M",
        birth=stamp("1979-04-12 00:00:00").date(),
        gender="F",
        line="100 Main St",
        city="Alderbrook",
        state="OR",
        postal="97701",
        phone="5035550101",
        ssn="900-55-1001",
        visit="V-ELENA-1",
        patient_class="I",
        admit=stamp("2026-08-01 15:00:00"),
        diagnoses=[{"code": "E119", "display": "Type 2 diabetes mellitus without complications"}],
        allergies=[{"code": "PENICILLIN", "display": "Penicillin"}],
        note=r"Room request\.br\near window",
    )
    willa = render_oru(
        source="AMC",
        control="MSG-SAMPLE-ORU",
        event_time=stamp("2026-06-02 09:00:00"),
        mrn="AMC10015",
        family="Brooks",
        given="Willa",
        birth=stamp("1988-12-12 00:00:00").date(),
        gender="F",
        line="12 Pine & Oak St",
        city="Alderbrook",
        state="OR",
        postal="97702",
        phone="5035550115",
        ssn=None,
        visit="V-WILLA-1",
        code="2345-7",
        display="Glucose",
        system="LN",
        value="102",
        unit="mg/dL",
        low="70",
        high="99",
        flag="H",
        observed=stamp("2026-06-02 09:00:00"),
    )
    (directory / "hl7" / "adt_a01_elena.hl7").write_text(elena_a01.replace("\r", "\n"), encoding="utf-8")
    (directory / "hl7" / "oru_r01_willa.hl7").write_text(willa.replace("\r", "\n"), encoding="utf-8")
    patient = fhir_patient(
        source="CHO",
        fhir_id="cho-elena",
        version="2",
        updated=stamp("2026-09-15 16:00:00"),
        mrn="CHO10001",
        family="Voss",
        given="Elaina",
        middle=None,
        gender="F",
        birth="1979-04-12",
        line="100 Main St",
        city="Alderbrook",
        state="OR",
        postal="97701",
        phone="5035550199",
        ssn="900-55-1001",
    )
    lab = fhir_observation(
        obs_id="obs-sample-k",
        patient_id="cho-elena",
        encounter_id=None,
        code="2823-3",
        system=LOINC,
        display="Potassium",
        value=5.8,
        unit="mmol/L",
        low=3.5,
        high=5.1,
        flag="H",
        observed=stamp("2026-08-20 10:00:00"),
    )
    _dump(directory / "fhir" / "patient_elena.ndjson", [patient])
    _dump(directory / "fhir" / "observation_potassium.ndjson", [lab])


def _story(builder: _Builder) -> None:
    _elena(builder)
    _robert(builder)
    _sofia(builder)
    _helen(builder)
    _millers(builder)
    _grants(builder)
    _marcus(builder)
    _june(builder)
    _luis(builder)
    _ruth(builder)
    _samir(builder)
    _nora(builder)
    _owen(builder)
    _willa(builder)
    _quinn(builder)
    _yuri(builder)


def _elena(b: _Builder) -> None:
    birth = stamp("1979-04-12 00:00:00").date()
    common = dict(
        source="AMC", mrn="AMC10001", family="Voss", given="Elena", middle="M", birth=birth,
        gender="F", line="100 Main St", city="Alderbrook", state="OR", postal="97701",
        phone="5035550101", ssn="900-55-1001",
    )
    admit1, discharge1 = stamp("2026-08-01 15:00:00"), stamp("2026-08-05 11:00:00")
    b.hl7("AMC", "2026-08-01 15:04:00", render_adt(
        trigger="A01", control=b.control(), event_time=admit1, visit="V-ELENA-1", patient_class="I",
        admit=admit1, diagnoses=[{"code": "E119", "display": "Type 2 diabetes mellitus without complications"}],
        allergies=[{"code": "PENICILLIN", "display": "Penicillin"}], **common,
    ))
    b.hl7("AMC", "2026-08-05 11:10:00", render_adt(
        trigger="A03", control=b.control(), event_time=discharge1, visit="V-ELENA-1", patient_class="I",
        admit=admit1, discharge=discharge1, **common,
    ))
    admit2, discharge2 = stamp("2026-08-20 09:00:00"), stamp("2026-08-22 16:00:00")
    b.hl7("AMC", "2026-08-20 09:05:00", render_adt(
        trigger="A01", control=b.control(), event_time=admit2, visit="V-ELENA-2", patient_class="I",
        admit=admit2, **common,
    ))
    b.hl7("AMC", "2026-08-22 16:05:00", render_adt(
        trigger="A03", control=b.control(), event_time=discharge2, visit="V-ELENA-2", patient_class="I",
        admit=admit2, discharge=discharge2, **common,
    ))
    b.hl7("AMC", "2026-08-01 16:00:00", render_oru(
        source="AMC", control=b.control(), event_time=stamp("2026-08-01 16:00:00"), visit="V-ELENA-1",
        code="AMCGLU", display="Glucose", system="L", value="186", unit="mg/dL", low="70", high="99",
        flag="H", observed=stamp("2026-08-01 16:00:00"),
        mrn="AMC10001", family="Voss", given="Elena", birth=birth, gender="F",
        line="100 Main St", city="Alderbrook", state="OR", postal="97701", phone="5035550101", ssn="900-55-1001",
    ))
    b.hl7("AMC", "2026-08-20 10:20:00", render_oru(
        source="AMC", control=b.control(), event_time=stamp("2026-08-20 10:20:00"), visit="V-ELENA-2",
        code="2823-3", display="Potassium", system="LN", value="5.8", unit="mmol/L", low="3.5", high="5.1",
        flag="H", observed=stamp("2026-08-20 10:00:00"),
        mrn="AMC10001", family="Voss", given="Elena", birth=birth, gender="F",
        line="100 Main St", city="Alderbrook", state="OR", postal="97701", phone="5035550101", ssn="900-55-1001",
    ))
    b.hl7("AMC", "2026-08-21 10:20:00", render_oru(
        source="AMC", control=b.control(), event_time=stamp("2026-08-21 10:20:00"), visit="V-ELENA-2",
        code="2823-3", display="Potassium", system="LN", value="6.1", unit="mmol/L", low="3.5", high="5.1",
        flag="H", observed=stamp("2026-08-21 10:00:00"),
        mrn="AMC10001", family="Voss", given="Elena", birth=birth, gender="F",
        line="100 Main St", city="Alderbrook", state="OR", postal="97701", phone="5035550101", ssn="900-55-1001",
    ))
    first = fhir_patient(
        source="CHO", fhir_id="cho-elena", version="1", updated=stamp("2026-08-10 12:00:00"),
        mrn="CHO10001", family="Voss", given="Elaina", middle=None, gender="F", birth="1979-04-12",
        line="100 Main St", city="Alderbrook", state="OR", postal="97701", phone="5035550101", ssn="900-55-1001",
    )
    second = fhir_patient(
        source="CHO", fhir_id="cho-elena", version="2", updated=stamp("2026-09-15 16:00:00"),
        mrn="CHO10001", family="Voss", given="Elaina", middle=None, gender="F", birth="1979-04-12",
        line="100 Main St", city="Alderbrook", state="OR", postal="97701", phone="5035550199", ssn="900-55-1001",
    )
    b.fhir("CHO", "2026-08-10 12:00:00", first, stream=True, bulk=False)
    b.fhir("CHO", "2026-09-15 16:00:00", second, stream=True, bulk=True)
    clinic = fhir_encounter(
        source="CHO", enc_id="enc-elena-clinic", patient_id="cho-elena", status="finished", class_code="AMB",
        start=stamp("2026-09-02 17:00:00"), end=stamp("2026-09-02 17:30:00"), visit="V-ELENA-CLINIC",
        updated=stamp("2026-09-02 17:40:00"),
    )
    b.fhir("CHO", "2026-09-02 17:40:00", clinic, stream=True, bulk=True)
    b.fhir("CHO", "2026-08-10 12:05:00", fhir_condition(
        cond_id="cond-elena-dm", patient_id="cho-elena", code="E11.9", system=ICD10,
        display="Type 2 diabetes mellitus without complications", onset=stamp("2024-05-01 00:00:00"),
    ), stream=True, bulk=True)
    b.fhir("CHO", "2026-01-10 09:00:00", fhir_medication(
        med_id="med-elena-met", patient_id="cho-elena", code="860975", display="metformin 500 MG Oral Tablet",
        authored=stamp("2026-01-10 09:00:00"),
    ), stream=True, bulk=True)


def _simple_hl7_person(b, *, source, mrn, family, given, birth, gender, line, city, postal, ssn, when, phone, visit, patient_class="O", middle=None, state="OR", diagnoses=None, admit=None, discharge=None, trigger="A04"):
    event = stamp(when)
    b.hl7(source, when, render_adt(
        source=source, trigger=trigger, control=b.control(), event_time=event, mrn=mrn, family=family,
        given=given, middle=middle, birth=stamp(birth).date() if len(birth) > 4 else None, gender=gender,
        line=line, city=city, state=state, postal=postal, phone=phone, ssn=ssn, visit=visit,
        patient_class=patient_class, admit=admit or event, discharge=discharge, diagnoses=diagnoses,
        birth_raw=None if len(birth) > 4 else birth,
    ))


def _robert(b: _Builder) -> None:
    _simple_hl7_person(
        b, source="AMC", mrn="AMC10002", family="Smith", given="Robert", birth="1980-03-15 00:00:00",
        gender="M", line="18 River Rd", city="Rivergate", postal="97001", ssn="900-55-1002",
        when="2026-03-02 11:00:00", phone="5035550102", visit="V-ROBERT-1",
    )
    b.fhir("RGH", "2026-04-04 15:00:00", fhir_patient(
        source="RGH", fhir_id="rgh-robert", version="1", updated=stamp("2026-04-04 15:00:00"),
        mrn="RGH10002", family="Smith", given="Bob", middle=None, gender="M", birth="1980-03-15",
        line="18 River Road", city="Rivergate", state="OR", postal="97001", phone="5035550102", ssn="900-55-1002",
    ), stream=True, bulk=True)


def _sofia(b: _Builder) -> None:
    _simple_hl7_person(
        b, source="AMC", mrn="AMC10003", family="Alvarez", given="Sofia", birth="1992-11-02 00:00:00",
        gender="F", line="44 Cedar Ave", city="Alderbrook", postal="97701", ssn=None,
        when="2026-02-11 10:00:00", phone="5035550103", visit="V-SOFIA-1",
    )
    b.fhir("CHO", "2026-05-19 13:00:00", fhir_patient(
        source="CHO", fhir_id="cho-sofia", version="1", updated=stamp("2026-05-19 13:00:00"),
        mrn="CHO10003", family="Alvares", given="Sofia", middle=None, gender="F", birth="1992-11-02",
        line="44 Cedar Avenue", city="Alderbrook", state="OR", postal="97701", phone="5035550188", ssn=None,
    ), stream=True, bulk=True)


def _helen(b: _Builder) -> None:
    _simple_hl7_person(
        b, source="AMC", mrn="AMC10004", family="Cho", given="Helen", birth="1970-01-05 00:00:00",
        gender="F", line="9 Hearth Lane", city="Hearth", postal="97703", ssn=None,
        when="2026-01-20 09:00:00", phone="5035550104", visit="V-HELEN-1",
    )
    b.fhir("RGH", "2026-02-02 09:30:00", fhir_patient(
        source="RGH", fhir_id="rgh-helen", version="1", updated=stamp("2026-02-02 09:30:00"),
        mrn="RGH10004", family="Cho", given="Helen", middle=None, gender="F", birth="1971-01-05",
        line="9 Hearth Lane", city="Hearth", state="OR", postal="97703", phone="5035550104", ssn=None,
    ), stream=True, bulk=True)


def _millers(b: _Builder) -> None:
    _simple_hl7_person(
        b, source="AMC", mrn="AMC10005", family="Miller", given="James", birth="1960-04-02 00:00:00",
        gender="M", line="10 Oak St", city="Alderbrook", postal="97701", ssn="900-55-1005",
        when="2026-03-03 08:00:00", phone="5035550105", visit="V-MILLER-SR",
    )
    b.fhir("CHO", "2026-03-04 08:00:00", fhir_patient(
        source="CHO", fhir_id="cho-miller-jr", version="1", updated=stamp("2026-03-04 08:00:00"),
        mrn="CHO10006", family="Miller", given="James", middle=None, gender="M", birth="1990-04-02",
        line="88 Pine St", city="Rivergate", state="OR", postal="97001", phone="5035550106", ssn="900-55-1006",
    ), stream=True, bulk=True)


def _grants(b: _Builder) -> None:
    _simple_hl7_person(
        b, source="AMC", mrn="AMC10007", family="Grant", given="Olivia", birth="1988-02-02 00:00:00",
        gender="F", line="50 Market St", city="Alderbrook", postal="97701", ssn=None,
        when="2026-04-01 12:00:00", phone="5035550107", visit="V-OLIVIA",
    )
    _simple_hl7_person(
        b, source="RGH", mrn="RGH10008", family="Grant", given="Noah", birth="1988-07-19 00:00:00",
        gender="M", line="77 Market St", city="Alderbrook", postal="97701", ssn=None,
        when="2026-04-02 12:00:00", phone="5035550108", visit="V-NOAH",
    )


def _stay(b, source, mrn, family, given, birth, gender, line, city, postal, ssn, phone, visit, admit, discharge, patient_class="I"):
    event_admit, event_discharge = stamp(admit), stamp(discharge)
    common = dict(
        source=source, mrn=mrn, family=family, given=given, middle=None, birth=stamp(birth).date(),
        gender=gender, line=line, city=city, state="OR", postal=postal, phone=phone, ssn=ssn,
    )
    b.hl7(source, admit, render_adt(
        trigger="A01", control=b.control(), event_time=event_admit, visit=visit, patient_class=patient_class,
        admit=event_admit, **common,
    ))
    b.hl7(source, discharge, render_adt(
        trigger="A03", control=b.control(), event_time=event_discharge, visit=visit, patient_class=patient_class,
        admit=event_admit, discharge=event_discharge, **common,
    ))


def _marcus(b: _Builder) -> None:
    shared = dict(
        source="AMC", mrn="AMC10009", family="Hale", given="Marcus", birth="1976-06-06 00:00:00", gender="M",
        line="3 Depot Ave", city="Rivergate", postal="97001", ssn="900-55-1009", phone="5035550109",
    )
    _stay(b, visit="V-MARCUS-1", admit="2026-05-01 09:00:00", discharge="2026-05-01 18:00:00", **shared)
    _stay(b, visit="V-MARCUS-2", admit="2026-06-20 10:00:00", discharge="2026-06-22 10:00:00", **shared)


def _june(b: _Builder) -> None:
    shared = dict(
        source="AMC", mrn="AMC10010", family="Pell", given="June", birth="1958-09-09 00:00:00", gender="F",
        line="14 Birch Dr", city="Hearth", postal="97703", ssn="900-55-1010", phone="5035550110",
    )
    _stay(b, visit="V-JUNE-1", admit="2026-09-01 00:00:00", discharge="2026-09-01 08:00:00", **shared)
    _stay(b, visit="V-JUNE-2", admit="2026-10-01 08:00:00", discharge="2026-10-03 08:00:00", **shared)


def _luis(b: _Builder) -> None:
    _stay(
        b, source="AMC", mrn="AMC10011", family="Ortega", given="Luis", birth="1983-01-19 00:00:00", gender="M",
        line="6 Canyon Rd", city="Alderbrook", postal="97702", ssn="900-55-1011", phone="5035550111",
        visit="V-LUIS-AMC", admit="2026-07-08 08:00:00", discharge="2026-07-10 08:00:00",
    )
    patient = fhir_patient(
        source="RGH", fhir_id="rgh-luis", version="1", updated=stamp("2026-07-10 09:00:00"),
        mrn="RGH10011", family="Ortega", given="Luis", middle=None, gender="M", birth="1983-01-19",
        line="6 Canyon Road", city="Alderbrook", state="OR", postal="97702", phone="5035550111", ssn="900-55-1011",
    )
    b.fhir("RGH", "2026-07-10 09:00:00", patient, stream=True, bulk=True)
    b.fhir("RGH", "2026-07-12 15:00:00", fhir_encounter(
        source="RGH", enc_id="enc-luis-rgh", patient_id="rgh-luis", status="finished", class_code="IMP",
        start=stamp("2026-07-10 14:00:00"), end=stamp("2026-07-12 15:00:00"), visit="V-LUIS-RGH",
        updated=stamp("2026-07-12 15:00:00"),
    ), stream=True, bulk=True)


def _ruth(b: _Builder) -> None:
    _simple_hl7_person(
        b, source="AMC", mrn="AMC10012", family="Eng", given="Ruth", birth="1966-02-14 00:00:00", gender="F",
        line="21 Cedar Ct", city="Hearth", postal="97703", ssn="900-55-1012", when="2026-01-15 10:00:00",
        phone="5035550112", visit="V-RUTH-1", diagnoses=[{"code": "E119", "display": "Type 2 diabetes mellitus"}],
    )
    birth = stamp("1966-02-14 00:00:00").date()
    b.hl7("AMC", "2026-01-15 11:00:00", render_oru(
        source="AMC", control=b.control(), event_time=stamp("2026-01-15 11:00:00"), visit="V-RUTH-1",
        code="4548-4", display="Hemoglobin A1c", system="LN", value="8.4", unit="%", low="4.0", high="5.6",
        flag="H", observed=stamp("2026-01-15 11:00:00"),
        mrn="AMC10012", family="Eng", given="Ruth", birth=birth, gender="F",
        line="21 Cedar Ct", city="Hearth", state="OR", postal="97703", phone="5035550112", ssn="900-55-1012",
    ))


def _samir(b: _Builder) -> None:
    b.fhir("CHO", "2026-09-12 09:00:00", fhir_patient(
        source="CHO", fhir_id="cho-samir", version="1", updated=stamp("2026-09-12 09:00:00"),
        mrn="CHO10013", family="Qureshi", given="Samir", middle=None, gender="M", birth="1972-08-08",
        line="5 Orchard Pl", city="Cedar Hollow", state="OR", postal="97708", phone="5035550113", ssn="900-55-1013",
    ), stream=True, bulk=True)
    b.fhir("CHO", "2026-09-12 09:05:00", fhir_condition(
        cond_id="cond-samir-dm", patient_id="cho-samir", code="44054006", system=SNOMED,
        display="Type 2 diabetes mellitus", onset=stamp("2021-01-01 00:00:00"),
    ), stream=True, bulk=True)
    b.fhir("CHO", "2026-09-12 09:10:00", fhir_observation(
        obs_id="obs-samir-a1c", patient_id="cho-samir", encounter_id=None, code="4548-4", system=LOINC,
        display="Hemoglobin A1c", value=7.1, unit="%", low=4.0, high=5.6, flag="H",
        observed=stamp("2026-09-12 09:10:00"),
    ), stream=True, bulk=True)
    b.fhir("CHO", "2026-06-01 09:00:00", fhir_medication(
        med_id="med-samir-met", patient_id="cho-samir", code="860975", display="metformin 500 MG Oral Tablet",
        authored=stamp("2026-06-01 09:00:00"),
    ), stream=True, bulk=True)


def _nora(b: _Builder) -> None:
    _simple_hl7_person(
        b, source="AMC", mrn="AMC10014", family="Keene", given="Nora", birth="1975-05-05 00:00:00", gender="F",
        line="80 Hill St", city="Alderbrook", postal="97701", ssn="900-55-1014", when="2026-04-18 14:00:00",
        phone="5035550114", visit="V-NORA-1", diagnoses=[{"code": "I10", "display": "Essential hypertension"}],
    )
    b.fhir("CHO", "2026-04-19 09:00:00", fhir_patient(
        source="CHO", fhir_id="cho-nora", version="1", updated=stamp("2026-04-19 09:00:00"),
        mrn="CHO10014", family="Keene", given="Nora", middle=None, gender="F", birth="1975-05-05",
        line="80 Hill Street", city="Alderbrook", state="OR", postal="97701", phone="5035550114", ssn="900-55-1014",
    ), stream=True, bulk=True)
    b.fhir("CHO", "2026-04-19 09:10:00", fhir_medication(
        med_id="med-nora-lis", patient_id="cho-nora", code="314076",
        display="lisinopril 10 MG Oral Tablet", authored=stamp("2026-04-19 09:10:00"),
    ), stream=True, bulk=True)


def _owen(b: _Builder) -> None:
    b.fhir("RGH", "2026-08-08 08:00:00", fhir_patient(
        source="RGH", fhir_id="rgh-owen", version="1", updated=stamp("2026-08-08 08:00:00"),
        mrn="RGH10015", family="Park", given="Owen", middle=None, gender="M", birth="1969-09-09",
        line="2 Ferry St", city="Rivergate", state="OR", postal="97001", phone="5035550116", ssn="900-55-1016",
    ), stream=True, bulk=True)
    b.fhir("RGH", "2026-08-08 08:05:00", fhir_condition(
        cond_id="cond-owen-htn", patient_id="rgh-owen", code="I10", system=ICD10,
        display="Essential hypertension", onset=stamp("2019-01-01 00:00:00"),
    ), stream=True, bulk=True)
    b.fhir("RGH", "2026-08-08 08:20:00", fhir_observation(
        obs_id="obs-owen-sbp", patient_id="rgh-owen", encounter_id=None, code="8480-6", system=LOINC,
        display="Systolic blood pressure", value=128, unit="mm[Hg]", low=90, high=120, flag="H",
        observed=stamp("2026-08-08 08:20:00"),
    ), stream=True, bulk=True)


def _willa(b: _Builder) -> None:
    when = stamp("2026-06-02 09:00:00")
    b.hl7("AMC", "2026-06-02 09:00:00", render_adt(
        source="AMC", trigger="A04", control=b.control(), event_time=when, mrn="AMC10015", family="Brooks",
        given="Willa", middle=None, birth=stamp("1988-12-12 00:00:00").date(), gender="F",
        line="12 Pine & Oak St", city="Alderbrook", state="OR", postal="97702", phone="5035550115", ssn=None,
        visit="V-WILLA-1", patient_class="O", admit=when,
        note=r"Room request\.br\near window",
    ))


def _quinn(b: _Builder) -> None:
    birth = stamp("1991-03-03 00:00:00").date()
    _simple_hl7_person(
        b, source="AMC", mrn="AMC10016", family="Adler", given="Quinn", birth="1991-03-03 00:00:00", gender="O",
        line="19 West Ln", city="Alderbrook", postal="97702", ssn="900-55-1017", when="2026-06-06 10:00:00",
        phone="5035550117", visit="V-QUINN-1",
    )
    b.hl7("AMC", "2026-06-06 10:30:00", render_oru(
        source="AMC", control=b.control(), event_time=stamp("2026-06-06 10:30:00"), visit="V-QUINN-1",
        code="ZZZ-NOT-A-CODE", display="Local panel", system="L", value="4", unit="arb", low=None, high=None,
        flag=None, observed=stamp("2026-06-06 10:30:00"),
        mrn="AMC10016", family="Adler", given="Quinn", birth=birth, gender="O",
        line="19 West Ln", city="Alderbrook", state="OR", postal="97702", phone="5035550117", ssn="900-55-1017",
    ))


def _yuri(b: _Builder) -> None:
    b.fhir("CHO", "2026-07-01 12:00:00", fhir_patient(
        source="CHO", fhir_id="cho-yuri", version="1", updated=stamp("2026-07-01 12:00:00"),
        mrn="CHO10018", family="Nash", given="Yuri", middle=None, gender="M", birth="1984",
        line=None, city=None, state=None, postal=None, phone=None, ssn=None,
    ), stream=True, bulk=True)


def _fillers(builder: _Builder, count: int) -> None:
    last_names = [
        "Halewood", "Brickman", "Ibarra", "Yamamoto", "Petrov", "Okafor", "Bergstrand",
        "Macleod", "Ferreira", "Dunlevy", "Haddad", "Basu",
    ]
    sources = ["AMC", "RGH", "CHO"]
    for index in range(count):
        source = sources[index % 3]
        family = last_names[index]
        given = "Avery" if index % 2 == 0 else "Rowan"
        month = (index % 8) + 1
        day = (index % 20) + 1
        birth_text = f"{1970 + index:04d}-{month:02d}-{day:02d}"
        when = f"2026-{(index % 9) + 1:02d}-{10 + (index % 8):02d} 10:00:00"
        if source == "AMC":
            _simple_hl7_person(
                builder, source="AMC", mrn=f"AMC20{index:03d}", family=family, given=given,
                birth=birth_text + " 00:00:00", gender="F" if index % 2 == 0 else "M",
                line=f"{100 + index} Fixture St", city="Alderbrook", postal="97709",
                ssn=f"900-55-2{index:03d}", when=when, phone=f"5035552{index:03d}", visit=f"V-FILL-{index}",
            )
        else:
            builder.fhir(source, when, fhir_patient(
                source=source, fhir_id=f"{source.lower()}-fill-{index}", version="1", updated=stamp(when),
                mrn=f"{source}20{index:03d}", family=family, given=given, middle=None,
                gender="F" if index % 2 == 0 else "M", birth=birth_text,
                line=f"{100 + index} Fixture St", city="Alderbrook", state="OR", postal="97709",
                phone=f"5035552{index:03d}", ssn=f"900-55-2{index:03d}",
            ), stream=True, bulk=True)


def _defects(b: _Builder) -> None:
    # Retransmit of the first backfill message under a new transport id.
    original = b.backfill[0]
    b.hl7("AMC", original["event_time"], original["body"], event_id="strm-retransmit-elena")
    # Same transport id replayed by Relayline.
    replay = dict(original)
    b.backfill.append(replay)
    # No family name: reaches DQ rather than the parser.
    when = stamp("2026-05-05 05:05:00")
    b.hl7("AMC", "2026-05-05 05:05:00", render_adt(
        source="AMC", trigger="A04", control=b.control(), event_time=when, mrn="AMC19990", family="",
        given="", middle=None, birth=stamp("1981-01-01 00:00:00").date(), gender="F", line="1 Blank St",
        city="Alderbrook", state="OR", postal="97701", phone=None, ssn=None, visit="V-NONAME",
        patient_class="O", admit=when,
    ))
    b.hl7("AMC", "2026-05-05 05:06:00", render_adt(
        source="AMC", trigger="A04", control=b.control(), event_time=stamp("2026-05-05 05:06:00"),
        mrn="AMC19991", family="Future", given="Pat", middle=None, birth=stamp("2031-01-01 00:00:00").date(),
        gender="M", line="2 Later St", city="Alderbrook", state="OR", postal="97701", phone=None, ssn=None,
        visit="V-FUTURE", patient_class="O", admit=stamp("2026-05-05 05:06:00"),
    ))
    b.hl7("AMC", "2026-05-05 05:07:00", render_adt(
        source="AMC", trigger="A04", control=b.control(), event_time=stamp("2026-05-05 05:07:00"),
        mrn="AMC19992", family="Glyph", given="Pat", middle=None, birth=stamp("1982-02-02 00:00:00").date(),
        gender="X9", line="3 Odd St", city="Alderbrook", state="OR", postal="97701", phone=None, ssn=None,
        visit="V-GENDER", patient_class="O", admit=stamp("2026-05-05 05:07:00"),
    ))
    b.hl7("AMC", "2026-05-05 05:08:00", render_adt(
        source="AMC", trigger="A01", control=b.control(), event_time=stamp("2026-05-05 05:08:00"),
        mrn="AMC19993", family="Inverted", given="Pat", middle=None, birth=stamp("1983-03-03 00:00:00").date(),
        gender="F", line="4 Time St", city="Alderbrook", state="OR", postal="97701", phone=None, ssn=None,
        visit="V-INVERT", patient_class="I", admit=stamp("2026-05-06 05:08:00"), discharge=stamp("2026-05-05 05:08:00"),
    ))
    birth = stamp("1984-04-04 00:00:00").date()
    _simple_hl7_person(
        b, source="AMC", mrn="AMC19994", family="Spike", given="Pat", birth="1984-04-04 00:00:00", gender="M",
        line="5 Lab St", city="Alderbrook", postal="97701", ssn=None, when="2026-05-05 05:09:00",
        phone=None, visit="V-SPIKE",
    )
    b.hl7("AMC", "2026-05-05 05:09:30", render_oru(
        source="AMC", control=b.control(), event_time=stamp("2026-05-05 05:09:30"), visit="V-SPIKE",
        code="2345-7", display="Glucose", system="LN", value="4000", unit="mg/dL", low="70", high="99",
        flag="H", observed=stamp("2026-05-05 05:09:30"),
        mrn="AMC19994", family="Spike", given="Pat", birth=birth, gender="M",
        line="5 Lab St", city="Alderbrook", state="OR", postal="97701", phone=None, ssn=None,
    ))
    b.hl7("AMC", "2026-05-05 05:10:00", render_adt(
        source="AMC", trigger="A04", control=b.control(), event_time=stamp("2026-05-05 05:10:00"),
        mrn="AMC19995", family="Imported", given="Pat", middle=None, birth=stamp("1985-05-05 00:00:00").date(),
        gender="F", line="6 Realish St", city="Alderbrook", state="OR", postal="97701", phone=None,
        ssn="123-45-6789", visit="V-NONSYNTH", patient_class="O", admit=stamp("2026-05-05 05:10:00"),
    ))
    b.hl7("AMC", "2026-05-05 05:11:00", "THIS IS NOT HL7")
    b.hl7("CHO", "2026-05-05 05:12:00", "MSH|^~\\&|LUMEN|CHO|NORTHLINE|ALDERBROOK|20260505051200||ADT^A04|MSGDUP|P|2.5\rMSH|^~\\&|LUMEN|CHO|NORTHLINE|ALDERBROOK|20260505051200||ADT^A04|MSGDUP2|P|2.5\r")
    b.fhir("RGH", "2026-05-05 05:13:00", {"resourceType": "Observation", "id": "bad-obs", "status": "final"}, stream=True, bulk=False)
    b.backfill.append(
        {
            "source_system": "AMC",
            "payload_type": "HL7_V2",
            "event_time": "not-a-timestamp",
            "partition": 0,
            "offset": 99999,
            "body": "MSH|",
        }
    )


def _anchor_and_delay(b: _Builder) -> None:
    birth = stamp("1979-04-12 00:00:00").date()
    shared = dict(
        mrn="AMC10001", family="Voss", given="Elena", birth=birth, gender="F", line="100 Main St",
        city="Alderbrook", state="OR", postal="97701", phone="5035550101", ssn="900-55-1001",
    )
    b.hl7("AMC", ANCHOR, render_oru(
        source="AMC", control=b.control(), event_time=stamp(ANCHOR), visit="V-ELENA-2",
        code="2160-0", display="Creatinine", system="LN", value="1.1", unit="mg/dL", low="0.6", high="1.3",
        flag=None, observed=stamp(ANCHOR), **shared,
    ))
    b.hl7("AMC", LATE, render_oru(
        source="AMC", control=b.control(), event_time=stamp(LATE), visit="V-ELENA-2",
        code="1742-6", display="ALT", system="LN", value="62", unit="U/L", low="7", high="56",
        flag="H", observed=stamp(LATE), **shared,
    ), wave="delayed")
    b.hl7("AMC", FOLLOWING, render_oru(
        source="AMC", control=b.control(), event_time=stamp(FOLLOWING), visit="V-ELENA-2",
        code="718-7", display="Hemoglobin", system="LN", value="13.4", unit="g/dL", low="12.0", high="17.5",
        flag=None, observed=stamp(FOLLOWING), **shared,
    ), wave="delayed")


def _guard_clock(builder: _Builder) -> None:
    anchor = stamp(ANCHOR)
    for row in builder.backfill:
        if "event_id" not in row:
            continue
        try:
            seen = stamp(row["event_time"])
        except ValueError:
            continue
        if seen > anchor:
            raise RuntimeError(f"backfill event {row['event_id']} is after the watermark anchor")


def _dump(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
