#!/usr/bin/env python3
"""
SEO/GEO 完全版 セマンティック・ギャップ分析スクリプト v2
追加データ:
  - satohdental.com: pages CSV（ページ構造・H2）
  - 競合4サイト: キーワードランキングCSV
"""

import os, re, json, csv
from pathlib import Path
from collections import defaultdict, Counter

# ===== 設定 =====
BASE_DIR = Path("/home/satoshi/Projects/lmlab-analysis/crawled_data")
DOWNLOADS = Path("/home/satoshi/Downloads")
OUTPUT_DIR = Path("/home/satoshi/Projects/lmlab-analysis/reports")
OUTPUT_DIR.mkdir(exist_ok=True)

JISYA = "nakanodent.com"

KYOGAI_CRAWLED = [
    "tanaka-kyousei.com",
    "white-style.jp",
    "www.11ireba.com",
    "www.kyousei-smile.com",
    "implantsalon.jp",
    "okayama-all-on-4.com",
]

MODELING_CRAWLED = [
    "www.katsube-dc.com",
    "www.suzukishika.net",
]

SKIP_PATTERNS = re.compile(
    r"blog|news|column|recruit|sitemap|contact|privacy|terms|kyujin|staff_blog|"
    r"2017|2018|2019|2020|2021|2022|2023|2024|2025|2026",
    re.IGNORECASE
)

# ===== ユーティリティ =====
def read_md(filepath: Path) -> str:
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
        if text.startswith("---"):
            end = text.find("\n---\n", 4)
            if end != -1:
                text = text[end + 5:]
        return text
    except Exception:
        return ""

def extract_headings(text: str) -> dict:
    h1 = [h.strip() for h in re.findall(r"^#\s+(.+)", text, re.MULTILINE) if not h.startswith("|")]
    h2 = [h.strip() for h in re.findall(r"^##\s+(.+)", text, re.MULTILINE) if not h.startswith("|")]
    h3 = [h.strip() for h in re.findall(r"^###\s+(.+)", text, re.MULTILINE) if not h.startswith("|")]
    return {"h1": h1, "h2": h2, "h3": h3}

def extract_faqs(text: str) -> list:
    patterns = [r"^Q[\s\:\.：]\s*(.+)", r"^【Q[0-9]*】(.+)", r"^([^│\|].{5,30}？)\s*$"]
    faqs = []
    for pat in patterns:
        faqs.extend([f.strip() for f in re.findall(pat, text, re.MULTILINE) if len(f.strip()) > 5])
    return list(dict.fromkeys(faqs))[:30]

def extract_authority_signals(text: str) -> list:
    patterns = [
        r"(日本歯科(?:学会|医師会|矯正歯科学会|口腔外科学会|インプラント学会|歯周病学会)[^\n。]{0,30})",
        r"((?:専門医|認定医|指導医|会員|所属)[^\n。]{0,40})",
        r"(\d+[,，]?\d*\s*(?:症例|件|名|年以上|年の経験)[^\n。]{0,30})",
        r"((?:テレビ|新聞|雑誌|メディア|取材|掲載)[^\n。]{0,40})",
        r"((?:院長|ドクター|歯科医師)[^\n。]{0,30}(?:講師|講演|執筆|著書|論文)[^\n。]{0,30})",
        r"((?:セカンドオピニオン|他院|難症例)[^\n。]{0,40})",
        r"((?:CTスキャン|マイクロスコープ|歯科用CT|セレック|レーザー)[^\n。]{0,30})",
        r"((?:無料相談|初診カウンセリング|メール相談)[^\n。]{0,30})",
        r"((?:大学病院|研修|学術|学会発表)[^\n。]{0,40})",
    ]
    signals = []
    for pat in patterns:
        signals.extend([f.strip() for f in re.findall(pat, text)])
    return list(set(signals))[:20]

DENTAL_KEYWORDS = [
    "インプラント", "矯正", "ホワイトニング", "審美", "予防", "クリーニング",
    "虫歯", "歯周病", "根管", "入れ歯", "義歯", "セラミック", "ジルコニア",
    "マウスピース", "オールオン4", "小児", "子ども", "こども", "親知らず",
    "歯ぎしり", "顎関節", "知覚過敏", "口臭", "歯石", "スケーリング",
    "フッ素", "シーラント", "ブリッジ", "差し歯", "クラウン", "補綴",
    "歯科ドック", "定期検診", "メンテナンス", "リスク", "費用", "料金",
    "保険", "自由診療", "無痛", "痛み", "麻酔", "笑気", "静脈鎮静",
    "マイクロスコープ", "CT", "レーザー", "ラバーダム", "精密",
    "症例", "実績", "事例", "ビフォー", "アフター",
    "FAQ", "よくある", "流れ", "ステップ", "期間", "保証",
    "院長", "スタッフ", "理念", "こだわり", "特徴", "強み",
    "口コミ", "評判", "声", "体験", "感想",
    "アクセス", "診療時間", "休診", "予約",
    "セカンドオピニオン", "他院", "難症例",
]

def extract_topics(headings: list) -> set:
    topics = set()
    for h in headings:
        for kw in DENTAL_KEYWORDS:
            if kw in h:
                topics.add(kw)
    return topics

def normalize_heading(h: str) -> str:
    h = re.sub(r"[【】〔〕「」『』（）()・\-\s　]", "", h)
    h = re.sub(r"[0-9０-９①②③④⑤]", "", h)
    return h.lower()

def analyze_site(domain: str, skip_blog: bool = True) -> dict:
    assets_dir = BASE_DIR / domain / "text_assets"
    if not assets_dir.exists():
        return {}
    result = {
        "domain": domain, "pages": [], "all_h2": [], "all_h3": [],
        "all_faqs": [], "authority_signals": [], "topics": set(), "page_slugs": [],
    }
    for f in sorted(assets_dir.glob("*.md")):
        if skip_blog and SKIP_PATTERNS.search(f.name):
            continue
        text = read_md(f)
        headings = extract_headings(text)
        result["pages"].append({
            "file": f.name, "h1": headings["h1"], "h2": headings["h2"], "h3": headings["h3"],
            "faq_count": len(extract_faqs(text))
        })
        result["all_h2"].extend(headings["h2"])
        result["all_h3"].extend(headings["h3"])
        result["all_faqs"].extend(extract_faqs(text))
        result["authority_signals"].extend(extract_authority_signals(text))
        result["topics"].update(extract_topics(headings["h1"] + headings["h2"] + headings["h3"]))
    result["topics"] = sorted(result["topics"])
    result["authority_signals"] = list(set(result["authority_signals"]))[:25]
    print(f"  [MD-OK] {domain}: {len(result['pages'])}p, H2:{len(result['all_h2'])}")
    return result

# ===== CSV読み込み =====
def read_csv_safe(path, encoding="utf-8-sig"):
    rows = []
    try:
        with open(path, encoding=encoding, errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    except Exception as e:
        print(f"  [CSV-ERR] {path.name}: {e}")
    return rows

def load_satohdental_pages() -> dict:
    path = DOWNLOADS / "pages_satohdental.com_2026-06-09_07-48-29.csv"
    rows = read_csv_safe(path)
    result = {
        "domain": "satohdental.com", "pages": [], "all_h2": [],
        "all_faqs": [], "authority_signals": [], "topics": set(),
    }
    for row in rows:
        url = row.get("ページURL", "")
        if any(p in url for p in ["/blog", "/news", "/column"]):
            continue
        h1 = row.get("H1", "").strip()
        h2 = row.get("H2", "").strip()
        title = row.get("Title", "").strip()
        traffic = row.get("合計トラフィック", "0")
        result["pages"].append({"url": url, "h1": h1, "h2": h2, "title": title, "traffic": traffic})
        if h2:
            result["all_h2"].append(h2)
        result["topics"].update(extract_topics([h1, h2, title]))
    result["topics"] = sorted(result["topics"])
    print(f"  [CSV-OK] satohdental.com: {len(result['pages'])}p, H2:{len(result['all_h2'])}")
    return result

def load_keyword_csv(filepath: Path, domain: str) -> dict:
    rows = read_csv_safe(filepath)
    result = {"domain": domain, "keywords": [], "top_keywords": []}
    for row in rows:
        kw = row.get("キーワード", "").strip()
        volume = row.get("検索規模", "0").replace(",", "")
        rank = row.get("順位", "99")
        traffic = row.get("トラフィック", "0")
        url = row.get("URL", "")
        try:
            vol = int(volume)
        except Exception:
            vol = 0
        try:
            rnk = int(rank)
        except Exception:
            rnk = 99
        if kw:
            result["keywords"].append({"keyword": kw, "volume": vol, "rank": rnk, "url": url, "traffic": traffic})
    result["keywords"].sort(key=lambda x: x["volume"], reverse=True)
    result["top_keywords"] = result["keywords"][:50]
    print(f"  [KW-OK] {domain}: {len(result['keywords'])}キーワード")
    return result

# ===== メイン =====
print("=" * 60)
print("SEO/GEO セマンティック・ギャップ分析 v2")
print("=" * 60)

print("\n【1】自社データ読み込み...")
jisya = analyze_site(JISYA)

print("\n【2】競合データ読み込み（クロール済み）...")
kyogai_md = {}
for d in KYOGAI_CRAWLED:
    data = analyze_site(d)
    if data:
        kyogai_md[d] = data

print("\n【3】モデリング先データ読み込み...")
modeling_md = {}
for d in MODELING_CRAWLED:
    data = analyze_site(d)
    if data:
        modeling_md[d] = data

print("\n【4】satohdental.com ページCSV読み込み...")
satohdental = load_satohdental_pages()

print("\n【5】競合キーワードCSV読み込み...")
kw_files = {
    "okayama-ortho.com": "競合20位以上のキーワード郡1：export_research_jp_domain_history_jpy_2026-06_okayama-ortho.com.csv",
    "morimachi-dc.com":  "競合20位以上のキーワード郡2：export_research_jp_domain_history_jpy_2026-06_morimachi-dc.com.csv",
    "sanagawa-dental.com": "競合20位以上のキーワード郡3：export_research_jp_domain_history_jpy_2026-06_sanagawa-dental.com.csv",
    "fujioka-dc.jp":     "競合20位以上のキーワード郡4：export_research_jp_domain_history_jpy_2026-06_fujioka-dc.jp.csv",
}
kw_data = {}
for domain, fname in kw_files.items():
    path = DOWNLOADS / fname
    kw_data[domain] = load_keyword_csv(path, domain)

# ===== ギャップ計算 =====
print("\n【6】ギャップ分析中...")
jisya_topics = set(jisya.get("topics", []))
jisya_h2 = jisya.get("all_h2", [])

# 全競合トピック
all_kyogai_topics = set()
for d in kyogai_md.values():
    all_kyogai_topics.update(d.get("topics", []))
all_kyogai_topics.update(satohdental.get("topics", []))

# モデリング先トピック
all_modeling_topics = set()
for d in modeling_md.values():
    all_modeling_topics.update(d.get("topics", []))
all_modeling_topics.update(satohdental.get("topics", []))

gap_kyogai = sorted(all_kyogai_topics - jisya_topics)
gap_modeling = sorted(all_modeling_topics - jisya_topics)
gap_all = sorted((all_kyogai_topics | all_modeling_topics) - jisya_topics)

# キーワードから抽出するトピック（検索数100以上）
kw_topics = Counter()
for domain, kd in kw_data.items():
    for kw_item in kd["keywords"]:
        for dental_kw in DENTAL_KEYWORDS:
            if dental_kw in kw_item["keyword"] and kw_item["volume"] >= 100:
                kw_topics[dental_kw] += kw_item["volume"]

kw_gaps = [kw for kw, vol in kw_topics.most_common() if kw not in jisya_topics]

# 競合H2頻出
kyogai_h2_counter = Counter()
for d in kyogai_md.values():
    for h in d.get("all_h2", []):
        kyogai_h2_counter[h] += 1
for h2 in satohdental.get("all_h2", []):
    kyogai_h2_counter[h2] += 1

# キーワード全体（検索数順）
all_kws = []
for domain, kd in kw_data.items():
    for item in kd["keywords"]:
        all_kws.append({**item, "domain": domain})
all_kws.sort(key=lambda x: x["volume"], reverse=True)

# ===== レポート生成 =====
print("\n【7】レポート生成中...")

R = []

R.append("# SEO/GEO セマンティック・ギャップ分析レポート（完全版）")
R.append("\n**自社:** nakanodent.com | **分析日:** 2026年6月\n")
R.append("---\n")

# ------- エグゼクティブサマリー -------
R.append("## 📌 エグゼクティブサマリー\n")
R.append(f"""
| 指標 | 数値 |
|---|---|
| 自社保有トピック数 | **{len(jisya_topics)}** |
| 競合+モデリング先の合計ユニークトピック | **{len(all_kyogai_topics | all_modeling_topics)}** |
| **セマンティック・ギャップ数（要追加トピック）** | **{len(gap_all)}** |
| 検索数ベースで強化すべきキーワードカテゴリ数 | **{len(kw_gaps)}** |
| 競合最大キーワード保有数 | **okayama-ortho.com ({sum(1 for k in kw_data['okayama-ortho.com']['keywords'])}KW)** |
""")

# ------- SECTION 1: 各サイト概要 -------
R.append("---\n")
R.append("## 1. 解析サイト一覧\n")

R.append("### 1-1. 自社（nakanodent.com）\n")
R.append(f"- 解析ページ数: **{len(jisya.get('pages',[]))}p**")
R.append(f"- H2見出し数: **{len(jisya_h2)}個**")
R.append(f"- 保有トピック: {', '.join(sorted(jisya_topics))}")
R.append(f"- FAQ候補: **{len(jisya.get('all_faqs',[]))}件**\n")

R.append("### 1-2. 競合サイト（クロールデータ）\n")
R.append("| ドメイン | ページ数 | H2数 | トピック数 | FAQ候補 |")
R.append("|---|---|---|---|---|")
for domain, d in kyogai_md.items():
    R.append(f"| {domain} | {len(d.get('pages',[]))} | {len(d.get('all_h2',[]))} | {len(d.get('topics',[]))} | {len(d.get('all_faqs',[]))} |")
R.append(f"| satohdental.com (pages.csv) | {len(satohdental.get('pages',[]))} | {len(satohdental.get('all_h2',[]))} | {len(satohdental.get('topics',[]))} | - |")
R.append("")

R.append("### 1-3. 競合サイト（キーワードデータ）\n")
R.append("| ドメイン | KW総数 | 検索数最大KW | 検索数 |")
R.append("|---|---|---|---|")
for domain, kd in kw_data.items():
    top = kd["keywords"][0] if kd["keywords"] else {}
    R.append(f"| {domain} | {len(kd['keywords'])} | {top.get('keyword','－')} | {top.get('volume',0):,} |")
R.append("")

R.append("### 1-4. モデリング先\n")
R.append("| ドメイン | ページ数 | H2数 | トピック数 |")
R.append("|---|---|---|---|")
for domain, d in modeling_md.items():
    R.append(f"| {domain} | {len(d.get('pages',[]))} | {len(d.get('all_h2',[]))} | {len(d.get('topics',[]))} |")
R.append("")

# ------- SECTION 2: セマンティック・ギャップ -------
R.append("---\n")
R.append("## 2. セマンティック・ギャップ（自社に追加すべきトピック）\n")

R.append("### 2-1. 全ギャップ一覧（競合+モデリング先にあって自社にない）\n")
R.append("| トピック | 競合保有 | モデリング先保有 | 月間検索Vol（推計） |")
R.append("|---|---|---|---|")
for t in sorted(gap_all):
    in_k = "✅" if t in all_kyogai_topics else "─"
    in_m = "✅" if t in all_modeling_topics else "─"
    vol = kw_topics.get(t, 0)
    vol_str = f"{vol:,}" if vol > 0 else "─"
    R.append(f"| **{t}** | {in_k} | {in_m} | {vol_str} |")
R.append("")

R.append("### 2-2. 検索数ベースの強化優先KWカテゴリ（自社に不足）\n")
R.append("*競合キーワードCSVから算出した月間総検索数が多いカテゴリ*\n")
R.append("| カテゴリ | 月間推計検索数 | 代表競合ドメイン |")
R.append("|---|---|---|")
for kw, total_vol in kw_topics.most_common(25):
    if kw in jisya_topics:
        status = "（自社保有済み）"
    else:
        status = "⚠️ **自社未保有**"
    # 代表ドメイン
    rep_domains = [d for d, kd in kw_data.items() if any(kw in item["keyword"] for item in kd["keywords"])]
    R.append(f"| {kw} {status} | {total_vol:,} | {', '.join(rep_domains[:2])} |")
R.append("")

# ------- SECTION 3: 競合のH2見出し頻出ランキング -------
R.append("---\n")
R.append("## 3. 競合頻出H2見出し vs 自社（網羅性チェック）\n")
R.append("*複数競合に登場するH2 ＝ AIアンサーエンジンが「標準」と判断する情報項目*\n")
R.append("| 見出しテキスト | 競合出現数 | 自社対応 |")
R.append("|---|---|---|")
for h, cnt in kyogai_h2_counter.most_common(50):
    norm = normalize_heading(h)
    jisya_has = any(normalize_heading(jh) == norm for jh in jisya_h2)
    status = "✅" if jisya_has else "❌ 要追加"
    R.append(f"| {h} | {cnt} | {status} |")
R.append("")

# ------- SECTION 4: 競合キーワード詳細 -------
R.append("---\n")
R.append("## 4. 競合キーワード詳細（上位50件 / 検索数順）\n")
R.append("| キーワード | 検索数 | 順位 | ドメイン | URL |")
R.append("|---|---|---|---|---|")
for item in all_kws[:50]:
    R.append(f"| {item['keyword']} | {item['volume']:,} | {item['rank']} | {item['domain']} | {item['url'][:60]}... |")
R.append("")

# ------- SECTION 5: satohdental.com 構造分析 -------
R.append("---\n")
R.append("## 5. モデリング先 satohdental.com のページ構造\n")
R.append("*大阪の高権威歯科医院 — インプラント・審美・矯正で高集客*\n")
R.append("| URL | H1 | H2 | トラフィック |")
R.append("|---|---|---|---|")
for p in satohdental.get("pages", []):
    url_short = p["url"].replace("https://satohdental.com", "")
    R.append(f"| {url_short} | {p['h1'][:30] if p['h1'] else '─'} | {p['h2'][:35] if p['h2'] else '─'} | {p['traffic']} |")
R.append("")

# ------- SECTION 6: モデリング先「勝ちパターン」詳細 -------
R.append("---\n")
R.append("## 6. モデリング先「勝ちパターン」詳細抽出\n")

for idx, (domain, d) in enumerate(modeling_md.items(), 1):
    R.append(f"### 6-{idx}. {domain}\n")

    R.append("#### A) サイロ構造（ページ一覧）\n")
    for page in d.get("pages", []):
        slug = re.sub(r"^www\.", "", domain)
        slug = page["file"].replace(slug.replace(".", "_"), "").replace(".md", "")
        h1_title = page["h1"][0] if page["h1"] else "─"
        R.append(f"- **{slug}**: {h1_title}")
    R.append("")

    R.append("#### B) H2/H3 見出し構造の良い例（4つ以上H2を持つページ）\n")
    for page in d.get("pages", []):
        if len(page["h2"]) >= 4:
            slug = page["file"]
            R.append(f"**[{slug}]**")
            for h2 in page["h2"][:12]:
                R.append(f"  - {h2}")
            for h3 in page["h3"][:5]:
                R.append(f"    - {h3}")
            R.append("")

    R.append("#### C) 権威性シグナル（E-E-A-T）\n")
    for sig in d.get("authority_signals", [])[:20]:
        R.append(f"- {sig}")
    R.append("")

    R.append("#### D) FAQ・Q&Aコンテンツ（AEO対策）\n")
    for faq in d.get("all_faqs", [])[:20]:
        R.append(f"- {faq}")
    R.append("")

# ------- SECTION 7: 競合各サイトのH2構造 -------
R.append("---\n")
R.append("## 7. 競合サイト別 H2/H3 見出し構造（詳細）\n")

for domain, d in kyogai_md.items():
    R.append(f"### {domain}\n")
    for page in d.get("pages", []):
        if page["h2"] or page["h3"]:
            slug = page["file"]
            R.append(f"**[{slug}]**")
            for h2 in page["h2"][:10]:
                R.append(f"  - H2: {h2}")
            for h3 in page["h3"][:5]:
                R.append(f"    - H3: {h3}")
    R.append("")

# ------- SECTION 8: 具体的アクションプラン -------
R.append("---\n")
R.append("## 8. 🎯 具体的コンテンツアクションプラン（優先度順）\n")

R.append("""
### 🔴 Priority A（即実行 ─ 最大の検索ボリューム × ギャップ解消）

| # | アクション | 根拠 | 月間検索量 | 推奨URL |
|---|---|---|---|---|
| A1 | **インプラント専用ランディングページ刷新** | 全競合が最大注力、okayama-ortho.comは大量KW保有 | 超大 | /implant/ |
| A2 | **治療の流れ（ステップ・期間・通院回数）** を全診療ページに追加 | 競合H2頻出ランキング上位 | 大 | 各診療ページ内H2 |
| A3 | **費用・料金の総額シミュレーション表** | 競合複数サイトに明記、高検索意図 | 大 | /fee/ or 各診療内 |
| A4 | **FAQ専用ページ新設**（治療別Q&A 30問以上） | katsube/suzukiが保有、AEO最重要シグナル | 中〜大 | /faq/ |
| A5 | **症例・ビフォーアフターページ拡充** | tanaka-kyousei.comが圧倒的保有 | 大 | /case/ |

### 🟡 Priority B（3ヶ月以内 ─ E-E-A-T権威性強化）

| # | アクション | 根拠 | 推奨URL |
|---|---|---|---|
| B1 | **院長・歯科医師プロフィール詳細化**（学会・資格・症例数） | suzukishikaが高評価 | /dentist/ |
| B2 | **使用機器の専用説明ページ**（CT/マイクロスコープ） | katsube-dc.comが特設ページ保有 | /equipment/ |
| B3 | **口コミ・患者の声**をページ内構造化テキストで掲載 | GEO/AEOで必須シグナル | /voice/ |
| B4 | **リスクと注意事項** セクションを全診療ページに追加 | katsube-dc.comが全診療に設置 | 各診療ページ内 |
| B5 | **保険適用 vs 自由診療の比較表** | 競合が表形式で明示 | 料金ページ・各診療ページ |

### 🟢 Priority C（6ヶ月以内 ─ トピック網羅性）

| # | アクション | 根拠 | 推奨URL |
|---|---|---|---|
| C1 | **顎関節症・歯ぎしり専用ページ** | 競合に複数存在 | /bruxism/ |
| C2 | **口臭・知覚過敏コンテンツ** | ロングテール検索対策 | /prevention/内 or ブログ |
| C3 | **小児歯科詳細**（フッ素・シーラント・定期検診） | 競合が専用ページ | /kids/ |
| C4 | **歯科ドック（総合口腔検診）ページ** | suzukishikaの目玉コンテンツ | /dock/ |
| C5 | **セカンドオピニオン受付ページ** | E-E-A-T高評価シグナル | /second-opinion/ |
| C6 | **オールオン4専用ページ** | 競合KWに出現・高単価 | /allon4/ |
""")

# ------- SECTION 9: 自社H2一覧（現状確認） -------
R.append("---\n")
R.append("## 9. 自社（nakanodent.com）現在のH2見出し一覧\n")
h2_counter = Counter(jisya_h2)
for h, cnt in h2_counter.most_common(80):
    R.append(f"- ({cnt}回) {h}")
R.append("")

# ===== 出力 =====
report_path = OUTPUT_DIR / "semantic_gap_report_v2.md"
report_path.write_text("\n".join(R), encoding="utf-8")
print(f"\n✅ レポート完成: {report_path}")
print(f"   ファイルサイズ: {report_path.stat().st_size:,} bytes")

# JSON summary
summary = {
    "jisya_topics": sorted(jisya_topics),
    "gap_kyogai": gap_kyogai,
    "gap_modeling": gap_modeling,
    "gap_all": gap_all,
    "kw_gaps": kw_gaps,
    "top_kw_by_volume": [(kw, vol) for kw, vol in kw_topics.most_common(20)],
}
json_path = OUTPUT_DIR / "semantic_gap_summary.json"
json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✅ JSONサマリー完成: {json_path}")

print("\n" + "=" * 60)
print("【分析サマリー】")
print(f"  ギャップトピック: {gap_all}")
print(f"  検索数大・未保有KWカテゴリ: {kw_gaps[:5]}")
print("=" * 60)
