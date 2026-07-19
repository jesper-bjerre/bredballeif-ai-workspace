"""
HalBooking browser automation – handles login, navigation, page discovery,
and member creation on the ASP/AJAX admin site.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

load_dotenv()

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
DIAGNOSTIC_SCREENSHOTS_ENABLED = (
    os.getenv("BIF_ALLOW_DIAGNOSTIC_SCREENSHOTS", "false").strip().lower() == "true"
)
if DIAGNOSTIC_SCREENSHOTS_ENABLED:
    SCREENSHOTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class FormField:
    """Describes a single form element discovered on the page."""
    name: str
    field_type: str          # text, select, checkbox, radio, hidden, …
    element_id: str = ""
    label: str = ""
    required: bool = False
    options: list[str] = field(default_factory=list)   # for <select>
    value: str = ""          # current / default value


@dataclass
class PageInfo:
    """Snapshot of a page after navigation."""
    url: str
    title: str
    forms: list[list[FormField]] = field(default_factory=list)
    links: list[dict[str, str]] = field(default_factory=list)
    buttons: list[dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# HalBooking automation class
# ---------------------------------------------------------------------------
class HalBookingAutomation:
    """Drives a real browser session against the HalBooking admin site."""

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        headless: bool = True,
    ) -> None:
        self.base_url = (base_url or os.getenv("HALBOOKING_BASE_URL", "")).rstrip("/")
        self._username = username or os.getenv("HALBOOKING_USERNAME", "")
        self._password = password or os.getenv("HALBOOKING_PASSWORD", "")
        self._headless = headless

        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        """Launch browser and open a fresh context."""
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="da-DK",
        )
        self._page = self._context.new_page()
        # Auto-accept any JS dialogs (alert/confirm/beforeunload). The cart and
        # membership pages can raise a beforeunload confirm that otherwise blocks
        # subsequent navigation (e.g. when we leave to send a welcome email).
        self._page.on("dialog", lambda d: d.accept())

    def stop(self) -> None:
        """Close everything cleanly."""
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._pw = self._browser = self._context = self._page = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser not started – call start() first")
        return self._page

    # -- login ---------------------------------------------------------------
    def login(self) -> bool:
        """Log in to the HalBooking admin site.

        The site uses a Bootstrap modal with #loginname / #password fields.
        Clicking the Login button calls JS: login('default.asp','1') which
        does $.post('ajax.asp', {funktion:'login', value1: name, value2: pw})
        and then submits <form name="multiform"> via sende().
        """
        p = self.page

        # Navigate to the front page first
        p.goto(f"{self.base_url}/default.asp", wait_until="networkidle")
        self._screenshot("01_front_page")

        # Open the login modal
        login_link = p.locator('a:has-text("LOGIN")').first
        if login_link.is_visible():
            login_link.click()
            p.wait_for_timeout(1500)
            self._screenshot("02_login_form_opened")

        # Fill the login fields (#loginname = Medlemsnr, #password = Adgangskode)
        user_field = p.locator("#loginname")
        pass_field = p.locator("#password")

        if not user_field.is_visible() or not pass_field.is_visible():
            self._screenshot("02_login_fields_not_found")
            print("[!] Could not locate login fields. Check screenshots/.")
            return False

        user_field.fill(self._username)
        pass_field.fill(self._password)
        self._screenshot("03_credentials_filled")

        # Click the Login button which calls login('default.asp','1')
        login_btn = p.locator("#sub")
        if login_btn.is_visible():
            login_btn.click()
        else:
            # Fallback: invoke the JS login function directly
            p.evaluate("login('default.asp','1')")

        # Wait for the form submit and page navigation
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(3000)
        self._screenshot("04_after_login")

        # Check for success — after login the page should reload/navigate
        content = p.content().lower()
        if "ikke logget" in content or "forkert" in content:
            print("[!] Login failed – wrong credentials or session issue")
            return False

        print("[+] Login appears successful")
        return True

    # -- navigation ----------------------------------------------------------
    def navigate_to_find_user(self) -> PageInfo:
        """Navigate to admin_findbruger.asp (find/manage users page)."""
        self.page.goto(
            f"{self.base_url}/admin_findbruger.asp",
            wait_until="networkidle",
        )
        self.page.wait_for_timeout(1000)
        self._screenshot("05_find_user_page")
        return self.discover_page()

    def navigate_to(self, path: str) -> PageInfo:
        """Navigate to an arbitrary path under the base URL."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        self.page.goto(url, wait_until="networkidle")
        self.page.wait_for_timeout(1000)
        self._screenshot("nav_" + re.sub(r"\W+", "_", path)[:40])
        return self.discover_page()

    # -- page discovery ------------------------------------------------------
    def discover_page(self) -> PageInfo:
        """Inspect the current page and return structured info about all
        forms, fields, links and buttons."""
        p = self.page
        info = PageInfo(url=p.url, title=p.title())

        # --- discover forms ---
        form_els = p.locator("form").all()
        for form_el in form_els:
            fields: list[FormField] = []
            # inputs
            for inp in form_el.locator("input").all():
                fields.append(self._input_to_field(inp))
            # selects
            for sel in form_el.locator("select").all():
                fields.append(self._select_to_field(sel))
            # textareas
            for ta in form_el.locator("textarea").all():
                fields.append(FormField(
                    name=ta.get_attribute("name") or "",
                    field_type="textarea",
                    element_id=ta.get_attribute("id") or "",
                    value=ta.input_value(),
                ))
            if fields:
                info.forms.append(fields)

        # Also look for inputs NOT inside a <form> (AJAX sites often skip <form>)
        orphan_inputs = p.locator("input:not(form input), select:not(form select), textarea:not(form textarea)").all()
        if orphan_inputs:
            orphan_fields: list[FormField] = []
            for el in orphan_inputs:
                tag = el.evaluate("e => e.tagName.toLowerCase()")
                if tag == "select":
                    orphan_fields.append(self._select_to_field(el))
                elif tag == "textarea":
                    orphan_fields.append(FormField(
                        name=el.get_attribute("name") or "",
                        field_type="textarea",
                        element_id=el.get_attribute("id") or "",
                        value=el.input_value(),
                    ))
                else:
                    orphan_fields.append(self._input_to_field(el))
            if orphan_fields:
                info.forms.append(orphan_fields)

        # --- discover links ---
        for a in p.locator("a[href]").all():
            href = a.get_attribute("href") or ""
            text = (a.inner_text() or "").strip()[:80]
            if href and not href.startswith("javascript:void"):
                info.links.append({"text": text, "href": href})

        # --- discover buttons ---
        for btn in p.locator("button, input[type='button'], input[type='submit']").all():
            info.buttons.append({
                "text": (btn.inner_text() or btn.get_attribute("value") or "").strip()[:60],
                "id": btn.get_attribute("id") or "",
                "type": btn.get_attribute("type") or "",
            })

        return info

    # -- form interaction ----------------------------------------------------
    def fill_field(self, selector: str, value: str) -> None:
        """Fill a single field identified by CSS selector."""
        el = self.page.locator(selector).first
        el.wait_for(state="visible", timeout=5000)
        tag = el.evaluate("e => e.tagName.toLowerCase()")
        input_type = (el.get_attribute("type") or "").lower()

        if tag == "select":
            el.select_option(value)
        elif input_type == "checkbox":
            if value.lower() in ("true", "1", "yes", "on"):
                el.check()
            else:
                el.uncheck()
        elif input_type == "radio":
            el.check()
        else:
            el.fill(value)

    def fill_fields(self, field_values: dict[str, str]) -> None:
        """Fill multiple fields. Keys can be name, id, or CSS selector."""
        for key, value in field_values.items():
            # Try by name, then id, then as raw selector
            for selector in [
                f'[name="{key}"]',
                f'#{key}',
                key,
            ]:
                try:
                    el = self.page.locator(selector).first
                    if el.is_visible():
                        self.fill_field(selector, value)
                        break
                except Exception:
                    continue

    def click_button(self, text_or_selector: str) -> None:
        """Click a button by its visible text or CSS selector."""
        # Try as text first
        btn = self.page.locator(f'button:has-text("{text_or_selector}"), '
                                f'input[value="{text_or_selector}"]').first
        try:
            if btn.is_visible(timeout=2000):
                btn.click()
                self.page.wait_for_load_state("networkidle")
                return
        except Exception:
            pass

        # Try as CSS selector
        self.page.locator(text_or_selector).first.click()
        self.page.wait_for_load_state("networkidle")

    def wait_for_ajax(self, timeout_ms: int = 5000) -> None:
        """Wait until all AJAX (XMLHttpRequest / fetch) activity settles."""
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(min(timeout_ms, 1000))

    # -- member creation workflow --------------------------------------------
    def create_member(self, member_data: dict[str, str]) -> dict[str, Any]:
        """
        High-level workflow: create a new member on admin_findbruger.asp.

        Steps:
        1. Navigate to the find-user page.
        2. Look for a "new member" / "opret bruger" / "ny bruger" link or button.
        3. Discover the creation form fields.
        4. Fill in the supplied member_data.
        5. Submit and capture the result.

        Returns a dict with status and any discovered info.
        """
        p = self.page
        result: dict[str, Any] = {"success": False}

        # Step 1 – navigate
        page_info = self.navigate_to_find_user()
        result["page_info"] = self._page_info_to_dict(page_info)

        # Step 2 – find the "create new" link/button
        new_member_patterns = [
            'a:has-text("Opret")',
            'a:has-text("opret")',
            'a:has-text("Ny bruger")',
            'a:has-text("ny bruger")',
            'a:has-text("Tilføj")',
            'a:has-text("New")',
            'button:has-text("Opret")',
            'button:has-text("Ny")',
            'input[value*="Opret"]',
            'input[value*="opret"]',
            'input[value*="Ny"]',
            'a[href*="opret"]',
            'a[href*="nybruger"]',
            'a[href*="admin_bruger"]',
            'a[href*="editbruger"]',
            'a[href*="newbruger"]',
        ]

        clicked = False
        for selector in new_member_patterns:
            try:
                link = p.locator(selector).first
                if link.is_visible(timeout=1000):
                    link.click()
                    self.wait_for_ajax()
                    self._screenshot("06_new_member_form")
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            # Maybe the form is already on the page or loaded via AJAX
            # Try looking for a tab or a section
            self._screenshot("06_no_create_link_found")
            result["note"] = (
                "Could not find a 'create new member' link/button. "
                "The form might already be visible, or requires a different navigation path. "
                "Check screenshots/ for the current page state."
            )

        # Step 3 – discover the form
        form_info = self.discover_page()
        result["form_fields"] = self._page_info_to_dict(form_info)

        # Step 4 – fill in fields
        if member_data:
            self.fill_fields(member_data)
            self._screenshot("07_fields_filled")

        # Step 5 – submit (look for save/create button)
        save_patterns = [
            'button:has-text("Gem")',
            'button:has-text("gem")',
            'button:has-text("Opret")',
            'button:has-text("Save")',
            'input[type="submit"]',
            'input[value*="Gem"]',
            'input[value*="gem"]',
            'input[value*="Opret"]',
            'a:has-text("Gem")',
        ]

        submitted = False
        for selector in save_patterns:
            try:
                btn = p.locator(selector).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    self.wait_for_ajax(3000)
                    self._screenshot("08_after_submit")
                    submitted = True
                    break
            except Exception:
                continue

        result["submitted"] = submitted
        result["final_url"] = p.url
        result["success"] = submitted

        if not submitted:
            result["note"] = (
                result.get("note", "") +
                " Could not find a submit/save button. Check screenshots/."
            )

        return result

    # -- SOP onboarding workflow ---------------------------------------------
    def onboard_new_member(
        self,
        navn: str,
        mobil: str,
        email: str,
        membership_type: str,
        end_date: str,
        start_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Full onboarding workflow per SOP:
        1. Navigate to 'Opret nyt medlem'
        2. Fill: Gruppe=Padel medlem, Navn, Mobil, Email, email checkboxes
        3. Click 'Opret konto'
        4. Extract member number
        5. Read auto-generated password from Login info tab
        6. Set gratis gæstetimer to 0
        7. Click 'Opdater konto'
        8. Assign membership (prime/non-prime) with price 0 and end date

        Args:
            navn: Full name from Conventus
            mobil: Mobile number from Conventus
            email: Email from Conventus
            membership_type: 'prime' or 'non-prime'
            end_date: Membership end date, e.g. '31-12-2026'

        Returns dict with success status, member number, and welcome email.
        """
        p = self.page
        result: dict[str, Any] = {"success": False, "steps_completed": []}

        # --- Step 1: Navigate to Opret nyt medlem ---
        # Must go via admin_findbruger.asp first — direct URL returns 404.
        p.goto(f"{self.base_url}/admin_findbruger.asp", wait_until="networkidle")
        p.wait_for_timeout(1000)
        opret_div = p.locator("div[onclick*='admin_opretkonto.asp']")
        if opret_div.is_visible(timeout=5000):
            opret_div.click()
        else:
            p.evaluate("sende('admin_opretkonto.asp','nytmedlem','','','','')")
        p.wait_for_load_state("networkidle")
        # Wait for form JS to fully initialize (select options must be populated)
        try:
            p.wait_for_selector(
                '[name="konto_kundegruppe"] option:not(:first-child)',
                timeout=10000,
            )
        except Exception:
            pass
        p.wait_for_timeout(2000)
        self._screenshot("onboard_01_opret_form")

        # Verify we're on the creation page
        if "opretkonto" not in p.url and "opret" not in p.inner_text("body").lower()[:200]:
            self._screenshot("onboard_01_no_opret_page")
            result["error"] = "Kunne ikke navigere til oprettelsessiden. Se screenshots/."
            return result

        result["steps_completed"].append("1_navigate_opret")

        # --- Step 2: Fill creation form ---
        # Gruppe = "Padel medlem" — selecting triggers onchange which reloads
        # the page via sende(), so select FIRST, wait for reload, then fill.
        try:
            gruppe_sel = p.locator('[name="konto_kundegruppe"]').first
            if gruppe_sel.is_visible(timeout=3000):
                # Find option containing "Padel"
                options = gruppe_sel.locator("option").all()
                for opt in options:
                    if "padel" in (opt.inner_text() or "").lower():
                        gruppe_sel.select_option(opt.get_attribute("value"))
                        # The onchange triggers sende() which reloads the page
                        p.wait_for_load_state("networkidle")
                        p.wait_for_timeout(2000)
                        break
        except Exception as e:
            result["warnings"] = result.get("warnings", [])
            result["warnings"].append(f"Kunne ikke sætte medlemsgruppe: {type(e).__name__}")

        # After page reload, fill the other fields
        # Navn
        self._fill_if_visible('[name="konto_navn"]', navn)
        # Mobil
        self._fill_if_visible('[name="konto_mobil"]', mobil)
        # Email
        self._fill_if_visible('[name="konto_email"]', email)

        # --- Read auto-generated password from creation form (before submit) ---
        # Click the eye-icon to reveal the masked password, then read the value.
        password = ""
        try:
            eye_btn = p.locator(
                "button[title*='Vis'], button[title*='klar'], button[class*='eye'], "
                "span[class*='eye'], i[class*='eye'], button[onclick*='klar'], "
                "button[onclick*='vis']"
            ).first
            if eye_btn.is_visible(timeout=2000):
                eye_btn.click()
                p.wait_for_timeout(300)
            pw_field = p.locator("#konto_password1").first
            if pw_field.count() > 0:
                password = pw_field.input_value() or ""
        except Exception:
            pass
        result["password"] = password.strip()
        if password:
            print("  [+] Adgangskode oprettet (værdi redigeret fra log/output)")
            result["steps_completed"].append("password_read_from_form")

        # Email checkboxes
        for checkbox_name in ["konto_SvarMail", "konto_SendICS"]:
            try:
                cb = p.locator(f'[name="{checkbox_name}"]').first
                if cb.is_visible(timeout=1000):
                    cb.check()
            except Exception:
                pass

        self._screenshot("onboard_02_fields_filled")
        result["steps_completed"].append("2_fill_form")

        # --- Step 3: Click 'Opret konto' ---
        opret_btn = self._find_first([
            'span.btn:has-text("Opret konto")',
            'button:has-text("Opret konto")',
            'input[value*="Opret konto"]',
            'a:has-text("Opret konto")',
            'span.btn:has-text("Opret")',
        ])
        if not opret_btn:
            self._screenshot("onboard_03_no_opret_btn")
            result["error"] = "Kunne ikke finde 'Opret konto' knap. Se screenshots/."
            return result

        opret_btn.click()
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(3000)
        self._screenshot("onboard_03_after_opret")
        result["steps_completed"].append("3_opret_konto")

        # --- Step 4: Extract member number ---
        medlemsnr = ""
        try:
            body_text = p.inner_text("body")
            mnr_match = re.search(r"Medlemsnr:\s*(\d+)", body_text)
            if mnr_match:
                medlemsnr = mnr_match.group(1)
        except Exception:
            pass

        if not medlemsnr:
            self._screenshot("onboard_04_no_medlemsnr")
            result["error"] = "Kunne ikke finde medlemsnr efter oprettelse. Se screenshots/."
            return result

        result["medlemsnr"] = medlemsnr
        result["steps_completed"].append(f"4_got_medlemsnr_{medlemsnr}")
        print(f"  [+] Nyt medlemsnr: {medlemsnr}")

        # --- Step 5: Password already read from creation form (before submit) ---
        if result.get("password"):
            result["steps_completed"].append("5_password_already_read")
        else:
            # Fallback: try Login info tab on the new member's detail page
            fallback_pw = self.read_member_password()
            if fallback_pw:
                result["password"] = fallback_pw
                print("  [+] Adgangskode fundet (værdi redigeret fra log/output)")
                result["steps_completed"].append("5_read_password_fallback")
            else:
                result["warnings"] = result.get("warnings", [])
                result["warnings"].append("Kunne ikke aflæse auto-genereret adgangskode.")
                result["steps_completed"].append("5_read_password_failed")

        # --- Step 6: Set gratis gæstetimer to 0 ---
        profil_tab = self._find_first([
            'a:has-text("Din profil")',
            'span:has-text("Din profil")',
            'a:has-text("Medlemmets data")',
        ])
        if profil_tab:
            profil_tab.click()
            self.wait_for_ajax()
            p.wait_for_timeout(1000)

        self._fill_if_visible('[name="n_gratisgest"]', "0")
        self._fill_if_visible('#n_gratisgest', "0")
        self._screenshot("onboard_06_profile_set")
        result["steps_completed"].append("6_set_gratis_gaester_0")

        # --- Step 7: Click 'Opdater konto' ---
        opdater_btn = self._find_first([
            'span.btn:has-text("Opdater konto")',
            'button:has-text("Opdater konto")',
            'input[value*="Opdater konto"]',
            'a:has-text("Opdater konto")',
            'span.btn:has-text("Opdater")',
        ])
        if opdater_btn:
            opdater_btn.click()
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(2000)
            self._screenshot("onboard_07_after_opdater")
            result["steps_completed"].append("7_opdater_konto")
        else:
            result["warnings"] = result.get("warnings", [])
            result["warnings"].append("Kunne ikke finde 'Opdater konto' knap.")

        # --- Step 8: Assign membership ---
        self._assign_membership_on_detail_page(p, result, membership_type, end_date, start_date=start_date)

        result["success"] = True
        result["final_url"] = p.url
        return result

    def assign_membership(
        self,
        search_name: str,
        membership_type: str,
        end_date: str,
        start_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Assign a new membership to an existing member.

        Workflow:
        1. Search for the member and navigate to their detail page
        2. Navigate to Klippekort/medlemskaber
        3. Click +Tildel nyt medlemskab/klippekort
        4. Select the right membership product (varenr 1=non-prime, 2=prime)
        5. Set price to 0, start date to today-ish, end date as given
        6. Click Læg i indkøbskurv
        7. Click Godkend

        Args:
            search_name: Member name to search for
            membership_type: 'prime' or 'non-prime'
            end_date: Membership end date, e.g. '31-12-2026'
        """
        p = self.page
        result: dict[str, Any] = {"success": False, "steps_completed": []}

        # Step 1: Find the member
        search_result = self.search_member(search_name)
        if not search_result["success"]:
            result["error"] = f"Medlem '{search_name}' ikke fundet i HalBooking."
            return result

        # Extract member number from detail
        detail = search_result.get("member_detail", {})
        result["medlemsnr"] = detail.get("Medlemsnr", "")
        result["steps_completed"].append("1_found_member")

        # Make sure we're on the detail page (admin_konto.asp)
        if "admin_konto" not in p.url:
            result["error"] = "Ikke på medlemsdetaljeside efter søgning."
            return result

        # Step 2-7: Use shared membership assignment logic
        self._assign_membership_on_detail_page(p, result, membership_type, end_date, start_date=start_date)

        steps = result.get("steps_completed", [])
        result["success"] = (
            "8_membership_godkendt" in steps
            or "8_idempotent_already_exists" in steps
        )
        result["final_url"] = p.url
        return result

    def _assign_membership_on_detail_page(
        self,
        p: Page,
        result: dict[str, Any],
        membership_type: str,
        end_date: str,
        start_date: str | None = None,
    ) -> None:
        """
        Assign membership starting from the member detail page (admin_konto.asp).

        Navigation flow (discovered from actual site):
        1. Click "Klippekort/medlemskaber" sidebar div → admin_klippekort.asp
        2. Click "+Tildel nyt medlemskab/klippekort" button
        3. On catalog page: set mf_varenr (2=prime, 1=non-prime)
        4. Call sende('admin_klippekort.asp','loginsomklip','','','','')
        5. On purchase form: fill kobstartdato, kobslutdato, mf_specialpris
        6. Call nytabon1('<varenr>','0') (Læg i indkøbskurv)
        7. On cart page: fill meddelelse, check sendmail checkbox
        8. Click Godkend via sende('admin_kurv.asp','checkud',...)
        """
        # varenr: 2 = Padel Prime, 1 = Padel non-prime
        varenr = "2" if membership_type == "prime" else "1"

        # Step 8a: The member detail page (admin_konto.asp) already shows the
        # "Aktive medlemskaber/klippekort" panel with the
        # "+ Tildel nyt medlemskab/klippekort" button. Do NOT navigate to the
        # sidebar "Klippekort/medlemskaber" overview page — that page only has
        # per-product "Køb" buttons and not the Tildel button the flow needs.
        result["steps_completed"].append("8a_detail_page")

        # Step 8b: Click "+Tildel nyt medlemskab/klippekort"
        # The button is an <a class="btn btn-primary"> with
        # onclick="sende('admin_klippekort.asp','brugerklipstart',<uid>,...)".
        tildel_btn = self._find_first([
            'a[onclick*="brugerklipstart"]',
            '[onclick*="brugerklipstart"]',
            'a.btn:has-text("Tildel nyt medlemskab")',
            'a:has-text("Tildel nyt medlemskab")',
            'span.btn:has-text("Tildel nyt medlemskab")',
            'a.btn:has-text("Tildel")',
        ])
        if tildel_btn:
            tildel_btn.click()
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(3000)
            self._screenshot("onboard_08b_catalog_page")
            result["steps_completed"].append("8b_open_tildel")
        else:
            result.setdefault("warnings", []).append(
                "Kunne ikke finde 'Tildel nyt medlemskab' knap."
            )
            return

        # Step 8c: Set varenr and navigate to purchase form (bypass modal)
        p.evaluate(f"multiform.mf_varenr.value='{varenr}'")
        p.evaluate("sende('admin_klippekort.asp','loginsomklip','','','','')")
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(3000)
        self._screenshot("onboard_08c_purchase_form")
        result["steps_completed"].append("8c_purchase_form")

        # Step 8d: Fill purchase form
        # Start date: use provided start_date, or default to 01-01 of the end year
        if not start_date:
            try:
                end_year = end_date.split("-")[-1]
                start_date = f"01-01-{end_year}"
            except (IndexError, ValueError):
                start_date = end_date

        self._fill_if_visible('[name="kobstartdato"]', start_date)
        self._fill_if_visible('[name="kobslutdato"]', end_date)
        self._fill_if_visible('[name="mf_specialpris"]', "0,00")
        self._screenshot("onboard_08d_form_filled")
        result["steps_completed"].append("8d_form_filled")

        # Step 8e: Click "Læg i indkøbskurv" via JS
        p.evaluate(f"nytabon1('{varenr}','0')")
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(3000)
        self._screenshot("onboard_08e_cart")

        # Check for "Medlem har allerede denne vare" — idempotent no-op.
        # HalBooking afviser at give samme medlem samme produkt to gange.
        # Det er ikke en fejl: medlemmet HAR allerede præcis dette medlemskab,
        # så der er intet at gøre. Vi markerer success og afslutter tidligt.
        body_text = p.inner_text("body")
        if "allerede denne vare" in body_text.lower():
            self._screenshot("onboard_08e_already_exists")
            result.setdefault("warnings", []).append(
                "Medlem har allerede dette medlemskab — ingen handling nødvendig (idempotent)."
            )
            result["idempotent"] = True
            result["steps_completed"].append("8_idempotent_already_exists")
            return

        # Verify we're on the cart page
        if "admin_kurv" in p.url:
            result["steps_completed"].append("8e_in_cart")

            # Step 8f: Fill Meddelelse and check Send email
            self._fill_if_visible(
                '#meddelelse',
                'Bredballe IF Padel: Dit kontingent er fornyet/gyldigt',
            )
            # The sendmail checkbox is hidden but interactive via JS
            p.evaluate("document.getElementById('sendmail').checked = true")
            self._screenshot("onboard_08f_meddelelse_filled")
            result["steps_completed"].append("8f_meddelelse_and_email")

            # Step 8g: Click "Godkend"
            godkend_btn = self._find_first([
                'a[onclick*="checkud"]',
                '[onclick*="checkud"]',
                'a.btn:has-text("Godkend")',
                'a:has-text("Godkend")',
                'span.btn:has-text("Godkend")',
                'button:has-text("Godkend")',
            ])
            if godkend_btn:
                godkend_btn.click()
                p.wait_for_load_state("networkidle")
                p.wait_for_timeout(2000)
                self._screenshot("onboard_08g_after_godkend")
                result["steps_completed"].append("8_membership_godkendt")
            else:
                result.setdefault("warnings", []).append(
                    "Kunne ikke finde 'Godkend' knap på kurvsiden."
                )
        else:
            result.setdefault("warnings", []).append(
                "Ikke på kurvsiden efter 'Læg i indkøbskurv'. Se screenshots/."
            )

    def read_member_password(self) -> str:
        """Read the auto-generated password from the Login info tab.

        Must be called while on admin_konto.asp (member detail page).
        Navigates to Login info tab, clicks 'Vis klar tekst' to reveal
        the password, reads it from the field, then returns to profile tab.

        Returns the password string, or empty string on failure.
        """
        p = self.page
        password = ""

        # Navigate to Login info tab
        login_tab = self._find_first([
            'a:has-text("Login info")',
            'span:has-text("Login info")',
            'li:has-text("Login info")',
        ])
        if login_tab:
            login_tab.click()
            self.wait_for_ajax()
            p.wait_for_timeout(1500)
            self._screenshot("read_password_login_tab")

        # Read the password value from the field
        # (may only be populated for newly created members)
        try:
            pw_field = p.locator('#konto_password1').first
            if pw_field.is_visible(timeout=2000):
                password = pw_field.input_value() or ""
        except Exception:
            pass

        # Return to profile tab
        profil_tab = self._find_first([
            'a:has-text("Din profil")',
            'span:has-text("Din profil")',
            'a:has-text("Medlemmets data")',
        ])
        if profil_tab:
            profil_tab.click()
            self.wait_for_ajax()
            p.wait_for_timeout(500)

        return password.strip()

    def send_member_email(
        self,
        search_name: str,
        subject: str,
        body: str,
    ) -> dict[str, Any]:
        """Send an email to a member via the HalBooking 'Send email' modal.

        Workflow:
        1. Search for the member → navigate to admin_konto.asp
        2. Send email via the modal on the detail page

        Returns dict with success status and details.
        """
        p = self.page
        result: dict[str, Any] = {"success": False, "steps_completed": []}

        # Step 1: Search and navigate to member detail page
        search_result = self.search_member(search_name)
        if not search_result.get("success"):
            result["error"] = f"Medlem '{search_name}' ikke fundet i HalBooking."
            return result

        detail = search_result.get("member_detail", {})
        result["medlemsnr"] = detail.get("Medlemsnr", "")
        result["navn"] = detail.get("Navn", search_name)
        result["email"] = detail.get("Email", "")
        result["steps_completed"].append("1_found_member")

        if "admin_konto" not in p.url:
            result["error"] = "Ikke på medlemsdetaljeside efter søgning."
            return result

        # Step 2: Send email via modal
        self._send_email_on_detail_page(p, result, subject, body)
        return result

    def _send_email_on_detail_page(
        self,
        p: Page,
        result: dict[str, Any],
        subject: str,
        body: str,
    ) -> None:
        """Open the 'Send email' modal on admin_konto.asp and send an email.

        Must be called while on the member detail page (admin_konto.asp).
        Updates ``result`` dict in place with steps and success status.
        """
        # Click 'Send email' link to open the modal
        send_link = p.locator('a:has-text("Send email")').first
        try:
            if not send_link.is_visible(timeout=3000):
                result["error"] = "Kunne ikke finde 'Send email' link på medlemssiden."
                return
            send_link.click()
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(2000)
        except Exception as e:
            result["error"] = f"Fejl ved klik på 'Send email': {type(e).__name__}"
            return

        # Verify modal is open
        modal = p.locator(".modal.in")
        try:
            if not modal.first.is_visible(timeout=5000):
                result["error"] = "Email-modal åbnede ikke."
                return
        except Exception:
            result["error"] = "Email-modal åbnede ikke."
            return

        result["steps_completed"].append("email_modal_opened")
        self._screenshot("email_01_modal_opened")

        # Fill subject and body
        subject_field = modal.locator("#emailoverskrift").first
        body_field = modal.locator("#emailbesked").first

        try:
            subject_field.fill(subject[:50])  # maxlength=50
            body_field.fill(body[:3000])       # maxlength=3000
        except Exception as e:
            result["error"] = f"Fejl ved udfyldning af email-felter: {type(e).__name__}"
            return

        result["steps_completed"].append("email_fields_filled")
        self._screenshot("email_02_fields_filled")

        # Click 'Send' button. It is an <a class="btn btn-primary"> with
        # onclick="sende('admin_konto.asp','send_email',...)" — not a span.
        send_btn = None
        for sel in (
            'a[onclick*="send_email"]',
            'a.btn-primary:has-text("Send")',
            'span.btn-primary:has-text("Send")',
        ):
            cand = modal.locator(sel).first
            try:
                if cand.is_visible(timeout=2000):
                    send_btn = cand
                    break
            except Exception:
                continue
        if send_btn is None:
            result["error"] = "Kunne ikke finde 'Send' knap i modal."
            return
        try:
            send_btn.click()
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(3000)
        except Exception as e:
            result["error"] = f"Fejl ved klik på 'Send': {type(e).__name__}"
            return

        self._screenshot("email_03_after_send")

        # Check for success confirmation ("Mailen er sendt" or "Email sendt")
        try:
            confirmation = modal.locator(".beskedsendt").first
            if confirmation.is_visible(timeout=3000):
                result["steps_completed"].append("email_sent")
                result["success"] = True
            else:
                raise Exception("beskedsendt not visible")
        except Exception:
            try:
                body_text = p.inner_text("body")
                if "email sendt" in body_text.lower() or "mailen er sendt" in body_text.lower():
                    result["steps_completed"].append("email_sent")
                    result["success"] = True
                else:
                    try:
                        error_el = p.locator("#fejlbesked").first
                        if error_el.is_visible(timeout=1000):
                            error_text = error_el.inner_text().strip()
                            if error_text:
                                result["error"] = f"HalBooking fejl: {error_text}"
                                return
                    except Exception:
                        pass
                    result["steps_completed"].append("email_sent_unconfirmed")
                    result["success"] = True
            except Exception:
                result["steps_completed"].append("email_sent_unconfirmed")
                result["success"] = True

        result["final_url"] = p.url

    def exit_login_som_member(self) -> bool:
        """Exit the temporary 'login som medlem' mode, back to admin context.

        The membership purchase flow uses 'loginsomklip', which makes the admin
        browse AS the member. While in that mode admin pages (search, member
        detail) are inaccessible — navigating to admin_findbruger.asp just
        redirects to the member's own pages. The member view exposes a
        'LOG UD (ADM)' link with
        onclick="sende('admin_konto.asp','logudtempadmin',<uid>,...)" that drops
        back to the admin session and lands on the member's admin detail page
        (admin_konto.asp).

        Returns True if the exit link was found and clicked, False otherwise
        (e.g. we were already in normal admin context).
        """
        # The 'LOG UD (ADM)' link lives in a header menu that may be collapsed
        # (not "visible" to Playwright), so we read its onclick directly from
        # the DOM and execute the sende() call rather than clicking it.
        onclick = self.page.evaluate(
            """() => {
                const el = document.querySelector('[onclick*="logudtempadmin"]');
                return el ? el.getAttribute('onclick') : null;
            }"""
        )
        if not onclick:
            return False
        try:
            self.page.evaluate(onclick)
            self.page.wait_for_load_state("networkidle")
            self.page.wait_for_timeout(2000)
            self._screenshot("exit_login_som_member")
            return True
        except Exception:
            return False

    def get_sent_mail_subjects(self) -> list[str]:
        """Return the subjects (Emne) of every mail sent to the current member.

        Must be called while on the member detail page (admin_konto.asp).
        Navigates to the member-specific "Mails sendt" page (admin_mails.asp
        with funktion='bruger') via the sidebar link, reads the mail table,
        and returns the list of subjects. Note: this leaves the browser on
        the admin_mails.asp page — callers that need the detail page again
        should re-navigate (e.g. via get_member_detail).
        """
        p = self.page
        subjects: list[str] = []

        # The sidebar has two "Mails sendt" entries; only the member-specific
        # one carries funktion='bruger' + the member uid. Pick that one.
        mails_link = self._find_first([
            'div.link[onclick*="admin_mails.asp"][onclick*="bruger"]',
            '[onclick*="admin_mails.asp"][onclick*="bruger"]',
        ])
        if not mails_link:
            return subjects

        try:
            mails_link.click()
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(2000)
            self._screenshot("mails_sendt_page")
        except Exception:
            return subjects

        try:
            subjects = p.evaluate(
                r"""
                () => {
                  const out = [];
                  for (const tbl of document.querySelectorAll('table')) {
                    const rows = Array.from(tbl.querySelectorAll('tr'));
                    if (!rows.length) continue;
                    const header = Array.from(rows[0].querySelectorAll('td,th'))
                      .map(c => (c.textContent || '').trim());
                    const idx = header.indexOf('Emne');
                    if (idx === -1) continue;
                    for (let i = 1; i < rows.length; i++) {
                      const cells = Array.from(rows[i].querySelectorAll('td,th'))
                        .map(c => (c.textContent || '').trim());
                      if (cells[idx]) out.push(cells[idx]);
                    }
                  }
                  return out;
                }
                """
            ) or []
        except Exception:
            return []

        return subjects

    def has_welcome_email_been_sent(
        self, welcome_subject: str = "Velkommen som medlem"
    ) -> bool:
        """Check whether a welcome email has already been sent to the member.

        Reads the member's "Mails sendt" list and matches the welcome email
        subject (substring, case-insensitive). Must be called while on the
        member detail page (admin_konto.asp). Leaves the browser on the
        admin_mails.asp page.
        """
        needle = welcome_subject.lower()
        return any(needle in (s or "").lower() for s in self.get_sent_mail_subjects())

    def logout(self) -> None:
        """Log out of HalBooking via sende('admin_logud.asp','logud',...)."""
        try:
            self.page.evaluate("sende('admin_logud.asp','logud','','','','')")
            self.page.wait_for_load_state("networkidle")
            self.page.wait_for_timeout(1000)
        except Exception:
            pass

    def _fill_if_visible(self, selector: str, value: str) -> bool:
        """Fill a field if it's visible, return True if filled."""
        try:
            el = self.page.locator(selector).first
            if el.is_visible(timeout=1500):
                el.fill(value)
                return True
        except Exception:
            pass
        return False

    # -- member search workflow -----------------------------------------------
    def search_member(self, search_name: str) -> dict[str, Any]:
        """
        Search for a member by name on admin_findbruger.asp.

        The page has two search mechanisms:
        - #sogbru + sogbruger() — quick search (top bar)
        - #sogbru2 + sende('admin_findbruger.asp','sog2',...) — main search

        Results appear as a table with columns:
        Medlemsnr | Navn | Adresse | Telefon | Mobil | Medlemsgruppe | Aktivt Medlemskab

        Each row has a "Vælg medlem" button calling
        sende('admin_konto.asp','','{id}','','','{hash}')
        """
        p = self.page
        # success    = at least one member matched
        # search_ok  = the search itself executed correctly (page loaded,
        #              results parsed). search_ok=True + success=False means a
        #              legitimate "member not found" — safe to create. search_ok
        #              =False means a genuine failure — caller must NOT create.
        result: dict[str, Any] = {"success": False, "search_ok": False, "members": []}

        # Step 1 – navigate to the find-user page
        page_info = self.navigate_to_find_user()
        result["page_info"] = self._page_info_to_dict(page_info)

        # Step 2 – fill the search field and submit
        search_field = p.locator("#sogbru2")
        if not search_field.is_visible():
            search_field = p.locator("#sogbru")

        search_field.fill(search_name)
        self._screenshot("search_02_name_entered")

        # Submit via the search button
        search_btn = p.locator("#sogbruger2")
        if search_btn.is_visible():
            search_btn.click()
        else:
            # Fallback: call sogbruger() or press Enter
            btn = p.locator("#sogbruger")
            if btn.is_visible():
                btn.click()
            else:
                search_field.press("Enter")

        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(2000)
        self._screenshot("search_03_results")

        # The site may navigate directly to admin_konto.asp if only one match
        if "admin_konto" in p.url:
            detail = self._extract_detail_fields()
            member_summary = {}
            if detail:
                member_summary = {
                    "Medlemsnr": detail.get("Medlemsnr", ""),
                    "Navn": detail.get("Navn", ""),
                    "Adresse": detail.get("Adresse", ""),
                    "Telefon": detail.get("Telefon", ""),
                    "Mobil": detail.get("Mobil", ""),
                    "Email": detail.get("Email", ""),
                    "Medlemsgruppe": detail.get("Medlemsgruppe", ""),
                }
            result["members"] = [member_summary] if member_summary else []
            result["member_detail"] = detail
            result["success"] = bool(detail)
            result["search_ok"] = True
            result["search_term"] = search_name
            result["final_url"] = p.url
            return result

        # Step 3 – extract the result table
        result["members"] = self._extract_member_table()

        # Step 4 – if exactly one result, open detail automatically
        if len(result["members"]) == 1:
            detail = self._click_member_button(0)
            if detail:
                result["member_detail"] = detail

        result["success"] = len(result["members"]) > 0
        # The search ran correctly as long as we ended up on a recognised page
        # (the find-user page or a member detail page). If we are somewhere else
        # the search flow broke and the empty result is NOT trustworthy.
        result["search_ok"] = ("admin_findbruger" in p.url) or ("admin_konto" in p.url)
        result["search_term"] = search_name
        result["final_url"] = p.url

        if not result["success"]:
            result["note"] = (
                f"No members found matching '{search_name}'. "
                "Check screenshots/ for the page state."
            )

        return result

    def get_member_detail(self, search_name: str, row_index: int = 0) -> dict[str, Any]:
        """
        Search for a member and open their detail/account page.

        Clicks the "Vælg medlem" button for the matched row, which navigates
        to admin_konto.asp with full member details.
        """
        result: dict[str, Any] = {"success": False}

        # First do the search
        search_result = self.search_member(search_name)
        if not search_result["success"]:
            return search_result

        members = search_result["members"]
        if row_index >= len(members):
            result["note"] = f"Row index {row_index} out of range (found {len(members)} members)"
            result["members"] = members
            return result

        # If single result already has detail, add memberships and return
        if "member_detail" in search_result and row_index == 0:
            search_result["active_memberships"] = self._extract_active_memberships()
            return search_result

        # Click the "Vælg medlem" button for the specified row
        detail = self._click_member_button(row_index)
        result["member_detail"] = detail or {}
        result["success"] = bool(detail)
        result["members"] = members
        result["search_term"] = search_name
        if detail:
            result["active_memberships"] = self._extract_active_memberships()
        return result

    def _extract_member_table(self) -> list[dict[str, str]]:
        """Extract member rows from the results table on admin_findbruger.asp.

        The table has headers: Medlemsnr, Navn, Adresse, Telefon, Mobil,
        Medlemsgruppe, Aktivt Medlemskab, and a button column.
        """
        p = self.page
        members: list[dict[str, str]] = []

        # Find tables and pick the one with member data
        tables = p.locator("table").all()
        for table in tables:
            rows = table.locator("tr").all()
            if len(rows) < 2:
                continue

            # Get headers from first row
            header_row = rows[0]
            headers: list[str] = []
            for cell in header_row.locator("th, td").all():
                headers.append((cell.inner_text() or "").strip())

            # Must look like a member table
            header_text = " ".join(headers).lower()
            if "navn" not in header_text and "medlemsnr" not in header_text:
                continue

            # Extract data rows
            for row in rows[1:]:
                cells = row.locator("td").all()
                if not cells:
                    continue
                member: dict[str, str] = {}
                for i, cell in enumerate(cells):
                    key = headers[i] if i < len(headers) else f"col_{i}"
                    text = (cell.inner_text() or "").strip()
                    # Skip button-only columns
                    if text == "Vælg medlem":
                        continue
                    if text:
                        member[key] = text
                if member:
                    members.append(member)

        return members

    def _click_member_button(self, row_index: int) -> dict[str, str] | None:
        """Click the 'Vælg medlem' button for a specific row and extract
        the member detail page fields."""
        p = self.page

        # The buttons have sequential IDs: id_btn_1, id_btn_2, etc.
        btn_id = f"#id_btn_{row_index + 1}"
        btn = p.locator(btn_id)

        try:
            if not btn.is_visible(timeout=2000):
                # Fallback: find all "Vælg medlem" buttons
                all_btns = p.locator('span.btn:has-text("Vælg medlem")').all()
                if row_index < len(all_btns):
                    btn = all_btns[row_index]
                else:
                    return None

            btn.click()
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(2000)
            self._screenshot("search_04_member_detail")

            return self._extract_detail_fields()
        except Exception as e:
            print(f"[!] Could not click member button: {type(e).__name__}")
            return None

    def _extract_detail_fields(self) -> dict[str, str]:
        """Extract all member fields from admin_konto.asp detail page.

        The page uses input fields with konto_ prefix:
        konto_navn, konto_adresse1, konto_postnr, konto_postby,
        konto_telefon, konto_mobil, konto_email, konto_kundegruppe, etc.
        """
        p = self.page
        detail: dict[str, str] = {}

        # Map of field names to friendly display names
        field_map = {
            "konto_navn": "Navn",
            "konto_adresse1": "Adresse",
            "konto_co": "C/O",
            "konto_alinie3": "Adresselinie 3",
            "konto_landekode": "Land",
            "konto_postnr": "Postnr",
            "konto_postby": "By",
            "kommunenr": "Kommune",
            "konto_telefon": "Telefon",
            "konto_mobilland": "Mobillandekode",
            "konto_mobil": "Mobil",
            "konto_email": "Email",
            "konto_kundegruppe": "Medlemsgruppe",
            "konto_briknummer": "Briknummer",
            "konto_kortnummer": "Kortnummer",
            "konto_loginid": "Login ID",
            "konto_startomraede": "Startområde",
            "brugerinfo": "Brugerinfo",
            "prisgruppe": "Prisgruppe",
            "multibookregel": "Multi-bookingregel",
            "n_gratisgest": "Gratis gæster",
        }

        # Extract Medlemsnr from the page text
        try:
            body_text = p.inner_text("body")
            import re as _re
            mnr_match = _re.search(r"Medlemsnr:\s*(\d+)", body_text)
            if mnr_match:
                detail["Medlemsnr"] = mnr_match.group(1)
        except Exception:
            pass

        # Extract creation date
        try:
            oprettet_match = _re.search(r"Oprettet:\s*(.+?)(?:\n|$)", body_text)
            if oprettet_match:
                detail["Oprettet"] = oprettet_match.group(1).strip()
        except Exception:
            pass

        # Read all mapped fields
        for field_name, display_name in field_map.items():
            try:
                el = p.locator(f'[name="{field_name}"]').first
                if not el.count():
                    el = p.locator(f'#{field_name}').first
                if not el.count():
                    continue

                tag = el.evaluate("e => e.tagName.toLowerCase()")
                if tag == "select":
                    try:
                        opt = el.locator("option:checked").first
                        val = (opt.inner_text() or "").strip()
                    except Exception:
                        val = el.input_value()
                else:
                    val = el.input_value()

                if val and val != "0":
                    detail[display_name] = val
            except Exception:
                pass

        # Also capture any extra konto_ fields not in the map
        for inp in p.locator('input[name^="konto_"], select[name^="konto_"]').all():
            name = inp.get_attribute("name") or ""
            if name in field_map:
                continue
            try:
                tag = inp.evaluate("e => e.tagName.toLowerCase()")
                if tag == "select":
                    opt = inp.locator("option:checked").first
                    val = (opt.inner_text() or "").strip()
                else:
                    val = inp.input_value()
                if val and val != "0":
                    detail[name] = val
            except Exception:
                pass

        return detail

    # -- membership extraction -----------------------------------------------
    def _extract_active_memberships(self) -> list[dict[str, str]]:
        """Navigate to Klippekort/medlemskaber tab on the current detail page
        and extract active memberships.

        Must be called while on admin_konto.asp (member detail page).
        Returns a list of dicts with keys like 'type' and 'period'.
        """
        p = self.page
        memberships: list[dict[str, str]] = []

        # Click the "Klippekort/medlemskaber" sidebar link
        klip_div = self._find_first([
            'div:has-text("Klippekort/medlemskaber")',
        ])
        if not klip_div:
            return memberships

        klip_div.click()
        self.wait_for_ajax()
        p.wait_for_timeout(2000)
        self._screenshot("membership_01_klippekort_tab")

        # The active memberships section has a heading "Aktive medlemskaber/klippekort"
        # followed by rows showing membership type and date range.
        # Extract by finding tables or structured text in that section.
        try:
            body_text = p.inner_text("body")
            # Find the "Aktive" section
            import re as _re
            aktive_match = _re.search(
                r"Aktive medlemskaber/klippekort(.+?)(?:Udl.bne medlemskaber|Klippekortshistorik|Tildel nyt|$)",
                body_text,
                _re.DOTALL | _re.IGNORECASE,
            )
            if aktive_match:
                section = aktive_match.group(1).strip()
                # Parse rows: look for lines with membership name and date range
                # Typical format: "Padel Prime\n01-08-2022 - 31-12-2026"
                lines = [l.strip() for l in section.splitlines() if l.strip()]
                i = 0
                while i < len(lines):
                    line = lines[i]
                    # Look for a date range pattern on this or next line
                    date_pattern = r"(\d{2}-\d{2}-\d{4})\s*-\s*(\d{2}-\d{2}-\d{4})"
                    date_match = _re.search(date_pattern, line)
                    if date_match:
                        # Date range found on this line — membership name is previous line
                        entry: dict[str, str] = {
                            "start_date": date_match.group(1),
                            "end_date": date_match.group(2),
                            "period": f"{date_match.group(1)} - {date_match.group(2)}",
                        }
                        # Check if there's a name before the dates on this line
                        before_dates = line[:date_match.start()].strip()
                        if before_dates:
                            entry["name"] = before_dates
                        elif i > 0 and not _re.search(date_pattern, lines[i - 1]):
                            entry["name"] = lines[i - 1]
                        memberships.append(entry)
                    i += 1
        except Exception:
            pass

        # Fallback: try extracting from table rows
        if not memberships:
            try:
                tables = p.locator("table").all()
                for table in tables:
                    table_text = (table.inner_text() or "").lower()
                    if "padel" not in table_text and "medlemskab" not in table_text:
                        continue
                    rows = table.locator("tr").all()
                    for row in rows:
                        cells = row.locator("td").all()
                        texts = [(c.inner_text() or "").strip() for c in cells]
                        if len(texts) >= 2:
                            import re as _re
                            for t in texts:
                                date_match = _re.search(
                                    r"(\d{2}-\d{2}-\d{4})\s*-\s*(\d{2}-\d{2}-\d{4})", t
                                )
                                if date_match:
                                    name_parts = [x for x in texts if x != t and x]
                                    memberships.append({
                                        "name": " ".join(name_parts) if name_parts else "",
                                        "start_date": date_match.group(1),
                                        "end_date": date_match.group(2),
                                        "period": f"{date_match.group(1)} - {date_match.group(2)}",
                                    })
                                    break
            except Exception:
                pass

        # Navigate back to member data tab
        profil_tab = self._find_first([
            'a:has-text("Medlemmets data")',
            'div:has-text("Medlemmets data")',
            'a:has-text("Din profil")',
        ])
        if profil_tab:
            profil_tab.click()
            self.wait_for_ajax()
            p.wait_for_timeout(1000)

        return memberships

    def _extract_klippekort_all(self) -> tuple[list[dict], list[dict]]:
        """Extract ALL memberships (active + expired) from the already-loaded
        Klippekort/Medlemskaber page.

        Page format (tab-separated):
          Aktive medlemskaber/klippekort
          Varenr  Tekst  \\xa0  Datoer/Klip  Bem  \\xa0
          {varenr}  {name}  \\t  {DD-MM-YYYY} - {DD-MM-YYYY}  \\xa0  Ret

          Udløbne klippekort/Medlemskaber  (optional section)
          ...same format...

        Long-term memberships span multiple years (e.g. 01-08-2022 - 31-12-2026
        covers 2022, 2023, 2024, 2025, 2026). The 'years' key in each entry
        lists all years in the range.

        Returns (active_list, expired_list).
        """
        import re as _re

        p = self.page
        body_text = p.inner_text("body")

        date_range_pat = _re.compile(r"(\d{2}-\d{2}-\d{4})\s*-\s*(\d{2}-\d{2}-\d{4})")

        # Find section boundaries
        aktive_m = _re.search(r"Aktive\s+\S+", body_text, _re.IGNORECASE)
        udlob_m  = _re.search(r"Udl.bne\s+\S+", body_text, _re.IGNORECASE)

        aktive_start = aktive_m.end() if aktive_m else 0
        udlob_start  = udlob_m.start() if udlob_m else len(body_text)
        udlob_end    = udlob_m.end()   if udlob_m else len(body_text)

        aktive_section = body_text[aktive_start:udlob_start]
        udlob_section  = body_text[udlob_end:] if udlob_m else ""

        def parse_rows(text: str, default_expired: bool) -> list[dict]:
            entries = []
            for match in date_range_pat.finditer(text):
                start_str = match.group(1)
                end_str   = match.group(2)
                try:
                    start_year = int(start_str.split("-")[-1])
                    end_year   = int(end_str.split("-")[-1])
                except (ValueError, IndexError):
                    continue

                # Name: tab-separated fields on the same line, before the date range
                line_start = text.rfind("\n", 0, match.start())
                line_before = text[line_start + 1:match.start()]
                name_parts = [p.strip() for p in line_before.split("\t")
                               if p.strip() and p.strip() != "\xa0"]
                name = " ".join(name_parts) if name_parts else ""

                y1, y2 = min(start_year, end_year), max(start_year, end_year)
                entry: dict = {
                    "name": name,
                    "start_date": start_str,
                    "end_date": end_str,
                    "start_year": start_year,
                    "end_year": end_year,
                    "year": end_year,
                    "years": list(range(y1, y2 + 1)),
                    "status": "udløbet" if default_expired else "aktiv",
                }
                entries.append(entry)
            return entries

        active  = parse_rows(aktive_section, False)
        expired = parse_rows(udlob_section,  True)
        return active, expired

    # -- court availability (admin_baner.asp) --------------------------------
    # Padel courts in Bredballe. Column order in the day grid maps to these.
    PADEL_COURTS = ["SPORT 24", "Sydbank", "home Vejle"]

    def check_court_availability(
        self,
        date_str: str,
        time_from: str | None = None,
        time_to: str | None = None,
    ) -> dict[str, Any]:
        """Check which padel courts are free on a given date / time window.

        Navigates to ``admin_baner.asp``, sets the date in ``#banedato`` and
        reads the day grid. The grid has one column per court (in order:
        SPORT 24, Sydbank, home Vejle) and one block per time slot. Each slot
        is classified as ``free`` or ``booked``.

        Args:
            date_str:  Date to check, format ``DD-MM-YYYY`` (e.g. ``28-06-2026``).
            time_from: Optional lower bound ``HH:MM`` to filter slots (inclusive).
            time_to:   Optional upper bound ``HH:MM`` to filter slots (exclusive).

        Returns a dict::

            {
              "date": "28-06-2026",
              "success": bool,
              "courts": [
                {"bane": 1, "name": "SPORT 24",
                 "slots": [{"time": "08:00", "end": "09:00",
                            "status": "free"|"booked", "label": str}],
                 "free": ["08:00", ...], "booked": ["09:00", ...]},
                ...
              ],
              "note": str,          # set on error / when nothing parsed
            }
        """
        p = self.page
        result: dict[str, Any] = {
            "date": date_str,
            "success": False,
            "courts": [],
        }

        # --- Navigate to the court overview page ---
        p.goto(f"{self.base_url}/admin_baner.asp", wait_until="networkidle")
        p.wait_for_timeout(1500)
        self._screenshot("baner_01_loaded")

        # --- Set the date in #banedato and trigger the grid reload ---
        date_input = p.locator("#banedato").first
        if date_input.count() == 0:
            result["note"] = (
                "Kunne ikke finde datofeltet #banedato på admin_baner.asp. "
                "Se screenshots/baner_01_loaded.png."
            )
            return result

        # The field may be readonly (datepicker), so set the value via JS and
        # dispatch a change event to fire whatever onchange reloads the grid.
        try:
            date_input.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        p.evaluate(
            """(d) => {
                const el = document.getElementById('banedato');
                if (!el) return;
                el.value = d;
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }""",
            date_str,
        )
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(2500)
        self._screenshot("baner_02_date_set")

        # --- Locate the grid container (absolute XPath from the page) ---
        grid_xpath = (
            "/html/body/div[1]/form/div[1]/section/div/div/div[2]/div[2]/div/"
            "div[2]/div[2]/div/div[3]/div[2]/div"
        )
        container = p.locator(f"xpath={grid_xpath}").first
        if container.count() == 0:
            result["note"] = (
                "Kunne ikke finde bane-grid-containeren. Layoutet kan have "
                "ændret sig. Se screenshots/baner_02_date_set.png."
            )
            return result

        # --- Extract the per-column slot blocks ---
        # Walk each of the (up to) 3 columns and collect candidate slot blocks.
        # A block is anything carrying a time (in text or title) or an onclick.
        raw_columns = container.evaluate(
            r"""
            (root) => {
              const timeRe = /(\d{1,2})[.:](\d{2})/;
              // Direct children are the court columns.
              let cols = Array.from(root.children);
              // If the container wraps a single inner grid, descend once.
              if (cols.length === 1 && cols[0].children.length >= 2) {
                cols = Array.from(cols[0].children);
              }
              const out = [];
              for (const col of cols) {
                const blocks = [];
                // Candidate slot elements: leaf-ish nodes with text or onclick.
                const nodes = col.querySelectorAll('*');
                for (const n of nodes) {
                  const txt = (n.textContent || '').replace(/\s+/g, ' ').trim();
                  const title = (n.getAttribute && n.getAttribute('title')) || '';
                  const onclick = (n.getAttribute && n.getAttribute('onclick')) || '';
                  const cls = (n.className && n.className.toString()) || '';
                  const hasTime = timeRe.test(txt) || timeRe.test(title);
                  if (!hasTime && !onclick) continue;
                  // Skip wrapper nodes that just contain other slot nodes.
                  const childWithTime = Array.from(n.children).some(c =>
                    timeRe.test((c.textContent || '')) ||
                    timeRe.test((c.getAttribute && c.getAttribute('title')) || ''));
                  if (childWithTime && !onclick) continue;
                  let bg = '';
                  try { bg = getComputedStyle(n).backgroundColor || ''; } catch (e) {}
                  blocks.push({ text: txt, title, onclick, cls, bg });
                }
                out.push({
                  header: (col.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60),
                  blocks,
                });
              }
              return out;
            }
            """
        )

        result["courts"] = self._parse_court_columns(
            raw_columns, time_from=time_from, time_to=time_to
        )
        any_slots = any(c["slots"] for c in result["courts"])
        result["success"] = bool(result["courts"]) and any_slots
        if not any_slots:
            result["note"] = (
                "Grid fundet, men ingen tidsblokke kunne parses. Råt HTML gemmes "
                "ikke; brug kun eksplicit godkendt, kortlivet diagnostik."
            )
        return result

    def create_straks_booking(
        self,
        date_str: str,
        court: int,
        start_time: str,
        duration_minutes: int,
        text: str = "",
    ) -> dict[str, Any]:
        """Create and approve a booking from admin_baner/admin_straks.

        Flow:
        1. Open ``admin_baner.asp`` and set ``#banedato``.
        2. Click the free slot starting at ``start_time`` on ``court``.
        3. On ``admin_straks.asp`` set booking text and end time.
        4. Click ``Godkend reservation``.
        """
        p = self.page
        result: dict[str, Any] = {
            "success": False,
            "date": date_str,
            "court": court,
            "start_time": start_time,
            "duration_minutes": duration_minutes,
            "text": text,
            "steps_completed": [],
        }

        if court not in (1, 2, 3):
            result["note"] = "Bane skal være 1, 2 eller 3."
            return result
        if duration_minutes <= 0:
            result["note"] = "Varighed skal være over 0 minutter."
            return result
        if duration_minutes % 30 != 0:
            result["note"] = "Varighed skal være et multiplum af 30 minutter."
            return result

        first_end = self._time_add_minutes(start_time, 30)
        final_end = self._time_add_minutes(start_time, duration_minutes)
        if not first_end or not final_end:
            result["note"] = "Ugyldig tid. Brug format HH:MM."
            return result
        result["end_time"] = final_end

        # Step 1: open day grid and set date.
        p.goto(f"{self.base_url}/admin_baner.asp", wait_until="networkidle")
        p.wait_for_timeout(1200)
        date_input = p.locator("#banedato").first
        if date_input.count() == 0:
            result["note"] = "Kunne ikke finde #banedato på admin_baner.asp."
            return result

        p.evaluate(
            """(d) => {
                const el = document.getElementById('banedato');
                if (!el) return;
                el.value = d;
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }""",
            date_str,
        )
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(2000)
        self._screenshot("straks_01_grid_ready")
        result["steps_completed"].append("1_grid_ready")

        # Step 2: click the free half-hour block that starts the reservation.
        slot_selector = (
            f"span.btn_ledig[onclick*=\";1;{court};{start_time};{first_end};0;\"]"
        )
        slot = p.locator(slot_selector).first
        if slot.count() == 0:
            result["note"] = (
                f"Ingen ledig slot fundet på bane {court} kl. {start_time} "
                f"({start_time}-{first_end})."
            )
            self._screenshot("straks_01_no_slot")
            return result

        onclick = slot.get_attribute("onclick") or ""
        result["slot_onclick"] = onclick
        slot.click()
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(2000)
        self._screenshot("straks_02_form_open")
        result["steps_completed"].append("2_form_open")

        if "admin_straks.asp" not in p.url:
            result["note"] = "Kom ikke til admin_straks.asp efter klik på ledig slot."
            return result

        # Step 3: set text and expand end-time to requested duration.
        if text:
            if self._fill_if_visible("#book_tekst", text):
                result["steps_completed"].append("3_text_set")

        p.evaluate(
            """(cfg) => {
                const {dateStr, courtNo, fromTime, toTime} = cfg;
                const setVal = (name, value) => {
                    const el = document.querySelector(`[name="${name}"]`);
                    if (el) el.value = value;
                };
                setVal('mf_tiltid', toTime);
                setVal('mf_multiretbooking', `${dateStr};1;${courtNo};${fromTime};${toTime};0;`);
            }""",
            {
                "dateStr": date_str,
                "courtNo": court,
                "fromTime": start_time,
                "toTime": final_end,
            },
        )
        p.wait_for_timeout(300)
        self._screenshot("straks_03_form_updated")
        result["steps_completed"].append("3_duration_set")

        # Step 4: approve reservation.
        approve_btn = self._find_first([
            '#id_btn_2',
            'span.btn:has-text("Godkend reservation")',
            '[onclick*="godkendreservation"]',
        ])
        if not approve_btn:
            result["note"] = "Kunne ikke finde 'Godkend reservation' knappen."
            self._screenshot("straks_04_no_approve_btn")
            return result

        approve_btn.click()
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(2500)
        self._screenshot("straks_05_after_approve")
        result["steps_completed"].append("4_approved")

        body_text = p.inner_text("body").lower()
        success_markers = [
            "godkendt",
            "reservation",
            "oprettet",
            "booking",
        ]
        result["success"] = any(m in body_text for m in success_markers)
        if not result["success"]:
            # We still treat a redirect back to booking pages as likely success,
            # because HalBooking often does not show a strict success banner.
            result["success"] = any(
                x in p.url for x in ("admin_baner.asp", "admin_straks.asp", "admin_liste.asp")
            )

        result["final_url"] = p.url
        if not result["success"]:
            result["note"] = "Kunne ikke bekræfte booking sikkert ud fra sideindhold."
        return result

    def _parse_court_columns(
        self,
        raw_columns: list[dict],
        time_from: str | None = None,
        time_to: str | None = None,
    ) -> list[dict[str, Any]]:
        """Turn raw extracted column blocks into structured per-court slots.

        Classifies each block as ``free`` or ``booked`` and (optionally)
        filters slots to the ``time_from``/``time_to`` window.
        """
        time_re = re.compile(r"(\d{1,2})[.:](\d{2})")

        def to_minutes(hhmm: str | None) -> int | None:
            if not hhmm:
                return None
            m = time_re.search(hhmm)
            if not m:
                return None
            return int(m.group(1)) * 60 + int(m.group(2))

        lo = to_minutes(time_from)
        hi = to_minutes(time_to)

        courts: list[dict[str, Any]] = []
        for idx, col in enumerate(raw_columns):
            name = (
                self.PADEL_COURTS[idx]
                if idx < len(self.PADEL_COURTS)
                else f"Bane {idx + 1}"
            )
            slots: list[dict[str, Any]] = []
            seen: set[str] = set()
            for block in col.get("blocks", []):
                text = (block.get("text") or "").strip()
                title = (block.get("title") or "").strip()
                source = f"{text} {title}".strip()
                m = time_re.search(source)
                if not m:
                    continue
                start = f"{int(m.group(1)):02d}:{m.group(2)}"
                start_min = int(m.group(1)) * 60 + int(m.group(2))

                # Optional time-window filter.
                if lo is not None and start_min < lo:
                    continue
                if hi is not None and start_min >= hi:
                    continue

                # Second time on the block (if any) = end time.
                end = ""
                rest = source[m.end():]
                m2 = time_re.search(rest)
                if m2:
                    end = f"{int(m2.group(1)):02d}:{m2.group(2)}"

                # A slot is "booked" when it carries a label beyond the times
                # (a member/booking name) or a booking-coloured background.
                # An empty / create-booking cell is "free".
                onclick = (block.get("onclick") or "").lower()
                label = text
                for t in (start, end):
                    if t:
                        label = label.replace(t, "").replace(t.replace(":", "."), "")
                label = label.strip(" -–\u00a0")

                booked = bool(label) or "rediger" in onclick or "vis" in onclick
                if onclick and any(
                    k in onclick for k in ("nybooking", "opretbooking", "ledig", "book")
                ):
                    booked = False

                key = f"{start}|{end}"
                if key in seen:
                    continue
                seen.add(key)

                slots.append({
                    "time": start,
                    "end": end,
                    "status": "booked" if booked else "free",
                    "label": label,
                })

            slots.sort(key=lambda s: s["time"])
            courts.append({
                "bane": idx + 1,
                "name": name,
                "slots": slots,
                "free": [s["time"] for s in slots if s["status"] == "free"],
                "booked": [s["time"] for s in slots if s["status"] == "booked"],
            })
        return courts

    def _time_add_minutes(self, hhmm: str, minutes: int) -> str:
        """Return HH:MM plus ``minutes`` (24h wraparound)."""
        m = re.match(r"^(\d{1,2}):(\d{2})$", (hhmm or "").strip())
        if not m:
            return ""
        hour = int(m.group(1))
        minute = int(m.group(2))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return ""
        total = (hour * 60 + minute + minutes) % (24 * 60)
        return f"{total // 60:02d}:{total % 60:02d}"

    def get_membership_history(self, search_name: str) -> dict:
        """Return full membership history (active + expired) for a member.

        Navigates to admin_konto.asp → Klippekort/Medlemskaber tab and
        extracts all memberships.  The "Restklip/udløb" column value
        (e.g. "Torsdag 31-12-2024  Udløbet") is the canonical source for
        the expiry year, which also tells us that the member was active in
        that year.

        Returns:
            {
              "navn": str,
              "medlemsnr": str,
              "active": [...],     # memberships not yet expired
              "expired": [...],    # memberships that have expired
              "years_active": [2022, 2023, 2024],  # sorted unique years
              "success": bool,
              "note": str,         # set on error
            }
        """
        history: dict = {
            "navn": search_name,
            "medlemsnr": "",
            "active": [],
            "expired": [],
            "years_active": [],
            "success": False,
        }

        p = self.page

        # Navigate to member detail page
        search_result = self.search_member(search_name)
        if not search_result.get("success"):
            history["note"] = f"Ingen membri fundet for '{search_name}'."
            return history

        members = search_result.get("members", [])

        # If search landed on the list (not directly on detail), click first row
        if "admin_konto" not in p.url and members:
            detail = self._click_member_button(0)
            if detail:
                search_result["member_detail"] = detail

        detail = search_result.get("member_detail", {})
        history["navn"]      = detail.get("Navn", search_name)
        history["medlemsnr"] = detail.get("Medlemsnr", "")

        # Navigate to Klippekort/Medlemskaber tab
        klip_div = self._find_first(["div:has-text(\"Klippekort/medlemskaber\")"])
        if not klip_div:
            history["note"] = "Kunne ikke finde 'Klippekort/medlemskaber' fanen."
            return history

        klip_div.click()
        self.wait_for_ajax()
        p.wait_for_timeout(2000)
        self._screenshot("hist_01_klippekort")

        history["active"], history["expired"] = self._extract_klippekort_all()

        all_ms = history["active"] + history["expired"]
        years: set[int] = set()
        for ms in all_ms:
            # Use 'years' (expanded range) if available, else fall back to 'year'
            for y in ms.get("years", [ms.get("year", 0)]):
                if 2000 < y < 2100:
                    years.add(y)
        history["years_active"] = sorted(years)
        history["success"] = True

        return history

    # -- intercept AJAX calls ------------------------------------------------
    def start_ajax_capture(self) -> list[dict[str, Any]]:
        """Start capturing all XHR/fetch requests for debugging."""
        captured: list[dict[str, Any]] = []

        def on_request(request):
            if request.resource_type in ("xhr", "fetch"):
                captured.append({
                    "method": request.method,
                    "url": request.url,
                    "post_data": request.post_data,
                })

        self.page.on("request", on_request)
        return captured

    def get_page_html(self) -> str:
        """Return the current page's full HTML (useful for debugging AJAX pages)."""
        return self.page.content()

    # -- helpers -------------------------------------------------------------
    def _find_first(self, selectors: list[str]):
        """Return the first visible element matching any of the selectors."""
        for sel in selectors:
            try:
                loc = self.page.locator(sel).first
                if loc.is_visible(timeout=500):
                    return loc
            except Exception:
                continue
        return None

    def _input_to_field(self, el) -> FormField:
        return FormField(
            name=el.get_attribute("name") or "",
            field_type=el.get_attribute("type") or "text",
            element_id=el.get_attribute("id") or "",
            required=el.get_attribute("required") is not None,
            value=el.input_value() if el.get_attribute("type") != "file" else "",
        )

    def _select_to_field(self, el) -> FormField:
        options = []
        for opt in el.locator("option").all():
            val = opt.get_attribute("value") or ""
            text = (opt.inner_text() or "").strip()
            options.append(f"{val}={text}" if val != text else text)
        return FormField(
            name=el.get_attribute("name") or "",
            field_type="select",
            element_id=el.get_attribute("id") or "",
            options=options,
            value=el.input_value(),
        )

    def _screenshot(self, name: str) -> Path:
        path = SCREENSHOTS_DIR / f"{name}.png"
        if not DIAGNOSTIC_SCREENSHOTS_ENABLED:
            return path
        self.page.screenshot(path=str(path), full_page=True)
        return path

    def _page_info_to_dict(self, info: PageInfo) -> dict:
        return {
            "url": info.url,
            "title": info.title,
            "forms": [
                [
                    {
                        "name": f.name,
                        "type": f.field_type,
                        "id": f.element_id,
                        "label": f.label,
                        "required": f.required,
                        "options": f.options,
                        "value": f.value,
                    }
                    for f in form
                ]
                for form in info.forms
            ],
            "links": info.links[:50],   # cap to avoid huge output
            "buttons": info.buttons,
        }
