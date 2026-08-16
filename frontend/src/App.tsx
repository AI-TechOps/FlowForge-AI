/**
 * Routes and the authentication boundary.
 *
 * One decision worth naming: the app renders `Login` until `GET /api/me`
 * succeeds, rather than trusting the presence of a token. A token in
 * sessionStorage proves only that we once had one — it may be expired, or
 * signed by an issuer the backend has since stopped trusting. Asking the server
 * who we are is the only answer that cannot be stale, and it is one request.
 */

import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { authConfig, completeAuth0Login, storedToken } from "./auth";
import { useIdentity } from "./api/hooks";
import { ErrorState, Loading } from "./components/ui";
import { IdentityProvider, RequireRole, Shell } from "./shell/Shell";
import { AgentConfig } from "./screens/AgentConfig";
import { Approvals } from "./screens/Approvals";
import { Audit } from "./screens/Audit";
import { Dashboard } from "./screens/Dashboard";
import { Documents } from "./screens/Documents";
import { Evaluation } from "./screens/Evaluation";
import { Login } from "./screens/Login";
import { RunDetail } from "./screens/RunDetail";
import { Runs } from "./screens/Runs";
import { Tickets } from "./screens/Tickets";

export default function App() {
  const [token, setToken] = useState<string | null>(() => storedToken());
  const [authError, setAuthError] = useState<string | null>(null);
  const [exchanging, setExchanging] = useState(false);
  const config = authConfig();

  // Auth0 returns to the SPA with `?code=…`; exchange it once, then clean the
  // URL so a refresh does not attempt to redeem a spent code.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (!params.has("code") || config.provider !== "auth0") return;
    setExchanging(true);
    completeAuth0Login(config)
      .then((issued) => {
        setToken(issued);
        window.history.replaceState({}, "", window.location.pathname);
      })
      .catch((exc: Error) => setAuthError(exc.message))
      .finally(() => setExchanging(false));
  }, [config]);

  const identity = useIdentity(Boolean(token));

  // `loginLocal` and `completeAuth0Login` both persist the token themselves —
  // this only lifts it into React state so the tree re-renders.
  const onToken = useCallback((issued: string) => {
    setToken(issued);
    setAuthError(null);
  }, []);

  if (exchanging) return <Loading label="Completing sign-in" />;

  if (!token) {
    return (
      <>
        {authError && (
          <div className="banner banner--err" style={{ margin: "var(--sp-4)" }} role="alert">
            {authError}
          </div>
        )}
        <Login onToken={onToken} />
      </>
    );
  }

  if (identity.isPending) return <Loading label="Signing in" />;

  if (identity.isError || !identity.data) {
    // Two very different failures land here and "could not load your identity"
    // describes only one of them: an expired token, and a backend that is not
    // running at all. `GET /api/health` is the one endpoint that answers
    // without a token, so it is what separates "sign in again" from "start the
    // stack" — and the second is the one somebody demoing actually hits.
    return <IdentityFailure error={identity.error} onRestart={() => setToken(null)} />;
  }

  return (
    <IdentityProvider value={identity.data}>
      <Routes>
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route element={<Shell identity={identity.data} />}>
          <Route index element={<Dashboard />} />
          <Route path="tickets" element={<Tickets />} />
          <Route path="runs" element={<Runs />} />
          <Route path="runs/:runId" element={<RunDetail />} />
          <Route
            path="approvals"
            element={
              <RequireRole roles={["approver", "administrator"]}>
                <Approvals />
              </RequireRole>
            }
          />
          <Route
            path="documents"
            element={
              <RequireRole roles={["administrator"]}>
                <Documents />
              </RequireRole>
            }
          />
          <Route
            path="evaluation"
            element={
              <RequireRole roles={["administrator"]}>
                <Evaluation />
              </RequireRole>
            }
          />
          <Route
            path="audit"
            element={
              <RequireRole roles={["administrator"]}>
                <Audit />
              </RequireRole>
            }
          />
          <Route path="config" element={<AgentConfig />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </IdentityProvider>
  );
}

/**
 * Distinguishes an expired session from an unreachable backend by asking the
 * one endpoint that needs no token: `/api/health`.
 */
function IdentityFailure({ error, onRestart }: { error: unknown; onRestart: () => void }) {
  const [reachable, setReachable] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/health")
      .then((r) => r.ok)
      .catch(() => false)
      .then((ok) => {
        if (!cancelled) setReachable(ok);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (reachable === false) {
    return (
      <div className="state state--error" role="alert">
        <div className="state__title">FlowForge is not reachable</div>
        <p className="state__body">
          The backend did not answer <code>/api/health</code>. If you are running this locally,
          check that the <code>backend</code> container is up.
        </p>
        <button type="button" className="btn" onClick={() => window.location.reload()}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <>
      <ErrorState error={error ?? new Error("Could not load your identity")} />
      <div style={{ textAlign: "center", paddingBottom: "var(--sp-8)" }}>
        <button type="button" className="btn btn--primary" onClick={onRestart}>
          Back to sign in
        </button>
      </div>
    </>
  );
}

function NotFound() {
  const navigate = useNavigate();
  return (
    <div className="state">
      <div className="state__title">Page not found</div>
      <p className="state__body">That route does not exist in FlowForge.</p>
      <button type="button" className="btn btn--primary" onClick={() => navigate("/")}>
        Back to dashboard
      </button>
    </div>
  );
}
