"""판매통계 자동화 실패 시 로그에서 오류를 추출해 원인 설명 + 해결 방법을 생성.

run_sales_update.sh의 실패 알림에 사용된다.

사용법:
    python3 sales_error_report.py logs/download_sales.log         # 사람용 설명 출력
    python3 sales_error_report.py logs/download_sales.log --sig   # 오류 시그니처만 출력 (같은 오류 재발 비교용)
"""

import re
import sys

# 마지막 실행 구간을 찾기 위한 로그 마커
RUN_MARKER = re.compile(r"^===== .+(다운로드|업데이트) 시작")

# 오류 라인으로 간주할 패턴
ERROR_LINE = re.compile(r"(Error|Exception|Errno|Traceback|오류|실패)")

# (시그니처 키, 감지 정규식, 원인 설명, 해결 방법)
KNOWN_PATTERNS = [
    (
        "onedrive-dataless",
        re.compile(r"Resource deadlock avoided|\[Errno 11\]"),
        "OneDrive '저장 공간 확보' 기능이 엑셀 파일을 클라우드 전용(로컬 데이터 없음)으로 "
        "바꿔서 macOS 파일 복사가 실패했습니다.",
        "터미널에서 아래 명령으로 파일을 다시 내려받은 뒤 수동 재실행하세요.\n"
        '  head -c 100 "$HOME/Library/CloudStorage/OneDrive-개인/바탕 화면/판매 통계.xlsx" > /dev/null\n'
        "재발 방지: Finder에서 해당 파일 우클릭 → '이 디바이스에 항상 유지' 설정. "
        "(2026-07-02 copy_onedrive_safe 적용 이후에는 발생하지 않아야 정상 — 재발 시 코드 확인 필요)",
    ),
    (
        "tcc-permission",
        re.compile(r"Operation not permitted|\[Errno 1\]"),
        "cron이 바탕 화면(OneDrive) 파일에 접근할 권한이 없습니다. "
        "macOS 전체 디스크 접근 권한이 풀렸을 가능성이 높습니다 (OS 업데이트 후 종종 초기화됨).",
        "시스템 설정 > 개인정보 보호 및 보안 > 전체 디스크 접근 권한에서 "
        "/usr/sbin/cron 항목을 다시 켜세요. (GUI에서만 가능)",
    ),
    (
        "playwright-timeout",
        re.compile(r"TimeoutError|Timeout \d+ms exceeded"),
        "사이트 응답이 늦거나 페이지 구조(버튼/입력창 위치)가 바뀌어 자동화가 기다리다 실패했습니다.",
        "터미널에서 수동 재현해 보세요:\n"
        "  cd ~/fashion-monitor && /usr/bin/python3 -m collectors.download_sales\n"
        "일시적 지연이면 재실행으로 해결되고, 반복되면 사이트 UI 변경이므로 "
        "collectors/download_sales.py 셀렉터 수정이 필요합니다.",
    ),
    (
        "login-2fa",
        re.compile(r"2FA|TOTP|로그인.*(실패|오류)"),
        "무신사 파트너스 로그인 또는 2단계 인증(TOTP)에 실패했습니다. "
        "Chrome 세션 만료나 인증 앱 시간 오차가 원인일 수 있습니다.",
        "Chrome에서 무신사 파트너스(partner.musinsa.com)에 직접 로그인해 "
        "세션과 2FA가 정상인지 확인한 뒤 수동 재실행하세요.",
    ),
    (
        "network",
        re.compile(r"네트워크 미연결|ConnectionError|Connection refused|ERR_INTERNET|getaddrinfo"),
        "네트워크가 연결되지 않았습니다.",
        "인터넷 연결(Wi-Fi) 확인 후 수동 재실행하세요.",
    ),
    (
        "file-missing",
        re.compile(r"메인 파일 없음|FileNotFoundError|없음 →"),
        "판매 통계.xlsx 또는 다운로드된 소스 파일을 찾지 못했습니다. "
        "OneDrive 동기화 지연이나 파일 이동이 원인일 수 있습니다.",
        "OneDrive 동기화 상태를 확인하고, 바탕 화면에 '판매 통계.xlsx'가 있는지, "
        "'판매통계 BD' 폴더에 오늘 날짜 엑셀 5종이 있는지 확인하세요.",
    ),
    (
        "excel-corrupt",
        re.compile(r"BadZipFile|InvalidFileException"),
        "판매 통계.xlsx 파일이 손상됐을 가능성이 있습니다.",
        "바탕 화면의 '판매 통계 백업.xlsx'(어제자 정상본)를 '판매 통계.xlsx'로 "
        "복사해 복원한 뒤 수동 재실행하세요.",
    ),
]

MANUAL_RERUN = "수동 재실행: cd ~/fashion-monitor && bash run_sales_update.sh"


def _last_run_lines(log_path, tail=400):
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-tail:]
    except OSError:
        return []
    start = 0
    for i, line in enumerate(lines):
        if RUN_MARKER.search(line):
            start = i
    return lines[start:]


def _extract_error(lines):
    """마지막 Traceback 블록(요약) 또는 마지막 오류 라인을 반환."""
    tb_start = None
    for i, line in enumerate(lines):
        if line.startswith("Traceback (most recent call last):"):
            tb_start = i
    if tb_start is not None:
        block = lines[tb_start:]
        # 마지막 File 프레임(실패 위치)과 최종 예외 라인만 추림
        frames = [l.strip() for l in block if l.strip().startswith("File ")]
        final = ""
        for l in block[1:]:
            if not l.startswith((" ", "\t")) and l.strip():
                final = l.strip()
                break
        parts = []
        if frames:
            parts.append(frames[-1] if "fashion-monitor" not in "".join(frames) else
                         next((f for f in reversed(frames) if "fashion-monitor" in f), frames[-1]))
        if final:
            parts.append(final)
        if parts:
            return "\n".join(parts)
    for line in reversed(lines):
        if ERROR_LINE.search(line):
            return line.strip()
    return ""


def _normalize(text):
    """숫자/경로를 지워 같은 종류의 오류인지 비교 가능한 시그니처로 만든다."""
    sig = re.sub(r"\d+", "#", text)
    sig = re.sub(r"/[^\s'\"]+", "<path>", sig)
    return sig.strip()[:120]


def main():
    log_path = sys.argv[1] if len(sys.argv) > 1 else "logs/download_sales.log"
    sig_only = "--sig" in sys.argv

    lines = _last_run_lines(log_path)
    error_text = _extract_error(lines)

    if not error_text:
        if not sig_only:
            print("[오류 내용]\n로그에서 오류를 찾지 못했습니다. 로그 확인:\n"
                  "  tail -50 ~/fashion-monitor/logs/download_sales.log\n\n" + MANUAL_RERUN)
        return

    matched = None
    for key, pattern, why, fix in KNOWN_PATTERNS:
        if pattern.search(error_text):
            matched = (key, why, fix)
            break

    if sig_only:
        print(matched[0] if matched else "unknown:" + _normalize(error_text))
        return

    out = [f"[오류 내용]\n{error_text}"]
    if matched:
        _, why, fix = matched
        out.append(f"[원인 설명]\n{why}")
        out.append(f"[해결 방법]\n{fix}")
    else:
        out.append("[원인 설명]\n등록되지 않은 오류입니다. 로그 전체 확인:\n"
                   "  tail -50 ~/fashion-monitor/logs/download_sales.log")
    out.append(MANUAL_RERUN)
    print("\n\n".join(out))


if __name__ == "__main__":
    main()
