import Link from "next/link";
import { Suspense } from "react";

import { Icon } from "@/components/icons";
import { NewJobForm } from "@/components/recruiter";
import { requireRecruiter } from "@/lib/recruiter";

const STEPS = [
  { title: "Paste the description", text: "The whole job description, as you'd post it." },
  { title: "Review the skills", text: "Each proposed skill comes with the words it was found in. Keep, change or drop it." },
  { title: "Pick the assessment", text: "Choose the coding tasks every applicant gets, the same for all." },
  { title: "Open applications", text: "Developers apply with verified CVs and skills. You decide." },
];

export default function NewJobPage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
      <Link href="/recruiter" className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-accent">
        <Icon.Chevron className="size-4 rotate-90" /> All jobs
      </Link>
      <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Post a new job</h1>
      <p className="mt-1 mb-8 text-muted">Start from the job description. Nothing goes live until you&apos;ve confirmed it.</p>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="rounded-2xl border border-line bg-panel p-5 sm:p-7">
          <Suspense fallback={<div className="h-96 animate-pulse rounded-xl bg-line" />}>
            <Form />
          </Suspense>
        </section>
        <aside className="lg:sticky lg:top-20 lg:self-start">
          <div className="rounded-2xl border border-line bg-panel p-5 sm:p-6">
            <h2 className="font-semibold">How it works</h2>
            <ol className="mt-5">
              {STEPS.map((s, i) => (
                <li key={s.title} className="relative flex gap-3.5 pb-6 last:pb-0">
                  {i < STEPS.length - 1 && <span className="absolute top-8 bottom-0 left-[15px] w-px bg-line" aria-hidden />}
                  <span className={`grid size-8 shrink-0 place-items-center rounded-full text-sm font-bold ${i === 0 ? "bg-accent text-on-accent" : "bg-background text-muted ring-1 ring-line"}`}>{i + 1}</span>
                  <div className="pt-1">
                    <p className={`text-sm font-semibold ${i === 0 ? "" : "text-muted"}`}>{s.title}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-muted">{s.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </aside>
      </div>
    </main>
  );
}

async function Form() {
  const me = await requireRecruiter();
  return <NewJobForm orgs={me.orgs.map((o) => ({ id: o.id, name: o.name }))} />;
}
