# Candidate onboarding and evidence

No actual `karan_aggarwal_resume.pdf` was present in this authorized workspace. No real resume contents were parsed, no real candidate profile was saved, and none of the owner’s facts or preferences were silently verified. The existing profile and resource services remain authoritative.

## Private import

`POST /api/v1/dashboard/resumes` accepts raw `application/pdf`, at most 5 MiB and 20 pages, after owner authentication and request-size checks. A separate local pypdf process has a five-second CPU limit, ten-second deadline and memory ceiling (Linux address space; macOS RSS supervision). Encrypted/active-content/attachment PDFs are rejected. No external AI provider receives the PDF. Text is bounded, treated as data and rendered as text.

A dedicated `RESUME_ENCRYPTION_KEY` encrypts bytes with Fernet before database storage. A SHA-256 digest identifies the import. Unconfirmed uploads do not enter career facts. The owner reviews editable name/email/skill suggestions and source text, enters/reviews experience, education and projects, resolves conflicts, then confirms the final form. Heuristic extraction can miss structured fields and scanned PDFs; manual review is required. Reviewed public HTTPS resume links are also supported, with syntax validation and an explicit distinction from downloaded bytes/availability. The unresolved short alias is rejected as a confirmed original resume. No OCR or inferred salary, work authorization or dates.

The confirmation endpoint creates a private resume resource in the **existing** candidate-resource table with an internal `private-resume:` reference. The shared resume selector supports a private download path separately from a public URL. A private download never becomes a resume URL in a public application answer. Downloads require owner authentication, use attachment disposition and no-store headers, and are never served from a static directory. Resume variants must have a unique primary or be selected explicitly. Existing primary resources are never silently replaced. Production hosting must retain the encryption key and use private database access and encrypted backups.

## Exact public resource proposals

The onboarding manifest offers these owner-supplied links, unconfirmed by default:

- GitHub: https://github.com/karanagg166
- Primary LinkedIn: https://www.linkedin.com/in/karan-aggarwal-a13427276/
- Portfolio: https://portfolio-kappa-bay-76.vercel.app/
- Portfolio source: https://github.com/karanagg166/PORTFOLIO
- Exam Arena: https://github.com/karanagg166/ExamArena and https://exam-arena-mu.vercel.app/
- Quick Clinic: **https://github.com/karanagg166/Quick-Clinic** and https://quick-clinic-nine.vercel.app/
- Optional ShopSizzle: https://github.com/karanagg166/ShopSizzle and https://shop-sizzle-seven.vercel.app/ (availability and relationship require review)
- Codeforces: https://codeforces.com/profile/KaranCipherKnight
- LeetCode: https://leetcode.com/u/aggarwalkaran241/
- CodeChef: https://www.codechef.com/users/code_rush03
- Conflicting GFG: https://www.geeksforgeeks.org/user/aggarwalkaran241/ and https://www.geeksforgeeks.org/user/aggarwalklmvk/
- Optional CSES: https://cses.fi/user/225098 (independent confirmation required)
- Unresolved resume reference: https://url-shortner-jet-rho.vercel.app/r2wL9UE

Read-only GitHub API metadata checks returned the exact profile and repository URLs for GitHub, PORTFOLIO, ExamArena, Quick-Clinic, ShopSizzle and url-shortner. This verifies their current GitHub existence/casing, not authorship, resume relationship or live-site availability. All remain owner-review proposals. Other public profiles/live project links were not independently verified. The GFG control permits at most one selected account; the owner may skip both. ShopSizzle and CSES remain optional. Standard identity links use the existing profile fields; additional links use candidate resources. Changes require current profile version checks. Preferences are entered separately; team-size preference is a saved evidence-based preset.

## Resume short URL result

`backend/scripts/resolve_owner_resume.py` checks only the exact supplied alias. It validates public DNS/IPs at every HTTPS redirect, pins the connection to a validated IP while checking the hostname certificate, sends no credentials and bounds redirects/timeouts. This execution returned **unresolved: bounded_network_check_failed**. No original destination was invented.

Read-only inspection of the owner’s `url-shortner` repository showed the Next.js short-code route delegating to `/api/urls/resolve/{shortCode}` and the legitimate `public.urls` storage model using `short_code`, `original_url`, `user_id` and `is_active`. No authorized account/database lookup was available or performed. No records were changed. The short URL remains an unverified reference and cannot be confirmed as a resume from this manifest. A reviewed private PDF can independently provide the resume resource.
