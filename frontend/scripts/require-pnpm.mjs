// Keep every install on the reviewed package manager and lockfile.
import { existsSync, readFileSync } from "node:fs";
const root = new URL("../", import.meta.url);
const { packageManager } = JSON.parse(
  readFileSync(new URL("package.json", root), "utf8"),
);
const expected = packageManager.replace("@", "/");
const agent = process.env.npm_config_user_agent || "";
if (agent.split(" ")[0] !== expected) {
  console.error(
    `Use ${packageManager}: corepack prepare ${packageManager} --activate, then pnpm install --frozen-lockfile.`,
  );
  process.exit(1);
}
for (const file of ["package-lock.json", "npm-shrinkwrap.json", "yarn.lock"]) {
  if (existsSync(new URL(file, root))) {
    console.error(`${file} is unsupported. Use only pnpm-lock.yaml.`);
    process.exit(1);
  }
}
