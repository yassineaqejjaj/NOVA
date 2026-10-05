"use client";

import { Button, Input, Label } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api/client";
import type { OrbitIdentity } from "@/lib/api/types";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    connected: (v: { n: number }) => `ORBIT connected · ${v.n} project(s) available.`,
    connectedAs: "Connected as {name}",
    disconnect: "Disconnect",
    email: "ORBIT email",
    password: "ORBIT password",
    connect: "Connect ORBIT",
    passwordNotice: "Used once to open an ORBIT session. Your password is not stored.",
  },
  fr: {
    connected: (v: { n: number }) => `ORBIT connecté · ${v.n} projet${v.n > 1 ? "s" : ""} disponible${v.n > 1 ? "s" : ""}.`,
    connectedAs: "Connecté en tant que {name}",
    disconnect: "Déconnecter",
    email: "E-mail ORBIT",
    password: "Mot de passe ORBIT",
    connect: "Connecter ORBIT",
    passwordNotice: "Utilisé une seule fois pour ouvrir une session ORBIT. Votre mot de passe n’est pas conservé.",
  },
});

/** Link ORBIT: the password is sent once to obtain an ORBIT session; NOVA never stores it. */
export function OrbitLink({ identity, onLinked }: { identity?: OrbitIdentity; onLinked?: () => void }) {
  const client = useQueryClient();
  const t = useT(M);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const link = useMutation({
    mutationFn: () => api.post<{ projects_synced: number }>("/me/orbit", { email, password }),
    onSuccess: (r) => {
      setPassword("");
      toast(t("connected", { n: r.projects_synced }));
      void client.invalidateQueries();
      onLinked?.();
    },
  });
  const unlink = useMutation({ mutationFn: () => api.delete("/me/orbit"), onSuccess: () => void client.invalidateQueries() });

  if (identity?.linked) {
    return (
      <div className="flex items-center gap-3 text-[13.5px]">
        <span className="size-2 rounded-full bg-success" /> {t("connectedAs", { name: identity.display_name || identity.email })}
        <Button variant="ghost" size="sm" className="ml-auto" onClick={() => unlink.mutate()}>{t("disconnect")}</Button>
      </div>
    );
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); link.mutate(); }} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5"><Label htmlFor="orbit-email">{t("email")}</Label><Input id="orbit-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" /></div>
        <div className="space-y-1.5"><Label htmlFor="orbit-password">{t("password")}</Label><Input id="orbit-password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></div>
      </div>
      {link.error instanceof ApiError ? <p className="text-[13px] text-danger">{link.error.message}</p> : null}
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" size="sm" disabled={link.isPending}>{t("connect")}</Button>
        <span className="text-[12px] text-subtle">{t("passwordNotice")}</span>
      </div>
    </form>
  );
}
