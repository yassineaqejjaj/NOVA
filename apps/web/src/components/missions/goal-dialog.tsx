"use client";

import { Button, Dialog, DialogContent, Input, Label, Select, Textarea } from "@nova/ui";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/client";
import { useMe, useProjects } from "@/lib/api/hooks";
import { type GoalAutonomy, useCreateGoal } from "@/lib/api/missions";
import { useLang, useT } from "@/lib/i18n";

import { M } from "./missions.messages";
import { AutonomyLevels } from "./ui";

/** "Entrust to NOVA": a goal, its expected result, a due date, a project and the autonomy NOVA gets. */
export function GoalDialog({ open, onOpenChange, initialTitle = "" }: { open: boolean; onOpenChange: (v: boolean) => void; initialTitle?: string }) {
  const t = useT(M);
  const lang = useLang();
  const router = useRouter();
  const { data: projects } = useProjects();
  const { data: me } = useMe();
  const create = useCreateGoal();
  const [title, setTitle] = useState(initialTitle);
  const [outcome, setOutcome] = useState("");
  const [due, setDue] = useState("");
  const [project, setProject] = useState("");
  const preferred = me?.preferences.default_autonomy;
  const [autonomy, setAutonomy] = useState<GoalAutonomy>(
    preferred && preferred !== "assist" ? (preferred as GoalAutonomy) : "execute_with_approval",
  );
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const goal = await create.mutateAsync({ title, outcome, due_date: due ? new Date(`${due}T18:00:00`).toISOString() : null, project_id: project || null, autonomy, lang });
      onOpenChange(false);
      router.push(`/goals?goal=${goal.id}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("newGoal")} description={t("goalsDescription")} className="max-h-[80vh] overflow-y-auto sm:w-[min(92vw,620px)]">
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="goal-title">{t("goalTitle")}</Label>
            <Input id="goal-title" required minLength={3} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("goalTitlePlaceholder")} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="goal-outcome">{t("outcome")}</Label>
            <Textarea id="goal-outcome" rows={2} value={outcome} onChange={(e) => setOutcome(e.target.value)} placeholder={t("outcomePlaceholder")} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="goal-due">{t("dueDate")}</Label>
              <Input id="goal-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>{t("project")}</Label>
              <Select value={project || "none"} onValueChange={(v) => setProject(v === "none" ? "" : v)} options={[{ value: "none", label: t("noProject") }, ...(projects ?? []).map((p) => ({ value: p.id, label: p.name }))]} className="w-full" ariaLabel={t("project")} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>{t("autonomy")}</Label>
            <AutonomyLevels value={autonomy} onChange={setAutonomy} />
          </div>
          <div className="flex justify-end">
            <Button type="submit" variant="primary" disabled={create.isPending || title.trim().length < 3}>
              {create.isPending ? t("planning") : t("entrust")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
