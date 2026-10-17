"use client";

import { Badge, Button } from "@nova/ui";

import { useRevokeLink, useTestLink, useWorkspaceLinks } from "@/lib/api/hooks";
import type { FederatedLink, FederatedStatus, WorkspaceLinks } from "@/lib/api/types";
import { dateTime } from "@/lib/format";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    orbit: "ORBIT",
    forge: "FORGE",
    s_ok: "Healthy",
    s_expiring: "Expires soon",
    s_expired: "Expired",
    s_revoked: "Revoked",
    s_degraded: "Degraded",
    s_unlinked: "Not linked",
    s_not_configured: "Not configured",
    hint_unlinked: "NOVA holds no sign-in of yours for this service yet. Reconnect, or run the test to check the link.",
    hint_expired: "Your sign-in at the identity provider is over: NOVA can no longer act for you. Reconnect.",
    hint_revoked_user: "You revoked this delegation: NOVA does not act for you here until you reconnect.",
    hint_revoked_orbit: "ORBIT removed you from a project: the delegation stops until you reconnect.",
    hint_degraded: "The last exchange or call failed. NOVA never falls back to a key or another identity: nothing is done in your name meanwhile.",
    hint_not_configured: "This service is not configured on NOVA's side.",
    identity: "Who acts",
    identityValue: "you ({sub})",
    email: "E-mail",
    issuer: "Issuer",
    amr: "Sign-in method",
    act: "Acting on your behalf",
    actNone: "no one (direct)",
    actValue: "{sub} acts for you",
    project: "Target project",
    projectNone: "no project named",
    workspace: "Workspace",
    expiry: "Token",
    expiresAt: "expires {at} ({left})",
    left: "{n} s left",
    renewal: "exchanged again at the next call, never stored",
    session: "Your sign-in lasts until",
    scope: "Scope",
    role: "Role in the service",
    roleNone: "none (your project role stays local)",
    clearance: "Effective clearance",
    reason_no_cap: "your organisation sets no ceiling",
    reason_local: "your own clearance is the lower one (ceiling C{cap})",
    reason_capped_by_token: "capped by your organisation: C{cap} (yours is C{local})",
    exchange: "Last exchange",
    exchangeValue: "{status} · {at} · {ms} ms",
    exchangeErrors: "{n} consecutive error(s)",
    roundtrip: "Last round trip",
    roundtripValue: "{operation} · {status} · {ms} ms · {at}",
    never: "never",
    reconnect: "Reconnect",
    revoke: "Revoke delegation",
    test: "Test the link",
    testing: "Testing…",
    testOk: "Link works (a call that reads no data).",
    testFailed: "The test failed: {result}",
    workspaceTitle: "Links of the workspace",
    workspaceHint: "State of each member's links. Statuses only: no identity detail, no content.",
    member: "Member",
    noMembers: "No member has signed in through the identity provider yet.",
  },
  fr: {
    orbit: "ORBIT",
    forge: "FORGE",
    s_ok: "En bonne santé",
    s_expiring: "Expire bientôt",
    s_expired: "Expiré",
    s_revoked: "Révoqué",
    s_degraded: "Dégradé",
    s_unlinked: "Non lié",
    s_not_configured: "Non configuré",
    hint_unlinked: "NOVA ne détient pas encore de connexion de votre part pour ce service. Reconnectez-vous, ou lancez le test pour vérifier le lien.",
    hint_expired: "Votre connexion auprès du fournisseur d’identité est terminée : NOVA ne peut plus agir en votre nom. Reconnectez-vous.",
    hint_revoked_user: "Vous avez révoqué cette délégation : NOVA n’agit pas en votre nom ici tant que vous ne vous reconnectez pas.",
    hint_revoked_orbit: "ORBIT vous a retiré d’un projet : la délégation s’arrête jusqu’à votre reconnexion.",
    hint_degraded: "Le dernier échange ou appel a échoué. NOVA ne se rabat jamais sur une clé ni sur une autre identité : rien n’est fait en votre nom en attendant.",
    hint_not_configured: "Ce service n’est pas configuré du côté de NOVA.",
    identity: "Qui agit",
    identityValue: "vous ({sub})",
    email: "E-mail",
    issuer: "Émetteur",
    amr: "Méthode de connexion",
    act: "Agit en votre nom",
    actNone: "personne (direct)",
    actValue: "{sub} agit pour vous",
    project: "Projet cible",
    projectNone: "aucun projet nommé",
    workspace: "Espace",
    expiry: "Jeton",
    expiresAt: "expire le {at} ({left})",
    left: "{n} s restantes",
    renewal: "échangé à nouveau au prochain appel, jamais conservé",
    session: "Votre connexion dure jusqu’au",
    scope: "Périmètre",
    role: "Rôle dans le service",
    roleNone: "aucun (votre rôle de projet reste local)",
    clearance: "Habilitation effective",
    reason_no_cap: "votre organisation ne fixe pas de plafond",
    reason_local: "votre habilitation est la plus basse (plafond C{cap})",
    reason_capped_by_token: "plafonnée par votre organisation : C{cap} (la vôtre est C{local})",
    exchange: "Dernier échange",
    exchangeValue: "{status} · {at} · {ms} ms",
    exchangeErrors: "{n} erreur(s) consécutive(s)",
    roundtrip: "Dernier aller-retour",
    roundtripValue: "{operation} · {status} · {ms} ms · {at}",
    never: "jamais",
    reconnect: "Reconnecter",
    revoke: "Révoquer la délégation",
    test: "Tester le lien",
    testing: "Test en cours…",
    testOk: "Le lien fonctionne (un appel qui ne lit aucune donnée).",
    testFailed: "Le test a échoué : {result}",
    workspaceTitle: "Liens de l’espace",
    workspaceHint: "État des liens de chaque membre. Statuts uniquement : aucun détail d’identité, aucun contenu.",
    member: "Membre",
    noMembers: "Aucun membre ne s’est encore connecté par le fournisseur d’identité.",
  },
});

export const FEDERATED_TONE: Record<FederatedStatus, "success" | "warning" | "danger" | "neutral"> = {
  ok: "success",
  expiring: "warning",
  degraded: "warning",
  expired: "danger",
  revoked: "danger",
  unlinked: "neutral",
  not_configured: "neutral",
};

function Row({ label, children, testId }: { label: string; children: React.ReactNode; testId?: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-1.5 text-[13px]">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right" data-testid={testId}>{children}</dd>
    </div>
  );
}

export function FederatedSection({ link }: { link: FederatedLink }) {
  const t = useT(M);
  const revoke = useRevokeLink();
  const test = useTestLink();
  const hint =
    link.status === "unlinked" ? t("hint_unlinked")
    : link.status === "expired" ? t("hint_expired")
    : link.status === "revoked" ? (link.revoked_reason === "user" ? t("hint_revoked_user") : t("hint_revoked_orbit"))
    : link.status === "degraded" ? t("hint_degraded")
    : link.status === "not_configured" ? t("hint_not_configured")
    : null;
  const { identity, project, expiry, scope, last_exchange: exchange, roundtrip } = link;
  const reason = t(`reason_${scope.clearance.reason}` as "reason_local", { cap: scope.clearance.cap, local: scope.clearance.local });
  const result = test.data;
  return (
    <section data-testid={`federated-${link.service}`} data-status={link.status}>
      <h4 className="flex items-center gap-2 text-[14px] font-semibold">
        {t(link.service)} <Badge tone={FEDERATED_TONE[link.status]}>{t(`s_${link.status}` as "s_ok")}</Badge>
      </h4>
      {hint ? <p role="alert" className="mt-2 rounded-[10px] border border-warning/40 bg-warning/[0.06] px-3 py-2 text-[13px]" data-testid="federated-hint">{hint}</p> : null}
      {link.linked ? (
        <dl className="mt-1 divide-y divide-border/60">
          <Row label={t("identity")} testId="federated-identity">{identity.sub ? t("identityValue", { sub: identity.sub }) : "—"}</Row>
          {identity.email ? <Row label={t("email")}>{identity.email}</Row> : null}
          {identity.issuer ? <Row label={t("issuer")}>{identity.issuer}</Row> : null}
          <Row label={t("amr")} testId="federated-amr">{identity.amr.length ? identity.amr.join(", ") : "—"}</Row>
          <Row label={t("act")} testId="federated-act">{identity.act ? t("actValue", { sub: identity.act }) : t("actNone")}</Row>
          <Row label={t("project")} testId="federated-project">
            {project.alias || project.orion_project_id ? (
              <>
                {project.alias ? <code className="text-[12.5px]">{project.alias}</code> : null}
                {project.orion_project_id ? <span className="ml-2 text-[12px] text-muted">{project.orion_project_id}</span> : null}
              </>
            ) : t("projectNone")}
          </Row>
          {project.workspace_id ? <Row label={t("workspace")}>{project.workspace_id}</Row> : null}
          <Row label={t("expiry")} testId="federated-expiry">
            {expiry.expires_at ? t("expiresAt", { at: dateTime(expiry.expires_at), left: t("left", { n: expiry.remaining_seconds ?? 0 }) }) : "—"}
            <span className="block text-[12px] text-muted">{t("renewal")}</span>
          </Row>
          {expiry.session_expires_at ? <Row label={t("session")}>{dateTime(expiry.session_expires_at)}</Row> : null}
          <Row label={t("scope")} testId="federated-scope">{scope.scopes.length ? scope.scopes.join(", ") : "—"}</Row>
          <Row label={t("role")}>{scope.roles.length ? scope.roles.join(", ") : t("roleNone")}</Row>
          <Row label={t("clearance")} testId="federated-clearance">
            {`C${scope.clearance.effective}`}
            <span className="block text-[12px] text-muted">{reason}</span>
          </Row>
          <Row label={t("exchange")} testId="federated-exchange">
            {exchange.at ? t("exchangeValue", { status: exchange.status ?? "ok", at: dateTime(exchange.at), ms: exchange.exchange_ms ?? 0 }) : t("never")}
            {exchange.consecutive_errors > 0 ? (
              <span className="block text-[12px] text-warning">{t("exchangeErrors", { n: exchange.consecutive_errors })}{exchange.last_error ? ` · ${exchange.last_error}` : ""}</span>
            ) : null}
          </Row>
          <Row label={t("roundtrip")} testId="federated-roundtrip">
            {roundtrip ? t("roundtripValue", { operation: roundtrip.operation, status: roundtrip.status, ms: roundtrip.latency_ms, at: dateTime(roundtrip.at) }) : t("never")}
          </Row>
        </dl>
      ) : null}
      {link.actions.length ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {link.actions.includes("reconnect") ? (
            <Button variant="ghost" size="sm" onClick={() => window.location.assign("/api/v1/auth/login?next=%2Fsettings%23links")} data-testid="federated-reconnect">{t("reconnect")}</Button>
          ) : null}
          {link.actions.includes("test") ? (
            <Button variant="ghost" size="sm" disabled={test.isPending} onClick={() => test.mutate(link.service)} data-testid="federated-test">
              {test.isPending ? t("testing") : t("test")}
            </Button>
          ) : null}
          {link.actions.includes("revoke") && link.status !== "revoked" && link.linked ? (
            <Button variant="ghost" size="sm" disabled={revoke.isPending} onClick={() => revoke.mutate(link.service)} data-testid="federated-revoke">{t("revoke")}</Button>
          ) : null}
          {result ? (
            <span className="text-[12.5px] text-muted" role="status" data-testid="federated-test-result">
              {result.result === "ok" ? t("testOk") : t("testFailed", { result: result.result })}
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function WorkspaceTable({ data }: { data: WorkspaceLinks }) {
  const t = useT(M);
  if (data.members.length === 0) return <p className="text-[13px] text-muted">{t("noMembers")}</p>;
  return (
    <table className="w-full text-left text-[13px]" data-testid="workspace-links">
      <thead>
        <tr className="text-muted"><th className="py-1 pr-3 font-medium">{t("member")}</th><th className="pr-3 font-medium">{t("orbit")}</th><th className="font-medium">{t("forge")}</th></tr>
      </thead>
      <tbody>
        {data.members.map((m) => (
          <tr key={m.user_id} className="border-t border-border/60" data-testid="workspace-link-row">
            <td className="py-1.5 pr-3">{m.name} <span className="text-[12px] text-muted">{m.email}</span></td>
            {(["orbit", "forge"] as const).map((s) => (
              <td key={s} className="pr-3"><Badge tone={FEDERATED_TONE[m.services[s].status]}>{t(`s_${m.services[s].status}` as "s_ok")}</Badge>
                {m.services[s].consecutive_errors > 0 ? <span className="ml-1 text-[12px] text-warning">×{m.services[s].consecutive_errors}</span> : null}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Administrators: the state of the workspace's federated links, statuses only. */
export function WorkspaceLinksSection({ isAdmin }: { isAdmin: boolean }) {
  const t = useT(M);
  const { data } = useWorkspaceLinks(isAdmin);
  if (!isAdmin || !data || data.mode !== "token_exchange") return null;
  return (
    <section data-testid="workspace-links-section">
      <h4 className="text-[14px] font-semibold">{t("workspaceTitle")}</h4>
      <p className="mb-2 mt-0.5 text-[13px] text-muted">{t("workspaceHint")}</p>
      <WorkspaceTable data={data} />
    </section>
  );
}
