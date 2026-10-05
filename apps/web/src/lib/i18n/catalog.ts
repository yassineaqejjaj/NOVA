"use client";

import type { ArtifactTypeDef, SectionDefinition, SkillSummary } from "@/lib/api/types";

import type { Lang } from "./index";

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
