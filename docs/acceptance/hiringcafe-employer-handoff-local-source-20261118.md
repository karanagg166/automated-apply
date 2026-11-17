# HiringCafe employer application handoff

Local branch `feat/rust-agent-runtime`, implementation `67a06d23f89e1c2aba103d30037b48f8fdbca01f`.

The HiringCafe import form accepts an optional employer link on a supported Greenhouse, Lever, Ashby, or SmartRecruiters application board. The importer validates it during preview and save. The packet displays the original HiringCafe posting and offers the employer destination after checking the retained source observation, saved application URL, and canonical employer vacancy identity. The current packet still requires owner approval. A changed destination invalidates review. Portal-only jobs keep their existing listing handoff, and reimports preserve existing employer and observation history.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source formatting and whitespace | PASS | Rust formatting, dashboard Prettier and Git whitespace checks completed. |
| Dashboard workflow | NOT TESTED | The reviewed-import fixture adds a HiringCafe case covering preview, approval, save and URL redaction from browser attempt storage. |
| Disposable PostgreSQL | NOT TESTED | One new packet fixture covers original posting attribution, employer handoff and stale evidence. The existing import case now checks unsupported URLs and retained attribution. |
| Installed workflow and employer application | NOT TESTED | No actual browser form, employer receipt, service replacement or provider operation took place. |

Run the frontend discovery suite and disposable Rust PostgreSQL suite with the combined local gate. The estimate remains 58% complete. Existing portal-only rows retain their prior evidence on reimport. Employer identity and permission to act still require the existing review and execution checks.
