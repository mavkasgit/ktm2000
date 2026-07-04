import { cn } from "@/shared/utils/cn";

export type ImportDialogStep = "upload" | "preview" | "result";

/** Shared dialog width/height tiers for import wizards. */
export const IMPORT_DIALOG_SIZES = {
  /** Result screen: icon + summary + close button. */
  compact: "max-w-lg",
  /** Upload / form step (compact wizard). */
  form: "max-w-2xl",
  /** Upload step with side-by-side template + reference panels. */
  formWide: "w-[50vw] max-w-[50vw]",
  /** Full preview table. */
  preview: "w-[85vw] max-w-[85vw] h-[92vh] max-h-[92vh]",
} as const;

export type ImportDialogUploadSize = "form" | "formWide";

export type GetImportDialogContentClassOptions = {
  className?: string;
  uploadSize?: ImportDialogUploadSize;
};

export const IMPORT_DIALOG_CONTENT_BASE =
  "w-full gap-2 p-3 sm:p-4 overflow-hidden flex flex-col transition-all duration-300";

export function getImportDialogSizeClass(
  step: ImportDialogStep,
  options?: Pick<GetImportDialogContentClassOptions, "uploadSize">,
): string {
  switch (step) {
    case "preview":
      return IMPORT_DIALOG_SIZES.preview;
    case "result":
      return `${IMPORT_DIALOG_SIZES.compact} max-h-[90vh]`;
    case "upload":
      return `${IMPORT_DIALOG_SIZES[options?.uploadSize ?? "form"]} max-h-[90vh]`;
    default:
      return `${IMPORT_DIALOG_SIZES.form} max-h-[90vh]`;
  }
}

export function getImportDialogContentClass(
  step: ImportDialogStep,
  options?: GetImportDialogContentClassOptions,
): string {
  return cn(IMPORT_DIALOG_CONTENT_BASE, getImportDialogSizeClass(step, options), options?.className);
}