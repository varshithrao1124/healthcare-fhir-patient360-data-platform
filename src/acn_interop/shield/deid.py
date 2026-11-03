"""Safe-harbor style projection computed after clinical measures."""

from __future__ import annotations

from datetime import date


def age_band(birth: date | None, as_of: date) -> str:
    if birth is None:
        return "unknown"
    years = as_of.year - birth.year - ((as_of.month, as_of.day) < (birth.month, birth.day))
    if years < 18:
        return "0-17"
    if years < 45:
        return "18-44"
    if years < 65:
        return "45-64"
    return "65+"


def postal3(value: str | None) -> str | None:
    digits = "".join(character for character in (value or "") if character.isdigit())
    return digits[:3] if digits else None


FORBIDDEN_DEID_COLUMNS = {
    "family_name",
    "given_name",
    "middle_name",
    "address_line",
    "city",
    "state",
    "phone",
    "ssn",
    "ssn_token",
    "birth_date",
    "source_person_id",
    "postal_code",
    "enterprise_person_id",
    "admit_time",
    "discharge_time",
}


def identifier_columns(columns: list[str]) -> list[str]:
    return sorted(set(columns) & FORBIDDEN_DEID_COLUMNS)
