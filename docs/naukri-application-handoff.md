# Naukri manual handoff walkthrough

All names, links, questions, resume resources and receipts below are fictional examples. Replace
IDs with saved records returned by your own authorized development backend. No portal requests,
login, browser opening, downloads, file uploads or application submissions occur on the backend.
See [the application contract](application-preparation.md) for migration, security and lifecycle details.

## Executable offline demonstration

```bash
backend/venv/bin/python -m backend.scripts.demo_application_preparation
```

This creates a disposable in-memory database and uses an injected fake Gemini provider. Its output
demonstrates Job → Profile → Resume → Questions → Grounded Answer → Review → Manual Handoff →
User-Reported Submission. The reported completion is fictional test data, not an actual application.

## Saved profile, resume and job

Use existing protected profile/resource/discovery APIs; Phase 5A does not replace them. For example,
Alex Example has the confirmed Example Relay project: purpose "A service for sharing task updates",
contribution "I implemented backend authentication using Python and FastAPI", challenge "Concurrent
connections required consistent authentication", and solution "I checked authentication before
accepting each connection". Alex's saved links are `https://github.com/example` and
`https://www.linkedin.com/in/example`. Unknown salary and country-specific authorization remain missing.

The saved `CandidateResource` is a confirmed primary resume named "Confirmed Backend Resume", URL
`https://drive.google.com/file/d/fictional-resume/view`. It has no uploaded bytes. The job is Backend
Engineer at Example Circuit, discovered from a saved Naukri posting, with a saved external application
URL `https://circuit.example.org/careers/backend`. Returning this URL does not live-verify it.

## REST walkthrough

In a shell, set `API=http://127.0.0.1:8000`, `JOB_ID` to the saved job UUID and `JOB_AGENT_API_TOKEN`
from your secret environment. Do not paste tokens into documentation, issue comments or logs.

Preview and create (neither spends AI credits):

```bash
curl -sS "$API/api/v1/jobs/$JOB_ID/application-preview" \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{}'

curl -sS "$API/api/v1/jobs/$JOB_ID/application-packets" \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"idempotency_key":"example-packet-0001","questions":[{"question":"Describe your most technically challenging project","field_type":"textarea","required":true,"max_characters":1200,"max_words":150,"writing_style":"technical"}]}'
```

The creation response contains `id`, `revision=1`, the selected resume, field UUIDs and missing
information. Set `PACKET_ID` to the response's packet ID and `FIELD_ID` to the narrative field ID.
The question stays unanswered until explicit generation or human input. The seven core fields
are local checklist items, not a discovered Naukri form. You can add actual form questions later:

```bash
curl -sS "$API/api/v1/application-packets/$PACKET_ID/questions" \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"expected_revision":1,"questions":[{"question":"What is your GitHub profile?","field_type":"url","required":true}]}'
```

That saved link resolves deterministically and advances the packet to revision 2. Generate the
narrative with the configured Gemini account (this explicit request can consume its existing quota):

```bash
curl -sS "$API/api/v1/application-packets/$PACKET_ID/questions/$FIELD_ID/generate" \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"expected_revision":2}'
```

With the offline fixture, the proposed answer is:

> Example Relay is a service for sharing task updates. I implemented backend authentication using
> Python and FastAPI. Concurrent connections required consistent authentication. I checked
> authentication before accepting each connection.

Its provenance includes verified project references, `source=gemini`, the existing answer draft
ID, and pending human review. A real Gemini response can differ and must pass validation/review.
Unavailable credentials produce `provider_unavailable`, missing evidence produces `needs_input`,
and unsupported claims/over-limit output produce `validation_failed`; none is a completed answer.

Inspect the entire packet, compare each narrative to saved evidence, check that the vacancy remains
open, and confirm the correct resume/destination. Human edits use the field PATCH with
`{"expected_revision":3,"answer":"Your factual corrected answer"}` and require re-review. For the
unchanged generated example, review/approve revision 3 (replace the placeholder field UUID):

```bash
curl -sS "$API/api/v1/application-packets/$PACKET_ID/review" \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"expected_revision":3,"action":"approve","reviewed_field_ids":["REPLACE_WITH_NARRATIVE_FIELD_UUID"],"confirm_resume":true,"confirm_destination":true}'

curl -sS "$API/api/v1/application-packets/$PACKET_ID/handoff" \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN"
```

Revision 4 is now approved for manual handoff. If you edited an answer or added more questions,
use the latest response revision and review all populated narratives/edited fields. Stale packets
must be refreshed and re-reviewed. Handoff GETs do not mutate the packet or open anything.

## What the owner receives

```text
Company: Example Circuit
Position: Backend Engineer
Preparation platform: Naukri
Destination: employer_external (saved URL; availability not live verified)
Application URL: https://circuit.example.org/careers/backend
Resume: Confirmed Backend Resume
Resume resource: saved UUID + version digest
Resume link: https://drive.google.com/file/d/fictional-resume/view
Resume instruction: manual_resume_upload_required
GitHub: https://github.com/example
LinkedIn: https://www.linkedin.com/in/example
Question: Describe your most technically challenging project
Prepared answer: the reviewed Example Relay answer above
Review: approved for exact revision 4
Readiness: ready_for_manual_handoff
Submission mode: manual_handoff
Submitted: false
```

Open the returned URL yourself in your normal browser. Verify its destination and active vacancy,
select the actual resume file, copy the reviewed answers, complete any remaining fields, and submit
on the official site. An expired listing or new mandatory question can require additional input;
the packet does not guarantee acceptance by that website. Never report completion merely because
you opened the link or approved a packet.

Optionally record opening (a report only, not a browser command), then actual submission:

```bash
curl -sS -X PATCH "$API/api/v1/application-packets/$PACKET_ID/tracking" \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"expected_revision":4,"lifecycle_state":"external_application_opened"}'

curl -sS "$API/api/v1/application-packets/$PACKET_ID/report-submission" \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"expected_revision":5,"idempotency_key":"example-submission-0001","human_confirmed":true,"confirmation":"I submitted this application on the official website","receipt_reference":"Example owner-reported confirmation ABC"}'

curl -sS "$API/api/v1/application-packets/$PACKET_ID/events" \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN"
```

The evidence is labeled `confirmation_source=user_reported`, `evidence_confidence=self_reported_unverified`.
The packet becomes `user_reported_submitted`, tracking becomes `applied_manually`, readiness becomes
`completed_by_user`. `Job.status` remains unchanged. The optional receipt is owner-supplied text;
there is no Naukri/provider confirmation. Retrying the identical original report returns the same
evidence, not a second submission event. Follow-up outcomes such as interview/offer can be recorded
through tracking with the latest revision. They neither send messages nor erase submission history.

## Future execution

Phase 5B — Supported Browser/Application Execution Without apply-extension — starts with a separate
review of a permitted integration method and explicit provider/account authority. No official
submission route or browser execution architecture has been verified or implemented here. A future
provider-confirmed state needs real authorized receipt evidence and a separately reviewed migration.
