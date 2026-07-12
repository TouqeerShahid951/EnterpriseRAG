import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AlertCircle, CheckCircle2, Info, TriangleAlert, X } from "lucide-react";

type ToastTone = "error" | "info" | "success" | "warning";

type ToastInput = {
  description?: string;
  duration?: number;
  title: string;
  tone?: ToastTone;
};

type ToastItem = Required<Pick<ToastInput, "title" | "tone">> &
  Pick<ToastInput, "description"> & {
    closing: boolean;
    id: number;
  };

type ToastContextValue = {
  dismiss: (id: number) => void;
  notify: (toast: ToastInput) => number;
};

const ToastContext = createContext<ToastContextValue | null>(null);
const DEFAULT_DURATION = 5200;
const EXIT_DURATION = 180;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(0);
  const dismissTimers = useRef(new Map<number, number>());
  const removalTimers = useRef(new Map<number, number>());

  const remove = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
    dismissTimers.current.delete(id);
    removalTimers.current.delete(id);
  }, []);

  const dismiss = useCallback((id: number) => {
    const dismissTimer = dismissTimers.current.get(id);
    if (dismissTimer) window.clearTimeout(dismissTimer);

    setToasts((current) =>
      current.map((toast) => (toast.id === id ? { ...toast, closing: true } : toast)),
    );
    if (removalTimers.current.has(id)) return;
    removalTimers.current.set(id, window.setTimeout(() => remove(id), EXIT_DURATION));
  }, [remove]);

  const notify = useCallback((input: ToastInput) => {
    const id = ++nextId.current;
    const tone = input.tone ?? "info";
    const duration = input.duration ?? (tone === "error" ? 0 : DEFAULT_DURATION);
    setToasts((current) => [
      ...current,
      {
        closing: false,
        description: input.description,
        id,
        title: input.title,
        tone,
      },
    ]);
    if (duration > 0) {
      dismissTimers.current.set(id, window.setTimeout(() => dismiss(id), duration));
    }
    return id;
  }, [dismiss]);

  useEffect(() => () => {
    dismissTimers.current.forEach((timer) => window.clearTimeout(timer));
    removalTimers.current.forEach((timer) => window.clearTimeout(timer));
  }, []);

  const value = useMemo(() => ({ dismiss, notify }), [dismiss, notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport dismiss={dismiss} toasts={toasts} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider.");
  return context;
}

function ToastViewport({ dismiss, toasts }: { dismiss: (id: number) => void; toasts: ToastItem[] }) {
  return (
    <section className="Prudentia-toast-viewport" aria-label="Notifications">
      {toasts.map((toast) => (
        <article
          className="Prudentia-toast"
          data-closing={toast.closing || undefined}
          data-tone={toast.tone}
          key={toast.id}
          role={toast.tone === "error" ? "alert" : "status"}
        >
          <span className="Prudentia-toast-icon" aria-hidden="true">
            <ToastIcon tone={toast.tone} />
          </span>
          <span className="Prudentia-toast-copy">
            <strong>{toast.title}</strong>
            {toast.description ? <span>{toast.description}</span> : null}
          </span>
          <button type="button" onClick={() => dismiss(toast.id)} aria-label="Dismiss notification">
            <X size={16} />
          </button>
        </article>
      ))}
    </section>
  );
}

function ToastIcon({ tone }: { tone: ToastTone }) {
  if (tone === "success") return <CheckCircle2 size={18} />;
  if (tone === "error") return <AlertCircle size={18} />;
  if (tone === "warning") return <TriangleAlert size={18} />;
  return <Info size={18} />;
}
