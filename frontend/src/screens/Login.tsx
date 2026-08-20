/**
 * MVP step 1 — "Admin logs in".
 *
 * Phase 4 already made this real against both providers; Phase 6 moves it into
 * the design system and adds what a demo needs: the seeded identities are
 * labelled with the roles they hold, so the person watching can see *why*
 * signing in as operator@demo produces a different application than
 * approver@demo. That is the segregation-of-duties story, told at the door.
 */

import { useState } from "react";

import { authConfig, loginAuth0, loginLocal } from "../auth";
import { Icon } from "../components/ui";
import { TID, testid } from "../testids";

/**
 * Roles as `scripts/seed.py` grants them. Presentation only — the token's
 * roles come from `user_roles` on every request (D18), never from this list.
 */
const SEEDED: { email: string; roles: string; blurb: string }[] = [
  { email: "admin@demo", roles: "administrator", blurb: "Uploads docs, reviews eval, sees spend" },
  { email: "operator@demo", roles: "operator", blurb: "Files tickets and starts triage" },
  { email: "approver@demo", roles: "approver", blurb: "The human gate on every write" },
  { email: "demo@demo", roles: "all three", blurb: "Convenience identity for a solo walkthrough" },
];

export function Login({ onToken }: { onToken: (token: string) => void }) {
  const config = authConfig();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const signIn = async (email: string) => {
    setBusy(email);
    setError(null);
    try {
      if (config.provider === "auth0") {
        await loginAuth0(config);
        return; // redirects away
      }
      onToken(await loginLocal(email));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="login">
      <div className="login__card" {...testid(TID.loginCard)}>
        <div className="login__brand">
          <span className="sidebar__mark">FF</span>
          FlowForge
        </div>
        <p className="muted" style={{ fontSize: "var(--fs-md)" }}>
          AI triage for internal support, with a human on every write.
        </p>

        {config.provider === "auth0" ? (
          <div className="login__identities">
            <button
              type="button"
              className="btn btn--primary"
              style={{ height: 38 }}
              onClick={() => void signIn("")}
              disabled={busy !== null}
              {...testid(TID.loginAuth0)}
            >
              {Icon.external({ size: 14 })}
              Continue with Auth0
            </button>
          </div>
        ) : (
          <>
            <div className="sidebar__section" style={{ padding: "var(--sp-5) 0 var(--sp-1)" }}>
              Local dev issuer
            </div>
            <div className="login__identities">
              {SEEDED.map((user) => (
                <button
                  key={user.email}
                  type="button"
                  className="identity-btn"
                  onClick={() => void signIn(user.email)}
                  disabled={busy !== null}
                  {...testid(TID.loginIdentity(user.email))}
                >
                  <span className="identity-btn__avatar">{user.email[0]?.toUpperCase()}</span>
                  <span style={{ minWidth: 0 }}>
                    <span className="identity-btn__email">{user.email}</span>
                    <span className="identity-btn__roles" style={{ display: "block" }}>
                      {busy === user.email ? "Signing in…" : `${user.roles} — ${user.blurb}`}
                    </span>
                  </span>
                </button>
              ))}
            </div>
            <p className="faint" style={{ fontSize: "var(--fs-xs)", marginTop: "var(--sp-4)" }}>
              A real deployment redirects to Auth0 instead. Roles are read from the database on
              every request, so this picker chooses an identity — never a permission.
            </p>
          </>
        )}

        {error && (
          <div
            className="banner banner--err"
            style={{ marginTop: "var(--sp-4)" }}
            role="alert"
            {...testid(TID.loginError)}
          >
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
