"""
HTML 대시보드 생성기.

수집/분석 결과를 Chart.js 기반 단일 HTML 파일로 출력한다.
data/dashboard.html 에 매일 덮어쓰기 저장.
"""

import json
import logging
import os
from typing import Dict, List, Optional
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _rank_badge(change) -> str:
    if change is None:
        return '<span class="badge new">NEW</span>'
    if change > 0:
        return f'<span class="badge up">▲{change}</span>'
    if change < 0:
        return f'<span class="badge down">▼{abs(change)}</span>'
    return '<span class="badge same">→</span>'


def _signal_cards(signals: List[Dict]) -> str:
    if not signals:
        return '<p class="empty">감지된 시그널 없음</p>'
    parts = []
    for s in signals:
        trend_pct = s.get("trend_pct", 0) or 0
        rank_change = s.get("rank_change")
        rank_txt = "NEW" if s.get("is_new_entry") else (f"▲{rank_change}" if rank_change else "-")

        # score/level 누락 시 trend_pct 기반 추정
        score = s.get("score") or 0
        level = s.get("level") or ""
        if score == 0 and trend_pct > 0:
            rank_bonus = 20 if s.get("is_new_entry") else (15 if rank_change and rank_change >= 5 else 0)
            score = min(int(trend_pct * 1.5) + rank_bonus, 100)
        if not any(e in level for e in ("🔴","🟡","🟢")):
            level = "🔴 긴급" if score >= 80 else ("🟡 주의" if score >= 50 else "🟢 참고")

        # open_label 누락 시 score 기반 추정
        open_label = s.get("open_label") or ""
        if not open_label and score > 0:
            from datetime import date as _date, timedelta as _td
            _today = _date.today()
            days = 5 if score >= 80 else (10 if score >= 50 else 14)
            open_label = f"{(_today + _td(days=days)).strftime('%m/%d')}까지 오픈 권장"

        issues = s.get("issues", [])
        issue_html = "".join(f'<span class="issue-tag">{i}</span>' for i in issues)
        level_cls = "lvl-red" if "🔴" in level else ("lvl-yellow" if "🟡" in level else "lvl-green")
        score_disp = str(score) if score else "?"
        parts.append(f"""
        <div class="signal-card {level_cls}">
          <div class="signal-score">{score_disp}</div>
          <h3>{level} {s.get('keyword','')}</h3>
          <p class="signal-meta">트렌드 +{trend_pct:.0f}% | 랭킹 {rank_txt}</p>
          <p class="signal-theme">→ {s.get('theme','')}</p>
          <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px">{issue_html}</div>
          <div class="open-date">📅 권장 오픈일: <strong>{open_label or '계산 중'}</strong></div>
          <p class="signal-meta" style="margin-top:6px">{s.get('brand','')} / {s.get('category','')}</p>
        </div>""")
    return "\n".join(parts)


def _md_action_cards(actions: List[Dict]) -> str:
    if not actions:
        return '<p class="empty">오늘 우선 처리할 고신뢰 액션이 없습니다.</p>'
    parts = []
    for index, action in enumerate(actions, 1):
        evidence = "".join(
            f'<span class="action-evidence">{item}</span>'
            for item in action.get("evidence", [])
        )
        parts.append(f"""
        <article class="action-card">
          <div class="action-rank">{index}</div>
          <div class="action-source">{action.get('source','시장 신호')}</div>
          <h3>{action.get('title','')}</h3>
          <div class="action-evidence-row">{evidence}</div>
          <p><b>권장 행동</b> {action.get('action','')}</p>
          <div class="action-footer">
            <span>기한 {action.get('deadline','')}</span>
            <strong>우선순위 {action.get('confidence',0)}점</strong>
          </div>
        </article>""")
    return "\n".join(parts)


def _cross_platform_block(rows: List[Dict]) -> str:
    if not rows:
        return '<p class="empty">현재 양 플랫폼 공통 반응 브랜드가 없습니다.</p>'
    trs = []
    for row in rows[:8]:
        change = row.get("rank_change")
        change_text = f"▲{change}" if change and change > 0 else "-"
        trs.append(
            f'<tr><td><b>{row.get("brand","")}</b></td>'
            f'<td>{row.get("musinsa_count",0)}개 / 최고 {row.get("musinsa_best_rank","-")}위</td>'
            f'<td>{row.get("cm29_count",0)}개 / 최고 {row.get("cm29_best_rank","-")}위</td>'
            f'<td style="color:#2f9e44;font-weight:700">{change_text}</td>'
            f'<td>{row.get("score",0)}점</td></tr>'
        )
    return (
        '<table><thead><tr><th>브랜드</th><th>무신사</th><th>29CM</th>'
        '<th>최고순위 변화</th><th>교차점수</th></tr></thead>'
        f'<tbody>{"".join(trs)}</tbody></table>'
    )


def _review_insight_block(items: List[Dict]) -> str:
    if not items:
        return '<p class="empty">분석 가능한 신규 진입 리뷰가 없습니다.</p>'
    cards = []
    for item in items[:6]:
        review = item.get("review_analysis", {})
        negative = ", ".join(review.get("top_negative", [])[:3]) or "특이사항 없음"
        cards.append(
            f'<div class="review-card"><h3>{item.get("product_name","")}</h3>'
            f'<p>{item.get("brand","")} · 감성 {review.get("sentiment_score","-")}점</p>'
            f'<p><b>{review.get("summary","")}</b></p>'
            f'<p class="muted">주의 키워드: {negative}</p></div>'
        )
    return "".join(cards)


def _data_status_block(status: Dict) -> str:
    counts = status.get("counts", {}) if status else {}
    failed = status.get("failed", []) if status else []
    state = "일부 수집 실패" if failed else "정상 수집"
    cls = "status-warning" if failed else "status-ok"
    details = " / ".join(failed[:3]) if failed else "공개 데이터 기준"
    return f"""
    <div class="data-status {cls}">
      <strong>{state}</strong>
      <span>무신사 {counts.get('musinsa',0):,}건</span>
      <span>29CM {counts.get('cm29',0):,}건</span>
      <span>트렌드 {counts.get('trends',0):,}건</span>
      <span>기획전 {counts.get('events',0):,}건</span>
      <span>{details}</span>
    </div>"""


def _backtest_block(rows: List[Dict]) -> str:
    if not rows:
        return '<p class="empty">스냅샷이 7일 이상 쌓이면 추천 적중 여부가 표시됩니다.</p>'
    completed = [
        row for row in rows
        if row.get("status") in ("적중", "부분 적중", "실패")
    ][:3]
    if completed:
        cases = "".join(
            f'<article class="case-card"><span>{row.get("status")}</span>'
            f'<h3>{row.get("theme") or row.get("keyword","")}</h3>'
            f'<p>추천점수 {row.get("score",0)}점 · 7일 변화 '
            f'{row.get("day7_change",0):+.1f}계단</p>'
            f'<p class="muted">{row.get("reason","")}</p></article>'
            for row in completed
        )
        case_html = f'<h3 class="sub">대표 검증 사례</h3><div class="case-grid">{cases}</div>'
    else:
        case_html = '<p class="empty">대표 사례는 7일 검증이 끝난 뒤 자동 선정됩니다.</p>'
    trs = []
    colors = {
        "적중": "#2f9e44",
        "부분 적중": "#e67700",
        "실패": "#e03131",
        "보류": "#6c757d",
        "검증 대기": "#3b5bdb",
    }
    for row in rows[:10]:
        day3 = "-" if row.get("day3_change") is None else f'{row["day3_change"]:+.1f}'
        day7 = "-" if row.get("day7_change") is None else f'{row["day7_change"]:+.1f}'
        status = row.get("status", "검증 대기")
        trs.append(
            f'<tr><td>{row.get("signal_date","")}</td>'
            f'<td><b>{row.get("theme") or row.get("keyword","")}</b></td>'
            f'<td>{row.get("score",0)}점</td><td>{day3}</td><td>{day7}</td>'
            f'<td style="color:{colors.get(status,"#555")};font-weight:800">{status}</td>'
            f'<td class="muted">{row.get("reason","")}</td></tr>'
        )
    table = (
        '<table><thead><tr><th>추천일</th><th>추천</th><th>추천점수</th>'
        '<th>3일 순위변화</th><th>7일 순위변화</th><th>결과</th><th>판정 근거</th>'
        f'</tr></thead><tbody>{"".join(trs)}</tbody></table>'
    )
    return case_html + table


def _methodology_block() -> str:
    return """
    <div class="method-grid">
      <div><b>공개 데이터 출처</b><p>무신사·29CM 공개 랭킹, 무신사 검색어,
      네이버 데이터랩, Google Trends, Open-Meteo, 공개 상품 리뷰</p></div>
      <div><b>추천 방식</b><p>검색 상승, 랭킹 변화, 할인·품절, 플랫폼 교차 반응,
      날씨 적합도를 결합하며 출처가 겹치지 않게 신뢰도 상위 3개를 표시합니다.
      신뢰도는 성공 확률이 아니라 공개 신호의 상대적 우선순위 점수입니다.</p></div>
      <div><b>기획전 신호 점수</b><p>트렌드 30점 + 랭킹 25점 + 할인 15점 +
      품절 10점 + 복수 카테고리 10점 + 작년 동기 10점으로 계산합니다.</p></div>
      <div><b>플랫폼 교차 점수</b><p>양 플랫폼 동시 진입 35점 + 노출 상품 수
      최대 40점 + 최근 최고순위 5계단 이상 상승 20점으로 계산합니다.</p></div>
      <div><b>날씨 액션 점수</b><p>현재는 최고기온과 3일 예보에 따른 규칙 기반
      68점으로 표시합니다. 백테스트가 쌓이면 계절별 적중률로 보정할 예정입니다.</p></div>
      <div><b>백테스트 기준</b><p>추천일 대비 3일·7일 후 관련 상품 평균 순위를 비교해
      적중, 부분 적중, 보류, 실패로 판정합니다.</p></div>
      <div><b>분석 한계</b><p>공개 랭킹은 실제 판매량과 동일하지 않으며 플랫폼 노출 정책,
      광고, 재고 변화의 영향을 받을 수 있습니다. 내부 매출은 사용하지 않습니다.</p></div>
    </div>"""


def _ranking_table(
    items: List[Dict],
    cat_prefix: str,
    period: str = "1일",
    baseline_available: bool = True,
) -> str:
    """cat_prefix 로 시작하는 카테고리 중 period 일치 항목의 TOP 30 반환."""
    # 대분류_전체 우선, 없으면 대분류_ 시작하는 전체 아이템에서 rank 오름차순
    full_cat = f"{cat_prefix}_전체"
    rows = [i for i in items
            if i.get("category") == full_cat and i.get("period") == period]
    if not rows:
        rows = [i for i in items
                if i.get("category", "").startswith(cat_prefix + "_")
                and i.get("period") == period]
        rows.sort(key=lambda x: x.get("rank", 999))
    rows = rows[:10]

    if not rows:
        return f'<p class="empty">데이터 없음 (수집 후 표시됩니다)</p>'
    trs = []
    for item in rows:
        comparison_available = item.get(
            "comparison_available", baseline_available
        )
        badge = (
            _rank_badge(item.get("rank_change"))
            if comparison_available
            else '<span class="badge same">대기</span>'
        )
        price = f"{item.get('price', 0):,}"
        disc  = item.get("discount_rate", 0)
        disc_str = f'<span class="disc">-{disc}%</span>' if disc else ""
        url   = item.get("url", "#")
        name  = item.get("product_name", "")
        brand = item.get("brand", "")
        subcat = item.get("category", "").replace(cat_prefix + "_", "")
        trs.append(f"""
        <tr>
          <td>{item['rank']}</td>
          <td>{badge}</td>
          <td><a href="{url}" target="_blank">{name}</a></td>
          <td>{brand}</td>
          <td>{price}원 {disc_str}</td>
          <td style="color:#888;font-size:11px">{subcat}</td>
        </tr>""")
    return f"""
    <table>
      <thead><tr><th>#</th><th>변동</th><th>상품명</th><th>브랜드</th><th>가격</th><th>세분류</th></tr></thead>
      <tbody>{"".join(trs)}</tbody>
    </table>"""


def _new_entry_cards(new_entries: List[Dict], baseline_available: bool = True) -> str:
    if not baseline_available:
        return (
            '<p class="empty">직전 수집일 비교 데이터가 없어 신규 진입 판정 대기 중입니다. '
            '다음 수집일부터 정확히 표시됩니다.</p>'
        )
    if not new_entries:
        return '<p class="empty">신규 진입 없음</p>'
    parts = []
    for item in new_entries[:6]:
        price = f"{item.get('price', 0):,}"
        fit   = item.get("fit_type") or "-"
        rating = item.get("rating") or "-"
        reviews = item.get("review_count") or 0
        parts.append(f"""
        <div class="entry-card">
          <div class="entry-cat">{item.get('category','')}</div>
          <h4><a href="{item.get('url','#')}" target="_blank">{item.get('product_name','')}</a></h4>
          <p class="brand">{item.get('brand','')}</p>
          <p>{price}원 | 핏: {fit}</p>
          <p>★ {rating} ({reviews:,}리뷰)</p>
        </div>""")
    return "\n".join(parts)


def _trend_chart_data(trend_data: List[Dict]) -> str:
    """Chart.js용 트렌드 데이터 JSON 생성."""
    kw_data: Dict[str, Dict] = {}
    for t in trend_data:
        kw  = t.get("keyword", "")
        pf  = t.get("platform", "")
        score = t.get("score", 0)
        if kw and pf != "구글_트렌딩":
            if kw not in kw_data or score > kw_data[kw]["score"]:
                kw_data[kw] = {"score": score, "change_pct": t.get("change_pct", 0)}

    sorted_kw = sorted(kw_data.items(), key=lambda x: x[1]["score"], reverse=True)[:10]
    labels = [k for k, _ in sorted_kw]
    scores = [v["score"] for _, v in sorted_kw]
    changes = [v["change_pct"] for _, v in sorted_kw]
    return json.dumps({"labels": labels, "scores": scores, "changes": changes}, ensure_ascii=False)


def _price_chart_data(price_result: Dict) -> str:
    cats = list(price_result.get("by_category", {}).keys())
    avgs = [price_result["by_category"][c]["avg"] for c in cats]
    return json.dumps({"labels": cats, "avgs": avgs}, ensure_ascii=False)


def _brand_section(brand_data: List[Dict]) -> str:
    """관심 브랜드 현황 — 랭킹 진입 브랜드는 상품 목록까지 표시."""
    in_ranking  = [b for b in brand_data if b.get("product_count", 0) > 0]
    out_ranking = [b for b in brand_data if b.get("product_count", 0) == 0]

    parts = []

    if in_ranking:
        parts.append('<h3 style="font-size:13px;color:#27ae60;margin-bottom:8px">✅ 랭킹 진입</h3>')
        for b in in_ranking:
            cnt    = b["product_count"]
            change = b.get("count_change")
            change_str = (f'<span style="color:#27ae60">+{change}</span>' if change and change > 0
                          else (f'<span style="color:#e74c3c">{change}</span>' if change and change < 0 else ""))
            products   = b.get("products", [])

            parts.append(f'<div style="border:1px solid #e0e0e0;border-radius:8px;padding:12px;margin-bottom:10px">')
            parts.append(f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">')
            parts.append(f'<strong style="font-size:14px">{b["brand"]}</strong>')
            parts.append(f'<span style="color:#888;font-size:12px">랭킹 내 {cnt}개 {change_str}</span>')
            parts.append('</div>')

            history = b.get("history_7d", [])
            if history:
                trend = "".join(
                    f'<span title="{h.get("date","")}" style="display:inline-flex;align-items:center;justify-content:center;min-width:28px;height:22px;border-radius:6px;background:#f1f3f5;font-size:10px">'
                    f'{h.get("count",0)}</span>'
                    for h in history
                )
                parts.append(
                    f'<div style="display:flex;gap:4px;align-items:center;margin-bottom:8px">'
                    f'<span style="font-size:10px;color:#888;margin-right:3px">최근 흐름</span>{trend}</div>'
                )

            # 상품 목록 (최대 5개)
            if products:
                parts.append('<table style="width:100%;font-size:12px">')
                parts.append('<tr style="color:#888"><td>순위</td><td>상품명</td><td>카테고리</td><td>기간</td><td>가격</td></tr>')
                for p in sorted(products, key=lambda x: x.get("rank",999))[:5]:
                    rank_ch = p.get("rank_change")
                    badge = ""
                    if rank_ch is None:
                        badge = '<span style="background:#ede0ff;color:#7d3c98;padding:1px 5px;border-radius:8px;font-size:10px">NEW</span>'
                    elif rank_ch > 0:
                        badge = f'<span style="color:#27ae60">▲{rank_ch}</span>'
                    elif rank_ch < 0:
                        badge = f'<span style="color:#e74c3c">▼{abs(rank_ch)}</span>'
                    period_badge = p.get("period", "")
                    period_color = {"1일":"#1a73e8","주간":"#27ae60","월간":"#e67e22"}.get(period_badge, "#888")
                    parts.append(
                        f'<tr><td>{p.get("rank","-")}위 {badge}</td>'
                        f'<td><a href="{p.get("url","#")}" target="_blank" style="color:#1a73e8">'
                        f'{p.get("product_name","")}</a></td>'
                        f'<td style="color:#888">{p.get("category","").replace("_전체","")}</td>'
                        f'<td><span style="background:{period_color};color:#fff;padding:1px 6px;border-radius:8px;font-size:10px">{period_badge}</span></td>'
                        f'<td>{p.get("price",0):,}원</td></tr>'
                    )
                parts.append('</table>')
            parts.append('</div>')

    if out_ranking:
        out_names = ", ".join(b["brand"] for b in out_ranking)
        parts.append(f'<p style="color:#aaa;font-size:12px;margin-top:8px">랭킹 외: {out_names}</p>')

    if not in_ranking and not out_ranking:
        return '<p class="empty">브랜드 데이터 없음</p>'

    return "\n".join(parts)


def _brand_rows(brand_data: List[Dict]) -> str:
    """레거시 — _brand_section으로 대체됨."""
    return _brand_section(brand_data)


def _cm29_index(cm29_data: List[Dict]) -> str:
    """29CM 데이터를 '기간|카테고리' 키로 JSON 인덱싱."""
    index: dict = {}
    for item in cm29_data:
        period = item.get("period", "1일")
        cat    = item.get("category", "")
        key    = f"{period}|{cat}"
        index.setdefault(key, []).append({
            "rank":          item.get("rank"),
            "rank_change":   item.get("rank_change"),
            "comparison_available": item.get("comparison_available", False),
            "product_name":  item.get("product_name", ""),
            "brand":         item.get("brand", ""),
            "price":         item.get("price", 0),
            "discount_rate": item.get("discount_rate", 0),
            "review_count":  item.get("review_count", 0),
            "review_score":  item.get("review_score", 0),
            "is_sold_out":   item.get("is_sold_out", False),
            "url":           item.get("url", ""),
        })
    for key in index:
        index[key].sort(key=lambda x: x.get("rank") or 999)
    return json.dumps(index, ensure_ascii=False)


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def _weather_block(weather_data: Dict) -> str:
    if not weather_data:
        return ""
    sig = weather_data.get("category_signal", {})
    sig_html = " | ".join(f"<b>{cat}</b>: {v}" for cat, v in sig.items())
    fc = weather_data.get("forecast_3d", [])
    fc_html = " → ".join(
        f"{f['date'][-5:]} {f['temp_max']:.0f}°/{f['temp_min']:.0f}° {f['weather']}"
        for f in fc
    )
    return f"""
  <div class="section">
    <h2>🌤 오늘의 날씨 & 패션 수요 예측</h2>
    <p style="font-size:18px;margin-bottom:8px">
      <b>{weather_data.get('current_temp')}°C</b>
      <span style="color:#888;font-size:14px"> (체감 {weather_data.get('apparent_temp')}°C) / {weather_data.get('weather_label')} / 최고 {weather_data.get('temp_max')}°C</span>
    </p>
    <p style="margin-bottom:6px">📊 카테고리별 수요 신호: {sig_html}</p>
    <p style="color:#888;font-size:13px">3일 예보: {fc_html}</p>
  </div>"""


def _keyword_table(keyword_data: List[Dict]) -> str:
    if not keyword_data:
        return '<p class="empty">데이터 없음</p>'
    rows = sorted([k for k in keyword_data if k.get("platform") == "무신사_검색어"],
                  key=lambda x: x.get("rank", 999))
    if not rows:
        return '<p class="empty">검색어 데이터 없음</p>'

    def _row_html(r):
        fluct = r.get("fluctuation_label","→")
        amt   = r.get("fluctuation_amount", 0)
        color = "#27ae60" if "▲" in fluct else ("#e74c3c" if "▼" in fluct else "#888")
        badge = f'<span style="color:{color};font-weight:bold">{fluct}{amt if amt else ""}</span>'
        if "NEW" in fluct:
            badge = '<span style="background:#ede0ff;color:#7d3c98;padding:2px 6px;border-radius:10px;font-size:11px">NEW</span>'
        return f"<tr><td>{r['rank']}</td><td>{badge}</td><td>{r['keyword']}</td></tr>"

    initial = rows[:5]
    extra   = rows[5:]
    initial_html = "".join(_row_html(r) for r in initial)
    extra_html   = "".join(_row_html(r) for r in extra)

    expand_btn = ""
    if extra:
        expand_btn = f"""
        <tr id="kw-expand-row">
          <td colspan="3" style="text-align:center;padding:6px">
            <button onclick="toggleKeywords()" id="kw-btn"
              style="border:1px solid #ddd;background:#f8f9fa;padding:5px 18px;border-radius:20px;cursor:pointer;font-size:12px;color:#555">
              ▼ {len(rows)}위까지 펼치기
            </button>
          </td>
        </tr>"""
        extra_rows = f'<tbody id="kw-extra" style="display:none">{"".join(_row_html(r) for r in extra)}</tbody>'
    else:
        extra_rows = ""

    return f"""<table>
      <thead><tr><th>#</th><th>변동</th><th>검색어</th></tr></thead>
      <tbody>{initial_html}</tbody>
      {extra_rows}
      <tbody>{expand_btn}</tbody>
    </table>
    <script>
    function toggleKeywords() {{
      const el = document.getElementById('kw-extra');
      const btn = document.getElementById('kw-btn');
      if (el.style.display === 'none') {{
        el.style.display = '';
        btn.textContent = '▲ 접기';
      }} else {{
        el.style.display = 'none';
        btn.textContent = '▼ {len(rows)}위까지 펼치기';
      }}
    }}
    </script>"""


def _forecast_table(forecasts: List[Dict]) -> str:
    if not forecasts:
        return '<p class="empty">예측 데이터 없음 (데이터 축적 후 정확도 향상)</p>'
    rows = forecasts[:10]
    trs = []
    for f in rows:
        dir_color = {"↑상승": "#27ae60", "↓하락": "#e74c3c", "→유지": "#888"}.get(
            f.get("trend_direction","→유지"), "#888")
        conf_bg = {"높음": "#d4f5e2", "보통": "#fff3cd", "낮음": "#f0f0f0"}.get(
            f.get("confidence","낮음"), "#f0f0f0")
        trs.append(
            f'<tr><td>{f["keyword"]}</td>'
            f'<td style="color:{dir_color};font-weight:bold">{f["trend_direction"]}</td>'
            f'<td>{f["forecast_score"]}</td>'
            f'<td style="background:{conf_bg};border-radius:10px;padding:2px 8px;font-size:11px">'
            f'{f["confidence"]}</td></tr>'
        )
    return f"""<table>
      <thead><tr><th>키워드</th><th>트렌드</th><th>예측점수</th><th>신뢰도</th></tr></thead>
      <tbody>{"".join(trs)}</tbody></table>"""


def _steady_seller_rows(steady: List[Dict]) -> str:
    if not steady:
        return '<p class="empty">데이터 축적 중 (2주 이상 수집 후 표시)</p>'
    rows = steady[:10]
    trs = []
    for s in rows:
        badge = "🏆" if s.get("is_steady") else "📈"
        trs.append(
            f'<tr><td>{badge}</td>'
            f'<td><a href="{s.get("url","#")}" target="_blank">{s.get("product_name","")}</a></td>'
            f'<td>{s.get("brand","")}</td>'
            f'<td>{s.get("appearances",0)}회</td>'
            f'<td>{s.get("best_rank","-")}위</td></tr>'
        )
    return f"""<table>
      <thead><tr><th></th><th>상품명</th><th>브랜드</th><th>등장</th><th>최고순위</th></tr></thead>
      <tbody>{"".join(trs)}</tbody></table>"""


def _events_block(musinsa_evs: List[Dict], cm29_evs: List[Dict]) -> str:
    """기획전/에디션 섹션 HTML."""
    parts = ['<div>']

    # 무신사 기획전
    parts.append('<div><h3 style="font-size:13px;color:#555;margin-bottom:8px">🛒 무신사 기획전</h3>')
    if musinsa_evs:
        for e in musinsa_evs[:6]:
            badge = e.get("period") or f'{e["item_count"]}개 상품'
            parts.append(
                f'<div class="event-item">'
                f'<span class="event-title">{e["title"]}</span>'
                f'<span class="event-badge">{badge}</span>'
                f'</div>'
            )
    else:
        parts.append('<p class="empty">수집 중</p>')
    parts.append('</div>')

    parts.append('<div style="margin-top:14px"><h3 style="font-size:13px;color:#555;margin-bottom:8px">🛍 29CM 에디션</h3>')
    if cm29_evs:
        for e in cm29_evs[:6]:
            badge = e.get("period") or f'{e.get("item_count",0)}개 상품'
            parts.append(
                f'<div class="event-item">'
                f'<span class="event-title">{e.get("title","")}</span>'
                f'<span class="event-badge">{badge}</span>'
                f'</div>'
            )
    else:
        parts.append('<p class="empty">수집 중</p>')
    parts.append('</div>')

    parts.append('</div>')
    return "\n".join(parts)


def _brand_ranking_block(brand_ranks: List[Dict]) -> str:
    """무신사 브랜드 랭킹 테이블."""
    if not brand_ranks:
        return '<p class="empty">수집 중</p>'
    trs = []
    for b in brand_ranks[:15]:
        fluct = b.get("fluctuation_type","NONE")
        amt   = b.get("fluctuation_amt", 0)
        badge = ""
        if fluct == "UP":
            badge = f'<span style="color:#27ae60">▲{amt}</span>'
        elif fluct == "DOWN":
            badge = f'<span style="color:#e74c3c">▼{amt}</span>'
        elif fluct == "NEW":
            badge = '<span style="background:#ede0ff;color:#7d3c98;padding:1px 5px;border-radius:8px;font-size:10px">NEW</span>'
        label = f'<span style="color:#888;font-size:11px">{b.get("label","")}</span>' if b.get("label") else ""
        url = b.get("url","#")
        trs.append(
            f'<tr><td>{b["rank"]}</td><td>{badge}</td>'
            f'<td><a href="{url}" target="_blank">{b["brand"]}</a> {label}</td></tr>'
        )
    return f'<table><thead><tr><th>#</th><th>변동</th><th>브랜드</th></tr></thead><tbody>{"".join(trs)}</tbody></table>'


def _material_color_block(mat_color: Dict) -> str:
    """소재·색상 트렌드 블록."""
    if not mat_color:
        return '<p class="empty">신규 진입 상품 분석 중</p>'
    mats   = mat_color.get("top_materials", [])
    colors = mat_color.get("top_colors", [])
    fits   = mat_color.get("fit_types", [])
    parts  = []
    if mats:
        tags = "".join(f'<span class="issue-tag" style="margin:2px">{m}({n})</span>' for m,n in mats)
        parts.append(f'<p style="margin-bottom:6px"><b>소재:</b> {tags}</p>')
    if fits:
        tags = "".join(f'<span class="issue-tag" style="margin:2px;background:#e8f5e9;color:#2e7d32;border-color:#4caf50">{f}({n})</span>' for f,n in fits)
        parts.append(f'<p style="margin-bottom:6px"><b>핏:</b> {tags}</p>')
    if colors:
        tags = "".join(f'<span class="issue-tag" style="margin:2px;background:#e3f2fd;color:#1565c0;border-color:#42a5f5">{c}({n})</span>' for c,n in colors[:5])
        parts.append(f'<p><b>색상:</b> {tags}</p>')
    return "\n".join(parts) if parts else '<p class="empty">데이터 없음</p>'


def _cat_growth_block(cat_growth: List[Dict]) -> str:
    """카테고리 성장률 테이블."""
    if not cat_growth:
        return '<p class="empty">데이터 2주 이상 쌓이면 표시됩니다</p>'
    trs = []
    for c in cat_growth[:6]:
        trend = c.get("trend","")
        change = c.get("rank_change", 0)
        color = "#27ae60" if change > 0 else ("#e74c3c" if change < 0 else "#888")
        trs.append(
            f'<tr><td>{c["category"]}</td>'
            f'<td style="color:{color};font-weight:bold">{trend}</td>'
            f'<td style="color:{color}">{change:+.1f}</td>'
            f'<td style="color:#888;font-size:11px">{c.get("growth_pct",0):+.1f}%</td></tr>'
        )
    return f'<table><thead><tr><th>카테고리</th><th>트렌드</th><th>순위변화</th><th>성장률</th></tr></thead><tbody>{"".join(trs)}</tbody></table>'


def generate(
    rank_diff_result: Dict,
    trend_data: List[Dict],
    price_result: Dict,
    brand_data: List[Dict],
    signals: List[Dict],
    weather_data: Optional[Dict] = None,
    keyword_data: Optional[List[Dict]] = None,
    forecasts: Optional[List[Dict]] = None,
    steady: Optional[List[Dict]] = None,
    cm29_data: Optional[List[Dict]] = None,
    overall_data: Optional[List[Dict]] = None,
    brand_ranks: Optional[List[Dict]] = None,
    musinsa_evs: Optional[List[Dict]] = None,
    cm29_evs: Optional[List[Dict]] = None,
    mat_color: Optional[Dict] = None,
    cat_growth: Optional[List[Dict]] = None,
    md_actions: Optional[List[Dict]] = None,
    cross_platform: Optional[List[Dict]] = None,
    reviewed_entries: Optional[List[Dict]] = None,
    data_status: Optional[Dict] = None,
    backtests: Optional[List[Dict]] = None,
    history_dates: Optional[List[str]] = None,
) -> str:
    """
    대시보드 HTML 생성 후 파일 저장.

    Returns:
        저장된 파일 경로.
    """
    from datetime import timedelta
    kst_now   = datetime.now(timezone.utc) + timedelta(hours=9)
    now_str   = kst_now.strftime("%Y-%m-%d %H:%M KST")
    today_str = kst_now.strftime("%Y년 %m월 %d일")
    items     = rank_diff_result.get("items", [])
    trend_json = _trend_chart_data(trend_data)
    price_json = _price_chart_data(price_result)
    cm29_json  = _cm29_index(cm29_data or [])

    # 전체 랭킹(gf=A) 인덱싱 — 남성 랭킹과 동일한 구조, 별도 키셋
    _overall_items = overall_data or []
    overall_index: dict = {}
    for item in _overall_items:
        cat    = item.get("category", "")
        period = item.get("period", "1일")
        for main in ["상의", "아우터", "바지"]:
            if not cat.startswith(main + "_"):
                continue
            sub = cat[len(main) + 1:]
            key = f"{period}|{main}" if sub == "전체" else f"{period}|{main}_{sub}"
            overall_index.setdefault(key, []).append({
                "rank":          item.get("rank"),
                "rank_change":   item.get("rank_change"),
                "comparison_available": item.get("comparison_available", False),
                "product_name":  item.get("product_name", ""),
                "brand":         item.get("brand", ""),
                "price":         item.get("price", 0),
                "discount_rate": item.get("discount_rate", 0),
                "url":           item.get("url", ""),
                "category":      cat,
                "period":        period,
            })
            break
    for key in overall_index:
        overall_index[key].sort(key=lambda x: x.get("rank") or 999)
        overall_index[key] = overall_index[key][:30]
    overall_json = json.dumps(overall_index, ensure_ascii=False)

    # 기간 × 카테고리(대분류 + 세분류) 인덱싱 — 남성
    # key 예시: "1일|상의", "주간|상의_반소매티셔츠", "월간|아우터_후드집업"
    _MAIN_CATS = ["상의", "아우터", "바지"]
    ranking_index: dict = {}

    def _to_row(i):
        return {
            "rank":          i.get("rank"),
            "rank_change":   i.get("rank_change"),
            "comparison_available": i.get("comparison_available", False),
            "product_name":  i.get("product_name", ""),
            "brand":         i.get("brand", ""),
            "price":         i.get("price", 0),
            "discount_rate": i.get("discount_rate", 0),
            "review_count":  i.get("review_count", 0),
            "review_score":  i.get("review_score", 0),
            "url":           i.get("url", ""),
            "category":      i.get("category", ""),
            "period":        i.get("period", ""),
        }

    for item in items:
        cat    = item.get("category", "")
        period = item.get("period", "1일")
        for main in _MAIN_CATS:
            if not cat.startswith(main + "_"):
                continue
            sub = cat[len(main) + 1:]   # e.g. "전체", "반소매티셔츠"

            # 세분류별 key: 전체 → "1일|상의", 나머지 → "1일|상의_반소매티셔츠"
            if sub == "전체":
                key = f"{period}|{main}"
            else:
                key = f"{period}|{main}_{sub}"

            ranking_index.setdefault(key, [])
            ranking_index[key].append(_to_row(item))
            break

    # rank 오름차순 정렬, TOP 30 제한
    for key in ranking_index:
        ranking_index[key].sort(key=lambda x: x.get("rank") or 999)
        ranking_index[key] = ranking_index[key][:30]

    ranking_json = json.dumps(ranking_index, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>패션 MD 마켓 인텔리전스 — {today_str}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:#f0f2f5; --card:#fff; --accent:#3b5bdb; --danger:#e03131;
    --success:#2f9e44; --warning:#e67700; --new:#7048e8;
    --border:#e9ecef; --text:#212529; --muted:#6c757d;
  }}
  *{{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif; background:var(--bg); color:var(--text); font-size:14px; line-height:1.6; }}
  /* ── 헤더 ── */
  header {{ background:linear-gradient(135deg,#0f0c29,#302b63,#24243e); color:#fff; padding:18px 28px; box-shadow:0 2px 10px rgba(0,0,0,.3); }}
  .header-inner {{ max-width:1280px; margin:0 auto; display:flex; justify-content:space-between; align-items:center; }}
  header h1 {{ font-size:19px; font-weight:700; letter-spacing:-.5px; }}
  header .meta {{ font-size:12px; color:#94a3b8; }}
  /* ── 빠른 이동 ── */
  .nav-bar {{ background:#fff; border:1px solid var(--border); border-radius:12px; margin-bottom:16px; }}
  .nav-inner {{ display:flex; overflow-x:auto; scrollbar-width:none; padding:0 4px; }}
  .nav-inner::-webkit-scrollbar {{ display:none; }}
  .nav-item {{ padding:10px 14px; font-size:12px; font-weight:600; color:var(--muted); text-decoration:none; white-space:nowrap; border-bottom:2px solid transparent; transition:all .2s; }}
  .nav-item:hover {{ color:var(--accent); border-bottom-color:var(--accent); }}
  /* ── 레이아웃 ── */
  .container {{ max-width:1280px; margin:0 auto; padding:24px 20px; }}
  .section {{ background:var(--card); border-radius:16px; padding:22px 24px; margin-bottom:20px; box-shadow:0 1px 3px rgba(0,0,0,.05); border:1px solid var(--border); }}
  h2 {{ font-size:15px; font-weight:700; margin-bottom:16px; display:flex; align-items:center; gap:8px; }}
  h2 .line {{ flex:1; height:1px; background:var(--border); margin-left:4px; }}
  h3.sub {{ font-size:13px; font-weight:600; color:var(--muted); margin-bottom:10px; }}
  .col-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; }}
  @media(max-width:800px){{ .col-2{{ grid-template-columns:1fr; }} }}
  /* ── 탭 ── */
  .tabs {{ display:flex; gap:6px; margin-bottom:12px; flex-wrap:wrap; }}
  .tab {{ padding:5px 14px; border-radius:20px; border:1.5px solid var(--border); cursor:pointer; font-size:12px; font-weight:600; transition:all .15s; color:var(--muted); background:#fff; user-select:none; }}
  .tab:hover {{ border-color:var(--accent); color:var(--accent); }}
  .tab.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  .tab-content {{ display:none; }}
  .tab-content.active {{ display:block; }}
  /* ── 테이블 ── */
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  thead th {{ background:#f8f9fa; padding:8px 10px; text-align:left; font-weight:700; font-size:11px; color:var(--muted); border-bottom:1.5px solid var(--border); text-transform:uppercase; letter-spacing:.5px; }}
  td {{ padding:8px 10px; border-bottom:1px solid #f3f4f6; vertical-align:middle; }}
  td a, .entry-card h4 a {{ overflow-wrap:anywhere; word-break:keep-all; }}
  tbody tr:hover {{ background:#f5f7ff; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  /* ── 배지 ── */
  .badge {{ font-size:11px; padding:2px 7px; border-radius:10px; font-weight:700; white-space:nowrap; }}
  .badge.up   {{ background:#d3f9d8; color:#1a5e2a; }}
  .badge.down {{ background:#ffe3e3; color:#7d1a1a; }}
  .badge.new  {{ background:#e5dbff; color:#5f3dc4; }}
  .badge.same {{ background:#f1f3f5; color:#868e96; }}
  .disc {{ color:var(--danger); font-size:12px; font-weight:700; }}
  /* ── 기획전 시그널 카드 ── */
  .signal-section {{ background:linear-gradient(135deg,#fff9f5,#fff); }}
  .signal-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:14px; }}
  .signal-card {{ border-radius:12px; padding:16px; border-left:4px solid; position:relative; }}
  .signal-card.lvl-red    {{ background:#fff5f5; border-left-color:var(--danger); }}
  .signal-card.lvl-yellow {{ background:#fffaf0; border-left-color:var(--warning); }}
  .signal-card.lvl-green  {{ background:#f0fdf4; border-left-color:var(--success); }}
  .signal-score {{ position:absolute; top:14px; right:14px; width:34px; height:34px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:800; color:#fff; }}
  .signal-card.lvl-red    .signal-score {{ background:var(--danger); }}
  .signal-card.lvl-yellow .signal-score {{ background:var(--warning); }}
  .signal-card.lvl-green  .signal-score {{ background:var(--success); }}
  .signal-card h3 {{ font-size:14px; font-weight:700; margin-bottom:4px; padding-right:44px; }}
  .signal-card.lvl-red    h3 {{ color:var(--danger); }}
  .signal-card.lvl-yellow h3 {{ color:var(--warning); }}
  .signal-card.lvl-green  h3 {{ color:var(--success); }}
  .signal-card .signal-meta {{ font-size:12px; color:var(--muted); }}
  .signal-card .signal-theme {{ font-size:13px; font-weight:600; color:var(--text); margin:6px 0 4px; }}
  .signal-card .open-date {{ margin-top:10px; background:rgba(255,255,255,.75); border-radius:8px; padding:6px 10px; font-size:12px; }}
  /* ── 신규 진입 카드 ── */
  .entry-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:12px; }}
  .entry-card {{ border:1.5px solid var(--border); border-radius:12px; padding:14px; transition:box-shadow .15s; }}
  .entry-card:hover {{ box-shadow:0 4px 16px rgba(0,0,0,.1); }}
  .entry-cat {{ font-size:10px; color:var(--accent); font-weight:800; margin-bottom:5px; letter-spacing:.8px; text-transform:uppercase; }}
  .entry-card h4 {{ font-size:13px; margin-bottom:4px; line-height:1.4; }}
  .entry-card .brand {{ color:var(--muted); font-size:12px; margin-bottom:5px; }}
  /* ── 오늘의 액션 ── */
  .action-section {{ background:linear-gradient(135deg,#f5f7ff,#fff); }}
  .action-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; }}
  .action-card {{ position:relative; border:1px solid #dfe4ff; border-radius:14px; padding:16px; background:#fff; }}
  .action-rank {{ position:absolute;right:14px;top:14px;width:28px;height:28px;border-radius:50%;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:800; }}
  .action-source {{ color:var(--accent);font-size:11px;font-weight:800;margin-bottom:5px; }}
  .action-card h3 {{ font-size:15px;padding-right:34px;margin-bottom:10px; }}
  .action-card p {{ font-size:12px;margin-top:10px; }}
  .action-evidence-row {{ display:flex;flex-wrap:wrap;gap:5px; }}
  .action-evidence {{ background:#eef1ff;color:#364fc7;border-radius:12px;padding:2px 7px;font-size:11px; }}
  .action-footer {{ display:flex;justify-content:space-between;margin-top:12px;padding-top:9px;border-top:1px solid var(--border);font-size:11px;color:var(--muted); }}
  .action-footer strong {{ color:var(--accent); }}
  .data-status {{ display:flex;gap:12px;flex-wrap:wrap;align-items:center;padding:8px 12px;margin-bottom:14px;border-radius:10px;font-size:11px; }}
  .status-ok {{ background:#ebfbee;color:#2b8a3e; }}
  .status-warning {{ background:#fff4e6;color:#d9480f; }}
  .review-grid {{ display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px; }}
  .review-card {{ border:1px solid var(--border);border-radius:10px;padding:12px; }}
  .review-card h3 {{ font-size:12px;margin-bottom:5px; }}
  .review-card p {{ font-size:11px; }}
  .muted {{ color:var(--muted); }}
  .method-grid {{ display:grid;grid-template-columns:1fr 1fr;gap:12px; }}
  .method-grid>div {{ background:#f8f9fa;border-radius:10px;padding:13px; }}
  .method-grid p {{ color:var(--muted);font-size:12px;margin-top:5px; }}
  .case-grid {{ display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px; }}
  .case-card {{ border:1px solid var(--border);border-radius:10px;padding:12px; }}
  .case-card span {{ color:var(--accent);font-size:11px;font-weight:800; }}
  .case-card h3 {{ font-size:13px;margin:4px 0; }}
  .case-card p {{ font-size:11px; }}
  details.section {{ padding:0; overflow:hidden; }}
  details.section>summary {{ list-style:none;cursor:pointer;padding:18px 24px;font-size:15px;font-weight:700;display:flex;align-items:center;gap:8px; }}
  details.section>summary::-webkit-details-marker {{ display:none; }}
  details.section>summary::after {{ content:'▾';margin-left:auto;color:var(--muted);font-size:14px;display:inline-block;transition:transform .2s; }}
  details.section:not([open])>summary::after {{ transform:rotate(-90deg); }}
  details.section>.detail-body {{ padding:0 24px 22px; }}
  @media(max-width:900px){{ .action-grid{{grid-template-columns:1fr;}} }}
  @media(max-width:700px){{ .method-grid,.case-grid{{grid-template-columns:1fr;}} }}
  /* ── 기획전 이벤트 ── */
  .event-item {{ display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid #f3f4f6; }}
  .event-item:last-child {{ border-bottom:none; }}
  .event-title {{ font-size:13px; font-weight:600; }}
  .event-badge {{ font-size:11px; padding:3px 10px; border-radius:20px; background:#fff3cd; color:#92400e; border:1px solid #fbbf24; white-space:nowrap; flex-shrink:0; margin-left:8px; }}
  /* ── 공통 ── */
  .chart-row {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  @media(max-width:700px){{ .chart-row{{ grid-template-columns:1fr; }} }}
  .empty {{ color:var(--muted); font-style:italic; font-size:13px; padding:6px 0; }}
  .issue-tag {{ background:#fff3cd; color:#856404; border:1px solid #ffc107; border-radius:12px; padding:2px 8px; font-size:11px; }}
  .expand-btn {{ display:block; width:100%; margin-top:10px; padding:8px; border:1.5px solid var(--border); border-radius:20px; background:#f8f9fa; cursor:pointer; font-size:12px; color:var(--muted); transition:all .15s; }}
  .expand-btn:hover {{ border-color:var(--accent); color:var(--accent); background:#fff; }}
</style>
</head>
<body>
<header>
  <div class="header-inner">
    <h1>패션 MD 마켓 인텔리전스</h1>
    <span class="meta">공개 데이터 기반 · 마지막 업데이트: {now_str}</span>
  </div>
</header>
<div class="container">

  <!-- 빠른 이동 -->
  <nav class="nav-bar">
    <div class="nav-inner">
      <a class="nav-item" href="#md-actions">✅ 오늘의 액션</a>
      <a class="nav-item" href="#watch-brands">🏷 관심 브랜드</a>
      <a class="nav-item" href="#cross-platform">↔ 교차 상승</a>
      <a class="nav-item" href="#musinsa-ranking">🏆 무신사 랭킹</a>
      <a class="nav-item" href="#cm29-ranking">🛍 29CM 랭킹</a>
      <a class="nav-item" href="#new-entries">⬆ 신규 진입</a>
      <a class="nav-item" href="#signals">🎯 기획전 시그널</a>
      <a class="nav-item" href="#keywords">🔍 검색어</a>
      <a class="nav-item" href="#events">🎪 기획전 현황</a>
      <a class="nav-item" href="#brand-ranking">📊 브랜드 랭킹</a>
      <a class="nav-item" href="#trends">📈 트렌드</a>
      <a class="nav-item" href="#backtest">🧪 백테스트</a>
      <a class="nav-item" href="#methodology">📖 방법론</a>
      <a class="nav-item" href="#steady">🏅 스테디셀러</a>
    </div>
  </nav>

  {_data_status_block(data_status or {})}

  <details id="md-actions" class="section action-section" open>
    <summary>✅ 오늘의 MD 액션</summary>
    <div class="detail-body">
    <div class="action-grid">{_md_action_cards(md_actions or [])}</div>
    </div>
  </details>

  {_weather_block(weather_data)}

  <!-- 1. 무신사 랭킹 TOP 30 -->
  <details id="musinsa-ranking" class="section" open>
    <summary>🏆 무신사 랭킹 TOP 30</summary>
    <div class="detail-body">
    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
      <div class="tabs" id="gender-tabs">
        <div class="tab active" onclick="switchGender('남성',this)">👔 남성</div>
        <div class="tab" onclick="switchGender('전체',this)">🌐 전체</div>
      </div>
      <div class="tabs" id="period-tabs">
        <div class="tab active" onclick="switchPeriod('1일',this)">1일</div>
        <div class="tab" onclick="switchPeriod('주간',this)">주간</div>
        <div class="tab" onclick="switchPeriod('월간',this)">월간</div>
      </div>
    </div>
    <div class="tabs" id="main-cat-tabs" style="margin-bottom:6px">
      <div class="tab active" onclick="switchMainCat('상의',this)">상의</div>
      <div class="tab" onclick="switchMainCat('아우터',this)">아우터</div>
      <div class="tab" onclick="switchMainCat('바지',this)">바지</div>
    </div>
    <div id="sub-cat-tabs" class="tabs" style="margin-bottom:12px;flex-wrap:wrap"></div>
    <div id="ranking-table-area">
      {_ranking_table(
          items,
          '상의',
          '1일',
          rank_diff_result.get('baseline_available', True),
      )}
    </div>
    </div>
  </details>

  <!-- 2. 29CM 남성 베스트 -->
  <details id="cm29-ranking" class="section" open>
    <summary>🛍 29CM 남성 베스트 TOP 30</summary>
    <div class="detail-body">
    <div class="tabs" id="cm29-cat-tabs" style="margin-bottom:12px;flex-wrap:wrap">
      <div class="tab active" onclick="switchCm29Cat('남성_전체',this)">전체</div>
      <div class="tab" onclick="switchCm29Cat('남성_상의',this)">상의</div>
      <div class="tab" onclick="switchCm29Cat('남성_아우터',this)">아우터</div>
      <div class="tab" onclick="switchCm29Cat('남성_셋업',this)">셋업</div>
      <div class="tab" onclick="switchCm29Cat('남성_하의',this)">하의</div>
      <div class="tab" onclick="switchCm29Cat('남성_니트웨어',this)">니트웨어</div>
    </div>
    <div id="cm29-table-area"></div>
    </div>
  </details>

  <!-- 3. 신규 진입 상품 -->
  <details id="new-entries" class="section" open>
    <summary>⬆ 오늘의 신규 진입 상품</summary>
    <div class="detail-body">
    <div class="entry-grid">
      {_new_entry_cards(
          rank_diff_result.get('new_entries', []),
          rank_diff_result.get('baseline_available', True),
      )}
    </div>
    </div>
  </details>

  <details id="review-insights" class="section" open>
    <summary>💬 신규 진입 리뷰 인사이트</summary>
    <div class="detail-body">
    <div class="review-grid">{_review_insight_block(reviewed_entries or [])}</div>
    </div>
  </details>

  <!-- 4. 기획전 시그널 -->
  <details id="signals" class="section signal-section" open>
    <summary>🎯 기획전 타이밍 시그널</summary>
    <div class="detail-body">
    <div class="signal-grid">
      {_signal_cards(signals)}
    </div>
    </div>
  </details>

  <details id="watch-brands" class="section" open>
    <summary>🏷 관심 브랜드 현황</summary>
    <div class="detail-body">
    {_brand_section(brand_data)}
    </div>
  </details>

  <details id="cross-platform" class="section" open>
    <summary>↔ 무신사 · 29CM 교차 상승</summary>
    <div class="detail-body">
    {_cross_platform_block(cross_platform or [])}
    </div>
  </details>

  <!-- 5. 실시간 검색어 + 트렌드 예측 -->
  <details id="keywords" class="section" open>
    <summary>🔍 무신사 실시간 검색어 & 트렌드 예측</summary>
    <div class="detail-body">
    <div class="col-2">
      <div>
        <h3 class="sub">실시간 검색어 TOP 20</h3>
        {_keyword_table(keyword_data or [])}
      </div>
      <div>
        <h3 class="sub">트렌드 예측 (데이터 축적 중)</h3>
        {_forecast_table(forecasts or [])}
      </div>
    </div>
    </div>
  </details>

  <!-- 6. 기획전 현황 -->
  <details id="events" class="section" open>
    <summary>🎪 기획전 & 에디션 현황</summary>
    <div class="detail-body">
    {_events_block(musinsa_evs or [], cm29_evs or [])}
    </div>
  </details>

  <!-- 7. 브랜드 랭킹 & 카테고리 성장률 -->
  <details id="brand-ranking" class="section" open>
    <summary>📊 브랜드 랭킹 & 카테고리 성장률</summary>
    <div class="detail-body">
    <div class="col-2">
      <div>
        <h3 class="sub">🏆 무신사 브랜드 TOP 15</h3>
        {_brand_ranking_block(brand_ranks or [])}
      </div>
      <div>
        <h3 class="sub">📈 카테고리 성장률 (주간)</h3>
        {_cat_growth_block(cat_growth or [])}
      </div>
    </div>
    </div>
  </details>

  <!-- 8. 트렌드 & 가격 분포 -->
  <details id="trends" class="section" open>
    <summary>📈 트렌드 & 가격 분포</summary>
    <div class="detail-body">
    <div class="chart-row">
      <div><canvas id="trendChart" height="200"></canvas></div>
      <div><canvas id="priceChart" height="200"></canvas></div>
    </div>
    </div>
  </details>

  <!-- 9. 스테디셀러 -->
  <details id="steady" class="section" open>
    <summary>🏅 스테디셀러 (연속 TOP 10)</summary>
    <div class="detail-body">
    {_steady_seller_rows(steady or [])}
    </div>
  </details>

  <!-- 11. 소재·색상 트렌드 -->
  <details class="section" open>
    <summary>🧵 신규 진입 소재·색상 트렌드</summary>
    <div class="detail-body">
    {_material_color_block(mat_color or {})}
    </div>
  </details>

  <details id="backtest" class="section" open>
    <summary>🧪 과거 추천 백테스트</summary>
    <div class="detail-body">
    <p class="muted" style="margin-bottom:10px">성과가 좋은 추천만 선별하지 않고 검증 가능한 모든 추천을 같은 기준으로 평가합니다.</p>
    {_backtest_block(backtests or [])}
    </div>
  </details>

  <details id="methodology" class="section" open>
    <summary>📖 데이터 출처와 분석 방법론</summary>
    <div class="detail-body">
    {_methodology_block()}
    <p class="muted" style="margin-top:12px">보유 스냅샷: {len(history_dates or [])}일 · {", ".join((history_dates or [])[-7:]) or "수집 시작 전"}</p>
    </div>
  </details>

</div>

<script>
// 랭킹 데이터
const rankingData  = {ranking_json};   // 남성(gf=M)
const overallData  = {overall_json};   // 전체(gf=A)
const rankingBaselineAvailable = {
    json.dumps(rank_diff_result.get("baseline_available", True))
};
let currentGender  = '남성';           // 현재 선택 성별

// 세분류 정의
const subCats = {{
  '상의':  ['전체','반소매티셔츠','긴소매티셔츠','맨투맨스웨트','후드티셔츠','셔츠블라우스','니트스웨터','피케카라티','민소매티셔츠'],
  '아우터': ['전체','후드집업','블루종MA1','슈트블레이저','나일론코치','카디건','사파리헌팅','트러커재킷','환절기코트','플리스뽀글이','레더라이더스'],
  '바지':  ['전체','데님팬츠','트레이닝조거','슈트슬랙스','숏팬츠','코튼팬츠'],
}};

let currentPeriod = '1일';
let currentMainCat = '상의';
let currentSubCat = '전체';
let rankingExpanded = false;

function renderRankingTable() {{
  const area = document.getElementById('ranking-table-area');
  const catKey = currentSubCat === '전체'
    ? currentMainCat
    : currentMainCat + '_' + currentSubCat;
  const key = currentPeriod + '|' + catKey;
  const dataset = currentGender === '전체' ? overallData : rankingData;
  const allRows = dataset[key] || [];

  if (!allRows.length) {{
    area.innerHTML = '<p class="empty">데이터 없음 (수집 후 표시됩니다)</p>';
    return;
  }}

  const visibleRows = rankingExpanded ? allRows : allRows.slice(0, 10);
  let html = '<table><thead><tr><th>#</th><th>변동</th><th>상품명</th><th>브랜드</th><th>가격</th><th>리뷰</th><th>세분류</th></tr></thead><tbody>';
  visibleRows.forEach(r => {{
    const ch = r.rank_change;
    let badge = '';
    if (!r.comparison_available) badge = '<span class="badge same">대기</span>';
    else if (ch === null || ch === undefined) badge = '<span class="badge new">NEW</span>';
    else if (ch > 0) badge = '<span class="badge up">▲' + ch + '</span>';
    else if (ch < 0) badge = '<span class="badge down">▼' + Math.abs(ch) + '</span>';
    else badge = '<span class="badge same">→</span>';
    const disc = r.discount_rate ? '<span class="disc">-' + r.discount_rate + '%</span>' : '';
    const subcat = (r.category || '').replace(currentMainCat + '_', '');
    const review = r.review_count ? Number(r.review_count).toLocaleString() + '개' : '-';
    html += '<tr><td>' + r.rank + '</td><td>' + badge + '</td>';
    html += '<td><a href="' + r.url + '" target="_blank">' + (r.product_name || '') + '</a></td>';
    html += '<td>' + (r.brand || '') + '</td>';
    html += '<td>' + Number(r.price).toLocaleString() + '원 ' + disc + '</td>';
    html += '<td style="color:#888;font-size:11px">' + review + '</td>';
    html += '<td style="color:#888;font-size:11px">' + subcat + '</td></tr>';
  }});
  html += '</tbody></table>';

  if (allRows.length > 10) {{
    const btnText = rankingExpanded ? '▲ 접기' : '▼ ' + allRows.length + '위까지 펼치기';
    html += '<button class="expand-btn" onclick="toggleRanking()">' + btnText + '</button>';
  }}
  area.innerHTML = html;
}}

function toggleRanking() {{
  rankingExpanded = !rankingExpanded;
  renderRankingTable();
}}

function renderSubCatTabs() {{
  const container = document.getElementById('sub-cat-tabs');
  const subs = subCats[currentMainCat] || [];
  container.innerHTML = subs.map(s =>
    `<div class="tab sub-tab${{s === currentSubCat ? ' active' : ''}}" onclick="switchSubCat('${{s}}',this)">${{s}}</div>`
  ).join('');
}}

function switchGender(gender, el) {{
  currentGender = gender;
  document.querySelectorAll('#gender-tabs .tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  rankingExpanded = false;
  renderRankingTable();
}}

function switchPeriod(period, el) {{
  currentPeriod = period;
  document.querySelectorAll('#period-tabs .tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  renderRankingTable();
}}

function switchMainCat(cat, el) {{
  currentMainCat = cat;
  currentSubCat = '전체';
  document.querySelectorAll('#main-cat-tabs .tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  renderSubCatTabs();
  renderRankingTable();
}}

function switchSubCat(sub, el) {{
  currentSubCat = sub;
  document.querySelectorAll('#sub-cat-tabs .tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  renderRankingTable();
}}

// 세분류 탭 스타일
const subStyle = document.createElement('style');
subStyle.textContent = '.sub-tab {{ font-size:12px; padding:4px 10px; background:#f5f5f5; border-color:#ddd; }}';
document.head.appendChild(subStyle);

renderSubCatTabs();
renderRankingTable();

// ── 29CM 랭킹 ──────────────────────────────────────────────────────────────────
const cm29Data = {cm29_json};
let cm29Cat = '남성_전체';
let cm29Expanded = false;

function renderCm29Table() {{
  const area = document.getElementById('cm29-table-area');
  const key = '실시간|' + cm29Cat;
  const allRows = cm29Data[key] || [];
  if (!allRows.length) {{
    area.innerHTML = '<p class="empty">데이터 없음 (수집 후 표시됩니다)</p>';
    return;
  }}
  const visibleRows = cm29Expanded ? allRows : allRows.slice(0, 10);
  let html = '<table><thead><tr><th>#</th><th>변동</th><th>상품명</th><th>브랜드</th><th>가격</th><th>리뷰</th><th>평점</th></tr></thead><tbody>';
  visibleRows.forEach(r => {{
    const ch = r.rank_change;
    let badge = '';
    if (!r.comparison_available) badge = '<span class="badge same">대기</span>';
    else if (ch === null || ch === undefined) badge = '<span class="badge new">NEW</span>';
    else if (ch > 0) badge = '<span class="badge up">▲' + ch + '</span>';
    else if (ch < 0) badge = '<span class="badge down">▼' + Math.abs(ch) + '</span>';
    else badge = '<span class="badge same">→</span>';
    const disc   = r.discount_rate ? '<span class="disc">-' + r.discount_rate + '%</span>' : '';
    const score  = r.review_score ? '★' + r.review_score : '-';
    const review = r.review_count ? Number(r.review_count).toLocaleString() + '개' : '-';
    const sold   = r.is_sold_out ? ' <span style="color:#e74c3c;font-size:10px">품절</span>' : '';
    html += '<tr><td>' + r.rank + '</td><td>' + badge + '</td>';
    html += '<td><a href="' + r.url + '" target="_blank">' + (r.product_name || '') + '</a>' + sold + '</td>';
    html += '<td>' + (r.brand || '') + '</td>';
    html += '<td>' + Number(r.price).toLocaleString() + '원 ' + disc + '</td>';
    html += '<td style="color:#888;font-size:11px">' + review + '</td>';
    html += '<td style="color:#888;font-size:11px">' + score + '</td></tr>';
  }});
  html += '</tbody></table>';
  if (allRows.length > 10) {{
    const btnText = cm29Expanded ? '▲ 접기' : '▼ ' + allRows.length + '위까지 펼치기';
    html += '<button class="expand-btn" onclick="toggleCm29()">' + btnText + '</button>';
  }}
  area.innerHTML = html;
}}

function switchCm29Cat(cat, el) {{
  cm29Cat = cat; cm29Expanded = false;
  document.querySelectorAll('#cm29-cat-tabs .tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  renderCm29Table();
}}

function toggleCm29() {{
  cm29Expanded = !cm29Expanded;
  renderCm29Table();
}}

renderCm29Table();

// 트렌드 차트
const td = {trend_json};
const pd = {price_json};
let chartsRendered = false;
function renderCharts() {{
  if (chartsRendered) return;
  chartsRendered = true;
  if (td.labels.length) {{
  new Chart(document.getElementById('trendChart'), {{
    type: 'bar',
    data: {{
      labels: td.labels,
      datasets: [{{
        label: '관심도 점수',
        data: td.scores,
        backgroundColor: 'rgba(26,115,232,0.7)',
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: '패션 키워드 관심도' }} }},
      scales: {{ y: {{ beginAtZero: true, max: 100 }} }}
    }}
  }});
  }}

// 가격 분포 차트
  if (pd.labels.length) {{
  new Chart(document.getElementById('priceChart'), {{
    type: 'bar',
    data: {{
      labels: pd.labels,
      datasets: [{{
        label: '평균가 (원)',
        data: pd.avgs,
        backgroundColor: ['rgba(52,152,219,0.7)','rgba(231,76,60,0.7)','rgba(46,204,113,0.7)'],
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: '카테고리별 평균가' }} }},
      scales: {{ y: {{ beginAtZero: true }} }}
    }}
  }});
  }}
}}

const chartSection = document.getElementById('trends');
chartSection.addEventListener('toggle', () => {{
  if (chartSection.open) renderCharts();
}});
if ('IntersectionObserver' in window) {{
  const chartObserver = new IntersectionObserver(entries => {{
    if (entries.some(entry => entry.isIntersecting)) {{
      renderCharts();
      chartObserver.disconnect();
    }}
  }}, {{ rootMargin: '200px' }});
  chartObserver.observe(chartSection);
}} else {{
  renderCharts();
}}

document.querySelectorAll('.nav-item[href^="#"]').forEach(link => {{
  link.addEventListener('click', () => {{
    const target = document.querySelector(link.getAttribute('href'));
    if (target && target.tagName === 'DETAILS') target.open = true;
  }});
}});
</script>
</body>
</html>"""

    html = "\n".join(line.rstrip() for line in html.splitlines()) + "\n"
    path = config.DASHBOARD_OUTPUT_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    # GitHub Pages용 docs/ 에도 동시 저장
    docs_path = os.path.join(os.path.dirname(path) or ".", "..", "docs", "dashboard.html")
    docs_path = os.path.normpath(docs_path)
    os.makedirs(os.path.dirname(docs_path), exist_ok=True)
    with open(docs_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info("대시보드 저장 완료: %s + %s", path, docs_path)
    return path
