import axios from "axios";

const DEFAULT_API_BASE_URL = "http://localhost:5201/api";

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
