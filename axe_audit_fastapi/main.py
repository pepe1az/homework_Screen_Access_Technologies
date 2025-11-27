from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, AnyHttpUrl
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


app = FastAPI(
    title="axe-core accessibility audit service (Playwright)",
    description="Проверка доступности сайтов через axe-core + Playwright (Chromium)",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    version="1.0.0",
)

app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")


class CheckRequest(BaseModel):
    url: AnyHttpUrl


@app.on_event("startup")
async def startup_event():
    app.state.playwright = await async_playwright().start()
    app.state.browser = await app.state.playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox"],
    )


@app.on_event("shutdown")
async def shutdown_event():
    await app.state.browser.close()
    await app.state.playwright.stop()


@app.get("/")
async def root():
    return {
        "message": "axe-core accessibility audit service (Playwright)",
        "how_to_use": 'POST /api/check {"url": "https://example.com"} или открой /ui/',
    }


@app.post("/api/check")
async def check_accessibility(payload: CheckRequest):
    url = str(payload.url)
    browser = app.state.browser

    context = await browser.new_context()
    page = await context.new_page()

    try:
        try:
            await page.goto(
                url,
                wait_until="networkidle",
                timeout=60_000,
            )
        except PlaywrightTimeoutError:
            await page.goto(
                url,
                wait_until="load",
                timeout=90_000,
            )

        await page.add_script_tag(
            url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.0/axe.min.js"
        )

        results = await page.evaluate(
            """async () => {
                return await axe.run();
            }"""
        )

        return {
            "url": url,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "violations": results.get("violations", []),
            "passes": results.get("passes", []),
            "incomplete": results.get("incomplete", []),
            "inapplicable": results.get("inapplicable", []),
        }

    except PlaywrightTimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Страница слишком долго загружается или не переходит в стабильное состояние.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Не удалось проверить сайт: {e}",
        )
    finally:
        await context.close()
