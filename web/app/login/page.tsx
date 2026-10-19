"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useI18n } from "@/lib/i18n";

function LoginInner() {
  const { t } = useI18n();
  const params = useSearchParams();
  const config = params.get("error") === "config";
  return (
    <main className="gate">
      <section className="card">
        <h1>{t("signInTitle")}</h1>
        <p>{config ? t("configError") : t("signInBody")}</p>
        <p><a className="primary" href="/api/auth/login" style={{ display: "inline-block", textDecoration: "none" }}>{t("signIn")}</a></p>
      </section>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}
