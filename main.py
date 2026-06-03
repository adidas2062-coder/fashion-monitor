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
from datetime import date

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

def _run(label: str, func, *args, **kwargs):
    """함수 실행 — 예외가 발생해도 로그만 남기고 계속."""
    try:
        logger.info("▶ %s 시작", label)
        result = func(*args, **kwargs)
        logger.info("✅ %s 완료", label)
        return result
    except Exception as exc:
        logger.error("❌ %s 실패: %s", label, exc, exc_info=True)
        return None


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
    periods = _collect_periods()
    logger.info("=" * 60)
    logger.info("패션 모니터링 시작 (%s) 수집기간=%s%s",
                today, periods, "  [DRY RUN]" if dry_run else "")
    logger.info("=" * 60)

    # ── 1. 수집 ───────────────────────────────────────────────────────────────
    from collectors import musinsa, google_trends, naver_datalab, instagram

    today_rankings = _run("무신사 랭킹 수집", musinsa.collect, periods=periods) or []
    time.sleep(config.REQUEST_DELAY)

    google_data  = _run("구글 트렌드 수집", google_trends.collect) or []
    time.sleep(config.REQUEST_DELAY)

    naver_data   = _run("네이버 데이터랩 수집", naver_datalab.collect) or []
    time.sleep(config.REQUEST_DELAY)

    insta_data   = _run("인스타그램 수집", instagram.collect) or []

    # 작년 동기 아카이브 (YoY 비교용 — 매일 수집)
    from collectors import musinsa_archive
    archive_data = _run("작년 동기 아카이브 수집", musinsa_archive.collect) or []

    trend_data   = google_data + naver_data + insta_data
    logger.info("트렌드 데이터 합계: %d건", len(trend_data))

    # ── 2. 어제 랭킹 조회 (순위 변동 비교용) ─────────────────────────────────
    from exporters import notion_exporter

    yesterday_rankings = _run("노션 어제 랭킹 조회", notion_exporter.fetch_yesterday_rankings) or []

    # ── 3. 분석 ───────────────────────────────────────────────────────────────
    from analyzers import rank_diff, new_entry, price_analysis, brand_tracker, timing_signal

    rank_result  = _run("순위 변동 분석", rank_diff.analyze, today_rankings, yesterday_rankings) or {
        "items": today_rankings, "top_risers": [], "top_fallers": [],
        "new_entries": [], "dropouts": [], "summary": "",
    }
    time.sleep(0.5)

    # 신규 진입 상세 수집 — 어제 데이터 없는 첫 실행 시 전체가 신규가 되므로 상한 적용
    _MAX_NEW_ENTRY_DETAIL = 30
    raw_new = rank_result.get("new_entries", [])
    if len(raw_new) > _MAX_NEW_ENTRY_DETAIL:
        logger.info("신규 진입 %d건 중 상위 %d건만 상세 수집 (첫 실행 또는 대량 진입)", len(raw_new), _MAX_NEW_ENTRY_DETAIL)
        raw_new = raw_new[:_MAX_NEW_ENTRY_DETAIL]
    new_entries  = _run("신규 진입 상품 상세 수집", new_entry.enrich, raw_new) or []
    time.sleep(config.REQUEST_DELAY)

    price_result = _run("가격대 분포 분석", price_analysis.analyze, today_rankings, yesterday_rankings) or {}
    brand_result = _run("브랜드 트래킹", brand_tracker.analyze, today_rankings, yesterday_rankings) or []
    signals      = _run("기획전 시그널 감지", timing_signal.detect, trend_data, rank_result, archive_data) or []

    # ── 4. 저장 ───────────────────────────────────────────────────────────────
    if not dry_run:
        # 노션 저장
        _run("노션 랭킹 저장",       notion_exporter.save_rankings,      rank_result.get("items", today_rankings))
        _run("노션 트렌드 저장",     notion_exporter.save_trends,        trend_data)
        _run("노션 신규진입 저장",   notion_exporter.save_new_entries,   new_entries)
        _run("노션 브랜드 저장",     notion_exporter.save_brand_tracking, brand_result)
        _run("노션 시그널 저장",     notion_exporter.save_signals,       signals)

        # 기획전 시그널 즉시 카카오 알림
        from exporters import kakao_notify
        for sig in signals:
            _run("카카오 시그널 즉시 알림", kakao_notify.send_signal_alert, sig)
    else:
        logger.info("[DRY RUN] 저장 단계 스킵")

    # ── 5. 대시보드 생성 (dry-run 포함 항상 생성) ────────────────────────────
    from exporters import dashboard
    dash_path = _run(
        "HTML 대시보드 생성",
        dashboard.generate,
        rank_result, trend_data, price_result, brand_result, signals,
    )

    # ── 6. 카카오 일일 요약 발송 ──────────────────────────────────────────────
    if not dry_run:
        from exporters import kakao_notify
        _run("카카오 일일 요약 발송", kakao_notify.send_daily_summary, rank_result, trend_data, signals)

    # ── 7. 주간 리포트 (월요일만) ─────────────────────────────────────────────
    if date.today().weekday() == 0 and not dry_run:   # 0 = 월요일
        from exporters import weekly_report
        _run("주간 리포트 생성", weekly_report.generate, trend_data)

    # ── 완료 ──────────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(
        "패션 모니터링 완료 | 랭킹:%d 트렌드:%d 신규:%d 시그널:%d%s",
        len(today_rankings), len(trend_data), len(new_entries), len(signals),
        f" | 대시보드: {dash_path}" if dash_path else "",
    )
    logger.info("=" * 60)


# ── 진입점 ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="패션 MD 모니터링 자동화")
    parser.add_argument("--dry-run", action="store_true", help="수집·분석만 실행 (노션/카카오 저장 생략)")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
