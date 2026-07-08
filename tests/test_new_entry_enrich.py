"""
신규 진입 상품 상세 파싱 — 색상/소재 추출 테스트.

실제 무신사에서 받아온 샘플(tests/fixtures)로 순수 함수를 검증한다.
네트워크 없이 돌아간다.
"""

import json
import os

from analyzers import new_entry

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_options():
    with open(os.path.join(FIX, "options_4693117.json"), encoding="utf-8") as f:
        return json.load(f)


def _load_material_snippet():
    with open(os.path.join(FIX, "material_snippet_4693117.txt"), encoding="utf-8") as f:
        return f.read()


# ── 색상 ──────────────────────────────────────────────────────────────────────

def test_normalize_color_from_option_code():
    # 'BLK0_BLACK' → '블랙'
    assert new_entry._normalize_color("BLK0_BLACK") == "블랙"

def test_normalize_color_plain_english():
    assert new_entry._normalize_color("WHITE") == "화이트"

def test_normalize_color_already_korean():
    assert new_entry._normalize_color("네이비") == "네이비"

def test_normalize_color_unknown_code_is_dropped():
    # 알 수 없는 코드(BLK0 단독)는 쓰레기값 대신 빈 문자열
    assert new_entry._normalize_color("BLK0") == ""

def test_extract_colors_from_real_options():
    colors = new_entry._extract_colors_from_options(_load_options())
    assert "블랙" in colors
    assert all(isinstance(c, str) and c for c in colors)  # 빈/쓰레기값 없음

def test_extract_colors_empty_input():
    assert new_entry._extract_colors_from_options({}) == []
    assert new_entry._extract_colors_from_options(None) == []


# ── 색상 폴백 (상품명) ─────────────────────────────────────────────────────────

def test_colors_from_name():
    name = "터프 폴로 반팔 티셔츠 블랙 SR123UPS11"
    assert new_entry._colors_from_name(name) == ["블랙"]

def test_colors_from_name_none():
    assert new_entry._colors_from_name("소재 좋은 반팔티") == []


# ── 소재 ──────────────────────────────────────────────────────────────────────

def test_material_from_real_html_snippet():
    assert new_entry._material_from_html(_load_material_snippet()) == "폴리에스터(100)"

def test_material_from_html_empty():
    assert new_entry._material_from_html("") == ""
    assert new_entry._material_from_html("<div>소재 정보 없음</div>") == ""
