import { expect, test } from "@playwright/test";

test("workspace shows the three panes and library search", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Archive Workbench" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Documents" })).toBeVisible();
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Chat and notes" })).toBeVisible();
  await expect(page.getByLabel("Upload a scan or PDF")).toBeVisible();
  await page.getByRole("button", { name: "Library search" }).click();
  await expect(page.getByRole("searchbox", { name: "Library query" })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Internet Archive" })).toBeChecked();
});
