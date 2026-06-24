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
import os
import re
import subprocess
import time
from typing import Optional, Tuple

from playwright.sync_api import sync_playwright, BrowserContext, Page

import config

logger = logging.getLogger(__name__)

LOGIN_URL = "https://partner-sso.one.musinsa.com/oauth/login?clientId=MUSINSA_PARTNER&platform=mss&redirectUri=https%3A%2F%2Fpartner.musinsa.com"
AUTHENTICATOR_EXT_ID = "npjilhodcgmigpladpfkkclbmkebalfd"


def _get_totp_from_pyotp(secret: str) -> Optional[str]:
    """config에 TOTP 시크릿이 있으면 pyotp로 직접 코드 생성 (가장 안정적)."""
    try:
        import pyotp
        code = pyotp.TOTP(secret).now()
        logger.info("[2FA] pyotp 코드 생성: %s", code)
        return code
    except Exception as exc:
        logger.warning("[2FA] pyotp 실패: %s", exc)
        return None


def _secret_for_keyword(keyword: str) -> str:
    """계정 keyword에 대응하는 config TOTP secret 반환."""
    normalized = (keyword or "").strip().lower()
    musinsa_id = getattr(config, "MUSINSA_PARTNERS_ID", "")
    edinburgh_id = getattr(config, "EDINBURGH_PARTNERS_ID", "")

    if normalized in {"musinsa", "connectkinrock"} or keyword == musinsa_id:
        return (
            os.environ.get("MUSINSA_TOTP_SECRET")
            or getattr(config, "MUSINSA_TOTP_SECRET", "")
            or ""
        )
    if normalized in {"edinburgh", "edinburghclub"} or keyword == edinburgh_id:
        return (
            os.environ.get("EDINBURGH_TOTP_SECRET")
            or getattr(config, "EDINBURGH_TOTP_SECRET", "")
            or ""
        )
    return ""


def _get_totp_from_secret(keyword: str) -> Optional[str]:
    secret = _secret_for_keyword(keyword)
    if not secret:
        return None
    return _get_totp_from_pyotp(secret)


def _get_totp_from_chrome(keyword: str = "musinsa") -> Optional[str]:
    """
    실행 중인 Chrome에서 Authenticator 확장 팝업을 탭으로 열고
    keyword(계정 ID)에 해당하는 TOTP 6자리 코드를 읽어 반환.

    element ID 패턴: otp-cell-musinsa-sso-partner-{keyword}-musinsa-sso-partner-
    Chrome 창이 없어도 새 창을 만들어 처리.
    """
    def pyotp_fallback(reason: str) -> Optional[str]:
        code = _get_totp_from_secret(keyword)
        if code:
            logger.info("[2FA] Chrome Authenticator 실패(%s) — pyotp fallback 사용", reason)
            return code
        logger.warning("[2FA] Chrome Authenticator 실패(%s), config TOTP_SECRET 없음/실패: %s", reason, keyword)
        return None

    chrome_check = subprocess.run(
        ["pgrep", "-x", "Google Chrome"],
        capture_output=True,
        text=True,
    )
    if chrome_check.returncode != 0:
        return pyotp_fallback("Chrome 프로세스 없음")

    ext_url = f"chrome-extension://{AUTHENTICATOR_EXT_ID}/popup.html"

    # 단일 따옴표만 쓰는 JS — AppleScript 이스케이프 충돌 없음
    direct_id = f"otp-cell-musinsa-sso-partner-{keyword}-musinsa-sso-partner-"
    js = (
        f"var el=document.getElementById('{direct_id}');"
        "if(el){var d=el.innerText.replace(/[^0-9]/g,'').substring(0,6);if(d.length===6){d}else{''}}"
        "else{var list=document.getElementById('otp-list');list?list.innerText:''}"
    )

    raw = ""
    for attempt in range(3):
        combined_script = f"""tell application "Google Chrome"
    if (count of windows) = 0 then
        make new window
        delay 1
    end if
    set authTab to make new tab at end of tabs of window 1
    set URL of authTab to "{ext_url}"
    delay {2 + attempt}
    set tabResult to execute authTab javascript "{js}"
    close authTab
    return tabResult
end tell"""
        try:
            result = subprocess.run(["osascript", "-e", combined_script], capture_output=True, text=True)
        except Exception as exc:
            logger.warning("[2FA] osascript 실행 실패 (%d/3): %s", attempt + 1, exc)
            continue
        raw = result.stdout.strip()
        if raw:
            break
        logger.info("[2FA] 확장 로딩 재시도 (%d/3)...", attempt + 1)

    # 6자리 숫자 직접 반환됐으면 성공
    if re.fullmatch(r"\d{6}", raw):
        logger.info("[2FA] TOTP 코드 획득 (Chrome): %s", raw)
        return raw

    # fallback: otp-list 전체 텍스트 파싱
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
        logger.info("[2FA] TOTP 코드 획득 (Chrome 파싱): %s", code)
    else:
        logger.warning("[2FA] '%s' 계정 미발견. Chrome Authenticator 확인 필요. 전체 목록:\n%s", keyword, raw)
        return pyotp_fallback("코드 미획득")

    return code


def login() -> Tuple[Page, BrowserContext, object]:
    """
    무신사 파트너스 로그인 (2FA 포함).
    반환값: (page, context, playwright) — 사용 후 context.close() + playwright.stop() 호출
    """
    pw = sync_playwright().start()
    session_dir = os.path.expanduser("~/.config/musinsa-playwright/login")
    os.makedirs(session_dir, exist_ok=True)
    context = pw.chromium.launch_persistent_context(
        user_data_dir=session_dir,
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
