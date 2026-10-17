import { BookOpen, CalendarCheck, Mic } from "lucide-react";

import { Logo } from "@/components/Logo";

const POINTS = [
  { icon: BookOpen, text: "Answers from your own documents, with sources" },
  { icon: CalendarCheck, text: "Books appointments — and always confirms first" },
  { icon: Mic, text: "Customers can chat or simply talk" },
];

/** Split-screen layout for login/signup: form on the left, brand panel on the right. */
export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="flex flex-col px-6 py-8 sm:px-12">
        <Logo />
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-12">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-2 text-sm text-muted">{subtitle}</p>
          <div className="mt-8">{children}</div>
        </div>
      </div>

      <div className="relative hidden overflow-hidden bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-600 lg:block">
        <div className="pointer-events-none absolute inset-0 bg-grid opacity-30" />
        <div className="relative flex h-full flex-col justify-center px-16 text-white">
          <h2 className="max-w-md text-3xl font-semibold leading-tight tracking-tight">
            Your front desk, answering every customer — day and night.
          </h2>
          <ul className="mt-10 space-y-5">
            {POINTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-indigo-50">
                <span className="flex size-9 items-center justify-center rounded-lg bg-white/15 backdrop-blur">
                  <Icon className="size-4" />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
