#!/usr/bin/env python3
"""
OnHighGround2 プロジェクト構成ドキュメント Excel 生成スクリプト
"""

from openpyxl import Workbook
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, GradientFill
)
from openpyxl.utils import get_column_letter

# ======= スタイル定義 =======

def border_thin():
    side = Side(style="thin", color="AAAAAA")
    return Border(left=side, right=side, top=side, bottom=side)

def header_fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def apply_header(ws, row, col, value, color="2E5FA3", font_size=10, bold=True):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = Font(name="游ゴシック", bold=bold, color="FFFFFF", size=font_size)
    cell.fill = header_fill(color)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = border_thin()
    return cell

def apply_cell(ws, row, col, value, bold=False, wrap=True, indent=0,
               fill_color=None, font_color="000000", align="left"):
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = Font(name="游ゴシック", bold=bold, size=10, color=font_color)
    cell.alignment = Alignment(
        horizontal=align, vertical="top", wrap_text=wrap, indent=indent
    )
    if fill_color:
        cell.fill = PatternFill("solid", fgColor=fill_color)
    cell.border = border_thin()
    return cell

def set_col_widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

def freeze(ws, cell="A2"):
    ws.freeze_panes = cell

# ======= シート1: プロジェクト概要 =======

def sheet_overview(wb):
    ws = wb.create_sheet("① プロジェクト概要")

    ws.merge_cells("A1:E1")
    title = ws.cell(1, 1, "OnHighGround2 — 災害避難ナビゲーションシステム プロジェクト概要")
    title.font = Font(name="游ゴシック", bold=True, size=14, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="1A3A5C")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    # コンセプト
    ws.merge_cells("A3:E3")
    ws.cell(3, 1, "■ コンセプト").font = Font(name="游ゴシック", bold=True, size=11, color="2E5FA3")

    rows = [
        ("目的", "災害時に「危険エリア」だけでなく「安全な場所への避難ルート」をガイドする"),
        ("基本思想", "danger → safe location → escape route の流れで避難行動を支援"),
        ("対象ハザード", "津波 / 高潮 / 洪水 / 土砂災害（モジュール式・地域ごとに有効化可能）"),
        ("対象地域", "現在：関東地方（東京・神奈川・千葉）"),
        ("ライセンス", "オープンソース志向 / OSS・オープンデータを最大限活用"),
    ]
    for i, (k, v) in enumerate(rows, 4):
        apply_cell(ws, i, 1, k, bold=True, fill_color="EBF2FF", align="center")
        ws.merge_cells(f"B{i}:E{i}")
        apply_cell(ws, i, 2, v)

    # 技術スタック
    ws.merge_cells("A10:E10")
    ws.cell(10, 1, "■ 技術スタック").font = Font(name="游ゴシック", bold=True, size=11, color="2E5FA3")

    headers = ["レイヤー", "技術", "バージョン", "役割", "備考"]
    for i, h in enumerate(headers, 1):
        apply_header(ws, 11, i, h)

    stack = [
        ("地図ライブラリ", "Leaflet.js", "1.9.4", "フロントエンド地図表示", "OpenStreetMap タイル利用"),
        ("ルーティング UI", "Leaflet Routing Machine", "-", "ルート描画・操作", "OSRM と連携"),
        ("ルーティングエンジン", "OSRM", "latest", "車・徒歩ルート計算", "Docker コンテナ × 2"),
        ("バックエンド", "FastAPI", "0.104.1", "REST API サーバー", "Python 3.11"),
        ("非同期サーバー", "Uvicorn", "0.24.0", "ASGI サーバー", "-"),
        ("GIS ライブラリ", "Rasterio", "1.4.3", "標高 GeoTIFF 読み込み", "GDAL ベース"),
        ("数値計算", "NumPy", ">=1.26,<2", "標高データ処理", "-"),
        ("データ検証", "Pydantic", "2.5.0", "API スキーマ定義", "-"),
        ("Webサーバー", "Nginx (alpine)", "latest", "静的配信・リバースプロキシ", "ポート 8080"),
        ("コンテナ", "Docker Compose", "-", "全サービス統合管理", "4コンテナ構成"),
        ("タイル生成", "tippecanoe", "-", "GeoJSON → MBTiles 変換", "別途インストール要"),
        ("道路データ", "OpenStreetMap (PBF)", "-", "ルーティング用道路網", "Geofabrik 配布"),
        ("標高データ", "国土地理院 DEM", "5m メッシュ", "標高計算・避難先評価", "GeoTIFF 形式"),
    ]
    for i, row in enumerate(stack, 12):
        bg = "F5F9FF" if i % 2 == 0 else "FFFFFF"
        for j, val in enumerate(row, 1):
            apply_cell(ws, i, j, val, fill_color=bg)

    set_col_widths(ws, [20, 30, 16, 28, 30])
    freeze(ws, "A2")

# ======= シート2: ディレクトリ構成 =======

def sheet_directory(wb):
    ws = wb.create_sheet("② ディレクトリ構成")

    ws.merge_cells("A1:F1")
    title = ws.cell(1, 1, "ディレクトリ構成 — 全ファイル・フォルダの役割")
    title.font = Font(name="游ゴシック", bold=True, size=13, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="1A3A5C")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    headers = ["パス", "種別", "役割・説明", "Git 管理", "対応 MD ファイル", "備考"]
    for i, h in enumerate(headers, 1):
        apply_header(ws, 2, i, h)

    entries = [
        # (パス, 種別, 説明, Git管理, 対応MD, 備考)
        ("/ (ルート)", "DIR", "プロジェクトルート", "✓", "-", "-"),
        ("README.md", "MD", "プロジェクト全体の説明・セットアップ手順", "✓", "README.md", "最初に読むべき"),
        ("QUICKSTART.md", "MD", "5分で起動するためのクイックスタートガイド", "✓", "QUICKSTART.md", "初回セットアップ向け"),
        ("DATA_REQUIREMENTS.md", "MD", "必要な外部データの種類・入手先・配置場所", "✓", "DATA_REQUIREMENTS.md", "データ準備の手順書"),
        ("CLAUDE.md", "MD", "Claude Code 向けプロジェクト指示", "✓", "CLAUDE.md", "AI アシスタント向け"),
        ("AI_CONTEXT.md", "MD", "AI アシスタント向けアーキテクチャ説明", "✓", "AI_CONTEXT.md", "開発補助用"),
        ("VPS-README.md", "MD", "VPS 本番環境での運用手順・設定メモ", "✓", "VPS-README.md", "本番デプロイ向け"),
        ("docker-compose.yml", "YAML", "全 Docker サービスの定義（4コンテナ）", "✓", "README.md / QUICKSTART.md", "起動コマンド: docker compose up"),
        ("nginx.conf", "CONF", "Nginx リバースプロキシ設定", "✓", "-", "ポート 8080 でリクエスト受付"),
        ("frontend/", "DIR", "Web フロントエンド（SPA）", "✓", "README.md", "-"),
        ("frontend/index.html", "HTML", "地図 UI のメインファイル（単一ファイル SPA）", "✓", "README.md", "Leaflet.js + Leaflet Routing Machine"),
        ("frontend/hazard/", "DIR", "【legacy 互換先】frontend が暫定参照する同期先。正本ではなく、publish による一時配置先。", "✗ (gitignore)", "README.md / scripts/README.md", "縮退対象"),
        ("backend/", "DIR", "FastAPI バックエンド", "✓", "README.md / AI_CONTEXT.md", "-"),
        ("backend/main.py", "PY", "FastAPI メインアプリ（API エンドポイント定義）", "✓", "-", "526行"),
        ("backend/elevation_service.py", "PY", "標高データ処理サービス（rasterio 使用）", "✓", "-", "-"),
        ("backend/app.properties", "CONF", "アプリケーション設定（DEM パス・CORS 等）", "✓", "-", "Java .properties 形式"),
        ("backend/requirements.txt", "TXT", "Python 依存パッケージ一覧", "✓", "-", "-"),
        ("backend/Dockerfile", "DOC", "バックエンド Docker イメージ定義", "✓", "-", "Python 3.11-slim ベース"),
        ("scripts/", "DIR", "ユーティリティスクリプト", "✓", "scripts/README.md", "-"),
        ("scripts/build_tiles.py", "PY", "GeoJSON → MBTiles ベクタータイル変換スクリプト", "✓", "scripts/README.md", "tippecanoe 必須"),
        ("scripts/README.md", "MD", "タイル生成パイプラインの詳細説明", "✓", "scripts/README.md", "-"),
        ("data_processing/", "DIR", "DEM データ変換スクリプト", "✓", "DATA_REQUIREMENTS.md", "-"),
        ("data_processing/convert_dem.py", "PY", "国土地理院 XML → GeoTIFF 変換スクリプト", "✓", "DATA_REQUIREMENTS.md", "rasterio / numpy 使用"),
        ("data_lake/", "DIR", "データ基盤の正本。raw / normalized / validated / tiles / registry / logs を含む。", "一部 ✓", "README.md / DATA_REQUIREMENTS.md", "現行正本"),
        ("data_lake/validated/tokyo/dem/elevation.tif", "TIF", "標高 GeoTIFF の canonical 参照先", "✗ (gitignore)", "DATA_REQUIREMENTS.md", "backend が優先して参照"),
        ("data_lake/validated/tokyo/shelter/tokyo_shelter.geojson", "GeoJSON", "避難所データの canonical 参照先", "✗ (gitignore)", "DATA_REQUIREMENTS.md", "backend が優先して参照"),
        ("data_lake/raw/tokyo/osm/kanto-260214.osm.pbf", "PBF", "OSM 道路ネットワーク元データの canonical 参照先", "✗ (gitignore)", "DATA_REQUIREMENTS.md", "数百MB〜1GB"),
        ("data_lake/validated/tokyo/osm/driving/", "DIR", "OSRM 車ルーティング処理済みデータ", "✗ (gitignore)", "DATA_REQUIREMENTS.md", "validated 正本"),
        ("data_lake/validated/tokyo/osm/walking/", "DIR", "OSRM 徒歩ルーティング処理済みデータ", "✗ (gitignore)", "DATA_REQUIREMENTS.md", "validated 正本"),
        ("data_lake/validated/tokyo/", "DIR", "build_tiles.py の正規入力元", "✗ (gitignore)", "scripts/README.md", "validated 正本"),
        ("data_lake/tiles/tokyo/", "DIR", "生成済みベクタータイル（MBTiles）の正本", "✗ (gitignore)", "scripts/README.md", "frontend / 配信用正本"),
        ("data/", "DIR", "legacy データ置き場", "✗ (gitignore)", "DATA_REQUIREMENTS.md", "縮退対象"),
        ("tiles/", "DIR", "legacy MBTiles 置き場", "✗ (gitignore)", "scripts/README.md", "縮退対象"),
        ("国土地理院避難所データ/", "DIR", "緊急避難場所 CSV データ", "一部 ✓", "DATA_REQUIREMENTS.md", "国土地理院配布"),
    ]

    for i, row in enumerate(entries, 3):
        bg = "F5F9FF" if i % 2 == 1 else "FFFFFF"
        # Git管理列の色付け
        git_color = bg
        if row[3] == "✗ (gitignore)":
            git_color = "FFF3CD"
        for j, val in enumerate(row, 1):
            c = apply_cell(ws, i, j, val, fill_color=bg if j != 4 else git_color)
            if j == 4 and "✗" in val:
                c.font = Font(name="游ゴシック", size=10, color="C55A11")
        ws.row_dimensions[i].height = 18

    set_col_widths(ws, [42, 9, 42, 14, 36, 34])
    freeze(ws, "A3")

# ======= シート3: 事前準備データ =======

def sheet_data_requirements(wb):
    ws = wb.create_sheet("③ 事前準備データ")

    ws.merge_cells("A1:G1")
    title = ws.cell(1, 1, "事前準備データ — 起動前に手動で配置が必要なファイル一覧")
    title.font = Font(name="游ゴシック", bold=True, size=13, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="1A3A5C")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # 注記
    ws.merge_cells("A2:G2")
    note = ws.cell(2, 1, "⚠️  現在の正本は data_lake/ です。legacy の data/ は互換確認用で、以下は canonical 配置先を基準に記載しています。")
    note.font = Font(name="游ゴシック", bold=True, size=10, color="7B2A00")
    note.fill = PatternFill("solid", fgColor="FFF3CD")
    note.alignment = Alignment(wrap_text=True)

    headers = ["優先度", "ファイル / ディレクトリ", "用途", "入手先", "変換手順", "ファイルサイズ目安", "対応 MD"]
    for i, h in enumerate(headers, 1):
        apply_header(ws, 3, i, h)

    data = [
        (
            "★ 必須",
            "data_lake/raw/tokyo/osm/kanto-260214.osm.pbf",
            "OSRM 道路ルーティング用 OSM データ\n（車・徒歩ルート計算の基盤）",
            "Geofabrik: download.geofabrik.de\n→ Asia > Japan > Kanto\nまたは BBBike.org でカスタム抽出",
            "ダウンロードしてそのまま配置\n（変換不要）\ndocker compose up 時に OSRM が自動前処理",
            "400MB〜1GB",
            "DATA_REQUIREMENTS.md\nQUICKSTART.md",
        ),
        (
            "★ 必須",
            "data_lake/validated/tokyo/dem/elevation.tif",
            "標高計算・避難先評価用 DEM\n（標高差フィルタ・プロファイル表示）",
            "国土地理院 基盤地図情報ダウンロードサービス\nhttps://fgd.gsi.go.jp/download/\n→ 数値標高モデル 5m メッシュ（DEM5A/B）推奨",
            "1. 対象地域の XML ファイルを複数ダウンロード\n2. 以下で GeoTIFF に変換・マージ:\n   python data_processing/convert_dem.py \\\n     /path/to/xml/dir data_lake/validated/tokyo/dem/elevation.tif --merge",
            "数百MB（関東全域）",
            "DATA_REQUIREMENTS.md",
        ),
        (
            "★ 必須",
            "data_lake/validated/tokyo/tsunami/\n*.geojson\n(互換同期先: frontend/hazard/)",
            "validated を経由して配信される津波データ\n（津波浸水想定区域の表示）",
            "国土数値情報ダウンロードサービス\nhttps://nlftp.mlit.go.jp/ksj/\n→ A40: 津波浸水想定\n（GML または Shapefile 形式）",
            "1. 国土数値情報から A40 データをダウンロード\n2. GeoJSON に変換\n3. data_lake/normalized または validated に配置\n4. 必要なら publish で frontend/hazard に同期",
            "数十MB / ファイル",
            "DATA_REQUIREMENTS.md\nscripts/README.md",
        ),
        (
            "推奨",
            "data_lake/validated/tokyo/shelter/\n（GeoJSON 正本）",
            "緊急避難場所の表示・検索\n（/api/emergency-shelters エンドポイント）",
            "国土地理院 緊急避難場所データ\nhttps://hinanbasho.gsi.go.jp/\nまたは各自治体のオープンデータポータル",
            "download / normalize / validate を通して data_lake/validated/tokyo/shelter に配置",
            "小〜中",
            "DATA_REQUIREMENTS.md",
        ),
        (
            "オプション",
            "data_lake/validated/tokyo/\n**/*.geojson",
            "タイル生成（MBTiles）の正規入力ソース",
            "normalize / validate を通した GeoJSON を配置",
            "python scripts/build_tiles.py\n# デフォルトで data_lake/validated/tokyo を参照",
            "validated と同じ",
            "scripts/README.md",
        ),
    ]

    for i, row in enumerate(data, 4):
        bg = "F5F9FF" if i % 2 == 0 else "FFFFFF"
        priority_colors = {
            "★ 必須": ("FFE6E6", "C00000"),
            "推奨": ("FFF3CD", "7B4A00"),
            "オプション": ("E8F5E9", "2E6B2E"),
        }
        pc, fc = priority_colors.get(row[0], (bg, "000000"))
        apply_cell(ws, i, 1, row[0], bold=True, fill_color=pc, font_color=fc, align="center")
        for j in range(1, 7):
            apply_cell(ws, i, j + 1, row[j], fill_color=bg)
        ws.row_dimensions[i].height = 80

    set_col_widths(ws, [11, 34, 32, 38, 46, 16, 24])
    freeze(ws, "A4")

# ======= シート4: システム起動手順 =======

def sheet_startup(wb):
    ws = wb.create_sheet("④ 起動・操作手順")

    ws.merge_cells("A1:D1")
    title = ws.cell(1, 1, "起動・操作手順 — 初回セットアップから日常操作まで")
    title.font = Font(name="游ゴシック", bold=True, size=13, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="1A3A5C")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    headers = ["ステップ", "操作内容", "コマンド / 手順", "参照 MD"]
    for i, h in enumerate(headers, 1):
        apply_header(ws, 2, i, h)

    steps = [
        # 初回セットアップ
        ("【初回】1", "リポジトリをクローン",
         "git clone https://github.com/brokendish/OnHighGround2.git\ncd OnHighGround2",
         "QUICKSTART.md"),
        ("【初回】2", "OSM データを配置\n（★必須）",
         "# Geofabrik から関東地方 PBF をダウンロード\nmkdir -p data_lake/raw/tokyo/osm\nmv kanto-260214.osm.pbf data_lake/raw/tokyo/osm/",
         "DATA_REQUIREMENTS.md"),
        ("【初回】3", "DEM 標高データを変換・配置\n（★必須）",
         "# 国土地理院 XML をダウンロード後\npython data_processing/convert_dem.py \\\n  /path/to/xml/dir data_lake/validated/tokyo/dem/elevation.tif --merge",
         "DATA_REQUIREMENTS.md"),
        ("【初回】4", "ハザード GeoJSON を配置\n（★必須）",
         "# 既存データを data_lake へ集約\n./init_data_lake.sh\n./scripts/migrate/migrate_to_data_lake.sh",
         "DATA_REQUIREMENTS.md"),
        ("【初回】5", "Docker Compose でサービス起動\n（初回は OSRM 前処理で時間がかかる）",
         "docker compose up -d\n# OSRM 初回処理: 数分〜数十分",
         "QUICKSTART.md"),
        ("【初回】6", "ブラウザで動作確認",
         "http://localhost:8080",
         "QUICKSTART.md"),
        # 日常操作
        ("【日常】7", "サービス起動",
         "docker compose up -d",
         "README.md"),
        ("【日常】8", "サービス停止",
         "docker compose down",
         "README.md"),
        ("【日常】9", "ログ確認",
         "docker compose logs -f backend\ndocker compose logs -f osrm-driving",
         "README.md"),
        ("【日常】10", "バックエンド API ヘルスチェック",
         "curl http://localhost:8080/api/health",
         "-"),
        # タイル生成
        ("【タイル】11", "ハザード GeoJSON からベクタータイル生成\n（tippecanoe 要インストール）",
         "# macOS\nbrew install tippecanoe\n# 生成実行\npython scripts/build_tiles.py",
         "scripts/README.md"),
        ("【タイル】12", "特定の入力ディレクトリを指定してタイル生成",
         "python scripts/build_tiles.py --input data_lake/validated/tokyo/tsunami --minzoom 8 --maxzoom 16",
         "scripts/README.md"),
        ("【タイル】13", "タイル生成のドライラン（実行確認）",
         "python scripts/build_tiles.py --dry-run",
         "scripts/README.md"),
        # VPS デプロイ
        ("【VPS】14", "本番環境 VPS へのデプロイ",
         "# VPS-README.md を参照",
         "VPS-README.md"),
    ]

    for i, (step, op, cmd, md) in enumerate(steps, 3):
        bg = "FFFFFF"
        if step.startswith("【初回】"):
            bg = "EBF2FF"
        elif step.startswith("【タイル】"):
            bg = "E8F5E9"
        elif step.startswith("【VPS】"):
            bg = "FFF3CD"
        apply_cell(ws, i, 1, step, bold=True, fill_color=bg, align="center")
        apply_cell(ws, i, 2, op, fill_color=bg)
        apply_cell(ws, i, 3, cmd, fill_color="F8F8F8")
        ws.cell(i, 3).font = Font(name="Courier New", size=9, color="1A3A5C")
        apply_cell(ws, i, 4, md, fill_color=bg, align="center")
        ws.row_dimensions[i].height = 50

    set_col_widths(ws, [14, 28, 58, 24])
    freeze(ws, "A3")

# ======= シート5: ハザードデータ =======

def sheet_hazard(wb):
    ws = wb.create_sheet("⑤ ハザードデータ詳細")

    ws.merge_cells("A1:F1")
    title = ws.cell(1, 1, "ハザードデータ — 種類・格納場所・入手方法・フロントエンド連携")
    title.font = Font(name="游ゴシック", bold=True, size=13, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="1A3A5C")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    headers = ["ハザード種別", "現状", "GeoJSON ファイル名", "格納ディレクトリ", "データソース", "入手・変換方法"]
    for i, h in enumerate(headers, 1):
        apply_header(ws, 2, i, h)

    hazards = [
        ("津波浸水想定\n（東京都）", "実装済み ✓",
         "tsunami_tokyo.geojson",
         "data_lake/validated/tokyo/tsunami/\n(互換同期先: frontend/hazard/)",
         "国土数値情報\nA40: 津波浸水想定\n（東京都）",
         "1. MLIT 国土数値情報からダウンロード\n2. ogr2ogr または QGIS で GeoJSON 変換\n3. validated に配置\n4. 必要なら publish で同期"),
        ("津波浸水想定\n（神奈川県）", "実装済み ✓",
         "tsunami_kanagawa.geojson",
         "data_lake/validated/tokyo/tsunami/\n(互換同期先: frontend/hazard/)",
         "国土数値情報\nA40: 津波浸水想定\n（神奈川県）",
         "同上（神奈川県分）"),
        ("津波浸水想定\n（千葉県）", "実装済み ✓",
         "tsunami_chiba.geojson",
         "data_lake/validated/tokyo/tsunami/\n(互換同期先: frontend/hazard/)",
         "国土数値情報\nA40: 津波浸水想定\n（千葉県）",
         "同上（千葉県分）"),
        ("洪水浸水想定", "未実装 (将来対応)",
         "flood_{prefecture}.geojson",
         "data_lake/validated/tokyo/flood/\ndata_lake/tiles/tokyo/flood/",
         "国土数値情報\nA31: 洪水浸水想定区域",
         "同様の手順で GeoJSON に変換して配置\nフロントエンドのトグル追加が必要"),
        ("高潮浸水想定", "未実装 (将来対応)",
         "storm_surge_{prefecture}.geojson",
         "data_lake/validated/tokyo/storm_surge/\ndata_lake/tiles/tokyo/storm_surge/",
         "国土数値情報\nA35: 高潮浸水想定区域",
         "同様の手順で GeoJSON に変換して配置"),
        ("土砂災害警戒区域", "未実装 (将来対応)",
         "landslide_{prefecture}.geojson",
         "data_lake/validated/tokyo/urban_flood/\ndata_lake/tiles/tokyo/urban_flood/",
         "国土数値情報\nA33: 土砂災害警戒区域",
         "同様の手順で GeoJSON に変換して配置"),
    ]

    status_colors = {
        "実装済み ✓": ("E8F5E9", "2E6B2E"),
        "未実装 (将来対応)": ("F5F5F5", "888888"),
    }

    for i, row in enumerate(hazards, 3):
        bg = "F5F9FF" if i % 2 == 1 else "FFFFFF"
        apply_cell(ws, i, 1, row[0], bold=True, fill_color=bg)
        sc, fc = status_colors.get(row[1].split(" ✓")[0] + (" ✓" if "✓" in row[1] else ""), (bg, "000000"))
        apply_cell(ws, i, 2, row[1], fill_color=sc, font_color=fc, align="center", bold=True)
        for j in range(2, 6):
            apply_cell(ws, i, j + 1, row[j], fill_color=bg)
        ws.row_dimensions[i].height = 70

    # タイル化 現在地と将来方針
    ws.merge_cells("A10:F10")
    tile_note = ws.cell(10, 1,
        "【タイル化 現在地と方針】"
        " 現在の正本は data_lake/validated から生成される data_lake/tiles です。"
        " frontend/hazard/ は移行期間の互換同期先で、将来的には data_lake/tiles への直接配信へ寄せます。"
    )
    tile_note.font = Font(name="游ゴシック", size=10, bold=False, color="1A3A5C")
    tile_note.fill = PatternFill("solid", fgColor="EBF2FF")
    tile_note.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[10].height = 40

    # nginx 配信設定の説明
    ws.merge_cells("A12:F12")
    ws.cell(12, 1, "■ nginx による配信設定").font = Font(name="游ゴシック", bold=True, size=11, color="2E5FA3")

    ws.merge_cells("A13:F13")
    nginx_note = ws.cell(13, 1,
        "frontend/hazard/*.geojson は互換用途として nginx によって /hazard/ パスで静的配信されます。\n"
        "Content-Type: application/geo+json\n"
        "CORS: Access-Control-Allow-Origin: * (全許可)\n"
        "正本は data_lake/tiles/ で、frontend/hazard は publish による一時同期先です。"
    )
    nginx_note.font = Font(name="游ゴシック", size=10)
    nginx_note.fill = PatternFill("solid", fgColor="F0F8FF")
    nginx_note.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[13].height = 60

    set_col_widths(ws, [20, 16, 34, 34, 28, 46])
    freeze(ws, "A3")

# ======= シート6: データフロー =======

def sheet_dataflow(wb):
    ws = wb.create_sheet("⑥ データフロー")

    ws.merge_cells("A1:G1")
    title = ws.cell(1, 1, "データフロー — 外部データ入手からシステム稼働・タイル配信まで")
    title.font = Font(name="游ゴシック", bold=True, size=13, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="1A3A5C")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    headers = ["データ種別", "① 入手元（外部）", "② 変換・処理", "③ 配置先（ローカル）",
               "④ 読み込みコンポーネント", "⑤ 提供機能", "状態"]
    for i, h in enumerate(headers, 1):
        apply_header(ws, 2, i, h)

    arrow = "→"

    flows = [
        (
            "道路ネットワーク\n(OSM PBF)",
            "Geofabrik\ndownload.geofabrik.de\n関東地方 PBF",
            "変換不要\n（配置のみ）\ndocker compose up 時に\nosrm-extract → osrm-partition\n→ osrm-customize を自動実行",
            f"data_lake/raw/tokyo/osm/kanto-260214.osm.pbf\n{arrow}\ndata_lake/validated/tokyo/osm/driving/\ndata_lake/validated/tokyo/osm/walking/",
            "OSRM コンテナ\n(osrm-driving:5000)\n(osrm-walking:5001)",
            "車・徒歩の\nルート計算\n（nginx 経由でフロントに提供）",
            "稼働中 ✓",
        ),
        (
            "標高データ\n(DEM GeoTIFF)",
            "国土地理院\n基盤地図情報\n5m メッシュ DEM\n(XML 形式)",
            "data_processing/convert_dem.py\n--merge オプションで\n複数 XML を結合し\nGeoTIFF に変換",
            f"data_lake/validated/tokyo/dem/elevation.tif",
            "backend\n(elevation_service.py\n/ rasterio)",
            "標高値取得 API\n避難先標高フィルタ\n標高プロファイル API",
            "稼働中 ✓",
        ),
        (
            "ハザード GeoJSON\n【フロント描画用】\n(津波浸水想定区域)",
            "国土数値情報\nnlftp.mlit.go.jp\nA40: 津波浸水想定\n(GML / Shapefile)",
            "QGIS または ogr2ogr で\nGeoJSON に変換\nEPSG:4326 (WGS84) を確認",
            f"data_lake/validated/tokyo/tsunami/\n*.geojson\n(互換同期先: frontend/hazard/)",
            "tile_build / publish\n↓\nnginx 互換配信 または\n将来のタイル配信",
            "地図上への\nハザードレイヤー\n描画・表示",
            "稼働中 ✓",
        ),
        (
            "ハザード GeoJSON\n【タイル生成用】\n(正規ソース)",
            "normalize / validate を通過した GeoJSON",
            "build_tiles.py が validated を再帰走査",
            f"data_lake/validated/tokyo/\n**/*.geojson",
            "scripts/build_tiles.py\n(tippecanoe)",
            "→ data_lake/tiles/**/*.mbtiles\n現在の配信正本",
            "手動実行 △\n（将来自動化）",
        ),
        (
            "ベクタータイル\n(MBTiles)",
            "上記\ndata_lake/validated/tokyo/\nの GeoJSON",
            "scripts/build_tiles.py\n--input data_lake/validated/tokyo\n--minzoom 5 --maxzoom 14",
            f"data_lake/tiles/tokyo/\n<hazard>/*.mbtiles",
            "【将来】\nPMTiles\nまたは Martin\nタイルサーバー",
            "【将来】\n高パフォーマンスな\nベクタータイル配信\n（大規模・本番向け）",
            "未実装\n（将来対応）",
        ),
        (
            "緊急避難場所\n(GeoJSON / CSV)",
            "国土地理院\n緊急避難場所データ\nhinanbasho.gsi.go.jp\nまたは各自治体",
            "download / normalize / validate を通過\nbackend は validated を優先",
            f"data_lake/validated/tokyo/shelter/\nlegacy: 国土地理院避難所データ/",
            "backend\n(main.py / startup)\n起動時に全件メモリ読込",
            "避難場所一覧 API\n(/api/emergency-shelters)\nバウンディングボックス\nフィルタ対応",
            "稼働中 ✓",
        ),
    ]

    status_colors = {
        "稼働中 ✓":    ("E8F5E9", "2E6B2E"),
        "手動実行 △\n（将来自動化）": ("FFF3CD", "7B4A00"),
        "未実装\n（将来対応）": ("F5F5F5", "888888"),
    }

    for i, row in enumerate(flows, 3):
        bg = "F5F9FF" if i % 2 == 1 else "FFFFFF"
        for j, val in enumerate(row[:-1], 1):
            c = apply_cell(ws, i, j, val, fill_color=bg)
            # ③ 配置先列は Courier New
            if j == 4:
                c.font = Font(name="Courier New", size=9, color="1A3A5C")
        # 状態列
        sc, fc = status_colors.get(row[-1], (bg, "000000"))
        apply_cell(ws, i, 7, row[-1], fill_color=sc, font_color=fc, align="center", bold=True)
        ws.row_dimensions[i].height = 80

    # 凡例
    ws.merge_cells("A10:G10")
    ws.cell(10, 1, "■ フロー概念図").font = Font(name="游ゴシック", bold=True, size=11, color="2E5FA3")

    ws.merge_cells("A11:G11")
    diagram = ws.cell(11, 1,
        "外部データ入手 → ローカル変換・配置 → Docker サービス起動 → ブラウザでアクセス\n\n"
        "  [Geofabrik PBF] ─→ data_lake/raw/tokyo/osm/ ─→ data_lake/validated/tokyo/osm/ ─→ OSRM ─→ ルート表示\n"
        "  [国土地理院 DEM XML] → 変換 → data_lake/validated/tokyo/dem/ ─→ backend(FastAPI) ─→ /api/elevation 等\n"
        "  [ハザード元データ] → raw/normalized/validated ─→ build_tiles.py ─→ data_lake/tiles/ ─→ [互換] frontend/hazard または [将来] タイル配信\n"
        "  [避難所データ] ─────────→ data_lake/validated/tokyo/shelter/ ─→ backend → /api/shelters → 避難場所表示"
    )
    diagram.font = Font(name="Courier New", size=9, color="1A3A5C")
    diagram.fill = PatternFill("solid", fgColor="F8F8F8")
    diagram.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[11].height = 100

    set_col_widths(ws, [18, 22, 30, 34, 22, 22, 14])
    freeze(ws, "A3")


# ======= シート7: API エンドポイント =======

def sheet_api(wb):
    ws = wb.create_sheet("⑦ API エンドポイント")

    ws.merge_cells("A1:F1")
    title = ws.cell(1, 1, "バックエンド API エンドポイント一覧 (FastAPI / backend/main.py)")
    title.font = Font(name="游ゴシック", bold=True, size=13, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="1A3A5C")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    headers = ["メソッド", "パス", "説明", "主なパラメータ", "レスポンス概要", "用途"]
    for i, h in enumerate(headers, 1):
        apply_header(ws, 2, i, h)

    method_colors = {
        "GET": ("D4EDDA", "155724"),
        "POST": ("CCE5FF", "004085"),
    }

    endpoints = [
        ("GET", "/", "API ルート情報", "-", "name, version, endpoints リスト", "生存確認"),
        ("GET", "/health", "ヘルスチェック", "-", "status, elevation_data, shelter_count", "監視・動作確認"),
        ("GET", "/api/elevation",
         "指定座標の標高値を取得",
         "lat: 緯度 (float)\nlon: 経度 (float)",
         "elevation_m (float)",
         "地点の標高確認"),
        ("POST", "/api/evacuation",
         "避難目的地候補を検索\n（標高・距離フィルタ付き）",
         "lat, lon: 現在地\nmode: driving/walking\nmax_distance_km: 最大距離\nmin_elevation_diff: 最小標高差",
         "candidates リスト\n（name, lat, lon, elevation, distance）",
         "避難先探索（メイン機能）"),
        ("POST", "/api/elevation-profile",
         "2点間の標高プロファイルを取得",
         "start: {lat, lon}\nend: {lat, lon}\nsteps: サンプル数",
         "points リスト\n（距離, 標高, 座標）",
         "ルート沿いの標高グラフ表示"),
        ("GET", "/api/emergency-shelters",
         "緊急避難場所一覧を取得\n（バウンディングボックスフィルタ対応）",
         "min_lat, max_lat\nmin_lon, max_lon\n（省略時: 全件）",
         "shelters リスト\n（name, address, lat, lon, type）",
         "避難場所マーカー表示"),
        ("GET", "/api/stats",
         "システム統計情報",
         "-",
         "elevation_data_loaded\nshelter_count, memory_usage",
         "管理・デバッグ用"),
    ]

    for i, (method, path, desc, params, resp, usage) in enumerate(endpoints, 3):
        mc, fc = method_colors.get(method, ("FFFFFF", "000000"))
        apply_cell(ws, i, 1, method, bold=True, fill_color=mc, font_color=fc, align="center")
        c = apply_cell(ws, i, 2, path)
        c.font = Font(name="Courier New", size=9, bold=True, color="1A3A5C")
        for j, val in enumerate([desc, params, resp, usage], 3):
            apply_cell(ws, i, j, val)
        ws.row_dimensions[i].height = 50

    # アクセス URL
    ws.merge_cells("A11:F11")
    ws.cell(11, 1, "■ アクセス URL").font = Font(name="游ゴシック", bold=True, size=11, color="2E5FA3")

    ws.merge_cells("A12:F12")
    url_note = ws.cell(12, 1,
        "ローカル開発: http://localhost:8080/api/{endpoint}\n"
        "直接バックエンド: http://localhost:8000/api/{endpoint}\n"
        "nginx プロキシ: /api/ → backend:8000/api/ （CORS 解決済み）\n"
        "OSRM プロキシ: /osrm/driving/route/v1 → osrm-driving:5000"
    )
    url_note.font = Font(name="游ゴシック", size=10)
    url_note.fill = PatternFill("solid", fgColor="F0F8FF")
    url_note.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[12].height = 60

    set_col_widths(ws, [9, 30, 28, 34, 34, 20])
    freeze(ws, "A3")

# ======= シート8: MD ファイル対応表 =======

def sheet_md_mapping(wb):
    ws = wb.create_sheet("⑧ MDファイル対応表")

    ws.merge_cells("A1:G1")
    title = ws.cell(1, 1, "MD ファイル対応表 — 各 Markdown ファイルの役割・対象者・掲載内容")
    title.font = Font(name="游ゴシック", bold=True, size=13, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="1A3A5C")
    title.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    headers = ["MD ファイル", "主な対象者", "掲載トピック", "プロジェクト概要", "ディレクトリ構成",
               "データ準備", "起動手順 / タイル生成"]
    for i, h in enumerate(headers, 1):
        apply_header(ws, 2, i, h)

    md_files = [
        ("README.md",
         "開発者・新規参加者",
         "・プロジェクト概要\n・システム構成図\n・Docker 起動手順\n・主要ファイル説明\n・よくある質問",
         "◎ 詳細あり", "△ 概要のみ", "△ 概要のみ", "◎ 詳細あり"),
        ("QUICKSTART.md",
         "初回セットアップ者",
         "・5分で起動するための手順\n・必要データの最小セット\n・初回エラー対処",
         "○ 簡易", "✕ なし", "○ 最小限", "◎ 手順あり"),
        ("DATA_REQUIREMENTS.md",
         "データ管理者\nGIS 担当者",
         "・必要な外部データ 3種の詳細\n・入手先 URL・ダウンロード方法\n・変換コマンド\n・ディレクトリ配置場所",
         "✕ なし", "○ データ関連のみ", "◎ 詳細あり", "△ 変換手順のみ"),
        ("scripts/README.md",
         "タイル生成担当者\nGIS エンジニア",
         "・build_tiles.py の使い方\n・tippecanoe インストール方法\n・ディレクトリ構成\n・将来のタイル構成",
         "✕ なし", "○ タイル関連のみ", "△ GeoJSON 配置のみ", "◎ タイル生成詳細"),
        ("VPS-README.md",
         "インフラエンジニア\nサーバー管理者",
         "・VPS 本番環境構築手順\n・nginx 本番設定\n・SSL/TLS 設定\n・Docker 本番運用メモ",
         "✕ なし", "✕ なし", "✕ なし", "○ 本番デプロイ"),
        ("CLAUDE.md",
         "Claude AI アシスタント",
         "・プロジェクトの背景・目的\n・技術スタック一覧\n・設計原則\n・AI 支援スコープ",
         "◎ 詳細あり", "✕ なし", "✕ なし", "✕ なし"),
        ("AI_CONTEXT.md",
         "AI アシスタント全般\n(Cursor, Copilot 等)",
         "・システムアーキテクチャ\n・コンポーネント間の関係\n・API 設計方針\n・今後の拡張ポイント",
         "◎ 詳細あり", "△ 概要のみ", "✕ なし", "✕ なし"),
    ]

    mark_colors = {
        "◎ 詳細あり": ("E8F5E9", "2E6B2E"),
        "○ 簡易": ("EBF2FF", "1A3A5C"),
        "○ 最小限": ("EBF2FF", "1A3A5C"),
        "○ タイル関連のみ": ("EBF2FF", "1A3A5C"),
        "○ データ関連のみ": ("EBF2FF", "1A3A5C"),
        "○ 本番デプロイ": ("EBF2FF", "1A3A5C"),
        "△ 概要のみ": ("FFF3CD", "7B4A00"),
        "△ 変換手順のみ": ("FFF3CD", "7B4A00"),
        "△ GeoJSON 配置のみ": ("FFF3CD", "7B4A00"),
        "✕ なし": ("F5F5F5", "AAAAAA"),
    }

    for i, row in enumerate(md_files, 3):
        bg = "F5F9FF" if i % 2 == 1 else "FFFFFF"
        apply_cell(ws, i, 1, row[0], bold=True, fill_color=bg)
        apply_cell(ws, i, 2, row[1], fill_color=bg)
        apply_cell(ws, i, 3, row[2], fill_color=bg)
        for j, mark in enumerate(row[3:], 4):
            mc, fc = mark_colors.get(mark, (bg, "000000"))
            apply_cell(ws, i, j, mark, fill_color=mc, font_color=fc, align="center", bold=("◎" in mark))
        ws.row_dimensions[i].height = 70

    # 凡例
    ws.merge_cells("A11:G11")
    ws.cell(11, 1, "■ 凡例").font = Font(name="游ゴシック", bold=True, size=11, color="2E5FA3")

    legend_items = [
        ("◎ 詳細あり", "そのトピックについて詳細な情報・手順が記載されている", "E8F5E9", "2E6B2E"),
        ("○ 概要あり", "そのトピックについて概要・参照情報が記載されている", "EBF2FF", "1A3A5C"),
        ("△ 一部のみ", "関連する一部の情報のみ記載されている", "FFF3CD", "7B4A00"),
        ("✕ なし", "そのトピックについての記載はない", "F5F5F5", "AAAAAA"),
    ]
    for i, (mark, desc, bc, fc) in enumerate(legend_items, 12):
        apply_cell(ws, i, 1, mark, bold=True, fill_color=bc, font_color=fc, align="center")
        ws.merge_cells(f"B{i}:G{i}")
        apply_cell(ws, i, 2, desc, fill_color="FFFFFF")

    set_col_widths(ws, [30, 22, 46, 16, 16, 16, 20])
    freeze(ws, "A3")

# ======= メイン =======

def main():
    wb = Workbook()
    wb.remove(wb.active)  # デフォルトシートを削除

    sheet_overview(wb)
    sheet_directory(wb)
    sheet_data_requirements(wb)
    sheet_startup(wb)
    sheet_hazard(wb)
    sheet_dataflow(wb)
    sheet_api(wb)
    sheet_md_mapping(wb)

    output_path = "/Users/hideki/Documents/GitHub/OnHighGround2/OnHighGround2_構成ドキュメント.xlsx"
    wb.save(output_path)
    print(f"✓ 保存完了: {output_path}")


if __name__ == "__main__":
    main()
