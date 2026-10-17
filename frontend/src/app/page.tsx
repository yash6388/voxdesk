import {
  ArrowRight,
  Bot,
  BookOpen,
  Brain,
  CalendarDays,
  FileUp,
  Mic,
  Network,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { Logo } from "@/components/Logo";
import { SiteFooter } from "@/components/SiteFooter";
import { ButtonLink } from "@/components/ui/Button";
import { Badge } from "@/components/ui/primitives";
import { BRAND_TINT, cn } from "@/lib/utils";

const FEATURES = [
  {
    icon: BookOpen,
    title: "Grounded answers",
    body: "Hybrid search over your own documents — prices, hours, policies — with citations on every answer. No guessing.",
    soon: false,
  },
  {
    icon: Brain,
    title: "Remembers the conversation",
    body: "Follow-ups like “and how long does it take?” just work. Every conversation is checkpointed and resumable.",
    soon: false,
  },
  {
    icon: ShieldCheck,
    title: "Isolated per business",
    body: "Each business gets its own knowledge base and conversations, strictly separated at the data layer.",
    soon: false,
  },
  {
    icon: CalendarDays,
    title: "Books appointments",
    body: "Checks real availability and books, reschedules or cancels — always asking the customer to confirm first.",
    soon: false,
  },
  {
    icon: Network,
    title: "Specialist agents",
    body: "Every request goes to the right specialist — one that knows your business, one that manages your calendar.",
    soon: true,
  },
  {
    icon: Mic,
    title: "Talks, not just types",
    body: "Real-time voice: speech-to-text, the same agents, and natural text-to-speech replies.",
    soon: true,
  },
];

const STEPS = [
  {
    icon: FileUp,
    title: "Upload your documents",
    body: "Drop in your price list, FAQs and policies. VoxDesk chunks and indexes them in seconds.",
  },
  {
    icon: CalendarDays,
    title: "Set up services",
    body: "Add your services and opening hours so the agent can book real appointments.",
  },
  {
    icon: Sparkles,
    title: "Let customers ask",
    body: "Customers chat or talk to your agent, and get instant, accurate answers 24/7.",
  },
];

export default function Landing() {
  return (
    <div className="relative overflow-hidden">
      {/* Background glow */}
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[640px] bg-grid [mask-image:linear-gradient(to_bottom,black,transparent)]" />
      <div className="pointer-events-none absolute left-1/2 top-[-200px] -z-10 h-[500px] w-[900px] -translate-x-1/2 rounded-full bg-gradient-to-r from-indigo-500/25 via-violet-500/25 to-fuchsia-500/25 blur-3xl" />

      {/* Nav */}
      <header className="mx-auto flex max-w-6xl items-center justify-between px-4 py-5">
        <Logo />
        <nav className="flex items-center gap-2">
          <a href="#features" className="hidden px-3 text-sm text-muted hover:text-foreground sm:block">
            Features
          </a>
          <a href="#how" className="hidden px-3 text-sm text-muted hover:text-foreground sm:block">
            How it works
          </a>
          <ButtonLink href="/dashboard" size="sm">
            Open dashboard <ArrowRight className="size-4" />
          </ButtonLink>
        </nav>
      </header>

      {/* Hero */}
      <section className="mx-auto grid max-w-6xl items-center gap-12 px-4 pb-24 pt-12 lg:grid-cols-2 lg:pt-20">
        <div className="animate-fade-in">
          <Badge tone="brand" className="mb-5">
            <Sparkles className="size-3" /> Multi-agent AI for small businesses
          </Badge>
          <h1 className="text-4xl font-semibold leading-tight tracking-tight sm:text-5xl lg:text-6xl">
            Every question answered.
            <br />
            <span className="text-gradient">Every booking handled.</span>
          </h1>
          <p className="mt-6 max-w-xl text-lg text-muted">
            VoxDesk gives your salon, clinic or restaurant an AI agent that answers customers from your
            own documents and books their appointments — by chat today, by voice soon.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <ButtonLink href="/dashboard" size="lg">
              Get started <ArrowRight className="size-4" />
            </ButtonLink>
            <ButtonLink href="#how" size="lg" variant="secondary">
              See how it works
            </ButtonLink>
          </div>
        </div>

        <ChatPreview />
      </section>

      {/* Features */}
      <section id="features" className="mx-auto max-w-6xl px-4 py-24">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            An assistant that actually knows your business
          </h2>
          <p className="mt-4 text-muted">
            Not a generic chatbot. Answers come from your documents, with sources, and the agent says
            “I don’t know” instead of making things up.
          </p>
        </div>
        <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, body, soon }) => (
            <div
              key={title}
              className="group rounded-2xl border border-border bg-surface p-6 transition hover:-translate-y-0.5 hover:shadow-lg hover:shadow-indigo-500/5"
            >
              <div className="flex items-center justify-between">
                <span className={cn("flex size-10 items-center justify-center rounded-xl", BRAND_TINT)}>
                  <Icon className="size-5" />
                </span>
                {soon && <Badge>Coming soon</Badge>}
              </div>
              <h3 className="mt-4 font-semibold">{title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="mx-auto max-w-6xl px-4 pb-24">
        <h2 className="text-center text-3xl font-semibold tracking-tight sm:text-4xl">
          Live in three steps
        </h2>
        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, body }, i) => (
            <div key={title} className="relative rounded-2xl border border-border bg-surface p-6">
              <span className="absolute right-5 top-4 text-5xl font-bold text-zinc-100 dark:text-zinc-800">
                {i + 1}
              </span>
              <Icon className="relative size-6 text-violet-600 dark:text-violet-400" />
              <h3 className="relative mt-4 font-semibold">{title}</h3>
              <p className="relative mt-2 text-sm text-muted">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-6xl px-4 pb-24">
        <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-indigo-600 via-violet-600 to-fuchsia-600 px-8 py-14 text-center text-white">
          <div className="pointer-events-none absolute inset-0 bg-grid opacity-30" />
          <h2 className="relative text-3xl font-semibold tracking-tight">
            Give your front desk a superpower
          </h2>
          <p className="relative mx-auto mt-3 max-w-xl text-indigo-100">
            Create a business, upload a document, and chat with your agent in under a minute.
          </p>
          <ButtonLink
            href="/dashboard"
            size="lg"
            variant="secondary"
            className="relative mt-8 border-transparent bg-white text-zinc-900 hover:bg-zinc-100"
          >
            Open dashboard <ArrowRight className="size-4" />
          </ButtonLink>
        </div>
      </section>

      <SiteFooter />
    </div>
  );
}

/** Static illustration of a real conversation, shown in the hero. */
function ChatPreview() {
  return (
    <div className="relative animate-fade-in [animation-delay:150ms]">
      <div className="absolute -inset-4 -z-10 rounded-[2rem] bg-gradient-to-br from-indigo-500/20 to-fuchsia-500/20 blur-2xl" />
      <div className="animate-float rounded-2xl border border-border bg-surface p-5 shadow-2xl shadow-indigo-500/10">
        <div className="flex items-center gap-3 border-b border-border pb-4">
          <span className={cn("flex size-9 items-center justify-center rounded-full", BRAND_TINT)}>
            <Bot className="size-5" />
          </span>
          <div>
            <div className="text-sm font-semibold">Glow Studio Salon</div>
            <div className="flex items-center gap-1.5 text-xs text-muted">
              <span className="size-1.5 rounded-full bg-emerald-500" /> AI assistant · online
            </div>
          </div>
        </div>
        <div className="space-y-3 pt-4 text-sm">
          <div className="ml-auto w-fit max-w-[80%] rounded-2xl rounded-br-sm bg-indigo-600 text-white dark:bg-indigo-500 px-4 py-2">
            How much is a keratin treatment?
          </div>
          <div className="w-fit max-w-[85%]">
            <div className="mb-1 text-xs text-muted">📚 searched “keratin treatment cost”</div>
            <div className="rounded-2xl rounded-bl-sm bg-zinc-100 px-4 py-2 dark:bg-zinc-800">
              A keratin smoothing treatment costs ₹6,500{" "}
              <span className="rounded bg-indigo-100 px-1 text-xs font-medium text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
                1
              </span>
            </div>
          </div>
          <div className="ml-auto w-fit max-w-[80%] rounded-2xl rounded-br-sm bg-indigo-600 text-white dark:bg-indigo-500 px-4 py-2">
            And how long does it take?
          </div>
          <div className="w-fit max-w-[85%] rounded-2xl rounded-bl-sm bg-zinc-100 px-4 py-2 dark:bg-zinc-800">
            The keratin smoothing treatment takes 3 hours{" "}
            <span className="rounded bg-indigo-100 px-1 text-xs font-medium text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
              1
            </span>
            .
          </div>
        </div>
      </div>
    </div>
  );
}
