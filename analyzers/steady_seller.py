"""
스테디셀러 감지기.

노션 랭킹 DB에서 N주 이상 TOP 10에 연속 등장하는 상품을
스테디셀러로 분류한다.

첫 실행 시에는 오늘 수집 데이터만으로 판별하고,
데이터가 쌓일수록 정확도가 높아진다.
"""

import logging
from collections import defaultdict
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MIN_WEEKS = 2        # 스테디셀러 판별 최소 등장 횟수
_TOP_N_THRESHOLD = 10 # TOP 몇 위 이내만 집계


def detect_from_notion(client, ranking_db_id: str, weeks: int = 4) -> List[Dict]:
    """
    노션 DB에서 최근 N주 데이터를 조회해 스테디셀러 감지.

    Args:
        client:         notion_client.Client 인스턴스.
        ranking_db_id:  노션 랭킹 DB ID.
        weeks:          조회할 최근 주 수.

    Returns:
        스테디셀러 상품 목록 (등장 횟수 내림차순).
    """
    from datetime import date, timedelta
    start = (date.today() - timedelta(weeks=weeks)).isoformat()

    try:
        resp = client.databases.query(
            database_id=ranking_db_id,
            filter={
                "and": [
                    {"property": "날짜",  "date": {"on_or_after": start}},
                    {"property": "순위",  "number": {"less_than_or_equal_to": _TOP_N_THRESHOLD}},
                ]
            },
        )
        pages = resp.get("results", [])
    except Exception as exc:
        logger.error("스테디셀러 노션 조회 실패: %s", exc)
        return []

    # 상품별 등장 날짜 집계
    product_dates: Dict[str, set] = defaultdict(set)
    product_info:  Dict[str, Dict] = {}

    for page in pages:
        props = page.get("properties", {})
        def get_title(p): return (p.get("title") or [{}])[0].get("text",{}).get("content","")
        def get_text(p):  return (p.get("rich_text") or [{}])[0].get("text",{}).get("content","")
        def get_num(p):   return p.get("number")
        def get_sel(p):   s=p.get("select"); return s.get("name","") if s else ""
        def get_date(p):  d=p.get("date"); return d.get("start","") if d else ""

        name = get_title(props.get("상품명",{}))
        if not name:
            continue

        dt   = get_date(props.get("날짜",{}))
        rank = get_num(props.get("순위",{}))

        product_dates[name].add(dt)
        if name not in product_info:
            product_info[name] = {
                "product_name": name,
                "brand":        get_text(props.get("브랜드",{})),
                "category":     get_sel(props.get("카테고리",{})),
                "best_rank":    rank,
                "url":          props.get("URL",{}).get("url",""),
            }
        else:
            cur_best = product_info[name].get("best_rank") or 999
            if rank and rank < cur_best:
                product_info[name]["best_rank"] = rank

    # 스테디셀러 필터링
    results: List[Dict] = []
    for name, dates in product_dates.items():
        count = len(dates)
        if count >= _MIN_WEEKS:
            info = product_info.get(name, {})
            results.append({
                **info,
                "appearances": count,
                "dates":       sorted(dates),
                "is_steady":   count >= 3,  # 3회 이상이면 확실한 스테디셀러
            })

    results.sort(key=lambda x: x["appearances"], reverse=True)
    logger.info("스테디셀러 감지: %d개 (최소 %d회 등장)", len(results), _MIN_WEEKS)
    return results


def detect_from_items(items_history: List[List[Dict]], top_n: int = _TOP_N_THRESHOLD) -> List[Dict]:
    """
    수집된 랭킹 데이터 목록(여러 날)으로 스테디셀러 감지.
    노션 없이도 동작하는 버전.

    Args:
        items_history: 날짜별 랭킹 아이템 목록의 리스트.
                       [[오늘 아이템들], [어제 아이템들], ...]
    """
    product_days: Dict[str, int] = defaultdict(int)
    product_info: Dict[str, Dict] = {}

    for day_items in items_history:
        seen_today = set()
        for item in day_items:
            rank = item.get("rank", 999)
            name = item.get("product_name", "")
            if not name or rank > top_n or name in seen_today:
                continue
            seen_today.add(name)
            product_days[name] += 1
            if name not in product_info or (item.get("rank",999) < product_info[name].get("best_rank",999)):
                product_info[name] = {
                    "product_name": name,
                    "brand":        item.get("brand",""),
                    "category":     item.get("category",""),
                    "best_rank":    rank,
                    "url":          item.get("url",""),
                    "appearances":  0,
                    "is_steady":    False,
                }

    results = []
    for name, count in product_days.items():
        if count >= _MIN_WEEKS and name in product_info:
            info = {**product_info[name], "appearances": count, "is_steady": count >= 3}
            results.append(info)

    results.sort(key=lambda x: x["appearances"], reverse=True)
    return results
