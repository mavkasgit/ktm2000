import { test as base, expect, type Page } from "@playwright/test";

import { ensureDbBootstrapped } from "./api-helpers";

/**
 * Shared fixtures for E2E tests.
 * Provides authenticated page context and helpers for the KTM2000 workflow.
 *
 * Login: Break Glass (общий auth-shell, идентичен HRMS) или OIDC/Authentik.
 * Режим выбирается через E2E_AUTH_MODE: `auto` (по умолчанию),
 * `break-glass` или `oidc`. Dev credentials можно переопределить через
 * E2E_ADMIN_PASSWORD, E2E_OIDC_USERNAME и E2E_OIDC_PASSWORD.
 */

type AuthMode = "auto" | "break-glass" | "oidc";

const AUTH_MODE = (process.env.E2E_AUTH_MODE || "auto") as AuthMode;
const BREAK_GLASS_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "break-glass-dev";
const OIDC_USERNAME = process.env.E2E_OIDC_USERNAME || "akadmin";
const OIDC_PASSWORD = process.env.E2E_OIDC_PASSWORD || "akadmin-dev-local";
const APP_ORIGIN = new URL(
  process.env.PLAYWRIGHT_TEST_BASE_URL || "http://localhost:5172",
).origin;

function safeCurrentUrl(page: Page) {
  const url = new URL(page.url());
  return `${url.origin}${url.pathname}`;
}

function configuredAuthMode(): AuthMode {
  if (AUTH_MODE === "break-glass" || AUTH_MODE === "oidc" || AUTH_MODE === "auto") {
    return AUTH_MODE;
  }
  throw new Error(`E2E_AUTH_MODE must be auto, break-glass or oidc; got ${AUTH_MODE}`);
}

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
    }),
  );
}

/** Вход через Break Glass; уже выполненный логин не требует повторной формы. */
export async function loginWithBreakGlass(page: Page) {
  await page.goto("/login");
  const passwordInput = page.getByPlaceholder("Пароль аварийного доступа");
  const screen = await Promise.race([
    passwordInput.waitFor({ state: "visible" }).then(() => "login"),
    page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 15_000 }).then(
      () => "authenticated"
    ),
  ]).catch(() => {
    throw new Error(`Break Glass login form is unavailable; current URL: ${safeCurrentUrl(page)}`);
  });
  if (screen === "authenticated") return;

  const submit = page.getByRole("button", { name: "Аварийный вход" });
  await passwordInput.fill(BREAK_GLASS_PASSWORD);
  for (let attempt = 1; attempt <= 3; attempt++) {
    await submit.click();
    try {
      await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 15_000 });
      return;
    } catch {
      if (attempt === 3) {
        throw new Error(
          `Break Glass login failed after ${attempt} attempts; current URL: ${safeCurrentUrl(page)}`
        );
      }
      // Seed может кратковременно занимать backend; повторяем вход через ту же форму.
      await passwordInput.fill(BREAK_GLASS_PASSWORD);
    }
  }
}

/** Вход через UI внешнего Authentik; credentials не попадают в лог. */
export async function loginWithOidc(page: Page) {
  await page.goto("/login");
  try {
    await page.waitForURL(
      (url) => url.origin !== APP_ORIGIN || !url.pathname.includes("/login"),
      { timeout: 20_000 }
    );
  } catch {
    throw new Error(`OIDC login did not start; current URL: ${safeCurrentUrl(page)}`);
  }

  if (new URL(page.url()).origin !== APP_ORIGIN) {
    const username = page.getByRole("textbox", { name: /Email or Username/i });
    const password = page.getByRole("textbox", { name: /Пароль|Password/i });
    await username.waitFor({ state: "visible", timeout: 20_000 });
    await password.waitFor({ state: "visible", timeout: 20_000 });
    try {
      await username.fill(OIDC_USERNAME);
      await password.fill(OIDC_PASSWORD);
      await page.getByRole("button", { name: "Войти", exact: true }).click();
    } catch {
      throw new Error(`OIDC login form is unavailable; current URL: ${safeCurrentUrl(page)}`);
    }
  }

  try {
    await page.waitForURL(
      (url) =>
        url.origin === APP_ORIGIN &&
        !url.pathname.includes("/login") &&
        !url.pathname.includes("/auth/callback"),
      { timeout: 30_000 }
    );
  } catch {
    throw new Error(`OIDC login did not return to the app; current URL: ${safeCurrentUrl(page)}`);
  }
}

/** Авторизация по env-режиму; auto читает реальную OIDC-конфигурацию. */
async function ensureAuthenticated(page: Page) {
  await ensureDbBootstrapped();
  const mode = configuredAuthMode();

  if (mode === "break-glass") {
    await stubOidcDisabled(page);
    await loginWithBreakGlass(page);
    return;
  }
  if (mode === "oidc") {
    await loginWithOidc(page);
    return;
  }

  const response = await page.request.get("/api/auth/oidc/config", { failOnStatusCode: false });
  if (!response.ok()) {
    throw new Error(`Cannot read OIDC config: HTTP ${response.status()}`);
  }
  const config = (await response.json()) as { enabled?: unknown };
  if (typeof config.enabled !== "boolean") {
    throw new Error("Cannot read OIDC config: response has no boolean 'enabled' field");
  }

  if (config.enabled) {
    await loginWithOidc(page);
  } else {
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
