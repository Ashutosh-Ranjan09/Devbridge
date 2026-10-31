import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16's defaults, kept: both become permanent in the next major release. Every
  // page here reads the session, so each renders a static shell and streams its
  // signed-in part behind <Suspense>.
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    // A CV upload and a chat file are server actions, and an action's body is capped at
    // 1 MB by default. 11 MB: the chat's 10 MB file limit (lib/definitions.ts; a CV's is
    // 5 MB), plus multipart's own overhead.
    serverActions: { bodySizeLimit: "11mb" },
  },
  turbopack: {
    rules: {
      "*.css": { loaders: ["@tailwindcss/turbopack"], as: "*.css" },
    },
  },
};

export default nextConfig;
