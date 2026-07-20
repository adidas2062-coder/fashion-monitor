"""
주간 리포트 생성기 (매주 월요일).

지난 7일치 노션 랭킹 DB 데이터를 집계해
PDF 파일과 노션 페이지를 생성한다.

포함 내용:
  1. 카테고리별 랭킹 변동 요약
  2. 주간 TOP 상승 브랜드/상품
  3. 트렌드 키워드 주간 흐름
  4. 신규 진입 상품 목록
  5. 가격대 분포 변화
  6. 기획전 시그널 발생 이력
  7. 다음 주 주목 키워드 예측
"""

import logging
import os
from datetime import date, timedelta
from typing import Dict, List, Optional

import config

logger = logging.getLogger(__name__)


# ── 노션에서 주간 데이터 조회 ─────────────────────────────────────────────────

_DATA_SOURCE_CACHE: Dict[str, str] = {}


def _resolve_data_source_id(client, db_id: str) -> str:
    """DB id로부터 data source id를 얻는다(notion-client 3.x: query는 data source 단위).

    notion-client 2.x의 `databases.query`가 3.x에서 제거되어, 먼저 DB를
    retrieve해 첫 data source id를 뽑아 캐시한다.
    """
    if db_id in _DATA_SOURCE_CACHE:
        return _DATA_SOURCE_CACHE[db_id]
    db = client.databases.retrieve(database_id=db_id)
    sources = db.get("data_sources") or []
    if not sources:
        raise ValueError(f"DB {db_id}에 data source가 없습니다")
    ds_id = sources[0]["id"]
    _DATA_SOURCE_CACHE[db_id] = ds_id
    return ds_id


def _fetch_weekly_data(client, db_id: str, start: str, end: str) -> List[Dict]:
    """노션 DB에서 date 범위로 데이터 조회(전체 페이지 순회)."""
    try:
        ds_id = _resolve_data_source_id(client, db_id)
        date_filter = {
            "and": [
                {"property": "날짜", "date": {"on_or_after": start}},
                {"property": "날짜", "date": {"on_or_before": end}},
            ]
        }
        results: List[Dict] = []
        cursor: Optional[str] = None
        while True:
            resp = client.data_sources.query(
                data_source_id=ds_id,
                filter=date_filter,
                **({"start_cursor": cursor} if cursor else {}),
            )
            results.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        return results
    except Exception as exc:
        logger.error("노션 주간 데이터 조회 실패: %s", exc)
        return []


def _page_to_dict(page: Dict) -> Dict:
    props = page.get("properties", {})
    def title(p): return (p.get("title") or [{}])[0].get("text",{}).get("content","")
    def text(p):  return (p.get("rich_text") or [{}])[0].get("text",{}).get("content","")
    def num(p):   return p.get("number")
    def sel(p):   s=p.get("select"); return s.get("name","") if s else ""
    def url(p):   return p.get("url","")
    def dt(p):    d=p.get("date"); return d.get("start","") if d else ""
    return {
        "product_name":  title(props.get("상품명",{})),
        "collected_at":  dt(props.get("날짜",{})),
        "category":      sel(props.get("카테고리",{})),
        "rank":          num(props.get("순위",{})),
        "rank_change":   num(props.get("순위변동",{})),
        "brand":         text(props.get("브랜드",{})),
        "price":         num(props.get("가격",{})) or 0,
        "discount_rate": num(props.get("할인율",{})) or 0,
        "url":           url(props.get("URL",{})),
    }


# ── 분석 함수 ─────────────────────────────────────────────────────────────────

def _top_risers(items: List[Dict], n: int = 5) -> List[Dict]:
    ranked = [i for i in items if i.get("rank_change") is not None and i["rank_change"] > 0]
    return sorted(ranked, key=lambda x: x["rank_change"], reverse=True)[:n]


def _top_brands(items: List[Dict], n: int = 5) -> List[Dict]:
    from collections import Counter
    counts = Counter(i.get("brand","") for i in items if i.get("brand"))
    return [{"brand": b, "count": c} for b, c in counts.most_common(n)]


def _price_summary(items: List[Dict]) -> Dict:
    import statistics
    by_cat: Dict[str, List[int]] = {}
    for i in items:
        cat = i.get("category","기타")
        by_cat.setdefault(cat, []).append(i.get("price",0))
    return {
        cat: {"avg": round(statistics.mean(prices)), "count": len(prices)}
        for cat, prices in by_cat.items() if prices
    }


# ── PDF 생성 ─────────────────────────────────────────────────────────────────

def _make_pdf(report_data: Dict, path: str) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import platform

    # 한글 폰트 등록
    font_name = "NotoSans"
    font_paths = [
        "/System/Library/Fonts/Supplemental/NotoSansKR-Regular.ttf",
        "/Library/Fonts/NotoSansKR-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        os.path.expanduser("~/Library/Fonts/NotoSansKR-Regular.ttf"),
    ]
    registered = False
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont(font_name, fp))
                registered = True
                break
            except Exception:
                pass
    if not registered:
        font_name = "Helvetica"   # 한글 깨지지만 파일은 생성됨

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", fontName=font_name, fontSize=16, spaceAfter=8, textColor=colors.HexColor("#1a73e8"))
    h2 = ParagraphStyle("H2", fontName=font_name, fontSize=13, spaceAfter=6, textColor=colors.HexColor("#333"))
    body = ParagraphStyle("Body", fontName=font_name, fontSize=10, spaceAfter=4, leading=14)

    story = []
    week_str = report_data.get("week_label","")

    story.append(Paragraph(f"패션 MD 주간 리포트 — {week_str}", h1))
    story.append(Spacer(1, 0.3*cm))

    # 1. 카테고리별 요약
    story.append(Paragraph("1. 카테고리별 가격 현황", h2))
    price_sum = report_data.get("price_summary", {})
    for cat, stat in price_sum.items():
        story.append(Paragraph(f"  [{cat}] 평균 {stat['avg']:,}원 / {stat['count']}건", body))
    story.append(Spacer(1, 0.3*cm))

    # 2. TOP 상승 상품
    story.append(Paragraph("2. 주간 TOP 상승 상품", h2))
    risers = report_data.get("top_risers", [])
    if risers:
        tdata = [["순위", "상품명", "브랜드", "카테고리", "상승폭"]]
        for i, r in enumerate(risers, 1):
            tdata.append([
                str(i),
                r.get("product_name","")[:20],
                r.get("brand",""),
                r.get("category",""),
                f'+{r.get("rank_change",0)}',
            ])
        t = Table(tdata, colWidths=[1.2*cm, 7*cm, 3.5*cm, 3.5*cm, 1.8*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a73e8")),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,-1), font_name),
            ("FONTSIZE",   (0,0), (-1,-1), 9),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f0f4ff")]),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#ddd")),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("  데이터 없음", body))
    story.append(Spacer(1, 0.3*cm))

    # 3. TOP 브랜드
    story.append(Paragraph("3. 주간 상위 브랜드", h2))
    for b in report_data.get("top_brands", []):
        story.append(Paragraph(f"  {b['brand']} — {b['count']}회 랭킹 진입", body))
    story.append(Spacer(1, 0.3*cm))

    # 4. 신규 진입 상품
    story.append(Paragraph("4. 주간 신규 진입 상품", h2))
    new_entries = report_data.get("new_entries", [])
    if new_entries:
        tdata = [["상품명", "브랜드", "카테고리", "가격", "날짜"]]
        for item in new_entries[:10]:
            tdata.append([
                item.get("product_name","")[:22],
                item.get("brand",""),
                item.get("category",""),
                f"{item.get('price',0):,}원",
                item.get("collected_at",""),
            ])
        t = Table(tdata, colWidths=[6*cm, 3.5*cm, 2.5*cm, 2.5*cm, 2.5*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a73e8")),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,-1), font_name),
            ("FONTSIZE",   (0,0), (-1,-1), 9),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f0f4ff")]),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#ddd")),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("  데이터 없음", body))
    story.append(Spacer(1, 0.3*cm))

    # 5. 기획전 시그널
    story.append(Paragraph("5. 주간 기획전 시그널", h2))
    signals = report_data.get("signals", [])
    if signals:
        for s in signals:
            story.append(Paragraph(
                f"  [{s.get('collected_at','')}] {s.get('keyword','')} — {s.get('theme','')}",
                body,
            ))
    else:
        story.append(Paragraph("  이번 주 시그널 없음", body))

    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    doc.build(story)
    logger.info("주간 리포트 PDF 저장: %s", path)


# ── 노션 주간 리포트 페이지 생성 ──────────────────────────────────────────────

def _create_notion_page(client, report_data: Dict) -> None:
    """노션 랭킹 DB 상위 페이지에 주간 리포트 페이지 추가."""
    if not config.NOTION_RANKING_DB_ID:
        return
    week_str = report_data.get("week_label","")
    risers_text = "\n".join(
        f"  {r['brand']} / {r['product_name'][:20]} (+{r['rank_change']})"
        for r in report_data.get("top_risers", [])[:5]
    ) or "없음"
    brands_text = "\n".join(
        f"  {b['brand']} ({b['count']}회)"
        for b in report_data.get("top_brands", [])[:5]
    ) or "없음"
    price_lines = "\n".join(
        f"  [{cat}] 평균 {st['avg']:,}원"
        for cat, st in report_data.get("price_summary", {}).items()
    ) or "없음"

    content = f"## {week_str} 주간 리포트\n\n"
    content += f"### 🏆 TOP 상승 상품\n{risers_text}\n\n"
    content += f"### 🏷 주요 브랜드\n{brands_text}\n\n"
    content += f"### 💰 가격 현황\n{price_lines}\n\n"
    content += f"### 📊 신규 진입: {len(report_data.get('new_entries',[]))}건\n"

    try:
        client.pages.create(
            parent={"database_id": config.NOTION_RANKING_DB_ID},
            properties={
                "상품명": {"title": [{"text": {"content": f"[주간리포트] {week_str}"}}]},
                "날짜":   {"date": {"start": date.today().isoformat()}},
                "카테고리": {"select": {"name": "주간리포트"}},
            },
        )
        logger.info("노션 주간 리포트 페이지 생성 완료")
    except Exception as exc:
        logger.error("노션 주간 리포트 페이지 생성 실패: %s", exc)


# ── 공개 인터페이스 ────────────────────────────────────────────────────────────

def generate(trend_data: Optional[List[Dict]] = None) -> Optional[str]:
    """
    주간 리포트 생성. 매주 월요일 main.py에서 호출.

    Args:
        trend_data: 이번 주 수집된 트렌드 데이터 (없으면 빈 리스트 사용).

    Returns:
        생성된 PDF 경로. 노션 API 없거나 실패 시 None.
    """
    if not config.NOTION_API_KEY or not config.NOTION_RANKING_DB_ID:
        logger.warning("노션 API 미설정 — 주간 리포트 스킵")
        return None

    from notion_client import Client
    client = Client(auth=config.NOTION_API_KEY)

    today     = date.today()
    week_start = today - timedelta(days=7)
    week_label = f"{week_start.strftime('%m/%d')}~{today.strftime('%m/%d')}"
    logger.info("주간 리포트 생성 시작: %s", week_label)

    # 노션에서 주간 랭킹 데이터 조회
    pages = _fetch_weekly_data(
        client, config.NOTION_RANKING_DB_ID,
        week_start.isoformat(), today.isoformat(),
    )
    items = [_page_to_dict(p) for p in pages]
    logger.info("주간 랭킹 데이터: %d건", len(items))

    # 신규 진입 상품 (노션 신규진입 DB)
    new_entry_pages: List[Dict] = []
    if config.NOTION_NEW_ENTRY_DB_ID:
        new_entry_pages = _fetch_weekly_data(
            client, config.NOTION_NEW_ENTRY_DB_ID,
            week_start.isoformat(), today.isoformat(),
        )

    # 기획전 시그널 (노션 시그널 DB)
    signal_pages: List[Dict] = []
    if config.NOTION_SIGNAL_DB_ID:
        raw = _fetch_weekly_data(
            client, config.NOTION_SIGNAL_DB_ID,
            week_start.isoformat(), today.isoformat(),
        )
        signal_pages = [_page_to_dict(p) for p in raw]

    report_data = {
        "week_label":    week_label,
        "top_risers":    _top_risers(items),
        "top_brands":    _top_brands(items),
        "price_summary": _price_summary(items),
        "new_entries":   [_page_to_dict(p) for p in new_entry_pages],
        "signals":       signal_pages,
        "trend_data":    trend_data or [],
    }

    # PDF 생성
    os.makedirs(config.REPORT_OUTPUT_DIR, exist_ok=True)
    pdf_path = os.path.join(
        config.REPORT_OUTPUT_DIR,
        f"weekly_{today.strftime('%Y%m%d')}.pdf",
    )
    try:
        _make_pdf(report_data, pdf_path)
    except Exception as exc:
        logger.error("PDF 생성 실패: %s", exc)
        pdf_path = None

    # 노션 페이지 생성
    _create_notion_page(client, report_data)

    logger.info("주간 리포트 완료")
    return pdf_path
