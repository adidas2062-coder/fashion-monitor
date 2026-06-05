"""소재·색상 트렌드 집계기 — 신규 진입 상품 데이터 기반."""
import logging
from collections import Counter
from typing import Dict, List

logger = logging.getLogger(__name__)

# 소재 정규화 맵
_MATERIAL_MAP = {
    "린넨": "린넨", "linen": "린넨",
    "데님": "데님", "denim": "데님",
    "니트": "니트", "knit": "니트",
    "코튼": "코튼", "cotton": "코튼", "면": "코튼",
    "울": "울", "wool": "울",
    "폴리": "폴리", "polyester": "폴리",
    "나일론": "나일론", "nylon": "나일론",
    "레이온": "레이온", "rayon": "레이온",
    "시어서커": "시어서커", "실크": "실크", "silk": "실크",
}


def analyze(new_entries: List[Dict]) -> Dict:
    """
    신규 진입 상품 목록에서 소재·색상 트렌드 집계.

    Args:
        new_entries: new_entry.enrich() 결과 목록.

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
        # 소재
        raw_mat = (item.get("material") or "").lower()
        for key, normalized in _MATERIAL_MAP.items():
            if key in raw_mat:
                material_counter[normalized] += 1
                break

        # 색상
        for color in item.get("colors", []):
            if color and len(color) > 1:
                color_counter[color.strip()] += 1

        # 핏
        fit = item.get("fit_type", "")
        if fit:
            fit_counter[fit] += 1

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
