import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16's defaults, kept: both become permanent in the next major release. Every
  // page here reads the session, so each renders a static shell and streams its
  // signed-in part behind <Suspense>.
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
    },
  },
};

export default nextConfig;
