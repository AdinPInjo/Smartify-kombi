import { useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, LocateFixed } from "lucide-react";
import type { TrackPoint } from "@/api/types";
import { dateTime, fmt } from "@/lib/format";

/** Index of the last point recorded at or before `ts` (points are sorted by time). */
export function pointAt(points: TrackPoint[], ts: number): number {
  let lo = 0;
  let hi = points.length - 1;
  if (hi < 0) return -1;
  if (ts <= points[0].created_at) return 0;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (points[mid].created_at <= ts) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

const PLAY_SECONDS = 20; // a full replay of the selected period takes about this long
const TICK_MS = 50;

/**
 * Time slider under the map: drag to see where the van was at that moment.
 * `time` null means "now" (whole route, live position).
 */
export function TrackScrubber({
  points,
  time,
  onChange,
}: {
  points: TrackPoint[];
  time: number | null;
  onChange: (time: number | null) => void;
}) {
  const [playing, setPlaying] = useState(false);
  const start = points[0]?.created_at ?? 0;
  const end = points[points.length - 1]?.created_at ?? 0;
  const span = Math.max(1, end - start);
  const step = Math.max(1, Math.round(span / 1000));
  const value = time ?? end;
  const index = useMemo(() => pointAt(points, value), [points, value]);
  const point = index >= 0 ? points[index] : null;

  // Keep the latest values for the play timer without restarting it each tick.
  const latest = useRef({ value, start, end, span });
  latest.current = { value, start, end, span };

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      const { value, start, end, span } = latest.current;
      const next = value + (span / (PLAY_SECONDS * 1000)) * TICK_MS;
      if (next >= end) {
        onChange(end);
        setPlaying(false);
      } else {
        onChange(Math.max(start, next));
      }
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, [playing, onChange]);

  if (points.length < 2) {
    return <p className="small muted" style={{ margin: 0 }}>Not enough route recorded in this period to replay yet.</p>;
  }

  const togglePlay = () => {
    if (!playing && value >= end) onChange(start); // replay from the beginning
    setPlaying(!playing);
  };

  return (
    <div className="scrubber">
      <div className="scrubber-row">
        <button
          type="button"
          className="btn small"
          onClick={togglePlay}
          aria-label={playing ? "Pause replay" : "Replay the route"}
        >
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <input
          type="range"
          className="scrubber-range"
          min={start}
          max={end}
          step={step}
          value={value}
          onChange={(e) => {
            setPlaying(false);
            onChange(Number(e.target.value));
          }}
          aria-label="Time along the route"
          aria-valuetext={point ? dateTime(point.created_at) : undefined}
        />
        <button
          type="button"
          className="btn small ghost"
          onClick={() => {
            setPlaying(false);
            onChange(null);
          }}
          disabled={time === null}
          aria-label="Back to the current position"
        >
          <LocateFixed size={16} /> Now
        </button>
      </div>
      <div className="scrubber-meta">
        <span className="tiny faint mono">{dateTime(start)}</span>
        <span className="small">
          {time === null ? (
            <span className="muted">Now · whole route</span>
          ) : point ? (
            <>
              <strong>{dateTime(point.created_at)}</strong>
              <span className="muted"> · {fmt(point.speed_kmh, 0)} km/h</span>
            </>
          ) : null}
        </span>
        <span className="tiny faint mono">{dateTime(end)}</span>
      </div>
    </div>
  );
}
