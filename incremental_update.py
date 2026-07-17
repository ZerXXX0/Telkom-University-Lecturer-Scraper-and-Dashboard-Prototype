import os
import json
import asyncio
import httpx
import re
import numpy as np
from sqlalchemy.orm import Session, joinedload
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from tqdm import tqdm

from config import settings
from database.postgres import SessionLocal, init_db
from database.models import (
    Lecturer, Profile, Publication, Keyword, ResearchInterest, 
    Coauthor, Embedding, Recommendation, Collaboration
)
from utils.logger import get_logger
from parser.normalize import normalize_name, normalize_keyword, clean_name_for_search, extract_keywords_from_pub_titles
from parser.merge import categorize_ai
from embedding.embedder import compute_embedding
from recommendation.recommender import generate_recommendations
from scraper.openalex import fetch_url, search_author_on_openalex, get_author_works, scrape_lecturer_openalex
from main import (
    process_lecturer,
    search_lecturer_profiles,
    download_pages,
    clean_html,
    extract_information,
    extract_photo_url_from_html,
    get_url_from_html_file,
    extract_profiles_from_urls,
    merge_profiles
)

logger = get_logger("incremental_updater")

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



def classify_group(group_text: str) -> str:
    group_lower = group_text.lower()
    if 'dsis' in group_lower or 'data science' in group_lower or 'intelligent systems' in group_lower:
        return 'DSIS'
    if 'seal' in group_lower or 'software' in group_lower or 'rekayasa perangkat lunak' in group_lower:
        return 'SEAL'
    if 'citi' in group_lower or 'cyber' in group_lower or 'network' in group_lower or 'teknologi informasi' in group_lower:
        return 'CITI'
    return 'DSIS'

def lecturer_db_to_json(lecturer: Lecturer) -> dict:
    """Reconstruct profile JSON structure from database entities."""
    profiles_dict = {
        "google_scholar": None,
        "sinta": None,
        "orcid": None,
        "scopus": None
    }
    for p in lecturer.profiles:
        profiles_dict[p.platform] = p.url
        
    research_interests = [ri.interest for ri in lecturer.research_interests]
    keywords = [k.keyword for k in lecturer.keywords]
    coauthors = [ca.coauthor_name for ca in lecturer.coauthors]
    
    # Sort publications by database ID to preserve original order
    publications = sorted(lecturer.publications, key=lambda x: x.id)
    publication_titles = [p.title for p in publications]
    publication_years = [p.year if p.year is not None else 0 for p in publications]
    
    embedding_data = {}
    if lecturer.embeddings:
        kw_emb = lecturer.embeddings.keyword_embedding
        pub_emb = lecturer.embeddings.publication_embedding
        
        if kw_emb is not None:
            if hasattr(kw_emb, "tolist"):
                kw_emb = kw_emb.tolist()
            elif isinstance(kw_emb, np.ndarray):
                kw_emb = list(kw_emb)
            else:
                kw_emb = list(kw_emb)
                
        if pub_emb is not None:
            if hasattr(pub_emb, "tolist"):
                pub_emb = pub_emb.tolist()
            elif isinstance(pub_emb, np.ndarray):
                pub_emb = list(pub_emb)
            else:
                pub_emb = list(pub_emb)
                
        embedding_data = {
            "keyword": kw_emb,
            "publication": pub_emb
        }
        
    return {
        "basic_info": {
            "name": lecturer.full_name,
            "code": lecturer.code,
            "study_program": lecturer.study_program,
            "research_group": lecturer.research_group,
            "academic_rank": lecturer.academic_rank,
            "field": lecturer.field,
            "lecturer_code": lecturer.lecturer_code
        },
        "identity": {
            "full_name": lecturer.full_name,
            "titles": lecturer.titles,
            "name_with_title": lecturer.name_with_title,
            "email": lecturer.email,
            "photo": lecturer.photo
        },
        "profiles": profiles_dict,
        "research": {
            "research_interests": research_interests,
            "keywords": keywords,
            "ai_categories": lecturer.ai_categories or [],
            "publication_titles": publication_titles,
            "publication_years": publication_years,
            "coauthors": coauthors,
            "sinta_scopus_citations": lecturer.sinta_scopus_citations,
            "sinta_scopus_h_index": lecturer.sinta_scopus_h_index,
            "sinta_scopus_i10_index": lecturer.sinta_scopus_i10_index,
            "sinta_scholar_citations": lecturer.sinta_scholar_citations,
            "sinta_scholar_h_index": lecturer.sinta_scholar_h_index,
            "sinta_scholar_i10_index": lecturer.sinta_scholar_i10_index,
            "sinta_wos_citations": lecturer.sinta_wos_citations,
            "sinta_wos_h_index": lecturer.sinta_wos_h_index,
            "sinta_wos_i10_index": lecturer.sinta_wos_i10_index,
            "citation_count": lecturer.citation_count,
            "h_index": lecturer.h_index,
            "i10_index": lecturer.i10_index
        },
        "embeddings": embedding_data,
        "sinta_metrics": lecturer.sinta_metrics or {}
    }

PROGRESS_FILE = os.path.abspath(".update_progress.json")

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {
                    "completed_existing": set(data.get("completed_existing", [])),
                    "completed_new": set(data.get("completed_new", [])),
                    "has_changes": data.get("has_changes", False)
                }
        except Exception as e:
            logger.warning(f"Failed to load progress file: {e}. Starting fresh.")
    return {"completed_existing": set(), "completed_new": set(), "has_changes": False}

def save_progress(progress):
    try:
        os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                "completed_existing": list(progress["completed_existing"]),
                "completed_new": list(progress["completed_new"]),
                "has_changes": progress["has_changes"]
            }, f, indent=4)
    except Exception as e:
        logger.warning(f"Failed to save progress: {e}")

def clear_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            os.remove(PROGRESS_FILE)
            logger.info("Cleared progress file.")
        except Exception as e:
            logger.warning(f"Failed to remove progress file: {e}")

def restore_json_from_db(skip_codes=None):
    """Sync manual edits in DB back to JSON files to ensure they are not overwritten."""
    if skip_codes is None:
        skip_codes = set()
    try:
        db: Session = SessionLocal()
        db_lecturers = db.query(Lecturer).all()
    except Exception as e:
        logger.warning(f"Database connection failed during JSON restore: {e}. Skipping DB-to-JSON sync.")
        return

    os.makedirs(settings.JSON_DIR, exist_ok=True)
    logger.info(f"Syncing manual edits and restoring database records to JSON (total: {len(db_lecturers)})...")
    for lecturer in db_lecturers:
        code = lecturer.code
        if code in skip_codes:
            logger.info(f"Skipping JSON restore for lecturer {code} (already updated in previous runs).")
            continue
        db_json = lecturer_db_to_json(lecturer)
        json_path = os.path.join(settings.JSON_DIR, f"{code}.json")
        
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                local_data = json.load(f)
                
            # Merge fields (prefer database edits as the source of truth)
            for k, v in db_json["basic_info"].items():
                if v: local_data["basic_info"][k] = v
                
            for k, v in db_json["identity"].items():
                if v: local_data["identity"][k] = v
                
            for k, v in db_json["profiles"].items():
                if v: local_data["profiles"][k] = v
                
            if db_json.get("research", {}).get("publication_titles"):
                local_data["research"] = db_json["research"]
                
            if db_json.get("embeddings"):
                local_data["embeddings"] = db_json["embeddings"]
                
            if db_json.get("sinta_metrics"):
                local_data["sinta_metrics"] = db_json["sinta_metrics"]
                
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(local_data, f, indent=4)
        else:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(db_json, f, indent=4)
    db.close()

async def scrape_soc_lecturers_extended():
    """Scrape the lecturer list with extended columns: Kelompok Keahlian and Research Interest."""
    logger.info("Launching Playwright to scrape SOC lecturer directory page...")
    proxy_env = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("ALL_PROXY")
    launch_kwargs = {"headless": True}
    if proxy_env:
        launch_kwargs["proxy"] = {"server": proxy_env}
        logger.info(f"Using Playwright proxy: {proxy_env}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        url = "https://soc.telkomuniversity.ac.id/dosen-fakultas-informatika/"
        logger.info(f"Navigating to {url}...")
        await page.goto(url, timeout=60000)
        try:
            await page.wait_for_selector('#tablepress-22', timeout=30000)
        except Exception as e:
            logger.warning(f"wait_for_selector failed, sleeping 5 seconds as fallback. Error: {e}")
            await asyncio.sleep(5)
        
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        table = soup.select_one('#tablepress-22')
        if not table:
            logger.error("Table #tablepress-22 not found on page!")
            await browser.close()
            return []
            
        rows = table.select('tbody tr')
        logger.info(f"Found {len(rows)} rows in table.")
        
        scraped_data = []
        for row in rows:
            cols = row.select('td')
            if len(cols) < 8:
                continue
                
            img = cols[1].find('img')
            photo_url = None
            if img:
                photo_url = img.get('data-src') or img.get('src')
                if photo_url and photo_url.startswith('data:'):
                    photo_url = None
            
            name = cols[2].get_text(strip=True)
            lecturer_code = cols[3].get_text(strip=True)
            nip = cols[4].get_text(strip=True)
            if nip and '-' in nip:
                nip = nip.split('-')[0].strip()
            research_group_text = cols[5].get_text(strip=True)
            field_text = cols[6].get_text(strip=True)
            
            sinta_url = None
            scholar_url = None
            scopus_url = None
            links = cols[7].find_all('a')
            for link in links:
                href = link.get('href', '')
                text = link.get_text(strip=True).lower()
                if 'sinta' in text or 'sinta' in href:
                    sinta_url = href
                elif 'scholar' in text or 'scholar' in href or 'citations?user=' in href:
                    scholar_url = href
                elif 'scopus' in text or 'scopus' in href:
                    scopus_url = href
            
            scraped_data.append({
                "photo_url": photo_url,
                "name": name,
                "code": lecturer_code,
                "nip": nip,
                "research_group_text": research_group_text,
                "field_text": field_text,
                "sinta_url": sinta_url,
                "scholar_url": scholar_url,
                "scopus_url": scopus_url
            })
            
        await browser.close()
        logger.info(f"Scraped {len(scraped_data)} lecturers from SOC website.")
        return scraped_data

def parse_metrics_table(html):
    soup = BeautifulSoup(html, 'html.parser')
    t = soup.find('table')
    if not t:
        return None
    
    headers = []
    header_tr = t.find('tr')
    if header_tr:
        headers = [th.get_text(strip=True).lower() for th in header_tr.find_all(['td', 'th'])]
    
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
    
    rows = t.find_all('tr')[1:]
    for r in rows:
        cells = [c.get_text(strip=True) for c in r.find_all(['td', 'th'])]
        if not cells:
            continue
        
        label = cells[0].lower().replace(" ", "_").replace("-", "_")
        
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

async def fetch_sinta_metrics_for_lecturer(client, name, sinta_url):
    match = re.search(r'/profile/(\d+)', sinta_url)
    if not match:
        logger.warning(f"Could not extract Sinta ID from URL: {sinta_url} for {name}")
        return None
    sinta_id = match.group(1)
    url = f"https://sinta.kemdiktisaintek.go.id/authors/profile/{sinta_id}/?view=metrics"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    for attempt in range(3):
        try:
            r = await client.get(url, headers=headers, timeout=15.0)
            if r.status_code == 200:
                metrics = parse_metrics_table(r.text)
                if metrics:
                    logger.info(f"Successfully fetched Sinta metrics for {name}")
                    return metrics
            elif r.status_code == 404:
                return None
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed to fetch Sinta metrics for {name}: {e}")
        await asyncio.sleep(1.0)
    return None

def parse_field_text(field_text: str) -> list[str]:
    if not field_text:
        return []
    parts = re.split(r',|;', field_text)
    cleaned = []
    for p in parts:
        p_clean = p.strip()
        if p_clean and len(p_clean) > 2:
            p_clean = " ".join(w.capitalize() for w in p_clean.split())
            cleaned.append(p_clean)
    return cleaned


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


async def fetch_sinta_publications_for_view(client: httpx.AsyncClient, sinta_id: str, view: str) -> dict:
    url = f"https://sinta.kemdiktisaintek.go.id/authors/profile/{sinta_id}/?view={view}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        r = await client.get(url, headers=headers)
        if r.status_code == 200:
            return parse_sinta_html(r.text)
    except Exception as e:
        logger.warning(f"Error fetching SINTA view {view} for {sinta_id}: {e}")
    return None

async def fetch_sinta_publications(client: httpx.AsyncClient, sinta_id: str) -> dict:
    views = ["googlescholar", "scopus", "wos"]
    merged = {
        "publication_titles": [],
        "publication_years": [],
        "coauthors": set(),
        "citation_count": 0
    }
    
    seen_titles = set()
    for view in views:
        res = await fetch_sinta_publications_for_view(client, sinta_id, view)
        if res:
            for title, year in zip(res.get("publication_titles", []), res.get("publication_years", [])):
                norm_title = title.lower().strip()
                if norm_title not in seen_titles:
                    seen_titles.add(norm_title)
                    merged["publication_titles"].append(title)
                    merged["publication_years"].append(year)
            merged["coauthors"].update(res.get("coauthors", []))
            merged["citation_count"] = max(merged["citation_count"], res.get("citation_count", 0))
            
    merged["coauthors"] = list(merged["coauthors"])
    return merged

async def get_latest_openalex_publications(client, name, db_profiles):
    """Retrieve publications from OpenAlex using ORCID or Name search."""
    orcid = db_profiles.get("orcid")
    author_id = None
    author_profile = None
    
    if orcid:
        clean_orcid = orcid.replace("https://orcid.org/", "").strip()
        url = f"https://api.openalex.org/authors/orcid:{clean_orcid}"
        try:
            data = await fetch_url(client, url)
            if data:
                author_profile = data
                author_id = data.get("id")
                logger.info(f"Found OpenAlex profile via ORCID {orcid}: {author_id}")
        except Exception as e:
            logger.warning(f"Error searching by ORCID on OpenAlex for {name}: {e}")
            
    if not author_id:
        author_profile = await search_author_on_openalex(client, name)
        if author_profile:
            author_id = author_profile.get("id")
            
    if author_id:
        works = await get_author_works(client, author_id)
        return works, author_profile
        
    return [], None

async def check_and_update_publications(client, name, code, db_profiles, photo_url=None, soc_item=None):
    """Check if there are any new publications, profiles, or metrics for this lecturer and update them."""
    works, author_profile = await get_latest_openalex_publications(client, name, db_profiles)
    
    json_path = os.path.join(settings.JSON_DIR, f"{code}.json")
    if not os.path.exists(json_path):
        return False, None
        
    with open(json_path, 'r', encoding='utf-8') as f:
        local_data = json.load(f)
        
    res = local_data.setdefault("research", {})
    profiles = local_data.setdefault("profiles", {})
    
    has_changes = False
    
    # 1. Update profiles from SOC scraped data
    if soc_item:
        if soc_item.get("sinta_url") and not profiles.get("sinta"):
            profiles["sinta"] = soc_item["sinta_url"]
            has_changes = True
        if soc_item.get("scholar_url") and not profiles.get("google_scholar"):
            profiles["google_scholar"] = soc_item["scholar_url"]
            has_changes = True
        if soc_item.get("scopus_url") and not profiles.get("scopus"):
            profiles["scopus"] = soc_item["scopus_url"]
            has_changes = True
            
    # 2. Merge field_text from SOC into research_interests and keywords
    if soc_item and soc_item.get("field_text"):
        field_interests = parse_field_text(soc_item["field_text"])
        if field_interests:
            existing_interests = {ri.lower().strip() for ri in res.setdefault("research_interests", [])}
            existing_keywords = {kw.lower().strip() for kw in res.setdefault("keywords", [])}
            
            interests_added = False
            for fi in field_interests:
                if fi.lower().strip() not in existing_interests:
                    res["research_interests"].append(fi)
                    interests_added = True
                if fi.lower().strip() not in existing_keywords:
                    res["keywords"].append(normalize_keyword(fi))
                    interests_added = True
            if interests_added:
                has_changes = True

    # 3. Fetch SINTA metrics if sinta_url is present and sinta_metrics is empty
    sinta_url = profiles.get("sinta")
    if sinta_url and not local_data.get("sinta_metrics"):
        metrics = await fetch_sinta_metrics_for_lecturer(client, name, sinta_url)
        if metrics:
            local_data["sinta_metrics"] = metrics
            
            res["sinta_scopus_citations"] = metrics.get("scopus", {}).get("citation", 0)
            res["sinta_scopus_h_index"] = metrics.get("scopus", {}).get("h_index", 0)
            res["sinta_scopus_i10_index"] = metrics.get("scopus", {}).get("i10_index", 0)
            
            res["sinta_scholar_citations"] = metrics.get("google_scholar", {}).get("citation", 0)
            res["sinta_scholar_h_index"] = metrics.get("google_scholar", {}).get("h_index", 0)
            res["sinta_scholar_i10_index"] = metrics.get("google_scholar", {}).get("i10_index", 0)
            
            res["sinta_wos_citations"] = metrics.get("wos", {}).get("citation", 0)
            res["sinta_wos_h_index"] = metrics.get("wos", {}).get("h_index", 0)
            res["sinta_wos_i10_index"] = metrics.get("wos", {}).get("i10_index", 0)
            
            # Also update base citation metrics if sinta has them
            res["citation_count"] = res["sinta_scholar_citations"] or res.get("citation_count", 0)
            res["h_index"] = res["sinta_scholar_h_index"] or res.get("h_index", 0)
            res["i10_index"] = res["sinta_scholar_i10_index"] or res.get("i10_index", 0)
            
            has_changes = True

    # 4. Process new publications from OpenAlex
    scraped_titles = []
    scraped_years = []
    scraped_coauthors = set()
    scraped_keywords = set()
    
    if works:
        for work in works:
            title = work.get("title")
            if title:
                scraped_titles.append(title)
            year = work.get("publication_year")
            scraped_years.append(year if year else 0)
            
            authorships = work.get("authorships", [])
            for auth in authorships:
                ca_name = auth.get("author", {}).get("display_name")
                if ca_name:
                    scraped_coauthors.add(normalize_name(ca_name))
                    
            work_concepts = work.get("concepts", [])
            for c in work_concepts:
                c_name = c.get("display_name")
                if c_name:
                    scraped_keywords.add(normalize_keyword(c_name))
                    
        existing_titles = {t.lower().strip() for t in res.get("publication_titles", [])}
        new_titles = [t for t in scraped_titles if t.lower().strip() not in existing_titles]
        
        citation_count = author_profile.get("cited_by_count", 0) if author_profile else res.get("citation_count", 0)
        summary_stats = author_profile.get("summary_stats", {}) if author_profile else {}
        h_index = summary_stats.get("h_index", 0) if summary_stats else res.get("h_index", 0)
        i10_index = summary_stats.get("i10_index", 0) if summary_stats else res.get("i10_index", 0)
        
        if citation_count > res.get("citation_count", 0):
            res["citation_count"] = citation_count
            res["h_index"] = h_index
            res["i10_index"] = i10_index
            has_changes = True
            
        if new_titles:
            # Append new publications and years
            res.setdefault("publication_titles", []).extend(new_titles)
            for title in new_titles:
                idx = scraped_titles.index(title)
                res.setdefault("publication_years", []).append(scraped_years[idx])
                
            # Merge coauthors and keywords
            local_coauthors = set(res.get("coauthors", []))
            local_coauthors.update(scraped_coauthors)
            res["coauthors"] = list(local_coauthors)
            
            local_keywords = set(res.get("keywords", []))
            local_keywords.update(scraped_keywords)
            res["keywords"] = list(local_keywords)
            
            has_changes = True

    # 5. Process Photo URL
    if photo_url and not local_data.get("identity", {}).get("photo"):
        local_data.setdefault("identity", {})["photo"] = photo_url
        has_changes = True
        
    if has_changes:
        logger.info(f"Updates found for {name} ({code}).")
        
        # Recompute categories and embeddings
        res["ai_categories"] = categorize_ai(res)
        
        kw_text = " ".join(res.get("keywords", []))
        pub_text = " ".join(res.get("publication_titles", []))
        local_data["embeddings"] = {
            "keyword": compute_embedding(kw_text) if kw_text else [0.0]*384,
            "publication": compute_embedding(pub_text) if pub_text else [0.0]*384
        }
        
        local_data["research"] = res
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(local_data, f, indent=4)
            
        return True, local_data
        
    return False, local_data

def sync_all_to_db():
    """Sync the local JSON profiles into the relational database using an upsert mechanism."""
    db: Session = SessionLocal()
    init_db()  # Ensure tables are properly created
    
    json_dir = settings.JSON_DIR
    lecturer_data = []
    for filename in os.listdir(json_dir):
        if not filename.endswith(".json"): continue
        with open(os.path.join(json_dir, filename), 'r') as f:
            data = json.load(f)
            lecturer_data.append(data)
            
    code_to_id = {}
    logger.info("Syncing base lecturer records...")
    for data in lecturer_data:
        basic = data.get("basic_info", {})
        identity = data.get("identity", {})
        research = data.get("research", {})
        code = basic.get("code") or data.get("id")
        
        db_lecturer = db.query(Lecturer).filter_by(code=code).first()
        if not db_lecturer:
            db_lecturer = Lecturer(code=code)
            db.add(db_lecturer)
            
        db_lecturer.lecturer_code = basic.get("lecturer_code")
        db_lecturer.study_program = basic.get("study_program")
        db_lecturer.research_group = basic.get("research_group")
        db_lecturer.academic_rank = basic.get("academic_rank")
        db_lecturer.field = basic.get("field")
        
        db_lecturer.full_name = identity.get("full_name")
        db_lecturer.titles = identity.get("titles")
        db_lecturer.name_with_title = identity.get("name_with_title")
        db_lecturer.email = identity.get("email")
        db_lecturer.photo = identity.get("photo")
        
        db_lecturer.citation_count = research.get("sinta_scholar_citations", 0) or research.get("citation_count", 0)
        db_lecturer.h_index = research.get("sinta_scholar_h_index", 0) or research.get("h_index", 0)
        db_lecturer.i10_index = research.get("sinta_scholar_i10_index", 0) or research.get("i10_index", 0)
        
        db_lecturer.sinta_scopus_citations = research.get("sinta_scopus_citations", 0)
        db_lecturer.sinta_scopus_h_index = research.get("sinta_scopus_h_index", 0)
        db_lecturer.sinta_scopus_i10_index = research.get("sinta_scopus_i10_index", 0)
        
        db_lecturer.sinta_scholar_citations = research.get("sinta_scholar_citations", 0)
        db_lecturer.sinta_scholar_h_index = research.get("sinta_scholar_h_index", 0)
        db_lecturer.sinta_scholar_i10_index = research.get("sinta_scholar_i10_index", 0)
        
        db_lecturer.sinta_wos_citations = research.get("sinta_wos_citations", 0)
        db_lecturer.sinta_wos_h_index = research.get("sinta_wos_h_index", 0)
        db_lecturer.sinta_wos_i10_index = research.get("sinta_wos_i10_index", 0)
        
        db_lecturer.ai_categories = research.get("ai_categories", [])
        db_lecturer.sinta_metrics = data.get("sinta_metrics", {})
        
        db.commit()
        db.refresh(db_lecturer)
        code_to_id[code] = db_lecturer.id

    logger.info("Syncing lecturer relational details...")
    for data in lecturer_data:
        basic = data.get("basic_info", {})
        research = data.get("research", {})
        profiles = data.get("profiles", {})
        emb = data.get("embeddings")
        code = basic.get("code") or data.get("id")
        
        lecturer_id = code_to_id.get(code)
        if not lecturer_id:
            continue
            
        # Update Profiles (wipes only this lecturer's profiles and re-inserts)
        db.query(Profile).filter_by(lecturer_id=lecturer_id).delete()
        for platform, url in profiles.items():
            if url:
                db.add(Profile(lecturer_id=lecturer_id, platform=platform, url=url))
                
        # Update Keywords
        db.query(Keyword).filter_by(lecturer_id=lecturer_id).delete()
        for kw in research.get("keywords", []):
            db.add(Keyword(lecturer_id=lecturer_id, keyword=kw))
            
        # Update Research Interests
        db.query(ResearchInterest).filter_by(lecturer_id=lecturer_id).delete()
        for ri in research.get("research_interests", []):
            db.add(ResearchInterest(lecturer_id=lecturer_id, interest=ri))
            
        # Update Publications
        db.query(Publication).filter_by(lecturer_id=lecturer_id).delete()
        pub_titles = research.get("publication_titles", [])
        pub_years = research.get("publication_years", [])
        for i, pub in enumerate(pub_titles):
            year = pub_years[i] if i < len(pub_years) else None
            db.add(Publication(lecturer_id=lecturer_id, title=pub, year=year))
            
        # Update Coauthors
        db.query(Coauthor).filter_by(lecturer_id=lecturer_id).delete()
        for ca in research.get("coauthors", []):
            db.add(Coauthor(lecturer_id=lecturer_id, coauthor_name=ca))
            
        # Update Embeddings
        db.query(Embedding).filter_by(lecturer_id=lecturer_id).delete()
        if emb:
            db.add(Embedding(
                lecturer_id=lecturer_id,
                keyword_embedding=emb.get("keyword"),
                publication_embedding=emb.get("publication")
            ))
            
        # Update Recommendations
        db.query(Recommendation).filter_by(lecturer_id=lecturer_id).delete()
        recs = data.get("recommendations", [])
        for rec in recs:
            rec_code = rec.get("recommended_lecturer_id")
            rec_lecturer_id = code_to_id.get(rec_code)
            if rec_lecturer_id:
                db.add(Recommendation(
                    lecturer_id=lecturer_id,
                    recommended_lecturer_id=rec_lecturer_id,
                    score=rec.get("score"),
                    reasons=rec.get("reasons", [])
                ))
        db.commit()

    logger.info("Rebuilding collaboration network...")
    db.query(Collaboration).delete()
    db.commit()
    
    pub_to_lecturers = {}
    for data in lecturer_data:
        basic = data.get("basic_info", {})
        code = basic.get("code") or data.get("id")
        lecturer_id = code_to_id.get(code)
        if not lecturer_id:
            continue
        research = data.get("research", {})
        for title in research.get("publication_titles", []):
            t_clean = title.strip().lower()
            if not t_clean: continue
            if t_clean not in pub_to_lecturers:
                pub_to_lecturers[t_clean] = []
            pub_to_lecturers[t_clean].append((lecturer_id, title))
            
    from collections import defaultdict
    pair_collabs = defaultdict(list)
    for t_clean, lecturers_list in pub_to_lecturers.items():
        if len(lecturers_list) > 1:
            unique_lecturers = list(set(lecturers_list))
            for i in range(len(unique_lecturers)):
                for j in range(i+1, len(unique_lecturers)):
                    id1, title1 = unique_lecturers[i]
                    id2, title2 = unique_lecturers[j]
                    if id1 == id2: continue
                    p1, p2 = sorted([id1, id2])
                    pair_collabs[(p1, p2)].append(title1)
                    
    for (id1, id2), shared_pubs in pair_collabs.items():
        db.add(Collaboration(
            lecturer_id_1=id1,
            lecturer_id_2=id2,
            collaboration_count=len(shared_pubs),
            shared_publications=shared_pubs
        ))
    db.commit()
    db.close()
    logger.info("Incremental database sync completed!")


async def process_new_lecturer(item):
    name = item.get("name")
    code = item.get("nip") or f"new_{item.get('code')}"
    search_name = clean_name_for_search(name)
    
    logger.info(f"Processing new lecturer: {name} ({code}) - Search Name: {search_name}")
    
    # 1. Initialize default profile structure
    profile = {
        "basic_info": {
            "name": name,
            "code": code,
            "study_program": "",
            "research_group": classify_group(item.get("research_group_text", "")),
            "academic_rank": "",
            "field": item.get("field_text", ""),
            "lecturer_code": item.get("code")
        },
        "identity": {
            "full_name": clean_name_for_search(name),
            "titles": None,
            "name_with_title": name,
            "email": None,
            "photo": item.get("photo_url")
        },
        "profiles": {
            "google_scholar": item.get("scholar_url"),
            "sinta": item.get("sinta_url"),
            "orcid": None,
            "scopus": item.get("scopus_url")
        },
        "research": {
            "research_interests": parse_field_text(item.get("field_text", "")),
            "keywords": [normalize_keyword(k) for k in parse_field_text(item.get("field_text", ""))],
            "ai_categories": [],
            "publication_titles": [],
            "publication_years": [],
            "coauthors": [],
            "sinta_scopus_citations": 0,
            "sinta_scopus_h_index": 0,
            "sinta_scopus_i10_index": 0,
            "sinta_scholar_citations": 0,
            "sinta_scholar_h_index": 0,
            "sinta_scholar_i10_index": 0,
            "sinta_wos_citations": 0,
            "sinta_wos_h_index": 0,
            "sinta_wos_i10_index": 0,
            "citation_count": 0,
            "h_index": 0,
            "i10_index": 0
        },
        "embeddings": {},
        "recommendations": [],
        "sinta_metrics": {}
    }
    
    has_publications = False
    
    # Stage 1: Try OpenAlex
    try:
        async with httpx.AsyncClient() as client:
            openalex_profile = await scrape_lecturer_openalex(client, profile["basic_info"])
        if openalex_profile and openalex_profile.get("research", {}).get("publication_titles"):
            logger.info(f"Successfully retrieved publications from OpenAlex for {name}.")
            profile["research"] = openalex_profile["research"]
            for key in ["orcid", "scopus"]:
                val = openalex_profile["profiles"].get(key)
                if val:
                    profile["profiles"][key] = val
            has_publications = True
    except Exception as e:
        logger.warning(f"Error scraping from OpenAlex for {name}: {e}")
        
    # Stage 2: SINTA fallback
    if not has_publications:
        sinta_url = profile["profiles"].get("sinta")
        sinta_id = None
        if sinta_url:
            match = re.search(r'/profile/(\d+)', sinta_url)
            if match:
                sinta_id = match.group(1)
                
        async with httpx.AsyncClient() as client:
            if not sinta_id:
                try:
                    sinta_id = await search_sinta_author_async(client, search_name)
                except Exception as e:
                    logger.warning(f"Error searching SINTA author: {e}")
            
            if sinta_id:
                if not profile["profiles"].get("sinta"):
                    profile["profiles"]["sinta"] = f"https://sinta.kemdiktisaintek.go.id/authors/profile/{sinta_id}"
                try:
                    sinta_res = await fetch_sinta_publications(client, sinta_id)
                    if sinta_res and sinta_res.get("publication_titles"):
                        logger.info(f"Successfully retrieved publications from SINTA for {name}.")
                        profile["research"]["publication_titles"] = sinta_res["publication_titles"]
                        profile["research"]["publication_years"] = sinta_res["publication_years"]
                        profile["research"]["coauthors"] = sinta_res["coauthors"]
                        profile["research"]["citation_count"] = sinta_res["citation_count"]
                        has_publications = True
                except Exception as e:
                    logger.warning(f"Error fetching SINTA publications: {e}")
                    
    # Stage 3: Always search/scrape web profiles to fill missing identity details and links
    try:
        urls = await search_lecturer_profiles(search_name, "Telkom University")
        html_files = await download_pages(urls, f"{code}_raw")
        cleaned_files = [clean_html(f) for f in html_files]
        
        local_publications = []
        local_years = []
        local_coauthors = set()
        local_citation_count = 0
        local_h_index = 0
        local_i10_index = 0
        
        extracted_data = []
        verified_scholar_url = None
        for raw_f, cf in zip(html_files, cleaned_files):
            is_scholar = False
            try:
                with open(raw_f, 'r', encoding='utf-8') as hf:
                    html_content = hf.read()
                if "scholar.google.com/citations?user=" in html_content or "‪Google Scholar‬" in html_content:
                    soup = BeautifulSoup(html_content, 'html.parser')
                    if verify_scholar_profile(soup, search_name):
                        logger.info(f"Found verified Google Scholar HTML for {name} in downloads. Parsing locally...")
                        verified_scholar_url = get_url_from_html_file(raw_f)
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
                continue
                
            try:
                with open(cf, 'r', encoding='utf-8') as f:
                    text = f.read()
                if len(text) > 100:
                    ext_data = extract_information(text)
                    if isinstance(ext_data, list):
                        if ext_data and isinstance(ext_data[0], dict):
                            ext_data = ext_data[0]
                        else:
                            ext_data = {}
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
            except Exception as ex:
                logger.warning(f"Failed to read/extract info: {ex}")
                
        if not has_publications and local_publications:
            logger.info(f"Successfully retrieved publications from local HTML parse for {name}.")
            profile["research"]["publication_titles"] = local_publications
            profile["research"]["publication_years"] = local_years
            profile["research"]["coauthors"] = list(local_coauthors)
            profile["research"]["citation_count"] = local_citation_count
            profile["research"]["h_index"] = local_h_index
            profile["research"]["i10_index"] = local_i10_index
            has_publications = True
            
        web_merged = merge_profiles(extracted_data, profile["basic_info"])
        search_profiles = extract_profiles_from_urls(urls)
        for platform, url in search_profiles.items():
            if platform == "google_scholar":
                if verified_scholar_url:
                    profile["profiles"]["google_scholar"] = verified_scholar_url
            else:
                if url and not profile["profiles"].get(platform):
                    profile["profiles"][platform] = url
                
        # Merge web identity details
        for key in ["full_name", "titles", "email", "photo"]:
            web_val = web_merged["identity"].get(key)
            if web_val and not profile["identity"].get(key):
                profile["identity"][key] = web_val
                
        for key in profile["profiles"].keys():
            web_val = web_merged["profiles"].get(key)
            if web_val and not profile["profiles"].get(key):
                profile["profiles"][key] = web_val
                
        if not has_publications and web_merged.get("research", {}).get("publication_titles"):
            logger.info(f"Using web-extracted publications as fallback for {name}.")
            profile["research"] = web_merged["research"]
            has_publications = True
    except Exception as e:
        logger.warning(f"Error during web scraping fallback for {name}: {e}")
        
    # Fetch SINTA metrics
    sinta_url = profile["profiles"].get("sinta")
    if sinta_url:
        try:
            async with httpx.AsyncClient() as client:
                metrics = await fetch_sinta_metrics_for_lecturer(client, name, sinta_url)
            if metrics:
                profile["sinta_metrics"] = metrics
                res = profile["research"]
                res["sinta_scopus_citations"] = metrics.get("scopus", {}).get("citation", 0)
                res["sinta_scopus_h_index"] = metrics.get("scopus", {}).get("h_index", 0)
                res["sinta_scopus_i10_index"] = metrics.get("scopus", {}).get("i10_index", 0)
                
                res["sinta_scholar_citations"] = metrics.get("google_scholar", {}).get("citation", 0)
                res["sinta_scholar_h_index"] = metrics.get("google_scholar", {}).get("h_index", 0)
                res["sinta_scholar_i10_index"] = metrics.get("google_scholar", {}).get("i10_index", 0)
                
                res["sinta_wos_citations"] = metrics.get("wos", {}).get("citation", 0)
                res["sinta_wos_h_index"] = metrics.get("wos", {}).get("h_index", 0)
                res["sinta_wos_i10_index"] = metrics.get("wos", {}).get("i10_index", 0)
                
                res["citation_count"] = res["sinta_scholar_citations"] or res.get("citation_count", 0)
                res["h_index"] = res["sinta_scholar_h_index"] or res.get("h_index", 0)
                res["i10_index"] = res["sinta_scholar_i10_index"] or res.get("i10_index", 0)
        except Exception as e:
            logger.warning(f"Error fetching SINTA metrics for {name}: {e}")
            
    # Post-process: compute categories and embeddings
    if not profile["research"].get("keywords") and profile["research"].get("publication_titles"):
        profile["research"]["keywords"] = extract_keywords_from_pub_titles(profile["research"]["publication_titles"])
        
    profile["research"]["ai_categories"] = categorize_ai(profile["research"])
    kw_text = " ".join(profile["research"].get("keywords", []))
    pub_text = " ".join(profile["research"].get("publication_titles", []))
    profile["embeddings"] = {
        "keyword": compute_embedding(kw_text) if kw_text else [0.0]*384,
        "publication": compute_embedding(pub_text) if pub_text else [0.0]*384
    }
    
    # Save JSON file
    json_path = os.path.join(settings.JSON_DIR, f"{code}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(profile, f, indent=4)
        
    return profile

class MockProfile:
    def __init__(self, platform, url):
        self.platform = platform
        self.url = url

class MockLecturer:
    def __init__(self, data):
        self.code = data.get("basic_info", {}).get("code") or data.get("id")
        self.name = data.get("basic_info", {}).get("name")
        self.profiles = [MockProfile(platform, url) for platform, url in data.get("profiles", {}).items() if url]

async def main():
    # Load any progress from a previous interrupted run
    progress = load_progress()
    skip_codes = progress["completed_existing"].union(progress["completed_new"])
    
    # Step 1: Restore and update JSON cache from DB first (recovers manual DB edits, skipping completed ones)
    restore_json_from_db(skip_codes=skip_codes)
    
    # Step 2: Connect to DB and gather existing records
    db_lecturers = []
    db_connected = False
    try:
        db = SessionLocal()
        db_lecturers = db.query(Lecturer).options(joinedload(Lecturer.profiles)).all()
        db.close()
        db_connected = True
    except Exception as e:
        logger.warning(f"Database connection failed: {e}. Falling back to local JSON cache for matching.")
        db_lecturers = []
        if os.path.exists(settings.JSON_DIR):
            for filename in os.listdir(settings.JSON_DIR):
                if filename.endswith(".json") and filename != ".update_progress.json":
                    try:
                        with open(os.path.join(settings.JSON_DIR, filename), 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        db_lecturers.append(MockLecturer(data))
                    except Exception as je:
                        logger.warning(f"Failed to load JSON file {filename} for mock DB: {je}")
    
    # Step 3: Scrape latest lecturer directory from SOC
    scraped_lecturers = await scrape_soc_lecturers_extended()
    if not scraped_lecturers:
        logger.error("Failed to scrape lecturer directory from SOC website. Exiting.")
        return
        
    # Step 4: Compare lists to identify new vs existing lecturers
    new_lecturers = []
    existing_lecturers = []
    
    for item in scraped_lecturers:
        nip = item.get("nip", "").strip()
        name = item.get("name", "").strip()
        
        matched_db = None
        if nip:
            matched_db = next((l for l in db_lecturers if l.code == nip), None)
            
        if not matched_db:
            base_name = get_base_name(name)
            matched_db = next((l for l in db_lecturers if get_base_name(l.full_name) == base_name), None)
            
        # Re-route lecturers with 0 publications to new_lecturers to force re-scraping
        has_no_pubs = False
        code_to_check = nip or (f"new_{item.get('code')}" if item.get('code') else "")
        if matched_db:
            code_to_check = matched_db.code
            
        if code_to_check:
            json_path = os.path.join(settings.JSON_DIR, f"{code_to_check}.json")
            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        l_data = json.load(f)
                    pubs = l_data.get("research", {}).get("publication_titles", [])
                    if not pubs:
                        has_no_pubs = True
                except Exception:
                    has_no_pubs = True
            else:
                has_no_pubs = True
                
        if matched_db and not has_no_pubs:
            existing_lecturers.append((item, matched_db))
        else:
            new_lecturers.append(item)
            
    logger.info(f"Identified {len(new_lecturers)} new lecturers and {len(existing_lecturers)} existing lecturers.")
    
    # Step 5: Check and scrape publication updates for existing lecturers
    if existing_lecturers:
        logger.info("Processing publication updates for existing lecturers...")
        async with httpx.AsyncClient() as client:
            for item, db_lect in tqdm(existing_lecturers, desc="Checking publications"):
                # Get the db profiles to fetch details (which includes any manual on-the-fly edits)
                db_profiles = {p.platform: p.url for p in db_lect.profiles}
                name = db_lect.full_name
                code = db_lect.code
                
                if code in progress["completed_existing"]:
                    logger.info(f"Skipping publication check for {name} ({code}) - already completed.")
                    continue
                
                try:
                    photo_url = item.get("photo_url")
                    updated, _ = await check_and_update_publications(
                        client, name, code, db_profiles, photo_url=photo_url, soc_item=item
                    )
                    if updated:
                        progress["has_changes"] = True
                    
                    progress["completed_existing"].add(code)
                    save_progress(progress)
                    await asyncio.sleep(1.0)  # Rate limit respect
                except Exception as e:
                    logger.error(f"Error updating publications for {name}: {e}")
                    
    # Step 6: Scrape complete details for new lecturers
    if new_lecturers:
        logger.info("Processing complete scraping for new lecturers...")
        for item in tqdm(new_lecturers, desc="Scraping new lecturers"):
            name = item.get("name")
            code = item.get("nip") or f"new_{item.get('code')}"
            
            if code in progress["completed_new"]:
                logger.info(f"Skipping scraping for new lecturer {name} ({code}) - already completed.")
                continue
                
            try:
                await process_new_lecturer(item)
                progress["has_changes"] = True
                progress["completed_new"].add(code)
                save_progress(progress)
                await asyncio.sleep(2.0)
            except Exception as e:
                logger.error(f"Error processing new lecturer {item.get('name')}: {e}")
                
    # Step 7: Recompute recommendations if there were additions or updates
    if progress["has_changes"]:
        logger.info("Updating recommendation matrix since profiles changed...")
        all_profiles = []
        for filename in os.listdir(settings.JSON_DIR):
            if filename == ".update_progress.json" or not filename.endswith(".json"): continue
            with open(os.path.join(settings.JSON_DIR, filename), 'r', encoding='utf-8') as f:
                profile = json.load(f)
                profile["id"] = profile["basic_info"]["code"]
                all_profiles.append(profile)
                
        for profile in tqdm(all_profiles, desc="Generating recommendations"):
            recs = generate_recommendations(profile["id"], all_profiles)
            profile["recommendations"] = recs
            
            json_path = os.path.join(settings.JSON_DIR, f"{profile['id']}.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(profile, f, indent=4)
                
        # Step 8: Sync everything back to PostgreSQL database
        try:
            logger.info("Synchronizing data back to database...")
            sync_all_to_db()
        except Exception as e:
            logger.error(f"Failed to synchronize data back to database: {e}. Please run 'save_to_db.py' manually once connection is restored.")
        clear_progress()
    else:
        logger.info("No updates or new lecturers detected. Database is up to date.")
        clear_progress()

if __name__ == "__main__":
    asyncio.run(main())
