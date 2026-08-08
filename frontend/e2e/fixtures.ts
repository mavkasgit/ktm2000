import { test as base, expect, type Page } from "@playwright/test";

/**
 * Shared fixtures for E2E tests.
 * Provides authenticated page context and helpers for the KTM2000 workflow.
 *
 * Login: Break Glass (общий auth-shell, идентичен HRMS). На dev/test-бэкенде
 * OIDC может быть включён — стабим /auth/oidc/config, чтобы форма аварийного
 * входа была доступна без авто-редиректа в Authentik.
 * Пароль: BREAK_GLASS_PASSWORD бэкенда (в dev "break-glass-dev"), override E2E_ADMIN_PASSWORD.
 */

const BREAK_GLASS_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "break-glass-dev";

/** Стаб /api/auth/oidc/config → enabled=false (без перехода в Authentik). */
export async function stubOidcDisabled(page: Page) {
  await page.route("**/auth/oidc/config", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        enabled: false,
        authorization_url: null,
        client_id: null,
        redirect_uri: null,
        scopes: null,
        issuer: null,
        sso_only: false,
        login_hint_enabled: false,
      }),
    })
  );
}

/** Вход через Break Glass (пароль аварийного доступа). */
export async function loginWithBreakGlass(page: Page) {
  await page.goto("/login");
  await page.getByPlaceholder("Пароль аварийного доступа").fill(BREAK_GLASS_PASSWORD);
  await page.getByRole("button", { name: "Аварийный вход" }).click();
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 12_000 });
}

/** Авторизация, если текущая страница /login (иначе — уже вошли). */
async function ensureAuthenticated(page: Page) {
  await stubOidcDisabled(page);
  await page.goto("/");
  await page.waitForTimeout(500);
  const url = page.url();
  if (url.includes("login")) {
    await loginWithBreakGlass(page);
  }
}

export const test = base.extend<{
  authenticatedPage: Page;
  loginAsAdmin: () => Promise<void>;
  seedTestData: () => Promise<void>;
}>({
  authenticatedPage: async ({ page }, use) => {
    await ensureAuthenticated(page);
    await use(page);
  },

  loginAsAdmin: async ({ page }, use) => {
    await use(async () => {
      await ensureAuthenticated(page);
    });
  },

  seedTestData: async ({ page }, use) => {
    await use(async () => {
      // Use the seed API to set up test data
      const response = await page.evaluate(async () => {
        const res = await fetch("/api/routes-seed?force=true", { method: "POST" });
        return res.json();
      });
      expect(response).toBeDefined();
    });
  },
});

export { expect };
