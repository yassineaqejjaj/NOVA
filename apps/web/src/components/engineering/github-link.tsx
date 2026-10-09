"use client";

import { Badge, Button, Input, Label } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api/client";
import { engKeys, type GithubStatus, useGithub } from "@/lib/api/engineering";
import { useT } from "@/lib/i18n";

import { M } from "./engineering.messages";

/** Settings → GitHub: personal access token, encrypted at rest. */
export function GithubLink() {
  const t = useT(M);
  const client = useQueryClient();
  const { data } = useGithub();
  const [token, setToken] = useState("");
  const link = useMutation({
    mutationFn: () => api.put<GithubStatus>("/me/github", { token: token.trim() }),
    onSuccess: (next) => {
      client.setQueryData(engKeys.github, next);
      void client.invalidateQueries({ queryKey: engKeys.repos });
      setToken("");
      toast(t("ghSaved"));
    },
  });
  const unlink = useMutation({
    mutationFn: () => api.delete("/me/github"),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: engKeys.github });
      void client.invalidateQueries({ queryKey: engKeys.repos });
    },
  });
  if (!data) return null;
  const err = (e: unknown) => (e instanceof ApiError ? <p role="alert" className="text-[13px] text-danger">{e.message}</p> : null);
  return (
    <div className="space-y-4">
      {data.linked ? (
        <div className="flex flex-wrap items-center gap-2 text-[13.5px]">
          <span className="size-2 rounded-full bg-success" aria-hidden />
          {t("ghConnected", { login: data.login })}
          {data.scopes ? <Badge>{data.scopes}</Badge> : null}
          <Button variant="ghost" size="sm" className="ml-auto" onClick={() => unlink.mutate()} disabled={unlink.isPending}>{t("ghRemove")}</Button>
        </div>
      ) : null}
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (token.trim().length >= 10) link.mutate();
        }}
      >
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="gh-token">{t("ghToken")}</Label>
            <Input id="gh-token" type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" placeholder="github_pat_…" />
          </div>
          <Button type="submit" size="sm" variant={data.linked ? "secondary" : "primary"} disabled={token.trim().length < 10 || link.isPending}>{t("ghSave")}</Button>
        </div>
        {err(link.error)}
        <p className="text-[12.5px] text-muted">{t("ghTokenHelp")}</p>
        <p className="text-[12px] text-subtle">{t("ghStored")}</p>
      </form>
    </div>
  );
}
