"""Reproduce owner tracking/report DTOs without loading private runtime configuration."""
import argparse
import json

from rust.scripts.packet_contract_corpus import ROOT, packet_models


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    models = packet_models()
    cases = []
    for kind, name, base, variants in (
        ("submission", "SubmissionInput", dict(expected_revision=1, idempotency_key="fictional-report-01", human_confirmed=True, confirmation="I submitted this application on the official website"), dict(human_confirmed=[False, 1, "true", None], confirmation=["submitted", None, " I submitted this application on the official website "], receipt_reference=[None, "", " ", " receipt-1 ", "x" * 256], idempotency_key=["short", "abcdefgh!", "abcdefgh\n", " abcdefgh ", "x" * 101])),
        ("tracking", "TrackingInput", dict(expected_revision=1, tracking_state="archived"), dict(tracking_state=[None, "not_applied", "applied_manually", "applied_verified", "application_incomplete", "application_rejected", "interview_scheduled", "offer_received", "archived", " archived ", "invented"], lifecycle_state=[None, "external_application_opened", "withdrawn", "abandoned", "submitting", "provider_confirmed_submitted", " withdrawn "])),
    ):
        requests = [base, {}, {**base, "approved_revision": 2}]
        variants.update(expected_revision=[None, 0, 1, 2147483646, 2147483647, True, 1.0, 1.5, "1", "1.0"], note=[None, "", " ", " audit note ", "x" * 1001])
        for key, values in variants.items():
            requests.extend({**base, key: value} for value in values)
        for request in requests:
            try:
                result = dict(accepted=True, output=models[name].model_validate(request).model_dump(mode="json"))
            except ValueError:
                result = dict(accepted=False)
            cases.append(dict(kind=kind, input=request, **result))
    path = ROOT / "rust/agent-runtime/tests/fixtures/packet-tracking-corpus.json"
    encoded = json.dumps(cases, indent=2, sort_keys=True) + "\n"
    if args.check:
        if path.read_text() != encoded:
            raise SystemExit("packet_tracking_contract_drift")
    else:
        path.write_text(encoded)
    print(f"fictional_packet_tracking_contracts:{len(cases)}")


if __name__ == "__main__":
    main()
