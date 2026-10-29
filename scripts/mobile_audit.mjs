#!/usr/bin/env node
/**
 * Phone-width layout audit for the local web frontend.
 *
 * The web layer is server-rendered and has no build step, so there is nothing
 * here to unit-test: a table that widens the page or a rail that hides under
 * the header is only visible in a browser. This script drives Chromium at the
 * four widths that matter and fails on the two things that actually break:
 *
 *   1. document-level horizontal scroll (a page you have to drag sideways);
 *   2. a table that widens its panel instead of scrolling inside it.
 *
 * It also reports touch targets under 32px and visible text under 12px, as
 * warnings — those are tastes, not failures, but a phone is where they bite.
 *
 * Usage (with the server running: `osu-critique serve`):
 *
 *     node scripts/mobile_audit.mjs [base-url] [--shots DIR]
 *
 * Needs Playwright (`npm i playwright`) or a module path in
 * PLAYWRIGHT_MODULE, plus the Chromium it ships with (CHROMIUM_PATH to point
 * at a system one).
 */
import { mkdir } from "node:fs/promises";

const argv = process.argv.slice(2);
const BASE = (argv.find((a) => a.startsWith("http")) || "http://127.0.0.1:8765")
  .replace(/\/$/, "");
const shotsAt = argv.indexOf("--shots");
const SHOTS = shotsAt >= 0 ? argv[shotsAt + 1] : null;
const WIDTHS = [320, 360, 390, 430];
const HEIGHT = 844;

const modulePath = process.env.PLAYWRIGHT_MODULE || "playwright";
let chromium;
try {
  ({ chromium } = await import(modulePath));
} catch (err) {
  console.error(`cannot load Playwright from '${modulePath}'.\n`
    + "  npm i playwright   (or set PLAYWRIGHT_MODULE to its index.mjs)\n"
    + `  ${err.message}`);
  process.exit(2);
}

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage({ viewport: { width: 390, height: HEIGHT } });

/** Routes worth auditing: the three page families, discovered from the corpus
 *  itself so this runs against any out/ directory, fixture or real. */
async function discover() {
  await page.goto(BASE + "/");
  const map = await page.evaluate(() =>
    document.querySelector('a.card[href^="/map/"]')?.getAttribute("href"));
  const run = map ? await page.evaluate(async (href) => {
    const html = await (await fetch(href)).text();
    return (html.match(/href="(\/run\/[^"]+)"/) || [])[1] || null;
  }, map) : null;
  const answer = await page.evaluate(async () => {
    const html = await (await fetch("/ask")).text();
    return (html.match(/href="(\/ask\/[a-f0-9]{16,})"/) || [])[1] || null;
  });
  return ["/", map, run, "/feed", "/ask", answer].filter(Boolean);
}

/** Run in the page: everything measured from the live layout. */
const audit = () => {
  const iw = window.innerWidth;
  const overflow = [];

  const clipped = (el) => {
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      if (getComputedStyle(a).overflowX !== "visible") return true;
    }
    return false;
  };

  document.querySelectorAll("body *").forEach((el) => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || r.right <= iw + 1) return;
    // a table inside .tscroll is the fix, not the bug
    if (clipped(el)) return;
    overflow.push({ tag: el.tagName.toLowerCase(),
                    cls: String(el.className || "").slice(0, 36),
                    right: Math.round(r.right) });
  });

  const small = [];
  document.querySelectorAll("button, input, select, a.pick, a.ghost, .tray-x, .rail a, .pill-link")
    .forEach((el) => {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      if (r.height < 32 || r.width < 32) {
        small.push({ tag: el.tagName.toLowerCase(),
                     cls: String(el.className || "").slice(0, 24),
                     h: Math.round(r.height), w: Math.round(r.width) });
      }
    });

  const tiny = [];
  document.querySelectorAll("p, li, td, th, pre, .k2, .sub, .stats, .fineprint, .md *")
    .forEach((el) => {
      if (!el.textContent.trim()) return;
      if (getComputedStyle(el).display === "none") return;
      const fs = parseFloat(getComputedStyle(el).fontSize);
      if (fs && fs < 12) tiny.push({ tag: el.tagName.toLowerCase(),
                                     cls: String(el.className || "").slice(0, 24),
                                     fs });
    });

  return { docSW: document.documentElement.scrollWidth, iw,
           overflow: overflow.slice(0, 6), overflowCount: overflow.length,
           small: small.slice(0, 6), smallCount: small.length,
           tiny: tiny.slice(0, 4), tinyCount: tiny.length };
};

const routes = await discover();
if (SHOTS) await mkdir(SHOTS, { recursive: true });
console.log(`auditing ${BASE} · ${routes.length} routes · widths ${WIDTHS.join("/")}`);
let failed = 0;

for (const route of routes) {
  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: HEIGHT });
    await page.goto(BASE + route, { waitUntil: "networkidle" }).catch(() => {});
    const r = await page.evaluate(audit);
    const overflow = r.docSW > r.iw + 1;
    if (overflow) failed++;
    const notes = [
      overflow ? `document.scrollWidth=${r.docSW}` : "",
      r.overflowCount ? `${r.overflowCount} unclipped offenders` : "",
      r.smallCount ? `${r.smallCount} small targets` : "",
      r.tinyCount ? `${r.tinyCount} under 12px` : "",
    ].filter(Boolean).join(" · ");
    console.log(`${overflow ? "FAIL" : "ok  "} ${String(width).padEnd(4)} `
      + `${route.slice(0, 48).padEnd(49)} ${notes}`);
    if (overflow) console.log("      ", JSON.stringify(r.overflow, null, 1));
    if (width === 390 && r.smallCount) console.log("       small:", JSON.stringify(r.small));
    if (width === 390 && r.tinyCount) console.log("       tiny :", JSON.stringify(r.tiny));
    if (SHOTS) {
      const name = route.replace(/[^\w]+/g, "-").replace(/^-|-$/g, "") || "root";
      await page.screenshot({ path: `${SHOTS}/${name}-${width}.png` });
    }
  }
}

await browser.close();
console.log(failed
  ? `\n${failed} page(s) scroll sideways. That is the bug this script exists for.`
  : "\nno horizontal overflow at any width");
process.exit(failed ? 1 : 0);
