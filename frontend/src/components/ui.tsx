import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

export function Card({
  label,
  action,
  children,
  className = "",
  highlight = false,
}: {
  label?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  highlight?: boolean;
}) {
  return (
    <section className={`card ${highlight ? "highlight" : ""} ${className}`}>
      {(label || action) && (
        <div className="row-between">
          {label ? <h2 className="label" style={{ margin: 0 }}>{label}</h2> : <span />}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Num({
  value,
  unit,
  size = "m",
  className = "",
}: {
  value: ReactNode;
  unit?: string;
  size?: "xxl" | "xl" | "l" | "m" | "s";
  className?: string;
}) {
  return (
    <span className={`num num-${size} ${className}`}>
      {value}
      {unit && <span className="unit">{unit}</span>}
    </span>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  disabled,
  large,
  label,
}: {
  options: { value: T; label: string }[];
  value: T | null;
  onChange: (value: T) => void;
  disabled?: boolean;
  large?: boolean;
  label: string;
}) {
  return (
    <div className={`segmented ${large ? "large" : ""}`} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          disabled={disabled}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small className="faint tiny">{hint}</small>}
    </label>
  );
}

export function Dialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, select, button")?.focus();
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="row-between">
          <h2 className="page-title" style={{ fontSize: 26 }}>{title}</h2>
          <button type="button" className="btn ghost small" onClick={onClose} aria-label="Close">
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Skeleton({ height = 20, width = "100%" }: { height?: number; width?: number | string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden="true" />;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return <div className="notice error" role="alert">{message}</div>;
}

// --- toasts ----------------------------------------------------------------------

interface Toast {
  id: number;
  text: string;
  error: boolean;
}

const ToastContext = createContext<(text: string, error?: boolean) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const show = useCallback((text: string, error = false) => {
    const id = Date.now() + Math.random();
    setToasts((list) => [...list, { id, text, error }]);
    window.setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), error ? 6000 : 3000);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast ${toast.error ? "error" : ""}`}>
            {toast.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

/** Show the error message of a failed mutation as a toast. */
export function useErrorToast() {
  const toast = useToast();
  return (error: unknown) => toast(error instanceof Error ? error.message : String(error), true);
}
