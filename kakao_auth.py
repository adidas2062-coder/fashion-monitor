"""
카카오 나에게 보내기 — 액세스 토큰 발급 스크립트.

실행하면:
  1. 브라우저에서 카카오 로그인 페이지가 열립니다.
  2. 로그인 + 동의 후 카카오가 https://localhost?code=XXXX 로 리다이렉트합니다.
  3. 브라우저가 "연결 거부" 오류를 보여주더라도 주소창 URL을 복사해 붙여넣으세요.
     (로컬 HTTP 서버 자동 수신이 성공하면 수동 입력 불필요)
  4. 토큰이 config.py의 KAKAO_ACCESS_TOKEN 에 자동 저장됩니다.

사용법:
    python3 kakao_auth.py
"""

import http.server
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import json

# ── 설정 ───────────────────────────────────────────────────────────────────────
KAKAO_REST_API_KEY = "deae5cadb2012e898946a7d03ab84358"
REDIRECT_URI       = "https://localhost"
LOCAL_PORT         = 8080   # 자동 수신용 보조 포트 (redirect_uri 와 다름)

AUTH_URL   = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL  = "https://kauth.kakao.com/oauth/token"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.py")


# ── 로컬 서버 (자동 코드 수신 시도) ──────────────────────────────────────────
_received_code: list = []

class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code   = params.get("code", [None])[0]
        if code:
            _received_code.append(code)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"""<html><body style="font-family:sans-serif;text-align:center;padding:60px">
            <h2>&#10003; 카카오 인증 완료!</h2>
            <p>이 창을 닫고 터미널로 돌아가세요.</p>
            </body></html>""")
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass   # 서버 로그 억제


def _start_local_server():
    """포트 8080에서 임시 HTTP 서버 시작 (백그라운드 스레드)."""
    try:
        server = http.server.HTTPServer(("localhost", LOCAL_PORT), _Handler)
        server.timeout = 120
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        return server
    except OSError:
        return None


# ── 토큰 교환 ─────────────────────────────────────────────────────────────────

def _exchange_code(code: str) -> dict:
    payload = urllib.parse.urlencode({
        "grant_type":   "authorization_code",
        "client_id":    KAKAO_REST_API_KEY,
        "redirect_uri": REDIRECT_URI,
        "code":         code,
    }).encode("utf-8")

    req = urllib.request.Request(TOKEN_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── config.py 업데이트 ────────────────────────────────────────────────────────

def _save_token(access_token: str, refresh_token: str = "") -> None:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # KAKAO_ACCESS_TOKEN 교체
    content = re.sub(
        r'^KAKAO_ACCESS_TOKEN\s*=\s*.*$',
        f'KAKAO_ACCESS_TOKEN = "{access_token}"',
        content, flags=re.MULTILINE,
    )

    # KAKAO_REFRESH_TOKEN 이 있으면 교체, 없으면 KAKAO_ACCESS_TOKEN 바로 뒤에 추가
    if refresh_token:
        if "KAKAO_REFRESH_TOKEN" in content:
            content = re.sub(
                r'^KAKAO_REFRESH_TOKEN\s*=\s*.*$',
                f'KAKAO_REFRESH_TOKEN = "{refresh_token}"',
                content, flags=re.MULTILINE,
            )
        else:
            content = content.replace(
                f'KAKAO_ACCESS_TOKEN = "{access_token}"',
                f'KAKAO_ACCESS_TOKEN = "{access_token}"\nKAKAO_REFRESH_TOKEN = "{refresh_token}"',
            )

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"\n✅ config.py 저장 완료")
    print(f"   KAKAO_ACCESS_TOKEN  = {access_token[:20]}...")
    if refresh_token:
        print(f"   KAKAO_REFRESH_TOKEN = {refresh_token[:20]}...")


# ── 메인 흐름 ─────────────────────────────────────────────────────────────────

def main():
    auth_url = (
        f"{AUTH_URL}"
        f"?client_id={KAKAO_REST_API_KEY}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
        f"&response_type=code"
        f"&scope=talk_message"
    )

    print("=" * 60)
    print("  카카오 나에게 보내기 — 토큰 발급")
    print("=" * 60)
    print()

    # 로컬 서버 시작 (https://localhost 리다이렉트이므로 자동 수신 불가,
    # 하지만 혹시 http://localhost:8080 으로도 콜백이 오면 잡기 위해 유지)
    server = _start_local_server()
    if server:
        print(f"[보조] 로컬 서버 시작 (port {LOCAL_PORT})")

    print("\n[1] 브라우저에서 카카오 로그인 페이지가 열립니다.")
    print("[2] 카카오 계정으로 로그인 후 '동의하고 계속하기'를 클릭하세요.")
    print("[3] 리다이렉트 후 브라우저 주소창에 다음과 같은 URL이 표시됩니다:")
    print("      https://localhost?code=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
    print("    → '연결 거부' 오류가 떠도 괜찮습니다. 주소창 URL을 복사하세요.")
    print()

    time.sleep(1)
    webbrowser.open(auth_url)

    # 자동 수신 대기 (최대 5초)
    for _ in range(10):
        time.sleep(0.5)
        if _received_code:
            break

    if _received_code:
        code = _received_code[0]
        print(f"\n✅ 인증 코드 자동 수신: {code[:10]}...")
    else:
        print("\n브라우저에서 리다이렉트된 URL 전체를 붙여넣으세요.")
        print("예) https://localhost?code=XXXXX&state=...\n")
        raw = input("URL 또는 code 값: ").strip()

        # URL 전체 또는 code 값만 입력 모두 허용
        if raw.startswith("http"):
            parsed = urllib.parse.urlparse(raw)
            params = urllib.parse.parse_qs(parsed.query)
            code   = params.get("code", [None])[0]
            if not code:
                print("❌ URL에서 code 파라미터를 찾을 수 없습니다.")
                sys.exit(1)
        else:
            code = raw

    print("\n[4] 액세스 토큰 교환 중...")
    try:
        token_data = _exchange_code(code)
    except Exception as e:
        print(f"❌ 토큰 교환 실패: {e}")
        sys.exit(1)

    if "error" in token_data:
        print(f"❌ 카카오 오류: {token_data.get('error_description', token_data)}")
        sys.exit(1)

    access_token  = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in    = token_data.get("expires_in", 0)

    print(f"\n액세스 토큰 유효시간: {expires_in // 3600}시간 {(expires_in % 3600) // 60}분")

    _save_token(access_token, refresh_token)

    print()
    print("=" * 60)
    print("  완료! 이제 카카오톡 알림이 발송됩니다.")
    print("  ※ 액세스 토큰은 6시간마다 만료됩니다.")
    print("     만료 시 이 스크립트를 다시 실행하거나")
    print("     kakao_refresh.py 로 자동 갱신하세요.")
    print("=" * 60)


if __name__ == "__main__":
    main()
