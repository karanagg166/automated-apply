import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
const envFile = new URL("../backend/.env", import.meta.url);
if (existsSync(envFile) && process.env.FRONTEND_ISOLATED !== "1")
  process.loadEnvFile(envFile);
const child = spawn(
  process.execPath,
  ["node_modules/next/dist/bin/next", ...process.argv.slice(2)],
  { stdio: "inherit", env: process.env },
);
child.on("exit", (code) => process.exit(code ?? 1));
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => child.kill(signal));
