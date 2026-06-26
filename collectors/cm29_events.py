"""29CM 에디션/기획전 모니터링 — Playwright로 /store/event 페이지 수집."""
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)

_EVENT_URL = "https://www.29cm.co.kr/store/event"


def _kst_today() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")


def collect() -> List[Dict]:
    """29CM 이벤트/에디션 목록 수집 (Playwright CSR 렌더링)."""
    collected_at = _kst_today()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("playwright 미설치 — pip install playwright && playwright install chromium")
        return []

    results = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page.goto(_EVENT_URL, wait_until="domcontentloaded", timeout=30_000)
            try:
                page.wait_for_selector('a[href*="/content/brand-news/"]', timeout=20_000)
            except Exception:
                logger.warning("29CM 이벤트 카드 대기 시간 초과 — 현재 로드된 내용으로 시도")

            # 이벤트 카드: a[href*="/content/brand-news/"]
            cards = page.query_selector_all('a[href*="/content/brand-news/"]')
            logger.info("29CM /store/event: 카드 %d개 발견", len(cards))

            seen_hrefs = set()
            for card in cards:
                href = card.get_attribute("href") or ""
                if not href or href in seen_hrefs:
                    continue
                seen_hrefs.add(href)

                if href.startswith("http"):
                    url = href
                elif href.startswith("//"):
                    url = "https:" + href
                else:
                    url = "https://www.29cm.co.kr" + href
                event_id = href.rstrip("/").split("/")[-1]

                # 카드 내 텍스트 노드 수집
                texts = card.evaluate("""el => {
                    const nodes = [...el.querySelectorAll('span, p, h1, h2, h3, div')];
                    return nodes
                        .map(n => n.childNodes.length === 1 && n.firstChild.nodeType === 3
                            ? n.textContent.trim() : '')
                        .filter(t => t.length > 1 && t.length < 120);
                }""")
                # 중복 제거하면서 순서 유지
                unique_texts = list(dict.fromkeys(texts))

                title    = unique_texts[0] if unique_texts else ""
                sub_title = unique_texts[1] if len(unique_texts) > 1 else ""
                date_str  = next((t for t in unique_texts if "~" in t or "." in t and len(t) < 30), "")

                if not title:
                    continue

                results.append({
                    "list_no":      event_id,
                    "title":        title,
                    "sub_title":    sub_title,
                    "date_range":   date_str,
                    "url":          url,
                    "image_url":    "",
                    "updated_at":   collected_at,
                    "platform":     "29CM",
                    "collected_at": collected_at,
                })

            browser.close()

    except Exception as e:
        logger.error("29CM 이벤트 수집 실패: %s", e)
        return []

    logger.info("29CM 이벤트 수집 완료: %d개", len(results))
    return results
