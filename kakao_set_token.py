"""
카카오 액세스 토큰 직접 입력 스크립트.

카카오 디벨로퍼스 → 도구 → REST API 테스트에서 발급받은 토큰을
config.py에 저장합니다.

사용법:
    python3 kakao_set_token.py
"""
import re, sys, os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.py")

print("카카오 액세스 토큰을 입력하세요.")
print("(developers.kakao.com → 도구 → REST API 테스트 → 토큰 가져오기)")
print()
token = input("access_token: ").strip()

if not token:
    print("❌ 토큰이 비어 있습니다.")
    sys.exit(1)

# 유효성 검사 — 토큰으로 실제 API 호출
import urllib.request, urllib.error, json

req = urllib.request.Request(
    "https://kapi.kakao.com/v2/api/talk/memo/default/send",
    data=urllib.parse.urlencode({
        "template_object": json.dumps({
            "object_type": "text",
            "text": "[패션 모니터] 카카오 연결 테스트 완료! ✅",
            "link": {"web_url": "https://www.musinsa.com"},
        }, ensure_ascii=False)
    }).encode("utf-8"),
    method="POST"
)
req.add_header("Authorization", f"Bearer {token}")
req.add_header("Content-Type", "application/x-www-form-urlencoded")

import urllib.parse
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
        if body.get("result_code") == 0:
            print("✅ 토큰 유효 — 카카오톡 테스트 메시지 발송됨")
        else:
            print(f"⚠️  응답: {body}")
except urllib.error.HTTPError as e:
    err = json.loads(e.read())
    print(f"❌ 토큰 검증 실패 (HTTP {e.code}): {err}")
    if input("그래도 저장하시겠습니까? (y/n): ").strip().lower() != "y":
        sys.exit(1)

# config.py 저장
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    content = f.read()

content = re.sub(
    r'^KAKAO_ACCESS_TOKEN\s*=\s*.*$',
    f'KAKAO_ACCESS_TOKEN = "{token}"',
    content, flags=re.MULTILINE,
)

with open(CONFIG_PATH, "w", encoding="utf-8") as f:
    f.write(content)

print(f"\n✅ config.py 저장 완료: KAKAO_ACCESS_TOKEN = {token[:15]}...")
print("   카카오톡 알림이 활성화됩니다.")
