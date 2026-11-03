"""Render HL7 v2 messages and FHIR R4 resources for the fictional population."""

from __future__ import annotations

from datetime import date, datetime

APP = {"AMC": "VISTARA", "RGH": "LUMEN", "CHO": "LUMEN"}
ATTENDING = {
    "AMC": {"id": "SYNTH-PRAC-AMC", "family": "Okonkwo", "given": "Ada"},
    "RGH": {"id": "SYNTH-PRAC-RGH", "family": "Ellison", "given": "Jonah"},
    "CHO": {"id": "SYNTH-PRAC-CHO", "family": "Raman", "given": "Priya"},
}
GENDER = {"M": "male", "F": "female", "O": "other", "U": "unknown"}
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"


def hl7_ts(value: datetime | date) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d%H%M%S")
    return value.strftime("%Y%m%d")


def iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def escape(value: str | None) -> str:
    text = value or ""
    return (
        text.replace("\\", "\\E\\")
        .replace("|", "\\F\\")
        .replace("^", "\\S\\")
        .replace("&", "\\T\\")
        .replace("~", "\\R\\")
    )


def render_adt(
    *,
    source: str,
    trigger: str,
    control: str,
    event_time: datetime,
    mrn: str,
    family: str,
    given: str,
    middle: str | None,
    birth: date | None,
    gender: str,
    line: str | None,
    city: str | None,
    state: str | None,
    postal: str | None,
    phone: str | None,
    ssn: str | None,
    visit: str | None = None,
    patient_class: str = "I",
    admit: datetime | None = None,
    discharge: datetime | None = None,
    diagnoses: list[dict] | None = None,
    allergies: list[dict] | None = None,
    note: str | None = None,
    birth_raw: str | None = None,
) -> str:
    segments = [
        f"MSH|^~\\&|{APP[source]}|{source}|NORTHLINE|ALDERBROOK|{hl7_ts(event_time)}||ADT^{trigger}|{control}|P|2.5",
        f"EVN|{trigger}|{hl7_ts(event_time)}",
    ]
    pid3 = f"{escape(mrn)}^^^{source}^MR"
    if ssn:
        pid3 += "~" + escape("".join(ch for ch in ssn if ch.isdigit())) + "^^^USSSA^SS"
    dob = birth_raw if birth_raw is not None else (hl7_ts(birth) if birth else "")
    segments.append(
        "PID|1||"
        + pid3
        + "||"
        + f"{escape(family)}^{escape(given)}^{escape(middle)}"
        + "||"
        + dob
        + "|"
        + (gender or "")
        + "|||"
        + f"{escape(line)}^^{escape(city)}^{escape(state)}^{escape(postal)}||{escape(phone)}"
    )
    if visit:
        attending = ATTENDING[source]
        fields = [""] * 45
        fields[0] = "1"
        fields[1] = patient_class
        fields[2] = "MED^101^A"
        fields[6] = f"{attending['id']}^{escape(attending['family'])}^{escape(attending['given'])}"
        fields[18] = visit
        fields[43] = hl7_ts(admit) if admit else ""
        fields[44] = hl7_ts(discharge) if discharge else ""
        segments.append("PV1|" + "|".join(fields))
    for index, diagnosis in enumerate(diagnoses or [], start=1):
        segments.append(
            f"DG1|{index}||{diagnosis['code']}^{escape(diagnosis['display'])}^{diagnosis.get('system', 'I10')}|||A"
        )
    for index, allergy in enumerate(allergies or [], start=1):
        segments.append(
            f"AL1|{index}|DA|{escape(allergy['code'])}^{escape(allergy['display'])}^L|{allergy.get('severity', 'SV')}"
        )
    if note:
        segments.append(f"NTE|1||{note}")
    return "\r".join(segments) + "\r"


def render_oru(
    *,
    source: str,
    control: str,
    event_time: datetime,
    mrn: str,
    family: str,
    given: str,
    birth: date,
    gender: str,
    line: str | None,
    city: str | None,
    state: str | None,
    postal: str | None,
    phone: str | None,
    ssn: str | None,
    visit: str | None,
    code: str,
    display: str,
    system: str,
    value: str,
    unit: str,
    low: str | None,
    high: str | None,
    flag: str | None,
    observed: datetime,
) -> str:
    pid3 = f"{escape(mrn)}^^^{source}^MR"
    if ssn:
        pid3 += "~" + escape("".join(ch for ch in ssn if ch.isdigit())) + "^^^USSSA^SS"
    segments = [
        f"MSH|^~\\&|{APP[source]}|{source}|NORTHLINE|ALDERBROOK|{hl7_ts(event_time)}||ORU^R01|{control}|P|2.5",
        "PID|1||"
        + pid3
        + "||"
        + f"{escape(family)}^{escape(given)}^"
        + "||"
        + hl7_ts(birth)
        + "|"
        + gender
        + "|||"
        + f"{escape(line)}^^{escape(city)}^{escape(state)}^{escape(postal)}||{escape(phone)}",
    ]
    if visit:
        segments.append(f"PV1|1|I|MED^101^A||||||||||||||||{visit}")
    segments.append(f"OBR|1|{control}||{code}^{escape(display)}^{system}|||{hl7_ts(observed)}")
    fields = [""] * 14
    fields[0] = "1"
    fields[1] = "NM"
    fields[2] = f"{code}^{escape(display)}^{system}"
    fields[4] = value
    fields[5] = unit
    fields[6] = f"{low}-{high}" if low and high else ""
    fields[7] = flag or ""
    fields[10] = "F"
    fields[13] = hl7_ts(observed)
    segments.append("OBX|" + "|".join(fields))
    return "\r".join(segments) + "\r"


def fhir_patient(
    *,
    source: str,
    fhir_id: str,
    version: str,
    updated: datetime,
    mrn: str,
    family: str,
    given: str,
    middle: str | None,
    gender: str,
    birth: str | None,
    line: str | None,
    city: str | None,
    state: str | None,
    postal: str | None,
    phone: str | None,
    ssn: str | None,
) -> dict:
    identifiers = [
        {
            "system": f"http://alderbrook.example/mrn/{source}",
            "value": mrn,
            "type": {"coding": [{"code": "MR"}]},
        }
    ]
    if ssn:
        identifiers.append({"system": "http://hl7.org/fhir/sid/us-ssn", "value": ssn})
    given_names = [given] if given else []
    if middle:
        given_names.append(middle)
    resource = {
        "resourceType": "Patient",
        "id": fhir_id,
        "meta": {"versionId": version, "lastUpdated": iso(updated)},
        "identifier": identifiers,
        "name": [{"use": "official", "family": family, "given": given_names}],
        "gender": GENDER.get(gender, gender),
        "extension": [
            {
                "url": "http://alderbrook.example/fhir/StructureDefinition/source-ehr",
                "valueString": "LumenClinic" if source != "AMC" else "Vistara Chart",
            }
        ],
    }
    if birth:
        resource["birthDate"] = birth
    if line:
        resource["address"] = [{"line": [line], "city": city, "state": state, "postalCode": postal}]
    if phone:
        resource["telecom"] = [{"system": "phone", "value": phone}]
    return resource


def fhir_encounter(
    *,
    source: str,
    enc_id: str,
    patient_id: str,
    status: str,
    class_code: str,
    start: datetime,
    end: datetime | None,
    visit: str,
    updated: datetime,
) -> dict:
    period = {"start": iso(start)}
    if end:
        period["end"] = iso(end)
    return {
        "resourceType": "Encounter",
        "id": enc_id,
        "meta": {"versionId": "1", "lastUpdated": iso(updated)},
        "status": status,
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": class_code},
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": period,
        "identifier": [{"system": f"http://alderbrook.example/visit/{source}", "value": visit}],
        "participant": [{"individual": {"reference": f"Practitioner/{ATTENDING[source]['id']}"}}],
        "serviceProvider": {"reference": f"Organization/org-{source.lower()}"},
    }


def fhir_observation(
    *,
    obs_id: str,
    patient_id: str,
    encounter_id: str | None,
    code: str,
    system: str,
    display: str,
    value: float,
    unit: str,
    low: float | None,
    high: float | None,
    flag: str | None,
    observed: datetime,
) -> dict:
    resource = {
        "resourceType": "Observation",
        "id": obs_id,
        "meta": {"versionId": "1", "lastUpdated": iso(observed)},
        "status": "final",
        "code": {"coding": [{"system": system, "code": code, "display": display}], "text": display},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": iso(observed),
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org"},
    }
    if encounter_id:
        resource["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    if low is not None and high is not None:
        resource["referenceRange"] = [{"low": {"value": low}, "high": {"value": high}}]
    if flag:
        resource["interpretation"] = [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "code": flag}]}]
    return resource


def fhir_condition(*, cond_id: str, patient_id: str, code: str, system: str, display: str, onset: datetime) -> dict:
    return {
        "resourceType": "Condition",
        "id": cond_id,
        "meta": {"versionId": "1", "lastUpdated": iso(onset)},
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "code": {"coding": [{"system": system, "code": code, "display": display}], "text": display},
        "subject": {"reference": f"Patient/{patient_id}"},
        "onsetDateTime": iso(onset),
    }


def fhir_medication(*, med_id: str, patient_id: str, code: str, display: str, authored: datetime) -> dict:
    return {
        "resourceType": "MedicationRequest",
        "id": med_id,
        "meta": {"versionId": "1", "lastUpdated": iso(authored)},
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [{"system": RXNORM, "code": code, "display": display}]
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": iso(authored),
    }


def fhir_allergy(*, allergy_id: str, patient_id: str, substance: str, updated: datetime) -> dict:
    return {
        "resourceType": "AllergyIntolerance",
        "id": allergy_id,
        "meta": {"versionId": "1", "lastUpdated": iso(updated)},
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "criticality": "high",
        "code": {"text": substance},
        "patient": {"reference": f"Patient/{patient_id}"},
    }


def reference_resources() -> dict[str, list[dict]]:
    practitioners = []
    organizations = []
    for source, attending in ATTENDING.items():
        practitioners.append(
            {
                "resourceType": "Practitioner",
                "id": attending["id"],
                "meta": {"versionId": "1", "lastUpdated": "2026-01-01T00:00:00Z"},
                "identifier": [{"system": "http://alderbrook.example/practitioner", "value": attending["id"]}],
                "name": [{"family": attending["family"], "given": [attending["given"]]}],
            }
        )
        organizations.append(
            {
                "resourceType": "Organization",
                "id": f"org-{source.lower()}",
                "meta": {"versionId": "1", "lastUpdated": "2026-01-01T00:00:00Z"},
                "identifier": [{"system": "http://alderbrook.example/facility", "value": source}],
                "name": {
                    "AMC": "Alderbrook Medical Center",
                    "RGH": "Rivergate Community Hospital",
                    "CHO": "Cedar Hollow Outpatient",
                }[source],
                "type": [{"coding": [{"code": "prov"}]}],
            }
        )
    return {"Practitioner": practitioners, "Organization": organizations}
