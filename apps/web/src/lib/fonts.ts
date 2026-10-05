import { Montserrat } from "next/font/google";

/** NOVA's brand typeface (landing, sign-in, logout, legal pages): declared once, shared by the layouts. */
export const montserrat = Montserrat({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-montserrat", display: "swap" });
