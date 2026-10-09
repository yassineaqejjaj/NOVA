"use client";

import { Badge, Button, Input, Label } from "@nova/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api/client";
import type { FigmaStatus } from "@/lib/api/types";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    connectedAs: "Connected to Figma as {name}",
    connectedToast: "Figma connected.",
    tokenSavedToast: "Figma token saved.",
    disconnect: "Disconnect",
    connect: "Connect with Figma",
    redirecting: "Redirecting to Figma…",
    oauthUnavailable: "Connecting with Figma is not enabled on this NOVA yet: it needs a Figma OAuth client configured by your administrator. You can use a personal access token below in the meantime.",
    mcp: "MCP",
    mcpHint: "Connected through Figma MCP",
    canWrite: "Can write to the canvas",
    readOnly: "Read-only",
    modeOauth: "Figma account",
    modeToken: "Access token",
    tokenTitle: "Or use a personal access token",
    tokenHint: "Read-only degraded mode: NOVA can read your Figma files (frames, variables, images) to generate code and audits, but cannot create or edit anything in Figma. Create a token in Figma with read-only scopes.",
    token: "Figma personal access token",
    saveToken: "Save token",
    tokenNotice: "Stored encrypted. NOVA never writes to your files with a token.",
    upgradeHint: "Connect with Figma to let NOVA push mockups to your files.",
  },
  fr: {
    connectedAs: "Connecté à Figma en tant que {name}",
    connectedToast: "Figma connecté.",
    tokenSavedToast: "Jeton Figma enregistré.",
    disconnect: "Déconnecter",
    connect: "Se connecter avec Figma",
    redirecting: "Redirection vers Figma…",
    oauthUnavailable: "La connexion avec Figma n’est pas encore activée sur ce NOVA : elle nécessite un client OAuth Figma configuré par votre administrateur. Vous pouvez utiliser un jeton d’accès personnel ci-dessous en attendant.",
    mcp: "MCP",
    mcpHint: "Connecté via Figma MCP",
    canWrite: "Peut écrire dans le canevas",
    readOnly: "Lecture seule",
    modeOauth: "Compte Figma",
    modeToken: "Jeton d’accès",
    tokenTitle: "Ou utilisez un jeton d’accès personnel",
    tokenHint: "Mode dégradé en lecture seule : NOVA peut lire vos fichiers Figma (cadres, variables, images) pour générer du code et des audits, mais ne peut rien créer ni modifier dans Figma. Créez un jeton dans Figma avec des portées en lecture seule.",
    token: "Jeton d’accès personnel Figma",
    saveToken: "Enregistrer le jeton",
    tokenNotice: "Stocké chiffré. NOVA n’écrit jamais dans vos fichiers avec un jeton.",
    upgradeHint: "Connectez-vous avec Figma pour que NOVA puisse pousser des maquettes dans vos fichiers.",
  },
});

const KEY = ["figma"] as const;

/** Link Figma: OAuth through the Figma MCP server (read + write), or a personal access token (read-only fallback). */
export function FigmaLink() {
  const t = useT(M);
  const client = useQueryClient();
  const router = useRouter();
  const [token, setToken] = useState("");
  const { data: status } = useQuery({ queryKey: KEY, queryFn: () => api.get<FigmaStatus>("/me/figma") });

  // Return from the OAuth callback: /settings?figma=connected
  const handled = useRef(false);
  useEffect(() => {
    if (handled.current || typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (url.searchParams.get("figma") !== "connected") return;
    handled.current = true;
    toast(t("connectedToast"));
    void client.invalidateQueries({ queryKey: KEY });
    url.searchParams.delete("figma");
    router.replace(`${url.pathname}${url.search}${url.hash}`);
  }, [client, router, t]);

  const connect = useMutation({
    mutationFn: () => api.post<{ authorize_url: string }>("/me/figma/connect"),
    onSuccess: (r) => {
      window.location.href = r.authorize_url;
    },
  });
  const saveToken = useMutation({
    mutationFn: () => api.post("/me/figma/token", { token }),
    onSuccess: () => {
      setToken("");
      toast(t("tokenSavedToast"));
      void client.invalidateQueries({ queryKey: KEY });
    },
  });
  const unlink = useMutation({ mutationFn: () => api.delete("/me/figma"), onSuccess: () => void client.invalidateQueries({ queryKey: KEY }) });

  if (!status) return null;
  const oauth = status.oauth_available;
  const error = (e: unknown) => (e instanceof ApiError ? <p role="alert" className="text-[13px] text-danger">{e.message}</p> : null);

  const connectBlock = (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" size="sm" onClick={() => connect.mutate()} disabled={!oauth || connect.isPending} aria-describedby={oauth ? undefined : "figma-oauth-unavailable"}>
          {connect.isPending || connect.isSuccess ? t("redirecting") : t("connect")}
        </Button>
        {status.linked && status.mode === "token" ? <span className="text-[12px] text-subtle">{t("upgradeHint")}</span> : null}
      </div>
      {!oauth ? <p id="figma-oauth-unavailable" className="text-[12.5px] text-subtle">{t("oauthUnavailable")}</p> : null}
      {error(connect.error)}
    </div>
  );

  const tokenBlock = (
    <form onSubmit={(e) => { e.preventDefault(); if (token.trim()) saveToken.mutate(); }} className="space-y-2">
      <div>
        <h3 className="text-[13px] font-medium">{t("tokenTitle")}</h3>
        <p className="mt-0.5 text-[12.5px] text-muted">{t("tokenHint")}</p>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <div className="flex-1 space-y-1.5">
          <Label htmlFor="figma-token">{t("token")}</Label>
          <Input id="figma-token" type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" placeholder="figd_…" />
        </div>
        <Button type="submit" size="sm" variant="secondary" disabled={!token.trim() || saveToken.isPending}>{t("saveToken")}</Button>
      </div>
      {error(saveToken.error)}
      <p className="text-[12px] text-subtle">{t("tokenNotice")}</p>
    </form>
  );

  return (
    <div className="space-y-5">
      {status.linked ? (
        <div className="flex flex-wrap items-center gap-2 text-[13.5px]">
          <span className="size-2 rounded-full bg-success" aria-hidden />
          {t("connectedAs", { name: status.figma_handle || "Figma" })}
          {status.mode ? <Badge>{status.mode === "oauth" ? t("modeOauth") : t("modeToken")}</Badge> : null}
          {status.mcp ? <Badge tone="accent" title={t("mcpHint")}>{t("mcp")}</Badge> : null}
          <Badge tone={status.can_write ? "success" : "neutral"}>{status.can_write ? t("canWrite") : t("readOnly")}</Badge>
          <Button variant="ghost" size="sm" className="ml-auto" onClick={() => unlink.mutate()} disabled={unlink.isPending}>{t("disconnect")}</Button>
        </div>
      ) : null}
      {error(unlink.error)}
      {status.mode !== "oauth" ? connectBlock : null}
      {status.mode !== "oauth" ? tokenBlock : null}
    </div>
  );
}
