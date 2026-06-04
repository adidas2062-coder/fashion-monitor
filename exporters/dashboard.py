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
        rank_txt = "NEW" if s.get("is_new_entry") else (f"▲{s.get('rank_change',0)}" if s.get("rank_change") else "-")
        level    = s.get("level", "🟢 참고")
        score    = s.get("score", 0)
        issues   = s.get("issues", [])
        issue_html = "".join(f'<span class="issue-tag">{i}</span>' for i in issues)
        level_color = {"🔴": "#e74c3c", "🟡": "#f39c12", "🟢": "#27ae60"}.get(level[:2], "#888")
        parts.append(f"""
        <div class="signal-card" style="border-color:{level_color}">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <h3 style="color:{level_color}">{level} {s.get('keyword','')}</h3>
            <span style="background:{level_color};color:#fff;border-radius:20px;padding:2px 10px;font-size:12px;font-weight:bold">{score}점</span>
          </div>
          <p>트렌드 +{s.get('trend_pct',0):.0f}% | 랭킹 {rank_txt}</p>
          <p class="theme" style="margin:4px 0">→ {s.get('theme','')}</p>
          <div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px">{issue_html}</div>
          <div style="margin-top:8px;background:#f8f9fa;border-radius:8px;padding:8px 10px;font-size:12px">
            <span style="color:#888">📅 기획전 권장 오픈일:</span>
            <strong style="color:{level_color};margin-left:6px">{s.get('open_label','계산 중')}</strong>
          </div>
          <p class="meta" style="margin-top:4px">{s.get('brand','')} / {s.get('category','')}</p>
        </div>""")
    return "\n".join(parts)


def _ranking_table(items: List[Dict], cat_prefix: str, period: str = "1일") -> str:
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
        badge = _rank_badge(item.get("rank_change"))
        price = f"{item.get('price', 0):,}"
        disc  = item.get("discount_rate", 0)
        disc_str = f'<span class="disc">-{disc}%</span>' if disc else ""
        url   = item.get("url", "#")
        name  = item.get("product_name", "")[:30]
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


def _new_entry_cards(new_entries: List[Dict]) -> str:
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
          <h4><a href="{item.get('url','#')}" target="_blank">{item.get('product_name','')[:25]}</a></h4>
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

            # 상품 목록 (최대 5개)
            if products:
                parts.append('<table style="width:100%;font-size:12px">')
                parts.append('<tr style="color:#888"><td>순위</td><td>상품명</td><td>카테고리</td><td>가격</td></tr>')
                for p in sorted(products, key=lambda x: x.get("rank",999))[:5]:
                    rank_ch = p.get("rank_change")
                    badge = ""
                    if rank_ch is None:
                        badge = '<span style="background:#ede0ff;color:#7d3c98;padding:1px 5px;border-radius:8px;font-size:10px">NEW</span>'
                    elif rank_ch > 0:
                        badge = f'<span style="color:#27ae60">▲{rank_ch}</span>'
                    elif rank_ch < 0:
                        badge = f'<span style="color:#e74c3c">▼{abs(rank_ch)}</span>'
                    parts.append(
                        f'<tr><td>{p.get("rank","-")}위 {badge}</td>'
                        f'<td><a href="{p.get("url","#")}" target="_blank" style="color:#1a73e8">'
                        f'{p.get("product_name","")[:22]}</a></td>'
                        f'<td style="color:#888">{p.get("category","").replace("_전체","")}</td>'
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
            "product_name":  item.get("product_name", ""),
            "brand":         item.get("brand", ""),
            "price":         item.get("price", 0),
            "discount_rate": item.get("discount_rate", 0),
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
            f'<td><a href="{s.get("url","#")}" target="_blank">{s.get("product_name","")[:25]}</a></td>'
            f'<td>{s.get("brand","")}</td>'
            f'<td>{s.get("appearances",0)}회</td>'
            f'<td>{s.get("best_rank","-")}위</td></tr>'
        )
    return f"""<table>
      <thead><tr><th></th><th>상품명</th><th>브랜드</th><th>등장</th><th>최고순위</th></tr></thead>
      <tbody>{"".join(trs)}</tbody></table>"""


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

    # 기간 × 카테고리(대분류 + 세분류) 인덱싱
    # key 예시: "1일|상의", "주간|상의_반소매티셔츠", "월간|아우터_후드집업"
    _MAIN_CATS = ["상의", "아우터", "바지"]
    ranking_index: dict = {}

    def _to_row(i):
        return {
            "rank":          i.get("rank"),
            "rank_change":   i.get("rank_change"),
            "product_name":  i.get("product_name", ""),
            "brand":         i.get("brand", ""),
            "price":         i.get("price", 0),
            "discount_rate": i.get("discount_rate", 0),
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
<title>패션 MD 모니터링 대시보드 — {today_str}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:#f8f9fa; --card:#fff; --accent:#1a73e8; --signal:#ff6b00;
    --up:#2ecc71; --down:#e74c3c; --new:#9b59b6; --border:#e0e0e0;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Apple SD Gothic Neo',sans-serif; background:var(--bg); color:#222; font-size:14px; }}
  header {{ background:#111; color:#fff; padding:16px 24px; display:flex; justify-content:space-between; align-items:center; }}
  header h1 {{ font-size:18px; }}
  header .meta {{ font-size:12px; color:#aaa; }}
  .container {{ max-width:1200px; margin:0 auto; padding:20px; }}
  .section {{ background:var(--card); border-radius:12px; padding:20px; margin-bottom:20px; box-shadow:0 1px 4px rgba(0,0,0,.08); }}
  h2 {{ font-size:16px; margin-bottom:14px; border-bottom:2px solid var(--accent); padding-bottom:6px; }}
  /* 시그널 */
  .signal-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:12px; }}
  .signal-card {{ background:#fff8f0; border:2px solid var(--signal); border-radius:10px; padding:14px; }}
  .signal-card h3 {{ color:var(--signal); font-size:15px; margin-bottom:6px; }}
  .signal-card .theme {{ font-weight:bold; color:#333; }}
  .signal-card .meta {{ font-size:12px; color:#888; margin-top:4px; }}
  /* 탭 */
  .tabs {{ display:flex; gap:8px; margin-bottom:12px; }}
  .tab {{ padding:6px 14px; border-radius:20px; border:1px solid var(--border); cursor:pointer; font-size:13px; }}
  .tab.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
  .tab-content {{ display:none; }}
  .tab-content.active {{ display:block; }}
  /* 테이블 */
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ background:#f0f4ff; padding:8px; text-align:left; font-weight:600; }}
  td {{ padding:8px; border-bottom:1px solid var(--border); }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  /* 배지 */
  .badge {{ font-size:11px; padding:2px 6px; border-radius:10px; font-weight:bold; }}
  .badge.up   {{ background:#d4f5e2; color:#1a7a40; }}
  .badge.down {{ background:#fde8e8; color:#c0392b; }}
  .badge.new  {{ background:#ede0ff; color:#7d3c98; }}
  .badge.same {{ background:#eee; color:#666; }}
  .disc {{ color:#e74c3c; font-size:12px; }}
  /* 신규 진입 카드 */
  .entry-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:12px; }}
  .entry-card {{ border:1px solid var(--border); border-radius:10px; padding:12px; }}
  .entry-cat {{ font-size:11px; color:var(--accent); font-weight:bold; margin-bottom:4px; }}
  .entry-card h4 {{ font-size:13px; margin-bottom:4px; }}
  .entry-card .brand {{ color:#888; font-size:12px; margin-bottom:4px; }}
  /* 차트 */
  .chart-row {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  @media(max-width:700px){{ .chart-row{{ grid-template-columns:1fr; }} }}
  .empty {{ color:#aaa; font-style:italic; }}
  .issue-tag {{ background:#fff3cd; color:#856404; border:1px solid #ffc107; border-radius:12px; padding:2px 8px; font-size:11px; }}
</style>
</head>
<body>
<header>
  <h1>👗 패션 MD 모니터링 대시보드</h1>
  <span class="meta">마지막 업데이트: {now_str}</span>
</header>
<div class="container">

  <!-- 1. 날씨 & 수요 예측 -->
  {_weather_block(weather_data or {{}})}

  <!-- 2. 기획전 시그널 -->
  <div class="section">
    <h2>🎯 기획전 타이밍 시그널</h2>
    <div class="signal-grid">
      {_signal_cards(signals)}
    </div>
  </div>

  <!-- 3. 실시간 검색어 + 트렌드 예측 -->
  <div class="section">
    <h2>🔍 무신사 실시간 검색어 & 다음주 트렌드 예측</h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
      <div>
        <h3 style="font-size:14px;margin-bottom:8px;color:#555">실시간 검색어 TOP 20</h3>
        {_keyword_table(keyword_data or [])}
      </div>
      <div>
        <h3 style="font-size:14px;margin-bottom:8px;color:#555">트렌드 예측 (데이터 축적 중)</h3>
        {_forecast_table(forecasts or [])}
      </div>
    </div>
  </div>

  <!-- 4. 무신사 랭킹 TOP 30 -->
  <div class="section">
    <h2>🏆 무신사 랭킹 TOP 30</h2>

    <!-- 기간 탭 -->
    <div class="tabs" id="period-tabs" style="margin-bottom:10px">
      <div class="tab active" onclick="switchPeriod('1일',this)">1일</div>
      <div class="tab" onclick="switchPeriod('주간',this)">주간</div>
      <div class="tab" onclick="switchPeriod('월간',this)">월간</div>
    </div>

    <!-- 대분류 탭 -->
    <div class="tabs" id="main-cat-tabs" style="margin-bottom:6px">
      <div class="tab active" onclick="switchMainCat('상의',this)">상의</div>
      <div class="tab" onclick="switchMainCat('아우터',this)">아우터</div>
      <div class="tab" onclick="switchMainCat('바지',this)">바지</div>
    </div>

    <!-- 세분류 탭 -->
    <div id="sub-cat-tabs" class="tabs" style="margin-bottom:12px;flex-wrap:wrap"></div>

    <div id="ranking-table-area">
      {_ranking_table(items,'상의','1일')}
    </div>
  </div>

  <!-- 5. 신규 진입 상품 -->
  <div class="section">
    <h2>⬆ 오늘의 신규 진입 상품</h2>
    <div class="entry-grid">
      {_new_entry_cards(rank_diff_result.get('new_entries', []))}
    </div>
  </div>

  <!-- 6. 트렌드 & 가격 분포 -->
  <div class="section">
    <h2>📊 트렌드 & 가격 분포</h2>
    <div class="chart-row">
      <div><canvas id="trendChart" height="200"></canvas></div>
      <div><canvas id="priceChart" height="200"></canvas></div>
    </div>
  </div>

  <!-- 7. 스테디셀러 -->
  <div class="section">
    <h2>🏆 스테디셀러 (연속 TOP 10)</h2>
    {_steady_seller_rows(steady or [])}
  </div>

  <!-- 29CM 남성 랭킹 -->
  <div class="section">
    <h2>🛍 29CM 남성 베스트 TOP 30</h2>

    <!-- 카테고리 탭 -->
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

  <!-- 8. 관심 브랜드 현황 (맨 아래) -->
  <div class="section">
    <h2>🏷 관심 브랜드 현황</h2>
    {_brand_section(brand_data)}
  </div>

</div>

<script>
// 랭킹 데이터 (기간 × 카테고리 × 상품 목록)
const rankingData = {ranking_json};

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
  const allRows = rankingData[key] || [];

  if (!allRows.length) {{
    area.innerHTML = '<p class="empty">데이터 없음 (수집 후 표시됩니다)</p>';
    return;
  }}

  const visibleRows = rankingExpanded ? allRows : allRows.slice(0, 10);
  let html = '<table><thead><tr><th>#</th><th>변동</th><th>상품명</th><th>브랜드</th><th>가격</th><th>세분류</th></tr></thead><tbody>';
  visibleRows.forEach(r => {{
    const ch = r.rank_change;
    let badge = '';
    if (ch === null || ch === undefined) badge = '<span class="badge new">NEW</span>';
    else if (ch > 0) badge = '<span class="badge up">▲' + ch + '</span>';
    else if (ch < 0) badge = '<span class="badge down">▼' + Math.abs(ch) + '</span>';
    else badge = '<span class="badge same">→</span>';
    const disc = r.discount_rate ? '<span class="disc">-' + r.discount_rate + '%</span>' : '';
    const subcat = (r.category || '').replace(currentMainCat + '_', '');
    html += '<tr><td>' + r.rank + '</td><td>' + badge + '</td>';
    html += '<td><a href="' + r.url + '" target="_blank">' + (r.product_name || '').slice(0, 30) + '</a></td>';
    html += '<td>' + (r.brand || '') + '</td>';
    html += '<td>' + Number(r.price).toLocaleString() + '원 ' + disc + '</td>';
    html += '<td style="color:#888;font-size:11px">' + subcat + '</td></tr>';
  }});
  html += '</tbody></table>';

  if (allRows.length > 10) {{
    const btnText = rankingExpanded ? '▲ 접기' : '▼ ' + allRows.length + '위까지 펼치기';
    html += '<div style="text-align:center;margin-top:8px">'
      + '<button onclick="toggleRanking()" style="border:1px solid #ddd;background:#f8f9fa;padding:6px 20px;border-radius:20px;cursor:pointer;font-size:13px;color:#555">'
      + btnText + '</button></div>';
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
  let html = '<table><thead><tr><th>#</th><th>상품명</th><th>브랜드</th><th>가격</th><th>평점</th></tr></thead><tbody>';
  visibleRows.forEach(r => {{
    const disc = r.discount_rate ? '<span class="disc">-' + r.discount_rate + '%</span>' : '';
    const score = r.review_score ? '★' + r.review_score : '';
    const sold = r.is_sold_out ? ' <span style="color:#e74c3c;font-size:10px">품절</span>' : '';
    html += '<tr><td>' + r.rank + '</td>';
    html += '<td><a href="' + r.url + '" target="_blank">' + (r.product_name || '').slice(0, 30) + '</a>' + sold + '</td>';
    html += '<td>' + (r.brand || '') + '</td>';
    html += '<td>' + Number(r.price).toLocaleString() + '원 ' + disc + '</td>';
    html += '<td style="color:#888;font-size:11px">' + score + '</td></tr>';
  }});
  html += '</tbody></table>';
  if (allRows.length > 10) {{
    const btnText = cm29Expanded ? '▲ 접기' : '▼ ' + allRows.length + '위까지 펼치기';
    html += '<div style="text-align:center;margin-top:8px"><button onclick="toggleCm29()" style="border:1px solid #ddd;background:#f8f9fa;padding:6px 20px;border-radius:20px;cursor:pointer;font-size:13px;color:#555">' + btnText + '</button></div>';
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
const pd = {price_json};
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
</script>
</body>
</html>"""

    os.makedirs("data", exist_ok=True)
    path = config.DASHBOARD_OUTPUT_PATH
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("대시보드 저장 완료: %s", path)
    return path
