import { expect, test, type Page } from "@playwright/test";

async function dismiss(page: Page) {
  const start = page.getByRole("button", { name: "Got it" });
  if (await start.isVisible().catch(() => false)) await start.click();
}

async function expectFits(page: Page) {
  const box = await page.evaluate(() => {
    const root = document.documentElement;
    const chat = document.querySelector(".chat");
    const ask = document.querySelector("#question");
    const chatBox = chat?.getBoundingClientRect();
    const askBox = ask?.getBoundingClientRect();
    return {
      scroll: root.scrollWidth,
      client: root.clientWidth,
      chatRight: chatBox ? chatBox.right : 0,
      askRight: askBox ? askBox.right : 0,
      chatLeft: chatBox ? chatBox.left : 0,
    };
  });
  expect(box.scroll).toBeLessThanOrEqual(box.client + 1);
  expect(box.chatRight).toBeLessThanOrEqual(box.client + 1);
  expect(box.askRight).toBeLessThanOrEqual(box.client + 1);
  expect(box.chatLeft).toBeGreaterThanOrEqual(-1);
}

test("laptop widths keep the three panes inside the window", async ({ page }) => {
  test.setTimeout(60_000);
  await page.addInitScript(() => localStorage.setItem("aw-onboarded", "1"));
  for (const width of [1280, 1366, 1440]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto("/");
    await expect(page.getByRole("complementary", { name: "Chat and notes" })).toBeVisible();
    await expect(page.getByText("Select a document.")).toHaveCount(0);
    const empty = page.getByRole("heading", { name: "Drop a scan or PDF here" });
    if (await empty.count()) await expect(empty).toBeVisible();
    await expectFits(page);
    const lang = page.locator("header select");
    await lang.selectOption("hi");
    await expect(page.locator("html")).toHaveAttribute("lang", "hi");
    await expectFits(page);
    await lang.selectOption("en");
  }
});

test("127.0.0.1 page loads redirect to localhost and the API does not", async ({ page, request }) => {
  const base = new URL(process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3000");
  const port = base.port || "3000";
  await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "commit" }).catch(() => {});
  await page.waitForURL((url) => url.hostname === "localhost");
  expect(new URL(page.url()).hostname).toBe("localhost");
  const health = await request.get(`http://127.0.0.1:${port}/api/health`, { maxRedirects: 0 });
  expect(health.status()).toBe(200);
  const body = await health.json();
  expect(body.max_file_mb).toBeGreaterThanOrEqual(500);
});

test("a rejected upload names the file and the reason", async ({ page, request }) => {
  await page.addInitScript(() => localStorage.setItem("aw-onboarded", "1"));
  await page.goto("/");
  await dismiss(page);
  await page.getByLabel("Upload a scan or PDF").setInputFiles({
    name: "not-a-scan.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("not a pdf"),
  });
  const banner = page.locator(".banner");
  await expect(banner).toContainText("not-a-scan.pdf");
  await expect(banner).toContainText("unsupported or corrupt file type");
  const listed = await request.get("/api/documents");
  if (listed.ok()) {
    const docs = await listed.json() as { id: string; filename: string }[];
    for (const doc of docs) {
      if (doc.filename === "not-a-scan.pdf") await request.delete(`/api/documents/${doc.id}`);
    }
  }
});
