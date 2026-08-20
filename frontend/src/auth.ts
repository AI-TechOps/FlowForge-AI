/**
 * Login, two ways, behind one interface.
 *
 * The backend runs either the local dev issuer or a real Auth0 tenant (D18
 * decision 1), and the frontend has to work against both. Which one is
 * selected by build-time configuration: VITE_AUTH0_DOMAIN present means Auth0,
 * absent means the dev issuer.
 *
 * A `GET /api/auth/config` endpoint would read better — the frontend could not
 * then disagree with the server — but it would have to be readable before a
 * token exists, making it a second unauthenticated route and forcing a G4.1
 * exemption. D18 decision 5 rejected exemption lists; adding one in the same
 * phase for our own convenience is not the trade to make. If the two do
 * disagree, the dev-issuer path surfaces it immediately as a 404 with a
 * message saying so.
 *
 * The Auth0 path is Authorization Code + PKCE with no client secret — the
 * correct flow for a SPA, where any "secret" shipped to the browser is not one.
 * The verifier and the `state` nonce are held in sessionStorage only until the
 * code is exchanged.
 *
 * PKCE and `state` solve different problems and both are required. PKCE stops
 * a stolen authorization code being redeemed by anyone but us; `state` stops
 * an attacker's code being redeemed *by* us, which is how login CSRF works —
 * the victim ends up signed into the attacker's account. Auth0's SDK would
 * handle this; implementing the flow by hand means implementing both halves.
 *
 * Phase 4 scope: enough to make "Admin logs in" real (MVP step 1). The screens
 * are Phase 6, and this is deliberately not the beginning of one.
 */

const TOKEN_KEY = "flowforge.access_token";
const VERIFIER_KEY = "flowforge.pkce_verifier";
const STATE_KEY = "flowforge.oauth_state";

export interface AuthConfig {
  provider: "auth0" | "local";
  domain?: string | null;
  client_id?: string | null;
  audience?: string | null;
}

export interface Identity {
  id: string;
  org_id: string;
  email: string;
  roles: string[];
}

export function storedToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

// sessionStorage, not localStorage: the token dies with the tab. Neither is
// proof against XSS — an httpOnly cookie would be — but a token that outlives
// the browsing session on a shared machine is the easier mistake to avoid.
function storeToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export function authConfig(): AuthConfig {
  const domain = import.meta.env.VITE_AUTH0_DOMAIN;
  if (!domain) return { provider: "local" };
  return {
    provider: "auth0",
    domain,
    client_id: import.meta.env.VITE_AUTH0_CLIENT_ID,
    audience: import.meta.env.VITE_AUTH0_AUDIENCE,
  };
}

export async function fetchIdentity(token: string): Promise<Identity> {
  const response = await fetch("/api/me", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (response.status === 401) throw new Error("session expired");
  if (response.status === 403) throw new Error("no FlowForge account for this identity");
  if (!response.ok) throw new Error(`/api/me failed (${response.status})`);
  return response.json();
}

/**
 * Dev issuer: one round trip, no redirect.
 *
 * The failure messages are written for whoever is looking at the screen, which
 * during a demo is not necessarily the person who built this. A bare
 * "login failed (502)" says nothing actionable; "the backend is not reachable"
 * says which of the four containers to look at.
 */
export async function loginLocal(email: string): Promise<string> {
  let response: Response;
  try {
    response = await fetch("/api/dev/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
  } catch {
    // fetch only rejects when the request never completed at all.
    throw new Error("Cannot reach FlowForge. Is the stack running?");
  }

  if (response.status === 404) {
    // The dev issuer 404s under Auth0 or in prod, by design (D18).
    throw new Error(
      "The local dev issuer is not enabled on this backend — it is configured for Auth0.",
    );
  }
  if (response.status === 502 || response.status === 503 || response.status === 504) {
    throw new Error(`The backend is not responding (${response.status}). Check the API container.`);
  }
  if (!response.ok) {
    let detail = "";
    try {
      detail = ((await response.json()) as { detail?: string }).detail ?? "";
    } catch {
      /* not JSON; the status is all we have */
    }
    throw new Error(detail || `Sign-in failed (${response.status}).`);
  }

  const { access_token } = await response.json();
  storeToken(access_token);
  return access_token;
}

function randomVerifier(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return base64Url(bytes);
}

function base64Url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

/** Auth0: redirect to the hosted login page. */
export async function loginAuth0(config: AuthConfig): Promise<void> {
  const verifier = randomVerifier();
  const state = randomVerifier();
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);
  const parameters = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id ?? "",
    redirect_uri: `${window.location.origin}/callback`,
    // `email` is requested so the backend can resolve the identity at first
    // login. The access token for a custom API does not carry it, so the
    // backend asks /userinfo — which requires exactly these scopes.
    scope: "openid profile email",
    audience: config.audience ?? "",
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
    state: state,
  });
  window.location.assign(`https://${config.domain}/authorize?${parameters}`);
}

/**
 * Exchange the authorization code for a token, then clean the URL.
 *
 * The code is single-use and ends up in browser history, so the verifier is
 * dropped and the query string replaced whether or not the exchange succeeded.
 */
export async function completeAuth0Login(config: AuthConfig): Promise<string> {
  const query = new URLSearchParams(window.location.search);
  const code = query.get("code");
  const returnedState = query.get("state");
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  const expectedState = sessionStorage.getItem(STATE_KEY);

  try {
    if (!code || !verifier || !expectedState) throw new Error("no login in progress");
    // Compared before the code is redeemed, not after. A callback we did not
    // initiate must never reach the token endpoint.
    if (returnedState !== expectedState) {
      throw new Error("login state mismatch — this callback did not come from a login we started");
    }
    const response = await fetch(`https://${config.domain}/oauth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        grant_type: "authorization_code",
        client_id: config.client_id,
        code_verifier: verifier,
        code,
        redirect_uri: `${window.location.origin}/callback`,
      }),
    });
    if (!response.ok) throw new Error(`token exchange failed (${response.status})`);
    const { access_token } = await response.json();
    storeToken(access_token);
    return access_token;
  } finally {
    sessionStorage.removeItem(VERIFIER_KEY);
    sessionStorage.removeItem(STATE_KEY);
    window.history.replaceState({}, "", window.location.pathname);
  }
}
