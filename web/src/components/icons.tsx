/** The brand mark and the line icons every page uses. No "use client": server and
 * client components can both render them. */

export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <defs>
        <linearGradient id="mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#0f3d3a" />
          <stop offset="1" stopColor="#14b8a6" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#mark)" />
      <path d="M10 8.5h5.5a7.5 7.5 0 0 1 0 15H10z" fill="none" stroke="#fff" strokeWidth="2.6" />
      <circle cx="23.5" cy="8.5" r="2.5" fill="#f59e0b" />
    </svg>
  );
}

type IconProps = { className?: string };
const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export const Icon = {
  Mail: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <rect x="3" y="5" width="18" height="14" rx="2.5" /><path d="m4 7 8 6 8-6" />
    </svg>
  ),
  Lock: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <rect x="4.5" y="10.5" width="15" height="10" rx="2.5" /><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
    </svg>
  ),
  User: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <circle cx="12" cy="8" r="4" /><path d="M4.5 20a7.5 7.5 0 0 1 15 0" />
    </svg>
  ),
  Building: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <path d="M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16M16 9h2a2 2 0 0 1 2 2v10M3 21h18M8 7h4M8 11h4M8 15h4" />
    </svg>
  ),
  Code: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <path d="m8 7-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16" />
    </svg>
  ),
  Briefcase: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <rect x="3" y="7" width="18" height="13" rx="2.5" /><path d="M8.5 7V5.5a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2V7M3 12.5h18" />
    </svg>
  ),
  Eye: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <path d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7Z" /><circle cx="12" cy="12" r="3" />
    </svg>
  ),
  EyeOff: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <path d="M10.6 5.1A9.7 9.7 0 0 1 12 5c6 0 9.5 7 9.5 7a16 16 0 0 1-2.6 3.5M6.6 6.6C3.9 8.3 2.5 12 2.5 12s3.5 7 9.5 7a9 9 0 0 0 5.4-1.6M3 3l18 18M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </svg>
  ),
  Check: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke} strokeWidth={3.2}>
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </svg>
  ),
  Chevron: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  ),
  Clock: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />
    </svg>
  ),
  File: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 14.5l2 2 4-4" />
    </svg>
  ),
  Arrow: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  ),
  Spark: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6" />
    </svg>
  ),
  Upload: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <path d="M12 15V4M7 9l5-5 5 5M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </svg>
  ),
  Globe: ({ className }: IconProps) => (
    <svg viewBox="0 0 24 24" className={className} aria-hidden {...stroke}>
      <circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </svg>
  ),
};
