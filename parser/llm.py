import google.generativeai as genai
import json
from config import settings
from utils.retry import with_retry

genai.configure(api_key=settings.GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash', generation_config={"response_mime_type": "application/json"})

DAILY_QUOTA_EXCEEDED = False

@with_retry(max_attempts=5, min_wait=5, max_wait=30)
def extract_information(text: str) -> dict:
    global DAILY_QUOTA_EXCEEDED
    if DAILY_QUOTA_EXCEEDED:
        return {}
        
    prompt = f"""You are an information extraction system.
Given the following cleaned webpage text, extract all lecturer information into a structured JSON object.

JSON Schema to return:
{{
  "name": "full name of the lecturer (string, null if missing)",
  "titles": "academic titles/degrees, e.g. S.T., M.T., Ph.D. (string, null if missing)",
  "email": "email address (string, null if missing)",
  "photo": "URL of the lecturer's profile photo if explicitly mentioned/found in the text (string, null if missing)",
  "profiles": {{
    "google_scholar": "Google Scholar profile URL (string, null if missing)",
    "sinta": "SINTA profile URL (string, null if missing)",
    "orcid": "ORCID URL/ID (string, null if missing)",
    "scopus": "Scopus profile URL (string, null if missing)"
  }},
  "research_interests": ["list of research interests/fields (array of strings)"],
  "keywords": ["list of keywords (array of strings)"],
  "publication_titles": ["list of publication titles found on this page (array of strings)"],
  "publication_years": [list of publication years as integers matching the publication titles order (array of integers)],
  "coauthors": ["list of co-authors names (array of strings)"],
  "citation_count": 0,
  "h_index": 0,
  "i10_index": 0
}}

Rules:
1. Return ONLY the JSON object. Do not wrap it in markdown code blocks or add any other text.
2. Never hallucinate information. If a field is not found in the text, return null or an empty list.
3. Keep publication titles exactly as written.

Text:
{text[:15000]}
"""
    
    try:
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        err_str = str(e)
        if "Quota exceeded" in err_str and "GenerateRequestsPerDay" in err_str:
            DAILY_QUOTA_EXCEEDED = True
            return {}
        raise e
