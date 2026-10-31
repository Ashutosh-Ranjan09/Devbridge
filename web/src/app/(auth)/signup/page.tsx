import type { Metadata } from "next";

import { AuthShell } from "@/components/auth";

export const metadata: Metadata = { title: "Create an account · DevBridge" };

export default function SignupPage() {
  return <AuthShell initial="signup" />;
}
