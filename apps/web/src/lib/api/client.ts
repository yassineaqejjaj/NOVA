import { knownSystemLabel } from "@/components/conversation/blocks.messages";
import { getLang, type Lang } from "@/lib/i18n";

import type { Action, ApiErrorBody } from "./types";

/** French text of the API's error details (`apps/api/nova_api`), exact English detail → French. */
const DETAIL_FR: Record<string, string> = {
  "Your session has expired. Sign in again.": "Votre session a expiré. Reconnectez-vous.",
  "Sign in again.": "Reconnectez-vous.",
  "Invalid access token.": "Jeton d’accès invalide.",
  "Sign in to use NOVA.": "Connectez-vous pour utiliser NOVA.",
  "The sign-in attempt expired. Try again.": "La tentative de connexion a expiré. Réessayez.",
  "The sign-in attempt is invalid. Try again.": "La tentative de connexion n’est pas valide. Réessayez.",
  "Keycloak refused the sign-in.": "Keycloak a refusé la connexion.",
  "The identity token is invalid.": "Le jeton d’identité n’est pas valide.",
  "Not available.": "Non disponible.",
  "This task is not waiting for you.": "Cette tâche n’attend pas de réponse de votre part.",
  "Only a running task can be paused.": "Seule une tâche en cours peut être mise en pause.",
  "This task is not paused.": "Cette tâche n’est pas en pause.",
  "Only failed tasks can be retried.": "Seules les tâches en échec peuvent être relancées.",
  "This context provider does not support account linking.": "Ce fournisseur de contexte ne permet pas de relier un compte.",
  "ORBIT rejected these credentials.": "ORBIT a refusé ces identifiants.",
  "Voice is not available right now. You can keep typing to NOVA.": "La voix n’est pas disponible pour le moment. Vous pouvez continuer à écrire à NOVA.",
  "That recording is too long — keep it under a minute and a half.": "Cet enregistrement est trop long — limitez-le à une minute et demie.",
  "NOVA didn't hear anything.": "NOVA n’a rien entendu.",
  "Unknown artifact type.": "Type d’Artefact inconnu.",
  "This Artifact changed since you opened it (NOVA or a teammate saved a new version).": "Cet Artefact a changé depuis que vous l’avez ouvert (NOVA ou un membre de l’équipe a enregistré une nouvelle version).",
  "Unknown section.": "Section inconnue.",
  "This version is not waiting for approval.": "Cette version n’attend pas de validation.",
  "Not found, or you don't have access.": "Introuvable, ou vous n’y avez pas accès.",
  "Some fields are invalid.": "Certains champs ne sont pas valides.",
  "Something went wrong on NOVA's side. Please retry.": "Une erreur s’est produite du côté de NOVA. Veuillez réessayer.",
  "Something went wrong.": "Une erreur s’est produite.",
};

/** Fallback by error code when the detail is not known (e.g. a validation message). */
const CODE_FR: Record<string, string> = {
  error: "Une erreur s’est produite.",
  unauthorized: "Reconnectez-vous pour continuer.",
  invalid_login: "La connexion a échoué. Réessayez.",
  not_found: "Introuvable, ou vous n’y avez pas accès.",
  not_waiting: "Cette tâche n’attend pas de réponse de votre part.",
  not_running: "Seule une tâche en cours peut être mise en pause.",
  not_paused: "Cette tâche n’est pas en pause.",
  not_failed: "Seules les tâches en échec peuvent être relancées.",
  not_proposed: "Cette version n’attend pas de validation.",
  not_supported: "Cette opération n’est pas prise en charge.",
  orbit_login_failed: "ORBIT a refusé ces identifiants.",
  voice_unavailable: "La voix n’est pas disponible pour le moment. Vous pouvez continuer à écrire à NOVA.",
  audio_too_long: "Cet enregistrement est trop long — limitez-le à une minute et demie.",
  empty_audio: "NOVA n’a rien entendu.",
  validation_error: "Certains champs ne sont pas valides.",
  version_conflict: "Cet Artefact a changé depuis que vous l’avez ouvert. Rechargez-le pour continuer.",
  internal_error: "Une erreur s’est produite du côté de NOVA. Veuillez réessayer.",
  orbit_unauthorized: "Votre session ORBIT a expiré. Reconnectez ORBIT.",
  orbit_not_linked: "ORBIT n’est pas connecté. Connectez votre compte ORBIT.",
  orbit_forbidden: "Droits insuffisants dans ORBIT.",
  orbit_not_found: "Introuvable dans ORBIT.",
  orbit_unavailable: "ORBIT est indisponible pour le moment. Réessayez.",
  orbit_invalid: "ORBIT a refusé la demande.",
};

/** The error message in the interface language: known detail, else the code's message, else the English detail. */
export function apiErrorMessage(code: string, detail: string, lang: Lang = getLang()): string {
  if (lang === "en") return detail;
  return DETAIL_FR[detail] ?? (code.startsWith("orbit_") ? knownSystemLabel(detail, lang) : null) ?? CODE_FR[code] ?? detail;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public actions: Action[] = [],
    /** The API's English detail (`message` is localized). */
    public detail: string = message,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method,
    credentials: "include",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (response.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
  }
  if (!response.ok) {
    let data: Partial<ApiErrorBody> = {};
    try {
      data = await response.json();
    } catch {
      /* non-JSON error */
    }
    const code = data.code ?? "error";
    const detail = data.detail ?? "Something went wrong.";
    throw new ApiError(response.status, code, apiErrorMessage(code, detail), data.actions ?? [], detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

export function qs(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : "";
}
