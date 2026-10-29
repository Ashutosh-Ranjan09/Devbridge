import Link from "next/link";

export default function RecruiterLayout({ children }: LayoutProps<"/recruiter">) {
  return (
    <>
      <nav className="border-b border-line">
        <div className="mx-auto flex w-full max-w-3xl gap-5 px-4 py-2 text-sm">
          <Link href="/recruiter" className="text-accent hover:underline">Jobs</Link>
          <Link href="/recruiter/jobs/new" className="text-accent hover:underline">New job</Link>
        </div>
      </nav>
      {children}
    </>
  );
}
