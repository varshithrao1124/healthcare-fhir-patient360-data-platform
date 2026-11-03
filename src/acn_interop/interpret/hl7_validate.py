"""Structural checks that decide whether an HL7 message can be interpreted."""

from __future__ import annotations

from acn_interop.interpret.hl7_parser import Message


def validate_hl7(message: Message) -> list[str]:
    errors: list[str] = []
    if message.seg("MSH") is None:
        return ["MSH segment missing"]
    message_type = message.get("MSH", 9, 1)
    trigger = message.get("MSH", 9, 2)
    if not message_type:
        errors.append("MSH-9 message type missing")
    if not message.get("MSH", 10):
        errors.append("MSH-10 control id missing")
    if message_type not in {"ADT", "ORU"}:
        errors.append(f"unsupported message type {message_type or 'blank'}")
    if message_type in {"ADT", "ORU"} and message.seg("PID") is None:
        errors.append("PID segment missing")
    if message.seg("PID") is not None and not _mrn(message):
        errors.append("PID-3 MR identifier missing")
    if message_type == "ADT" and trigger in {"A01", "A03", "A04"} and message.seg("PV1") is None:
        errors.append("PV1 segment missing")
    if message_type == "ADT" and trigger not in {"A01", "A03", "A04", "A08"}:
        errors.append(f"unsupported ADT trigger {trigger or 'blank'}")
    if message_type == "ORU" and not message.segs("OBX"):
        errors.append("OBX segment missing")
    return errors


def _mrn(message: Message) -> str:
    segment = message.seg("PID")
    if segment is None or len(segment.fields) <= 3:
        return ""
    for repetition in segment.fields[3]:
        identifier = repetition[0][0] if repetition and repetition[0] else ""
        id_type = ""
        if len(repetition) >= 5 and repetition[4]:
            id_type = repetition[4][0]
        if identifier and id_type in {"MR", "MRN"}:
            return identifier
    return ""
