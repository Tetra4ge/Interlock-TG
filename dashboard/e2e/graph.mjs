// Browser test for the Inspector's subgraph canvas, against the fixture server
// (a seeded multi-hop question and a stubbed graph; no TigerGraph needed).
//
//   CORS_ORIGINS=http://localhost:3001 uv run python -m tests.e2e.fixture_server   # :8001
//   cd dashboard && NEXT_PUBLIC_API_URL=http://localhost:8001 npx next dev -p 3001
//   npm run e2e:graph
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

mkdirSync("e2e/screenshots", { recursive: true });
const BASE = process.env.DASHBOARD_URL || "http://localhost:3001";
const results = [];
const ok = (name, cond, detail = "") => results.push({ name, pass: !!cond, detail });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

const url = "/inspector?rag=fx-rag&graphrag=fx-graphrag&agent=fx-agent&q=FX-MH-0001&gold=1";
await page.goto(BASE + url, { waitUntil: "networkidle", timeout: 90000 });

ok("three answer cards side by side", (await page.getByTestId("answer-short").count()) === 3 || (await page.locator("article").count()) === 3, `${await page.locator("article").count()} articles`);
ok("RAG shows the wrong abstention", (await page.getByText("Wrong abstention").count()) > 0);
ok("both graph pipelines are marked correct", (await page.getByText("Correct", { exact: true }).count()) === 2);

const svg = page.getByRole("img", { name: /Knowledge graph/ });
await svg.waitFor({ timeout: 30000 });
ok("subgraph canvas renders", true);
ok("4 nodes: two people and two companies", (await svg.locator("circle").count()) === 4, `${await svg.locator("circle").count()} nodes`);
ok("3 edges drawn", (await svg.locator('g[role="button"]').count()) === 3, `${await svg.locator('g[role="button"]').count()} edges`);
ok("nodes are labelled with entity names", (await svg.getByText("Tata Motors Limited").count()) > 0 && (await svg.getByText("Anil Kumar Sharma").count()) > 0);
ok("legend shows 'several pipelines' and gold evidence", (await page.getByText("several pipelines").count()) > 0 && (await page.getByText("on gold evidence page").count()) > 0);

const halos = await svg.locator('path[stroke="#f59e0b"]').count();
// Gold evidence is page-level: all three edges sit on a gold page (Steel p.46 holds two of them).
ok("every edge on a gold page is haloed", halos === 3, `${halos} halos`);
ok("a graph-only edge is coloured by its pipeline", (await svg.locator('path[stroke="#10B981"]').count()) > 0); // d-steel-2: GraphRAG only

ok("3 of 3 facts found", (await page.getByText("3 of 3 facts found").count()) > 0);
await svg.locator('g[role="button"]').nth(0).click();
const detail = page.locator('[aria-live="polite"]').filter({ hasText: "Source:" });
await detail.waitFor({ timeout: 5000 });
ok("clicking an edge shows its source page and quote", (await detail.innerText()).includes("p.") && (await detail.innerText()).includes("Independent Director"));
await svg.locator('g[role="button"]').nth(0).press("Enter");
ok("Enter on a focused edge toggles it (keyboard accessible)", (await page.getByText("Click an edge to see its source page and quote.").count()) > 0);

await page.getByRole("button", { name: /Citation 1/ }).first().click();
ok("citation drawer opens for a graph answer", (await page.getByRole("dialog").count()) === 1);
await page.screenshot({ path: "e2e/screenshots/subgraph.png", fullPage: true });

const unexpected = errors.filter((m) => !/Failed to load resource.*404/.test(m));
ok("no unexpected console errors", unexpected.length === 0, unexpected.join(" | "));
await browser.close();

for (const r of results) console.log(`${r.pass ? "PASS" : "FAIL"}  ${r.name}${r.detail ? `  (${r.detail})` : ""}`);
const failed = results.filter((r) => !r.pass).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
