import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("http://playwright.dev")
        await page.screenshot(path="example_screenshot.png")
        print("Screenshot saved to example_screenshot.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
