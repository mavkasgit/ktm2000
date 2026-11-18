import { apiClient } from "@/shared/api/client";
import { saveBlobAsFile } from "@/shared/lib/downloadFile";

import type { BackupInfo, BackupJob, BackupPreview, BackupRestoreRequest } from "./types";

export async function fetchBackupConfig(): Promise<{ db_name: string; auto_enabled: boolean; time_of_day: string }> {
  const { data } = await apiClient.get<{ db_name: string; auto_enabled: boolean; time_of_day: string }>("/backups/config");
  return data;
}

export async function updateBackupConfig(payload: { auto_enabled: boolean; time_of_day: string }): Promise<{ auto_enabled: boolean; time_of_day: string }> {
  const { data } = await apiClient.patch<{ auto_enabled: boolean; time_of_day: string }>("/backups/config", payload);
  return data;
}

export type ListBackupsParams = {
  limit?: number;
  offset?: number;
  search?: string;
  /** Сортировка строкой `поле:порядок[,поле:порядок]` — старший приоритет первый. */
  sort?: string;
  backup_type?: string;
  filename?: string;
  db_name?: string;
  comment?: string;
  size?: number;
  created_at?: string;
};

export type BackupsListResponse = {
  items: BackupInfo[];
  total: number;
  limit: number;
  offset: number;
};

export async function fetchBackups(params: ListBackupsParams = {}): Promise<BackupsListResponse> {
  const { data } = await apiClient.get<BackupsListResponse>("/backups", { params });
  return data;
}

export async function createBackup(): Promise<BackupInfo> {
  const { data } = await apiClient.post<BackupInfo>("/backups");
  return data;
}

export async function startBackupJob(): Promise<BackupJob> {
  const { data } = await apiClient.post<BackupJob>("/backups/jobs");
  return data;
}

export async function fetchBackupJob(jobId: string): Promise<BackupJob> {
  const { data } = await apiClient.get<BackupJob>(`/backups/jobs/${jobId}`);
  return data;
}

export async function fetchCurrentPreview(): Promise<BackupPreview> {
  const { data } = await apiClient.get<BackupPreview>("/backups/current-preview");
  return data;
}

/**
 * Скачать файл бэкапа через API-клиент, а не ссылкой.
 *
 * Ручка admin-only (#409), и голая ссылка `<a href>`/`window.open` уводит
 * браузер в навигацию без заголовка `Authorization` — пользователь видит JSON
 * `401` (ADR-0052 п.9). Ответ приходит blob'ом и сохраняется как файл.
 */
export async function downloadBackup(filename: string): Promise<void> {
  const { data } = await apiClient.get<Blob>(`/backups/${filename}/download`, {
    responseType: "blob",
  });
  saveBlobAsFile(data, filename);
}

export async function previewBackup(filename: string): Promise<BackupPreview> {
  const { data } = await apiClient.post<BackupPreview>(`/backups/${filename}/preview`);
  return data;
}

export async function updateBackupComment(filename: string, comment: string): Promise<{ filename: string; comment: string }> {
  const { data } = await apiClient.patch(`/backups/${filename}/comment`, { comment });
  return data;
}

export async function deleteBackup(filename: string): Promise<{ status: string; filename: string }> {
  const { data } = await apiClient.delete(`/backups/${filename}`);
  return data;
}

export async function bulkDeleteBackups(filenames: string[]): Promise<{ deleted: string[]; not_found: string[] }> {
  const { data } = await apiClient.post("/backups/bulk-delete", { filenames });
  return data;
}

export async function deleteBackupsOlderThan(days: number): Promise<{ deleted: string[]; cutoff: string }> {
  const { data } = await apiClient.post("/backups/delete-older-than", { days });
  return data;
}

export async function uploadPreview(file: File): Promise<BackupPreview> {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post<BackupPreview>("/backups/upload-preview", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function restoreBackup(filename: string, payload: BackupRestoreRequest): Promise<{ status: string; db_name: string; filename: string }> {
  const { data } = await apiClient.post(`/backups/${filename}/restore`, payload);
  return data;
}

export async function uploadRestore(file: File, payload: BackupRestoreRequest): Promise<{ status: string; db_name: string; filename: string }> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("confirmed_db_name", payload.db_name);
  const { data } = await apiClient.post("/backups/upload-restore", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}
