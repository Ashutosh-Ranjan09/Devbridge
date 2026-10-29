import type { ReactNode } from "react";

/** The few pieces every page uses. Tailwind classes, no component library. */

export function Page({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8">
      <h1 className="mb-6 text-2xl font-semibold">{title}</h1>
      {children}
    </main>
  );
}

export function Card({ children }: { children: ReactNode }) {
  return <section className="rounded-lg border border-line bg-panel p-5">{children}</section>;
}

export function Field({
  label, name, type = "text", defaultValue, errors, autoComplete,
}: {
  label: string; name: string; type?: string; defaultValue?: string; errors?: string[]; autoComplete?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      <input
        name={name} type={type} defaultValue={defaultValue} autoComplete={autoComplete}
        aria-invalid={errors ? true : undefined}
        className="w-full rounded-md border border-line bg-background px-3 py-2 outline-none focus:border-accent"
      />
      {errors?.map((e) => <span key={e} className="mt-1 block text-sm text-danger">{e}</span>)}
    </label>
  );
}

export function Button({ children, pending }: { children: ReactNode; pending?: boolean }) {
  return (
    <button
      type="submit" disabled={pending}
      className="rounded-md bg-accent px-4 py-2 font-medium text-on-accent disabled:opacity-60"
    >
      {pending ? "Working…" : children}
    </button>
  );
}

export function Loading() {
  return <p className="text-muted">Loading…</p>;
}
