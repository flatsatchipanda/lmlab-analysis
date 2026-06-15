import os
import re
import csv
import pandas as pd
from urllib.parse import urlparse

# Set workspace directory path
workspace_dir = "/home/satoshi/Projects/lmlab-analysis"
crawled_data_dir = os.path.join(workspace_dir, "crawled_data")

# Domains list
target_domains = [
    "nakanodent.com",
    "implantsalon.jp",
    "kyousei-smile.com",
    "white-style.jp",
    "11ireba.com",
    "okayama-all-on-4.com"
]

# Mapping table to match exact folder names in crawled_data
domain_to_folder = {
    "nakanodent.com": "nakanodent.com",
    "implantsalon.jp": "implantsalon.jp",
    "kyousei-smile.com": "www.kyousei-smile.com",
    "white-style.jp": "white-style.jp",
    "11ireba.com": "www.11ireba.com",
    "okayama-all-on-4.com": "okayama-all-on-4.com"
}

def clean_h1(h1_text):
    if pd.isna(h1_text):
        return ""
    # Remove excessive whitespaces/newlines and clean text
    cleaned = re.sub(r'\s+', ' ', str(h1_text)).strip()
    return cleaned

def extract_h2_headings(filepath):
    """
    Extracts H2 headings from a markdown file.
    H2 format: starts with '## ' or '##' followed by text, or HTML <h2> tags.
    """
    if not os.path.exists(filepath):
        return []
    
    h2_list = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # First check if this is a frontmatter block and skip it
        # YAML frontmatter starts with --- and ends with ---
        frontmatter_end = 0
        if content.startswith('---'):
            match = re.search(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
            if match:
                frontmatter_end = match.end()
        
        body_content = content[frontmatter_end:]
        
        # Extract markdown H2 headings: lines starting with '## '
        # We need to ignore inside code blocks if any, but standard regex line check works for most pages
        lines = body_content.split('\n')
        for line in lines:
            line = line.strip()
            # Markdown heading (must be exactly ## followed by a space)
            if line.startswith('## '):
                heading = line[3:].strip()
                # Remove markdown styling inside heading if any
                heading = re.sub(r'[\*\_`]', '', heading)
                if heading:
                    h2_list.append(heading)
            # HTML <h2> heading
            else:
                html_matches = re.findall(r'<h2[^>]*>(.*?)</h2>', line, re.IGNORECASE)
                for hm in html_matches:
                    clean_hm = re.sub(r'<[^>]+>', '', hm).strip()
                    if clean_hm:
                        h2_list.append(clean_hm)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    
    return h2_list

def main():
    all_records = []
    
    # Track stats
    stats = {d: 0 for d in target_domains}
    
    for domain in target_domains:
        folder_name = domain_to_folder[domain]
        domain_path = os.path.join(crawled_data_dir, folder_name)
        
        if not os.path.exists(domain_path):
            print(f"Warning: Directory for {domain} does not exist at {domain_path}")
            continue
            
        url_list_file = os.path.join(domain_path, "site_url_list.csv")
        crawl_sum_file = os.path.join(domain_path, "crawl_summary.csv")
        text_assets_dir = os.path.join(domain_path, "text_assets")
        
        if not os.path.exists(url_list_file):
            print(f"Error: site_url_list.csv not found for {domain}")
            continue
            
        # Read site_url_list.csv (contains exact URLs, status, title, h1, etc.)
        url_df = pd.read_csv(url_list_file)
        
        # Read crawl_summary.csv (contains filename details)
        # Check columns of crawl_summary.csv. Typical format: URL, 使用ツール, 判定, 文字数, 保存ファイル名
        # Some headers might have different case: URL vs url
        crawl_sum_df = pd.DataFrame()
        if os.path.exists(crawl_sum_file):
            crawl_sum_df = pd.read_csv(crawl_sum_file)
            # Normalize column names to lowercase/standard format
            crawl_sum_df.columns = [col.lower().strip() for col in crawl_sum_df.columns]
        
        # We will loop through the exact URLs from site_url_list.csv to make sure no URL is missed.
        # Check standard columns in site_url_list: url, status, title, h1, url_type
        # Normalize column names to lowercase
        url_df.columns = [col.lower().strip() for col in url_df.columns]
        
        # Keep track of urls in this domain
        domain_urls = url_df['url'].dropna().unique()
        stats[domain] = len(domain_urls)
        
        for idx, row in url_df.iterrows():
            url = row.get('url')
            if pd.isna(url):
                continue
                
            # Basic info from site_url_list.csv
            status = row.get('status', '')
            title = row.get('title', '')
            h1 = row.get('h1', '')
            
            # Clean title and h1
            if pd.notna(title):
                title = str(title).strip()
            else:
                title = ""
            h1 = clean_h1(h1)
            
            # Now lookup this URL in crawl_summary.csv to find its text asset filename
            file_name = None
            if not crawl_sum_df.empty:
                # Find matching row for URL
                matching_rows = crawl_sum_df[crawl_sum_df['url'] == url]
                if not matching_rows.empty:
                    # Column naming: '保存ファイル名' or 'save_file_name' or something similar
                    # Let's check columns for 'ファイル' or 'file'
                    file_col = None
                    for col in crawl_sum_df.columns:
                        if 'ファイル' in col or 'file' in col:
                            file_col = col
                            break
                    if file_col:
                        file_name = matching_rows.iloc[0][file_col]
            
            # Determine file path and status
            file_status = "正常"
            h2_headings_str = ""
            
            if pd.isna(file_name) or not file_name:
                # If not in crawl summary, let's flag as要確認 (no file found)
                file_status = "要確認（ファイルなし/エラー）"
            else:
                file_name_str = str(file_name).strip()
                file_path = os.path.join(text_assets_dir, file_name_str)
                
                # Check if file has [要確認] in the filename
                if "[要確認]" in file_name_str:
                    file_status = "要確認（ファイル名フラグ）"
                
                if not os.path.exists(file_path):
                    file_status = "要確認（ファイル未存在）"
                else:
                    # Check if file is empty or contains error message or very short content
                    try:
                        file_size = os.path.getsize(file_path)
                        if file_size == 0:
                            file_status = "要確認（空ファイル）"
                        else:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                file_content = f.read()
                            # Check content length or error-like indicators
                            if not file_content.strip() or len(file_content.strip()) < 20:
                                file_status = "要確認（コンテンツ過少/空）"
                            elif "取得エラー" in file_content or "Error" in file_content:
                                file_status = "要確認（取得エラー表記あり）"
                            else:
                                # Process H2 headings for normal/OK files
                                h2_list = extract_h2_headings(file_path)
                                h2_headings_str = ", ".join(h2_list)
                    except Exception as e:
                        file_status = f"要確認（読み込みエラー: {str(e)}）"
            
            # Build record
            record = {
                "domain": domain,
                "url": url,
                "status": status,
                "title": title,
                "h1": h1,
                "h2_headings": h2_headings_str,
                "file_status": file_status,
                "interim_triage": "",
                "redirect_to_url": ""
            }
            all_records.append(record)
            
    # Output to dataframe
    master_df = pd.DataFrame(all_records)
    
    # Save to total_site_mapping_master.csv in the workspace directory
    output_path = os.path.join(workspace_dir, "total_site_mapping_master.csv")
    master_df.to_csv(output_path, index=False, encoding='utf-8-sig')
    
    print(f"Master file saved successfully to: {output_path}")
    print(f"Total processed rows: {len(master_df)}")
    print("\nDomain stats:")
    for d, count in stats.items():
        print(f"  {d}: {count} URLs")

if __name__ == "__main__":
    main()
