# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "pandas",
# ]
# ///

import argparse
import sys
import time
import requests
import pandas as pd

def extract_note_articles(creator_id, output_csv="note_article_list.csv"):
    base_url = f"https://note.com/api/v2/creators/{creator_id}/contents"
    note_data = []
    page = 1

    print(f"noteユーザーID '{creator_id}' からの記事抽出を開始します...")

    while True:
        # kind=note で通常の記事のみを指定
        params = {"kind": "note", "page": page}
        try:
            response = requests.get(base_url, params=params, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
        except Exception as e:
            print(f"接続エラーが発生しました: {e}")
            break

        if response.status_code == 404:
            print(f"エラー: 指定されたクリエイターID '{creator_id}' が見つかりませんでした (404)。")
            break
        elif response.status_code != 200:
            print(f"エラーが発生しました (ステータスコード: {response.status_code})")
            break

        try:
            data = response.json()
        except ValueError:
            print("エラー: レスポンスをJSONとしてデコードできませんでした。")
            break

        contents = data.get("data", {}).get("contents", [])

        # 記事がこれ以上なければ終了
        if not contents:
            break

        for content in contents:
            note_data.append(
                {
                    "url": content.get("noteUrl"),
                    "title": content.get("name"),
                    "publish_date": content.get("publishAt"),
                    "like_count": content.get("likeCount"),
                }
            )

        print(f"Page {page} の取得完了... ({len(contents)}件)")
        
        # 続きがあるか判定
        is_last = data.get("data", {}).get("isLastPage", True)
        if is_last:
            break
            
        page += 1
        time.sleep(1)  # サーバー負荷軽減のためのウェイト

    if note_data:
        df_note = pd.DataFrame(note_data)
        df_note.to_csv(output_csv, index=False, encoding="utf-8-sig")
        print(f"完了！合計 {len(df_note)} 件のnote記事を抽出しました。結果は '{output_csv}' に保存されました。")
    else:
        print("抽出された記事はありませんでした。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="noteの指定クリエイターの全通常記事一覧を抽出します。")
    parser.add_argument("creator_id", nargs="?", help="noteのクリエイターID (例: note.com/xxxx の xxxx 部分)")
    parser.add_argument("-o", "--output", default="note_article_list.csv", help="出力先CSVファイル名 (デフォルト: note_article_list.csv)")

    args = parser.parse_args()

    creator_id = args.creator_id
    if not creator_id:
        # デフォルトでユーザー入力を促す
        try:
            creator_id = input("noteクリエイターIDを入力してください: ").strip()
        except KeyboardInterrupt:
            print("\nキャンセルされました。")
            sys.exit(0)

    if not creator_id:
        print("クリエイターIDが指定されていません。終了します。")
        sys.exit(1)

    extract_note_articles(creator_id, args.output)
