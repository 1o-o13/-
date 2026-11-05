// API 호출. 같은 주소의 /api로 보내고(next.config rewrites) 로그인은 HttpOnly 쿠키로 유지된다.
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const res = await fetch(`/api${path}`, {
    ...rest,
    credentials: "same-origin",
    headers: json === undefined ? rest.headers : { "Content-Type": "application/json", ...rest.headers },
    body: json === undefined ? rest.body : JSON.stringify(json),
  });
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const d = body?.detail;
    // 입력 틀 오류(422)는 첫 항목의 안내 문구를 보여 준다 (pydantic: "Value error, ...")
    const msg = typeof d === "string" ? d : Array.isArray(d) && d[0]?.msg ? String(d[0].msg).replace(/^Value error, /, "") : "요청을 처리하지 못했습니다";
    throw new ApiError(res.status, msg);
  }
  return body as T;
}

/** 로그인이 풀렸으면 로그인 화면으로. 그 밖의 오류 문구는 화면에 보여 준다 */
export function errorText(e: unknown, go: (path: string) => void, admin = false): string {
  if (e instanceof ApiError && e.status === 401) go(admin ? "/admin/login" : "/login");
  return e instanceof Error ? e.message : String(e);
}
