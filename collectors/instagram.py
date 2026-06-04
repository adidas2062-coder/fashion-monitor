"""
인스타그램 해시태그 게시물 수 수집기.

instaloader를 사용해 패션 해시태그별 게시물 수를 수집한다.
Instagram이 로그인 없이는 해시태그 데이터를 차단하므로,
config.py의 INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD 가 설정된 경우에만 실행한다.
실패 시 경고 로그만 남기고 빈 리스트 반환 (다른 모듈 계속 실행).

⚠️  Instagram API는 빈번히 정책이 바뀌므로 가장 불안정한 수집 모듈이다.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────


def _kst_today() -> str:
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")

def _build_loader():
    """
    instaloader 인스턴스 생성 및 로그인.
    로그인 성공 시 인스턴스 반환, 실패·미설정 시 None.
    """
    try:
        import instaloader  # 지연 임포트 — 설치 여부 런타임 확인
    except ImportError:
        logger.warning("instaloader 미설치 — 인스타그램 수집 스킵 (pip install instaloader)")
        return None

    if not config.INSTAGRAM_USERNAME or not config.INSTAGRAM_PASSWORD:
        logger.warning("INSTAGRAM_USERNAME/PASSWORD 미설정 — 인스타그램 수집 스킵")
        return None

    L = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        quiet=True,
    )
    try:
        L.login(config.INSTAGRAM_USERNAME, config.INSTAGRAM_PASSWORD)
        logger.info("Instagram 로그인 성공: %s", config.INSTAGRAM_USERNAME)
        return L
    except Exception as exc:
        logger.error("Instagram 로그인 실패: %s", exc)
        return None


def _fetch_tag(loader, tag: str) -> Optional[int]:
    """
    단일 해시태그 게시물 수 반환.
    실패 시 None.
    """
    import instaloader

    try:
        hashtag = instaloader.Hashtag.from_name(loader.context, tag)
        return hashtag.mediacount
    except instaloader.exceptions.ConnectionException as exc:
        logger.warning("해시태그 [#%s] 조회 실패: %s", tag, exc)
        return None
    except Exception as exc:
        logger.warning("해시태그 [#%s] 예외: %s", tag, exc)
        return None


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def collect(tags: Optional[List[str]] = None) -> List[Dict]:
    """
    패션 해시태그별 게시물 수 수집.

    Args:
        tags: 수집할 해시태그 목록. None이면 config.INSTAGRAM_TAGS 사용.

    Returns:
        해시태그별 dict 목록. 로그인 실패·미설정 시 빈 리스트.
    """
    tags = tags or config.INSTAGRAM_TAGS
    collected_at = _kst_today()

    loader = _build_loader()
    if loader is None:
        return []

    results: List[Dict] = []
    for i, tag in enumerate(tags):
        if i > 0:
            time.sleep(config.REQUEST_DELAY * 2)   # 인스타는 더 길게 대기

        count = _fetch_tag(loader, tag)
        if count is None:
            continue

        results.append({
            "platform":    "인스타",
            "keyword":     f"#{tag}",
            "score":       count,
            "prev_score":  0,
            "change":      0.0,
            "change_pct":  0.0,
            "collected_at": collected_at,
        })
        logger.info("  #%s: %d건", tag, count)

    logger.info("인스타그램 수집 완료: %d/%d 태그", len(results), len(tags))
    return results
