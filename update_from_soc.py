import os
import json
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from config import settings

def get_base_name(name):
    # Split by comma to remove degrees at the end
    base = name.split(',')[0]
    base = base.lower()
    # Remove titles
    for title in ['dr. eng.', 'dr. eng', 'dr.', 'prof.', 'ir.', 'eng.']:
        if base.startswith(title):
            base = base[len(title):].strip()
    # Keep only letters
    base = ''.join(c for c in base if c.isalpha())
    return base

async def scrape_soc_lecturers():
    print("Launching playwright to scrape SOC lecturer page...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        url = "https://soc.telkomuniversity.ac.id/dosen-fakultas-informatika/"
        print(f"Navigating to {url}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # Give dynamic content time to load
        await asyncio.sleep(5)
        
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        table = soup.select_one('#tablepress-22')
        if not table:
            print("Table #tablepress-22 not found on page!")
            await browser.close()
            return []
            
        rows = table.select('tbody tr')
        print(f"Found {len(rows)} rows in table.")
        
        scraped_data = []
        for row in rows:
            cols = row.select('td')
            if len(cols) < 8:
                continue
                
            # Extract photo (check data-src first for lazy loading, fallback to src)
            img = cols[1].find('img')
            photo_url = None
            if img:
                photo_url = img.get('data-src') or img.get('src')
                # If it's a base64 SVG placeholder, ignore it
                if photo_url and photo_url.startswith('data:'):
                    photo_url = None
            
            # Extract name, code, NIP
            name = cols[2].get_text(strip=True)
            lecturer_code = cols[3].get_text(strip=True)
            nip = cols[4].get_text(strip=True)
            
            # Extract detail links
            sinta_url = None
            scholar_url = None
            links = cols[7].find_all('a')
            for link in links:
                href = link.get('href', '')
                text = link.get_text(strip=True).lower()
                if 'sinta' in text or 'sinta' in href:
                    sinta_url = href
                elif 'scholar' in text or 'scholar' in href or 'citations?user=' in href:
                    scholar_url = href
            
            scraped_data.append({
                "photo_url": photo_url,
                "name": name,
                "code": lecturer_code,
                "nip": nip,
                "sinta_url": sinta_url,
                "scholar_url": scholar_url
            })
            
        await browser.close()
        print(f"Scraped {len(scraped_data)} lecturers from SOC website.")
        return scraped_data

async def update_json_files(scraped_lecturers):
    # Index scraped lecturers by NIP and by base name
    by_nip = {item['nip'].strip(): item for item in scraped_lecturers if item['nip']}
    by_name = {get_base_name(item['name']): item for item in scraped_lecturers}
    
    # We will update files in both directories to ensure consistency
    directories = [
        os.path.abspath('data/json'),
        os.path.abspath(settings.JSON_DIR)
    ]
    # Remove duplicate path if they are the same
    directories = list(set(directories))
    
    print(f"Updating JSON files in directories: {directories}")
    
    total_updated = 0
    total_files_processed = 0
    
    for directory in directories:
        if not os.path.exists(directory):
            print(f"Directory {directory} does not exist. Skipping.")
            continue
            
        files = [os.path.join(directory, f) for f in os.listdir(directory) if f.endswith('.json')]
        print(f"Processing {len(files)} JSON files in {directory}...")
        
        for filepath in files:
            filename = os.path.basename(filepath)
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            basic = data.get("basic_info", {})
            identity = data.get("identity", {})
            profiles = data.get("profiles", {})
            
            name = basic.get("name", "")
            nip_part = filename.replace('.json', '').split('-')[0]
            
            matched_item = None
            if nip_part in by_nip:
                matched_item = by_nip[nip_part]
            elif get_base_name(name) in by_name:
                matched_item = by_name[get_base_name(name)]
                
            if matched_item:
                # 1. Update basic info with lecturer_code
                basic["lecturer_code"] = matched_item["code"]
                
                # 2. Update photo url if found
                if matched_item["photo_url"]:
                    identity["photo"] = matched_item["photo_url"]
                    
                # 3. Update Sinta URL
                if matched_item["sinta_url"]:
                    profiles["sinta"] = matched_item["sinta_url"]
                    
                # 4. Update Google Scholar URL
                if matched_item["scholar_url"]:
                    profiles["google_scholar"] = matched_item["scholar_url"]
                    
                # Save back
                data["basic_info"] = basic
                data["identity"] = identity
                data["profiles"] = profiles
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)
                
                if directory == directories[0]: # count once per file
                    total_updated += 1
            else:
                print(f"Warning: No match found for {name} ({nip_part}) in scraped website data.")
                
            if directory == directories[0]:
                total_files_processed += 1
                
    print(f"Successfully matched and updated {total_updated} / {total_files_processed} lecturers.")

async def main():
    scraped = await scrape_soc_lecturers()
    if scraped:
        await update_json_files(scraped)
        print("JSON files updated successfully.")
    else:
        print("Failed to scrape lecturer profiles from SOC website.")

if __name__ == "__main__":
    asyncio.run(main())
