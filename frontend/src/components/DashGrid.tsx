// A grid of cards the owner arranges: drag by the handle (mouse, finger or pen),
// pick a width and a height, hide and show cards. Used by the Overview and the
// tablet panel; each keeps its own layout (lib/dashLayout.ts).

import { ArrowLeft, ArrowRight, EyeOff, GripVertical, Plus } from "lucide-react";
import { useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { change, moveTo, step, WIDTHS, type CardLayout, type DashLayout } from "@/lib/dashLayout";

export function DashGrid<Id extends string>({
  layout,
  save,
  editing,
  labels,
  render,
  className = "",
}: {
  layout: DashLayout<Id>;
  save: (layout: DashLayout<Id>) => void;
  editing: boolean;
  labels: Record<Id, string>;
  render: (card: CardLayout<Id>) => ReactNode;
  className?: string;
}) {
  const drag = useDrag(layout, save);
  const visible = layout.cards.filter((c) => !c.hidden);
  const hidden = layout.cards.filter((c) => c.hidden);
  return (
    <>
      <div className={`dash ${editing ? "editing" : ""} ${className}`}>
        {visible.map((card, index) => (
          <div
            key={card.id}
            data-card={card.id}
            className={`dash-item ${drag.dragging === card.id ? "dragging" : ""}`}
            style={{ "--w": card.w, "--wm": card.w >= 4 ? 2 : 1, "--h": card.h } as CSSProperties}
          >
            {render(card)}
            {editing && (
              <EditBar
                card={card}
                label={labels[card.id]}
                first={index === 0}
                last={index === visible.length - 1}
                onChange={(values) => save(change(layout, card.id, values))}
                onStep={(direction) => save(step(layout, card.id, direction))}
                handle={drag.handle(card.id)}
              />
            )}
          </div>
        ))}
      </div>
      {editing && hidden.length > 0 && (
        <div className="row wrap" style={{ gap: 8 }}>
          <span className="small muted">Hidden:</span>
          {hidden.map((card) => (
            <button key={card.id} type="button" className="btn small" onClick={() => save(change(layout, card.id, { hidden: false }))}>
              <Plus size={16} aria-hidden="true" /> {labels[card.id]}
            </button>
          ))}
        </div>
      )}
    </>
  );
}

type DragHandle = {
  onPointerDown: (event: ReactPointerEvent<HTMLElement>) => void;
  onPointerMove: (event: ReactPointerEvent<HTMLElement>) => void;
  onPointerUp: () => void;
  onPointerCancel: () => void;
};

/** Drag a card by its handle; the others make room live. */
function useDrag<Id extends string>(layout: DashLayout<Id>, save: (layout: DashLayout<Id>) => void) {
  const [dragging, setDragging] = useState<Id | null>(null);
  const latest = useRef(layout);
  latest.current = layout;
  const lastTarget = useRef<string | null>(null);

  const handle = (id: Id): DragHandle => ({
    onPointerDown: (event) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      lastTarget.current = null;
      setDragging(id);
    },
    onPointerMove: (event) => {
      if (dragging !== id) return;
      // Scroll when dragging near the top or bottom edge of the screen.
      if (event.clientY < 70) window.scrollBy(0, -14);
      else if (event.clientY > window.innerHeight - 110) window.scrollBy(0, 14);
      const over = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>("[data-card]");
      const target = over?.dataset.card as Id | undefined;
      if (!target || target === id) {
        lastTarget.current = null;
        return;
      }
      // After a swap the other card may now sit under the finger: don't swap back.
      if (target === lastTarget.current) return;
      lastTarget.current = target;
      save(moveTo(latest.current, id, target));
    },
    onPointerUp: () => setDragging(null),
    onPointerCancel: () => setDragging(null),
  });
  return { dragging, handle };
}

function EditBar<Id extends string>({
  card,
  label,
  first,
  last,
  onChange,
  onStep,
  handle,
}: {
  card: CardLayout<Id>;
  label: string;
  first: boolean;
  last: boolean;
  onChange: (values: Partial<Omit<CardLayout<Id>, "id">>) => void;
  onStep: (direction: -1 | 1) => void;
  handle: DragHandle;
}) {
  return (
    <div className="dash-edit" role="group" aria-label={`${label}: layout`}>
      <div className="dash-edit-top">
        <button type="button" className="dash-handle" aria-label={`Drag ${label}`} {...handle}>
          <GripVertical size={20} aria-hidden="true" />
        </button>
        <strong className="small grow" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {label}
        </strong>
        <button type="button" className="dash-icon" aria-label={`Move ${label} earlier`} disabled={first} onClick={() => onStep(-1)}>
          <ArrowLeft size={18} aria-hidden="true" />
        </button>
        <button type="button" className="dash-icon" aria-label={`Move ${label} later`} disabled={last} onClick={() => onStep(1)}>
          <ArrowRight size={18} aria-hidden="true" />
        </button>
        <button type="button" className="dash-icon" aria-label={`Hide ${label}`} onClick={() => onChange({ hidden: true })}>
          <EyeOff size={18} aria-hidden="true" />
        </button>
      </div>
      <div className="dash-options" role="group" aria-label="Width">
        {WIDTHS.map((width) => (
          <button
            key={width.value}
            type="button"
            className={card.w === width.value ? "on" : ""}
            aria-pressed={card.w === width.value}
            aria-label={`Width: ${width.name}`}
            onClick={() => onChange({ w: width.value })}
          >
            {width.label}
          </button>
        ))}
      </div>
      <div className="dash-options" role="group" aria-label="Height">
        {([1, 2] as const).map((h) => (
          <button key={h} type="button" className={card.h === h ? "on" : ""} aria-pressed={card.h === h} onClick={() => onChange({ h })}>
            {h === 1 ? "1 row" : "2 rows"}
          </button>
        ))}
      </div>
    </div>
  );
}
