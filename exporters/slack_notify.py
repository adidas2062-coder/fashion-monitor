"""
슬랙 알림 모듈.

Incoming Webhook으로 일일 요약 및 기획전 시그널을 발송한다.
토큰 만료 없음 — Webhook URL이 유효한 한 영구 동작.

config.py에 SLACK_WEBHOOK_URL 설정 필요.
"""

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)


def _kst_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=9)


def _post(payload: dict) -> bool:
    """슬랙 Webhook POST. 성공 시 True."""
    if not getattr(config, "SLACK_WEBHOOK_URL", ""):
        logger.warning("SLACK_WEBHOOK_URL 미설정 — 슬랙 발송 스킵")
        logger.info("[슬랙 미발송 미리보기]\n%s",
                    json.dumps(payload, ensure_ascii=False, indent=2)[:500])
        return False

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req  = urllib.request.Request(config.SLACK_WEBHOOK_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            if body == "ok":
                logger.info("슬랙 발송 성공")
                return True
            logger.warning("슬랙 응답 이상: %s", body)
            return False
    except urllib.error.HTTPError as exc:
        logger.error("슬랙 HTTP 에러 %d: %s", exc.code, exc.read().decode()[:200])
        return False
    except Exception as exc:
        logger.error("슬랙 발송 실패: %s", exc)
        return False


def _fmt_change(change: Optional[int], is_new: bool = False) -> str:
    if is_new:    return "🆕"
    if change is None: return ""
    if change > 0: return f"🔺{change}"
    if change < 0: return f"🔻{abs(change)}"
    return "➡️"


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def send_daily_summary(
    rank_diff_result: Dict,
    trend_data: List[Dict],
    signals: List[Dict],
    weather_data: Optional[Dict] = None,
    cm29_data: Optional[List[Dict]] = None,
    overall_rankings: Optional[List[Dict]] = None,
) -> bool:
    """슬랙 일일 요약 발송."""
    now = _kst_now()
    today_str = now.strftime("%-m월 %-d일")

    # 날씨
    wx_text = ""
    if weather_data:
        sig = weather_data.get("category_signal", {})
        sig_str = " | ".join(f"{k.replace('_전체','')}: {v}" for k,v in sig.items())
        wx_text = f"☀️ *{weather_data.get('current_temp')}°C* ({weather_data.get('weather_label')})  {sig_str}"

    # 트렌드
    trend_sorted = sorted(
        [t for t in trend_data if t.get("change_pct", 0) > 0
         and t.get("platform") not in ("구글_트렌딩", "무신사_검색어")],
        key=lambda x: x["change_pct"], reverse=True,
    )[:3]
    trend_text = "\n".join(
        f"  • {'구글' if '구글' in t.get('platform','') else '네이버'}: *{t['keyword']}* +{t['change_pct']:.0f}%"
        for t in trend_sorted
    ) or "  • (데이터 수집 중)"

    # 무신사 실검 TOP 5
    kw_items = sorted(
        [t for t in trend_data if t.get("platform") == "무신사_검색어"],
        key=lambda x: x.get("rank", 999),
    )[:5]
    kw_text = "  " + "  ·  ".join(f"{k['rank']}위 {k['keyword']}" for k in kw_items) if kw_items else "  없음"

    # 무신사 전체 카테고리 1위
    overall_lines = []
    for cat_name, label in [("상의_전체","상의"), ("아우터_전체","아우터"), ("바지_전체","바지")]:
        items_in_cat = sorted(
            [i for i in (overall_rankings or []) if i.get("category") == cat_name and i.get("period") == "1일"],
            key=lambda x: x.get("rank", 999),
        )
        if items_in_cat:
            t = items_in_cat[0]
            disc = f" `-{t['discount_rate']}%`" if t.get("discount_rate") else ""
            overall_lines.append(f"  • [{label}] *{t.get('product_name','')[:18]}* / {t.get('brand','')}{disc}")
    overall_text = "\n".join(overall_lines) if overall_lines else "  없음"

    # 29CM 남성 TOP 3
    cm29_top = sorted(
        [i for i in (cm29_data or []) if i.get("category") == "남성_전체"],
        key=lambda x: x.get("rank", 999),
    )[:3]
    cm29_text = "\n".join(
        f"  • {i['rank']}위 *{i.get('product_name','')[:18]}* / {i.get('brand','')} "
        + (f"`-{i['discount_rate']}%`" if i.get('discount_rate') else "")
        for i in cm29_top
    ) if cm29_top else "  없음"

    # 신규 진입 TOP 3
    new_entries = rank_diff_result.get("new_entries", [])[:3]
    new_text = "\n".join(
        f"  • [{i.get('category','').replace('_전체','')}] *{i.get('product_name','')[:16]}* / {i.get('brand','')} `{i.get('price',0):,}원`"
        for i in new_entries
    ) if new_entries else "  없음"

    # 기획전 시그널
    signal_blocks = []
    for s in signals:
        issues_str = " · ".join(s.get("issues", []))
        signal_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{s['level']} *{s['keyword']}* 기획전 시그널 _(신뢰도 {s.get('score',0)}점)_\n"
                    f"  트렌드 +{s.get('trend_pct',0):.0f}%"
                    + (f"  |  ⚠️ {issues_str}" if issues_str else "") + "\n"
                    f"  → *{s.get('theme','')}*\n"
                    f"  📅 권장 오픈일: `{s.get('open_label','')}`"
                )
            }
        })

    signal_section = signal_blocks if signal_blocks else [{
        "type": "section",
        "text": {"type": "mrkdwn", "text": "  시그널 없음"}
    }]

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"👗 패션 모니터 일일 리포트 — {today_str}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": wx_text}} if wx_text else None,
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*📈 트렌드 급등 키워드*\n{trend_text}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*🔍 무신사 실검 TOP5*\n{kw_text}"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*🏆 무신사 전체 카테고리 1위*\n{overall_text}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*🛍 29CM 남성 TOP3*\n{cm29_text}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*⬆ 신규 진입 ({len(new_entries)}건)*\n{new_text}"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "*🎯 기획전 시그널*"}},
        *signal_section,
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"패션 모니터 | {now.strftime('%H:%M')} KST"}]},
    ]
    blocks = [b for b in blocks if b]  # None 제거

    return _post({"blocks": blocks})


def send_signal_alert(signal: Dict) -> bool:
    """기획전 시그널 즉시 단독 알림."""
    level     = signal.get("level", "🟢 참고")
    score     = signal.get("score", 0)
    issues    = signal.get("issues", [])
    open_label = signal.get("open_label", "")
    rank_txt  = _fmt_change(signal.get("rank_change"), signal.get("is_new_entry", False))
    yoy       = signal.get("yoy_last_rank")

    issue_text = ("\n  ⚠️ " + " / ".join(issues)) if issues else ""
    yoy_text   = f"\n  📊 작년 동기 최고순위: {yoy}위" if yoy else ""

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{level} 기획전 타이밍 시그널 감지!"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": (
            f"*키워드:* #{signal.get('keyword','')}\n"
            f"*신뢰도:* {score}점\n"
            f"*트렌드:* +{signal.get('trend_pct',0):.0f}% 상승{issue_text}{yoy_text}\n\n"
            f"*추천 테마:* {signal.get('theme','')}\n"
            f"*📅 권장 오픈일:* `{open_label}`\n"
            f"*무신사 랭킹:* {signal.get('category','').replace('_전체','')} {rank_txt}"
        )}},
    ]

    return _post({"blocks": blocks})
