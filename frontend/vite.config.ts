import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
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
    include: ["src/test/**/*.test.tsx"],
    // Default 5000ms mepet buat test yang render <App/>: sejak gerbang login
    // ditambahkan (LoginPage.tsx), test itu sekarang butuh satu ronde
    // fetch+render ekstra (loginThroughUI di testHelpers.ts) sebelum konten
    // dashboard yang sebenarnya diuji sempat muncul.
    testTimeout: 10000
  }
});
