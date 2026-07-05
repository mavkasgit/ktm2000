type GetAuditLogsQueryKeyParams = {
  limit?: number;
  offset?: number;
  status?: string | null;
  section_id?: number;
  search?: string | null;
  section_name?: string | null;
  product_sku?: string | null;
  action?: string | null;
  entity_type?: string | null;
  user_name?: string | null;
  sort_by?: string | null;
  sort_order?: string | null;
  date_from?: string | null;
  date_to?: string | null;
};

type StockTransactionsQueryKeyParams = {
  productId?: number;
  locationId?: number;
  limit?: number;
  offset?: number;
  search?: string;
  dateFrom?: string;
  dateTo?: string;
  sort_by?: string;
  sort_order?: string;
  reason?: string;
  from_location?: string;
  to_location?: string;
  quality_state?: string;
  comment?: string;
};

type StockBalancesQueryKeyParams = {
  locationId?: number;
  locationIds?: number[];
  search?: string;
  limit?: number;
  offset?: number;
  sort_by?: string;
  sort_order?: string;
  sku?: string;
  quantity?: string;
  quality?: string;
  location?: string;
  operations?: string;
};

type ExecutionRowsQueryKeyParams = {
  section_id?: number;
  limit?: number;
  offset?: number;
  search?: string;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  plan_position_id?: string;
  source_row_number?: string;
  production_plan_id?: string;
  product_sku?: string;
  source_sku?: string;
  source_name?: string;
  quantity?: string;
  route_name?: string;
  status?: string;
  current_stage_section_name?: string;
};

type AllPlanPositionsQueryKeyParams = {
  limit?: number;
  offset?: number;
  search?: string;
  sort_by?: string;
  sort_order?: string;
  status?: string;
  validation_status?: string;
  source_sku?: string;
  source_name?: string;
  has_route?: string;
  has_errors?: string;
  has_warnings?: string;
};

type UsersListQueryKeyParams = {
  limit?: number;
  offset?: number;
  search?: string;
  sort_by?: string;
  sort_order?: string;
  role?: string;
  is_active?: boolean;
  full_name?: string;
  email?: string;
  section?: string;
};

type HrmsEmployeesQueryKeyParams = {
  limit?: number;
  offset?: number;
  search?: string;
  sort_by?: string;
  sort_order?: string;
  department?: string;
  linked?: boolean;
};

type SectionBoardQueryKeyParams = {
  date_from?: string;
  date_to?: string;
  status?: string;
  search?: string;
  product_sku?: string;
  sort_by?: string;
  sort_order?: string;
  limit?: number;
  offset?: number;
  singleSectionLockId?: number | null;
};

type ReadyToTransferQueryKeyParams = {
  limit?: number;
  offset?: number;
  search?: string;
  sort_by?: string;
  sort_order?: string;
  product_sku?: string;
  operation_name?: string;
  next_operation_name?: string;
  next_section_name?: string;
  task_id?: number;
  transferable_qty?: string;
};

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
    defects: (spgId: number) => ["spg-defects", spgId] as const,
    snapshotAll: () => ["spg-snapshot"] as const,
    defectsAll: () => ["spg-defects"] as const,
  },
  auditLogs: {
    list: (params?: GetAuditLogsQueryKeyParams) => ["auditLogs", params ?? {}] as const,
  },
  users: {
    list: (params?: UsersListQueryKeyParams) => ["users", "list", params ?? {}] as const,
  },
  hrmsEmployees: {
    list: (params?: HrmsEmployeesQueryKeyParams) => ["hrms-employees", params ?? {}] as const,
  },
  stock: {
    balances: (params?: StockBalancesQueryKeyParams) =>
      ["stock-balances", params ?? {}] as const,
    balancesAll: () => ["stock-balances"] as const,
    transactions: (params?: StockTransactionsQueryKeyParams) =>
      ["stock-transactions", params ?? {}] as const,
    productBalance: (productId: number) => ["stock-product-balance", productId] as const,
  },
  shopfloor: {
    board: (sectionId: number, params?: SectionBoardQueryKeyParams) =>
      ["shopfloor-board", sectionId, params ?? {}] as const,
    stats: (sectionId: number) => ["shopfloor-stats", sectionId] as const,
    incomingTransfers: (sectionId: number) => ["shopfloor-incoming-transfers", sectionId] as const,
    summary: () => ["shopfloor-sections-summary"] as const,
    boardAll: () => ["shopfloor-board"] as const,
    statsAll: () => ["shopfloor-stats"] as const,
    incomingTransfersAll: () => ["shopfloor-incoming-transfers"] as const,
  },
  transfers: {
    ready: (
      spgId: number | null,
      params?: ReadyToTransferQueryKeyParams,
    ) => ["transfers-ready", spgId, params ?? {}] as const,
    readyAll: (params?: ReadyToTransferQueryKeyParams) =>
      ["transfers-ready", "all", params ?? {}] as const,
    history: (
      spgId: number | null,
      params?: {
        limit?: number;
        offset?: number;
        search?: string;
        status?: string;
        sort_by?: string;
        sort_order?: string;
        date_from?: string;
        date_to?: string;
        product_sku?: string;
        from_section_name?: string;
        to_section_name?: string;
      },
    ) => ["transfers-history", spgId, params ?? {}] as const,
    historyAll: (
      params?: {
        limit?: number;
        offset?: number;
        search?: string;
        status?: string;
        sort_by?: string;
        sort_order?: string;
        date_from?: string;
        date_to?: string;
        product_sku?: string;
        from_section_name?: string;
        to_section_name?: string;
      },
    ) => ["transfers-history", "all", params ?? {}] as const,
  },
  plan: {
    allPositions: (params?: AllPlanPositionsQueryKeyParams) =>
      ["all-plan-positions", params ?? {}] as const,
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
    rows: (params?: ExecutionRowsQueryKeyParams) =>
      ["production-planning-rows", params ?? {}] as const,
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
    list: (params?: Record<string, unknown>) => ["raw-materials", params ?? {}] as const,
  },
  importTemplates: {
    all: () => ["import-templates"] as const,
    list: (params?: Record<string, unknown>) => ["import-templates", "list", params ?? {}] as const,
    stats: () => ["import-templates-stats"] as const,
    versions: (id: number) => ["import-templates-versions", id] as const,
    activeVersion: (id: number) => ["import-templates-active-version", id] as const,
    modal: () => ["import-templates", "import-modal"] as const,
  },
  backups: {
    all: () => ["backups"] as const,
    list: (params?: Record<string, unknown>) => ["backups", "list", params ?? {}] as const,
    config: () => ["backup-config"] as const,
    job: (jobId: number) => ["backup-job", jobId] as const,
    jobs: () => ["backup-jobs"] as const,
    currentPreview: () => ["current-preview"] as const,
    previews: (id: number) => ["backup-previews", id] as const,
    previewsAll: () => ["backup-previews"] as const,
  },
};
