// Service worker PWA (vite-plugin-pwa, registerType "autoUpdate"). Registrasi
// aktual dilakukan oleh /registerSW.js yang di-inject ke index.html saat build;
// sw.js sudah memanggil skipWaiting + clientsClaim, jadi SW baru langsung aktif
// dan mengklaim tab yang sedang terbuka.
//
// Yang KURANG dari registrasi bawaan: halaman yang sedang jalan tetap memakai
// bundle JS lama sampai reload manual. Listener di bawah me-reload SEKALI saat
// SW baru mengambil alih (event `controllerchange`) supaya perbaikan langsung
// kepakai pada kunjungan berikutnya, bukan dua reload kemudian.
//
// Aktivasi SW PERTAMA kali (belum ada controller) di-skip supaya kunjungan
// perdana tidak reload sia-sia. Aman di jsdom/test: `serviceWorker` tidak ada
// di navigator -> fungsi langsung keluar.
export function watchServiceWorkerUpdate(): void {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) {
    return;
  }

  let hadController = Boolean(navigator.serviceWorker.controller);

  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!hadController) {
      // Aktivasi pertama pada kunjungan perdana -- bukan update.
      hadController = true;
      return;
    }
    window.location.reload();
  });
}
