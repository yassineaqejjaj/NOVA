"use client";

import { useMemo } from "react";

import { type CatalogNames, systemLabel } from "@/components/conversation/blocks.messages";
import { useArtifactTypes, useSkills } from "@/lib/api/hooks";
import type { ArtifactTypeDef, SectionDefinition, SkillDetail, SkillSummary } from "@/lib/api/types";

import { type Lang, useLang } from "./index";

/** Localized display names for catalog objects (Skills, Artifact types, sections). Falls back to English. */
export function skillName(skill: Pick<SkillSummary, "name" | "translations">, lang: Lang): string {
  return skill.translations?.[lang]?.name || skill.name;
}

export function skillSummary(skill: Pick<SkillSummary, "summary" | "translations">, lang: Lang): string {
  return skill.translations?.[lang]?.summary || skill.summary;
}

export function skillArtifactTypeName(skill: Pick<SkillSummary, "artifact_type_name" | "translations">, lang: Lang): string | null {
  return skill.translations?.[lang]?.artifact_type_name || skill.artifact_type_name;
}

export function typeName(def: Pick<ArtifactTypeDef, "name" | "translations"> | undefined | null, lang: Lang, fallback = ""): string {
  if (!def) return fallback;
  return def.translations?.[lang]?.name || def.name;
}

export function typeDescription(def: Pick<ArtifactTypeDef, "description" | "translations">, lang: Lang): string {
  return def.translations?.[lang]?.description || def.description;
}

export function sectionTitle(def: Pick<ArtifactTypeDef, "translations"> | undefined | null, section: SectionDefinition, lang: Lang): string {
  return def?.translations?.[lang]?.sections?.[section.key]?.title || section.title;
}

export function sectionDescription(def: Pick<ArtifactTypeDef, "translations"> | undefined | null, section: SectionDefinition, lang: Lang): string {
  return def?.translations?.[lang]?.sections?.[section.key]?.description || section.description;
}

// --- Skill details (translations.<lang>: purpose, method, principles, steps, criteria, checks, inputs) ---------

type Translated = Pick<SkillSummary, "translations">;

export function skillPurpose(skill: Pick<SkillDetail, "purpose" | "translations">, lang: Lang): string {
  return skill.translations?.[lang]?.purpose || skill.purpose;
}

/** Name of the Skill's methodology. */
export function skillMethod(skill: Pick<SkillDetail, "methodology" | "translations">, lang: Lang): string {
  return skill.translations?.[lang]?.method || skill.methodology.name;
}

/** Methodology principles; the translation follows the same order (each missing entry falls back to English). */
export function skillPrinciples(skill: Pick<SkillDetail, "methodology" | "translations">, lang: Lang): string[] {
  const translated = skill.translations?.[lang]?.principles;
  return skill.methodology.principles.map((principle, i) => translated?.[i] || principle);
}

export function skillStepTitle(skill: Translated | undefined | null, stepId: string, fallback: string, lang: Lang): string {
  return skill?.translations?.[lang]?.steps?.[stepId] || fallback;
}

/** Question of an evaluation criterion, by criterion key. */
export function skillCriterion(skill: Translated | undefined | null, key: string, fallback: string, lang: Lang): string {
  return skill?.translations?.[lang]?.criteria?.[key] || fallback;
}

/** Description of a deterministic evaluation check, by its position in evaluation.checks. */
export function skillCheck(skill: Translated | undefined | null, index: number, fallback: string, lang: Lang): string {
  return skill?.translations?.[lang]?.checks?.[index] || fallback;
}

/** Translated description and question of a Skill input (empty when not translated). */
export function skillInput(skill: Translated | undefined | null, name: string, lang: Lang): { description?: string; question?: string } {
  const input = skill?.translations?.[lang]?.inputs?.[name];
  return { description: input?.description || undefined, question: input?.question || undefined };
}

/** A question NOVA asks for a Skill input: the Skill's translated question when known, else the text as asked. */
export function questionText(skills: SkillSummary[] | undefined, q: { key: string; question: string; skill_id?: string | null }, lang: Lang): string {
  if (lang === "en" || !skills) return q.question;
  const owners = q.skill_id ? skills.filter((s) => s.id === q.skill_id) : skills.filter((s) => s.translations?.[lang]?.inputs?.[q.key]);
  if (owners.length !== 1) return q.question;
  const input = skillInput(owners[0], q.key, lang);
  return input.question || input.description || q.question;
}

// --- Names embedded in system text -----------------------------------------------------------------

/** Maps English catalog names (Skill names and step titles, Artifact type names, section titles) to the language. */
export function catalogNames(skills: SkillSummary[] | undefined, types: ArtifactTypeDef[] | undefined, lang: Lang): CatalogNames {
  if (lang === "en") return (name) => name;
  const map = new Map<string, string>();
  const add = (english: string, localized: string | undefined | null) => {
    if (english && localized && !map.has(english)) map.set(english, localized);
  };
  for (const skill of skills ?? []) {
    add(skill.name, skillName(skill, lang));
    for (const step of skill.steps) add(step.title, skill.translations?.[lang]?.steps?.[step.id]);
  }
  for (const def of types ?? []) {
    add(def.name, typeName(def, lang));
    for (const section of def.sections) add(section.title, sectionTitle(def, section, lang));
  }
  return (name) => map.get(name) ?? name;
}

export function useCatalogNames(): CatalogNames {
  const lang = useLang();
  const { data: skills } = useSkills();
  const { data: types } = useArtifactTypes();
  return useMemo(() => catalogNames(skills, types, lang), [skills, types, lang]);
}

/** `systemLabel` bound to the interface language and the catalog names. */
export function useSystemLabel(): (label: string) => string {
  const lang = useLang();
  const names = useCatalogNames();
  return useMemo(() => (label: string) => systemLabel(label, lang, names), [lang, names]);
}

/** Skill referenced by id or by its English name (task lists carry names). */
export function findSkill(skills: SkillSummary[] | undefined, ref: string | null | undefined): SkillSummary | undefined {
  return ref ? skills?.find((s) => s.id === ref || s.name === ref) : undefined;
}

/** Title of a plan step: the localized Skill name when the step is named after its Skill, else its system label. */
export function planStepTitle(step: { title: string; skill_id?: string | null }, skills: SkillSummary[] | undefined, lang: Lang, names?: CatalogNames): string {
  const skill = findSkill(skills, step.skill_id);
  if (skill && step.title === skill.name) return skillName(skill, lang);
  return systemLabel(step.title, lang, names);
}

/**
 * Label of a progress line. Lines of a plan step are keyed "<plan step id>:<skill step id>" and labelled with the
 * English Skill step title: the translated title is used when known, else the system label.
 */
export function stepActivityLabel(
  skills: SkillSummary[] | undefined,
  planSteps: { id: string; skill_id?: string | null }[] | undefined,
  line: { key: string; label: string },
  lang: Lang,
  names?: CatalogNames,
): string {
  const at = line.key.indexOf(":");
  if (lang !== "en" && at > 0) {
    const stepId = line.key.slice(0, at);
    const subId = line.key.slice(at + 1);
    const planStep = planSteps?.find((s) => s.id === stepId);
    const skill = planStep?.skill_id
      ? findSkill(skills, planStep.skill_id)
      : skills?.find((k) => k.steps.some((st) => st.id === subId && st.title === line.label));
    const title = skill?.translations?.[lang]?.steps?.[subId];
    if (title) return title;
  }
  return systemLabel(line.label, lang, names);
}
