// The child creates its own cluster. Ambient DB URLs are never accepted here.
import { spawn, spawnSync } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

export async function nativePostgresFixture(python) {
  if (!python?.startsWith("/"))
    throw new Error("absolute_existing_test_python_required");
  const script = fileURLToPath(
    new URL("../../scripts/serve_fixture_postgres.py", import.meta.url),
  );
  const child = spawn(python, ["-u", script], {
    stdio: ["pipe", "pipe", "inherit"],
    env: {
      PATH: process.env.PATH || "",
      HOME: process.env.HOME,
      LANG: "C",
      LC_ALL: "C",
      PYTHONNOUSERSITE: "1",
    },
  });
  const exited = new Promise((resolve) => child.once("close", resolve));
  const lines = createInterface({ input: child.stdout });
  let timer;
  try {
    const line = await new Promise((resolve, reject) => {
      timer = setTimeout(
        () => reject(new Error("fixture_postgres_start_timeout")),
        60000,
      );
      lines.once("line", resolve);
      child.once("error", () =>
        reject(new Error("fixture_postgres_start_failed")),
      );
      child.once("exit", () =>
        reject(new Error("fixture_postgres_exited_early")),
      );
    });
    clearTimeout(timer);
    const value = JSON.parse(line);
    const url = new URL(value.database_url);
    if (
      url.protocol !== "postgresql:" ||
      url.hostname !== "127.0.0.1" ||
      url.username !== "postgres" ||
      !/^[A-Za-z0-9_-]{43}$/.test(url.password) ||
      url.pathname !== "/candidate_profile_test" ||
      !url.port ||
      Number(url.port) < 1025 ||
      url.search ||
      url.hash
    )
      throw new Error("fixture_postgres_child_protocol_invalid");
    let closing;
    const close = () =>
      (closing ||= (async () => {
        child.stdin.end();
        const code = await exited;
        if (code !== 0) throw new Error("fixture_postgres_shutdown_failed");
      })());
    // On abrupt parent death the kernel closes stdin, also releasing the cluster.
    process.once("SIGTERM", () => {
      close().finally(() => process.exit(143));
    });
    const sql = (query) => {
      if (typeof query !== "string" || query.length > 1024 * 1024)
        throw new Error("fixture_postgres_query_invalid");
      const result = spawnSync(
        "/opt/homebrew/opt/postgresql@17/bin/psql",
        [
          "-h",
          url.hostname,
          "-p",
          url.port,
          "-U",
          url.username,
          "-d",
          url.pathname.slice(1),
          "-X",
          "-v",
          "ON_ERROR_STOP=1",
          "-Atc",
          query,
        ],
        {
          encoding: "utf8",
          env: {
            PATH: process.env.PATH || "",
            HOME: process.env.HOME,
            LANG: "C",
            LC_ALL: "C",
            PGPASSWORD: url.password,
            PGPASSFILE: "/dev/null",
            PGSERVICEFILE: "/dev/null",
          },
          timeout: 30000,
        },
      );
      if (result.error || result.status !== 0)
        throw new Error("fixture_postgres_query_failed");
      return result.stdout.trim();
    };
    return { url: value.database_url, port: Number(url.port), sql, close };
  } catch (error) {
    clearTimeout(timer);
    child.stdin.end();
    child.kill("SIGTERM");
    await exited;
    throw error;
  } finally {
    lines.close();
  }
}
