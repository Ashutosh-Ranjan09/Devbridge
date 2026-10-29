import * as z from "zod";

const email = z.string().trim().toLowerCase().pipe(z.email({ error: "Enter a valid email." }));
const name = z.string().trim().min(2, { error: "At least 2 characters." }).max(100);
// Length, not character classes: a long passphrase is stronger than a short password
// with one digit and one symbol in it.
const password = z
  .string()
  .min(10, { error: "At least 10 characters." })
  .max(200, { error: "At most 200 characters." });

export const LoginSchema = z.object({
  email,
  password: z.string().min(1, { error: "Enter your password." }),
});

export const SignupSchema = z.discriminatedUnion("role", [
  z.object({ role: z.literal("CANDIDATE"), name, email, password }),
  z.object({
    role: z.literal("RECRUITER"),
    name,
    email,
    password,
    orgName: z.string().trim().min(2, { error: "Name your organisation." }).max(100),
    orgKind: z.enum(["ENTERPRISE", "CLIENT"], { error: "Choose one." }),
  }),
]);

/** What a form action returns: errors per field, one message, and the values to put
 * back in the form. Never the password. */
export type FormState =
  | { errors?: Record<string, string[] | undefined>; message?: string; values?: Record<string, string> }
  | undefined;
