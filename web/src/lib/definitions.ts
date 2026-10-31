import * as z from "zod";

import { endOfDay } from "./tasks";
import type { Examples } from "./types";

const email = z.string().trim().toLowerCase().pipe(z.email({ error: "Enter a valid email." }));
const name = z.string().trim().min(2, { error: "At least 2 characters." }).max(100);
// Length, not character classes: a long passphrase is stronger than a short password
// with one digit and one symbol in it.
const password = z
  .string()
  .min(10, { error: "At least 10 characters." })
  .max(200, { error: "At most 200 characters." });

export const ResetSchema = z.object({ password });

export const ChangePasswordSchema = z.object({
  current: z.string().min(1, { error: "Enter your current password." }),
  password,
});

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

/** The Run button's state: the examples it ran, or why it could not, and the code. */
export type RunState = (NonNullable<FormState> & { examples?: Examples }) | undefined;

/** What was typed, for a refused action to hand back: React resets a form after its
 * action runs, and a field with no value passed back comes back empty. */
export function typed(form: FormData): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of form) if (typeof v === "string") out[k] = v;
  return out;
}

// ── candidate ───────────────────────────────────────────────────────────────

export const MAX_CV_BYTES = 5 * 1024 * 1024;

/** What M5 reads: PDF (a scan is read by OCR) or Word. Checked here so a wrong file is
 * refused before it is sent anywhere. */
export const CvSchema = z.object({
  cv: z
    .instanceof(File, { error: "Choose a file." })
    .refine((f) => f.size > 0, { error: "Choose a file." })
    .refine((f) => f.size <= MAX_CV_BYTES, { error: "At most 5 MB." })
    .refine((f) => /\.(pdf|docx)$/i.test(f.name), { error: "A .pdf or .docx file." }),
});

/** A document backing a line of the CV: a PDF or a photo of one. No SVG or HTML, which
 * could run script when opened from this site. */
export const ProofSchema = z.object({
  file: z
    .instanceof(File, { error: "Choose a file." })
    .refine((f) => f.size > 0, { error: "Choose a file." })
    .refine((f) => f.size <= MAX_CV_BYTES, { error: "At most 5 MB." })
    .refine((f) => /\.(pdf|png|jpe?g)$/i.test(f.name), { error: "A PDF, PNG or JPG." }),
  label: z.string().trim().min(2, { error: "Say what it proves." }).max(300),
});

/** M5's own rule for a username (cvv.models.api.HANDLE), checked here so a wrong one
 * is said beside its field. Every field is optional: blank is "I have no account". */
const handle = z
  .string()
  .trim()
  .refine((s) => s === "" || /^[A-Za-z0-9][A-Za-z0-9_.-]{0,38}$/.test(s), {
    error: "A username only: letters, digits, _ . - (no link).",
  })
  .transform((s) => s || null);

/** Anything the CV leaves out, in the candidate's words. Optional; blank is none. */
export const NoteSchema = z
  .string()
  .trim()
  .max(2000, { error: "At most 2,000 characters." })
  .transform((s) => s || null);

export const HANDLE_FIELDS = ["github", "codeforces", "leetcode", "codechef"] as const;
export const HandlesSchema = z.object(Object.fromEntries(HANDLE_FIELDS.map((k) => [k, handle])) as Record<
  (typeof HANDLE_FIELDS)[number],
  typeof handle
>);

export const SubmissionSchema = z.object({
  code: z.string().min(1, { error: "Write some code first." }).max(200_000, { error: "At most 200,000 characters." }),
});

// ── recruiter ───────────────────────────────────────────────────────────────

export const NewJobSchema = z.object({
  title: z.string().trim().min(3, { error: "Give the job a title." }).max(120),
  text: z.string().trim().min(50, { error: "Paste the whole job description (at least 50 characters)." }).max(50_000),
  orgId: z.string().min(1, { error: "Choose an organisation." }),
  model: z.literal("on").optional(), // a checkbox: present when ticked
});

/** A bar as typed: blank is "no bar"; otherwise a number from 0 to 1. */
export const BarSchema = z
  .string()
  .trim()
  .transform((s, ctx) => {
    if (s === "") return null;
    const n = Number(s);
    if (!Number.isFinite(n) || n < 0 || n > 1) {
      ctx.addIssue({ code: "custom", message: "A bar is a number from 0 to 1, or blank." });
      return z.NEVER;
    }
    return n;
  });

/** The day a job's tasks can be started until. Assessment refuses past and far-off dates
 * too; checking here returns the form with the date kept instead of a module's message. */
export const START_BY_MAX_DAYS = 60;
export const StartBySchema = z.object({
  startBy: z
    .string({ error: "Pick a date." })
    .regex(/^\d{4}-\d{2}-\d{2}$/, { error: "Pick a date." })
    .refine((d) => endOfDay(d).getTime() > Date.now(), { error: "That day has already passed." })
    .refine((d) => endOfDay(d).getTime() <= Date.now() + START_BY_MAX_DAYS * 86_400_000,
      { error: `At most ${START_BY_MAX_DAYS} days ahead.` }),
});

export const DecisionSchema = z.object({
  outcome: z.enum(["ADVANCE", "REJECT", "HIRE"], { error: "Choose an outcome." }),
  // A person decides, and says why in words another person can read and dispute.
  reason: z.string().trim().min(10, { error: "Say why, in at least 10 characters." }).max(2000),
});

// ── admin ───────────────────────────────────────────────────────────────────

export const MarkSchema = z.object({
  mark: z.enum(["VERIFIED", "UNVERIFIED"], { error: "Choose verified or unverified." }),
  // What the admin looked at, so whoever reads the mark can weigh it and dispute it.
  note: z.string().trim().min(10, { error: "Say what you checked, in at least 10 characters." }).max(1000),
});
