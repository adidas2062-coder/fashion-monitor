#!/bin/bash
# 패션 MD 랭킹 수집 + 슬랙 요약 (main.py)
# 8:50~9:10 사이 매분 cron이 깨워보고, 노트북이 켜져 네트워크가 잡히는 첫 순간 1회만 실행
cd "/Users/jeonjuwon/fashion-monitor" || exit 1

MARKER="logs/.fashion_ran_$(date '+%Y%m%d')"

# 자정 넘어 실행될 가능성 대비: "오늘 실행했는지"가 아니라 "오늘 08시 이후 실행했는지"로 판단
TODAY_8AM=$(date -j -f "%Y-%m-%d %H:%M:%S" "$(date '+%Y-%m-%d') 08:00:00" "+%s")
if [ -f "$MARKER" ]; then
    MARKER_TIME=$(stat -f %m "$MARKER")
    [ "$MARKER_TIME" -ge "$TODAY_8AM" ] && exit 0
fi
curl -s --max-time 5 https://www.google.com > /dev/null 2>&1 || exit 0
touch "$MARKER"

/usr/bin/python3 main.py >> logs/cron.log 2>&1

# 프론트엔드 연동용 JSON 데이터 내보내기
/usr/bin/python3 export_json.py >> logs/cron.log 2>&1
/usr/bin/python3 export_real_sales.py >> logs/cron.log 2>&1
