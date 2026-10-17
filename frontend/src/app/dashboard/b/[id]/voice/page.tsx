"use client";

import {
  AudioLines,
  Bot,
  ExternalLink,
  Gauge,
  Keyboard,
  Mic,
  RotateCcw,
  Send,
  Square,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ConfirmCard } from "@/components/chat/ConfirmCard";
import { Badge, Card, PageHeader } from "@/components/ui/primitives";
import { BRAND_TINT, cn, formatMs } from "@/lib/utils";
import { type VoiceStatus, type VoiceTiming, useVoiceSession } from "@/lib/useVoiceSession";

const STATUS_TEXT: Record<VoiceStatus, string> = {
  connecting: "Connecting…",
  idle: "Hold to talk",
  listening: "Listening… release to send",
  thinking: "Thinking…",
  speaking: "Speaking — press to interrupt",
  offline: "Voice service offline",
};

export default function VoicePage() {
  const { id } = useParams<{ id: string }>();
  const voice = useVoiceSession(id);
  const [typing, setTyping] = useState(false);
  const [text, setText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [voice.messages]);

  const busy = voice.status === "connecting" || voice.status === "offline";
  const pending = voice.messages.some((m) => m.confirmation?.state === "pending");

  return (
    <>
      <PageHeader
        title="Voice"
        description="Talk to your agent the way a customer would on a call."
        actions={
          <button
            onClick={voice.newConversation}
            className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-muted transition hover:bg-zinc-100 hover:text-foreground dark:hover:bg-zinc-800"
          >
            <RotateCcw className="size-4" /> New conversation
          </button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card className="flex h-[calc(100vh-13rem)] min-h-[560px] flex-col overflow-hidden">
          {/* Transcript */}
          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-6">
            {voice.messages.length === 0 && (
              <div className="flex h-full flex-col items-center justify-center text-center text-sm text-muted">
                <AudioLines className="mb-3 size-8 text-indigo-500" />
                Hold the button and ask something like
                <span className="mt-1 font-medium text-foreground">
                  “Do you have parking?” or “Book a haircut tomorrow at 4”
                </span>
              </div>
            )}
            {voice.messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[80%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-sm text-white dark:bg-indigo-500">
                    {m.text}
                  </div>
                </div>
              ) : (
                <div key={m.id} className="space-y-3">
                  {(m.text || m.error) && (
                    <div className="flex gap-3">
                      <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-full", BRAND_TINT)}>
                        <Bot className="size-4" />
                      </span>
                      <div className="max-w-[80%] rounded-2xl rounded-tl-md bg-zinc-100 px-4 py-2.5 text-sm leading-relaxed dark:bg-zinc-800/70">
                        {m.text.replace(/\s*\[\d+(?:,\s*\d+)*\]/g, "")}
                        {m.error && <span className="text-red-600">{m.error}</span>}
                      </div>
                    </div>
                  )}
                  {m.confirmation && (
                    <div className="pl-10">
                      <ConfirmCard
                        confirmation={m.confirmation}
                        busy={voice.status === "thinking"}
                        onDecide={voice.confirm}
                      />
                      {m.confirmation.state === "pending" && (
                        <p className="mt-2 text-xs text-muted">…or just say “yes” or “no”.</p>
                      )}
                    </div>
                  )}
                </div>
              ),
            )}
          </div>

          {/* Controls */}
          <div className="border-t border-border p-6">
            <div className="flex flex-col items-center gap-3">
              <TalkButton
                status={voice.status}
                disabled={busy}
                onPress={voice.startTalking}
                onRelease={voice.stopTalking}
              />
              <p className="text-sm font-medium">
                {pending && voice.status === "idle" ? "Say “yes” to confirm or “no” to cancel" : STATUS_TEXT[voice.status]}
              </p>
              {voice.micError && <p className="text-sm text-red-600">{voice.micError}</p>}

              {typing ? (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    voice.sendText(text);
                    setText("");
                  }}
                  className="flex w-full max-w-md items-center gap-2"
                >
                  <input
                    autoFocus
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="Type what you'd say…"
                    className="h-9 flex-1 rounded-lg border border-border bg-background px-3 text-sm outline-none focus:border-indigo-500"
                  />
                  <button aria-label="Send" className="flex size-9 items-center justify-center rounded-lg bg-indigo-600 text-white hover:bg-indigo-700">
                    <Send className="size-4" />
                  </button>
                </form>
              ) : (
                <button
                  onClick={() => setTyping(true)}
                  className="flex items-center gap-1.5 text-xs text-muted hover:text-foreground"
                >
                  <Keyboard className="size-3.5" /> Type instead
                </button>
              )}
            </div>
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="p-5">
            <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted">Engines</h3>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-muted">Speech-to-text</dt>
                <dd><Badge tone="brand">{voice.engines?.stt ?? "—"}</Badge></dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted">Text-to-speech</dt>
                <dd><Badge tone="brand">{voice.engines?.tts ?? "—"}</Badge></dd>
              </div>
            </dl>
          </Card>
          <LatencyCard timing={voice.timing} />
        </div>
      </div>
    </>
  );
}

function TalkButton({
  status,
  disabled,
  onPress,
  onRelease,
}: {
  status: VoiceStatus;
  disabled: boolean;
  onPress: () => void;
  onRelease: () => void;
}) {
  const listening = status === "listening";
  const speaking = status === "speaking";
  return (
    <div className="relative flex size-28 items-center justify-center">
      {(listening || speaking) && (
        <>
          <span className="absolute inset-0 animate-ping rounded-full bg-indigo-500/20" />
          <span className="absolute inset-3 animate-pulse rounded-full bg-indigo-500/20" />
        </>
      )}
      <button
        disabled={disabled}
        aria-label={listening ? "Release to send" : "Hold to talk"}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          onPress();
        }}
        onPointerUp={onRelease}
        onPointerCancel={onRelease}
        onKeyDown={(e) => (e.key === " " || e.key === "Enter") && !e.repeat && onPress()}
        onKeyUp={(e) => (e.key === " " || e.key === "Enter") && onRelease()}
        className={cn(
          "relative flex size-20 touch-none select-none items-center justify-center rounded-full text-white shadow-xl transition active:scale-95 disabled:opacity-40",
          listening
            ? "bg-red-500 shadow-red-500/30"
            : "bg-gradient-to-br from-indigo-500 via-violet-500 to-fuchsia-500 shadow-violet-500/30",
        )}
      >
        {listening ? <Square className="size-7" fill="currentColor" /> : <Mic className="size-8" />}
      </button>
    </div>
  );
}

function LatencyCard({ timing }: { timing: VoiceTiming | null }) {
  const rows: [string, number | undefined, string][] = [
    ["Speech-to-text", timing?.stt_ms, "Recording → transcript"],
    ["First token", timing?.first_token_ms, "Agent starts answering"],
    ["First audio", timing?.first_audio_ms, "What the caller feels"],
    ["Total", timing?.total_ms, "Whole turn"],
  ];
  return (
    <Card className="p-5">
      <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted">
        <Gauge className="size-3.5" /> Last turn latency
      </h3>
      <ul className="space-y-2.5">
        {rows.map(([label, value, hint]) => (
          <li key={label} className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm">{label}</div>
              <div className="text-[11px] text-muted">{hint}</div>
            </div>
            <span className="font-mono text-sm font-semibold">
              {value === undefined ? "—" : formatMs(value)}
            </span>
          </li>
        ))}
      </ul>
      {timing?.traceUrl && (
        <a
          href={timing.traceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-4 flex items-center justify-between rounded-lg border border-border px-3 py-2 text-xs font-medium transition hover:border-indigo-300 hover:text-indigo-700 dark:hover:border-indigo-500/50 dark:hover:text-indigo-300"
        >
          Open trace in Langfuse <ExternalLink className="size-3.5" />
        </a>
      )}
    </Card>
  );
}
