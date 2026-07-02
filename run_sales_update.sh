#!/bin/bash
# 평일 아침: 판매통계 엑셀 5종 자동 다운로드 → 판매 통계.xlsx 자동 업데이트 → 슬랙 알림
# 8:50~9:10 사이 매분 cron이 깨워보고, 노트북이 켜져 네트워크가 잡히는 첫 순간 1회만 실행
cd "/Users/jeonjuwon/fashion-monitor" || exit 1

LOG="logs/download_sales.log"
MARKER="logs/.sales_ran_$(date '+%Y%m%d')"
FAIL_STATE="logs/.sales_fail_$(date '+%Y%m%d')"   # 직전 실패의 오류 시그니처
STOP_FILE="logs/.sales_stop_$(date '+%Y%m%d')"    # 같은 오류 2회 연속 → 오늘 재시도 중단

# 중복 실행 방지 락 (mkdir은 원자적 — curl 대기 중 다음 분 cron이 동시 진입하는 것 방지)
LOCKDIR="/tmp/.sales_update.lock"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
    exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT

# 같은 오류 2회 연속으로 오늘 중단된 상태면 재시도하지 않음
[ -f "$STOP_FILE" ] && exit 0

# 실패 처리: 오류 설명+해결법을 슬랙으로 발송하고, 같은 오류가 2회 연속이면 오늘은 중단
handle_failure() {
    local stage_msg="$1"
    local detail sig
    detail=$(/usr/bin/python3 sales_error_report.py "$LOG" 2>/dev/null)
    sig=$(/usr/bin/python3 sales_error_report.py "$LOG" --sig 2>/dev/null)
    rm -f "$MARKER"
    if [ -n "$sig" ] && [ -f "$FAIL_STATE" ] && [ "$(cat "$FAIL_STATE" 2>/dev/null)" = "$sig" ]; then
        rm -f "$FAIL_STATE"
        touch "$STOP_FILE"
        /usr/bin/python3 notify_sales_done.py "실패" "$stage_msg
같은 오류로 2회 연속 실패 — 오늘 자동 재시도를 중단합니다.
해결 후 재실행: rm -f ~/fashion-monitor/$STOP_FILE && cd ~/fashion-monitor && bash run_sales_update.sh

$detail" >> "$LOG" 2>&1
    else
        printf '%s' "$sig" > "$FAIL_STATE"
        /usr/bin/python3 notify_sales_done.py "실패" "$stage_msg (다음 크론에서 1회 재시도)

$detail" >> "$LOG" 2>&1
    fi
    exit 1
}

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
    handle_failure "다운로드 오류"
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 판매 통계.xlsx 업데이트 시작 =====" >> "$LOG"

# Excel이 열려있어도 기존 인스턴스 재사용으로 처리 — 잠금 체크 불필요
if /usr/bin/python3 "$UPDATE_PY" >> "$LOG" 2>&1; then
    if /usr/bin/python3 tests/smoke_sales_check.py >> "$LOG" 2>&1; then
        /usr/bin/python3 notify_sales_done.py "성공" "다운로드 + 판매 통계.xlsx 업데이트 완료" >> "$LOG" 2>&1
        touch "$MARKER"
        rm -f "$FAIL_STATE"
    else
        handle_failure "smoke 검증 실패 — 판매 통계.xlsx 미갱신"
    fi
else
    handle_failure "update_sales.py 오류"
fi
