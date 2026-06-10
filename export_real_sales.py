#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob
import os
import re
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import pandas as pd

BD_DIR = os.path.expanduser("~/Library/CloudStorage/OneDrive-개인/바탕 화면/판매통계 BD")
OUTPUT_JSON = "/Users/jeonjuwon/.gemini/antigravity/scratch/fashion-md-simulator/data/json/sales_real.json"

def to_num(val):
    if val is None or (isinstance(val, float) and str(val) == 'nan'):
        return 0
    if isinstance(val, (int, float)):
        return val
    s = str(val).replace(',', '').strip()
    if s in ('', 'nan', 'None'):
        return 0
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return 0

def parse_musinsa_xls(fpath):
    if not fpath or not os.path.exists(fpath): return []
    with open(fpath, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    content = re.sub(r' xmlns[^=]*="[^"]*"', '', content)
    content = re.sub(r'<\?[^>]+\?>', '', content)
    content = re.sub(r'ss:', '', content)
    root = ET.fromstring(content)
    result = []
    for ws_elem in root.findall('.//Worksheet'):
        table = ws_elem.find('.//Table')
        if table is None: continue
        for i, row_elem in enumerate(table.findall('Row')):
            if i < 1: continue
            cells = [c.findtext('Data', '') for c in row_elem.findall('Cell')]
            if not cells or not cells[0]: continue
            date_str = cells[0].strip()
            if len(date_str) >= 10 and re.match(r'\d{4}[\.\-]\d{2}[\.\-]\d{2}', date_str):
                d = date_str[:10].replace('.', '-')
                vals = [to_num(v) for v in cells[1:]]
                # 무신사: 14개 데이터 [결제건, 결제액, 취소건, 취소액, 교환건, 교환액, 반품건, 반품액, 순매출건, 순매출액, ...]
                # 주문건수 = 순매출건수 (index 8), 매출 = 순매출액 (index 9)
                if len(vals) >= 10:
                    result.append({"date": d, "orders": vals[8], "revenue": vals[9]})
    return result

def parse_29cm_report(fpath):
    if not fpath or not os.path.exists(fpath): return []
    df = pd.read_excel(fpath, header=0)
    result = []
    for _, row in df.iterrows():
        date_raw = str(row.iloc[0])[:10]
        if not re.match(r'\d{4}-\d{2}-\d{2}', date_raw): continue
        # 주문건수 = index 4, 주문금액 = index 3, 환불건수 = index 6, 환불금액 = index 5
        orders = to_num(row.iloc[4]) - to_num(row.iloc[6])
        revenue = to_num(row.iloc[3]) - to_num(row.iloc[5])
        result.append({"date": date_raw, "orders": max(0, orders), "revenue": max(0, revenue)})
    return result

def parse_global_orders(fpath):
    if not fpath or not os.path.exists(fpath): return []
    dfs = pd.read_html(fpath, encoding='utf-8', header=0, converters={1: str, 2: str})
    if not dfs: return []
    df = dfs[0].copy()
    # 주문일련번호 기준 중복 제거
    df = df.drop_duplicates(subset=[df.columns[2]], keep='last')
    
    # 글로벌은 건별 리스트임. 날짜별 합산 필요
    # 상품명 컬럼 등에서 브랜드 판별. (보통 EIX... 면 에든버러, 등. 아니면 매입가 합계)
    # 여기서는 날짜별 통합만 수행
    # 입금일시(index 38) 기준으로 그룹핑
    daily_stats = {}
    for _, row in df.iterrows():
        # 입금일시: index 26
        date_raw = str(row.iloc[26])[:10]
        if not re.match(r'\d{4}-\d{2}-\d{2}', date_raw): continue
        # 매입가: index 18
        rev = to_num(row.iloc[18])
        # 스타일넘버: index 9
        brand = "에든버러클럽" if "E" in str(row.iloc[9]).upper() else "커넥트킨록"
        
        key = (date_raw, brand)
        if key not in daily_stats:
            daily_stats[key] = {"orders": 0, "revenue": 0}
        daily_stats[key]["orders"] += 1
        daily_stats[key]["revenue"] += rev
    
    res_c = []
    res_e = []
    for (d, b), v in daily_stats.items():
        if b == "커넥트킨록":
            res_c.append({"date": d, "orders": v["orders"], "revenue": v["revenue"]})
        else:
            res_e.append({"date": d, "orders": v["orders"], "revenue": v["revenue"]})
    return res_c, res_e

def get_latest(pattern):
    files = sorted(glob.glob(os.path.join(BD_DIR, pattern)))
    return files[-1] if files else None

def build_daily_dict(data_list):
    d = {}
    for item in data_list:
        d[item["date"]] = {"orders": item["orders"], "revenue": item["revenue"]}
    return d

def main():
    print("Exporting real sales data...")
    f_m_c = get_latest("일별주문통계_커넥트킨록_*.xls")
    f_m_e = get_latest("일별주문통계_에든버러클럽_*.xls")
    f_c_c = get_latest("29CM_커넥트킨록_*.xlsx")
    f_c_e = get_latest("29CM_에든버러클럽_*.xlsx")
    f_g = get_latest("글로벌주문내역_*.xls")

    m_c = build_daily_dict(parse_musinsa_xls(f_m_c))
    m_e = build_daily_dict(parse_musinsa_xls(f_m_e))
    c_c = build_daily_dict(parse_29cm_report(f_c_c))
    c_e = build_daily_dict(parse_29cm_report(f_c_e))
    
    g_c_list, g_e_list = parse_global_orders(f_g)
    g_c = build_daily_dict(g_c_list)
    g_e = build_daily_dict(g_e_list)

    today = datetime.now()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(13, -1, -1)]

    result = {
        "ok": True,
        "updated_at": datetime.now().isoformat(),
        "data": {
            "dates": dates,
            "total": {"today_revenue": 0, "today_orders": 0, "revenue_change_pct": 0, "daily_revenue": [], "daily_orders": []},
            "connect": {
                "musinsa_revenue": [], "cm29_revenue": [], "global_revenue": [],
                "musinsa_orders": [], "cm29_orders": [], "global_orders": []
            },
            "edinburgh": {
                "musinsa_revenue": [], "cm29_revenue": [], "global_revenue": [],
                "musinsa_orders": [], "cm29_orders": [], "global_orders": []
            }
        }
    }

    tot_rev = []
    tot_ord = []
    
    for d in dates:
        # Connect
        rev_m_c = m_c.get(d, {}).get("revenue", 0)
        ord_m_c = m_c.get(d, {}).get("orders", 0)
        rev_c_c = c_c.get(d, {}).get("revenue", 0)
        ord_c_c = c_c.get(d, {}).get("orders", 0)
        rev_g_c = g_c.get(d, {}).get("revenue", 0)
        ord_g_c = g_c.get(d, {}).get("orders", 0)
        
        result["data"]["connect"]["musinsa_revenue"].append(rev_m_c)
        result["data"]["connect"]["cm29_revenue"].append(rev_c_c)
        result["data"]["connect"]["global_revenue"].append(rev_g_c)
        result["data"]["connect"]["musinsa_orders"].append(ord_m_c)
        result["data"]["connect"]["cm29_orders"].append(ord_c_c)
        result["data"]["connect"]["global_orders"].append(ord_g_c)

        # Edinburgh
        rev_m_e = m_e.get(d, {}).get("revenue", 0)
        ord_m_e = m_e.get(d, {}).get("orders", 0)
        rev_c_e = c_e.get(d, {}).get("revenue", 0)
        ord_c_e = c_e.get(d, {}).get("orders", 0)
        rev_g_e = g_e.get(d, {}).get("revenue", 0)
        ord_g_e = g_e.get(d, {}).get("orders", 0)
        
        result["data"]["edinburgh"]["musinsa_revenue"].append(rev_m_e)
        result["data"]["edinburgh"]["cm29_revenue"].append(rev_c_e)
        result["data"]["edinburgh"]["global_revenue"].append(rev_g_e)
        result["data"]["edinburgh"]["musinsa_orders"].append(ord_m_e)
        result["data"]["edinburgh"]["cm29_orders"].append(ord_c_e)
        result["data"]["edinburgh"]["global_orders"].append(ord_g_e)

        # Total
        tr = rev_m_c + rev_c_c + rev_g_c + rev_m_e + rev_c_e + rev_g_e
        to = ord_m_c + ord_c_c + ord_g_c + ord_m_e + ord_c_e + ord_g_e
        tot_rev.append(tr)
        tot_ord.append(to)

    result["data"]["total"]["daily_revenue"] = tot_rev
    result["data"]["total"]["daily_orders"] = tot_ord
    
    today_idx = -1 # Yesterday if today has no data? Let's just take last
    today_rev = tot_rev[-1]
    yest_rev = tot_rev[-2] if len(tot_rev) > 1 else 1
    
    # If today's data is 0 and yesterday is not 0 (meaning today's file hasn't downloaded yet),
    # we should use yesterday's data as the "latest"
    if today_rev == 0 and yest_rev > 0:
        today_rev = yest_rev
        yest_rev = tot_rev[-3] if len(tot_rev) > 2 else 1
        today_idx = -2
        
    result["data"]["total"]["today_revenue"] = today_rev
    result["data"]["total"]["today_orders"] = tot_ord[today_idx]
    result["data"]["total"]["revenue_change_pct"] = round((today_rev - yest_rev) / (yest_rev or 1) * 100, 1)
    
    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Exported sales data to {OUTPUT_JSON}")

if __name__ == "__main__":
    main()
