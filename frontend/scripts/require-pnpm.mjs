// Keep local, CI and image installs on the committed pnpm dependency graph.
if (!process.env.npm_config_user_agent?.startsWith("pnpm/")) {
  process.stderr.write("Use pnpm install --frozen-lockfile in frontend.\n");
  process.exit(1);
}
