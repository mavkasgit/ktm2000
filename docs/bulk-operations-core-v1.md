# Reusable Bulk Operations Core V1

## Goal

Build one reusable bulk-operations core for selection, execution, hotkeys, and partial-result reporting, then integrate it through page-specific adapters instead of a universal table UI.

## V1 Scope

- Planning: bulk route assignment reuses the shared selection, runner, power bar, hotkeys, and result dialog.
- Execution: bulk take-to-work, cancel, and restore reuse the same frontend core.
- Backend execution-control API adds batch cancel and restore endpoints with per-position results.
- Bulk semantics are partial success. A batch returns one result per requested row and does not stop at the first failure.

## Frontend Core Interfaces

```ts
export interface BulkSelectionController<TId> {
  selectedIds: Set<TId>;
  selectedCount: number;
  selectOne(id: TId, checked?: boolean): void;
  selectAllFiltered(ids: Iterable<TId>): void;
  clear(): void;
  replace(ids: Iterable<TId>): void;
  pruneTo(ids: Iterable<TId>): void;
  isSelected(id: TId): boolean;
  isAllSelected(ids: Iterable<TId>): boolean;
  isIndeterminate(ids: Iterable<TId>): boolean;
}

export interface BulkActionDefinition<TId, TContext> {
  id: string;
  label: string;
  primaryLabel?: string;
  pendingLabel?: string;
  isEligible?: (id: TId, context: TContext) => boolean;
  getIneligibleReason?: (id: TId, context: TContext) => string | null | undefined;
  run(ids: TId[], context: TContext): Promise<BulkActionResultItem<TId>[]>;
}

export interface BulkActionResultItem<TId> {
  id: TId;
  status: "success" | "failed" | "skipped";
  reason?: string | null;
  label?: string;
  meta?: Record<string, unknown>;
}
```

## Backend V1 Contracts

```ts
type CancelBatchRequest = {
  position_ids: number[];
  reason?: string;
};

type RestoreBatchRequest = {
  position_ids: number[];
  reason?: string;
};

type BatchActionResponse = {
  results: Array<{
    position_id: number;
    status: "success" | "failed" | "skipped";
    reason?: string | null;
  }>;
};
```

Endpoints:

- `POST /production-planning/rows/cancel-batch`
- `POST /production-planning/rows/restore-batch`

Existing single-item endpoints remain intact.

## Phase 2 Shopfloor Design

Shopfloor should reuse the frontend bulk core and add only a shopfloor adapter layer. The adapter owns row eligibility, quantity defaults, and payload shaping.

Planned batch contracts:

```ts
type ShopfloorIssueBatchRequest = {
  task_ids: number[];
  quantity_strategy: "max_per_row";
  executor_user_id?: number;
  comment?: string;
  idempotency_key?: string;
};

type ShopfloorCompleteBatchRequest = {
  task_ids: number[];
  quantity_strategy: "max_per_row";
  defect_quantity?: number;
  executor_user_id?: number;
  comment?: string;
  idempotency_key?: string;
};

type ShopfloorSendBatchRequest = {
  task_ids: number[];
  quantity_strategy: "max_per_row";
  to_section_id?: number;
  executor_user_id?: number;
  comment?: string;
  idempotency_key?: string;
};

type ShopfloorBatchResponse = {
  results: Array<{
    task_id: number;
    position_id?: number;
    status: "success" | "failed" | "skipped";
    reason?: string | null;
    movement_id?: number | null;
    transfer_id?: number | null;
    quantity?: number;
  }>;
};
```

Phase 2 endpoints:

- `POST /shopfloor/tasks/issue-batch`
- `POST /shopfloor/tasks/complete-batch`
- `POST /shopfloor/tasks/send-batch`

Default quantity strategy is `max_per_row`. Per-row validation remains shopfloor-specific: only tasks valid for the chosen operation are selectable, and the backend still returns per-item skipped/failed outcomes to preserve partial-success semantics.
