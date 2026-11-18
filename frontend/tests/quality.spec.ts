import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { csvCell } from "../src/export";
import { screeningScore } from "../src/context";
import type { Screening } from "../src/types";

test("admin role controls preserve the last admin and manager permissions", async ({
  page,
  request,
}) => {
  const backend = process.env.PLAYWRIGHT_API_URL ?? "http://127.0.0.1:8001";
  const login = async (email: string) => {
    const response = await request.post(`${backend}/api/auth/login`, {
      data: {
        email,
        password: process.env.LOCAL_DEMO_PASSWORD ?? "local-demo-only",
      },
    });
    expect(response.ok()).toBeTruthy();
    return (await response.json()).access_token as string;
  };
  await page.goto("/");
  const adminToken = await login("admin@demo.local");
  await page.evaluate(
    (token) => sessionStorage.setItem("hireline_token", token),
    adminToken,
  );
  await page.goto("/settings");
  page.on("dialog", (dialog) => dialog.accept());
  const managerRole = page.getByRole("combobox", {
    name: "Role for Jordan Lee",
  });
  await managerRole.selectOption("recruiter");
  await expect(page.getByRole("status")).toContainText("Staff role updated");
  await expect(managerRole).toBeEnabled();
  await managerRole.selectOption("manager");
  await expect(managerRole).toBeEnabled();
  await page
    .getByRole("combobox", { name: "Role for Alex Morgan" })
    .selectOption("manager");
  await expect(page.getByRole("alert")).toContainText(
    "retain at least one admin",
  );
  const managerToken = await login("manager@demo.local");
  await page.evaluate(
    (token) => sessionStorage.setItem("hireline_token", token),
    managerToken,
  );
  await page.reload();
  await expect(page.getByRole("heading", { name: "Staff access" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Create a job", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByText("Sign in to inspect", { exact: true }),
  ).toHaveCount(4);
});

test("incomplete or stale screenings never become valid scores", () => {
  for (const status of ["queued", "failed", "stale"]) {
    expect(screeningScore({ status, score: 100 } as Screening)).toBeUndefined();
  }
  expect(screeningScore({ status: "approved", score: 0 } as Screening)).toBe(0);
  expect(
    screeningScore({ status: "awaiting_review", score: 75 } as Screening),
  ).toBe(75);
});

test("CSV cells escape quotes and spreadsheet formulas", () => {
  expect(csvCell('A, "B"')).toBe('"A, ""B"""');
  expect(csvCell(" =SUM(A1)")).toBe('"\' =SUM(A1)"');
  expect(csvCell("Plain text")).toBe('"Plain text"');
});

for (const width of [390, 1440]) {
  test(`workspace routes are accessible at ${width}px`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    for (const route of [
      "/",
      "/jobs",
      "/candidates",
      "/pipeline",
      "/analytics",
      "/settings",
    ]) {
      await page.goto(route);
      await expect(page.locator(".loading-state")).toHaveCount(0);
      await expect(page.locator(".page-content > *").first()).toBeVisible();
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth),
      ).toBeLessThanOrEqual(width);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(results.violations, `${route} accessibility`).toEqual([]);
    }
    expect(errors).toEqual([]);
  });
}

test("job links preserve their filter and keyboard search works", async ({
  page,
}) => {
  await page.goto("/jobs");
  const job = page.locator(".job-card").first();
  const title = await job.getByRole("heading").innerText();
  await job.getByRole("button", { name: "View candidates" }).click();
  await expect(page).toHaveURL(/\/candidates\?job=/);
  await expect(
    page.getByRole("combobox", { name: "Filter by job" }),
  ).toHaveValue(/.+/);
  for (const cell of await page
    .locator(".candidate-table tbody .table-job")
    .all()) {
    await expect(cell).toContainText(title);
  }
  await page.reload();
  await expect(
    page.getByRole("combobox", { name: "Filter by job" }),
  ).not.toHaveValue("all");
  await page.keyboard.press("Control+k");
  await expect(
    page.getByRole("textbox", { name: "Search candidates" }),
  ).toBeFocused();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Job openings." }),
  ).toBeVisible();
});

test("mobile menu and dialogs keep keyboard focus within the active surface", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const menu = page.getByRole("button", { name: "Open navigation" });
  await menu.click();
  await expect(
    page
      .getByRole("navigation")
      .getByRole("button", { name: "Overview", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toBeFocused();
  await page.getByRole("button", { name: "Staff sign in" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(results.violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Staff sign in" }),
  ).toBeFocused();
});

test("network failure offers recovery and stale authentication cannot clear a new session", async ({
  page,
}) => {
  await page.route("**/api/demo", (route) => route.abort());
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("unreachable");
  await page.unroute("**/api/demo");
  await page.getByRole("button", { name: "Retry connection" }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await page.route("**/api/session-race", async (route) => {
    await page.evaluate(() =>
      sessionStorage.setItem("hireline_token", "new-session"),
    );
    await route.fulfill({
      status: 401,
      json: { detail: "Expired old session" },
    });
  });
  const retained = await page.evaluate(async () => {
    sessionStorage.setItem("hireline_token", "old-session");
    // Exercise the actual browser API helper with a deliberately delayed old response.
    const modulePath = "/src/api.ts";
    const { api } = await import(modulePath);
    await api("/session-race").catch(() => {});
    return sessionStorage.getItem("hireline_token");
  });
  expect(retained).toBe("new-session");
});
