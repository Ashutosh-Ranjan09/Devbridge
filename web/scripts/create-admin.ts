/** Admins are made here, never by signing up: `npm run create-admin -- EMAIL "NAME"`.
 * The password is read from the terminal, not the command line, so it stays out of the
 * shell's history. */

import { createInterface } from "node:readline/promises";

import { PrismaBetterSqlite3 } from "@prisma/adapter-better-sqlite3";
import bcrypt from "bcryptjs";

import { PrismaClient } from "../src/generated/prisma/client";

const [email, name] = process.argv.slice(2);
if (!email || !name) {
  console.error('usage: npm run create-admin -- EMAIL "NAME"');
  process.exit(1);
}

const rl = createInterface({ input: process.stdin, output: process.stdout });
const password = await rl.question("Password (at least 10 characters): ");
rl.close();
if (password.length < 10) {
  console.error("too short");
  process.exit(1);
}

const db = new PrismaClient({ adapter: new PrismaBetterSqlite3({ url: process.env.DATABASE_URL! }) });
await db.user.create({
  data: { email: email.trim().toLowerCase(), name, role: "ADMIN", passwordHash: await bcrypt.hash(password, 12) },
});
console.log(`admin ${email} created`);
await db.$disconnect();
