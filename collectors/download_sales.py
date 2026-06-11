"""
무신사 파트너스 + 29CM 판매통계 자동 다운로드

다운로드 목록:
  1. 무신사 일별 주문 통계 - 커넥트킨록 (2026-01-01 ~ 오늘)
  2. 무신사 일별 주문 통계 - 에든버러클럽 (2026-01-01 ~ 오늘)
  3. 무신사 글로벌 주문 내역 (오늘 ~ 30일 전)
  4. 29CM 매출리포트 - 커넥트킨록
  5. 29CM 매출리포트 - 에든버러클럽

저장 위치: ~/Library/CloudStorage/OneDrive-개인/바탕 화면/판매통계 BD/
  - 기존 엑셀 파일 전부 삭제 후 저장
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright, BrowserContext, Page, Frame

import config
from collectors.musinsa_partners import _get_totp_from_chrome

logger = logging.getLogger(__name__)

SAVE_DIR = Path.home() / "Library/CloudStorage/OneDrive-개인/바탕 화면/판매통계 BD"

MUSINSA_LOGIN_URL = (
    "https://partner-sso.one.musinsa.com/oauth/login"
    "?clientId=MUSINSA_PARTNER&platform=mss"
    "&redirectUri=https%3A%2F%2Fpartner.musinsa.com"
)
CM29_LOGIN_URL = (
    "https://partner-sso.one.musinsa.com/oauth/login"
    "?clientId=E9_PARTNER&platform=29cm"
    "&redirectUri=https%3A%2F%2Fpartner-auth.29cm.co.kr%2F"
)


# ── 공통 유틸 ────────────────────────────────────────────────────────────────

def _clear_old_excel_files(keep_date: str):
    """오늘 날짜(keep_date, YYYYMMDD)가 아닌 엑셀 파일만 삭제."""
    removed = 0
    for f in SAVE_DIR.glob("*.xls*"):
        if keep_date not in f.name:
            f.unlink()
            removed += 1
    logger.info("[정리] 이전 엑셀 파일 %d개 삭제 (오늘 %s 것만 유지)", removed, keep_date)


def _sso_login(page: Page, user_id: str, password: str, totp_keyword: str):
    """SSO 로그인 (2FA 포함). 이미 로그인된 경우 스킵."""
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # 로그인 폼이 없으면 이미 로그인된 상태
    if page.locator('input[name="id"]').count() == 0:
        logger.info("[로그인] 이미 세션 유효 (%s)", user_id)
        return

    page.locator('input[name="id"]').fill(user_id)
    page.locator('input[type="password"]').fill(password)
    page.locator('button[type="submit"]').click()
    time.sleep(5)

    if page.locator('input[name="code"]').count() > 0:
        code = _get_totp_from_chrome(keyword=totp_keyword)
        if code:
            page.locator('input[name="code"]').fill(code)
            page.locator('button[type="submit"]').click()
            page.wait_for_load_state("networkidle")
            time.sleep(5)
    logger.info("[로그인] 완료 (%s)", user_id)


def _get_bizest_frame(page: Page, timeout: int = 20) -> Frame:
    """bizest.musinsa.com iframe 반환. timeout 초 대기. 내부 콘텐츠 로딩까지 대기."""
    page.wait_for_load_state("networkidle")
    for _ in range(timeout * 2):
        for f in page.frames:
            if "bizest" in f.url and f.url != "about:blank":
                try:
                    f.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                return f
        time.sleep(0.5)
    raise RuntimeError("bizest iframe을 찾지 못했습니다.")


def _fill_date(frame: Frame, name: str, value: str):
    """날짜 입력 — 첫 번째 보이는 필드에 네이티브 fill 사용."""
    frame.locator(f'input[name="{name}"]').first.fill(value)


def _search(frame: Frame):
    frame.locator('button:has-text("검색")').first.click()
    time.sleep(4)


def _with_retry(func, *args, retries: int = 3, **kwargs):
    """페이지 로딩 지연 등 일시적 오류 대비 재시도 (재시도 시 동일 페이지 재진입)."""
    for attempt in range(1, retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if attempt == retries:
                raise
            logger.warning("[재시도] %s 실패 (%d/%d): %s", func.__name__, attempt, retries, exc)
            time.sleep(3)


def _right_click_export(page: Page, frame: Frame, save_path: Path):
    """ag-Grid 우클릭 → 내보내기 클릭 → .xls 직접 다운로드."""
    # iframe 스크롤로 그리드를 뷰포트 안으로 올리기
    frame.evaluate("window.scrollTo(0, 550)")
    time.sleep(1)

    # 그리드 body 페이지 좌표 계산
    grid_box = frame.evaluate("""() => {
        const r = document.querySelector('.ag-body-viewport').getBoundingClientRect();
        return {top: r.top, left: r.left};
    }""")
    iframe_box = page.locator("iframe").first.bounding_box()
    click_x = iframe_box["x"] + grid_box["left"] + 200
    click_y = iframe_box["y"] + grid_box["top"] + 30

    # 우클릭 → 컨텍스트 메뉴
    page.mouse.click(click_x, click_y, button="right")
    time.sleep(1.5)

    # "내보내기" 클릭 → 즉시 .xls 다운로드
    with page.expect_download(timeout=15000) as dl_info:
        frame.locator(':text("내보내기")').first.click()

    dl_info.value.save_as(str(save_path))
    logger.info("[다운로드] %s (원본: %s)", save_path.name, dl_info.value.suggested_filename)


# ── 무신사 다운로드 ──────────────────────────────────────────────────────────

def _download_daily_order_stats(page: Page, brand_name: str, save_path: Path):
    """일별 주문 통계 - 브랜드 지정 다운로드."""
    today = datetime.now().strftime("%Y-%m-%d")

    page.goto("https://partner.musinsa.com/statistics/order-daily")
    frame = _get_bizest_frame(page)

    _fill_date(frame, "S_SDATE", "2026-01-01")
    _fill_date(frame, "S_EDATE", today)
    frame.locator('input[name="S_BRAND_NM"]').first.fill(brand_name)
    frame.locator('input[name="S_BRAND_NM"]').first.press("Enter")
    time.sleep(1)
    _search(frame)

    _right_click_export(page, frame, save_path)


def _download_global_orders(page: Page, save_path: Path):
    """글로벌 주문 내역 - 자료받기 다운로드. 결과 없으면 스킵."""
    today = datetime.now()
    s_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    e_date = today.strftime("%Y-%m-%d")

    page.goto("https://partner.musinsa.com/order/global-history")
    frame = _get_bizest_frame(page)

    _fill_date(frame, "S_SDATE", s_date)
    _fill_date(frame, "S_EDATE", e_date)

    # 7일 이상 조회 시 confirm 경고창 → 자동 수락
    page.once("dialog", lambda d: d.accept())
    _search(frame)

    try:
        with page.expect_download(timeout=10000) as dl_info:
            frame.locator('a:has-text("자료받기"), button:has-text("자료받기")').first.click()
        dl_info.value.save_as(str(save_path))
        logger.info("[다운로드] %s", save_path.name)
    except Exception:
        logger.warning("[글로벌 주문] 검색 결과 없음 — 파일 생략")


# ── 29CM 다운로드 ─────────────────────────────────────────────────────────────

def _download_29cm_sales(page: Page, save_path: Path):
    """29CM 매출리포트 - 30일 검색 후 엑셀 다운로드."""
    # 로그인 후 리다이렉트 위치와 무관하게 통계 페이지로 이동
    page.goto("https://partner-connect.29cm.co.kr/statistics")
    page.wait_for_load_state("networkidle")
    time.sleep(4)

    # 30일 버튼 클릭
    page.locator('button:has-text("30일")').first.click()
    time.sleep(1)

    # 검색하기
    page.locator('button:has-text("검색하기")').first.click()
    time.sleep(3)

    # 엑셀 다운로드
    with page.expect_download(timeout=15000) as dl_info:
        page.locator('button:has-text("엑셀 다운로드")').first.click()
    dl_info.value.save_as(str(save_path))
    logger.info("[다운로드] %s", save_path.name)


# ── 메인 ────────────────────────────────────────────────────────────────────

def run():
    today_str = datetime.now().strftime("%Y%m%d")

    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir="/tmp/musinsa_download",
        headless=False,
        viewport={"width": 1280, "height": 900},
        locale="ko-KR",
        accept_downloads=True,
    )

    # ── 무신사 로그인 (커넥트킨록) ──────────────────────────────────────────
    page = ctx.new_page()
    page.goto(MUSINSA_LOGIN_URL)
    _sso_login(page, config.MUSINSA_PARTNERS_ID, config.MUSINSA_PARTNERS_PASSWORD,
               config.MUSINSA_PARTNERS_ID)

    # 1. 일별 주문 통계 - 커넥트킨록
    logger.info("[1/5] 일별 주문 통계 - 커넥트킨록")
    _with_retry(_download_daily_order_stats, page, "커넥트킨록",
                SAVE_DIR / f"일별주문통계_커넥트킨록_{today_str}.xls")

    # 2. 일별 주문 통계 - 에든버러클럽 (같은 계정으로 브랜드만 변경)
    logger.info("[2/5] 일별 주문 통계 - 에든버러클럽")
    _with_retry(_download_daily_order_stats, page, "에든버러클럽",
                SAVE_DIR / f"일별주문통계_에든버러클럽_{today_str}.xls")

    # 3. 글로벌 주문 내역
    logger.info("[3/5] 글로벌 주문 내역")
    _with_retry(_download_global_orders, page, SAVE_DIR / f"글로벌주문내역_{today_str}.xls")

    page.close()

    # ── 29CM - 커넥트킨록 ────────────────────────────────────────────────────
    logger.info("[4/5] 29CM 매출리포트 - 커넥트킨록")
    page = ctx.new_page()
    page.goto("https://partner-connect.29cm.co.kr/statistics")
    _sso_login(page, config.MUSINSA_PARTNERS_ID, config.MUSINSA_PARTNERS_PASSWORD,
               config.MUSINSA_PARTNERS_ID)
    _with_retry(_download_29cm_sales, page, SAVE_DIR / f"29CM_커넥트킨록_{today_str}.xlsx")
    page.close()

    # ── 29CM - 에든버러클럽 (세션 초기화 후 다른 계정으로 로그인) ────────────
    logger.info("[5/5] 29CM 매출리포트 - 에든버러클럽")
    ctx.clear_cookies()  # 이전 29CM 세션 제거
    page = ctx.new_page()
    page.goto("https://partner-connect.29cm.co.kr/statistics")
    _sso_login(page, config.EDINBURGH_PARTNERS_ID, config.EDINBURGH_PARTNERS_PASSWORD,
               config.EDINBURGH_PARTNERS_ID)
    _with_retry(_download_29cm_sales, page, SAVE_DIR / f"29CM_에든버러클럽_{today_str}.xlsx")
    page.close()

    ctx.close()
    pw.stop()
    logger.info("[완료] 모든 파일 다운로드 완료 → %s", SAVE_DIR)

    # 5개 모두 저장 완료 후 이전 날짜 파일 정리
    _clear_old_excel_files(today_str)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run()
