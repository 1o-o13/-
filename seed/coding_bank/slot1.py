"""1번 (알고리즘형, 기본 골드 3) 문제 모음. 백준 유형을 새벽소프트 업무 상황으로 새로 쓴 문제 (원문 복제 아님).
generator(size, rnd): size 1~5 그룹 입력 / validator(inp): 입력 제약 검사 / wrong_codes: CT-08 오답 (kind: minor 사소한 실수, approach 접근 오류)
"""

ROBOT = {
    "key": "s1-robot", "slot": 1, "tier": "골드3", "type": "BFS", "title": "물류 로봇의 최단 경로",
    "statement": """로지패스 물류 센터의 로봇은 N×M 격자에서 (1,1)에서 출발해 (N,M)까지 이동한다. `0`은 빈칸, `1`은 선반이다.
로봇은 상하좌우로 한 칸씩 움직이며, 이동하는 동안 **선반을 최대 한 번** 치우고 지나갈 수 있다.
출발 칸과 도착 칸을 포함해 지나간 칸 수의 최솟값을 출력한다. 갈 수 없으면 `-1`을 출력한다.

**입력**  첫 줄에 N M (1 ≤ N, M ≤ 300). 다음 N줄에 0과 1로 된 길이 M의 문자열. 출발 칸과 도착 칸은 0이다.
**출력**  지나간 칸 수의 최솟값 또는 -1""",
    "examples": [("3 4\n0100\n1110\n1000\n", "6\n"), ("2 2\n01\n10\n", "3\n")],
    "solution_python": """import sys
from collections import deque
def main():
    data = sys.stdin.read().split()
    n, m = int(data[0]), int(data[1])
    g = data[2:2 + n]
    INF = -1
    dist = [[[INF] * m for _ in range(n)] for _ in range(2)]
    dist[0][0][0] = 1
    q = deque([(0, 0, 0)])
    while q:
        b, r, c = q.popleft()
        d = dist[b][r][c]
        if r == n - 1 and c == m - 1:
            print(d); return
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < n and 0 <= nc < m:
                nb = b + (g[nr][nc] == '1')
                if nb <= 1 and dist[nb][nr][nc] == INF:
                    dist[nb][nr][nc] = d + 1
                    q.append((nb, nr, nc))
    print(-1)
main()
""",
    "solution_java": """import java.io.*;
import java.util.*;
public class Main {
    public static void main(String[] args) throws IOException {
        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
        StringTokenizer st = new StringTokenizer(br.readLine());
        int n = Integer.parseInt(st.nextToken()), m = Integer.parseInt(st.nextToken());
        char[][] g = new char[n][];
        for (int i = 0; i < n; i++) g[i] = br.readLine().trim().toCharArray();
        int[][][] dist = new int[2][n][m];
        ArrayDeque<int[]> q = new ArrayDeque<>();
        dist[0][0][0] = 1; q.add(new int[]{0, 0, 0});
        int[] dr = {1, -1, 0, 0}, dc = {0, 0, 1, -1};
        while (!q.isEmpty()) {
            int[] cur = q.poll(); int b = cur[0], r = cur[1], c = cur[2], d = dist[b][r][c];
            if (r == n - 1 && c == m - 1) { System.out.println(d); return; }
            for (int k = 0; k < 4; k++) {
                int nr = r + dr[k], nc = c + dc[k];
                if (nr < 0 || nc < 0 || nr >= n || nc >= m) continue;
                int nb = b + (g[nr][nc] == '1' ? 1 : 0);
                if (nb <= 1 && dist[nb][nr][nc] == 0) { dist[nb][nr][nc] = d + 1; q.add(new int[]{nb, nr, nc}); }
            }
        }
        System.out.println(-1);
    }
}
""",
    "brute_force": """import sys, itertools
from collections import deque
def bfs(g, n, m):
    d = [[-1] * m for _ in range(n)]; d[0][0] = 1; q = deque([(0, 0)])
    while q:
        r, c = q.popleft()
        for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
            nr, nc = r+dr, c+dc
            if 0 <= nr < n and 0 <= nc < m and g[nr][nc] == '0' and d[nr][nc] < 0:
                d[nr][nc] = d[r][c] + 1; q.append((nr, nc))
    return d[n-1][m-1]
data = sys.stdin.read().split(); n, m = int(data[0]), int(data[1]); g = [list(x) for x in data[2:2+n]]
best = bfs(g, n, m)
for r in range(n):
    for c in range(m):
        if g[r][c] == '1':
            g[r][c] = '0'; v = bfs(g, n, m); g[r][c] = '1'
            if v > 0 and (best < 0 or v < best): best = v
print(best)
""",
    "generator": """def gen(size, rnd):
    n = [3, 8, 30, 100, 200][size - 1]; m = [4, 9, 30, 120, 200][size - 1]
    p = rnd.choice([0.2, 0.35, 0.5])
    rows = [''.join('1' if rnd.random() < p else '0' for _ in range(m)) for _ in range(n)]
    rows[0] = '0' + rows[0][1:]; rows[-1] = rows[-1][:-1] + '0'
    return f"{n} {m}\\n" + "\\n".join(rows) + "\\n"
""",
    "validator": """def check(inp):
    lines = inp.split(); n, m = int(lines[0]), int(lines[1]); g = lines[2:]
    return 1 <= n <= 300 and 1 <= m <= 300 and len(g) == n and all(len(r) == m and set(r) <= {'0','1'} for r in g) and g[0][0] == '0' and g[-1][-1] == '0'
""",
    "wrong_codes": [
        {"kind": "approach", "note": "선반을 치울 수 없다고 보고 BFS", "code": """import sys
from collections import deque
data = sys.stdin.read().split(); n, m = int(data[0]), int(data[1]); g = data[2:2+n]
d = [[-1]*m for _ in range(n)]; d[0][0] = 1; q = deque([(0,0)])
while q:
    r, c = q.popleft()
    for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
        nr, nc = r+dr, c+dc
        if 0 <= nr < n and 0 <= nc < m and g[nr][nc] == '0' and d[nr][nc] < 0:
            d[nr][nc] = d[r][c]+1; q.append((nr, nc))
print(d[n-1][m-1])
"""},
        {"kind": "minor", "note": "방문 표시를 선반 사용 여부와 나누지 않음", "code": """import sys
from collections import deque
data = sys.stdin.read().split(); n, m = int(data[0]), int(data[1]); g = data[2:2+n]
seen = [[False]*m for _ in range(n)]; seen[0][0] = True; q = deque([(0,0,0,1)]); ans = -1
while q:
    r, c, b, d = q.popleft()
    if (r, c) == (n-1, m-1): ans = d; break
    for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
        nr, nc = r+dr, c+dc
        if 0 <= nr < n and 0 <= nc < m and not seen[nr][nc]:
            nb = b + (g[nr][nc] == '1')
            if nb <= 1: seen[nr][nc] = True; q.append((nr, nc, nb, d+1))
print(ans)
"""},
        {"kind": "minor", "note": "지나간 칸 수에서 출발 칸을 빼먹음", "code": """import sys
from collections import deque
data = sys.stdin.read().split(); n, m = int(data[0]), int(data[1]); g = data[2:2+n]
dist = [[[-1]*m for _ in range(n)] for _ in range(2)]; dist[0][0][0] = 0; q = deque([(0,0,0)])
while q:
    b, r, c = q.popleft(); d = dist[b][r][c]
    if (r, c) == (n-1, m-1): print(d); break
    for dr, dc in ((1,0),(-1,0),(0,1),(0,-1)):
        nr, nc = r+dr, c+dc
        if 0 <= nr < n and 0 <= nc < m:
            nb = b + (g[nr][nc] == '1')
            if nb <= 1 and dist[nb][nr][nc] < 0: dist[nb][nr][nc] = d+1; q.append((nb, nr, nc))
else:
    print(-1)
"""},
    ],
}

ROUTE = {
    "key": "s1-route", "slot": 1, "tier": "골드3", "type": "다익스트라", "title": "정산 서버까지 가장 빠른 길",
    "statement": """정산온의 데이터센터에는 서버 N대와 단방향 회선 M개가 있다. 회선 i는 서버 u에서 v로 데이터를 w초에 보낸다.
서버 S에서 서버 T로 보내는 가장 짧은 시간과, 그 시간으로 보낼 수 있는 **서로 다른 경로의 수를 1,000,000,007로 나눈 나머지**를 출력한다.
도달할 수 없으면 `-1`만 출력한다.

**입력**  첫 줄에 N M (2 ≤ N ≤ 20,000, 1 ≤ M ≤ 100,000). 다음 M줄에 u v w (1 ≤ u, v ≤ N, u ≠ v, 1 ≤ w ≤ 1,000). 마지막 줄에 S T (S ≠ T).
**출력**  최단 시간과 경로 수를 공백으로 구분해 출력하거나 -1""",
    "examples": [("4 5\n1 2 1\n1 3 1\n2 4 1\n3 4 1\n1 4 3\n1 4\n", "2 2\n"), ("3 1\n1 2 5\n1 3\n", "-1\n")],
    "solution_python": """import sys, heapq
def main():
    it = iter(sys.stdin.buffer.read().split()); n, m = int(next(it)), int(next(it))
    adj = [[] for _ in range(n + 1)]
    for _ in range(m):
        u, v, w = int(next(it)), int(next(it)), int(next(it)); adj[u].append((v, w))
    s, t = int(next(it)), int(next(it))
    MOD = 10**9 + 7; INF = float('inf')
    dist = [INF] * (n + 1); cnt = [0] * (n + 1); dist[s] = 0; cnt[s] = 1; pq = [(0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]: continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]: dist[v] = nd; cnt[v] = cnt[u]; heapq.heappush(pq, (nd, v))
            elif nd == dist[v]: cnt[v] = (cnt[v] + cnt[u]) % MOD
    print(-1 if dist[t] == INF else f"{dist[t]} {cnt[t]}")
main()
""",
    "solution_java": """import java.io.*;
import java.util.*;
public class Main {
    public static void main(String[] args) throws IOException {
        DataInputStream in = new DataInputStream(new BufferedInputStream(System.in, 1 << 16));
        int n = next(in), m = next(in);
        int[] head = new int[n + 1], nxt = new int[m], to = new int[m], wt = new int[m];
        Arrays.fill(head, -1);
        for (int i = 0; i < m; i++) { int u = next(in), v = next(in), w = next(in); to[i] = v; wt[i] = w; nxt[i] = head[u]; head[u] = i; }
        int s = next(in), t = next(in);
        final long MOD = 1_000_000_007L;
        long[] dist = new long[n + 1]; long[] cnt = new long[n + 1];
        Arrays.fill(dist, Long.MAX_VALUE); dist[s] = 0; cnt[s] = 1;
        PriorityQueue<long[]> pq = new PriorityQueue<>((a, b) -> Long.compare(a[0], b[0]));
        pq.add(new long[]{0, s});
        while (!pq.isEmpty()) {
            long[] cur = pq.poll(); int u = (int) cur[1];
            if (cur[0] > dist[u]) continue;
            for (int e = head[u]; e != -1; e = nxt[e]) {
                int v = to[e]; long nd = cur[0] + wt[e];
                if (nd < dist[v]) { dist[v] = nd; cnt[v] = cnt[u]; pq.add(new long[]{nd, v}); }
                else if (nd == dist[v]) cnt[v] = (cnt[v] + cnt[u]) % MOD;
            }
        }
        System.out.println(dist[t] == Long.MAX_VALUE ? "-1" : dist[t] + " " + cnt[t]);
    }
    static int next(DataInputStream in) throws IOException {
        int r = 0, b = in.read();
        while (b < '0') b = in.read();
        while (b >= '0') { r = r * 10 + b - '0'; b = in.read(); }
        return r;
    }
}
""",
    "brute_force": None,
    "generator": """def gen(size, rnd):
    if size >= 3 and rnd.random() < 0.4:                 # 마름모 사슬: 최단 경로 수 2^k (나머지 처리 확인)
        k = rnd.randint(31, 60); e = []; nid = k + 2
        for i in range(1, k + 1):
            a, b = nid, nid + 1; nid += 2
            e += [f"{i} {a} 1", f"{i} {b} 1", f"{a} {i+1} 1", f"{b} {i+1} 1"]
        return f"{nid - 1} {len(e)}\\n" + "\\n".join(e) + f"\\n1 {k + 1}\\n"
    n = [4, 10, 200, 3000, 10000][size - 1]; m = [6, 25, 1500, 40000, 50000][size - 1]
    wmax = rnd.choice([2, 5, 1000])
    edges = []
    for _ in range(m):
        u = rnd.randint(1, n); v = rnd.randint(1, n - 1); v = v + 1 if v >= u else v
        edges.append(f"{u} {v} {rnd.randint(1, wmax)}")
    s = rnd.randint(1, n); t = rnd.randint(1, n - 1); t = t + 1 if t >= s else t
    return f"{n} {m}\\n" + "\\n".join(edges) + f"\\n{s} {t}\\n"
""",
    "validator": """def check(inp):
    a = list(map(int, inp.split())); n, m = a[0], a[1]
    if not (2 <= n <= 20000 and 1 <= m <= 100000 and len(a) == 2 + 3 * m + 2): return False
    for i in range(m):
        u, v, w = a[2 + 3*i: 5 + 3*i]
        if not (1 <= u <= n and 1 <= v <= n and u != v and 1 <= w <= 1000): return False
    s, t = a[-2], a[-1]
    return 1 <= s <= n and 1 <= t <= n and s != t
""",
    "wrong_codes": [
        {"kind": "approach", "note": "가중치를 무시한 BFS", "code": """import sys
from collections import deque
it = iter(sys.stdin.read().split()); n, m = int(next(it)), int(next(it)); adj = [[] for _ in range(n+1)]
for _ in range(m):
    u, v, w = int(next(it)), int(next(it)), int(next(it)); adj[u].append((v, w))
s, t = int(next(it)), int(next(it)); d = [-1]*(n+1); d[s] = 0; c = [0]*(n+1); c[s] = 1; q = deque([s]); sumw = [0]*(n+1)
while q:
    u = q.popleft()
    for v, w in adj[u]:
        if d[v] < 0: d[v] = d[u]+1; sumw[v] = sumw[u]+w; c[v] = c[u]; q.append(v)
        elif d[v] == d[u]+1: c[v] += c[u]
print(-1 if d[t] < 0 else f"{sumw[t]} {c[t] % (10**9+7)}")
"""},
        {"kind": "minor", "note": "경로 수를 나머지로 줄이지 않음 (큰 수 그대로)", "code": """import sys, heapq
it = iter(sys.stdin.read().split()); n, m = int(next(it)), int(next(it)); adj = [[] for _ in range(n+1)]
for _ in range(m):
    u, v, w = int(next(it)), int(next(it)), int(next(it)); adj[u].append((v, w))
s, t = int(next(it)), int(next(it)); INF = float('inf'); dist = [INF]*(n+1); cnt = [0]*(n+1); dist[s] = 0; cnt[s] = 1; pq = [(0, s)]
while pq:
    d, u = heapq.heappop(pq)
    if d > dist[u]: continue
    for v, w in adj[u]:
        if d+w < dist[v]: dist[v] = d+w; cnt[v] = cnt[u]; heapq.heappush(pq, (d+w, v))
        elif d+w == dist[v]: cnt[v] += cnt[u]
print(-1 if dist[t] == INF else f"{dist[t]} {cnt[t]}")
"""},
        {"kind": "minor", "note": "같은 시간 경로를 더하지 않음 (경로 수 항상 1)", "code": """import sys, heapq
it = iter(sys.stdin.read().split()); n, m = int(next(it)), int(next(it)); adj = [[] for _ in range(n+1)]
for _ in range(m):
    u, v, w = int(next(it)), int(next(it)), int(next(it)); adj[u].append((v, w))
s, t = int(next(it)), int(next(it)); INF = float('inf'); dist = [INF]*(n+1); dist[s] = 0; pq = [(0, s)]
while pq:
    d, u = heapq.heappop(pq)
    if d > dist[u]: continue
    for v, w in adj[u]:
        if d+w < dist[v]: dist[v] = d+w; heapq.heappush(pq, (d+w, v))
print(-1 if dist[t] == INF else f"{dist[t]} 1")
"""},
    ],
}

PROBLEMS = [ROBOT, ROUTE]
