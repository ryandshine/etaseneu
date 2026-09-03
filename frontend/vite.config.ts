import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    // PWA: yang di-cache HANYA app shell (JS/CSS/HTML ber-hash) supaya cold-boot
    // di HP -- Chrome Android agresif men-discard tab -- tidak perlu mengunduh
    // ulang bundle. Data /api SENGAJA tidak di-cache di service worker: caching
    // data ditangani di lapisan hook (lib/dashboardPersistence.ts) yang tahu
    // cara revalidasi; SW yang menyajikan JSON API basi malah mem-bypass itu.
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: "auto",
      includeAssets: ["favicon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "ETA SENEU",
        short_name: "ETA SENEU",
        description:
          "Peringatan dini & rekap titik panas di kawasan Perhutanan Sosial dan Hutan Adat.",
        lang: "id",
        theme_color: "#0f1115",
        background_color: "#0a0b0e",
        display: "standalone",
        orientation: "portrait",
        start_url: "/",
        scope: "/",
        icons: [
          { src: "/pwa-192.png", sizes: "192x192", type: "image/png" },
          { src: "/pwa-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "/pwa-512-maskable.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,woff,woff2}"],
        navigateFallback: "/index.html",
        // Jangan sajikan index.html untuk request /api -- biarkan lolos ke jaringan.
        navigateFallbackDenylist: [/^\/api\//],
        cleanupOutdatedCaches: true,
        clientsClaim: true,
      },
      devOptions: { enabled: false },
    }),
  ],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return;
          }

          if (id.includes("react-leaflet") || id.includes("/leaflet/")) {
            return "map-vendor";
          }

          if (id.includes("/recharts/")) {
            return "charts-vendor";
          }

          if (id.includes("/react/") || id.includes("/react-dom/")) {
            return "react-vendor";
          }
        }
      }
    }
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8011"
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    include: ["src/test/**/*.test.ts", "src/test/**/*.test.tsx"],
    // Default 5000ms mepet buat test yang render <App/>: sejak gerbang login
    // ditambahkan (LoginPage.tsx), test itu sekarang butuh satu ronde
    // fetch+render ekstra (loginThroughUI di testHelpers.ts) sebelum konten
    // dashboard yang sebenarnya diuji sempat muncul.
    testTimeout: 10000
  }
});
