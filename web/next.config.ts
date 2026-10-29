import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16's defaults, kept: both become permanent in the next major release. Every
  // page here reads the session, so each renders a static shell and streams its
  // signed-in part behind <Suspense>.
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    // A CV upload is a server action, and an action's body is capped at 1 MB by default.
    // 6 MB: the 5 MB file limit in lib/definitions.ts, plus multipart's own overhead.
    serverActions: { bodySizeLimit: "6mb" },
  },
  turbopack: {
    rules: {
      "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
    },
  },
};

export default nextConfig;
