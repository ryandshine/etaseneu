import { beforeEach } from "vitest";

// Sesi produksi memang persisten di localStorage. Tiap test harus dimulai
// dari browser bersih agar login satu test tidak mengubah gerbang test lain.
beforeEach(() => {
  window.localStorage.clear();
});
