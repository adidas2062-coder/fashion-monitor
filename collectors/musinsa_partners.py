"""
무신사 파트너스 로그인 + 데이터 수집기.

AppleScript로 실행 중인 Chrome의 Authenticator 확장에서 TOTP 코드를 읽어
2FA를 자동 처리한다. Chrome을 닫을 필요 없음.

사전 조건:
  - config.py 에 MUSINSA_PARTNERS_EMAIL / MUSINSA_PARTNERS_PASSWORD 입력
  - Chrome에 Authenticator 확장 설치 + 무신사 파트너스 계정 등록
  - pip install playwright && playwright install chromium
"""

import logging
import re
import subprocess
import time
from typing import Optional, Tuple

from playwright.sync_api import sync_playwright, BrowserContext, Page

import config

logger = logging.getLogger(__name__)

LOGIN_URL = "https://partner-sso.one.musinsa.com/oauth/login?clientId=MUSINSA_PARTNER&platform=mss&redirectUri=https%3A%2F%2Fpartner.musinsa.com"
AUTHENTICATOR_EXT_ID = "npjilhodcgmigpladpfkkclbmkebalfd"


def _get_totp_from_chrome(keyword: str = "musinsa") -> Optional[str]:
    """
    실행 중인 Chrome에서 Authenticator 확장 팝업을 탭으로 열고
    keyword에 해당하는 TOTP 6자리 코드를 읽어 반환.
    """
    ext_url = f"chrome-extension://{AUTHENTICATOR_EXT_ID}/popup.html"

    # 1) 새 탭으로 확장 팝업 열기
    open_script = f'''
    tell application "Google Chrome"
        set newTab to make new tab at end of tabs of window 1
        set URL of newTab to "{ext_url}"
        set index of window 1 to 1
    end tell
    '''
    # 2) 탭 열기 + 읽기 + 닫기를 한 스크립트에서 처리 (재시도 3회)
    raw = ""
    for attempt in range(3):
        combined_script = f'''
        tell application "Google Chrome"
            set authTab to make new tab at end of tabs of window 1
            set URL of authTab to "{ext_url}"
            delay {2 + attempt}
            set tabResult to execute authTab javascript "document.getElementById('otp-list') ? document.getElementById('otp-list').innerText : ''"
            close authTab
            return tabResult
        end tell
        '''
        result = subprocess.run(
            ["osascript", "-e", combined_script],
            capture_output=True, text=True
        )
        raw = result.stdout.strip()
        if raw:
            break
        logger.info("[2FA] 확장 로딩 재시도 (%d/3)...", attempt + 1)

    # 텍스트 형식: "계정명\n\n\t783365\t\t\n계정명2\n..."
    code = None
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower():
            for j in range(i + 1, min(i + 5, len(lines))):
                digits = re.findall(r"\d{6}", lines[j])
                if digits:
                    code = digits[0]
                    break
            break

    if code:
        logger.info("[2FA] TOTP 코드 획득: %s", code)
    else:
        logger.warning("[2FA] '%s' 계정 미발견. 전체 목록:\n%s", keyword, raw)

    return code
    return None


def login() -> Tuple[Page, BrowserContext, object]:
    """
    무신사 파트너스 로그인 (2FA 포함).
    반환값: (page, context, playwright) — 사용 후 context.close() + playwright.stop() 호출
    """
    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir="/tmp/musinsa_partners_profile",
        headless=False,
        viewport={"width": 1280, "height": 900},
        locale="ko-KR",
    )

    page = context.new_page()
    page.goto(LOGIN_URL)
    page.wait_for_load_state("networkidle")

    # ── 이메일 / 비밀번호 입력 ──────────────────────────────────────────────
    page.locator('input[name="id"], input[name="userId"], input[name="username"], #id').first.fill(
        config.MUSINSA_PARTNERS_ID
    )
    page.locator('input[type="password"]').first.fill(
        config.MUSINSA_PARTNERS_PASSWORD
    )
    page.locator('button[type="submit"]').first.click()
    logger.info("[로그인] 이메일/비밀번호 입력 완료")

    # ── 2FA 감지 ────────────────────────────────────────────────────────────
    try:
        page.wait_for_url(re.compile(r"2fa|otp|verify|two.?factor", re.I), timeout=8000)
        is_2fa = True
    except Exception:
        otp_input = page.locator(
            'input[name="otp"], input[name="code"], input[maxlength="6"]'
        )
        is_2fa = otp_input.count() > 0

    if is_2fa:
        logger.info("[2FA] 2차 인증 페이지 감지 — Chrome에서 코드 읽는 중...")
        totp_code = _get_totp_from_chrome(keyword=config.MUSINSA_PARTNERS_ID)

        if totp_code:
            page.locator('input[name="code"]').fill(totp_code)
            page.locator('button[type="submit"]').click()
        else:
            logger.warning("[2FA] 자동 코드 획득 실패 — 수동으로 입력 후 엔터")
            input("수동 입력 완료 후 엔터: ")

    page.wait_for_load_state("networkidle", timeout=15000)
    logger.info("[완료] 로그인 성공")
    return page, context, pw


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    page, ctx, pw = login()
    print(f"\n현재 URL: {page.url}")
    input("\n브라우저를 유지합니다. 엔터를 누르면 종료합니다: ")
    ctx.close()
    pw.stop()
