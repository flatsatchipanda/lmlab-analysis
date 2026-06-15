#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_silo_triage_v2.py  (改訂版)
-----------------------
total_site_mapping_master.csv を読み込み、サイロ型サイト構造の
トリアージ判定と統合先URLを自動付与して total_site_mapping_final_v2.csv に保存する。

【サイロ構造】
  インプラント        : nakanodent.com/implant/
    ← implantsalon.jp, okayama-all-on-4.com
  矯正歯科            : nakanodent.com/orthodontic/
    ← kyousei-smile.com
  審美・ホワイトニング : nakanodent.com/white/
    ← white-style.jp
  精密入れ歯          : nakanodent.com/denture/
    ← 11ireba.com
"""

import csv
import re
import urllib.parse
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────
INPUT_FILE  = Path(__file__).parent / "total_site_mapping_master.csv"
OUTPUT_FILE = Path(__file__).parent / "total_site_mapping_final_v2.csv"
BASE_URL    = "https://nakanodent.com"

# 専門サイト → サイロ親パス
DOMAIN_TO_SILO = {
    "implantsalon.jp":      "/implant/",
    "okayama-all-on-4.com": "/implant/",
    "kyousei-smile.com":    "/orthodontic/",
    "white-style.jp":       "/white/",
    "11ireba.com":          "/denture/",
}

# ─────────────────────────────────────────────────────────────
# 共通ページ判定ルール
# 専門サイトのこれらパスは本院の既存ページへ集約
# (check_fn, 本院の対応URL)
# ─────────────────────────────────────────────────────────────
# ※ パスは小文字化済みの path_lower で評価
COMMON_PAGE_RULES = [
    # アクセス
    (lambda p: "access" in p.strip("/").split("/"),
     f"{BASE_URL}/c-ndc/access/"),
    # FAQ / Q&A
    (lambda p: any(x in p for x in ("/faq", "/qa/")),
     f"{BASE_URL}/c-solve/faq/"),
    # 料金・価格
    (lambda p: any(x in p for x in ("/price", "/cost/", "/menu/")),
     f"{BASE_URL}/c-price/"),
    # スタッフ・院長紹介（数値プレフィックス含む: 006staff, 007member）
    (lambda p: any(x in p for x in ("/director", "/member", "/staff")),
     f"{BASE_URL}/c-ndc/c-staff/"),
    # 初診・カウンセリング・相談
    (lambda p: any(x in p for x in ("/first-counseling", "/counseling", "/consult")),
     f"{BASE_URL}/c-solve/counseling/"),
    # メール・お問い合わせ・予約
    (lambda p: any(x in p for x in ("/mail", "/appoint")),
     f"{BASE_URL}/c-contact/mail/"),
    # 院内見学・ガイド・ツアー
    (lambda p: any(x in p for x in ("/guide", "/tour")),
     f"{BASE_URL}/c-ndc/c-salon/guide/"),
    # ニュース
    (lambda p: "/news" in p,
     f"{BASE_URL}/c-ndc/news/"),
    # 診断
    (lambda p: any(x in p for x in ("/diagnosis", "/choices")),
     f"{BASE_URL}/c-solve/diagnosis/"),
    # プレゼント
    (lambda p: "/present" in p,
     f"{BASE_URL}/c-solve/"),
    # 静脈内鎮静
    (lambda p: "/sedation" in p,
     f"{BASE_URL}/c-treatment/sedation/"),
    # 冊子・資料
    (lambda p: "/booklet" in p,
     f"{BASE_URL}/c-solve/"),
]

# 11ireba.com 専用：数値プレフィックスを持つパスのスラッグ変換テーブル
# /001superireb/ → superireb 等、先頭数字+スラッグ形式を辞書で管理
# ※ 共通ページルールに合致しないものだけここへ来る
IREBA_SLUG_MAP = {
    "001superireb": "superireb",
    "002difference": "difference",
    "003medical":   "medical",
    "004treatment": "treatment",
    "005dental":    "dental",
    "006staff":     "staff",     # → 共通ページルールで処理される
    "007member":    "member",    # → 共通ページルールで処理される
    "008inquiry":   "inquiry",   # → 共通ページルールで処理される
    "012all-on-4":  "all-on-4",
    "013mini":      "mini",
    "014smiledenture": "smiledenture",
}

# ─────────────────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────────────────

def strip_numeric_prefix(slug: str) -> str:
    """
    '006staff' → 'staff', '012All-on-4' → 'all-on-4' のように
    先頭の数字列を除去して小文字化する。
    数字のみのスラッグ（例: '123'）は空文字を返す。
    """
    cleaned = re.sub(r'^\d+', '', slug).lower()
    return cleaned


def build_silo_url(silo_path: str, page_path: str, domain: str = "") -> str:
    """
    専門サイトのパスをサイロ配下のURLへ変換する。

    変換ルール:
    1. /c-xxx/yyy/  → silo + yyy/   （c-プレフィックスの親ディレクトリを除去）
    2. /c-xxx/      → silo           （c-親ディレクトリのみ = サイロルート）
    3. /yyy/        → silo + yyy/    （プレフィックスなし、そのまま結合）
       ただし 11ireba の数値プレフィックスは strip_numeric_prefix で除去

    例:
      /c-implant/all-on-4/  → /implant/all-on-4/
      /c-solve/             → /implant/
      /denture/             → /denture/          ← 11ireba の /denture/ はサイロ名と同名
      /006staff/            → /denture/staff/    ← 数値除去
      /reason/              → /denture/reason/
    """
    parts = [p for p in page_path.split("/") if p]

    if not parts:
        return f"{BASE_URL}{silo_path}"

    # ① 先頭が c-xxx 形式 → 親ディレクトリとして除去
    if parts[0].startswith("c-"):
        parts = parts[1:]
    # ② 先頭が数字開始スラッグ（11ireba 方式） → 数字プレフィックス除去
    elif re.match(r'^\d', parts[0]):
        cleaned = strip_numeric_prefix(parts[0])
        if cleaned:
            parts[0] = cleaned
        else:
            parts = parts[1:]  # 数字のみ → 除去

    if not parts:
        return f"{BASE_URL}{silo_path}"

    # サイロ名と同名のスラッグは重複しないよう除去
    # 例: silo_path="/denture/", parts[0]="denture" → そのままサイロルートへ
    silo_name = silo_path.strip("/")
    if len(parts) == 1 and parts[0].lower() == silo_name.lower():
        return f"{BASE_URL}{silo_path}"

    sub = "/".join(p.lower() for p in parts) + "/"
    return f"{BASE_URL}{silo_path}{sub}"


# ─────────────────────────────────────────────────────────────
# トリアージ ロジック
# ─────────────────────────────────────────────────────────────

def triage_nakanodent(row: dict) -> tuple[str, str]:
    """本院 nakanodent.com 行のトリアージを返す (interim_triage, redirect_to_url)"""
    url         = row["url"]
    status      = str(row["status"]).strip()
    file_status = row["file_status"].strip()

    # 1. ステータス異常
    if status != "200":
        return "削除または要確認", ""

    # 2. /c-treat/ → /c-treatment/ 正規化（重複パス解消）
    if "/c-treat/" in url:
        normalized = url.replace("/c-treat/", "/c-treatment/")
        return "統合（正規化）", normalized

    # 3. file_status が要確認（ファイル名フラグ）
    if "要確認" in file_status:
        return "維持・要確認", ""

    # 4. 正常ページ
    return "維持・部分更新", ""


def triage_specialist(row: dict, silo_path: str) -> tuple[str, str]:
    """専門サイト行のトリアージを返す (interim_triage, redirect_to_url)"""
    url         = row["url"]
    status      = str(row["status"]).strip()
    file_status = row["file_status"].strip()
    domain      = row["domain"].strip()
    parsed      = urllib.parse.urlparse(url)
    path        = parsed.path   # 例: /c-implant/all-on-4/

    # 1. ステータス異常 or 要確認
    if status != "200" or "要確認" in file_status:
        return "削除", ""

    # 2. トップページ
    if path in ("/", ""):
        return "統合（ピラー化）", f"{BASE_URL}{silo_path}"

    path_lower = path.lower()

    # 3. 共通ページ（本院に集約）
    for check_fn, main_url in COMMON_PAGE_RULES:
        if check_fn(path_lower):
            return "削除（本院へ集約）", main_url

    # 4. 下層ページ → サイロ配下へ統合
    silo_url = build_silo_url(silo_path, path, domain)
    return "統合", silo_url


# ─────────────────────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────────────────────

def main():
    print(f"Reading: {INPUT_FILE}")
    with open(INPUT_FILE, encoding="utf-8-sig", newline="") as f:
        reader     = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows       = list(reader)

    print(f"Total rows: {len(rows)}")

    triage_counts: dict[str, int] = {}
    processed = []

    for row in rows:
        domain = row["domain"].strip()

        if domain == "nakanodent.com":
            triage, redirect = triage_nakanodent(row)
        elif domain in DOMAIN_TO_SILO:
            silo_path = DOMAIN_TO_SILO[domain]
            triage, redirect = triage_specialist(row, silo_path)
        else:
            triage, redirect = "要確認（未知ドメイン）", ""

        row["interim_triage"]  = triage
        row["redirect_to_url"] = redirect
        triage_counts[triage]  = triage_counts.get(triage, 0) + 1
        processed.append(row)

    # ── 保存 ──
    print(f"\nWriting: {OUTPUT_FILE}")
    with open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(processed)

    # ── 全体サマリー ──
    print("\n" + "=" * 58)
    print("  トリアージ判定 件数サマリー")
    print("=" * 58)
    total = 0
    for label, count in sorted(triage_counts.items(), key=lambda x: -x[1]):
        print(f"  {label:<28} : {count:>4} 件")
        total += count
    print("-" * 58)
    print(f"  {'合計':<28} : {total:>4} 件")
    print("=" * 58)

    # ── ドメイン別サマリー ──
    print("\nドメイン別 判定内訳:")
    domain_order = [
        "nakanodent.com",
        "implantsalon.jp",
        "okayama-all-on-4.com",
        "kyousei-smile.com",
        "white-style.jp",
        "11ireba.com",
    ]
    domain_triage: dict[str, dict[str, int]] = {}
    for row in processed:
        d = row["domain"]
        t = row["interim_triage"]
        domain_triage.setdefault(d, {})
        domain_triage[d][t] = domain_triage[d].get(t, 0) + 1

    for d in domain_order:
        if d not in domain_triage:
            continue
        counts = domain_triage[d]
        sub = sum(counts.values())
        print(f"\n  [{d}]  計 {sub} 件")
        for t, c in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"    {t:<28} : {c:>4} 件")

    print(f"\n✅ 完了: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
