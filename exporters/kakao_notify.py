"""
카카오톡 나에게 보내기 알림 모듈.

카카오 디벨로퍼스 REST API로 일일 요약 및 기획전 시그널을 발송한다.
KAKAO_ACCESS_TOKEN 미설정 시 로그만 출력하고 스킵한다.

토큰 갱신: 카카오 액세스 토큰은 6시간 유효.
장기 운영 시 리프레시 토큰으로 갱신 필요 (별도 설정).
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)

_KAKAO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _send(text: str) -> bool:
    """
    카카오톡 나에게 보내기 텍스트 전송.
    성공 시 True, 실패 시 False.
    """
    if not config.KAKAO_ACCESS_TOKEN:
        logger.warning("KAKAO_ACCESS_TOKEN 미설정 — 카카오 발송 스킵")
        logger.info("[카카오 미발송 메시지 미리보기]\n%s", text)
        return False

    template = {
        "object_type": "text",
        "text":        text[:2000],
        "link": {
            "web_url":        "https://www.musinsa.com/main/musinsa/ranking",
            "mobile_web_url": "https://www.musinsa.com/main/musinsa/ranking",
        },
    }
    payload = urllib.parse.urlencode(
        {"template_object": json.dumps(template, ensure_ascii=False)}
    ).encode("utf-8")

    req = urllib.request.Request(_KAKAO_SEND_URL, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {config.KAKAO_ACCESS_TOKEN}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("result_code") == 0:
                logger.info("카카오 발송 성공")
                return True
            logger.warning("카카오 발송 응답 이상: %s", body)
            return False
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        logger.error("카카오 HTTP 에러 %d: %s", exc.code, err[:300])
        return False
    except Exception as exc:
        logger.error("카카오 발송 실패: %s", exc)
        return False


def _fmt_rank_change(change: Optional[int], is_new: bool = False) -> str:
    if is_new:
        return "NEW"
    if change is None:
        return "-"
    if change > 0:
        return f"▲{change}"
    if change < 0:
        return f"▼{abs(change)}"
    return "→"


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def send_daily_summary(
    rank_diff_result: Dict,
    trend_data: List[Dict],
    signals: List[Dict],
) -> bool:
    """
    일일 요약 알림 발송.

    Args:
        rank_diff_result: rank_diff.analyze() 결과.
        trend_data:       google_trends + naver_datalab 통합 데이터.
        signals:          timing_signal.detect() 결과.
    """
    today_str = date.today().strftime("%m.%d")

    # ── 급등 트렌드 키워드 (변화율 큰 순 TOP 3) ──────────────────────────────
    trend_sorted = sorted(
        [t for t in trend_data if t.get("change_pct", 0) > 0],
        key=lambda x: x["change_pct"],
        reverse=True,
    )
    trend_lines: List[str] = []
    for t in trend_sorted[:3]:
        pct = t["change_pct"]
        kw  = t["keyword"]
        platform = "구글" if "구글" in t.get("platform", "") else "네이버"
        trend_lines.append(f"  {platform}: {kw} +{pct:.0f}%")
    trend_block = "\n".join(trend_lines) if trend_lines else "  (수집 데이터 없음)"

    # ── 신규 진입 상품 TOP 3 ─────────────────────────────────────────────────
    new_entries = rank_diff_result.get("new_entries", [])[:3]
    new_lines: List[str] = []
    for item in new_entries:
        price = f"{item.get('price', 0):,}원"
        new_lines.append(f"  {item.get('product_name','')[:15]} / {item.get('brand','')} / {price}")
    new_block = "\n".join(new_lines) if new_lines else "  없음"

    # ── 전체 TOP 3 ────────────────────────────────────────────────────────────
    top_items = sorted(
        rank_diff_result.get("items", []),
        key=lambda x: x.get("rank", 999),
    )[:3]
    top_lines: List[str] = []
    for item in top_items:
        change = _fmt_rank_change(item.get("rank_change"), item.get("rank_change") is None)
        top_lines.append(
            f"  {item['rank']}위 {item.get('product_name','')[:15]} / {item.get('brand','')} {change}"
        )
    top_block = "\n".join(top_lines) if top_lines else "  없음"

    # ── 기획전 시그널 ─────────────────────────────────────────────────────────
    signal_lines: List[str] = []
    for s in signals:
        rank_txt = _fmt_rank_change(s.get("rank_change"), s.get("is_new_entry", False))
        signal_lines.append(f"  {s['keyword']} — {s.get('theme','')} ({rank_txt})")
    signal_block = "\n".join(signal_lines) if signal_lines else "  없음"

    message = f"""[패션 모니터] {today_str} 오전 10시

📈 오늘의 급등 키워드
{trend_block}

⬆ 신규 진입 상품 ({len(new_entries)}개)
{new_block}

🔥 TOP 3 (전체)
{top_block}

🎯 기획전 시그널
{signal_block}"""

    return _send(message.strip())


def send_signal_alert(signal: Dict) -> bool:
    """기획전 시그널 즉시 단독 알림."""
    rank_txt = _fmt_rank_change(signal.get("rank_change"), signal.get("is_new_entry", False))
    level    = signal.get("level", "🟢 참고")
    score    = signal.get("score", 0)
    issues   = signal.get("issues", [])
    issue_str = ("\n" + "\n".join(f"  ⚠️ {i}" for i in issues)) if issues else ""

    message = f"""{level} 기획전 타이밍 시그널! (신뢰도 {score}점)
키워드: {signal.get('keyword','')}
- 트렌드 상승: +{signal.get('trend_pct',0):.0f}%
- 무신사 랭킹: {signal.get('category','')} ({rank_txt}){issue_str}
→ 추천 기획전 테마: {signal.get('theme','')}"""

    return _send(message.strip())
