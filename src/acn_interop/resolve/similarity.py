"""String similarity and blocking keys used by the master patient index."""

from __future__ import annotations

_SOUNDEX = {
    **dict.fromkeys("BFPV", "1"),
    **dict.fromkeys("CGJKQSXZ", "2"),
    **dict.fromkeys("DT", "3"),
    **dict.fromkeys("L", "4"),
    **dict.fromkeys("MN", "5"),
    **dict.fromkeys("R", "6"),
}


def soundex(value: str | None) -> str:
    letters = "".join(character for character in (value or "").upper() if character.isalpha())
    if not letters:
        return ""
    first = letters[0]
    tail = "".join(character for character in letters[1:] if character not in "AEIOUYHW")
    digits: list[str] = []
    previous = _SOUNDEX.get(first, "")
    for character in tail:
        code = _SOUNDEX.get(character, "")
        if not code:
            previous = ""
            continue
        if code != previous:
            digits.append(code)
        previous = code
    if digits and _SOUNDEX.get(first) == digits[0]:
        digits = digits[1:]
    return (first + "".join(digits) + "000")[:4]


def jaro(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    len_left, len_right = len(left), len(right)
    window = max(len_left, len_right) // 2 - 1
    window = max(window, 0)
    left_flags = [False] * len_left
    right_flags = [False] * len_right
    matches = 0
    for index, character in enumerate(left):
        start = max(0, index - window)
        end = min(index + window + 1, len_right)
        for cursor in range(start, end):
            if right_flags[cursor] or right[cursor] != character:
                continue
            left_flags[index] = True
            right_flags[cursor] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    transpositions = 0
    cursor = 0
    for index, flag in enumerate(left_flags):
        if not flag:
            continue
        while not right_flags[cursor]:
            cursor += 1
        if left[index] != right[cursor]:
            transpositions += 1
        cursor += 1
    transpositions /= 2
    return (matches / len_left + matches / len_right + (matches - transpositions) / matches) / 3


def jaro_winkler(left: str | None, right: str | None, prefix_scale: float = 0.1) -> float:
    left = left or ""
    right = right or ""
    base = jaro(left, right)
    prefix = 0
    for pair in zip(left, right):
        if pair[0] != pair[1] or prefix == 4:
            break
        prefix += 1
    return base + prefix * prefix_scale * (1 - base)
