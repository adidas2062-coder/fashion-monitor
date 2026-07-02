"""기획전 시그널 점수 체계 정기 감사(재보정) 도구.

보유한 스냅샷 전체에 현재 timing_signal 로직을 소급 적용해:
  1. 일별 시그널 수·레벨 분포 (과잉 여부)
  2. 지표별 발동률·평균 기여 (포화/죽은 지표 탐지)
  3. day3/day7 실제 랭킹 변화 기준 백테스트 적중률 (절대 + 시장효과 차감 상대)
  4. 점수 ↔ 실제 성과 상관계수 (점수 서열의 변별력)
를 출력한다. 배점을 조정한 뒤 이 도구로 전후를 비교할 것.

사용법: cd ~/fashion-monitor && python3 signal_score_audit.py
권장 주기: 2~4주마다 (백테스트 표본이 쌓일수록 판단이 정확해짐)
"""
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "/Users/jeonjuwon/fashion-monitor")

from analyzers import rank_diff, timing_signal, category_mix, signal_backtest
from exporters import snapshot_store


def _daily(items):
    return [i for i in items if i.get("period", "1일") == "1일"]


def _corr(pairs):
    n = len(pairs)
    if n < 5:
        return None
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    cov = sum((x - mx) * (y - my) for x, y in pairs) / n
    sx = (sum((x - mx) ** 2 for x, _ in pairs) / n) ** 0.5
    sy = (sum((y - my) ** 2 for _, y in pairs) / n) ** 0.5
    return cov / (sx * sy) if sx and sy else 0.0


def simulate():
    """스냅샷 전 기간에 현재 로직을 소급 적용해 일별 시그널을 생성한다."""
    rank_dates = snapshot_store.available_dates("musinsa_rankings")
    rankings_all = {d: snapshot_store.load("musinsa_rankings", d) for d in rank_dates}
    weather_dates = set(snapshot_store.available_dates("weather"))
    ob_dates = set(snapshot_store.available_dates("musinsa_overall_best"))

    by_date = {}
    for d in snapshot_store.available_dates("trends"):
        if d not in rank_dates:
            continue
        idx = rank_dates.index(d)
        if idx <= 0:
            continue
        trend_data = snapshot_store.load("trends", d)
        realtime = [t for t in trend_data if t.get("platform") == "무신사_검색어"]
        rr = rank_diff.analyze(_daily(rankings_all[d]), _daily(rankings_all[rank_dates[idx - 1]]))
        history = [rankings_all[x] for x in rank_dates[:idx + 1]][-14:]
        weather = (snapshot_store.load("weather", d) or [{}])[0] if d in weather_dates else None
        if d in ob_dates:
            ob = _daily(snapshot_store.load("musinsa_overall_best", d))
            cw, _ = category_mix.compute_category_weight(
                ob, snapshot_store.load("musinsa_overall", d))
        else:
            cw = {}
        by_date[d] = timing_signal.detect(
            trend_data, rr, None, weather, None, history, cw, realtime)
    return by_date, rankings_all, rank_dates


def main():
    by_date, rankings_all, rank_dates = simulate()

    print("=== 일별 시그널 수/레벨 ===")
    for d, sigs in by_date.items():
        lv = Counter("긴급" if s["score"] >= 80 else "주의" if s["score"] >= 50 else "참고"
                     for s in sigs)
        print(f"{d}: {len(sigs)}건 {sorted((s['score'] for s in sigs), reverse=True)} {dict(lv)}")
    all_sigs = [s for sigs in by_date.values() for s in sigs]
    print(f"\n총 {len(all_sigs)}건, 일평균 {len(all_sigs) / max(1, len(by_date)):.1f}건")

    contrib = defaultdict(list)
    for s in all_sigs:
        for k, v in s["score_breakdown"].items():
            contrib[k].append(v)
    print("\n=== 지표별: 발동률 / 발동 시 평균 기여 (포화·사망 지표 점검) ===")
    for k, vals in sorted(contrib.items()):
        nz = [v for v in vals if v]
        rate = len(nz) / len(vals) * 100 if vals else 0
        avg = sum(nz) / len(nz) if nz else 0
        flag = " ⚠️포화" if rate > 90 and avg > 10 else (" ⚠️사망" if rate < 5 else "")
        print(f"  {k:22s} 발동 {rate:4.0f}% | 평균 {avg:+.1f}점{flag}")

    # day7 평가 가능한 날짜만 백테스트 (마지막 랭킹일 기준 -7일)
    from datetime import date, timedelta
    last = date.fromisoformat(rank_dates[-1])
    cutoff = (last - timedelta(days=7)).isoformat()
    rows = signal_backtest.evaluate(
        {d: v for d, v in by_date.items() if d <= cutoff}, rankings_all)
    stats = signal_backtest.aggregate_stats(rows)
    o, orel = stats.get("overall", {}), stats.get("overall_relative", {})
    print(f"\n=== 백테스트 (~{cutoff} 발생분, day7 실측) ===")
    print(f"  표본 {o.get('count', 0)}건 | 절대 적중 {o.get('hit_rate', 0):.0f}%"
          f" / 적중+부분 {o.get('hit_or_partial_rate', 0):.0f}%")
    print(f"  상대(시장효과 차감) 적중 {orel.get('hit_rate', 0):.0f}%"
          f" / 적중+부분 {orel.get('hit_or_partial_rate', 0):.0f}%")
    for bucket, v in sorted(stats.get("by_score_bucket_relative", {}).items()):
        print(f"  [상대] 점수 {bucket}: 적중 {v.get('hit_rate', 0):.0f}% (n={v.get('count', 0)})")

    r_abs = _corr([(r["score"], r["day7_change"]) for r in rows
                   if r.get("day7_change") is not None and r.get("score") is not None])
    r_rel = _corr([(r["score"], r["relative_day7_change"]) for r in rows
                   if r.get("relative_day7_change") is not None and r.get("score") is not None])
    if r_abs is not None:
        print(f"\n점수 ↔ day7 변화 상관 r = {r_abs:+.2f} | 상대 변화 상관 r = {r_rel:+.2f}")
        print("(r이 +0.3 이상으로 올라오면 점수 서열을 우선순위 판단에 써도 된다는 뜻)")


if __name__ == "__main__":
    main()
