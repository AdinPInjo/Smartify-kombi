/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
}

/** The dashboard's version, from package.json. */
declare const __APP_VERSION__: string;
