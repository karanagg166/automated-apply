// Active-tab assistance on a selected posting only; no login or private API access.
export function naukriFormUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      ["naukri.com", "www.naukri.com"].includes(url.hostname) &&
      !url.username && !url.password && !url.port && !url.search && !url.hash &&
      /^\/job-listings-[a-zA-Z0-9%_-]+-[0-9]{10,20}\/?$/.test(url.pathname);
  } catch { return false; }
}
