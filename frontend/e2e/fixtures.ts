import { test as base, expect, type Page } from "@playwright/test";

import { apiStandToken, ensureDbBootstrapped } from "./api-helpers";
import { passCache, testCacheKey } from "./pass-cache";

/**
 * Shared fixtures for E2E tests.
 * Provides authenticated page context and helpers for the KTM2000 workflow.
 *
 * Login: Break Glass (общий auth-shell, идентичен HRMS) или OIDC/Authentik.
 * Режим выбирается через E2E_AUTH_MODE: `break-glass` (по умолчанию),
 * `auto` или `oidc`. Dev credentials можно переопределить через
 * E2E_ADMIN_PASSWORD, E2E_OIDC_USERNAME и E2E_OIDC_PASSWORD.
 *
 * По умолчанию `break-glass`: прогон не должен зависеть от внешнего IdP.
 * В `oidc` вход идёт в Authentik на отдельной машине, и его моргание
 * превращало зелёный прогон в прогон «на ретраях». `auto` оставлен для
 * ручной отладки — он читает `/api/auth/oidc/config` и выбирает по факту.
 */

type AuthMode = "auto" | "break-glass" | "oidc";

const AUTH_MODE = (process.env.E2E_AUTH_MODE || "break-glass") as AuthMode;
const BREAK_GLASS_PASSWORD = process.env.E2E_ADMIN_PASSWORD || "break-glass-dev";
const OIDC_USERNAME = process.env.E2E_OIDC_USERNAME || "akadmin";
const OIDC_PASSWORD = process.env.E2E_OIDC_PASSWORD || "akadmin-dev-local";
// Без адреса стенда fall back'а на devstack нет: 5172 здесь означал бы
// авторизацию на чужом стенде (и падение по OIDC-заглушке там, где её нет).
const APP_ORIGIN = new URL(process.env.PLAYWRIGHT_TEST_BASE_URL!).origin;

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

// Кеш «уже проходил на этой версии»: с флагом `E2E_SKIP_PASSED=1` зелёный
// тест пропускается, прогон гоняет только непроверенное и упавшее. Ключ
// версии — коммит вместе с диффом рабочего дерева (`pass-cache.ts`).
//
// Именно автофикстура, а не `test.beforeEach`/`test.afterEach` из этого
// модуля: Playwright выполняет хуки в области того файла, который их
// зарегистрировал, и при переиспользовании воркера между спеками хуки из
// общего модуля отваливаются после первой спеки — прогон молча переставал
// записывать результаты (проверено: 1 запись на 6 тестов). Фикстура живёт в
// графе фикстур каждого теста и от переиспользования воркера не зависит.
const testWithPassCache = base.extend<{ _passCache: void }>({
  _passCache: [
    async ({}, use, testInfo) => {
      const key = testCacheKey(testInfo.project.name, testInfo.titlePath);
      if (passCache.alreadyPassed(key)) {
        test.skip(
          true,
          `уже проходил на этой версии (E2E_SKIP_PASSED=1); зелёных в кеше: ${passCache.knownCount()}`,
        );
      }
      await use();
      // Попытка с ретраем записывается, но с пометкой `passedOnRetry`:
      // результат зелёный, но не «прошёл с первой попытки», и кеш такой тест
      // в следующем прогоне пропускать не будет — пока он не станет зелёным
      // чисто. Сама видимость флейка в прогоне — у репортера
      // `green-on-retry-reporter.ts`. Маскировать retry нельзя: запись делается
      // по фактическому результату последней попытки, а не «на всякий случай».
      passCache.record(key, testInfo.status ?? "unknown", testInfo.retry);
    },
    { auto: true },
  ],
});

export const test = testWithPassCache.extend<{
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
      const token = await apiStandToken();
      const response = await page.evaluate(async (bearer) => {
        // Сырой `fetch` страницы идёт мимо apiClient-интерсептора, поэтому
        // Bearer передаём сами — иначе гвард `/api/routes-seed` отвечает 401.
        const res = await fetch("/api/routes-seed?force=true", {
          method: "POST",
          headers: { Authorization: `Bearer ${bearer}` },
        });
        return res.json();
      }, token);
      expect(response).toBeDefined();
    });
  },
});

export { expect };
