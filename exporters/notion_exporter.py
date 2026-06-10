"""
노션 DB 저장 모듈.

각 수집/분석 결과를 노션 데이터베이스에 저장한다.
노션 API 키 또는 DB ID가 미설정이면 해당 저장을 스킵한다.
저장 실패 시 로컬 CSV 백업을 생성한다.
"""

import csv
import logging
import os
import time
from datetime import date
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)

_RETRY_MAX   = 3
_RETRY_DELAY = 2.0


# ── 노션 클라이언트 초기화 ────────────────────────────────────────────────────

def _client():
    """노션 Client 인스턴스 반환. API 키 미설정 시 None."""
    if not config.NOTION_API_KEY:
        return None
    from notion_client import Client
    return Client(auth=config.NOTION_API_KEY)


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _prop_title(value: str) -> Dict:
    return {"title": [{"text": {"content": str(value)[:2000]}}]}

def _prop_text(value: str) -> Dict:
    return {"rich_text": [{"text": {"content": str(value)[:2000]}}]}

def _prop_number(value) -> Dict:
    try:
        return {"number": float(value) if value is not None else None}
    except (TypeError, ValueError):
        return {"number": None}

def _prop_select(value: str) -> Dict:
    return {"select": {"name": str(value)[:100]}} if value else {"select": None}

def _prop_date(value: str) -> Dict:
    return {"date": {"start": value}} if value else {"date": None}

def _prop_url(value: str) -> Dict:
    return {"url": value} if value else {"url": None}


def _create_page(client, db_id: str, properties: Dict) -> bool:
    """단일 페이지 생성. 실패 시 False 반환."""
    for attempt in range(1, _RETRY_MAX + 1):
        try:
            client.pages.create(
                parent={"database_id": db_id},
                properties=properties,
            )
            return True
        except Exception as exc:
            logger.warning("노션 페이지 생성 실패 (시도 %d/%d): %s", attempt, _RETRY_MAX, exc)
            if attempt < _RETRY_MAX:
                time.sleep(_RETRY_DELAY)
    return False


def _csv_backup(filename: str, rows: List[Dict]) -> None:
    """노션 저장 실패 시 CSV 파일로 백업."""
    os.makedirs("data", exist_ok=True)
    path = f"data/{filename}"
    if not rows:
        return
    fieldnames = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(rows)
    logger.info("CSV 백업 저장: %s (%d건)", path, len(rows))


def _check_db(db_id_attr: str) -> Optional[str]:
    """config에서 DB ID를 읽고, 미설정이면 None과 경고 반환."""
    db_id = getattr(config, db_id_attr, "")
    if not db_id:
        logger.warning("%s 미설정 — 해당 저장 스킵", db_id_attr)
        return None
    return db_id


# ── 공개 저장 함수 ────────────────────────────────────────────────────────────

def save_rankings(items: List[Dict]) -> None:
    """무신사 랭킹 데이터를 노션 DB에 저장."""
    client = _client()
    db_id  = _check_db("NOTION_RANKING_DB_ID")
    if not client or not db_id:
        _csv_backup(f"backup_ranking_{date.today()}.csv", items)
        return

    logger.info("노션 랭킹 저장 시작: %d건", len(items))
    fail = 0
    for item in items:
        props = {
            "상품명":    _prop_title(item.get("product_name", "")),
            "날짜":      _prop_date(item.get("collected_at", "")),
            "카테고리":  _prop_select(item.get("category", "")),
            "순위":      _prop_number(item.get("rank")),
            "순위변동":  _prop_number(item.get("rank_change")),
            "브랜드":    _prop_text(item.get("brand", "")),
            "가격":      _prop_number(item.get("price")),
            "할인율":    _prop_number(item.get("discount_rate")),
            "URL":       _prop_url(item.get("url", "")),
        }
        if not _create_page(client, db_id, props):
            fail += 1
        time.sleep(0.35)

    logger.info("노션 랭킹 저장 완료: %d건 성공 / %d건 실패", len(items) - fail, fail)
    if fail:
        _csv_backup(f"backup_ranking_{date.today()}.csv", items)


def save_trends(items: List[Dict]) -> None:
    """트렌드 키워드 데이터를 노션 DB에 저장."""
    client = _client()
    db_id  = _check_db("NOTION_TREND_DB_ID")
    if not client or not db_id:
        _csv_backup(f"backup_trend_{date.today()}.csv", items)
        return

    logger.info("노션 트렌드 저장 시작: %d건", len(items))
    fail = 0
    for item in items:
        props = {
            "키워드":       _prop_title(item.get("keyword", "")),
            "날짜":         _prop_date(item.get("collected_at", "")),
            "플랫폼":       _prop_select(item.get("platform", "")),
            "점수/수치":    _prop_number(item.get("score")),
            "전주대비변화": _prop_number(item.get("change_pct")),
            "순위":         _prop_number(item.get("rank")),
            "변동레이블":   _prop_text(item.get("fluctuation_label", "")),
            "변동수":       _prop_number(item.get("fluctuation_amount")),
        }
        if not _create_page(client, db_id, props):
            fail += 1
        time.sleep(0.35)

    logger.info("노션 트렌드 저장 완료: %d건 성공 / %d건 실패", len(items) - fail, fail)
    if fail:
        _csv_backup(f"backup_trend_{date.today()}.csv", items)


def save_new_entries(items: List[Dict]) -> None:
    """신규 진입 상품을 노션 DB에 저장."""
    client = _client()
    db_id  = _check_db("NOTION_NEW_ENTRY_DB_ID")
    if not client or not db_id:
        _csv_backup(f"backup_new_entry_{date.today()}.csv", items)
        return

    logger.info("노션 신규진입 저장 시작: %d건", len(items))
    fail = 0
    for item in items:
        colors_str = ", ".join(item.get("colors", []))
        props = {
            "상품명":   _prop_title(item.get("product_name", "")),
            "날짜":     _prop_date(item.get("collected_at", "")),
            "카테고리": _prop_select(item.get("category", "")),
            "브랜드":   _prop_text(item.get("brand", "")),
            "가격":     _prop_number(item.get("price")),
            "소재":     _prop_text(item.get("material", "")),
            "핏타입":   _prop_select(item.get("fit_type", "")),
            "주요색상": _prop_text(colors_str),
            "리뷰수":   _prop_number(item.get("review_count")),
            "평점":     _prop_number(item.get("rating")),
            "URL":      _prop_url(item.get("url", "")),
        }
        if not _create_page(client, db_id, props):
            fail += 1
        time.sleep(0.35)

    logger.info("노션 신규진입 저장 완료: %d건 성공 / %d건 실패", len(items) - fail, fail)
    if fail:
        _csv_backup(f"backup_new_entry_{date.today()}.csv", items)


def save_brand_tracking(items: List[Dict]) -> None:
    """브랜드 트래킹 데이터를 노션 DB에 저장."""
    client = _client()
    db_id  = _check_db("NOTION_BRAND_DB_ID")
    if not client or not db_id:
        _csv_backup(f"backup_brand_{date.today()}.csv", items)
        return

    logger.info("노션 브랜드 저장 시작: %d건", len(items))
    fail = 0
    for item in items:
        props = {
            "브랜드":       _prop_title(item.get("brand", "")),
            "날짜":         _prop_date(item.get("collected_at", "")),
            "랭킹내상품수": _prop_number(item.get("product_count")),
            "최고순위":     _prop_number(item.get("best_rank")),
            "최고순위상품": _prop_text(item.get("best_product") or ""),
        }
        if not _create_page(client, db_id, props):
            fail += 1
        time.sleep(0.35)

    logger.info("노션 브랜드 저장 완료: %d건 성공 / %d건 실패", len(items) - fail, fail)
    if fail:
        _csv_backup(f"backup_brand_{date.today()}.csv", items)


def save_signals(signals: List[Dict]) -> None:
    """기획전 시그널을 노션 DB에 저장."""
    if not signals:
        return
    client = _client()
    db_id  = _check_db("NOTION_SIGNAL_DB_ID")
    if not client or not db_id:
        _csv_backup(f"backup_signal_{date.today()}.csv", signals)
        return

    logger.info("노션 시그널 저장 시작: %d건", len(signals))
    fail = 0
    for s in signals:
        props = {
            "키워드":      _prop_title(s.get("keyword", "")),
            "날짜":        _prop_date(s.get("collected_at", "")),
            "트렌드상승률": _prop_number(s.get("trend_pct")),
            "랭킹변동":    _prop_number(s.get("rank_change")),
            "추천테마":    _prop_text(s.get("theme", "")),
            "점수":        _prop_number(s.get("score")),
            "레벨":        _prop_select(s.get("level", "")),
            "브랜드":      _prop_text(s.get("brand", "")),
            "카테고리":    _prop_select(s.get("category", "")),
            "권장오픈일":  _prop_text(s.get("open_label", "")),
            "신규진입":    _prop_select("예" if s.get("is_new_entry") else "아니오"),
        }
        if not _create_page(client, db_id, props):
            fail += 1
        time.sleep(0.35)

    logger.info("노션 시그널 저장 완료: %d건 성공 / %d건 실패", len(signals) - fail, fail)
    if fail:
        _csv_backup(f"backup_signal_{date.today()}.csv", signals)


def save_cm29_rankings(items: List[Dict]) -> None:
    """29CM 남성 랭킹 데이터를 노션 DB에 저장."""
    client = _client()
    db_id  = _check_db("CM29_RANKING_DB_ID")
    save_items = items

    if not client or not db_id:
        _csv_backup(f"backup_29cm_{date.today()}.csv", save_items)
        return

    logger.info("노션 29CM 랭킹 저장 시작: %d건", len(save_items))
    fail = 0
    for item in items:
        props = {
            "상품명":   _prop_title(item.get("product_name", "")),
            "날짜":     _prop_date(item.get("collected_at", "")),
            "카테고리": _prop_select(item.get("category", "")),
            "기간":     _prop_select(item.get("period", "")),
            "순위":     _prop_number(item.get("rank")),
            "브랜드":   _prop_text(item.get("brand", "")),
            "가격":     _prop_number(item.get("price")),
            "할인율":   _prop_number(item.get("discount_rate")),
            "리뷰수":   _prop_number(item.get("review_count")),
            "평점":     _prop_number(item.get("review_score")),
            "URL":      _prop_url(item.get("url", "")),
        }
        if not _create_page(client, db_id, props):
            fail += 1
        time.sleep(0.35)

    logger.info("노션 29CM 랭킹 저장 완료: %d건 성공 / %d건 실패", len(items) - fail, fail)
    if fail:
        _csv_backup(f"backup_29cm_{date.today()}.csv", items)


def fetch_yesterday_rankings() -> List[Dict]:
    """
    노션 DB에서 어제 날짜 무신사 랭킹 데이터를 조회해 반환.
    API 키 미설정 또는 실패 시 빈 리스트.
    """
    client = _client()
    db_id  = _check_db("NOTION_RANKING_DB_ID")
    if not client or not db_id:
        return []

    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    try:
        response = client.databases.query(
            database_id=db_id,
            filter={
                "property": "날짜",
                "date": {"equals": yesterday},
            },
        )
        results = response.get("results", [])
        items: List[Dict] = []
        for page in results:
            props = page.get("properties", {})
            def get_title(p):
                return (p.get("title") or [{}])[0].get("text", {}).get("content", "")
            def get_text(p):
                return (p.get("rich_text") or [{}])[0].get("text", {}).get("content", "")
            def get_number(p):
                return p.get("number")
            def get_select(p):
                sel = p.get("select")
                return sel.get("name", "") if sel else ""
            def get_url(p):
                return p.get("url", "")

            items.append({
                "product_name":  get_title(props.get("상품명", {})),
                "collected_at":  yesterday,
                "category":      get_select(props.get("카테고리", {})),
                "rank":          get_number(props.get("순위", {})),
                "rank_change":   get_number(props.get("순위변동", {})),
                "brand":         get_text(props.get("브랜드", {})),
                "price":         get_number(props.get("가격", {})) or 0,
                "discount_rate": get_number(props.get("할인율", {})) or 0,
                "url":           get_url(props.get("URL", {})),
            })
        logger.info("어제 랭킹 조회 완료: %d건 (%s)", len(items), yesterday)
        return items
    except Exception as exc:
        logger.error("어제 랭킹 조회 실패: %s", exc)
        return []
