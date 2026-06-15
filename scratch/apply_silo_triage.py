"""
apply_silo_triage.py
====================
total_site_mapping_master.csv を読み込み、
サイロ型サイト構造に基づいてトリアージ判定と統合先URLを自動付与し、
total_site_mapping_final.csv として保存するスクリプト。

【サイロ定義】
  インプラント    : nakanodent.com/c-treatment/implant/
  矯正歯科       : nakanodent.com/c-treatment/orthodontic/
  審美・ホワイトニング: nakanodent.com/c-treatment/white/
  精密入れ歯     : nakanodent.com/c-treatment/denture/

【ドメインとサイロの対応】
  implantsalon.jp          → /c-treatment/implant/
  okayama-all-on-4.com     → /c-treatment/implant/
  kyousei-smile.com        → /c-treatment/orthodontic/
  white-style.jp           → /c-treatment/white/
  11ireba.com              → /c-treatment/denture/
"""

import re
import pandas as pd
from urllib.parse import urlparse

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────

INPUT_CSV  = "total_site_mapping_master.csv"
OUTPUT_CSV = "total_site_mapping_final.csv"
BASE_URL   = "https://nakanodent.com"

# 各専門サイトとサイロ親パスの対応
DOMAIN_SILO_MAP = {
    "implantsalon.jp":       "/c-treatment/implant/",
    "okayama-all-on-4.com":  "/c-treatment/implant/",
    "kyousei-smile.com":     "/c-treatment/orthodontic/",
    "white-style.jp":        "/c-treatment/white/",
    "11ireba.com":           "/c-treatment/denture/",
}

# ─────────────────────────────────────────────
# 「共通ページ」判定キーワード → 本院の既存共通ページにリダイレクト
# 対象: 料金・アクセス・FAQ・お問い合わせ・相談 等
# ─────────────────────────────────────────────
COMMON_PAGE_RULES = [
    # (urlパターン正規表現, 統合先パス, 判定ラベル)
    (r"/(c-clinic/price|salon/cost|menu|price)/",
     "/c-user/",
     "削除（本院へ集約）"),
    (r"/(access|guide|c-salon/guide)/",
     "/c-contact/",
     "削除（本院へ集約）"),
    (r"/(c-solve/faq|qa|faq)/",
     "/c-treatment/qa/",
     "削除（本院へ集約）"),
    (r"/(c-solve/mail|mail|c-contact/mail|c-solve/counseling|counseling|c-solve/first-counseling|first-counseling|appoint|008inquiry)/",
     "/c-contact/mail/",
     "削除（本院へ集約）"),
    (r"/(c-solve/diagnosis|diagnosis)/",
     "/c-contact/",
     "削除（本院へ集約）"),
    (r"/(c-salon/director|director|006staff|staff)/",
     "/c-ndc/c-staff/",
     "削除（本院へ集約）"),
    (r"/(c-salon/sedation|sedation)/",
     "/c-treatment/painless/",
     "削除（本院へ集約）"),
    (r"/(c-solve/choices|choices)/",
     "/c-treatment/implant/",
     "削除（本院へ集約）"),
    (r"/(c-solve/present|present)/",
     "/c-contact/",
     "削除（本院へ集約）"),
    (r"/(c-solve|c-clinic/news|tour|007member|member|reason|c-clinic/itero)/",
     "/c-ndc/",
     "削除（本院へ集約）"),
    (r"/(c-salon/consult|consult)/",
     "/c-contact/",
     "削除（本院へ集約）"),
    (r"/(c-solve/booklet|booklet)/",
     "/c-contact/",
     "削除（本院へ集約）"),
    (r"/(c-solve/knowledge|knowledge)/",
     "/c-ndc/c-staff/column/",
     "削除（本院へ集約）"),
    (r"/(c-clinic/news)/",
     "/c-ndc/c-staff/column/",
     "削除（本院へ集約）"),
    (r"/(invisalign)/",
     "/c-treatment/orthodontic/",
     "統合"),
]

# ─────────────────────────────────────────────
# 診療コンテンツ（本院サイロへ統合）のパス判定
# 専門サイトの治療ページキーワード
# ─────────────────────────────────────────────
TREATMENT_PATTERNS = [
    r"/c-implant/",
    r"/c-orthodontics/",
    r"/c-treatment/",
    r"/denture",
    r"/[0-9]+[a-z]+/",          # 11ireba.com 式のパス (e.g. /001superireb/, /002difference/)
]

# ─────────────────────────────────────────────
# nakanodent.com の診療ページ判定
# ─────────────────────────────────────────────
NAKANO_TREATMENT_PATHS = ["/c-treatment/"]
NAKANO_STATUS_ERROR_LABEL = "削除（または要リダイレクト確認）"


def get_url_path(url: str) -> str:
    """URLからパス部分のみを取得"""
    return urlparse(url).path


def is_top_page(path: str) -> bool:
    """トップページ（/）か判定"""
    return path.rstrip("/") == "" or path == "/"


def classify_common_page(path: str) -> tuple[str, str] | None:
    """
    共通ページ（料金/アクセス/FAQ等）に該当するかチェック。
    該当した場合は (triage, redirect_path) を返す。該当しない場合は None。
    """
    for pattern, redirect_path, label in COMMON_PAGE_RULES:
        if re.search(pattern, path):
            return label, redirect_path
    return None


def is_treatment_page(path: str) -> bool:
    """専門サイトの治療・診療コンテンツページかどうか判定"""
    for pat in TREATMENT_PATTERNS:
        if re.search(pat, path):
            return True
    return False


def build_integrated_url(path: str, silo_base: str) -> str:
    """
    専門サイトのパスをサイロベースに結合して統合先URLを生成。
    例: /c-implant/all-on-4/ + /c-treatment/implant/ → /c-treatment/implant/all-on-4/
    """
    # c-implant/ / c-orthodontics/ / c-treatment/ などのプレフィックスを除去
    clean = re.sub(
        r"^/(c-implant|c-orthodontics|c-treatment|c-solve|c-salon|c-clinic)/",
        "/",
        path,
    )
    # silo_base の末尾スラグとcleanの先頭が同一になる場合はサイロトップに統合
    # 例: silo=/c-treatment/denture/ かつ clean=/denture/ → /c-treatment/denture/
    silo_leaf = silo_base.rstrip("/").split("/")[-1]  # e.g. "denture"
    clean_stripped = clean.strip("/")
    if clean_stripped == silo_leaf:
        return BASE_URL + silo_base
    # /の重複を整理
    merged = silo_base.rstrip("/") + "/" + clean.lstrip("/")
    merged = re.sub(r"/+", "/", merged)
    return BASE_URL + merged


def classify_specialty_url(row: pd.Series, silo_base: str) -> tuple[str, str]:
    """
    専門サイトの1行を受け取り、(interim_triage, redirect_to_url) を返す。
    """
    url = row["url"]
    status = row["status"]
    file_status = str(row["file_status"]).strip()
    path = get_url_path(url)

    # ① statusが200以外、または file_status が「要確認」
    if str(status) != "200" or "要確認" in file_status:
        return "削除", ""

    # ② トップページ（/）
    if is_top_page(path):
        return "統合", BASE_URL + silo_base

    # ③ 共通ページ判定（料金/アクセス/FAQ等）
    common = classify_common_page(path)
    if common:
        label, redirect_path = common
        return label, BASE_URL + redirect_path

    # ④ 診療コンテンツページ（サイロ配下に統合）
    if is_treatment_page(path):
        return "統合", build_integrated_url(path, silo_base)

    # ⑤ その他（分類しきれないページはデフォルト統合扱い）
    return "統合", build_integrated_url(path, silo_base)


def classify_nakanodent_url(row: pd.Series) -> tuple[str, str]:
    """
    nakanodent.com の1行を受け取り、(interim_triage, redirect_to_url) を返す。
    """
    url = row["url"]
    status = row["status"]
    path = get_url_path(url)

    # status が 200 以外
    if str(status) != "200":
        return NAKANO_STATUS_ERROR_LABEL, ""

    # 診療ページ（/c-treatment/ 配下）
    for t in NAKANO_TREATMENT_PATHS:
        if path.startswith(t) and path.rstrip("/") != t.rstrip("/"):
            return "全面リライト", url  # 既存URLは維持

    # 主要カテゴリトップ
    if any(path.startswith(p) for p in NAKANO_TREATMENT_PATHS):
        return "部分更新", url

    # それ以外（ブログ・FAQ・採用 etc.）
    return "現状維持", url


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────

def main():
    print(f"読み込み中: {INPUT_CSV}")
    df = pd.read_csv(INPUT_CSV)

    # 既存列をリセット
    df["interim_triage"]   = ""
    df["redirect_to_url"]  = ""

    results = []

    for idx, row in df.iterrows():
        domain = str(row["domain"]).strip()

        if domain in DOMAIN_SILO_MAP:
            silo_base = DOMAIN_SILO_MAP[domain]
            triage, redirect = classify_specialty_url(row, silo_base)
        elif domain == "nakanodent.com":
            triage, redirect = classify_nakanodent_url(row)
        else:
            triage, redirect = "要確認", ""

        df.at[idx, "interim_triage"]  = triage
        df.at[idx, "redirect_to_url"] = redirect
        results.append(triage)

    # ─── 保存 ───
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n保存完了: {OUTPUT_CSV}")

    # ─── サマリー ───
    triage_counts = df["interim_triage"].value_counts()
    total = len(df)
    print(f"\n{'='*50}")
    print(f"  トリアージ判定サマリー  (総URL数: {total})")
    print(f"{'='*50}")
    for label, count in triage_counts.items():
        pct = count / total * 100
        print(f"  {label:<30} {count:>4} 件  ({pct:.1f}%)")
    print(f"{'='*50}")

    # ─── ドメイン別 × 判定別クロス集計 ───
    print("\nドメイン別 × 判定別内訳:")
    cross = pd.crosstab(df["domain"], df["interim_triage"])
    print(cross.to_string())

    # ─── 統合URL が確定した専門サイト件数 ───
    specialty_domains = list(DOMAIN_SILO_MAP.keys())
    merged = df[df["domain"].isin(specialty_domains) & (df["interim_triage"] == "統合")]
    print(f"\n統合URLが確定した専門サイトページ数: {len(merged)} 件")

    # ─── サンプル出力 ───
    print("\n【統合サンプル（各ドメイン最初の3件）】")
    for domain in specialty_domains:
        sample = df[(df["domain"] == domain) & (df["interim_triage"] == "統合")].head(3)
        if len(sample):
            print(f"\n  {domain}:")
            for _, r in sample.iterrows():
                print(f"    {r['url']}")
                print(f"    → {r['redirect_to_url']}")


if __name__ == "__main__":
    main()
