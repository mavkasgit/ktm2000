import { useEffect, useRef, useState } from "react"
import { Plus, Trash2, Upload } from "lucide-react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  listImportTemplates,
  createImportTemplate,
  updateImportTemplate,
  deleteImportTemplate,
  type ImportTemplate,
  type CreateImportTemplateInput,
} from "@/shared/api/importTemplates"
import { getExcelSheetNames, previewExcelSheet } from "@/shared/api/imports"
import { Button } from "@/shared/ui/Button"
import { Input } from "@/shared/ui/Input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui/Dialog"
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
} from "@/shared/ui/AlertDialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/shared/ui/Select"
import { Badge } from "@/shared/ui/Badge"
import { toast } from "@/shared/ui/use-toast"
import { getErrorMessage } from "@/shared/api/client"

// Reverse mapping: header name (normalized) → system key
const HEADER_KEY_BY_NAME: Record<string, string> = {
  "артикул": "sku",
  "пополнение": "replenishment",
  "наименование": "product_name",
  "остатки сырья на ктм": "raw_stock_ktm",
  "цвет": "color",
  "кол-во шт. в 2,7": "input_quantity",
  "длина, м": "input_length",
  "пробивка/сверловка": "operation",
  "упаковка": "packaging",
  "примечание": "note",
  "длина после упак, м": "output_length",
  "кол-во штук готовой продукции": "output_quantity",
  "запад": "west_quantity",
  "восток": "east_quantity",
  "вид конечного продукта": "output_kind",
  "комментарии": "comments",
  "упаковка в 1,8": "packaging_1_8_quantity",
  "добавить": "add_quantity",
  "срок готовности": "due_date",
  "клиент": "customer",
  "приоритет": "priority",
  "заказ": "order_ref",
}

function normalizeHeader(value: string): string {
  return value.toLowerCase().replace(/\u00a0/g, " ").trim().replace(/\s+/g, " ")
}

function toColumnLetter(index: number): string {
  let n = Math.max(1, Math.floor(index))
  let out = ""
  while (n > 0) {
    const rem = (n - 1) % 26
    out = String.fromCharCode(65 + rem) + out
    n = Math.floor((n - 1) / 26)
  }
  return out
}

function transliterateToCode(name: string): string {
  const ruToEn: Record<string, string> = {
    а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "yo", ж: "zh",
    з: "z", и: "i", й: "y", к: "k", л: "l", м: "m", н: "n", о: "o",
    п: "p", р: "r", с: "s", т: "t", у: "u", ф: "f", х: "kh", ц: "ts",
    ч: "ch", ш: "sh", щ: "shch", ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
  }
  return name
    .toLowerCase()
    .split("")
    .map((ch) => ruToEn[ch] ?? ch)
    .join("")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, 40)
}

type OperationNormalizationRow = {
  contains: string
  operation_code: string
  operation_name: string
  pack_op_code: string
  pack_op_name: string
  normalized_pack_op_family: string
  priority: number
}

type OutputKindNormalizationRow = {
  contains: string
  result: string
  priority: number
}

const DEFAULT_NORMALIZATION_RULES: Record<string, unknown> = {
  version: 1,
  operation: {
    rules: [
      { priority: 100, contains: ["без рассеив"], result: { operation_code: "PACK", operation_name: "Упаковка", additional_pack_operations: [{ operation_code: "PACK_CUSTOM", operation_name_template: "Доп. упаковочная операция: {raw}" }], normalized_pack_op_family: "CUSTOM" } },
      { priority: 90, contains: ["окн"], result: { operation_code: "PRESS_WINDOW", operation_name: "Пресс окно", additional_pack_operations: [], normalized_pack_op_family: "NONE" } },
      { priority: 80, contains: ["греб"], result: { operation_code: "PRESS_COMB", operation_name: "Пресс гребенка", additional_pack_operations: [], normalized_pack_op_family: "NONE" } },
      { priority: 70, contains: ["сверл", "сверло"], result: { operation_code: "DRILL", operation_name: "Сверловка", additional_pack_operations: [], normalized_pack_op_family: "NONE" } },
      { priority: 60, contains: ["клей"], result: { operation_code: "PACK", operation_name: "Упаковка", additional_pack_operations: [{ operation_code: "PACK_GLUE", operation_name: "Упаковка с клеевой операцией" }], normalized_pack_op_family: "GLUE" } },
      { priority: 50, contains: ["рассеив"], result: { operation_code: "PACK", operation_name: "Упаковка", additional_pack_operations: [{ operation_code: "PACK_DIFFUSER", operation_name: "Упаковка с рассеивателем" }], normalized_pack_op_family: "DIFFUSER" } },
    ],
    fallback: {
      operation_code: "PACK",
      operation_name: "Упаковка",
      additional_pack_operations: [{ operation_code: "PACK_CUSTOM", operation_name_template: "Доп. упаковочная операция: {raw}" }],
      normalized_pack_op_family: "CUSTOM",
    },
  },
  output_kind: {
    rules: [
      { priority: 100, contains: ["гп", "гп."], result: "finished_good" },
      { priority: 90, contains: ["пф", "пф."], result: "semi_finished_shipment" },
    ],
    fallback: "raw",
  },
}

function parseOperationRules(raw: unknown): OperationNormalizationRow[] {
  const rules = ((raw as any)?.operation?.rules ?? []) as unknown[]
  const rows = rules
    .filter((rule) => rule && typeof rule === "object")
    .map((rule) => {
      const rec = rule as Record<string, any>
      const res = (rec.result ?? {}) as Record<string, any>
      const pack = Array.isArray(res.additional_pack_operations) ? (res.additional_pack_operations[0] as Record<string, any> | undefined) : undefined
      const contains = Array.isArray(rec.contains) ? rec.contains.map((v) => String(v)).join(", ") : String(rec.contains ?? "")
      return {
        contains,
        operation_code: String(res.operation_code ?? ""),
        operation_name: String(res.operation_name ?? ""),
        pack_op_code: String(pack?.operation_code ?? ""),
        pack_op_name: String(pack?.operation_name ?? pack?.operation_name_template ?? ""),
        normalized_pack_op_family: String(res.normalized_pack_op_family ?? "NONE"),
        priority: Number(rec.priority ?? 0),
      } as OperationNormalizationRow
    })
  return rows.length > 0 ? rows : parseOperationRules(DEFAULT_NORMALIZATION_RULES)
}

function parseOutputKindRules(raw: unknown): OutputKindNormalizationRow[] {
  const rules = ((raw as any)?.output_kind?.rules ?? []) as unknown[]
  const rows = rules
    .filter((rule) => rule && typeof rule === "object")
    .map((rule) => {
      const rec = rule as Record<string, any>
      const contains = Array.isArray(rec.contains) ? rec.contains.map((v) => String(v)).join(", ") : String(rec.contains ?? "")
      return {
        contains,
        result: String(rec.result ?? ""),
        priority: Number(rec.priority ?? 0),
      } as OutputKindNormalizationRow
    })
  return rows.length > 0 ? rows : parseOutputKindRules(DEFAULT_NORMALIZATION_RULES)
}

function parseOperationFallback(raw: unknown): OperationNormalizationRow {
  const fallback = ((raw as any)?.operation?.fallback ?? (DEFAULT_NORMALIZATION_RULES as any).operation.fallback) as Record<string, any>
  const pack = Array.isArray(fallback.additional_pack_operations)
    ? (fallback.additional_pack_operations[0] as Record<string, any> | undefined)
    : undefined
  return {
    contains: "",
    operation_code: String(fallback.operation_code ?? "PACK"),
    operation_name: String(fallback.operation_name ?? "Упаковка"),
    pack_op_code: String(pack?.operation_code ?? "PACK_CUSTOM"),
    pack_op_name: String(pack?.operation_name ?? pack?.operation_name_template ?? "Доп. упаковочная операция: {raw}"),
    normalized_pack_op_family: String(fallback.normalized_pack_op_family ?? "CUSTOM"),
    priority: 0,
  }
}

export function ImportTemplatesPage() {
  const queryClient = useQueryClient()
  const { data: templates, isLoading } = useQuery({
    queryKey: ["import-templates"],
    queryFn: listImportTemplates,
  })

  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<ImportTemplate | null>(null)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deletingTemplate, setDeletingTemplate] = useState<ImportTemplate | null>(null)

  const sortedTemplates = (templates ?? [])
    .slice()
    .sort((a, b) => a.sort_order - b.sort_order)

  const createFileRef = useRef<HTMLInputElement>(null)

  const handleCreate = () => {
    setEditingTemplate(null)
    createFileRef.current?.click()
  }

  const handleEdit = (t: ImportTemplate) => {
    setEditingTemplate(t)
    setEditDialogOpen(true)
  }

  const handleDelete = (t: ImportTemplate) => {
    setDeletingTemplate(t)
    setDeleteDialogOpen(true)
  }

  const confirmDelete = async () => {
    if (!deletingTemplate) return
    try {
      await deleteImportTemplate(deletingTemplate.id)
      toast({ title: "Шаблон удалён", variant: "success" })
      queryClient.invalidateQueries({ queryKey: ["import-templates"] })
    } catch (e) {
      toast({ title: "Ошибка", description: getErrorMessage(e), variant: "destructive" })
    } finally {
      setDeleteDialogOpen(false)
      setDeletingTemplate(null)
    }
  }

  const handleCreateFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setEditingTemplate(null)
    setEditDialogOpen(true)
    // Pass file to dialog via a custom event or state
    // We'll use a state to carry the pending file
    setPendingCreateFile(file)
    e.target.value = ""
  }

  const [pendingCreateFile, setPendingCreateFile] = useState<File | null>(null)

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-l font-semibold">Шаблоны импорта</h2>
        <Button size="sm" onClick={handleCreate}>
          <Plus className="h-4 w-4 mr-1" />
          Создать шаблон
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Загрузка...</p>}

      {!isLoading && sortedTemplates.length === 0 && (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Нет шаблонов. Нажмите «Создать шаблон» чтобы добавить.
        </div>
      )}

      {sortedTemplates.length > 0 && (
        <div className="rounded-lg border overflow-auto">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">Имя</th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">Код</th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">Название кнопки</th>
                <th className="text-left p-3 text-xs font-medium text-muted-foreground">Описание</th>
              </tr>
            </thead>
            <tbody>
              {sortedTemplates.map(t => (
                <tr key={t.id} className={`border-b cursor-pointer hover:bg-muted/50 ${!t.is_active ? "opacity-50" : ""}`} onClick={() => handleEdit(t)}>
                  <td className="p-3 font-medium">{t.name}</td>
                  <td className="p-3 font-mono text-xs">{t.code ?? "—"}</td>
                  <td className="p-3">{t.button_label ?? "—"}</td>
                  <td className="p-3 max-w-[200px] truncate" title={t.description ?? undefined}>
                    {t.description ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <input
        ref={createFileRef}
        type="file"
        accept=".xlsx,.xls,.xlsm,.xlsb,.ods"
        className="hidden"
        onChange={handleCreateFile}
      />

      <TemplateDialog
        open={editDialogOpen}
        onOpenChange={setEditDialogOpen}
        template={editingTemplate}
        pendingCreateFile={pendingCreateFile}
        onFileProcessed={() => setPendingCreateFile(null)}
        onSuccess={() => {
          setEditDialogOpen(false)
          setPendingCreateFile(null)
          queryClient.invalidateQueries({ queryKey: ["import-templates"] })
        }}
      />

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Удалить шаблон?</AlertDialogTitle>
            <AlertDialogDescription>
              Шаблон «{deletingTemplate?.name}» будет удалён. Это действие нельзя отменить.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Отмена</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>Удалить</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

function TemplateDialog(props: {
  open: boolean
  onOpenChange: (open: boolean) => void
  template: ImportTemplate | null
  pendingCreateFile: File | null
  onFileProcessed: () => void
  onSuccess: () => void
}) {
  const [name, setName] = useState(props.template?.name ?? "")
  const [code, setCode] = useState(props.template?.code ?? "")
  const [buttonLabel, setButtonLabel] = useState(props.template?.button_label ?? "")
  const [description, setDescription] = useState(props.template?.description ?? "")
  const [sortOrder, setSortOrder] = useState(String(props.template?.sort_order ?? 0))
  const [isActive, setIsActive] = useState(props.template?.is_active ?? true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  type PassportColumn = { column: string; header: string; key: string }
  const [passportColumns, setPassportColumns] = useState<PassportColumn[]>([])
  const [operationRules, setOperationRules] = useState<OperationNormalizationRow[]>([])
  const [operationFallback, setOperationFallback] = useState<OperationNormalizationRow>(parseOperationFallback(DEFAULT_NORMALIZATION_RULES))
  const [outputKindRules, setOutputKindRules] = useState<OutputKindNormalizationRow[]>([])
  const [outputKindFallback, setOutputKindFallback] = useState<string>("raw")

  // Excel passport loading
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [passportFile, setPassportFile] = useState<File | null>(null)
  const [sheetNames, setSheetNames] = useState<string[]>([])
  const [sheetIndex, setSheetIndex] = useState(0)
  const [loadingPassport, setLoadingPassport] = useState(false)

  const isEdit = !!props.template

  useEffect(() => {
    setName(props.template?.name ?? "")
    setCode(props.template?.code ?? "")
    setButtonLabel(props.template?.button_label ?? "")
    setDescription(props.template?.description ?? "")
    setSortOrder(String(props.template?.sort_order ?? 0))
    setIsActive(props.template?.is_active ?? true)
    setError(null)

    const mapping = props.template?.column_mapping ?? {}
    const cols: PassportColumn[] = Object.entries(mapping).map(([key, value]) => {
      if (typeof value === "object" && value !== null) {
        const obj = value as Record<string, unknown>
        return { key, header: String(obj.header ?? key), column: String(obj.column ?? "") }
      }
      return { key, header: typeof value === "string" ? value : key, column: "" }
    })
    setPassportColumns(cols)
    const normalization = props.template?.normalization_rules ?? DEFAULT_NORMALIZATION_RULES
    setOperationRules(parseOperationRules(normalization))
    setOperationFallback(parseOperationFallback(normalization))
    setOutputKindRules(parseOutputKindRules(normalization))
    setOutputKindFallback(String((normalization as any)?.output_kind?.fallback ?? "raw"))
    // Reset file state on dialog open
    setPassportFile(null)
    setSheetNames([])
    setSheetIndex(0)
  }, [props.template, props.open])

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEdit) {
      setCode(transliterateToCode(value))
    }
  }

  const handlePassportFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setPassportFile(file)
    setLoadingPassport(true)
    try {
      const names = await getExcelSheetNames(file)
      setSheetNames(names)
      setSheetIndex(0)
      await loadPassportFromExcel(file, names, 0)
    } catch (e) {
      toast({ variant: "destructive", title: "Ошибка чтения Excel", description: getErrorMessage(e) })
    } finally {
      setLoadingPassport(false)
    }
  }

  const handleSheetChange = async (idx: number) => {
    setSheetIndex(idx)
    if (passportFile && sheetNames.length > 0) {
      setLoadingPassport(true)
      try {
        await loadPassportFromExcel(passportFile, sheetNames, idx)
      } catch (e) {
        toast({ variant: "destructive", title: "Ошибка чтения листа", description: getErrorMessage(e) })
      } finally {
        setLoadingPassport(false)
      }
    }
  }

  const loadPassportFromExcel = async (file: File, names: string[], sIdx: number) => {
    const preview = await previewExcelSheet(file, { sheet_index: sIdx })
    const items = preview.items as Record<string, unknown>[]
    if (items.length === 0) {
      toast({ title: "Лист пустой", description: "Не удалось извлечь заголовки", variant: "destructive" })
      return
    }
    // Extract headers from raw_columns_meta of the first item
    const firstItem = items[0]
    const payload = (firstItem.payload as Record<string, unknown> | undefined) ?? {}
    const meta = Array.isArray(payload.raw_columns_meta) ? payload.raw_columns_meta : []

    const cols: PassportColumn[] = []
    for (const raw of meta) {
      const column = raw as Record<string, unknown>
      const index = Number(column.index ?? 0)
      if (!Number.isFinite(index) || index <= 0) continue
      const header = String(column.header ?? `column_${index}`).trim()
      const letter = String(column.letter ?? "").trim() || toColumnLetter(index)
      const normalized = normalizeHeader(header)
      const autoKey = HEADER_KEY_BY_NAME[normalized] ?? ""
      cols.push({
        column: letter,
        header,
        key: autoKey,
      })
    }
    cols.sort((a, b) => a.column.localeCompare(b.column))
    setPassportColumns(cols)

    // Auto-set name from filename if empty (create mode)
    if (!isEdit && !name) {
      const nameFromFile = file.name.replace(/\.[^.]+$/, "").replace(/[_-]/g, " ")
      setName(nameFromFile)
      setCode(transliterateToCode(nameFromFile))
    }

    toast({ title: "Паспорт загружен", description: `Найдено ${cols.length} колонок`, variant: "success" })
  }

  // Auto-load passport from pending create file
  useEffect(() => {
    if (props.pendingCreateFile && !isEdit && props.open) {
      const file = props.pendingCreateFile
      setLoadingPassport(true)
      getExcelSheetNames(file)
        .then((names) => {
          setPassportFile(file)
          setSheetNames(names)
          setSheetIndex(0)
          return loadPassportFromExcel(file, names, 0)
        })
        .catch((e) => {
          toast({ variant: "destructive", title: "Ошибка чтения Excel", description: getErrorMessage(e) })
        })
        .finally(() => {
          setLoadingPassport(false)
          props.onFileProcessed()
        })
    }
  }, [props.pendingCreateFile, props.open, isEdit])

  const addPassportColumn = () => {
    setPassportColumns(prev => [...prev, { column: "", header: "", key: "" }])
  }

  const updatePassportColumn = (idx: number, field: keyof PassportColumn, value: string) => {
    setPassportColumns(prev =>
      prev.map((col, i) => (i === idx ? { ...col, [field]: value } : col))
    )
  }

  const removePassportColumn = (idx: number) => {
    setPassportColumns(prev => prev.filter((_, i) => i !== idx))
  }

  const updateOperationRule = (idx: number, patch: Partial<OperationNormalizationRow>) => {
    setOperationRules((prev) => prev.map((row, i) => (i === idx ? { ...row, ...patch } : row)))
  }

  const addOperationRule = () => {
    setOperationRules((prev) => [
      ...prev,
      {
        contains: "",
        operation_code: "",
        operation_name: "",
        pack_op_code: "",
        pack_op_name: "",
        normalized_pack_op_family: "NONE",
        priority: 0,
      },
    ])
  }

  const removeOperationRule = (idx: number) => {
    setOperationRules((prev) => prev.filter((_, i) => i !== idx))
  }

  const updateOutputKindRule = (idx: number, patch: Partial<OutputKindNormalizationRow>) => {
    setOutputKindRules((prev) => prev.map((row, i) => (i === idx ? { ...row, ...patch } : row)))
  }

  const addOutputKindRule = () => {
    setOutputKindRules((prev) => [...prev, { contains: "", result: "", priority: 0 }])
  }

  const removeOutputKindRule = (idx: number) => {
    setOutputKindRules((prev) => prev.filter((_, i) => i !== idx))
  }

  const buildNormalizationRules = (): Record<string, unknown> => {
    const operation = operationRules
      .map((row) => {
        const contains = row.contains.split(",").map((item) => item.trim()).filter(Boolean)
        if (contains.length === 0 || !row.operation_code.trim()) return null
        const packOpCode = row.pack_op_code.trim()
        const packOpName = row.pack_op_name.trim()
        const packOps = packOpCode
          ? [
              packOpCode === "PACK_CUSTOM"
                ? { operation_code: packOpCode, operation_name_template: packOpName || "Доп. упаковочная операция: {raw}" }
                : { operation_code: packOpCode, operation_name: packOpName || packOpCode },
            ]
          : []
        return {
          priority: Number(row.priority) || 0,
          contains,
          result: {
            operation_code: row.operation_code.trim(),
            operation_name: row.operation_name.trim() || row.operation_code.trim(),
            additional_pack_operations: packOps,
            normalized_pack_op_family: row.normalized_pack_op_family.trim() || "NONE",
          },
        }
      })
      .filter(Boolean)

    const outputKind = outputKindRules
      .map((row) => {
        const contains = row.contains.split(",").map((item) => item.trim()).filter(Boolean)
        if (contains.length === 0 || !row.result.trim()) return null
        return {
          priority: Number(row.priority) || 0,
          contains,
          result: row.result.trim(),
        }
      })
      .filter(Boolean)

    const fallbackPackOpCode = operationFallback.pack_op_code.trim()
    const fallbackPackOpName = operationFallback.pack_op_name.trim()
    const fallbackPackOps = fallbackPackOpCode
      ? [
          fallbackPackOpCode === "PACK_CUSTOM"
            ? { operation_code: fallbackPackOpCode, operation_name_template: fallbackPackOpName || "Доп. упаковочная операция: {raw}" }
            : { operation_code: fallbackPackOpCode, operation_name: fallbackPackOpName || fallbackPackOpCode },
        ]
      : []

    return {
      version: 1,
      operation: {
        rules: operation,
        fallback: {
          operation_code: operationFallback.operation_code.trim() || "PACK",
          operation_name: operationFallback.operation_name.trim() || "Упаковка",
          additional_pack_operations: fallbackPackOps,
          normalized_pack_op_family: operationFallback.normalized_pack_op_family.trim() || "CUSTOM",
        },
      },
      output_kind: {
        rules: outputKind,
        fallback: outputKindFallback.trim() || "raw",
      },
    }
  }

  const handleSave = async () => {
    if (!name.trim()) {
      setError("Название обязательно")
      return
    }
    setSaving(true)
    setError(null)
    try {
      const columnMapping: Record<string, string | { header?: string; column?: string }> = {}
      for (const col of passportColumns) {
        if (col.key.trim()) {
          columnMapping[col.key.trim()] = {
            header: col.header.trim() || col.column.trim(),
            column: col.column.trim(),
          }
        }
      }
      const input: CreateImportTemplateInput = {
        name: name.trim(),
        code: code.trim() || null,
        button_label: buttonLabel.trim() || null,
        description: description.trim() || null,
        sort_order: Number(sortOrder) || 0,
        is_active: isActive,
        column_mapping: columnMapping,
        normalization_rules: buildNormalizationRules(),
      }
      if (isEdit && props.template) {
        await updateImportTemplate(props.template.id, input)
        toast({ title: "Шаблон обновлён", variant: "success" })
      } else {
        await createImportTemplate(input)
        toast({ title: "Шаблон создан", variant: "success" })
      }
      props.onSuccess()
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteFromDialog = async () => {
    if (!props.template) return
    setSaving(true)
    setError(null)
    try {
      await deleteImportTemplate(props.template.id)
      toast({ title: "Шаблон удалён", variant: "success" })
      props.onSuccess()
    } catch (e) {
      setError(getErrorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Редактировать группу" : "Новый шаблон импорта"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Измените параметры шаблона импорта"
              : "Создайте шаблон импорта с привязкой к профилю правил"}
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {error}
          </div>
        )}

        {loadingPassport && (
          <div className="flex items-center justify-center py-12">
            <div className="flex flex-col items-center gap-3">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
              <p className="text-sm text-muted-foreground">Загрузка файла...</p>
            </div>
          </div>
        )}

        <div className={loadingPassport ? "pointer-events-none opacity-50" : ""}>

        <div className="flex flex-wrap gap-4">
          <div className="w-[250px]">
            <label className="text-sm font-medium">Название *</label>
            <Input value={name} onChange={e => handleNameChange(e.target.value)} placeholder="Название шаблона" />
          </div>
          <div className="w-[250px]">
            <label className="text-sm font-medium">Код</label>
            <Input value={code} onChange={e => setCode(e.target.value)} placeholder="Код шаблона" />
          </div>
        </div>

        {/* Паспорт колонок Excel */}
        <div className="mt-6">
          <h3 className="text-sm font-medium">Паспорт колонок Excel</h3>

          <div className="flex gap-2 mb-3 items-center">
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls,.xlsm,.xlsb,.ods"
              className="hidden"
              onChange={handlePassportFileChange}
            />
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              disabled={loadingPassport}
            >
              <Upload className="h-3.5 w-3.5 mr-1" />
              {loadingPassport ? "Загрузка..." : passportFile ? "Загрузить другой файл" : "Загрузить Excel"}
            </Button>
            {passportFile && (
              <span className="text-xs text-muted-foreground truncate max-w-[200px]">
                {passportFile.name}
              </span>
            )}
            {sheetNames.length > 1 && (
              <Select value={String(sheetIndex)} onValueChange={(v) => handleSheetChange(Number(v))}>
                <SelectTrigger className="h-7 w-[180px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {sheetNames.map((name, idx) => (
                    <SelectItem key={idx} value={String(idx)}>{name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="rounded-lg border overflow-hidden">
            <div className="max-h-[300px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="border-b bg-background sticky top-0 z-10">
                <tr>
                  <th className="text-left py-2 px-1 text-xs font-medium">№</th>
                  <th className="text-left py-2 px-1 text-xs font-medium">Колонка</th>
                  <th className="text-left py-2 px-1 text-xs font-medium">Заголовок</th>
                  <th className="text-left py-2 px-1 text-xs font-medium">Системный ключ</th>
                  <th className="py-2 px-1"></th>
                </tr>
              </thead>
              <tbody className="pt-1">
                {passportColumns.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-3 text-center text-muted-foreground text-xs">
                      Паспорт колонок пуст.
                    </td>
                  </tr>
                ) : (
                  passportColumns.map((col, idx) => (
                    <tr key={idx} className="border-b">
                      <td className="py-0.5 px-1 text-xs">{idx + 1}</td>
                      <td className="py-0.5 px-1">
                        <Input
                          value={col.column}
                          onChange={e => updatePassportColumn(idx, "column", e.target.value)}
                          placeholder="A"
                          className="h-5 text-xs py-0 px-1"
                        />
                      </td>
                      <td className="py-0.5 px-1">
                        <Input
                          value={col.header}
                          onChange={e => updatePassportColumn(idx, "header", e.target.value)}
                          placeholder="Заголовок"
                          className="h-5 text-xs py-0 px-1"
                        />
                      </td>
                      <td className="py-0.5 px-1">
                        <Input
                          value={col.key}
                          onChange={e => updatePassportColumn(idx, "key", e.target.value)}
                          placeholder="Системный ключ"
                          className="h-5 text-xs py-0 px-1"
                        />
                      </td>
                      <td className="py-0.5 px-1 w-6">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-5 w-5 p-0 text-red-600"
                          onClick={() => removePassportColumn(idx)}
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
            </div>
          </div>
          <div className="mt-2 flex gap-2">
            <Button variant="outline" size="sm" onClick={addPassportColumn}>
              <Plus className="h-3.5 w-3.5 mr-1" />
              Добавить
            </Button>
          </div>
        </div>

        <div className="mt-6 space-y-4">
          <h3 className="text-sm font-medium">Правила нормализации</h3>

          <div className="rounded-lg border overflow-hidden">
            <div className="border-b bg-muted/40 px-3 py-2 text-xs font-medium">Операция: сырой текст → operation_code</div>
            <div className="max-h-[220px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="border-b bg-background sticky top-0 z-10">
                  <tr>
                    <th className="text-left py-2 px-1">contains</th>
                    <th className="text-left py-2 px-1">operation_code</th>
                    <th className="text-left py-2 px-1">operation_name</th>
                    <th className="text-left py-2 px-1">pack_op_code</th>
                    <th className="text-left py-2 px-1">pack_op_name</th>
                    <th className="text-left py-2 px-1">pack_family</th>
                    <th className="text-left py-2 px-1">priority</th>
                    <th className="py-2 px-1" />
                  </tr>
                </thead>
                <tbody>
                  {operationRules.map((row, idx) => (
                    <tr key={idx} className="border-b">
                      <td className="py-0.5 px-1"><Input value={row.contains} onChange={e => updateOperationRule(idx, { contains: e.target.value })} className="h-6 text-xs py-0 px-1" /></td>
                      <td className="py-0.5 px-1"><Input value={row.operation_code} onChange={e => updateOperationRule(idx, { operation_code: e.target.value })} className="h-6 text-xs py-0 px-1" /></td>
                      <td className="py-0.5 px-1"><Input value={row.operation_name} onChange={e => updateOperationRule(idx, { operation_name: e.target.value })} className="h-6 text-xs py-0 px-1" /></td>
                      <td className="py-0.5 px-1"><Input value={row.pack_op_code} onChange={e => updateOperationRule(idx, { pack_op_code: e.target.value })} className="h-6 text-xs py-0 px-1" /></td>
                      <td className="py-0.5 px-1"><Input value={row.pack_op_name} onChange={e => updateOperationRule(idx, { pack_op_name: e.target.value })} className="h-6 text-xs py-0 px-1" /></td>
                      <td className="py-0.5 px-1"><Input value={row.normalized_pack_op_family} onChange={e => updateOperationRule(idx, { normalized_pack_op_family: e.target.value })} className="h-6 text-xs py-0 px-1" /></td>
                      <td className="py-0.5 px-1"><Input type="number" value={String(row.priority)} onChange={e => updateOperationRule(idx, { priority: Number(e.target.value) || 0 })} className="h-6 w-16 text-xs py-0 px-1" /></td>
                      <td className="py-0.5 px-1">
                        <Button variant="ghost" size="sm" className="h-5 w-5 p-0 text-red-600" onClick={() => removeOperationRule(idx)}>
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="px-2 py-2">
              <Button variant="outline" size="sm" onClick={addOperationRule}>
                <Plus className="h-3.5 w-3.5 mr-1" />
                Добавить правило операции
              </Button>
            </div>
          </div>

          <div className="rounded-lg border p-3 text-xs grid grid-cols-1 md:grid-cols-5 gap-2">
            <div className="font-medium md:col-span-5">Fallback для операции</div>
            <Input value={operationFallback.operation_code} onChange={e => setOperationFallback(prev => ({ ...prev, operation_code: e.target.value }))} placeholder="operation_code" className="h-7 text-xs" />
            <Input value={operationFallback.operation_name} onChange={e => setOperationFallback(prev => ({ ...prev, operation_name: e.target.value }))} placeholder="operation_name" className="h-7 text-xs" />
            <Input value={operationFallback.pack_op_code} onChange={e => setOperationFallback(prev => ({ ...prev, pack_op_code: e.target.value }))} placeholder="pack_op_code" className="h-7 text-xs" />
            <Input value={operationFallback.pack_op_name} onChange={e => setOperationFallback(prev => ({ ...prev, pack_op_name: e.target.value }))} placeholder="pack_op_name/template" className="h-7 text-xs" />
            <Input value={operationFallback.normalized_pack_op_family} onChange={e => setOperationFallback(prev => ({ ...prev, normalized_pack_op_family: e.target.value }))} placeholder="pack_family" className="h-7 text-xs" />
          </div>

          <div className="rounded-lg border overflow-hidden">
            <div className="border-b bg-muted/40 px-3 py-2 text-xs font-medium">Output kind: сырой текст → normalized value</div>
            <div className="max-h-[180px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="border-b bg-background sticky top-0 z-10">
                  <tr>
                    <th className="text-left py-2 px-1">contains</th>
                    <th className="text-left py-2 px-1">result</th>
                    <th className="text-left py-2 px-1">priority</th>
                    <th className="py-2 px-1" />
                  </tr>
                </thead>
                <tbody>
                  {outputKindRules.map((row, idx) => (
                    <tr key={idx} className="border-b">
                      <td className="py-0.5 px-1"><Input value={row.contains} onChange={e => updateOutputKindRule(idx, { contains: e.target.value })} className="h-6 text-xs py-0 px-1" /></td>
                      <td className="py-0.5 px-1"><Input value={row.result} onChange={e => updateOutputKindRule(idx, { result: e.target.value })} className="h-6 text-xs py-0 px-1" /></td>
                      <td className="py-0.5 px-1"><Input type="number" value={String(row.priority)} onChange={e => updateOutputKindRule(idx, { priority: Number(e.target.value) || 0 })} className="h-6 w-16 text-xs py-0 px-1" /></td>
                      <td className="py-0.5 px-1">
                        <Button variant="ghost" size="sm" className="h-5 w-5 p-0 text-red-600" onClick={() => removeOutputKindRule(idx)}>
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="px-2 py-2 flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={addOutputKindRule}>
                <Plus className="h-3.5 w-3.5 mr-1" />
                Добавить правило output_kind
              </Button>
              <div className="ml-auto flex items-center gap-2">
                <span className="text-xs text-muted-foreground">fallback</span>
                <Input value={outputKindFallback} onChange={e => setOutputKindFallback(e.target.value)} className="h-7 w-36 text-xs" />
              </div>
            </div>
          </div>
        </div>
        </div>

        <DialogFooter className="flex items-center justify-between w-full sm:justify-between">
          <div>
            {isEdit && (
              <Button variant="destructive" onClick={() => void handleDeleteFromDialog()} disabled={saving}>
                <Trash2 className="mr-1 h-4 w-4" />
                Удалить
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="tpl-active"
              checked={isActive}
              onChange={e => setIsActive(e.target.checked)}
              className="h-4 w-4"
            />
            <label htmlFor="tpl-active" className="text-sm">Активен</label>
            <Button variant="outline" onClick={() => props.onOpenChange(false)} disabled={saving}>
              Отмена
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Сохранение..." : "Сохранить"}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
