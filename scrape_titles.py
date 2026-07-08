import os
import json
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from config import settings

def extract_titles(full_name_web):
    prefixes = []
    name_part = full_name_web
    suffix_part = ""
    if ',' in full_name_web:
        name_part, suffix_part = full_name_web.split(',', 1)
        suffix_part = suffix_part.strip()
        
    name_part = name_part.strip()
    words = name_part.split()
    prefix_words = []
    for word in words:
        w_lower = word.lower().rstrip('.')
        if w_lower in ['dr', 'prof', 'ir', 'eng', 'assoc', 'asst', 'adjunct']:
            prefix_words.append(word)
        elif '-' in w_lower:
            # Handle cases like dr.-ing.
            parts = w_lower.split('-')
            if all(p.rstrip('.') in ['dr', 'ing', 'eng', 'prof', 'ir', 'assoc', 'asst', 'adjunct'] for p in parts if p):
                prefix_words.append(word)
            else:
                break
        else:
            break
            
    prefix_str = " ".join(prefix_words)
    
    all_titles = []
    if prefix_str:
        all_titles.append(prefix_str)
    if suffix_part:
        all_titles.append(suffix_part)
        
    return ", ".join(all_titles) if all_titles else None

def get_base_name(name):
    # Split by comma to remove degrees at the end
    base = name.split(',')[0]
    base = base.lower()
    # Remove titles
    prefixes_to_strip = [
        'assoc. prof. dr.', 'assoc. prof.', 'asst. prof. dr.', 'asst. prof.',
        'adjunct prof.', 'dr. eng.', 'dr. eng', 'dr.', 'prof.', 'ir.', 'eng.', 'dr.-ing.'
    ]
    for title in prefixes_to_strip:
        if base.startswith(title):
            base = base[len(title):].strip()
    # Keep only letters
    base = ''.join(c for c in base if c.isalpha())
    return base

async def scrape_and_update():
    print("Launching playwright to scrape SOC lecturer page for titles...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        url = "https://soc.telkomuniversity.ac.id/dosen-fakultas-informatika/"
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)
        
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        await browser.close()
        
        table = soup.select_one('#tablepress-22')
        if not table:
            print("Table #tablepress-22 not found on page!")
            return
            
        rows = table.select('tbody tr')
        print(f"Found {len(rows)} rows in table.")
        
        scraped_data = []
        for row in rows:
            cols = row.select('td')
            if len(cols) < 8:
                continue
            full_name_web = cols[2].get_text(strip=True)
            nip = cols[4].get_text(strip=True)
            
            titles = extract_titles(full_name_web)
            
            scraped_data.append({
                "full_name_web": full_name_web,
                "nip": nip,
                "titles": titles
            })
            
    # Index scraped lecturers by NIP and by base name
    by_nip = {item['nip'].strip(): item for item in scraped_data if item['nip']}
    by_name = {get_base_name(item['full_name_web']): item for item in scraped_data}
    
    # We will update files in both directories
    directories = [
        os.path.abspath('data/json'),
        os.path.abspath(settings.JSON_DIR)
    ]
    directories = list(set(directories))
    
    total_updated = 0
    total_processed = 0
    
    for directory in directories:
        if not os.path.exists(directory):
            continue
        files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith('.json')]
        for filepath in files:
            filename = os.path.basename(filepath)
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            basic = data.get("basic_info", {})
            identity = data.get("identity", {})
            
            name = basic.get("name", "")
            nip_part = filename.replace('.json', '').split('-')[0]
            
            matched_item = None
            if nip_part in by_nip:
                matched_item = by_nip[nip_part]
            elif get_base_name(name) in by_name:
                matched_item = by_name[get_base_name(name)]
                
            if matched_item:
                identity["titles"] = matched_item["titles"]
                identity["name_with_title"] = matched_item["full_name_web"]
                data["identity"] = identity
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)
                    
                if directory == directories[0]:
                    total_updated += 1
                    print(f"Updated titles for {name} ({nip_part}): {matched_item['titles']}")
            else:
                print(f"Warning: No match for {name} ({nip_part})")
                
            if directory == directories[0]:
                total_processed += 1
                
    print(f"\nFinished updating titles. Updated {total_updated} / {total_processed} lecturers.")

if __name__ == "__main__":
    asyncio.run(scrape_and_update())
