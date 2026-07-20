"""
패션 MD 모니터링 자동화 — 메인 실행 진입점.

매일 오전 10시 cron job으로 실행한다.
각 모듈은 독립 실행 — 하나 실패해도 나머지 계속 진행.

실행:
    python3 main.py              # 전체 실행
    python3 main.py --dry-run    # 수집만 (노션/카카오 저장 생략)
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta

import config

# ── 로그 설정 ─────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("main")


# ── 단계별 실행 래퍼 ─────────────────────────────────────────────────────────

_fail_log: list = []   # 실패한 모듈 추적


def _run(label: str, func, *args, **kwargs):
    """함수 실행 — 예외가 발생해도 로그만 남기고 계속."""
    try:
        logger.info("▶ %s 시작", label)
        result = func(*args, **kwargs)
        logger.info("✅ %s 완료", label)
        return result
    except Exception as exc:
        logger.error("❌ %s 실패: %s", label, exc, exc_info=True)
        _fail_log.append(label)
        return None


def _check_anomaly(label: str, data, min_count: int = 1) -> bool:
    """데이터 이상 감지 — 수집 건수가 0이면 True(이상)."""
    count = len(data) if data else 0
    if count < min_count:
        logger.warning("⚠️ 데이터 이상 감지: %s → %d건 (최소 %d건 필요)", label, count, min_count)
        _fail_log.append(f"{label}(데이터 없음)")
        return True
    return False


def _send_failure_alert(fails: list) -> None:
    """수집 실패 슬랙 알림."""
    if not fails:
        return
    try:
        from exporters.slack_notify import _post
        _post({"text": f"⚠️ *패션 모니터 수집 오류*\n실패 항목: {', '.join(fails)}"})
    except Exception as e:
        logger.warning("실패 알림 발송 오류: %s", e)


# ── 파이프라인 ────────────────────────────────────────────────────────────────

def _collect_periods() -> list:
    """날짜 조건에 따라 오늘 수집할 기간 목록 결정."""
    today = date.today()
    is_monday          = today.weekday() == 0
    is_first_monday    = is_monday and today.day <= 7

    periods = ["DAILY"]                           # 매일
    if is_monday:
        periods.append("WEEKLY")                  # 매주 월요일
    if is_first_monday:
        periods.append("MONTHLY")                 # 매월 첫째주 월요일
    return periods


def run(dry_run: bool = False) -> None:
    today = date.today()

    # ── 하루 1회 실행 가드 (중복 실행 방지) ──────────────────────────────────
    guard_file = f"/tmp/fashion_monitor_{today}.guard"
    if not dry_run:
        if os.path.exists(guard_file):
            logger.warning("⚠️ 오늘(%s) 이미 실행됨 — 중복 실행 방지로 종료. 강제 실행은 --dry-run 사용", today)
            return
        open(guard_file, "w").close()

    periods = _collect_periods()
    logger.info("=" * 60)
    logger.info("패션 모니터링 시작 (%s) 수집기간=%s%s",
                today, periods, "  [DRY RUN]" if dry_run else "")
    logger.info("=" * 60)

    # ── 1. 수집 ───────────────────────────────────────────────────────────────
    from collectors import musinsa, google_trends, naver_datalab, instagram

    # 노션 저장용 — 남성 필터, 오늘 스케줄 기간만
    today_rankings = _run("무신사 남성 랭킹 수집", musinsa.collect, periods=periods, gf="M") or []
    time.sleep(config.REQUEST_DELAY)

    # 대시보드는 남성·전체 모두 같은 기간과 카테고리 범위를 제공한다.
    all_periods = ["DAILY", "WEEKLY", "MONTHLY"]
    all_overall = _run(
        "무신사 전체 랭킹 수집",
        musinsa.collect,
        periods=all_periods,
        gf="A",
    ) or []
    time.sleep(config.REQUEST_DELAY)

    # 카테고리(상의/아우터/바지)를 안 가린 진짜 통합 "전체 베스트" 랭킹.
    # category_mix 분석용: gf=A, DAILY, 100건
    overall_best = _run(
        "무신사 통합 전체 베스트 수집",
        musinsa.fetch_category,
        "전체", "", "DAILY", 100,
        gf="A",
    ) or []
    time.sleep(config.REQUEST_DELAY)

    # 대시보드 "전체" 탭용 — 1일/주간/월간 × 남성(gf=M) / 전체(gf=A)
    male_best: list = []
    overall_best_tabs: list = []
    for _p in all_periods:
        _items = _run(f"무신사 남성 전체 베스트 {_p}", musinsa.fetch_category, "전체", "", _p, 30, gf="M") or []
        male_best.extend(_items)
        time.sleep(config.REQUEST_DELAY)
        _items = _run(f"무신사 전체 전체 베스트 {_p}", musinsa.fetch_category, "전체", "", _p, 30, gf="A") or []
        overall_best_tabs.extend(_items)
        time.sleep(config.REQUEST_DELAY)

    # 대시보드용 — 항상 3개 기간 모두 수집 (표시 전용, 노션 미저장)
    if set(periods) == set(all_periods):
        dashboard_rankings = today_rankings
    else:
        missing = [p for p in all_periods if p not in periods]
        logger.info("대시보드용 추가 수집: %s", missing)
        extra = _run("대시보드용 추가 기간 수집", musinsa.collect, periods=missing, gf="M") or []
        dashboard_rankings = today_rankings + extra
        time.sleep(config.REQUEST_DELAY)

    # 29CM 남성 랭킹 수집 (매일)
    from collectors import cm29_ranking, musinsa_brand_ranking, musinsa_events, cm29_events, musinsa_magazine
    cm29_data    = _run("29CM 남성 랭킹 수집",    cm29_ranking.collect) or []
    brand_ranks  = _run("무신사 브랜드 랭킹 수집",  musinsa_brand_ranking.collect) or []
    brand_ranks_formal = _run("무신사 컨템포러리포멀 브랜드 랭킹 수집", musinsa_brand_ranking.collect_formal) or []
    musinsa_evs  = _run("무신사 기획전 수집",       musinsa_events.collect) or []
    cm29_evs     = _run("29CM 에디션 수집",        cm29_events.collect) or []
    mag_items    = _run("무신사 매거진 수집",       musinsa_magazine.collect) or []

    # 이상 감지
    _check_anomaly("무신사 남성 랭킹", today_rankings, min_count=30)
    _check_anomaly("29CM 랭킹", cm29_data, min_count=5)
    time.sleep(config.REQUEST_DELAY)

    google_data  = _run("구글 트렌드 수집", google_trends.collect) or []
    time.sleep(config.REQUEST_DELAY)

    naver_data   = _run("네이버 데이터랩 수집", naver_datalab.collect) or []
    time.sleep(config.REQUEST_DELAY)

    insta_data   = _run("인스타그램 수집", instagram.collect) or []

    # 무신사 검색어 랭킹
    from collectors import musinsa_keywords, musinsa_archive, weather
    keyword_data = _run("무신사 검색어 랭킹 수집", musinsa_keywords.collect) or []
    time.sleep(config.REQUEST_DELAY)

    # 날씨
    weather_data = _run("날씨 수집", weather.collect) or {}

    # 작년 동기 아카이브 (YoY 비교용)
    archive_data = _run("작년 동기 아카이브 수집", musinsa_archive.collect) or []

    trend_data   = google_data + naver_data + insta_data + keyword_data
    logger.info("트렌드 데이터 합계: %d건 (검색어 %d건 포함)", len(trend_data), len(keyword_data))

    # 비교는 같은 기간끼리 수행한다. 운영 시그널은 일간 랭킹만 사용한다.
    from exporters import snapshot_store
    previous_dashboard_rankings = snapshot_store.load_latest_before(
        "musinsa_rankings", today.isoformat()
    )
    previous_daily_rankings = [
        item for item in previous_dashboard_rankings
        if item.get("period", "1일") == "1일"
    ]
    previous_cm29 = snapshot_store.load_latest_before(
        "cm29_rankings", today.isoformat()
    )
    previous_overall = snapshot_store.load_latest_before(
        "musinsa_overall", today.isoformat()
    )
    previous_male_best = snapshot_store.load_latest_before(
        "musinsa_best", today.isoformat()
    )
    previous_overall_best = snapshot_store.load_latest_before(
        "musinsa_overall_best", today.isoformat()
    )

    # 날짜별 전체 원본은 노션 저장 여부와 무관하게 항상 보존한다.
    _run("무신사 전체 스냅샷 저장", snapshot_store.save, "musinsa_rankings", dashboard_rankings)
    _run("무신사 전체성별 스냅샷 저장", snapshot_store.save, "musinsa_overall", all_overall)
    _run("무신사 남성 통합 베스트 스냅샷 저장", snapshot_store.save, "musinsa_best", male_best)
    _run("무신사 전체 통합 베스트 스냅샷 저장", snapshot_store.save, "musinsa_overall_best", overall_best_tabs)
    _run("29CM 스냅샷 저장", snapshot_store.save, "cm29_rankings", cm29_data)
    _run("트렌드 스냅샷 저장", snapshot_store.save, "trends", trend_data)
    _run("실시간 검색어 스냅샷 저장", snapshot_store.save, "musinsa_keywords", keyword_data)
    ranking_history_14d = snapshot_store.load_history("musinsa_rankings", limit=14)
    trend_history_28d = snapshot_store.load_history("trends", limit=28)

    # ── 2. 직전 수집일 랭킹 조회 (순위 변동 비교용) ──────────────────────────
    from exporters import notion_exporter

    previous_cm29 = previous_cm29 or (
        _run(
            "노션 29CM 직전 수집일 랭킹 조회",
            notion_exporter.fetch_latest_cm29_before,
            today,
        ) or []
    )

    yesterday_rankings = previous_daily_rankings or (
        _run(
            "노션 직전 수집일 랭킹 조회",
            notion_exporter.fetch_latest_rankings_before,
            today,
        ) or []
    )

    # ── 3. 분석 ───────────────────────────────────────────────────────────────
    from analyzers import rank_diff, new_entry, price_analysis, brand_tracker, timing_signal

    today_daily_rankings = [
        item for item in today_rankings
        if item.get("period", "1일") == "1일"
    ]
    rank_result  = _run("순위 변동 분석", rank_diff.analyze, today_daily_rankings, yesterday_rankings) or {
        "items": today_daily_rankings, "top_risers": [], "top_fallers": [],
        "new_entries": [], "dropouts": [], "summary": "",
        "baseline_available": False,
    }
    time.sleep(0.5)

    # 신규 진입 상세 수집 — 비교 기준이 없는 첫 실행은 신규 판정을 보류한다.
    _MAX_NEW_ENTRY_DETAIL = 30
    raw_new = rank_result.get("new_entries", [])
    if len(raw_new) > _MAX_NEW_ENTRY_DETAIL:
        logger.info("신규 진입 %d건 중 상위 %d건만 상세 수집 (첫 실행 또는 대량 진입)", len(raw_new), _MAX_NEW_ENTRY_DETAIL)
        raw_new = raw_new[:_MAX_NEW_ENTRY_DETAIL]
    new_entries  = _run("신규 진입 상품 상세 수집", new_entry.enrich, raw_new) or []
    time.sleep(config.REQUEST_DELAY)

    price_result = _run("가격대 분포 분석", price_analysis.analyze, today_daily_rankings, yesterday_rankings) or {}
    brand_result = _run("브랜드 트래킹", brand_tracker.analyze, today_daily_rankings, yesterday_rankings) or []

    # ── 과거 시그널 백테스트 — timing_signal.detect()보다 먼저 계산해
    #    적중률 가중치를 오늘의 스코어링/MD 액션에 피드백한다.
    from analyzers import signal_backtest
    signal_dates = snapshot_store.available_dates("signals")
    signals_by_date = {
        d: snapshot_store.load("signals", d) for d in signal_dates
    }
    # +3일/+7일 정확한 날짜에 수집 실패(휴일 등)가 있어도 백테스트가 보류 상태로
    # 멈추지 않도록, signal_backtest._nearest_snapshot_date()가 탐색할 수 있는
    # 여유분(최대 +3일)까지 함께 로드 대상에 포함한다.
    required_ranking_dates = set()
    for signal_date in signal_dates:
        base = date.fromisoformat(signal_date)
        required_ranking_dates.add(signal_date)
        for target_days in (3, 7):
            for fallback_offset in range(0, 4):
                required_ranking_dates.add(
                    (base + timedelta(days=target_days + fallback_offset)).isoformat()
                )
    available_ranking_dates = set(
        snapshot_store.available_dates("musinsa_rankings")
    )
    backtests = _run(
        "과거 시그널 백테스트",
        signal_backtest.evaluate,
        signals_by_date,
        {
            d: snapshot_store.load("musinsa_rankings", d)
            for d in required_ranking_dates
            if d in available_ranking_dates
        },
    ) or []
    backtest_stats = _run("백테스트 통계 집계", signal_backtest.aggregate_stats, backtests) or {}
    backtest_keyword_weights = _run(
        "백테스트 키워드 가중치 산출", signal_backtest.keyword_hit_weights, backtests
    ) or {}

    from analyzers import category_mix
    category_weights, category_weight_samples = _run(
        "카테고리 실제 비중 산출 (통합 전체 베스트 기준)",
        category_mix.compute_category_weight,
        overall_best, all_overall,
    ) or ({}, {})
    logger.info("카테고리 비중 가중치: %s (매칭 표본: %s)", category_weights, category_weight_samples)

    signals      = _run(
        "기획전 시그널 감지",
        timing_signal.detect,
        trend_data, rank_result, archive_data, weather_data,
        backtest_keyword_weights,
        ranking_history_14d,
        category_weights,
        keyword_data,   # 무신사 실시간 검색어 — 내부 근거 게이트/점수에 사용
    ) or []

    # 신규 모듈
    from analyzers import material_color_trend, category_growth, magazine_trend as magazine_trend_mod, soldout_trend as soldout_trend_mod
    mat_color    = _run("소재·색상 트렌드 집계", material_color_trend.analyze, new_entries) or {}
    cat_growth = _run(
        "카테고리 성장률 분석",
        category_growth.analyze_items_history,
        ranking_history_14d,
    ) or []
    mag_trend    = _run("매거진 트렌드 분석", magazine_trend_mod.analyze, mag_items) or {}
    soldout_data = _run("이탈률 추이 분석", soldout_trend_mod.analyze, ranking_history_14d) or []

    # 신규 진입 리뷰 키워드 분석
    from analyzers import review_keywords, steady_seller, trend_forecast
    reviewed_entries = _run("리뷰 키워드 분석", review_keywords.analyze_batch, new_entries[:10]) or []

    ranking_history = ranking_history_14d[-7:]
    brand_result = brand_tracker.attach_history(brand_result, ranking_history)

    from analyzers import platform_cross, md_actions
    cross_platform = _run(
        "무신사·29CM 교차 분석",
        platform_cross.analyze,
        today_daily_rankings,
        cm29_data,
        previous_daily_rankings,
        previous_cm29,
    ) or []

    steady = _run(
        "스테디셀러 감지",
        steady_seller.detect_from_items,
        ranking_history_14d,
    ) or []
    steady_dropouts = _run(
        "스테디셀러 이탈 감지",
        steady_seller.detect_dropouts,
        steady,
        today_daily_rankings,
    ) or []

    # 트렌드 예측
    forecasts = _run(
        "트렌드 예측",
        trend_forecast.forecast_from_trend_data,
        list(reversed(trend_history_28d)),
    ) or []

    md_action_items = _run(
        "오늘의 MD 액션 생성",
        md_actions.build,
        signals,
        weather_data,
        cross_platform,
        reviewed_entries,
        7,
        backtest_stats,
        forecasts,
        steady_dropouts,
        price_result,
    ) or []

    # ── 4. 대시보드 생성 ──────────────────────────────────────────────────────
    # 느린 외부 저장 전에 오늘 결과를 먼저 확인할 수 있게 한다.
    from analyzers import rank_diff as _rd
    dashboard_rank_result = _rd.analyze(
        dashboard_rankings, previous_dashboard_rankings
    ) if previous_dashboard_rankings else {
        "items": dashboard_rankings,
        "top_risers": [],
        "top_fallers": [],
        "new_entries": [],
        "dropouts": [],
        "summary": "",
        "baseline_available": False,
    }
    overall_rank_result = _rd.analyze(
        all_overall, previous_overall
    ) if previous_overall else {
        "items": all_overall,
        "top_risers": [],
        "top_fallers": [],
        "new_entries": [],
        "dropouts": [],
        "summary": "",
        "baseline_available": False,
    }
    cm29_rank_result = _rd.analyze(
        cm29_data, previous_cm29
    ) if previous_cm29 else {
        "items": cm29_data,
        "top_risers": [],
        "top_fallers": [],
        "new_entries": [],
        "dropouts": [],
        "summary": "",
        "baseline_available": False,
    }
    male_best_rank_result = _rd.analyze(
        male_best, previous_male_best
    ) if previous_male_best else {
        "items": male_best,
        "top_risers": [],
        "top_fallers": [],
        "new_entries": [],
        "dropouts": [],
        "summary": "",
        "baseline_available": False,
    }
    overall_best_rank_result = _rd.analyze(
        overall_best_tabs, previous_overall_best
    ) if previous_overall_best else {
        "items": overall_best_tabs,
        "top_risers": [],
        "top_fallers": [],
        "new_entries": [],
        "dropouts": [],
        "summary": "",
        "baseline_available": False,
    }

    from exporters import dashboard
    dash_path = _run(
        "HTML 대시보드 생성",
        dashboard.generate,
        dashboard_rank_result, trend_data, price_result, brand_result, signals,
        weather_data, keyword_data, forecasts, steady,
        cm29_rank_result["items"],
        overall_rank_result["items"],
        brand_ranks, musinsa_evs, cm29_evs, mat_color, cat_growth,
        md_action_items, cross_platform, reviewed_entries,
        {
            "failed": list(_fail_log),
            "counts": {
                "musinsa": len(dashboard_rankings),
                "cm29": len(cm29_data),
                "trends": len(trend_data),
                "events": len(musinsa_evs) + len(cm29_evs),
            },
        },
        backtests,
        snapshot_store.available_dates("musinsa_rankings"),
        backtest_stats,
        top_male=male_best_rank_result["items"],
        top_all=overall_best_rank_result["items"],
        magazine_trend=mag_trend,
        soldout_trend=soldout_data,
        brand_ranks_formal=brand_ranks_formal,
    )

    _run("시그널 스냅샷 저장", snapshot_store.save, "signals", signals)
    _run("날씨 스냅샷 저장", snapshot_store.save, "weather", [weather_data] if weather_data else [])

    # ── 5. 외부 저장 ──────────────────────────────────────────────────────────
    if not dry_run:
        # 노션 저장
        _run("노션 랭킹 저장",       notion_exporter.save_rankings,      rank_result.get("items", today_rankings))
        _run("노션 29CM 랭킹 저장",  notion_exporter.save_cm29_rankings, cm29_data)
        _run("노션 트렌드 저장",     notion_exporter.save_trends,        trend_data)
        _run("노션 신규진입 저장",   notion_exporter.save_new_entries,   new_entries)
        _run("노션 브랜드 저장",     notion_exporter.save_brand_tracking, brand_result)
        _run("노션 시그널 저장",     notion_exporter.save_signals,       signals)

        # 기획전 시그널 즉시 알림 (점수 50점 이상=🟡주의/🔴긴급만 단독 발송, 슬랙 우선/카카오 보조)
        # 🟢참고 레벨은 일일 요약의 시그널 섹션에서만 확인 — 중복 알림 방지
        from exporters import slack_notify, kakao_notify
        urgent_signals = [s for s in signals if s.get("score", 0) >= 50]
        for sig in urgent_signals:
            if getattr(config, "SLACK_WEBHOOK_URL", ""):
                _run("슬랙 시그널 즉시 알림", slack_notify.send_signal_alert, sig)
            else:
                _run("카카오 시그널 즉시 알림", kakao_notify.send_signal_alert, sig)
    else:
        logger.info("[DRY RUN] 저장 단계 스킵")

    # ── 6. 일일 요약 발송 (슬랙 우선, 카카오 보조) ───────────────────────────
    if not dry_run:
        from exporters import slack_notify, kakao_notify
        if getattr(config, "SLACK_WEBHOOK_URL", ""):
            _run("슬랙 일일 요약 발송", slack_notify.send_daily_summary,
                 rank_result, trend_data, signals, weather_data, cm29_data, all_overall)
        else:
            _run("카카오 일일 요약 발송", kakao_notify.send_daily_summary,
                 rank_result, trend_data, signals, weather_data, cm29_data, all_overall)

    # ── 7. 주간 리포트 (월요일만) ─────────────────────────────────────────────
    if date.today().weekday() == 0 and not dry_run:   # 0 = 월요일
        from exporters import weekly_report
        _run("주간 리포트 생성", weekly_report.generate, trend_data)

    # ── 8. 수집 실패 알림 ────────────────────────────────────────────────────
    if _fail_log and not dry_run:
        _send_failure_alert(_fail_log)

    # ── 완료 ──────────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(
        "패션 모니터링 완료 | 랭킹:%d 트렌드:%d 신규:%d 시그널:%d 기획전(무신사:%d/29CM:%d)%s",
        len(today_rankings), len(trend_data), len(new_entries), len(signals),
        len(musinsa_evs), len(cm29_evs),
        f" | 대시보드: {dash_path}" if dash_path else "",
    )
    logger.info("=" * 60)


# ── 진입점 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="패션 MD 모니터링 자동화")
    parser.add_argument("--dry-run", action="store_true", help="수집·분석만 실행 (노션/카카오 저장 생략)")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
