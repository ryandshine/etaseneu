/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Site key (publik) widget Cloudflare Turnstile di halaman login.
   *  Kosong / tak diset = widget tidak dirender, login jalan seperti biasa. */
  readonly VITE_TURNSTILE_SITE_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** API global yang disuntik script https://challenges.cloudflare.com/turnstile/v0/api.js */
interface TurnstileApi {
  render: (
    container: HTMLElement | string,
    options: {
      sitekey: string;
      callback?: (token: string) => void;
      "expired-callback"?: () => void;
      "error-callback"?: () => void;
      theme?: "auto" | "light" | "dark";
      size?: "normal" | "flexible" | "compact";
    }
  ) => string;
  reset: (widgetId?: string) => void;
  remove: (widgetId?: string) => void;
}

interface Window {
  turnstile?: TurnstileApi;
  onloadTurnstileCallback?: () => void;
}
