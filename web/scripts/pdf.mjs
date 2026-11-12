// HTML 파일 → PDF (A4). 화면정의서·테스트 화면 문서용 (scripts/build_screen_docs.py가 부른다, 11/12)
//   node scripts/pdf.mjs 입력.html 출력.pdf [landscape]
import { chromium } from "@playwright/test";
import { pathToFileURL } from "node:url";

const [src, out, orient] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage();
await page.goto(pathToFileURL(src).href, { waitUntil: "load" });
await page.pdf({ path: out, format: "A4", landscape: orient === "landscape", printBackground: true,
  margin: { top: "14mm", bottom: "14mm", left: "12mm", right: "12mm" },
  displayHeaderFooter: true, headerTemplate: "<span></span>",
  footerTemplate: '<div style="font-size:8px;width:100%;text-align:center;color:#888"><span class="pageNumber"></span> / <span class="totalPages"></span></div>' });
await browser.close();
console.log(out);
