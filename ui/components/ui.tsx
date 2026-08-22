/**
 * Small shared presentational primitives for the B3 console.
 *
 * Deliberately dependency-free (no component library) so the UI ships as plain source the
 * reviewer can read end to end.
 */

import type { ReactNode } from "react";

export function Panel({
  title,
  children,
  right,
}: {
  title: string;
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-ink-200 bg-white shadow-panel">
      <header className="flex items-center justify-between border-b border-ink-100 px-4 py-3">
        <h2 className="text-sm font-semibold tracking-wide text-ink-700">{title}</h2>
        {right}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad" | "info";
}) {
  const tones: Record<string, string> = {
    neutral: "bg-ink-100 text-ink-700",
    good: "bg-emerald-100 text-emerald-800",
    warn: "bg-amber-100 text-amber-800",
    bad: "bg-rose-100 text-rose-800",
    info: "bg-regblue-100 text-regblue-800",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export function NotAdviceBanner({ disclaimer }: { disclaimer?: string }) {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <p className="font-semibold">Decision-support, not financial advice.</p>
      <p className="mt-1 text-amber-800">
        {disclaimer ||
          "This material is for the relationship manager only. The RM is the human checker and is responsible for any advice given to the client."}
      </p>
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-800">
      {message}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-ink-400">{children}</p>;
}
