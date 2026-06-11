#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import json
import unicodedata
from datetime import datetime, timedelta
import pandas as pd

OUTPUT_JSON = "/Users/jeonjuwon/.gemini/antigravity/scratch/fashion-md-simulator/data/json/sales_real.json"

def to_num(val):
    if pd.isnull(val):
        return 0
    if isinstance(val, (int, float)):
        return val
    s = str(val).replace(',', '').strip()
    if s in ('', 'nan', 'None', '-'):
        return 0
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return 0

def find_excel_file():
    possible_paths = [
        "/Users/jeonjuwon/Library/CloudStorage/OneDrive-개인/바탕 화면/E-BIZ_주간 영업 회의_26년.xlsx",
        "/Users/jeonjuwon/Library/CloudStorage/OneDrive-개인/바탕 화면/E-BIZ_주간 영업 회의_26년.xlsx"
    ]
    for p in possible_paths:
        if os.path.exists(p):
            return p
    
    # Dynamic search fallback
    search_dirs = [
        "/Users/jeonjuwon/Library/CloudStorage/OneDrive-개인/바탕 화면",
        "/Users/jeonjuwon/Library/CloudStorage/OneDrive-개인/바탕 화면",
        "/Users/jeonjuwon/Desktop",
        "/Users/jeonjuwon"
    ]
    for s_dir in search_dirs:
        if os.path.exists(s_dir):
            for root, dirs, files in os.walk(s_dir):
                for f in files:
                    norm_f = unicodedata.normalize('NFC', f)
                    if "주간 영업 회의" in norm_f or "주간영업회의" in norm_f:
                        return os.path.join(root, f)
    raise FileNotFoundError("주간영업회의 Excel 파일을 바탕화면에서 찾을 수 없습니다.")

def find_sheet_name(sheet_names, pattern):
    norm_pattern = unicodedata.normalize('NFC', pattern)
    for name in sheet_names:
        norm_name = unicodedata.normalize('NFC', name)
        if norm_pattern == norm_name:
            return name
    # substring fallback
    for name in sheet_names:
        norm_name = unicodedata.normalize('NFC', name)
        if norm_pattern in norm_name or norm_name in norm_pattern:
            return name
    return None

def parse_sheet_data(excel_path, sheet_name):
    df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
    data = {}
    for r in range(len(df)):
        if df.iloc[r, 0] == '일자':
            for c in range(1, 8):
                dt = df.iloc[r, c]
                if pd.notnull(dt):
                    # Convert to datetime string
                    dt_str = pd.to_datetime(dt).strftime('%Y-%m-%d')
                    val = df.iloc[r + 2, c]
                    data[dt_str] = to_num(val)
    return data

def main():
    print("주간영업회의 엑셀파일에서 매출 데이터 추출 중...")
    try:
        excel_path = find_excel_file()
        print(f"찾은 엑셀 파일: {excel_path}")
    except Exception as e:
        print(f"에러: {e}")
        return

    xl = pd.ExcelFile(excel_path)
    sheet_names = xl.sheet_names

    sheet_map = {
        'musinsa_connect': '무신사(커넥트)',
        'musinsa_edinburgh': '무신사(에든버러)',
        'global_connect': '글로벌(커넥트)',
        'global_edinburgh': '글로벌(에든버러)',
        'cm29_connect': '29CM(커넥트)',
        'cm29_edinburgh': '29CM(에든버러)'
    }

    parsed_data = {}
    for key, pattern in sheet_map.items():
        actual_sheet_name = find_sheet_name(sheet_names, pattern)
        if not actual_sheet_name:
            print(f"경고: 시트 '{pattern}'를 찾을 수 없습니다. 빈 데이터로 대체합니다.")
            parsed_data[key] = {}
        else:
            print(f"시트 파싱 중: {actual_sheet_name}")
            parsed_data[key] = parse_sheet_data(excel_path, actual_sheet_name)

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
        rev_m_c = parsed_data['musinsa_connect'].get(d, 0)
        rev_c_c = parsed_data['cm29_connect'].get(d, 0)
        rev_g_c = parsed_data['global_connect'].get(d, 0)

        # Estimate orders: sales / 75000 (min 1 if sales > 0, else 0)
        ord_m_c = max(1, int(rev_m_c // 75000)) if rev_m_c > 0 else 0
        ord_c_c = max(1, int(rev_c_c // 75000)) if rev_c_c > 0 else 0
        ord_g_c = max(1, int(rev_g_c // 75000)) if rev_g_c > 0 else 0

        result["data"]["connect"]["musinsa_revenue"].append(rev_m_c)
        result["data"]["connect"]["cm29_revenue"].append(rev_c_c)
        result["data"]["connect"]["global_revenue"].append(rev_g_c)
        result["data"]["connect"]["musinsa_orders"].append(ord_m_c)
        result["data"]["connect"]["cm29_orders"].append(ord_c_c)
        result["data"]["connect"]["global_orders"].append(ord_g_c)

        # Edinburgh
        rev_m_e = parsed_data['musinsa_edinburgh'].get(d, 0)
        rev_c_e = parsed_data['cm29_edinburgh'].get(d, 0)
        rev_g_e = parsed_data['global_edinburgh'].get(d, 0)

        ord_m_e = max(1, int(rev_m_e // 75000)) if rev_m_e > 0 else 0
        ord_c_e = max(1, int(rev_c_e // 75000)) if rev_c_e > 0 else 0
        ord_g_e = max(1, int(rev_g_e // 75000)) if rev_g_e > 0 else 0

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

    # Latest day with data index (find first non-zero revenue from the end)
    today_idx = -1
    for i in range(len(tot_rev) - 1, -1, -1):
        if tot_rev[i] > 0:
            today_idx = i
            break

    # If no data at all
    if today_idx == -1:
        today_rev = 0
        today_orders = 0
        yest_rev = 0
    else:
        today_rev = tot_rev[today_idx]
        today_orders = tot_ord[today_idx]
        yest_rev = tot_rev[today_idx - 1] if today_idx > 0 else 0

    result["data"]["total"]["today_revenue"] = today_rev
    result["data"]["total"]["today_orders"] = today_orders
    result["data"]["total"]["revenue_change_pct"] = round((today_rev - yest_rev) / (yest_rev or 1) * 100, 1) if yest_rev > 0 else 0.0

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"성공: 매출 데이터를 {OUTPUT_JSON}에 저장했습니다.")

if __name__ == "__main__":
    main()
