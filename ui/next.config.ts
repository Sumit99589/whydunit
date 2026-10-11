import type { NextConfig } from "next";

const ENGINE = process.env.WHYDUNIT_ENGINE_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  // Server-Sent Events from the engine are proxied through this origin; gzip would hold back the stream's tail.
  compress: false,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  // The browser talks to the engine through this origin (no CORS, SSE included).
  async rewrites() {
    return [{ source: "/engine/:path*", destination: `${ENGINE}/:path*` }];
  },
};

export default nextConfig;
