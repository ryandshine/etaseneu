import { useEffect, useState } from "react";

type PasswordGateModalProps = {
  open: boolean;
  error: string | null;
  verifying?: boolean;
  onSubmit: (password: string) => void;
  onCancel: () => void;
};

// Pengganti window.prompt()/alert() bawaan browser. Password yang diketik
// diverifikasi ke backend (POST /api/auth/verify), bukan dicocokkan ke
// string hardcoded di sini -- lihat App.tsx.
export function PasswordGateModal({ open, error, verifying, onSubmit, onCancel }: PasswordGateModalProps) {
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (open) {
      setPassword("");
    }
  }, [open]);

  if (!open) {
    return null;
  }

  return (
    <div className="password-gate-overlay" role="presentation" onClick={onCancel}>
      <form
        className="password-gate-card panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="password-gate-title"
        onClick={(event) => event.stopPropagation()}
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit(password);
        }}
      >
        <p id="password-gate-title" className="password-gate-title">
          Masukkan password untuk mengakses Pengaturan
        </p>
        <input
          type="password"
          autoFocus
          value={password}
          disabled={verifying}
          onChange={(event) => setPassword(event.currentTarget.value)}
          className="password-gate-input"
          aria-label="Password"
        />
        {error ? <p className="password-gate-error">{error}</p> : null}
        <div className="password-gate-actions">
          <button type="button" className="password-gate-cancel" onClick={onCancel} disabled={verifying}>
            Batal
          </button>
          <button type="submit" className="password-gate-confirm" disabled={verifying}>
            {verifying ? "Memverifikasi..." : "Lanjut"}
          </button>
        </div>
      </form>
    </div>
  );
}
