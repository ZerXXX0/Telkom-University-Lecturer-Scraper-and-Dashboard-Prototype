import os
import json
import asyncio
import httpx
from main import (
    search_lecturer_profiles,
    download_pages,
    clean_html,
    extract_information,
    extract_photo_url_from_html,
    get_url_from_html_file,
    extract_profiles_from_urls,
    merge_profiles
)
from config import settings
from utils.logger import get_logger
from tqdm import tqdm
from scraper.openalex import scrape_lecturer_openalex
from embedding.embedder import compute_embedding
from parser.merge import categorize_ai
from bs4 import BeautifulSoup
import re

logger = get_logger("updater")

def parse_google_scholar_html(html_content: str) -> dict:
    soup = BeautifulSoup(html_content, 'html.parser')
    publications = []
    years = []
    coauthors = set()
    
    for row in soup.select('.gsc_a_tr'):
        title_link = row.select_one('.gsc_a_at')
        if not title_link:
            continue
        title = title_link.get_text(strip=True)
        
        # Authors
        gray_divs = row.select('.gs_gray')
        authors_text = ""
        if len(gray_divs) > 0:
            authors_text = gray_divs[0].get_text(strip=True)
            
        # Year
        year_span = row.select_one('.gsc_a_y')
        year = None
        if year_span:
            year_text = year_span.get_text(strip=True)
            if year_text.isdigit():
                year = int(year_text)
                
        publications.append(title)
        if year:
            years.append(year)
        else:
            years.append(0)
            
        # Extract coauthors
        if authors_text:
            for author in re.split(r',|;', authors_text):
                author = author.strip().replace('...', '')
                if author and len(author) > 2:
                    coauthors.add(author)
                    
    # Metrics
    citation_count = 0
    h_index = 0
    i10_index = 0
    
    metrics_rows = soup.select('#gsc_rsb_st tr')
    for row in metrics_rows:
        tds = row.select('td')
        if len(tds) >= 2:
            metric_name = row.select_one('.gsc_rsb_sc1') or tds[0]
            metric_name_text = metric_name.get_text(strip=True).lower()
            val_text = tds[1].get_text(strip=True)
            if val_text.isdigit():
                val = int(val_text)
                if any(k in metric_name_text for k in ['zitate', 'citations', 'citat']):
                    citation_count = val
                elif 'h-index' in metric_name_text:
                    h_index = val
                elif 'i10-index' in metric_name_text:
                    i10_index = val
                    
    return {
        "publication_titles": publications,
        "publication_years": years,
        "coauthors": list(coauthors),
        "citation_count": citation_count,
        "h_index": h_index,
        "i10_index": i10_index
    }

def parse_sinta_html(html_content: str) -> dict:
    soup = BeautifulSoup(html_content, 'html.parser')
    publications = []
    years = []
    coauthors = set()
    total_citations = 0
    
    for item in soup.select('.ar-list-item'):
        title_a = item.select_one('.ar-title a')
        if not title_a:
            continue
        title = title_a.get_text(strip=True)
        publications.append(title)
        
        # Year
        year_a = item.select_one('.ar-year')
        year = 0
        if year_a:
            year_text = year_a.get_text(strip=True)
            match = re.search(r'\d{4}', year_text)
            if match:
                year = int(match.group())
        years.append(year)
        
        # Authors
        meta_links = item.select('.ar-meta a')
        authors_text = ""
        for link in meta_links:
            text = link.get_text(strip=True)
            if text.startswith("Authors :"):
                authors_text = text.replace("Authors :", "").strip()
                break
        if authors_text:
            for author in re.split(r',|;', authors_text):
                author = author.strip().replace('...', '')
                if author and len(author) > 2:
                    coauthors.add(author)
                    
        # Citations
        cited_a = item.select_one('.ar-cited')
        if cited_a:
            cited_text = cited_a.get_text(strip=True)
            match = re.search(r'\d+', cited_text)
            if match:
                total_citations += int(match.group())
                
    return {
        "publication_titles": publications,
        "publication_years": years,
        "coauthors": list(coauthors),
        "citation_count": total_citations,
        "h_index": 0,
        "i10_index": 0
    }

def verify_scholar_profile(soup, lecturer_name: str) -> bool:
    name_div = soup.select_one('#gsc_prf_in')
    if not name_div:
        return False
    profile_name = name_div.get_text(strip=True).lower()
    
    # 1. Clean and tokenize lecturer name
    lec_clean = lecturer_name.lower().replace(",", "").replace(".", "")
    lec_words = [w for w in lec_clean.split() if len(w) > 2 and w not in [
        'kom', 'mkom', 'si', 'msi', 'spd', 'dr', 'prof', 'dra', 'drs', 'ir', 'eng', 'mt', 'smt', 'smat', 'mmat', 'meng'
    ]]
    
    # 2. Tokenize profile name
    prof_words = [w for w in profile_name.split() if len(w) > 1]
    
    # 3. Check for significant word overlap or direct substring match
    matching_words = [w for w in lec_words if w in prof_words]
    overlap_count = len(matching_words)
    has_name_overlap = (overlap_count >= 2) or (overlap_count == 1 and lec_words and matching_words[0] == lec_words[0]) or (lec_clean in profile_name) or (profile_name in lec_clean)
    if not has_name_overlap:
        return False
        
    # 4. Check affiliation
    aff_div = soup.select_one('#gsc_prf_i') or soup.select_one('.gsc_prf_il')
    if aff_div:
        aff_text = aff_div.get_text(strip=True).lower()
        if "telkom" in aff_text or "tel-u" in aff_text:
            return True
        other_orgs = ["yogyakarta", "banten", "muhammadiyah", "uii", "gadjah mada", "ugm", "indonesia university of", "universitas islam indonesia"]
        if any(org in aff_text for org in other_orgs):
            return False
            
    if profile_name == lec_clean:
        return True
    return False

async def search_sinta_author_async(client: httpx.AsyncClient, name: str) -> str:
    url = f"https://sinta.kemdiktisaintek.go.id/authors?q={name.replace(' ', '+')}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    r = await client.get(url, headers=headers)
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, 'html.parser')
    author_links = []
    for a in soup.select('a'):
        href = a.get('href', '')
        if '/authors/profile/' in href:
            match = re.search(r'/profile/(\d+)', href)
            if match:
                author_links.append((match.group(1), a))
                
    for author_id, a_tag in author_links:
        parent = a_tag.parent
        for _ in range(4):
            if parent:
                parent_text = parent.get_text().lower()
                if 'telkom' in parent_text or 'tel-u' in parent_text:
                    return author_id
                parent = parent.parent
    if len(author_links) == 1:
        return author_links[0][0]
    return None

async def fetch_sinta_publications(client: httpx.AsyncClient, sinta_id: str) -> dict:
    url = f"https://sinta.kemdiktisaintek.go.id/authors/profile/{sinta_id}/?view=googlescholar"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    r = await client.get(url, headers=headers)
    if r.status_code == 200:
        return parse_sinta_html(r.text)
    return None

async def update_lecturer_json(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    basic = data.get("basic_info", {})
    identity = data.get("identity", {})
    profiles = data.get("profiles", {})
    
    # Check if key info (email or profiles or publications) is missing
    has_email = bool(identity.get("email"))
    has_profiles = any(v for k, v in profiles.items() if k not in ["orcid", "scopus"])
    has_publications = len(data.get("research", {}).get("publication_titles", [])) > 0
    
    if has_publications:
        # We only want to process the 17 lecturers who have no publications
        return False
        
    name = basic.get("name")
    code = basic.get("code") or data.get("id")
    if not name or name == "nan":
        return False
        
    logger.info(f"Scraping missing details for: {name} ({code})")
    
    try:
        # 1. Self-healing: if publications are missing, try fetching from OpenAlex first
        openalex_profile = None
        if not has_publications:
            logger.info(f"Publications missing for {name}. Attempting to fetch from OpenAlex...")
            try:
                async with httpx.AsyncClient() as client:
                    openalex_profile = await scrape_lecturer_openalex(client, basic)
                if openalex_profile and openalex_profile.get("research", {}).get("publication_titles"):
                    logger.info(f"Successfully retrieved publications from OpenAlex for {name}.")
                    # Update research fields
                    data["research"] = openalex_profile["research"]
                    data["research"]["ai_categories"] = categorize_ai(data["research"])
                    
                    # Update profiles from OpenAlex
                    for key in ["orcid", "scopus"]:
                        val = openalex_profile["profiles"].get(key)
                        if val and not data["profiles"].get(key):
                            data["profiles"][key] = val
                            
                    # Recompute embeddings
                    kw_text = " ".join(data["research"]["keywords"])
                    pub_text = " ".join(data["research"]["publication_titles"])
                    data["embeddings"] = {
                        "keyword": compute_embedding(kw_text),
                        "publication": compute_embedding(pub_text)
                    }
                    has_publications = True
            except Exception as e:
                logger.warning(f"Error scraping from OpenAlex for {name}: {e}")

        # 1b. SINTA Fallback: if publications are still missing, try searching SINTA directly
        if not has_publications:
            logger.info(f"Publications still missing for {name}. Attempting SINTA search fallback...")
            try:
                async with httpx.AsyncClient() as client:
                    sinta_id = await search_sinta_author_async(client, name)
                    if sinta_id:
                        logger.info(f"Found SINTA ID {sinta_id} for {name}. Fetching publications from SINTA...")
                        sinta_res = await fetch_sinta_publications(client, sinta_id)
                        if sinta_res and sinta_res.get("publication_titles"):
                            logger.info(f"Successfully retrieved publications from SINTA for {name}.")
                            data["research"]["publication_titles"] = sinta_res["publication_titles"]
                            data["research"]["publication_years"] = sinta_res["publication_years"]
                            data["research"]["coauthors"] = sinta_res["coauthors"]
                            data["research"]["citation_count"] = sinta_res["citation_count"]
                            data["research"]["ai_categories"] = categorize_ai(data["research"])
                            data["profiles"]["sinta"] = f"https://sinta.kemdiktisaintek.go.id/authors/profile/{sinta_id}"
                            
                            # Recompute embeddings
                            kw_text = " ".join(data["research"]["keywords"])
                            pub_text = " ".join(data["research"]["publication_titles"])
                            data["embeddings"] = {
                                "keyword": compute_embedding(kw_text),
                                "publication": compute_embedding(pub_text)
                            }
                            has_publications = True
            except Exception as e:
                logger.warning(f"Error scraping from SINTA for {name}: {e}")
                
        # 2. Always search/scrape web profiles to fill missing identity details and links
        urls = await search_lecturer_profiles(name, "Telkom University")
        html_files = await download_pages(urls, f"{code}_raw")
        cleaned_files = [clean_html(f) for f in html_files]
        
        # Local HTML Parsers (Scholar / SINTA) fallback for publications
        local_publications = []
        local_years = []
        local_coauthors = set()
        local_citation_count = 0
        local_h_index = 0
        local_i10_index = 0
        
        extracted_data = []
        for raw_f, cf in zip(html_files, cleaned_files):
            # Parse Google Scholar HTML pages locally if they are verified
            is_scholar = False
            try:
                with open(raw_f, 'r', encoding='utf-8') as hf:
                    html_content = hf.read()
                if "scholar.google.com/citations?user=" in html_content or "‪Google Scholar‬" in html_content:
                    soup = BeautifulSoup(html_content, 'html.parser')
                    if verify_scholar_profile(soup, name):
                        logger.info(f"Found verified Google Scholar HTML for {name} in downloads. Parsing locally...")
                        res = parse_google_scholar_html(html_content)
                        if res and res.get("publication_titles"):
                            local_publications.extend(res["publication_titles"])
                            local_years.extend(res["publication_years"])
                            local_coauthors.update(res["coauthors"])
                            local_citation_count = max(local_citation_count, res["citation_count"])
                            local_h_index = max(local_h_index, res["h_index"])
                            local_i10_index = max(local_i10_index, res["i10_index"])
                            is_scholar = True
            except Exception as e:
                logger.warning(f"Error checking raw html for scholar profile: {e}")
                
            if is_scholar:
                continue # Skip Gemini for Google Scholar pages since we parse them locally!
                
            with open(cf, 'r', encoding='utf-8') as f:
                text = f.read()
                ext_data = None
                try:
                    ext_data = extract_information(text)
                except Exception as ex:
                    logger.warning(f"Failed to extract info with Gemini for {name}: {ex}")
                if ext_data:
                    base_url = get_url_from_html_file(raw_f)
                    if not ext_data.get("photo") and not ext_data.get("identity", {}).get("photo"):
                        try:
                            with open(raw_f, 'r', encoding='utf-8') as hf:
                                html_content = hf.read()
                            photo_url = extract_photo_url_from_html(html_content, base_url or "", name, code)
                            if photo_url:
                                if "identity" not in ext_data:
                                    ext_data["identity"] = {}
                                ext_data["identity"]["photo"] = photo_url
                        except Exception as pe:
                            logger.warning(f"Error photo: {pe}")
                    extracted_data.append(ext_data)
                    
        # Apply local parsed publications if any were found
        if not has_publications and local_publications:
            logger.info(f"Successfully retrieved publications from local HTML parse for {name}.")
            data["research"]["publication_titles"] = local_publications
            data["research"]["publication_years"] = local_years
            data["research"]["coauthors"] = list(local_coauthors)
            data["research"]["citation_count"] = local_citation_count
            data["research"]["h_index"] = local_h_index
            data["research"]["i10_index"] = local_i10_index
            data["research"]["ai_categories"] = categorize_ai(data["research"])
            
            # Recompute embeddings
            kw_text = " ".join(data["research"]["keywords"])
            pub_text = " ".join(data["research"]["publication_titles"])
            data["embeddings"] = {
                "keyword": compute_embedding(kw_text),
                "publication": compute_embedding(pub_text)
            }
            has_publications = True
            
        web_merged = merge_profiles(extracted_data, basic)
        search_profiles = extract_profiles_from_urls(urls)
        for platform, url in search_profiles.items():
            if url and not web_merged["profiles"].get(platform):
                web_merged["profiles"][platform] = url
                
        # 3. Merge web details into existing JSON
        # Update identity
        for key in ["full_name", "titles", "email", "photo"]:
            web_val = web_merged["identity"].get(key)
            if web_val and not data["identity"].get(key):
                data["identity"][key] = web_val
                
        # Update profiles
        for key in data["profiles"].keys():
            web_val = web_merged["profiles"].get(key)
            if web_val and not data["profiles"].get(key):
                data["profiles"][key] = web_val
                
        # 4. Fallback: If still no publications (OpenAlex/SINTA failed), use web-extracted publications (from other HTML pages parsed by Gemini)
        if not has_publications and web_merged.get("research", {}).get("publication_titles"):
            logger.info(f"Using web-extracted publications as fallback for {name}.")
            data["research"] = web_merged["research"]
            data["research"]["ai_categories"] = categorize_ai(data["research"])
            
            # Recompute embeddings
            kw_text = " ".join(data["research"]["keywords"])
            pub_text = " ".join(data["research"]["publication_titles"])
            data["embeddings"] = {
                "keyword": compute_embedding(kw_text),
                "publication": compute_embedding(pub_text)
            }
                
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
            
        logger.info(f"Successfully updated JSON for {name}")
        return True
    except Exception as e:
        logger.error(f"Failed to update {name}: {e}")
        return False

async def main():
    json_dir = settings.JSON_DIR
    if not os.path.exists(json_dir):
        logger.error(f"JSON directory {json_dir} does not exist.")
        return
        
    files = [os.path.join(json_dir, f) for f in os.listdir(json_dir) if f.endswith(".json")]
    logger.info(f"Found {len(files)} JSON files to inspect.")
    
    updated_count = 0
    for filepath in tqdm(files, desc="Updating JSON files"):
        success = await update_lecturer_json(filepath)
        if success:
            updated_count += 1
            await asyncio.sleep(2.0)  # Gentle delay between lecturers
            
    logger.info(f"Finished updating JSON files. Total updated: {updated_count}")
    print("\nNext step: Run 'python save_to_db.py' to reload the updated profiles to your database.")

if __name__ == "__main__":
    asyncio.run(main())
