#!/bin/bash
# 패션 MD 랭킹 수집 + 슬랙 요약 (main.py)
# 8:50~9:10 사이 매분 cron이 깨워보고, 노트북이 켜져 네트워크가 잡히는 첫 순간 1회만 실행
cd "/Users/jeonjuwon/fashion-monitor" || exit 1

# 프로젝트 venv python 사용 (Scrapling 등 포함). 없으면 시스템 python으로 폴백.
PY="/Users/jeonjuwon/fashion-monitor/.venv/bin/python"
[ -x "$PY" ] || PY="/usr/bin/python3"

MARKER="logs/.fashion_ran_$(date '+%Y%m%d')"

# 중복 실행 방지 락 (mkdir은 원자적 — curl 대기 중 다음 분 cron이 동시 진입하는 것 방지)
LOCKDIR="/tmp/.fashion_monitor.lock"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
    exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT

# 자정 넘어 실행될 가능성 대비: "오늘 실행했는지"가 아니라 "오늘 08시 이후 실행했는지"로 판단
TODAY_8AM=$(date -j -f "%Y-%m-%d %H:%M:%S" "$(date '+%Y-%m-%d') 08:00:00" "+%s")
if [ -f "$MARKER" ]; then
    MARKER_TIME=$(stat -f %m "$MARKER")
    [ "$MARKER_TIME" -ge "$TODAY_8AM" ] && exit 0
fi
curl -s --max-time 5 https://www.google.com > /dev/null 2>&1 || exit 0
touch "$MARKER"

"$PY" main.py >> logs/cron.log 2>&1

# 프론트엔드 연동용 JSON 데이터 내보내기
"$PY" export_json.py >> logs/cron.log 2>&1
"$PY" export_real_sales.py >> logs/cron.log 2>&1

# GitHub Pages 대시보드 동기화 — docs/dashboard.html만 커밋+푸시 (다른 작업 중인 변경은 건드리지 않음)
if ! git diff --quiet -- docs/dashboard.html || ! git diff --cached --quiet -- docs/dashboard.html; then
    git add docs/dashboard.html
    git commit -m "chore: 대시보드 자동 갱신 ($(date '+%Y-%m-%d %H:%M'))" >> logs/cron.log 2>&1
    git push origin main >> logs/cron.log 2>&1
fi
