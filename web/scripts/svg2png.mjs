// SVG → PNG (2배 해상도). 워크플로우·DB 관계도 그림용 (scripts/build_diagrams.py가 부른다, 11/17)
//   node scripts/svg2png.mjs 폴더   → 폴더 안의 *.svg 마다 같은 이름 .png
import { chromium } from "@playwright/test";
import { readdirSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const dir = process.argv[2];
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ deviceScaleFactor: 2 });
for (const f of readdirSync(dir).filter((x) => x.endsWith(".svg"))) {
  await page.goto(pathToFileURL(join(dir, f)).href);
  const el = await page.$("svg");
  await el.screenshot({ path: join(dir, f.replace(/\.svg$/, ".png")) });
  console.log(f);
}
await browser.close();
