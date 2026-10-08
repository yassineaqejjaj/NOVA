import { DM_Sans, Montserrat } from "next/font/google";

/** NOVA's brand typeface (landing, legal pages): declared once, shared by the layouts. */
export const montserrat = Montserrat({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-montserrat", display: "swap" });

/** Sign-in, sign-up and logout screens (NOVA's authentication design). */
export const dmSans = DM_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-dm-sans", display: "swap" });
