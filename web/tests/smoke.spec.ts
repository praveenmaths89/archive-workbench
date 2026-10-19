import { expect, test } from "@playwright/test";

test("workspace search, Hindi, and dark mode", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Archive Workbench" })).toBeVisible();
  const start = page.getByRole("button", { name: "Got it" });
  await start.waitFor({ state: "visible" });
  await start.click();

  await expect(page.getByRole("navigation", { name: "Documents" })).toBeVisible();
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Chat and notes" })).toBeVisible();
  await expect(page.getByLabel("Upload a scan or PDF")).toBeVisible();

  await page.getByRole("button", { name: "Search open libraries" }).click();
  await expect(page.getByRole("searchbox", { name: "Library query" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Internet Archive" })).toBeChecked();

  await page.getByRole("button", { name: "Workspace" }).click();
  await page.getByRole("button", { name: "Search your documents" }).click();
  const search = page.getByRole("searchbox", { name: "Document search" });
  await expect(search).toBeVisible();
  await search.fill("minute");
  await page.keyboard.press("Escape");
  await expect(search).toBeHidden();

  await page.getByRole("button", { name: "Dark mode" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  await page.getByLabel("Interface language").selectOption("hi");
  await expect(page.locator("html")).toHaveAttribute("lang", "hi");
  await expect(page.getByRole("navigation", { name: "दस्तावेज़" })).toBeVisible();
});
