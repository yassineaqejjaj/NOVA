"use client";

import { Button, Input, Label } from "@nova/ui";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { NovaLogo } from "@/components/shell/nova-mark";
import { api, ApiError } from "@/lib/api/client";

function LoginForm() {
  const params = useSearchParams();
  const next = params.get("next") ?? "/";
  const { data: config } = useQuery({ queryKey: ["auth-config"], queryFn: () => api.get<{ mode: "oidc" | "dev" }>("/auth/config") });
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const devLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.post("/auth/dev-login", { email, name });
      window.location.href = next;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed");
    }
  };

  return (
    <div className="w-[min(92vw,380px)]">
      <div className="mb-8 flex flex-col items-center text-center">
        <NovaLogo height={40} />
        <h1 className="mt-6 text-xl font-semibold tracking-tight">Sign in</h1>
        <p className="mt-1 text-sm text-muted">Your personal AI product agent.</p>
      </div>
      {!config ? null : config.mode === "dev" ? (
        <form onSubmit={devLogin} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="name">Name</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" />
          </div>
          {error ? <p className="text-sm text-danger">{error}</p> : null}
          <Button type="submit" variant="primary" className="w-full">
            Continue
          </Button>
          <p className="text-center text-[12px] text-subtle">Development sign-in. Production uses your company SSO.</p>
        </form>
      ) : (
        <Button variant="primary" className="w-full" onClick={() => (window.location.href = `/api/v1/auth/login?next=${encodeURIComponent(next)}`)}>
          Continue with company SSO
        </Button>
      )}
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Suspense>
        <LoginForm />
      </Suspense>
    </div>
  );
}
