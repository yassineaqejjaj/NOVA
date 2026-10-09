"use client";

import { Button, Card, cn, Input, Label, Select, Separator } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { ProfilePicker } from "@/components/agents/profile-picker";
import { GithubLink } from "@/components/engineering/github-link";
import { LlmSettings } from "@/components/engineering/llm-settings";
import { M as EM } from "@/components/engineering/engineering.messages";
import { PermissionsCard } from "@/components/missions/permissions";
import { FigmaLink } from "@/components/figma-link";
import { OrbitLink } from "@/components/orbit-link";
import { ORB_PALETTES, type OrbPalette, NovaOrb } from "@/components/shell/nova-orb";
import { Page, PageHeader } from "@/components/shell/page";
import { api } from "@/lib/api/client";
import { keys, useMe } from "@/lib/api/hooks";
import type { OrbState, Preferences } from "@/lib/api/types";
import { agentOf, type AgentProfile } from "@/lib/agents";
import { defineMessages, type Lang, LANGS, translate, useLang, useT } from "@/lib/i18n";
import { useUi } from "@/stores/ui";

const M = defineMessages({
  en: {
    title: "Settings",
    description: "Make NOVA yours, choose its model, and connect the tools it works with.",
    sections: "Settings sections",
    nav_profile: "Profile",
    nav_appearance: "Appearance",
    nav_autonomy: "Autonomy",
    nav_llm: "AI model",
    nav_integrations: "Integrations",
    nav_account: "Account",
    profileSection: "Profile",
    profileSectionHint: "Who you are and how NOVA works with you.",
    appearanceSection: "Appearance",
    appearanceSectionHint: "Language, theme and NOVA’s orb.",
    autonomySection: "Autonomy and permissions",
    autonomySectionHint: "What NOVA may do alone, what needs your approval, and what it never does.",
    llmSection: "AI model",
    llmSectionHint: "The model behind NOVA’s conversations and code work.",
    integrationsSection: "Integrations",
    integrationsSectionHint: "Connect the knowledge and tools NOVA acts with. Credentials are stored encrypted.",
    accountSection: "Account",
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
    figmaHint: "Lets NOVA read your Figma designs to generate code and audits, and push mockups to Figma when connected with Figma.",
    orbitHint: "NOVA retrieves context from ORBIT as you, so it only sees what you can see.",
    profile: "Your profile",
    profileHint: "The specialist agent of your profile leads your work; NOVA brings in the others when a task needs them.",
    profileSaved: "Profile updated.",
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
    s_clarification: "Needs clarification",
    s_completed: "Completed",
  },
  fr: {
    title: "Paramètres",
    description: "Personnalisez NOVA, choisissez son modèle et connectez les outils avec lesquels il travaille.",
    sections: "Rubriques des paramètres",
    nav_profile: "Profil",
    nav_appearance: "Apparence",
    nav_autonomy: "Autonomie",
    nav_llm: "Modèle d’IA",
    nav_integrations: "Intégrations",
    nav_account: "Compte",
    profileSection: "Profil",
    profileSectionHint: "Qui vous êtes et comment NOVA travaille avec vous.",
    appearanceSection: "Apparence",
    appearanceSectionHint: "Langue, thème et orbe de NOVA.",
    autonomySection: "Autonomie et permissions",
    autonomySectionHint: "Ce que NOVA peut faire seul, ce qui demande votre accord, et ce qu’il ne fait jamais.",
    llmSection: "Modèle d’IA",
    llmSectionHint: "Le modèle derrière les conversations et le travail de code de NOVA.",
    integrationsSection: "Intégrations",
    integrationsSectionHint: "Connectez les connaissances et les outils avec lesquels NOVA agit. Les identifiants sont stockés chiffrés.",
    accountSection: "Compte",
    yourNova: "Votre NOVA",
    yourNovaHint: "La personnalisation ne remplace jamais les politiques ni les permissions de l’entreprise.",
    name: "Nom",
    role: "Votre rôle",
    tone: "Ton",
    tonePlaceholder: "clair et concis",
    methods: "Méthodes préférées",
    format: "Format des Artefacts",
    structured: "Structuré",
    concise: "Concis",
    detailed: "Détaillé",
    autonomy: "Autonomie par défaut",
    save: "Enregistrer",
    saved: "Enregistré.",
    figmaHint: "Permet à NOVA de lire vos maquettes Figma pour générer du code et des audits, et d’y pousser des maquettes lorsque la connexion se fait avec Figma.",
    orbitHint: "NOVA récupère le contexte d’ORBIT en votre nom : il ne voit que ce que vous pouvez voir.",
    profile: "Votre profil",
    profileHint: "L’agent spécialiste de votre profil pilote votre travail ; NOVA fait intervenir les autres quand une tâche le demande.",
    profileSaved: "Profil mis à jour.",
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
    s_clarification: "Besoin d’une précision",
    s_completed: "Terminé",
  },
});

const PREVIEW_STATES: OrbState[] = ["idle", "thinking", "working", "waiting", "clarification", "completed"];

export default function SettingsPage() {
  const router = useRouter();
  const t = useT(M);
  const te = useT(EM);
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
    // Only this card's fields: autonomy, permissions, language, orb and profile are saved where they are edited.
    mutationFn: () =>
      api.patch("/me/preferences", {
        nova_name: prefs?.nova_name,
        role: prefs?.role,
        tone: prefs?.tone,
        preferred_methods: prefs?.preferred_methods,
        artifact_format: prefs?.artifact_format,
      }),
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
  const chooseProfile = (value: AgentProfile) => {
    setPrefs((current) => (current ? { ...current, profile: value } : current));
    savePreference.mutate({ profile: value }, { onSuccess: () => toast(t("profileSaved")) });
  };
  const logout = () => router.push("/logout"); // confirmation screen
  if (!me || !prefs) return null;
  const set = (patch: Partial<Preferences>) => setPrefs({ ...prefs, ...patch });

  const sections = [
    { id: "profile", label: t("nav_profile") },
    { id: "appearance", label: t("nav_appearance") },
    { id: "autonomy", label: t("nav_autonomy") },
    { id: "ai-model", label: t("nav_llm") },
    { id: "integrations", label: t("nav_integrations") },
    { id: "account", label: t("nav_account") },
  ];

  return (
    <Page wide>
      <PageHeader title={t("title")} description={t("description")} />

      <div className="md:grid md:grid-cols-[190px_minmax(0,1fr)] md:gap-10">
        <SettingsNav items={sections} label={t("sections")} />

        <div className="min-w-0 space-y-14">
          <Section id="profile" title={t("profileSection")} hint={t("profileSectionHint")}>
            <Card className="p-5">
              <h3 className="text-[15px] font-semibold">{t("profile")}</h3>
              <p className="mt-0.5 text-[13px] text-muted">{t("profileHint")}</p>
              <div className="mt-4"><ProfilePicker value={agentOf(prefs.profile)} onChange={chooseProfile} /></div>
            </Card>

            <Card className="p-5">
              <h3 className="text-[15px] font-semibold">{t("yourNova")}</h3>
              <p className="mt-0.5 text-[13px] text-muted">{t("yourNovaHint")}</p>
              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5"><Label htmlFor="nova-name">{t("name")}</Label><Input id="nova-name" value={prefs.nova_name} onChange={(e) => set({ nova_name: e.target.value })} /></div>
                <div className="space-y-1.5"><Label htmlFor="role">{t("role")}</Label><Input id="role" value={prefs.role ?? ""} onChange={(e) => set({ role: e.target.value })} /></div>
                <div className="space-y-1.5"><Label htmlFor="tone">{t("tone")}</Label><Input id="tone" value={prefs.tone ?? ""} onChange={(e) => set({ tone: e.target.value })} placeholder={t("tonePlaceholder")} /></div>
                <div className="space-y-1.5"><Label htmlFor="methods">{t("methods")}</Label><Input id="methods" value={(prefs.preferred_methods ?? []).join(", ")} onChange={(e) => set({ preferred_methods: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} placeholder="RICE, Jobs To Be Done" /></div>
                <div className="space-y-1.5"><Label>{t("format")}</Label><Select value={prefs.artifact_format ?? "structured"} onValueChange={(v) => set({ artifact_format: v })} options={[{ value: "structured", label: t("structured") }, { value: "concise", label: t("concise") }, { value: "detailed", label: t("detailed") }]} className="w-full" /></div>
              </div>
              <div className="mt-5 flex justify-end"><Button variant="primary" size="sm" onClick={() => save.mutate()} disabled={save.isPending}>{t("save")}</Button></div>
            </Card>
          </Section>

          <Section id="appearance" title={t("appearanceSection")} hint={t("appearanceSectionHint")}>
            <Card className="p-5">
              <h3 className="text-[15px] font-semibold">{t("language")}</h3>
              <p className="mt-0.5 text-[13px] text-muted">{t("languageHint")}</p>
              <div role="radiogroup" aria-label={t("language")} className="mt-4 flex gap-2">
                {LANGS.map((l) => (
                  <Button key={l.value} role="radio" aria-checked={lang === l.value} size="sm" variant={lang === l.value ? "primary" : "secondary"} onClick={() => chooseLang(l.value)}>
                    {l.label}
                  </Button>
                ))}
              </div>
              <Separator className="my-5" />
              <h3 className="text-[15px] font-semibold">{t("appearance")}</h3>
              <div className="mt-3 flex gap-2">
                <Button size="sm" variant={theme === "dark" ? "primary" : "secondary"} onClick={() => setTheme("dark")}>{t("dark")}</Button>
                <Button size="sm" variant={theme === "light" ? "primary" : "secondary"} onClick={() => setTheme("light")}>{t("light")}</Button>
              </div>
            </Card>

            <Card className="p-5">
              <h3 className="text-[15px] font-semibold">{t("orb")}</h3>
              <p className="mt-0.5 text-[13px] text-muted">{t("orbHint")}</p>
              <div className="mt-5 flex flex-col gap-6 sm:flex-row sm:items-center">
                <div className="flex flex-col items-center gap-3 rounded-[20px] bg-surface-2/70 px-8 py-6">
                  <NovaOrb state={previewState} size={84} reflection title={t("preview")} />
                  <div className="mt-2 flex max-w-[260px] flex-wrap justify-center gap-1" role="group" aria-label={t("preview")}>
                    {PREVIEW_STATES.map((s) => (
                      <button
                        key={s}
                        onClick={() => {
                          // "Completed" is a live transition: replay it from a calm orb.
                          if (s === "completed") {
                            setPreviewState("idle");
                            setTimeout(() => setPreviewState("completed"), 80);
                          } else setPreviewState(s);
                        }}
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
                          <NovaOrb color={key} size={36} state="completed" />
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
          </Section>

          <Section id="autonomy" title={t("autonomySection")} hint={t("autonomySectionHint")}>
            <PermissionsCard />
          </Section>

          <Section id="ai-model" title={t("llmSection")} hint={t("llmSectionHint")}>
            <Card id="llm" className="scroll-mt-10 p-5">
              <h3 className="text-[15px] font-semibold">{te("llmTitle")}</h3>
              <p className="mb-4 mt-0.5 text-[13px] text-muted">{te("llmHint")}</p>
              <LlmSettings />
            </Card>
          </Section>

          <Section id="integrations" title={t("integrationsSection")} hint={t("integrationsSectionHint")}>
            <Card id="orbit" className="scroll-mt-10 p-5">
              <h3 className="text-[15px] font-semibold">ORBIT</h3>
              <p className="mb-4 mt-0.5 text-[13px] text-muted">{t("orbitHint")}</p>
              <OrbitLink identity={me.orbit} />
            </Card>
            <Card id="github" className="scroll-mt-10 p-5">
              <h3 className="text-[15px] font-semibold">{te("ghTitle")}</h3>
              <p className="mb-4 mt-0.5 text-[13px] text-muted">{te("ghHint")}</p>
              <GithubLink />
            </Card>
            <Card id="figma" className="scroll-mt-10 p-5">
              <h3 className="text-[15px] font-semibold">Figma</h3>
              <p className="mb-4 mt-0.5 text-[13px] text-muted">{t("figmaHint")}</p>
              <FigmaLink />
            </Card>
          </Section>

          <Section id="account" title={t("accountSection")}>
            <Card className="flex items-center p-5 text-[13px] text-muted">
              {t("signedInAs", { email: me.email })}
              <Button variant="ghost" size="sm" className="ml-auto" onClick={() => void logout()}>{t("signOut")}</Button>
            </Card>
          </Section>
        </div>
      </div>
    </Page>
  );
}

function Section({ id, title, hint, children }: { id: string; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-24">
      <header className="mb-4">
        <h2 id={`${id}-title`} className="text-[19px] font-semibold tracking-tight">{title}</h2>
        {hint ? <p className="mt-0.5 text-[13px] text-muted">{hint}</p> : null}
      </header>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

/** Section navigation: a sticky column on desktop, a sticky scrolling bar on phones. The current section follows the scroll. */
function SettingsNav({ items, label }: { items: { id: string; label: string }[]; label: string }) {
  const [active, setActive] = useState(items[0]!.id);
  useEffect(() => {
    const nodes = items.map((i) => document.getElementById(i.id)).filter((n): n is HTMLElement => !!n);
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (visible) setActive(visible.target.id);
      },
      { rootMargin: "-10% 0px -75% 0px" },
    );
    nodes.forEach((n) => observer.observe(n));
    return () => observer.disconnect();
  }, [items]);
  return (
    <nav aria-label={label} className="sticky top-0 z-10 -mx-5 mb-6 overflow-x-auto bg-background/90 px-5 py-2 backdrop-blur md:static md:mx-0 md:mb-0 md:overflow-visible md:bg-transparent md:p-0 md:backdrop-blur-none">
      <ul className="flex gap-1 md:sticky md:top-10 md:flex-col">
        {items.map((item) => (
          <li key={item.id} className="shrink-0">
            <a
              href={`#${item.id}`}
              aria-current={active === item.id ? "location" : undefined}
              onClick={() => setActive(item.id)}
              className={cn(
                "block rounded-[10px] px-3 py-1.5 text-[13.5px] transition-colors",
                active === item.id ? "bg-surface-2 font-medium text-text" : "text-muted hover:bg-surface-2/60 hover:text-text",
              )}
            >
              {item.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
