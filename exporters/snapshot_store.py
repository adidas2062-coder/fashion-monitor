"""날짜별 전체 수집 원본을 JSON 스냅샷으로 보존한다."""

import json
import os
from datetime import date
from typing import Dict, List


def save(name: str, rows: List[Dict], collected_on: str = "") -> str:
    snapshot_date = collected_on or (
        rows[0].get("collected_at", "") if rows else ""
    ) or date.today().isoformat()
    directory = os.path.join("data", "snapshots", snapshot_date)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{name}.json")
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)
    return path


def load(name: str, collected_on: str) -> List[Dict]:
    path = os.path.join("data", "snapshots", collected_on, f"{name}.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, list) else []


def available_dates(name: str) -> List[str]:
    root = os.path.join("data", "snapshots")
    if not os.path.isdir(root):
        return []
    dates = [
        entry for entry in os.listdir(root)
        if os.path.isfile(os.path.join(root, entry, f"{name}.json"))
    ]
    return sorted(dates)


def load_latest_before(
    name: str,
    collected_on: str,
    weekdays_only: bool = False,
) -> List[Dict]:
    candidates = [d for d in available_dates(name) if d < collected_on]
    if weekdays_only:
        candidates = [
            value for value in candidates
            if date.fromisoformat(value).weekday() < 5
        ]
    return load(name, candidates[-1]) if candidates else []


def load_history(name: str, limit: int = 7, before: str = "") -> List[List[Dict]]:
    dates = available_dates(name)
    if before:
        dates = [d for d in dates if d < before]
    return [load(name, value) for value in dates[-limit:]]
