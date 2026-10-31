/** A task's dates and state in words. Dates are India's: a recruiter picks a day, and the
 * task can be started until the end of it, IST, wherever the server runs. */

import type { Task } from "./types";

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

/** An issued task has no clock yet: it waits for the candidate to press Start. */
export function taskStatus(task: Task | null): string {
  if (!task) return "unavailable";
  if (task.status === "issued") return task.start_by ? `not started · start by ${when(task.start_by)}` : "not started";
  if (task.status === "expired" && !task.started_at) return "expired · never started";
  return task.status;
}
