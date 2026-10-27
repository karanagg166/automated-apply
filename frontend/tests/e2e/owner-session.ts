import { expect, type BrowserContext, type Page } from "@playwright/test";

let ownerCookies: Awaited<ReturnType<BrowserContext["cookies"]>> | undefined;

// Authenticate through the actual owner UI once per worker. Each journey starts
// with an anonymous context, so its denial checks still run before calling this.
// Reuse the issued cookies instead of exhausting the production login limiter.
export async function login(page: Page) {
  if (ownerCookies) {
    await page.context().addCookies(ownerCookies);
    await page.goto("/");
  } else {
    await page.goto("/login");
    await page
      .getByLabel("Owner passphrase")
      .fill("fictional-ui-owner-passphrase");
    await page.getByRole("button", { name: "Enter workspace" }).click();
  }
  await expect(page).toHaveURL("/");
  if (!ownerCookies) ownerCookies = await page.context().cookies();
}
