"use client";

import { Badge, Button, cn, Dialog, DialogPrimitive, Switch, Tooltip } from "@nova/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ExternalLink, Mic, MicOff, Square, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { systemLabel, systemMarkdown } from "@/components/conversation/blocks.messages";
import { NovaOrb, type OrbState, orbStateFromPhase } from "@/components/shell/nova-orb";
import { api, ApiError } from "@/lib/api/client";
import { useArtifactTypes, useSendIntent, useSkills } from "@/lib/api/hooks";
import type { Conversation, Message, TaskSummary } from "@/lib/api/types";
import { defineMessages, useLang, useT } from "@/lib/i18n";
import { questionText, typeName, useCatalogNames } from "@/lib/i18n/catalog";
import { VoicePlayer, transcribe } from "@/lib/voice/speaker";
import { VoiceRecorder } from "@/lib/voice/recorder";
import { spokenReply, yesNo } from "@/lib/voice/spoken";

const M = defineMessages({
  en: {
    title: "Talk with NOVA",
    autonomous: "Autonomous agent — NOVA carries out the work without asking for confirmation; external actions still follow company policy.",
    handsFree: "Hands-free",
    handsFreeHint: "NOVA listens again after answering",
    tapToTalk: "Tap to talk",
    listening: "Listening…",
    transcribing: "Understanding…",
    working: "NOVA is working…",
    speaking: "NOVA is speaking — tap to interrupt",
    idle: "Tap the microphone and speak",
    you: "You",
    nova: "NOVA",
    ack: "On it.",
    nothingHeard: "I didn't catch that. Could you say it again?",
    created: (v: { title: string; type: string }) => `I created ${v.type ? `the ${v.type} ` : ""}“${v.title}”. It's in your library.`,
    updated: (v: { title: string }) => `I updated “${v.title}”.`,
    more: "The rest is on screen.",
    confidential: "This answer contains confidential information, so I won't read it aloud. It's on your screen.",
    failed: "I couldn't finish this task.",
    confirmPrompt: "I'm ready to go ahead. Shall I continue? Say yes or no.",
    approvalPrompt: "This changes something outside NOVA and needs your approval. Do you approve? Say yes or no.",
    yesNoRetry: "Please answer yes or no.",
    stopped: "Stopped.",
    micDenied: "Microphone access was refused. Allow it in your browser to talk with NOVA.",
    unavailable: "Voice is not available right now. You can keep typing to NOVA.",
    openConversation: "Open the conversation",
    stop: "Stop",
    close: "Close",
    confidentialBadge: "Not read aloud",
    providerExternal: "Speech recognition and voice by ElevenLabs (external service). Confidential answers are never read aloud.",
    providerSelfHosted: "Speech recognition and voice run on NOVA's own servers.",
  },
  fr: {
    title: "Parler avec NOVA",
    autonomous: "Agent autonome — NOVA réalise le travail sans demander de confirmation ; les actions externes suivent toujours la politique de l’entreprise.",
    handsFree: "Mains libres",
    handsFreeHint: "NOVA vous réécoute après avoir répondu",
    tapToTalk: "Touchez pour parler",
    listening: "Je vous écoute…",
    transcribing: "Je comprends…",
    working: "NOVA travaille…",
    speaking: "NOVA parle — touchez pour l’interrompre",
    idle: "Touchez le micro et parlez",
    you: "Vous",
    nova: "NOVA",
    ack: "Je m’en occupe.",
    nothingHeard: "Je n’ai pas bien entendu. Pouvez-vous répéter ?",
    created: (v: { title: string; type: string }) => `J’ai créé ${v.type ? `le document ${v.type} ` : ""}« ${v.title} ». Il est dans votre Bibliothèque.`,
    updated: (v: { title: string }) => `J’ai mis à jour « ${v.title} ».`,
    more: "La suite est à l’écran.",
    confidential: "Cette réponse contient des informations confidentielles : je ne la lis pas à voix haute. Elle est affichée à l’écran.",
    failed: "Je n’ai pas pu terminer cette tâche.",
    confirmPrompt: "Je suis prêt à lancer le travail. Je continue ? Répondez oui ou non.",
    approvalPrompt: "Cette action modifie un système externe et demande votre validation. Vous validez ? Répondez oui ou non.",
    yesNoRetry: "Répondez simplement oui ou non.",
    stopped: "Arrêté.",
    micDenied: "L’accès au micro a été refusé. Autorisez-le dans votre navigateur pour parler avec NOVA.",
    unavailable: "La voix n’est pas disponible pour le moment. Vous pouvez continuer à écrire à NOVA.",
    openConversation: "Ouvrir la conversation",
    stop: "Arrêter",
    close: "Fermer",
    confidentialBadge: "Non lu à voix haute",
    providerExternal: "Reconnaissance vocale et voix par ElevenLabs (service externe). Les réponses confidentielles ne sont jamais lues.",
    providerSelfHosted: "La reconnaissance vocale et la voix tournent sur les serveurs de NOVA.",
  },
});

type Phase = "idle" | "listening" | "transcribing" | "working" | "speaking";
interface Caption {
  id: number;
  who: "you" | "nova";
  text: string;
  confidential?: boolean;
}
type Pending = { kind: "questions"; taskId: string; keys: string[]; questions: string[] } | { kind: "decision"; taskId: string; approve: string; reject: string } | null;

const TERMINAL = new Set(["completed", "failed", "cancelled", "paused"]);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function VoiceSession({
  open,
  onOpenChange,
  conversationId: initialConversation,
  projectId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  conversationId?: string | null;
  projectId?: string | null;
}) {
  const t = useT(M);
  const lang = useLang();
  const client = useQueryClient();
  const { data: voiceStatus } = useQuery({
    queryKey: ["voice-status"],
    queryFn: () => api.get<{ enabled: boolean; stt?: string; tts?: string }>("/voice/status"),
    staleTime: 300_000,
    enabled: open,
  });
  const send = useSendIntent();
  const { data: skills } = useSkills();
  const { data: types } = useArtifactTypes();
  const names = useCatalogNames();
  const [phase, setPhase] = useState<Phase>("idle");
  const [orb, setOrb] = useState<OrbState>("idle");
  const [level, setLevel] = useState(0);
  const [handsFree, setHandsFree] = useState(true);
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(initialConversation ?? null);
  const recorder = useRef<VoiceRecorder | null>(null);
  const player = useRef(new VoicePlayer());
  const generation = useRef(0); // bumps on close/stop: running loops end
  const pending = useRef<Pending>(null);
  const handsFreeRef = useRef(handsFree);
  const speechLang = useRef<"fr" | "en">(lang);
  const conversationRef = useRef<string | null>(initialConversation ?? null);
  const listenRef = useRef<(gen: number) => Promise<void>>(async () => undefined);
  handsFreeRef.current = handsFree;
  conversationRef.current = conversationId;

  const say = useCallback((who: Caption["who"], text: string, confidential = false) => {
    setCaptions((c) => [...c.slice(-12), { id: Date.now() + Math.random(), who, text, confidential }]);
  }, []);

  const speak = useCallback(
    async (text: string, gen: number) => {
      if (!text || gen !== generation.current) return;
      setPhase("speaking");
      setOrb("speaking");
      try {
        await player.current.speak(text, speechLang.current);
      } catch {
        /* playback refused or service down: the caption stays on screen */
      }
    },
    [],
  );

  /** Polls the conversation until NOVA's reply task finishes or waits for the user. */
  const follow = useCallback(async (id: string, gen: number): Promise<{ message?: Message; task?: TaskSummary | null }> => {
    for (;;) {
      if (gen !== generation.current) return {};
      const conversation = await api.get<Conversation>(`/conversations/${id}`);
      client.setQueryData(["conversation", id], conversation);
      const reply = [...(conversation.messages ?? [])].reverse().find((m) => m.role === "nova");
      const task = reply?.task;
      if (task) setOrb(task.status === "waiting_user" ? "waiting" : orbStateFromPhase(task.phase));
      if (task && (TERMINAL.has(task.status) || task.status === "waiting_user")) return { message: reply, task };
      if (!task && reply && reply.blocks.length) return { message: reply, task: null };
      await sleep(1500);
    }
  }, [client]);

  const conclude = useCallback(
    async (id: string, gen: number) => {
      const { message, task } = await follow(id, gen);
      if (gen !== generation.current) return;
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: ["today"] });
      if (task?.status === "waiting_user" && task.waiting_for) {
        const waiting = task.waiting_for;
        if (waiting.kind === "questions") {
          const questions = waiting.questions.map((q) => questionText(skills, q, lang));
          pending.current = { kind: "questions", taskId: task.id, keys: waiting.questions.map((q) => q.key), questions };
          const question = questions[0] ?? "";
          say("nova", question);
          setOrb("clarification");
          await speak(question, gen);
        } else {
          const approval = waiting.kind === "approval";
          pending.current = { kind: "decision", taskId: task.id, approve: approval ? "approve" : "run", reject: approval ? "reject" : "cancel" };
          const prompt = approval ? t("approvalPrompt") : t("confirmPrompt");
          say("nova", prompt);
          await speak(prompt, gen);
        }
      } else {
        pending.current = null;
        const spoken = spokenReply(message, {
          created: (title, type) => t("created", { title, type: typeName(types?.find((d) => d.name === type), lang, type) }),
          updated: (title) => t("updated", { title }),
          more: t("more"),
          confidential: t("confidential"),
          failed: t("failed"),
          markdown: (markdown) => systemMarkdown(markdown, lang, names),
          label: (label) => systemLabel(label, lang, names),
        });
        if (spoken.text) say("nova", spoken.text, spoken.confidential);
        await speak(spoken.text, gen);
        setOrb("completed");
      }
      if (gen === generation.current) {
        if (handsFreeRef.current) void listenRef.current(gen);
        else setPhase("idle");
      }
    },
    [client, follow, say, speak, t, skills, types, lang, names],
  );

  const handle = useCallback(
    async (text: string, gen: number) => {
      say("you", text);
      setPhase("working");
      setOrb("thinking");
      const waiting = pending.current;
      try {
        if (waiting?.kind === "questions") {
          const [first, ...rest] = waiting.keys;
          const answers = Object.fromEntries([[first, text], ...rest.map((k) => [k, ""])].filter(([k]) => k));
          pending.current = null;
          await api.post(`/executions/${waiting.taskId}/resume`, { value: answers });
        } else if (waiting?.kind === "decision") {
          const answer = yesNo(text);
          if (!answer) {
            say("nova", t("yesNoRetry"));
            await speak(t("yesNoRetry"), gen);
            return void listenRef.current(gen);
          }
          pending.current = null;
          await api.post(`/executions/${waiting.taskId}/resume`, { value: { action: answer === "yes" ? waiting.approve : waiting.reject } });
        } else {
          const result = await send.mutateAsync({
            conversationId: conversationRef.current,
            payload: { text, project_id: projectId ?? null, context_mode: "auto", autonomy: "execute_automatically", attachments: [] },
          });
          conversationRef.current = result.conversation.id;
          setConversationId(result.conversation.id);
          void speak(t("ack"), gen).then(() => gen === generation.current && setPhase("working"));
          await conclude(result.conversation.id, gen);
          return;
        }
        if (conversationRef.current) await conclude(conversationRef.current, gen);
      } catch (exc) {
        setError(exc instanceof ApiError ? exc.message : t("unavailable"));
        setPhase("idle");
        setOrb("idle");
      }
    },
    [conclude, projectId, say, send, speak, t],
  );

  const listen = useCallback(
    async (gen: number) => {
      if (gen !== generation.current) return;
      setError(null);
      setPhase("listening");
      setOrb("listening");
      const rec = new VoiceRecorder({ onLevel: setLevel });
      recorder.current = rec;
      let recording;
      try {
        recording = await rec.start();
      } catch {
        setError(t("micDenied"));
        setPhase("idle");
        setOrb("idle");
        return;
      }
      recorder.current = null;
      if (gen !== generation.current) return;
      if (!recording.heardSpeech) {
        setPhase("idle");
        setOrb("idle");
        return;
      }
      setPhase("transcribing");
      setOrb("thinking");
      try {
        const heard = await transcribe(recording.blob);
        if (heard.language === "fr" || heard.language === "en") speechLang.current = heard.language;
        const text = heard.text.trim();
        if (!text) {
          await speak(t("nothingHeard"), gen);
          return void listenRef.current(gen);
        }
        await handle(text, gen);
      } catch {
        setError(t("unavailable"));
        setPhase("idle");
        setOrb("idle");
      }
    },
    [handle, speak, t],
  );
  listenRef.current = listen;

  const stopAll = useCallback(() => {
    generation.current += 1;
    recorder.current?.cancel();
    player.current.stop();
    setPhase("idle");
    setOrb("idle");
    setLevel(0);
  }, []);

  /** Mic button: start listening, end the utterance, or interrupt NOVA (barge-in). */
  const toggle = useCallback(() => {
    if (phase === "listening") return recorder.current?.stop();
    if (phase === "speaking") player.current.stop();
    generation.current += 1;
    void listen(generation.current);
  }, [listen, phase]);

  useEffect(() => {
    if (open) {
      speechLang.current = lang;
      setConversationId(initialConversation ?? null);
      conversationRef.current = initialConversation ?? null;
      generation.current += 1;
      void listen(generation.current);
    } else stopAll();
    return () => undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "Space" && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, toggle]);

  const status = { idle: t("idle"), listening: t("listening"), transcribing: t("transcribing"), working: t("working"), speaking: t("speaking") }[phase];

  return (
    <Dialog open={open} onOpenChange={(o) => (o ? onOpenChange(o) : (stopAll(), onOpenChange(false)))}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-background/95 backdrop-blur-md" />
        <DialogPrimitive.Content className="fixed inset-0 z-50 flex flex-col items-center px-5 py-6 focus:outline-none" aria-describedby={undefined}>
          <DialogPrimitive.Title className="sr-only">{t("title")}</DialogPrimitive.Title>
          <div className="flex w-full max-w-3xl items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-[13px] text-muted">
              <Switch checked={handsFree} onCheckedChange={setHandsFree} aria-label={t("handsFree")} />
              <Tooltip content={t("handsFreeHint")}><span>{t("handsFree")}</span></Tooltip>
            </label>
            <div className="flex items-center gap-1">
              {conversationId ? (
                <Button variant="ghost" size="sm" asChild>
                  <Link href={`/c/${conversationId}`} onClick={() => onOpenChange(false)}>
                    <ExternalLink /> {t("openConversation")}
                  </Link>
                </Button>
              ) : null}
              <DialogPrimitive.Close asChild>
                <Button variant="ghost" size="icon" aria-label={t("close")}>
                  <X />
                </Button>
              </DialogPrimitive.Close>
            </div>
          </div>

          <div className="flex flex-1 flex-col items-center justify-center gap-6">
            <motion.div animate={{ scale: phase === "listening" ? 1 + level * 0.12 : 1 }} transition={{ type: "spring", stiffness: 300, damping: 20 }}>
              <NovaOrb state={orb} size={220} reflection title={status} />
            </motion.div>
            <p className="mt-6 text-[15px] font-medium text-text/80" aria-live="polite" data-testid="voice-status">
              {status}
            </p>
            {error ? <p className="max-w-md text-center text-[13.5px] text-danger">{error}</p> : null}
          </div>

          <ol className="mb-5 flex max-h-[30vh] w-full max-w-2xl flex-col gap-2 overflow-y-auto" aria-label={t("title")} data-testid="voice-captions">
            {captions.map((c) => (
              <li key={c.id} className={cn("flex", c.who === "you" ? "justify-end" : "justify-start")}>
                <span className={cn("max-w-[85%] rounded-[16px] px-3.5 py-2 text-[14px]", c.who === "you" ? "bg-accent-soft text-text" : "bg-surface-2 text-text")}>
                  <span className="mr-1.5 text-[11.5px] font-semibold uppercase tracking-wide text-subtle">{c.who === "you" ? t("you") : t("nova")}</span>
                  {c.text}
                  {c.confidential ? <Badge tone="warning" className="ml-2">{t("confidentialBadge")}</Badge> : null}
                </span>
              </li>
            ))}
          </ol>

          <div className="flex flex-col items-center gap-3">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={toggle}
                aria-label={phase === "listening" ? t("stop") : t("tapToTalk")}
                className={cn(
                  "flex size-16 items-center justify-center rounded-full text-white shadow-[0_12px_30px_-10px_var(--accent)] transition-transform hover:scale-105",
                  phase === "listening" ? "bg-danger" : "bg-accent",
                )}
              >
                {phase === "listening" ? <MicOff className="size-7" /> : <Mic className="size-7" />}
              </button>
              {phase !== "idle" ? (
                <Button variant="secondary" size="icon" className="size-11 rounded-full" onClick={stopAll} aria-label={t("stop")}>
                  <Square className="!size-4" />
                </Button>
              ) : null}
            </div>
            <p className="max-w-lg text-center text-[12px] text-subtle">{t("autonomous")}</p>
            {voiceStatus ? (
              <p className="max-w-lg text-center text-[11.5px] text-subtle" data-testid="voice-provider">
                {voiceStatus.stt === "elevenlabs" || voiceStatus.tts === "elevenlabs" ? t("providerExternal") : t("providerSelfHosted")}
              </p>
            ) : null}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </Dialog>
  );
}
