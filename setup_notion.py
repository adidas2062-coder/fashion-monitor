"""
노션 DB 자동 생성 스크립트.

config.py에 있는 5개 페이지 안에
컬럼 스키마가 정의된 데이터베이스를 자동으로 생성하고
실제 DB ID를 config.py에 업데이트한다.

실행:
    python3 setup_notion.py
"""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
import config
from notion_client import Client

client = Client(auth=config.NOTION_API_KEY)

# ── DB 스키마 정의 ────────────────────────────────────────────────────────────

SCHEMAS = {
    "NOTION_RANKING_DB_ID": {
        "title":   "무신사 랭킹",
        "page_id": config.NOTION_RANKING_DB_ID,
        "properties": {
            "상품명":   {"title": {}},
            "날짜":     {"date": {}},
            "카테고리": {"select": {}},
            "기간":     {"select": {}},
            "순위":     {"number": {"format": "number"}},
            "순위변동": {"number": {"format": "number"}},
            "브랜드":   {"rich_text": {}},
            "가격":     {"number": {"format": "won"}},
            "할인율":   {"number": {"format": "percent"}},
            "URL":      {"url": {}},
        },
    },
    "NOTION_TREND_DB_ID": {
        "title":   "트렌드 키워드",
        "page_id": config.NOTION_TREND_DB_ID,
        "properties": {
            "키워드":       {"title": {}},
            "날짜":         {"date": {}},
            "플랫폼":       {"select": {}},
            "점수/수치":    {"number": {"format": "number"}},
            "전주대비변화": {"number": {"format": "number"}},
        },
    },
    "NOTION_NEW_ENTRY_DB_ID": {
        "title":   "신규진입상품",
        "page_id": config.NOTION_NEW_ENTRY_DB_ID,
        "properties": {
            "상품명":   {"title": {}},
            "날짜":     {"date": {}},
            "카테고리": {"select": {}},
            "브랜드":   {"rich_text": {}},
            "가격":     {"number": {"format": "won"}},
            "소재":     {"rich_text": {}},
            "핏타입":   {"select": {}},
            "주요색상": {"rich_text": {}},
            "리뷰수":   {"number": {"format": "number"}},
            "평점":     {"number": {"format": "number"}},
            "URL":      {"url": {}},
        },
    },
    "NOTION_BRAND_DB_ID": {
        "title":   "브랜드트래킹",
        "page_id": config.NOTION_BRAND_DB_ID,
        "properties": {
            "브랜드":       {"title": {}},
            "날짜":         {"date": {}},
            "랭킹내상품수": {"number": {"format": "number"}},
            "최고순위":     {"number": {"format": "number"}},
            "최고순위상품": {"rich_text": {}},
        },
    },
    "NOTION_SIGNAL_DB_ID": {
        "title":   "기획전시그널",
        "page_id": config.NOTION_SIGNAL_DB_ID,
        "properties": {
            "키워드":      {"title": {}},
            "날짜":        {"date": {}},
            "트렌드상승률": {"number": {"format": "number"}},
            "랭킹변동":    {"number": {"format": "number"}},
            "추천테마":    {"rich_text": {}},
        },
    },
}


def create_db(config_key: str, schema: dict) -> str:
    """페이지 안에 DB 생성 → DB ID 반환."""
    print(f"\n[{schema['title']}] 생성 중...", end=" ", flush=True)
    try:
        result = client.databases.create(
            parent={"type": "page_id", "page_id": schema["page_id"]},
            title=[{"type": "text", "text": {"content": schema["title"]}}],
            properties=schema["properties"],
        )
        db_id = result["id"].replace("-", "")
        print(f"✅ ID={db_id}")
        return db_id
    except Exception as e:
        print(f"❌ 실패: {e}")
        return ""


def update_config(updates: dict) -> None:
    """config.py의 DB ID 값 업데이트."""
    with open("config.py", "r", encoding="utf-8") as f:
        content = f.read()

    for key, new_id in updates.items():
        if not new_id:
            continue
        content = re.sub(
            rf'^{key}\s*=\s*"[^"]*"',
            f'{key} = "{new_id}"',
            content,
            flags=re.MULTILINE,
        )

    with open("config.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("\nconfig.py 업데이트 완료")


def main():
    print("=" * 55)
    print("  노션 DB 자동 생성")
    print("=" * 55)

    if not config.NOTION_API_KEY:
        print("❌ NOTION_API_KEY 가 비어있습니다.")
        sys.exit(1)

    updates = {}
    for config_key, schema in SCHEMAS.items():
        db_id = create_db(config_key, schema)
        if db_id:
            updates[config_key] = db_id

    if updates:
        update_config(updates)
        print(f"\n✅ {len(updates)}/5개 DB 생성 완료")
        print("\n생성된 DB ID:")
        for k, v in updates.items():
            print(f"  {k} = {v}")
    else:
        print("\n❌ DB 생성 실패 — 노션 페이지 연결 상태를 확인하세요.")


if __name__ == "__main__":
    main()
