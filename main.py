import os
import asyncio
import pandas as pd
import json
import httpx
from config import settings
from scraper.search import search_lecturer_profiles
from scraper.playwright_client import download_pages
from scraper.cleaner import clean_html
from scraper.openalex import scrape_lecturer_openalex
from parser.llm import extract_information
from parser.merge import merge_profiles, categorize_ai
from embedding.embedder import compute_embedding
from utils.logger import get_logger
from tqdm import tqdm

logger = get_logger("main")

def classify_research_group(field: str, study_program: str) -> str:
    field_lower = field.lower()
    prog_lower = study_program.lower()
    
    if 'data science' in prog_lower:
        return 'DSIS'
    if 'rekayasa perangkat lunak' in prog_lower:
        return 'SEAL'
    if 'teknologi informasi' in prog_lower or 'forensik' in prog_lower:
        return 'CITI'
        
    seal_keywords = ['software', 'programming', 'instruction', 'learning', 'human computer', 'design', 'requirements']
    if any(k in field_lower for k in seal_keywords):
        return 'SEAL'
        
    citi_keywords = ['network', 'security', 'hardware', 'systems', 'operating', 'infrastructure', 'forensics']
    if any(k in field_lower for k in citi_keywords):
        return 'CITI'
        
    return 'DSIS'

def load_input_data():
    input_file = os.path.join(settings.INPUT_DIR, "Keilmuan Dosen FIF.xlsx")
    if not os.path.exists(input_file):
        logger.error(f"Input file {input_file} not found.")
        return []
    
    df = pd.read_excel(input_file)
    records = []
    for _, row in df.iterrows():
        field_val = str(row.get("PLOTTING KEILMUAN (2025)", "")).strip()
        prog_val = str(row.get("PROGRAM STUDI", "")).strip()
        rg = classify_research_group(field_val, prog_val)
        
        records.append({
            "name": str(row.get("NAMA", "")).strip(),
            "code": str(row.get("NIP", "")).strip(),
            "study_program": prog_val,
            "research_group": rg,
            "academic_rank": str(row.get("JAD TERAKHIR", "")).strip(),
            "field": field_val
        })
    return records

def extract_profiles_from_urls(urls: list[str]) -> dict:
    profiles = {
        "google_scholar": None,
        "sinta": None,
        "orcid": None,
        "scopus": None
    }
    for url in urls:
        url_lower = url.lower()
        if "scholar.google" in url_lower:
            profiles["google_scholar"] = url
        elif "sinta.kemdikbud" in url_lower or "sinta.ristek" in url_lower or "sinta.kemdiktisaintek" in url_lower:
            profiles["sinta"] = url
        elif "orcid.org" in url_lower:
            profiles["orcid"] = url
        elif "scopus.com" in url_lower:
            profiles["scopus"] = url
    return profiles

def extract_photo_url_from_html(html_content: str, base_url: str, lecturer_name: str, lecturer_code: str) -> str:
    from bs4 import BeautifulSoup
    import urllib.parse
    
    soup = BeautifulSoup(html_content, 'lxml')
    img_tags = soup.find_all('img')
    
    # Priority 1: img with src containing the lecturer's code/NIP
    if lecturer_code:
        for img in img_tags:
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src and lecturer_code in src:
                return urllib.parse.urljoin(base_url, src)
                
    # Priority 2: img with class/id/alt containing profile keywords
    profile_keywords = ['profile', 'avatar', 'dosen', 'photo', 'picture', 'lecturer', 'face', 'portrait']
    for img in img_tags:
        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
        if not src:
            continue
        
        alt = (img.get('alt') or '').lower()
        if alt and any(kw in alt for kw in [lecturer_name.lower(), 'photo', 'profil']):
            return urllib.parse.urljoin(base_url, src)
            
        classes = [c.lower() for c in (img.get('class') or [])]
        img_id = (img.get('id') or '').lower()
        if any(any(kw in c for kw in profile_keywords) for c in classes) or any(kw in img_id for kw in profile_keywords):
            width = img.get('width')
            height = img.get('height')
            if width and width.isdigit() and int(width) < 50:
                continue
            if height and height.isdigit() and int(height) < 50:
                continue
            return urllib.parse.urljoin(base_url, src)
            
    # Priority 3: First img tag that is likely not an icon/logo
    for img in img_tags:
        src = img.get('src') or img.get('data-src')
        if not src:
            continue
        src_lower = src.lower()
        if any(x in src_lower for x in ['logo', 'icon', 'header', 'footer', 'banner', 'theme', 'wp-content/themes', 'assets/']):
            continue
        return urllib.parse.urljoin(base_url, src)
        
    return None

def get_url_from_html_file(filepath: str) -> str:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            first_line = f.readline()
            if first_line.startswith("<!-- URL:"):
                return first_line.replace("<!-- URL:", "").replace("-->", "").strip()
    except Exception:
        pass
    return ""

async def process_lecturer(lecturer_info):
    name = lecturer_info.get("name")
    code = lecturer_info.get("code")
    
    if name == "nan" or not name:
        return None
        
    logger.info(f"Processing lecturer: {name} ({code})")
    
    # Fault tolerance & Resume Interrupted Jobs
    json_path = os.path.join(settings.JSON_DIR, f"{code}.json")
    if os.path.exists(json_path):
        logger.info(f"Skipping {name}, already processed.")
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    # Try fetching from OpenAlex first
    openalex_profile = None
    try:
        async with httpx.AsyncClient() as client:
            openalex_profile = await scrape_lecturer_openalex(client, lecturer_info)
        await asyncio.sleep(1.0)
    except Exception as e:
        logger.warning(f"Error scraping from OpenAlex for {name}: {e}")
        
    # Always search/scrape web profiles to fill missing identity & links
    logger.info(f"Searching web profiles for '{name}' to fill identity & link details...")
    urls = await search_lecturer_profiles(name, "Telkom University")
    
    html_files = await download_pages(urls, f"{code}_raw")
    cleaned_files = [clean_html(f) for f in html_files]
    
    extracted_data = []
    for raw_f, cf in zip(html_files, cleaned_files):
        with open(cf, 'r', encoding='utf-8') as f:
            text = f.read()
        if len(text) > 100:
            data = extract_information(text)
            if data:
                # Get base URL from HTML file comment
                base_url = get_url_from_html_file(raw_f)
                
                # Programmatically extract photo URL from raw HTML if not in data
                if not data.get("photo") and not data.get("identity", {}).get("photo"):
                    try:
                        with open(raw_f, 'r', encoding='utf-8') as hf:
                            html_content = hf.read()
                        photo_url = extract_photo_url_from_html(html_content, base_url or "", name, code)
                        if photo_url:
                            if "identity" not in data:
                                data["identity"] = {}
                            data["identity"]["photo"] = photo_url
                    except Exception as pe:
                        logger.warning(f"Error extracting photo from HTML: {pe}")
                
                extracted_data.append(data)
                
    web_merged = merge_profiles(extracted_data, lecturer_info)
    
    # Classify search URLs directly to get additional profile links
    search_profiles = extract_profiles_from_urls(urls)
    for platform, url in search_profiles.items():
        if url and not web_merged["profiles"].get(platform):
            web_merged["profiles"][platform] = url
            
    # Combine OpenAlex and Web data depending on what succeeded
    if openalex_profile:
        logger.info(f"Successfully scraped '{name}' data from OpenAlex. Merging web details (preserving publications)...")
        
        # Keep publications data from OpenAlex as is, only update identity and profiles from web
        merged = openalex_profile
        
        # Merge identity (prefer web data for fields like email, photo, titles since OpenAlex lacks them)
        for key in ["full_name", "titles", "email", "photo"]:
            web_val = web_merged["identity"].get(key)
            if web_val and not merged["identity"].get(key):
                merged["identity"][key] = web_val
                
        # Merge profiles (prefer web data, but keep any existing ORCID/Scopus from OpenAlex if web is empty)
        for key in merged["profiles"].keys():
            web_val = web_merged["profiles"].get(key)
            if web_val and not merged["profiles"].get(key):
                merged["profiles"][key] = web_val
    else:
        logger.info(f"OpenAlex profile not found or failed for '{name}'. Using web scraped data.")
        merged = web_merged
    
    merged["research"]["ai_categories"] = categorize_ai(merged["research"])
    
    kw_text = " ".join(merged["research"]["keywords"])
    pub_text = " ".join(merged["research"]["publication_titles"])
    
    merged["embeddings"] = {
        "keyword": compute_embedding(kw_text),
        "publication": compute_embedding(pub_text)
    }
    
    try:
        from validator import validate_profile
        validate_profile(merged)
    except Exception as ve:
        logger.warning(f"Pydantic validation warning for {name}: {ve}")
        
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, indent=4)
        
    return merged

async def run_pipeline():
    os.makedirs(settings.JSON_DIR, exist_ok=True)
    os.makedirs(settings.INPUT_DIR, exist_ok=True)
    
    lecturers = load_input_data()
    if not lecturers:
        logger.warning("No lecturers to process. Please add the input Excel file.")
        return
        
    all_profiles = []
    
    for lecturer in tqdm(lecturers, desc="Processing lecturers"):
        try:
            profile = await process_lecturer(lecturer)
            if profile:
                profile["id"] = lecturer["code"]
                all_profiles.append(profile)
        except Exception as e:
            logger.error(f"Failed to process {lecturer.get('name')}: {e}")
            # Continue pipeline to next lecturer even on failure
            
    logger.info("Generating recommendations...")
    from recommendation.recommender import generate_recommendations
    
    for profile in all_profiles:
        recs = generate_recommendations(profile["id"], all_profiles)
        profile["recommendations"] = recs
        
        # Validate profile with recommendations
        try:
            from validator import validate_profile
            validate_profile(profile)
        except Exception as ve:
            logger.warning(f"Pydantic validation warning for recommendation profile {profile.get('basic_info', {}).get('name')}: {ve}")
            
        # update JSON with recommendations
        json_path = os.path.join(settings.JSON_DIR, f"{profile['id']}.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=4)
            
    logger.info("Pipeline completed. Next step: Save to Database using a separate script or expanding this one.")

if __name__ == "__main__":
    asyncio.run(run_pipeline())
