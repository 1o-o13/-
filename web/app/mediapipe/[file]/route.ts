// MediaPipe wasm을 설치된 패키지에서 그대로 내준다 (외부 CDN을 쓰지 않음)
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const DIR = path.join(process.cwd(), "node_modules", "@mediapipe", "tasks-vision", "wasm");

export async function GET(_req: Request, ctx: { params: Promise<{ file: string }> }) {
  const { file } = await ctx.params;
  if (!(await readdir(DIR)).includes(file)) return new Response("없음", { status: 404 });
  const type = file.endsWith(".wasm") ? "application/wasm" : "text/javascript";
  return new Response(await readFile(path.join(DIR, file)), { headers: { "Content-Type": type } });
}
