"""Project-.env owner config: portal-login vault, resume fallback, target_titles roles."""

from __future__ import annotations

from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.auth import ChainVault, EnvVault, MemoryVault
from backend.app.browser_v2.rules import CandidatePreferences
from backend.app.browser_v2.service import apply_env_profile, env_profile_overrides

PW = "TEST_FAKE_TOKEN_ONLY"


def test_env_vault_shared_login_with_per_portal_override():
    env = {"PORTAL_LOGIN_EMAIL": "owner@example.com", "PORTAL_LOGIN_PASSWORD": PW,
           "PORTAL_NAUKRI_EMAIL": "naukri@example.com", "PORTAL_NAUKRI_PASSWORD": PW + "_N"}
    vault = EnvVault(env)
    assert vault.get("instahyre") == ("owner@example.com", PW)
    assert vault.get("naukri") == ("naukri@example.com", PW + "_N")
    assert EnvVault({"PORTAL_LOGIN_EMAIL": "owner@example.com"}).get("naukri") is None  # no password: none


def test_chain_vault_prefers_project_env_then_keychain():
    keychain = MemoryVault({"wellfound": ("kc@example.com", "TEST_FAKE_KC")})
    chain = ChainVault(EnvVault({}), keychain)
    assert chain.get("wellfound") == ("kc@example.com", "TEST_FAKE_KC") and chain.get("naukri") is None
    chain = ChainVault(EnvVault({"PORTAL_LOGIN_EMAIL": "e@example.com", "PORTAL_LOGIN_PASSWORD": PW}), keychain)
    assert chain.get("wellfound") == ("e@example.com", PW)


def test_resume_path_from_project_env_fills_only_missing_resume(tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    overrides = env_profile_overrides({"CANDIDATE_RESUME_PATH": str(pdf)})
    facts = apply_env_profile(CandidateFacts.from_profile({"full_name": "Test Candidate"}), overrides)
    assert facts.resume_files == {"default": str(pdf)} and facts.identity["resume_path"] == str(pdf)
    stored = CandidateFacts.from_profile({"preferences": {"resume_files": {"backend": "/x/b.pdf"}}})
    assert apply_env_profile(stored, overrides).resume_files == {"backend": "/x/b.pdf"}  # DB value wins
    assert apply_env_profile(CandidateFacts(), env_profile_overrides({"CANDIDATE_RESUME_PATH": str(tmp_path / "no.pdf")})
                             ).resume_files == {}  # missing file: never pretend


def test_target_titles_from_dashboard_schema_count_as_target_roles():
    prefs = CandidatePreferences.from_profile({"preferences": {"target_titles": ["Backend Engineer", "SDE"]}})
    assert prefs.target_roles == ("Backend Engineer", "SDE")
