import ReactMarkdown from "react-markdown";

/** A task's story and requirements. react-markdown never renders raw HTML (no
 * rehype-raw here, and none may be added): text from a module is shown, not run. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="space-y-3 leading-relaxed">
      <ReactMarkdown
        components={{
          h2: (p) => <h2 className="mt-4 text-lg font-semibold" {...p} />,
          ul: (p) => <ul className="list-disc space-y-1 pl-6" {...p} />,
          code: (p) => <code className="rounded bg-background px-1 font-mono text-sm" {...p} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
