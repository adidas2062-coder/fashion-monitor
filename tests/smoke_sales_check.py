#!/usr/bin/env python3
import os
import pathlib
import sys
from datetime import datetime


STATS_FILE = pathlib.Path.home() / "Library/CloudStorage/OneDrive-개인/바탕 화면/판매 통계.xlsx"


def today_8am_timestamp(now=None):
    now = now or datetime.now()
    return datetime(now.year, now.month, now.day, 8, 0, 0).timestamp()


def main():
    if not STATS_FILE.exists():
        print(f"판매 통계.xlsx 없음: {STATS_FILE}", file=sys.stderr)
        return 1

    mtime = os.path.getmtime(STATS_FILE)
    cutoff = today_8am_timestamp()
    if mtime < cutoff:
        updated_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        cutoff_at = datetime.fromtimestamp(cutoff).strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"판매 통계.xlsx mtime 오래됨: {updated_at} < {cutoff_at}",
            file=sys.stderr,
        )
        return 1

    print(f"판매 통계.xlsx 업데이트 확인: {datetime.fromtimestamp(mtime):%Y-%m-%d %H:%M:%S}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
