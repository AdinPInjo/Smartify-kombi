// A step-by-step guide for first-time setup (Victron devices, diesel heater):
// one step at a time, with Back and Next. Opens by itself the first time and
// can be opened again any time.

import { BookOpen, ChevronLeft, ChevronRight, X } from "lucide-react";
import { useState, type ReactNode } from "react";

export interface GuideStep {
  title: string;
  body: ReactNode;
  /** Shown under "Something wrong?" on this step. */
  trouble?: ReactNode;
}

function remembered(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "closed";
  } catch {
    return false;
  }
}

function remember(key: string, closed: boolean) {
  try {
    if (closed) window.localStorage.setItem(key, "closed");
    else window.localStorage.removeItem(key);
  } catch {
    /* only for this visit then */
  }
}

export function SetupGuide({
  id,
  title,
  steps,
  startOpen = true,
}: {
  /** Remembers per device whether the guide was closed. */
  id: string;
  title: string;
  steps: GuideStep[];
  /** Open unless closed before (e.g. only while nothing is set up yet). */
  startOpen?: boolean;
}) {
  const key = `smartify.guide.${id}`;
  const [open, setOpen] = useState(() => startOpen && !remembered(key));
  const [index, setIndex] = useState(0);
  const step = steps[index];
  const last = index === steps.length - 1;

  const close = () => {
    setOpen(false);
    remember(key, true);
  };

  if (!open) {
    return (
      <button
        type="button"
        className="btn small ghost"
        style={{ alignSelf: "flex-start" }}
        onClick={() => {
          setIndex(0);
          setOpen(true);
          remember(key, false);
        }}
      >
        <BookOpen size={16} aria-hidden="true" /> {title}: step by step
      </button>
    );
  }

  return (
    <section className="card guide" aria-label={title}>
      <div className="row-between">
        <span className="label row" style={{ gap: 8 }}>
          <BookOpen size={15} aria-hidden="true" /> {title}
        </span>
        <button type="button" className="btn small ghost" onClick={close} aria-label="Close the guide">
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <div className="guide-steps" aria-hidden="true">
        {steps.map((s, i) => (
          <span key={s.title} className={i <= index ? "done" : ""} />
        ))}
      </div>
      <div className="stack" style={{ gap: 10 }} aria-live="polite">
        <span className="tiny faint">
          Step {index + 1} of {steps.length}
        </span>
        <h3 className="guide-title">{step.title}</h3>
        <div className="stack" style={{ gap: 10 }}>{step.body}</div>
        {step.trouble && (
          <details>
            <summary className="small" style={{ cursor: "pointer" }}>Something wrong?</summary>
            <div className="small muted stack" style={{ gap: 6, marginTop: 8 }}>{step.trouble}</div>
          </details>
        )}
      </div>
      <div className="row-between">
        <button type="button" className="btn ghost" disabled={index === 0} onClick={() => setIndex(index - 1)}>
          <ChevronLeft size={18} aria-hidden="true" /> Back
        </button>
        {last ? (
          <button type="button" className="btn primary" onClick={close}>
            Done
          </button>
        ) : (
          <button type="button" className="btn primary" onClick={() => setIndex(index + 1)}>
            Next <ChevronRight size={18} aria-hidden="true" />
          </button>
        )}
      </div>
    </section>
  );
}
