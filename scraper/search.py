import asyncio
from playwright.async_api import async_playwright
from utils.logger import get_logger
import urllib.parse

logger = get_logger("scraper.search")

async def search_lecturer_profiles(name: str, institution: str):
    dork_university = f'site:telkomuniversity.ac.id "{name}"'
    dork_scholar = f'"{name}" Telkom University site:scholar.google.com'
    
    queries = [
        {"url": f"https://search.yahoo.com/search?p={urllib.parse.quote(dork_university)}", "source": "yahoo_university"},
        {"url": f"https://search.yahoo.com/search?p={urllib.parse.quote(dork_scholar)}", "source": "yahoo_scholar"}
    ]
    
    urls = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = await context.new_page()
        
        try:
            for q in queries:
                logger.info(f"Searching {q['source']} via Playwright: {name}")
                
                try:
                    await page.goto(q['url'], wait_until="domcontentloaded", timeout=15000)
                    
                    page_urls = await page.evaluate('''() => {
                        const links = document.querySelectorAll('div.compTitle a');
                        const result = [];
                        for (let a of links) {
                            if (a.href) result.push(a.href);
                        }
                        return result;
                    }''')
                    
                    for link in page_urls:
                        if link and link.startswith('http') and link not in urls and 'yahoo.com' not in link:
                            urls.append(link)
                            
                except Exception as e:
                    logger.warning(f"Failed to search {q['source']}: {e}")
                    
                await asyncio.sleep(2)
                
            await browser.close()
        except Exception as e:
            logger.error(f"Playwright search crashed: {e}")
        
    return urls[:10]
