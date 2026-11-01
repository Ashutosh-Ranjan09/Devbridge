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
          h3: (p) => <h3 className="mt-3 font-semibold" {...p} />,
          ol: (p) => <ol className="list-decimal space-y-1 pl-6" {...p} />,
          pre: (p) => <pre className="overflow-x-auto rounded-xl bg-[#1e1e1e] p-4 text-[13px] text-[#d4d4d4] [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-inherit" {...p} />,
          code: (p) => <code className="rounded bg-background px-1.5 py-0.5 font-mono text-[13px] ring-1 ring-line" {...p} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
