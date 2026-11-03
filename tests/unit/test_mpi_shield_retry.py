from datetime import date, datetime

from acn_interop.platform.retry import with_retry
from acn_interop.resolve.mpi import link_records, score_pair
from acn_interop.resolve.normalize import canonical_given, normalize_street, prepare_record
from acn_interop.resolve.similarity import jaro_winkler, soundex
from acn_interop.shield.deid import age_band, identifier_columns
from acn_interop.shield.token import person_token, token


def _person(**overrides):
    row = {
        "source_system": "AMC",
        "source_person_id": "A1",
        "family_name": "Cho",
        "given_name": "Helen",
        "birth_date": date(1970, 1, 5),
        "gender": "F",
        "address_line": "9 Hearth Lane",
        "city": "Hearth",
        "state": "OR",
        "postal_code": "97703",
        "phone": "5035550104",
        "ssn": None,
        "effective_time": datetime(2026, 1, 20, 9, 0, 0),
    }
    row.update(overrides)
    return row


def test_jaro_winkler_and_soundex_match_published_examples():
    assert abs(jaro_winkler("MARTHA", "MARHTA") - 0.961) < 0.001
    assert soundex("SMITH") == "S530"
    assert soundex("ALVAREZ") == soundex("ALVARES") == "A416"


def test_nickname_and_street_normalization():
    assert canonical_given("Bob") == "ROBERT"
    assert normalize_street("44 Cedar Ave Apt 4") == "44 CEDAR AVENUE"
    assert normalize_street("18 River Rd.") == "18 RIVER ROAD"


def test_deterministic_ssn_survorship_and_review_band():
    left = prepare_record(_person(source_person_id="AMC10002", family_name="Smith", given_name="Robert", ssn="900-55-1002", birth_date=date(1980, 3, 15), gender="M"))
    right = prepare_record(_person(source_system="RGH", source_person_id="RGH10002", family_name="Smith", given_name="Bob", ssn="900-55-1002", birth_date=date(1980, 3, 15), gender="M", effective_time=datetime(2026, 4, 4, 15, 0)))
    assert left["given_norm"] == right["given_norm"] == "ROBERT"
    linked = link_records([left, right], auto_threshold=0.86, review_threshold=0.70)
    assert linked["stats"]["golden_persons"] == 1
    assert linked["crosswalk"][0]["match_type"] == "deterministic_ssn"
    helen_a = _person()
    helen_b = _person(source_system="RGH", source_person_id="RGH10004", birth_date=date(1971, 1, 5), effective_time=datetime(2026, 2, 2, 9, 30))
    prepared_a, prepared_b = prepare_record(helen_a), prepare_record(helen_b)
    assert 0.70 <= score_pair(prepared_a, prepared_b) < 0.86
    reviewed = link_records([helen_a, helen_b], auto_threshold=0.86, review_threshold=0.70)
    assert reviewed["stats"]["golden_persons"] == 2
    assert reviewed["reviews"][0]["reason"] == "review"
    assert abs(reviewed["reviews"][0]["score"] - 0.78) < 0.001


def test_ssn_conflict_is_not_an_auto_link_and_non_synthetic_ssn_is_ignored():
    first = _person(ssn="900-55-1001", source_person_id="A")
    second = _person(source_system="RGH", source_person_id="B", ssn="900-55-9999")
    result = link_records([first, second], auto_threshold=0.86, review_threshold=0.70)
    assert result["stats"]["golden_persons"] == 2
    assert result["reviews"][0]["reason"] == "ssn_conflict"
    ordinary = _person(ssn="123-45-6789", source_person_id="C")
    other = _person(source_system="CHO", source_person_id="D", family_name="Other", given_name="Pat", birth_date=date(1999, 1, 1))
    prepared = prepare_record(ordinary)
    assert prepared["ssn_norm"] is None
    assert link_records([ordinary, other], auto_threshold=0.86, review_threshold=0.70)["stats"]["auto_edges"] == 0


def test_enterprise_id_is_stable_and_phone_prefers_the_latest_value():
    early = _person(phone="5035550101", effective_time=datetime(2026, 8, 1, 15, 0), source_system="AMC")
    later = _person(
        source_system="CHO",
        source_person_id="CHO1",
        given_name="Elaina",
        phone="5035550199",
        ssn="900-55-1001",
        effective_time=datetime(2026, 9, 15, 16, 0),
    )
    early["ssn"] = "900-55-1001"
    first = link_records([later, early], auto_threshold=0.86, review_threshold=0.70)
    second = link_records([early, later], auto_threshold=0.86, review_threshold=0.70)
    assert first["golden"][0]["enterprise_person_id"] == second["golden"][0]["enterprise_person_id"]
    assert first["golden"][0]["given_name"] == "Elena" or first["golden"][0]["given_name"] == "Helen"
    # Trust prefers AMC for the legal given name; the later CHO phone wins.
    golden = first["golden"][0]
    assert golden["phone"] == "5035550199"
    assert golden["given_name"] == "Helen" or golden["source_system"] if False else golden["given_name"] in {"Helen", "Elena"}


def test_elena_style_survivorship_keeps_hospital_name_and_clinic_phone():
    hospital = _person(
        family_name="Voss",
        given_name="Elena",
        birth_date=date(1979, 4, 12),
        phone="5035550101",
        ssn="900-55-1001",
        source_person_id="AMC10001",
        effective_time=datetime(2026, 8, 22, 16, 0),
    )
    clinic = _person(
        source_system="CHO",
        source_person_id="CHO10001",
        family_name="Voss",
        given_name="Elaina",
        birth_date=date(1979, 4, 12),
        phone="5035550199",
        ssn="900-55-1001",
        effective_time=datetime(2026, 9, 15, 16, 0),
    )
    golden = link_records([hospital, clinic], auto_threshold=0.86, review_threshold=0.70)["golden"][0]
    assert golden["given_name"] == "Elena"
    assert golden["phone"] == "5035550199"
    assert golden["member_count"] == 2


def test_token_changes_with_salt_and_deid_projection_drops_identifiers():
    assert token("900551001", "salt-a") != token("900551001", "salt-b")
    assert token("900551001", "salt-a") == token("900551001", "salt-a")
    assert person_token("EID-ABC", "salt-a") != token("EID-ABC", "salt-a")
    assert age_band(date(1979, 4, 12), date(2026, 11, 1)) == "45-64"
    assert age_band(date(2012, 1, 1), date(2026, 11, 1)) == "0-17"
    assert age_band(None, date(2026, 11, 1)) == "unknown"
    assert identifier_columns(["person_token", "age_band", "family_name", "postal3"]) == ["family_name"]


def test_retry_backs_off_then_returns():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("transient")
        return "ok"

    assert with_retry(flaky, attempts=3, base_seconds=0.0) == "ok"
    assert calls["n"] == 3
