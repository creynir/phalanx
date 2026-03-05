import asyncio
import os
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        # Get absolute path to the HTML file
        file_path = f"file://{os.path.abspath('phalanx_ui_mockup.html')}"

        await page.goto(file_path)
        # Wait a moment for Tailwind CDN to load and apply styles
        await page.wait_for_timeout(2000)

        await page.screenshot(path="phalanx_ui_mockup.png")
        print("UI mockup screenshot saved to phalanx_ui_mockup.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
