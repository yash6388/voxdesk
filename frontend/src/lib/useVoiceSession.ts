"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { API_URL, type Confirmation, type Delegation, type Route } from "@/lib/api";

export type VoiceStatus = "connecting" | "idle" | "listening" | "thinking" | "speaking" | "offline";

export type VoiceTiming = {
  traceUrl?: string;
  stt_ms?: number;
  first_token_ms?: number;
  first_audio_ms?: number;
  total_ms?: number;
};

export type VoiceMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  route?: Route;
  delegation?: Delegation;
  confirmation?: Confirmation & { state: "pending" | "approved" | "declined" };
  error?: string;
};

type Engines = { stt: string; tts: string };

const threadKey = (businessId: string) => `voxdesk:voice-thread:${businessId}`;

function storedThread(businessId: string): string | null {
  try {
    return localStorage.getItem(threadKey(businessId));
  } catch {
    return null;
  }
}

function pickMimeType(): string | undefined {
  const preferred = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  return preferred.find((t) => typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t));
}

/**
 * One voice conversation over the /voice WebSocket: records the mic, plays the agent's
 * audio in order, and keeps a transcript. Pressing talk while the agent is speaking
 * interrupts it (barge-in).
 */
export function useVoiceSession(businessId: string) {
  const [status, setStatus] = useState<VoiceStatus>("connecting");
  const [messages, setMessages] = useState<VoiceMessage[]>([]);
  const [timing, setTiming] = useState<VoiceTiming | null>(null);
  const [engines, setEngines] = useState<Engines | null>(null);
  const [micError, setMicError] = useState<string | null>(null);

  const ws = useRef<WebSocket | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const audioCtx = useRef<AudioContext | null>(null);
  const playQueue = useRef<ArrayBuffer[]>([]);
  const playing = useRef<AudioBufferSourceNode | null>(null);
  const awaitingAudio = useRef(false);
  const turnOpen = useRef(false);
  const assistantId = useRef<string | null>(null);
  const traceUrl = useRef<string | undefined>(undefined);

  // ---------- transcript helpers ----------

  const patchAssistant = useCallback((fn: (m: VoiceMessage) => VoiceMessage) => {
    setMessages((prev) => {
      let id = assistantId.current;
      let list = prev;
      if (!id) {
        id = crypto.randomUUID();
        assistantId.current = id;
        list = [...prev, { id, role: "assistant", text: "" }];
      }
      return list.map((m) => (m.id === id ? fn(m) : m));
    });
  }, []);

  // ---------- audio playback (strictly in order) ----------

  const playNext = useCallback(async () => {
    const ctx = audioCtx.current;
    if (!ctx || playing.current || playQueue.current.length === 0) {
      if (!playing.current && playQueue.current.length === 0) {
        setStatus(turnOpen.current ? "thinking" : "idle");
      }
      return;
    }
    const data = playQueue.current.shift()!;
    try {
      const buffer = await ctx.decodeAudioData(data);
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      source.onended = () => {
        playing.current = null;
        void playNext();
      };
      playing.current = source;
      setStatus("speaking");
      source.start();
    } catch {
      void playNext(); // skip an undecodable chunk rather than stalling
    }
  }, []);

  const stopPlayback = useCallback(() => {
    playQueue.current = [];
    if (playing.current) {
      playing.current.onended = null;
      playing.current.stop();
      playing.current = null;
    }
  }, []);

  // ---------- WebSocket ----------

  useEffect(() => {
    const thread = storedThread(businessId);
    const url = `${API_URL.replace(/^http/, "ws")}/voice/${businessId}${thread ? `?thread_id=${thread}` : ""}`;
    const socket = new WebSocket(url);
    socket.binaryType = "arraybuffer";
    ws.current = socket;

    socket.onclose = () => setStatus("offline");
    socket.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        if (awaitingAudio.current) {
          awaitingAudio.current = false;
          playQueue.current.push(event.data);
          void playNext();
        }
        return;
      }
      const msg = JSON.parse(event.data);
      switch (msg.type) {
        case "ready":
          setEngines({ stt: msg.stt, tts: msg.tts });
          setStatus("idle");
          try {
            localStorage.setItem(threadKey(businessId), msg.thread_id);
          } catch {}
          if (msg.pending_confirmation) {
            patchAssistant((m) => ({
              ...m,
              confirmation: { ...msg.pending_confirmation, state: "pending" },
            }));
            assistantId.current = null;
          }
          break;
        case "transcript":
          turnOpen.current = true;
          setStatus("thinking");
          assistantId.current = null;
          if (msg.text) {
            setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "user", text: msg.text }]);
          }
          break;
        case "route":
          patchAssistant((m) => ({ ...m, route: msg.data }));
          break;
        case "delegation":
          patchAssistant((m) => ({ ...m, delegation: msg.data }));
          break;
        case "token":
          patchAssistant((m) => ({ ...m, text: m.text + msg.data.text }));
          break;
        case "confirm":
          patchAssistant((m) => ({ ...m, confirmation: { ...msg.data, state: "pending" } }));
          break;
        case "decision":
          setMessages((prev) =>
            prev.map((m) =>
              m.confirmation?.state === "pending"
                ? { ...m, confirmation: { ...m.confirmation, state: msg.approved ? "approved" : "declined" } }
                : m,
            ),
          );
          assistantId.current = null;
          break;
        case "error":
          patchAssistant((m) => ({ ...m, error: msg.data.message }));
          break;
        case "audio":
          awaitingAudio.current = true; // the next binary frame is this sentence's audio
          break;
        case "trace":
          traceUrl.current = msg.url;
          break;
        case "timing":
          setTiming({ ...msg, traceUrl: traceUrl.current });
          traceUrl.current = undefined;
          break;
        case "turn_end":
        case "interrupted":
          turnOpen.current = false;
          assistantId.current = null;
          if (!playing.current && playQueue.current.length === 0) setStatus("idle");
          break;
      }
    };

    return () => {
      socket.close();
      stopPlayback();
    };
  }, [businessId, patchAssistant, playNext, stopPlayback]);

  // ---------- microphone ----------

  const startTalking = useCallback(async () => {
    setMicError(null);
    // Audio can only start after a user gesture; create the context on the first press.
    audioCtx.current ??= new AudioContext();
    if (audioCtx.current.state === "suspended") await audioCtx.current.resume();

    // Barge-in: stop the agent mid-sentence and cancel its reply on the server.
    if (playing.current || turnOpen.current) {
      stopPlayback();
      ws.current?.send(JSON.stringify({ type: "interrupt" }));
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      const mimeType = pickMimeType();
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: rec.mimeType });
        if (blob.size > 0 && ws.current?.readyState === WebSocket.OPEN) {
          setStatus("thinking");
          ws.current.send(await blob.arrayBuffer());
        } else {
          setStatus("idle");
        }
      };
      recorder.current = rec;
      rec.start();
      setStatus("listening");
    } catch {
      setMicError("Microphone access was blocked. Allow it in your browser's site settings.");
      setStatus("idle");
    }
  }, [stopPlayback]);

  const stopTalking = useCallback(() => {
    if (recorder.current?.state === "recording") recorder.current.stop();
    recorder.current = null;
  }, []);

  const sendText = useCallback((text: string) => {
    if (!text.trim() || ws.current?.readyState !== WebSocket.OPEN) return;
    audioCtx.current ??= new AudioContext();
    stopPlayback();
    ws.current.send(JSON.stringify({ type: "text", text }));
  }, [stopPlayback]);

  const confirm = useCallback((approved: boolean) => {
    ws.current?.send(JSON.stringify({ type: "confirm", approved }));
  }, []);

  const newConversation = useCallback(() => {
    try {
      localStorage.removeItem(threadKey(businessId));
    } catch {}
    window.location.reload();
  }, [businessId]);

  return {
    status,
    messages,
    timing,
    engines,
    micError,
    startTalking,
    stopTalking,
    sendText,
    confirm,
    newConversation,
  };
}
