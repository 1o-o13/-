"""2번 (응용형, 기본 골드 3) 문제 모음. 프로그래머스 응용 유형을 새벽소프트 업무 상황으로 새로 쓴 문제 (원문 복제 아님)."""

WINDOW = {
    "key": "s2-window", "slot": 2, "tier": "골드3", "type": "슬라이딩 윈도우", "title": "알림 폭주 구간 찾기",
    "statement": """알림센터는 알림 N건의 기록을 시간순으로 갖고 있다. i번째 알림은 시각 tᵢ(초)에 사용자 uᵢ에게 보냈다.
길이가 K초인 구간 [x, x+K) 중에서, 그 안에 알림을 받은 **서로 다른 사용자 수**가 가장 많은 구간의 사용자 수를 출력한다.

**입력**  첫 줄에 N K (1 ≤ N ≤ 200,000, 1 ≤ K ≤ 10⁹). 다음 N줄에 tᵢ uᵢ (0 ≤ tᵢ ≤ 10⁹, tᵢ는 줄어들지 않음, 1 ≤ uᵢ ≤ 10⁹)
**출력**  서로 다른 사용자 수의 최댓값""",
    "examples": [("6 10\n0 1\n3 2\n5 1\n9 3\n12 4\n25 1\n", "4\n"), ("3 1\n5 7\n5 8\n6 9\n", "2\n")],
    "solution_python": """import sys
def main():
    data = sys.stdin.buffer.read().split(); n, k = int(data[0]), int(data[1])
    t = data[2::2]; u = data[3::2]; t = list(map(int, t)); u = list(map(int, u))
    cnt = {}; lo = 0; best = 0
    for hi in range(n):
        cnt[u[hi]] = cnt.get(u[hi], 0) + 1
        while t[hi] - t[lo] >= k:
            c = cnt[u[lo]] - 1
            if c: cnt[u[lo]] = c
            else: del cnt[u[lo]]
            lo += 1
        if len(cnt) > best: best = len(cnt)
    print(best)
main()
""",
    "solution_java": """import java.io.*;
import java.util.*;
public class Main {
    public static void main(String[] args) throws IOException {
        DataInputStream in = new DataInputStream(new BufferedInputStream(System.in, 1 << 16));
        int n = (int) next(in); long k = next(in);
        long[] t = new long[n]; long[] u = new long[n];
        for (int i = 0; i < n; i++) { t[i] = next(in); u[i] = next(in); }
        HashMap<Long, Integer> cnt = new HashMap<>();
        int lo = 0, best = 0;
        for (int hi = 0; hi < n; hi++) {
            cnt.merge(u[hi], 1, Integer::sum);
            while (t[hi] - t[lo] >= k) {
                int c = cnt.get(u[lo]) - 1;
                if (c == 0) cnt.remove(u[lo]); else cnt.put(u[lo], c);
                lo++;
            }
            best = Math.max(best, cnt.size());
        }
        System.out.println(best);
    }
    static long next(DataInputStream in) throws IOException {
        long r = 0; int b = in.read();
        while (b < '0') b = in.read();
        while (b >= '0') { r = r * 10 + b - '0'; b = in.read(); }
        return r;
    }
}
""",
    "brute_force": """import sys
data = sys.stdin.read().split(); n, k = int(data[0]), int(data[1]); ev = [(int(data[2+2*i]), int(data[3+2*i])) for i in range(n)]
print(max(len({u for t, u in ev if x <= t < x + k}) for x, _ in ev))
""",
    "generator": """def gen(size, rnd):
    n = [5, 30, 2000, 10000, 50000][size - 1]
    users = rnd.choice([3, 50, n])
    t = 0; rows = []
    for _ in range(n):
        t += rnd.choice([0, 0, 1, 2, 5, 30])
        rows.append(f"{t} {rnd.randint(1, users)}")
    k = rnd.choice([1, 10, 100, 10**9])
    return f"{n} {k}\\n" + "\\n".join(rows) + "\\n"
""",
    "validator": """def check(inp):
    a = list(map(int, inp.split())); n, k = a[0], a[1]
    if not (1 <= n <= 200000 and 1 <= k <= 10**9 and len(a) == 2 + 2 * n): return False
    t = a[2::2]; u = a[3::2]
    return all(0 <= x <= 10**9 for x in t) and all(t[i] <= t[i+1] for i in range(n-1)) and all(1 <= x <= 10**9 for x in u)
""",
    "wrong_codes": [
        {"kind": "minor", "note": "구간 끝을 포함함 (t - t_lo > K)", "code": """import sys
data = sys.stdin.read().split(); n, k = int(data[0]), int(data[1]); t = list(map(int, data[2::2])); u = list(map(int, data[3::2]))
cnt = {}; lo = 0; best = 0
for hi in range(n):
    cnt[u[hi]] = cnt.get(u[hi], 0) + 1
    while t[hi] - t[lo] > k:
        cnt[u[lo]] -= 1
        if not cnt[u[lo]]: del cnt[u[lo]]
        lo += 1
    best = max(best, len(cnt))
print(best)
"""},
        {"kind": "approach", "note": "사용자 수 대신 알림 건수를 셈", "code": """import sys
data = sys.stdin.read().split(); n, k = int(data[0]), int(data[1]); t = list(map(int, data[2::2])); lo = 0; best = 0
for hi in range(n):
    while t[hi] - t[lo] >= k: lo += 1
    best = max(best, hi - lo + 1)
print(best)
"""},
        {"kind": "approach", "note": "구간마다 다시 세는 O(N²) (큰 입력 시간 초과)", "code": """import sys
data = sys.stdin.read().split(); n, k = int(data[0]), int(data[1]); t = list(map(int, data[2::2])); u = list(map(int, data[3::2])); best = 0
for i in range(n):
    s = set(); j = i
    while j < n and t[j] - t[i] < k: s.add(u[j]); j += 1
    best = max(best, len(s))
print(best)
"""},
    ],
}

STOCK = {
    "key": "s2-stock", "slot": 2, "tier": "골드3", "type": "우선순위 큐", "title": "재고 예약 처리 순서",
    "statement": """스톡키퍼는 예약 요청 N건을 처리한다. i번째 요청은 시각 aᵢ에 들어오고, 처리에 dᵢ초가 걸리며, 우선순위가 pᵢ이다.
작업자는 한 명이고 한 번에 한 요청만 처리한다. 작업자가 쉬고 있을 때 **이미 들어와 기다리는 요청 중**
우선순위가 가장 높은 것을 고른다. 우선순위가 같으면 먼저 들어온 것, 그것도 같으면 번호가 작은 것을 고른다.
기다리는 요청이 없으면 다음 요청이 들어올 때까지 쉰다. 요청이 처리되는 순서대로 번호를 출력한다.

**입력**  첫 줄에 N (1 ≤ N ≤ 200,000). 다음 N줄에 aᵢ dᵢ pᵢ (0 ≤ aᵢ ≤ 10⁹, 1 ≤ dᵢ ≤ 10⁴, 1 ≤ pᵢ ≤ 10⁹). 번호는 1부터.
**출력**  처리 순서를 공백으로 구분해 한 줄에""",
    "examples": [("4\n0 3 1\n1 1 5\n2 1 5\n10 1 1\n", "1 2 3 4\n"), ("3\n0 5 1\n0 5 3\n1 1 9\n", "2 3 1\n")],
    "solution_python": """import sys, heapq
def main():
    data = sys.stdin.buffer.read().split(); n = int(data[0])
    req = sorted((int(data[1+3*i]), i + 1, int(data[2+3*i]), int(data[3+3*i])) for i in range(n))
    pq = []; now = 0; j = 0; out = []
    while len(out) < n:
        if not pq and j < n and req[j][0] > now: now = req[j][0]
        while j < n and req[j][0] <= now:
            a, idx, d, p = req[j]; heapq.heappush(pq, (-p, a, idx, d)); j += 1
        _, a, idx, d = heapq.heappop(pq); now += d; out.append(idx)
    print(' '.join(map(str, out)))
main()
""",
    "solution_java": """import java.io.*;
import java.util.*;
public class Main {
    public static void main(String[] args) throws IOException {
        DataInputStream in = new DataInputStream(new BufferedInputStream(System.in, 1 << 16));
        int n = (int) next(in);
        long[][] r = new long[n][];
        for (int i = 0; i < n; i++) { long a = next(in), d = next(in), p = next(in); r[i] = new long[]{a, i + 1, d, p}; }
        Arrays.sort(r, (x, y) -> x[0] != y[0] ? Long.compare(x[0], y[0]) : Long.compare(x[1], y[1]));
        PriorityQueue<long[]> pq = new PriorityQueue<>((x, y) -> x[3] != y[3] ? Long.compare(y[3], x[3])
            : x[0] != y[0] ? Long.compare(x[0], y[0]) : Long.compare(x[1], y[1]));
        long now = 0; int j = 0, done = 0; StringBuilder sb = new StringBuilder();
        while (done < n) {
            if (pq.isEmpty() && j < n && r[j][0] > now) now = r[j][0];
            while (j < n && r[j][0] <= now) pq.add(r[j++]);
            long[] c = pq.poll(); now += c[2]; done++;
            if (sb.length() > 0) sb.append(' ');
            sb.append(c[1]);
        }
        System.out.println(sb);
    }
    static long next(DataInputStream in) throws IOException {
        long v = 0; int b = in.read();
        while (b < '0') b = in.read();
        while (b >= '0') { v = v * 10 + b - '0'; b = in.read(); }
        return v;
    }
}
""",
    "brute_force": """import sys
data = sys.stdin.read().split(); n = int(data[0]); req = [(int(data[1+3*i]), int(data[2+3*i]), int(data[3+3*i]), i+1) for i in range(n)]
left = set(range(n)); now = 0; out = []
while left:
    ready = [i for i in left if req[i][0] <= now]
    if not ready: now = min(req[i][0] for i in left); continue
    i = min(ready, key=lambda i: (-req[i][2], req[i][0], req[i][3])); left.remove(i); now += req[i][1]; out.append(req[i][3])
print(' '.join(map(str, out)))
""",
    "generator": """def gen(size, rnd):
    n = [4, 25, 2000, 10000, 30000][size - 1]
    pmax = rnd.choice([2, 10, 10**9]); gap = rnd.choice([0, 1, 3, 20])
    a = 0; rows = []
    for _ in range(n):
        a += rnd.randint(0, gap); rows.append(f"{a} {rnd.randint(1, rnd.choice([1, 5, 10000]))} {rnd.randint(1, pmax)}")
    rnd.shuffle(rows)
    return f"{n}\\n" + "\\n".join(rows) + "\\n"
""",
    "validator": """def check(inp):
    a = list(map(int, inp.split())); n = a[0]
    if not (1 <= n <= 200000 and len(a) == 1 + 3 * n): return False
    return all(0 <= a[1+3*i] <= 10**9 and 1 <= a[2+3*i] <= 10**4 and 1 <= a[3+3*i] <= 10**9 for i in range(n))
""",
    "wrong_codes": [
        {"kind": "minor", "note": "같은 우선순위에서 번호 순으로만 고름 (도착 시각 무시)", "code": """import sys, heapq
data = sys.stdin.read().split(); n = int(data[0]); req = sorted((int(data[1+3*i]), i+1, int(data[2+3*i]), int(data[3+3*i])) for i in range(n))
pq = []; now = 0; j = 0; out = []
while len(out) < n:
    if not pq and j < n and req[j][0] > now: now = req[j][0]
    while j < n and req[j][0] <= now:
        a, idx, d, p = req[j]; heapq.heappush(pq, (-p, idx, d)); j += 1
    _, idx, d = heapq.heappop(pq); now += d; out.append(idx)
print(' '.join(map(str, out)))
"""},
        {"kind": "approach", "note": "들어온 순서대로만 처리 (우선순위 무시)", "code": """import sys
data = sys.stdin.read().split(); n = int(data[0]); req = sorted((int(data[1+3*i]), i+1) for i in range(n))
print(' '.join(str(i) for _, i in req))
"""},
        {"kind": "minor", "note": "쉬는 동안 시각을 다음 요청으로 옮기지 않음", "code": """import sys, heapq
data = sys.stdin.read().split(); n = int(data[0]); req = sorted((int(data[1+3*i]), i+1, int(data[2+3*i]), int(data[3+3*i])) for i in range(n))
pq = []; now = 0; j = 0; out = []
while len(out) < n:
    while j < n and (req[j][0] <= now or not pq):
        a, idx, d, p = req[j]; heapq.heappush(pq, (-p, a, idx, d)); j += 1
    _, a, idx, d = heapq.heappop(pq); now = now + d; out.append(idx)
print(' '.join(map(str, out)))
"""},
    ],
}

PROBLEMS = [WINDOW, STOCK]
