import os
import json
from config import settings
from database.postgres import SessionLocal
from database.models import Lecturer, Profile, Publication, Keyword, ResearchInterest, Coauthor, Embedding, Recommendation, Collaboration
from sqlalchemy.orm import Session
from utils.logger import get_logger

logger = get_logger("save_to_db")

def populate_db():
    db: Session = SessionLocal()
    
    json_dir = settings.JSON_DIR
    if not os.path.exists(json_dir):
        logger.error("JSON directory not found")
        return
        
    # Read all JSON files
    lecturer_data = []
    for filename in os.listdir(json_dir):
        if not filename.endswith(".json"): continue
        with open(os.path.join(json_dir, filename), 'r') as f:
            data = json.load(f)
            lecturer_data.append(data)
            
    # Pass 1: Clear existing and create base Lecturer records to get their database IDs
    code_to_id = {}
    
    logger.info("Cleaning up existing database records in relational order...")
    try:
        db.query(Collaboration).delete()
        db.query(Recommendation).delete()
        db.query(Embedding).delete()
        db.query(Profile).delete()
        db.query(Publication).delete()
        db.query(Keyword).delete()
        db.query(ResearchInterest).delete()
        db.query(Coauthor).delete()
        db.query(Lecturer).delete()
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error cleaning database: {e}")
        return
        
            
    logger.info("Inserting base lecturer records...")
    for data in lecturer_data:
        basic = data.get("basic_info", {})
        identity = data.get("identity", {})
        research = data.get("research", {})
        code = basic.get("code") or data.get("id")
        
        lecturer = Lecturer(
            name=basic.get("name"),
            code=code,
            lecturer_code=basic.get("lecturer_code"),
            study_program=basic.get("study_program"),
            research_group=basic.get("research_group"),
            academic_rank=basic.get("academic_rank"),
            field=basic.get("field"),
            full_name=identity.get("full_name"),
            titles=identity.get("titles"),
            name_with_title=identity.get("name_with_title"),
            email=identity.get("email"),
            photo=identity.get("photo"),
            citation_count=research.get("sinta_scholar_citations", 0),
            h_index=research.get("sinta_scholar_h_index", 0),
            i10_index=research.get("sinta_scholar_i10_index", 0),
            sinta_scopus_citations=research.get("sinta_scopus_citations", 0),
            sinta_scopus_h_index=research.get("sinta_scopus_h_index", 0),
            sinta_scopus_i10_index=research.get("sinta_scopus_i10_index", 0),
            sinta_scholar_citations=research.get("sinta_scholar_citations", 0),
            sinta_scholar_h_index=research.get("sinta_scholar_h_index", 0),
            sinta_scholar_i10_index=research.get("sinta_scholar_i10_index", 0),
            sinta_wos_citations=research.get("sinta_wos_citations", 0),
            sinta_wos_h_index=research.get("sinta_wos_h_index", 0),
            sinta_wos_i10_index=research.get("sinta_wos_i10_index", 0),
            ai_categories=research.get("ai_categories", []),
            sinta_metrics=data.get("sinta_metrics", {})
        )
        db.add(lecturer)
        db.commit()
        db.refresh(lecturer)
        code_to_id[code] = lecturer.id

    # Pass 2: Populate all relational detail tables including recommendations
    logger.info("Populating relational tables and recommendations...")
    for data in lecturer_data:
        basic = data.get("basic_info", {})
        research = data.get("research", {})
        profiles = data.get("profiles", {})
        emb = data.get("embeddings")
        code = basic.get("code") or data.get("id")
        
        lecturer_id = code_to_id.get(code)
        if not lecturer_id:
            continue
            
        # Add keywords
        for kw in research.get("keywords", []):
            db.add(Keyword(lecturer_id=lecturer_id, keyword=kw))
            
        # Add research interests
        for ri in research.get("research_interests", []):
            db.add(ResearchInterest(lecturer_id=lecturer_id, interest=ri))
            
        # Add publications
        pub_titles = research.get("publication_titles", [])
        pub_years = research.get("publication_years", [])
        for i, pub in enumerate(pub_titles):
            year = pub_years[i] if i < len(pub_years) else None
            db.add(Publication(lecturer_id=lecturer_id, title=pub, year=year))
            
        # Add coauthors
        for ca in research.get("coauthors", []):
            db.add(Coauthor(lecturer_id=lecturer_id, coauthor_name=ca))
            
        # Add profiles
        for platform, url in profiles.items():
            if url:
                db.add(Profile(lecturer_id=lecturer_id, platform=platform, url=url))
            
        # Add embeddings
        if emb:
            db.add(Embedding(
                lecturer_id=lecturer_id,
                keyword_embedding=emb.get("keyword"),
                publication_embedding=emb.get("publication")
            ))
            
        # Add recommendations
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
        logger.info(f"Populated details for {basic.get('name')} ({code}).")

    # Pass 3: Compute and populate collaborations
    logger.info("Computing and populating collaboration network table...")
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
            if not t_clean:
                continue
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
                    if id1 == id2:
                        continue
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
    logger.info(f"Populated {len(pair_collabs)} collaborations.")

    logger.info("Database population complete!")

if __name__ == "__main__":
    populate_db()
