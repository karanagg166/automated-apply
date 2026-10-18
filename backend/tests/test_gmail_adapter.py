"""Tests for Gmail job alert email parsing and adapter."""

import pytest
from backend.app.services.job_sources.gmail_adapter import GmailJobAlertAdapter


def test_naukri_alert_html_parsing():
    adapter = GmailJobAlertAdapter()
    sample_html = """
    <html>
      <body>
        <h2>Naukri Job Alerts for 'Python Backend Engineer'</h2>
        <div class="job-card">
          <a href="https://www.naukri.com/job-listings-python-backend-razorpay-12345">Senior Backend Engineer</a>
          <p>Company: Razorpay in Bengaluru</p>
        </div>
      </body>
    </html>
    """
    jobs = adapter.parse_alert_html_or_text(
        message_id="msg_001",
        subject="Naukri Job Alert: Senior Backend Engineer roles in Bengaluru",
        sender="alert@naukri.com",
        body=sample_html,
    )

    assert len(jobs) >= 1
    job = jobs[0]
    assert job.source_name == "gmail_alert"
    assert "Senior Backend Engineer" in job.title
    assert "Razorpay" in job.company_name
    assert "naukri.com" in job.original_url
    assert job.data_provenance["email_message_id"] == "msg_001"


def test_linkedin_alert_html_parsing():
    adapter = GmailJobAlertAdapter()
    sample_html = """
    <html>
      <body>
        <p>30 new jobs in India match your preferences</p>
        <a href="https://www.linkedin.com/jobs/view/4100223344">Staff Python Architect</a>
        at Atlassian in Bengaluru, Karnataka, India
      </body>
    </html>
    """
    jobs = adapter.parse_alert_html_or_text(
        message_id="msg_002",
        subject="30 new jobs for 'Python Architect'",
        sender="jobalerts-noreply@linkedin.com",
        body=sample_html,
    )

    assert len(jobs) >= 1
    job = jobs[0]
    assert job.source_name == "gmail_alert"
    assert "Staff Python Architect" in job.title
    assert "Atlassian" in job.company_name


@pytest.mark.asyncio
async def test_gmail_adapter_unconfigured_status():
    adapter = GmailJobAlertAdapter(
        client_id=None, client_secret=None, refresh_token=None
    )
    status = await adapter.test_connection()
    assert status["status"] == "not_attempted"
    assert status["details"]["is_parser_ready"] is True
