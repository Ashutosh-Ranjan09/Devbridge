import Link from "next/link";

const LINKS = [
  ["/candidate", "Overview"],
  ["/candidate/cv", "CV"],
  ["/candidate/skills", "Skills"],
  ["/candidate/assessments", "Assessments"],
] as const;

export default function CandidateLayout({ children }: LayoutProps<"/candidate">) {
  return (
    <>
      <nav className="border-b border-line">
        <div className="mx-auto flex w-full max-w-3xl gap-5 overflow-x-auto px-4 py-2 text-sm">
          {LINKS.map(([href, label]) => (
            <Link key={href} href={href} className="text-accent hover:underline">{label}</Link>
          ))}
        </div>
      </nav>
      {children}
    </>
  );
}
