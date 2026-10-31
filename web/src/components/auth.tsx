"use client";

import { type ReactNode, useState } from "react";

import { LoginForm } from "@/app/(auth)/login/form";
import { SignupForm } from "@/app/(auth)/signup/form";
import { Icon, Mark } from "@/components/icons";

/** The login and signup pages: one card, both forms mounted, and a panel that slides
 * over whichever is not in use. Switching rewrites the URL without a navigation, so
 * nothing typed in either form is lost and a refresh opens the same side. */

export type AuthMode = "login" | "signup";

const cx = (...c: (string | false | undefined)[]) => c.filter(Boolean).join(" ");
const EASE = "duration-700 ease-[cubic-bezier(0.65,0,0.35,1)]";

export function AuthShell({ initial }: { initial: AuthMode }) {
  const [mode, setMode] = useState<AuthMode>(initial);
  const signup = mode === "signup";

  function show(next: AuthMode) {
    setMode(next);
    window.history.replaceState(null, "", next === "login" ? "/login" : "/signup");
  }

  return (
    <main className="auth-backdrop flex flex-1 items-center justify-center px-4 py-4 md:py-6">
      <div className="relative w-full max-w-md overflow-hidden rounded-[28px] bg-panel shadow-[0_30px_80px_-30px_rgba(15,61,58,0.45)] ring-1 ring-line md:h-[min(680px,calc(100dvh-6.5rem))] md:min-h-[460px] md:max-w-5xl">
        {/* Log in: left half; slides right and fades out when signing up. */}
        <section
          inert={signup}
          className={cx(
            "transition-all md:absolute md:inset-y-0 md:left-0 md:w-1/2", EASE,
            signup ? "max-md:hidden md:pointer-events-none md:translate-x-full md:opacity-0" : "z-20",
          )}
        >
          <FormFrame>
            <LoginForm onSwitch={() => show("signup")} />
          </FormFrame>
        </section>

        {/* Sign up: starts under the login form, slides into the right half. */}
        <section
          inert={!signup}
          className={cx(
            "transition-all md:absolute md:inset-y-0 md:left-0 md:w-1/2", EASE,
            signup ? "z-20 md:translate-x-full" : "max-md:hidden md:pointer-events-none md:opacity-0",
          )}
        >
          <FormFrame>
            <SignupForm onSwitch={() => show("login")} />
          </FormFrame>
        </section>

        {/* The sliding panel: right half for log in, left half for sign up. */}
        <div
          className={cx(
            "absolute inset-y-0 left-1/2 z-30 hidden w-1/2 overflow-hidden transition-all md:block", EASE,
            signup ? "-translate-x-full rounded-r-[140px]" : "rounded-l-[140px]",
          )}
        >
          <div
            className={cx(
              "auth-panel absolute inset-y-0 -left-full w-[200%] text-white transition-transform", EASE,
              signup && "translate-x-1/2",
            )}
          >
            <Overlay
              side="left" visible={signup}
              eyebrow="Already have an account?"
              title="Welcome back"
              body="Log in to see your verified skills, take your assessments and follow your applications."
              action="Log in"
              onAction={() => show("login")}
            />
            <Overlay
              side="right" visible={!signup}
              eyebrow="New to DevBridge?"
              title="Let your work speak for you"
              body="Your CV, checked against the places your work actually lives."
              action="Create account"
              onAction={() => show("signup")}
            >
              <ul className="mt-8 space-y-3 text-left text-sm text-white/90">
                {[
                  "Checked against GitHub, Codeforces, LeetCode and live deployments",
                  "Skills measured from evidence, not keywords",
                  "Coding tasks unique to you, and equally hard for everyone",
                ].map((line) => (
                  <li key={line} className="flex items-start gap-3">
                    <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-highlight text-[#1f1300]">
                      <Icon.Check className="size-3" />
                    </span>
                    {line}
                  </li>
                ))}
              </ul>
            </Overlay>
          </div>
        </div>
      </div>
    </main>
  );
}

/** Scrolls if a form outgrows the card (a recruiter's fields plus errors), and centres
 * it when it does not. */
function FormFrame({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full flex-col overflow-y-auto px-6 py-8 sm:px-12 short:py-5">
      <div className="my-auto w-full">{children}</div>
    </div>
  );
}

function Overlay({
  side, visible, eyebrow, title, body, action, onAction, children,
}: {
  side: "left" | "right"; visible: boolean; eyebrow: string; title: string; body: string;
  action: string; onAction: () => void; children?: ReactNode;
}) {
  const hidden = side === "left" ? "-translate-x-[20%]" : "translate-x-[20%]";
  return (
    <div
      aria-hidden={!visible}
      className={cx(
        "absolute inset-y-0 flex w-1/2 flex-col items-center justify-center px-14 text-center transition-transform", EASE,
        side === "left" ? "left-0" : "right-0",
        !visible && hidden,
      )}
    >
      <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-medium tracking-wide text-white/85 ring-1 ring-white/20">
        {eyebrow}
      </span>
      <h2 className="mt-5 text-3xl font-bold tracking-tight">{title}</h2>
      <p className="mt-3 max-w-xs text-base leading-relaxed text-white/80">{body}</p>
      <button
        type="button" onClick={onAction} tabIndex={visible ? 0 : -1}
        className="mt-8 rounded-full border-2 border-white/80 px-9 py-2.5 text-sm font-semibold tracking-wide uppercase transition hover:bg-white hover:text-[#0f3d3a] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
      >
        {action}
      </button>
      {children}
    </div>
  );
}

/** The top of each form: the mark, a title and one line under it. */
export function AuthHeading({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="mb-7 text-center short:mb-5 tight:mb-4">
      <Mark className="mx-auto mb-4 size-11 short:mb-3 short:size-9 tight:hidden" />
      <h1 className="text-3xl font-bold tracking-tight text-brand short:text-2xl">{title}</h1>
      <p className="mt-2 text-sm text-muted tight:hidden">{subtitle}</p>
    </div>
  );
}


/** An input with an icon inside it. The label is for screen readers; the placeholder
 * and the icon say the same to everyone else. */
export function AuthField({
  label, name, icon, type = "text", defaultValue, errors, autoComplete,
}: {
  label: string; name: string; icon: keyof typeof Icon; type?: string; defaultValue?: string;
  errors?: string[]; autoComplete?: string;
}) {
  const [revealed, setRevealed] = useState(false);
  const secret = type === "password";
  const Glyph = Icon[icon];
  return (
    <label className="block">
      <span className="sr-only">{label}</span>
      <span className="relative block">
        <Glyph className="pointer-events-none absolute top-1/2 left-4 size-[18px] -translate-y-1/2 text-muted" />
        <input
          name={name} type={secret && revealed ? "text" : type} defaultValue={defaultValue}
          autoComplete={autoComplete} placeholder={label}
          aria-invalid={errors ? true : undefined}
          className={cx(
            "h-12 w-full rounded-xl border bg-background pl-11 short:h-11 text-[15px] outline-none transition placeholder:text-muted/80",
            "focus:border-brand focus:ring-4 focus:ring-brand/15",
            secret ? "pr-12" : "pr-4",
            errors ? "border-danger" : "border-line",
          )}
        />
        {secret && (
          <button
            type="button" onClick={() => setRevealed((r) => !r)}
            aria-label={revealed ? "Hide password" : "Show password"}
            className="absolute top-1/2 right-3 grid size-8 -translate-y-1/2 place-items-center rounded-lg text-muted transition hover:text-foreground"
          >
            {revealed ? <Icon.EyeOff className="size-[18px]" /> : <Icon.Eye className="size-[18px]" />}
          </button>
        )}
      </span>
      {errors?.map((e) => <span key={e} className="mt-1.5 block pl-1 text-sm text-danger">{e}</span>)}
    </label>
  );
}

export function AuthSubmit({ children, pending }: { children: ReactNode; pending?: boolean }) {
  return (
    <button
      type="submit" disabled={pending}
      className="auth-button h-12 w-full short:h-11 rounded-xl text-[15px] font-semibold text-white shadow-[0_10px_24px_-10px_rgba(15,118,110,0.7)] transition hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:opacity-60"
    >
      {pending ? "Working…" : children}
    </button>
  );
}

export function AuthMessage({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
      {children}
    </p>
  );
}

/** Below the form on a phone, where the sliding panel is not shown. */
export function AuthSwitch({ prompt, action, onClick }: { prompt: string; action: string; onClick: () => void }) {
  return (
    <p className="mt-6 text-center text-sm text-muted md:hidden">
      {prompt}{" "}
      <button type="button" onClick={onClick} className="font-semibold text-brand hover:underline">{action}</button>
    </p>
  );
}
