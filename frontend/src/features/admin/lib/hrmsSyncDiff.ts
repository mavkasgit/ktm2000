import type { HrmsEmployee } from "../api"

export type HrmsEmployeeField = "name" | "tab_number" | "position" | "department"

export type HrmsEmployeeChange = {
  before: HrmsEmployee
  after: HrmsEmployee
  fields: HrmsEmployeeField[]
}

export type HrmsSyncDiff = {
  added: HrmsEmployee[]
  removed: HrmsEmployee[]
  changed: HrmsEmployeeChange[]
  unchangedCount: number
}

const FIELD_LABELS: Record<HrmsEmployeeField, string> = {
  name: "ФИО",
  tab_number: "Табельный №",
  position: "Должность",
  department: "Подразделение",
}

export function getHrmsFieldLabel(field: HrmsEmployeeField): string {
  return FIELD_LABELS[field]
}

function normalizeValue(value: string | null | undefined): string {
  return (value ?? "").trim()
}

function getChangedFields(before: HrmsEmployee, after: HrmsEmployee): HrmsEmployeeField[] {
  const fields: HrmsEmployeeField[] = []
  if (normalizeValue(before.name) !== normalizeValue(after.name)) fields.push("name")
  if (normalizeValue(before.tab_number) !== normalizeValue(after.tab_number)) fields.push("tab_number")
  if (normalizeValue(before.position) !== normalizeValue(after.position)) fields.push("position")
  if (normalizeValue(before.department) !== normalizeValue(after.department)) fields.push("department")
  return fields
}

export function computeHrmsSyncDiff(before: HrmsEmployee[], after: HrmsEmployee[]): HrmsSyncDiff {
  const beforeMap = new Map(before.map((employee) => [employee.id, employee]))
  const afterMap = new Map(after.map((employee) => [employee.id, employee]))

  const added: HrmsEmployee[] = []
  const removed: HrmsEmployee[] = []
  const changed: HrmsEmployeeChange[] = []
  let unchangedCount = 0

  for (const employee of after) {
    const previous = beforeMap.get(employee.id)
    if (!previous) {
      added.push(employee)
      continue
    }
    const fields = getChangedFields(previous, employee)
    if (fields.length > 0) {
      changed.push({ before: previous, after: employee, fields })
    } else {
      unchangedCount += 1
    }
  }

  for (const employee of before) {
    if (!afterMap.has(employee.id)) {
      removed.push(employee)
    }
  }

  added.sort((a, b) => a.name.localeCompare(b.name, "ru"))
  removed.sort((a, b) => a.name.localeCompare(b.name, "ru"))
  changed.sort((a, b) => a.after.name.localeCompare(b.after.name, "ru"))

  return { added, removed, changed, unchangedCount }
}

export function hasHrmsSyncDiff(diff: HrmsSyncDiff): boolean {
  return diff.added.length > 0 || diff.removed.length > 0 || diff.changed.length > 0
}