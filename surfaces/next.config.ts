import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // The orchestration tier runs as a separate service (SRS 2.4: Python
  // containers). In development it is on :8000; in production the deployment
  // sets COWRIE_API_URL. Proxying /api through Next keeps the browser on one
  // origin, which avoids CORS entirely and means the PWA service worker only
  // ever sees same-origin requests.
  async rewrites() {
    // Render supplies COWRIE_API_URL as a bare host:port, so add the scheme
    // when one is missing rather than requiring the value to be pre-formatted.
    const raw = process.env.COWRIE_API_URL ?? "http://127.0.0.1:8000";
    const api = /^https?:\/\//.test(raw) ? raw : `https://${raw}`;
    return [{ source: "/api/:path*", destination: `${api}/:path*` }];
  },
};

export default config;
