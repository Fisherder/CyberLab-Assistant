/** @type {import('next').NextConfig} */
const apiInternalBase = process.env.CLA_API_INTERNAL_BASE ?? "http://127.0.0.1:8000";

const nextConfig = {
  output: "standalone",
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
