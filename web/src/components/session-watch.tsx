"use client";

import { useEffect } from "react";

/** One browser holds one session cookie, so logging in or out in one tab changes who
 * every other tab is. Next keeps the root layout across in-app navigation, so a tab's
 * header could name one person above another's page. Each tab says who it shows; a tab
 * showing someone else reloads. */
export function SessionWatch({ userId }: { userId: string | null }) {
  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel("devbridge-session");
    channel.onmessage = (e) => { if (e.data !== userId) location.reload(); };
    channel.postMessage(userId);
    return () => channel.close();
  }, [userId]);
  return null;
}
