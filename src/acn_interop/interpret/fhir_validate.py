"""Minimal FHIR R4 structural checks used before flattening."""

from __future__ import annotations

import re

REFERENCE = re.compile(r"([A-Za-z]+)/([^/\s]+)$")
STATUS = {
    "Observation": {"registered", "preliminary", "final", "amended", "corrected", "cancelled", "entered-in-error", "unknown"},
    "Encounter": {"planned", "arrived", "triaged", "in-progress", "onleave", "finished", "cancelled", "entered-in-error", "unknown"},
    "Condition": {"active", "recurrence", "relapse", "inactive", "remission", "resolved"},
    "MedicationRequest": {"active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft", "unknown"},
    "AllergyIntolerance": {"active", "inactive", "resolved"},
}


def validate_fhir(resource: dict) -> list[str]:
    if not isinstance(resource, dict):
        return ["payload is not a JSON object"]
    resource_type = resource.get("resourceType")
    if not resource_type:
        return ["resourceType missing"]
    errors: list[str] = []
    if not resource.get("id"):
        errors.append("id missing")
    if resource_type == "Patient":
        has_name = bool(resource.get("name"))
        has_mrn = _mrn(resource) is not None
        if not has_name and not resource.get("identifier"):
            errors.append("Patient needs a name or identifier")
        if not has_mrn:
            errors.append("Patient.identifier MR missing")
    elif resource_type == "Observation":
        if not resource.get("code"):
            errors.append("Observation.code missing")
        if not _reference(resource.get("subject")):
            errors.append("Observation.subject missing")
    elif resource_type == "Encounter":
        if not _reference(resource.get("subject")):
            errors.append("Encounter.subject missing")
        if not (resource.get("period") or {}).get("start"):
            errors.append("Encounter.period.start missing")
        if not _encounter_class(resource):
            errors.append("Encounter.class missing")
    elif resource_type == "Condition":
        if not resource.get("code"):
            errors.append("Condition.code missing")
        if not _reference(resource.get("subject")):
            errors.append("Condition.subject missing")
    elif resource_type == "MedicationRequest":
        if not _reference(resource.get("subject")):
            errors.append("MedicationRequest.subject missing")
        if not (resource.get("medicationCodeableConcept") or resource.get("medicationReference")):
            errors.append("MedicationRequest medication missing")
    elif resource_type == "AllergyIntolerance":
        if not _reference(resource.get("patient")):
            errors.append("AllergyIntolerance.patient missing")
    elif resource_type == "Practitioner":
        if not resource.get("name"):
            errors.append("Practitioner.name missing")
    elif resource_type == "Organization":
        if not resource.get("name"):
            errors.append("Organization.name missing")
    else:
        errors.append(f"unsupported resourceType {resource_type}")
    status = resource.get("status")
    allowed = STATUS.get(resource_type)
    if status and allowed and status not in allowed:
        errors.append(f"status {status} outside {resource_type} value set")
    for key in ("subject", "patient"):
        reference = resource.get(key)
        if isinstance(reference, dict) and reference.get("reference"):
            if not REFERENCE.search(reference["reference"]):
                errors.append(f"{key}.reference is not Resource/id")
    return errors


def _mrn(resource: dict) -> str | None:
    for identifier in resource.get("identifier") or []:
        code = (((identifier.get("type") or {}).get("coding") or [{}])[0]).get("code")
        if code in {"MR", "MRN"} and identifier.get("value"):
            return identifier["value"]
    return None


def _reference(node) -> str | None:
    if not isinstance(node, dict):
        return None
    reference = node.get("reference")
    if not reference:
        return None
    match = REFERENCE.search(reference)
    return match.group(2) if match else None


def _encounter_class(resource: dict) -> str | None:
    klass = resource.get("class") or {}
    if isinstance(klass, dict) and klass.get("code"):
        return klass["code"]
    coding = (klass.get("coding") or [{}])[0] if isinstance(klass, dict) else {}
    return coding.get("code")
