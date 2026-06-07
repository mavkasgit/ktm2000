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

export type ApiErrorResponse = {
  detail?: string;
};

/** Extract a human-readable error message from an Axios error */
export function getErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "response" in error) {
    const axErr = error as { response?: { status?: number; data?: ApiErrorResponse } };
    const status = axErr.response?.status;
    const detail = axErr.response?.data?.detail;
    if (detail) return translateError(detail);
    if (status) return `HTTP ${status}: ${axErr.response?.data ? JSON.stringify(axErr.response.data) : "Нет тела ответа"}`;
  }
  if (error instanceof Error) return translateError(error.message);
  return translateError(String(error ?? ""));
}
