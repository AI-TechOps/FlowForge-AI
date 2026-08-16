/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Absent means the local dev issuer is in use. See src/auth.ts.
  readonly VITE_AUTH0_DOMAIN?: string;
  readonly VITE_AUTH0_CLIENT_ID?: string;
  readonly VITE_AUTH0_AUDIENCE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
