// First-run setup: shown once, on a fresh install, before anything else.
import { Bell, Eye, EyeOff, ListChecks, Lock, SunMedium, Wifi } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useHealth } from "@/api/hooks";
import { Topo } from "@/components/instruments";
import { ErrorNote, Field, Skeleton } from "@/components/ui";

type Step = "welcome" | "account" | "done";

const TOO_COMMON = ["changeme", "password", "12345678", "123456789", "qwertyui", "smartify", "kombi123"];

function strength(password: string): { label: string; good: boolean } {
  if (password.length === 0) return { label: "", good: false };
  if (password.length < 8) return { label: `${8 - password.length} more characters`, good: false };
  if (TOO_COMMON.includes(password.toLowerCase())) return { label: "too easy to guess", good: false };
  const kinds = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  if (password.length >= 14 || kinds >= 3) return { label: "strong", good: true };
  return { label: "okay", good: true };
}

export function Setup() {
  const health = useHealth();
  const [step, setStep] = useState<Step>("welcome");

  if (health.isPending) {
    return (
      <Screen>
        <Skeleton height={260} />
      </Screen>
    );
  }
  // Already set up (and not just finished here): nothing to do on this page.
  if (!health.data?.setup_required && step !== "done") return <Navigate to="/" replace />;

  return (
    <Screen>
      <div className="guide-steps" aria-hidden="true">
        {(["welcome", "account", "done"] as Step[]).map((s, i, all) => (
          <span key={s} className={i <= all.indexOf(step) ? "done" : ""} />
        ))}
      </div>
      {step === "welcome" && <Welcome onNext={() => setStep("account")} />}
      {step === "account" && <Account onDone={() => setStep("done")} />}
      {step === "done" && <Done />}
    </Screen>
  );
}

function Screen({ children }: { children: ReactNode }) {
  return (
    <div className="shell" style={{ display: "grid", placeItems: "center", padding: 16, minHeight: "100vh" }}>
      <Topo />
      <section className="card setup-card">{children}</section>
    </div>
  );
}

function Welcome({ onNext }: { onNext: () => void }) {
  return (
    <div className="stack" style={{ gap: 16 }}>
      <img src="logo.svg" alt="" width={84} height={84} />
      <div className="stack" style={{ gap: 6 }}>
        <div className="label">Smartify · Kombi</div>
        <h1 className="page-title" style={{ fontSize: 40 }}>Welcome aboard</h1>
      </div>
      <p className="muted" style={{ margin: 0 }}>
        Your van's dashboard is installed and running. Let's make it yours: first a login, so only you can switch things in
        your van. It takes a minute.
      </p>
      <button type="button" className="btn primary" onClick={onNext}>
        Let's start
      </button>
    </div>
  );
}

function Account({ onDone }: { onDone: () => void }) {
  const client = useQueryClient();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const rating = strength(password);
  const matches = repeat.length > 0 && repeat === password;
  const ready = rating.good && matches && username.trim().length > 0 && !/\s/.test(username.trim());

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/setup", { username: username.trim(), password });
      await client.invalidateQueries();
      onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="stack" style={{ gap: 16 }} onSubmit={submit}>
      <div className="stack" style={{ gap: 6 }}>
        <div className="label row" style={{ gap: 8 }}>
          <Lock size={14} aria-hidden="true" /> Your login
        </div>
        <h1 className="page-title" style={{ fontSize: 34 }}>Create your login</h1>
        <p className="muted" style={{ margin: 0 }}>
          Anyone on the same WiFi as the van could open this dashboard. The login keeps your heater, fan and everything else
          in your hands.
        </p>
      </div>
      <Field label="Username">
        <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="off" required />
      </Field>
      <Field label="Password" hint="At least 8 characters. A few words in a row are easy to remember and hard to guess.">
        <div className="row" style={{ gap: 8 }}>
          <input
            className="input"
            type={show ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            required
            autoFocus
          />
          <button type="button" className="btn ghost" onClick={() => setShow(!show)} aria-label={show ? "Hide password" : "Show password"} style={{ minWidth: 44, padding: 0 }}>
            {show ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
          </button>
        </div>
      </Field>
      {rating.label && (
        <div className="row small" style={{ gap: 8 }}>
          <div className="strength" aria-hidden="true">
            <i style={{ width: rating.good ? (rating.label === "strong" ? "100%" : "60%") : "25%", background: rating.good ? "var(--ok)" : "var(--alert)" }} />
          </div>
          <span className={rating.good ? "c-ok" : "c-alert"}>{rating.label}</span>
        </div>
      )}
      <Field label="Repeat password">
        <input
          className="input"
          type={show ? "text" : "password"}
          value={repeat}
          onChange={(e) => setRepeat(e.target.value)}
          autoComplete="new-password"
          required
        />
      </Field>
      {repeat.length > 0 && !matches && <span className="small c-alert">The passwords are not the same yet.</span>}
      <ErrorNote error={error} />
      <button type="submit" className="btn primary" disabled={!ready || busy}>
        {busy ? "Saving…" : "Create login"}
      </button>
      <span className="tiny faint">
        Your phone or browser can save it. Forgot it later? It can be reset on the Pi (see docs/install.md).
      </span>
    </form>
  );
}

function NextStep({ to, icon, title, text }: { to: string; icon: ReactNode; title: string; text: string }) {
  return (
    <Link to={to} className="next-step">
      <span className="next-icon">{icon}</span>
      <span className="stack" style={{ gap: 2 }}>
        <strong>{title}</strong>
        <span className="small muted">{text}</span>
      </span>
      <span className="muted" aria-hidden="true">›</span>
    </Link>
  );
}

function Done() {
  const navigate = useNavigate();
  return (
    <div className="stack" style={{ gap: 16 }}>
      <img src="logo.svg" alt="" width={64} height={64} />
      <div className="stack" style={{ gap: 6 }}>
        <div className="label">All set</div>
        <h1 className="page-title" style={{ fontSize: 34 }}>Your dashboard is ready</h1>
        <p className="muted" style={{ margin: 0 }}>You're signed in. Here's what most people set up next, in any order:</p>
      </div>
      <div className="stack" style={{ gap: 8 }}>
        <NextStep to="/notifications" icon={<Bell size={18} />} title="Alerts on your phone" text="Battery, frost, theft and more, in 3 minutes." />
        <NextStep to="/energy/devices" icon={<SunMedium size={18} />} title="Victron devices" text="Battery, solar and chargers over Bluetooth." />
        <NextStep to="/switches" icon={<ListChecks size={18} />} title="Switches & rules" text="Heater, fan, pump: on a schedule or by temperature." />
        <NextStep to="/settings" icon={<Wifi size={18} />} title="WiFi" text="Join a campsite network from the dashboard." />
      </div>
      <button type="button" className="btn primary" onClick={() => navigate("/", { replace: true })}>
        Open the dashboard
      </button>
    </div>
  );
}
