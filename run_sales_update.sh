#!/bin/bash
# 평일 아침: 판매통계 엑셀 5종 자동 다운로드 → 슬랙 완료 알림
# (update_sales.py 반영은 너무 느려 자동화에서 제외 — 알림 받은 후 수동 실행)
# 8:50~9:10 사이 매분 cron이 깨워보고, 노트북이 켜져 네트워크가 잡히는 첫 순간 1회만 실행
cd "/Users/jeonjuwon/fashion-monitor" || exit 1

LOG="logs/download_sales.log"
MARKER="logs/.sales_ran_$(date '+%Y%m%d')"

# 자정 넘어 실행될 가능성 대비: "오늘 실행했는지"가 아니라 "오늘 08시 이후 실행했는지"로 판단
TODAY_8AM=$(date -j -f "%Y-%m-%d %H:%M:%S" "$(date '+%Y-%m-%d') 08:00:00" "+%s")
if [ -f "$MARKER" ]; then
    MARKER_TIME=$(stat -f %m "$MARKER")
    [ "$MARKER_TIME" -ge "$TODAY_8AM" ] && exit 0
fi
curl -s --max-time 5 https://www.google.com > /dev/null 2>&1 || exit 0
touch "$MARKER"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 판매통계 다운로드 시작 =====" >> "$LOG"

if /usr/bin/python3 -m collectors.download_sales >> "$LOG" 2>&1; then
    /usr/bin/python3 notify_sales_done.py "성공" "엑셀 5종 다운로드 완료 — 판매통계 BD 폴더 확인" >> "$LOG" 2>&1
else
    /usr/bin/python3 notify_sales_done.py "실패" "logs/download_sales.log 확인 필요" >> "$LOG" 2>&1
fi
