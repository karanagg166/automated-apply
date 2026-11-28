"""Live 2026-11-28 Twilio: Greenhouse "Location (City)" is a react-select whose geo suggestions
arrive asynchronously; Enter after the short settle picked nothing -> "Please enter your location"."""

from __future__ import annotations

import pytest

from backend.app.browser_v2.adapters.common import HostedFormFiller
from backend.app.browser_v2.adapters.shared.combobox import pick_combobox_option
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


# Live 2026-11-28 Stripe: react-select only opens its menu after a pointer press; fill() alone
# left aria-expanded=false, so no suggestion ever rendered.
CLICK_TO_OPEN = html("""
  <input id="loc" role="combobox" data-aa-field="0" aria-expanded="false" autocomplete="off">
  <div id="loc-listbox" role="listbox"></div>
  <input type="hidden" id="picked">
  <script>
    const input = document.getElementById("loc"), box = document.getElementById("loc-listbox");
    input.addEventListener("mousedown", () => {
      input.setAttribute("aria-expanded", "true"); input.setAttribute("aria-controls", "loc-listbox"); });
    input.addEventListener("input", () => {
      box.innerHTML = "";
      if (input.getAttribute("aria-expanded") !== "true") return;
      const li = document.createElement("div");
      li.setAttribute("role", "option"); li.textContent = input.value + ", Haryana, India";
      li.addEventListener("click", () => { document.getElementById("picked").value = li.textContent; });
      setTimeout(() => box.appendChild(li), 300);
    });
  </script>""")

SCHOOL = html("""
  <label for="school">School*</label>
  <input id="school" role="combobox" data-aa-field="0" aria-controls="school-listbox" autocomplete="off">
  <div id="school-listbox" role="listbox"></div>
  <input type="hidden" id="picked">
  <script>
    const input = document.getElementById("school"), box = document.getElementById("school-listbox");
    const SCHOOLS = ["Indian Institute of Technology Delhi (IITD)", "Other"];
    input.addEventListener("input", () => {
      box.innerHTML = "";
      setTimeout(() => {
        for (const s of SCHOOLS.filter(s => s.toLowerCase().includes(input.value.toLowerCase()))) {
          const li = document.createElement("div");
          li.setAttribute("role", "option"); li.textContent = s;
          li.addEventListener("click", () => { document.getElementById("picked").value = s; });
          box.appendChild(li);
        }
      }, 400);
    });
  </script>""")


async def test_combobox_menu_that_opens_only_on_click_still_gets_the_city(web):
    page, site = web
    site.add(URL, CLICK_TO_OPEN)
    await page.goto(URL)
    await HostedFormFiller(jitter=(0, 0))._type(page, {"idx": 0, "kind": "combobox"}, "Faridabad")
    assert await picked(page) == "Faridabad, Haryana, India"


async def test_unlisted_college_picks_the_school_lists_own_other(web):
    page, site = web
    site.add(URL, SCHOOL)
    await page.goto(URL)
    filler = HostedFormFiller(jitter=(0, 0))
    assert await filler._apply_answer(page, {"idx": 0, "kind": "combobox", "label": "School*"}, "IIITDM Jabalpur")
    assert await picked(page) == "Other"


async def test_other_is_never_picked_for_non_education_questions(web):
    page, site = web
    site.add(URL, SCHOOL.replace("School*", "How did you hear about us?*"))
    await page.goto(URL)
    filler = HostedFormFiller(jitter=(0, 0))
    await filler._apply_answer(page, {"idx": 0, "kind": "combobox", "label": "How did you hear about us?*"},
                               "LinkedIn")
    assert await picked(page) == ""


def test_degree_aliases_map_indian_degrees_to_ats_levels():
    from backend.app.browser_v2.adapters.shared.combobox import degree_aliases

    assert degree_aliases("B.Tech")[0] == "Bachelor's Degree"
    assert degree_aliases("BTech CSE")[0] == "Bachelor's Degree"
    assert degree_aliases("B.E.")[0] == "Bachelor's Degree"
    assert degree_aliases("MCA")[0] == "Master's Degree"
    assert degree_aliases("M.Tech")[0] == "Master's Degree"
    assert degree_aliases("MBA")[0].startswith("Master of Business Administration")
    assert degree_aliases("Diploma") == ()


DEGREE = html("""
  <label for="deg">Degree*</label>
  <input id="deg" role="combobox" data-aa-field="0" aria-controls="deg-listbox" autocomplete="off">
  <div id="deg-listbox" role="listbox"></div>
  <input type="hidden" id="picked">
  <script>
    const input = document.getElementById("deg"), box = document.getElementById("deg-listbox");
    const LEVELS = ["Associate's Degree", "Bachelor's Degree", "Engineer's Degree", "Master's Degree", "Other"];
    input.addEventListener("input", () => {
      box.innerHTML = "";
      for (const s of LEVELS.filter(s => s.toLowerCase().includes(input.value.toLowerCase()))) {
        const li = document.createElement("div");
        li.setAttribute("role", "option"); li.textContent = s;
        li.addEventListener("click", () => { document.getElementById("picked").value = s; });
        box.appendChild(li);
      }
    });
  </script>""")


async def test_btech_picks_bachelors_degree_level(web):
    page, site = web
    site.add(URL, DEGREE)
    await page.goto(URL)
    filler = HostedFormFiller(jitter=(0, 0))
    assert await filler._apply_answer(page, {"idx": 0, "kind": "combobox", "label": "Degree*"}, "B.Tech")
    assert await picked(page) == "Bachelor's Degree"
