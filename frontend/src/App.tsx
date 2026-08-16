import { useCallback, useEffect, useState } from "react";

import {
  authConfig,
  clearToken,
  completeAuth0Login,
  fetchIdentity,
  Identity,
  loginAuth0,
  loginLocal,
  storedToken,
} from "./auth";

interface Health {
  status: string;
  db: string;
  redis: string;
}

const SEED_USERS = ["admin@demo", "operator@demo", "approver@demo", "demo@demo"];

/**
 * Phase 4 delivers MVP step 1 — "Admin logs in" — and nothing more.
 *
 * The definition of done says that step is *real*, which a login reachable
 * only by curl is not. So: sign in, see who you are and what you may do, sign
 * out. The dashboard screens are Phase 6 and this is deliberately not the
 * start of one.
 */
export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const config = authConfig();

  useEffect(() => {
    const poll = () =>
      fetch("/api/health")
        .then((r) => r.json())
        .then((h: Health) => {
          setHealth(h);
          setHealthError(false);
        })
        .catch(() => setHealthError(true));
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  const loadIdentity = useCallback(async (token: string) => {
    try {
      setIdentity(await fetchIdentity(token));
      setError(null);
    } catch (exc) {
      // A stored token that no longer works is worse than none: every
      // subsequent call 401s with no explanation. Drop it and say why.
      clearToken();
      setIdentity(null);
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  useEffect(() => {
    const returningFromAuth0 = new URLSearchParams(window.location.search).has("code");
    if (returningFromAuth0 && config.provider === "auth0") {
      completeAuth0Login(config)
        .then(loadIdentity)
        .catch((exc: Error) => setError(exc.message));
      return;
    }
    const existing = storedToken();
    if (existing) void loadIdentity(existing);
  }, [config, loadIdentity]);

  const signIn = async (email: string) => {
    setBusy(true);
    setError(null);
    try {
      if (config.provider === "auth0") {
        await loginAuth0(config);
        return;
      }
      await loadIdentity(await loginLocal(email));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    const token = storedToken();
    if (token) {
      // Best-effort: logout revokes nothing server-side (we issue no token of
      // our own), so the meaningful part is dropping it here.
      await fetch("/api/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => undefined);
    }
    clearToken();
    setIdentity(null);
  };

  const healthy = !healthError && health?.status === "ok";
  const dotColor =
    healthError || (health && health.status !== "ok") ? "#d33" : healthy ? "#2a2" : "#999";
  const healthLabel = healthError
    ? "backend unreachable"
    : health
      ? `backend ${health.status} (db: ${health.db}, redis: ${health.redis})`
      : "checking…";

  return (
    <main
      style={{
        fontFamily: "system-ui, sans-serif",
        padding: "3rem 1.5rem",
        maxWidth: 640,
        margin: "0 auto",
      }}
    >
      <h1 style={{ marginBottom: "0.25rem" }}>FlowForge-AI</h1>
      <p style={{ color: "#666", marginTop: 0 }}>
        <span
          style={{
            display: "inline-block",
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: dotColor,
            marginRight: 8,
          }}
        />
        {healthLabel}
      </p>

      <hr style={{ border: 0, borderTop: "1px solid #e5e5e5", margin: "1.5rem 0" }} />

      {identity ? (
        <section>
          <h2 style={{ fontSize: "1.1rem" }}>Signed in</h2>
          <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "0.4rem 1rem" }}>
            <dt style={{ color: "#666" }}>Email</dt>
            <dd style={{ margin: 0 }}>{identity.email}</dd>
            <dt style={{ color: "#666" }}>Roles</dt>
            <dd style={{ margin: 0 }}>{identity.roles.join(", ") || "none"}</dd>
            <dt style={{ color: "#666" }}>Organization</dt>
            <dd style={{ margin: 0, fontFamily: "ui-monospace, monospace", fontSize: "0.85rem" }}>
              {identity.org_id}
            </dd>
          </dl>
          <button type="button" onClick={signOut} style={{ marginTop: "1.25rem", padding: "0.5rem 1rem" }}>
            Sign out
          </button>
        </section>
      ) : (
        <section>
          <h2 style={{ fontSize: "1.1rem" }}>Sign in</h2>
          {config.provider === "auth0" ? (
            <button
              type="button"
              onClick={() => void signIn("")}
              disabled={busy}
              style={{ padding: "0.5rem 1rem" }}
            >
              Continue with Auth0
            </button>
          ) : (
            <>
              <p style={{ color: "#666", fontSize: "0.9rem" }}>
                Local dev issuer — pick a seeded identity. A real deployment
                redirects to Auth0 instead.
              </p>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                {SEED_USERS.map((email) => (
                  <button
                    key={email}
                    type="button"
                    onClick={() => void signIn(email)}
                    disabled={busy}
                    style={{ padding: "0.5rem 0.9rem" }}
                  >
                    {email}
                  </button>
                ))}
              </div>
            </>
          )}
        </section>
      )}

      {error && (
        <p style={{ color: "#d33", marginTop: "1.25rem" }} role="alert">
          {error}
        </p>
      )}
    </main>
  );
}
