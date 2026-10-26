"""Closed paraphrase grammar for narrative routing and approved-answer retrieval.

Full-question matches only: extra entities, qualifications, negation or instructions
must retain their original meaning. This never rewrites the saved question, model
prompt or owner approval, and never establishes a candidate fact.
"""

import re

from backend.app.services.profile_link_resolver import normalize

PHRASES = (
    (
        r"(?:walk (?:me|us) through|share an example of) (?:a|your) "
        r"project(?: (?:that )?you (?:built|developed|implemented))?",
        "Describe a project you built",
    ),
    (
        r"walk (?:me|us) through (?:a|your) (?:technically )?challenging "
        r"project(?: (?:that )?you (?:built|developed|implemented))?",
        "Describe a challenging project you built",
    ),
    (
        r"(?:give (?:me|us) (?:a|your) (?:brief )?professional introduction|"
        r"share (?:a|your) (?:short )?professional bio|"
        r"tell (?:me|us) a little about yourself|briefly introduce yourself)",
        "Introduce yourself",
    ),
    (
        r"(?:what (?:attracts|drew|draws) you to (?:this|our) "
        r"(?:company|role|position|opportunity)|"
        r"what (?:excites|interests) you about (?:this|our) "
        r"(?:company|role|position|opportunity)|"
        r"what is your motivation for (?:applying|joining)(?: here)?)",
        "Why do you want to join this company",
    ),
    (
        r"what (?:attracts|drew|draws) you to (?:this|our) startup",
        "Why do you want to join this startup",
    ),
)


def canonical_question(question: str) -> str | None:
    if len(question) > 2000:
        return None
    text = normalize(question)
    for pattern, canonical in PHRASES:
        if re.fullmatch(pattern, text):
            return canonical
    return None
