import { useState } from "react";
import { Flame } from "lucide-react";
import type { AppSession } from "../types/api";

type LoginPageProps = {
  onSuccess: (session: AppSession) => void;
};

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

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setVerifying(true);
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password })
      });
      if (response.ok) {
        const data = await response.json();
        onSuccess({ token: data.token, username: data.username, role: data.role });
        return;
      }
      setError(
        response.status === 503
          ? "Login belum dikonfigurasi di server."
          : "Username atau password salah."
      );
    } catch {
      setError("Gagal menghubungi server. Coba lagi.");
    } finally {
      setVerifying(false);
    }
  };

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

        {error ? <p className="login-error">{error}</p> : null}

        <button type="submit" className="login-submit" disabled={verifying}>
          {verifying ? "Memverifikasi..." : "Masuk"}
        </button>
      </form>
    </div>
  );
}
