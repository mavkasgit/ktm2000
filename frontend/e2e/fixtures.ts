import { test as base, expect, type Page, type BrowserContext } from "@playwright/test";

/**
 * Shared fixtures for E2E tests.
 * Provides authenticated page context and helpers for the KTM2000 workflow.
 */

export const test = base.extend<{
  authenticatedPage: Page;
  loginAsAdmin: () => Promise<void>;
  seedTestData: () => Promise<void>;
}>({
  authenticatedPage: async ({ page }, use) => {
    // Login before each test
    await page.goto("/");
    await page.waitForTimeout(500);

    // Check if we're already on the dashboard (no auth needed in dev mode)
    // or if we need to login
    const url = page.url();
    if (!url.includes("login")) {
      await use(page);
      return;
    }

    // Perform login
    await page.getByLabel(/email|логин|почта/i).first().fill("admin@ktm2000.local");
    await page.getByLabel(/password|пароль/i).first().fill("admin");
    await page.getByRole("button", { name: /войти|login/i }).click();
    await page.waitForURL("**/planning", { timeout: 10_000 }).catch(() => {});

    await use(page);
  },

  loginAsAdmin: async ({ page }, use) => {
    await use(async () => {
      await page.goto("/");
      await page.waitForTimeout(500);
      const url = page.url();
      if (url.includes("login")) {
        await page.getByLabel(/email|логин|почта/i).first().fill("admin@ktm2000.local");
        await page.getByLabel(/password|пароль/i).first().fill("admin");
        await page.getByRole("button", { name: /войти|login/i }).click();
        await page.waitForURL("**/planning", { timeout: 10_000 }).catch(() => {});
      }
    });
  },

  seedTestData: async ({ page }, use) => {
    await use(async () => {
      // Use the seed API to set up test data
      const response = await page.evaluate(async () => {
        const res = await fetch("/api/routes/seed", { method: "POST" });
        return res.json();
      });
      expect(response).toBeDefined();
    });
  },
});

export { expect };
