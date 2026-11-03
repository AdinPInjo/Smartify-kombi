// Guided setup for push notifications: choose an app, install it, connect, test, choose alerts.
import { BellRing, CheckCircle2, Copy, ExternalLink, Loader2, Send } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useNotificationAction } from "@/api/hooks";
import type { NotificationSettings, NotifyChannel } from "@/api/types";
import { AlertGroups, CHANNEL_NAMES, TestButton, useNotifyPatch } from "./NotificationParts";
import { ErrorNote, useToast } from "./ui";

type Step = "choose" | "app" | "bot" | "connect" | "test" | "alerts" | "done";

const READABLE_TOPIC = /^kombi(-[a-z2-9]{4}){4}$/;
const BOT_TOKEN = /^\d+:[A-Za-z0-9_-]{20,}$/;

const ua = typeof navigator === "undefined" ? "" : navigator.userAgent;
const IS_ANDROID = /android/i.test(ua);
const IS_IOS = /iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && typeof document !== "undefined" && "ontouchend" in document);

const STORES = {
  ntfy: {
    ios: "https://apps.apple.com/app/ntfy/id1625396347",
    android: "https://play.google.com/store/apps/details?id=io.heckel.ntfy",
  },
  telegram: {
    ios: "https://apps.apple.com/app/telegram-messenger/id686449807",
    android: "https://play.google.com/store/apps/details?id=org.telegram.messenger",
  },
};

function stepsFor(channel: NotifyChannel | null, firstSetup: boolean): Step[] {
  const middle: Step[] = channel === "telegram" ? ["bot", "connect", "test"] : ["app", "connect", "test"];
  return [...(firstSetup || !channel ? (["choose"] as Step[]) : []), ...middle, ...(firstSetup ? (["alerts"] as Step[]) : []), "done"];
}

export function SetupGuide({
  settings,
  channel: initialChannel,
  firstSetup,
  onClose,
}: {
  settings: NotificationSettings;
  /** Start directly with this channel (adding a second one). */
  channel?: NotifyChannel;
  /** First time: also choose alerts at the end. */
  firstSetup: boolean;
  onClose: () => void;
}) {
  const [channel, setChannel] = useState<NotifyChannel | null>(initialChannel ?? null);
  const steps = stepsFor(channel, firstSetup);
  const [step, setStep] = useState<Step>(steps[0]);
  const index = steps.indexOf(step);
  const next = () => setStep(steps[Math.min(index + 1, steps.length - 1)]);
  const back = () => setStep(steps[Math.max(index - 1, 0)]);

  return (
    <section className="card guide" aria-label="Notification setup">
      <div className="row-between">
        <h2 className="label row" style={{ margin: 0, gap: 8 }}>
          <BellRing size={16} aria-hidden="true" /> Set up notifications{channel ? ` · ${CHANNEL_NAMES[channel]}` : ""}
        </h2>
        <span className="tiny faint">
          Step {index + 1} of {steps.length}
        </span>
      </div>
      <div className="guide-steps" aria-hidden="true">
        {steps.map((s, i) => (
          <span key={s} className={i <= index ? "done" : ""} />
        ))}
      </div>

      {step === "choose" && (
        <ChooseStep
          onChoose={(choice) => {
            setChannel(choice);
            setStep(choice === "telegram" ? "bot" : "app");
          }}
        />
      )}
      {step === "app" && <AppStep onNext={next} />}
      {step === "bot" && <BotStep settings={settings} onNext={next} />}
      {step === "connect" && channel === "ntfy" && <NtfyConnectStep settings={settings} onNext={next} />}
      {step === "connect" && channel === "telegram" && <TelegramConnectStep settings={settings} onNext={next} onBack={back} />}
      {step === "test" && channel && <TestStep channel={channel} settings={settings} onNext={next} onBack={back} />}
      {step === "alerts" && (
        <Pane
          title="What should the van tell you?"
          intro="Sensible defaults are already on. You can change this any time on this page."
          footer={
            <button type="button" className="btn primary" onClick={next}>
              Continue
            </button>
          }
        >
          <AlertGroups settings={settings} />
        </Pane>
      )}
      {step === "done" && channel && <DoneStep channel={channel} settings={settings} onClose={onClose} />}

      {step !== "done" && (
        <div className="row-between" style={{ marginTop: 4 }}>
          {index > 0 && step !== "test" ? (
            <button type="button" className="btn ghost small" onClick={back}>
              ← Back
            </button>
          ) : (
            <span />
          )}
          <button type="button" className="btn ghost small" onClick={onClose}>
            {firstSetup ? "Later" : "Cancel"}
          </button>
        </div>
      )}
    </section>
  );
}

function Pane({ title, intro, children, footer }: { title: string; intro?: ReactNode; children?: ReactNode; footer?: ReactNode }) {
  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="stack" style={{ gap: 4 }}>
        <h3 className="guide-title">{title}</h3>
        {intro && <p className="muted" style={{ margin: 0 }}>{intro}</p>}
      </div>
      {children}
      {footer && <div className="row wrap" style={{ gap: 10 }}>{footer}</div>}
    </div>
  );
}

function Numbered({ items }: { items: ReactNode[] }) {
  return (
    <ol className="guide-list">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ol>
  );
}

function StoreButtons({ app }: { app: keyof typeof STORES }) {
  const links = STORES[app];
  const name = app === "ntfy" ? "ntfy" : "Telegram";
  return (
    <div className="row wrap" style={{ gap: 10 }}>
      {!IS_ANDROID && (
        <a className={`btn ${IS_IOS ? "primary" : ""}`} href={links.ios} target="_blank" rel="noreferrer">
          {name} for iPhone <ExternalLink size={15} aria-hidden="true" />
        </a>
      )}
      {!IS_IOS && (
        <a className={`btn ${IS_ANDROID ? "primary" : ""}`} href={links.android} target="_blank" rel="noreferrer">
          {name} for Android <ExternalLink size={15} aria-hidden="true" />
        </a>
      )}
    </div>
  );
}

function CopyBox({ text, label }: { text: string; label: string }) {
  const toast = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${label} copied`);
    } catch {
      toast("Copying is blocked here: select the text and copy it by hand", true);
    }
  };
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="topic" aria-label={label}>
        {text}
      </div>
      <button type="button" className="btn" onClick={copy}>
        <Copy size={16} aria-hidden="true" /> Copy {label.toLowerCase()}
      </button>
    </div>
  );
}

// --- steps ----------------------------------------------------------------------------------------

function ChooseStep({ onChoose }: { onChoose: (channel: NotifyChannel) => void }) {
  return (
    <Pane
      title="Where should the van send messages?"
      intro="Pick the app you want them in. You can add the other one later."
    >
      <div className="grid-2">
        <button type="button" className="choice" onClick={() => onChoose("ntfy")}>
          <span className="row-between">
            <strong>ntfy app</strong>
            <span className="tag">recommended</span>
          </span>
          <span className="small muted">A free app made for notifications. No account, no phone number, set up in two minutes.</span>
        </button>
        <button type="button" className="choice" onClick={() => onChoose("telegram")}>
          <strong>Telegram</strong>
          <span className="small muted">
            Messages from your own Telegram bot. Good if you already use Telegram; takes a few more steps.
          </span>
        </button>
      </div>
      <p className="tiny faint" style={{ margin: 0 }}>
        Why not WhatsApp or SMS? WhatsApp only allows automatic messages through a paid business account, and SMS needs a SIM card
        in the van. Both apps above are free and reliable.
      </p>
    </Pane>
  );
}

function AppStep({ onNext }: { onNext: () => void }) {
  return (
    <Pane
      title="Install ntfy on your phone"
      intro="It's free and needs no account."
      footer={
        <button type="button" className="btn primary" onClick={onNext}>
          The app is installed
        </button>
      }
    >
      <StoreButtons app="ntfy" />
      <p className="small muted" style={{ margin: 0 }}>
        Open it once. When it asks to send notifications, tap <strong>Allow</strong>.
      </p>
    </Pane>
  );
}

function NtfyConnectStep({ settings, onNext }: { settings: NotificationSettings; onNext: () => void }) {
  const ntfy = settings.channels.ntfy;
  const action = useNotificationAction();
  const { patch } = useNotifyPatch();
  const prepared = useRef(false);
  const [error, setError] = useState<unknown>(null);

  // Give older installs an easy-to-type topic (nobody is subscribed yet), then switch ntfy on.
  useEffect(() => {
    if (prepared.current) return;
    prepared.current = true;
    const enable = () => patch({ channels: { ntfy: { enabled: true } } });
    if (!ntfy.enabled && !READABLE_TOPIC.test(ntfy.topic)) {
      action.mutate({ path: "/ntfy/new-topic" }, { onSuccess: enable, onError: setError });
    } else if (!ntfy.enabled) {
      enable();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const host = ntfy.server.replace(/^https?:\/\//, "");
  const ownServer = host !== "ntfy.sh";
  return (
    <Pane
      title="Subscribe to your van"
      intro="Your van has its own private topic. Subscribe to it in the app:"
      footer={
        <button type="button" className="btn primary" onClick={onNext} disabled={!ntfy.enabled}>
          I've subscribed
        </button>
      }
    >
      <ErrorNote error={error} />
      <CopyBox text={ntfy.topic} label="Topic" />
      {IS_ANDROID && (
        <a className="btn" href={`ntfy://${host}/${ntfy.topic}`}>
          Open in the ntfy app
        </a>
      )}
      <Numbered
        items={[
          <>
            In ntfy tap <strong>+</strong> (“Subscribe to topic”).
          </>,
          <>Paste or type the topic above, exactly as shown.</>,
          ownServer ? (
            <>
              Turn on <strong>Use another server</strong> and enter <code>{ntfy.server}</code>.
            </>
          ) : (
            <>Leave “Use another server” off.</>
          ),
          <>
            Tap <strong>Subscribe</strong>.
          </>,
        ]}
      />
      <p className="tiny faint" style={{ margin: 0 }}>
        The topic works like a password: anyone who knows it can read your van's messages. Don't post it anywhere.
      </p>
    </Pane>
  );
}

function BotStep({ settings, onNext }: { settings: NotificationSettings; onNext: () => void }) {
  const telegram = settings.channels.telegram;
  const { patch, pending } = useNotifyPatch();
  const [token, setToken] = useState("");
  const valid = BOT_TOKEN.test(token.trim());

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!valid) return;
    patch({ channels: { telegram: { bot_token: token.trim(), chat_id: "" } } }, () => {
      setToken("");
      onNext();
    });
  };

  return (
    <Pane title="Create your van's Telegram bot" intro="A bot is a Telegram account your van can write from. Making one takes a minute.">
      <StoreButtons app="telegram" />
      <Numbered
        items={[
          <>
            Open <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">@BotFather</a> in Telegram (the official bot for
            making bots, with a blue tick).
          </>,
          <>
            Send <code>/newbot</code>.
          </>,
          <>
            Send a name, for example <code>Kombi</code>, then a username ending in <code>bot</code>, for example{" "}
            <code>my_kombi_bot</code>.
          </>,
          <>
            BotFather answers with a <strong>token</strong> like <code>123456789:AAH…</code>. Copy it and paste it here:
          </>,
        ]}
      />
      <form className="stack" style={{ gap: 10 }} onSubmit={submit}>
        <input
          className="input mono"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder={telegram.bot_token_set ? "A token is saved. Paste a new one to replace it" : "123456789:AAH…"}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          aria-label="Bot token"
        />
        {token.trim() && !valid && <span className="small c-danger">That doesn't look like a bot token. Copy the whole line with the colon.</span>}
        <div className="row wrap" style={{ gap: 10 }}>
          <button type="submit" className="btn primary" disabled={!valid || pending}>
            Save token
          </button>
          {telegram.bot_token_set && !token && (
            <button type="button" className="btn" onClick={onNext}>
              Keep the saved token
            </button>
          )}
        </div>
      </form>
      <p className="tiny faint" style={{ margin: 0 }}>The token stays on the van. It is never shown again or sent anywhere else.</p>
    </Pane>
  );
}

function TelegramConnectStep({ settings, onNext, onBack }: { settings: NotificationSettings; onNext: () => void; onBack: () => void }) {
  const action = useNotificationAction();
  const { patch } = useNotifyPatch();
  const [found, setFound] = useState<string | null>(settings.channels.telegram.chat_id ? "your chat" : null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(!found);

  useEffect(() => {
    patch({ channels: { telegram: { enabled: true } } });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Look for the user's message every few seconds, for up to two minutes.
  useEffect(() => {
    if (!waiting) return;
    let tries = 0;
    const look = () => {
      tries += 1;
      action.mutate(
        { path: "/telegram/detect-chat" },
        {
          onSuccess: (result) => {
            const name = (result as unknown as { name?: string }).name;
            setFound(name || "your chat");
            setWaiting(false);
          },
          onError: (error) => {
            const message = error instanceof Error ? error.message : String(error);
            if (!message.startsWith("no message found")) {
              setFatal(message);
              setWaiting(false);
            } else if (tries >= 30) {
              setWaiting(false);
            }
          },
        },
      );
    };
    look();
    const timer = window.setInterval(look, 4000);
    return () => window.clearInterval(timer);
  }, [waiting]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Pane
      title="Say hello to your bot"
      intro="So the bot knows where to send messages, write to it once."
      footer={
        found ? (
          <button type="button" className="btn primary" onClick={onNext}>
            Continue
          </button>
        ) : fatal ? (
          <button type="button" className="btn" onClick={onBack}>
            ← Enter the token again
          </button>
        ) : (
          !waiting && (
            <button type="button" className="btn" onClick={() => setWaiting(true)}>
              Look again
            </button>
          )
        )
      }
    >
      <Numbered
        items={[
          <>
            In BotFather's answer tap the link to your bot (<code>t.me/…bot</code>).
          </>,
          <>
            Tap <strong>Start</strong>, or send it any message like “hi”.
          </>,
        ]}
      />
      {found ? (
        <div className="notice ok row" style={{ gap: 8 }}>
          <CheckCircle2 size={18} aria-hidden="true" /> Connected to {found}.
        </div>
      ) : fatal ? (
        <div className="notice error">{fatal}. Check that you copied the whole token from BotFather.</div>
      ) : waiting ? (
        <div className="row small muted" style={{ gap: 8 }}>
          <Loader2 size={16} className="spin" aria-hidden="true" /> Waiting for your message…
        </div>
      ) : (
        <span className="small muted">No message found yet. Send one to your bot, then look again.</span>
      )}
    </Pane>
  );
}

function TestStep({
  channel,
  settings,
  onNext,
  onBack,
}: {
  channel: NotifyChannel;
  settings: NotificationSettings;
  onNext: () => void;
  onBack: () => void;
}) {
  const [result, setResult] = useState<"none" | "sent" | "failed" | "missing">("none");
  const [error, setError] = useState<string | null>(null);
  const offline = error?.includes("no connection");

  return (
    <Pane
      title="Send a test"
      intro="Let's make sure messages really reach your phone."
      footer={
        result === "sent" ? (
          <>
            <button type="button" className="btn primary" onClick={onNext}>
              Yes, it arrived
            </button>
            <button type="button" className="btn" onClick={() => setResult("missing")}>
              Nothing arrived
            </button>
          </>
        ) : (
          <TestButton
            channel={channel}
            primary
            onResult={(message) => {
              setError(message);
              setResult(message ? "failed" : "sent");
            }}
          />
        )
      }
    >
      {result === "sent" && (
        <div className="notice row" style={{ gap: 8 }}>
          <Send size={18} aria-hidden="true" /> Sent. Did “Smartify test” arrive on your phone?
        </div>
      )}
      {result === "failed" && (
        <div className="notice error">
          {offline ? "The van can't reach the internet right now. Connect it to WiFi (Settings › WiFi), then try again." : error}
        </div>
      )}
      {result === "missing" && (
        <div className="stack" style={{ gap: 10 }}>
          <strong>Let's find out why</strong>
          <ul className="guide-list">
            {channel === "ntfy" ? (
              <>
                <li>
                  The topic in the app must be exactly <code>{settings.channels.ntfy.topic}</code>.
                </li>
                <li>Allow notifications for ntfy in your phone's settings.</li>
                {!IS_IOS && <li>Android: set ntfy's battery use to “Unrestricted” (Settings › Apps › ntfy › Battery).</li>}
                {!IS_ANDROID && <li>iPhone: open the ntfy app once after subscribing, and check Focus / Do Not Disturb.</li>}
              </>
            ) : (
              <>
                <li>Check that the chat with your bot isn't muted.</li>
                <li>Allow notifications for Telegram in your phone's settings.</li>
              </>
            )}
            <li>Your phone needs internet too (mobile data or WiFi).</li>
          </ul>
          <div className="row wrap" style={{ gap: 10 }}>
            <button type="button" className="btn primary" onClick={() => setResult("none")}>
              Try again
            </button>
            <button type="button" className="btn" onClick={onBack}>
              ← Back to the previous step
            </button>
          </div>
        </div>
      )}
    </Pane>
  );
}

function DoneStep({ channel, settings, onClose }: { channel: NotifyChannel; settings: NotificationSettings; onClose: () => void }) {
  const q = settings.quiet_hours;
  return (
    <Pane title="You're all set" footer={<button type="button" className="btn primary" onClick={onClose}>Done</button>}>
      <div className="notice ok row" style={{ gap: 8 }}>
        <CheckCircle2 size={18} aria-hidden="true" /> The van will now message you on {CHANNEL_NAMES[channel]}.
      </div>
      <ul className="guide-list">
        <li>Urgent alerts (the van is moving, too cold, too hot) come through day and night.</li>
        <li>{q.enabled ? `Other messages wait until ${q.to} if they happen between ${q.from} and ${q.to}.` : "Quiet hours are off: messages come straight away."}</li>
        <li>Without internet, messages wait in the van and go out once it's back online.</li>
        <li>Every message is also listed on this page.</li>
      </ul>
    </Pane>
  );
}
