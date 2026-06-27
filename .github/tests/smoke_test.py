"""
Spring PetClinic – Playwright smoke tests.

Runs a functional burst (8 UI checks) followed by a 5-minute sustained
availability window to confirm the app stays healthy under light traffic.

Usage:
  APP_URL=http://<ec2-ip>:8080 \
  python -m pytest .github/tests/smoke_test.py \
    -v --timeout=420 \
    --screenshot=only-on-failure \
    --video=retain-on-failure \
    --output=playwright-results
"""
import os
import re
import time

import pytest
from playwright.sync_api import Page, expect

APP_URL = os.environ.get("APP_URL", "http://localhost:8080").rstrip("/")
SMOKE_WINDOW_SECONDS = 5 * 60   # 5-minute availability window
POLL_INTERVAL_SECONDS = 15       # pause between availability polls


# ---------------------------------------------------------------------------
# Functional smoke checks
# ---------------------------------------------------------------------------

def test_home_page_loads(page: Page):
    page.goto(APP_URL)
    expect(page).to_have_title(re.compile(r"petclinic", re.IGNORECASE))
    expect(page.get_by_role("navigation")).to_be_visible()


def test_home_has_welcome_content(page: Page):
    page.goto(APP_URL)
    expect(page.locator("body")).to_contain_text(
        re.compile(r"welcome|petclinic", re.IGNORECASE)
    )


def test_navigation_links_present(page: Page):
    page.goto(APP_URL)
    nav = page.get_by_role("navigation")
    for link_text in ["Home", "Find owners", "Veterinarians"]:
        expect(nav.get_by_text(re.compile(link_text, re.IGNORECASE))).to_be_visible()


def test_vets_page_shows_table(page: Page):
    page.goto(f"{APP_URL}/vets.html")
    expect(page.locator("table")).to_be_visible()
    expect(page.locator("table tbody tr").first).to_be_visible()


def test_find_owners_form_renders(page: Page):
    page.goto(f"{APP_URL}/owners/find")
    expect(page.locator("input[name='lastName']")).to_be_visible()
    expect(page.locator("button[type='submit']")).to_be_visible()


def test_find_all_owners_returns_results(page: Page):
    page.goto(f"{APP_URL}/owners/find")
    page.locator("input[name='lastName']").fill("")
    page.locator("button[type='submit']").click()
    # Empty search should render a table or at least one owner link
    expect(
        page.locator("table, a[href*='/owners/']").first
    ).to_be_visible(timeout=10_000)


def test_new_owner_form_has_all_fields(page: Page):
    page.goto(f"{APP_URL}/owners/new")
    for field in ["firstName", "lastName", "address", "city", "telephone"]:
        expect(page.locator(f"input[name='{field}']")).to_be_visible()


def test_create_owner_end_to_end(page: Page):
    """Fill the new-owner form, submit, and verify redirect to the owner detail page."""
    page.goto(f"{APP_URL}/owners/new")
    page.locator("input[name='firstName']").fill("Smoke")
    page.locator("input[name='lastName']").fill("TestCI")
    page.locator("input[name='address']").fill("42 Pipeline Ave")
    page.locator("input[name='city']").fill("CICity")
    page.locator("input[name='telephone']").fill("5550001234")
    page.locator("button[type='submit']").click()
    expect(page).to_have_url(re.compile(r"/owners/\d+"), timeout=10_000)
    expect(page.locator("body")).to_contain_text("Smoke")


# ---------------------------------------------------------------------------
# Sustained 5-minute availability window
# ---------------------------------------------------------------------------

@pytest.mark.timeout(SMOKE_WINDOW_SECONDS + 60)
def test_sustained_availability_window(page: Page):
    """
    Cycle through critical pages every POLL_INTERVAL_SECONDS for 5 minutes.
    Validates the app stays healthy under light continuous load, not just at startup.
    Any HTTP 4xx/5xx or connection error is recorded; the test fails if any occur.
    """
    urls = [APP_URL, f"{APP_URL}/vets.html", f"{APP_URL}/owners/find"]
    start = time.monotonic()
    iteration = 0
    failures: list[str] = []

    while (elapsed := time.monotonic() - start) < SMOKE_WINDOW_SECONDS:
        url = urls[iteration % len(urls)]
        try:
            response = page.goto(url, timeout=15_000)
            status = response.status if response else -1
            if status < 0 or status >= 400:
                failures.append(f"[t+{elapsed:.0f}s] {url} → HTTP {status}")
                print(f"FAIL [{iteration:3d}] t+{elapsed:5.0f}s  {url}  HTTP {status}")
            else:
                print(f"  OK [{iteration:3d}] t+{elapsed:5.0f}s  {url}  ({status})")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"[t+{elapsed:.0f}s] {url} raised: {exc}")
            print(f"FAIL [{iteration:3d}] t+{elapsed:5.0f}s  {url}: {exc}")

        iteration += 1
        remaining = SMOKE_WINDOW_SECONDS - (time.monotonic() - start)
        if remaining > POLL_INTERVAL_SECONDS:
            time.sleep(POLL_INTERVAL_SECONDS)

    print(
        f"\nSmoke window complete: {iteration} checks over {SMOKE_WINDOW_SECONDS}s"
        f" — {len(failures)} failure(s)"
    )
    if failures:
        pytest.fail("Availability failures during smoke window:\n" + "\n".join(failures))
