from parser.normalize import normalize_name, normalize_keyword

def merge_profiles(extracted_data_list: list[dict], basic_info: dict) -> dict:
    merged = {
        "basic_info": basic_info,
        "identity": {
            "full_name": basic_info.get("name"),
            "titles": None,
            "email": None,
            "photo": None
        },
        "profiles": {
            "google_scholar": None, "sinta": None,
            "orcid": None, "scopus": None
        },
        "research": {
            "research_interests": set(), "keywords": set(), "ai_categories": set(),
            "publication_titles": set(), "publication_years": set(),
            "coauthors": set(), "citation_count": 0, "h_index": 0, "i10_index": 0
        }
    }
    
    for data in extracted_data_list:
        if not data: continue
        
        # Merge identity (keep first non-null)
        name_val = data.get("name") or data.get("full_name")
        if "identity" in data and isinstance(data["identity"], dict):
            name_val = name_val or data["identity"].get("name") or data["identity"].get("full_name")
        if name_val and not merged["identity"]["full_name"]:
            merged["identity"]["full_name"] = normalize_name(name_val)
            
        for key in ["titles", "email", "photo"]:
            val = None
            if "identity" in data and isinstance(data["identity"], dict):
                val = data["identity"].get(key)
            if not val:
                val = data.get(key)
            if val and not merged["identity"][key]:
                merged["identity"][key] = val
                
        # Merge profiles
        profiles_data = data.get("profiles") or data.get("profile_links") or {}
        for platform in merged["profiles"].keys():
            val = profiles_data.get(platform)
            if val and not merged["profiles"][platform]:
                merged["profiles"][platform] = val
        
        # Merge research
        if data.get("research_interests"):
            for ri in data["research_interests"]:
                merged["research"]["research_interests"].add(normalize_keyword(ri))
                
        if data.get("keywords"):
            for kw in data["keywords"]:
                merged["research"]["keywords"].add(normalize_keyword(kw))
                
        if data.get("publication_titles"):
            for pt in data["publication_titles"]:
                merged["research"]["publication_titles"].add(pt)

        if data.get("publication_years"):
            for py in data["publication_years"]:
                if py: merged["research"]["publication_years"].add(py)
                
        if data.get("coauthors"):
            for ca in data["coauthors"]:
                merged["research"]["coauthors"].add(normalize_name(ca))
                
        # Metrics - take max
        merged["research"]["citation_count"] = max(merged["research"]["citation_count"], 
                                                   data.get("citations") or data.get("citation_count") or 0)
        merged["research"]["h_index"] = max(merged["research"]["h_index"], data.get("h_index") or 0)
        merged["research"]["i10_index"] = max(merged["research"]["i10_index"], data.get("i10_index") or 0)
        
    # Convert sets back to lists
    merged["research"]["research_interests"] = list(merged["research"]["research_interests"])
    merged["research"]["keywords"] = list(merged["research"]["keywords"])
    merged["research"]["publication_titles"] = list(merged["research"]["publication_titles"])
    merged["research"]["publication_years"] = list(merged["research"]["publication_years"])
    merged["research"]["coauthors"] = list(merged["research"]["coauthors"])
    merged["research"]["ai_categories"] = list(merged["research"]["ai_categories"])
    
    return merged

def categorize_ai(research_data: dict) -> list[str]:
    categories = [
        "Machine Learning", "Deep Learning", "NLP", "Computer Vision",
        "Robotics", "Data Mining", "Data Science", "Knowledge Graph",
        "Information Retrieval", "Reinforcement Learning", "Multi-Agent Systems",
        "LLM", "Healthcare AI", "Explainable AI", "Federated Learning",
        "Bioinformatics", "Recommendation System", "Speech Processing",
        "Time Series", "Edge AI", "AI Security"
    ]
    
    text_to_search = " ".join(research_data.get("publication_titles", [])) + " " + \
                     " ".join(research_data.get("research_interests", [])) + " " + \
                     " ".join(research_data.get("keywords", []))
                     
    text_to_search = text_to_search.lower()
    
    labels = []
    for cat in categories:
        if cat.lower() in text_to_search:
            labels.append(cat)
            
    return labels
