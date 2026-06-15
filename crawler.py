# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "playwright",
#     "trafilatura",
#     "beautifulsoup4",
# ]
# ///

import argparse
import os
import csv
import time
import json
import requests
import re
from urllib.parse import urlparse, parse_qs, urljoin
from playwright.sync_api import sync_playwright
import trafilatura
from bs4 import BeautifulSoup

# --- 設定項目（CLIで上書き可能）---
URL_LIST_FILE = "urls.txt"             # インプットする一意のURLリスト
BASE_DIR = "."                                # 出力ベースディレクトリ（--dir で上書き）
OUTPUT_DIR = "text_assets"                    # マークダウンの保存先フォルダ名（BASE_DIR 配下）
LOG_FILE = "crawl_summary.csv"                # テキスト用のログCSV
MEDIA_LOG_FILE = "media_inventory.csv"        # コンテンツ固有の画像・動画棚卸しCSV
COMMON_MEDIA_LOG_FILE = "common_assets.csv"   # ヘッダー・フッター等の共通アセットCSV
MIN_CHAR_COUNT = 200                          # Playwrightに切り替える文字数の閾値

def clean_and_normalize_url(url):
    """生のURLをAI検索最適化（GEO）基準で精密にクリーンアップする"""
    url = url.split('#')[0].strip()
    if not url.startswith("http"):
        return None, "invalid_url"
        
    parsed = urlparse(url)
    path = parsed.path
    
    # 1. 完全なシステムゴミ・開発用URLを100%除外
    if any(k in url.lower() for k in ['feed', 'wp-json', 'wp-content', 'replytocom', 'archive-dropdown', 'action=']):
        return None, "system_garbage"
    
    # 2. 【追加】日付アーカイブページ（一覧ページなので不要）の除外
    if '/archives/date/' in path:
        return None, "date_archive"
        
    # 3. 【追加】ブログのページネーション（/page/2 等）の一括除外
    queries = parse_qs(parsed.query)
    if '/page/' in path or 'page' in queries:
        return None, "pagination"
        
    # 末尾スラッシュの統一（ファイル拡張子がない場合のみ補完）
    if not path.endswith('/') and not os.path.splitext(path)[1]:
        path += '/'
        
    # 4. 【罠の解消】クエリパラメータの精密なキー判定（部分一致のバグを回避）
    # WordPressのネイティブ短縮URL（?p=123）は重要な個別ページなので救う
    if 'p' in queries:
        return f"{parsed.scheme}://{parsed.netloc}{path}?p={queries['p'][0]}", "valid_shortlink"
    
    # カテゴリパラメータ（?cat=123）も救う
    if 'cat' in queries:
        return f"{parsed.scheme}://{parsed.netloc}{path}?cat={queries['cat'][0]}", "valid_category"
        
    # それ以外のゴミパラメータ（?amp=1, ?noamp=mobile等）はすべて削ぎ落としてベースURLに統合
    clean_url = f"{parsed.scheme}://{parsed.netloc}{path}"
    return clean_url, "pure_url"

# 共通レイアウト領域を特定するCSSセレクタパターン
_COMMON_AREA_TAGS = re.compile(
    r'^(header|footer|nav|aside)$', re.IGNORECASE
)
_COMMON_AREA_CLASSES = re.compile(
    r'header|footer|nav|sidebar|widget|breadcrumb|gnav|global-nav|site-nav|menu',
    re.IGNORECASE
)

def _get_element_section(element):
    """要素がコンテンツ領域か共通レイアウト領域かを判定して返す"""
    for parent in element.parents:
        tag = getattr(parent, 'name', '') or ''
        classes = ' '.join(parent.get('class', []))
        element_id = parent.get('id', '')
        if _COMMON_AREA_TAGS.match(tag):
            return 'common'
        if _COMMON_AREA_CLASSES.search(classes) or _COMMON_AREA_CLASSES.search(element_id):
            return 'common'
    return 'content'

def _extract_from_area(area, page_url, bg_pattern):
    """特定のエリアからメディア要素を抽出してリストで返す"""
    result = []
    seen_urls = set()

    # img タグ
    for img in area.find_all('img'):
        src = img.get('src')
        if src:
            src_abs = urljoin(page_url, src)
            if src_abs not in seen_urls:
                seen_urls.add(src_abs)
                alt = img.get('alt', '').strip()
                result.append({"page_url": page_url, "type": "画像(img)", "media_url": src_abs, "alt_or_title": alt})

    # iframe（YouTube / Vimeo 等）
    for iframe in area.find_all('iframe'):
        src = iframe.get('src')
        if src and any(v in src.lower() for v in ['youtube', 'vimeo', 'video', 'embed']):
            src_abs = urljoin(page_url, src)
            if src_abs not in seen_urls:
                seen_urls.add(src_abs)
                title = iframe.get('title', '').strip()
                result.append({"page_url": page_url, "type": "埋め込み動画(iframe)", "media_url": src_abs, "alt_or_title": title})

    # video / embed / object タグ
    for video in area.find_all(['video', 'embed', 'object']):
        src = video.get('src') or video.get('data')
        if not src and video.name == 'video':
            source = video.find('source')
            if source:
                src = source.get('src')
        if src:
            src_abs = urljoin(page_url, src)
            if src_abs not in seen_urls:
                seen_urls.add(src_abs)
                result.append({"page_url": page_url, "type": f"動画({video.name})", "media_url": src_abs, "alt_or_title": ""})

    # CSS インラインスタイルの背景画像
    for element in area.find_all(style=True):
        style_attr = element.get('style', '')
        for bg_url in bg_pattern.findall(style_attr):
            bg_url = bg_url.strip()
            if bg_url.startswith('data:'):
                continue
            src_abs = urljoin(page_url, bg_url)
            if src_abs not in seen_urls:
                seen_urls.add(src_abs)
                result.append({"page_url": page_url, "type": "背景画像(CSS)", "media_url": src_abs, "alt_or_title": ""})

    return result

def extract_media_elements(html_content, page_url):
    """HTMLからコンテンツ固有メディアと共通レイアウトメディアを分けて抽出する
    Returns:
        content_media: メインコンテンツ領域の画像・動画リスト
        common_media:  ヘッダー・フッター・サイドバー等の共通アセットリスト
    """
    if not html_content:
        return [], []

    soup = BeautifulSoup(html_content, 'html.parser')
    bg_pattern = re.compile(
        r'url\s*\(\s*[\'"\x00]?([^\'"\x00)\s]+)[\'"\x00]?\s*\)',
        re.IGNORECASE
    )

    # ── コンテンツ領域の特定（優先順位順に探索） ──
    content_area = (
        soup.find('main') or
        soup.find('article') or
        soup.find(class_=re.compile(
            r'entry-content|post-content|article-body|main-content|the-content',
            re.IGNORECASE
        )) or
        soup.find(id=re.compile(
            r'content|main|primary',
            re.IGNORECASE
        ))
    )

    # ── 共通レイアウト領域の収集 ──
    common_selectors = [
        soup.find('header'),
        soup.find('footer'),
        soup.find('nav'),
        soup.find('aside'),
        soup.find(class_=_COMMON_AREA_CLASSES),
    ]
    common_areas = [el for el in common_selectors if el is not None]

    if content_area:
        content_media = _extract_from_area(content_area, page_url, bg_pattern)
    else:
        # コンテンツ領域が特定できない場合は全体から抽出（フォールバック）
        content_media = _extract_from_area(soup, page_url, bg_pattern)
        common_areas = []  # 重複を避けるため共通領域は空にする

    # 共通領域のメディア（コンテンツに含まれるものは除外）
    content_urls = {m['media_url'] for m in content_media}
    common_media = []
    seen_common_urls = set()
    for area in common_areas:
        for item in _extract_from_area(area, page_url, bg_pattern):
            if item['media_url'] not in content_urls and item['media_url'] not in seen_common_urls:
                seen_common_urls.add(item['media_url'])
                common_media.append(item)

    return content_media, common_media


def fetch_with_trafilatura(url):
    """【第1の矢】高速なTrafilaturaだけでテキストを抜いてみる"""
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if response.status_code == 200:
            return trafilatura.extract(response.text, output_format="markdown"), 200, response.text
        return None, response.status_code, response.text
    except Exception as e:
        return None, f"ConnectionError: {str(e)}", ""

def fetch_with_playwright(url):
    """【第2の矢】JSブロックの壁をPlaywright（Chrome）で強行突破する"""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle")  # JSの動的描画を待つ
            html_content = page.content()
            markdown_text = trafilatura.extract(html_content, output_format="markdown")
            browser.close()
            return markdown_text, html_content
    except Exception as e:
        return f"# エラー\nPlaywrightでも取得失敗: {str(e)}", ""

def main():
    global URL_LIST_FILE, BASE_DIR, OUTPUT_DIR, LOG_FILE, MEDIA_LOG_FILE, COMMON_MEDIA_LOG_FILE

    # CLI 引数のパース（site_crawler.py からの自動呼び出しにも対応）
    parser = argparse.ArgumentParser(description="URLリストからコンテンツ・メディアを抽出します。")
    parser.add_argument("-i", "--input", default=None,
                        help="入力URLリストファイル（CSV or TXT）。デフォルト: urls.txt")
    parser.add_argument("-d", "--dir", default=None,
                        help="出力ベースディレクトリ。デフォルト: カレントディレクトリ")
    args = parser.parse_args()

    if args.input:
        URL_LIST_FILE = args.input
    if args.dir:
        BASE_DIR = args.dir
        OUTPUT_DIR = os.path.join(BASE_DIR, "text_assets")
        LOG_FILE            = os.path.join(BASE_DIR, "crawl_summary.csv")
        MEDIA_LOG_FILE      = os.path.join(BASE_DIR, "media_inventory.csv")
        COMMON_MEDIA_LOG_FILE = os.path.join(BASE_DIR, "common_assets.csv")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not os.path.exists(URL_LIST_FILE):
        print(f"エラー: {URL_LIST_FILE} が見つかりません。ファイルを配置してください。")
        return

    # CSVまたはテキストファイルからURLを読み込む
    raw_urls = []
    with open(URL_LIST_FILE, "r", encoding="utf-8") as f:
        # CSVのカンマやヘッダーを考慮して読み込み
        reader = csv.reader(f)
        for row in reader:
            if row:
                raw_urls.append(row[0])

    print(f"生のURLデータを読み込みました（総数: {len(raw_urls)} 件）")
    print("精密クリーンアップと重複排除（正規化）を自動実行します...")

    # URLのクリーンアップと重複の自動排除
    unique_targets = {}
    for url in raw_urls:
        clean_url, category = clean_and_normalize_url(url)
        if clean_url and clean_url not in unique_targets:
            unique_targets[clean_url] = category

    urls_to_crawl = list(unique_targets.keys())
    print(f"\n✨ クリーンアップ完了！本当に処理すべきURLは【計 {len(urls_to_crawl)} 件】に圧縮されました。")
    print("ハイブリッド巡回を開始します...\n")
    
    crawl_results = []
    all_discovered_media = []
    all_common_media = []

    for idx, url in enumerate(urls_to_crawl, 1):
        # URLの前後の空白・改行を除去（CRLFファイルの\rが混入するのを防ぐ）
        url = url.strip()
        if not url:
            continue
        # 既存の出力ファイルがあるかチェックしてレジューム（復元スキップ）
        safe_filename = (url.replace("https://", "").replace("http://", "")
                            .replace("/", "_").replace("?", "_")
                            .replace("\r", "").replace("\n", "").replace(" ", "_"))[:100]
        filename_ok = f"{safe_filename}.md"
        filename_check = f"[要確認]_{safe_filename}.md"
        filepath_ok = os.path.join(OUTPUT_DIR, filename_ok)
        filepath_check = os.path.join(OUTPUT_DIR, filename_check)

        existing_filepath = None
        if os.path.exists(filepath_ok):
            existing_filepath = filepath_ok
        elif os.path.exists(filepath_check):
            existing_filepath = filepath_check

        if existing_filepath:
            try:
                # 既存ファイルからフロントマターと内容を解析して結果リストを復元
                with open(existing_filepath, "r", encoding="utf-8") as in_f:
                    content = in_f.read()
                
                # フロントマターの簡易パース
                lines = content.split("\n")
                cached_method = "Trafilatura"
                cached_status = "OK"
                cached_media = []
                cached_common = []
                if len(lines) >= 5 and lines[0].strip() == "---":
                    for line in lines[1:]:
                        if line.strip() == "---":
                            break
                        if ":" in line:
                            k, v = line.split(":", 1)
                            k = k.strip()
                            v = v.strip()
                            if k == "method":
                                cached_method = v
                            elif k == "status":
                                cached_status = v
                            elif k == "media":
                                try:
                                    cached_media = json.loads(v)
                                except Exception:
                                    pass
                            elif k == "common":
                                try:
                                    cached_common = json.loads(v)
                                except Exception:
                                    pass
                
                # 本文の文字数をカウント
                body_start_idx = content.find("---\n\n")
                if body_start_idx != -1:
                    body_text = content[body_start_idx + 5:]
                else:
                    body_text = content
                char_count = len(body_text)

                print(f"[{idx}/{len(urls_to_crawl)}] スキップ（保存済み）: {url}")
                # メディア資産のリストを統合
                if cached_media:
                    all_discovered_media.extend(cached_media)
                if cached_common:
                    all_common_media.extend(cached_common)
                if cached_media or cached_common:
                    img_c = len([m for m in cached_media if '画像' in m['type']])
                    com_c = len(cached_common)
                    print(f"  └ キャッシュ復元: 固有画像 {img_c}件  ｜  共通アセット {com_c}件")

                crawl_results.append({
                    "URL": url,
                    "使用ツール": cached_method,
                    "判定": "OK" if "OK" in cached_status else "要確認",
                    "文字数": char_count,
                    "保存ファイル名": os.path.basename(existing_filepath)
                })
                continue
            except Exception as e:
                print(f"  ⚠️ 保存済みファイルの解析に失敗したため、再取得します: {e}")

        print(f"[{idx}/{len(urls_to_crawl)}] 処理中: {url}")
        method_used = "Trafilatura"
        status = "OK"
        html_content = ""
        
        # まずは最速のTrafilaturaで実行
        markdown_text, status_code, html_content = fetch_with_trafilatura(url)
        char_count = len(markdown_text) if markdown_text else 0
        
        # 【自動判定フォールバック】ステータスが200（成功）以外の場合はPlaywrightに切り替えずスキップ
        if status_code != 200:
            method_used = "Trafilatura"
            status = f"★要確認（HTTPエラー: {status_code}）"
            markdown_text = f"# エラー\n取得失敗（ステータス: {status_code}）"
            char_count = 0
        # 正常レスポンスだが文字数が極端に少ない場合はPlaywrightを起動
        elif char_count < MIN_CHAR_COUNT:
            print(f"  ⚠️ 本文が抜けないため、Playwright（ヘッドレスブラウザ）に切り替えます...")
            method_used = "Playwright"
            markdown_text, html_content = fetch_with_playwright(url)
            char_count = len(markdown_text) if markdown_text else 0
            
            if char_count < MIN_CHAR_COUNT:
                status = "★要確認（中身が空っぽ、または両方で抽出失敗）"
        
        # メディア要素の抽出（コンテンツ固有 / 共通アセット を分離）
        detected_media = []
        detected_common = []
        if html_content:
            detected_media, detected_common = extract_media_elements(html_content, url)
            all_discovered_media.extend(detected_media)
            all_common_media.extend(detected_common)
            img_c = len([m for m in detected_media if '画像' in m['type']])
            vid_c = len([m for m in detected_media if '動画' in m['type']])
            com_c = len(detected_common)
            print(f"  └ 固有資産: 画像 {img_c}件 / 動画 {vid_c}件  ｜  共通アセット: {com_c}件")

        # 安全なマークダウンファイル名を作成して保存
        filename = f"{'[要確認]_' if '★要確認' in status else ''}{safe_filename}.md"
        filepath = os.path.join(OUTPUT_DIR, filename)

        # メディアデータをJSON化してフロントマターに埋め込む（再開時の復元用）
        media_json = json.dumps(detected_media, ensure_ascii=False)
        common_json = json.dumps(detected_common, ensure_ascii=False)
        with open(filepath, "w", encoding="utf-8") as out_f:
            out_f.write(f"--- \nurl: {url}\nmethod: {method_used}\nstatus: {status}\nmedia: {media_json}\ncommon: {common_json}\n---\n\n")
            out_f.write(markdown_text if markdown_text else "")

        crawl_results.append({
            "URL": url,
            "使用ツール": method_used,
            "判定": "OK" if "OK" in status else "要確認",
            "文字数": char_count,
            "保存ファイル名": filename
        })
        time.sleep(0.5)

    # 1. クロールサマリーCSVの出力
    with open(LOG_FILE, "w", encoding="utf-8-sig", newline="") as log_f:
        writer = csv.DictWriter(log_f, fieldnames=["URL", "使用ツール", "判定", "文字数", "保存ファイル名"])
        writer.writeheader()
        writer.writerows(crawl_results)

    # 2. コンテンツ固有メディア資産CSVの出力
    with open(MEDIA_LOG_FILE, "w", encoding="utf-8-sig", newline="") as media_f:
        writer = csv.DictWriter(media_f, fieldnames=["page_url", "type", "media_url", "alt_or_title"])
        writer.writeheader()
        writer.writerows(all_discovered_media)

    # 3. 共通レイアウトアセットCSVの出力（ヘッダー・フッター・サイドバー等 / 重複排除）
    seen = set()
    unique_common = []
    for item in all_common_media:
        key = item['media_url']
        if key not in seen:
            seen.add(key)
            unique_common.append(item)
    with open(COMMON_MEDIA_LOG_FILE, "w", encoding="utf-8-sig", newline="") as common_f:
        writer = csv.DictWriter(common_f, fieldnames=["page_url", "type", "media_url", "alt_or_title"])
        writer.writeheader()
        writer.writerows(unique_common)

    print(f"\n🎉 すべてのリソースデータ抽出が完了しました！")
    print(f" 📄 テキスト資産     ── フォルダ「{OUTPUT_DIR}」にマークダウン保存完了")
    print(f" 🖼️  固有画像・動画   ── 「{MEDIA_LOG_FILE}」に {len(all_discovered_media)} 件を出力完了")
    print(f" 🗂️  共通レイアウト資産 ── 「{COMMON_MEDIA_LOG_FILE}」に {len(unique_common)} 件（重複排除済み）を出力完了")

if __name__ == "__main__":
    main()
