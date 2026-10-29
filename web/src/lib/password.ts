import "server-only";

import bcrypt from "bcryptjs";

// 12 rounds: about a quarter of a second per check, which is the point.
const COST = 12;

// Compared against when no account has the email, so a wrong email takes as long as a
// wrong password and the timing does not say which emails have accounts.
const NOBODY = bcrypt.hashSync("no account has this email", COST);

export function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, COST);
}

export function verifyPassword(password: string, hash: string | null | undefined): Promise<boolean> {
  return bcrypt.compare(password, hash ?? NOBODY);
}
