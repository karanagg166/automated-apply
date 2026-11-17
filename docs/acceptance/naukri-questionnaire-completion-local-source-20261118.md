# Naukri questionnaire completion and history verification

Local branch `feat/rust-agent-runtime`, implementation `898692e6328acc14be64a4cdff8f42ac543f7b34`.

After an acknowledged answer, the extension can observe that the original questionnaire drawer closed. It then uses the existing read-only listing observer in the same browser document. The backend checks both retained document identities, the account, the vacancy, and the original form binding before scheduling independent history verification. The original Apply admission and retained tab stay associated with the attempt.

A positive listing status is an intermediate observation. The native strict receipt still needs the Apply acknowledgment, this same-document completion evidence for questionnaires, and two independent history observations. The legacy route uses the same transition contract. A missing or mismatched status cannot trigger a write or reopen Apply.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source formatting and whitespace | PASS | Rust formatting, extension Prettier, and Git whitespace checks completed. |
| Extension and disposable PostgreSQL | NOT TESTED | Two extension cases cover drawer closure, owner adoption, and browser document stability. One PostgreSQL case covers original-document checks and switching to history without recording a receipt. |
| Live Naukri and local installation | NOT TESTED | No browser session, queue state, installed runtime, or application admission was used. |

Run the extension and disposable PostgreSQL suites with the combined local gate. The engineering estimate remains 58% complete. The first independently verified live Naukri worker receipt is outstanding.
