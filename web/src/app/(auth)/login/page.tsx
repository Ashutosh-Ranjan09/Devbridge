import type { Metadata } from "next";

import { AuthShell } from "@/components/auth";

export const metadata: Metadata = { title: "Log in · DevBridge" };

export default function LoginPage() {
  return <AuthShell initial="login" />;
}
