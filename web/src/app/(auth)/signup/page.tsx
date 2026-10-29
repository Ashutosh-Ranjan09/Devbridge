import { Card, Page } from "@/components/ui";

import { SignupForm } from "./form";

export default function SignupPage() {
  return (
    <Page title="Create an account">
      <Card><SignupForm /></Card>
    </Page>
  );
}
