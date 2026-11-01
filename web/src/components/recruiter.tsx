"use client";

import { useActionState, useState } from "react";

import { createJob, decide, editJob, sendAssessment } from "@/app/recruiter/actions";
import type { JobSkill, JobTasks } from "@/lib/types";

import { Icon } from "./icons";
import { Button } from "./ui";

const input = "h-11 w-full rounded-xl border border-line bg-background px-3.5 text-sm outline-none transition focus:border-accent focus:ring-4 focus:ring-accent/15";

export function NewJobForm({ orgs }: { orgs: { id: string; name: string }[] }) {
  const [state, action, pending] = useActionState(createJob, undefined);
  const [chars, setChars] = useState(state?.values?.text?.length ?? 0);
  return (
    <form action={action} className="relative space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,14rem)]">
        <label className={`block ${orgs.length > 1 ? "" : "sm:col-span-2"}`}>
          <span className="mb-1.5 block text-sm font-semibold">Job title</span>
          <input name="title" defaultValue={state?.values?.title} placeholder="e.g. Backend Engineer, Payments"
            aria-invalid={state?.errors?.title ? true : undefined} className={input} />
          {state?.errors?.title?.map((e) => <span key={e} className="mt-1 block text-sm text-danger">{e}</span>)}
        </label>
        {orgs.length > 1 ? (
          <label className="block">
            <span className="mb-1.5 block text-sm font-semibold">Hiring for</span>
            <select key={state?.values?.orgId} name="orgId" defaultValue={state?.values?.orgId} className={input}>
              {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
            {state?.errors?.orgId?.map((e) => <span key={e} className="mt-1 block text-sm text-danger">{e}</span>)}
          </label>
        ) : (
          <input type="hidden" name="orgId" value={orgs[0]?.id ?? ""} />
        )}
      </div>

      <label className="block">
        <span className="mb-1.5 flex items-baseline justify-between gap-2">
          <span className="text-sm font-semibold">Job description</span>
          <span className={`text-xs tabular-nums ${chars > 0 && chars < 50 ? "text-danger" : "text-muted"}`}>{chars.toLocaleString("en-IN")} characters</span>
        </span>
        <textarea name="text" rows={16} defaultValue={state?.values?.text} onChange={(e) => setChars(e.target.value.trim().length)}
          placeholder={"Paste the full description: the role, what they'll work on, and the skills you're looking for."}
          aria-invalid={state?.errors?.text ? true : undefined}
          className="w-full rounded-xl border border-line bg-background px-4 py-3 text-sm leading-relaxed outline-none transition focus:border-accent focus:ring-4 focus:ring-accent/15" />
        {state?.errors?.text?.map((e) => <span key={e} className="mt-1 block text-sm text-danger">{e}</span>)}
      </label>

      <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line p-4 transition has-[:checked]:border-accent/50 has-[:checked]:bg-accent/5">
        <input type="checkbox" name="model" defaultChecked={state?.values ? state.values.model === "on" : true} className="peer sr-only" />
        <span className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full bg-line transition peer-checked:bg-accent peer-focus-visible:ring-4 peer-focus-visible:ring-accent/25
          after:absolute after:top-0.5 after:left-0.5 after:size-4 after:rounded-full after:bg-white after:shadow after:transition peer-checked:after:translate-x-4" aria-hidden />
        <span>
          <span className="flex items-center gap-1.5 text-sm font-semibold"><Icon.Spark className="size-4 text-accent" /> Smart skill extraction</span>
          <span className="mt-0.5 block text-xs text-muted">
            A model reads the description and proposes skills, each quoted from your text. More thorough, but can take a few minutes.
          </span>
        </span>
      </label>

      {state?.message && <p role="alert" className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{state.message}</p>}
      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5">
        <Button pending={pending}>Propose skills</Button>
        <span className="text-sm text-muted">You&apos;ll review them next.</span>
      </div>

      {pending && (
        <div className="absolute -inset-2 grid place-items-center rounded-2xl bg-panel/85 backdrop-blur-[2px]" role="status">
          <div className="max-w-xs text-center">
            <span className="mx-auto block size-10 animate-spin rounded-full border-4 border-accent/20 border-t-accent" aria-hidden />
            <p className="mt-4 font-semibold">Reading the job description…</p>
            <p className="mt-1 text-sm text-muted">Finding each skill it asks for, with the words it was found in. With smart extraction this can take a few minutes.</p>
          </div>
        </div>
      )}
    </form>
  );
}

const PRIORITY = [["must", "Must-have"], ["nice", "Nice to have"], ["drop", "Drop"]] as const;

/** The proposed skills, and the tasks every applicant gets, for a person to fix before
 * confirming. */
export function SkillEditor({ jobId, skills, catalogue, tasks }: {
  jobId: string; skills: JobSkill[]; catalogue: { id: string; label: string }[]; tasks: JobTasks;
}) {
  const [state, action, pending] = useActionState(editJob.bind(null, jobId), undefined);
  const listed = skills.filter((s) => s.skill_id !== null);
  const typed = state?.values; // what was typed, after a refusal; else the job as stored
  const unlisted = skills.filter((s) => s.skill_id === null);
  const names = new Map(catalogue.map((c) => [c.id, c.label]));
  const label = (id: string) => names.get(id) ?? id;
  return (
    <form action={action} className="space-y-8">
      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold">Skills from the description</h2>
            <p className="text-sm text-muted">Each with the words it was found in. Set what matters, and a minimum bar for must-haves if you want one.</p>
          </div>
        </div>
        <ul className="space-y-2.5">
          {listed.map((s) => (
            <SkillRow key={s.skill_id} skill={s} label={label(s.skill_id as string)} typed={typed} errors={state?.errors?.[`bar:${s.skill_id}`]} />
          ))}
        </ul>
        {unlisted.length > 0 && (
          <p className="mt-3 rounded-xl bg-background px-4 py-3 text-sm text-muted ring-1 ring-line">
            <span className="font-medium text-foreground">Not on the skill list,</span> so nothing can check them:{" "}
            {unlisted.map((s) => s.surface).join(", ")}.
          </p>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-line p-3 text-sm">
          <span className="font-medium">Add a skill</span>
          <input name="add" list="skill-catalogue" defaultValue={typed?.add} placeholder="Search the skill list"
            className="h-9 min-w-0 flex-1 rounded-lg border border-line bg-background px-3 outline-none focus:border-accent sm:max-w-xs" />
          <datalist id="skill-catalogue">{catalogue.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}</datalist>
          <select key={typed?.addPriority ?? "must"} name="addPriority" defaultValue={typed?.addPriority ?? "must"}
            className="h-9 rounded-lg border border-line bg-background px-2 outline-none focus:border-accent">
            <option value="must">as a must-have</option>
            <option value="nice">as a nice-to-have</option>
          </select>
        </div>
        <p className="mt-2 text-xs text-muted">
          A must-have&apos;s bar (0–1) filters on the lower end of a candidate&apos;s skill range. Left blank: a skill a task
          tests is assessed, not filtered; any other must-have needs direct evidence of any level.
        </p>
      </section>
      <TaskPicker tasks={tasks} typed={typed} label={label} />
      <div className="flex flex-wrap items-center gap-3">
        <Button pending={pending} variant="outline">Save changes</Button>
        {state?.message && <p className={`text-sm ${state.values ? "text-danger" : "text-ok"}`}>{state.message}</p>}
        {state?.errors && !state.message && <p className="text-sm text-danger">Fix the marked bars, then save.</p>}
      </div>
    </form>
  );
}

function SkillRow({ skill, label, typed, errors }: { skill: JobSkill; label: string; typed?: Record<string, string>; errors?: string[] }) {
  const id = skill.skill_id as string;
  const initial = typed?.[`priority:${id}`] ?? skill.priority;
  const [priority, setPriority] = useState(initial);
  return (
    <li className={`rounded-xl border p-4 transition ${priority === "drop" ? "border-line bg-background opacity-60" : "border-line bg-panel"}`}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1 basis-56">
          <p className="flex flex-wrap items-center gap-2 font-semibold">
            {label}
            {skill.assessable && <span className="rounded-full bg-accent/10 px-2 py-0.5 text-[11px] font-semibold text-accent">Task available</span>}
            {skill.needs_review && <span className="rounded-full bg-highlight/15 px-2 py-0.5 text-[11px] font-semibold text-[#b45309] dark:text-highlight">Inferred: check it</span>}
          </p>
          <p className="mt-1 text-sm text-muted">&ldquo;{skill.quote}&rdquo;</p>
        </div>
        {/* keyed by its value: React applies a default only when it mounts */}
        <div key={initial} className="flex rounded-lg border border-line bg-background p-0.5 text-xs" role="radiogroup" aria-label={`${label} priority`}>
          {PRIORITY.map(([v, text]) => (
            <label key={v} className={`cursor-pointer rounded-md px-2.5 py-1.5 font-semibold transition ${priority === v
              ? v === "drop" ? "bg-danger/10 text-danger" : "bg-accent text-on-accent" : "text-muted hover:text-foreground"}`}>
              <input type="radio" name={`priority:${id}`} value={v} defaultChecked={initial === v} onChange={() => setPriority(v)} className="sr-only" />
              {text}
            </label>
          ))}
        </div>
        <label className={`flex items-center gap-2 text-xs font-medium text-muted ${priority === "must" ? "" : "invisible"}`}>
          Bar
          <input name={`bar:${id}`} defaultValue={typed?.[`bar:${id}`] ?? skill.bar ?? ""} inputMode="decimal" placeholder="none"
            aria-invalid={errors ? true : undefined}
            className="h-8 w-16 rounded-lg border border-line bg-background px-2 text-sm text-foreground outline-none focus:border-accent aria-invalid:border-danger" />
        </label>
      </div>
      {errors?.map((e) => <p key={e} className="mt-2 text-right text-xs text-danger">{e}</p>)}
    </li>
  );
}

/** Which tasks every applicant gets: the same for all of them, so results compare. */
function TaskPicker({ tasks, typed, label }: { tasks: JobTasks; typed?: Record<string, string>; label: (id: string) => string }) {
  const options = Object.entries(tasks.must).flatMap(([skill, list]) => list.map((o) => ({ ...o, skill })));
  const name = (o: { skill: string; pattern_id: string }) => `task:${o.skill}:${o.pattern_id}`;
  // After a refusal, what was ticked; else the job as stored.
  const ticked = (o: (typeof options)[number]) => (typed ? name(o) in typed : o.chosen);
  const [picked, setPicked] = useState(() => new Set(options.filter(ticked).map(name)));
  const minutes = options.filter((o) => picked.has(name(o))).reduce((sum, o) => sum + o.time_limit_minutes, 0);
  return (
    <fieldset>
      <input type="hidden" name="tasks" value="1" />
      <legend className="text-lg font-semibold">The assessment</legend>
      <p className="mb-3 text-sm text-muted">Coding tasks every applicant gets, the same for all, so results compare.</p>
      {options.length === 0 && <p className="rounded-xl bg-background px-4 py-3 text-sm text-muted ring-1 ring-line">No task tests any of these must-haves yet.</p>}
      <ul className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {options.map((o) => (
          <li key={name(o)}>
            <label className="flex h-full cursor-pointer items-start gap-3 rounded-xl border border-line p-4 transition has-[:checked]:border-accent/60 has-[:checked]:bg-accent/5">
              <input type="checkbox" name={name(o)} defaultChecked={ticked(o)} className="mt-0.5 size-4 accent-[var(--accent)]"
                onChange={(e) => setPicked((s) => { const n = new Set(s); if (e.target.checked) n.add(name(o)); else n.delete(name(o)); return n; })} />
              <span className="min-w-0">
                <span className="block font-semibold">{o.title}</span>
                <span className="mt-1 flex flex-wrap gap-1.5 text-xs text-muted">
                  <span className="rounded-md bg-background px-1.5 py-0.5 ring-1 ring-line">{label(o.skill)}</span>
                  <span className="rounded-md bg-background px-1.5 py-0.5 capitalize ring-1 ring-line">{o.level}</span>
                  <span className="flex items-center gap-1"><Icon.Clock className="size-3.5" />{o.time_limit_minutes} min</span>
                </span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      {options.length > 0 && (
        <p className="mt-3 text-sm">
          {picked.size === 0 ? <span className="text-muted">No tasks: nothing will be sent to applicants.</span>
            : <><span className="font-semibold">{picked.size} task{picked.size > 1 ? "s" : ""} · {minutes} minutes</span> <span className="text-muted">in all.</span></>}
          {" "}<span className="text-muted">An unbarred must-have no ticked task tests needs direct evidence of any level instead.</span>
        </p>
      )}
      {tasks.not_assessable.length > 0 && (
        <p className="mt-1 text-sm text-muted">No task tests: {tasks.not_assessable.map(label).join(", ")}.</p>
      )}
    </fieldset>
  );
}

/** Once tasks are sent the button goes: sending again returns the same tasks, so a
 * second click would only look like a second assessment. The form stays mounted so the
 * send's own message (which must-haves no task tests) survives the page refreshing. */
export function SendAssessment({ jobId, applicationId, sent, startBy, sends }: {
  jobId: string; applicationId: string; sent: boolean;
  startBy: { default: string; min: string; max: string }; // India's days, YYYY-MM-DD, from the server
  sends: { title: string; minutes: number }[] | null;      // the job's tasks; null: assessment did not say
}) {
  const [state, action, pending] = useActionState(sendAssessment.bind(null, jobId, applicationId), undefined);
  if (!sent && sends?.length === 0) {
    return <p className="text-sm text-muted">This job has no tasks, so there is nothing to send.</p>;
  }
  return (
    <form action={action} className="space-y-2">
      {sent ? (
        !state?.message && <p className="text-sm text-muted">Sent. Sending again would return the same tasks.</p>
      ) : (
        <>
          {sends && (
            <p className="text-sm">
              Sends: {sends.map((t) => t.title).join(", ")}{" "}
              <span className="text-muted">({sends.reduce((sum, t) => sum + t.minutes, 0)} minutes in all)</span>
            </p>
          )}
          <label className="block max-w-xs">
            <span className="mb-1 block text-sm font-medium">Start by</span>
            <input type="date" name="startBy" defaultValue={state?.values?.startBy ?? startBy.default}
              min={startBy.min} max={startBy.max} aria-invalid={state?.errors?.startBy ? true : undefined}
              className="w-full rounded-md border border-line bg-background px-3 py-2 outline-none focus:border-accent" />
            {state?.errors?.startBy?.map((e) => <span key={e} className="mt-1 block text-sm text-danger">{e}</span>)}
          </label>
          <p className="text-xs text-muted">
            The candidate can press Start until the end of this day (IST). Each task&apos;s time limit runs from then,
            the same for every candidate.
          </p>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="model" defaultChecked />
            Fit each task&apos;s story to this job description (the model chooses only from each task&apos;s allowed values)
          </label>
          <Button pending={pending}>Send an assessment</Button>
        </>
      )}
      {state?.message && <p className="text-sm">{state.message}</p>}
    </form>
  );
}

export function DecisionForm({ jobId, applicationId }: { jobId: string; applicationId: string }) {
  const [state, action, pending] = useActionState(decide.bind(null, jobId, applicationId), undefined);
  return (
    <form action={action} className="space-y-3">
      <div className="flex flex-wrap gap-4">
        {[["ADVANCE", "Advance"], ["REJECT", "Reject"], ["HIRE", "Hire"]].map(([value, label]) => (
          <label key={value} className="flex items-center gap-2">
            <input type="radio" name="outcome" value={value} defaultChecked={state?.values?.outcome === value} />{label}
          </label>
        ))}
      </div>
      {state?.errors?.outcome?.map((e) => <p key={e} className="text-sm text-danger">{e}</p>)}
      <label className="block">
        <span className="mb-1 block text-sm font-medium">Why (the candidate sees this)</span>
        <textarea name="reason" rows={3} defaultValue={state?.values?.reason}
          className="w-full rounded-md border border-line bg-background p-2 text-sm" />
        {state?.errors?.reason?.map((e) => <span key={e} className="block text-sm text-danger">{e}</span>)}
      </label>
      {state?.message && <p className="text-sm">{state.message}</p>}
      <Button pending={pending}>Record the decision</Button>
    </form>
  );
}
