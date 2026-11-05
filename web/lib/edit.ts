// 답변 인식 글 수정 비율 (11/11). 서버(api/interview/store.edit_ratio, difflib)가 최종 판단하고, 화면은 바뀐 정도를 미리 보여 준다.
// 띄어쓰기는 세지 않는다. 0 = 같음, 1 = 전부 다름
export const EDIT_MAX = 0.3;

export function editRatio(original: string, edited: string): number {
  const a = original.replace(/\s+/g, ""), b = edited.replace(/\s+/g, "");
  if (!a) return b ? 1 : 0;
  // 최장 공통 부분 수열(LCS) 길이로 비슷한 정도: 2·LCS / (|a|+|b|) — difflib ratio와 거의 같다
  let prev: number[] = new Array(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i++) {
    const cur = [0];
    for (let j = 1; j <= b.length; j++) cur[j] = a[i - 1] === b[j - 1] ? prev[j - 1] + 1 : Math.max(prev[j], cur[j - 1]);
    prev = cur;
  }
  return Math.round((1 - (2 * prev[b.length]) / (a.length + b.length)) * 1000) / 1000;
}
