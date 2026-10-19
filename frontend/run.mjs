import { cpSync, existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { parseArgs } from "node:util";
const envFile = new URL("../backend/.env", import.meta.url);
if (existsSync(envFile) && process.env.FRONTEND_ISOLATED !== "1")
  process.loadEnvFile(envFile);
let args = ["node_modules/next/dist/bin/next", ...process.argv.slice(2)];
if (process.argv[2] === "start") {
  const { values } = parseArgs({
    args: process.argv.slice(3),
    options: {
      hostname: { type: "string", short: "H" },
      port: { type: "string", short: "p" },
    },
  });
  cpSync(".next/static", ".next/standalone/.next/static", { recursive: true });
  process.env.HOSTNAME = values.hostname || "127.0.0.1";
  process.env.PORT = values.port || process.env.PORT || "3000";
  args = [".next/standalone/server.js"];
}
const child = spawn(process.execPath, args, {
  stdio: "inherit",
  env: process.env,
});
child.on("exit", (code) => process.exit(code ?? 1));
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => child.kill(signal));
