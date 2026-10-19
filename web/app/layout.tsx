import type { Metadata } from "next";
import {
  Noto_Sans,
  Noto_Sans_Bengali,
  Noto_Sans_Devanagari,
  Noto_Sans_Kannada,
  Noto_Sans_Tamil,
  Noto_Sans_Telugu,
  Noto_Serif,
} from "next/font/google";
import Providers from "./providers";
import "./globals.css";

const sans = Noto_Sans({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-sans",
  display: "swap",
});
const serif = Noto_Serif({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-serif",
  display: "swap",
});
const devanagari = Noto_Sans_Devanagari({
  subsets: ["devanagari"],
  weight: ["400", "600"],
  variable: "--font-deva",
  display: "swap",
});
const kannada = Noto_Sans_Kannada({
  subsets: ["kannada"],
  weight: ["400", "600"],
  variable: "--font-knda",
  display: "swap",
});
const tamil = Noto_Sans_Tamil({
  subsets: ["tamil"],
  weight: ["400", "600"],
  variable: "--font-taml",
  display: "swap",
});
const telugu = Noto_Sans_Telugu({
  subsets: ["telugu"],
  weight: ["400", "600"],
  variable: "--font-telu",
  display: "swap",
});
const bengali = Noto_Sans_Bengali({
  subsets: ["bengali"],
  weight: ["400", "600"],
  variable: "--font-beng",
  display: "swap",
});

const fonts = [
  sans.variable,
  serif.variable,
  devanagari.variable,
  kannada.variable,
  tamil.variable,
  telugu.variable,
  bengali.variable,
].join(" ");

export const metadata: Metadata = {
  title: "Archive Workbench",
  description: "A local research workbench for historical documents.",
};

const themeScript = `
try {
  var theme = localStorage.getItem("aw-theme");
  if (theme !== "light" && theme !== "dark") {
    theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.dataset.theme = theme;
  var locale = localStorage.getItem("aw-locale");
  if (locale) {
    document.documentElement.lang = locale;
    document.documentElement.dataset.locale = locale;
  }
} catch (e) {}
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={fonts} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
