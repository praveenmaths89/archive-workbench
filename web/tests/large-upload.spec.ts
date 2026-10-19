import { expect, test, type APIRequestContext } from "@playwright/test";

function bigPdf(streamBytes: number): Buffer {
  const header = "%PDF-1.4\n";
  const objects = [
    "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
    "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
    "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>\nendobj\n",
    `4 0 obj\n<< /Length ${streamBytes} >>\nstream\n`,
  ];
  const chunks: Buffer[] = [Buffer.from(header)];
  const starts = [0, 0, 0, 0, 0];
  for (let i = 0; i < objects.length; i += 1) {
    starts[i + 1] = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    chunks.push(Buffer.from(objects[i]));
  }
  chunks.push(Buffer.alloc(streamBytes, 0x20));
  chunks.push(Buffer.from("\nendstream\nendobj\n"));
  const bodyLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  let xref = "xref\n0 5\n0000000000 65535 f \n";
  for (let i = 1; i <= 4; i += 1) xref += `${String(starts[i]).padStart(10, "0")} 00000 n \n`;
  xref += `trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n${bodyLength}\n%%EOF\n`;
  chunks.push(Buffer.from(xref));
  return Buffer.concat(chunks);
}

async function removeNamed(request: APIRequestContext, filename: string) {
  const listed = await request.get("/api/documents");
  if (!listed.ok()) return;
  const docs = await listed.json() as { id: string; filename: string }[];
  for (const doc of docs) {
    if (doc.filename === filename) await request.delete(`/api/documents/${doc.id}`);
  }
}

test("uploads a file larger than 10MB through the web app", async ({ request }) => {
  test.setTimeout(90_000);
  const filename = "wide-scan.pdf";
  const pdf = bigPdf(11 * 1024 * 1024);
  expect(pdf.length).toBeGreaterThan(10 * 1024 * 1024);
  let id = "";
  try {
    const response = await request.post("/api/documents", {
      multipart: {
        files: { name: filename, mimeType: "application/pdf", buffer: pdf },
        options: "{}",
      },
      timeout: 60_000,
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    const payload = await response.json();
    const doc = payload.documents?.[0];
    id = doc?.id || "";
    expect(doc?.status, doc?.error).toBe("queued");
    expect(doc?.total_pages).toBe(1);
  } finally {
    if (id) await request.delete(`/api/documents/${id}`);
    else await removeNamed(request, filename);
  }
});
