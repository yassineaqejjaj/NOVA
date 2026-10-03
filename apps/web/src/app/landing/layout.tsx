import type { Metadata } from "next";
import { Montserrat } from "next/font/google";

const montserrat = Montserrat({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-montserrat", display: "swap" });

export const metadata: Metadata = {
  title: { absolute: "NOVA by devoteam — L’IA agentique pour les équipes produit" },
  description:
    "Nova orchestre vos experts et ses agents autour d’un même contexte pour cadrer, décider et livrer sans perte d’information.",
  openGraph: {
    title: "NOVA by devoteam",
    description: "L’IA agentique qui transforme votre équipe en force augmentée.",
    type: "website",
  },
};

export default function LandingLayout({ children }: { children: React.ReactNode }) {
  return <div className={montserrat.variable}>{children}</div>;
}
