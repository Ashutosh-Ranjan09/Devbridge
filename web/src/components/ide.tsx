"use client";

import dynamic from "next/dynamic";

/** The task workspace, browser only: its code starts from this browser's saved draft,
 * which the server cannot see, so rendering it there would not match. */
export const Workspace = dynamic(() => import("./workspace"), {
  ssr: false,
  loading: () => <div className="h-[calc(100dvh-56px)] animate-pulse bg-line" />,
});
