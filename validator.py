import os
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError

class BasicInfo(BaseModel):
    name: str
    code: str
    study_program: str
    research_group: str
    academic_rank: str
    field: str
    lecturer_code: Optional[str] = None

class Identity(BaseModel):
    full_name: Optional[str] = None
    titles: Optional[str] = None
    name_with_title: Optional[str] = None
    email: Optional[str] = None
    photo: Optional[str] = None

class Profiles(BaseModel):
    google_scholar: Optional[str] = None
    sinta: Optional[str] = None
    orcid: Optional[str] = None
    scopus: Optional[str] = None

class Research(BaseModel):
    research_interests: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    publication_titles: List[str] = Field(default_factory=list)
    coauthors: List[str] = Field(default_factory=list)
    ai_categories: List[str] = Field(default_factory=list)
    
    # SINTA Metrics
    sinta_scopus_citations: Optional[int] = 0
    sinta_scopus_h_index: Optional[int] = 0
    sinta_scopus_i10_index: Optional[int] = 0
    sinta_scholar_citations: Optional[int] = 0
    sinta_scholar_h_index: Optional[int] = 0
    sinta_scholar_i10_index: Optional[int] = 0
    sinta_wos_citations: Optional[int] = 0
    sinta_wos_h_index: Optional[int] = 0
    sinta_wos_i10_index: Optional[int] = 0

class Embeddings(BaseModel):
    keyword: List[float] = Field(default_factory=list)
    publication: List[float] = Field(default_factory=list)

class RecommendationItem(BaseModel):
    recommended_lecturer_id: str
    score: float
    reasons: List[str] = Field(default_factory=list)

class SintaMetricsBlock(BaseModel):
    google_scholar: Optional[Dict[str, Any]] = None
    scopus: Optional[Dict[str, Any]] = None
    wos: Optional[Dict[str, Any]] = None

class LecturerProfile(BaseModel):
    basic_info: BasicInfo
    identity: Identity
    profiles: Profiles
    research: Research
    embeddings: Optional[Embeddings] = None
    recommendations: List[RecommendationItem] = Field(default_factory=list)
    sinta_metrics: Optional[SintaMetricsBlock] = None

def validate_profile(data: dict) -> LecturerProfile:
    """Validate raw dict profile data against the Pydantic schema."""
    return LecturerProfile(**data)

def validate_all_json_files(directory: str) -> bool:
    """Validate all JSON files in the given directory."""
    if not os.path.exists(directory):
        print(f"Directory {directory} does not exist.")
        return False
        
    files = [f for f in os.listdir(directory) if f.endswith('.json')]
    errors = 0
    print(f"Validating {len(files)} files in {directory}...")
    
    for filename in files:
        filepath = os.path.join(directory, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            validate_profile(data)
        except ValidationError as ve:
            print(f"❌ Schema validation failed for {filename}:")
            print(ve)
            errors += 1
        except json.JSONDecodeError as je:
            print(f"❌ JSON Syntax error in {filename}: {je}")
            errors += 1
            
    if errors == 0:
        print("✅ All files validated successfully!")
        return True
    else:
        print(f"❌ Completed with {errors} validation errors.")
        return False

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Validate Lecturer JSON files.")
    parser.add_argument("--dir", default="data/json", help="Path to JSON directory")
    args = parser.parse_args()
    validate_all_json_files(args.dir)
