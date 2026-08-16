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
    // The token did not verify. Drop it and show the door again rather than
    // leaving every screen to fail with its own 401.
    return (
      <>
        <ErrorState error={identity.error ?? new Error("Could not load your identity")} />
        <div style={{ textAlign: "center", paddingBottom: "var(--sp-8)" }}>
          <button type="button" className="btn btn--primary" onClick={() => setToken(null)}>
            Back to sign in
          </button>
        </div>
      </>
    );
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
