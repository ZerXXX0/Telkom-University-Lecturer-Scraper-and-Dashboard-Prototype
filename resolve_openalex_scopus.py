import os
import json
import asyncio
import httpx
import re
from config import settings

TELKOM_UNIV_ID = "I862893732"

async def fetch_url(client: httpx.AsyncClient, url: str, params: dict = None) -> dict:
    if params is None:
        params = {}
    if settings.OPENALEX_EMAIL:
        params["mailto"] = settings.OPENALEX_EMAIL
    r = await client.get(url, params=params, timeout=15.0)
    if r.status_code == 200:
        return r.json()
    r.raise_for_status()

async def search_author(client: httpx.AsyncClient, name: str) -> dict:
    # 1. Search with institution filter
    url = "https://api.openalex.org/authors"
    params = {
        "search": name,
        "filter": f"last_known_institutions.id:{TELKOM_UNIV_ID}"
    }
    try:
        data = await fetch_url(client, url, params=params)
        results = data.get("results", [])
        if results:
            return results[0]
    except Exception:
        pass

    # 2. Search without institution filter and check affiliations
    params = {"search": name}
    try:
        data = await fetch_url(client, url, params=params)
        results = data.get("results", [])
        for auth in results[:5]:
            affiliations = auth.get("affiliations", [])
            inst_ids = [aff.get("institution", {}).get("id", "") for aff in affiliations]
            last_inst = auth.get("last_known_institution", {})
            last_inst_id = last_inst.get("id", "") if last_inst else ""
            if f"/{TELKOM_UNIV_ID}" in last_inst_id or any(f"/{TELKOM_UNIV_ID}" in inst_id for inst_id in inst_ids):
                return auth
    except Exception:
        pass
    return None

async def main():
    json_dir = os.path.abspath('data/json')
    files = [os.path.join(json_dir, f) for f in os.listdir(json_dir) if f.endswith('.json')]
    
    # We will update files in both directories
    directories = [
        os.path.abspath('data/json'),
        os.path.abspath(settings.JSON_DIR)
    ]
    directories = list(set(directories))
    
    client = httpx.AsyncClient(timeout=15.0)
    resolved_count = 0
    
    for filepath in files:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        profiles = data.get("profiles", {})
        scopus = profiles.get("scopus")
        
        if scopus:
            continue
            
        name = data.get("basic_info", {}).get("name", "")
        full_name = data.get("identity", {}).get("full_name", "")
        
        # Try search with name, if fails try with full_name
        author = await search_author(client, name)
        if not author and full_name:
            author = await search_author(client, full_name)
            
        if author:
            scopus_id = author.get("ids", {}).get("scopus")
            if scopus_id:
                scopus_id_clean = scopus_id.split("/")[-1]
                scopus_url = f"https://www.scopus.com/authid/detail.uri?authorId={scopus_id_clean}"
                
                # Update in both directories
                for d in directories:
                    target_path = os.path.join(d, os.path.basename(filepath))
                    if os.path.exists(target_path):
                        with open(target_path, 'r', encoding='utf-8') as tf:
                            tdata = json.load(tf)
                        tdata["profiles"]["scopus"] = scopus_url
                        # Also if orcid is missing and available on OpenAlex, update it
                        orcid = author.get("orcid")
                        if orcid and not tdata["profiles"].get("orcid"):
                            tdata["profiles"]["orcid"] = orcid
                        with open(target_path, 'w', encoding='utf-8') as tf:
                            json.dump(tdata, tf, indent=4)
                            
                print(f"Resolved Scopus ID {scopus_id_clean} via OpenAlex for {name}")
                resolved_count += 1
                
        await asyncio.sleep(0.2)
        
    print(f"\nResolved {resolved_count} authors via OpenAlex search.")
    await client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
