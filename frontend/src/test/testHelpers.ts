import { fireEvent, screen, waitForElementToBeRemoved } from "@testing-library/react";

// App() renders <LoginPage/> sampai loggedIn true (lihat App.tsx) -- test yang
// me-render <App/> langsung harus login dulu sebelum menyentuh konten
// dashboard, atau elemen yang dicari (leaflet-map, Filter Waktu, dst) tidak
// akan pernah muncul di DOM. Kredensialnya tidak penting di sini; fetchMock
// tiap test file harus meng-handle POST /api/auth/login dengan
// {ok:true, token, username, role} tanpa syarat -- ini cuma melewati
// gerbangnya, bukan menguji login itu sendiri (itu sudah dites di backend
// & di test khusus login kalau ada).
export async function loginThroughUI(): Promise<void> {
  const usernameInput = await screen.findByLabelText("Username");
  const passwordInput = screen.getByLabelText("Password");
  fireEvent.change(usernameInput, { target: { value: "admin" } });
  fireEvent.change(passwordInput, { target: { value: "test-password" } });
  fireEvent.click(screen.getByRole("button", { name: /masuk/i }));
  await waitForElementToBeRemoved(() => screen.queryByLabelText("Username"));
}
