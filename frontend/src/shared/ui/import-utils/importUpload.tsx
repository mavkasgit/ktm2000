import { useCallback, useEffect } from "react";
import { Upload } from "lucide-react";

import { cn } from "@/shared/utils/cn";
import { Badge } from "../badge";

export function useImportClipboardPaste(options: {
  enabled: boolean;
  onPaste: (text: string) => void;
}) {
  const { enabled, onPaste } = options;

  const handlePaste = useCallback(
    (e: ClipboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target instanceof HTMLInputElement ||
          target instanceof HTMLTextAreaElement ||
          target.isContentEditable)
      ) {
        return;
      }

      const text = e.clipboardData?.getData("text/plain");
      if (!text?.trim()) return;

      e.preventDefault();
      onPaste(text.trim());
    },
    [onPaste],
  );

  useEffect(() => {
    if (!enabled) return;
    document.addEventListener("paste", handlePaste);
    return () => document.removeEventListener("paste", handlePaste);
  }, [enabled, handlePaste]);
}

export type ImportUploadDropzoneProps = {
  inputRef: React.Ref<HTMLInputElement>;
  accept?: string;
  onFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  subtitle?: string;
  hint?: React.ReactNode;
  fileName?: string | null;
  className?: string;
};

export function ImportUploadDropzone({
  inputRef,
  accept = ".xlsx,.xls",
  onFileChange,
  onClick,
  disabled,
  title = "Выберите файл .xlsx / .xls",
  subtitle = "или вставьте скопированную таблицу — Ctrl+V",
  hint,
  fileName,
  className,
}: ImportUploadDropzoneProps) {
  return (
    <div
      onClick={() => {
        if (disabled) return;
        if (onClick) {
          onClick();
          return;
        }
        if (inputRef && typeof inputRef !== "function" && inputRef.current) {
          inputRef.current.click();
        }
      }}
      className={cn(
        "border-2 border-dashed border-muted-foreground/30 rounded-xl px-4 py-5 bg-muted/10",
        "flex flex-col items-center justify-center cursor-pointer",
        "hover:bg-accent/40 hover:border-primary/40 transition-colors",
        disabled && "opacity-50 cursor-not-allowed pointer-events-none",
        className,
      )}
    >
      <input
        type="file"
        ref={inputRef}
        onChange={onFileChange}
        accept={accept}
        className="hidden"
        disabled={disabled}
      />
      <Upload className="h-8 w-8 text-muted-foreground mb-2" />
      <span className="text-sm font-medium text-center">{fileName ?? title}</span>
      {!fileName && subtitle ? (
        <span className="text-[10px] text-muted-foreground mt-1 text-center">{subtitle}</span>
      ) : null}
      {hint}
    </div>
  );
}

export type ImportClipboardBannerProps = {
  text: string;
  invalidCount?: number;
  totalCount?: number;
  hints?: React.ReactNode;
  className?: string;
};

export function ImportClipboardBanner({
  text,
  invalidCount = 0,
  totalCount = 0,
  hints,
  className,
}: ImportClipboardBannerProps) {
  if (!text.trim()) return null;

  return (
    <div
      className={cn(
        "shrink-0 rounded-lg border border-amber-200/80 bg-amber-50/40 dark:bg-amber-950/10 dark:border-amber-900/40 p-3 space-y-2",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold text-amber-900 dark:text-amber-200 uppercase tracking-wider">
          Вставлено из буфера
        </span>
        {invalidCount > 0 ? (
          <Badge variant="outline" className="text-red-700 border-red-200 bg-red-50/50 text-[10px]">
            {invalidCount} строк с ошибками
          </Badge>
        ) : null}
      </div>
      <pre className="text-[10px] font-mono whitespace-pre-wrap max-h-28 overflow-y-auto rounded border border-amber-200/60 bg-background/80 p-2 leading-relaxed text-foreground">
        {text}
      </pre>
      {hints ??
        (totalCount === 0 ? (
          <p className="text-xs text-destructive leading-relaxed">
            Не удалось распознать ни одной строки. Укажите заголовки (Артикул, Кол-во, Статус качества,
            Операции, Участок) или вставьте данные без заголовков в порядке шаблона Excel. Колонки должны
            быть разделены табуляцией при копировании из Excel.
          </p>
        ) : invalidCount > 0 ? (
          <p className="text-xs text-muted-foreground leading-relaxed">
            Ниже — как система разобрала каждую строку. Ошибки указаны в последней колонке; включите
            «Сырые строки», чтобы увидеть исходные ячейки.
          </p>
        ) : null)}
    </div>
  );
}

export type ImportUploadIntroProps = {
  children: React.ReactNode;
  className?: string;
};

export function ImportUploadIntro({ children, className }: ImportUploadIntroProps) {
  return (
    <div className={cn("text-xs text-muted-foreground leading-relaxed space-y-1", className)}>
      {children}
    </div>
  );
}

export type ImportUploadSettingsCardProps = {
  title?: string;
  children: React.ReactNode;
  className?: string;
};

export function ImportUploadSettingsCard({
  title,
  children,
  className,
}: ImportUploadSettingsCardProps) {
  return (
    <div className={cn("p-3 bg-muted/40 rounded-lg border space-y-3", className)}>
      {title ? (
        <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider block">
          {title}
        </span>
      ) : null}
      {children}
    </div>
  );
}

export type ImportUploadFooterHintProps = {
  children: React.ReactNode;
  className?: string;
};

export function ImportUploadFooterHint({ children, className }: ImportUploadFooterHintProps) {
  return (
    <p className={cn("text-[10px] text-muted-foreground leading-snug", className)}>{children}</p>
  );
}

export const ImportUpload = {
  Dropzone: ImportUploadDropzone,
  ClipboardBanner: ImportClipboardBanner,
  Intro: ImportUploadIntro,
  SettingsCard: ImportUploadSettingsCard,
  FooterHint: ImportUploadFooterHint,
};