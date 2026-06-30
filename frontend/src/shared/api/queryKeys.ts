/**
 * Единая фабрика query-ключей для TanStack Query.
 *
 * Использование:
 *   queryClient.invalidateQueries({ queryKey: queryKeys.sections.all() });
 *   queryClient.invalidateQueries({ queryKey: queryKeys.shopfloor.board(sectionId) });
 *
 * Преимущества:
 *   - опечатки ловятся компилятором;
 *   - при переименовании ключа — одна точка изменения;
 *   - неявная документация: какие домены и варианты ключей существуют.
 */

export const queryKeys = {
  auth: {
    me: () => ["auth-me"] as const,
  },
  sections: {
    all: () => ["sections"] as const,
  },
  operations: {
    all: () => ["operations"] as const,
  },
  operationGroups: {
    all: () => ["operation-groups"] as const,
  },
  spg: {
    all: () => ["spg"] as const,
    list: () => ["spgs"] as const,
    snapshot: (spgId: number) => ["spg-snapshot", spgId] as const,
    remainders: (spgId: number) => ["spg-remainders", spgId] as const,
    defects: (spgId: number) => ["spg-defects", spgId] as const,
    remainderHistory: (spgId: number) => ["spg-remainder-history", spgId] as const,
    manualOperations: (spgId: number) => ["spg-manual-operations", spgId] as const,
    snapshotAll: () => ["spg-snapshot"] as const,
    remaindersAll: () => ["spg-remainders"] as const,
    defectsAll: () => ["spg-defects"] as const,
    remainderHistoryAll: () => ["spg-remainder-history"] as const,
    manualOperationsAll: () => ["spg-manual-operations"] as const,
  },
  shopfloor: {
    board: (sectionId: number) => ["shopfloor-board", sectionId] as const,
    stats: (sectionId: number) => ["shopfloor-stats", sectionId] as const,
    incomingTransfers: (sectionId: number) => ["shopfloor-incoming-transfers", sectionId] as const,
    summary: () => ["shopfloor-sections-summary"] as const,
    boardAll: () => ["shopfloor-board"] as const,
    statsAll: () => ["shopfloor-stats"] as const,
    incomingTransfersAll: () => ["shopfloor-incoming-transfers"] as const,
  },
  transfers: {
    ready: (spgId: number | null) => ["transfers-ready", spgId] as const,
    readyAll: () => ["transfers-ready", "all"] as const,
    history: (spgId: number | null) => ["transfers-history", spgId] as const,
    historyAll: () => ["transfers-history", "all"] as const,
  },
  plan: {
    allPositions: () => ["all-plan-positions"] as const,
    allFiles: () => ["all-plan-files"] as const,
    duplicates: (key?: string) => ["plan-duplicates-all", key ?? null] as const,
    preview: (planId: string | number) => ["plan-preview", planId] as const,
    positionDetail: (positionId: number) => ["plan-position-detail", positionId] as const,
    previewPage: (planId: string | number) => ["plan-preview-page", planId] as const,
    batchPreview: (batchId: string | number) => ["batch-preview", batchId] as const,
    routeCheck: (planId: string | number, positionId: number) =>
      ["route-check", planId, positionId] as const,
    list: () => ["plan-list"] as const,
    previewAll: () => ["plan-preview"] as const,
    positionDetailAll: () => ["plan-position-detail"] as const,
  },
  execution: {
    rows: () => ["production-planning-rows"] as const,
    rowDetail: (positionId: number) => ["production-planning-row-detail", positionId] as const,
    plans: () => ["plans"] as const,
    rowDetailAll: () => ["production-planning-row-detail"] as const,
  },
  routes: {
    all: () => ["routes"] as const,
    ruleProfiles: () => ["route-rule-profiles"] as const,
    selectionRules: () => ["route-selection-rules"] as const,
    seedPreview: () => ["seed-preview"] as const,
  },
  techcards: {
    all: () => ["techcards"] as const,
  },
  products: {
    all: () => ["products"] as const,
  },
  rawMaterials: {
    all: () => ["raw-materials"] as const,
  },
  importTemplates: {
    all: () => ["import-templates"] as const,
    stats: () => ["import-templates-stats"] as const,
    versions: (id: number) => ["import-templates-versions", id] as const,
    activeVersion: (id: number) => ["import-templates-active-version", id] as const,
    modal: () => ["import-templates", "import-modal"] as const,
  },
  backups: {
    all: () => ["backups"] as const,
    config: () => ["backup-config"] as const,
    job: (jobId: number) => ["backup-job", jobId] as const,
    jobs: () => ["backup-jobs"] as const,
    currentPreview: () => ["current-preview"] as const,
    previews: (id: number) => ["backup-previews", id] as const,
    previewsAll: () => ["backup-previews"] as const,
  },
};
