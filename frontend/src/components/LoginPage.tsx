import { useEffect, useRef, useState } from "react";
import { Flame } from "lucide-react";
import type { AppSession } from "../types/api";

type LoginPageProps = {
  onSuccess: (session: AppSession) => void;
};

// Site key (publik) widget Cloudflare Turnstile. Kalau kosong (mis. dev lokal
// atau produksi yang belum memasang key), widget tidak dirender dan tombol
// "Masuk" tidak diblok -- backend juga melewati verifikasi captcha saat
// TURNSTILE_SECRET_KEY kosong (fail-open, lihat backend config.py).
const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY?.trim() ?? "";

// Gerbang login untuk seluruh aplikasi -- terpisah dari PasswordGateModal
// (yang menjaga aksi admin di menu Pengaturan). Password diverifikasi ke
// backend (POST /api/auth/login), bukan dicocokkan ke string di sini.
// Sejak Manajemen User ada, akun bisa lebih dari satu (role admin/user) --
// backend yang memutuskan kredensial mana yang sah, respons-nya membawa
// token + role balik ke sini.
export function LoginPage({ onSuccess }: LoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);

  const captchaRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);

  // Render widget Turnstile secara eksplisit begitu script-nya siap. Script
  // dimuat async/defer di index.html, jadi window.turnstile bisa belum ada
  // saat komponen mount -- poll sebentar sampai tersedia.
  useEffect(() => {
    if (!TURNSTILE_SITE_KEY || !captchaRef.current) return;

    let cancelled = false;
    const mount = () => {
      if (cancelled || !captchaRef.current || !window.turnstile) return;
      if (widgetIdRef.current !== null) return;
      widgetIdRef.current = window.turnstile.render(captchaRef.current, {
        sitekey: TURNSTILE_SITE_KEY,
        theme: "dark",
        callback: (token) => {
          setCaptchaToken(token);
          setError(null);
        },
        "expired-callback": () => setCaptchaToken(null),
        "error-callback": () => setCaptchaToken(null),
      });
    };

    mount();
    const timer = window.setInterval(mount, 200);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      if (widgetIdRef.current !== null) {
        window.turnstile?.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
    };
  }, []);

  const resetCaptcha = () => {
    setCaptchaToken(null);
    if (widgetIdRef.current !== null) {
      window.turnstile?.reset(widgetIdRef.current);
    }
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setVerifying(true);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, turnstile_token: captchaToken })
      });
      if (response.ok) {
        const data = await response.json();
        onSuccess({ token: data.token, username: data.username, role: data.role });
        return;
      }
      // Token Turnstile sekali pakai -- apa pun hasil submit yang tidak
      // sukses, minta widget menerbitkan token baru untuk percobaan berikut.
      resetCaptcha();
      if (response.status === 503) {
        setError("Login belum dikonfigurasi di server.");
      } else if (response.status === 400) {
        setError("Verifikasi manusia gagal. Ulangi centang di bawah.");
      } else {
        setError("Username atau password salah.");
      }
    } catch {
      resetCaptcha();
      setError("Gagal menghubungi server. Coba lagi.");
    } finally {
      setVerifying(false);
    }
  };

  const captchaPending = Boolean(TURNSTILE_SITE_KEY) && !captchaToken;

  return (
    <div className="login-page">
      <form className="login-card panel" onSubmit={handleSubmit}>
        <div className="login-brand">
          <span className="login-brand-icon">
            <Flame size={22} />
          </span>
          <div>
            <p className="login-brand-title">ETA SENEU</p>
            <p className="login-brand-subtitle">KPS Hotspot Monitoring</p>
          </div>
        </div>

        <label className="login-field">
          <span>Username</span>
          <input
            type="text"
            autoFocus
            autoComplete="username"
            value={username}
            disabled={verifying}
            onChange={(event) => setUsername(event.currentTarget.value)}
            className="login-input"
          />
        </label>

        <label className="login-field">
          <span>Password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            disabled={verifying}
            onChange={(event) => setPassword(event.currentTarget.value)}
            className="login-input"
          />
        </label>

        {TURNSTILE_SITE_KEY ? (
          <div className="login-turnstile" ref={captchaRef} />
        ) : null}

        {error ? <p className="login-error">{error}</p> : null}

        <button
          type="submit"
          className="login-submit"
          disabled={verifying || captchaPending}
        >
          {verifying ? "Memverifikasi..." : "Masuk"}
        </button>
      </form>
    </div>
  );
}
