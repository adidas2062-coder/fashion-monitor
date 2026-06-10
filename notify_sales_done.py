"""판매통계 자동 업데이트(다운로드 + 반영) 완료/실패 슬랙 알림.

사용법: python3 notify_sales_done.py <성공|실패> [메시지]
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import config


def main():
    status = sys.argv[1] if len(sys.argv) > 1 else "완료"
    detail = sys.argv[2] if len(sys.argv) > 2 else ""

    now = datetime.now(timezone.utc) + timedelta(hours=9)
    emoji = "✅" if status == "성공" else "⚠️"
    text = f"{emoji} [{now.strftime('%-m/%-d %H:%M')}] 판매통계 자동 업데이트 {status}"
    if detail:
        text += f"\n{detail}"

    webhook = getattr(config, "SLACK_WEBHOOK_URL", "")
    if not webhook:
        print("SLACK_WEBHOOK_URL 미설정 — 알림 스킵")
        return

    data = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(webhook, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print("슬랙 발송:", resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"슬랙 HTTP 에러 {exc.code}: {exc.read().decode()[:200]}")
    except Exception as exc:
        print("슬랙 발송 실패:", exc)


if __name__ == "__main__":
    main()
