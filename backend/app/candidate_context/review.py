"""Private, inert owner review artifacts; generating requests never approves facts."""

import base64
import html
import json
import os
from pathlib import Path

from backend.app.candidate_context.common import canonical_hash


def confirmation_requests(profile, resume, primary_resource_id, projects):
    """Pin every request to the exact material shown in the private review."""
    return {
        "profile_id": str(profile.id),
        "profile_version": profile.version,
        "resume": {
            "method": "POST",
            "path": f"/api/v1/dashboard/resumes/{resume.id}/confirm",
            "body": {
                "owner_confirmed": True,
                "primary": True,
                "expected_primary_resource_id": str(primary_resource_id)
                if primary_resource_id
                else None,
                "expected_sha256": resume.sha256,
                "expected_profile_version": profile.version,
            },
        },
        "projects": [
            {
                "method": "POST",
                "path": f"/api/v1/dashboard/candidate-context/projects/{p.configuration.id}/approve",
                "body": {
                    "expected_revision": p.revision,
                    "fact_ids": [f.id for f in p.facts if f.approvable],
                    "owner_confirmed": True,
                },
            }
            for p in projects
        ],
    }


def render_review(payload, *, pdf_bytes):
    """All source text is escaped. The only script exports unchecked selections.

    There is no token, network submission, external asset or approval side effect.
    """
    esc = lambda value: html.escape(str(value), quote=True)
    blocks = []
    for project in payload["projects"]:
        rows = []
        for fact in project["facts"]:
            enabled = fact["approvable"]
            rows.append(
                '<tr><td><input type="checkbox" class="fact" data-project="'
                + esc(project["id"])
                + '" data-personal="'
                + str(fact["personal_claim"]).lower()
                + '" value="'
                + esc(fact["id"])
                + '"'
                + ("" if enabled else " disabled")
                + "></td><td>"
                + esc(fact["topic"])
                + (
                    " · personal claim"
                    if fact["personal_claim"]
                    else " · project observation"
                )
                + "<br><code>"
                + esc(fact["id"])
                + "</code></td><td>"
                + esc(fact["text"])
                + "<details><summary>Source references</summary><pre>"
                + esc(json.dumps(fact["evidence"], indent=2))
                + "</pre></details></td><td>"
                + esc(fact["verification"])
                + (
                    " · requires confirmation"
                    if enabled
                    else " · unsupported; excluded"
                )
                + "</td></tr>"
            )
        unsupported = project.get("unsupported_stack_claims", [])
        caveat = (
            (
                " Bounded automatic extraction did not establish these configured technologies: "
                + ", ".join(unsupported)
                + ". Inspect the supplied source references for additional support."
            )
            if unsupported
            else ""
        )
        blocks.append(
            "<section><h2>"
            + esc(project["name"])
            + "</h2><p>Source commit: <code>"
            + esc(
                project.get("commit_sha")
                or "No repository; resume/employment evidence only"
            )
            + "</code><br>Project revision: <code>"
            + esc(project["revision"])
            + "</code></p><p>"
            + esc(project.get("limitations", "") + caveat)
            + '</p><label><input type="checkbox" class="group" data-project="'
            + esc(project["id"])
            + '" data-personal="false"> Select this project’s supported observations after review</label>'
            + (
                '<label><input type="checkbox" class="group" data-project="'
                + esc(project["id"])
                + '" data-personal="true"> Separately confirm this project’s proposed personal contributions</label>'
                if any(
                    f["personal_claim"] and f["approvable"] for f in project["facts"]
                )
                else "<p>No personal contribution is proposed for this project.</p>"
            )
            + "<table><thead><tr><th>Select</th><th>Fact and ID</th><th>Proposed statement</th><th>Evidence classification</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></section>"
        )
    requests = (
        json.dumps(payload["requests"], ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace("&", "\\u0026")
    )
    # Data JSON is inert; source strings never become executable JavaScript.
    document = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; object-src data:; frame-src data:; base-uri 'none'; form-action 'none'; connect-src 'none'">
<title>Private resume and project owner review</title><style>body{font:16px system-ui;max-width:1400px;margin:32px auto;padding:0 20px;color:#172238;background:#f5f7fa}section{background:white;padding:24px;margin:20px 0;border:1px solid #ccd4df;border-radius:10px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:12px;text-align:left;border:1px solid #d7dce2;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere}code{overflow-wrap:anywhere;font-size:12px}object{width:100%;height:800px}input{width:20px;height:20px}button{padding:12px;font:inherit}li{margin:10px 0}.gate{background:#fff0ca;padding:20px}label{display:block;margin:14px 0}</style>
<h1>Private resume and project review</h1><p class="gate">Pending owner review. Nothing in this report confirms a resume or approves project facts. Select only the statements you accept. Downloading selections creates a local request file; it sends nothing.</p>"""
    document += (
        "<p>Profile version: "
        + esc(payload["profile_version"])
        + " · Review hash: <code>"
        + esc(payload["review_hash"])
        + "</code></p>"
    )
    document += (
        "<section><h2>Resume contents</h2><p>"
        + esc(payload["resume_status"])
        + "</p><p>SHA-256: <code>"
        + esc(payload["resume_sha256"])
        + "</code></p>"
    )
    document += (
        '<object type="application/pdf" data="data:application/pdf;base64,'
        + base64.b64encode(pdf_bytes).decode("ascii")
        + '"><p>Use the extracted text below if your browser cannot preview a local PDF.</p></object>'
    )
    document += (
        "<details open><summary>Safely extracted PDF text</summary><pre>"
        + esc(payload["resume_text"])
        + "</pre></details>"
    )
    document += '<label><input id="resume" type="checkbox"> I reviewed this PDF and approve it as my primary resume.</label></section>'
    document += (
        "<section><h2>Profile and resume differences</h2><ul>"
        + "".join("<li>" + esc(v) + "</li>" for v in payload["differences"])
        + "</ul>"
    )
    document += (
        "<details><summary>Saved profile version "
        + esc(payload["profile_version"])
        + "</summary><pre>"
        + esc(json.dumps(payload["profile"], indent=2))
        + "</pre></details></section>"
    )
    document += "".join(blocks)
    document += (
        "<section><h2>Unsupported claims and missing information</h2><ul>"
        + "".join("<li>" + esc(v) + "</li>" for v in payload["missing_information"])
        + "</ul></section>"
    )
    document += (
        "<section><h2>Current answer readiness (approved evidence only)</h2><pre>"
        + esc(json.dumps(payload["answer_checks"], indent=2))
        + "</pre></section>"
    )
    document += '<section><h2>Owner actions</h2><label><input id="confirm" type="checkbox"> I reviewed and approve the selected project facts, including any personal contribution statements.</label><button id="export" type="button">Download selected confirmation requests</button><p id="status" role="status"></p></section>'
    document += (
        '<script id="requests" type="application/json">' + requests + "</script>"
    )
    document += """<script>
for (const group of document.querySelectorAll('.group')) group.addEventListener('change', () => {
 for (const fact of document.querySelectorAll('.fact:not(:disabled)')) {
  if (fact.dataset.project === group.dataset.project && fact.dataset.personal === group.dataset.personal) fact.checked = group.checked;
 }
});
document.getElementById('export').addEventListener('click', () => {
 const requests = JSON.parse(document.getElementById('requests').textContent);
 const selected = [...document.querySelectorAll('.fact:checked')];
 if (selected.length && !document.getElementById('confirm').checked) {
   document.getElementById('status').textContent = 'Confirm that you reviewed the selected project facts first.'; return;
 }
 const result = {profile_id: requests.profile_id, profile_version: requests.profile_version, review_hash: requests.review_hash, requests: []};
 if (document.getElementById('resume').checked) result.requests.push(requests.resume);
 for (const request of requests.projects) {
   const id = request.path.split('/').at(-2);
   const ids = selected.filter(el => el.dataset.project === id).map(el => el.value);
   if (ids.length) result.requests.push({...request, body: {...request.body, fact_ids: ids}});
 }
 if (!result.requests.length) {document.getElementById('status').textContent = 'Select a reviewed resume or project fact first.'; return;}
 const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type:'application/json'}));
 const a = document.createElement('a'); a.href = url; a.download = 'selected-owner-confirmations.json'; a.click();
 URL.revokeObjectURL(url); document.getElementById('status').textContent = 'Saved locally. No approvals were sent.';
});
</script></html>"""
    return document


def write_private_review(output: Path, payload: dict, *, pdf_bytes: bytes):
    """Refuse tracked-tree output and create artifacts readable only by the owner."""
    output = output.expanduser().resolve()
    if any((parent / ".git").exists() for parent in (output, *output.parents)):
        raise ValueError("private_review_must_be_outside_repository")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    payload = {**payload, "review_hash": canonical_hash(payload)}
    payload["requests"] = {**payload["requests"], "review_hash": payload["review_hash"]}
    for name, data in [
        ("review.html", render_review(payload, pdf_bytes=pdf_bytes)),
        ("review-manifest.private.json", json.dumps(payload, indent=2)),
    ]:
        # Exclusive creation prevents symlink following and accidental review replacement.
        descriptor = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(data)
    return output / "review.html"


def selected_requests(manifest: dict, selection: dict) -> list[dict]:
    """Validate owner-selected requests against an intact, exact review artifact."""
    from copy import deepcopy

    original = deepcopy(manifest)
    review_hash = original.pop("review_hash")
    original["requests"].pop("review_hash")
    if (
        canonical_hash(original) != review_hash
        or selection.get("review_hash") != review_hash
        or selection.get("profile_id") != manifest["requests"]["profile_id"]
        or selection.get("profile_version") != manifest["profile_version"]
    ):
        raise ValueError("review_changed_regenerate")
    allowed = {
        r["path"]: r
        for r in [manifest["requests"]["resume"], *manifest["requests"]["projects"]]
    }
    result = selection.get("requests", [])
    if not result or len(result) > len(allowed):
        raise ValueError("select_reviewed_items")
    seen = set()
    for request in result:
        expected = deepcopy(allowed.get(request.get("path")))
        if (
            expected is None
            or request["path"] in seen
            or request.get("body", {}).get("owner_confirmed") is not True
        ):
            raise ValueError("explicit_owner_selection_required")
        seen.add(request["path"])
        if "fact_ids" in expected["body"]:
            ids = request["body"].get("fact_ids", [])
            if (
                not ids
                or len(set(ids)) != len(ids)
                or set(ids) - set(expected["body"]["fact_ids"])
            ):
                raise ValueError("fact_selection_not_in_review")
            expected["body"]["fact_ids"] = ids
        if request != expected:
            raise ValueError("confirmation_request_changed")
    return result
