import { useEffect, useState } from "react";
import type { AppUser, UserRole } from "../types/api";

type UserManagementPanelProps = {
  token: string;
  currentUsername: string;
};

// Gaya inline (bukan class CSS) sengaja mengikuti konvensi file
// SettingsPanel.tsx tempat panel ini dipasang -- lihat kartu-kartu lain di
// file itu (upload GeoJSON, daftar layer) yang juga begitu.
const cardStyle: React.CSSProperties = {
  background: "rgba(17, 24, 39, 0.5)",
  border: "1px solid rgba(255, 255, 255, 0.08)",
  borderRadius: "12px",
  padding: "2rem"
};

const inputStyle: React.CSSProperties = {
  background: "rgba(255, 255, 255, 0.04)",
  border: "1px solid rgba(255, 255, 255, 0.15)",
  color: "#fff",
  padding: "0.5rem 0.7rem",
  borderRadius: "6px",
  fontSize: "0.82rem"
};

const ghostButtonStyle: React.CSSProperties = {
  background: "transparent",
  border: "1px solid rgba(255, 255, 255, 0.15)",
  color: "#d1d5db",
  padding: "0.4rem 0.7rem",
  borderRadius: "6px",
  fontSize: "0.75rem",
  cursor: "pointer"
};

const dangerButtonStyle: React.CSSProperties = {
  ...ghostButtonStyle,
  border: "1px solid rgba(239,68,68,0.35)",
  color: "#fca5a5"
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

  return (
    <div style={cardStyle}>
      <h2 style={{ fontSize: "1.25rem", color: "#fff", fontWeight: 600, margin: "0 0 0.4rem" }}>
        Manajemen User
      </h2>
      <p style={{ color: "#9ca3af", fontSize: "0.8rem", margin: "0 0 1.5rem" }}>
        Tambah akun, ubah role, atau ganti password. Khusus role admin.
      </p>

      {error ? (
        <p style={{ color: "#fca5a5", fontSize: "0.8rem", marginBottom: "1rem" }}>{error}</p>
      ) : null}

      <form
        onSubmit={handleCreate}
        style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem", alignItems: "center", marginBottom: "1.5rem" }}
      >
        <input
          type="text"
          placeholder="Username"
          value={newUsername}
          onChange={(event) => setNewUsername(event.currentTarget.value)}
          required
          style={{ ...inputStyle, flex: "1 1 140px" }}
        />
        <input
          type="password"
          placeholder="Password (min. 6 karakter)"
          value={newPassword}
          onChange={(event) => setNewPassword(event.currentTarget.value)}
          required
          minLength={6}
          style={{ ...inputStyle, flex: "1 1 180px" }}
        />
        <select
          value={newRole}
          onChange={(event) => setNewRole(event.currentTarget.value as UserRole)}
          style={inputStyle}
        >
          <option value="user">User</option>
          <option value="admin">Admin</option>
        </select>
        <button
          type="submit"
          disabled={creating}
          style={{
            background: "#ff4e00",
            border: "1px solid #ff4e00",
            color: "#0b0c10",
            padding: "0.5rem 1rem",
            borderRadius: "6px",
            fontSize: "0.8rem",
            fontWeight: 700,
            cursor: creating ? "progress" : "pointer"
          }}
        >
          {creating ? "Menambah..." : "+ Tambah User"}
        </button>
      </form>

      {loading ? (
        <p style={{ color: "#6b7280", fontSize: "0.85rem" }}>Memuat daftar user...</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
          {users.map((user) => {
            const isSelf = user.username === currentUsername;
            const isBusy = busyId === user.id;
            return (
              <div
                key={user.id}
                style={{
                  background: "rgba(255, 255, 255, 0.02)",
                  border: "1px solid rgba(255, 255, 255, 0.05)",
                  borderRadius: "8px",
                  padding: "0.85rem 1rem",
                  display: "flex",
                  flexWrap: "wrap",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: "0.6rem"
                }}
              >
                <div>
                  <strong style={{ color: "#fff", fontSize: "0.9rem" }}>{user.username}</strong>
                  {isSelf ? (
                    <span style={{ color: "#6b7280", fontSize: "0.72rem", marginLeft: "0.4rem" }}>(kamu)</span>
                  ) : null}
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
                  <select
                    value={user.role}
                    disabled={isBusy}
                    onChange={(event) => handleRoleChange(user, event.currentTarget.value as UserRole)}
                    style={inputStyle}
                  >
                    <option value="user">User</option>
                    <option value="admin">Admin</option>
                  </select>

                  {passwordEditId === user.id ? (
                    <>
                      <input
                        type="password"
                        placeholder="Password baru"
                        value={passwordDraft}
                        onChange={(event) => setPasswordDraft(event.currentTarget.value)}
                        style={inputStyle}
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

                  {confirmDeleteId === user.id ? (
                    <>
                      <button
                        type="button"
                        disabled={isBusy}
                        onClick={() => handleDelete(user)}
                        style={{ ...dangerButtonStyle, background: "#ef4444", color: "#fff" }}
                      >
                        {isBusy ? "Menghapus..." : "Yakin, Hapus"}
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
                      style={{ ...dangerButtonStyle, opacity: isSelf ? 0.4 : 1, cursor: isSelf ? "not-allowed" : "pointer" }}
                    >
                      Hapus
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
