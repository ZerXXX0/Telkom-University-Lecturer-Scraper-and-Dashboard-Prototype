from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

def generate_recommendations(target_id, all_lecturers):
    if not all_lecturers:
        return []
        
    target = next((l for l in all_lecturers if l["id"] == target_id), None)
    if not target or "embeddings" not in target:
        return []
        
    recommendations = []
    
    for other in all_lecturers:
        if other["id"] == target["id"] or "embeddings" not in other:
            continue
            
        kw_sim = cosine_similarity(
            [target["embeddings"]["keyword"]], 
            [other["embeddings"]["keyword"]]
        )[0][0]
        
        pub_sim = cosine_similarity(
            [target["embeddings"]["publication"]], 
            [other["embeddings"]["publication"]]
        )[0][0]
        
        score = (kw_sim + pub_sim) / 2
        
        reasons = []
        
        # 1. Research group connection
        target_group = target.get("basic_info", {}).get("research_group", "FIF")
        other_group = other.get("basic_info", {}).get("research_group", "FIF")
        if target_group == other_group:
            reasons.append(f"Fellow members of the {target_group} Research Group")
        else:
            reasons.append(f"Cross-disciplinary potential: connecting {target_group} and {other_group}")
            
        # 2. Shared field
        target_field = target.get("basic_info", {}).get("field")
        other_field = other.get("basic_info", {}).get("field")
        if target_field and other_field and target_field.lower() == other_field.lower():
            reasons.append(f"Both specialize in {target_field}")
            
        # 3. Common keywords
        target_kws = {k.lower().strip() for k in target.get("research", {}).get("keywords", [])}
        other_kws = {k.lower().strip() for k in other.get("research", {}).get("keywords", [])}
        common_kws = target_kws.intersection(other_kws)
        if common_kws:
            matched_kws = []
            for k in target.get("research", {}).get("keywords", []):
                if k.lower().strip() in common_kws and k not in matched_kws:
                    matched_kws.append(k)
            reasons.append(f"Shared research themes: {', '.join(matched_kws[:3])}")
            
        # 4. Publication similarity check
        if pub_sim > 0.7:
            reasons.append(f"Very high publication topic overlap (similarity: {pub_sim:.2f})")
        elif pub_sim > 0.5:
            reasons.append(f"Moderate publication theme match (similarity: {pub_sim:.2f})")
            
        # 5. Co-author connection & score boost
        target_coauthors = target.get("research", {}).get("coauthors", [])
        other_coauthors = other.get("research", {}).get("coauthors", [])
        
        target_coauthors_clean = {ca.lower().strip() for ca in target_coauthors}
        other_coauthors_clean = {ca.lower().strip() for ca in other_coauthors}
        
        direct_collaboration = False
        target_name = target.get("basic_info", {}).get("name", "")
        other_name = other.get("basic_info", {}).get("name", "")
        
        target_parts = [p for p in target_name.lower().replace(",", "").replace(".", "").split() if len(p) > 2]
        other_parts = [p for p in other_name.lower().replace(",", "").replace(".", "").split() if len(p) > 2]
        
        if target_parts and other_parts:
            # Check if target name is listed as a coauthor in other's list
            for ca in other_coauthors_clean:
                if all(part in ca for part in target_parts):
                    direct_collaboration = True
                    break
            # Check if other name is listed as a coauthor in target's list
            if not direct_collaboration:
                for ca in target_coauthors_clean:
                    if all(part in ca for part in other_parts):
                        direct_collaboration = True
                        break
                        
        if direct_collaboration:
            score += 0.12  # 12% score boost for direct collaboration history
            reasons.append("Have previously co-authored research papers together")
            
        # Check shared co-authors (excluding themselves)
        common_coauthors = target_coauthors_clean.intersection(other_coauthors_clean)
        filtered_common = []
        for ca in common_coauthors:
            is_self_or_other = False
            if target_parts and all(part in ca for part in target_parts):
                is_self_or_other = True
            if other_parts and all(part in ca for part in other_parts):
                is_self_or_other = True
            if not is_self_or_other:
                filtered_common.append(ca)
                
        if filtered_common:
            original_common = []
            for ca in target_coauthors:
                if ca.lower().strip() in filtered_common and ca not in original_common:
                    original_common.append(ca)
            if original_common:
                boost_amt = min(0.15, 0.05 * len(original_common))
                score += boost_amt
                reasons.append(f"Both have collaborated with shared co-authors: {', '.join(original_common[:3])}")
                
        score = min(1.0, score)
        
        recommendations.append({
            "recommended_lecturer_id": other["id"],
            "score": float(score),
            "reasons": reasons
        })
        
    # Sort and return top 10
    recommendations.sort(key=lambda x: x["score"], reverse=True)
    return recommendations[:10]
