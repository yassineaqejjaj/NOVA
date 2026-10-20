"use client";

import { Badge, Skeleton } from "@nova/ui";

import { useLinks, useMe } from "@/lib/api/hooks";
import type { ForgeLink, Links, OrbitAgentKey } from "@/lib/api/types";
import { dateTime } from "@/lib/format";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    orbit: "ORBIT",
    forge: "FORGE",
    s_ok: "Healthy",
    s_degraded: "Last exchange failed",
    s_fallback: "Acting with the project key",
    s_expired: "Session expired",
    s_revoked: "Access revoked by Nova Context",
    revokedWarning: "Nova Context removed you from a project: your session was dropped and your clearance reset. Reconnect Nova Context to continue.",
    keyRevoked: "revoked by Nova Context",
    s_agent_key: "Project key only",
    s_unlinked: "Not connected",
    s_not_configured: "Not configured",
    fallbackWarning: "Your Nova Context session has expired: NOVA now acts with the project's agent key. That is a different identity with a reduced clearance. Reconnect Nova Context to act as yourself.",
    expiredWarning: "Your Nova Context session has expired and no project key is configured. Reconnect Nova Context.",
    acting: "Acting as",
    actingSession: "you (Nova Context session)",
    actingKey: "the project agent key",
    actingNone: "nobody",
    expires: "Session expires",
    expired: "Session expired",
    clearance: "Clearance",
    lastOk: "Last successful exchange",
    lastError: "Last error",
    never: "never",
    agentKeys: "Project agent keys",
    keyValid: "valid",
    keyRejected: "rejected by Nova Context",
    keyUnavailable: "not available (Nova Context does not report it)",
    keyScopes: "scopes",
    endpoint: "Endpoint",
    apiKey: "API key",
    present: "present",
    missing: "missing",
    inboundCredential: "Callback credential",
    callback: "Nova Quality calls NOVA at",
    capture: "Capture",
    queue: "Capture queue",
    queueNA: "not available",
    forgeOff: "Nova Quality is not configured: nothing is evaluated or captured.",
  },
  fr: {
    orbit: "ORBIT",
    forge: "FORGE",
    s_ok: "En bonne santé",
    s_degraded: "Dernier échange en erreur",
    s_fallback: "Agit avec la clé du projet",
    s_expired: "Session expirée",
    s_revoked: "Accès révoqué par Nova Context",
    revokedWarning: "Nova Context vous a retiré d’un projet : votre session a été supprimée et votre habilitation réinitialisée. Reconnectez Nova Context pour continuer.",
    keyRevoked: "révoquée par Nova Context",
    s_agent_key: "Clé de projet uniquement",
    s_unlinked: "Non connecté",
    s_not_configured: "Non configuré",
    fallbackWarning: "Votre session Nova Context a expiré : NOVA agit désormais avec la clé d’agent du projet. C’est une autre identité, avec une habilitation réduite. Reconnectez Nova Context pour agir en votre nom.",
    expiredWarning: "Votre session Nova Context a expiré et aucune clé de projet n’est configurée. Reconnectez Nova Context.",
    acting: "Agit en tant que",
    actingSession: "vous (session Nova Context)",
    actingKey: "la clé d’agent du projet",
    actingNone: "personne",
    expires: "La session expire",
    expired: "Session expirée",
    clearance: "Habilitation",
    lastOk: "Dernier échange réussi",
    lastError: "Dernière erreur",
    never: "jamais",
    agentKeys: "Clés d’agent des projets",
    keyValid: "valide",
    keyRejected: "refusée par Nova Context",
    keyUnavailable: "non disponible (Nova Context ne l’indique pas)",
    keyScopes: "périmètre",
    endpoint: "Adresse",
    apiKey: "Clé d’API",
    present: "présente",
    missing: "absente",
    inboundCredential: "Identifiant de rappel",
    callback: "Nova Quality rappelle NOVA à",
    capture: "Capture",
    queue: "File de capture",
    queueNA: "non disponible",
    forgeOff: "Nova Quality n’est pas configuré : rien n’est évalué ni capturé.",
  },
});

const TONE = { ok: "success", degraded: "warning", fallback: "warning", expired: "danger", revoked: "danger", agent_key: "neutral", unlinked: "neutral", not_configured: "neutral" } as const;

function Row({ label, children, testId }: { label: string; children: React.ReactNode; testId?: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-1.5 text-[13px]">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right" data-testid={testId}>{children}</dd>
    </div>
  );
}

function AgentKey({ k }: { k: OrbitAgentKey }) {
  const t = useT(M);
  const state = k.reason === "revoked" ? t("keyRevoked") : !k.available ? t("keyUnavailable") : k.valid ? t("keyValid") : t("keyRejected");
  return (
    <li className="flex flex-wrap items-center gap-2" data-testid="agent-key">
      <code className="text-[12.5px]">{k.project}</code>
      <Badge tone={k.available && k.valid ? "success" : k.available || k.reason === "revoked" ? "danger" : "neutral"}>{state}</Badge>
      {k.available && k.valid ? (
        <span className="text-[12px] text-muted">
          {k.clearance != null ? `C${k.clearance}` : ""}{k.scopes?.length ? ` · ${t("keyScopes")}: ${k.scopes.join(", ")}` : ""}
        </span>
      ) : null}
    </li>
  );
}

function OrbitSection({ orbit }: { orbit: Links["orbit"] }) {
  const t = useT(M);
  const acting = orbit.mode === "session" ? t("actingSession") : orbit.mode === "agent_key" ? t("actingKey") : t("actingNone");
  return (
    <section data-testid="link-orbit" data-status={orbit.status}>
      <h4 className="flex items-center gap-2 text-[14px] font-semibold">{t("orbit")} <Badge tone={TONE[orbit.status]}>{t(`s_${orbit.status}` as "s_ok")}</Badge></h4>
      {orbit.fallback ? <p role="alert" className="mt-2 rounded-[10px] border border-warning/40 bg-warning/[0.06] px-3 py-2 text-[13px]" data-testid="orbit-fallback">{t("fallbackWarning")}</p> : null}
      {orbit.status === "revoked" ? <p role="alert" className="mt-2 text-[13px] text-danger" data-testid="orbit-revoked">{t("revokedWarning")}</p> : null}
      {orbit.status === "expired" ? <p role="alert" className="mt-2 text-[13px] text-danger">{t("expiredWarning")}</p> : null}
      <dl className="mt-1 divide-y divide-border/60">
        <Row label={t("acting")} testId="orbit-acting">{acting}</Row>
        {orbit.expires_at ? <Row label={orbit.session_expired ? t("expired") : t("expires")}>{dateTime(orbit.expires_at)}</Row> : null}
        {orbit.clearance != null ? <Row label={t("clearance")}>{`C${orbit.clearance}`}</Row> : null}
        <Row label={t("lastOk")}>{orbit.last_success_at ? dateTime(orbit.last_success_at) : t("never")}</Row>
        {orbit.last_error_at ? <Row label={t("lastError")}>{`${dateTime(orbit.last_error_at)} · ${orbit.last_error ?? ""}`}</Row> : null}
      </dl>
      {orbit.agent_keys.length > 0 ? (
        <div className="mt-2">
          <h5 className="text-[12px] font-semibold uppercase tracking-wide text-subtle">{t("agentKeys")}</h5>
          <ul className="mt-1 space-y-1">{orbit.agent_keys.map((k) => <AgentKey key={k.project} k={k} />)}</ul>
        </div>
      ) : null}
    </section>
  );
}

function ForgeSection({ forge }: { forge: ForgeLink }) {
  const t = useT(M);
  return (
    <section data-testid="link-forge" data-status={forge.status}>
      <h4 className="flex items-center gap-2 text-[14px] font-semibold">{t("forge")} <Badge tone={TONE[forge.status]}>{t(`s_${forge.status}` as "s_ok")}</Badge></h4>
      {!forge.configured ? <p className="mt-2 text-[13px] text-muted">{t("forgeOff")}</p> : null}
      {forge.configured && forge.problems.length > 0 ? (
        <ul className="mt-2 list-disc pl-5 text-[13px] text-warning" data-testid="forge-problems">{forge.problems.map((p) => <li key={p}>{p}</li>)}</ul>
      ) : null}
      <dl className="mt-1 divide-y divide-border/60">
        <Row label={t("endpoint")}>{forge.endpoint || "—"}</Row>
        <Row label={t("apiKey")}>{forge.api_key_present ? t("present") : t("missing")}</Row>
        <Row label={t("inboundCredential")}>{forge.inbound_credential_set ? t("present") : t("missing")}</Row>
        <Row label={t("callback")}>{forge.callback_endpoint || "—"}</Row>
        <Row label={t("capture")}>{`${forge.capture_mode} · ${forge.capture_policy}`}</Row>
        <Row label={t("queue")}>{forge.capture_queue == null ? t("queueNA") : String(forge.capture_queue)}</Row>
        <Row label={t("lastOk")}>{forge.last_success_at ? dateTime(forge.last_success_at) : t("never")}</Row>
        {forge.last_error_at ? <Row label={t("lastError")}>{`${dateTime(forge.last_error_at)} · ${forge.last_error ?? ""}`}</Row> : null}
      </dl>
    </section>
  );
}

/** Settings → Links: who acts in ORBIT, until when, with which clearance, and the health of the ORBIT and FORGE links. */
export function LinksCard() {
  const { data } = useLinks();
  const me = useMe();
  if (!data) return <Skeleton className="h-32" />;
  return (
    <div className="space-y-5" data-testid="links-card" aria-live="polite" data-admin={me.data?.is_admin ? "true" : "false"}>
      <OrbitSection orbit={data.orbit} />
      {data.forge ? <ForgeSection forge={data.forge} /> : null}
    </div>
  );
}
