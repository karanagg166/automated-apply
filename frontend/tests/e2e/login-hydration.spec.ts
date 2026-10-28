import { test, expect } from "@playwright/test";

test("login remains safe when browser scripts are unavailable", async ({
  browser,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await page.goto("http://localhost:3100/login");
    await expect(page.locator("form")).toHaveAttribute("method", "post");
    await expect(page.locator("form")).toHaveAttribute("action", "/api/auth");
    await expect(page.getByLabel("Owner passphrase")).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Enter workspace" }),
    ).toBeDisabled();
    expect(new URL(page.url()).search).toBe("");
  } finally {
    await context.close();
  }
});
