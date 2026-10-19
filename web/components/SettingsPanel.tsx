"use client";

import { FormEvent, useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";

export type SettingsView = {
  provider: string;
  model: string;
  api_base: string;
  key_set: boolean;
  key_mask: string;
  key_source: string;
  ocr_engine: string;
  llm: boolean;
  is_admin: boolean;
  auth_disabled: boolean;
};

type AccessRow = { id: string; kind: string; value: string; is_admin: boolean; source: string };

const PROVIDERS = [
  ["anthropic", "providerAnthropic"],
  ["gemini", "providerGemini"],
  ["openai", "providerOpenai"],
  ["custom", "providerCustom"],
] as const;

export default function SettingsPanel({ onSaved }: { onSaved: (settings: SettingsView) => void }) {
  const { t } = useI18n();
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [engine, setEngine] = useState("tesseract");
  const [note, setNote] = useState("");
  const [models, setModels] = useState("");
  const [access, setAccess] = useState<AccessRow[]>([]);
  const [email, setEmail] = useState("");
  const [domain, setDomain] = useState("");
  const [me, setMe] = useState("");

  function apply(next: SettingsView) {
    setSettings(next);
    setProvider(next.provider || "anthropic");
    setModel(next.model || "");
    setApiBase(next.api_base || "");
    setEngine(next.ocr_engine || "tesseract");
    setApiKey("");
    onSaved(next);
  }

  useEffect(() => {
    let stop = false;
    async function load() {
      const [settingsRes, modelsRes, meRes] = await Promise.all([
        fetch("/api/settings"),
        fetch("/api/ocr/models"),
        fetch("/api/auth/me"),
      ]);
      if (stop) return;
      if (settingsRes.ok) {
        const body = await settingsRes.json();
        apply(body);
        if (body.is_admin) {
          const list = await fetch("/api/access");
          if (list.ok) setAccess(await list.json());
        }
      }
      if (modelsRes.ok) {
        const status = await modelsRes.json();
        setModels(status.message || status.state || "");
      }
      if (meRes.ok) {
        const who = await meRes.json();
        if (who.email) setMe(who.email);
      }
    }
    load();
    return () => { stop = true; };
    // apply is stable enough for this mount-only load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setNote("");
    const body: Record<string, string> = { provider, model, api_base: apiBase, ocr_engine: engine };
    if (apiKey.trim()) body.api_key = apiKey.trim();
    const response = await fetch("/api/settings", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      setNote(response.status === 403 ? t("adminOnly") : t("errorApi"));
      return;
    }
    apply(await response.json());
    setNote(t("saved"));
  }

  async function testKey() {
    setNote("");
    const response = await fetch("/api/settings/test", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ provider, model, api_base: apiBase, api_key: apiKey }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      setNote(typeof payload.detail === "string" ? payload.detail : t("adminOnly"));
      return;
    }
    setNote(payload.ok ? payload.detail : payload.detail || t("errorApi"));
  }

  async function clearKey() {
    const response = await fetch("/api/settings/key", { method: "DELETE" });
    if (!response.ok) {
      setNote(t("adminOnly"));
      return;
    }
    apply(await response.json());
    setNote(t("noKey"));
  }

  async function addAccess(kind: "email" | "domain", value: string) {
    const response = await fetch("/api/access", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ kind, value, is_admin: false }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      setNote(typeof payload.detail === "string" ? payload.detail : t("adminOnly"));
      return;
    }
    setAccess(await response.json());
    if (kind === "email") setEmail("");
    else setDomain("");
  }

  async function removeAccess(id: string) {
    const response = await fetch(`/api/access/${id}`, { method: "DELETE" });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      setNote(typeof payload.detail === "string" ? payload.detail : t("adminOnly"));
      return;
    }
    setAccess((rows) => rows.filter((row) => row.id !== id));
  }

  const locked = settings ? !settings.is_admin : true;

  return (
    <div className="settings">
      <h2 className="pane-title">{t("settingsTitle")}</h2>
      {me && <p className="quiet">{t("signedInAs", { email: me })}</p>}
      {settings?.auth_disabled && <p className="quiet">{t("authOff")}</p>}
      {settings?.key_source === "env" && <p className="quiet">{t("envKey")}</p>}
      {settings?.key_source === "none" && <p className="quiet">{t("noKey")}</p>}
      {settings?.key_source === "saved" && settings.key_mask && <p className="quiet">{settings.key_mask}</p>}
      {note && <p role="status">{note}</p>}

      <form className="card" onSubmit={save}>
        <h3 className="pane-title">{t("modelKey")}</h3>
        <p className="quiet">{t("modelKeyHelp")}</p>
        <div className="filters">
          <label className="field">
            {t("provider")}
            <select value={provider} disabled={locked} onChange={(event) => setProvider(event.target.value)}>
              {PROVIDERS.map(([id, key]) => <option key={id} value={id}>{t(key)}</option>)}
            </select>
          </label>
          <label className="field">
            {t("model")}
            <input value={model} disabled={locked} onChange={(event) => setModel(event.target.value)} />
          </label>
          <label className="field">
            {t("ocrDefault")}
            <select value={engine} disabled={locked} onChange={(event) => setEngine(event.target.value)}>
              <option value="tesseract">{t("freeTesseract")}</option>
              <option value="ppocr">{t("freePpocr")}</option>
              <option value="claude">{t("claude")}</option>
              <option value="gemini">{t("gemini")}</option>
            </select>
          </label>
          <label className="field">
            {t("apiBase")}
            <input value={apiBase} disabled={locked} placeholder={t("apiBaseHint")} onChange={(event) => setApiBase(event.target.value)} />
          </label>
          <label className="field">
            {t("apiKey")}
            <input type="password" autoComplete="off" value={apiKey} disabled={locked} onChange={(event) => setApiKey(event.target.value)} />
          </label>
        </div>
        <div className="row">
          <button className="primary" type="submit" disabled={locked}>{t("save")}</button>
          <button className="ghost" type="button" disabled={locked} onClick={testKey}>{t("testKey")}</button>
          <button className="ghost" type="button" disabled={locked} onClick={clearKey}>{t("clearKey")}</button>
        </div>
        {locked && <p className="quiet">{t("adminOnly")}</p>}
      </form>

      <section>
        <h3 className="pane-title">{t("ppocrStatus")}</h3>
        <p className="quiet">{models}</p>
      </section>

      {settings?.is_admin && (
        <section>
          <h3 className="pane-title">{t("accessList")}</h3>
          <p className="quiet">{t("accessHelp")}</p>
          <ul className="access-list">
            {access.map((row) => (
              <li key={row.id}>
                <span>{row.value} · {row.kind}{row.is_admin ? ` · ${t("admin")}` : ""}{row.source === "env" ? ` · ${t("fromEnv")}` : ""}</span>
                <button type="button" className="ghost" onClick={() => removeAccess(row.id)}>{t("remove")}</button>
              </li>
            ))}
          </ul>
          <form className="row" style={{ marginTop: 10 }} onSubmit={(event) => { event.preventDefault(); addAccess("email", email); }}>
            <label className="sr" htmlFor="add-email">{t("emailAddress")}</label>
            <input id="add-email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder={t("emailAddress")} />
            <button className="ghost" type="submit">{t("addEmail")}</button>
          </form>
          <form className="row" style={{ marginTop: 8 }} onSubmit={(event) => { event.preventDefault(); addAccess("domain", domain); }}>
            <label className="sr" htmlFor="add-domain">{t("domainName")}</label>
            <input id="add-domain" value={domain} onChange={(event) => setDomain(event.target.value)} placeholder={t("domainName")} />
            <button className="ghost" type="submit">{t("addDomain")}</button>
          </form>
        </section>
      )}
      <button
        className="ghost"
        type="button"
        onClick={async () => {
          await fetch("/api/auth/logout", { method: "POST" });
          window.location.href = "/";
        }}
      >{t("signOut")}</button>
    </div>
  );
}
