import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  label?: string;
};

type State = {
  error: Error | null;
};

// Class component karena React belum punya padanan fungsional untuk error
// boundary. Tanpa ini, error render di mana pun pada tree (mis. satu chart
// di Matriks Data) menjatuhkan SELURUH aplikasi jadi layar putih kosong --
// pengguna cuma lihat "[blank]" tanpa petunjuk apa pun terjadi di mana.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[ErrorBoundary${this.props.label ? ` ${this.props.label}` : ""}]`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          role="alert"
          style={{
            margin: "2rem auto",
            maxWidth: "560px",
            padding: "1.5rem 1.75rem",
            borderRadius: "12px",
            border: "1px solid rgba(239,68,68,0.35)",
            background: "rgba(239,68,68,0.06)",
            color: "#fff",
          }}
        >
          <strong style={{ display: "block", marginBottom: "0.4rem", color: "#fca5a5" }}>
            Terjadi kesalahan saat menampilkan{this.props.label ? ` ${this.props.label}` : " halaman ini"}.
          </strong>
          <p style={{ color: "#d1d5db", fontSize: "0.85rem", marginBottom: "1rem" }}>
            {this.state.error.message || "Kesalahan tidak diketahui."}
          </p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            style={{
              background: "transparent",
              border: "1px solid rgba(255,255,255,0.2)",
              color: "#fff",
              padding: "0.5rem 1rem",
              borderRadius: "6px",
              fontSize: "0.85rem",
              cursor: "pointer",
            }}
          >
            Coba Lagi
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
