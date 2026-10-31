"use client";

import { useActionState, useState } from "react";

import { createJob, decide, editJob, sendAssessment } from "@/app/recruiter/actions";
import type { JobSkill, JobTasks } from "@/lib/types";

import { Button, Field } from "./ui";

export function NewJobForm({ orgs }: { orgs: { id: string; name: string }[] }) {
  const [state, action, pending] = useActionState(createJob, undefined);
  return (
    <form action={action} className="space-y-4">
      <Field label="Title" name="title" defaultValue={state?.values?.title} errors={state?.errors?.title} />
      {orgs.length > 1 ? (
        <label className="block">
          <span className="mb-1 block text-sm font-medium">Organisation</span>
          <select name="orgId" className="w-full rounded-md border border-line bg-background px-3 py-2">
            {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
        </label>
      ) : (
        <input type="hidden" name="orgId" value={orgs[0]?.id ?? ""} />
      )}
      <label className="block">
        <span className="mb-1 block text-sm font-medium">Job description</span>
        <textarea name="text" rows={14} defaultValue={state?.values?.text}
          className="w-full rounded-md border border-line bg-background p-3 text-sm" />
        {state?.errors?.text?.map((e) => <span key={e} className="block text-sm text-danger">{e}</span>)}
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" name="model" defaultChecked={state?.values ? state.values.model === "on" : true} />
        Let the model propose skills (each must be quoted from the text; slower)
      </label>
      {state?.message && <p className="text-sm text-danger">{state.message}</p>}
      <Button pending={pending}>Propose skills</Button>
      {pending && <p className="text-sm text-muted">Reading the job description. With the model this can take a few minutes.</p>}
    </form>
  );
}

/** The proposed skills, and the tasks every applicant gets, for a person to fix before
 * confirming. */
export function SkillEditor({ jobId, skills, catalogue, tasks }: {
  jobId: string; skills: JobSkill[]; catalogue: string[]; tasks: JobTasks;
}) {
  const [state, action, pending] = useActionState(editJob.bind(null, jobId), undefined);
  const listed = skills.filter((s) => s.skill_id !== null);
  const typed = state?.values; // what was typed, after a refusal; else the job as stored
  const unlisted = skills.filter((s) => s.skill_id === null);
  return (
    <form action={action} className="space-y-4">
      <table className="w-full text-left text-sm">
        <thead className="text-muted">
          <tr><th className="py-1">Skill</th><th>As the JD says it</th><th>Priority</th><th>Bar (0–1)</th></tr>
        </thead>
        <tbody>
          {listed.map((s) => {
            const id = s.skill_id as string;
            const errors = state?.errors?.[`bar:${id}`];
            return (
              <tr key={id} className="border-t border-line align-top">
                <td className="py-2 pr-2">
                  <code>{id}</code>
                  {s.needs_review && <span className="block text-xs text-danger">inferred: check it</span>}
                  {s.assessable && <span className="block text-xs text-muted">a task tests this</span>}
                </td>
                <td className="py-2 pr-2 text-muted"><q>{s.quote}</q></td>
                <td className="py-2 pr-2">
                  {/* keyed by its value: React applies a <select>'s default only when it mounts */}
                  <select key={typed?.[`priority:${id}`] ?? s.priority} name={`priority:${id}`}
                    defaultValue={typed?.[`priority:${id}`] ?? s.priority} className="rounded border border-line bg-background px-1">
                    <option value="must">must</option>
                    <option value="nice">nice</option>
                    <option value="drop">drop</option>
                  </select>
                </td>
                <td className="py-2">
                  <input name={`bar:${id}`} defaultValue={typed?.[`bar:${id}`] ?? s.bar ?? ""} inputMode="decimal" placeholder="none"
                    className="w-20 rounded border border-line bg-background px-2" />
                  {errors?.map((e) => <span key={e} className="block text-xs text-danger">{e}</span>)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {unlisted.length > 0 && (
        <p className="text-sm text-muted">
          Named in the JD but not on the skill list, so nothing can check them:{" "}
          {unlisted.map((s) => s.surface).join(", ")}.
        </p>
      )}
      <p className="text-xs text-muted">
        A must-have&apos;s bar filters on the lower end of a candidate&apos;s interval. Blank: a skill a task
        tests is assessed, not filtered; any other must-have needs direct evidence of any level.
      </p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>Add</span>
        <input name="add" list="skill-catalogue" defaultValue={typed?.add} placeholder="skill id" className="rounded border border-line bg-background px-2 py-1" />
        <datalist id="skill-catalogue">{catalogue.map((c) => <option key={c} value={c} />)}</datalist>
        <select key={typed?.addPriority ?? "must"} name="addPriority" defaultValue={typed?.addPriority ?? "must"} className="rounded border border-line bg-background px-1 py-1">
          <option value="must">as a must-have</option>
          <option value="nice">as a nice-to-have</option>
        </select>
      </div>
      <TaskPicker tasks={tasks} typed={typed} />
      {state?.message && <p className="text-sm">{state.message}</p>}
      <Button pending={pending}>Save</Button>
    </form>
  );
}

/** Which tasks every applicant gets: the same for all of them, so results compare. */
function TaskPicker({ tasks, typed }: { tasks: JobTasks; typed?: Record<string, string> }) {
  const options = Object.entries(tasks.must).flatMap(([skill, list]) => list.map((o) => ({ ...o, skill })));
  const name = (o: { skill: string; pattern_id: string }) => `task:${o.skill}:${o.pattern_id}`;
  // After a refusal, what was ticked; else the job as stored.
  const ticked = (o: (typeof options)[number]) => (typed ? name(o) in typed : o.chosen);
  const [picked, setPicked] = useState(() => new Set(options.filter(ticked).map(name)));
  const minutes = options.filter((o) => picked.has(name(o))).reduce((sum, o) => sum + o.time_limit_minutes, 0);
  return (
    <fieldset className="space-y-2 border-t border-line pt-4">
      <input type="hidden" name="tasks" value="1" />
      <legend className="font-medium">Tasks every applicant gets</legend>
      {options.length === 0 && <p className="text-sm text-muted">No task tests any of these must-haves yet.</p>}
      {options.map((o) => (
        <label key={name(o)} className="flex items-center gap-2 text-sm">
          <input type="checkbox" name={name(o)} defaultChecked={ticked(o)}
            onChange={(e) => setPicked((s) => { const n = new Set(s); if (e.target.checked) n.add(name(o)); else n.delete(name(o)); return n; })} />
          <span><code>{o.skill}</code>: {o.title} <span className="text-muted">· {o.level} · {o.time_limit_minutes} min</span></span>
        </label>
      ))}
      {options.length > 0 && (
        <p className="text-sm text-muted">
          {picked.size === 0 ? "No tasks: nothing will be sent to applicants." : `${picked.size} task${picked.size > 1 ? "s" : ""}, ${minutes} minutes in all.`}
          {" "}An unbarred must-have no ticked task tests needs direct evidence of any level instead.
        </p>
      )}
      {tasks.not_assessable.length > 0 && (
        <p className="text-sm text-muted">No task tests: {tasks.not_assessable.join(", ")}.</p>
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
