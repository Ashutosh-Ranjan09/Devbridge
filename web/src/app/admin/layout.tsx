import Link from "next/link";

const LINKS = [
  ["/admin", "System"],
  ["/admin/accounts", "Accounts"],
  ["/admin/catalogue", "Checks & tasks"],
  ["/admin/quarantine", "Quarantine"],
] as const;

export default function AdminLayout({ children }: LayoutProps<"/admin">) {
  return (
    <>
      <nav className="border-b border-line">
        <div className="mx-auto flex w-full max-w-3xl gap-5 overflow-x-auto px-4 py-2 text-sm">
          {LINKS.map(([href, label]) => (
            <Link key={href} href={href} className="whitespace-nowrap text-accent hover:underline">{label}</Link>
          ))}
        </div>
      </nav>
      {children}
    </>
  );
}
