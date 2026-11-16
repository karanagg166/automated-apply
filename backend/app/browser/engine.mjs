// Installed executables only. The isolated driver never falls back to Chrome.
import { existsSync } from "node:fs";

export function installedBrowserExecutable(browser = "brave") {
  const executable = {
    darwin: {
      brave: "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
      edge: "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    },
    linux: { brave: "/usr/bin/brave-browser", edge: "/usr/bin/microsoft-edge" },
  }[process.platform]?.[browser];
  if (!executable || !existsSync(executable))
    throw new Error("selected_browser_unavailable_no_fallback");
  return executable;
}
