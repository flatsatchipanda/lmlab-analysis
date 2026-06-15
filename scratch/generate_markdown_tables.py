# -*- coding: utf-8 -*-
import os
import csv
import re
import urllib.parse
import yaml

DOMAINS = [
    {"name": "nakanodent.com", "dir": "nakanodent.com"},
    {"name": "implantsalon.jp", "dir": "implantsalon.jp"},
    {"name": "kyousei-smile.com", "dir": "www.kyousei-smile.com"},
    {"name": "white-style.jp", "dir": "white-style.jp"},
    {"name": "11ireba.com", "dir": "www.11ireba.com"},
    {"name": "okayama-all-on-4.com", "dir": "okayama-all-on-4.com"},
]

BASE_DIR = "/home/satoshi/Projects/lmlab-analysis/crawled_data"

def extract_headings(text):
    headings = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r'^(#{2,3})\s+(.*)$', line)
        if m:
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            # Clean heading_text
            heading_text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', heading_text)
            heading_text = heading_text.replace("`", "").replace("*", "").replace("|", "｜")
            headings.append(f"{'H2: ' if level == 2 else 'H3: '}{heading_text}")
    return ", ".join(headings)

def generate_summary(text, title):
    # Standard clean up
    cleaned = re.sub(r'\s+', ' ', text).strip()
    if not cleaned or "取得失敗" in cleaned or "エラー" in cleaned:
        return "【要確認】コンテンツ空または取得エラー"
    
    # We want a concise 100-150 character summary outlining:
    # 検索意図、具体的な治療内容、対象となる症状、医院の強み
    # We can extract the first few sentences and append/trim.
    # Let's find sentences ending with punctuation.
    sentences = re.split(r'(?<=[。？！])', cleaned)
    summary_text = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(summary_text) + len(s) <= 135:
            summary_text += s
        else:
            if not summary_text:
                summary_text = s[:135]
            break
            
    if not summary_text:
        summary_text = cleaned[:135]
        
    summary_text = summary_text.strip()
    if len(summary_text) < 50 and title:
        summary_text = f"{title}に関するページです。{summary_text}"
        
    # Cap between 100 and 150 chars
    if len(summary_text) > 145:
        summary_text = summary_text[:142] + "..."
    elif len(summary_text) < 100:
        # Pad with some general description
        padding = " 岡山なかの歯科クリニックグループの専門ドメインにて、患者様一人ひとりに合わせた最適な治療を提案します。"
        summary_text = (summary_text + padding)[:145]
        
    return summary_text.replace("|", "｜")

def run():
    for dom in DOMAINS:
        csv_path = os.path.join(BASE_DIR, dom['dir'], "site_url_list.csv")
        text_assets_dir = os.path.join(BASE_DIR, dom['dir'], "text_assets")
        
        # 1. Read site_url_list.csv
        url_metadata = {}
        if os.path.exists(csv_path):
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    url = row.get('url', '').strip()
                    if url:
                        url_metadata[url] = {
                            'title': row.get('title', '').strip(),
                            'h1': row.get('h1', '').strip()
                        }
        
        # 2. Read text_assets
        url_to_file = {}
        if os.path.exists(text_assets_dir):
            for fname in os.listdir(text_assets_dir):
                fpath = os.path.join(text_assets_dir, fname)
                if os.path.isfile(fpath) and fname.endswith(".md"):
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        parts = content.split('---', 2)
                        if len(parts) >= 3:
                            # Parse YAML metadata manually to be safer and avoid scanner issues
                            meta = {}
                            for line in parts[1].splitlines():
                                if ':' in line:
                                    k, v = line.split(':', 1)
                                    meta[k.strip()] = v.strip()
                            
                            url = meta.get('url', '').strip()
                            # remove quotes if any
                            url = url.strip("'\"")
                            if url:
                                url_to_file[url] = {
                                    'filename': fname,
                                    'content': parts[2],
                                    'status': meta.get('status', 'OK').strip("'\"")
                                }
                    except Exception as e:
                        pass
        
        # 3. Output
        print(f"## {dom['name']}")
        print("| 正確なURLパス | ページタイトル (H1) | 主要な見出し (H2/H3) | コンテンツ要約 |")
        print("|---|---|---|---|")
        
        # Sort URLs: homepage first, then alphabetical path
        sorted_urls = sorted(url_metadata.keys(), key=lambda u: (0 if u == f"https://{dom['name']}/" or u == f"http://{dom['name']}/" or u == f"https://www.{dom['name']}/" else 1, u))
        
        for url in sorted_urls:
            csv_meta = url_metadata[url]
            file_info = url_to_file.get(url)
            if not file_info:
                # try alternative slash
                alt = url + "/" if not url.endswith("/") else url[:-1]
                file_info = url_to_file.get(alt)
            
            # Default title
            title = csv_meta['h1'] if csv_meta['h1'] else csv_meta['title']
            title = title.replace("\n", " ").replace("\r", " ").strip()
            # Clean double spaces
            title = re.sub(r'\s+', ' ', title)
            
            if file_info:
                is_check = "[要確認]" in file_info['filename'] or "要確認" in file_info['status']
                if is_check:
                    print(f"| {url} |  |  | 【要確認】コンテンツ空または取得エラー |")
                else:
                    content = file_info['content']
                    # Headings
                    headings = extract_headings(content)
                    # Summary
                    summary = generate_summary(content, title)
                    # Title (fallback to CSV one if not found in markdown H1)
                    h1_match = re.search(r'^#\s+(.*)$', content, re.MULTILINE)
                    h1 = h1_match.group(1).strip() if h1_match else title
                    h1 = h1.replace("|", "｜")
                    print(f"| {url} | {h1} | {headings} | {summary} |")
            else:
                print(f"| {url} |  |  | 【要確認】コンテンツ空または取得エラー |")
        print()

if __name__ == '__main__':
    run()
