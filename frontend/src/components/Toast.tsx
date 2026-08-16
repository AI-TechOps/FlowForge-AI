/**
 * Toasts.
 *
 * Used for actions whose result happens somewhere the user is not looking:
 * approving sends a run back to a worker, uploading starts a background job.
 * Without this, the only feedback is a row quietly changing on a screen the
 * user may already have left.
 *
 * Deliberately not used for errors inside a form or a panel — those belong
 * next to the thing that failed, where the user is already looking. A toast
 * for an inline error is how an error message ends up dismissed unread.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { Icon } from "./ui";
import { TID, testid } from "../testids";

type Tone = "ok" | "err" | "info";

interface Toast {
  id: number;
  tone: Tone;
  title: string;
  body?: string;
}

const ToastContext = createContext<((t: Omit<Toast, "id">) => void) | null>(null);

export function useToast() {
  const push = useContext(ToastContext);
  // A no-op outside the provider rather than a throw: a component test that
  // renders one screen should not have to mount the whole app.
  return push ?? (() => undefined);
}

let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((toast: Omit<Toast, "id">) => {
    const id = nextId++;
    setToasts((list) => [...list, { ...toast, id }]);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id));
  }, []);

  const value = useMemo(() => push, [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="region" aria-live="polite" aria-label="Notifications">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={() => dismiss(toast.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  useEffect(() => {
    // Errors stay until dismissed; success and info clear themselves. An error
    // that vanishes after four seconds is an error nobody read.
    if (toast.tone === "err") return;
    const timer = setTimeout(onDismiss, 4500);
    return () => clearTimeout(timer);
  }, [toast.tone, onDismiss]);

  const icon = toast.tone === "err" ? Icon.alert({ size: 16 }) : Icon.check({ size: 16 });

  return (
    <div className={`toast toast--${toast.tone}`} role="status" {...testid(TID.toast)}>
      <span className="toast__icon">{icon}</span>
      <div style={{ minWidth: 0 }}>
        <div className="toast__title">{toast.title}</div>
        {toast.body && <div className="toast__body">{toast.body}</div>}
      </div>
      <button type="button" className="toast__close" onClick={onDismiss} aria-label="Dismiss">
        ✕
      </button>
    </div>
  );
}
