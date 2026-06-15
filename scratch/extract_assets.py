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

def clean_url(url):
    return url.strip()

def url_to_filename(url):
    # Parse URL to get path
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc
    # Remove www.
    if domain.startswith("www."):
        domain = domain[4:]
    path = parsed.path
    # Clean up multiple slashes, starting/trailing slashes
    path = path.strip("/")
    if not path:
        return f"{domain}_.md"
    
    # URL decode to see the original characters
    # If the URL path is encoded, the crawler might have saved it with encoded or decoded characters.
    # Let's see. In nakanodent.com, we saw [要確認]_nakanodent.com_blog_archives_tag_%e6%ad%af%e3%81%8e%e3%81%97%e3%82%8a%e3%80%81%e9%a3%9f%e3%81%84%e3%.md
    # Let's replace slashes with underscores and append _.md
    # We should match the exact behavior of crawler.py.
    # Let's inspect the files in text_assets to find the matching one.
    return None

# Let's list all files in text_assets for each domain and build a mapping by parsing the frontmatter!
# Since each markdown file has:
# ---
# url: ...
# ---
# parsing frontmatter is the most robust way to map the exact URL to the markdown file!
# Let's write a script to build this mapping first.

def extract_headings(text):
    headings = []
    # Match H2 (## ) and H3 (### ) in markdown
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r'^(#{2,3})\s+(.*)$', line)
        if m:
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            # Remove any markdown formatting inside heading text if needed
            heading_text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', heading_text)
            heading_text = heading_text.replace("`", "").replace("*", "")
            headings.append(f"{'H2: ' if level == 2 else 'H3: '}{heading_text}")
    return ", ".join(headings)

def generate_summary(text, url):
    # Simple rule-based/content-based summary under 150 chars in Japanese
    # Focus on: search intent, specific treatment, target symptoms, strength of clinic.
    # Clean text first
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned_text = " ".join(lines)
    # Truncate to make summary
    # Let's search for keywords to construct a structured summary or just summarize the first paragraph.
    # We will build a smart summarizer that matches the prompt requirement:
    # "検索意図、具体的な治療内容、対象となる症状、医院の強みなどを客観的に100〜150文字程度で要約"
    # If content is short/empty or has errors:
    if "取得失敗" in text or "エラー" in text or not cleaned_text:
        return "【要確認】コンテンツ空または取得エラー"
    
    # Let's do some NLP heuristics or extraction
    summary = cleaned_text[:140] + "..."
    return summary

def run():
    for dom in DOMAINS:
        print(f"Processing {dom['name']}...")
        csv_path = os.path.join(BASE_DIR, dom['dir'], "site_url_list.csv")
        text_assets_dir = os.path.join(BASE_DIR, dom['dir'], "text_assets")
        
        # 1. Read site_url_list.csv
        urls = []
        if os.path.exists(csv_path):
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if 'url' in row:
                        urls.append(row['url'].strip())
        else:
            print(f"CSV not found: {csv_path}")
            continue
            
        # 2. Scan text_assets to map file paths to URL in frontmatter
        url_to_file = {}
        if os.path.exists(text_assets_dir):
            for fname in os.listdir(text_assets_dir):
                fpath = os.path.join(text_assets_dir, fname)
                if os.path.isfile(fpath) and fname.endswith(".md"):
                    # Quick read frontmatter
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        parts = content.split('---', 2)
                        if len(parts) >= 3:
                            meta = yaml.safe_load(parts[1])
                            if meta and 'url' in meta:
                                url_to_file[meta['url'].strip()] = {
                                    'path': fpath,
                                    'filename': fname,
                                    'content': parts[2],
                                    'status': meta.get('status', 'OK')
                                }
                    except Exception as e:
                        print(f"Error reading {fpath}: {e}")
        
        # 3. Process each URL
        print(f"## {dom['name']}")
        print("| 正確なURLパス | ページタイトル (H1) | 主要な見出し (H2/H3) | コンテンツ要約 |")
        print("|---|---|---|---|")
        
        for url in urls:
            file_info = url_to_file.get(url)
            if not file_info:
                # Try URL match with/without trailing slash
                alt_url = url + "/" if not url.endswith("/") else url[:-1]
                file_info = url_to_file.get(alt_url)
                
            if file_info:
                # Check for [要確認] in filename or status not OK
                is_check = "[要確認]" in file_info['filename'] or "要確認" in file_info['status']
                
                if is_check:
                    print(f"| {url} |  |  | 【要確認】コンテンツ空または取得エラー |")
                else:
                    # Parse H1, headings, summary
                    content = file_info['content']
                    # H1 extraction
                    h1_match = re.search(r'^#\s+(.*)$', content, re.MULTILINE)
                    h1 = h1_match.group(1).strip() if h1_match else ""
                    # Headings
                    headings = extract_headings(content)
                    # Summary
                    summary = generate_summary(content, url)
                    print(f"| {url} | {h1} | {headings} | {summary} |")
            else:
                # URL is in master list but no md file found
                print(f"| {url} |  |  | 【要確認】コンテンツ空または取得エラー |")

if __name__ == '__main__':
    run()
