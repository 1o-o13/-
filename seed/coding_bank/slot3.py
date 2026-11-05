"""3번 대체 문제 모음 (등급별 1개). 3번은 LLM이 즉석 출제하고, 키가 없거나 검증이 2번 실패하면 같은 등급의 이 문제를 낸다 (CT-07).
모두 새벽소프트 업무 상황으로 새로 쓴 문제."""

SORT = {
    "key": "s3-silver1", "slot": 3, "tier": "실버1", "type": "정렬", "title": "인기 검색어 순위",
    "statement": """파인드는 하루 동안 들어온 검색어 N개로 인기 순위를 만든다. 많이 들어온 검색어가 먼저이고,
횟수가 같으면 사전순으로 앞선 검색어가 먼저다. 상위 K개를 한 줄에 하나씩 출력한다 (종류가 K보다 적으면 모두).

**입력**  첫 줄에 N K (1 ≤ N ≤ 200,000, 1 ≤ K ≤ 100). 다음 N줄에 영문 소문자 검색어 (길이 1~10)
**출력**  순위대로 검색어""",
    "examples": [("6 2\nbook\npay\nbook\nchat\npay\nbook\n", "book\npay\n")],
    "solution_python": """import sys
from collections import Counter
data = sys.stdin.read().split(); k = int(data[1]); c = Counter(data[2:])
print('\\n'.join(w for w, _ in sorted(c.items(), key=lambda x: (-x[1], x[0]))[:k]))
""",
    "solution_java": """import java.io.*;
import java.util.*;
public class Main {
    public static void main(String[] args) throws IOException {
        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
        StringTokenizer st = new StringTokenizer(br.readLine());
        int n = Integer.parseInt(st.nextToken()), k = Integer.parseInt(st.nextToken());
        HashMap<String, Integer> c = new HashMap<>();
        for (int i = 0; i < n; i++) c.merge(br.readLine().trim(), 1, Integer::sum);
        List<String> w = new ArrayList<>(c.keySet());
        w.sort((a, b) -> !c.get(a).equals(c.get(b)) ? c.get(b) - c.get(a) : a.compareTo(b));
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < Math.min(k, w.size()); i++) sb.append(w.get(i)).append('\\n');
        System.out.print(sb);
    }
}
""",
    "brute_force": None,
    "generator": """def gen(size, rnd):
    n = [5, 30, 1000, 10000, 50000][size - 1]; vocab = rnd.choice([3, 20, 500])
    words = [''.join(rnd.choice('abcdefghij') for _ in range(rnd.randint(1, 6))) for _ in range(vocab)]
    return f"{n} {rnd.randint(1, 100)}\\n" + "\\n".join(rnd.choice(words) for _ in range(n)) + "\\n"
""",
    "validator": """def check(inp):
    a = inp.split(); n, k = int(a[0]), int(a[1])
    return 1 <= n <= 200000 and 1 <= k <= 100 and len(a) == 2 + n and all(1 <= len(w) <= 10 and w.isalpha() and w.islower() for w in a[2:])
""",
    "wrong_codes": [
        {"kind": "minor", "note": "횟수가 같을 때 사전순 정렬을 빼먹음", "code": """import sys
from collections import Counter
data = sys.stdin.read().split(); k = int(data[1]); c = Counter(data[2:])
print('\\n'.join(w for w, _ in sorted(c.items(), key=lambda x: -x[1])[:k]))
"""},
        {"kind": "approach", "note": "사전순으로만 정렬", "code": """import sys
data = sys.stdin.read().split(); k = int(data[1])
print('\\n'.join(sorted(set(data[2:]))[:k]))
"""},
    ],
}

GROUP = {
    "key": "s3-gold5", "slot": 3, "tier": "골드5", "type": "유니온 파인드", "title": "원패스 계정 묶기",
    "statement": """원패스는 계정 N개를 관리한다. 처음에는 모두 따로다. 명령이 Q개 주어진다.
`1 a b`는 계정 a와 b가 속한 묶음을 합친다. `2 a b`는 a와 b가 같은 묶음이면 `YES`, 아니면 `NO`를 출력한다.

**입력**  첫 줄에 N Q (1 ≤ N ≤ 200,000, 1 ≤ Q ≤ 200,000). 다음 Q줄에 명령
**출력**  2번 명령마다 한 줄""",
    "examples": [("4 5\n1 1 2\n2 1 2\n2 1 3\n1 2 3\n2 1 3\n", "YES\nNO\nYES\n")],
    "solution_python": """import sys
def main():
    data = sys.stdin.buffer.read().split(); n, q = int(data[0]), int(data[1]); p = list(range(n + 1)); out = []
    def find(x):
        while p[x] != x:
            p[x] = p[p[x]]; x = p[x]
        return x
    for i in range(q):
        t, a, b = int(data[2+3*i]), int(data[3+3*i]), int(data[4+3*i])
        ra, rb = find(a), find(b)
        if t == 1: p[ra] = rb
        else: out.append('YES' if ra == rb else 'NO')
    print('\\n'.join(out))
main()
""",
    "solution_java": """import java.io.*;
import java.util.*;
public class Main {
    static int[] p;
    static int find(int x) { while (p[x] != x) { p[x] = p[p[x]]; x = p[x]; } return x; }
    public static void main(String[] args) throws IOException {
        DataInputStream in = new DataInputStream(new BufferedInputStream(System.in, 1 << 16));
        int n = next(in), q = next(in); p = new int[n + 1];
        for (int i = 0; i <= n; i++) p[i] = i;
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < q; i++) {
            int t = next(in), a = find(next(in)), b = find(next(in));
            if (t == 1) p[a] = b; else sb.append(a == b ? "YES" : "NO").append('\\n');
        }
        System.out.print(sb);
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
    n = [4, 20, 1000, 10000, 50000][size - 1]; q = [5, 30, 2000, 20000, 50000][size - 1]
    rows = [f"{rnd.choice([1, 2, 2])} {rnd.randint(1, n)} {rnd.randint(1, n)}" for _ in range(q - 1)] + [f"2 {rnd.randint(1, n)} {rnd.randint(1, n)}"]
    return f"{n} {q}\\n" + "\\n".join(rows) + "\\n"
""",
    "validator": """def check(inp):
    a = list(map(int, inp.split())); n, q = a[0], a[1]
    return 1 <= n <= 200000 and 1 <= q <= 200000 and len(a) == 2 + 3 * q and all(a[2+3*i] in (1, 2) and 1 <= a[3+3*i] <= n and 1 <= a[4+3*i] <= n for i in range(q))
""",
    "wrong_codes": [
        {"kind": "approach", "note": "합칠 때 대표가 아니라 원소를 바로 이음", "code": """import sys
data = sys.stdin.read().split(); n, q = int(data[0]), int(data[1]); p = list(range(n+1)); out = []
def find(x):
    while p[x] != x: x = p[x]
    return x
for i in range(q):
    t, a, b = int(data[2+3*i]), int(data[3+3*i]), int(data[4+3*i])
    if t == 1: p[a] = b
    else: out.append('YES' if find(a) == find(b) else 'NO')
print('\\n'.join(out))
"""},
        {"kind": "minor", "note": "출력을 소문자로 씀", "code": """import sys
data = sys.stdin.read().split(); n, q = int(data[0]), int(data[1]); p = list(range(n+1)); out = []
def find(x):
    while p[x] != x: p[x] = p[p[x]]; x = p[x]
    return x
for i in range(q):
    t, a, b = int(data[2+3*i]), int(data[3+3*i]), int(data[4+3*i]); ra, rb = find(a), find(b)
    if t == 1: p[ra] = rb
    else: out.append('yes' if ra == rb else 'no')
print('\\n'.join(out))
"""},
    ],
}

PIPELINE = {
    "key": "s3-gold4", "slot": 3, "tier": "골드4", "type": "위상 정렬", "title": "배포 파이프라인 완료 시간",
    "statement": """쉽잇의 배포 파이프라인에는 작업 N개가 있다. 작업 i는 tᵢ분이 걸린다. "a가 끝나야 b를 시작할 수 있다"는 조건이 M개 있다.
조건이 없는 작업들은 동시에 진행할 수 있다. 모든 작업이 끝나는 가장 이른 시각을 출력한다. 조건에 순환은 없다.

**입력**  첫 줄에 N M (1 ≤ N ≤ 100,000, 0 ≤ M ≤ 200,000). 둘째 줄에 t₁ … t_N (1 ≤ tᵢ ≤ 1,000). 다음 M줄에 a b
**출력**  모든 작업이 끝나는 시각""",
    "examples": [("4 3\n3 2 4 1\n1 2\n1 3\n3 4\n", "8\n")],
    "solution_python": """import sys
from collections import deque
def main():
    data = sys.stdin.buffer.read().split(); n, m = int(data[0]), int(data[1]); t = [0] + list(map(int, data[2:2+n]))
    adj = [[] for _ in range(n + 1)]; indeg = [0] * (n + 1); base = 2 + n
    for i in range(m):
        a, b = int(data[base+2*i]), int(data[base+2*i+1]); adj[a].append(b); indeg[b] += 1
    fin = [0] * (n + 1); start = [0] * (n + 1); q = deque(i for i in range(1, n + 1) if indeg[i] == 0)
    while q:
        u = q.popleft(); fin[u] = start[u] + t[u]
        for v in adj[u]:
            if fin[u] > start[v]: start[v] = fin[u]
            indeg[v] -= 1
            if indeg[v] == 0: q.append(v)
    print(max(fin))
main()
""",
    "solution_java": """import java.io.*;
import java.util.*;
public class Main {
    public static void main(String[] args) throws IOException {
        DataInputStream in = new DataInputStream(new BufferedInputStream(System.in, 1 << 16));
        int n = next(in), m = next(in); int[] t = new int[n + 1];
        for (int i = 1; i <= n; i++) t[i] = next(in);
        int[] head = new int[n + 1], nxt = new int[m], to = new int[m], indeg = new int[n + 1];
        Arrays.fill(head, -1);
        for (int i = 0; i < m; i++) { int a = next(in), b = next(in); to[i] = b; nxt[i] = head[a]; head[a] = i; indeg[b]++; }
        long[] start = new long[n + 1], fin = new long[n + 1]; int[] q = new int[n]; int qh = 0, qt = 0;
        for (int i = 1; i <= n; i++) if (indeg[i] == 0) q[qt++] = i;
        long best = 0;
        while (qh < qt) {
            int u = q[qh++]; fin[u] = start[u] + t[u]; best = Math.max(best, fin[u]);
            for (int e = head[u]; e != -1; e = nxt[e]) { int v = to[e]; start[v] = Math.max(start[v], fin[u]); if (--indeg[v] == 0) q[qt++] = v; }
        }
        System.out.println(best);
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
    n = [4, 15, 1000, 10000, 30000][size - 1]; m = [3, 25, 3000, 20000, 50000][size - 1]
    order = list(range(1, n + 1)); rnd.shuffle(order); pos = {v: i for i, v in enumerate(order)}
    edges = set()
    while len(edges) < min(m, n * (n - 1) // 2):
        a, b = rnd.randint(1, n), rnd.randint(1, n)
        if a != b:
            if pos[a] > pos[b]: a, b = b, a
            edges.add((a, b))
    t = ' '.join(str(rnd.randint(1, rnd.choice([1, 10, 1000]))) for _ in range(n))
    return f"{n} {len(edges)}\\n{t}\\n" + "".join(f"{a} {b}\\n" for a, b in edges)
""",
    "validator": """def check(inp):
    a = list(map(int, inp.split())); n, m = a[0], a[1]
    if not (1 <= n <= 100000 and 0 <= m <= 200000 and len(a) == 2 + n + 2 * m): return False
    return all(1 <= x <= 1000 for x in a[2:2+n]) and all(1 <= x <= n for x in a[2+n:])
""",
    "wrong_codes": [
        {"kind": "approach", "note": "작업 시간을 모두 더함 (동시 진행 무시)", "code": """import sys
data = sys.stdin.read().split(); n = int(data[0]); print(sum(map(int, data[2:2+n])))
"""},
        {"kind": "minor", "note": "여러 선행 작업 중 마지막으로 처리된 것만 기준으로 시작", "code": """import sys
from collections import deque
data = sys.stdin.read().split(); n, m = int(data[0]), int(data[1]); t = [0] + list(map(int, data[2:2+n]))
adj = [[] for _ in range(n+1)]; indeg = [0]*(n+1)
for i in range(m):
    a, b = int(data[2+n+2*i]), int(data[3+n+2*i]); adj[a].append(b); indeg[b] += 1
start = [0]*(n+1); fin = [0]*(n+1); q = deque(i for i in range(1, n+1) if indeg[i] == 0)
while q:
    u = q.popleft(); fin[u] = start[u] + t[u]
    for v in adj[u]:
        start[v] = fin[u]; indeg[v] -= 1
        if indeg[v] == 0: q.append(v)
print(max(fin))
"""},
    ],
}

UPGRADE = {
    "key": "s3-gold3", "slot": 3, "tier": "골드3", "type": "이분 탐색", "title": "버전 업그레이드 최대 단계",
    "statement": """톡허브는 서버 N대의 버전 기록 a₁ … a_N을 설치 순서대로 갖고 있다. 이 중 일부를 순서를 유지한 채 골라
**버전이 계속 올라가는**(앞보다 엄격히 큰) 업그레이드 경로를 만들 때, 고를 수 있는 서버 수의 최댓값을 출력한다.

**입력**  첫 줄에 N (1 ≤ N ≤ 200,000). 둘째 줄에 a₁ … a_N (1 ≤ aᵢ ≤ 10⁹)
**출력**  가장 긴 업그레이드 경로의 길이""",
    "examples": [("6\n10 20 10 30 20 50\n", "4\n")],
    "solution_python": """import sys, bisect
data = sys.stdin.buffer.read().split(); n = int(data[0]); tails = []
for x in map(int, data[1:1+n]):
    i = bisect.bisect_left(tails, x)
    if i == len(tails): tails.append(x)
    else: tails[i] = x
print(len(tails))
""",
    "solution_java": """import java.io.*;
import java.util.*;
public class Main {
    public static void main(String[] args) throws IOException {
        DataInputStream in = new DataInputStream(new BufferedInputStream(System.in, 1 << 16));
        int n = next(in); int[] tails = new int[n]; int len = 0;
        for (int i = 0; i < n; i++) {
            int x = next(in), lo = 0, hi = len;
            while (lo < hi) { int mid = (lo + hi) >>> 1; if (tails[mid] < x) lo = mid + 1; else hi = mid; }
            tails[lo] = x; if (lo == len) len++;
        }
        System.out.println(len);
    }
    static int next(DataInputStream in) throws IOException {
        int r = 0, b = in.read();
        while (b < '0') b = in.read();
        while (b >= '0') { r = r * 10 + b - '0'; b = in.read(); }
        return r;
    }
}
""",
    "brute_force": """import sys
data = sys.stdin.read().split(); n = int(data[0]); a = list(map(int, data[1:1+n])); d = [1]*n
for i in range(n):
    for j in range(i):
        if a[j] < a[i]: d[i] = max(d[i], d[j] + 1)
print(max(d))
""",
    "generator": """def gen(size, rnd):
    n = [6, 40, 2000, 10000, 50000][size - 1]; vmax = rnd.choice([5, 100, 10**9])
    return f"{n}\\n" + ' '.join(str(rnd.randint(1, vmax)) for _ in range(n)) + "\\n"
""",
    "validator": """def check(inp):
    a = list(map(int, inp.split())); n = a[0]
    return 1 <= n <= 200000 and len(a) == 1 + n and all(1 <= x <= 10**9 for x in a[1:])
""",
    "wrong_codes": [
        {"kind": "minor", "note": "같은 버전도 올라간 것으로 셈 (bisect_right)", "code": """import sys, bisect
data = sys.stdin.read().split(); n = int(data[0]); tails = []
for x in map(int, data[1:1+n]):
    i = bisect.bisect_right(tails, x)
    if i == len(tails): tails.append(x)
    else: tails[i] = x
print(len(tails))
"""},
        {"kind": "approach", "note": "O(N²) DP (큰 입력 시간 초과)", "code": """import sys
data = sys.stdin.read().split(); n = int(data[0]); a = list(map(int, data[1:1+n])); d = [1]*n
for i in range(n):
    for j in range(i):
        if a[j] < a[i] and d[j] + 1 > d[i]: d[i] = d[j] + 1
print(max(d))
"""},
    ],
}

BANDWIDTH = {
    "key": "s3-gold2", "slot": 3, "tier": "골드2", "type": "유니온 파인드", "title": "최대 대역폭 경로",
    "statement": """와치타워는 지점 N곳을 잇는 양방향 회선 M개를 감시한다. 회선 i의 대역폭은 cᵢ다.
지점 S에서 T로 데이터를 보낼 때, 경로의 대역폭은 경로에 있는 회선 대역폭의 **최솟값**이다.
S에서 T로 가는 경로 중 대역폭이 가장 큰 값을 출력한다. 갈 수 없으면 `-1`.

**입력**  첫 줄에 N M (2 ≤ N ≤ 100,000, 1 ≤ M ≤ 200,000). 다음 M줄에 u v c (1 ≤ c ≤ 10⁹). 마지막 줄에 S T (S ≠ T)
**출력**  최대 대역폭 또는 -1""",
    "examples": [("4 5\n1 2 5\n2 4 3\n1 3 4\n3 4 6\n1 4 1\n1 4\n", "4\n")],
    "solution_python": """import sys
def main():
    data = sys.stdin.buffer.read().split(); n, m = int(data[0]), int(data[1])
    e = sorted(((int(data[4+3*i]), int(data[2+3*i]), int(data[3+3*i])) for i in range(m)), reverse=True)
    s, t = int(data[2+3*m]), int(data[3+3*m]); p = list(range(n + 1))
    def find(x):
        while p[x] != x: p[x] = p[p[x]]; x = p[x]
        return x
    for c, u, v in e:
        p[find(u)] = find(v)
        if find(s) == find(t): print(c); return
    print(-1)
main()
""",
    "solution_java": """import java.io.*;
import java.util.*;
public class Main {
    static int[] p;
    static int find(int x) { while (p[x] != x) { p[x] = p[p[x]]; x = p[x]; } return x; }
    public static void main(String[] args) throws IOException {
        DataInputStream in = new DataInputStream(new BufferedInputStream(System.in, 1 << 16));
        int n = next(in), m = next(in); long[][] e = new long[m][];
        for (int i = 0; i < m; i++) { int u = next(in), v = next(in), c = next(in); e[i] = new long[]{c, u, v}; }
        int s = next(in), t = next(in); Arrays.sort(e, (a, b) -> Long.compare(b[0], a[0]));
        p = new int[n + 1]; for (int i = 0; i <= n; i++) p[i] = i;
        for (long[] x : e) { p[find((int) x[1])] = find((int) x[2]); if (find(s) == find(t)) { System.out.println(x[0]); return; } }
        System.out.println(-1);
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
    n = [4, 15, 1000, 10000, 30000][size - 1]; m = [5, 25, 3000, 20000, 30000][size - 1]; cmax = rnd.choice([3, 100, 10**9])
    rows = []
    for _ in range(m):
        u = rnd.randint(1, n); v = rnd.randint(1, n - 1); v = v + 1 if v >= u else v
        rows.append(f"{u} {v} {rnd.randint(1, cmax)}")
    s = rnd.randint(1, n); t = rnd.randint(1, n - 1); t = t + 1 if t >= s else t
    return f"{n} {m}\\n" + "\\n".join(rows) + f"\\n{s} {t}\\n"
""",
    "validator": """def check(inp):
    a = list(map(int, inp.split())); n, m = a[0], a[1]
    if not (2 <= n <= 100000 and 1 <= m <= 200000 and len(a) == 2 + 3 * m + 2): return False
    return all(1 <= a[2+3*i] <= n and 1 <= a[3+3*i] <= n and 1 <= a[4+3*i] <= 10**9 for i in range(m)) and a[-2] != a[-1]
""",
    "wrong_codes": [
        {"kind": "approach", "note": "최단 경로(회선 수)로 가서 그 경로의 최솟값을 냄", "code": """import sys
from collections import deque
data = sys.stdin.read().split(); n, m = int(data[0]), int(data[1]); adj = [[] for _ in range(n+1)]
for i in range(m):
    u, v, c = int(data[2+3*i]), int(data[3+3*i]), int(data[4+3*i]); adj[u].append((v, c)); adj[v].append((u, c))
s, t = int(data[2+3*m]), int(data[3+3*m]); best = {s: float('inf')}; q = deque([s])
while q:
    u = q.popleft()
    for v, c in adj[u]:
        if v not in best: best[v] = min(best[u], c); q.append(v)
print(best.get(t, -1))
"""},
        {"kind": "minor", "note": "가장 큰 회선 하나만 보고 답함", "code": """import sys
data = sys.stdin.read().split(); m = int(data[1]); print(max(int(data[4+3*i]) for i in range(m)))
"""},
    ],
}

PROBLEMS = [SORT, GROUP, PIPELINE, UPGRADE, BANDWIDTH]
