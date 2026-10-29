import { defineConfig } from "prisma/config";

// Prisma's CLI does not read .env itself (Next.js does, for the app). Node's own loader,
// rather than a dotenv dependency; a missing .env is fine when the variable is exported.
try {
  process.loadEnvFile();
} catch {}

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: { path: "prisma/migrations" },
  datasource: { url: process.env.DATABASE_URL },
});
