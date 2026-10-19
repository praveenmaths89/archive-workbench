import type { Metadata } from "next";
import { cookies } from "next/headers";
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
  display: "fallback",
  adjustFontFallback: true,
});
const serif = Noto_Serif({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-serif",
  display: "fallback",
  adjustFontFallback: true,
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

const LOCALES = ["en", "hi", "kn", "mr", "ta", "te", "bn"] as const;
type Locale = (typeof LOCALES)[number];

export const metadata: Metadata = {
  title: "Archive Workbench",
  description: "A local research workbench for historical documents.",
};

function panePx(value: string | undefined, min: number, max: number, fallback: number) {
  const n = Number(value);
  if (Number.isFinite(n) && n >= min && n <= max) return Math.round(n);
  return fallback;
}

const themeScript = `
try {
  if (location.hostname === "127.0.0.1") {
    location.replace("http://localhost:" + (location.port || "3000") + location.pathname + location.search + location.hash);
  }
  var allowed = {en:1,hi:1,kn:1,mr:1,ta:1,te:1,bn:1};
  var theme = localStorage.getItem("aw-theme");
  if (theme !== "light" && theme !== "dark") {
    theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.dataset.theme = theme;
  var locale = localStorage.getItem("aw-locale");
  if (!allowed[locale]) locale = document.documentElement.lang || "en";
  document.documentElement.lang = locale;
  document.documentElement.dataset.locale = locale;
  var left = Number(localStorage.getItem("aw-pane-left"));
  if (!(left >= 200 && left <= 520)) left = 260;
  var right = Number(localStorage.getItem("aw-pane-right"));
  if (!(right >= 240 && right <= 560)) right = 300;
  document.documentElement.style.setProperty("--pane-left", left + "px");
  document.documentElement.style.setProperty("--pane-right", right + "px");
  var hideLeft = localStorage.getItem("aw-hide-left") === "1" ? "1" : "0";
  var hideRight = localStorage.getItem("aw-hide-right") === "1" ? "1" : "0";
  if (hideLeft === "1") document.documentElement.dataset.hideLeft = "1";
  else delete document.documentElement.dataset.hideLeft;
  if (hideRight === "1") document.documentElement.dataset.hideRight = "1";
  else delete document.documentElement.dataset.hideRight;
  var cookie = "; Path=/; Max-Age=31536000; SameSite=Lax";
  document.cookie = "aw-theme=" + theme + cookie;
  document.cookie = "aw-locale=" + locale + cookie;
  document.cookie = "aw-pane-left=" + left + cookie;
  document.cookie = "aw-pane-right=" + right + cookie;
  document.cookie = "aw-hide-left=" + hideLeft + cookie;
  document.cookie = "aw-hide-right=" + hideRight + cookie;
} catch (e) {}
`;

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const jar = await cookies();
  const themeCookie = jar.get("aw-theme")?.value;
  const localeCookie = jar.get("aw-locale")?.value;
  const theme = themeCookie === "dark" || themeCookie === "light" ? themeCookie : "light";
  const locale: Locale = (LOCALES as readonly string[]).includes(localeCookie || "")
    ? localeCookie as Locale
    : "en";
  const paneLeft = panePx(jar.get("aw-pane-left")?.value, 200, 520, 260);
  const paneRight = panePx(jar.get("aw-pane-right")?.value, 240, 560, 300);
  const hideLeft = jar.get("aw-hide-left")?.value === "1";
  const hideRight = jar.get("aw-hide-right")?.value === "1";
  return (
    <html
      lang={locale}
      data-theme={theme}
      data-locale={locale}
      data-hide-left={hideLeft ? "1" : undefined}
      data-hide-right={hideRight ? "1" : undefined}
      className={fonts}
      style={{ ["--pane-left" as string]: `${paneLeft}px`, ["--pane-right" as string]: `${paneRight}px` }}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <Providers initialLocale={locale} initialTheme={theme}>{children}</Providers>
      </body>
    </html>
  );
}
