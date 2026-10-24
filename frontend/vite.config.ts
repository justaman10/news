import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Served from https://<user>.github.io/<repo>/, so assets need the repo as base path.
const base = process.env.VITE_BASE_PATH ?? "/news/";

export default defineConfig({
  base,
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg", "apple-touch-icon.png"],
      manifest: {
        name: "The Daily Brief",
        short_name: "Daily Brief",
        description: "Your personal daily newspaper.",
        start_url: base,
        scope: base,
        display: "standalone",
        background_color: "#faf7f0",
        theme_color: "#1d1b18",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        navigateFallback: `${base}index.html`,
        runtimeCaching: [
          {
            // Newspaper data: always try the network, fall back to the last copy offline.
            urlPattern: ({ url, request }) => url.pathname.includes("/rest/v1/") && request.method === "GET",
            handler: "NetworkFirst",
            options: {
              cacheName: "news-data",
              networkTimeoutSeconds: 6,
              expiration: { maxEntries: 300, maxAgeSeconds: 7 * 24 * 3600 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            urlPattern: ({ request }) => request.destination === "image",
            handler: "CacheFirst",
            options: {
              cacheName: "news-images",
              expiration: { maxEntries: 250, maxAgeSeconds: 14 * 24 * 3600 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            urlPattern: ({ url }) => url.origin === "https://fonts.googleapis.com" || url.origin === "https://fonts.gstatic.com",
            handler: "StaleWhileRevalidate",
            options: { cacheName: "fonts", expiration: { maxEntries: 20 } },
          },
        ],
      },
    }),
  ],
});
