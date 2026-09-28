import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import { invalidateAfter, invalidateEverything } from "@/shared/api/cacheInvalidation";
import { queryKeys } from "@/shared/api/queryKeys";

/**
 * Хуки бэкапов сбрасывают кэш через реестр (ADR-0041): перечень задетых
 * ключей — дело `CACHE_DOMAIN_KEYS.backups`, а не каждого хука. Перечислить
 * их здесь означало бы разойтись с реестром при первом же новом ключе
 * в `queryKeys.backups`.
 */

export function useBackupConfig() {
  return useQuery({
    queryKey: queryKeys.backups.config(),
    queryFn: api.fetchBackupConfig,
  });
}

export function useUpdateBackupConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.updateBackupConfig,
    onSuccess: () => {
      void invalidateAfter(queryClient, "backupsChanged");
    },
  });
}

export function useBackups(params: api.ListBackupsParams = {}) {
  return useQuery({
    queryKey: queryKeys.backups.list(params),
    queryFn: () => api.fetchBackups(params),
  });
}

export function useCreateBackup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.createBackup,
    onSuccess: () => {
      void invalidateAfter(queryClient, "backupsChanged");
    },
  });
}

export function useStartBackupJob() {
  return useMutation({
    mutationFn: api.startBackupJob,
  });
}

export function useBackupJob(jobId: string | null) {
  return useQuery({
    queryKey: queryKeys.backups.job(jobId as unknown as number),
    queryFn: () => api.fetchBackupJob(jobId!),
    enabled: Boolean(jobId),
    refetchInterval: 700,
  });
}

export function useCurrentPreview() {
  return useMutation({
    mutationFn: api.fetchCurrentPreview,
  });
}

export function usePreviewBackup() {
  return useMutation({
    mutationFn: (filename: string) => api.previewBackup(filename),
  });
}

export function useUploadPreview() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => api.uploadPreview(file),
    onSuccess: () => {
      void invalidateAfter(queryClient, "backupsChanged");
    },
  });
}

export function useUpdateBackupComment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ filename, comment }: { filename: string; comment: string }) =>
      api.updateBackupComment(filename, comment),
    onSuccess: () => {
      void invalidateAfter(queryClient, "backupsChanged");
    },
  });
}

export function useDeleteBackup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (filename: string) => api.deleteBackup(filename),
    onSuccess: () => {
      void invalidateAfter(queryClient, "backupsChanged");
    },
  });
}

export function useBulkDeleteBackups() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (filenames: string[]) => api.bulkDeleteBackups(filenames),
    onSuccess: () => {
      void invalidateAfter(queryClient, "backupsChanged");
    },
  });
}

export function useDeleteBackupsOlderThan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (days: number) => api.deleteBackupsOlderThan(days),
    onSuccess: () => {
      void invalidateAfter(queryClient, "backupsChanged");
    },
  });
}

export function useRestoreBackup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ filename, db_name }: { filename: string; db_name: string }) =>
      api.restoreBackup(filename, { db_name }),
    onSuccess: () => {
      // Восстановление переписывает саму БД, поэтому невалиден любой запрос,
      // а не только ключи домена `backups`. «Сбросить всё» живёт в реестре
      // (`invalidateEverything`): прямой вызов здесь был бы возвратом к
      // запрещённому ADR-0041 способу.
      void invalidateEverything(queryClient);
    },
  });
}

export function useUploadRestore() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, db_name }: { file: File; db_name: string }) =>
      api.uploadRestore(file, { db_name }),
    onSuccess: () => {
      // См. `useRestoreBackup`: после восстановления БД невалиден любой запрос.
      void invalidateEverything(queryClient);
    },
  });
}
