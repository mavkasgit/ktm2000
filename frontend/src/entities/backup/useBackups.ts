import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import { queryKeys } from "@/shared/api/queryKeys";

export function useBackupConfig() {
  return useQuery({
    queryKey: queryKeys.backups.config(),
    queryFn: api.fetchBackupConfig,
  });
}

export function useBackups() {
  return useQuery({
    queryKey: queryKeys.backups.all(),
    queryFn: api.fetchBackups,
  });
}

export function useCreateBackup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.createBackup,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.backups.all() });
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
    onSuccess: (_data, file) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.previews((file as unknown as { batch_id?: number })?.batch_id ?? -1) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.currentPreview() });
    },
  });
}

export function useUpdateBackupComment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ filename, comment }: { filename: string; comment: string }) =>
      api.updateBackupComment(filename, comment),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.currentPreview() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.previewsAll() });
    },
  });
}

export function useDeleteBackup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (filename: string) => api.deleteBackup(filename),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.previewsAll() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.currentPreview() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.jobs() });
    },
  });
}

export function useBulkDeleteBackups() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (filenames: string[]) => api.bulkDeleteBackups(filenames),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.previewsAll() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.currentPreview() });
    },
  });
}

export function useDeleteBackupsOlderThan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (days: number) => api.deleteBackupsOlderThan(days),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.all() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.previewsAll() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.backups.currentPreview() });
    },
  });
}

export function useRestoreBackup() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ filename, db_name }: { filename: string; db_name: string }) =>
      api.restoreBackup(filename, { db_name }),
    onSuccess: () => {
      // Восстановление БД — сбрасываем ВСЁ.
      void queryClient.invalidateQueries();
    },
  });
}

export function useUploadRestore() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, db_name }: { file: File; db_name: string }) =>
      api.uploadRestore(file, { db_name }),
    onSuccess: () => {
      // Восстановление БД — сбрасываем ВСЁ.
      void queryClient.invalidateQueries();
    },
  });
}
