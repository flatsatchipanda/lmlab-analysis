# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "advertools",
#     "pandas",
# ]
# ///

import argparse
import sys
import os
import re
import subprocess
from urllib.parse import urlparse, parse_qs
import pandas as pd
import advertools as adv


def domain_to_folder(url: str) -> str:
    """URLのドメイン(+パス)からフォルダ名を生成する
    例: https://fujioka-dc.jp/          → fujioka-dc.jp
    例: https://note.com/nakanodc_dr   → note.com_nakanodc_dr
    """
    parsed = urlparse(url)
    netloc = parsed.netloc or "unknown_site"
    path = parsed.path.strip("/")
    if path:
        # パスの / を _ に置換してフォルダ名に使う
        return f"{netloc}_{path.replace('/', '_')}"
    return netloc

def clean_and_normalize_url(url):
    """crawler.py と同等の URL クレンジング・正規化ロジック"""
    url = url.split('#')[0].strip()
    if not url.startswith("http"):
        return None, "invalid_url"
        
    parsed = urlparse(url)
    path = parsed.path
    
    # 1. 完全なシステムゴミ・開発用URLを100%除外
    if any(k in url.lower() for k in ['feed', 'wp-json', 'wp-content', 'replytocom', 'archive-dropdown', 'action=']):
        return None, "system_garbage"
    
    # 2. 日付アーカイブページ（一覧ページなので不要）の除外
    if '/archives/date/' in path:
        return None, "date_archive"
        
    # 3. ブログのページネーション（/page/2 等）の一括除外
    queries = parse_qs(parsed.query)
    if '/page/' in path or 'page' in queries:
        return None, "pagination"
        
    # 末尾スラッシュの統一（ファイル拡張子がない場合のみ補完）
    if not path.endswith('/') and not os.path.splitext(path)[1]:
        path += '/'
        
    # 4. クエリパラメータの精密なキー判定（部分一致のバグを回避）
    # WordPressのネイティブ短縮URL（?p=123）は重要な個別ページなので救う
    if 'p' in queries:
        return f"{parsed.scheme}://{parsed.netloc}{path}?p={queries['p'][0]}", "valid_shortlink"
    
    # カテゴリパラメータ（?cat=123）も救う
    if 'cat' in queries:
        return f"{parsed.scheme}://{parsed.netloc}{path}?cat={queries['cat'][0]}", "valid_category"
        
    # それ以外のゴミパラメータはすべて削ぎ落としてベースURLに統合
    clean_url = f"{parsed.scheme}://{parsed.netloc}{path}"
    return clean_url, "pure_url"

def crawl_site(start_url, output_jsonl, output_csv, page_limit=1000):
    # 開始URLのパスを URL フィルターとして使う（note.com 等のサブパス対応）
    parsed_start = urlparse(start_url)
    path_prefix_base = parsed_start.path.rstrip("/")  # 例: /nakanodc_dr
    has_path_filter = bool(path_prefix_base and path_prefix_base != "/")
    if has_path_filter:
        prefix_for_filter = f"{parsed_start.scheme}://{parsed_start.netloc}{path_prefix_base}"
        print(f"  ⚠️ サブパスフィルター有効: '{prefix_for_filter}' で始まるURLのみを出力します")

    print(f"クローリングを開始します: {start_url} (上限: {page_limit} ページ)")
    
    # robots.txtに従ってクロールを実行
    try:
        adv.crawl(
            url_list=[start_url],
            output_file=output_jsonl,
            follow_links=True,
            custom_settings={
                "LOG_LEVEL": "INFO",
                "CLOSESPIDER_PAGECOUNT": page_limit,
            },
        )
    except Exception as e:
        print(f"クローリング中にエラーが発生しました: {e}")
        if not os.path.exists(output_jsonl):
            print("エラー: クロール結果ファイルが生成されませんでした。終了します。")
            return None

    print("クロール結果の読み込みとURLの正規化処理を行っています...")
    
    try:
        df = pd.read_json(output_jsonl, lines=True)
    except Exception as e:
        print(f"クロール結果の解析に失敗しました: {e}")
        return None

    expected_cols = ["url", "status", "title", "h1"]
    existing_cols = [col for col in expected_cols if col in df.columns]
    df_urls = df[existing_cols].dropna(subset=["url"]).copy()

    # URL正規化ロジックの適用
    cleaned_data = []
    skipped = 0
    for idx, row in df_urls.iterrows():
        raw_url = row["url"]

        # サブパスフィルター: 開始URLのパスで始まらないURLはスキップ
        if has_path_filter and not raw_url.startswith(prefix_for_filter):
            skipped += 1
            continue

        clean_url, category = clean_and_normalize_url(raw_url)
        if clean_url:
            row_dict = row.to_dict()
            row_dict["url"] = clean_url
            row_dict["url_type"] = category
            cleaned_data.append(row_dict)

    if has_path_filter and skipped:
        print(f"  ℹ️ プレフィックス不一致の無関係URL {skipped} 件を除外しました")

    if not cleaned_data:
        print("有効なURLが抽出されませんでした。")
        return None

    df_cleaned = pd.DataFrame(cleaned_data)
    df_cleaned = df_cleaned.drop_duplicates(subset=["url"])

    df_cleaned.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"完了！正規化済みURL {len(df_cleaned)} 件の一覧を '{output_csv}' に保存しました。")
    return output_csv

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="サイトをクロールしてURLリストを生成し、続けてコンテンツ抽出も自動実行します。"
    )
    parser.add_argument("start_url", nargs="?", help="クロールを開始するトップページのURL")
    parser.add_argument("-l", "--limit", type=int, default=1000, help="クローリング最大ページ数 (デフォルト: 1000)")
    parser.add_argument("--no-extract", action="store_true", help="crawler.py によるコンテンツ抽出をスキップする")

    args = parser.parse_args()

    start_url = args.start_url
    if not start_url:
        try:
            start_url = input("開始URL（トップページなど）を入力してください: ").strip()
        except KeyboardInterrupt:
            print("\nキャンセルされました。")
            sys.exit(0)

    if not start_url:
        print("開始URLが指定されていません。終了します。")
        sys.exit(1)

    # ── ① ドメインフォルダの自動生成 ──
    folder_name = domain_to_folder(start_url)
    crawled_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawled_data")
    folder_path = os.path.join(crawled_data_dir, folder_name)
    os.makedirs(folder_path, exist_ok=True)
    print(f"\n📁 出力フォルダ: {folder_path}")

    output_jsonl = os.path.join(folder_path, "crawl_raw.jsonl")
    output_csv   = os.path.join(folder_path, "site_url_list.csv")

    # ── ② サイトクロール & URL一覧 CSV の生成 ──
    parsed_start = urlparse(start_url)
    if "note.com" in parsed_start.netloc:
        path_parts = [p for p in parsed_start.path.split("/") if p]
        if not path_parts:
            print("エラー: note.com のクリエイターIDをURLパスから特定できませんでした。")
            sys.exit(1)
        creator_id = path_parts[0]
        print(f"\n📝 note.com のURLを検出しました。note_extractor.py を使用して記事一覧を取得します。")
        print(f"   クリエイターID: {creator_id}")
        
        note_extractor_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "note_extractor.py")
        ret = subprocess.run(
            ["uv", "run", note_extractor_path, creator_id, "-o", output_csv],
            check=False,
        )
        if ret.returncode != 0:
            print("エラー: note_extractor.py の実行に失敗しました。")
            sys.exit(ret.returncode)
        result_csv = output_csv
    else:
        result_csv = crawl_site(start_url, output_jsonl, output_csv, args.limit)

    if result_csv is None:
        print("クロールが失敗したため、コンテンツ抽出をスキップします。")
        sys.exit(1)

    # ── ③ crawler.py によるコンテンツ抽出を自動実行 ──
    if args.no_extract:
        print("\n--no-extract が指定されたため、コンテンツ抽出をスキップしました。")
    else:
        crawler_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawler.py")
        print(f"\n🚀 コンテンツ抽出を開始します（crawler.py）...")
        print(f"   入力: {result_csv}")
        print(f"   出力先: {folder_path}")
        ret = subprocess.run(
            ["uv", "run", crawler_path, "--input", result_csv, "--dir", folder_path],
            check=False,
        )
        if ret.returncode != 0:
            print("\n⚠️  crawler.py が異常終了しました。")
            sys.exit(ret.returncode)

    print(f"\n✅ 完了！すべてのデータは '{folder_path}' に保存されています。")
