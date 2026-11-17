# Naukri worker dispatch and receipt proof

Local branch `feat/rust-agent-runtime`, implementation `579be223cfa9c487dc9280eb66cdb0267e622fe7`.

The native runtime now retains the authenticated browser acknowledgment of Apply with the original document, approved account, and durable admission. A strict receipt requires that acknowledgment to precede two independent history views. For the questionnaire path, it also requires an acknowledged answer and no original form loss. An unresolved admission can still reconcile against provider history, with its quota consumed. That history cannot enable recurring applications.

Recurring authorization also checks that the receipt matches the immutable submission evidence for the same packet and candidate. A packet with prior submission evidence is preserved and cannot be attributed to the new worker. The older receipt history readers retain their compatibility.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source formatting and whitespace | PASS | Rust formatting and Git whitespace checks completed. |
| Native receipt and PostgreSQL | NOT TESTED | One new fixture covers admitted Apply without browser acknowledgment. Existing fixtures now drive acknowledgment, independent reload, linked packet evidence, changed receipt hash and fallback past damaged records. |
| Live Naukri validation | NOT TESTED | No browser, queue, installed service or application admission was used. The recorded first strict worker receipt is still pending. |

Include the execution policy and disposable PostgreSQL suites in the combined local run. The engineering estimate remains 58% complete. The stricter receipt check needs validation against the approved browser path and the remaining supervised application attempt.
