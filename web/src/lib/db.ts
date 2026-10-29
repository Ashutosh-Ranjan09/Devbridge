import "server-only";

import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3";

import { PrismaClient } from "@/generated/prisma/client";

// One client per process. `next dev` re-evaluates modules on every edit; without the
// global, each reload would open another connection to the same SQLite file.
const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

function connect(): PrismaClient {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL is not set: copy .env.example to .env");
  return new PrismaClient({ adapter: new PrismaBetterSqlite3({ url }) });
}

export const db = globalForPrisma.prisma ?? connect();
if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = db;
