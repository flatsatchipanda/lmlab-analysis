#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
geo_cluster_mapping.py
----------------------
GEOクエリデータベース（44クラスター/2,658クエリ）を使い、
6サイト773URLをセマンティック・クラスタリングして
semantic_clustered_mapping_final.csv を出力する。

マッチングロジック: Jaccard係数 + 部分文字列スコアの加重平均
"""

import re
import os
import unicodedata
from pathlib import Path
import pandas as pd

# ─────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
INPUT_CSV  = BASE_DIR / "total_site_mapping_master.csv"
QUERY_DB   = BASE_DIR / "geo_query_db.xlsx"
TEXT_DIR   = BASE_DIR / "bucket1_text_assets"
OUTPUT_CSV = BASE_DIR / "semantic_clustered_mapping_final.csv"
BASE_URL   = "https://nakanodent.com"

C_TREAT_PATTERN = re.compile(r'/c-treat/')


# ─────────────────────────────────────────────────────────────
# ステップ1: GEOクエリDBをロード → {cluster_id: [query, ...]} 辞書
# ─────────────────────────────────────────────────────────────
def load_query_db(xlsx_path: Path) -> dict[str, list[str]]:
    xl = pd.ExcelFile(xlsx_path)
    cluster_sheets = [s for s in xl.sheet_names if re.match(r'C\d+_', s)]
    clusters: dict[str, list[str]] = {}
    for sheet in cluster_sheets:
        df = pd.read_excel(xlsx_path, sheet_name=sheet)
        query_col = df['Unnamed: 3']
        header_positions = query_col[query_col == 'クエリ'].index
        if len(header_positions) == 0:
            continue
        start = header_positions[0] + 1
        queries = [str(q).strip() for q in query_col.iloc[start:].dropna() if str(q).strip()]
        # sheet name like "C01_マウスピース矯正・基礎理解"
        cluster_id = sheet
        clusters[cluster_id] = queries
    return clusters


# ─────────────────────────────────────────────────────────────
# ステップ2: テキストからトークンセットを抽出
# ─────────────────────────────────────────────────────────────
def tokenize(text: str) -> set[str]:
    """日本語・英数字を2文字以上のN-gramとスペース区切りトークンに分割"""
    if not text or pd.isna(text):
        return set()
    text = str(text).lower()
    # スペース区切りトークン
    tokens = set(re.findall(r'[a-zA-Z0-9぀-鿿＀-￿]+', text))
    # 2文字bigram（日本語用）
    clean = re.sub(r'\s+', '', text)
    bigrams = {clean[i:i+2] for i in range(len(clean) - 1) if len(clean[i:i+2]) == 2}
    return tokens | bigrams


def score_url_vs_cluster(url_tokens: set[str], cluster_queries: list[str]) -> float:
    """URLトークンとクラスターのクエリ群のスコアを計算"""
    if not url_tokens or not cluster_queries:
        return 0.0

    scores = []
    for query in cluster_queries:
        q_tokens = tokenize(query)
        if not q_tokens:
            continue
        # Jaccard係数
        intersection = len(url_tokens & q_tokens)
        union = len(url_tokens | q_tokens)
        jaccard = intersection / union if union > 0 else 0.0
        # 部分マッチボーナス: クエリのトークンが全部URLに含まれるか
        coverage = intersection / len(q_tokens) if q_tokens else 0.0
        scores.append(0.4 * jaccard + 0.6 * coverage)

    if not scores:
        return 0.0
    # 上位5スコアの平均（ノイズ軽減）
    top = sorted(scores, reverse=True)[:5]
    return sum(top) / len(top)


# ─────────────────────────────────────────────────────────────
# ステップ3: URLからテキストを構築
# ─────────────────────────────────────────────────────────────
def build_url_text(row: pd.Series) -> str:
    """title, h1, h2, URLパスを結合してマッチング用テキストを作成"""
    parts = []
    url = str(row.get('url', ''))
    # URLパスから意味的なセグメントを抽出
    path = re.sub(r'https?://[^/]+', '', url).replace('-', ' ').replace('_', ' ').replace('/', ' ')
    parts.append(path)
    for col in ['title', 'h1', 'h2_headings']:
        val = row.get(col, '')
        if val and not pd.isna(val):
            parts.append(str(val))
    return ' '.join(parts)


def load_text_asset(url: str) -> str:
    """URLに対応するマークダウンファイルを読み込む"""
    # URL → ファイル名変換 (nakanodent.com/path/ → nakanodent.com_path_.md)
    clean = re.sub(r'https?://', '', url).rstrip('/')
    filename = clean.replace('/', '_') + '_.md'
    filepath = TEXT_DIR / filename
    if filepath.exists():
        try:
            text = filepath.read_text(encoding='utf-8')
            # H1/H2見出しとテキスト先頭部分のみ使用（速度最適化）
            lines = text.split('\n')
            relevant = [l for l in lines if l.startswith('#') or (l and len(l) < 80)]
            return ' '.join(relevant[:50])
        except Exception:
            pass
    return ''


# ─────────────────────────────────────────────────────────────
# ステップ4: トリアージ判定ルール
# ─────────────────────────────────────────────────────────────
DOMAIN_TO_SILO = {
    "implantsalon.jp":      "/implant/",
    "okayama-all-on-4.com": "/implant/",
    "kyousei-smile.com":    "/orthodontic/",
    "white-style.jp":       "/white/",
    "11ireba.com":          "/denture/",
}

COMMON_PAGE_PATTERNS = [
    (r'/access',        f"{BASE_URL}/c-ndc/access/"),
    (r'/faq|/qa/',      f"{BASE_URL}/c-solve/faq/"),
    (r'/price|/cost/|/menu/', f"{BASE_URL}/c-price/"),
    (r'/director|/member|/staff', f"{BASE_URL}/c-ndc/c-staff/"),
    (r'/first-counseling|/counseling|/consult', f"{BASE_URL}/c-solve/counseling/"),
    (r'/mail|/appoint', f"{BASE_URL}/c-contact/mail/"),
    (r'/guide|/tour',   f"{BASE_URL}/c-ndc/c-salon/guide/"),
    (r'/news',          f"{BASE_URL}/c-ndc/news/"),
    (r'/diagnosis|/choices', f"{BASE_URL}/c-solve/diagnosis/"),
]


def is_common_page(url: str, domain: str) -> tuple[bool, str]:
    if domain == 'nakanodent.com':
        return False, ''
    path = re.sub(r'https?://[^/]+', '', url).lower()
    for pattern, redirect in COMMON_PAGE_PATTERNS:
        if re.search(pattern, path):
            return True, redirect
    return False, ''


# ─────────────────────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────────────────────
def main():
    print("=== GEOクラスタリング・マッピング開始 ===\n")

    # 1. クエリDB読み込み
    print("1. GEOクエリDB読み込み中...")
    clusters = load_query_db(QUERY_DB)
    total_queries = sum(len(q) for q in clusters.values())
    print(f"   クラスター数: {len(clusters)}, 総クエリ数: {total_queries:,}")

    # クラスターごとのトークンセットをキャッシュ（速度最適化）
    cluster_tokens_cache: dict[str, list[set[str]]] = {}
    for cid, queries in clusters.items():
        cluster_tokens_cache[cid] = [tokenize(q) for q in queries]

    # 2. マスターCSV読み込み
    print("\n2. マスターCSV読み込み中...")
    df = pd.read_csv(INPUT_CSV)
    print(f"   総URL数: {len(df):,}")

    # 3. 処理
    print("\n3. 各URLを処理中...")
    results = []
    c_treat_normalized = 0

    for idx, row in df.iterrows():
        if idx % 100 == 0:
            print(f"   {idx}/{len(df)} 処理中...")

        url     = str(row.get('url', ''))
        domain  = str(row.get('domain', ''))
        status  = row.get('status', 0)
        fstatus = str(row.get('file_status', ''))

        result = row.to_dict()
        result['topic_cluster']   = ''
        result['cluster_score']   = 0.0
        result['interim_triage']  = ''
        result['redirect_to_url'] = ''

        # ── 処理2: /c-treat/ 正規化 ──
        if domain == 'nakanodent.com' and C_TREAT_PATTERN.search(url):
            new_url = C_TREAT_PATTERN.sub('/c-treatment/', url)
            result['redirect_to_url'] = new_url
            result['interim_triage']  = '統合（正規化）'
            c_treat_normalized += 1
            results.append(result)
            continue

        # ── エラーURL ──
        if status not in (200, '200'):
            result['interim_triage'] = '削除または要確認'
            results.append(result)
            continue

        # ── 共通ページ（専門サイト） ──
        is_common, redirect_url = is_common_page(url, domain)
        if is_common:
            result['interim_triage']  = '削除（本院へ集約）'
            result['redirect_to_url'] = redirect_url
            results.append(result)
            continue

        # ── 処理3: セマンティック・クラスタリング ──
        base_text = build_url_text(row)
        asset_text = load_text_asset(url)
        full_text = base_text + ' ' + asset_text
        url_tokens = tokenize(full_text)

        best_cluster = ''
        best_score   = 0.0
        for cid, query_list in clusters.items():
            score = score_url_vs_cluster(url_tokens, query_list)
            if score > best_score:
                best_score   = score
                best_cluster = cid

        result['topic_cluster'] = best_cluster
        result['cluster_score'] = round(best_score, 4)

        # ── 処理4: トリアージ判定 ──
        if fstatus == '要確認（ファイル名フラグ）' or '要確認' in fstatus:
            result['interim_triage'] = '要確認'
        elif domain != 'nakanodent.com':
            # 専門サイトのコンテンツページ → 後でカニバリ判定
            silo = DOMAIN_TO_SILO.get(domain, '')
            result['redirect_to_url'] = f"{BASE_URL}{silo}" if silo else ''
            result['interim_triage']  = 'モジュールとして集約（暫定）'
        else:
            result['interim_triage'] = '維持・部分更新'

        results.append(result)

    # 4. カニバリ判定: 同クラスターの複数URL → ピラー/モジュール決定
    print("\n4. カニバリ判定（クラスター内ピラー選定）...")
    result_df = pd.DataFrame(results)

    # nakanodent.com以外のドメインで、同クラスター内のURL群を集約判定
    spec_mask = result_df['domain'] != 'nakanodent.com'
    spec_df   = result_df[spec_mask & (result_df['topic_cluster'] != '')]

    # クラスターごとにグループ化
    for cluster_id, group in spec_df.groupby('topic_cluster'):
        if len(group) <= 1:
            continue
        # スコア最大 or URL最長（コンテンツが豊富な想定）をピラーに
        best_idx = group['cluster_score'].idxmax()
        best_url = group.loc[best_idx, 'url']
        # ピラーのredirect_to_urlは本院の対応URLのまま
        result_df.loc[best_idx, 'interim_triage'] = 'ピラーとして統合/リライト'
        # 他はそのピラーURLに集約
        for idx2, row2 in group.iterrows():
            if idx2 == best_idx:
                continue
            result_df.loc[idx2, 'interim_triage']  = 'モジュールとして集約'
            result_df.loc[idx2, 'redirect_to_url'] = best_url

    # 5. CSV出力
    print(f"\n5. CSV出力: {OUTPUT_CSV}")
    cols_order = [
        'domain', 'url', 'status', 'title', 'h1', 'h2_headings',
        'file_status', 'topic_cluster', 'cluster_score',
        'interim_triage', 'redirect_to_url'
    ]
    # 存在する列だけ
    cols_order = [c for c in cols_order if c in result_df.columns]
    result_df[cols_order].to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')

    # ─────────────────────────────────────────────────────────
    # 報告
    # ─────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("【処理サマリー】")
    print(f"  総処理件数        : {len(result_df):,} 件")
    print(f"  /c-treat/ 正規化  : {c_treat_normalized} 件")

    print("\n【トリアージ内訳】")
    triage_counts = result_df['interim_triage'].value_counts()
    for triage, cnt in triage_counts.items():
        print(f"  {triage:25s}: {cnt:4d} 件")

    print("\n【カニバリ上位5クラスター（URL集中度）】")
    cluster_counts = (
        result_df[result_df['topic_cluster'] != '']['topic_cluster']
        .value_counts()
        .head(5)
    )
    for cluster, cnt in cluster_counts.items():
        print(f"  {cluster}: {cnt} 件")

    print(f"\n出力完了: {OUTPUT_CSV}")
    print("="*60)


if __name__ == '__main__':
    main()
