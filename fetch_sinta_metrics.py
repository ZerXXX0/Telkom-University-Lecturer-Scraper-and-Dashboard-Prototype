import os
import json
import httpx
import asyncio
import re
from bs4 import BeautifulSoup
from config import settings

def parse_metrics_table(html):
    soup = BeautifulSoup(html, 'html.parser')
    t = soup.find('table')
    if not t:
        return None
    
    # Headers
    headers = []
    header_tr = t.find('tr')
    if header_tr:
        headers = [th.get_text(strip=True).lower() for th in header_tr.find_all(['td', 'th'])]
    
    # Check if we have Scopus, GScholar, WOS
    # The first cell of the header row is empty, followed by Scopus, GScholar, WOS
    if len(headers) < 2:
        return None
        
    metrics = {
        "scopus": {},
        "google_scholar": {},
        "wos": {}
    }
    
    mapping = {
        "scopus": "scopus",
        "gscholar": "google_scholar",
        "google scholar": "google_scholar",
        "wos": "wos"
    }
    
    rows = t.find_all('tr')[1:] # Skip header
    for r in rows:
        cells = [c.get_text(strip=True) for c in r.find_all(['td', 'th'])]
        if not cells:
            continue
        
        # Row label (e.g. Article, Citation, H-Index, etc.)
        label = cells[0].lower().replace(" ", "_").replace("-", "_")
        
        # Parse values
        for idx in range(1, len(cells)):
            if idx < len(headers):
                platform = headers[idx]
                std_platform = mapping.get(platform, platform)
                if std_platform in metrics:
                    val_str = cells[idx].replace(",", "").replace(".", "").strip()
                    try:
                        val = int(val_str) if val_str else 0
                    except ValueError:
                        val = 0
                    metrics[std_platform][label] = val
                    
    return metrics

async def fetch_lecturer_metrics(client, semaphore, name, sinta_url):
    # Extract sinta ID
    match = re.search(r'/profile/(\d+)', sinta_url)
    if not match:
        print(f"Could not extract Sinta ID from URL: {sinta_url} for {name}")
        return None
    sinta_id = match.group(1)
    url = f"https://sinta.kemdiktisaintek.go.id/authors/profile/{sinta_id}/?view=metrics"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    async with semaphore:
        for attempt in range(5):
            try:
                r = await client.get(url, headers=headers, timeout=15.0)
                if r.status_code == 200:
                    metrics = parse_metrics_table(r.text)
                    if metrics:
                        print(f"Successfully fetched metrics for {name}")
                        return metrics
                    else:
                        print(f"Metrics table not found for {name}")
                elif r.status_code == 404:
                    print(f"Sinta profile not found (404) for {name}")
                    return None
            except Exception as e:
                print(f"Attempt {attempt+1} failed for {name}: {e}")
            await asyncio.sleep(2.0)
    print(f"Failed to fetch metrics for {name} after all attempts.")
    return None

async def run_fetch():
    directories = [
        os.path.abspath('data/json'),
        os.path.abspath(settings.JSON_DIR)
    ]
    directories = list(set(directories))
    
    files = [f for f in os.listdir(directories[0]) if f.endswith('.json')]
    print(f"Scanning {len(files)} JSON files...")
    
    # We will limit concurrency to be polite and avoid timeouts
    semaphore = asyncio.Semaphore(5)
    
    tasks = []
    file_map = []
    
    async with httpx.AsyncClient() as client:
        for filename in files:
            filepath = os.path.join(directories[0], filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            basic = data.get("basic_info", {})
            name = basic.get("name", "Unknown")
            sinta_url = data.get("profiles", {}).get("sinta")
            
            # Skip if we already have metrics?
            # In this case we want to fetch for all since it's a new feature!
            if sinta_url:
                tasks.append(fetch_lecturer_metrics(client, semaphore, name, sinta_url))
                file_map.append(filename)
                
        results = await asyncio.gather(*tasks)
        
        # Save results
        updated_count = 0
        for filename, metrics in zip(file_map, results):
            if metrics:
                updated_count += 1
                for directory in directories:
                    filepath = os.path.join(directory, filename)
                    if os.path.exists(filepath):
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        data["sinta_metrics"] = metrics
                        with open(filepath, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=4)
                            
        print(f"Updated metrics in {updated_count} JSON files.")

if __name__ == "__main__":
    asyncio.run(run_fetch())
