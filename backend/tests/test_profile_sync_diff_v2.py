"""Phase 9D profile sync: pure normalisation + diff rules (no browser, no DB)."""

from __future__ import annotations

import hashlib

import pytest

from backend.app.browser_v2.profile_sync.canonical import snapshot_from_profile
from backend.app.browser_v2.profile_sync.diff import (
    compute_diff,
    normalize,
    parse_lpa,
    parse_notice_days,
    values_match,
)
from backend.app.browser_v2.profile_sync.models import (
    FIELDS,
    FieldDiff,
    FieldStatus,
    FieldValue,
    SyncReport,
    profile_sync_live,
    run_status,
    value_ref,
)

S = FieldStatus


@pytest.mark.parametrize(("raw", "lpa"), [
    (12.5, 12.5), (1250000, 12.5), ("12.5 LPA", 12.5), ("₹ 12,50,000", 12.5), ("12 Lacs 50 Thousand", 12.5),
    ("1.2 Cr", 120.0), ("18", 18.0), (None, None), ("not disclosed", None), (True, None),
])
def test_ctc_normalises_to_lpa(raw, lpa):
    assert parse_lpa(raw) == lpa


@pytest.mark.parametrize(("raw", "days"), [
    (30, 30), ("1 Month", 30), ("2 months", 60), ("15 Days or less", 15), ("Immediate joiner", 0),
    ("3 weeks", 21), ("Serving notice period", 0), (None, None), ("", None),
])
def test_notice_period_normalises_to_days(raw, days):
    assert parse_notice_days(raw) == days


def test_text_skills_and_locations_normalisation():
    assert normalize("profile_summary", "  Backend   engineer\n building APIs ") == "Backend engineer building APIs"
    assert normalize("resume_headline", "   ") is None
    assert normalize("key_skills", ["Python", " python ", "FastAPI"]) == frozenset({"python", "fastapi"})
    assert normalize("preferred_locations", "Bengaluru, Pune") == normalize("preferred_locations", ["pune", "BENGALURU"])
    assert values_match("current_ctc", 12.5, "12.5 Lacs") and not values_match("current_ctc", 12.5, "13 LPA")


def test_never_overwrites_a_portal_value_with_an_empty_source():
    portal = {"resume_headline": FieldValue("Senior Backend Engineer"), "profile_summary": FieldValue(""),
              "notice_period": FieldValue("1 Month")}
    diffs = {d.field: d for d in compute_diff({"resume_headline": "  ", "profile_summary": None,
                                               "notice_period": None}, portal, portal)}
    assert diffs["resume_headline"].status is S.SKIPPED_EMPTY_SOURCE
    assert diffs["resume_headline"].reason == "portal_value_kept"
    assert diffs["profile_summary"].status is S.SKIPPED_EMPTY_SOURCE
    assert diffs["notice_period"].status is S.SKIPPED_EMPTY_SOURCE


def test_skills_are_add_only_and_removals_are_only_reported():
    portal = {"key_skills": FieldValue(["Python", "Django", "jQuery"])}
    (diff,) = [d for d in compute_diff({"key_skills": ["python", "FastAPI", "Django", "PostgreSQL"]}, portal,
                                       {"key_skills"}) if d.field == "key_skills"]
    assert diff.status is S.WOULD_UPDATE
    assert diff.additions == ("FastAPI", "PostgreSQL") and diff.removals == ("jQuery",)
    assert diff.proposed == ["Python", "Django", "jQuery", "FastAPI", "PostgreSQL"]  # nothing removed
    assert diff.reason == "removals_not_applied"
    (same,) = [d for d in compute_diff({"key_skills": ["PYTHON"]}, portal, {"key_skills"})
               if d.field == "key_skills"]
    assert same.status is S.UNCHANGED and same.removals == ("Django", "jQuery")


def test_diff_statuses_for_unchanged_update_unsupported_and_not_calibrated():
    portal = {"current_ctc": FieldValue("12.5 LPA"), "expected_ctc": FieldValue("18 LPA"),
              "notice_period": FieldValue(status=S.SKIPPED_NOT_CALIBRATED, reason="selectors_not_calibrated")}
    diffs = {d.field: d for d in compute_diff({"current_ctc": 12.5, "expected_ctc": 20, "notice_period": 30},
                                              portal, {"current_ctc", "expected_ctc", "notice_period",
                                                       "resume_headline"})}
    assert set(diffs) == set(FIELDS)
    assert diffs["current_ctc"].status is S.UNCHANGED
    assert diffs["expected_ctc"].status is S.WOULD_UPDATE and diffs["expected_ctc"].proposed == 20
    assert diffs["notice_period"].status is S.SKIPPED_NOT_CALIBRATED
    assert diffs["resume_headline"].status is S.ERROR  # supported but not read
    assert diffs["profile_summary"].status is S.SKIPPED_UNSUPPORTED


def test_public_views_carry_only_hash_references():
    diff = FieldDiff("profile_summary", S.WOULD_UPDATE, "old secret text", "new secret text")
    public = diff.public()
    assert public["proposed"] == {"sha256": hashlib.sha256(b"new secret text").hexdigest(), "length": 15}
    assert "secret" not in repr(public)
    report = SyncReport("naukri", True, "cli", {"profile_summary": diff})
    assert "secret" not in repr(report.public()) and "1 would_update" in report.summary()
    assert value_ref(None) is None and (value_ref(["a"]) or {}).get("length") == 5


def test_run_status_aggregation():
    def report(*statuses):
        return SyncReport("naukri", False, "cli", {str(i): FieldDiff(str(i), s) for i, s in enumerate(statuses)})
    assert run_status(report(S.SKIPPED_UNSUPPORTED, S.SKIPPED_NOT_CALIBRATED)) == "skipped"
    assert run_status(report(S.UNCHANGED, S.WOULD_UPDATE)) == "ok"
    assert run_status(report(S.UPDATED, S.VERIFY_FAILED)) == "partial"
    assert run_status(report(S.ERROR, S.UNCHANGED)) == "failed"


def test_live_flag_is_read_defensively():
    assert profile_sync_live({"profile_sync": {"naukri": {"live": True}}}, "naukri")
    for prefs in (None, {}, {"profile_sync": None}, {"profile_sync": {"naukri": {"live": "true"}}},
                  {"profile_sync": {"naukri": True}}, {"profile_sync": {"wellfound": {"live": True}}}):
        assert not profile_sync_live(prefs, "naukri")


def test_canonical_snapshot_from_profile(tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake resume")
    profile = {"verified_skills": ["SQL", "python"], "summary": "Top-level summary",
               "preferences": {"headline": " Backend  Engineer ", "tech_stack": ["Python", "FastAPI"],
                               "notice_period_days": 30, "current_ctc": 12.5, "expected_ctc": 18,
                               "preferred_locations": ["Bengaluru"], "open_to_relocation": True,
                               "relocation_locations": ["Pune"], "current_location": "Delhi",
                               "resume_files": {"default": str(pdf)}}}
    snap = snapshot_from_profile(profile)
    assert snap.get("resume_headline") == "Backend Engineer"
    assert snap.get("profile_summary") == "Top-level summary"
    assert snap.get("key_skills") == ["Python", "FastAPI", "SQL"]
    assert snap.get("preferred_locations") == ["Bengaluru", "Pune"]
    assert snap.get("notice_period") == 30 and snap.get("current_location") == "Delhi"
    assert snap.resume_sha256 == hashlib.sha256(pdf.read_bytes()).hexdigest() and snap.resume_path == str(pdf)
    assert snap.get("resume_pdf") == {"path": str(pdf), "sha256": snap.resume_sha256}
    assert "Backend" not in repr(snap.public())
    empty = snapshot_from_profile({})
    assert empty.get("resume_pdf") is None and empty.get("key_skills") == []
