"use client";

import { useActionState, useState } from "react";

import { addProof, removeProof, uploadCv } from "@/app/candidate/actions";
import type { FormState } from "@/lib/definitions";

import { Icon } from "./icons";
import { Button } from "./ui";

const PLATFORMS = [["github", "GitHub"], ["codeforces", "Codeforces"], ["leetcode", "LeetCode"], ["codechef", "CodeChef"]] as const;

const input = "h-11 w-full rounded-xl border border-line bg-background px-3.5 text-sm outline-none transition focus:border-accent focus:ring-4 focus:ring-accent/15";

/** `saved`: the handles typed last time. A refused upload shows what was typed instead;
 * the file itself must be chosen again (a browser never refills a file input). */
export function UploadCv({ saved, again }: { saved: Record<string, string>; again: boolean }) {
  const [state, action, pending] = useActionState(uploadCv, undefined);
  // The chosen file's name, for the action state it was chosen under: React clears the
  // file input when an action returns, so a name from an earlier state is not shown.
  const [chosen, setChosen] = useState<{ name: string; under: typeof state } | null>(null);
  const [dragging, setDragging] = useState(false);
  const file = chosen && chosen.under === state ? chosen.name : null;
  const value = (k: string) => state?.values?.[k] ?? saved[k];
  const fileErrors = state?.errors?.cv;
  return (
    <form action={action} className="space-y-6">
      <div>
        <div
          className={`relative flex flex-col items-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition ${
            dragging ? "border-accent bg-accent/5" : fileErrors ? "border-danger/50" : file ? "border-accent/60 bg-accent/5" : "border-line hover:border-accent/60"}`}
        >
          {/* Covers the whole zone, so a click or a dropped file lands on the input itself. */}
          <input
            type="file" name="cv" accept=".pdf,.docx" aria-label="Your CV, PDF or Word"
            className="absolute inset-0 cursor-pointer opacity-0"
            onChange={(e) => setChosen(e.target.files?.[0] ? { name: e.target.files[0].name, under: state } : null)}
            onDragEnter={() => setDragging(true)} onDragLeave={() => setDragging(false)} onDrop={() => setDragging(false)}
          />
          <span className="grid size-12 place-items-center rounded-full bg-accent/10 text-accent">
            {file ? <Icon.File className="size-6" /> : <Icon.Upload className="size-6" />}
          </span>
          {file ? (
            <>
              <p className="mt-3 font-semibold break-all">{file}</p>
              <p className="mt-1 text-sm text-muted">Ready to check. Click to choose a different file.</p>
            </>
          ) : (
            <>
              <p className="mt-3 font-semibold">Drop your CV here, or <span className="text-accent">browse</span></p>
              <p className="mt-1 text-sm text-muted">PDF or Word, up to 5 MB</p>
            </>
          )}
        </div>
        {fileErrors?.map((e) => <p key={e} className="mt-2 text-sm text-danger">{e}</p>)}
      </div>

      <fieldset>
        <legend className="font-semibold">Your coding profiles <span className="font-normal text-muted">(optional)</span></legend>
        <p className="mt-1 mb-3 text-sm text-muted">
          Add any your CV leaves out.
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {PLATFORMS.map(([name, label]) => (
            <label key={name} className="block">
              <span className="mb-1 block text-sm font-medium">{label}</span>
              <input name={name} defaultValue={value(name)} placeholder="username" autoComplete="off"
                aria-invalid={state?.errors?.[name] ? true : undefined} className={input} />
              {state?.errors?.[name]?.map((e) => <span key={e} className="mt-1 block text-sm text-danger">{e}</span>)}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="block">
        <span className="font-semibold">A note for recruiters <span className="font-normal text-muted">(optional)</span></span>
        <span className="mt-1 mb-3 block text-sm text-muted">
          Shown to recruiters beside your CV.
        </span>
        <textarea name="note" rows={3} maxLength={2000} defaultValue={state?.values?.note}
          placeholder="For example: my main project is in a private repository; happy to walk through it."
          className="w-full rounded-xl border border-line bg-background px-3.5 py-3 text-sm outline-none transition focus:border-accent focus:ring-4 focus:ring-accent/15" />
        {state?.errors?.note?.map((e) => <span key={e} className="block text-sm text-danger">{e}</span>)}
      </label>

      {state?.message && <p role="alert" className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{state.message}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <Button pending={pending}>{again ? "Check this CV" : "Verify my CV"}</Button>
        <span className="text-sm text-muted">Takes about a minute.</span>
      </div>
    </form>
  );
}

/** "Replace CV": the upload form, opened on demand above the current CV. */
export function ReplaceCv({ saved }: { saved: Record<string, string> }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(!open)}
        className="flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition hover:brightness-110">
        {!open && <Icon.Upload className="size-4" />} {open ? "Cancel" : "Replace CV"}
      </button>
      {open && (
        <div className="w-full rounded-2xl border border-accent/40 bg-panel p-5 sm:p-6">
          <p className="mb-4 text-sm text-muted">The new CV replaces this one everywhere: only it counts for your skills, and your test results stay. Proofs start fresh for it. At most 3 a day.</p>
          <UploadCv saved={saved} again />
        </div>
      )}
    </>
  );
}

export type ProofFile = { id: string; fileName: string };

/** One CV line that a document can back: its proofs, and a way to add one. */
export function ProofItem({ claimId, kind, title, sub, proofs }: {
  claimId: string | null; kind: "Experience" | "Certificate" | "Education" | "Other";
  title: string; sub?: string; proofs: ProofFile[];
}) {
  const [adding, setAdding] = useState(false);
  const Glyph = Icon[kind === "Experience" ? "Briefcase" : kind === "Certificate" ? "Check" : kind === "Education" ? "Building" : "File"];
  return (
    <li className="rounded-xl border border-line p-4">
      <div className="flex items-start gap-3">
        <span className={`grid size-9 shrink-0 place-items-center rounded-lg ${proofs.length ? "bg-ok/10 text-ok" : "bg-highlight/15 text-[#b45309] dark:text-highlight"}`}>
          <Glyph className="size-[18px]" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-medium leading-snug">{title}</p>
          {sub && <p className="text-sm text-muted">{sub}</p>}
        </div>
        {!adding && (
          <button type="button" onClick={() => setAdding(true)}
            className={`shrink-0 rounded-lg px-3 py-1.5 text-sm font-semibold transition ${proofs.length ? "text-accent hover:bg-accent/10" : "bg-accent text-on-accent hover:brightness-110"}`}>
            {proofs.length ? "+ Add" : "Add proof"}
          </button>
        )}
      </div>
      {proofs.length > 0 && (
        <ul className="mt-3 space-y-1.5 pl-12">
          {proofs.map((p) => <ProofChip key={p.id} proof={p} />)}
        </ul>
      )}
      {adding && <AddProof claimId={claimId} label={title} free={claimId === null} onDone={() => setAdding(false)} />}
    </li>
  );
}

function AddProof({ claimId, label, free, onDone }: { claimId: string | null; label: string; free: boolean; onDone: () => void }) {
  const [state, action, pending] = useActionState(async (prev: FormState, form: FormData) => {
    const next = await addProof(claimId, prev, form);
    if (!next) onDone();
    return next;
  }, undefined);
  return (
    <form action={action} className="mt-3 space-y-2 pl-12">
      {free
        ? <input name="label" defaultValue={state?.values?.label} placeholder="What does it prove? e.g. Internship offer letter"
            className="h-10 w-full rounded-lg border border-line bg-background px-3 text-sm outline-none focus:border-accent" />
        : <input type="hidden" name="label" value={label} />}
      <input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg"
        className="block w-full text-sm text-muted file:mr-3 file:rounded-lg file:border-0 file:bg-accent/10 file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-accent" />
      {[...(state?.errors?.file ?? []), ...(state?.errors?.label ?? [])].map((e) => <p key={e} className="text-sm text-danger">{e}</p>)}
      {state?.message && <p className="text-sm text-danger">{state.message}</p>}
      <div className="flex items-center gap-2">
        <Button pending={pending}>Upload</Button>
        <button type="button" onClick={onDone} className="rounded-lg px-3 py-2 text-sm text-muted hover:text-foreground">Cancel</button>
        <span className="text-xs text-muted">PDF, PNG or JPG · 5 MB</span>
      </div>
    </form>
  );
}

function ProofChip({ proof }: { proof: ProofFile }) {
  const [state, action, pending] = useActionState(removeProof.bind(null, proof.id), undefined);
  return (
    <li className="flex items-center gap-2 text-sm">
      <Icon.File className="size-4 shrink-0 text-ok" />
      <a href={`/files/proof/${proof.id}`} target="_blank" rel="noopener" className="min-w-0 truncate font-medium hover:text-accent hover:underline">
        {proof.fileName}
      </a>
      <form action={action} className="ml-auto shrink-0">
        <button type="submit" disabled={pending} aria-label={`Remove ${proof.fileName}`}
          onClick={(e) => { if (!confirm(`Remove ${proof.fileName}?`)) e.preventDefault(); }}
          className="rounded px-1.5 text-muted transition hover:bg-danger/10 hover:text-danger disabled:opacity-50">
          {pending ? "…" : "×"}
        </button>
      </form>
      {state?.message && <span className="text-xs text-danger">{state.message}</span>}
    </li>
  );
}
