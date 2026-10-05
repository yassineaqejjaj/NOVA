import { Montserrat } from "next/font/google";

const montserrat = Montserrat({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-montserrat", display: "swap" });

/** Sign-in, sign-up, logout and legal pages: NOVA's brand typeface. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className={montserrat.variable}>{children}</div>;
}
