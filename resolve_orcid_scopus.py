import os
import json
import httpx
import time
from config import settings

def extract_orcid_id(url_or_id):
    if not url_or_id:
        return None
    url_or_id = str(url_or_id).strip()
    if 'orcid.org/' in url_or_id:
        return url_or_id.split('orcid.org/')[-1].strip('/')
    return url_or_id

def main():
    json_dir = os.path.abspath('data/json')
    files = [os.path.join(json_dir, f) for f in os.listdir(json_dir) if f.endswith('.json')]
    print(f"Processing {len(files)} files in {json_dir}...")
    
    resolved_count = 0
    already_had = 0
    missing_orcid = 0
    failed_resolve = 0
    
    client = httpx.Client(timeout=15.0)
    
    for filepath in files:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        profiles = data.get("profiles", {})
        scopus = profiles.get("scopus")
        orcid_val = profiles.get("orcid")
        
        name = data.get("basic_info", {}).get("name", "Unknown")
        
        if scopus:
            already_had += 1
            continue
            
        orcid_id = extract_orcid_id(orcid_val)
        if not orcid_id:
            missing_orcid += 1
            continue
            
        # Call ORCID API
        url = f"https://pub.orcid.org/v3.0/{orcid_id}/external-identifiers"
        headers = {"Accept": "application/json"}
        
        scopus_id = None
        try:
            r = client.get(url, headers=headers)
            if r.status_code == 200:
                res_data = r.json()
                for ext_id in res_data.get('external-identifier', []):
                    id_type = ext_id.get('external-id-type')
                    id_val = ext_id.get('external-id-value')
                    if id_type and 'scopus' in id_type.lower():
                        scopus_id = id_val
                        break
            elif r.status_code == 404:
                print(f"ORCID {orcid_id} for {name} returned 404")
            else:
                print(f"ORCID API returned status {r.status_code} for {name} ({orcid_id})")
        except Exception as e:
            print(f"Error querying ORCID for {name} ({orcid_id}): {e}")
            
        if scopus_id:
            scopus_url = f"https://www.scopus.com/authid/detail.uri?authorId={scopus_id}"
            profiles["scopus"] = scopus_url
            data["profiles"] = profiles
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            print(f"Resolved Scopus ID {scopus_id} for {name}")
            resolved_count += 1
        else:
            failed_resolve += 1
            
        # Small delay to respect rate limit
        time.sleep(0.2)
        
    print("\n--- Summary ---")
    print(f"Total processed: {len(files)}")
    print(f"Already had Scopus link: {already_had}")
    print(f"Missing ORCID link/ID: {missing_orcid}")
    print(f"Successfully resolved via ORCID: {resolved_count}")
    print(f"Failed to resolve via ORCID: {failed_resolve}")

if __name__ == "__main__":
    main()
