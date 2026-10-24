import sys

sys.path.insert(0, "/mnt/d/tracecore/tests_e2e")
from conftest import desk_login
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(base_url="http://127.0.0.1:8001")
    page.on("pageerror", lambda error: print("pageerror", str(error)))
    page.on("response", lambda response: print("response", response.status, response.url) if "/tracecore" in response.url else None)
    desk_login(page)
    response = page.request.get("/api/method/tracecore.v1.home.context")
    data = response.json()
    print("api-error", response.status, data.get("exc_type"), data.get("exception"), data.get("_server_messages"))
    print("traceback", data.get("exc"))
    page.goto("/tracecore")
    page.wait_for_timeout(3000)
    print("title", page.title())
    print("headings", page.get_by_role("heading").all_text_contents())
    print("alerts", page.get_by_role("alert").all_text_contents())
    print("scripts", page.locator("script[src]").evaluate_all("nodes => nodes.map(node => node.getAttribute('src'))"))
    print("main-count", page.get_by_role("main").count())
    browser.close()
