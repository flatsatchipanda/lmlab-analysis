# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "yt-dlp",
#     "youtube-transcript-api",
# ]
# ///

"""
YouTube チャンネル全動画 抽出スクリプト
========================================
機能:
  1. yt-dlp でチャンネル内の全動画のタイトル・URL・公開日を CSV に出力
  2. youtube-transcript-api で各動画の日本語字幕（文字起こし）を取得してテキスト保存

使い方:
  uv run youtube_channel_extractor.py --channel "https://www.youtube.com/@YourChannel/videos"

  # 特定の動画IDだけ字幕を取得したい場合（リスト取得はスキップ）
  uv run youtube_channel_extractor.py --transcript-only --video-ids "abc123,def456"

  # CSVは作成済みで字幕だけ取り直したい場合
  uv run youtube_channel_extractor.py --from-csv youtube_videos.csv
"""

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from pathlib import Path

# ──────────────────────────────────────────────
# 設定項目
# ──────────────────────────────────────────────
OUTPUT_CSV = "youtube_videos.csv"          # 動画リストの出力先
TRANSCRIPT_DIR = "youtube_transcripts"     # 文字起こしテキストの保存フォルダ
SUMMARY_CSV = "youtube_transcript_log.csv" # 文字起こし処理ログ

# 字幕取得の優先言語リスト（先頭ほど優先）
TRANSCRIPT_LANGS = ["ja", "ja-JP"]
# 自動生成字幕も許可するか（手動字幕が存在しない動画のフォールバック）
ALLOW_AUTO_GENERATED = True
# 動画リスト取得後、字幕取得前に入れるウェイト（秒）。過剰アクセス防止。
SLEEP_BETWEEN_REQUESTS = 3.0


# ──────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────
def safe_filename(text: str, max_len: int = 80) -> str:
    """ファイル名として使えない文字を除去・短縮する"""
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    text = text.strip().strip(".")
    return text[:max_len] if len(text) > max_len else text


def extract_video_id(url: str) -> str | None:
    """YouTube動画URLから動画IDを抽出する"""
    patterns = [
        r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


# ──────────────────────────────────────────────
# Step 1: yt-dlp でチャンネルの全動画リストを取得
# ──────────────────────────────────────────────
def fetch_video_list(channel_url: str, output_csv: str) -> list[dict]:
    """
    yt-dlp を使ってチャンネルの全動画リストを取得し CSV に保存する。
    返値: [{"title": ..., "url": ..., "video_id": ..., "upload_date": ...}, ...]
    """
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        print("❌ yt-dlp がインストールされていません。")
        print("   pip install yt-dlp  または  uv add yt-dlp  を実行してください。")
        sys.exit(1)

    import yt_dlp

    print(f"\n📋 Step 1: チャンネルの全動画リストを取得中...")
    print(f"   対象: {channel_url}")

    ydl_opts = {
        "extract_flat": True,       # 動画ページを開かずにメタデータのみ取得
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,       # エラーが出ても続行
        # 日本語タイトルを取得するために Accept-Language を ja に設定
        "http_headers": {"Accept-Language": "ja-JP,ja;q=0.9"},
        "extractor_args": {"youtube": {"lang": ["ja"]}},
    }

    videos = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
        if not info:
            print("❌ チャンネル情報の取得に失敗しました。URLを確認してください。")
            return []

        entries = info.get("entries", [])
        if not entries:
            print("⚠️ 動画が1本も見つかりませんでした。")
            return []

        for entry in entries:
            if not entry:
                continue
            video_id = entry.get("id", "")
            title = entry.get("title", "").strip()
            url = entry.get("url") or entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"
            upload_date = entry.get("upload_date", "")          # YYYYMMDD 形式
            duration = entry.get("duration", "")                # 秒数
            view_count = entry.get("view_count", "")

            # upload_date を YYYY-MM-DD 形式に変換
            if upload_date and len(upload_date) == 8:
                upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

            videos.append({
                "video_id": video_id,
                "title": title,
                "url": url,
                "upload_date": upload_date,
                "duration_sec": duration,
                "view_count": view_count,
            })

    print(f"   ✅ {len(videos)} 本の動画を検出しました。")

    # CSV に保存
    with open(output_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["video_id", "title", "url", "upload_date", "duration_sec", "view_count"])
        writer.writeheader()
        writer.writerows(videos)
    print(f"   💾 動画リストを保存しました: {output_csv}")

    return videos


# ──────────────────────────────────────────────
# Step 2: yt-dlp で字幕をダウンロードして取得
# ──────────────────────────────────────────────
def vtt_to_text(vtt_content: str) -> str:
    """VTTファイルの内容からタイムスタンプとタグを除去してテキストを抽出する"""
    lines = vtt_content.splitlines()
    text_lines = []
    timestamp_pattern = re.compile(r'(\d{2}:)?\d{2}:\d{2}\.\d{3} --> (\d{2}:)?\d{2}:\d{2}\.\d{3}')
    seen_lines = set()

    for line in lines:
        line = line.strip()
        # VTTのヘッダーやタイムスタンプ、メタデータ（align等）行をスキップ
        if not line or line == 'WEBVTT' or line.startswith('NOTE') or timestamp_pattern.match(line) or "align:" in line:
            continue
        
        # HTMLタグ（<c>など）を除去
        clean_line = re.sub(r'<[^>]+>', '', line)
        clean_line = clean_line.strip()
        
        # 重複行を排除してテキストを結合
        if clean_line and clean_line not in seen_lines:
            text_lines.append(clean_line)
            seen_lines.add(clean_line)

    return " ".join(text_lines)


def fetch_transcript(video_id: str) -> tuple[str, str]:
    """
    yt-dlpのextract_info(download=False)で字幕URLを抽出し、
    直接HTTP通信でVTTデータを取得してテキストに変換する。
    """
    import urllib.request
    import ssl
    try:
        import yt_dlp
    except ImportError:
        print("❌ yt-dlp がインストールされていません。")
        sys.exit(1)

    url = f"https://www.youtube.com/watch?v={video_id}"
    
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'check_formats': False,
        'youtube_include_dash_manifest': False,
        'youtube_include_hls_manifest': False,
        'format': 'worst',
        # システムの Chrome ブラウザから Cookie を直接自動取得して使用する
        'cookiesfrombrowser': ('chrome',),
        # yt-dlpの内部的なリクエスト間隔にゆらぎを持たせる設定
        'sleep_interval': 3,
        'max_sleep_interval': 8,
        # ブラウザに近いHTTPヘッダーを設定してブロックを回避
        'http_headers': {
            'Accept-Language': 'ja-JP,ja;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
        
        if not info_dict:
            return "", "動画情報の取得に失敗しました"

        # 字幕情報を探す (1. 手動字幕 `subtitles` -> 2. 自動生成字幕 `automatic_captions`)
        subtitles = info_dict.get('subtitles', {})
        auto_captions = info_dict.get('automatic_captions', {})

        subtitle_url = None
        lang_info = ""

        # 日本語(ja)の字幕を探す
        if 'ja' in subtitles:
            # 手動字幕のリストから優先度の高いフォーマット(vtt)を探す
            formats = subtitles['ja']
            for fmt in formats:
                if fmt.get('ext') == 'vtt' or 'vtt' in fmt.get('url', ''):
                    subtitle_url = fmt['url']
                    lang_info = "ja(手動)"
                    break
            if not subtitle_url and formats:
                subtitle_url = formats[0]['url']
                lang_info = "ja(手動)"

        # 手動字幕がなければ自動生成字幕を探す
        if not subtitle_url and 'ja' in auto_captions:
            formats = auto_captions['ja']
            for fmt in formats:
                if fmt.get('ext') == 'vtt' or 'vtt' in fmt.get('url', ''):
                    subtitle_url = fmt['url']
                    lang_info = "ja(自動生成)"
                    break
            if not subtitle_url and formats:
                subtitle_url = formats[0]['url']
                lang_info = "ja(自動生成)"

        if not subtitle_url:
            return "", "日本語の字幕(手動・自動)が見つかりません"

        # SSL証明書エラーを無視するコンテキスト設定
        ssl_context = ssl._create_unverified_context()
        
        # 字幕のVTTデータを直接ダウンロード
        req = urllib.request.Request(
            subtitle_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, context=ssl_context) as response:
            vtt_content = response.read().decode('utf-8')

        if not vtt_content:
            return "", "字幕データが空でした"

        full_text = vtt_to_text(vtt_content)
        if not full_text:
            return "", "字幕テキストのパース結果が空でした"

        return full_text, lang_info

    except yt_dlp.utils.DownloadError as e:
        return "", f"yt-dlp メタデータエラー: {str(e)}"
    except Exception as e:
        return "", f"エラー: {str(e)}"


def fetch_all_transcripts(videos: list[dict], transcript_dir: str, summary_csv: str):
    """
    動画リスト全件の字幕を取得してファイルに保存する。
    """
    os.makedirs(transcript_dir, exist_ok=True)

    print(f"\n📝 Step 2: 字幕（文字起こし）を一括取得中...")
    print(f"   保存先フォルダ: {transcript_dir}/")
    print(f"   対象件数: {len(videos)} 本\n")

    summary_rows = []
    success_count = 0
    skip_count = 0
    error_count = 0

    for idx, video in enumerate(videos, 1):
        video_id = video.get("video_id", "")
        title = video.get("title", f"video_{video_id}")
        upload_date = video.get("upload_date", "")
        url = video.get("url", f"https://www.youtube.com/watch?v={video_id}")

        if not video_id:
            print(f"  [{idx:4d}/{len(videos)}] ⚠️  動画IDが空のためスキップ: {title}")
            continue

        # 保存ファイル名: YYYY-MM-DD_タイトル.txt
        file_prefix = f"{upload_date}_{safe_filename(title)}" if upload_date else safe_filename(title)
        txt_path = Path(transcript_dir) / f"{file_prefix}.txt"
        json_path = Path(transcript_dir) / f"{file_prefix}.json"

        # 既存ファイルがあればスキップ（レジューム対応）
        if txt_path.exists():
            print(f"  [{idx:4d}/{len(videos)}] ⏭  スキップ（保存済み）: {title[:50]}")
            skip_count += 1
            summary_rows.append({
                "video_id": video_id,
                "title": title,
                "url": url,
                "upload_date": upload_date,
                "status": "スキップ(保存済み)",
                "lang_used": "",
                "char_count": txt_path.stat().st_size,
                "file": str(txt_path.name),
            })
            continue

        # 字幕取得
        text, lang_used = fetch_transcript(video_id)
        char_count = len(text)

        if text:
            # テキストファイルに保存（ヘッダー付き）
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"# {title}\n")
                f.write(f"URL: {url}\n")
                f.write(f"公開日: {upload_date}\n")
                f.write(f"字幕言語: {lang_used}\n")
                f.write(f"文字数: {char_count}\n")
                f.write("=" * 60 + "\n\n")
                f.write(text)

            # メタデータもJSONで保存（後で検索・分析に使える）
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({
                    "video_id": video_id,
                    "title": title,
                    "url": url,
                    "upload_date": upload_date,
                    "lang_used": lang_used,
                    "char_count": char_count,
                    "transcript": text,
                }, f, ensure_ascii=False, indent=2)

            status = "✅ 取得成功"
            success_count += 1
            print(f"  [{idx:4d}/{len(videos)}] ✅ {title[:50]} ({char_count:,}文字, {lang_used})")
        else:
            status = f"❌ 取得失敗: {lang_used}"
            error_count += 1
            print(f"  [{idx:4d}/{len(videos)}] ❌ {title[:50]} → {lang_used}")

        summary_rows.append({
            "video_id": video_id,
            "title": title,
            "url": url,
            "upload_date": upload_date,
            "status": status,
            "lang_used": lang_used,
            "char_count": char_count,
            "file": str(txt_path.name) if text else "",
        })

        # リクエストごとに 4〜9秒の間でランダムなウェイトを入れる（人間らしく見せるため）
        sleep_time = random.uniform(SLEEP_BETWEEN_REQUESTS, SLEEP_BETWEEN_REQUESTS + 12.0)
        time.sleep(sleep_time)

    # ログCSV保存
    with open(summary_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["video_id", "title", "url", "upload_date", "status", "lang_used", "char_count", "file"])
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"\n{'='*60}")
    print(f"🎉 字幕取得 完了！")
    print(f"   ✅ 取得成功: {success_count} 本")
    print(f"   ⏭  スキップ: {skip_count} 本（保存済み）")
    print(f"   ❌ 取得失敗: {error_count} 本（字幕なし等）")
    print(f"   📄 ログCSV : {summary_csv}")
    print(f"   📁 テキスト: {transcript_dir}/ フォルダ内")


# ──────────────────────────────────────────────
# キーワード検索ユーティリティ
# ──────────────────────────────────────────────
def search_transcripts(transcript_dir: str, keywords: list[str]):
    """
    取得済みの文字起こしテキストにキーワードで全文検索をかける。
    例: search_transcripts("youtube_transcripts", ["インプラント", "ホワイトニング"])
    """
    print(f"\n🔍 キーワード検索: {keywords}")
    print(f"   対象フォルダ: {transcript_dir}/\n")

    hits = []
    txt_files = list(Path(transcript_dir).glob("*.txt"))
    print(f"   検索対象: {len(txt_files)} ファイル\n")

    for txt_file in txt_files:
        try:
            content = txt_file.read_text(encoding="utf-8")
            matched_keywords = [kw for kw in keywords if kw in content]
            if matched_keywords:
                # タイトルをヘッダーから抽出
                lines = content.split("\n")
                title = lines[0].replace("# ", "").strip() if lines else txt_file.stem
                url_line = next((l for l in lines if l.startswith("URL:")), "")
                url = url_line.replace("URL:", "").strip()

                hits.append({
                    "ファイル": txt_file.name,
                    "タイトル": title,
                    "URL": url,
                    "ヒットキーワード": ", ".join(matched_keywords),
                })
                print(f"  🎯 {title[:60]}")
                print(f"     キーワード: {matched_keywords}")
                print(f"     URL: {url}\n")
        except Exception as e:
            print(f"  ⚠️ 読み込みエラー: {txt_file.name} ({e})")

    print(f"検索結果: {len(hits)} 件ヒット")
    return hits


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="YouTubeチャンネルの全動画リストと文字起こしを一括取得するスクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # チャンネルの全動画リスト取得 + 字幕取得（一括）
  uv run youtube_channel_extractor.py --channel "https://www.youtube.com/@YourChannel/videos"

  # 動画リスト取得のみ（字幕は後で）
  uv run youtube_channel_extractor.py --channel "https://www.youtube.com/@YourChannel/videos" --list-only

  # 既存CSVから字幕だけ取得
  uv run youtube_channel_extractor.py --from-csv youtube_videos.csv

  # キーワード検索（文字起こし済みテキストを横断検索）
  uv run youtube_channel_extractor.py --search "インプラント,ホワイトニング"
        """,
    )

    parser.add_argument("--channel", help="YouTubeチャンネルのURL（例: https://www.youtube.com/@channel/videos）")
    parser.add_argument("--from-csv", metavar="CSV_FILE", help="既存の動画リストCSVから字幕取得を再開する")
    parser.add_argument("--list-only", action="store_true", help="動画リストのCSV作成のみ（字幕取得はしない）")
    parser.add_argument("--search", metavar="KEYWORDS", help="カンマ区切りのキーワードで文字起こしテキストを検索する")
    parser.add_argument("--output-csv", default=OUTPUT_CSV, help=f"動画リストCSVのファイル名（デフォルト: {OUTPUT_CSV}）")
    parser.add_argument("--transcript-dir", default=TRANSCRIPT_DIR, help=f"文字起こし保存フォルダ（デフォルト: {TRANSCRIPT_DIR}）")
    parser.add_argument("--summary-csv", default=SUMMARY_CSV, help=f"字幕取得ログCSV（デフォルト: {SUMMARY_CSV}）")

    args = parser.parse_args()

    # ── キーワード検索モード ──
    if args.search:
        keywords = [kw.strip() for kw in args.search.split(",") if kw.strip()]
        results = search_transcripts(args.transcript_dir, keywords)
        if results:
            out_csv = "keyword_search_results.csv"
            with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["ファイル", "タイトル", "URL", "ヒットキーワード"])
                writer.writeheader()
                writer.writerows(results)
            print(f"   💾 検索結果を保存しました: {out_csv}")
        return

    # ── チャンネルURLから開始するモード ──
    if args.channel:
        videos = fetch_video_list(args.channel, args.output_csv)
        if not videos:
            return
        if not args.list_only:
            fetch_all_transcripts(videos, args.transcript_dir, args.summary_csv)
        return

    # ── 既存CSVから字幕取得を再開するモード ──
    if args.from_csv:
        csv_path = args.from_csv
        if not os.path.exists(csv_path):
            print(f"❌ CSVファイルが見つかりません: {csv_path}")
            sys.exit(1)

        videos = []
        with open(csv_path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                videos.append(row)
        print(f"📂 CSVから {len(videos)} 本の動画情報を読み込みました。")
        fetch_all_transcripts(videos, args.transcript_dir, args.summary_csv)
        return

    # 引数なしの場合はヘルプを表示
    parser.print_help()


if __name__ == "__main__":
    main()
