"""
HTML 대시보드 생성기.

수집/분석 결과를 Chart.js 기반 단일 HTML 파일로 출력한다.
data/dashboard.html 에 매일 덮어쓰기 저장.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List

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
        rank_txt = "NEW" if s.get("is_new_entry") else f"▲{s.get('rank_change',0)}"
        parts.append(f"""
        <div class="signal-card">
          <h3>🎯 {s.get('keyword','')}</h3>
          <p>트렌드 +{s.get('trend_pct',0):.0f}% | 랭킹 {rank_txt}</p>
          <p class="theme">→ {s.get('theme','')}</p>
          <p class="meta">{s.get('brand','')} / {s.get('category','')}</p>
        </div>""")
    return "\n".join(parts)


def _ranking_table(items: List[Dict], cat_prefix: str, period: str = "1일") -> str:
    """cat_prefix 로 시작하는 카테고리 중 period 일치 항목의 TOP 10 반환."""
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


def _brand_rows(brand_data: List[Dict]) -> str:
    rows = [b for b in brand_data if b.get("product_count", 0) > 0]
    if not rows:
        return "<tr><td colspan='4'>관심 브랜드 랭킹 외</td></tr>"
    parts = []
    for b in rows:
        cnt = b["product_count"]
        best = f"{b.get('best_rank','-')}위 ({b.get('best_category','')})"
        change = b.get("count_change")
        change_str = f"+{change}" if change and change > 0 else (str(change) if change else "-")
        parts.append(f"""
        <tr>
          <td><strong>{b['brand']}</strong></td>
          <td>{cnt}개</td>
          <td>{best}</td>
          <td>{change_str}</td>
        </tr>""")
    return "".join(parts)


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def generate(
    rank_diff_result: Dict,
    trend_data: List[Dict],
    price_result: Dict,
    brand_data: List[Dict],
    signals: List[Dict],
) -> str:
    """
    대시보드 HTML 생성 후 파일 저장.

    Returns:
        저장된 파일 경로.
    """
    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    today_str = datetime.now(timezone.utc).strftime("%Y년 %m월 %d일")
    items     = rank_diff_result.get("items", [])
    trend_json = _trend_chart_data(trend_data)
    price_json = _price_chart_data(price_result)

    # 기간 × 대분류 조합으로 랭킹 데이터 인덱싱
    # key: "1일|상의", "주간|아우터" 등 → TOP10 상품 목록
    _MAIN_CATS = {"상의": "상의", "아우터": "아우터", "바지": "바지"}
    ranking_index: dict = {}
    for item in items:
        cat  = item.get("category", "")
        period = item.get("period", "1일")
        for main in _MAIN_CATS:
            if cat.startswith(main + "_"):
                key = f"{period}|{main}"
                ranking_index.setdefault(key, [])
                if len(ranking_index[key]) < 10:
                    # 전체 서브카테고리 중 rank 낮은(좋은) 것 우선 — 전체 수집 후 정렬
                    ranking_index[key].append({
                        "rank":          item.get("rank"),
                        "rank_change":   item.get("rank_change"),
                        "product_name":  item.get("product_name", ""),
                        "brand":         item.get("brand", ""),
                        "price":         item.get("price", 0),
                        "discount_rate": item.get("discount_rate", 0),
                        "url":           item.get("url", ""),
                        "category":      cat,
                        "period":        period,
                    })
                break
    # 전체 서브카테고리 데이터를 전체(_전체) 우선, 나머지는 rank 오름차순 정렬
    for key in ranking_index:
        period_k, main_k = key.split("|")
        full_cat = f"{main_k}_전체"
        full_items = [i for i in items
                      if i.get("category") == full_cat and i.get("period") == period_k]
        if full_items:
            full_items.sort(key=lambda x: x.get("rank", 999))
            ranking_index[key] = [{
                "rank":          i.get("rank"),
                "rank_change":   i.get("rank_change"),
                "product_name":  i.get("product_name", ""),
                "brand":         i.get("brand", ""),
                "price":         i.get("price", 0),
                "discount_rate": i.get("discount_rate", 0),
                "url":           i.get("url", ""),
                "category":      i.get("category", ""),
                "period":        i.get("period", ""),
            } for i in full_items[:10]]
        else:
            ranking_index[key].sort(key=lambda x: x.get("rank", 999))
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
</style>
</head>
<body>
<header>
  <h1>👗 패션 MD 모니터링 대시보드</h1>
  <span class="meta">마지막 업데이트: {now_str}</span>
</header>
<div class="container">

  <!-- 기획전 시그널 -->
  <div class="section">
    <h2>🎯 기획전 타이밍 시그널</h2>
    <div class="signal-grid">
      {_signal_cards(signals)}
    </div>
  </div>

  <!-- 무신사 랭킹 TOP 10 -->
  <div class="section">
    <h2>🏆 무신사 랭킹 TOP 10</h2>
    <div style="display:flex;gap:16px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
      <div class="tabs" id="period-tabs">
        <div class="tab active" onclick="switchPeriod('1일',this)">1일</div>
        <div class="tab" onclick="switchPeriod('주간',this)">주간</div>
        <div class="tab" onclick="switchPeriod('월간',this)">월간</div>
      </div>
      <div class="tabs" id="cat-tabs">
        <div class="tab active" onclick="switchCat('상의',this)">상의</div>
        <div class="tab" onclick="switchCat('아우터',this)">아우터</div>
        <div class="tab" onclick="switchCat('바지',this)">바지</div>
      </div>
    </div>
    <div id="ranking-table-area">
      {_ranking_table(items,'상의','1일')}
    </div>
  </div>

  <!-- 신규 진입 상품 -->
  <div class="section">
    <h2>⬆ 오늘의 신규 진입 상품</h2>
    <div class="entry-grid">
      {_new_entry_cards(rank_diff_result.get('new_entries', []))}
    </div>
  </div>

  <!-- 차트 -->
  <div class="section">
    <h2>📊 트렌드 & 가격 분포</h2>
    <div class="chart-row">
      <div><canvas id="trendChart" height="200"></canvas></div>
      <div><canvas id="priceChart" height="200"></canvas></div>
    </div>
  </div>

  <!-- 브랜드 트래킹 -->
  <div class="section">
    <h2>🏷 관심 브랜드 현황</h2>
    <table>
      <thead><tr><th>브랜드</th><th>랭킹 내 상품수</th><th>최고 순위</th><th>전일 대비</th></tr></thead>
      <tbody>{_brand_rows(brand_data)}</tbody>
    </table>
  </div>

</div>

<script>
// 랭킹 데이터 (기간 × 카테고리 × 상품 목록)
const rankingData = {ranking_json};

let currentPeriod = '1일';
let currentCat = '상의';

function renderRankingTable() {{
  const area = document.getElementById('ranking-table-area');
  const key = currentPeriod + '|' + currentCat;
  const rows = rankingData[key] || [];
  if (!rows.length) {{
    area.innerHTML = '<p class="empty">데이터 없음 (수집 후 표시됩니다)</p>';
    return;
  }}
  let html = '<table><thead><tr><th>#</th><th>변동</th><th>상품명</th><th>브랜드</th><th>가격</th><th>세분류</th></tr></thead><tbody>';
  rows.forEach(r => {{
    const ch = r.rank_change;
    let badge = '';
    if (ch === null || ch === undefined) badge = '<span class="badge new">NEW</span>';
    else if (ch > 0) badge = '<span class="badge up">▲' + ch + '</span>';
    else if (ch < 0) badge = '<span class="badge down">▼' + Math.abs(ch) + '</span>';
    else badge = '<span class="badge same">→</span>';
    const disc = r.discount_rate ? '<span class="disc">-' + r.discount_rate + '%</span>' : '';
    const subcat = (r.category || '').replace(currentCat + '_', '');
    html += '<tr>';
    html += '<td>' + r.rank + '</td>';
    html += '<td>' + badge + '</td>';
    html += '<td><a href="' + r.url + '" target="_blank">' + (r.product_name || '').slice(0, 30) + '</a></td>';
    html += '<td>' + (r.brand || '') + '</td>';
    html += '<td>' + Number(r.price).toLocaleString() + '원 ' + disc + '</td>';
    html += '<td style="color:#888;font-size:11px">' + subcat + '</td>';
    html += '</tr>';
  }});
  html += '</tbody></table>';
  area.innerHTML = html;
}}

function switchPeriod(period, el) {{
  currentPeriod = period;
  document.querySelectorAll('#period-tabs .tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  renderRankingTable();
}}

function switchCat(cat, el) {{
  currentCat = cat;
  document.querySelectorAll('#cat-tabs .tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  renderRankingTable();
}}

renderRankingTable();

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
