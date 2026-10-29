import { Card, Page } from "@/components/ui";

import { LoginForm } from "./form";

export default function LoginPage() {
  return (
    <Page title="Log in">
      <Card><LoginForm /></Card>
    </Page>
  );
}
