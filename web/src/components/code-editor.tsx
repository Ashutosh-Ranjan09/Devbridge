"use client";

import { python } from "@codemirror/lang-python";
import { vscodeDark } from "@uiw/codemirror-theme-vscode";
import CodeMirror, { EditorView } from "@uiw/react-codemirror";

const EXTENSIONS = [
  python(),
  EditorView.lineWrapping,
  EditorView.theme({
    "&": { fontSize: "14px", height: "100%" },
    ".cm-scroller": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", lineHeight: "1.6" },
    ".cm-gutters": { borderRight: "none" },
  }),
];

/** CodeMirror with Python, a dark theme and Ctrl/⌘+Enter to run. Loaded in the browser
 * only (next/dynamic, ssr: false): an editor has nothing to render on the server. */
export default function CodeEditor({ value, onChange, onRun }: {
  value: string; onChange: (code: string) => void; onRun: () => void;
}) {
  return (
    // Caught before CodeMirror sees it, where Mod-Enter would insert a blank line.
    <div className="h-full" onKeyDownCapture={(e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        e.stopPropagation();
        onRun();
      }
    }}>
      <CodeMirror
        value={value} onChange={onChange} extensions={EXTENSIONS} theme={vscodeDark} height="100%"
        className="h-full" indentWithTab
        basicSetup={{ foldGutter: false, highlightActiveLine: true, bracketMatching: true, closeBrackets: true, autocompletion: true }}
        aria-label="Code editor"
      />
    </div>
  );
}
