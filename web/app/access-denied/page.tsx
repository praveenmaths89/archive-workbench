"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useI18n } from "@/lib/i18n";

function DeniedInner() {
  const { t } = useI18n();
  const params = useSearchParams();
  const email = params.get("email");
  const reason = params.get("reason");
  let detail = t("accessBody");
  if (reason === "cancelled") detail = t("reasonCancelled");
  if (reason === "state") detail = t("reasonState");
  if (reason === "google") detail = t("reasonGoogle");
  return (
    <main className="gate">
      <section className="card">
        <h1>{t("accessTitle")}</h1>
        <p>{detail}</p>
        {email && <p className="quiet">{email}</p>}
        <p><a href="/login">{t("accessHome")}</a></p>
      </section>
    </main>
  );
}

export default function AccessDeniedPage() {
  return (
    <Suspense fallback={null}>
      <DeniedInner />
    </Suspense>
  );
}
