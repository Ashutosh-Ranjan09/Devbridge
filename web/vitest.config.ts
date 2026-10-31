import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

const here = (path: string) => fileURLToPath(new URL(path, import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      "@": here("./src"),
      // `server-only` throws outside a React Server Components build; tests are server code.
      "server-only": here("./tests/empty.ts"),
    },
  },
  test: {
    environment: "node",
    globalSetup: ["./tests/global-setup.ts"],
    fileParallelism: false, // one SQLite file for the run
    env: { ASSESS_API_KEY: "test-key", M5_URL: "http://m5.test", M6_URL: "http://m6.test", ASSESS_URL: "http://assess.test",
           CHAT_URL: "http://chat.test", CHAT_API_KEY: "chat-key" },
  },
});
