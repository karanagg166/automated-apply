"""Tests for corporate email pattern candidate generation."""

from backend.app.services.email_candidate_generator import EmailCandidateGenerator


def test_standard_candidate_generation():
    candidates = EmailCandidateGenerator.generate_candidates(
        first_name="Alex",
        last_name="Smith",
        domain="techcorp.com",
    )
    assert len(candidates) > 0
    candidate_emails = [c.email for c in candidates]

    # Verify standard formats
    assert "alex.smith@techcorp.com" in candidate_emails
    assert "alex@techcorp.com" in candidate_emails
    assert "alexsmith@techcorp.com" in candidate_emails
    assert "asmith@techcorp.com" in candidate_emails

    # Verify strict safety guarantees
    for c in candidates:
        assert c.status == "candidate"
        assert "NOT a verified mailbox" in c.disclaimer


def test_accent_stripping_and_unicode_normalization():
    # Names with French accents or special characters
    candidates = EmailCandidateGenerator.generate_candidates(
        first_name="Élodie",
        last_name="René-Dupond",
        domain="https://www.company.fr/careers",
    )
    candidate_emails = [c.email for c in candidates]
    # 'élodie' -> 'elodie', 'rené-dupond' -> 'renedupond'
    assert "elodie.renedupond@company.fr" in candidate_emails


def test_known_pattern_prioritization():
    candidates = EmailCandidateGenerator.generate_candidates(
        first_name="Sarah",
        last_name="Connor",
        domain="cyberdyne.com",
        known_pattern="{first}_{last}@{domain}",
    )
    # The known pattern candidate should be first with higher confidence
    assert candidates[0].email == "sarah_connor@cyberdyne.com"
    assert candidates[0].confidence_score == 0.75
    assert candidates[0].status == "candidate"


def test_missing_last_name_handling():
    candidates = EmailCandidateGenerator.generate_candidates(
        first_name="Madonna",
        last_name="",
        domain="music.com",
    )
    candidate_emails = [c.email for c in candidates]
    assert "madonna@music.com" in candidate_emails
    # Patterns requiring last name should not be generated
    assert not any("." in e.split("@")[0] for e in candidate_emails)
