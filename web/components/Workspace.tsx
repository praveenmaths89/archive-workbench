"use client";

import dynamic from "next/dynamic";
import { FormEvent, PointerEvent as ReactPointerEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { LOCALES, LOCALE_NAMES, useI18n, type Locale } from "@/lib/i18n";
import type { Region } from "./Viewer";
import SettingsPanel, { type SettingsView } from "./SettingsPanel";

const Viewer = dynamic(() => import("./Viewer"), {
  ssr: false,
  loading: () => <div className="viewer-slot" aria-hidden="true" />,
});

type DocSummary = {
  id: string;
  filename: string;
  status: string;
  page_count: number;
  error?: string | null;
  explanation?: string | null;
  collection?: string | null;
  language?: string | null;
  progress?: string | null;
  ocr_engine?: string | null;
};

type PageInfo = {
  id: string;
  number: number;
  status: string;
  text: string;
  translation?: string | null;
  translation_language?: string | null;
  ocr_engine?: string | null;
  flagged: boolean;
  confidence: number;
};

type RegionInfo = Region & { page_id: string; page_number: number; idx: number; type: string };
type Note = { id: string; body: string };
type Citation = { n: number; kind: string; page?: number; region_id?: string | null; url?: string; title?: string };
type ChatMessage = { id: string; role: string; content: string; citations: Citation[] };
type Detail = DocSummary & { pages: PageInfo[]; regions: RegionInfo[]; notes: Note[]; jobs: { id: string; kind: string; status: string }[] };
type Hit = { title: string; url: string; creators: string[]; date?: string | null; description: string; source: string };
type SourceBlock = { source: string; status: string; error?: string | null; hits: Hit[] };
type SearchHit = {
  kind: string;
  document_id: string;
  filename: string;
  title: string;
  page: number | null;
  region_id: string | null;
  snippet: string;
};

const STATUS_KEY: Record<string, string> = {
  queued: "statusQueued",
  processing: "statusReading",
  done: "statusDone",
  done_with_errors: "statusDoneErrors",
  failed: "statusFailed",
  rejected: "statusRejected",
  stopped: "statusStopped",
  pending: "statusWaiting",
  skipped: "statusSkipped",
};

const SOURCES = [
  ["internet_archive", "Internet Archive"],
  ["loc", "Library of Congress"],
  ["wikidata", "Wikidata"],
  ["openalex", "OpenAlex"],
  ["gallica", "Gallica"],
  ["europeana", "Europeana"],
  ["dpla", "DPLA"],
] as const;

const DOC_LANGS = ["en", "hi", "kn", "mr", "ta", "te", "bn"];

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function applyPanes(left: number, right: number, hideLeft: boolean, hideRight: boolean) {
  const root = document.documentElement;
  root.style.setProperty("--pane-left", `${left}px`);
  root.style.setProperty("--pane-right", `${right}px`);
  if (hideLeft) root.dataset.hideLeft = "1";
  else delete root.dataset.hideLeft;
  if (hideRight) root.dataset.hideRight = "1";
  else delete root.dataset.hideRight;
}

export default function Workspace() {
  const { t, locale, setLocale, theme, setTheme } = useI18n();
  const [view, setView] = useState<"workspace" | "library" | "settings">("workspace");
  const [docs, setDocs] = useState<DocSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pageNumber, setPageNumber] = useState(1);
  const [activeRegion, setActiveRegion] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [pageRange, setPageRange] = useState("");
  const [question, setQuestion] = useState("");
  const [note, setNote] = useState("");
  const [language, setLanguage] = useState("hi");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [apiDown, setApiDown] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [query, setQuery] = useState("Kittur");
  const [picked, setPicked] = useState<string[]>(["internet_archive", "loc", "wikidata", "openalex", "gallica"]);
  const [library, setLibrary] = useState<SourceBlock[] | null>(null);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [uploadEngine, setUploadEngine] = useState("tesseract");
  const [collection, setCollection] = useState("");
  const [docLanguage, setDocLanguage] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchHits, setSearchHits] = useState<SearchHit[] | null>(null);
  const [filterCollection, setFilterCollection] = useState("");
  const [filterLanguage, setFilterLanguage] = useState("");
  const [filterEngine, setFilterEngine] = useState("");
  const [filterWhen, setFilterWhen] = useState("");
  const [findOpen, setFindOpen] = useState(false);
  const [findQuery, setFindQuery] = useState("");
  const [hideLeft, setHideLeft] = useState(false);
  const [hideRight, setHideRight] = useState(false);
  const [left, setLeft] = useState(260);
  const [right, setRight] = useState(300);
  const [panesReady, setPanesReady] = useState(false);
  const [listReady, setListReady] = useState(false);
  const [maxMb, setMaxMb] = useState(500);
  const [progress, setProgress] = useState<number | null>(null);
  const [stageOver, setStageOver] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const searchOpenRef = useRef(false);
  const viewRef = useRef(view);
  searchOpenRef.current = searchOpen;
  viewRef.current = view;

  async function refreshList() {
    const response = await fetch("/api/documents");
    if (!response.ok) throw new Error("documents");
    const rows = (await response.json()) as DocSummary[];
    setDocs(rows);
    return rows;
  }

  async function refreshDetail(id: string) {
    const [docRes, msgRes] = await Promise.all([
      fetch(`/api/documents/${id}`),
      fetch(`/api/documents/${id}/messages`),
    ]);
    if (!docRes.ok) return;
    const doc = (await docRes.json()) as Detail;
    setDetail(doc);
    if (msgRes.ok) setMessages(await msgRes.json());
  }

  useLayoutEffect(() => {
    const storedLeft = Number(localStorage.getItem("aw-pane-left"));
    const storedRight = Number(localStorage.getItem("aw-pane-right"));
    const nextLeft = storedLeft >= 200 && storedLeft <= 520 ? storedLeft : 260;
    const nextRight = storedRight >= 240 && storedRight <= 560 ? storedRight : 300;
    const nextHideLeft = localStorage.getItem("aw-hide-left") === "1";
    const nextHideRight = localStorage.getItem("aw-hide-right") === "1";
    setLeft(nextLeft);
    setRight(nextRight);
    setHideLeft(nextHideLeft);
    setHideRight(nextHideRight);
    applyPanes(nextLeft, nextRight, nextHideLeft, nextHideRight);
    setPanesReady(true);
    if (!localStorage.getItem("aw-onboarded")) setShowOnboarding(true);
    fetch("/api/settings").then(async (response) => {
      if (response.ok) setSettings(await response.json());
    }).catch(() => {});
    fetch("/api/health").then(async (response) => {
      if (!response.ok) return;
      const body = await response.json();
      if (typeof body.max_file_mb === "number" && body.max_file_mb > 0) setMaxMb(body.max_file_mb);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!panesReady) return;
    applyPanes(left, right, hideLeft, hideRight);
    const cookie = "; Path=/; Max-Age=31536000; SameSite=Lax";
    localStorage.setItem("aw-pane-left", String(left));
    localStorage.setItem("aw-pane-right", String(right));
    localStorage.setItem("aw-hide-left", hideLeft ? "1" : "0");
    localStorage.setItem("aw-hide-right", hideRight ? "1" : "0");
    document.cookie = `aw-pane-left=${left}${cookie}`;
    document.cookie = `aw-pane-right=${right}${cookie}`;
    document.cookie = `aw-hide-left=${hideLeft ? "1" : "0"}${cookie}`;
    document.cookie = `aw-hide-right=${hideRight ? "1" : "0"}${cookie}`;
  }, [left, right, hideLeft, hideRight, panesReady]);

  useEffect(() => {
    if (settings && !settings.llm && (uploadEngine === "claude" || uploadEngine === "gemini")) {
      setUploadEngine(settings.ocr_engine === "ppocr" ? "ppocr" : "tesseract");
    }
  }, [settings, uploadEngine]);

  useEffect(() => {
    let stop = false;
    async function tick() {
      try {
        const rows = await refreshList();
        if (stop) return;
        const id = selected && rows.some((row) => row.id === selected) ? selected : rows[0]?.id;
        if (id && id !== selected) setSelected(id);
        if (id) await refreshDetail(id);
        if (!stop) setApiDown(false);
      } catch {
        if (!stop) setApiDown(true);
      } finally {
        if (!stop) setListReady(true);
      }
    }
    tick();
    const timer = setInterval(tick, 2500);
    return () => { stop = true; clearInterval(timer); };
  }, [selected]);

  useEffect(() => {
    if (!detail) return;
    setCollection(detail.collection || "");
    setDocLanguage(detail.language || "");
  }, [detail?.id]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      } else if (meta && event.key.toLowerCase() === "f" && viewRef.current === "workspace" && !searchOpenRef.current) {
        event.preventDefault();
        setFindOpen(true);
      } else if (event.key === "Escape") {
        setSearchOpen(false);
        setFindOpen(false);
        setShowOnboarding(false);
        localStorage.setItem("aw-onboarded", "1");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!searchOpen || searchQuery.trim().length < 2) {
      if (!searchQuery.trim()) setSearchHits(null);
      return;
    }
    const handle = setTimeout(async () => {
      const params = new URLSearchParams({ q: searchQuery.trim() });
      if (filterCollection.trim()) params.set("collection", filterCollection.trim());
      if (filterLanguage.trim()) params.set("language", filterLanguage.trim());
      if (filterEngine) params.set("engine", filterEngine);
      if (filterWhen) {
        const from = new Date();
        from.setDate(from.getDate() - (filterWhen === "week" ? 7 : 30));
        params.set("uploaded_from", from.toISOString().slice(0, 10));
      }
      const response = await fetch(`/api/search?${params}`);
      if (!response.ok) {
        setError(t("errorSearch"));
        return;
      }
      setSearchHits(await response.json());
    }, 250);
    return () => clearTimeout(handle);
  }, [searchOpen, searchQuery, filterCollection, filterLanguage, filterEngine, filterWhen, t]);

  const page = detail?.pages?.find((item) => item.number === pageNumber) || detail?.pages?.[0];
  const regions = useMemo(
    () => (detail?.regions || []).filter((region) => region.page_number === (page?.number || pageNumber)).sort((a, b) => a.idx - b.idx),
    [detail, page, pageNumber],
  );
  const llm = Boolean(settings?.llm);
  const imageUrl = selected && page ? `/api/documents/${selected}/pages/${page.number}/image` : null;

  function statusLabel(status: string) {
    return t(STATUS_KEY[status] || status);
  }

  function upload(files: File[]) {
    if (!files.length) return;
    const limit = maxMb * 1024 * 1024;
    const tooBig = files.find((file) => file.size > limit);
    if (tooBig) {
      setError(t("errorTooBig", {
        name: tooBig.name,
        size: (tooBig.size / (1024 * 1024)).toFixed(1),
        max: maxMb,
      }));
      return;
    }
    setBusy("busyUpload");
    setProgress(0);
    setError("");
    const body = new FormData();
    for (const file of files) body.append("files", file);
    const options: { pages?: string; ocr_engine?: string; collection?: string; language?: string } = {
      ocr_engine: uploadEngine,
    };
    if (pageRange.trim()) options.pages = pageRange.trim();
    if (collection.trim()) options.collection = collection.trim();
    if (docLanguage.trim()) options.language = docLanguage.trim();
    body.append("options", JSON.stringify(options));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/documents");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) setProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onerror = () => {
      setBusy("");
      setProgress(null);
      setError(t("errorUpload", { max: maxMb }));
    };
    xhr.onload = () => {
      setBusy("");
      setProgress(null);
      let payload: { detail?: string; documents?: { status: string; id: string; filename: string; error?: string }[] } = {};
      try {
        payload = JSON.parse(xhr.responseText || "{}");
      } catch {
        payload = {};
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        setError(payload.detail ? `${t("errorUpload", { max: maxMb })} ${payload.detail}` : t("errorUpload", { max: maxMb }));
        return;
      }
      const rejected = (payload.documents || []).filter((row) => row.status === "rejected");
      if (rejected.length) {
        setError(rejected.map((row) => t("errorRejected", { name: row.filename, detail: row.error || t("errorUpload", { max: maxMb }) })).join(" "));
      }
      const queued = (payload.documents || []).find((row) => row.status === "queued");
      if (queued) {
        setSelected(queued.id);
        setPageNumber(1);
        setActiveRegion(null);
      }
      refreshList().catch(() => setApiDown(true));
    };
    xhr.send(body);
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!selected || !question.trim()) return;
    setBusy("busyAsk");
    setError("");
    const response = await fetch(`/api/documents/${selected}/ask`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question }),
    });
    setBusy("");
    if (response.status === 409) {
      setError(t("errorWait"));
      return;
    }
    if (!response.ok) {
      setError(t("errorAsk"));
      return;
    }
    setQuestion("");
    await refreshDetail(selected);
  }

  async function addNote(event: FormEvent) {
    event.preventDefault();
    if (!selected || !note.trim()) return;
    await fetch(`/api/documents/${selected}/notes`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ body: note }),
    });
    setNote("");
    await refreshDetail(selected);
  }

  async function removeNote(id: string) {
    if (!selected) return;
    await fetch(`/api/documents/${selected}/notes/${id}`, { method: "DELETE" });
    await refreshDetail(selected);
  }

  async function translate() {
    if (!selected) return;
    setBusy("busyTranslate");
    await fetch(`/api/documents/${selected}/translate`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ language }),
    });
    setBusy("");
  }

  async function removeDoc() {
    if (!selected) return;
    await fetch(`/api/documents/${selected}`, { method: "DELETE" });
    setSelected(null);
    setDetail(null);
    await refreshList();
  }

  async function saveDocMeta() {
    if (!selected) return;
    await fetch(`/api/documents/${selected}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ collection, language: docLanguage }),
    });
  }

  function onCite(citation: Citation) {
    if (citation.kind !== "document") return;
    if (citation.page) setPageNumber(citation.page);
    if (citation.region_id) setActiveRegion(citation.region_id);
  }

  function openHit(hit: SearchHit) {
    setView("workspace");
    setSelected(hit.document_id);
    setPageNumber(hit.page || 1);
    setActiveRegion(hit.region_id);
    setFindQuery(searchQuery.trim());
    setFindOpen(Boolean(searchQuery.trim()));
    setSearchOpen(false);
  }

  async function runLibrary(event: FormEvent) {
    event.preventDefault();
    setBusy("busySearch");
    setError("");
    const response = await fetch(`/api/library/search?q=${encodeURIComponent(query)}&sources=${picked.join(",")}`);
    setBusy("");
    if (!response.ok) {
      setError(t("errorLibrary"));
      return;
    }
    const payload = await response.json();
    setLibrary(payload.sources);
  }

  function beginResize(which: "left" | "right", event: ReactPointerEvent) {
    event.preventDefault();
    const startX = event.clientX;
    const start = which === "left" ? left : right;
    function move(ev: PointerEvent) {
      const dx = ev.clientX - startX;
      if (which === "left") {
        const next = clamp(start + dx, 200, 520);
        setLeft(next);
        document.documentElement.style.setProperty("--pane-left", `${next}px`);
      } else {
        const next = clamp(start - dx, 240, 560);
        setRight(next);
        document.documentElement.style.setProperty("--pane-right", `${next}px`);
      }
    }
    function up() {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  function dismissOnboarding() {
    localStorage.setItem("aw-onboarded", "1");
    setShowOnboarding(false);
  }

  const kindLabel = (kind: string) => {
    if (kind === "translation") return t("kindTranslation");
    if (kind === "note") return t("kindNote");
    return t("kindTranscription");
  };

  return (
    <div className="app">
      <a className="skip" href="#viewer">{t("skipToPage")}</a>
      <header className="top">
        <h1>Archive Workbench</h1>
        <button type="button" className="search-launch" onClick={() => setSearchOpen(true)}>
          <span>{t("searchYours")}</span>
          <kbd aria-hidden="true">Ctrl/Cmd K</kbd>
        </button>
        <nav className="views" aria-label="Views">
          <button type="button" aria-current={view === "workspace" ? "page" : undefined} onClick={() => setView("workspace")}>{t("workspace")}</button>
          <button type="button" aria-current={view === "library" ? "page" : undefined} onClick={() => setView("library")}>{t("libraries")}</button>
          <button type="button" aria-current={view === "settings" ? "page" : undefined} onClick={() => setView("settings")}>{t("settings")}</button>
        </nav>
        <div className="grow">
          <label className="lang">
            <span className="sr">{t("interfaceLanguage")}</span>
            <select aria-label={t("interfaceLanguage")} value={locale} onChange={(event) => setLocale(event.target.value as Locale)}>
              {LOCALES.map((code) => <option key={code} value={code}>{LOCALE_NAMES[code]}</option>)}
            </select>
          </label>
          <button
            type="button"
            className="theme-toggle"
            aria-label={theme === "dark" ? t("lightMode") : t("darkMode")}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? t("lightMode") : t("darkMode")}
          </button>
        </div>
      </header>
      {(apiDown || error) && <p className="error banner" role="alert">{apiDown ? t("errorApi") : error}</p>}
      {progress !== null && (
        <p className="progress upload-progress" role="status">
          <progress value={progress} max={100} />
          {t("uploadProgress", { n: progress })}
        </p>
      )}

      {view === "workspace" ? (
        <div className="workspace">
          <div className="slot slot-left">
            <div className="rail rail-left">
              <button type="button" onClick={() => setHideLeft(false)}>{t("showDocuments")}</button>
            </div>
            <nav className="library" aria-label={t("documents")}>
              <div className="pane-head">
                <h2 className="pane-title">{t("documents")}</h2>
                <button type="button" className="ghost" onClick={() => setHideLeft(true)}>{t("hideDocuments")}</button>
              </div>
              <form
                className={`drop${dragOver ? " over" : ""}`}
                onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={(event) => { event.preventDefault(); setDragOver(false); upload(Array.from(event.dataTransfer.files)); }}
              >
                <label className="file">
                  {t("upload")}
                  <input
                    type="file"
                    accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,application/pdf,image/*"
                    multiple
                    onChange={(event) => {
                      upload(Array.from(event.target.files || []));
                      event.target.value = "";
                    }}
                  />
                </label>
                <label className="field">
                  {t("pages")}
                  <input value={pageRange} onChange={(event) => setPageRange(event.target.value)} placeholder={t("pagesHint")} />
                </label>
                <label className="field">
                  <span className="row">
                    {t("engine")}
                    <Tip label={t("engineTip")} />
                  </span>
                  <select aria-label={t("engine")} value={uploadEngine} onChange={(event) => setUploadEngine(event.target.value)}>
                    <option value="tesseract">{t("freeTesseract")}</option>
                    <option value="ppocr">{t("freePpocr")}</option>
                    <option value="claude" disabled={!llm}>{t("claude")}</option>
                    <option value="gemini" disabled={!llm}>{t("gemini")}</option>
                  </select>
                </label>
                <p className="quiet needs-key">{settings && !llm ? t("needsKey") : "\u00a0"}</p>
                <label className="field">
                  {t("collection")}
                  <input value={collection} placeholder={t("collectionPlaceholder")} onChange={(event) => setCollection(event.target.value)} onBlur={saveDocMeta} />
                </label>
                <label className="field">
                  {t("docLanguage")}
                  <input list="doc-langs" value={docLanguage} onChange={(event) => setDocLanguage(event.target.value)} onBlur={saveDocMeta} />
                </label>
                <datalist id="doc-langs">
                  {DOC_LANGS.map((code) => <option key={code} value={code} />)}
                </datalist>
              </form>
              {docs.length === 0 ? (
                <p className="quiet">{t("noDocuments")}</p>
              ) : (
                <ul className="doc-list">
                  {docs.map((doc) => (
                    <li key={doc.id}>
                      <button type="button" className={doc.id === selected ? "selected" : ""} onClick={() => { setSelected(doc.id); setPageNumber(1); setActiveRegion(null); }}>
                        <span className="doc-name">{doc.filename}</span>
                        <span className={`doc-meta status-${doc.status}`}>
                          {statusLabel(doc.status)} · {doc.page_count}
                          {doc.progress ? ` · ${doc.progress}` : ""}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <p className="privacy">{t("privacy")}</p>
            </nav>
          </div>
          <div
            className="resizer left"
            role="separator"
            aria-orientation="vertical"
            aria-label={t("resizeDocuments")}
            tabIndex={0}
            onPointerDown={(event) => beginResize("left", event)}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") setLeft((value) => clamp(value - 16, 200, 520));
              if (event.key === "ArrowRight") setLeft((value) => clamp(value + 16, 200, 520));
            }}
          />
          <main className="page-pane" id="viewer">
            {!listReady || (docs.length > 0 && !detail) ? (
              <div className="viewer-slot" aria-hidden="true" />
            ) : !detail ? (
              <div
                className={`empty-stage${stageOver ? " over" : ""}`}
                onDragOver={(event) => { event.preventDefault(); setStageOver(true); }}
                onDragLeave={() => setStageOver(false)}
                onDrop={(event) => { event.preventDefault(); setStageOver(false); upload(Array.from(event.dataTransfer.files)); }}
              >
                <h2>{t("emptyTitle")}</h2>
                <p>{t("emptyBody")}</p>
                <label className="file">
                  {t("dropHere")}
                  <input
                    type="file"
                    aria-label={t("dropHere")}
                    accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,application/pdf,image/*"
                    multiple
                    onChange={(event) => {
                      upload(Array.from(event.target.files || []));
                      event.target.value = "";
                    }}
                  />
                </label>
                <p className="quiet">{t("upTo", { max: maxMb })}</p>
              </div>
            ) : (
              <>
                <p className="explanation">{detail.explanation || ((detail.status === "processing" || detail.status === "queued") ? t("reading") : t("noExplanation"))}</p>
                {(detail.status === "queued" || detail.status === "processing") && (
                  <p className="progress" role="status"><span className="bar" aria-hidden="true" />{detail.progress || t("reading")}</p>
                )}
                {detail.error && <p className="error">{detail.error}</p>}
                {findOpen && (
                  <form className="find-bar" onSubmit={(event) => event.preventDefault()}>
                    <label className="sr" htmlFor="find">{t("find")}</label>
                    <input id="find" value={findQuery} autoFocus aria-label={t("find")} placeholder={t("find")} onChange={(event) => setFindQuery(event.target.value)} />
                  </form>
                )}
                <div className="toolbar">
                  <button type="button" className="ghost" onClick={() => setPageNumber(Math.max(1, (page?.number || 1) - 1))} disabled={!page || page.number <= 1}>{t("previous")}</button>
                  <span>{t("pageOf", { n: page?.number || 1, total: detail.page_count })}</span>
                  <button type="button" className="ghost" onClick={() => setPageNumber(Math.min(detail.page_count, (page?.number || 1) + 1))} disabled={!page || page.number >= detail.page_count}>{t("next")}</button>
                  <button type="button" className="ghost" aria-pressed={showBoxes} onClick={() => setShowBoxes((value) => !value)}>{showBoxes ? t("hideBoxes") : t("showBoxes")}</button>
                  {page?.ocr_engine && <span>{t("readWith", { engine: page.ocr_engine })}</span>}
                </div>
                <Viewer
                  imageUrl={imageUrl}
                  regions={regions}
                  activeId={activeRegion}
                  showBoxes={showBoxes}
                  onSelect={setActiveRegion}
                  find={findQuery}
                  labels={{ zoomIn: t("zoomIn"), zoomOut: t("zoomOut"), fit: t("fitPage"), empty: t("nothingOnPage") }}
                />
                <section className="transcript" aria-label={t("transcription")}>
                  <h2 className="pane-title">{t("transcription")}</h2>
                  {page?.translation && (
                    <p className="quiet">{t("translationPrefix")} ({page.translation_language}): {page.translation.slice(0, 280)}</p>
                  )}
                  {regions.length === 0 ? <p className="quiet">{page?.text || t("nothingOnPage")}</p> : (
                    <ol>
                      {regions.map((region) => {
                        const hit = Boolean(findQuery) && region.text.toLowerCase().includes(findQuery.toLowerCase());
                        return (
                          <li key={region.id} className={`${region.id === activeRegion ? "active" : ""} ${hit ? "hit" : ""}`}>
                            <button type="button" onClick={() => setActiveRegion(region.id)}>{region.text || t("empty")}</button>
                            {region.confidence > 0 && region.confidence < 0.6 && <span className="flag">{t("lowConfidence")}</span>}
                            {page?.flagged && region.idx === 0 && <span className="flag">{t("needsReview")}</span>}
                          </li>
                        );
                      })}
                    </ol>
                  )}
                </section>
              </>
            )}
          </main>
          <div
            className="resizer right"
            role="separator"
            aria-orientation="vertical"
            aria-label={t("resizeChat")}
            tabIndex={0}
            onPointerDown={(event) => beginResize("right", event)}
            onKeyDown={(event) => {
              if (event.key === "ArrowLeft") setRight((value) => clamp(value + 16, 240, 560));
              if (event.key === "ArrowRight") setRight((value) => clamp(value - 16, 240, 560));
            }}
          />
          <div className="slot slot-right">
            <div className="rail rail-right">
              <button type="button" onClick={() => setHideRight(false)}>{t("showChat")}</button>
            </div>
            <aside className="chat" aria-label={t("chat")}>
              <section>
                <div className="pane-head">
                  <h2 className="pane-title">{t("ask")}</h2>
                  <span className="row">
                    <Tip label={t("citationTip")} />
                    <button type="button" className="ghost" onClick={() => setHideRight(true)}>{t("hideChat")}</button>
                  </span>
                </div>
                <div className="thread" aria-live="polite">
                  {messages.length === 0 && <p className="quiet">{t("askEmpty")}</p>}
                  {messages.map((message) => (
                    <article key={message.id} className={`bubble ${message.role}`}>
                      <span className="who">{message.role === "user" ? t("you") : t("workbench")}</span>
                      <MessageText message={message} onCite={onCite} />
                    </article>
                  ))}
                </div>
                <form className="ask" onSubmit={ask}>
                  <label className="sr" htmlFor="question">{t("question")}</label>
                  <input id="question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={t("askPlaceholder")} />
                  <button className="primary" type="submit">{t("ask")}</button>
                </form>
              </section>
              <section className="notes">
                <h2 className="pane-title">{t("notes")}</h2>
                <ul>
                  {(detail?.notes || []).map((item) => (
                    <li key={item.id}>
                      <span>{item.body}</span>
                      <button type="button" className="ghost" onClick={() => removeNote(item.id)}>{t("delete")}</button>
                    </li>
                  ))}
                </ul>
                <form onSubmit={addNote}>
                  <label className="sr" htmlFor="note">{t("note")}</label>
                  <textarea id="note" value={note} onChange={(event) => setNote(event.target.value)} placeholder={t("notePlaceholder")} />
                  <button className="ghost" type="submit">{t("addNote")}</button>
                </form>
              </section>
              {selected && (
                <section>
                  <h2 className="pane-title">{t("export")}</h2>
                  <div className="exports">
                    {["docx", "md", "json", "bibtex", "tei", "pdf", "txt"].map((format) => (
                      <a key={format} href={`/api/documents/${selected}/export?format=${format}`}>{format.toUpperCase()}</a>
                    ))}
                  </div>
                  <form className="row" onSubmit={(event) => { event.preventDefault(); translate(); }} style={{ marginTop: 10 }}>
                    <label className="field" style={{ flex: 1 }}>
                      {t("translationLanguage")}
                      <input list="tr-langs" value={language} onChange={(event) => setLanguage(event.target.value)} aria-label={t("translationLanguage")} />
                    </label>
                    <datalist id="tr-langs">
                      {DOC_LANGS.filter((code) => code !== "en").map((code) => <option key={code} value={code} />)}
                    </datalist>
                    <button className="ghost" type="submit">{t("translate")}</button>
                  </form>
                  <button type="button" className="ghost" style={{ marginTop: 10 }} onClick={removeDoc}>{t("deleteDocument")}</button>
                </section>
              )}
            </aside>
          </div>
        </div>
      ) : view === "library" ? (
        <section className="library-search" aria-label={t("libraries")}>
          <h2 className="pane-title">{t("libraries")}</h2>
          <p className="quiet">{t("librariesHelp")}</p>
          <form onSubmit={runLibrary}>
            <label className="sr" htmlFor="q">{t("libraryQuery")}</label>
            <input id="q" type="search" value={query} aria-label={t("libraryQuery")} onChange={(event) => setQuery(event.target.value)} />
            <div className="sources">
              {SOURCES.map(([id, label]) => (
                <label key={id}>
                  <input
                    type="checkbox"
                    checked={picked.includes(id)}
                    onChange={(event) => {
                      setPicked((current) => event.target.checked ? [...current, id] : current.filter((item) => item !== id));
                    }}
                  /> {label}{(id === "europeana" || id === "dpla") ? ` (${t("needsKey")})` : ""}
                </label>
              ))}
            </div>
            <button className="primary" type="submit">{t("search")}</button>
          </form>
          {library && (
            <>
              <div className="chips">
                {library.map((block) => (
                  <span key={block.source} className={`chip${block.status === "ok" ? "" : " warn"}`}>
                    {block.source}: {block.status === "ok" ? `${block.hits.length}` : block.status === "not_configured" ? "not configured" : block.error || block.status}
                  </span>
                ))}
              </div>
              <ul className="results">
                {library.flatMap((block) => block.hits.map((hit) => (
                  <li key={`${hit.source}-${hit.url}-${hit.title}`}>
                    <article>
                      <h3><a href={hit.url} target="_blank" rel="noreferrer">{hit.title}</a></h3>
                      <p className="source-line">{hit.source}{hit.date ? ` · ${hit.date}` : ""}{hit.creators?.length ? ` · ${hit.creators.join(", ")}` : ""}</p>
                      {hit.description && <p>{hit.description.slice(0, 320)}</p>}
                    </article>
                  </li>
                )))}
              </ul>
            </>
          )}
        </section>
      ) : (
        <SettingsPanel onSaved={setSettings} />
      )}

      {searchOpen && (
        <div className="modal" onMouseDown={() => setSearchOpen(false)}>
          <div
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-label={t("documentSearch")}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <p className="quiet">{t("yourDocumentsNote")}</p>
            <form onSubmit={(event) => event.preventDefault()}>
              <label className="sr" htmlFor="doc-search">{t("documentSearch")}</label>
              <input
                id="doc-search"
                className="search-field"
                type="search"
                autoFocus
                role="searchbox"
                aria-label={t("documentSearch")}
                placeholder={t("searchPlaceholder")}
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </form>
            <div className="filters">
              <label className="field">
                {t("collection")}
                <input value={filterCollection} onChange={(event) => setFilterCollection(event.target.value)} />
              </label>
              <label className="field">
                {t("docLanguage")}
                <input value={filterLanguage} placeholder={t("anyLanguage")} onChange={(event) => setFilterLanguage(event.target.value)} />
              </label>
              <label className="field">
                {t("dateUploaded")}
                <select aria-label={t("dateUploaded")} value={filterWhen} onChange={(event) => setFilterWhen(event.target.value)}>
                  <option value="">{t("anyTime")}</option>
                  <option value="week">{t("pastWeek")}</option>
                  <option value="month">{t("pastMonth")}</option>
                </select>
              </label>
              <label className="field">
                {t("engine")}
                <select aria-label={t("engine")} value={filterEngine} onChange={(event) => setFilterEngine(event.target.value)}>
                  <option value="">{t("anyEngine")}</option>
                  <option value="tesseract">Tesseract</option>
                  <option value="ppocr">PP-OCR</option>
                  <option value="claude">Claude</option>
                  <option value="gemini">Gemini</option>
                </select>
              </label>
            </div>
            {searchHits && searchHits.length === 0 && <p className="quiet">{t("noMatches")}</p>}
            {searchHits && searchHits.length > 0 && (
              <ul className="hit-list">
                {searchHits.map((hit, index) => (
                  <li key={`${hit.document_id}-${hit.kind}-${hit.page}-${index}`}>
                    <button type="button" className="hit-card" onClick={() => openHit(hit)}>
                      <h3>{hit.title || hit.filename}</h3>
                      <p className="hit-meta">{kindLabel(hit.kind)}{hit.page ? ` · ${hit.page}` : ""}</p>
                      <p dangerouslySetInnerHTML={{ __html: hit.snippet }} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p style={{ marginTop: 12 }}><button type="button" className="ghost" onClick={() => setSearchOpen(false)}>{t("close")}</button></p>
          </div>
        </div>
      )}

      {showOnboarding && (
        <div className="modal" onMouseDown={dismissOnboarding}>
          <div className="modal-card onboard" role="dialog" aria-modal="true" aria-label={t("gettingStarted")} onMouseDown={(event) => event.stopPropagation()}>
            <h2>{t("gettingStarted")}</h2>
            <ol>
              <li>{t("stepUpload")}</li>
              <li>{t("stepOcr")}</li>
              <li>{t("stepAsk")}</li>
              <li>{t("stepExport")}</li>
            </ol>
            <button type="button" className="primary" onClick={dismissOnboarding}>{t("gotIt")}</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Tip({ label }: { label: string }) {
  return (
    <span className="tip">
      <button type="button" className="tip-btn" aria-label={label}>?</button>
      <span role="tooltip" className="tip-pop">{label}</span>
    </span>
  );
}

function MessageText({ message, onCite }: { message: ChatMessage; onCite: (citation: Citation) => void }) {
  const parts = message.content.split(/(\[\d+\])/g);
  return (
    <p>
      {parts.map((part, index) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (!match) return <span key={index}>{part}</span>;
        const citation = (message.citations || []).find((item) => item.n === Number(match[1]));
        if (!citation) return <span key={index}>{part}</span>;
        if (citation.kind === "document") {
          return (
            <button key={index} type="button" className="cite" onClick={() => onCite(citation)}>
              {part}
            </button>
          );
        }
        return (
          <a key={index} className="cite" href={citation.url} target="_blank" rel="noreferrer">
            {part}
          </a>
        );
      })}
    </p>
  );
}
