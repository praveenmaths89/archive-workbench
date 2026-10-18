"use client";

import dynamic from "next/dynamic";
import { FormEvent, useEffect, useMemo, useState } from "react";
import type { Region } from "./Viewer";

const Viewer = dynamic(() => import("./Viewer"), { ssr: false });

type DocSummary = {
  id: string;
  filename: string;
  status: string;
  page_count: number;
  error?: string | null;
  explanation?: string | null;
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
type Citation = {
  n: number;
  kind: string;
  page?: number;
  region_id?: string | null;
  url?: string;
  title?: string;
};
type ChatMessage = { id: string; role: string; content: string; citations: Citation[] };
type Detail = DocSummary & { pages: PageInfo[]; regions: RegionInfo[]; notes: Note[]; jobs: { id: string; kind: string; status: string }[] };

type Hit = { title: string; url: string; creators: string[]; date?: string | null; description: string; source: string };
type SourceBlock = { source: string; status: string; error?: string | null; hits: Hit[] };

const STATUS: Record<string, string> = {
  queued: "Queued",
  processing: "Reading",
  done: "Done",
  done_with_errors: "Done, with errors",
  failed: "Failed",
  rejected: "Rejected",
  stopped: "Stopped",
  pending: "Waiting",
  skipped: "Not read",
};

const SOURCES = [
  ["internet_archive", "Internet Archive"],
  ["loc", "Library of Congress"],
  ["wikidata", "Wikidata"],
  ["openalex", "OpenAlex"],
  ["gallica", "Gallica"],
  ["europeana", "Europeana (needs a key)"],
  ["dpla", "DPLA (needs a key)"],
] as const;

function statusLabel(status: string) {
  return STATUS[status] || status;
}

export default function Workspace() {
  const [view, setView] = useState<"workspace" | "library">("workspace");
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
  const [dragOver, setDragOver] = useState(false);
  const [query, setQuery] = useState("Kittur");
  const [picked, setPicked] = useState<string[]>(["internet_archive", "loc", "wikidata", "openalex", "gallica"]);
  const [library, setLibrary] = useState<SourceBlock[] | null>(null);

  async function refreshList() {
    const response = await fetch("/api/documents");
    if (!response.ok) throw new Error("Could not load documents");
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

  useEffect(() => {
    let stop = false;
    async function tick() {
      try {
        const rows = await refreshList();
        if (stop) return;
        const id = selected && rows.some((row) => row.id === selected) ? selected : rows[0]?.id;
        if (id && id !== selected) setSelected(id);
        if (id) await refreshDetail(id);
        if (!stop) setError("");
      } catch {
        if (!stop) setError("The API is not reachable. If you just started the stack, wait a moment and reload.");
      }
    }
    tick();
    const timer = setInterval(tick, 2500);
    return () => { stop = true; clearInterval(timer); };
  }, [selected]);

  const page = detail?.pages?.find((item) => item.number === pageNumber) || detail?.pages?.[0];
  const regions = useMemo(
    () => (detail?.regions || []).filter((region) => region.page_number === (page?.number || pageNumber)).sort((a, b) => a.idx - b.idx),
    [detail, page, pageNumber],
  );

  async function upload(files: File[]) {
    if (!files.length) return;
    setBusy("Uploading");
    const body = new FormData();
    for (const file of files) body.append("files", file);
    const options: { pages?: string } = {};
    if (pageRange.trim()) options.pages = pageRange.trim();
    body.append("options", JSON.stringify(options));
    const response = await fetch("/api/documents", { method: "POST", body });
    setBusy("");
    if (!response.ok) {
      setError("Upload failed.");
      return;
    }
    const payload = await response.json();
    const queued = (payload.documents || []).find((row: { status: string; id: string }) => row.status === "queued");
    if (queued) setSelected(queued.id);
    await refreshList();
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!selected || !question.trim()) return;
    setBusy("Asking");
    const response = await fetch(`/api/documents/${selected}/ask`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question }),
    });
    setBusy("");
    if (response.status === 409) {
      setError("Wait until reading finishes, then ask again.");
      return;
    }
    if (!response.ok) {
      setError("Could not ask that question.");
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
    setBusy("Translating");
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

  function onCite(citation: Citation) {
    if (citation.kind !== "document") return;
    if (citation.page) setPageNumber(citation.page);
    if (citation.region_id) setActiveRegion(citation.region_id);
  }

  async function runLibrary(event: FormEvent) {
    event.preventDefault();
    setBusy("Searching");
    const response = await fetch(`/api/library/search?q=${encodeURIComponent(query)}&sources=${picked.join(",")}`);
    setBusy("");
    if (!response.ok) {
      setError("Library search failed.");
      return;
    }
    const payload = await response.json();
    setLibrary(payload.sources);
  }

  const imageUrl = selected && page ? `/api/documents/${selected}/pages/${page.number}/image` : null;

  return (
    <div className="app">
      <a className="skip" href="#viewer">Skip to page</a>
      <header className="top">
        <h1>Archive Workbench</h1>
        <nav className="views" aria-label="Views">
          <button type="button" aria-current={view === "workspace" ? "page" : undefined} onClick={() => setView("workspace")}>Workspace</button>
          <button type="button" aria-current={view === "library" ? "page" : undefined} onClick={() => setView("library")}>Library search</button>
        </nav>
        {busy && <span className="quiet">{busy}</span>}
      </header>
      {error && <p className="error" role="alert" style={{ margin: "8px 18px" }}>{error}</p>}

      {view === "workspace" ? (
        <div className="workspace">
          <nav className="library" aria-label="Documents">
            <h2 className="pane-title">Documents</h2>
            <form
              className={`drop${dragOver ? " over" : ""}`}
              onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(event) => { event.preventDefault(); setDragOver(false); upload(Array.from(event.dataTransfer.files)); }}
            >
              <label className="file">
                Upload a scan or PDF
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
              <label>
                Pages
                <input value={pageRange} onChange={(event) => setPageRange(event.target.value)} placeholder="all, or 1-3, 5" />
              </label>
            </form>
            {docs.length === 0 ? (
              <p className="quiet">No documents yet. Upload a scan or PDF to start.</p>
            ) : (
              <ul className="doc-list">
                {docs.map((doc) => (
                  <li key={doc.id}>
                    <button type="button" className={doc.id === selected ? "selected" : ""} onClick={() => { setSelected(doc.id); setPageNumber(1); setActiveRegion(null); }}>
                      <span className="doc-name">{doc.filename}</span>
                      <span className={`doc-meta status-${doc.status}`}>{statusLabel(doc.status)} · {doc.page_count} page{doc.page_count === 1 ? "" : "s"}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <p className="privacy">Documents stay on this machine. API keys stay in the environment file.</p>
          </nav>

          <main className="page-pane" id="viewer">
            {!detail ? (
              <p className="quiet">Select a document.</p>
            ) : (
              <>
                <p className="explanation">{detail.explanation || (detail.status === "processing" || detail.status === "queued" ? "Reading the pages…" : "No explanation yet.")}</p>
                {detail.error && <p className="error">{detail.error}</p>}
                <div className="toolbar">
                  <button type="button" className="ghost" onClick={() => setPageNumber(Math.max(1, (page?.number || 1) - 1))} disabled={!page || page.number <= 1}>Previous page</button>
                  <span>Page {page?.number || 1} of {detail.page_count}</span>
                  <button type="button" className="ghost" onClick={() => setPageNumber(Math.min(detail.page_count, (page?.number || 1) + 1))} disabled={!page || page.number >= detail.page_count}>Next page</button>
                  <button type="button" className="ghost" aria-pressed={showBoxes} onClick={() => setShowBoxes((value) => !value)}>{showBoxes ? "Hide boxes" : "Show boxes"}</button>
                  {page?.ocr_engine && <span>Read with {page.ocr_engine}</span>}
                </div>
                <Viewer
                  imageUrl={imageUrl}
                  regions={regions}
                  activeId={activeRegion}
                  showBoxes={showBoxes}
                  onSelect={setActiveRegion}
                />
                <section className="transcript" aria-label="Transcription">
                  <h2 className="pane-title">Transcription</h2>
                  {page?.translation && (
                    <p className="quiet">Translation ({page.translation_language}): {page.translation.slice(0, 280)}</p>
                  )}
                  {regions.length === 0 ? <p className="quiet">{page?.text || "Nothing transcribed on this page yet."}</p> : (
                    <ol>
                      {regions.map((region) => (
                        <li key={region.id} className={region.id === activeRegion ? "active" : ""}>
                          <button type="button" onClick={() => setActiveRegion(region.id)}>{region.text || "(empty)"}</button>
                          {region.confidence > 0 && region.confidence < 0.6 && <span className="flag">low confidence</span>}
                          {page?.flagged && region.idx === 0 && <span className="flag">needs review</span>}
                        </li>
                      ))}
                    </ol>
                  )}
                </section>
              </>
            )}
          </main>

          <aside className="chat" aria-label="Chat and notes">
            <section>
              <h2 className="pane-title">Ask</h2>
              <div className="thread" aria-live="polite">
                {messages.length === 0 && <p className="quiet">Ask about this document. Answers cite a page region, and a library source when one was retrieved.</p>}
                {messages.map((message) => (
                  <article key={message.id} className={`bubble ${message.role}`}>
                    <span className="who">{message.role === "user" ? "You" : "Workbench"}</span>
                    <MessageText message={message} onCite={onCite} />
                  </article>
                ))}
              </div>
              <form className="ask" onSubmit={ask}>
                <label className="sr" htmlFor="question">Question</label>
                <input id="question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What is this document about?" />
                <button className="primary" type="submit">Ask</button>
              </form>
            </section>
            <section className="notes">
              <h2 className="pane-title">Notes</h2>
              <ul>
                {(detail?.notes || []).map((item) => (
                  <li key={item.id}>
                    <span>{item.body}</span>
                    <button type="button" className="ghost" onClick={() => removeNote(item.id)}>Delete</button>
                  </li>
                ))}
              </ul>
              <form onSubmit={addNote}>
                <label className="sr" htmlFor="note">Note</label>
                <textarea id="note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="A note on this document" />
                <button className="ghost" type="submit">Add note</button>
              </form>
            </section>
            {selected && (
              <section>
                <h2 className="pane-title">Export and tools</h2>
                <div className="exports">
                  {["docx", "md", "json", "bibtex", "tei", "pdf", "txt"].map((format) => (
                    <a key={format} href={`/api/documents/${selected}/export?format=${format}`}>{format.toUpperCase()}</a>
                  ))}
                </div>
                <form className="row" onSubmit={(event) => { event.preventDefault(); translate(); }} style={{ marginTop: 10 }}>
                  <label className="sr" htmlFor="lang">Translation language</label>
                  <input id="lang" value={language} onChange={(event) => setLanguage(event.target.value)} aria-label="Translation language" />
                  <button className="ghost" type="submit">Translate</button>
                </form>
                <button type="button" className="ghost" style={{ marginTop: 10 }} onClick={removeDoc}>Delete document</button>
              </section>
            )}
          </aside>
        </div>
      ) : (
        <section className="library-search" aria-label="Library search">
          <h2 className="pane-title">Open libraries</h2>
          <p className="quiet">Search sends the query only, not your documents. Europeana and DPLA stay quiet until a key is set.</p>
          <form onSubmit={runLibrary}>
            <label className="sr" htmlFor="q">Library query</label>
            <input id="q" type="search" role="searchbox" value={query} onChange={(event) => setQuery(event.target.value)} />
            <div className="sources">
              {SOURCES.map(([id, label]) => (
                <label key={id}>
                  <input
                    type="checkbox"
                    checked={picked.includes(id)}
                    onChange={(event) => {
                      setPicked((current) => event.target.checked ? [...current, id] : current.filter((item) => item !== id));
                    }}
                  /> {label}
                </label>
              ))}
            </div>
            <button className="primary" type="submit">Search</button>
          </form>
          {library && (
            <>
              <div className="chips">
                {library.map((block) => (
                  <span key={block.source} className={`chip${block.status === "ok" ? "" : " warn"}`}>
                    {block.source}: {block.status === "ok" ? `${block.hits.length} hits` : block.status === "not_configured" ? "not configured" : block.error || block.status}
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
      )}
    </div>
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
