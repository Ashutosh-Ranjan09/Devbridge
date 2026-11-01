/** A task's dates and state in words. Dates are India's: a recruiter picks a day, and the
 * task can be started until the end of it, IST, wherever the server runs. */

import type { Task, TaskResults } from "./types";

const IST = "Asia/Kolkata";
const DAY_MS = 86_400_000;

/** The day `days` from now in India, as an <input type="date"> value (YYYY-MM-DD). */
export function dayIn(days: number, from = new Date()): string {
  return new Date(from.getTime() + days * DAY_MS).toLocaleDateString("en-CA", { timeZone: IST });
}

/** The last moment of that day in India. */
export const endOfDay = (day: string): Date => new Date(`${day}T23:59:59+05:30`);

export function when(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { timeZone: IST, dateStyle: "medium", timeStyle: "short" });
}

/** A date without the time, in India: "31 Oct 2026". */
export function day(at: Date | string): string {
  return new Date(at).toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short", year: "numeric" });
}

/** The rows of a module's answer that belong to this job's applicants, with who each is.
 * A row `who` does not recognise (a session or subject this site did not issue for one
 * of them) is not shown. */
export function forApplicants<T, W>(rows: T[], who: (row: T) => W | undefined): (T & { who: W })[] {
  return rows.flatMap((r) => {
    const w = who(r);
    return w === undefined ? [] : [{ ...r, who: w }];
  });
}

/** Why a task has no result yet, in words. */
export function pendingStatus(p: TaskResults["pending"][number], maxAttempts: number): string {
  if (p.status === "issued") return p.start_by ? `not started · start by ${when(p.start_by)}` : "not started";
  if (p.status === "expired") return p.started ? "expired · nothing submitted in time" : "expired · never started";
  return `open · ${p.attempts_used} of ${maxAttempts} attempts used`;
}

/** An issued task has no clock yet: it waits for the candidate to press Start. */
export function taskStatus(task: Task | null): string {
  if (!task) return "unavailable";
  if (task.status === "issued") return task.start_by ? `not started · start by ${when(task.start_by)}` : "not started";
  if (task.status === "expired" && !task.started_at) return "expired · never started";
  if (task.status === "open") return `open · ${task.attempts_used} of ${task.max_attempts} attempts used`;
  return task.status;
}

/** What the button on a practice task already given says, by its state. */
export const PRACTISED: Record<Task["status"], string> = {
  issued: "Open", open: "Continue", submitted: "See result", expired: "See task",
};
