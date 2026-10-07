// Browser smoke test for the dashboard. It drives every page against a RUNNING dashboard and API.
//
//   uv run hl serve                      # API on :8000 (set DEMO_MODE=true and no GROQ_API_KEY
//                                        #   to exercise the no-key demo path asserted below)
//   cd dashboard && npm run build && npm start
//   npx playwright install chromium      # once
//   npm run e2e
//
// It expects the local run store to contain a RAG and an agent dev run and the shipped cache.
import { mkdirSync } from "node:fs";
mkdirSync("e2e/screenshots", { recursive: true });
import { chromium } from "playwright";

const BASE = process.env.DASHBOARD_URL || "http://localhost:3000";
const results = [];
const ok = (name, cond, detail = "") => {
  results.push({ name, pass: !!cond, detail });
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const consoleErrors = [];
page.on("console", (m) => m.type() === "error" && consoleErrors.push(`${page.url()} :: ${m.text()}`));
page.on("pageerror", (e) => consoleErrors.push(`${page.url()} :: pageerror ${e.message}`));

async function visit(path) {
  const res = await page.goto(BASE + path, { waitUntil: "networkidle", timeout: 60000 });
  return res.status();
}

// 1. Overview
ok("overview 200", (await visit("/")) === 200);
await page.waitForSelector(".recharts-wrapper", { timeout: 30000 });
ok("overview: grouped bars rendered", (await page.locator(".recharts-bar-rectangle").count()) > 0, `${await page.locator(".recharts-bar-rectangle").count()} bars`);
ok("overview: CI error bars rendered", (await page.locator(".recharts-errorBar").count()) > 0, `${await page.locator(".recharts-errorBar").count()} error bars`);
ok("overview: leader table + disclaimer", (await page.getByText("Where each wins").count()) > 0 && (await page.getByText("Research demo.").count()) >= 2);
await page.screenshot({ path: "e2e/screenshots/overview.png", fullPage: true });

// run selector changes the URL
const ragSelect = page.locator("select").first();
const options = await ragSelect.locator("option").allTextContents();
ok("selector lists the rag runs", options.some((o) => o.includes("rag-test")), options.join(" | "));
await ragSelect.selectOption({ label: options.find((o) => o.includes("rag-test")) });
await page.waitForURL(/rag=rag-test/, { timeout: 30000 });
ok("selecting a run updates the URL and re-renders", page.url().includes("rag=rag-test"));

// nav
await page.getByRole("link", { name: "Trade-offs" }).click();
await page.waitForURL(/tradeoffs/, { timeout: 30000 });
await page.waitForSelector(".recharts-wrapper");
ok("nav to trade-offs: scatter + bar charts", (await page.locator(".recharts-scatter").count()) > 0 && (await page.locator(".recharts-bar-rectangle").count()) > 0);
ok("trade-offs: takeaway text present", (await page.getByText("the LLM calls").count()) > 0);
ok("active nav link marked", (await page.locator('nav a[aria-current="page"]').innerText()) === "Trade-offs");
await page.screenshot({ path: "e2e/screenshots/tradeoffs.png", fullPage: true });

// 3. Failures: filters
await visit("/failures");
await page.waitForSelector(".recharts-wrapper");
const totalText = await page.getByText(/Showing \d+ of \d+ failures/).innerText();
const total = Number(totalText.match(/of (\d+)/)[1]);
await page.getByPlaceholder("question text, answer or id").fill("tata motors");
const filteredText = await page.getByText(/Showing \d+ of \d+ failures/).innerText();
const filtered = Number(filteredText.match(/Showing (\d+)/)[1]);
ok("failures: search narrows the table", filtered < total && filtered > 0, `${filtered} of ${total}`);
await page.getByRole("button", { name: "Clear" }).click();
await page.locator("select").nth(4).selectOption("rag"); // the Pipeline filter (0-2 are the run selectors)
ok("failures: stacked chart rendered", (await page.locator(".recharts-bar-rectangle").count()) > 0);
await page.screenshot({ path: "e2e/screenshots/failures.png", fullPage: true });

// 4. Inspector
await visit("/inspector?q=Q-SF-0001&gold=1");
ok("inspector: gold answer shown", (await page.getByText("Gold:").count()) > 0);
ok("inspector: answer cards for each selected run", (await page.getByTestId("answer-short").count()) >= 2, `${await page.getByTestId("answer-short").count()} cards`);
const chip = page.getByRole("button", { name: /^Citation 1/ }).first();
ok("inspector: citation chips present", (await chip.count()) > 0);
await chip.click();
await page.getByRole("dialog").waitFor();
ok("inspector: chip opens the evidence drawer", (await page.getByRole("dialog").innerText()).match(/Evidence E\d|Citation/));
await page.getByRole("button", { name: "Show source page text" }).first().click();
await page.getByText(/Source text unavailable/).waitFor({ timeout: 20000 });
ok("inspector: missing source file handled gracefully", true);
await page.keyboard.press("Escape");
ok("inspector: Escape closes the drawer", (await page.getByRole("dialog").count()) === 0);
ok("inspector: traces rendered", (await page.getByText("vector_search").count()) > 0);
ok("inspector: subgraph empty-state (text-only runs)", (await page.getByText(/no subgraph to draw/).count()) > 0);
await page.getByPlaceholder("search text, id or category").fill("favourite food");
ok("inspector: picker filters questions", (await page.getByRole("listbox", { name: "Questions" }).getByRole("option").count()) === 1);
await page.screenshot({ path: "e2e/screenshots/inspector.png", fullPage: true });

// 5. Live (demo mode, no key)
await visit("/live");
ok("live: demo banner", (await page.getByText(/no API key is configured/).count()) > 0);
await page.getByRole("button", { name: "Who is the statutory auditor of Tata Motors in FY2023-24?" }).click();
await page.getByTestId("answer-short").first().waitFor({ timeout: 40000 });
ok("live: cached question answered", (await page.getByTestId("answer-short").count()) >= 2);
ok("live: marked as cached", (await page.getByText("stored results, no model call").count()) > 0);
ok("live: a pipeline with no stored answer says so", (await page.getByText("No stored answer for this pipeline.").count()) > 0);
await page.getByRole("textbox").fill("What is the weather in Mumbai?");
await page.getByRole("button", { name: "Ask all three" }).click();
await page.getByText("That question needs a live model").waitFor({ timeout: 40000 });
ok("live: uncached question explains it needs a key", (await page.locator("[role=alert]:not(#__next-route-announcer__)").first().innerText()).includes("API key"));
await page.getByRole("textbox").fill("");
ok("live: empty question can't be submitted", await page.getByRole("button", { name: "Ask all three" }).isDisabled());
await page.screenshot({ path: "e2e/screenshots/live.png", fullPage: true });

// 6. other pages
await visit("/data-quality");
ok("data quality: counts + provenance", (await page.getByText("Provenance").count()) > 0 && (await page.getByText(/of accepted facts carry a verbatim quote/).count()) > 0);
await visit("/review-queue");
ok("review queue: lists pending items", (await page.getByText("hl review").count()) > 0);
ok("404 page", (await visit("/nope")) === 404 && (await page.getByText("Page not found").count()) > 0);

// The browser logs every non-2xx response; these three are deliberate error paths under test
// (missing source file, uncached question with no key, an unknown URL).
const expected = (m) => /Failed to load resource.*(404|503)/.test(m) && /(inspector|live|nope)/.test(m);
const unexpected = consoleErrors.filter((m) => !expected(m));
ok("no unexpected console or page errors on any page", unexpected.length === 0, unexpected.slice(0, 5).join("\n"));
await browser.close();

for (const r of results) console.log(`${r.pass ? "PASS" : "FAIL"}  ${r.name}${r.detail && !r.pass ? "  -> " + r.detail : r.detail ? "  (" + r.detail + ")" : ""}`);
const failed = results.filter((r) => !r.pass).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
