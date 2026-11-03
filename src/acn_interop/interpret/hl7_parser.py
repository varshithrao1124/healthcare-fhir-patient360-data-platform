"""HL7 v2 segment parser.

Handles MSH separator discovery, escape sequences, repetitions, components,
and subcomponents. MSH-2 is not escape-processed: it defines the escape character.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from acn_interop.platform.errors import ParseError


@dataclass(frozen=True)
class Separators:
    field: str = "|"
    component: str = "^"
    repetition: str = "~"
    escape: str = "\\"
    subcomponent: str = "&"


@dataclass
class Segment:
    name: str
    fields: list[list[list[list[str]]]] = field(default_factory=list)

    def value(self, index: int, component: int = 1, repetition: int = 1, sub: int = 1) -> str:
        if index >= len(self.fields):
            return ""
        reps = self.fields[index]
        if not reps or repetition < 1 or repetition > len(reps):
            return ""
        comps = reps[repetition - 1]
        if component < 1 or component > len(comps):
            return ""
        subs = comps[component - 1]
        if sub < 1 or sub > len(subs):
            return ""
        return subs[sub - 1]


@dataclass
class Message:
    separators: Separators
    segments: list[Segment]

    def seg(self, name: str) -> Segment | None:
        found = self.segs(name)
        return found[0] if found else None

    def segs(self, name: str) -> list[Segment]:
        return [segment for segment in self.segments if segment.name == name]

    def get(self, name: str, index: int, component: int = 1, repetition: int = 1, sub: int = 1) -> str:
        segment = self.seg(name)
        if segment is None:
            return ""
        return segment.value(index, component, repetition, sub)


def parse_message(raw: str) -> Message:
    if raw is None or not str(raw).strip():
        raise ParseError("empty HL7 payload")
    text = str(raw).replace("\r\n", "\r").replace("\n", "\r").strip("\r")
    lines = [line for line in text.split("\r") if line.strip()]
    if not lines or not lines[0].startswith("MSH"):
        raise ParseError("MSH segment missing")
    msh_count = sum(1 for line in lines if line.startswith("MSH"))
    if msh_count > 1:
        raise ParseError("batched HL7 messages are not accepted in one envelope")
    separators = _separators_from_msh(lines[0])
    segments = [_parse_segment(lines[0], separators, is_msh=True)]
    segments.extend(_parse_segment(line, separators, is_msh=False) for line in lines[1:])
    return Message(separators=separators, segments=segments)


def _separators_from_msh(line: str) -> Separators:
    if len(line) < 8 or not line.startswith("MSH"):
        raise ParseError("MSH encoding characters missing")
    return Separators(
        field=line[3],
        component=line[4],
        repetition=line[5],
        escape=line[6],
        subcomponent=line[7],
    )


def _parse_segment(line: str, separators: Separators, *, is_msh: bool) -> Segment:
    if is_msh:
        parts = line.split(separators.field)
        fields: list[list[list[list[str]]]] = [[]]
        fields.append([[[separators.field]]])
        fields.append([[[parts[1]]]])
        for raw in parts[2:]:
            fields.append(_parse_field(raw, separators))
        return Segment("MSH", fields)
    parts = _split_escaped(line, separators.field, separators.escape)
    name = parts[0]
    if len(name) != 3 or not name.isalnum():
        raise ParseError(f"invalid segment name {name!r}")
    fields = [[]]
    for raw in parts[1:]:
        fields.append(_parse_field(raw, separators))
    return Segment(name, fields)


def _parse_field(raw: str, separators: Separators) -> list[list[list[str]]]:
    if raw == "":
        return []
    repetitions = _split_escaped(raw, separators.repetition, separators.escape)
    parsed: list[list[list[str]]] = []
    for repetition in repetitions:
        components = _split_escaped(repetition, separators.component, separators.escape)
        parsed.append(
            [
                [_unescape(piece, separators) for piece in _split_escaped(component, separators.subcomponent, separators.escape)]
                for component in components
            ]
        )
    return parsed


def _split_escaped(value: str, separator: str, escape: str) -> list[str]:
    parts: list[str] = []
    buffer: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == escape:
            closing = value.find(escape, index + 1)
            if closing == -1:
                buffer.append(value[index:])
                break
            buffer.append(value[index : closing + 1])
            index = closing + 1
            continue
        if value[index] == separator:
            parts.append("".join(buffer))
            buffer = []
            index += 1
            continue
        buffer.append(value[index])
        index += 1
    parts.append("".join(buffer))
    return parts


def _unescape(value: str, separators: Separators) -> str:
    escape = separators.escape
    if escape not in value:
        return value
    output: list[str] = []
    index = 0
    mapping = {
        "F": separators.field,
        "S": separators.component,
        "T": separators.subcomponent,
        "R": separators.repetition,
        "E": separators.escape,
    }
    while index < len(value):
        if value[index] != escape:
            output.append(value[index])
            index += 1
            continue
        closing = value.find(escape, index + 1)
        if closing == -1:
            output.append(value[index:])
            break
        code = value[index + 1 : closing]
        if code in mapping:
            output.append(mapping[code])
        elif code == ".br":
            output.append("\n")
        elif code.startswith("X") and len(code) > 1 and len(code) % 2 == 1:
            try:
                output.append(bytes.fromhex(code[1:]).decode("ascii"))
            except ValueError:
                output.append(code)
        else:
            output.append(code)
        index = closing + 1
    return "".join(output)
