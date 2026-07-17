import asyncio
import httpx
from utils.logger import get_logger
from utils.retry import with_retry
from parser.normalize import normalize_name, normalize_keyword, clean_name_for_search
from config import settings

logger = get_logger("scraper.openalex")

# Telkom University OpenAlex Institution ID
TELKOM_UNIV_ID = "I862893732"

@with_retry(max_attempts=5, min_wait=3, max_wait=30)
async def fetch_url(client: httpx.AsyncClient, url: str, params: dict = None) -> dict:
    """Helper to fetch JSON content with retry and timeout."""
    if params is None:
        params = {}
    if settings.OPENALEX_EMAIL:
        params["mailto"] = settings.OPENALEX_EMAIL
        
    response = await client.get(url, params=params, timeout=15.0)
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 429:
        logger.warning(f"Rate limited (429) for {url}. Sleeping 5 seconds before retry...")
        await asyncio.sleep(5)
        response.raise_for_status()
    else:
        logger.warning(f"Failed to fetch {url}: HTTP {response.status_code}")
        response.raise_for_status()

async def search_author_on_openalex(client: httpx.AsyncClient, name: str, institution_id: str = TELKOM_UNIV_ID) -> dict:
    """
    Search for an author by name on OpenAlex.
    First tries with an institution filter (Telkom University).
    If no match, falls back to a wider search and manually checks affiliations.
    """
    # Clean name by removing titles and degrees
    search_name = clean_name_for_search(name)

    logger.info(f"Searching author '{name}' (cleaned: '{search_name}') on OpenAlex...")
    
    # 1. Search with institution filter
    # filter format: last_known_institutions.id:<id>
    url = "https://api.openalex.org/authors"
    params = {
        "search": search_name,
        "filter": f"last_known_institutions.id:{institution_id}"
    }
    
    try:
        data = await fetch_url(client, url, params=params)
        results = data.get("results", [])
        if results:
            logger.info(f"Found author '{name}' with institution filter. ID: {results[0].get('id')}")
            return results[0]
    except Exception as e:
        logger.warning(f"Error during filtered author search for '{name}': {e}")

    # 2. Fallback search: search without filter and scan affiliations
    logger.info(f"Running fallback search for '{name}' (cleaned: '{search_name}') without institution filter...")
    params = {"search": search_name}
    try:
        data = await fetch_url(client, url, params=params)
        results = data.get("results", [])
        for auth in results[:5]: # check top 5 matches
            affiliations = auth.get("affiliations", [])
            inst_ids = [aff.get("institution", {}).get("id", "") for aff in affiliations]
            last_inst = auth.get("last_known_institution", {})
            last_inst_id = last_inst.get("id", "") if last_inst else ""
            
            # Check if Telkom University is in the affiliations history or last known institution
            if f"/{institution_id}" in last_inst_id or any(f"/{institution_id}" in inst_id for inst_id in inst_ids):
                logger.info(f"Found author '{name}' via fallback check. ID: {auth.get('id')}")
                return auth
    except Exception as e:
        logger.warning(f"Error during fallback author search for '{name}': {e}")
        
    logger.info(f"No match found for author '{name}' associated with institution {institution_id}.")
    return None

async def get_author_works(client: httpx.AsyncClient, author_id: str) -> list:
    """
    Fetch all works (publications) associated with an author ID from OpenAlex.
    Paginates to retrieve the full list.
    """
    clean_id = author_id.split("/")[-1]
    logger.info(f"Fetching all publications for author ID {clean_id}...")
    
    works = []
    page = 1
    per_page = 200  # OpenAlex maximum per page
    
    while True:
        url = "https://api.openalex.org/works"
        params = {
            "filter": f"author.id:{clean_id}",
            "per_page": per_page,
            "page": page
        }
        
        try:
            data = await fetch_url(client, url, params=params)
            results = data.get("results", [])
            if not results:
                break
            
            works.extend(results)
            logger.info(f"Fetched page {page} for {clean_id} ({len(results)} works). Total so far: {len(works)}")
            
            # Break if we have retrieved all works
            if len(results) < per_page:
                break
                
            page += 1
            await asyncio.sleep(0.5) # respect rate limit guidelines
        except Exception as e:
            logger.error(f"Error fetching works page {page} for author {clean_id}: {e}")
            break
            
    return works

def process_author_profile(author_data: dict, works: list, basic_info: dict) -> dict:
    """
    Processes OpenAlex author data and works list to build a profile JSON object
    conforming to the pipeline schema.
    """
    full_name = author_data.get("display_name") or basic_info.get("name")
    orcid = author_data.get("orcid")
    
    # Extract profiles URLs
    ids = author_data.get("ids", {})
    scopus_id = ids.get("scopus")
    scopus_url = f"https://www.scopus.com/authid/detail.uri?authorId={scopus_id.split('/')[-1]}" if scopus_id else None
    
    profiles = {
        "telkom_profile": None,
        "google_scholar": None,
        "sinta": None,
        "orcid": orcid,
        "scopus": scopus_url,
        "dblp": None,
        "semantic_scholar": None,
        "researchgate": None,
        "linkedin": None
    }
    
    # Extract concepts as interests and keywords
    x_concepts = author_data.get("x_concepts", [])
    research_interests = set()
    keywords = set()
    
    for concept in x_concepts:
        disp_name = concept.get("display_name")
        if not disp_name:
            continue
        norm_kw = normalize_keyword(disp_name)
        level = concept.get("level")
        
        # level 0, 1 concepts -> general interests, level 2+ -> more specific keywords
        if level is not None and level <= 1:
            research_interests.add(norm_kw)
        else:
            keywords.add(norm_kw)
            
    # Process publications, coauthors, and publish years from works
    publication_titles = []
    publication_years = []
    coauthors = set()
    
    author_display_name_norm = normalize_name(full_name).lower()
    
    for work in works:
        title = work.get("title")
        if title:
            publication_titles.append(title)
            
        year = work.get("publication_year")
        if year:
            publication_years.append(year)
            
        # Collect coauthors
        authorships = work.get("authorships", [])
        for auth in authorships:
            author_inst = auth.get("author", {})
            ca_name = author_inst.get("display_name")
            if ca_name:
                ca_norm = normalize_name(ca_name)
                # Exclude target author themselves
                if ca_norm.lower() != author_display_name_norm:
                    coauthors.add(ca_norm)
                    
        # Extract additional concepts from individual works
        work_concepts = work.get("concepts", [])
        for c in work_concepts:
            c_name = c.get("display_name")
            if c_name:
                keywords.add(normalize_keyword(c_name))
                
    # Combine stats
    summary_stats = author_data.get("summary_stats", {})
    citation_count = author_data.get("cited_by_count", 0)
    h_index = summary_stats.get("h_index", 0)
    i10_index = summary_stats.get("i10_index", 0)
    
    return {
        "basic_info": basic_info,
        "identity": {
            "full_name": normalize_name(full_name),
            "titles": None,
            "email": None,
            "office": None,
            "photo": None
        },
        "profiles": profiles,
        "research": {
            "research_interests": list(research_interests),
            "keywords": list(keywords),
            "ai_categories": [], # populated later by categorizer
            "publication_titles": publication_titles,
            "publication_years": publication_years,
            "coauthors": list(coauthors),
            "citation_count": citation_count,
            "h_index": h_index,
            "i10_index": i10_index
        }
    }

async def scrape_lecturer_openalex(client: httpx.AsyncClient, lecturer_info: dict) -> dict:
    """
    Search, retrieve, and process OpenAlex data for a single lecturer.
    """
    name = lecturer_info.get("name")
    author_profile = await search_author_on_openalex(client, name)
    if not author_profile:
        return None
        
    works = await get_author_works(client, author_profile.get("id"))
    profile = process_author_profile(author_profile, works, lecturer_info)
    return profile
