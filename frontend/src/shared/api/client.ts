import axios from "axios";

import { translateError } from "./errorMessages";

const DEFAULT_API_BASE_URL = "/api";

const envBaseUrl = import.meta.env.VITE_API_BASE_URL;

export const API_BASE_URL = (typeof envBaseUrl === "string" && envBaseUrl.trim().length > 0
  ? envBaseUrl
  : DEFAULT_API_BASE_URL
).replace(/\/+$/, "");

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000,
});

const TOKEN_KEY = "ktm2000_token";

/** Interceptor: подставляет Authorization-заголовок из localStorage */
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/** Interceptor: при 401 очищает токен и перенаправляет на /login */
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (
      error?.response?.status === 401 &&
      window.location.pathname !== "/login"
    ) {
      localStorage.removeItem(TOKEN_KEY);
      window.location.href = "/login";
    }
    return Promise.reject(error);
  },
);

export type ApiErrorResponse = {
  detail?: string | ValidationErrorItem[] | Record<string, unknown>;
};

type ValidationErrorItem = {
  type?: string;
  loc?: (string | number)[];
  msg?: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
};

/** Преобразует detail из FastAPI (строка или массив pydantic-ошибок) в текст */
export function formatApiDetail(detail: unknown): string {
  if (detail == null) return "";
  if (typeof detail === "string") return translateError(detail);
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return translateError(item);
        if (item && typeof item === "object" && "msg" in item) {
          const ve = item as ValidationErrorItem;
          const field = ve.loc?.filter((part) => part !== "body").join(" → ") ?? "";
          const message = ve.msg ? translateError(ve.msg) : "";
          return field ? `${field}: ${message}` : message;
        }
        return String(item);
      })
      .filter(Boolean)
      .join("\n");
  }
  if (typeof detail === "object" && "msg" in detail) {
    return formatApiDetail([(detail as ValidationErrorItem)]);
  }
  return translateError(String(detail));
}

/** Extract a human-readable error message from an Axios error */
export function getErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "response" in error) {
    const axErr = error as { response?: { status?: number; data?: ApiErrorResponse } };
    const status = axErr.response?.status;
    const detail = axErr.response?.data?.detail;
    if (detail != null) {
      const formatted = formatApiDetail(detail);
      if (formatted) return formatted;
    }
    if (status) return `HTTP ${status}: ${axErr.response?.data ? JSON.stringify(axErr.response.data) : "Нет тела ответа"}`;
  }
  if (error instanceof Error) return translateError(error.message);
  return translateError(String(error ?? ""));
}
