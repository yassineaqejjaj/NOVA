import { dmSans, montserrat } from "@/lib/fonts";

/** Sign-in, sign-up, logout and legal pages: NOVA's brand typefaces. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className={`${montserrat.variable} ${dmSans.variable}`}>{children}</div>;
}
