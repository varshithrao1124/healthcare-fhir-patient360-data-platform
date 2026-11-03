"""Date parsing shared by HL7 and FHIR extractors."""

from __future__ import annotations

from datetime import date, datetime


def parse_hl7_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    digits = "".join(character for character in value if character.isdigit())
    formats = (("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12), ("%Y%m%d%H", 10), ("%Y%m%d", 8))
    for fmt, size in formats:
        if len(digits) >= size:
            try:
                return datetime.strptime(digits[:size], fmt)
            except ValueError:
                return None
    return None


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "")
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")]
    text = text.replace("T", " ")
    for size, fmt in ((19, "%Y-%m-%d %H:%M:%S"), (16, "%Y-%m-%d %H:%M"), (10, "%Y-%m-%d")):
        if len(text) < size:
            continue
        try:
            return datetime.strptime(text[:size], fmt)
        except ValueError:
            return None
    return parse_hl7_datetime(value)


def parse_date_only(value: str | None) -> date | None:
    if not value:
        return None
    digits = "".join(character for character in str(value) if character.isdigit())
    if len(digits) == 4:
        return None
    parsed = parse_iso_datetime(value) or parse_hl7_datetime(value)
    return parsed.date() if parsed else None
