import { useEffect, useState } from "react";
import type { AppUser, UserRole } from "../types/api";
import { formatDateTimeWIB } from "../lib/date";

type UserManagementPanelProps = {
  token: string;
  currentUsername: string;
};

// Gaya inline (bukan class CSS) sengaja mengikuti konvensi file
// SettingsPanel.tsx tempat panel ini dipasang -- lihat kartu-kartu lain di
// file itu (upload GeoJSON, daftar layer) yang juga begitu. Class ".field"
// dipakai untuk form supaya label-nya konsisten dengan FilterPanel.tsx
// (label terlihat, bukan cuma placeholder -- lihat index.css).
const cardStyle: React.CSSProperties = {
  background: "rgba(17, 24, 39, 0.5)",
  border: "1px solid rgba(255, 255, 255, 0.08)",
  borderRadius: "12px",
  padding: "2rem",
  // Grid item di SettingsPanel (display:grid, gridTemplateColumns:"1fr")
  // defaultnya min-width:auto -- menolak menyusut di bawah min-content
  // tabelnya sendiri, jadi di layar sempit kartu ini melebar ke kanan dan
  // terpotong diam-diam oleh .workspace-stage{overflow:hidden} (bukan
  // scrollbar horizontal). Pola bug + fix yang sama persis sudah
  // didokumentasikan untuk .matrix-ledger di index.css.
  minWidth: 0
};

// Dipakai untuk input password inline (mini-form "Ganti Password" per baris)
// yang tidak dibungkus <label className="field"> -- disamakan ukurannya
// dengan .filter-select-input/.field input (40px, 0.72rem) di index.css
// supaya tetap konsisten walau tidak lewat class yang sama.
const inlineInputStyle: React.CSSProperties = {
  background: "rgba(255, 255, 255, 0.03)",
  border: "1px solid rgba(255, 255, 255, 0.12)",
  color: "#fff",
  padding: "0.5rem 0.6rem",
  borderRadius: "6px",
  fontSize: "0.72rem",
  height: "40px",
  width: "140px"
};

const ghostButtonStyle: React.CSSProperties = {
  background: "transparent",
  border: "1px solid rgba(255, 255, 255, 0.15)",
  color: "#d1d5db",
  padding: "0.4rem 0.7rem",
  borderRadius: "6px",
  fontSize: "0.75rem",
  cursor: "pointer",
  whiteSpace: "nowrap"
};

const dangerButtonStyle: React.CSSProperties = {
  ...ghostButtonStyle,
  border: "1px solid rgba(239,68,68,0.35)",
  color: "#fca5a5"
};

const roleDotColor: Record<UserRole, string> = {
  admin: "#f97316",
  user: "#6b7280"
};

export function UserManagementPanel({ token, currentUsername }: UserManagementPanelProps) {
  const [users, setUsers] = useState<AppUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<UserRole>("user");
  const [creating, setCreating] = useState(false);

  const [passwordEditId, setPasswordEditId] = useState<number | null>(null);
  const [passwordDraft, setPasswordDraft] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [confirmRevokeId, setConfirmRevokeId] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const authHeaders = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json"
  };

  const fetchUsers = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/auth/users", { headers: authHeaders });
      if (!response.ok) {
        throw new Error("Gagal memuat daftar user.");
      }
      setUsers(await response.json());
    } catch {
      setError("Gagal memuat daftar user.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setCreating(true);
    try {
      const response = await fetch("/api/auth/users", {
        method: "POST",
        headers: authHeaders,
        body: JSON.stringify({ username: newUsername, password: newPassword, role: newRole })
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || "Gagal menambah user.");
      }
      setNewUsername("");
      setNewPassword("");
      setNewRole("user");
      await fetchUsers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal menambah user.");
    } finally {
      setCreating(false);
    }
  };

  const handleRoleChange = async (user: AppUser, role: UserRole) => {
    setBusyId(user.id);
    setError(null);
    try {
      const response = await fetch(`/api/auth/users/${user.id}`, {
        method: "PATCH",
        headers: authHeaders,
        body: JSON.stringify({ role })
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || "Gagal mengubah role.");
      }
      await fetchUsers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal mengubah role.");
    } finally {
      setBusyId(null);
    }
  };

  const handlePasswordSave = async (user: AppUser) => {
    if (passwordDraft.length < 6) {
      setError("Password minimal 6 karakter.");
      return;
    }
    setBusyId(user.id);
    setError(null);
    try {
      const response = await fetch(`/api/auth/users/${user.id}`, {
        method: "PATCH",
        headers: authHeaders,
        body: JSON.stringify({ password: passwordDraft })
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || "Gagal mengganti password.");
      }
      setPasswordEditId(null);
      setPasswordDraft("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal mengganti password.");
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (user: AppUser) => {
    setBusyId(user.id);
    setError(null);
    try {
      const response = await fetch(`/api/auth/users/${user.id}`, {
        method: "DELETE",
        headers: authHeaders
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || "Gagal menghapus user.");
      }
      setConfirmDeleteId(null);
      await fetchUsers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal menghapus user.");
    } finally {
      setBusyId(null);
    }
  };

  const handleRevokeSessions = async (user: AppUser) => {
    setBusyId(user.id);
    setError(null);
    try {
      const response = await fetch(`/api/auth/users/${user.id}/sessions/revoke`, {
        method: "POST",
        headers: authHeaders
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || "Gagal mencabut sesi.");
      }
      setConfirmRevokeId(null);
      await fetchUsers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal mencabut sesi.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div style={cardStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.75rem", flexWrap: "wrap", gap: "0.5rem" }}>
        <div>
          <h2 style={{ fontSize: "1.25rem", color: "#fff", fontWeight: 600, margin: "0 0 0.35rem" }}>
            Manajemen User
          </h2>
          <p style={{ color: "#9ca3af", fontSize: "0.8rem", margin: 0 }}>
            Tambah akun, ubah role, ganti password, dan cabut sesi perangkat. Khusus role admin.
          </p>
        </div>
        <span style={{ color: "#6b7280", fontSize: "0.72rem", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "999px", padding: "0.3rem 0.7rem", whiteSpace: "nowrap" }}>
          {users.length} akun terdaftar
        </span>
      </div>

      {error ? (
        <p role="alert" style={{ color: "#fca5a5", fontSize: "0.8rem", marginBottom: "1.25rem", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: "6px", padding: "0.6rem 0.8rem" }}>
          {error}
        </p>
      ) : null}

      <form onSubmit={handleCreate} style={{ marginBottom: "2rem", paddingBottom: "1.75rem", borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
        <p style={{ color: "#e5e7eb", fontSize: "0.8rem", fontWeight: 600, margin: "0 0 0.85rem", letterSpacing: "0.02em" }}>
          Tambah User Baru
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "0.75rem", alignItems: "end" }}>
          <label className="field">
            <span>Username</span>
            <input
              type="text"
              value={newUsername}
              onChange={(event) => setNewUsername(event.currentTarget.value)}
              required
            />
          </label>
          <label className="field">
            <span>Password (min. 6 karakter)</span>
            <input
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.currentTarget.value)}
              required
              minLength={6}
            />
          </label>
          <label className="field">
            <span>Role</span>
            <select
              value={newRole}
              onChange={(event) => setNewRole(event.currentTarget.value as UserRole)}
              className="filter-select-input"
            >
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
          </label>
          <button
            type="submit"
            disabled={creating}
            style={{
              background: "#ff4e00",
              border: "1px solid #ff4e00",
              color: "#0b0c10",
              padding: "0.6rem 1.1rem",
              borderRadius: "6px",
              fontSize: "0.8rem",
              fontWeight: 700,
              cursor: creating ? "progress" : "pointer",
              whiteSpace: "nowrap"
            }}
          >
            {creating ? "Menambah..." : "+ Tambah"}
          </button>
        </div>
      </form>

      {loading ? (
        <p style={{ color: "#6b7280", fontSize: "0.85rem" }}>Memuat daftar user...</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
            <thead>
              <tr>
                {["Username", "Role", "Sesi aktif", "Dibuat", "Aksi"].map((heading, i) => (
                  <th
                    key={heading}
                    style={{
                      textAlign: i === 4 ? "right" : "left",
                      color: "#6b7280",
                      fontSize: "0.7rem",
                      fontWeight: 600,
                      letterSpacing: "0.05em",
                      textTransform: "uppercase",
                      padding: "0 0 0.6rem",
                      borderBottom: "1px solid rgba(255,255,255,0.08)"
                    }}
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const isSelf = user.username === currentUsername;
                const isBusy = busyId === user.id;
                return (
                  <tr key={user.id} style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                    <td style={{ padding: "0.85rem 0.5rem 0.85rem 0", verticalAlign: "middle" }}>
                      <strong style={{ color: "#fff", fontSize: "0.9rem" }}>{user.username}</strong>
                      {isSelf ? (
                        <span style={{ color: "#6b7280", fontSize: "0.72rem", marginLeft: "0.4rem" }}>(kamu)</span>
                      ) : null}
                    </td>
                    <td style={{ padding: "0.85rem 0.5rem", verticalAlign: "middle" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                        <span
                          aria-hidden="true"
                          style={{ width: "6px", height: "6px", borderRadius: "50%", backgroundColor: roleDotColor[user.role], flexShrink: 0 }}
                        />
                        <select
                          aria-label={`Role untuk ${user.username}`}
                          value={user.role}
                          disabled={isBusy}
                          onChange={(event) => handleRoleChange(user, event.currentTarget.value as UserRole)}
                          className="filter-select-input"
                          style={{ width: "auto" }}
                        >
                          <option value="user">User</option>
                          <option value="admin">Admin</option>
                        </select>
                      </div>
                    </td>
                    <td style={{ padding: "0.85rem 0.5rem", verticalAlign: "middle", color: (user.active_sessions ?? 0) > 0 ? "#86efac" : "#6b7280", fontSize: "0.78rem", whiteSpace: "nowrap" }}>
                      {user.active_sessions ?? 0}
                    </td>
                    <td style={{ padding: "0.85rem 0.5rem", verticalAlign: "middle", color: "#9ca3af", fontSize: "0.78rem", whiteSpace: "nowrap" }}>
                      {formatDateTimeWIB(user.created_at)}
                    </td>
                    <td style={{ padding: "0.85rem 0 0.85rem 0.5rem", verticalAlign: "middle" }}>
                      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                        {passwordEditId === user.id ? (
                          <>
                            <input
                              type="password"
                              aria-label={`Password baru untuk ${user.username}`}
                              placeholder="Password baru"
                              value={passwordDraft}
                              onChange={(event) => setPasswordDraft(event.currentTarget.value)}
                              style={inlineInputStyle}
                              autoFocus
                            />
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => handlePasswordSave(user)}
                              style={{ ...ghostButtonStyle, borderColor: "rgba(16,185,129,0.4)", color: "#6ee7b7" }}
                            >
                              Simpan
                            </button>
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => {
                                setPasswordEditId(null);
                                setPasswordDraft("");
                              }}
                              style={ghostButtonStyle}
                            >
                              Batal
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            onClick={() => {
                              setPasswordEditId(user.id);
                              setPasswordDraft("");
                            }}
                            style={ghostButtonStyle}
                          >
                            Ganti Password
                          </button>
                        )}

                        {confirmRevokeId === user.id ? (
                          <>
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => void handleRevokeSessions(user)}
                              style={{ ...dangerButtonStyle, background: "rgba(239,68,68,0.2)" }}
                            >
                              {isBusy ? "Mencabut..." : "Yakin?"}
                            </button>
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => setConfirmRevokeId(null)}
                              style={ghostButtonStyle}
                            >
                              Batal
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            disabled={(user.active_sessions ?? 0) <= (isSelf ? 1 : 0) || isBusy}
                            title={isSelf ? "Cabut sesi lain, sesi ini dipertahankan" : `Revoke semua sesi ${user.username}`}
                            onClick={() => setConfirmRevokeId(user.id)}
                            style={{ ...dangerButtonStyle, opacity: (user.active_sessions ?? 0) <= (isSelf ? 1 : 0) ? 0.35 : 1, cursor: (user.active_sessions ?? 0) <= (isSelf ? 1 : 0) ? "not-allowed" : "pointer" }}
                          >
                            {isSelf ? "Revoke sesi lain" : "Revoke sesi"}
                          </button>
                        )}

                        {confirmDeleteId === user.id ? (
                          <>
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => handleDelete(user)}
                              style={{ ...dangerButtonStyle, background: "#ef4444", color: "#fff" }}
                            >
                              {isBusy ? "Menghapus..." : "Yakin?"}
                            </button>
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => setConfirmDeleteId(null)}
                              style={ghostButtonStyle}
                            >
                              Batal
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            disabled={isSelf}
                            title={isSelf ? "Tidak bisa menghapus akun sendiri" : `Hapus ${user.username}`}
                            onClick={() => setConfirmDeleteId(user.id)}
                            style={{ ...dangerButtonStyle, opacity: isSelf ? 0.35 : 1, cursor: isSelf ? "not-allowed" : "pointer" }}
                          >
                            Hapus
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
