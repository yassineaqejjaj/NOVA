"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { NovaLogo } from "@/components/shell/nova-mark";
import { useLang } from "@/lib/i18n";

import { LanguageSwitch } from "./auth-ui";

type Doc = { title: string; updated: string; draft: string; back: string; sections: { h: string; p: string[] }[] };

const DOCS: Record<"terms" | "privacy", Record<"en" | "fr", Doc>> = {
  terms: {
    en: {
      title: "Terms of Service",
      updated: "Version of 5 October 2026",
      draft: "Working version describing how NOVA operates — to be validated by Devoteam’s legal team.",
      back: "Back to sign-in",
      sections: [
        { h: "Who can use NOVA", p: ["NOVA is Devoteam’s personal AI product agent. Accounts are personal: one per person, with your own e-mail address (confirmed by an e-mailed code when verification is enabled); never share your password. The shared demo account is for demonstrations only."] },
        { h: "What NOVA does", p: ["NOVA plans and carries out product, project, design and engineering work with specialist AI agents, from your requests and the project context you can access in ORBIT. Its deliverables are proposals: you remain responsible for reviewing them before using or sharing them."] },
        { h: "Acceptable use", p: ["Use NOVA for your professional work only. Respect the classification of the information you handle (C0 public to C3 secret) and the confidentiality commitments made to clients. Do not use NOVA for content related to crypto exchanges, adult content, pirated content or healthcare."] },
        { h: "Availability", p: ["NOVA is provided as is, without a service-level commitment. Features may change; accounts may be suspended in case of misuse."] },
      ],
    },
    fr: {
      title: "Conditions d’utilisation",
      updated: "Version du 5 octobre 2026",
      draft: "Version de travail décrivant le fonctionnement de NOVA — à valider par le service juridique de Devoteam.",
      back: "Retour à la connexion",
      sections: [
        { h: "Qui peut utiliser NOVA", p: ["NOVA est l’agent produit IA personnel de Devoteam. Les comptes sont personnels : un par personne, avec votre propre adresse e-mail (confirmée par un code envoyé par e-mail lorsque la vérification est active) ; ne partagez jamais votre mot de passe. Le compte démo partagé est réservé aux démonstrations."] },
        { h: "Ce que fait NOVA", p: ["NOVA planifie et réalise des travaux produit, projet, design et ingénierie avec des agents IA spécialisés, à partir de vos demandes et du contexte projet auquel vous avez accès dans ORBIT. Ses livrables sont des propositions : vous restez responsable de leur relecture avant de les utiliser ou de les partager."] },
        { h: "Usage acceptable", p: ["Utilisez NOVA uniquement pour votre travail professionnel. Respectez la classification des informations manipulées (C0 public à C3 secret) et les engagements de confidentialité pris envers les clients. N’utilisez pas NOVA pour des contenus liés aux plateformes d’échange de cryptomonnaies, aux contenus pour adultes, aux contenus piratés ou à la santé."] },
        { h: "Disponibilité", p: ["NOVA est fourni en l’état, sans engagement de niveau de service. Les fonctionnalités peuvent évoluer ; un compte peut être suspendu en cas d’usage abusif."] },
      ],
    },
  },
  privacy: {
    en: {
      title: "Privacy Policy",
      updated: "Version of 5 October 2026",
      draft: "Working version describing how NOVA processes data — to be validated by Devoteam’s legal team and DPO.",
      back: "Back to sign-in",
      sections: [
        { h: "Data NOVA keeps", p: ["Your account: name, work e-mail, preferences. Your work: requests, conversations, Artifacts, their versions and the references of the context used. An audit trail of sign-ins and changes. Passwords are kept by the identity service (Keycloak), never by NOVA; verification codes are stored only as a hash and expire after 15 minutes."] },
        { h: "Processors", p: ["Requests and the context needed to answer them are processed by the language model provider Anthropic (Claude). When you use voice, audio is transcribed and answers are spoken by ElevenLabs. Project context comes from ORBIT with your own access rights; quality evaluations go to FORGE. NOVA is hosted on Railway and Vercel."] },
        { h: "Classification", p: ["Content classified C2 confidential or C3 secret is shown with its classification, never moved to a less protected place and never read aloud."] },
        { h: "Cookies", p: ["A single sign-in cookie (httpOnly) keeps your session; interface preferences (theme, language) stay in your browser."] },
        { h: "Your rights", p: ["You can ask your NOVA administrator for access, correction or deletion of your data."] },
      ],
    },
    fr: {
      title: "Politique de confidentialité",
      updated: "Version du 5 octobre 2026",
      draft: "Version de travail décrivant les traitements de NOVA — à valider par le service juridique et le DPO de Devoteam.",
      back: "Retour à la connexion",
      sections: [
        { h: "Données conservées par NOVA", p: ["Votre compte : nom, e-mail professionnel, préférences. Votre travail : demandes, conversations, Artefacts, leurs versions et les références du contexte utilisé. Une trace d’audit des connexions et des modifications. Les mots de passe sont conservés par le service d’identité (Keycloak), jamais par NOVA ; les codes de vérification ne sont stockés que sous forme hachée et expirent après 15 minutes."] },
        { h: "Sous-traitants", p: ["Les demandes et le contexte nécessaire pour y répondre sont traités par le fournisseur de modèle de langage Anthropic (Claude). Lorsque vous utilisez la voix, l’audio est transcrit et les réponses sont lues par ElevenLabs. Le contexte projet provient d’ORBIT avec vos propres droits ; les évaluations de qualité vont à FORGE. NOVA est hébergé sur Railway et Vercel."] },
        { h: "Classification", p: ["Les contenus classés C2 confidentiel ou C3 secret sont affichés avec leur classification, ne sont jamais déplacés vers un lieu moins protégé et ne sont jamais lus à voix haute."] },
        { h: "Cookies", p: ["Un seul cookie de connexion (httpOnly) maintient votre session ; les préférences d’interface (thème, langue) restent dans votre navigateur."] },
        { h: "Vos droits", p: ["Vous pouvez demander à votre administrateur NOVA l’accès, la rectification ou la suppression de vos données."] },
      ],
    },
  },
};

export function LegalPage({ doc }: { doc: "terms" | "privacy" }) {
  const lang = useLang();
  const d = DOCS[doc][lang];
  return (
    <div className="min-h-dvh bg-background font-[family-name:var(--font-montserrat)] text-text">
      <header className="mx-auto flex max-w-3xl items-center justify-between px-4 py-6">
        <NovaLogo height={22} />
        <LanguageSwitch tone="light" />
      </header>
      <main className="mx-auto max-w-3xl px-4 pb-16">
        <Link href="/login" className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="size-3.5" /> {d.back}</Link>
        <h1 className="mt-4 text-[32px] font-semibold tracking-tight">{d.title}</h1>
        <p className="mt-1 text-[13px] text-subtle">{d.updated}</p>
        <p className="mt-4 rounded-[10px] bg-warning/10 px-3 py-2 text-[13px] text-warning">{d.draft}</p>
        {d.sections.map((s) => (
          <section key={s.h} className="mt-8">
            <h2 className="text-[17px] font-semibold">{s.h}</h2>
            {s.p.map((p) => <p key={p} className="mt-2 text-[14.5px] leading-relaxed text-muted">{p}</p>)}
          </section>
        ))}
      </main>
    </div>
  );
}
