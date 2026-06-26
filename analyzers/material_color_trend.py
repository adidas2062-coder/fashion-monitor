"""소재·색상 트렌드 집계기 — 신규 진입 상품 데이터 기반."""
import logging
import re
from collections import Counter
from typing import Dict, List

logger = logging.getLogger(__name__)

# 소재 정규화 맵 (상품명 키워드 포함)
_MATERIAL_MAP = {
    "린넨": "린넨", "linen": "린넨",
    "데님": "데님", "denim": "데님", "청": "데님",
    "니트": "니트", "knit": "니트",
    "코튼": "코튼", "cotton": "코튼", "면": "코튼",
    "울": "울", "wool": "울",
    "폴리": "폴리", "polyester": "폴리",
    "나일론": "나일론", "nylon": "나일론",
    "레이온": "레이온", "rayon": "레이온",
    "시어서커": "시어서커",
    "실크": "실크", "silk": "실크",
    "테리": "테리", "terry": "테리",
    "플리스": "플리스", "fleece": "플리스",
    "저지": "저지", "jersey": "저지",
    "체크": "체크", "스트라이프": "스트라이프",
    "옥스포드": "옥스포드", "oxford": "옥스포드",
    "피케": "피케", "pique": "피케",
    "벨벳": "벨벳", "velvet": "벨벳",
    "워싱": "워싱", "와플": "와플", "waffle": "와플",
}

# 색상 키워드 (상품명에서 추출)
_COLOR_KEYWORDS = [
    "블랙", "화이트", "베이지", "그레이", "그레이", "네이비", "카키", "아이보리",
    "브라운", "오트밀", "크림", "그린", "블루", "레드", "버건디", "올리브",
    "차콜", "피그먼트", "옐로우", "오렌지", "퍼플", "라벤더", "민트", "코랄",
    "스카이", "인디고", "머스타드", "와인", "샌드", "모카",
]

# 핏 키워드
_FIT_KEYWORDS = {
    "오버핏": "오버핏", "오버사이즈": "오버핏", "oversized": "오버핏",
    "와이드": "와이드", "루즈": "루즈",
    "슬림": "슬림", "slim": "슬림",
    "레귤러": "레귤러", "regular": "레귤러",
    "크롭": "크롭", "crop": "크롭",
}


def _extract_from_name(product_name: str, material_counter, color_counter, fit_counter):
    """상품명에서 소재·색상·핏 키워드를 탐색해 카운터에 추가."""
    lower = product_name.lower()
    # 소재
    for key, normalized in _MATERIAL_MAP.items():
        if key.lower() in lower:
            material_counter[normalized] += 1
            break
    # 색상 (상품명 그대로 검색)
    for color in _COLOR_KEYWORDS:
        if color in product_name:
            color_counter[color] += 1
            break
    # 핏
    for kw, normalized in _FIT_KEYWORDS.items():
        if kw.lower() in lower:
            fit_counter[normalized] += 1
            break


def analyze(new_entries: List[Dict]) -> Dict:
    """
    신규 진입 상품 목록에서 소재·색상 트렌드 집계.

    Args:
        new_entries: new_entry.enrich() 결과 목록.
                     enrich()에서 구조화 데이터(material, colors, fit_type)가 없으면
                     product_name 키워드 폴백을 사용한다.

    Returns:
        {
          "top_materials": [(소재, 건수), ...],
          "top_colors":    [(색상, 건수), ...],
          "fit_types":     [(핏, 건수), ...],
          "summary":       요약 문자열,
        }
    """
    material_counter = Counter()
    color_counter    = Counter()
    fit_counter      = Counter()

    for item in new_entries:
        pname = item.get("product_name", "")
        lower = pname.lower()

        # 소재 — 구조화 우선, 없으면 상품명 폴백
        raw_mat = (item.get("material") or "").lower()
        mat_found = False
        if raw_mat:
            for key, normalized in _MATERIAL_MAP.items():
                if key.lower() in raw_mat:
                    material_counter[normalized] += 1
                    mat_found = True
                    break
        if not mat_found and pname:
            for key, normalized in _MATERIAL_MAP.items():
                if key.lower() in lower:
                    material_counter[normalized] += 1
                    break

        # 색상 — 구조화 우선, 없으면 상품명 폴백
        colors = item.get("colors", [])
        if colors:
            for color in colors:
                if color and len(color) > 1:
                    color_counter[color.strip()] += 1
        elif pname:
            for color in _COLOR_KEYWORDS:
                if color in pname:
                    color_counter[color] += 1
                    break

        # 핏 (구조화 우선, 없으면 상품명 폴백)
        fit = item.get("fit_type", "")
        if fit:
            fit_counter[fit] += 1
        elif pname:
            for kw, normalized in _FIT_KEYWORDS.items():
                if kw.lower() in lower:
                    fit_counter[normalized] += 1
                    break

    top_materials = material_counter.most_common(5)
    top_colors    = color_counter.most_common(5)
    top_fits      = fit_counter.most_common(3)

    summary_parts = []
    if top_materials:
        summary_parts.append("소재: " + " · ".join(f"{m}({n})" for m, n in top_materials[:3]))
    if top_fits:
        summary_parts.append("핏: " + " · ".join(f"{f}({n})" for f, n in top_fits))

    result = {
        "top_materials": top_materials,
        "top_colors":    top_colors,
        "fit_types":     top_fits,
        "total_items":   len(new_entries),
        "summary":       " | ".join(summary_parts) if summary_parts else "데이터 부족",
    }

    logger.info("소재·색상 트렌드 집계: 소재 %d종 색상 %d종",
                len(material_counter), len(color_counter))
    return result
