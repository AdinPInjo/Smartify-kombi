import { BellOff, Smartphone } from "lucide-react";
import { useState } from "react";
import { useMode, useNotificationSettings } from "@/api/hooks";
import type { NotificationSettings, NotifyChannel } from "@/api/types";
import { AlertGroups, CHANNEL_NAMES, HistoryCard, QuietHoursCard, TestButton, TheftCard, useNotifyPatch } from "@/components/NotificationParts";
import { SetupGuide } from "@/components/NotificationSetup";
import { PageHeader } from "@/components/PageHeader";
import { OnlyOnVan } from "@/components/RemoteBanner";
import { Card, ErrorNote, Skeleton } from "@/components/ui";

export function Notifications() {
  const { cloud } = useMode();
  const settings = useNotificationSettings(!cloud);
  const [guide, setGuide] = useState<{ channel?: NotifyChannel; first: boolean } | null>(null);
  const [later, setLater] = useState(false);
  const s = settings.data;
  const active = s?.active_channels ?? [];
  const configured = active.length > 0;

  const sub = cloud
    ? undefined
    : !s
      ? undefined
      : configured
        ? `Messages go to ${active.map((c) => CHANNEL_NAMES[c]).join(" and ")}`
        : "Not set up yet: the van can't reach you";

  return (
    <main className="page">
      <PageHeader kicker="Alerts" title="Notifications" sub={sub} />
      {cloud && (
        <Card label="Notifications">
          <OnlyOnVan what="Setting up notifications" />
        </Card>
      )}
      {!cloud && settings.isPending && <Skeleton height={260} />}
      {!cloud && settings.error && <ErrorNote error={settings.error} />}
      {s && (
        <>
          {guide ? (
            <SetupGuide settings={s} channel={guide.channel} firstSetup={guide.first} onClose={() => setGuide(null)} />
          ) : !configured && !later ? (
            <Welcome onStart={() => setGuide({ first: true })} onLater={() => setLater(true)} />
          ) : !configured ? (
            <div className="notice row-between wrap">
              <span className="row" style={{ gap: 8 }}>
                <BellOff size={18} aria-hidden="true" /> No app is connected, so the van can't send you anything yet.
              </span>
              <button type="button" className="btn small primary" onClick={() => setGuide({ first: true })}>
                Set up now
              </button>
            </div>
          ) : null}

          {!guide && (configured || later) && (
            <div className="grid">
              <div className="stack" style={{ gap: "var(--gap)" }}>
                <PhoneCard settings={s} onSetup={(channel) => setGuide({ channel, first: false })} />
                <TheftCard settings={s} />
                <QuietHoursCard settings={s} />
              </div>
              <div className="stack" style={{ gap: "var(--gap)" }}>
                <section className="card">
                  <h2 className="label" style={{ margin: 0 }}>What to tell you</h2>
                  <AlertGroups settings={s} includeTheft={false} />
                </section>
                <HistoryCard />
              </div>
            </div>
          )}
        </>
      )}
    </main>
  );
}

function Welcome({ onStart, onLater }: { onStart: () => void; onLater: () => void }) {
  return (
    <section className="card highlight welcome">
      <Smartphone size={34} aria-hidden="true" className="c-accent" />
      <h2 className="guide-title" style={{ fontSize: 28 }}>Let your van message you</h2>
      <p className="muted" style={{ margin: 0, maxWidth: 560 }}>
        Get a notification on your phone when the battery runs low, it's freezing or too hot inside, frost is coming, the water
        tank is almost empty, or when the van starts moving while you're away.
      </p>
      <ul className="guide-list">
        <li>Free, with the ntfy app or Telegram</li>
        <li>About 3 minutes to set up</li>
        <li>Works on iPhone and Android</li>
      </ul>
      <div className="row wrap" style={{ gap: 10 }}>
        <button type="button" className="btn primary" onClick={onStart}>
          Start setup
        </button>
        <button type="button" className="btn ghost" onClick={onLater}>
          Not now
        </button>
      </div>
    </section>
  );
}

function PhoneCard({ settings, onSetup }: { settings: NotificationSettings; onSetup: (channel: NotifyChannel) => void }) {
  const { patch } = useNotifyPatch();
  const { ntfy, telegram } = settings.channels;
  const rows: { channel: NotifyChannel; ready: boolean; enabled: boolean; detail: string }[] = [
    {
      channel: "ntfy",
      enabled: ntfy.enabled,
      ready: settings.active_channels.includes("ntfy"),
      detail: ntfy.enabled ? `topic ${ntfy.topic}` : "not used",
    },
    {
      channel: "telegram",
      enabled: telegram.enabled,
      ready: settings.active_channels.includes("telegram"),
      detail: settings.active_channels.includes("telegram") ? "your bot" : telegram.enabled ? "setup not finished" : "not used",
    },
  ];
  return (
    <section className="card">
      <h2 className="label" style={{ margin: 0 }}>Your phone</h2>
      <div className="list">
        {rows.map(({ channel, ready, enabled, detail }) => (
          <div key={channel} className="stack" style={{ gap: 8 }}>
            <div className="row-between">
              <span className="row" style={{ gap: 10, minWidth: 0 }}>
                <span className={`dot ${ready ? "ok" : enabled ? "warn" : "off"}`} />
                <span className="stack" style={{ gap: 0, minWidth: 0 }}>
                  <strong>{CHANNEL_NAMES[channel]}</strong>
                  <span className="tiny faint" style={{ overflowWrap: "anywhere" }}>{detail}</span>
                </span>
              </span>
            </div>
            <div className="row wrap" style={{ gap: 8 }}>
              {ready ? (
                <>
                  <TestButton channel={channel} />
                  <button
                    type="button"
                    className="btn small ghost"
                    onClick={() => {
                      if (!window.confirm(`Stop sending notifications to ${CHANNEL_NAMES[channel]}?`)) return;
                      patch(
                        channel === "telegram"
                          ? { channels: { telegram: { enabled: false, bot_token: null, chat_id: "" } } }
                          : { channels: { ntfy: { enabled: false } } },
                      );
                    }}
                  >
                    Remove
                  </button>
                </>
              ) : (
                <button type="button" className="btn small" onClick={() => onSetup(channel)}>
                  {enabled ? "Finish setup" : `Add ${CHANNEL_NAMES[channel]}`}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
