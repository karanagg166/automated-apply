import pytest
from backend.app.services.application_question_classifier import ApplicationQuestionClassifier


@pytest.mark.parametrize("question,category,field", [
    ("GitHub profile link?", "profile_link", None), ("Upload your resume", "file_upload", None),
    ("How many years of experience do you have?", "personal_details", "verified_experience_years"),
    ("What is your notice period?", "personal_details", "notice_period_days"),
    ("Email address", "personal_details", "email"), ("Your full name", "personal_details", "full_name"),
    ("Tell us about your most technically challenging project", "project_explanation", None),
    ("What's the most impressive thing you have built?", "project_explanation", None),
    ("Why would you like to work at our startup?", "startup_interest", None),
    ("Why join our company?", "motivation", None), ("Work authorization", "work_authorization", "work_authorization"),
    ("What is your current salary?", "compensation", None),
    ("Describe your experience with FastAPI", "technical_experience", None),
    ("Tell us about yourself", "short_text", None), ("What is your favorite color?", "unknown", None),
    ("Email and phone", "unknown", None), ("How many years of experience in Python?", "unknown", None),
])
def test_classification(question, category, field):
    result = ApplicationQuestionClassifier().classify(question)
    assert (result.question_type, result.field) == (category, field)
