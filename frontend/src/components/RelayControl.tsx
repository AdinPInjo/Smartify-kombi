import { ListChecks } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useSetRelayMode } from "@/api/hooks";
import type { Relay } from "@/api/types";
import { duration } from "@/lib/format";
import { Dialog, Segmented, useErrorToast } from "./ui";

type Mode = "auto" | "on" | "off";

export function relayTitle(relay: Relay): string {
  return relay.label || relay.name.charAt(0).toUpperCase() + relay.name.slice(1);
}

function modeOf(relay: Relay): Mode {
  return relay.mode === "auto" ? "auto" : (relay.manual_state ?? "off");
}

/** One line explaining why the relay is in its current state. */
export function relayExplanation(relay: Relay, now = Date.now() / 1000): string {
  if (relay.remote) return relay.remote;
  if (!relay.enabled) return "Disabled";
  if (relay.last_error) return `Hardware error: ${relay.last_error}`;
  if (relay.pending) return `Waiting: ${relay.pending}`;
  if (relay.mode === "manual") {
    const until = relay.manual_until ? ` · auto again in ${duration(relay.manual_until - now)}` : "";
    return `Manual ${relay.manual_state ?? ""}${until}`;
  }
  const why = relay.explanation ?? relay.reason;
  return why ? capitalize(why) : "Automatic";
}

function capitalize(text: string) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const DURATIONS = [
  { minutes: 30, label: "30 min" },
  { minutes: 60, label: "1 hour" },
  { minutes: 120, label: "2 hours" },
  { minutes: 240, label: "4 hours" },
  { minutes: 0, label: "Until I switch it back" },
];

export function RelayControl({ relay, large = false, link = true }: { relay: Relay; large?: boolean; link?: boolean }) {
  const setMode = useSetRelayMode();
  const showError = useErrorToast();
  const [askDuration, setAskDuration] = useState<"on" | "off" | null>(null);
  const on = relay.state === "on";

  const apply = (mode: Mode, minutes?: number) =>
    setMode.mutate({ id: relay.id, mode, durationMinutes: minutes || undefined }, { onError: showError });

  const choose = (mode: Mode) => {
    if (mode === "auto") apply("auto");
    else setAskDuration(mode);
  };

  return (
    <div className={`tile ${on ? "highlight" : ""}`} style={{ gap: 10, padding: large ? 16 : 14 }}>
      <div className="row-between">
        <div className="row">
          <span className={`dot ${on ? "on" : "off"}`} style={large ? { width: 12, height: 12 } : undefined} />
          {link ? (
            <Link to={`/switches/${relay.id}`} style={{ color: "inherit" }}>
              <span className="num" style={{ fontSize: large ? 30 : 24 }}>{relayTitle(relay)}</span>
            </Link>
          ) : (
            <span className="num" style={{ fontSize: large ? 30 : 24 }}>{relayTitle(relay)}</span>
          )}
        </div>
        <div className="row" style={{ gap: 8 }}>
          <span className={`mono tiny ${on ? "c-accent" : "muted"}`}>{on ? "ON" : "OFF"}</span>
          {link && (
            <Link to={`/switches/${relay.id}#rules`} className="btn small" aria-label={`Rules for ${relayTitle(relay)}`}>
              <ListChecks size={16} aria-hidden="true" /> Rules
            </Link>
          )}
        </div>
      </div>
      <div className={`small ${relay.last_error ? "c-danger" : "muted"}`}>{relayExplanation(relay)}</div>
      <Segmented<Mode>
        label={`${relayTitle(relay)} mode`}
        large={large}
        value={modeOf(relay)}
        disabled={setMode.isPending || !relay.enabled}
        onChange={choose}
        options={[
          { value: "auto", label: "Auto" },
          { value: "on", label: "On" },
          { value: "off", label: "Off" },
        ]}
      />
      {askDuration && (
        <Dialog title={`${relayTitle(relay)} ${askDuration}`} onClose={() => setAskDuration(null)}>
          <p className="muted" style={{ margin: 0 }}>
            For how long? Afterwards the rules take over again.
            {askDuration === "on" && relay.cutoff_max_c !== null &&
              ` The safety cutoff (${relay.cutoff_max_c} °C) still applies.`}
          </p>
          <div className="stack">
            {DURATIONS.map((d) => (
              <button
                key={d.minutes}
                type="button"
                className="btn"
                onClick={() => {
                  apply(askDuration, d.minutes);
                  setAskDuration(null);
                }}
              >
                {d.label}
              </button>
            ))}
          </div>
        </Dialog>
      )}
    </div>
  );
}
