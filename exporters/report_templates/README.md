# 리포트 디자인 템플릿 (모던 고딕)

사용자가 승인한 **보고서 디자인**. 다음에 보고서 작성을 요청하면 이 스타일을 응용한다.
(주간 자동 리포트는 만들지 않기로 함 — 대시보드로 매일 체크하므로. 필요할 때만 수동 생성.)

## 디자인 특징
- 폰트: **Pretendard** (`~/Library/Fonts/Pretendard-*.otf`, 이미 설치됨), 폴백 Apple SD Gothic Neo
- 흰 배경 / 넉넉한 여백 / 큰 제목 / 절제된 포인트 컬러(파랑 `#2563eb`)
- 상단 **KPI 카드**, 표는 1위 검정 강조 + **빨간 할인 배지**(`#e11d48`), 가격 우측정렬
- 인사이트는 파란 좌측 라인 카드, 하단 "MD 액션" 블록

## 렌더링 (중요)
- **반드시 Chrome headless로 렌더** — weasyprint로 만들면 macOS 미리보기가 한글 폰트를
  못 읽어 글자가 깨진다. Chrome(Skia/PDF)은 미리보기·아이폰 어디서나 정상.
- 배경색이 나오게 CSS에 `print-color-adjust:exact` 유지.

```bash
# 1) 데이터로 HTML 생성 (build_modern_report.py 안의 데이터/문구 수정)
~/fashion-monitor/.venv/bin/python build_modern_report.py
# 2) Chrome로 PDF 렌더
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
  --no-pdf-header-footer --print-to-pdf=out.pdf "file://$PWD/modern_weekly.html"
```

## 파일
- `modern_report_template.html` — 완성 디자인 참고본 (실제 이번 주 데이터로 채워진 샘플)
- `build_modern_report.py` — 데이터→HTML 생성 스크립트 (문구·데이터만 바꿔 재사용)
- 샘플 결과: `~/fashion-monitor/data/reports/modern_weekly.pdf`
