/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_AUTH_IDLE_TIMEOUT_MINUTES?: string;
  readonly VITE_AUTH_IDLE_WARNING_SECONDS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
