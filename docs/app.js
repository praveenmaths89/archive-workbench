"use strict";

const LIMITS = { files: 3, bytes: 8 * 1024 * 1024, pages: 5, edge: 1600 };
const docs = [];
let active = -1;
let pageIndex = 0;
let busy = false;
let editing = false;
let worker = null;
let workerLang = "";

const $ = (id) => document.getElementById(id);
const statusEl = $("status");

function asset(path) {
  return new URL(path, document.baseURI).href;
}

function setStatus(message, bad) {
  statusEl.textContent = message || "";
  statusEl.className = bad ? "bad" : "";
}

function stem(name) {
  const base = String(name || "document").split(/[/\\]/).pop().replace(/[^A-Za-z0-9._-]+/g, "_");
  const dot = base.lastIndexOf(".");
  const raw = (dot > 0 ? base.slice(0, dot) : base).slice(0, 80);
  return raw || "document";
}

function sniff(bytes) {
  if (bytes.length >= 5 && bytes[0] === 0x25 && bytes[1] === 0x50 && bytes[2] === 0x44 && bytes[3] === 0x46) return "pdf";
  if (bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) return "image";
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "image";
  if (bytes.length >= 12 && bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 &&
      bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50) return "image";
  if (bytes.length >= 4 && ((bytes[0] === 0x49 && bytes[1] === 0x49) || (bytes[0] === 0x4d && bytes[1] === 0x4d))) return "tiff";
  return "";
}

function canvasBlob(canvas) {
  return new Promise((resolve) => canvas.toBlob((blob) => resolve(blob), "image/jpeg", 0.85));
}

function fitCanvas(width, height) {
  const edge = Math.max(width, height);
  const scale = edge > LIMITS.edge ? LIMITS.edge / edge : 1;
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  return { canvas, scale };
}

async function recognize(canvas, lang, psm) {
  if (!worker || workerLang !== lang) {
    if (worker) await worker.terminate();
    worker = null;
    workerLang = "";
    setStatus("Loading the OCR engine for this language. The page stays on this device.");
    worker = await Tesseract.createWorker(lang, 1, {
      workerPath: asset("vendor/tesseract/worker.min.js"),
      corePath: asset("vendor/tesseract/tesseract-core-simd-lstm.wasm.js"),
      langPath: asset("vendor/tessdata"),
      workerBlobURL: false,
      cacheMethod: "none",
      gzip: true,
    });
    workerLang = lang;
  }
  await worker.setParameters({ tessedit_pageseg_mode: psm || "6" });
  setStatus("Reading the page…");
  const result = await worker.recognize(canvas);
  const text = (result.data.text || "").trim();
  const confidence = Math.round((result.data.confidence || 0)) / 100;
  return { text, confidence };
}

async function pagesFromPdf(bytes) {
  const pdf = await pdfjsLib.getDocument({ data: bytes, disableWorker: true, isEvalSupported: false }).promise;
  const total = pdf.numPages;
  const count = Math.min(total, LIMITS.pages);
  const pages = [];
  for (let n = 1; n <= count; n += 1) {
    const page = await pdf.getPage(n);
    const content = await page.getTextContent();
    const text = content.items.map((item) => item.str).join(" ").replace(/\s+/g, " ").trim();
    const base = page.getViewport({ scale: 1 });
    const sized = fitCanvas(base.width * 2, base.height * 2);
    const viewport = page.getViewport({ scale: sized.scale * 2 });
    sized.canvas.width = Math.round(viewport.width);
    sized.canvas.height = Math.round(viewport.height);
    const ctx = sized.canvas.getContext("2d", { alpha: false });
    await page.render({ canvasContext: ctx, viewport }).promise;
    const blob = await canvasBlob(sized.canvas);
    const usable = text.length >= 40;
    pages.push({
      number: n,
      source: usable ? "text layer" : "tesseract",
      text: usable ? text : "",
      confidence: usable ? 1 : 0,
      imageUrl: URL.createObjectURL(blob),
      canvas: usable ? null : sized.canvas,
      edited: false,
    });
  }
  return { pages, note: total > count ? `Only the first ${count} of ${total} pages were read.` : "" };
}

async function pagesFromImage(file, bytes) {
  const bitmap = await createImageBitmap(new Blob([bytes], { type: file.type || "image/jpeg" }));
  if (bitmap.width * bitmap.height > 25000000) {
    bitmap.close();
    throw new Error("image is too large");
  }
  const sized = fitCanvas(bitmap.width, bitmap.height);
  const ctx = sized.canvas.getContext("2d", { alpha: false });
  ctx.drawImage(bitmap, 0, 0, sized.canvas.width, sized.canvas.height);
  bitmap.close();
  const blob = await canvasBlob(sized.canvas);
  return {
    pages: [{
      number: 1,
      source: "tesseract",
      text: "",
      confidence: 0,
      imageUrl: URL.createObjectURL(blob),
      canvas: sized.canvas,
      edited: false,
    }],
    note: "",
  };
}

async function transcribe(doc) {
  const lang = $("lang").value;
  for (const page of doc.pages) {
    if (page.source !== "tesseract" || page.text) continue;
    const psm = doc.psm || "6";
    const read = await recognize(page.canvas, lang, psm);
    page.text = read.text;
    page.confidence = read.confidence;
    page.canvas = null;
    render();
  }
}

async function addFiles(fileList, extra) {
  if (busy) return;
  const files = [...fileList];
  if (!files.length) return;
  if (docs.length + files.length > LIMITS.files) {
    setStatus(`Up to ${LIMITS.files} documents at a time. Remove one to add another.`, true);
    return;
  }
  busy = true;
  try {
    for (const file of files) {
      if (file.size > LIMITS.bytes) {
        setStatus(`${file.name} is over ${LIMITS.bytes / 1024 / 1024} MB and was skipped.`, true);
        continue;
      }
      const bytes = new Uint8Array(await file.arrayBuffer());
      const kind = sniff(bytes);
      if (kind === "tiff") {
        setStatus("TIFF is not decoded in this browser edition. Export a PNG, JPEG, or PDF and try again.", true);
        continue;
      }
      if (!kind) {
        setStatus(`${file.name} is not a PDF, PNG, JPEG, or WebP file.`, true);
        continue;
      }
      setStatus(`Opening ${file.name}…`);
      let built;
      try {
        built = kind === "pdf" ? await pagesFromPdf(bytes) : await pagesFromImage(file, bytes);
      } catch (err) {
        const name = err && err.name === "PasswordException" ? "This PDF is password-protected and was not opened." : "This file could not be opened.";
        setStatus(name, true);
        continue;
      }
      const doc = { id: crypto.randomUUID(), name: file.name, pages: built.pages, note: built.note, psm: extra && extra.psm };
      docs.push(doc);
      active = docs.length - 1;
      pageIndex = 0;
      render();
      await transcribe(doc);
      if (doc.note) setStatus(doc.note);
      else setStatus("");
      render();
    }
  } catch (err) {
    setStatus(err && err.message ? err.message : "The page could not be read.", true);
  } finally {
    busy = false;
    render();
  }
}

function renderList() {
  const list = $("list");
  list.replaceChildren();
  docs.forEach((doc, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "doc" + (index === active ? " on" : "");
    const title = document.createElement("b");
    title.textContent = doc.name;
    const meta = document.createElement("span");
    meta.className = "sm";
    const done = doc.pages.filter((p) => p.text || p.source === "text layer").length;
    meta.textContent = `${done}/${doc.pages.length} pages`;
    button.append(title, meta);
    button.addEventListener("click", () => {
      active = index;
      pageIndex = 0;
      editing = false;
      render();
    });
    list.append(button);
  });
}

function downloadButtons(doc) {
  const box = $("downloads");
  box.replaceChildren();
  [["txt", "TXT"], ["md", "Markdown"], ["json", "JSON"], ["docx", "DOCX"]].forEach(([fmt, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => download(doc, fmt));
    box.append(button);
  });
}

function renderPage(doc) {
  const page = doc.pages[pageIndex];
  $("img").src = page.imageUrl;
  const box = $("text");
  box.replaceChildren();
  const bar = document.createElement("div");
  bar.className = "pager";
  const prev = document.createElement("button");
  prev.type = "button";
  prev.textContent = "←";
  prev.disabled = pageIndex === 0;
  prev.addEventListener("click", () => { pageIndex -= 1; editing = false; render(); });
  const label = document.createElement("b");
  label.textContent = `Page ${page.number} / ${doc.pages.length}`;
  const next = document.createElement("button");
  next.type = "button";
  next.textContent = "→";
  next.disabled = pageIndex >= doc.pages.length - 1;
  next.addEventListener("click", () => { pageIndex += 1; editing = false; render(); });
  const source = document.createElement("span");
  source.className = "chip";
  source.textContent = page.edited ? "edited" : page.source;
  bar.append(prev, label, next, source);
  const edit = document.createElement("button");
  edit.type = "button";
  edit.textContent = editing ? "Cancel" : "Edit text";
  edit.addEventListener("click", () => { editing = !editing; render(); });
  bar.append(edit);
  box.append(bar);
  if (editing) {
    const area = document.createElement("textarea");
    area.className = "edit";
    area.value = page.text;
    const save = document.createElement("button");
    save.type = "button";
    save.className = "primary";
    save.textContent = "Save";
    save.addEventListener("click", () => {
      page.text = area.value;
      page.edited = true;
      editing = false;
      render();
    });
    box.append(area, save);
    return;
  }
  const pre = document.createElement("pre");
  pre.textContent = page.text || (busy ? "Reading…" : "No text on this page.");
  box.append(pre);
}

function render() {
  renderList();
  const doc = docs[active];
  $("empty").style.display = doc ? "none" : "";
  $("work").classList.toggle("on", !!doc);
  if (!doc) return;
  if (pageIndex >= doc.pages.length) pageIndex = 0;
  $("title").textContent = doc.name;
  downloadButtons(doc);
  renderPage(doc);
}

function bodyText(doc) {
  return doc.pages.map((p) => `--- Page ${p.number} ---\n${p.text || ""}`).join("\n\n");
}

function markdown(doc) {
  return doc.pages.map((p) => `## Page ${p.number}\n\n${p.text || ""}`).join("\n\n");
}

function xml(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function crc32(bytes) {
  let c = -1;
  for (let i = 0; i < bytes.length; i += 1) {
    c ^= bytes[i];
    for (let k = 0; k < 8; k += 1) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
  }
  return (c ^ -1) >>> 0;
}

function concat(chunks) {
  const size = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const out = new Uint8Array(size);
  let offset = 0;
  chunks.forEach((chunk) => { out.set(chunk, offset); offset += chunk.length; });
  return out;
}

function zipStore(files) {
  const enc = new TextEncoder();
  const parts = [];
  const central = [];
  let offset = 0;
  files.forEach(([name, data]) => {
    const nameBytes = enc.encode(name);
    const crc = crc32(data);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);
    local.setUint16(6, 0x0800, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, data.length, true);
    local.setUint16(26, nameBytes.length, true);
    parts.push(new Uint8Array(local.buffer), nameBytes, data);
    const cen = new DataView(new ArrayBuffer(46));
    cen.setUint32(0, 0x02014b50, true);
    cen.setUint16(4, 20, true);
    cen.setUint16(6, 20, true);
    cen.setUint16(8, 0x0800, true);
    cen.setUint32(16, crc, true);
    cen.setUint32(20, data.length, true);
    cen.setUint32(24, data.length, true);
    cen.setUint16(28, nameBytes.length, true);
    cen.setUint32(42, offset, true);
    central.push(new Uint8Array(cen.buffer), nameBytes);
    offset += 30 + nameBytes.length + data.length;
  });
  const centralBytes = concat(central);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, centralBytes.length, true);
  end.setUint32(16, offset, true);
  return concat([...parts, centralBytes, new Uint8Array(end.buffer)]);
}

function docxBytes(doc) {
  const enc = new TextEncoder();
  const paragraphs = bodyText(doc).split("\n").map((line) => (
    `<w:p><w:r><w:t xml:space="preserve">${xml(line)}</w:t></w:r></w:p>`
  )).join("");
  const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${paragraphs}</w:body></w:document>`;
  const types = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>`;
  const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`;
  const wordRels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>`;
  return zipStore([
    ["[Content_Types].xml", enc.encode(types)],
    ["_rels/.rels", enc.encode(rels)],
    ["word/document.xml", enc.encode(documentXml)],
    ["word/_rels/document.xml.rels", enc.encode(wordRels)],
  ]);
}

function download(doc, fmt) {
  const name = stem(doc.name);
  let blob;
  if (fmt === "txt") blob = new Blob([bodyText(doc)], { type: "text/plain;charset=utf-8" });
  else if (fmt === "md") blob = new Blob([markdown(doc)], { type: "text/markdown;charset=utf-8" });
  else if (fmt === "json") {
    const payload = {
      filename: doc.name,
      pages: doc.pages.map((p) => ({ number: p.number, source: p.source, confidence: p.confidence, edited: p.edited, text: p.text })),
    };
    blob = new Blob([JSON.stringify(payload, null, 1)], { type: "application/json" });
  } else blob = new Blob([docxBytes(doc)], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${name}.${fmt}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 4000);
}

async function sample() {
  const canvas = document.createElement("canvas");
  canvas.width = 1600;
  canvas.height = 480;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#111111";
  ctx.font = "80px sans-serif";
  ctx.fillText("Kittur fort 1824", 90, 260);
  const blob = await canvasBlob(canvas);
  const file = new File([blob], "sample-page.png", { type: "image/png" });
  await addFiles([file], { psm: "7" });
}

const drop = $("drop");
const input = $("file");
drop.addEventListener("click", () => input.click());
drop.addEventListener("keydown", (event) => { if (event.key === "Enter") input.click(); });
drop.addEventListener("dragover", (event) => { event.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (event) => {
  event.preventDefault();
  drop.classList.remove("over");
  addFiles(event.dataTransfer.files);
});
input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
$("sample").addEventListener("click", sample);
$("remove").addEventListener("click", () => {
  const doc = docs[active];
  if (!doc) return;
  doc.pages.forEach((p) => URL.revokeObjectURL(p.imageUrl));
  docs.splice(active, 1);
  active = docs.length ? Math.min(active, docs.length - 1) : -1;
  pageIndex = 0;
  editing = false;
  render();
});
document.addEventListener("keydown", (event) => {
  if (editing || event.target.matches("input, textarea, select") || active < 0) return;
  const doc = docs[active];
  if (event.key === "ArrowRight" && pageIndex < doc.pages.length - 1) { pageIndex += 1; render(); }
  if (event.key === "ArrowLeft" && pageIndex > 0) { pageIndex -= 1; render(); }
});
