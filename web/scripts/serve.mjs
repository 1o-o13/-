// 웹 운영 서버 + 고치면 자동 반영 (11/10). 손으로 docker compose restart web 하지 않아도 된다.
// - 3000번은 이 스크립트가 받아 지금 쓰는 Next 운영 서버(next start)로 넘긴다 (Node 기본 http만 씀, 새 패키지 없음)
// - 화면 코드(app·lib·public·설정 파일)가 바뀌면 뒤에서 새로 빌드 → 새 서버가 준비되면 요청을 그쪽으로 돌리고 옛 서버를 내린다 (끊김 없음)
// - 빌드가 실패하면 옛 서버를 그대로 쓰고 오류만 남긴다. Windows Docker는 파일 변경 알림이 안 와서 3초마다 수정 시각을 본다
// - 빌드 결과는 .build/a 와 .build/b 를 번갈아 쓴다 (NEXT_DIST_DIR, next.config.ts distDir)
// - 다시 켜질 때(Docker·PC 재시작, 11/11) 마지막으로 쓰던 빌드를 바로 띄운다 → 몇 초 안에 접속됨. 코드가 바뀌었으면 그 뒤 뒤에서 다시 빌드
// - 패키지 설치(npm ci)는 package-lock.json 내용이 바뀌었을 때만 한다 (매번 하면 켜질 때마다 40초씩 멈춤)
import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const PORT = 3000;
const WATCH_DIRS = ["app", "lib", "public"];
const WATCH_FILES = ["next.config.ts", "package.json", "package-lock.json", "postcss.config.mjs"];   // tsconfig.json은 Next가 빌드 때 스스로 고쳐서 보지 않음
const POLL_MS = 3000;
const log = (...a) => console.log(`[serve ${new Date().toISOString().slice(11, 19)}]`, ...a);

let current = null; // { port, proc, slot }
let nextPort = 3101;  // 새 서버마다 새 내부 포트 (옛 서버가 아직 떠 있어도 겹치지 않게)
let building = false;
let lastSig = "";
const NEXT = path.join(ROOT, "node_modules", ".bin", "next");
const STATE = path.join(ROOT, ".build", "current.json");   // 마지막으로 전환한 빌드 { slot, sig }
const LOCK_MARK = path.join(ROOT, "node_modules", ".lock-hash");
const lockHash = () => { try { return crypto.createHash("sha256").update(fs.readFileSync(path.join(ROOT, "package-lock.json"))).digest("hex"); } catch { return ""; } };
const readText = (f) => { try { return fs.readFileSync(f, "utf8"); } catch { return ""; } };

async function install() {                       // 패키지 목록이 바뀌었거나 설치된 적이 없을 때만
  const h = lockHash();
  if (h && readText(LOCK_MARK) === h && fs.existsSync(NEXT)) return;
  log("패키지 설치 (npm ci)");
  if (await run("npm", ["ci", "--no-audit", "--no-fund"])) fs.writeFileSync(LOCK_MARK, h);
}

function signature() {
  // 바뀐 것 = 파일 수정 시각·크기의 합
  let acc = 0, n = 0;
  const walk = (p) => {
    let st;
    try { st = fs.statSync(p); } catch { return; }
    if (st.isDirectory()) {
      for (const f of fs.readdirSync(p)) if (f !== "node_modules" && !f.startsWith(".")) walk(path.join(p, f));
    } else {
      acc += st.mtimeMs + st.size;
      n += 1;
    }
  };
  WATCH_DIRS.forEach((d) => walk(path.join(ROOT, d)));
  WATCH_FILES.forEach((f) => walk(path.join(ROOT, f)));
  return `${n}:${Math.round(acc)}`;
}

function run(cmd, args, env = {}) {
  return new Promise((resolve) => {
    const p = spawn(cmd, args, { cwd: ROOT, env: { ...process.env, ...env }, stdio: "inherit" });
    p.on("exit", (code) => resolve(code === 0));
  });
}

async function ready(port, ms = 120_000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const ok = await new Promise((r) => http.get({ port, path: "/login", timeout: 3000 }, (res) => { res.resume(); r(res.statusCode === 200); }).on("error", () => r(false)));
    if (ok) return true;
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

async function switchTo(slot, port, sig) {
  const dist = `.build/${slot}`;
  const proc = spawn(NEXT, ["start", "-p", String(port), "-H", "127.0.0.1"], { cwd: ROOT, env: { ...process.env, NEXT_DIST_DIR: dist }, stdio: "inherit" });
  let died = false;
  proc.on("exit", () => { died = true; });
  if (!(await ready(port)) || died) {             // 뜨다가 죽었으면(포트 충돌 등) 전환하지 않는다
    proc.kill("SIGTERM");
    return false;
  }
  const old = current;
  current = { port, proc, slot };
  lastSig = sig;
  fs.writeFileSync(STATE, JSON.stringify({ slot, sig }));
  log(`새 화면으로 전환 (${dist}, 내부 포트 ${port})`);
  if (old) setTimeout(() => old.proc.kill("SIGTERM"), 30_000); // 옛 서버에 걸린 요청(SSE 등)이 끝날 시간을 준다
  return true;
}

/** 다시 켜질 때: 마지막으로 쓰던 빌드(없으면 가장 최근 빌드)를 바로 띄운다. 코드가 그 뒤 바뀌었으면 주기 검사가 다시 빌드한다 */
async function resume() {
  let st = null;
  try { st = JSON.parse(readText(STATE)); } catch { /* 처음이면 없음 */ }
  const built = ["a", "b"].filter((x) => fs.existsSync(path.join(ROOT, ".build", x, "BUILD_ID")))
    .sort((x, y) => fs.statSync(path.join(ROOT, ".build", y, "BUILD_ID")).mtimeMs - fs.statSync(path.join(ROOT, ".build", x, "BUILD_ID")).mtimeMs);
  const slot = st && built.includes(st.slot) ? st.slot : built[0];
  if (!slot) return false;
  const port = nextPort;
  nextPort += 1;
  log(`다시 시작 → 지난 빌드(.build/${slot})를 바로 띄웁니다`);
  return switchTo(slot, port, st?.slot === slot ? st.sig : "");
}

async function deploy(reason) {
  if (building) return;
  building = true;
  const sig = signature();
  const slot = current?.slot === "a" ? "b" : "a";
  const dist = `.build/${slot}`;
  const port = nextPort;
  nextPort = nextPort >= 3199 ? 3101 : nextPort + 1;
  log(`${reason} → 빌드 시작 (${dist})`);
  try {
    await install();
    if (!(await run(NEXT, ["build"], { NEXT_DIST_DIR: dist }))) {
      log("빌드 실패 → 지금 화면을 그대로 씁니다. 코드를 고치면 다시 빌드합니다");
      lastSig = sig;
      return;
    }
    if (!(await switchTo(slot, port, sig))) {
      log("새 서버가 뜨지 않음 → 지금 화면을 그대로 씁니다");
      lastSig = sig;
    }
  } finally {
    building = false;
  }
}

// 3000번: 지금 서버로 그대로 넘긴다 (SSE 스트림도 그대로 흘려보냄)
http.createServer((req, res) => {
  if (!current) {
    res.writeHead(503, { "content-type": "text/plain; charset=utf-8", "retry-after": "5" });
    return res.end("화면을 준비하고 있습니다. 잠시 뒤 다시 시도해 주세요.");
  }
  const up = http.request({ host: "127.0.0.1", port: current.port, path: req.url, method: req.method, headers: req.headers }, (r) => {
    res.writeHead(r.statusCode ?? 502, r.headers);
    r.pipe(res);
  });
  up.on("error", () => { if (!res.headersSent) res.writeHead(502); res.end(); });
  req.pipe(up);
}).listen(PORT, "0.0.0.0", () => log(`3000번 대기`));

await install();
if (!(await resume())) await deploy("처음 시작");
else if (signature() !== lastSig) deploy("지난 빌드 뒤 화면 코드 바뀜");
setInterval(() => {
  if (!building && signature() !== lastSig) deploy("화면 코드 바뀜");
}, POLL_MS);
