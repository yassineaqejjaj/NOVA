"use client";

import { Badge, Button, Skeleton } from "@nova/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorNotice } from "@/components/shell/page";
import { api, ApiError, qs } from "@/lib/api/client";
import type { SnapshotDetail, SnapshotInfo, SnapshotRef } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    title: "ORBIT snapshots",
    hint: "Versioned contexts created in ORBIT. NOVA only remembers which one you want agents to use; the content stays in ORBIT and is read with your rights.",
    loadFailed: "ORBIT could not list the snapshots",
    empty: "No snapshot in this project yet. Create one in ORBIT's Explorer.",
    versions: (v: { n: number }) => `${v.n} version${v.n === 1 ? "" : "s"}`,
    latest: "latest v{v}",
    select: "Preview",
    active: "Used by agents",
    activeVersion: "Used by agents · v{v}",
    activeLatest: "Used by agents · latest",
    use: "Use for agents",
    stop: "Stop using",
    preview: "Preview",
    version: "Version",
    items: (v: { n: number }) => `${v.n} item${v.n === 1 ? "" : "s"}`,
    tokens: "{n} tokens",
    forgotten: "forgotten",
    previewFailed: "ORBIT could not provide this snapshot",
    followLatest: "Follow the latest version",
    pinVersion: "Pin this version",
    saved: "Reference saved",
    removed: "Reference removed",
  },
  fr: {
    title: "Snapshots ORBIT",
    hint: "Contextes versionnés créés dans ORBIT. NOVA retient seulement celui que vous voulez faire utiliser aux agents ; le contenu reste dans ORBIT et est lu avec vos droits.",
    loadFailed: "ORBIT n’a pas pu lister les snapshots",
    empty: "Aucun snapshot dans ce projet pour l’instant. Créez-en un dans l’Explorer d’ORBIT.",
    versions: (v: { n: number }) => `${v.n} version${v.n > 1 ? "s" : ""}`,
    latest: "dernière v{v}",
    select: "Aperçu",
    active: "Utilisé par les agents",
    activeVersion: "Utilisé par les agents · v{v}",
    activeLatest: "Utilisé par les agents · dernière version",
    use: "Utiliser pour les agents",
    stop: "Ne plus utiliser",
    preview: "Aperçu",
    version: "Version",
    items: (v: { n: number }) => `${v.n} élément${v.n > 1 ? "s" : ""}`,
    tokens: "{n} jetons",
    forgotten: "oublié",
    previewFailed: "ORBIT n’a pas pu fournir ce snapshot",
    followLatest: "Suivre la dernière version",
    pinVersion: "Figer cette version",
    saved: "Référence enregistrée",
    removed: "Référence retirée",
  },
});

interface Listing { snapshots: SnapshotInfo[]; reference: SnapshotRef | null }

export function SnapshotsSection({ projectId }: { projectId: string }) {
  const t = useT(M);
  const client = useQueryClient();
  const [selected, setSelected] = useState<{ name: string; version: number | null } | null>(null);
  const listKey = ["context-snapshots", projectId];
  const list = useQuery({ queryKey: listKey, queryFn: () => api.get<Listing>(`/context/snapshots${qs({ project_id: projectId })}`) });
  const detail = useQuery({
    queryKey: ["context-snapshot", projectId, selected?.name, selected?.version],
    queryFn: () => api.get<{ snapshot: SnapshotDetail }>(`/context/snapshots/${encodeURIComponent(selected!.name)}${qs({ project_id: projectId, version: selected!.version })}`),
    enabled: !!selected,
  });
  const reference = list.data?.reference ?? null;
  const use = useMutation({
    mutationFn: (ref: SnapshotRef) => api.put("/context/snapshots/reference", { project_id: projectId, name: ref.name, version: ref.version }),
    onSuccess: () => { toast(t("saved")); return client.invalidateQueries({ queryKey: listKey }); },
  });
  const stop = useMutation({
    mutationFn: () => api.delete(`/context/snapshots/reference${qs({ project_id: projectId })}`),
    onSuccess: () => { toast(t("removed")); return client.invalidateQueries({ queryKey: listKey }); },
  });
  const snap = detail.data?.snapshot;
  const activeLabel = (s: SnapshotInfo) => (reference?.name === s.name ? (reference.version ? t("activeVersion", { v: reference.version }) : t("activeLatest")) : null);
  const mutationError = use.error ?? stop.error;

  return (
    <section aria-labelledby="orbit-snapshots-title">
      <h2 id="orbit-snapshots-title" className="mb-1 text-[12px] font-medium uppercase tracking-wider text-subtle">{t("title")}</h2>
      <p className="mb-3 text-[12.5px] text-subtle">{t("hint")}</p>
      {list.isLoading ? <Skeleton className="h-20" /> : null}
      {list.error instanceof ApiError ? <ErrorNotice title={t("loadFailed")} message={list.error.message} /> : null}
      {mutationError instanceof ApiError ? <ErrorNotice title={t("previewFailed")} message={mutationError.message} /> : null}
      {list.data && list.data.snapshots.length === 0 ? <p className="text-[13px] text-subtle">{t("empty")}</p> : null}
      <ul className="space-y-2">
        {list.data?.snapshots.map((s) => {
          const active = activeLabel(s);
          const isSelected = selected?.name === s.name;
          return (
            <li key={s.name} className={`rounded-[10px] border bg-surface px-3 py-2 ${isSelected ? "border-accent" : "border-border"}`}>
              <div className="flex flex-wrap items-center gap-2 text-[13.5px]">
                <Camera className="size-3.5 text-subtle" aria-hidden />
                <button type="button" aria-pressed={isSelected} onClick={() => setSelected({ name: s.name, version: null })} className="font-medium hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">{s.name}</button>
                <Badge>{t("latest", { v: s.latest_version })}</Badge>
                <span className="text-[11.5px] text-subtle">{t("versions", { n: s.versions })}</span>
                {active ? <Badge tone="success">{active}</Badge> : null}
                <span className="ml-auto text-[11.5px] text-subtle">{s.updated_at ? timeAgo(s.updated_at) : ""}</span>
              </div>
              {s.last_task ? <p className="mt-0.5 line-clamp-1 text-[12.5px] text-muted">{s.last_task}</p> : null}
              <div className="mt-1.5 flex gap-2">
                {reference?.name === s.name ? (
                  <Button size="sm" variant="ghost" disabled={stop.isPending} onClick={() => stop.mutate()}>{t("stop")}</Button>
                ) : (
                  <Button size="sm" disabled={use.isPending} onClick={() => use.mutate({ name: s.name, version: null })}>{t("use")}</Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {selected ? (
        <div className="mt-3 rounded-[12px] border border-border bg-surface p-3" aria-live="polite">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[12.5px]">
            <span className="font-medium">{t("preview")} · {selected.name}</span>
            {snap ? <>
              <Badge>{t("version")} {snap.version}</Badge>
              <span className="text-subtle">{t("items", { n: snap.items.length })} · {t("tokens", { n: snap.token_count })}</span>
            </> : null}
            {snap && list.data ? (
              <span className="ml-auto flex gap-2">
                <Button size="sm" variant="ghost" disabled={use.isPending} onClick={() => use.mutate({ name: snap.name, version: snap.version })}>{t("pinVersion")}</Button>
                <Button size="sm" variant="ghost" disabled={use.isPending} onClick={() => use.mutate({ name: snap.name, version: null })}>{t("followLatest")}</Button>
              </span>
            ) : null}
          </div>
          {detail.isLoading ? <Skeleton className="h-24" /> : null}
          {detail.error instanceof ApiError ? <ErrorNotice title={t("previewFailed")} message={detail.error.message} /> : null}
          {snap ? <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-[8px] bg-surface-2 p-3 text-[12.5px] text-muted" tabIndex={0}>{snap.content}</pre> : null}
          {snap?.items.some((i) => i.forgotten) ? <p className="mt-1 text-[11.5px] text-subtle">{snap.items.filter((i) => i.forgotten).length} {t("forgotten")}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
