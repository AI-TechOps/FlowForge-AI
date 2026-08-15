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
 * The verifier is held in sessionStorage only until the code is exchanged.
 *
 * Phase 4 scope: enough to make "Admin logs in" real (MVP step 1). The screens
 * are Phase 6, and this is deliberately not the beginning of one.
 */

const TOKEN_KEY = "flowforge.access_token";
const VERIFIER_KEY = "flowforge.pkce_verifier";

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

/** Dev issuer: one round trip, no redirect. */
export async function loginLocal(email: string): Promise<string> {
  const response = await fetch("/api/dev/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!response.ok) throw new Error(`local login failed (${response.status})`);
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
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  const parameters = new URLSearchParams({
    response_type: "code",
    client_id: config.client_id ?? "",
    redirect_uri: `${window.location.origin}/callback`,
    scope: "openid profile email",
    audience: config.audience ?? "",
    code_challenge: await challengeFor(verifier),
    code_challenge_method: "S256",
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
  const code = new URLSearchParams(window.location.search).get("code");
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  if (!code || !verifier) throw new Error("no login in progress");

  try {
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
    window.history.replaceState({}, "", window.location.pathname);
  }
}
