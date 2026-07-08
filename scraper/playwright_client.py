import os
from playwright.async_api import async_playwright
import asyncio
from utils.logger import get_logger
from config import settings

logger = get_logger("scraper.playwright")

async def download_pages(urls: list[str], output_prefix: str):
    results = []
    os.makedirs(settings.RAW_DIR, exist_ok=True)
    
    # Fast exit if no urls
    if not urls:
        return results
        
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        for idx, url in enumerate(urls):
            try:
                async def fetch_one():
                    p_page = await context.new_page()
                    try:
                        logger.info(f"Downloading {url}")
                        await p_page.goto(url, wait_until="domcontentloaded", timeout=25000)
                        await asyncio.sleep(2) # Give dynamic frameworks extra time
                        
                        html = ""
                        for attempt in range(3):
                            try:
                                html = await p_page.content()
                                break
                            except Exception as e:
                                if "navigating" in str(e).lower():
                                    await asyncio.sleep(2)
                                else:
                                    raise
                        
                        filepath = os.path.join(settings.RAW_DIR, f"{output_prefix}_{idx}.html")
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(f"<!-- URL: {url} -->\n{html}")
                            
                        results.append(filepath)
                    finally:
                        await p_page.close()

                # Wrap the entire operation in a 35-second hard timeout
                await asyncio.wait_for(fetch_one(), timeout=35.0)
            except asyncio.TimeoutError:
                logger.error(f"Timeout (35s) exceeded downloading {url}")
            except Exception as e:
                logger.error(f"Error downloading {url}: {e}")
                
        await browser.close()
    return results
