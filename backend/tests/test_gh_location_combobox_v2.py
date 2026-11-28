"""Live 2026-11-28 Twilio: Greenhouse "Location (City)" is a react-select whose geo suggestions
arrive asynchronously; Enter after the short settle picked nothing -> "Please enter your location"."""

from __future__ import annotations

import pytest

from backend.app.browser_v2.adapters.common import HostedFormFiller
from backend.app.browser_v2.adapters.shared.form_filler import pick_combobox_option
from backend.tests.phase6a_fixtures import (  # noqa: F401
    chromium_fixture,
    html,
    web_fixture,
)

pytestmark = [pytest.mark.asyncio(loop_scope="module"),
              pytest.mark.filterwarnings("ignore:The test <Function:pytest.PytestWarning")]

URL = "https://job-boards.greenhouse.io/acme/jobs/1"
PAGE = html("""
  <ul id="phone-codes"><li role="option">India+91</li><li role="option">Faridabad Decoy</li></ul>
  <label for="loc">Location (City)*</label>
  <input id="loc" role="combobox" data-aa-field="0" aria-controls="loc-listbox" autocomplete="off">
  <div id="loc-listbox" role="listbox"></div>
  <input type="hidden" id="picked">
  <script>
    const input = document.getElementById("loc"), box = document.getElementById("loc-listbox");
    input.addEventListener("input", () => {
      box.innerHTML = "";
      const q = input.value;
      setTimeout(() => {  // async geo lookup
        for (const city of [q + ", Haryana, India", "Goth " + q + ", Sindh, Pakistan"]) {
          const li = document.createElement("div");
          li.setAttribute("role", "option"); li.textContent = city;
          li.addEventListener("click", () => { document.getElementById("picked").value = city; box.innerHTML = ""; });
          box.appendChild(li);
        }
      }, %DELAY%);
    });
  </script>""")


async def picked(page) -> str:
    return await page.evaluate("document.getElementById('picked').value")


async def test_identity_location_waits_for_async_suggestions_and_picks_the_city(web):
    page, site = web
    site.add(URL, PAGE.replace("%DELAY%", "800"))
    await page.goto(URL)
    filler = HostedFormFiller(jitter=(0, 0))
    await filler._type(page, {"idx": 0, "kind": "combobox"}, "Faridabad")
    assert await picked(page) == "Faridabad, Haryana, India"


async def test_prefix_match_never_uses_a_page_wide_list(web):
    page, site = web
    site.add(URL, PAGE.replace("%DELAY%", "800").replace(' aria-controls="loc-listbox"', ""))
    await page.goto(URL)
    locator = page.locator("#loc")
    await locator.fill("Faridabad")
    assert not await pick_combobox_option(page, locator, "Faridabad", exact=False, wait_ms=1200)
    assert await picked(page) == ""


async def test_exact_answer_still_picks_an_exact_option(web):
    page, site = web
    site.add(URL, PAGE.replace("%DELAY%", "100"))
    await page.goto(URL)
    locator = page.locator("#loc")
    await locator.fill("Pune")
    assert await pick_combobox_option(page, locator, "Pune, Haryana, India", exact=True, wait_ms=1500)
    assert await picked(page) == "Pune, Haryana, India"
