"use client";

import { Button } from "@nova/ui";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { M } from "@/components/auth/auth.messages";
import { LanguageSwitch, Planet } from "@/components/auth/auth-ui";
import { NovaLogo } from "@/components/shell/nova-mark";
import { api } from "@/lib/api/client";
import { useT } from "@/lib/i18n";

/** Logout confirmation: NOVA's planet above the horizon. */
export default function LogoutPage() {
  const t = useT(M);
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const logout = async () => {
    setPending(true);
    try {
      const r = await api.post<{ redirect: string | null }>("/auth/logout");
      window.location.href = r.redirect ?? "/";
    } catch {
      window.location.href = "/";
    }
  };
  return (
    <div className="relative isolate flex min-h-dvh flex-col items-center overflow-hidden bg-[#07070b] px-4 font-[family-name:var(--font-montserrat)] text-white">
      <div className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_50%_30%,rgb(248_72_94/0.16),transparent_55%)]" />
      {/* horizon */}
      <div className="absolute left-1/2 top-[80vh] -z-10 h-[220vw] w-[220vw] -translate-x-1/2 rounded-full bg-[#0c0c13] shadow-[0_-40px_140px_-30px_rgb(248_72_94/0.7)] ring-1 ring-[#f8485e]/50 sm:h-[160vw] sm:w-[160vw]" />
      <div className="absolute right-4 top-4"><LanguageSwitch /></div>
      <div className="mt-[10vh] flex w-full max-w-[360px] flex-col items-center text-center">
        <NovaLogo height={26} className="brightness-0 invert" />
        <Planet size={170} className="mt-6" />
        <h1 className="mt-4 text-[30px] font-medium tracking-tight">{t("loggingOut")}</h1>
        <p className="mt-2 text-[15px] text-white/70">{t("logoutQuestion")}</p>
        <div className="mt-8 w-full space-y-3">
          <Button variant="primary" size="lg" className="h-12 w-full rounded-[12px] text-[15px]" onClick={logout} disabled={pending}>
            {pending ? t("loggedOutWait") : t("logout")}
          </Button>
          <button type="button" className="h-12 w-full rounded-[12px] border border-white/25 text-[15px] font-medium text-white transition-colors hover:bg-white/10 disabled:opacity-50" onClick={() => (window.history.length > 1 ? router.back() : router.replace("/"))} disabled={pending}>
            {t("cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}
