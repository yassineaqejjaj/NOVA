"use client";

import { Button, cn, Tooltip } from "@nova/ui";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Building2, KeyRound, Lock, Mail, User } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { M, ERRORS } from "@/components/auth/auth.messages";
import { AuthShell, Checkbox, CodeInput, Field, GoogleIcon, PasswordField, PasswordRules, passwordRules, Tabs } from "@/components/auth/auth-ui";
import { NovaLogo } from "@/components/shell/nova-mark";
import { api, ApiError } from "@/lib/api/client";
import { translate, useLang, useT } from "@/lib/i18n";

interface AuthConfig {
  mode: "oidc" | "dev";
  /** domains: [] = any address; verification: the account waits for the e-mailed code */
  signup: { enabled: boolean; domains: string[]; verification: boolean };
  password_reset: boolean;
  dev_outbox: boolean;
  providers: { id: string; name: string; available: boolean }[];
}

type Step = "signin" | "signup" | "verify" | "forgot" | "reset";

const fade = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: -6 }, transition: { duration: 0.2 } };

function useAuthConfig() {
  return useQuery({ queryKey: ["auth-config"], queryFn: () => api.get<AuthConfig>("/auth/config"), staleTime: 60_000 });
}

/** The code the development outbox received (no e-mail server outside production). */
function useDevCode(email: string, enabled: boolean, nonce: number) {
  return useQuery({
    queryKey: ["dev-code", email, nonce],
    queryFn: () => api.get<{ code: string | null }>(`/auth/dev/outbox?email=${encodeURIComponent(email)}`),
    enabled: enabled && !!email,
  });
}

function useErrorText(domains: string[]) {
  const lang = useLang();
  const t = useT(M);
  return (err: unknown) => {
    if (err instanceof ApiError && err.code in ERRORS.en) {
      return translate(ERRORS, lang, err.code as keyof typeof ERRORS.en, { domains: domains.map((d) => `@${d}`).join(", ") });
    }
    return err instanceof ApiError ? err.message : t("failed");
  };
}

function Submit({ pending, children }: { pending: boolean; children: React.ReactNode }) {
  return (
    <Button type="submit" variant="primary" size="lg" className="h-[52px] w-full rounded-[10px] text-[16px] font-semibold" disabled={pending}>
      {children} <ArrowRight className="!size-[18px]" />
    </Button>
  );
}

function Notice({ tone = "danger", children }: { tone?: "danger" | "info" | "success"; children: React.ReactNode }) {
  return (
    <p role={tone === "danger" ? "alert" : "status"} className={cn("rounded-[10px] px-3 py-2 text-[13px]", tone === "danger" ? "bg-danger/10 text-danger" : tone === "success" ? "bg-success/10 text-success" : "bg-surface-2 text-muted")}>
      {children}
    </p>
  );
}

function Providers({ config }: { config: AuthConfig }) {
  const t = useT(M);
  return (
    <>
      <div className="my-5 flex items-center gap-4 text-[14px] text-subtle">
        <span className="h-px flex-1 bg-border-strong" />
        {t("orContinue")}
        <span className="h-px flex-1 bg-border-strong" />
      </div>
      {config.providers.map((p) => {
        const button = (
          <button
            type="button"
            disabled={!p.available}
            aria-disabled={!p.available}
            className="relative flex h-[52px] w-full items-center justify-center gap-3 rounded-[10px] border border-border-strong bg-surface text-[15px] text-text transition-colors enabled:hover:bg-surface-2 disabled:cursor-not-allowed"
          >
            <GoogleIcon className="size-5" />
            <span>
              {t("continueWith")} <span className="font-semibold">{p.name}</span>
            </span>
            {!p.available ? (
              <span className="absolute right-3 rounded-full bg-violet-500/12 px-2.5 py-0.5 text-[12px] font-medium text-violet-600 dark:text-violet-300">{t("soon")}</span>
            ) : null}
          </button>
        );
        return p.available ? (
          <div key={p.id}>{button}</div>
        ) : (
          <Tooltip key={p.id} content={t("googleSoon")}>
            <span className="block">{button}</span>
          </Tooltip>
        );
      })}
    </>
  );
}

function SignIn({ config, next, onForgot, onUnverified, notice }: { config: AuthConfig; next: string; onForgot: (email: string) => void; onUnverified: (email: string) => void; notice: string | null }) {
  const t = useT(M);
  const errorText = useErrorText(config.signup.domains);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      await api.post("/auth/password-login", { email, password, remember });
      window.location.href = next;
    } catch (err) {
      if (err instanceof ApiError && err.code === "email_not_verified") return onUnverified(email);
      setError(errorText(err));
      setPending(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-5" aria-label={t("signIn")}>
      {notice ? <Notice tone="success">{notice}</Notice> : null}
      <Field icon={Mail} label={t("workEmail")} type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder={t("emailPlaceholder")} />
      <PasswordField icon={Lock} label={t("password")} value={password} onChange={setPassword} autoComplete="current-password" />
      <div className="flex items-center justify-between gap-3 pt-0.5">
        <Checkbox checked={remember} onChange={setRemember}>{t("keepSignedIn")}</Checkbox>
        {config.password_reset ? (
          <button type="button" onClick={() => onForgot(email)} className="text-[13px] text-accent underline-offset-4 hover:underline">{t("forgot")}</button>
        ) : null}
      </div>
      {error ? <Notice>{error}</Notice> : null}
      <Submit pending={pending}>{t("signIn")}</Submit>
      <Providers config={config} />
    </form>
  );
}

function companyOf(email: string, domains: string[]): string {
  const domain = email.split("@")[1]?.toLowerCase() ?? "";
  if (!domains.includes(domain)) return "";
  const name = domain.split(".")[0] ?? "";
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function SignUp({ config, onSent }: { config: AuthConfig; onSent: (email: string) => void }) {
  const t = useT(M);
  const lang = useLang();
  const router = useRouter();
  const anyDomain = config.signup.domains.length === 0;
  const errorText = useErrorText(config.signup.domains);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [accept, setAccept] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const domains = config.signup.domains.map((d) => `@${d}`).join(", ");
  const rules = passwordRules(password);
  const ready = rules.length && rules.letters && rules.digits && accept;
  if (!config.signup.enabled) return <Notice tone="info">{t("signupUnavailable")}</Notice>;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const result = await api.post<{ verification: boolean }>("/auth/signup", { email, name, password, accept_terms: accept, lang });
      if (!result.verification) return router.replace("/welcome"); // active at once (no e-mail verification)
      onSent(email.trim().toLowerCase());
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPending(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-5" aria-label={t("signUp")}>
      <Field icon={Mail} label={anyDomain ? t("email") : t("workEmail")} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder={anyDomain ? t("anyEmailPlaceholder") : t("emailPlaceholder")} hint={anyDomain ? undefined : t("companyHint", { domains })} />
      <Field icon={User} label={t("fullName")} autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)} placeholder={t("namePlaceholder")} />
      {anyDomain ? null : <Field icon={Building2} label={t("company")} readOnly tabIndex={-1} value={companyOf(email, config.signup.domains)} placeholder="—" />}
      <div>
        <PasswordField icon={Lock} label={t("createPassword")} value={password} onChange={setPassword} autoComplete="new-password" />
        <PasswordRules password={password} />
      </div>
      <div className="pt-1">
        <Checkbox checked={accept} onChange={setAccept}>
          {t("agree")}{" "}
          <Link href="/legal/terms" target="_blank" className="text-accent underline underline-offset-2">{t("terms")}</Link> {t("and")}{" "}
          <Link href="/legal/privacy" target="_blank" className="text-accent underline underline-offset-2">{t("privacy")}</Link>
        </Checkbox>
      </div>
      {error ? <Notice>{error}</Notice> : null}
      <Button type="submit" variant="primary" size="lg" className="h-[52px] w-full rounded-[10px] text-[16px] font-semibold" disabled={pending || !ready}>
        {t("createAccount")} <ArrowRight className="!size-[18px]" />
      </Button>
      <Providers config={config} />
    </form>
  );
}

function useCountdown(seconds: number, key: number) {
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    setLeft(seconds);
    const id = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [seconds, key]);
  return left;
}

function Verify({ config, email, onBack }: { config: AuthConfig; email: string; onBack: () => void }) {
  const t = useT(M);
  const lang = useLang();
  const router = useRouter();
  const errorText = useErrorText(config.signup.domains);
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const left = useCountdown(60, sent);
  const dev = useDevCode(email, config.dev_outbox, sent);
  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (code.length !== 6) return;
    setPending(true);
    setError(null);
    try {
      await api.post("/auth/signup/verify", { email, code });
      router.replace("/welcome");
    } catch (err) {
      setError(errorText(err));
      setPending(false);
    }
  };
  const resend = async () => {
    setError(null);
    try {
      await api.post("/auth/signup/resend", { email, lang });
      setSent((n) => n + 1);
      setInfo(t("resent"));
    } catch (err) {
      setError(errorText(err));
    }
  };
  return (
    <form onSubmit={submit} className="space-y-4" aria-label={t("verifyTitle")}>
      <p className="text-[14px] leading-relaxed text-muted">{t("verifyText", { email, minutes: 15 })}</p>
      <CodeInput value={code} onChange={setCode} />
      {config.dev_outbox && dev.data?.code ? <Notice tone="info">{t("devCode", { code: dev.data.code })}</Notice> : null}
      {info && !error ? <Notice tone="success">{info}</Notice> : null}
      {error ? <Notice>{error}</Notice> : null}
      <Submit pending={pending || code.length !== 6}>{t("verify")}</Submit>
      <div className="flex items-center justify-between text-[13px]">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-muted hover:text-text"><ArrowLeft className="size-3.5" /> {t("changeEmail")}</button>
        <button type="button" onClick={resend} disabled={left > 0} className="text-accent disabled:text-subtle">{left > 0 ? t("resendIn", { s: left }) : t("resend")}</button>
      </div>
    </form>
  );
}

function Forgot({ config, initial, onSent, onBack }: { config: AuthConfig; initial: string; onSent: (email: string) => void; onBack: () => void }) {
  const t = useT(M);
  const lang = useLang();
  const errorText = useErrorText(config.signup.domains);
  const [email, setEmail] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      await api.post("/auth/password/forgot", { email, lang });
      onSent(email.trim().toLowerCase());
    } catch (err) {
      setError(errorText(err));
      setPending(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-5" aria-label={t("forgotTitle")}>
      <p className="text-[14px] leading-relaxed text-muted">{t("forgotText")}</p>
      <Field icon={Mail} label={t("workEmail")} type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder={t("emailPlaceholder")} />
      {error ? <Notice>{error}</Notice> : null}
      <Submit pending={pending}>{t("sendCode")}</Submit>
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="size-3.5" /> {t("backToSignIn")}</button>
    </form>
  );
}

function Reset({ config, email, onDone, onBack }: { config: AuthConfig; email: string; onDone: () => void; onBack: () => void }) {
  const t = useT(M);
  const errorText = useErrorText(config.signup.domains);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const dev = useDevCode(email, config.dev_outbox, 0);
  const rules = passwordRules(password);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      await api.post("/auth/password/reset", { email, code, password });
      onDone();
    } catch (err) {
      setError(errorText(err));
      setPending(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-5" aria-label={t("resetTitle")}>
      <p className="text-[14px] leading-relaxed text-muted">{t("resetText", { email })}</p>
      <CodeInput value={code} onChange={setCode} />
      {config.dev_outbox && dev.data?.code ? <Notice tone="info">{t("devCode", { code: dev.data.code })}</Notice> : null}
      <div>
        <PasswordField icon={KeyRound} label={t("newPassword")} value={password} onChange={setPassword} autoComplete="new-password" />
        <PasswordRules password={password} />
      </div>
      {error ? <Notice>{error}</Notice> : null}
      <Submit pending={pending || code.length !== 6 || !(rules.length && rules.letters && rules.digits)}>{t("resetSubmit")}</Submit>
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="size-3.5" /> {t("backToSignIn")}</button>
    </form>
  );
}

function AuthFlow() {
  const t = useT(M);
  const params = useSearchParams();
  const next = (() => {
    const target = params.get("next") ?? "/";
    return target.startsWith("/") && !target.startsWith("//") ? target : "/";
  })();
  const { data: config } = useAuthConfig();
  const [step, setStep] = useState<Step>(params.get("tab") === "signup" ? "signup" : "signin");
  const [email, setEmail] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const isEntry = step === "signin" || step === "signup";
  const heading = step === "verify" ? t("verifyTitle") : step === "forgot" ? t("forgotTitle") : step === "reset" ? t("resetTitle") : null;

  return (
    <AuthShell>
      <div className="rounded-[22px] border border-border bg-surface px-6 pb-8 pt-6 shadow-[0_30px_80px_-40px_rgb(30_20_18/0.3)] sm:px-9 lg:pt-9">
        {/* on phones the cosmic banner above already carries the logo */}
        <div className="hidden justify-center lg:flex">
          <NovaLogo height={50} />
        </div>
        {isEntry ? (
          <div className="mb-7 lg:mt-8">
            <Tabs value={step} onChange={(v) => { setNotice(null); setStep(v as Step); }} items={[{ value: "signin", label: t("signIn") }, { value: "signup", label: t("signUp") }]} />
          </div>
        ) : (
          <div className="mb-6 text-center lg:mt-7">
            {step === "verify" ? <div className="text-[11.5px] font-medium uppercase tracking-[0.14em] text-subtle">{t("verifyEyebrow")}</div> : null}
            <h2 className="mt-1.5 text-[24px] font-semibold tracking-tight">{heading}</h2>
          </div>
        )}
        {!config ? (
          <div className="h-64" />
        ) : (
          <AnimatePresence mode="wait">
            <motion.div key={step} {...fade}>
              {step === "signin" ? (
                <SignIn config={config} next={next} notice={notice} onForgot={(e) => { setEmail(e); setStep("forgot"); }} onUnverified={(e) => { setEmail(e.trim().toLowerCase()); setStep("verify"); }} />
              ) : step === "signup" ? (
                <SignUp config={config} onSent={(e) => { setEmail(e); setStep("verify"); }} />
              ) : step === "verify" ? (
                <Verify config={config} email={email} onBack={() => setStep("signup")} />
              ) : step === "forgot" ? (
                config.password_reset ? <Forgot config={config} initial={email} onSent={(e) => { setEmail(e); setStep("reset"); }} onBack={() => setStep("signin")} /> : <Notice tone="info">{t("resetUnavailable")}</Notice>
              ) : (
                <Reset config={config} email={email} onDone={() => { setNotice(t("resetDone")); setStep("signin"); }} onBack={() => setStep("signin")} />
              )}
            </motion.div>
          </AnimatePresence>
        )}
      </div>
    </AuthShell>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <AuthFlow />
    </Suspense>
  );
}
