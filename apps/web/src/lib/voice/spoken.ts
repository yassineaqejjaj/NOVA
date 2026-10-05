import type { Message } from "@/lib/api/types";

/** What NOVA says out loud for a reply. Classified content (C2/C3) is never read: it stays on screen. */
export interface Spoken {
  text: string;
  confidential: boolean;
}

const MAX_CHARS = 650;

export function plainText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/!\[[^\]]*]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/\s*[[(](?:S\d+(?:\s*[,;/]\s*S?\d+)*)[\])]/g, "") // citations (S1), [S2], (S1/S3)
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/[*_`>|]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function clip(text: string, more: string): string {
  if (text.length <= MAX_CHARS) return text;
  const cut = text.slice(0, MAX_CHARS);
  const end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("! "), cut.lastIndexOf("? "));
  return `${end > 200 ? cut.slice(0, end + 1) : cut} ${more}`;
}

export function spokenReply(
  message: Message | undefined,
  copy: { created: (title: string, type: string) => string; updated: (title: string) => string; more: string; confidential: string; failed: string },
): Spoken {
  if (!message) return { text: "", confidential: false };
  let classification = 0;
  const parts: string[] = [];
  for (const block of [...message.blocks].sort((a, b) => a.position - b.position)) {
    const data = block.data as Record<string, unknown>;
    if (block.type === "context_sources") classification = Math.max(classification, Number(data.max_classification ?? 0));
    if (block.type === "artifact") {
      classification = Math.max(classification, Number(data.classification ?? 0));
      const title = String(data.title ?? "");
      parts.push(Number(data.version ?? 1) > 1 ? copy.updated(title) : copy.created(title, String(data.type_name ?? "")));
    }
    if (block.type === "text" && typeof data.markdown === "string") parts.push(plainText(data.markdown));
    if (block.type === "error") parts.push(String(data.title ?? copy.failed));
  }
  if (classification >= 2) return { text: copy.confidential, confidential: true };
  return { text: clip(parts.filter(Boolean).join(" "), copy.more), confidential: false };
}

const YES = /\b(oui|ouais|ok|okay|d'accord|vas-y|go|valide|approuve|confirme|yes|yeah|sure|approve|confirm|continue)\b/i;
const NO = /\b(non|annule|stop|arrête|refuse|no|nope|cancel|reject)\b/i;

export function yesNo(text: string): "yes" | "no" | null {
  if (NO.test(text)) return "no";
  if (YES.test(text)) return "yes";
  return null;
}
