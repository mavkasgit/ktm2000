import * as React from "react"
import { Check, Search } from "lucide-react"
import { Popover, PopoverContent, PopoverTrigger } from "./Popover"
import { Input } from "./Input"
import { cn } from "@/shared/utils/cn"

export type ComboboxOption = {
  label: string
  value: string
}

export type ComboboxProps = {
  options: ComboboxOption[]
  value?: string
  onValueChange?: (value: string) => void
  placeholder?: string
  emptyText?: string
  triggerContent?: React.ReactNode
  className?: string
}

export function Combobox({
  options,
  value,
  onValueChange,
  placeholder = "Выберите...",
  emptyText = "Ничего не найдено",
  triggerContent,
  className,
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false)
  const [search, setSearch] = React.useState("")

  const selected = options.find((o) => o.value === value)
  const filtered = options.filter((o) =>
    o.label.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1 text-sm w-full justify-start text-left",
            className
          )}
        >
          {triggerContent || selected?.label || placeholder}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[280px] p-2" align="start">
        <div className="relative mb-2">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Поиск..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8 h-8 text-sm"
            autoFocus
          />
        </div>
        <div className="max-h-[200px] overflow-auto">
          {filtered.length === 0 && (
            <p className="text-sm text-muted-foreground py-2 text-center">{emptyText}</p>
          )}
          {filtered.map((option) => (
            <button
              key={option.value}
              type="button"
              className={cn(
                "w-full text-left px-2 py-1.5 text-sm rounded-sm hover:bg-accent flex items-center gap-2",
                value === option.value && "bg-accent"
              )}
              onClick={() => {
                onValueChange?.(option.value)
                setOpen(false)
                setSearch("")
              }}
            >
              <Check
                className={cn(
                  "h-4 w-4 shrink-0",
                  value === option.value ? "opacity-100" : "opacity-0"
                )}
              />
              <span className="truncate">{option.label}</span>
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
