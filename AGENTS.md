Use **pnpm 12.14.0** for all frontend package installation, scripts and browser tools.
From the repository root, run `pnpm --dir frontend install --frozen-lockfile` and
`pnpm --dir frontend run <script>`; use `pnpm --dir frontend exec <tool>` for binaries.
Do not use npm or npx, and do not recreate `package-lock.json`. The frontend's only
dependency lockfile is `frontend/pnpm-lock.yaml`.
