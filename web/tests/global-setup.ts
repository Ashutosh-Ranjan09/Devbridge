import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** A fresh database and file folder for each run, the database migrated exactly as
 * `npm run db:migrate` would. The real .data/ is never touched. */
export default function setup() {
  const dir = mkdtempSync(join(tmpdir(), "devbridge-web-"));
  process.env.DATABASE_URL = `file:${join(dir, "test.db")}`;
  process.env.FILES_DIR = join(dir, "files");
  execFileSync("npx", ["prisma", "migrate", "deploy"], { env: process.env, stdio: "ignore" });
  return () => rmSync(dir, { recursive: true, force: true });
}
