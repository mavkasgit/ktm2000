import { useEffect, useId, useState } from "react"
import { cn } from "@/shared/utils/cn"

export interface DateTimePickerProps {
  date: string
  time: string
  onDateChange: (date: string) => void
  onTimeChange: (time: string) => void
  label?: string
  placeholder?: string
  className?: string
  disabled?: boolean
  dateDisabled?: boolean
}

function formatDateForDisplay(isoDate: string): string {
  if (!isoDate) return ""
  if (isoDate.includes(".")) return isoDate
  const [year, month, day] = isoDate.split("-")
  if (!year || !month || !day) return ""
  return `${day}.${month}.${year}`
}

function formatDateForStorage(displayDate: string): string {
  if (!displayDate) return ""
  const parts = displayDate.split(".")
  if (parts.length !== 3) return ""
  const [day, month, year] = parts
  if (day.length !== 2 || month.length !== 2 || year.length !== 4) return ""
  return `${year}-${month}-${day}`
}

function formatTimeForDisplay(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 4)
  if (digits.length <= 2) return digits
  return `${digits.slice(0, 2)}:${digits.slice(2)}`
}

function isValidTime(value: string): boolean {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(value)
}

function formatDateForInput(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 8)
  let result = ""
  for (let i = 0; i < digits.length; i++) {
    if (i === 2 || i === 4) result += "."
    result += digits[i]
  }
  return result
}

export function DateTimePicker({
  date,
  time,
  onDateChange,
  onTimeChange,
  label,
  placeholder,
  className,
  disabled = false,
  dateDisabled = false,
}: DateTimePickerProps) {
  const id = useId()
  const [timeInputValue, setTimeInputValue] = useState("")
  const [dateInputValue, setDateInputValue] = useState("")

  useEffect(() => {
    setTimeInputValue(time || "")
  }, [time])

  useEffect(() => {
    setDateInputValue(formatDateForDisplay(date))
  }, [date, time])

  const handleTimeChange = (raw: string) => {
    const formatted = formatTimeForDisplay(raw)
    setTimeInputValue(formatted)
    if (isValidTime(formatted)) {
      onTimeChange(formatted)
    }
  }

  const handleDateChange = (raw: string) => {
    const formatted = formatDateForInput(raw)
    setDateInputValue(formatted)
    const nextDate = formatDateForStorage(formatted)
    if (nextDate) {
      onDateChange(nextDate)
    }
  }

  return (
    <div className={cn("relative", className)}>
      {label && (
        <label htmlFor={id} className="text-sm font-medium whitespace-nowrap">
          {label}
        </label>
      )}
      <div className={cn("flex flex-row gap-2", disabled && "opacity-50 pointer-events-none")}>
        <input
          id={`${id}-time`}
          type="text"
          placeholder="ЧЧ:ММ"
          aria-label={`${label || placeholder || "Дата и время"}: время`}
          value={timeInputValue}
          onChange={(e) => handleTimeChange(e.target.value)}
          onFocus={(e) => e.target.select()}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur() }}
          className="flex h-10 w-[130px] rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-0 placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          maxLength={5}
          disabled={disabled}
        />
        <input
          id={id}
          type="text"
          placeholder={placeholder || "ДД.ММ.ГГГГ"}
          aria-label={`${label || placeholder || "Дата и time"}: дата`}
          value={dateInputValue}
          onChange={(e) => handleDateChange(e.target.value)}
          onFocus={(e) => e.target.select()}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur() }}
          className={cn(
            "flex h-10 w-[130px] rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-0 placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            dateDisabled && "bg-muted text-muted-foreground"
          )}
          maxLength={10}
          disabled={disabled || dateDisabled}
        />
      </div>
    </div>
  )
}
