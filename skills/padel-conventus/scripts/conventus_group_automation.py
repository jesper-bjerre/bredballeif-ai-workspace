"""
Conventus Group Automation — Playwright-based browser automation for
creating and configuring groups (events/træningshold) in Conventus.

Handles:
  - Login to Conventus
  - Creating a group via grp_add_action.php
  - Editing group details (max participants, description, price, visibility, etc.)

No official API exists for group creation — this is deterministic browser automation.
"""

from __future__ import annotations

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
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# Conventus department IDs
AFDELING_PADEL = "55804"

# Conventus URLs
CONVENTUS_BASE = "https://www.conventus.dk"
LOGIN_URL = f"{CONVENTUS_BASE}/login/index.php"
LOGGEDIN_BASE = f"{CONVENTUS_BASE}/login/loggedin.php"


def _to_date_input_format(date_str: str) -> str:
    """Convert DD-MM-YYYY to YYYY-MM-DD for HTML <input type='date'> fields.
    Returns the input unchanged if it's already in YYYY-MM-DD format.
    """
    if not date_str:
        return date_str
    # Already ISO format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str
    # Convert DD-MM-YYYY to YYYY-MM-DD
    m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", date_str)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return date_str


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class GroupConfig:
    """Configuration for creating a Conventus group."""
    title: str                          # e.g. "Americano Herrer den 7. juli kl. 19:00-21:00"
    date_from: str                      # dd-mm-yyyy
    date_to: str                        # dd-mm-yyyy (usually same as date_from for single-day)
    department_id: str = AFDELING_PADEL
    activity_id: str = "371"            # default activity ID for Padel
    group_type: str = "1"              # 1 = event/aktivitet
    max_participants: int = 12
    description: str = ""
    price: str = ""
    public: bool = True
    waiting_list: bool = True           # "ot" checkbox — tillad overskydende tilmeldinger
    payment_required: bool = True       # "betaling" checkbox — kræv betaling


@dataclass
class GroupResult:
    """Result from group creation."""
    success: bool
    group_id: str = ""
    edit_url: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Conventus Group Automation class
# ---------------------------------------------------------------------------
class ConventusGroupAutomation:
    """Drives a real browser session against the Conventus admin site."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        headless: bool = True,
    ) -> None:
        self._username = username or os.getenv("CONVENTUS_USERNAME", "")
        self._password = password or os.getenv("CONVENTUS_PASSWORD", "")
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
        # Auto-accept any JS dialogs (alert/confirm)
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

    # -- helpers -------------------------------------------------------------
    def _screenshot(self, name: str) -> str:
        """Take a screenshot for debugging. Returns the file path."""
        path = SCREENSHOTS_DIR / f"conventus_{name}.png"
        try:
            self.page.screenshot(path=str(path), full_page=False)
        except Exception:
            pass  # screenshot is best-effort
        return str(path)

    def _wait_for_stable(self, ms: int = 1500) -> None:
        """Wait for network idle + extra settling time."""
        try:
            self.page.wait_for_load_state("networkidle")
        except Exception:
            pass
        self.page.wait_for_timeout(ms)

    # -- login ---------------------------------------------------------------
    def login(self) -> bool:
        """Log in to Conventus.

        Navigates to the login page, fills brugernavn/password fields,
        clicks "Log ind", and verifies success.
        """
        p = self.page

        if not self._username or not self._password:
            print("[!] CONVENTUS_USERNAME and CONVENTUS_PASSWORD must be set (env or .env)")
            return False

        # Navigate to login page
        p.goto(LOGIN_URL, wait_until="networkidle")
        self._wait_for_stable(1000)
        self._screenshot("01_login_page")

        # Fill credentials
        user_field = p.locator('input[name="brugernavn"]')
        pass_field = p.locator('input[name="password"]')

        if not user_field.is_visible(timeout=5000):
            # Maybe already logged in?
            content = p.content()
            if "loggedin.php" in content or "logud" in content.lower():
                print("[+] Already logged in to Conventus")
                return True
            self._screenshot("01_login_fields_missing")
            print("[!] Could not locate login fields")
            return False

        user_field.fill(self._username)
        pass_field.fill(self._password)
        self._screenshot("02_credentials_filled")

        # Click "Log ind" button
        login_btn = p.locator('button.btn-success, input[type="submit"].btn-success')
        # Also try more specific selectors
        if not login_btn.is_visible():
            login_btn = p.locator('button:has-text("Log ind")')
        if not login_btn.is_visible():
            login_btn = p.locator('input[type="submit"]')

        login_btn.click()
        self._wait_for_stable(3000)
        self._screenshot("03_after_login")
        self._debug_page_state("after_login")

        # Handle "Husk mig" (remember me) intermediate page
        # Conventus redirects to before_login/husk_mig.php after successful login
        if "husk_mig" in p.url:
            print("[*] On 'Husk mig' page — handling device registration")
            # First click "Hav tillid til denne enhed" to reveal device name field
            trust_btn = p.locator('button:has-text("Hav tillid")')
            if trust_btn.is_visible(timeout=3000):
                trust_btn.click()
                print("[*] Clicked 'Hav tillid til denne enhed'")
                p.wait_for_timeout(500)

            # Fill device name
            device_field = p.locator('input[name="enhedens_navn"]')
            if device_field.is_visible(timeout=3000):
                device_field.fill("BIF Automation")
                print("[*] Filled device name")

            # Submit the form directly via JavaScript to avoid visibility issues
            try:
                p.evaluate("document.getElementById('husk_mig')?.submit()")
                print("[*] Submitted husk_mig form via JS")
            except Exception:
                # Fallback: try clicking Gem button
                gem_btn = p.locator('button:has-text("Gem")')
                if gem_btn.is_visible(timeout=2000):
                    gem_btn.click()
                    print("[*] Clicked 'Gem' on Husk-mig page")
                else:
                    # Force click even if not visible
                    gem_btn.click(force=True)
                    print("[*] Force-clicked 'Gem' on Husk-mig page")

            self._wait_for_stable(3000)
            self._screenshot("03b_after_husk_mig")
            self._debug_page_state("after_husk_mig")

        # Verify success — look for logged-in indicators
        content = p.content().lower()
        if "logud" in content or "loggedin" in p.url:
            print("[+] Conventus login successful")
            return True

        # If we're now on a loggedin page, we're good
        if "loggedin" in p.url:
            print("[+] Conventus login successful (redirected to loggedin)")
            return True

        # Still on husk_mig or similar — try navigating directly to loggedin
        if "husk_mig" in p.url or "before_login" in p.url:
            print("[*] Still on pre-login page — trying direct navigation to test login")
            p.goto(LOGGEDIN_BASE, wait_until="networkidle")
            self._wait_for_stable(2000)
            self._debug_page_state("after_direct_goto")
            if "loggedin" in p.url or "logud" in p.content().lower():
                print("[+] Login verified via direct navigation")
                return True

        # Check for error messages
        if "forkert" in content or "fejl" in content:
            print("[!] Login failed — wrong credentials")
            return False

        print("[!] Login status unclear — proceeding anyway")
        return True

    def _debug_page_state(self, label: str) -> None:
        """Print debug info about the current page to help diagnose issues."""
        p = self.page
        print(f"[D] {label} — URL: {p.url[:120]}")
        print(f"[D] {label} — Title: {p.title()[:80]}")

        # Check for iframes
        frames = p.frames
        print(f"[D] {label} — Frames: {len(frames)}")
        for i, frame in enumerate(frames):
            print(f"[D]   Frame {i}: url={frame.url[:100]}")

        # List all input fields on the page (main frame)
        try:
            inputs = p.locator("input").all()
            print(f"[D] {label} — Input fields on page: {len(inputs)}")
            for inp in inputs[:15]:  # limit output
                name = inp.get_attribute("name") or ""
                inp_id = inp.get_attribute("id") or ""
                inp_type = inp.get_attribute("type") or ""
                if name or inp_id:
                    print(f"[D]   input name='{name}' id='{inp_id}' type='{inp_type}'")
        except Exception as e:
            print(f"[D] Could not enumerate inputs: {e}")

        # Check page content snippet for key indicators
        try:
            content = p.content()
            if "grp_add" in content:
                print(f"[D] Page contains 'grp_add' — group creation form expected")
            if "titel" in content:
                print(f"[D] Page contains 'titel' — title field exists in HTML")
            if "periode_fra" in content:
                print(f"[D] Page contains 'periode_fra' — date field exists in HTML")
            if "logud" in content.lower():
                print(f"[D] Page contains 'logud' — user IS logged in")
            elif "loggedin" in content:
                print(f"[D] Page contains 'loggedin'")
            if "Log ind" in content or "brugernavn" in content:
                print(f"[D] Page contains login form — user may NOT be logged in")
        except Exception:
            pass

    def _find_input_in_any_frame(self, name: str, timeout: float = 5000) -> "Locator | None":
        """Search for an input[name=X] in the main page and all iframes."""
        from playwright.sync_api import Locator, TimeoutError as PlaywrightTimeout

        p = self.page

        # Try main frame first
        try:
            loc = p.locator(f'input[name="{name}"]')
            if loc.is_visible(timeout=min(timeout, 2000)):
                return loc
        except PlaywrightTimeout:
            pass

        # Try each iframe
        for frame in p.frames:
            if frame == p.main_frame:
                continue
            try:
                loc = frame.locator(f'input[name="{name}"]')
                if loc.is_visible(timeout=min(timeout, 2000)):
                    print(f"[D] Found '{name}' in iframe: {frame.url[:80]}")
                    return loc
            except PlaywrightTimeout:
                continue

        return None

    # -- group creation ------------------------------------------------------
    def create_group(self, config: GroupConfig) -> GroupResult:
        """Create a new group in Conventus via the grp_add.php page.

        Steps:
        1. Navigate to grp_add.php?page=adressebog/medlemmer/grp_add.php&idv1=DEPT_ID
        2. Fill in title, date range
        3. Click "Gem" then "Ja" (confirm)
        4. Extract the new group ID from the redirect
        """
        p = self.page

        add_url = f"{LOGGEDIN_BASE}?page=adressebog/medlemmer/grp_add.php&idv1={config.department_id}"
        print(f"[*] Navigating to group creation: {add_url}")
        p.goto(add_url, wait_until="networkidle")
        self._wait_for_stable(2000)
        self._screenshot("04_group_add_form")
        self._debug_page_state("group_add")

        # Fill title — search in main page and iframes
        title_field = self._find_input_in_any_frame("titel")
        if title_field is None:
            # Try alternative: the field might have id="titel" instead of name="titel"
            try:
                title_field = p.locator('#titel, input[name="titel"]')
                title_field.wait_for(state="visible", timeout=3000)
            except Exception:
                pass

        if title_field is None:
            self._screenshot("04b_title_field_missing")
            return GroupResult(
                success=False,
                error="Could not find 'titel' field on group creation page — check screenshots",
            )

        title_field.fill(config.title)
        print(f"[*] Filled title: {config.title}")

        # Convert DD-MM-YYYY to YYYY-MM-DD for HTML date inputs
        date_from_iso = _to_date_input_format(config.date_from)
        date_to_iso = _to_date_input_format(config.date_to)

        # Fill date from
        date_from_field = self._find_input_in_any_frame("periode_fra")
        if date_from_field is None:
            try:
                date_from_field = p.locator('#periode_fra, input[name="periode_fra"]')
                date_from_field.wait_for(state="visible", timeout=2000)
            except Exception:
                pass
        if date_from_field:
            date_from_field.fill(date_from_iso)
            print(f"[*] Filled periode_fra: {date_from_iso}")
        else:
            print("[!] Could not find periode_fra field")

        # Fill date to
        date_to_field = self._find_input_in_any_frame("periode_til")
        if date_to_field is None:
            try:
                date_to_field = p.locator('#periode_til, input[name="periode_til"]')
                date_to_field.wait_for(state="visible", timeout=2000)
            except Exception:
                pass
        if date_to_field:
            date_to_field.fill(date_to_iso)
            print(f"[*] Filled periode_til: {date_to_iso}")
        else:
            print("[!] Could not find periode_til field")

        self._screenshot("05_form_filled")

        # Click "Gem" button
        save_btn = p.locator('button:has-text("Gem"), input[value="Gem"], button[name="gem"]').first
        if save_btn.is_visible():
            save_btn.click()
            print("[*] Clicked 'Gem'")
        else:
            return GroupResult(success=False, error="Could not find 'Gem' button")

        # Wait for confirm dialog or redirect
        self._wait_for_stable(2000)
        self._screenshot("06_after_save")

        # Handle "Ja" confirmation button if present
        # Conventus shows a confirmation page after submitting grp_add
        ja_btn = p.locator('button:has-text("Ja"), input[value="Ja"], a:has-text("Ja")')
        if ja_btn.is_visible(timeout=3000):
            ja_btn.first.click()
            print("[*] Clicked 'Ja' confirmation")
            self._wait_for_stable(2000)
            self._screenshot("07_after_confirm")

        # Extract group ID from URL or page content
        group_id = self._extract_group_id()
        if group_id:
            print(f"[+] Group created with ID: {group_id}")
            return GroupResult(
                success=True,
                group_id=group_id,
                edit_url=f"{LOGGEDIN_BASE}?page=adressebog/medlemmer/grp_edit.php&idv1={group_id}",
            )

        # Try to find group ID in the page content
        self._screenshot("08_missing_group_id")
        return GroupResult(
            success=True,
            error="Group likely created but could not extract ID from page",
        )

    def _extract_group_id(self) -> str:
        """Try to extract the newly created group ID from the current page.

        Looks for patterns like:
        - URL: grp_edit.php?idv1=1050009
        - Page content links to the group
        """
        p = self.page

        # Try URL first
        url = p.url
        m = re.search(r"idv1=(\d+)", url)
        if m and m.group(1) != AFDELING_PADEL:
            return m.group(1)

        # Try page content — look for grp_edit.php links
        content = p.content()
        m = re.search(r"grp_edit\.php\?[^\"']*idv1=(\d+)", content)
        if m:
            gid = m.group(1)
            if gid != AFDELING_PADEL:
                return gid

        # Try to find a newly added group link in redirect page
        # Conventus often redirects to the group list after creation
        links = p.locator('a[href*="grp_edit.php"]').all()
        if links:
            for link in links:
                href = link.get_attribute("href") or ""
                m = re.search(r"idv1=(\d+)", href)
                if m and m.group(1) != AFDELING_PADEL:
                    return m.group(1)

        return ""

    # -- group editing -------------------------------------------------------
    def edit_group(self, group_id: str, config: GroupConfig) -> bool:
        """Edit an existing group with additional settings.

        Navigates to grp_edit.php and fills in:
        - max participants
        - description
        - price
        - visibility (offentlig)
        - waiting list (ot)
        - payment required (betaling)
        """
        p = self.page
        edit_url = f"{LOGGEDIN_BASE}?page=adressebog/medlemmer/grp_edit.php&idv1={group_id}"
        print(f"[*] Navigating to group edit: {edit_url}")
        p.goto(edit_url, wait_until="networkidle")
        self._wait_for_stable(1000)
        self._screenshot("09_group_edit_page")

        # Fill max participants
        if config.max_participants > 0:
            max_field = p.locator('input[name="maxdeltagere"]')
            if max_field.is_visible(timeout=3000):
                max_field.fill(str(config.max_participants))
                print(f"[*] Max participants set to: {config.max_participants}")
            else:
                print("[!] Could not find maxdeltagere field")

        # Fill description
        if config.description:
            desc_field = p.locator('textarea[name="om_gruppen"]')
            if desc_field.is_visible(timeout=3000):
                desc_field.fill(config.description)
                print(f"[*] Description set")
            else:
                print("[!] Could not find om_gruppen field")

        # Fill price
        if config.price:
            price_field = p.locator('input[name="kontingent"]')
            if price_field.is_visible(timeout=3000):
                price_field.fill(config.price)
                print(f"[*] Price set to: {config.price}")
            else:
                print("[!] Could not find kontingent field")

        # Set visibility (offentlig = "Ja")
        public_select = p.locator('select[name="offentlig"]')
        if public_select.is_visible(timeout=3000):
            public_select.select_option("Ja" if config.public else "Nej")
            print(f"[*] Public visibility set to: {'Ja' if config.public else 'Nej'}")
        else:
            print("[!] Could not find offentlig select")

        # Check "Tillad overskydende tilmeldinger" (ot)
        ot_checkbox = p.locator('input[name="ot"]')
        if ot_checkbox.is_visible(timeout=3000):
            is_checked = ot_checkbox.is_checked()
            if config.waiting_list and not is_checked:
                ot_checkbox.check()
                print("[*] Checked 'Tillad overskydende tilmeldinger' (ot)")
            elif not config.waiting_list and is_checked:
                ot_checkbox.uncheck()
                print("[*] Unchecked 'Tillad overskydende tilmeldinger' (ot)")

        # Check "Kræv betaling" (betaling)
        betaling_checkbox = p.locator('input[name="betaling"]')
        if betaling_checkbox.is_visible(timeout=3000):
            is_checked = betaling_checkbox.is_checked()
            if config.payment_required and not is_checked:
                betaling_checkbox.check()
                print("[*] Checked 'Kræv betaling' (betaling)")
            elif not config.payment_required and is_checked:
                betaling_checkbox.uncheck()
                print("[*] Unchecked 'Kræv betaling' (betaling)")

        self._screenshot("10_edit_form_filled")

        # Click "Gem" to save
        save_btn = p.locator('button:has-text("Gem"), input[value="Gem"]').first
        if save_btn.is_visible():
            save_btn.click()
            print("[*] Clicked 'Gem' to save edits")
        else:
            print("[!] Could not find Save button on edit page")
            return False

        self._wait_for_stable(2000)
        self._screenshot("11_edits_saved")
        print("[+] Group edit completed")
        return True


# ---------------------------------------------------------------------------
# High-level convenience functions
# ---------------------------------------------------------------------------
def create_americano(
    title: str,
    date: str,
    max_participants: int = 12,
    description: str = "",
    price: str = "",
    headless: bool = True,
) -> GroupResult:
    """Create an Americano event group in Conventus.

    Args:
        title: Event title, e.g. "Americano Herrer den 7. juli kl. 19:00-21:00"
        date: Date in dd-mm-yyyy format, e.g. "07-07-2026"
        max_participants: Maximum number of participants (default 12 for Americano)
        description: Event description text
        price: Event price, e.g. "50"
        headless: Run browser in headless mode

    Returns:
        GroupResult with success status and group ID
    """
    config = GroupConfig(
        title=title,
        date_from=date,
        date_to=date,
        max_participants=max_participants,
        description=description,
        price=price,
        public=True,
        waiting_list=True,
        payment_required=True,
    )

    auto = ConventusGroupAutomation(headless=headless)
    try:
        auto.start()

        # Login
        if not auto.login():
            return GroupResult(success=False, error="Login failed")

        # Create the group
        result = auto.create_group(config)
        if not result.success:
            return result

        # Edit the group with additional settings
        if result.group_id:
            auto.edit_group(result.group_id, config)
        else:
            print("[!] No group ID found — skipping edit step. Manual edit may be needed.")

        return result
    except Exception as e:
        return GroupResult(success=False, error=str(e))
    finally:
        auto.stop()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def _parse_args() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        description="Conventus group automation — create events/groups via browser automation"
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_americano = sub.add_parser("create-americano", help="Create an Americano event")
    p_americano.add_argument("--title", required=True, help="Event title")
    p_americano.add_argument("--date", required=True, help="Date (dd-mm-yyyy)")
    p_americano.add_argument("--max", type=int, default=12, help="Max participants (default: 12)")
    p_americano.add_argument("--description", default="", help="Event description")
    p_americano.add_argument("--price", default="", help="Price (e.g. 50)")
    p_americano.add_argument(
        "--no-headless", action="store_true", help="Show browser window (for debugging)"
    )

    p_create = sub.add_parser("create-group", help="Create a generic group with full config")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--date-from", required=True)
    p_create.add_argument("--date-to", default="")
    p_create.add_argument("--department", default=AFDELING_PADEL)
    p_create.add_argument("--activity", default="371")
    p_create.add_argument("--max", type=int, default=0)
    p_create.add_argument("--description", default="")
    p_create.add_argument("--price", default="")
    p_create.add_argument("--no-public", action="store_true")
    p_create.add_argument("--no-waiting-list", action="store_true")
    p_create.add_argument("--no-payment", action="store_true")
    p_create.add_argument("--no-headless", action="store_true")

    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.action == "create-americano":
        result = create_americano(
            title=args.title,
            date=args.date,
            max_participants=args.max,
            description=args.description,
            price=args.price,
            headless=not args.no_headless,
        )
        if result.success:
            print(f"\n✅ Americano oprettet!")
            print(f"   Gruppe ID: {result.group_id}")
            print(f"   Edit URL:  {result.edit_url}")
        else:
            print(f"\n❌ Fejl: {result.error}")
            sys.exit(1)

    elif args.action == "create-group":
        config = GroupConfig(
            title=args.title,
            date_from=args.date_from,
            date_to=args.date_to or args.date_from,
            department_id=args.department,
            activity_id=args.activity,
            max_participants=args.max,
            description=args.description,
            price=args.price,
            public=not args.no_public,
            waiting_list=not args.no_waiting_list,
            payment_required=not args.no_payment,
        )

        auto = ConventusGroupAutomation(headless=not args.no_headless)
        try:
            auto.start()
            if not auto.login():
                print("❌ Login fejlede")
                sys.exit(1)
            result = auto.create_group(config)
            if result.success and result.group_id:
                auto.edit_group(result.group_id, config)
            if result.success:
                print(f"\n✅ Gruppe oprettet! ID: {result.group_id}")
                print(f"   Edit URL: {result.edit_url}")
            else:
                print(f"\n❌ Fejl: {result.error}")
                sys.exit(1)
        finally:
            auto.stop()


if __name__ == "__main__":
    import sys
    main()
