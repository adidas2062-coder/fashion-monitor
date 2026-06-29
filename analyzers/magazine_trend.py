"""무신사 매거진 트렌드 분석 — 콘텐츠 타입·키워드 집계."""
import logging
import re
from collections import Counter, defaultdict
from typing import Dict, List

logger = logging.getLogger(__name__)

# 제목에서 추출할 패션 카테고리 키워드
_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "상의":  ["티셔츠", "반팔", "긴팔", "맨투맨", "후드", "셔츠", "니트", "블라우스", "탑", "카라"],
    "아우터": ["자켓", "재킷", "코트", "점퍼", "패딩", "바람막이", "집업", "가디건", "블레이저", "아우터"],
    "바지":  ["팬츠", "슬랙스", "데님", "청바지", "조거", "숏", "반바지", "와이드"],
    "신발":  ["스니커즈", "운동화", "러닝화", "샌들", "로퍼", "부츠"],
    "가방":  ["백", "가방", "크로스백", "토트", "파우치"],
}

# 주목할 소재/스타일 키워드
_STYLE_KEYWORDS = [
    "린넨", "데님", "오버핏", "와이드", "크롭", "루즈", "슬림",
    "캐주얼", "스트릿", "스포티", "미니멀", "빈티지", "워크웨어",
    "아웃도어", "러닝", "코어",
]


def analyze(magazine_items: List[Dict]) -> Dict:
    """매거진 콘텐츠 목록에서 트렌드를 집계한다.

    Returns:
        {
          "content_types":  [(타입, 건수), ...],   # 콘텐츠 유형 분포
          "top_keywords":   [(키워드, 건수), ...],  # 제목 키워드 빈도
          "top_categories": [(카테고리, 건수), ...],# 패션 카테고리 언급 빈도
          "hot_items":      [콘텐츠 dict, ...],    # 조회수 높은 상위 5건
          "recent_items":   [콘텐츠 dict, ...],    # 최신 5건
          "summary":        str,
        }
    """
    if not magazine_items:
        return {
            "content_types": [], "top_keywords": [], "top_categories": [],
            "hot_items": [], "recent_items": [], "summary": "데이터 없음",
        }

    type_counter     = Counter()
    keyword_counter  = Counter()
    category_counter = Counter()

    def _parse_view(view_text: str) -> int:
        """'1.2만', '6.8천' → 정수"""
        if not view_text:
            return 0
        try:
            if "만" in view_text:
                return int(float(view_text.replace("만", "").strip()) * 10_000)
            if "천" in view_text:
                return int(float(view_text.replace("천", "").strip()) * 1_000)
            return int(view_text.replace(",", ""))
        except ValueError:
            return 0

    for item in magazine_items:
        # 콘텐츠 유형
        ct = item.get("content_type", "")
        if ct:
            type_counter[ct] += 1

        # 제목 키워드
        title = item.get("title", "")
        for kw in _STYLE_KEYWORDS:
            if kw in title:
                keyword_counter[kw] += 1

        # 패션 카테고리 언급
        for cat, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in title for kw in keywords):
                category_counter[cat] += 1

    # 조회수 기준 상위 5건
    enriched = [
        {**it, "_view_int": _parse_view(it.get("view_count", ""))}
        for it in magazine_items
    ]
    hot_items = sorted(enriched, key=lambda x: x["_view_int"], reverse=True)[:5]
    for h in hot_items:
        h.pop("_view_int", None)

    # 날짜 기준 최신 5건
    recent_items = sorted(
        magazine_items,
        key=lambda x: x.get("date", ""),
        reverse=True,
    )[:5]

    top_keywords   = keyword_counter.most_common(8)
    top_categories = category_counter.most_common(5)
    top_types      = type_counter.most_common(5)

    summary_parts = []
    if top_keywords:
        summary_parts.append("키워드: " + " · ".join(f"{k}({n})" for k, n in top_keywords[:4]))
    if top_categories:
        summary_parts.append("카테고리: " + " · ".join(f"{c}({n})" for c, n in top_categories[:3]))

    logger.info("매거진 트렌드 집계: 콘텐츠 %d건, 키워드 %d종", len(magazine_items), len(keyword_counter))
    return {
        "content_types":  top_types,
        "top_keywords":   top_keywords,
        "top_categories": top_categories,
        "hot_items":      hot_items,
        "recent_items":   recent_items,
        "summary":        " | ".join(summary_parts) if summary_parts else "키워드 없음",
    }
