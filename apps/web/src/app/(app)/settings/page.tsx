"use client";

import { Button, Card, cn, Input, Label, Select, Separator } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { OrbitLink } from "@/components/orbit-link";
import { ORB_PALETTES, type OrbPalette, NovaOrb } from "@/components/shell/nova-orb";
import { Page, PageHeader } from "@/components/shell/page";
import { api } from "@/lib/api/client";
import { keys, useMe } from "@/lib/api/hooks";
import type { AutonomyMode, OrbState, Preferences } from "@/lib/api/types";
import { autonomyOptions } from "@/lib/autonomy";
import { defineMessages, type Lang, LANGS, translate, useLang, useT } from "@/lib/i18n";
import { useUi } from "@/stores/ui";

const M = defineMessages({
  en: {
    title: "Settings",
    yourNova: "Your NOVA",
    yourNovaHint: "Personalization never overrides company policies or permissions.",
    name: "Name",
    role: "Your role",
    tone: "Tone",
    tonePlaceholder: "clear and concise",
    methods: "Preferred methods",
    format: "Artifact format",
    structured: "Structured",
    concise: "Concise",
    detailed: "Detailed",
    autonomy: "Default autonomy",
    save: "Save",
    saved: "Saved.",
    orbitHint: "NOVA retrieves context from ORBIT as you, so it only sees what you can see.",
    language: "Language",
    languageHint: "Interface language. NOVA answers in the language you write in.",
    languageSaved: "Language updated.",
    orb: "NOVA’s orb",
    orbHint: "The orb is NOVA’s presence: its color is yours, its motion shows what NOVA is doing.",
    orbSaved: "Orb color updated.",
    preview: "Preview",
    appearance: "Appearance",
    dark: "Dark",
    light: "Light",
    signedInAs: "Signed in as {email}",
    signOut: "Sign out",
    coral: "Coral",
    rose: "Rose",
    violet: "Violet",
    ocean: "Ocean",
    emerald: "Emerald",
    amber: "Amber",
    graphite: "Graphite",
    s_idle: "Ready",
    s_thinking: "Thinking",
    s_working: "Working",
    s_waiting: "Waiting for you",
  },
  fr: {
    title: "Paramètres",
    yourNova: "Votre NOVA",
    yourNovaHint: "La personnalisation ne remplace jamais les politiques ni les permissions de l’entreprise.",
    name: "Nom",
    role: "Votre rôle",
    tone: "Ton",
    tonePlaceholder: "clair et concis",
    methods: "Méthodes préférées",
    format: "Format des artefacts",
    structured: "Structuré",
    concise: "Concis",
    detailed: "Détaillé",
    autonomy: "Autonomie par défaut",
    save: "Enregistrer",
    saved: "Enregistré.",
    orbitHint: "NOVA récupère le contexte d’ORBIT en votre nom : il ne voit que ce que vous pouvez voir.",
    language: "Langue",
    languageHint: "Langue de l’interface. NOVA répond dans la langue dans laquelle vous écrivez.",
    languageSaved: "Langue mise à jour.",
    orb: "L’orbe de NOVA",
    orbHint: "L’orbe incarne NOVA : sa couleur est la vôtre, son mouvement montre ce que fait NOVA.",
    orbSaved: "Couleur de l’orbe mise à jour.",
    preview: "Aperçu",
    appearance: "Apparence",
    dark: "Sombre",
    light: "Clair",
    signedInAs: "Connecté en tant que {email}",
    signOut: "Se déconnecter",
    coral: "Corail",
    rose: "Rose",
    violet: "Violet",
    ocean: "Océan",
    emerald: "Émeraude",
    amber: "Ambre",
    graphite: "Graphite",
    s_idle: "Prêt",
    s_thinking: "Réfléchit",
    s_working: "Travaille",
    s_waiting: "Vous attend",
  },
});

const PREVIEW_STATES: OrbState[] = ["idle", "thinking", "working", "waiting"];

export default function SettingsPage() {
  const t = useT(M);
  const lang = useLang();
  const { data: me } = useMe();
  const client = useQueryClient();
  const theme = useUi((s) => s.theme);
  const setTheme = useUi((s) => s.setTheme);
  const setLang = useUi((s) => s.setLang);
  const orbColor = useUi((s) => s.orbColor);
  const setOrbColor = useUi((s) => s.setOrbColor);
  const [previewState, setPreviewState] = useState<OrbState>("idle");
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  useEffect(() => {
    if (me) setPrefs(me.preferences);
  }, [me]);

  const save = useMutation({
    mutationFn: () => api.patch("/me/preferences", { ...prefs, onboarding_completed: undefined }),
    onSuccess: () => {
      toast(t("saved"));
      void client.invalidateQueries({ queryKey: keys.me });
    },
  });
  // Language and orb color apply instantly and are saved to the profile (they follow the user across devices).
  const savePreference = useMutation({
    mutationFn: (patch: Partial<Preferences>) => api.patch("/me/preferences", patch),
    onSuccess: () => void client.invalidateQueries({ queryKey: keys.me }),
  });
  const chooseLang = (value: Lang) => {
    setLang(value);
    savePreference.mutate({ language: value }, { onSuccess: () => toast(translate(M, value, "languageSaved")) });
  };
  const chooseOrb = (value: OrbPalette) => {
    setOrbColor(value);
    savePreference.mutate({ orb_color: value }, { onSuccess: () => toast(t("orbSaved")) });
  };
  const logout = async () => {
    const r = await api.post<{ redirect: string | null }>("/auth/logout");
    window.location.href = r.redirect ?? "/login";
  };
  if (!me || !prefs) return null;
  const set = (patch: Partial<Preferences>) => setPrefs({ ...prefs, ...patch });

  return (
    <Page>
      <PageHeader title={t("title")} />

      <Card className="p-5">
        <h2 className="text-[15px] font-semibold">{t("orb")}</h2>
        <p className="mt-0.5 text-[13px] text-muted">{t("orbHint")}</p>
        <div className="mt-5 flex flex-col gap-6 sm:flex-row sm:items-center">
          <div className="flex flex-col items-center gap-3 rounded-[20px] bg-surface-2/70 px-8 py-6">
            <NovaOrb state={previewState} size={84} reflection title={t("preview")} />
            <div className="mt-2 flex gap-1" role="group" aria-label={t("preview")}>
              {PREVIEW_STATES.map((s) => (
                <button
                  key={s}
                  onClick={() => setPreviewState(s)}
                  aria-pressed={previewState === s}
                  className={cn("rounded-full px-2.5 py-1 text-[11.5px]", previewState === s ? "bg-surface text-text shadow-sm" : "text-subtle hover:text-text")}
                >
                  {t(`s_${s}` as "s_idle")}
                </button>
              ))}
            </div>
          </div>
          <div role="radiogroup" aria-label={t("orb")} className="grid flex-1 grid-cols-4 gap-3 sm:grid-cols-7">
            {(Object.keys(ORB_PALETTES) as OrbPalette[]).map((key) => {
              const active = orbColor === key;
              return (
                <button
                  key={key}
                  role="radio"
                  aria-checked={active}
                  aria-label={t(key)}
                  onClick={() => chooseOrb(key)}
                  className={cn("group flex flex-col items-center gap-1.5 rounded-[14px] p-2 transition-colors", active ? "bg-surface-2" : "hover:bg-surface-2/60")}
                >
                  <span className={cn("relative rounded-full p-0.5 ring-2 transition-[box-shadow]", active ? "ring-text/70" : "ring-transparent")}>
                    <NovaOrb color={key} size={36} />
                    {active ? (
                      <span className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-text text-background">
                        <Check className="size-2.5" />
                      </span>
                    ) : null}
                  </span>
                  <span className={cn("text-[12px]", active ? "font-medium text-text" : "text-muted")}>{t(key)}</span>
                </button>
              );
            })}
          </div>
        </div>
      </Card>

      <Card className="mt-6 p-5">
        <h2 className="text-[15px] font-semibold">{t("language")}</h2>
        <p className="mt-0.5 text-[13px] text-muted">{t("languageHint")}</p>
        <div role="radiogroup" aria-label={t("language")} className="mt-4 flex gap-2">
          {LANGS.map((l) => (
            <Button key={l.value} role="radio" aria-checked={lang === l.value} size="sm" variant={lang === l.value ? "primary" : "secondary"} onClick={() => chooseLang(l.value)}>
              {l.label}
            </Button>
          ))}
        </div>
      </Card>

      <Card className="mt-6 p-5">
        <h2 className="text-[15px] font-semibold">{t("yourNova")}</h2>
        <p className="mt-0.5 text-[13px] text-muted">{t("yourNovaHint")}</p>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5"><Label htmlFor="nova-name">{t("name")}</Label><Input id="nova-name" value={prefs.nova_name} onChange={(e) => set({ nova_name: e.target.value })} /></div>
          <div className="space-y-1.5"><Label htmlFor="role">{t("role")}</Label><Input id="role" value={prefs.role ?? ""} onChange={(e) => set({ role: e.target.value })} /></div>
          <div className="space-y-1.5"><Label htmlFor="tone">{t("tone")}</Label><Input id="tone" value={prefs.tone ?? ""} onChange={(e) => set({ tone: e.target.value })} placeholder={t("tonePlaceholder")} /></div>
          <div className="space-y-1.5"><Label htmlFor="methods">{t("methods")}</Label><Input id="methods" value={(prefs.preferred_methods ?? []).join(", ")} onChange={(e) => set({ preferred_methods: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} placeholder="RICE, Jobs To Be Done" /></div>
          <div className="space-y-1.5"><Label>{t("format")}</Label><Select value={prefs.artifact_format ?? "structured"} onValueChange={(v) => set({ artifact_format: v })} options={[{ value: "structured", label: t("structured") }, { value: "concise", label: t("concise") }, { value: "detailed", label: t("detailed") }]} className="w-full" /></div>
          <div className="space-y-1.5"><Label>{t("autonomy")}</Label><Select value={prefs.default_autonomy ?? "assist"} onValueChange={(v) => set({ default_autonomy: v as AutonomyMode })} options={autonomyOptions(lang)} className="w-full" /></div>
        </div>
        <div className="mt-5 flex justify-end"><Button variant="primary" size="sm" onClick={() => save.mutate()} disabled={save.isPending}>{t("save")}</Button></div>
      </Card>

      <Card id="orbit" className="mt-6 scroll-mt-10 p-5">
        <h2 className="text-[15px] font-semibold">ORBIT</h2>
        <p className="mb-4 mt-0.5 text-[13px] text-muted">{t("orbitHint")}</p>
        <OrbitLink identity={me.orbit} />
      </Card>

      <Card className="mt-6 p-5">
        <h2 className="text-[15px] font-semibold">{t("appearance")}</h2>
        <div className="mt-3 flex gap-2">
          <Button size="sm" variant={theme === "dark" ? "primary" : "secondary"} onClick={() => setTheme("dark")}>{t("dark")}</Button>
          <Button size="sm" variant={theme === "light" ? "primary" : "secondary"} onClick={() => setTheme("light")}>{t("light")}</Button>
        </div>
        <Separator className="my-5" />
        <div className="flex items-center text-[13px] text-muted">
          {t("signedInAs", { email: me.email })}
          <Button variant="ghost" size="sm" className="ml-auto" onClick={() => void logout()}>{t("signOut")}</Button>
        </div>
      </Card>
    </Page>
  );
}
