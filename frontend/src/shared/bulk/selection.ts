import { useCallback, useMemo, useState } from "react";

export type BulkId = string | number;

export interface BulkSelectionController<TId extends BulkId> {
  selectedIds: Set<TId>;
  selectedCount: number;
  selectOne: (id: TId, checked?: boolean) => void;
  selectAllFiltered: (ids: Iterable<TId>) => void;
  clear: () => void;
  replace: (ids: Iterable<TId>) => void;
  pruneTo: (ids: Iterable<TId>) => void;
  isSelected: (id: TId) => boolean;
  isAllSelected: (ids: Iterable<TId>) => boolean;
  isIndeterminate: (ids: Iterable<TId>) => boolean;
}

export function toggleBulkSelection<TId extends BulkId>(
  selectedIds: Set<TId>,
  id: TId,
  checked?: boolean,
): Set<TId> {
  const next = new Set(selectedIds);
  const shouldSelect = checked ?? !next.has(id);
  if (shouldSelect) {
    next.add(id);
  } else {
    next.delete(id);
  }
  return next;
}

export function selectAllFilteredIds<TId extends BulkId>(ids: Iterable<TId>): Set<TId> {
  return new Set(ids);
}

export function areAllSelected<TId extends BulkId>(selectedIds: Set<TId>, ids: Iterable<TId>): boolean {
  const filteredIds = Array.from(ids);
  return filteredIds.length > 0 && filteredIds.every((id) => selectedIds.has(id));
}

export function isSelectionIndeterminate<TId extends BulkId>(selectedIds: Set<TId>, ids: Iterable<TId>): boolean {
  const filteredIds = Array.from(ids);
  if (filteredIds.length === 0) return false;
  const selectedCount = filteredIds.filter((id) => selectedIds.has(id)).length;
  return selectedCount > 0 && selectedCount < filteredIds.length;
}

export function pruneSelectionToIds<TId extends BulkId>(selectedIds: Set<TId>, ids: Iterable<TId>): Set<TId> {
  const allowed = new Set(ids);
  return new Set(Array.from(selectedIds).filter((id) => allowed.has(id)));
}

export function useBulkSelection<TId extends BulkId>(initialIds: Iterable<TId> = []): BulkSelectionController<TId> {
  const [selectedIds, setSelectedIds] = useState<Set<TId>>(() => new Set(initialIds));

  const selectOne = useCallback((id: TId, checked?: boolean) => {
    setSelectedIds((prev) => toggleBulkSelection(prev, id, checked));
  }, []);

  const selectAllFiltered = useCallback((ids: Iterable<TId>) => {
    setSelectedIds(selectAllFilteredIds(ids));
  }, []);

  const clear = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const replace = useCallback((ids: Iterable<TId>) => {
    setSelectedIds(new Set(ids));
  }, []);

  const pruneTo = useCallback((ids: Iterable<TId>) => {
    setSelectedIds((prev) => {
      const next = pruneSelectionToIds(prev, ids);
      if (next.size === prev.size && Array.from(next).every((id) => prev.has(id))) {
        return prev;
      }
      return next;
    });
  }, []);

  return useMemo(
    () => ({
      selectedIds,
      selectedCount: selectedIds.size,
      selectOne,
      selectAllFiltered,
      clear,
      replace,
      pruneTo,
      isSelected: (id: TId) => selectedIds.has(id),
      isAllSelected: (ids: Iterable<TId>) => areAllSelected(selectedIds, ids),
      isIndeterminate: (ids: Iterable<TId>) => isSelectionIndeterminate(selectedIds, ids),
    }),
    [clear, pruneTo, replace, selectAllFiltered, selectOne, selectedIds],
  );
}
