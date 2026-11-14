"""Fictional profile compatibility corpus; imports public DTOs only, never settings or DB."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from backend.app.schemas.candidate_profile import (
    CandidateProfileCreate,
    CandidateProfileUpdate,
)

ROOT = Path(__file__).resolve().parents[2]
BASE = {"full_name": "Fictional Person", "email": "fictional@example.com"}


def cases():
    yield "create", BASE
    for field in CandidateProfileCreate.model_fields:
        for value in [None, False, True, 0, 1, 1.0, "", "  ", [], {}, " alpha   beta "]:
            yield "create", {**BASE, field: value}
            yield "update", {field: value}
    for field, values in {
        "full_name": ["a" * 200, "a" * 201, "é" * 200, " A\u001cB\u00a0C ", "İ Σ ß"],
        "email": ["Joe <TEST@Example.COM>", "é@example.com", "e\u0301@example.com", "x@example.test", "x@localhost", "x@例え.テスト", "x@xn--bcher-kva.de", "a+b@example.com", '"a b"@example.com', "a..b@example.com", "x@-example.com", "x@123.123", "foo@EXAMPLE.COM.", "SUPPORT@Example.com", "a" * 65 + "@example.com", "\u0301@example.com", "\ue000@example.com"],
        "verified_skills": [[" Rust ", "RUST", "Straße", "STRASSE", " A   B ", "a b"], ["a" * 201], [" A " * 100], ["a"] * 101, ["x\u001cy", "x y"]],
        "portfolio_url": ["HTTPS://EXAMPLE.COM", "http://localhost", "https://bücher.de/a b", "ftp://example.com", "https://user:secret@example.com", "https://@example.com", "https://example.com/path?q=a b#x", "not a url", "http://[::1]"],
        "verified_experience_years": ["1_0", "1e2", "1.0", "NaN", "Infinity", -0.1, 100, 100.1],
        "verified_roles": [[{"company": " A   B ", "role": " Rust ", "start_date": "2026-11-14", "end_date": "2026-11-13"}], [{"company": "A", "role": "R", "start_date": 1794614400}], [{"company": "A", "role": "R", "start_date": "2026-11-14T00:00:00+05:30"}]],
    }.items():
        for value in values:
            yield "create", {**BASE, field: value}
            yield "update", {field: value}
    for field, values in {
        "notice_period_days": [None, True, "1.0", "1e2", "1_0", "01", 1.5, -1, 3650, 3651],
        "open_to_relocation": [True, False, 0, 1, "true", None],
        "prioritize_startups": [True, False, 0, 1, "yes", "off", "TRUE", "0", None],
        "availability_date": ["2026-11-14", "2026-02-30", "2026-1-1", "2026-11-14T00:00:00Z", "2026-11-14 00:00:00", "2026-11-14T00:00:00+05:30", "2026-11-14T01:00:00Z", 1794614400, "1794614400", 1794614400000, True],
        "work_authorizations": [[{"country_code": "IN", "country_name": "India", "authorized_to_work": True}], [{"country_code": "IN", "country_name": "India", "authorized_to_work": 1}], [{"country_code": "IN", "country_name": "India", "authorized_to_work": True}] * 2],
        "employment_types": [["full_time", "full_time"], ["FULL_TIME"], ["full_time"] * 4],
    }.items():
        for value in values:
            yield "create", {**BASE, "preferences": {field: value}}
            yield "update", {"preferences": {field: value}}
    for amount in ["100.000", "1E+2", "-0.000", "100.0100", "1000000000000.000", "100.001", "1E+100000", "0E-100", "1_0", "١٢.٣٠", 100, 100.0, True, -1]:
        preference = {"expected_compensation": {"amount": amount, "currency": "INR", "period": "year", "kind": "ctc"}}
        yield "create", {**BASE, "preferences": preference}
        yield "update", {"preferences": preference}
    for email in ["Joe Person <a@example.com>", '"Joe Person" <a@example.com>', "a@☃.net", "a@💩.la", "a@faß.de", "a@a。com", "a@а.com", "a@l·l.cat", "a@ab--cd.com", "a@example.onion", "a@home.arpa", "a@example.local", "a@xn--n3h.net", "a@a_b.com", "é" * 100 + "@example.com"]:
        yield "create", {**BASE, "email": email}
    for field in ["notice_period_days", "minimum_salary", "prioritize_startups"]:
        for value in ["1__0", "_1", "1_", "+01", "1.", ".0", "-0.0", "0x10", "1.000", "١٢", "1e+1", "1.0000000000000000000000001", "1_0.0_0", "1_._0", "1_e2", "1e_2", "1e+_2", "+_1", "-_1", ".0_", "1._0", "1_.0", "1_e_+_2", "1_0", 1.0, 0.0, 0.5, "1.0"]:
            yield "create", {**BASE, "preferences": {field: value}}
            yield "update", {"preferences": {field: value}}
    for value in ["0000-01-01", "0001-01-01", "0000-01-01T00:00:00Z", "9999-12-31", "2026-1-1T00:00:00", "2026-11-14t00:00:00z", "2026-11-14_00:00:00", "2026-11-14T00:00:00.000001Z", "2026-11-14T00:00:00.0000000Z", "2026-11-14", "2026-11-14Z", "1794614400000", 1794614400.000001, 1794614400000, 0, -86400]:
        yield "create", {**BASE, "preferences": {"availability_date": value}}
    for value in ["1__0", "_1", "1_", "+01", "1.", ".0", "-0E+99", "0E-999999999999999999", "٠.٠٠", "١_٢.٣٠", "1e-2", "1000000000000.01"]:
        yield "create", {**BASE, "preferences": {"expected_compensation": {"amount": value, "currency": "INR", "period": "year", "kind": "ctc"}}}
    for value in [" " * 2050 + "https://example.com", "https://example.com/" + "é" * 700, "https://example.com/" + "a" * 2028, "https://example.com/" + "a" * 2029]:
        yield "create", {**BASE, "portfolio_url": value}
    for value in ["2026-11-14T0:00:00", "2026-11-14T00:0:00", "2026-11-14T00:00:0", "2026-11-14T00:00", "2026-11-14t00:00:00", "2026-11-14_00:00:00+05:30", "2026-11-14 00:00:00+05:30", "2026-11-14T00:00:00.0000001Z", "2026-11-14T00:00:00,000Z", "2026-11-14T00:00+05", "2026-11-14T00:00+0530", "2026-11-14T00:00+23:59", "2026-11-14T00:00+24:00", "1.7946144e9"]:
        yield "create", {**BASE, "preferences": {"availability_date": value}}
    for field,values in {"full_name":[" Fictional   Person "," A\u001cB ","A "*101],"summary":[" One   two\nthree ","x"*4001],"phone":[" 1  2\t3 "],"portfolio_url":["https://example.com/a\nb"," https://example.com "],"verified_skills":[[" Rust ","RUST","A   B"]]}.items():
        for value in values:
            yield "record",{**BASE,field:value}
    for field, size in [("full_name", 199), ("summary", 3999), ("phone", 49)]:
        value = "\u001c" + "x" * size + "\u001f"
        yield "create", {**BASE, field: value}
        yield "record", {**BASE, field: value}
    for value in [["\u001cRust\u001f"], ["x" * 200 + "\u001c"]]:
        yield "create", {**BASE, "verified_skills": value}
        yield "update", {"verified_skills": value}
    yield "update", {}
    yield "update", {"preferences": {}}
    yield "create", {**BASE, "unexpected": "no"}
    yield "update", {"unexpected": "no"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    results = []
    for operation, data in cases():
        model = CandidateProfileUpdate if operation == "update" else CandidateProfileCreate
        try:
            parsed = model.model_validate(SimpleNamespace(**data) if operation == "record" else data)
            result = {"accepted": True, "value": parsed.model_dump(mode="json", exclude_unset=operation == "update")}
        except ValueError:
            result = {"accepted": False}
        results.append({"operation": operation, "input": data, **result})
    path = ROOT / "rust/agent-runtime/tests/fixtures/profile-corpus.json"
    encoded = json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    if check:
        if path.read_text() != encoded:
            raise SystemExit("profile_corpus_drift")
    else:
        path.write_text(encoded)
    print(f"fictional_profile_cases:{len(results)}")


if __name__ == "__main__":
    main()
