// Proxy /api/* to the FastAPI backend so the browser makes same-origin calls
// (no CORS friction). Override the backend location with BACKEND_URL.
// In Docker the rewrite destination is baked at build time from the BACKEND_URL
// build arg (defaults to the compose service name); for local dev it's read at
// runtime and defaults to localhost:8000.
const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },
};

export default nextConfig;
