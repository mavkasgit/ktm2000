import * as ToastPrimitives from "@radix-ui/react-toast";
import { CheckCircle, AlertCircle, X, Copy, ClipboardCheck } from "lucide-react";
import { useToast, type ToastData } from "./use-toast";
import * as React from "react";

function ToastIcon({ variant }: { variant: ToastData["variant"] }) {
  if (variant === "success") return <CheckCircle className="h-5 w-5 text-green-600" />;
  if (variant === "destructive") return <AlertCircle className="h-5 w-5 text-red-600" />;
  return null;
}

function toastClasses(variant: ToastData["variant"]) {
  const base =
    "group pointer-events-auto relative flex w-full items-center gap-3 overflow-hidden rounded-md border p-4 pr-8 shadow-sm transition-all data-[state=open]:animate-slide-in-from-right data-[state=closed]:animate-fade-out data-[swipe=cancel]:translate-x-0 data-[swipe=end]:translate-x-[var(--radix-toast-swipe-end-x)] data-[swipe=move]:translate-x-[var(--radix-toast-swipe-move-x)] data-[state=open]:duration-300 data-[state=closed]:duration-200 data-[state=open]:slide-in-from-right-full md:max-w-sm";
  if (variant === "success") return `${base} border-green-200 bg-green-50 text-green-900`;
  if (variant === "destructive") return `${base} border-red-200 bg-red-50 text-red-900`;
  return `${base} border bg-background text-foreground`;
}

function CopyButtonInline({ t }: { t: ToastData }) {
  const [copied, setCopied] = React.useState(false);

  if (copied) {
    return (
      <div className="flex-shrink-0 p-1.5" title="Скопировано">
        <ClipboardCheck className="h-4 w-4 text-green-600" />
      </div>
    );
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        e.preventDefault();
        const text = t.title + (t.description ? `: ${t.description}` : "");
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        try {
          document.execCommand("copy");
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        } catch {
        } finally {
          document.body.removeChild(textarea);
        }
      }}
      className="flex-shrink-0 p-1.5 rounded-md hover:bg-red-100 transition-colors cursor-pointer"
      title="Копировать ошибку"
      type="button"
    >
      <Copy className="h-4 w-4 text-red-500" />
    </button>
  );
}

export function Toaster() {
  const { toasts, dismissToast } = useToast();

  return (
    <ToastPrimitives.Provider>
      <ToastPrimitives.Viewport className="fixed top-4 right-4 z-[9999] flex max-h-screen w-full flex-col gap-2 p-4 md:max-w-[420px]">
        {toasts.map((t) => (
          <ToastPrimitives.Root
            key={t.id}
            className={toastClasses(t.variant)}
            onOpenChange={(open) => {
              if (!open) dismissToast(t.id);
            }}
          >
            <ToastIcon variant={t.variant} />
            <div className="flex flex-col gap-1 flex-1 min-w-0 pointer-events-auto" style={{ userSelect: "text", WebkitUserSelect: "text" }}>
              {t.title && (
                <div className="text-sm font-semibold break-words whitespace-normal">
                  {t.title}
                </div>
              )}
              {t.description && (
                <div className="text-sm opacity-90 break-words whitespace-normal">
                  {t.description}
                </div>
              )}
            </div>
            {t.variant === "destructive" && <CopyButtonInline t={t} />}
            <ToastPrimitives.Close className="absolute right-2 top-2 rounded-md p-1 opacity-60 transition-opacity hover:opacity-100 focus:outline-none z-50 relative">
              <X className="h-4 w-4" />
            </ToastPrimitives.Close>
          </ToastPrimitives.Root>
        ))}
      </ToastPrimitives.Viewport>
    </ToastPrimitives.Provider>
  );
}
