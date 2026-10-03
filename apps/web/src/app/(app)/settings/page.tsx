"use client";

import { Button, Card, Input, Label, Select, Separator } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { OrbitLink } from "@/components/orbit-link";
import { Page, PageHeader } from "@/components/shell/page";
import { api } from "@/lib/api/client";
import { keys, useMe } from "@/lib/api/hooks";
import type { AutonomyMode, Preferences } from "@/lib/api/types";
import { AUTONOMY } from "@/lib/autonomy";
import { useUi } from "@/stores/ui";


export default function SettingsPage() {
  const { data: me } = useMe();
  const client = useQueryClient();
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  useEffect(() => { if (me) setPrefs(me.preferences); }, [me]);
  const save = useMutation({
    mutationFn: () => api.patch("/me/preferences", { ...prefs, onboarding_completed: undefined }),
    onSuccess: () => { toast("Saved."); void client.invalidateQueries({ queryKey: keys.me }); },
  });
  const logout = async () => {
    const r = await api.post<{ redirect: string | null }>("/auth/logout");
    window.location.href = r.redirect ?? "/login";
  };
  if (!me || !prefs) return null;
  const set = (patch: Partial<Preferences>) => setPrefs({ ...prefs, ...patch });

  return (
    <Page>
      <PageHeader title="Settings" />
      <Card className="p-5">
        <h2 className="text-[15px] font-semibold">Your NOVA</h2>
        <p className="mt-0.5 text-[13px] text-muted">Personalization never overrides company policies or permissions.</p>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5"><Label htmlFor="nova-name">Name</Label><Input id="nova-name" value={prefs.nova_name} onChange={(e) => set({ nova_name: e.target.value })} /></div>
          <div className="space-y-1.5"><Label htmlFor="role">Your role</Label><Input id="role" value={prefs.role ?? ""} onChange={(e) => set({ role: e.target.value })} /></div>
          <div className="space-y-1.5"><Label htmlFor="tone">Tone</Label><Input id="tone" value={prefs.tone ?? ""} onChange={(e) => set({ tone: e.target.value })} placeholder="clear and concise" /></div>
          <div className="space-y-1.5"><Label htmlFor="methods">Preferred methods</Label><Input id="methods" value={(prefs.preferred_methods ?? []).join(", ")} onChange={(e) => set({ preferred_methods: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} placeholder="RICE, Jobs To Be Done" /></div>
          <div className="space-y-1.5"><Label>Artifact format</Label><Select value={prefs.artifact_format ?? "structured"} onValueChange={(v) => set({ artifact_format: v })} options={[{ value: "structured", label: "Structured" }, { value: "concise", label: "Concise" }, { value: "detailed", label: "Detailed" }]} className="w-full" /></div>
          <div className="space-y-1.5"><Label>Default autonomy</Label><Select value={prefs.default_autonomy ?? "assist"} onValueChange={(v) => set({ default_autonomy: v as AutonomyMode })} options={AUTONOMY} className="w-full" /></div>
        </div>
        <div className="mt-5 flex justify-end"><Button variant="primary" size="sm" onClick={() => save.mutate()} disabled={save.isPending}>Save</Button></div>
      </Card>

      <Card id="orbit" className="mt-6 scroll-mt-10 p-5">
        <h2 className="text-[15px] font-semibold">ORBIT</h2>
        <p className="mb-4 mt-0.5 text-[13px] text-muted">NOVA retrieves context from ORBIT as you, so it only sees what you can see.</p>
        <OrbitLink identity={me.orbit} />
      </Card>

      <Card className="mt-6 p-5">
        <h2 className="text-[15px] font-semibold">Appearance</h2>
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant={theme === "dark" ? "primary" : "secondary"} onClick={() => setTheme("dark")}>Dark</Button>
          <Button size="sm" variant={theme === "light" ? "primary" : "secondary"} onClick={() => setTheme("light")}>Light</Button>
        </div>
        <Separator className="my-5" />
        <div className="flex items-center text-[13px] text-muted">
          Signed in as {me.email}
          <Button variant="ghost" size="sm" className="ml-auto" onClick={() => void logout()}>Sign out</Button>
        </div>
      </Card>
    </Page>
  );
}
