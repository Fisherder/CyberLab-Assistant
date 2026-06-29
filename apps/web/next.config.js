const { PHASE_DEVELOPMENT_SERVER } = require("next/constants");

/** @param {string} phase Next.js 当前运行阶段。 */
module.exports = (phase) => {
  const apiInternalBase = process.env.CLA_API_INTERNAL_BASE ?? "http://127.0.0.1:8000";
  const defaultDistDir = phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : ".next-build";
  const distDir = process.env.CLA_NEXT_DIST_DIR ?? defaultDistDir;

  /** @type {import('next').NextConfig} */
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

  return nextConfig;
};
