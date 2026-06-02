"""
전날 대비 순위 변동 분석기.

오늘 수집한 무신사 랭킹 데이터와 어제 데이터를 비교해
상승/하락/신규/이탈 상품을 판별한다.

어제 데이터 소스: 노션 DB (notion_exporter에서 주입) 또는 직접 전달.
노션 연동 전에도 단독으로 사용 가능하도록 순수 데이터 변환 함수로 구현.
"""

import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _key(item: Dict) -> Tuple[str, str]:
    """상품 동일성 판단 기준: (카테고리, 상품명)."""
    return (item.get("category", ""), item.get("product_name", ""))


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def analyze(today: List[Dict], yesterday: List[Dict]) -> Dict:
    """
    오늘 랭킹과 어제 랭킹을 비교해 변동 정보를 반환한다.

    Args:
        today:     오늘 수집된 무신사 상품 dict 목록 (collectors/musinsa.py 출력 형식).
        yesterday: 어제 수집된 무신사 상품 dict 목록 (동일 형식).

    Returns:
        {
          "items":       오늘 상품 목록에 rank_change 필드 추가된 버전,
          "top_risers":  상승 TOP 5,
          "top_fallers": 하락 TOP 5,
          "new_entries": 신규 진입 상품 목록,
          "dropouts":    이탈 상품 목록,
          "summary":     카테고리별 요약 문자열,
        }
    """
    # 어제 데이터를 (카테고리, 상품명) → 순위 맵으로 변환
    yesterday_map: Dict[Tuple, int] = {_key(item): item["rank"] for item in yesterday}
    today_keys = {_key(item) for item in today}

    enriched: List[Dict] = []
    for item in today:
        k = _key(item)
        yesterday_rank = yesterday_map.get(k)
        if yesterday_rank is None:
            rank_change = None   # 신규 진입
        else:
            rank_change = yesterday_rank - item["rank"]  # 양수=상승
        enriched.append({**item, "rank_change": rank_change})

    # 신규 진입: 어제 없던 상품
    new_entries = [i for i in enriched if i["rank_change"] is None]

    # 이탈: 어제 있었지만 오늘 없는 상품
    dropouts: List[Dict] = []
    for item in yesterday:
        if _key(item) not in today_keys:
            dropouts.append(item)

    # 순위 변동 랭킹 (신규 제외)
    changed = [i for i in enriched if i["rank_change"] is not None]
    top_risers  = sorted(changed, key=lambda x: x["rank_change"], reverse=True)[:5]
    top_fallers = sorted(changed, key=lambda x: x["rank_change"])[:5]

    # 카테고리별 요약
    summary_lines: List[str] = []
    cats = dict.fromkeys(i["category"] for i in enriched)
    for cat in cats:
        cat_items = [i for i in enriched if i["category"] == cat]
        new_cnt  = sum(1 for i in cat_items if i["rank_change"] is None)
        rise_cnt = sum(1 for i in cat_items if i["rank_change"] and i["rank_change"] > 0)
        fall_cnt = sum(1 for i in cat_items if i["rank_change"] and i["rank_change"] < 0)
        summary_lines.append(
            f"[{cat}] 신규:{new_cnt} 상승:{rise_cnt} 하락:{fall_cnt}"
        )

    result = {
        "items":       enriched,
        "top_risers":  top_risers,
        "top_fallers": top_fallers,
        "new_entries": new_entries,
        "dropouts":    dropouts,
        "summary":     " | ".join(summary_lines),
    }

    logger.info(
        "순위 변동 분석 완료 — 신규:%d 이탈:%d 상승TOP:%s 하락TOP:%s",
        len(new_entries),
        len(dropouts),
        [f"{i['product_name'][:10]}(+{i['rank_change']})" for i in top_risers[:3]],
        [f"{i['product_name'][:10]}({i['rank_change']})"  for i in top_fallers[:3]],
    )
    return result
