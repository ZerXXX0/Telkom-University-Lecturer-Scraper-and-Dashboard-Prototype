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
from parser.normalize import normalize_name, normalize_keyword
from parser.merge import categorize_ai
from embedding.embedder import compute_embedding
from recommendation.recommender import generate_recommendations
from scraper.openalex import fetch_url, search_author_on_openalex, get_author_works
from main import process_lecturer

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
            "name": lecturer.name,
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
    db: Session = SessionLocal()
    os.makedirs(settings.JSON_DIR, exist_ok=True)
    db_lecturers = db.query(Lecturer).all()
    
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
            research_group_text = cols[5].get_text(strip=True)
            field_text = cols[6].get_text(strip=True)
            
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
                "research_group_text": research_group_text,
                "field_text": field_text,
                "sinta_url": sinta_url,
                "scholar_url": scholar_url
            })
            
        await browser.close()
        logger.info(f"Scraped {len(scraped_data)} lecturers from SOC website.")
        return scraped_data

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

async def check_and_update_publications(client, name, code, db_profiles):
    """Check if there are any new publications for this lecturer and update them."""
    works, author_profile = await get_latest_openalex_publications(client, name, db_profiles)
    if not works:
        return False, None
        
    scraped_titles = []
    scraped_years = []
    scraped_coauthors = set()
    scraped_keywords = set()
    
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
                
    json_path = os.path.join(settings.JSON_DIR, f"{code}.json")
    if not os.path.exists(json_path):
        return False, None
        
    with open(json_path, 'r', encoding='utf-8') as f:
        local_data = json.load(f)
        
    res = local_data.get("research", {})
    existing_titles = {t.lower().strip() for t in res.get("publication_titles", [])}
    new_titles = [t for t in scraped_titles if t.lower().strip() not in existing_titles]
    
    citation_count = author_profile.get("cited_by_count", 0) if author_profile else res.get("citation_count", 0)
    summary_stats = author_profile.get("summary_stats", {}) if author_profile else {}
    h_index = summary_stats.get("h_index", 0) if summary_stats else res.get("h_index", 0)
    i10_index = summary_stats.get("i10_index", 0) if summary_stats else res.get("i10_index", 0)
    
    metrics_changed = (
        citation_count != res.get("citation_count", 0) or
        h_index != res.get("h_index", 0) or
        i10_index != res.get("i10_index", 0)
    )
    
    if new_titles or metrics_changed:
        logger.info(f"Updates found for {name} ({code}). New publications: {len(new_titles)}. Metrics updated: {metrics_changed}")
        
        if new_titles:
            # Append new publications and years
            res["publication_titles"].extend(new_titles)
            for title in new_titles:
                idx = scraped_titles.index(title)
                res["publication_years"].append(scraped_years[idx])
                
            # Merge coauthors and keywords
            local_coauthors = set(res.get("coauthors", []))
            local_coauthors.update(scraped_coauthors)
            res["coauthors"] = list(local_coauthors)
            
            local_keywords = set(res.get("keywords", []))
            local_keywords.update(scraped_keywords)
            res["keywords"] = list(local_keywords)
            
            # Recompute categories and embeddings
            res["ai_categories"] = categorize_ai(res)
            
            kw_text = " ".join(res["keywords"])
            pub_text = " ".join(res["publication_titles"])
            local_data["embeddings"] = {
                "keyword": compute_embedding(kw_text),
                "publication": compute_embedding(pub_text)
            }
            
        res["citation_count"] = citation_count
        res["h_index"] = h_index
        res["i10_index"] = i10_index
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
            
        db_lecturer.name = basic.get("name")
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

async def main():
    # Load any progress from a previous interrupted run
    progress = load_progress()
    skip_codes = progress["completed_existing"].union(progress["completed_new"])
    
    # Step 1: Restore and update JSON cache from DB first (recovers manual DB edits, skipping completed ones)
    restore_json_from_db(skip_codes=skip_codes)
    
    # Step 2: Connect to DB and gather existing records
    db = SessionLocal()
    db_lecturers = db.query(Lecturer).options(joinedload(Lecturer.profiles)).all()
    db.close()
    
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
            matched_db = next((l for l in db_lecturers if get_base_name(l.name) == base_name), None)
            
        if matched_db:
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
                name = db_lect.name
                code = db_lect.code
                
                if code in progress["completed_existing"]:
                    logger.info(f"Skipping publication check for {name} ({code}) - already completed.")
                    continue
                
                try:
                    updated, _ = await check_and_update_publications(client, name, code, db_profiles)
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
                
            basic_info = {
                "name": name,
                "code": code,
                "study_program": "",
                "research_group": classify_group(item.get("research_group_text", "")),
                "academic_rank": "",
                "field": item.get("field_text", ""),
                "lecturer_code": item.get("code")
            }
            try:
                # process_lecturer scrapes openalex, web profiles, LLM extraction, and saves to JSON
                await process_lecturer(basic_info)
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
        logger.info("Synchronizing data back to database...")
        sync_all_to_db()
        clear_progress()
    else:
        logger.info("No updates or new lecturers detected. Database is up to date.")
        clear_progress()

if __name__ == "__main__":
    asyncio.run(main())
