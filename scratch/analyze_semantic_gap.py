#!/usr/bin/env python3
"""
SEO/GEO セマンティック・ギャップ分析スクリプト
自社 nakanodent.com と競合・モデリング先の比較分析

利用可能データ:
  自社:        nakanodent.com
  競合:        tanaka-kyousei.com, white-style.jp, www.11ireba.com,
               www.kyousei-smile.com, implantsalon.jp, okayama-all-on-4.com
  モデリング先: www.katsube-dc.com, www.suzukishika.net
"""

import os
import re
import json
from pathlib import Path
from collections import defaultdict, Counter

# ===== 設定 =====
BASE_DIR = Path("/home/satoshi/Projects/lmlab-analysis/crawled_data")
OUTPUT_DIR = Path("/home/satoshi/Projects/lmlab-analysis/reports")
OUTPUT_DIR.mkdir(exist_ok=True)

JISYA = "nakanodent.com"

KYOGAI = [
    "tanaka-kyousei.com",
    "white-style.jp",
    "www.11ireba.com",
    "www.kyousei-smile.com",
    "implantsalon.jp",
    "okayama-all-on-4.com",
]

MODELING = [
    "www.katsube-dc.com",
    "www.suzukishika.net",
]

# ブログ・ニュース系は分析から除外
SKIP_PATTERNS = re.compile(
    r"blog|news|column|recruit|sitemap|contact|privacy|terms|recruit|kyujin|staff_blog|"
    r"2017|2018|2019|2020|2021|2022|2023|2024|2025|2026",
    re.IGNORECASE
)

def read_md(filepath: Path) -> str:
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
        # フロントマターを除去
        if text.startswith("---"):
            end = text.find("\n---\n", 4)
            if end != -1:
                text = text[end + 5:]
        return text
    except Exception:
        return ""

def extract_headings(text: str) -> dict:
    h1 = re.findall(r"^#\s+(.+)", text, re.MULTILINE)
    h2 = re.findall(r"^##\s+(.+)", text, re.MULTILINE)
    h3 = re.findall(r"^###\s+(.+)", text, re.MULTILINE)
    # 表の中のヘッドラインを除外
    h1 = [h.strip() for h in h1 if not h.startswith("|")]
    h2 = [h.strip() for h in h2 if not h.startswith("|")]
    h3 = [h.strip() for h in h3 if not h.startswith("|")]
    return {"h1": h1, "h2": h2, "h3": h3}

def extract_faqs(text: str) -> list:
    """Q: / Q. / 【Q】 / ？で終わる行をFAQ候補として抽出"""
    patterns = [
        r"^Q[\s\:\.：]\s*(.+)",
        r"^【Q[0-9]*】(.+)",
        r"^([^│\|]+？)\s*$",  # ？で終わる行
    ]
    faqs = []
    for pat in patterns:
        found = re.findall(pat, text, re.MULTILINE)
        faqs.extend([f.strip() for f in found if len(f.strip()) > 5])
    return faqs[:20]  # 上位20件

def extract_authority_signals(text: str) -> list:
    """権威性シグナルの抽出: 資格、学会、受賞、掲載、実績数値など"""
    signals = []
    authority_patterns = [
        r"(日本歯科(?:学会|医師会|矯正歯科学会|口腔外科学会|インプラント学会|歯周病学会)[^\s\n。]{0,30})",
        r"((?:専門医|認定医|指導医|会員|所属)[^\n。]{0,40})",
        r"(\d+[,，]?\d*\s*(?:症例|件|名|年以上|年の経験)[^\n。]{0,30})",
        r"((?:テレビ|新聞|雑誌|メディア|取材|掲載)[^\n。]{0,40})",
        r"((?:院長|ドクター|歯科医師)[^\n。]{0,30}(?:講師|講演|執筆|著書|論文)[^\n。]{0,30})",
        r"((?:セカンドオピニオン|他院|難症例)[^\n。]{0,40})",
        r"((?:CTスキャン|マイクロスコープ|歯科用CT|セレック|レーザー)[^\n。]{0,30})",
        r"((?:無料相談|初診カウンセリング|メール相談)[^\n。]{0,30})",
    ]
    for pat in authority_patterns:
        found = re.findall(pat, text)
        signals.extend([f.strip() for f in found])
    return list(set(signals))[:15]

def normalize_heading(h: str) -> str:
    """見出しを正規化して比較しやすくする"""
    h = re.sub(r"[【】〔〕「」『』（）()・\-\s]", "", h)
    h = re.sub(r"[0-9０-９]", "", h)
    return h.lower()

def extract_topics(headings: list) -> set:
    """見出しからトピックキーワードを抽出"""
    topics = set()
    dental_keywords = [
        "インプラント", "矯正", "ホワイトニング", "審美", "予防", "クリーニング",
        "虫歯", "歯周病", "根管", "入れ歯", "義歯", "セラミック", "ジルコニア",
        "マウスピース", "オールオン4", "小児", "子ども", "こども", "親知らず",
        "歯ぎしり", "顎関節", "知覚過敏", "口臭", "歯石", "スケーリング",
        "フッ素", "シーラント", "ブリッジ", "差し歯", "クラウン", "補綴",
        "歯科ドック", "定期検診", "メンテナンス", "リスク", "費用", "料金",
        "保険", "自由診療", "無痛", "痛みない", "麻酔", "笑気", "静脈鎮静",
        "マイクロスコープ", "CT", "レーザー", "ラバーダム", "精密",
        "症例", "実績", "事例", "ビフォー", "アフター",
        "FAQ", "よくある", "流れ", "ステップ", "期間", "保証",
        "院長", "スタッフ", "理念", "こだわり", "特徴", "強み",
        "口コミ", "評判", "声", "体験", "感想",
        "アクセス", "診療時間", "休診", "予約",
    ]
    for h in headings:
        for kw in dental_keywords:
            if kw in h:
                topics.add(kw)
    return topics

def analyze_site(domain: str, skip_blog: bool = True) -> dict:
    """ドメインの全MDファイルを解析"""
    assets_dir = BASE_DIR / domain / "text_assets"
    if not assets_dir.exists():
        print(f"  [SKIP] {domain}: text_assets不存在")
        return {}

    result = {
        "domain": domain,
        "pages": [],
        "all_h2": [],
        "all_h3": [],
        "all_faqs": [],
        "authority_signals": [],
        "topics": set(),
        "page_slugs": [],
    }

    md_files = sorted(assets_dir.glob("*.md"))
    for f in md_files:
        fname = f.name
        if skip_blog and SKIP_PATTERNS.search(fname):
            continue

        text = read_md(f)
        headings = extract_headings(text)
        faqs = extract_faqs(text)
        signals = extract_authority_signals(text)

        result["pages"].append({
            "file": fname,
            "h1": headings["h1"],
            "h2": headings["h2"],
            "h3": headings["h3"],
            "faq_count": len(faqs),
        })
        result["all_h2"].extend(headings["h2"])
        result["all_h3"].extend(headings["h3"])
        result["all_faqs"].extend(faqs)
        result["authority_signals"].extend(signals)
        result["topics"].update(extract_topics(headings["h1"] + headings["h2"] + headings["h3"]))
        result["page_slugs"].append(fname)

    result["topics"] = sorted(result["topics"])
    result["authority_signals"] = list(set(result["authority_signals"]))[:20]
    print(f"  [OK] {domain}: {len(result['pages'])}ページ, H2:{len(result['all_h2'])}, FAQ候補:{len(result['all_faqs'])}")
    return result


# ===== メイン分析 =====
print("=" * 60)
print("SEO/GEO セマンティック・ギャップ分析")
print("=" * 60)

print("\n【1】自社データ読み込み中...")
jisya_data = analyze_site(JISYA)

print("\n【2】競合データ読み込み中...")
kyogai_data = {}
for domain in KYOGAI:
    d = analyze_site(domain)
    if d:
        kyogai_data[domain] = d

print("\n【3】モデリング先データ読み込み中...")
modeling_data = {}
for domain in MODELING:
    d = analyze_site(domain)
    if d:
        modeling_data[domain] = d

# ===== トピック比較分析 =====
print("\n【4】セマンティック・ギャップ分析中...")

jisya_topics = set(jisya_data.get("topics", []))
jisya_h2_set = set(normalize_heading(h) for h in jisya_data.get("all_h2", []))

# 競合が持っていて自社にないトピック
all_kyogai_topics = set()
for d in kyogai_data.values():
    all_kyogai_topics.update(d.get("topics", []))

# モデリング先が持つトピック
all_modeling_topics = set()
for d in modeling_data.values():
    all_modeling_topics.update(d.get("topics", []))

gap_kyogai = all_kyogai_topics - jisya_topics
gap_modeling = all_modeling_topics - jisya_topics
all_gaps = (gap_kyogai | gap_modeling)

print(f"\n  自社トピック数: {len(jisya_topics)}")
print(f"  競合合計トピック数: {len(all_kyogai_topics)}")
print(f"  モデリング先合計トピック数: {len(all_modeling_topics)}")
print(f"  ギャップ（競合にあって自社にない）: {len(gap_kyogai)}")
print(f"  ギャップ（モデリング先にあって自社にない）: {len(gap_modeling)}")

# 競合H2見出しの頻出ランキング
kyogai_h2_counter = Counter()
for d in kyogai_data.values():
    for h in d.get("all_h2", []):
        kyogai_h2_counter[h] += 1

modeling_h2_counter = Counter()
for d in modeling_data.values():
    for h in d.get("all_h2", []):
        modeling_h2_counter[h] += 1

# ===== レポート生成 =====
print("\n【5】レポート生成中...")

# ==== SECTION 1: サイト概要 ====
report_lines = []
report_lines.append("# SEO/GEO セマンティック・ギャップ分析レポート")
report_lines.append(f"\n**自社:** nakanodent.com  \n**分析日:** 2026年6月\n")
report_lines.append("---\n")

# ==== SECTION 2: 各サイト構造サマリー ====
report_lines.append("## 1. 各サイト構造サマリー\n")
report_lines.append("### 1-1. 自社（nakanodent.com）\n")
report_lines.append(f"- 解析ページ数（ブログ除く）: **{len(jisya_data.get('pages', []))}ページ**")
report_lines.append(f"- 検出H2見出し数: **{len(jisya_data.get('all_h2', []))}個**")
report_lines.append(f"- 検出トピック: **{', '.join(sorted(jisya_topics)) or 'なし'}**")
report_lines.append(f"- FAQ候補数: **{len(jisya_data.get('all_faqs', []))}件**\n")

report_lines.append("### 1-2. 競合サイト\n")
report_lines.append("| ドメイン | 解析ページ | H2数 | トピック数 | FAQ候補 |")
report_lines.append("|---|---|---|---|---|")
for domain, d in kyogai_data.items():
    report_lines.append(
        f"| {domain} | {len(d.get('pages',[]))} | {len(d.get('all_h2',[]))} | "
        f"{len(d.get('topics',[]))} | {len(d.get('all_faqs',[]))} |"
    )
report_lines.append("")

report_lines.append("### 1-3. モデリング先サイト\n")
report_lines.append("| ドメイン | 解析ページ | H2数 | トピック数 | FAQ候補 |")
report_lines.append("|---|---|---|---|---|")
for domain, d in modeling_data.items():
    report_lines.append(
        f"| {domain} | {len(d.get('pages',[]))} | {len(d.get('all_h2',[]))} | "
        f"{len(d.get('topics',[]))} | {len(d.get('all_faqs',[]))} |"
    )
report_lines.append("")

# ==== SECTION 3: セマンティック・ギャップ（新規トピック候補） ====
report_lines.append("---\n")
report_lines.append("## 2. セマンティック・ギャップ（自社に追加すべきトピック）\n")

report_lines.append("### 2-1. 競合にあって自社にないトピック（優先度：高）\n")
if gap_kyogai:
    for t in sorted(gap_kyogai):
        # どの競合が持っているか
        holders = [d for d, data in kyogai_data.items() if t in data.get("topics", [])]
        report_lines.append(f"- **{t}** ← {', '.join(holders)}")
else:
    report_lines.append("- なし（自社は競合のトピックを網羅）")
report_lines.append("")

report_lines.append("### 2-2. モデリング先にあって自社にないトピック（参考）\n")
if gap_modeling:
    for t in sorted(gap_modeling):
        holders = [d for d, data in modeling_data.items() if t in data.get("topics", [])]
        report_lines.append(f"- **{t}** ← {', '.join(holders)}")
else:
    report_lines.append("- なし")
report_lines.append("")

# ==== SECTION 4: 競合H2見出し頻出ランキング ====
report_lines.append("---\n")
report_lines.append("## 3. 競合が使う頻出H2見出し（自社比較）\n")
report_lines.append("*競合複数サイトで使われているH2見出し ＝ GEO/AEOで重要な網羅トピック*\n")
report_lines.append("| 見出しテキスト | 競合出現数 | 自社に存在 |")
report_lines.append("|---|---|---|")
for h, cnt in kyogai_h2_counter.most_common(40):
    norm = normalize_heading(h)
    in_jisya = "✅" if any(normalize_heading(jh) == norm for jh in jisya_data.get("all_h2", [])) else "❌ **要追加**"
    report_lines.append(f"| {h} | {cnt} | {in_jisya} |")
report_lines.append("")

# ==== SECTION 5: 各ドメイン別のH2/H3構造 ====
report_lines.append("---\n")
report_lines.append("## 4. 競合サイト別 主要H2/H3見出し構造\n")

for domain, d in kyogai_data.items():
    report_lines.append(f"### {domain}\n")
    for page in d.get("pages", []):
        if page["h2"] or page["h3"]:
            slug = page["file"].replace(f"{domain.replace('www.', '')}_", "").replace(".md", "")
            report_lines.append(f"**[{slug}]**")
            for h2 in page["h2"][:8]:
                report_lines.append(f"  - H2: {h2}")
                # H3はH2の後に続くもの（簡易的）
            for h3 in page["h3"][:5]:
                report_lines.append(f"    - H3: {h3}")
    report_lines.append("")

# ==== SECTION 6: モデリング先の「勝ちパターン」 ====
report_lines.append("---\n")
report_lines.append("## 5. モデリング先の「勝ちパターン」抽出\n")

for domain, d in modeling_data.items():
    report_lines.append(f"### 5-{list(modeling_data.keys()).index(domain)+1}. {domain}\n")

    # ページ構成
    report_lines.append("#### ① ページ構成（サイロ構造）\n")
    for page in d.get("pages", []):
        slug = page["file"].replace(f"{domain.replace('www.', '')}_", "").replace(".md", "")
        if page["h1"]:
            report_lines.append(f"- **{slug}**: {page['h1'][0] if page['h1'] else 'タイトルなし'}")
    report_lines.append("")

    # H2見出し構造の良い例
    report_lines.append("#### ② 優れたH2見出し構造の例\n")
    for page in d.get("pages", []):
        if len(page["h2"]) >= 4:
            slug = page["file"].replace(f"{domain.replace('www.', '')}_", "").replace(".md", "")
            report_lines.append(f"**【{slug}】**")
            for h2 in page["h2"][:10]:
                report_lines.append(f"  - {h2}")
            report_lines.append("")

    # 権威性シグナル
    report_lines.append("#### ③ 権威性シグナル（E-E-A-T）\n")
    for sig in d.get("authority_signals", [])[:15]:
        report_lines.append(f"- {sig}")
    report_lines.append("")

    # FAQ
    report_lines.append("#### ④ FAQコンテンツ（AEO最重要）\n")
    for faq in d.get("all_faqs", [])[:15]:
        report_lines.append(f"- Q: {faq}")
    report_lines.append("")

# ==== SECTION 7: AEO/GEO具体的アクション提言 ====
report_lines.append("---\n")
report_lines.append("## 6. AEO/GEO 具体的コンテンツ追加アクション（優先度順）\n")

report_lines.append("""
### 🔴 Priority A（即実行 ─ セマンティックギャップ解消）

| # | 追加すべきコンテンツ | 根拠（競合・モデリング先） | 推奨ページ形式 |
|---|---|---|---|
| 1 | 治療の「リスクと注意事項」専用セクション | katsube-dc.com が全診療に設置 | 各診療ページ内のH2追加 |
| 2 | 治療費用の「総額シミュレーション」 | 競合複数サイトに明記 | 料金ページ刷新 |
| 3 | FAQ専用ページ（治療別Q&A） | suzukishika.net・katsube-dc.comが大量保有 | /faq/ 新設 |
| 4 | 症例写真・ビフォーアフターギャラリー | tanaka-kyousei.comがcase/で大量保有 | /case/ 新設 or 拡充 |
| 5 | 「他院との違い」比較コンテンツ | モデリング先が「選ばれる理由」として設置 | /features/ or トップ内 |

### 🟡 Priority B（3ヶ月以内 ─ 権威性強化）

| # | 追加すべきコンテンツ | 根拠 | 推奨ページ形式 |
|---|---|---|---|
| 6 | 院長・歯科医師の詳細プロフィール（学会・資格一覧） | suzukishika.net で高評価 | /dentist/ または /about/ 内 |
| 7 | 使用機器の詳細説明ページ（CT/マイクロスコープ等） | katsube-dc.com の特設ページ | /equipment/ 新設 |
| 8 | 治療の流れ（ステップ・期間・通院回数） | 競合全サイトに標準装備 | 各診療ページ内H2追加 |
| 9 | 患者の声・口コミ（構造化テキスト形式） | GEO/AEOで必須 | /voice/ または各ページ内 |
| 10 | 「保険適用か自由診療か」の明示 | 競合が表で明示 | 料金ページ・各診療ページ |

### 🟢 Priority C（6ヶ月以内 ─ トピック網羅性）

| # | 追加すべきコンテンツ | 根拠 | 推奨ページ形式 |
|---|---|---|---|
| 11 | 顎関節症・歯ぎしり専用ページ | 競合サイトに存在 | /bruxism/ 新設 |
| 12 | 口臭・知覚過敏 専用コンテンツ | 競合に複数存在 | /prevention/ 内またはブログ |
| 13 | 小児歯科の詳細ページ（フッ素・シーラント） | 競合が専用ページ保有 | /kids/ 拡充 |
| 14 | 歯科ドック（口腔内総合検診）ページ | suzukishika.net の目玉コンテンツ | /dock/ 新設 |
| 15 | セカンドオピニオン受付ページ | モデリング先で高権威性訴求 | /second-opinion/ 新設 |
""")

# ==== SECTION 8: 自社のH2一覧（参考） ====
report_lines.append("---\n")
report_lines.append("## 7. 自社（nakanodent.com）現在のH2見出し一覧（参考）\n")
h2_counter = Counter(jisya_data.get("all_h2", []))
for h, cnt in h2_counter.most_common(60):
    report_lines.append(f"- ({cnt}回) {h}")
report_lines.append("")

# ===== ファイル出力 =====
report_path = OUTPUT_DIR / "semantic_gap_report.md"
report_path.write_text("\n".join(report_lines), encoding="utf-8")
print(f"\n✅ レポート出力完了: {report_path}")

# JSON出力（データ検証用）
json_data = {
    "jisya_topics": sorted(jisya_topics),
    "kyogai_topics": {d: sorted(data.get("topics", [])) for d, data in kyogai_data.items()},
    "modeling_topics": {d: sorted(data.get("topics", [])) for d, data in modeling_data.items()},
    "gap_kyogai": sorted(gap_kyogai),
    "gap_modeling": sorted(gap_modeling),
}
json_path = OUTPUT_DIR / "semantic_gap_data.json"
json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✅ JSONデータ出力完了: {json_path}")

print("\n" + "=" * 60)
print(f"【分析完了】")
print(f"  セマンティック・ギャップ（競合比）: {sorted(gap_kyogai)}")
print(f"  セマンティック・ギャップ（モデリング比）: {sorted(gap_modeling)}")
print("=" * 60)
