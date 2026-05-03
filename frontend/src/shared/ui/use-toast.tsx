import * as React from "react";
import * as ToastPrimitives from "@radix-ui/react-toast";

export type ToastVariant = "default" | "success" | "destructive";

export interface ToastData {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
}

type ToastAction =
  | { type: "ADD_TOAST"; toast: ToastData }
  | { type: "DISMISS_TOAST"; toastId?: string }
  | { type: "REMOVE_TOAST"; toastId?: string };

interface ToastState {
  toasts: ToastData[];
}

const toastTimeouts = new Map<string, ReturnType<typeof setTimeout>>();

const addToRemoveQueue = (toastId: string) => {
  if (toastTimeouts.has(toastId)) return;
  const timeout = setTimeout(() => {
    toastTimeouts.delete(toastId);
    dispatch({ type: "DISMISS_TOAST", toastId });
  }, 4000);
  toastTimeouts.set(toastId, timeout);
};

const reducer = (state: ToastState, action: ToastAction): ToastState => {
  switch (action.type) {
    case "ADD_TOAST":
      return { ...state, toasts: [action.toast, ...state.toasts].slice(0, 3) };
    case "DISMISS_TOAST": {
      const { toastId } = action;
      if (toastId) {
        addToRemoveQueue(toastId);
      }
      return {
        ...state,
        toasts: state.toasts.map((t) =>
          t.id === toastId || toastId === undefined ? { ...t, id: t.id } : t
        ),
      };
    }
    case "REMOVE_TOAST": {
      const { toastId } = action;
      if (toastId === undefined) return { ...state, toasts: [] };
      return {
        ...state,
        toasts: state.toasts.filter((t) => t.id !== toastId),
      };
    }
  }
};

const listeners: Array<(state: ToastState) => void> = [];
let memoryState: ToastState = { toasts: [] };

function dispatch(action: ToastAction) {
  memoryState = reducer(memoryState, action);
  listeners.forEach((fn) => fn(memoryState));
}

let toastCount = 0;
export function toast(opts: Omit<ToastData, "id">) {
  const id = `toast-${Date.now()}-${++toastCount}`;
  dispatch({ type: "ADD_TOAST", toast: { ...opts, id } });
  return id;
}

export function dismissToast(toastId?: string) {
  dispatch({ type: "DISMISS_TOAST", toastId });
}

export function useToast() {
  const [state, setState] = React.useState<ToastState>(memoryState);

  React.useEffect(() => {
    listeners.push(setState);
    return () => {
      const index = listeners.indexOf(setState);
      if (index > -1) listeners.splice(index, 1);
    };
  }, [state]);

  return {
    toasts: state.toasts,
    addToast: (opts: Omit<ToastData, "id">) => toast(opts),
    dismissToast,
  };
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<ToastState>(memoryState);

  React.useEffect(() => {
    listeners.push(setState);
    return () => {
      const index = listeners.indexOf(setState);
      if (index > -1) listeners.splice(index, 1);
    };
  }, []);

  return (
    <ToastPrimitives.Provider>
      {children}
      {state.toasts.map((t) => (
        <ToastPrimitives.Root
          key={t.id}
          className="group pointer-events-auto relative flex w-full items-center justify-between space-x-4 overflow-hidden rounded-md border p-4 pr-8 shadow-sm transition-all data-[state=open]:animate-slide-in-from-right data-[state=closed]:animate-fade-out data-[swipe=cancel]:translate-x-0 data-[swipe=end]:translate-x-[var(--radix-toast-swipe-end-x)] data-[swipe=move]:translate-x-[var(--radix-toast-swipe-move-x)] data-[state=open]:duration-300 data-[state=closed]:duration-200 data-[state=open]:slide-in-from-right-full md:max-w-sm"
          data-state={t.id ? "open" : "closed"}
          onOpenChange={(open) => {
            if (!open) dismissToast(t.id);
          }}
        >
          <div className="flex flex-col gap-1">
            {t.title && (
              <ToastPrimitives.Title className="text-sm font-semibold">
                {t.title}
              </ToastPrimitives.Title>
            )}
            {t.description && (
              <ToastPrimitives.Description className="text-sm opacity-90">
                {t.description}
              </ToastPrimitives.Description>
            )}
          </div>
          <ToastPrimitives.Close className="absolute right-2 top-2 rounded-md p-1 opacity-60 transition-opacity hover:opacity-100 focus:outline-none">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </ToastPrimitives.Close>
        </ToastPrimitives.Root>
      ))}
      <ToastPrimitives.Viewport className="fixed top-4 right-4 z-[100] flex max-h-screen w-full flex-col gap-2 p-4 md:max-w-[420px]" />
    </ToastPrimitives.Provider>
  );
}
