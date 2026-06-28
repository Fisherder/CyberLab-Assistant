/** @type {import('next').NextConfig} */
const apiInternalBase = process.env.CLA_API_INTERNAL_BASE ?? "http://127.0.0.1:8000";
const distDir = process.env.CLA_NEXT_DIST_DIR ?? ".next";

const nextConfig = {
  output: "standalone",
  distDir,
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiInternalBase}/api/:path*`
      }
    ];
  }
};

module.exports = nextConfig;
