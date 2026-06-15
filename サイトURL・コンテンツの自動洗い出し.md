# サイトURL・コンテンツの自動洗い出し

## 提案：ドメインフォルダへの自動整理 + 連続実行

```
crawled_data/fujioka-dc.jp/
├── crawl_raw.jsonl       ← 中間ファイル（内部用）
├── site_url_list.csv     ← site_crawler のアウトプット
├── text_assets/          ← crawler のマークダウン群
├── crawl_summary.csv     ← crawler サマリー
├── media_inventory.csv   ← メディア棚卸し
└── common_assets.csv     ← 共通アセット
```

**コマンド1つで全部完結：**
```bash
uv run site_crawler.py https://fujioka-dc.jp/
```
---

実行すると以下が自動で行われます：

```
① 📁 crawled_data/fujioka-dc.jp/ フォルダを自動作成
② 🌐 サイト全体をクロール → site_url_list.csv 生成
③ 🚀 crawler.py を自動呼び出し → コンテンツ・メディア抽出
```

**出力フォルダ構成：**
```
crawled_data/fujioka-dc.jp/
├── crawl_raw.jsonl          ← 中間ファイル（内部用）
├── site_url_list.csv        ← URL一覧
├── text_assets/             ← ページごとのMarkdown
├── crawl_summary.csv        ← 抽出サマリー
├── media_inventory.csv      ← ページ固有メディア
└── common_assets.csv        ← 共通アセット（ヘッダー等）
```

### オプション

| オプション | 説明 |
|---|---|
| `-l 500` | クロール上限ページ数を変更（デフォルト: 1000ページ） |
| `--no-extract` | URL一覧CSVだけ作成し、コンテンツ抽出はスキップ |
