"""
카카오 액세스 토큰 자동 갱신 스크립트.

config.py의 KAKAO_REFRESH_TOKEN 으로 액세스 토큰을 갱신하고
KAKAO_ACCESS_TOKEN 을 덮어씁니다.

cron에 등록해 매 5시간마다 자동 실행하거나
main.py 실행 전에 호출할 수 있습니다.

crontab 예시 (매 5시간):
    0 */5 * * * cd ~/fashion-monitor && python3 kakao_refresh.py >> logs/cron.log 2>&1
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

KAKAO_REST_API_KEY = "deae5cadb2012e898946a7d03ab84358"
REDIRECT_URI       = "https://localhost"
TOKEN_URL          = "https://kauth.kakao.com/oauth/token"
CONFIG_PATH        = os.path.join(os.path.dirname(__file__), "config.py")


def _load_refresh_token() -> str:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'^KAKAO_REFRESH_TOKEN\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    return m.group(1) if m else ""


def _save_tokens(access_token: str, refresh_token: str = "") -> None:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    content = re.sub(
        r'^KAKAO_ACCESS_TOKEN\s*=\s*.*$',
        f'KAKAO_ACCESS_TOKEN = "{access_token}"',
        content, flags=re.MULTILINE,
    )
    if refresh_token:
        if "KAKAO_REFRESH_TOKEN" in content:
            content = re.sub(
                r'^KAKAO_REFRESH_TOKEN\s*=\s*.*$',
                f'KAKAO_REFRESH_TOKEN = "{refresh_token}"',
                content, flags=re.MULTILINE,
            )

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    refresh_token = _load_refresh_token()
    if not refresh_token:
        print("❌ KAKAO_REFRESH_TOKEN 이 config.py에 없습니다.")
        print("   먼저 kakao_auth.py 를 실행해 초기 토큰을 발급하세요.")
        sys.exit(1)

    payload = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "client_id":     KAKAO_REST_API_KEY,
        "refresh_token": refresh_token,
    }).encode("utf-8")

    req = urllib.request.Request(TOKEN_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"❌ 토큰 갱신 요청 실패: {e}")
        sys.exit(1)

    if "error" in data:
        print(f"❌ 카카오 오류: {data.get('error_description', data)}")
        print("   리프레시 토큰이 만료되었습니다. kakao_auth.py 를 다시 실행하세요.")
        sys.exit(1)

    new_access  = data.get("access_token", "")
    new_refresh = data.get("refresh_token", "")   # 갱신된 경우만 반환
    expires_in  = data.get("expires_in", 0)

    _save_tokens(new_access, new_refresh)
    print(f"✅ 카카오 토큰 갱신 완료 (유효: {expires_in // 3600}시간 {(expires_in % 3600) // 60}분)")


if __name__ == "__main__":
    main()
