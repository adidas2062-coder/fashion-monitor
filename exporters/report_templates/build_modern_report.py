import json, os

data = json.load(open("/private/tmp/claude-501/-Users-jeonjuwon/f6351051-810a-4ae7-8173-0c672c5bdb6e/scratchpad/weekly_data.json", encoding="utf-8"))
AVG = {"상의": 61182, "아우터": 195560, "바지": 36332}
SUB = {"상의": "반팔티 중심 · 회전 빠름", "아우터": "고가 테크웨어 vs 중저가 트랙탑", "바지": "무신사 스탠다드 장악"}

def rows(cat):
    out = []
    for r in data[cat]:
        dc = f'<span class="badge">-{r["dc"]}%</span>' if r["dc"] else ''
        out.append(f'''<tr>
          <td class="rk">{r['rank']}</td>
          <td class="br">{r['brand']}</td>
          <td class="nm">{r['name']}</td>
          <td class="pr">{r['price']:,}<span class="won">원</span></td>
          <td class="dc">{dc}</td>
        </tr>''')
    return "\n".join(out)

def section(cat):
    return f'''<section class="cat">
      <div class="cat-head">
        <h2>{cat}</h2>
        <div class="cat-sub">{SUB[cat]}</div>
        <div class="cat-avg">평균 <b>{AVG[cat]:,}</b>원</div>
      </div>
      <table>
        <thead><tr><th>#</th><th>브랜드</th><th>상품명</th><th>가격</th><th>할인</th></tr></thead>
        <tbody>{rows(cat)}</tbody>
      </table>
    </section>'''

html = f'''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>무신사 남성 주간 트렌드 리포트</title>
<style>
:root {{
  --ink:#111418; --sub:#6b7280; --line:#eceef1; --line2:#f4f5f7;
  --accent:#111418; --sale:#e11d48; --hl:#f0f4ff; --brand:#2563eb;
}}
* {{ margin:0; padding:0; box-sizing:border-box; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
@page {{ size:A4; margin:16mm 15mm; }}
body {{ font-family:"Pretendard","Apple SD Gothic Neo",sans-serif; color:var(--ink);
  font-size:10.5pt; line-height:1.5; letter-spacing:-0.2px; background:#fff; }}
.wrap {{ max-width:180mm; margin:0 auto; }}

/* Header */
.hero {{ border-bottom:2px solid var(--ink); padding-bottom:14px; margin-bottom:22px; }}
.eyebrow {{ font-size:8.5pt; font-weight:600; color:var(--brand); letter-spacing:1px; text-transform:uppercase; }}
.hero h1 {{ font-size:26pt; font-weight:800; letter-spacing:-1px; margin:6px 0 4px; line-height:1.15; }}
.hero .meta {{ font-size:9pt; color:var(--sub); }}

/* KPI cards */
.kpis {{ display:flex; gap:10px; margin-bottom:26px; }}
.kpi {{ flex:1; border:1px solid var(--line); border-radius:12px; padding:14px 16px; background:#fff; }}
.kpi .k-cat {{ font-size:9pt; font-weight:700; color:var(--sub); }}
.kpi .k-val {{ font-size:17pt; font-weight:800; letter-spacing:-0.5px; margin-top:3px; }}
.kpi .k-val small {{ font-size:10pt; font-weight:600; color:var(--sub); }}
.kpi .k-sub {{ font-size:8pt; color:var(--sub); margin-top:5px; line-height:1.35; }}

/* Section */
.section-label {{ font-size:9pt; font-weight:700; color:var(--sub); letter-spacing:0.5px;
  margin:4px 0 12px; padding-bottom:6px; border-bottom:1px solid var(--line); }}
.cat {{ margin-bottom:20px; break-inside:avoid; }}
.cat-head {{ display:flex; align-items:baseline; gap:10px; margin-bottom:8px; }}
.cat-head h2 {{ font-size:14pt; font-weight:800; }}
.cat-sub {{ font-size:8.5pt; color:var(--sub); flex:1; }}
.cat-avg {{ font-size:9pt; color:var(--sub); }}
.cat-avg b {{ color:var(--ink); font-weight:800; font-size:11pt; }}

/* Table */
table {{ width:100%; border-collapse:collapse; }}
thead th {{ font-size:8pt; font-weight:700; color:var(--sub); text-align:left;
  padding:6px 8px; border-bottom:1.5px solid var(--ink); }}
thead th:nth-child(4),thead th:nth-child(5) {{ text-align:right; }}
tbody td {{ padding:7px 8px; border-bottom:1px solid var(--line2); font-size:9.5pt; vertical-align:middle; }}
tbody tr:nth-child(1) .rk {{ background:var(--ink); color:#fff; }}
.rk {{ width:22px; text-align:center; font-weight:800; font-size:9pt; color:var(--sub);
  border-radius:6px; }}
.br {{ font-weight:700; white-space:nowrap; width:80px; }}
.nm {{ color:#374151; }}
.pr {{ text-align:right; font-weight:700; white-space:nowrap; font-variant-numeric:tabular-nums; }}
.pr .won {{ font-weight:500; color:var(--sub); font-size:8.5pt; margin-left:1px; }}
.dc {{ text-align:right; width:52px; }}
.badge {{ display:inline-block; font-size:8pt; font-weight:800; color:var(--sale);
  background:#fff1f3; padding:2px 6px; border-radius:20px; }}

/* Insight */
.insights {{ margin-top:8px; }}
.ins {{ border:1px solid var(--line); border-left:3px solid var(--brand); border-radius:10px;
  padding:12px 15px; margin-bottom:9px; break-inside:avoid; }}
.ins h3 {{ font-size:10.5pt; font-weight:800; margin-bottom:3px; }}
.ins p {{ font-size:9.5pt; color:#374151; }}
.ins b {{ color:var(--ink); background:var(--hl); padding:0 3px; border-radius:3px; font-weight:700; }}

/* Actions */
.actions {{ background:#f8f9fb; border-radius:12px; padding:16px 18px; margin-top:14px; }}
.actions h3 {{ font-size:10pt; font-weight:800; margin-bottom:8px; }}
.actions li {{ list-style:none; font-size:9.5pt; padding:4px 0 4px 18px; position:relative; color:#374151; }}
.actions li:before {{ content:"→"; position:absolute; left:0; color:var(--brand); font-weight:800; }}
.actions li b {{ color:var(--ink); font-weight:700; }}

footer {{ margin-top:20px; padding-top:10px; border-top:1px solid var(--line);
  font-size:8pt; color:var(--sub); text-align:center; }}
.spacer {{ height:8px; }}
</style></head>
<body><div class="wrap">

<div class="hero">
  <div class="eyebrow">Weekly Trend Report</div>
  <h1>무신사 남성 주간 트렌드 리포트</h1>
  <div class="meta">2026.07.08 · 무신사 남성 주간 랭킹 · 상의·아우터·바지 TOP 8 · fashion-monitor 자동수집</div>
</div>

<div class="kpis">
  <div class="kpi"><div class="k-cat">상의 평균가</div><div class="k-val">61,182<small>원</small></div><div class="k-sub">반팔티 중심 · 할인율 30~39%로 회전 빠름</div></div>
  <div class="kpi"><div class="k-cat">아우터 평균가</div><div class="k-val">195,560<small>원</small></div><div class="k-sub">상·하의 대비 3~5배 · 가격 양극화</div></div>
  <div class="kpi"><div class="k-cat">바지 평균가</div><div class="k-val">36,332<small>원</small></div><div class="k-sub">무신사 스탠다드 TOP8 중 4개 장악</div></div>
</div>

<div class="section-label">카테고리별 주간 랭킹</div>
{section("상의")}
{section("아우터")}
{section("바지")}

<div class="section-label">MD 트렌드 인사이트</div>
<div class="insights">
  <div class="ins"><h3>여름 키워드가 전 카테고리를 관통</h3><p>'린넨 라이크', '쿨', '반팔', '크롭'이 상·하의에 동시 등장. 계절 수요가 <b>특정 소재·실루엣으로 수렴</b> 중 — 여름 린넨·쿨소재 라인 노출 확대 시점.</p></div>
  <div class="ins"><h3>바지 = 무신사 스탠다드 천하</h3><p>바지 TOP8 중 <b>4개가 무신사 스탠다드</b>. 가성비 와이드·밴딩 슬랙스가 표준화 — 경쟁 브랜드는 소재·컬러 차별화 없이는 진입 난이도 높음.</p></div>
  <div class="ins"><h3>아우터 가격 양극화 뚜렷</h3><p>아크테릭스(29만·61만) 테크웨어 vs 스파오·무신사 스탠다드(7~8만) 트랙탑·블레이저. <b>중간가(10~15만)대는 수요 공백.</b></p></div>
  <div class="ins"><h3>남성 상의에 '크롭' 실루엣 부상</h3><p>키뮤어가 크롭 반팔로 6·8위 동시 진입. 니치였던 <b>크롭이 주류로 올라오는 신호</b> — 테스트 SKU 소량 편성 검토.</p></div>
</div>

<div class="actions">
  <h3>이번 주 MD 액션</h3>
  <ul>
    <li><b>기획전</b> — '여름 린넨·쿨' 통합 기획전 우선 검토 (상·하의 교차 수요 확인)</li>
    <li><b>발주</b> — 와이드·밴딩 슬랙스는 차별화 포인트 없이 물량 확대 지양</li>
    <li><b>신규</b> — 남성 크롭 반팔 테스트 SKU 소량 편성</li>
    <li><b>가격</b> — 아우터 중간가대 진입 시 수요 공백 리스크 점검</li>
  </ul>
</div>

<footer>출처: 무신사 남성 주간 랭킹 · fashion-monitor 자동수집 · 2026.07.08 · 가격·할인율은 수집 시점 기준</footer>

</div></body></html>'''

dest = "/Users/jeonjuwon/fashion-monitor/data/reports/modern_weekly.html"
open(dest, "w", encoding="utf-8").write(html)
print("HTML 생성:", dest, f"({len(html):,} bytes)")
