"""Flatten FHIR R4 resources, including extensions and codeable concepts."""

from __future__ import annotations

from acn_interop.interpret.dates import parse_date_only, parse_iso_datetime
from acn_interop.interpret.fhir_validate import _encounter_class, _mrn, _reference

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"


def extract_fhir(resource: dict, meta: dict) -> dict[str, list[dict]]:
    resource_type = resource.get("resourceType")
    handler = {
        "Patient": _patient,
        "Encounter": _encounter,
        "Observation": _observation,
        "Condition": _condition,
        "MedicationRequest": _medication,
        "AllergyIntolerance": _allergy,
        "Practitioner": _practitioner,
        "Organization": _organization,
    }[resource_type]
    row = handler(resource, meta)
    bucket = {
        "Patient": "persons",
        "Encounter": "encounters",
        "Observation": "observations",
        "Condition": "conditions",
        "MedicationRequest": "medications",
        "AllergyIntolerance": "allergies",
        "Practitioner": "practitioners",
        "Organization": "organizations",
    }[resource_type]
    empty = {name: [] for name in (
        "persons", "encounters", "observations", "conditions", "medications",
        "allergies", "practitioners", "organizations",
    )}
    empty[bucket] = [row]
    return empty


def extension_map(resource: dict) -> dict[str, str]:
    found = {}
    for extension in resource.get("extension") or []:
        url = extension.get("url") or ""
        key = url.rstrip("/").split("/")[-1]
        for candidate in ("valueString", "valueCode", "valueDateTime", "valueUri"):
            if extension.get(candidate) is not None:
                found[key] = str(extension[candidate])
                break
    return found


def _prefer(concept: dict | None, system_tokens: tuple[str, ...]) -> dict:
    codings = (concept or {}).get("coding") or []
    for token in system_tokens:
        for coding in codings:
            if token in (coding.get("system") or ""):
                return coding
    return codings[0] if codings else {}


def _common(resource: dict, meta: dict, key: str) -> dict:
    version = ((resource.get("meta") or {}).get("versionId")) or "1"
    effective = parse_iso_datetime((resource.get("meta") or {}).get("lastUpdated")) or meta["event_time"]
    return {
        "source_system": meta["source_system"],
        "source_format": "FHIR_R4",
        "message_key": f"{meta['source_system']}|{resource.get('resourceType')}|{resource.get('id')}|{version}|{key}",
        "effective_time": effective,
        "event_id": meta["event_id"],
        "ingest_time": meta["ingest_time"],
        "extensions": extension_map(resource),
    }


def _patient(resource: dict, meta: dict) -> dict:
    name = (resource.get("name") or [{}])[0]
    given = name.get("given") or []
    address = (resource.get("address") or [{}])[0]
    lines = address.get("line") or []
    telecom = resource.get("telecom") or []
    phone = next((item.get("value") for item in telecom if item.get("system") == "phone"), None)
    ssn = None
    for identifier in resource.get("identifier") or []:
        system = identifier.get("system") or ""
        if system.endswith("us-ssn") or system.endswith("/ssn"):
            ssn = "".join(ch for ch in (identifier.get("value") or "") if ch.isdigit())
    common = _common(resource, meta, "patient")
    birth_raw = resource.get("birthDate")
    return {
        **{k: v for k, v in common.items() if k != "extensions"},
        "source_person_id": _mrn(resource),
        "vendor_record_id": resource.get("id"),
        "family_name": name.get("family"),
        "given_name": given[0] if given else None,
        "middle_name": given[1] if len(given) > 1 else None,
        "birth_date": parse_date_only(birth_raw),
        "birth_date_raw": birth_raw,
        "gender": _gender(resource.get("gender")),
        "address_line": lines[0] if lines else None,
        "city": address.get("city"),
        "state": address.get("state"),
        "postal_code": address.get("postalCode"),
        "phone": phone,
        "ssn": ssn,
        "facility_id": meta["source_system"],
        "ehr_product": common["extensions"].get("source-ehr"),
        "fhir_patient_id": resource.get("id"),
        "demographic_authority": True,
    }


def _encounter(resource: dict, meta: dict) -> dict:
    period = resource.get("period") or {}
    participant = (resource.get("participant") or [{}])[0]
    individual = participant.get("individual") or {}
    attending_ref = individual.get("reference") or ""
    attending_id = attending_ref.split("/")[-1] if attending_ref else None
    identifier = (resource.get("identifier") or [{}])[0]
    reason = (resource.get("reasonCode") or [{}])[0]
    common = _common(resource, meta, "encounter")
    return {
        **{k: v for k, v in common.items() if k != "extensions"},
        "source_encounter_id": identifier.get("value") or resource.get("id"),
        "source_person_id": None,
        "fhir_patient_id": _reference(resource.get("subject")),
        "class_code": _encounter_class(resource),
        "status": resource.get("status") or "unknown",
        "admit_time": parse_iso_datetime(period.get("start")),
        "discharge_time": parse_iso_datetime(period.get("end")),
        "facility_id": meta["source_system"],
        "attending_id": attending_id,
        "attending_family": None,
        "attending_given": None,
        "reason_text": reason.get("text"),
    }


def _observation(resource: dict, meta: dict) -> dict:
    coding = _prefer(resource.get("code"), (LOINC,))
    quantity = resource.get("valueQuantity") or {}
    ref = (resource.get("referenceRange") or [{}])[0]
    low = ((ref.get("low") or {}).get("value"))
    high = ((ref.get("high") or {}).get("value"))
    interpretation = (((resource.get("interpretation") or [{}])[0]).get("coding") or [{}])[0]
    encounter_ref = _reference(resource.get("encounter"))
    common = _common(resource, meta, coding.get("code") or "obs")
    value = quantity.get("value")
    return {
        **{k: v for k, v in common.items() if k != "extensions"},
        "source_observation_id": resource.get("id"),
        "source_person_id": None,
        "fhir_patient_id": _reference(resource.get("subject")),
        "source_encounter_id": encounter_ref,
        "local_code": coding.get("code"),
        "local_system": coding.get("system"),
        "display": coding.get("display") or (resource.get("code") or {}).get("text"),
        "value_numeric": float(value) if isinstance(value, (int, float)) else None,
        "value_text": None if isinstance(value, (int, float)) else resource.get("valueString"),
        "value_unit": quantity.get("unit"),
        "ref_low": float(low) if isinstance(low, (int, float)) else None,
        "ref_high": float(high) if isinstance(high, (int, float)) else None,
        "abnormal_flag": interpretation.get("code"),
        "effective_time": parse_iso_datetime(resource.get("effectiveDateTime")) or common["effective_time"],
        "status": resource.get("status"),
    }


def _condition(resource: dict, meta: dict) -> dict:
    coding = _prefer(resource.get("code"), (SNOMED, ICD10, "icd-10"))
    common = _common(resource, meta, coding.get("code") or "condition")
    onset = resource.get("onsetDateTime")
    clinical = ((resource.get("clinicalStatus") or {}).get("coding") or [{}])[0]
    return {
        **{k: v for k, v in common.items() if k != "extensions"},
        "source_condition_id": resource.get("id"),
        "source_person_id": None,
        "fhir_patient_id": _reference(resource.get("subject")),
        "local_code": coding.get("code"),
        "local_system": coding.get("system"),
        "display": coding.get("display") or (resource.get("code") or {}).get("text"),
        "clinical_status": clinical.get("code") or "active",
        "onset_time": parse_iso_datetime(onset),
    }


def _medication(resource: dict, meta: dict) -> dict:
    coding = _prefer(resource.get("medicationCodeableConcept"), (RXNORM,))
    common = _common(resource, meta, coding.get("code") or "med")
    return {
        **{k: v for k, v in common.items() if k != "extensions"},
        "source_medication_id": resource.get("id"),
        "source_person_id": None,
        "fhir_patient_id": _reference(resource.get("subject")),
        "local_code": coding.get("code"),
        "local_system": coding.get("system"),
        "display": coding.get("display"),
        "status": resource.get("status"),
        "authored_time": parse_iso_datetime(resource.get("authoredOn")) or common["effective_time"],
    }


def _allergy(resource: dict, meta: dict) -> dict:
    coding = _prefer(resource.get("code"), (SNOMED,))
    common = _common(resource, meta, coding.get("code") or "allergy")
    return {
        **{k: v for k, v in common.items() if k != "extensions"},
        "source_allergy_id": resource.get("id"),
        "source_person_id": None,
        "fhir_patient_id": _reference(resource.get("patient")),
        "substance": coding.get("display") or (resource.get("code") or {}).get("text"),
        "criticality": resource.get("criticality"),
        "clinical_status": (((resource.get("clinicalStatus") or {}).get("coding") or [{}])[0]).get("code") or "active",
    }


def _practitioner(resource: dict, meta: dict) -> dict:
    name = (resource.get("name") or [{}])[0]
    given = name.get("given") or []
    return {
        "source_system": meta["source_system"],
        "practitioner_id": resource.get("id"),
        "family_name": name.get("family"),
        "given_name": given[0] if given else None,
        "source_format": "FHIR_R4",
    }


def _organization(resource: dict, meta: dict) -> dict:
    org_type = (((resource.get("type") or [{}])[0]).get("coding") or [{}])[0]
    identifier = (resource.get("identifier") or [{}])[0]
    return {
        "source_system": identifier.get("value") or meta["source_system"],
        "organization_id": resource.get("id"),
        "name": resource.get("name"),
        "facility_type": org_type.get("code"),
        "source_format": "FHIR_R4",
    }


def _gender(value: str | None) -> str:
    mapping = {
        "male": "M",
        "female": "F",
        "other": "O",
        "unknown": "U",
        "m": "M",
        "f": "F",
        "o": "O",
        "u": "U",
    }
    if not value:
        return "U"
    return mapping.get(value.strip().lower(), value.strip().upper())
