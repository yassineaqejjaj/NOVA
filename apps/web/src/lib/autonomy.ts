import type { AutonomyMode } from "@/lib/api/types";

export const AUTONOMY: { value: AutonomyMode; label: string; hint: string }[] = [
  { value: "suggest", label: "Suggest", hint: "NOVA proposes; nothing runs without you" },
  { value: "assist", label: "Assist", hint: "Single Skills run; workflows wait for your OK (default)" },
  { value: "execute_with_approval", label: "Execute with approval", hint: "Runs workflows; changes to existing Artifacts wait for approval" },
  { value: "execute_automatically", label: "Execute automatically", hint: "No confirmation; external changes still follow company policy" },
];
