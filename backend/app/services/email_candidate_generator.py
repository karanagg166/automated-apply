"""Email candidate generation based on corporate pattern inference."""

import re
import unicodedata
from backend.app.schemas.contact import EmailCandidate


class EmailCandidateGenerator:
    """Generates standard corporate email candidates from person name and company domain.
    
    IMPORTANT: Generated candidates are mathematically derived guesses and are
    strictly labeled as status="candidate". They MUST NOT be treated as verified.
    """

    SUPPORTED_PATTERNS = [
        ("{first}.{last}@{domain}", "first.last"),
        ("{first}@{domain}", "first"),
        ("{first}{last}@{domain}", "firstlast"),
        ("{f}{last}@{domain}", "flast"),
        ("{first}{l}@{domain}", "firstl"),
        ("{last}.{first}@{domain}", "last.first"),
    ]

    @staticmethod
    def _clean_string(text: str) -> str:
        """Normalize Unicode, strip accents, and remove non-alphanumeric characters."""
        if not text:
            return ""
        # Normalize to NFKD and drop combining diacritical marks
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ASCII", "ignore").decode("ASCII")
        # Remove any characters other than letters and digits
        return re.sub(r"[^a-zA-Z0-9]", "", ascii_text).lower()

    @classmethod
    def generate_candidates(
        cls,
        first_name: str,
        last_name: str,
        domain: str,
        known_pattern: str | None = None,
    ) -> list[EmailCandidate]:
        """Generate email candidates for a given name and company domain."""
        if not domain:
            return []

        cleaned_domain = domain.strip().lower()
        # Remove any leading http://, https://, or www.
        cleaned_domain = re.sub(r"^(https?://)?(www\.)?", "", cleaned_domain).split("/")[0]

        fn = cls._clean_string(first_name)
        ln = cls._clean_string(last_name)

        if not fn and not ln:
            return []

        f_initial = fn[0] if fn else ""
        l_initial = ln[0] if ln else ""

        # Context dict for formatting
        context = {
            "first": fn,
            "last": ln,
            "f": f_initial,
            "l": l_initial,
            "domain": cleaned_domain,
        }

        candidates: list[EmailCandidate] = []

        # If the company has a verified known pattern in our database, prioritize it
        if known_pattern:
            try:
                formatted_email = known_pattern.format(**context)
                if "@" in formatted_email and "." in formatted_email.split("@")[1]:
                    candidates.append(
                        EmailCandidate(
                            email=formatted_email,
                            pattern_used=f"known_company_pattern:{known_pattern}",
                            status="candidate",
                            confidence_score=0.75,
                        )
                    )
            except (KeyError, IndexError, ValueError):
                pass

        # Generate candidates from standard patterns
        for template, pattern_name in cls.SUPPORTED_PATTERNS:
            # Skip patterns that require last name if last name is missing
            if "{last}" in template and not ln:
                continue
            if "{first}" in template and not fn:
                continue
            if "{l}" in template and not l_initial:
                continue
            if "{f}" in template and not f_initial:
                continue

            try:
                candidate_email = template.format(**context)
                # Avoid duplicate if already generated from known pattern
                if not any(c.email == candidate_email for c in candidates):
                    candidates.append(
                        EmailCandidate(
                            email=candidate_email,
                            pattern_used=template,
                            status="candidate",
                            confidence_score=0.40,
                        )
                    )
            except (KeyError, IndexError, ValueError):
                continue

        return candidates
