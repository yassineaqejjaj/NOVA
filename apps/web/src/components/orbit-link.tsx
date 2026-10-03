"use client";

import { Button, Input, Label } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "@/lib/api/client";
import type { OrbitIdentity } from "@/lib/api/types";

/** Link ORBIT: the password is sent once to obtain an ORBIT session; NOVA never stores it. */
export function OrbitLink({ identity, onLinked }: { identity?: OrbitIdentity; onLinked?: () => void }) {
  const client = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const link = useMutation({
    mutationFn: () => api.post<{ projects_synced: number }>("/me/orbit", { email, password }),
    onSuccess: (r) => {
      setPassword("");
      toast(`ORBIT connected · ${r.projects_synced} project(s) available.`);
      void client.invalidateQueries();
      onLinked?.();
    },
  });
  const unlink = useMutation({ mutationFn: () => api.delete("/me/orbit"), onSuccess: () => void client.invalidateQueries() });

  if (identity?.linked) {
    return (
      <div className="flex items-center gap-3 text-[13.5px]">
        <span className="size-2 rounded-full bg-success" /> Connected as {identity.display_name || identity.email}
        <Button variant="ghost" size="sm" className="ml-auto" onClick={() => unlink.mutate()}>Disconnect</Button>
      </div>
    );
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); link.mutate(); }} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5"><Label htmlFor="orbit-email">ORBIT email</Label><Input id="orbit-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" /></div>
        <div className="space-y-1.5"><Label htmlFor="orbit-password">ORBIT password</Label><Input id="orbit-password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></div>
      </div>
      {link.error instanceof ApiError ? <p className="text-[13px] text-danger">{link.error.message}</p> : null}
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" size="sm" disabled={link.isPending}>Connect ORBIT</Button>
        <span className="text-[12px] text-subtle">Used once to open an ORBIT session. Your password is not stored.</span>
      </div>
    </form>
  );
}
