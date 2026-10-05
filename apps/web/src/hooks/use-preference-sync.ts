"use client";

import { useEffect } from "react";

import type { Me } from "@/lib/api/types";
import { type OrbColor, useUi } from "@/stores/ui";

/** Applies the user's stored interface preferences (language, orb color) on any device. */
export function usePreferenceSync(me: Me | undefined) {
  const setLang = useUi((s) => s.setLang);
  const setOrbColor = useUi((s) => s.setOrbColor);
  const language = me?.preferences.language;
  const orbColor = me?.preferences.orb_color;
  useEffect(() => {
    if (language === "en" || language === "fr") setLang(language);
  }, [language, setLang]);
  useEffect(() => {
    if (orbColor) setOrbColor(orbColor as OrbColor);
  }, [orbColor, setOrbColor]);
}
