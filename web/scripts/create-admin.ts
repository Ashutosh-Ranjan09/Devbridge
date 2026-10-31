/** Admins are made here, never by signing up: `npm run create-admin -- EMAIL "NAME"`.
 * Run again for an existing admin, it sets a new password and logs them out everywhere:
 * the site's reset links are never for an admin's own account. The password is read
 * from the terminal, not the command line, so it stays out of the shell's history. */

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
const address = email.trim().toLowerCase();
const passwordHash = await bcrypt.hash(password, 12);
const existing = await db.user.findUnique({ where: { email: address } });
if (existing && existing.role !== "ADMIN") {
  console.error(`${address} belongs to a ${existing.role.toLowerCase()}, not an admin`);
  process.exit(1);
}
if (existing) {
  await db.$transaction([
    db.user.update({ where: { id: existing.id }, data: { passwordHash } }),
    db.session.deleteMany({ where: { userId: existing.id } }),
    db.loginFailure.deleteMany({ where: { email: address } }),
  ]);
  console.log(`admin ${address}: new password set, logged out everywhere`);
} else {
  await db.user.create({ data: { email: address, name, role: "ADMIN", passwordHash } });
  console.log(`admin ${address} created`);
}
await db.$disconnect();
