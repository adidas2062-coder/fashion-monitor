#!/bin/bash
# 평일 아침: 판매통계 엑셀 5종 자동 다운로드 → 판매 통계.xlsx 자동 업데이트 → 슬랙 알림
# 8:50~9:10 사이 매분 cron이 깨워보고, 노트북이 켜져 네트워크가 잡히는 첫 순간 1회만 실행
cd "/Users/jeonjuwon/fashion-monitor" || exit 1

LOG="logs/download_sales.log"
MARKER="logs/.sales_ran_$(date '+%Y%m%d')"

# 중복 실행 방지 락 (mkdir은 원자적 — curl 대기 중 다음 분 cron이 동시 진입하는 것 방지)
LOCKDIR="/tmp/.sales_update.lock"
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

if [ -z "${DISPLAY:-}" ]; then
    export SALES_HEADLESS="${SALES_HEADLESS:-0}"
    if launchctl print "gui/$(id -u)" > /dev/null 2>&1; then
        echo "===== $(date '+%Y-%m-%d %H:%M:%S') DISPLAY 없음, Aqua GUI 세션 확인: SALES_HEADLESS=$SALES_HEADLESS =====" >> "$LOG"
    else
        echo "===== $(date '+%Y-%m-%d %H:%M:%S') DISPLAY 없음, Aqua GUI 세션 확인 실패: SALES_HEADLESS=$SALES_HEADLESS =====" >> "$LOG"
    fi
fi

NETWORK_OK=0
for attempt in $(seq 1 20); do
    if curl -s --max-time 5 https://www.google.com > /dev/null 2>&1; then
        NETWORK_OK=1
        break
    fi
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') 네트워크 대기 중 (${attempt}/20) =====" >> "$LOG"
    sleep 30
done

if [ "$NETWORK_OK" -ne 1 ]; then
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') 네트워크 미연결: 다음 cron에서 재시도 =====" >> "$LOG"
    exit 0
fi

UPDATE_PY="$(dirname "$0")/update_sales.py"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 판매통계 다운로드 시작 =====" >> "$LOG"

if ! /usr/bin/python3 -m collectors.download_sales >> "$LOG" 2>&1; then
    /usr/bin/python3 notify_sales_done.py "실패" "다운로드 오류 — logs/download_sales.log 확인 필요" >> "$LOG" 2>&1
    rm -f "$MARKER"
    exit 1
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 판매 통계.xlsx 업데이트 시작 =====" >> "$LOG"

# Excel이 열려있어도 기존 인스턴스 재사용으로 처리 — 잠금 체크 불필요
if /usr/bin/python3 "$UPDATE_PY" >> "$LOG" 2>&1; then
    if /usr/bin/python3 tests/smoke_sales_check.py >> "$LOG" 2>&1; then
        /usr/bin/python3 notify_sales_done.py "성공" "다운로드 + 판매 통계.xlsx 업데이트 완료" >> "$LOG" 2>&1
        touch "$MARKER"
    else
        /usr/bin/python3 notify_sales_done.py "실패" "smoke 검증 실패 — 판매 통계.xlsx 미갱신" >> "$LOG" 2>&1
        rm -f "$MARKER"
        exit 1
    fi
else
    /usr/bin/python3 notify_sales_done.py "실패" "update_sales.py 오류 — logs/download_sales.log 확인 필요" >> "$LOG" 2>&1
    rm -f "$MARKER"
    exit 1
fi
