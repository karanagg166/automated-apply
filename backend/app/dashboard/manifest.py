"""Owner-supplied public resource proposals. Never seed or verify a real profile."""

LINKS = [
    ("github", "GitHub", "https://github.com/karanagg166", None),
    (
        "linkedin",
        "LinkedIn",
        "https://www.linkedin.com/in/karan-aggarwal-a13427276/",
        None,
    ),
    ("portfolio", "Portfolio", "https://portfolio-kappa-bay-76.vercel.app/", None),
    ("other", "Portfolio source", "https://github.com/karanagg166/PORTFOLIO", None),
    ("other", "Exam Arena source", "https://github.com/karanagg166/ExamArena", None),
    ("other", "Exam Arena live", "https://exam-arena-mu.vercel.app/", None),
    (
        "other",
        "Quick Clinic source",
        "https://github.com/karanagg166/Quick-Clinic",
        None,
    ),
    ("other", "Quick Clinic live", "https://quick-clinic-nine.vercel.app/", None),
    (
        "other",
        "ShopSizzle source (optional)",
        "https://github.com/karanagg166/ShopSizzle",
        "project_relationship_requires_review",
    ),
    (
        "other",
        "ShopSizzle live (optional)",
        "https://shop-sizzle-seven.vercel.app/",
        "availability_and_project_relationship_require_review",
    ),
    (
        "codeforces",
        "Codeforces",
        "https://codeforces.com/profile/KaranCipherKnight",
        None,
    ),
    ("leetcode", "LeetCode", "https://leetcode.com/u/aggarwalkaran241/", None),
    ("other", "CodeChef", "https://www.codechef.com/users/code_rush03", None),
    (
        "geeksforgeeks",
        "GeeksforGeeks (resume)",
        "https://www.geeksforgeeks.org/user/aggarwalkaran241/",
        "conflicting_gfg",
    ),
    (
        "geeksforgeeks",
        "GeeksforGeeks (GitHub README)",
        "https://www.geeksforgeeks.org/user/aggarwalklmvk/",
        "conflicting_gfg",
    ),
    (
        "other",
        "CSES (optional)",
        "https://cses.fi/user/225098",
        "independent_confirmation_required",
    ),
    (
        "resume",
        "Resume short link (destination unresolved)",
        "https://url-shortner-jet-rho.vercel.app/r2wL9UE",
        "destination_unresolved",
    ),
]


def link_manifest():
    return {
        "resources": [
            dict(
                resource_type=t,
                label=label,
                url=url,
                status="conflicting"
                if issue == "conflicting_gfg"
                else "awaiting_owner_review",
                issue=issue,
                user_confirmed=False,
                availability="not_checked",
            )
            for t, label, url, issue in LINKS
        ],
        "resume_status": "awaiting_upload",
        "facts_verified": False,
    }
