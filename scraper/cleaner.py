from bs4 import BeautifulSoup
import os
from config import settings
from utils.logger import get_logger

logger = get_logger("scraper.cleaner")

def clean_html(filepath: str) -> str:
    with open(filepath, 'r', encoding='utf-8') as f:
        html = f.read()
        
    soup = BeautifulSoup(html, 'lxml')
    
    # Remove unwanted tags
    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript', 'meta', 'link', 'svg']):
        tag.decompose()
        
    # Get text
    text = soup.get_text(separator='\n')
    
    # Clean whitespace
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned_text = '\n'.join(lines)
    
    filename = os.path.basename(filepath).replace('.html', '.txt')
    out_path = os.path.join(settings.CLEANED_DIR, filename)
    os.makedirs(settings.CLEANED_DIR, exist_ok=True)
    
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(cleaned_text)
        
    return out_path
