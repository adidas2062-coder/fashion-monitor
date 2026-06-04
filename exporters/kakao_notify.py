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
    weather_data: Optional[Dict] = None,
    cm29_data: Optional[List[Dict]] = None,
    overall_rankings: Optional[List[Dict]] = None,
) -> bool:
    """일일 요약 알림 발송."""
    from datetime import datetime, timezone, timedelta
    kst_now   = datetime.now(timezone.utc) + timedelta(hours=9)
    today_str = kst_now.strftime("%m.%d")

    # ── 날씨 ─────────────────────────────────────────────────────────────────
    if weather_data:
        wx_sig = weather_data.get("category_signal", {})
        sig_str = " / ".join(f"{k.replace('_전체','')}: {v}" for k,v in wx_sig.items())
        wx_line = f"☀️ {weather_data.get('current_temp')}°C ({weather_data.get('weather_label')}) — {sig_str}"
    else:
        wx_line = ""

    # ── 급등 트렌드 키워드 TOP 3 ─────────────────────────────────────────────
    trend_sorted = sorted(
        [t for t in trend_data if t.get("change_pct", 0) > 0
         and t.get("platform") not in ("구글_트렌딩", "무신사_검색어")],
        key=lambda x: x["change_pct"], reverse=True,
    )
    trend_lines = []
    for t in trend_sorted[:3]:
        pf = "구글" if "구글" in t.get("platform","") else "네이버"
        trend_lines.append(f"  {pf}: {t['keyword']} +{t['change_pct']:.0f}%")
    trend_block = "\n".join(trend_lines) if trend_lines else "  (데이터 수집 중)"

    # ── 무신사 실검 TOP 5 ─────────────────────────────────────────────────────
    kw_items = sorted(
        [t for t in trend_data if t.get("platform") == "무신사_검색어"],
        key=lambda x: x.get("rank", 999),
    )[:5]
    kw_block = "  " + " · ".join(
        f"{k['rank']}위 {k['keyword']}" + (
            f"({'▲' if k.get('fluctuation_type')=='UP' else '▼' if k.get('fluctuation_type')=='DOWN' else ''})"
            if k.get("fluctuation_type") not in ("NONE", None) else ""
        )
        for k in kw_items
    ) if kw_items else "  없음"

    # ── 무신사 전체 랭킹 1일 TOP 3 ───────────────────────────────────────────
    overall_top = sorted(
        [i for i in (overall_rankings or [])
         if i.get("category") == "상의_전체" and i.get("period") == "1일"],
        key=lambda x: x.get("rank", 999),
    )[:3]
    if not overall_top:
        # 폴백: rank_diff items에서 상의_전체 1일
        overall_top = sorted(
            [i for i in rank_diff_result.get("items", [])
             if i.get("category") == "상의_전체" and i.get("period") == "1일"],
            key=lambda x: x.get("rank", 999),
        )[:3]
    musinsa_lines = []
    for item in overall_top:
        ch = _fmt_rank_change(item.get("rank_change"), item.get("rank_change") is None)
        musinsa_lines.append(
            f"  {item['rank']}위 {item.get('product_name','')[:14]} / {item.get('brand','')} {ch}"
        )
    musinsa_block = "\n".join(musinsa_lines) if musinsa_lines else "  없음"

    # ── 29CM 남성 TOP 3 ───────────────────────────────────────────────────────
    cm29_top = sorted(
        [i for i in (cm29_data or []) if i.get("category") == "남성_전체"],
        key=lambda x: x.get("rank", 999),
    )[:3]
    cm29_lines = []
    for item in cm29_top:
        disc = f" -{item['discount_rate']}%" if item.get("discount_rate") else ""
        cm29_lines.append(
            f"  {item['rank']}위 {item.get('product_name','')[:14]} / {item.get('brand','')}{disc}"
        )
    cm29_block = "\n".join(cm29_lines) if cm29_lines else "  없음"

    # ── 신규 진입 TOP 3 ───────────────────────────────────────────────────────
    new_entries = rank_diff_result.get("new_entries", [])[:3]
    new_lines = []
    for item in new_entries:
        cat = item.get("category","").replace("_전체","")
        new_lines.append(
            f"  [{cat}] {item.get('product_name','')[:14]} / {item.get('brand','')} {item.get('price',0):,}원"
        )
    new_block = "\n".join(new_lines) if new_lines else "  없음"

    # ── 기획전 시그널 ─────────────────────────────────────────────────────────
    signal_lines = []
    for s in signals:
        issues_str = " · ".join(s.get("issues", []))
        signal_lines.append(
            f"  {s['level']} [{s['keyword']}] 신뢰도{s.get('score',0)}점\n"
            f"  → {s.get('theme','')} | 오픈: {s.get('open_label','')}\n"
            f"  ⚠️ {issues_str}" if issues_str else
            f"  {s['level']} [{s['keyword']}] → {s.get('theme','')} | 오픈: {s.get('open_label','')}"
        )
    signal_block = "\n".join(signal_lines) if signal_lines else "  없음"

    # ── 메시지 조립 ───────────────────────────────────────────────────────────
    wx_section = f"\n{wx_line}\n" if wx_line else ""
    # ── 무신사 전체 카테고리별 1위 ────────────────────────────────────────────
    overall_no1_lines = []
    for cat_name in ["상의_전체", "아우터_전체", "바지_전체"]:
        cat_label = cat_name.replace("_전체", "")
        items_in_cat = sorted(
            [i for i in (overall_rankings or [])
             if i.get("category") == cat_name and i.get("period") == "1일"],
            key=lambda x: x.get("rank", 999),
        )
        if items_in_cat:
            top1 = items_in_cat[0]
            disc = f" -{top1.get('discount_rate')}%" if top1.get("discount_rate") else ""
            overall_no1_lines.append(
                f"  [{cat_label}] {top1.get('product_name','')[:14]} / {top1.get('brand','')}{disc}"
            )
    overall_block = "\n".join(overall_no1_lines) if overall_no1_lines else "  없음"

    message = f"""[패션 모니터] {today_str} 일일 리포트{wx_section}
📈 트렌드 급등 키워드
{trend_block}

🔍 무신사 실검 TOP5
{kw_block}

🏆 무신사 전체 카테고리 1위
{overall_block}

👔 무신사 상의 전체 TOP3
{musinsa_block}

🛍 29CM 남성 TOP3
{cm29_block}

⬆ 신규 진입 ({len(new_entries)}건)
{new_block}

🎯 기획전 시그널
{signal_block}"""

    return _send(message.strip())


def send_signal_alert(signal: Dict) -> bool:
    """기획전 시그널 즉시 단독 알림."""
    rank_txt  = _fmt_rank_change(signal.get("rank_change"), signal.get("is_new_entry", False))
    level     = signal.get("level", "🟢 참고")
    score     = signal.get("score", 0)
    issues    = signal.get("issues", [])
    open_label = signal.get("open_label", "")

    # 이슈 요약
    issue_str = ""
    if issues:
        issue_str = "\n  ⚠️ " + " / ".join(issues)

    # YoY 정보
    yoy = signal.get("yoy_last_rank")
    yoy_str = f"\n  📊 작년 동기 최고순위: {yoy}위" if yoy else ""

    message = f"""{level} 기획전 타이밍 시그널 감지! (신뢰도 {score}점)

키워드: #{signal.get('keyword','')}
트렌드: +{signal.get('trend_pct',0):.0f}% 상승{issue_str}{yoy_str}

→ 추천 테마: {signal.get('theme','')}
📅 권장 오픈일: {open_label}

무신사 {signal.get('category','').replace('_전체','')} 랭킹 {rank_txt if rank_txt != '-' else '연관 상품 다수 진입'}"""

    return _send(message.strip())
