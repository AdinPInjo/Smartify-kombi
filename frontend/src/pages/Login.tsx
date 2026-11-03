import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useHealth } from "@/api/hooks";
import { Topo } from "@/components/instruments";
import { ErrorNote, Field } from "@/components/ui";

export function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const client = useQueryClient();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const health = useHealth();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/login", { username, password });
      await client.invalidateQueries();
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : "/", { replace: true });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (health.data?.setup_required) return <Navigate to="/setup" replace />;

  return (
    <div className="shell" style={{ display: "grid", placeItems: "center", padding: 16 }}>
      <Topo />
      <form className="card" onSubmit={submit} style={{ width: "100%", maxWidth: 380, position: "relative", gap: 16 }}>
        <div className="row" style={{ gap: 14 }}>
          <img src="logo.svg" alt="" width={56} height={56} />
          <div className="stack" style={{ gap: 4 }}>
            <div className="label">Smartify · Kombi</div>
            <h1 className="page-title">Sign in</h1>
          </div>
        </div>
        <Field label="Username">
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </Field>
        <Field label="Password">
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            autoFocus
          />
        </Field>
        <ErrorNote error={error} />
        <button className="btn primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
