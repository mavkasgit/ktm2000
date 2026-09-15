import * as React from "react";

export type ToastVariant = "default" | "success" | "destructive";

export interface ToastData {
  id: string;
  variant: ToastVariant;
  title: string;
  description?: string;
  open?: boolean;
}

type ToastAction =
  | { type: "ADD_TOAST"; toast: ToastData }
  | { type: "DISMISS_TOAST"; toastId?: string }
  | { type: "REMOVE_TOAST"; toastId?: string };

interface ToastState {
  toasts: ToastData[];
}

const toastTimeouts = new Map<string, ReturnType<typeof setTimeout>>();

/** Держим тост в DOM на время exit-анимации (`data-[state=closed]:duration-200`), затем убираем из стека. */
const TOAST_REMOVE_DELAY = 300;

const addToRemoveQueue = (toastId: string) => {
  if (toastTimeouts.has(toastId)) return;
  const timeout = setTimeout(() => {
    toastTimeouts.delete(toastId);
    dispatch({ type: "REMOVE_TOAST", toastId });
  }, TOAST_REMOVE_DELAY);
  toastTimeouts.set(toastId, timeout);
};

const reducer = (state: ToastState, action: ToastAction): ToastState => {
  switch (action.type) {
    case "ADD_TOAST":
      return {
        ...state,
        toasts: [{ ...action.toast, open: true }, ...state.toasts].slice(0, 3),
      };
    case "DISMISS_TOAST": {
      const { toastId } = action;
      if (toastId) {
        addToRemoveQueue(toastId);
      } else {
        state.toasts.forEach((t) => {
          addToRemoveQueue(t.id);
        });
      }
      return {
        ...state,
        toasts: state.toasts.map((t) =>
          t.id === toastId || toastId === undefined ? { ...t, open: false } : t
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

const listeners = new Set<() => void>();
let memoryState: ToastState = { toasts: [] };

function dispatch(action: ToastAction) {
  memoryState = reducer(memoryState, action);
  listeners.forEach((notify) => notify());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
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
  const state = React.useSyncExternalStore(subscribe, () => memoryState);

  return {
    toasts: state.toasts,
    addToast: (opts: Omit<ToastData, "id">) => toast(opts),
    dismissToast,
  };
}
