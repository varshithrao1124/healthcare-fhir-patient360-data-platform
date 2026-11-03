"""Deterministic and probabilistic master patient index.

Blocking keeps comparisons inside shared Soundex buckets. Survivorship then
builds one enterprise person per cluster. Pairs that fall in the review band,
and pairs with conflicting synthetic SSNs, are not merged.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from itertools import combinations

from acn_interop.resolve.normalize import prepare_record
from acn_interop.resolve.similarity import jaro_winkler, soundex

WEIGHTS = {
    "given": 0.28,
    "family": 0.32,
    "dob": 0.22,
    "gender": 0.06,
    "street": 0.07,
    "postal": 0.05,
}
TRUST = {"AMC": 30, "RGH": 20, "CHO": 10}


class _UnionFind:
    def __init__(self, keys: list[str]):
        self.parent = {key: key for key in keys}

    def find(self, key: str) -> str:
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def union(self, left: str, right: str) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def score_pair(left: dict, right: dict) -> float:
    given = _jw(left.get("given_norm"), right.get("given_norm"))
    family = _jw(left.get("family_norm"), right.get("family_norm"))
    dob = 1.0 if left.get("dob") and left.get("dob") == right.get("dob") else 0.0
    gender = 1.0 if left.get("gender") in {"M", "F", "O"} and left.get("gender") == right.get("gender") else 0.0
    street = _jw(left.get("street_norm"), right.get("street_norm"))
    postal = 1.0 if left.get("postal5") and left.get("postal5") == right.get("postal5") else 0.0
    return (
        WEIGHTS["given"] * given
        + WEIGHTS["family"] * family
        + WEIGHTS["dob"] * dob
        + WEIGHTS["gender"] * gender
        + WEIGHTS["street"] * street
        + WEIGHTS["postal"] * postal
    )


def link_records(rows: list[dict], *, auto_threshold: float, review_threshold: float) -> dict:
    prepared = [prepare_record(row) for row in rows if row.get("source_person_id")]
    by_key = {row["key"]: row for row in prepared}
    union = _UnionFind(list(by_key))
    compared: set[frozenset[str]] = set()
    auto_edges: list[dict] = []
    reviews: list[dict] = []
    for bucket in _blocks(prepared).values():
        if len(bucket) < 2:
            continue
        for left, right in combinations(bucket, 2):
            pair = frozenset((left["key"], right["key"]))
            if pair in compared:
                continue
            compared.add(pair)
            action, score, reason = _decide(left, right, auto_threshold, review_threshold)
            edge = {
                "left_source": left["source_system"],
                "left_person_id": left["source_person_id"],
                "right_source": right["source_system"],
                "right_person_id": right["source_person_id"],
                "score": round(score, 4),
                "reason": reason,
            }
            if action == "auto":
                union.union(left["key"], right["key"])
                auto_edges.append(edge)
            elif action == "review":
                reviews.append(edge)
    clusters: dict[str, list[dict]] = defaultdict(list)
    for key, row in by_key.items():
        clusters[union.find(key)].append(row)
    crosswalk = []
    golden = []
    for members in clusters.values():
        enterprise_id = _enterprise_id(members)
        best = _best_edge_by_member(members, auto_edges)
        for member in members:
            edge = best.get(member["key"])
            crosswalk.append(
                {
                    "enterprise_person_id": enterprise_id,
                    "source_system": member["source_system"],
                    "source_person_id": member["source_person_id"],
                    "match_type": edge["reason"] if edge else "unmatched",
                    "match_score": edge["score"] if edge else None,
                    "cluster_size": len(members),
                }
            )
        golden.append(_survive(enterprise_id, members))
    return {
        "crosswalk": crosswalk,
        "golden": golden,
        "reviews": reviews,
        "stats": {
            "source_persons": len(prepared),
            "golden_persons": len(golden),
            "pairs_compared": len(compared),
            "auto_edges": len(auto_edges),
            "review_edges": len(reviews),
            "possible_pairs": len(prepared) * (len(prepared) - 1) // 2,
        },
    }


def _blocks(rows: list[dict]) -> dict[tuple, list[dict]]:
    blocks: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("ssn_norm"):
            blocks[("ssn", row["ssn_norm"])].append(row)
        family_sound = soundex(row.get("family_norm"))
        if family_sound and row.get("year"):
            blocks[("soundex-year", family_sound, row["year"])].append(row)
        if family_sound and row.get("postal3"):
            blocks[("soundex-postal", family_sound, row["postal3"])].append(row)
    return blocks


def _decide(left: dict, right: dict, auto_threshold: float, review_threshold: float):
    left_ssn, right_ssn = left.get("ssn_norm"), right.get("ssn_norm")
    if left_ssn and right_ssn and left_ssn == right_ssn:
        return "auto", 1.0, "deterministic_ssn"
    score = score_pair(left, right)
    if left_ssn and right_ssn and left_ssn != right_ssn:
        return "review", score, "ssn_conflict"
    if left.get("demo_key") and left["demo_key"] == right["demo_key"]:
        return "auto", max(score, 0.99), "deterministic_demographic"
    if score >= auto_threshold:
        return "auto", score, "probabilistic"
    if score >= review_threshold:
        return "review", score, "review"
    return "reject", score, "reject"


def _best_edge_by_member(members: list[dict], edges: list[dict]) -> dict[str, dict]:
    keys = {member["key"] for member in members}
    best: dict[str, dict] = {}
    rank = {"deterministic_ssn": 3, "deterministic_demographic": 2, "probabilistic": 1}
    for edge in edges:
        left = f"{edge['left_source']}|{edge['left_person_id']}"
        right = f"{edge['right_source']}|{edge['right_person_id']}"
        if left not in keys or right not in keys:
            continue
        for key in (left, right):
            current = best.get(key)
            if current is None or rank.get(edge["reason"], 0) > rank.get(current["reason"], 0):
                best[key] = edge
    return best


def _enterprise_id(members: list[dict]) -> str:
    material = "|".join(sorted(member["key"] for member in members))
    return "EID-" + hashlib.sha256(material.encode()).hexdigest()[:10].upper()


def _survive(enterprise_id: str, members: list[dict]) -> dict:
    return {
        "enterprise_person_id": enterprise_id,
        "family_name": _pick(members, "family_name", "trust"),
        "given_name": _pick(members, "given_name", "trust"),
        "middle_name": _pick(members, "middle_name", "trust"),
        "birth_date": _pick(members, "birth_date", "trust"),
        "gender": _pick(members, "gender", "trust"),
        "address_line": _pick(members, "address_line", "trust"),
        "city": _pick(members, "city", "trust"),
        "state": _pick(members, "state", "trust"),
        "postal_code": _pick(members, "postal_code", "trust"),
        "phone": _pick(members, "phone", "recent"),
        "ssn": _pick(members, "ssn", "trust"),
        "member_count": len(members),
        "updated_at": max(member["effective_time"] for member in members),
    }


def _pick(members: list[dict], field: str, mode: str):
    present = [member for member in members if member.get(field) not in (None, "")]
    if not present:
        return None
    if mode == "recent":
        present.sort(key=lambda member: member["effective_time"], reverse=True)
    else:
        present.sort(
            key=lambda member: (TRUST.get(member["source_system"], 0), member["effective_time"]),
            reverse=True,
        )
    return present[0][field]


def _jw(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    return jaro_winkler(left, right)
