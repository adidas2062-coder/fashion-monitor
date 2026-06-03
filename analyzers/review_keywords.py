"""
리뷰 키워드 분석기 (무료, API 키 불필요).

무신사 상품 리뷰 텍스트에서 긍정/부정 키워드 빈도를 집계해
간단한 감성 점수와 핵심 키워드를 추출한다.
"""

import json
import logging
import re
import time
import urllib.request
from typing import Dict, List, Tuple

import config

logger = logging.getLogger(__name__)

# 패션 리뷰 긍정 키워드
_POSITIVE = [
    "좋아요", "좋아", "굿", "good", "만족", "예뻐요", "예뻐", "예쁘", "이뻐",
    "fit", "핏", "핏이", "딱", "딱이에요", "딱 맞", "완벽", "추천", "재구매",
    "가성비", "퀄리티", "고급", "시원", "따뜻", "편해요", "편안", "편하",
    "색감", "색상", "깔끔", "세련", "트렌디", "스타일", "고급스러",
    "배송빨리", "빠른배송", "기대이상", "강추", "베스트",
]

# 패션 리뷰 부정 키워드
_NEGATIVE = [
    "실망", "별로", "안좋", "불만", "환불", "반품", "아쉽", "작아요", "작아",
    "커요", "커서", "크네요", "두꺼워", "얇아", "얇아요", "거칠", "냄새",
    "색다름", "달라요", "다르", "배송느려", "배송이 늦", "오래걸",
    "사이즈 오류", "불량", "터짐", "뜯김", "품질 나쁘", "저렴해 보",
]

# 사이즈 관련 (중립적이지만 중요)
_SIZE_ISSUES = ["사이즈", "작", "크", "XL", "기장", "어깨"]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.musinsa.com/",
}


def _fetch_reviews(goods_no: int, page: int = 0) -> List[str]:
    """무신사 리뷰 API에서 텍스트 목록 가져오기."""
    url = (
        f"https://goods.musinsa.com/api2/review/v1/view/list"
        f"?page={page}&pageSize=20&goodsNo={goods_no}"
        f"&sort=up_cnt_desc&selectedSimilarNo={goods_no}"
    )
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        reviews = data.get("data", {}).get("list", [])
        return [r.get("content","") for r in reviews if r.get("content")]
    except Exception as exc:
        logger.debug("리뷰 수집 실패 (goodsNo=%d): %s", goods_no, exc)
        return []


def _extract_goods_no(url: str) -> int:
    """상품 URL에서 goodsNo 추출."""
    m = re.search(r"/products/(\d+)", url)
    return int(m.group(1)) if m else 0


def analyze(item: Dict, max_reviews: int = 40) -> Dict:
    """
    단일 상품 리뷰 키워드 분석.

    Args:
        item:        상품 dict (url, product_name 포함).
        max_reviews: 분석할 최대 리뷰 수.

    Returns:
        {
          positive_count, negative_count, sentiment_score,
          top_positive, top_negative, size_mentions,
          summary
        }
    """
    goods_no = _extract_goods_no(item.get("url",""))
    if not goods_no:
        return {}

    # 리뷰 수집 (최대 2페이지)
    texts: List[str] = []
    for page in range(0, 2):
        batch = _fetch_reviews(goods_no, page)
        texts.extend(batch)
        if len(texts) >= max_reviews or len(batch) < 20:
            break
        time.sleep(config.REQUEST_DELAY)

    if not texts:
        return {}

    texts = texts[:max_reviews]
    full_text = " ".join(texts).lower()

    # 긍정/부정 카운트
    pos_counts = {kw: full_text.count(kw) for kw in _POSITIVE if kw in full_text}
    neg_counts = {kw: full_text.count(kw) for kw in _NEGATIVE if kw in full_text}
    size_count = sum(full_text.count(kw) for kw in _SIZE_ISSUES)

    pos_total = sum(pos_counts.values())
    neg_total = sum(neg_counts.values())
    total     = pos_total + neg_total or 1

    # 감성 점수 0~100 (50이 중립)
    sentiment_score = round((pos_total / total) * 100)

    # TOP 키워드
    top_pos = sorted(pos_counts.items(), key=lambda x: -x[1])[:5]
    top_neg = sorted(neg_counts.items(), key=lambda x: -x[1])[:3]

    # 요약 문장
    if sentiment_score >= 70:
        summary = f"긍정적 반응 우세 ({sentiment_score}점)"
    elif sentiment_score >= 50:
        summary = f"보통 반응 ({sentiment_score}점)"
    else:
        summary = f"부정 의견 주의 ({sentiment_score}점)"

    if size_count >= 5:
        summary += " / 사이즈 언급 많음"

    return {
        "review_count":   len(texts),
        "positive_count": pos_total,
        "negative_count": neg_total,
        "sentiment_score": sentiment_score,
        "top_positive":   [kw for kw, _ in top_pos],
        "top_negative":   [kw for kw, _ in top_neg],
        "size_mentions":  size_count,
        "summary":        summary,
    }


def analyze_batch(items: List[Dict]) -> List[Dict]:
    """여러 상품 배치 분석."""
    results = []
    for i, item in enumerate(items):
        if i > 0:
            time.sleep(config.REQUEST_DELAY * 2)
        result = analyze(item)
        if result:
            results.append({**item, "review_analysis": result})
            logger.info("리뷰 분석: %s → %s",
                        item.get("product_name","")[:20],
                        result["summary"])
    return results
