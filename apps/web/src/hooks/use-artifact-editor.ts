"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api/client";
import { keys, useArtifact, useArtifactComments } from "@/lib/api/hooks";
import type { ArtifactContent, SectionContent } from "@/lib/api/types";

export type SaveState = { kind: "idle" } | { kind: "saving" } | { kind: "saved"; version: number } | { kind: "conflict" } | { kind: "error"; message: string };

/** Artifact editing state shared by the split panel and the full-page editor: optimistic autosave with
 * conflict detection, version viewing, proposed-version approval. */
export function useArtifactEditor(artifactId: string) {
  const client = useQueryClient();
  const [viewVersion, setViewVersion] = useState<number | null>(null);
  const { data: artifact, isLoading, error } = useArtifact(artifactId, viewVersion);
  const { data: comments } = useArtifactComments(artifactId);
  const [draft, setDraft] = useState<ArtifactContent | null>(null);
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [baseVersion, setBaseVersion] = useState<number | null>(null);
  const [save, setSave] = useState<SaveState>({ kind: "idle" });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const viewingOld = viewVersion !== null && artifact && viewVersion !== artifact.version;
  const editable = !!artifact?.can_edit && !viewingOld && save.kind !== "conflict";

  // Adopt server content when nothing local is pending (new version from NOVA or a teammate).
  useEffect(() => {
    if (!artifact) return;
    // Only strictly newer versions are adopted, so a stale cache never rolls back what was just saved.
    if (dirty.size === 0 && (baseVersion === null || artifact.viewing_version > baseVersion || viewVersion !== null)) {
      setDraft(artifact.content);
      setBaseVersion(artifact.viewing_version);
    }
  }, [artifact, dirty.size, baseVersion, viewVersion]);

  const persist = useCallback(
    async (content: ArtifactContent, keysToSave: Set<string>, version: number) => {
      setSave({ kind: "saving" });
      const sections: Record<string, SectionContent> = {};
      for (const key of keysToSave) if (key !== "title") sections[key] = content.sections[key]!;
      try {
        const result = await api.patch<{ version: number }>(`/artifacts/${artifactId}`, {
          base_version: version,
          sections,
          title: keysToSave.has("title") ? content.title : undefined,
        });
        setBaseVersion(result.version);
        setDirty(new Set());
        setSave({ kind: "saved", version: result.version });
        void client.invalidateQueries({ queryKey: keys.artifactVersions(artifactId) });
        void client.invalidateQueries({ queryKey: ["artifact", artifactId] });
        void client.invalidateQueries({ queryKey: ["artifacts"] });
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) setSave({ kind: "conflict" });
        else setSave({ kind: "error", message: err instanceof Error ? err.message : "Save failed" });
      }
    },
    [artifactId, client],
  );

  const schedule = (content: ArtifactContent, changedKey: string) => {
    const next = new Set(dirty).add(changedKey);
    setDraft(content);
    setDirty(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => baseVersion !== null && void persist(content, next, baseVersion), 1200);
  };

  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);

  const approve = useMutation({
    mutationFn: (version: number) => api.post(`/artifacts/${artifactId}/versions/${version}/approve`),
    onSuccess: () => {
      toast("Version approved.");
      setViewVersion(null);
      void client.invalidateQueries({ queryKey: ["artifact", artifactId] });
      void client.invalidateQueries({ queryKey: ["conversation"] });
    },
  });
  const setStatus = useMutation({
    mutationFn: (status: string) => api.patch(`/artifacts/${artifactId}`, { base_version: baseVersion, status }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["artifact", artifactId] }),
  });

  const reload = () => {
    setDirty(new Set());
    setBaseVersion(null);
    setSave({ kind: "idle" });
    void client.invalidateQueries({ queryKey: ["artifact", artifactId] });
  };

  return {
    artifact, isLoading, error, comments, draft, dirty, baseVersion, save, viewVersion, setViewVersion,
    viewingOld: !!viewingOld, editable, schedule, approve, setStatus, reload,
  };
}
