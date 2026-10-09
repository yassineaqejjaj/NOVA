import localFont from "next/font/local";

// Self-hosted variable fonts (latin subset, OFL): the build never depends on fonts.googleapis.com.

/** NOVA's brand typeface (landing, legal pages): declared once, shared by the layouts. */
export const montserrat = localFont({
  src: "../assets/fonts/montserrat-latin-wght-normal.woff2",
  weight: "100 900",
  variable: "--font-montserrat",
  display: "swap",
});

/** Sign-in, sign-up and logout screens (NOVA's authentication design). */
export const dmSans = localFont({
  src: "../assets/fonts/dm-sans-latin-wght-normal.woff2",
  weight: "100 1000",
  variable: "--font-dm-sans",
  display: "swap",
});
