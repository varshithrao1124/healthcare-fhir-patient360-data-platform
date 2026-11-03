"""Name, address, and identifier normalization ahead of matching."""

from __future__ import annotations

import re
from datetime import date

NICKNAMES = {
    "BOB": "ROBERT",
    "ROB": "ROBERT",
    "ROBBY": "ROBERT",
    "BOBBY": "ROBERT",
    "BILL": "WILLIAM",
    "BILLY": "WILLIAM",
    "WILL": "WILLIAM",
    "WILLIE": "WILLIAM",
    "LIZ": "ELIZABETH",
    "BETH": "ELIZABETH",
    "LIZZY": "ELIZABETH",
    "JIM": "JAMES",
    "JIMMY": "JAMES",
    "KATE": "KATHERINE",
    "KATIE": "KATHERINE",
    "KATHY": "KATHERINE",
    "MAGGIE": "MARGARET",
    "PEGGY": "MARGARET",
    "MEG": "MARGARET",
    "TONY": "ANTHONY",
    "CHRIS": "CHRISTOPHER",
    "MIKE": "MICHAEL",
    "MICKEY": "MICHAEL",
}

SUFFIXES = {
    "ST": "STREET",
    "STREET": "STREET",
    "AVE": "AVENUE",
    "AVENUE": "AVENUE",
    "RD": "ROAD",
    "ROAD": "ROAD",
    "BLVD": "BOULEVARD",
    "DR": "DRIVE",
    "LN": "LANE",
    "CT": "COURT",
    "PL": "PLACE",
    "HWY": "HIGHWAY",
    "TER": "TERRACE",
}


def letters(value: str | None) -> str:
    return "".join(character for character in (value or "").upper() if character.isalpha())


def canonical_given(value: str | None) -> str:
    token = letters(value)
    return NICKNAMES.get(token, token)


def normalize_street(value: str | None) -> str:
    text = (value or "").upper().replace("&", " AND ")
    text = text.replace(".", " ").replace(",", " ").replace("#", " ")
    text = re.sub(r"\b(APT|APARTMENT|UNIT|STE|SUITE)\b.*$", "", text)
    tokens = [token for token in text.split() if token]
    if tokens:
        tokens[-1] = SUFFIXES.get(tokens[-1], tokens[-1])
    return " ".join(tokens)


def postal5(value: str | None) -> str:
    digits = "".join(character for character in (value or "") if character.isdigit())
    return digits[:5]


def synthetic_ssn(value: str | None) -> str | None:
    """Only 900-series numbers are eligible match keys.

    SSA does not issue area 900-999. Northline refuses any other pattern so a
    non-synthetic identifier cannot become a deterministic link.
    """
    digits = "".join(character for character in (value or "") if character.isdigit())
    if len(digits) == 9 and digits.startswith("9"):
        return digits
    return None


def prepare_record(row: dict) -> dict:
    dob = row.get("birth_date")
    if isinstance(dob, str):
        dob = date.fromisoformat(dob)
    given = canonical_given(row.get("given_name"))
    family = letters(row.get("family_name"))
    gender = (row.get("gender") or "").upper()
    prepared = {
        **row,
        "key": f"{row['source_system']}|{row['source_person_id']}",
        "given_norm": given,
        "family_norm": family,
        "street_norm": normalize_street(row.get("address_line")),
        "postal5": postal5(row.get("postal_code")),
        "postal3": postal5(row.get("postal_code"))[:3],
        "ssn_norm": synthetic_ssn(row.get("ssn")),
        "dob": dob,
        "year": str(dob.year) if isinstance(dob, date) else "",
        "gender": gender,
    }
    if given and family and isinstance(dob, date) and gender in {"M", "F", "O"}:
        prepared["demo_key"] = (given, family, dob.isoformat(), gender)
    else:
        prepared["demo_key"] = None
    return prepared
