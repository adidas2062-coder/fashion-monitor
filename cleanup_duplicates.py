"""6/12 cron 중복 실행으로 생성된 노션 중복 페이지 정리 (아카이브 처리).

대상: 랭킹 DB, 29CM 랭킹 DB, 트렌드 DB (2026-06-12 데이터)
방식: 페이지의 모든 속성값을 직렬화해 "지문(fingerprint)"을 만들고,
      동일 지문을 가진 페이지들 중 가장 먼저 생성된 1개만 남기고 나머지는 archived=True 처리.
      (archived=True는 노션 휴지통으로 이동 — 30일간 복구 가능)
"""

import time
from collections import defaultdict

import config
from notion_client import Client

nc = Client(auth=config.NOTION_API_KEY)

TARGETS = {
    "랭킹 DB": config.NOTION_RANKING_DB_ID,
    "29CM 랭킹 DB": config.CM29_RANKING_DB_ID,
    "트렌드 DB": config.NOTION_TREND_DB_ID,
}

DATE = "2026-06-12"


def fetch_all(db_id):
    pages = []
    cursor = None
    while True:
        resp = nc.databases.query(
            database_id=db_id,
            filter={"property": "날짜", "date": {"equals": DATE}},
            start_cursor=cursor,
            page_size=100,
        )
        pages.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]
    return pages


def serialize_value(prop):
    t = prop["type"]
    v = prop.get(t)
    if t in ("title", "rich_text"):
        return "".join(seg.get("plain_text", "") for seg in (v or []))
    if t == "number":
        return v
    if t == "select":
        return v["name"] if v else None
    if t == "multi_select":
        return tuple(sorted(x["name"] for x in (v or [])))
    if t == "status":
        return v["name"] if v else None
    if t == "date":
        if not v:
            return None
        return (v.get("start"), v.get("end"))
    if t in ("url", "email", "phone_number", "checkbox"):
        return v
    return str(v)


def fingerprint(page):
    props = page["properties"]
    items = []
    for name, prop in props.items():
        items.append((name, serialize_value(prop)))
    return tuple(sorted(items, key=lambda x: x[0]))


def main():
    total_archived = 0
    for label, db_id in TARGETS.items():
        pages = fetch_all(db_id)
        groups = defaultdict(list)
        for p in pages:
            groups[fingerprint(p)].append(p)

        to_archive = []
        for fp, plist in groups.items():
            if len(plist) > 1:
                plist.sort(key=lambda p: p["created_time"])
                to_archive.extend(plist[1:])  # 가장 먼저 생성된 1개만 남김

        print(f"{label}: 총 {len(pages)}건, 유니크 {len(groups)}건, 아카이브 대상 {len(to_archive)}건")

        for p in to_archive:
            nc.pages.update(page_id=p["id"], archived=True)
            total_archived += 1
            time.sleep(0.35)

        print(f"{label}: 아카이브 완료 ({len(to_archive)}건)")

    print(f"\n총 아카이브: {total_archived}건")


if __name__ == "__main__":
    main()
