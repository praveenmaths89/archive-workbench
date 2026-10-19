"use client";

import { I18nProvider, type Locale } from "@/lib/i18n";

export default function Providers({
  children,
  initialLocale,
  initialTheme,
}: {
  children: React.ReactNode;
  initialLocale: Locale;
  initialTheme: "light" | "dark";
}) {
  return (
    <I18nProvider initialLocale={initialLocale} initialTheme={initialTheme}>
      {children}
    </I18nProvider>
  );
}
