"""
HalBooking browser automation – read-only court availability.

This module drives a real browser session against the Bredballe HalBooking
site and does exactly one thing: log in and read which padel courts are free
on a given date. It never creates, edits, books or deletes anything.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
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


class HalBookingAutomation:
    """Read-only HalBooking session: login + court availability only."""

    PADEL_COURTS = ["SPORT 24", "Sydbank", "home Vejle"]

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
        # Auto-accept any JS dialogs (alert/confirm/beforeunload) so a stray
        # prompt can't block navigation.
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
        """Log in to the HalBooking site.

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

    # -- court availability (read-only) --------------------------------------
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

        # --- Navigate to the requested date ---
        # The #banedato field has NO onchange handler, so setting its value does
        # not reload the grid. The site only changes day through its nav buttons,
        # which call sende('admin_baner.asp', 'dagfrem'|'dagback'|'dd', ...). We
        # therefore read the currently loaded day and step forward/back until we
        # reach the requested date — the site's own proven navigation path.
        date_input = p.locator("#banedato").first
        if date_input.count() == 0:
            result["note"] = (
                "Kunne ikke finde datofeltet #banedato på admin_baner.asp. "
                "Se screenshots/baner_01_loaded.png."
            )
            return result

        try:
            target = datetime.strptime(date_str, "%d-%m-%Y").date()
        except ValueError:
            result["note"] = f"Ugyldig dato '{date_str}'. Brug DD-MM-YYYY."
            return result

        def _read_current():
            raw = (date_input.input_value() or "").strip()
            try:
                return datetime.strptime(raw, "%d-%m-%Y").date()
            except ValueError:
                return None

        current = _read_current()
        if current is None:
            # Reset to today, then retry reading the field.
            p.evaluate("() => { if (typeof sende==='function') "
                       "sende('admin_baner.asp','dd','','','',''); }")
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(1500)
            current = _read_current()
        if current is None:
            result["note"] = (
                "Kunne ikke aflæse den aktuelle dato i #banedato. "
                "Se screenshots/baner_01_loaded.png."
            )
            return result

        delta = (target - current).days
        if abs(delta) > 366:
            result["note"] = (
                f"Datoen {date_str} er for langt væk ({delta} dage fra den "
                "aktuelt viste dag)."
            )
            return result

        action = "dagfrem" if delta > 0 else "dagback"
        for _ in range(abs(delta)):
            p.evaluate(
                f"() => {{ if (typeof sende==='function') "
                f"sende('admin_baner.asp','{action}','','','',''); }}"
            )
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(900)

        landed = _read_current()
        self._screenshot("baner_02_date_set")
        if landed != target:
            result["note"] = (
                f"Kunne ikke navigere til {date_str} (endte på "
                f"'{landed.strftime('%d-%m-%Y') if landed else '?'}'). "
                "Se screenshots/baner_02_date_set.png."
            )
            return result

        # --- Extract the grid ---
        # The day view is a set of court columns (``.bane``) plus a separate
        # time gutter (``.banetid-XX`` labels). Court cells (``span.banefelt``)
        # carry NO time themselves — their position implies the time. Each
        # column is a top-to-bottom stack of 30-minute cells; a cell's pixel
        # height tells how many 30-minute slots it spans (40px ≈ 1, 82px ≈ 2).
        #   - free cell:   class ``btn_ledig`` (empty)
        #   - booked cell: class ``bane_greenbg``/``bane_redbg`` (+ booking name)
        # We read the first gutter time as the grid start and walk each column.
        grid = p.evaluate(
            r"""
            () => {
              const parseT = (s) => {
                const m = (s || '').match(/(\d{1,2})[:.](\d{2})/);
                return m ? (+m[1]) * 60 + (+m[2]) : null;
              };
              // Grid start = earliest time label in the gutter.
              let start = null;
              document.querySelectorAll('[class*="banetid-"]').forEach((el) => {
                if (el.children.length) return;
                const v = parseT(el.textContent);
                if (v != null && (start == null || v < start)) start = v;
              });
              const cols = [];
              document.querySelectorAll('.bane').forEach((col) => {
                const headEl = col.querySelector('.baneheadtxt');
                const header = headEl ? headEl.textContent.trim() : '';
                const cells = [];
                col.querySelectorAll('span.banefelt').forEach((f) => {
                  const cls = f.className || '';
                  const isLedig = cls.includes('btn_ledig');
                  const isBooked = cls.includes('bane_greenbg') ||
                                   cls.includes('bane_redbg') ||
                                   cls.includes('bane_yellowbg');
                  if (!isLedig && !isBooked) return;  // skip header/non-slot spans
                  let h = parseInt((f.style.height || '').replace('px', ''), 10);
                  if (!h) h = Math.round(f.getBoundingClientRect().height) || 40;
                  const label = (f.textContent || '').replace(/\s+/g, ' ').trim();
                  cells.push({ h, booked: isBooked || label.length > 0, label });
                });
                if (cells.length) cols.push({ header, cells });
              });
              return { start, cols };
            }
            """
        )

        start_min = grid.get("start")
        raw_cols = grid.get("cols") or []
        if start_min is None or not raw_cols:
            result["note"] = (
                "Kunne ikke læse bane-grid'et (ingen tid-kolonne eller bane-"
                "kolonner fundet). Layoutet kan have ændret sig. Se "
                "screenshots/baner_02_date_set.png."
            )
            return result

        result["courts"] = self._parse_court_columns(
            raw_cols, start_min, time_from=time_from, time_to=time_to
        )
        any_slots = any(c["slots"] for c in result["courts"])
        result["success"] = bool(result["courts"]) and any_slots
        if not any_slots:
            result["note"] = (
                "Grid fundet, men ingen tidsblokke kunne parses. Se "
                "screenshots/baner_02_date_set.png."
            )
        return result

    # -- court booking (write) -----------------------------------------------
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

        # Navigate to the requested date using sende() day-stepping
        try:
            from datetime import datetime
            target = datetime.strptime(date_str, "%d-%m-%Y").date()

            def _read_current():
                raw = (date_input.input_value() or "").strip()
                try:
                    return datetime.strptime(raw, "%d-%m-%Y").date()
                except ValueError:
                    return None

            current = _read_current()
            if current is None:
                p.evaluate("() => { if (typeof sende==='function') "
                           "sende('admin_baner.asp','dd','','','',''); }")
                p.wait_for_load_state("networkidle")
                p.wait_for_timeout(1500)
                current = _read_current()

            if current is not None:
                delta = (target - current).days
                action = "dagfrem" if delta > 0 else "dagback"
                for _ in range(abs(delta)):
                    p.evaluate(
                        f"() => {{ if (typeof sende==='function') "
                        f"sende('admin_baner.asp','{action}','','','',''); }}"
                    )
                    p.wait_for_load_state("networkidle")
                    p.wait_for_timeout(900)
        except Exception:
            pass

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

        # Step 3: set text FIRST so it's visible before any time-extension
        # buttons are clicked (order matters for visual feedback).
        if text:
            if self._fill_if_visible("#book_tekst", text):
                result["steps_completed"].append("3_text_set")

        # Build the multiretbooking value – the field HalBooking uses to
        # expand a booking across multiple consecutive 30-minute slots.
        # Format: DD-MM-YYYY;1;<court>;<start_time>;<end_time>;0;
        multi_ret = f"{date_str};1;{court};{start_time};{final_end};0;"

        # If duration > 30 min, click the HalBooking time-extension button
        # (genvis_straksknap('HH:MM')) instead of setting hidden fields
        # directly. HalBooking's "Godkend reservation" reads state set by
        # those buttons — raw hidden-field manipulation is ignored.
        if duration_minutes > 30:
            extend_btn = p.locator(f"[onclick*=\"genvis_straksknap('{final_end}')\"]").first
            if extend_btn.count() > 0:
                extend_btn.click()
                p.wait_for_timeout(600)
                self._screenshot("straks_03_time_extended")
                result["steps_completed"].append("3_time_extended")
            else:
                # Fallback: try setting hidden fields + dispatching events
                p.evaluate(
                    """(cfg) => {
                        const setAndNotify = (name, value) => {
                            const el = document.querySelector(`[name="${name}"]`);
                            if (!el) return;
                            el.value = value;
                            if (el.tagName === 'SELECT') {
                                for (const opt of el.options) {
                                    if (opt.value === value || opt.textContent.trim() === value) {
                                        el.selectedIndex = opt.index;
                                        break;
                                    }
                                }
                            }
                            el.dispatchEvent(new Event('input',  {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        };
                        setAndNotify('mf_tiltid',          cfg.toTime);
                        setAndNotify('mf_multiretbooking', cfg.multiRet);
                    }""",
                    {"toTime": final_end, "multiRet": multi_ret},
                )
                p.wait_for_timeout(400)
                self._screenshot("straks_03_fallback_hidden")
                result["steps_completed"].append("3_fallback_hidden")

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

    # -- multi-booking (admin_multi.asp) -------------------------------------

    def create_multi_booking(
        self,
        date_str: str,
        courts: list[int],
        start_time: str,
        duration_minutes: int,
        text: str = "",
    ) -> dict[str, Any]:
        """Create bookings via Multi-booking (admin_multi.asp).

        Multi-booking is the preferred method because it provides an access
        code (``adgangskode``) for the door lock.

        Flow:
        1. Navigate to admin_baner.asp, set date, click "Multi-booking".
        2. On admin_multi.asp, check the checkboxes for each 30-min slot
           for each requested court.
        3. Click "Opret bookinger" (id_btn_7).
        4. On the review page: fill text, read access code, click
           "Vis de valgte bookinger" (visknap).
        5. On the confirmation page: click "OK - Opret bookinger" (id_btn_3).
        """
        p = self.page
        result: dict[str, Any] = {
            "success": False,
            "date": date_str,
            "courts": courts,
            "start_time": start_time,
            "duration_minutes": duration_minutes,
            "text": text,
            "access_code": "",
            "steps_completed": [],
        }

        if not courts:
            result["note"] = "Ingen baner valgt."
            return result
        if duration_minutes <= 0 or duration_minutes % 30 != 0:
            result["note"] = "Varighed skal være et positivt multiplum af 30 minutter."
            return result

        # Calculate slot indices. Grid starts at 05:00, each row = 30 min.
        start_minutes = self._hhmm_to_minutes(start_time)
        if start_minutes is None:
            result["note"] = f"Ugyldig starttid: {start_time}"
            return result
        # Slot 0 = 05:00 (300 minutes)
        start_slot = (start_minutes - 300) // 30
        num_slots = duration_minutes // 30
        if start_slot < 0:
            result["note"] = "Starttidspunkt er før kl. 05:00."
            return result

        # --- Step 1: navigate to admin_baner.asp and set date ---
        p.goto(f"{self.base_url}/admin_baner.asp", wait_until="networkidle")
        p.wait_for_timeout(1500)
        self._navigate_date(date_str)
        self._screenshot("multi_01_date_set")
        result["steps_completed"].append("1_date_set")

        # --- Step 2: click Multi-booking ---
        # The Multi-booking button is a visible DIV with a specific onclick.
        # Using the onclick pattern is more reliable than text matching.
        multi_btn = p.locator("[onclick*=\"admin_multi.asp\"][onclick*=\"velg\"]").first
        if multi_btn.count() == 0:
            # Fallback: try visible div with exact text
            multi_btn = p.locator("div:visible:has-text('Multi-booking')").first
        if multi_btn.count() == 0:
            result["note"] = "Kunne ikke finde 'Multi-booking' knap."
            self._screenshot("multi_02_no_btn")
            return result
        multi_btn.click(force=True)
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(2500)
        if "admin_multi.asp" not in p.url:
            result["note"] = "Kom ikke til admin_multi.asp efter Multi-booking klik."
            return result
        self._screenshot("multi_02_grid")
        result["steps_completed"].append("2_multi_grid")

        # --- Step 3: check the relevant checkboxes (via JS to avoid viewport issues) ---
        court_prefixes = {1: "B1E", 2: "B2E", 3: "B3E"}
        cb_names = []
        for court in courts:
            prefix = court_prefixes.get(court)
            if not prefix:
                continue
            for slot_offset in range(num_slots):
                slot_idx = start_slot + slot_offset
                cb_names.append(f"{prefix}{slot_idx}")

        if not cb_names:
            result["note"] = "Ingen checkboxes at vælge."
            return result

        # Build JS to check all desired checkboxes at once
        checked_count = p.evaluate(f"""(names) => {{
            let count = 0;
            names.forEach(name => {{
                const cb = document.querySelector("input[name='" + name + "']");
                if (!cb) return;
                cb.checked = true;
                // Fire HalBooking's blocklick handler
                if (typeof blocklick === 'function' && cb.form) {{
                    const partner = cb.form[name];
                    if (partner) blocklick(cb, partner, '');
                }}
                // Also dispatch events for any other listeners
                cb.dispatchEvent(new Event('change', {{bubbles: true}}));
                cb.dispatchEvent(new Event('click', {{bubbles: true}}));
                if (typeof cb.onfocus === 'function') cb.onfocus();
                count++;
            }});
            return count;
        }}""", cb_names)

        if checked_count == 0:
            result["note"] = "Kunne ikke finde nogen ledige checkboxes for de valgte baner/tider."
            self._screenshot("multi_03_no_slots")
            return result

        p.wait_for_timeout(300)

        self._screenshot("multi_03_checked")
        result["steps_completed"].append("3_slots_checked")

        # --- Step 4: click "Opret bookinger" ---
        submit_btn = p.locator("#id_btn_7").first
        if submit_btn.count() == 0:
            result["note"] = "Kunne ikke finde 'Opret bookinger' knap (id_btn_7)."
            return result
        submit_btn.click()
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(2500)
        self._screenshot("multi_04_review")
        result["steps_completed"].append("4_on_review")

        # --- Step 5: set text, read access code, click "Vis de valgte bookinger" ---
        if text:
            booktekst = p.locator("#booktekst").first
            if booktekst.count() > 0:
                booktekst.fill(text)
                p.wait_for_timeout(300)

        # Read the access code
        access_input = p.locator("#n_adgangskode").first
        if access_input.count() > 0:
            result["access_code"] = (access_input.input_value() or "").strip()

        self._screenshot("multi_05_text_and_code")
        result["steps_completed"].append("5_text_and_code")

        # Click "Vis de valgte bookinger" (span#visknap)
        vis_btn = p.locator("#visknap").first
        if vis_btn.count() == 0:
            result["note"] = "Kunne ikke finde 'Vis de valgte bookinger' knap (visknap)."
            return result
        vis_btn.click()
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(2500)
        self._screenshot("multi_06_confirm")
        result["steps_completed"].append("6_on_confirm")

        # --- Step 6: click "OK - Opret bookinger" ---
        ok_btn = p.locator("#id_btn_3").first
        if ok_btn.count() == 0:
            ok_btn = p.locator("a:has-text('OK - Opret bookinger')").first
        if ok_btn.count() == 0:
            ok_btn = p.locator("span:has-text('OK - Opret bookinger')").first
        if ok_btn.count() == 0:
            result["note"] = "Kunne ikke finde 'OK - Opret bookinger' knap (id_btn_3)."
            return result
        ok_btn.click()
        p.wait_for_load_state("networkidle")
        p.wait_for_timeout(2500)
        self._screenshot("multi_07_done")
        result["steps_completed"].append("7_done")

        # Determine success
        body_text = p.inner_text("body").lower()
        success_markers = ["godkendt", "oprettet", "booking"]
        result["success"] = any(m in body_text for m in success_markers)
        if not result["success"]:
            result["success"] = any(
                x in p.url for x in ("admin_baner.asp", "admin_liste.asp")
            )
        result["final_url"] = p.url
        if not result["success"]:
            result["note"] = result.get("note") or "Kunne ikke bekræfte booking."

        return result

    def _navigate_date(self, date_str: str) -> None:
        """Navigate admin_baner.asp to *date_str* (DD-MM-YYYY) using sende()."""
        p = self.page
        target = datetime.strptime(date_str, "%d-%m-%Y").date()

        def _read_current():
            date_input = p.locator("#banedato").first
            raw = (date_input.input_value() or "").strip()
            try:
                return datetime.strptime(raw, "%d-%m-%Y").date()
            except ValueError:
                return None

        current = _read_current()
        if current is None:
            p.evaluate('() => { if (typeof sende==="function") sende("admin_baner.asp","dd","","","",""); }')
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(1500)
            current = _read_current()

        if current is not None and current != target:
            delta = (target - current).days
            action = "dagfrem" if delta > 0 else "dagback"
            for _ in range(abs(delta)):
                p.evaluate(f'() => {{ if (typeof sende==="function") sende("admin_baner.asp","{action}","","","",""); }}')
                p.wait_for_load_state("networkidle")
                p.wait_for_timeout(900)

    def _hhmm_to_minutes(self, hhmm: str) -> int | None:
        """Convert HH:MM to minutes since midnight, or None if invalid."""
        m = re.match(r"^(\d{1,2}):(\d{2})$", (hhmm or "").strip())
        if not m:
            return None
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return hour * 60 + minute

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

    def _find_first(self, selectors: list[str]) -> Any:
        """Return the first visible locator matching any of the selectors."""
        for sel in selectors:
            try:
                el = self.page.locator(sel).first
                if el.count() > 0:
                    return el
            except Exception:
                continue
        return None

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

    def _parse_court_columns(
        self,
        raw_cols: list[dict],
        start_min: int,
        time_from: str | None = None,
        time_to: str | None = None,
    ) -> list[dict[str, Any]]:
        """Turn raw column cell-stacks into structured per-court slots.

        Each cell spans ``round(height / 42)`` 30-minute slots starting at
        ``start_min``. Cells are classified ``free`` or ``booked`` and,
        optionally, filtered to the ``time_from``/``time_to`` window (kept when
        the slot overlaps the window at all).
        """
        time_re = re.compile(r"(\d{1,2})[.:](\d{2})")

        def to_minutes(hhmm: str | None) -> int | None:
            if not hhmm:
                return None
            m = time_re.search(hhmm)
            if not m:
                return None
            return int(m.group(1)) * 60 + int(m.group(2))

        def fmt(minutes: int) -> str:
            minutes %= 24 * 60
            return f"{minutes // 60:02d}:{minutes % 60:02d}"

        lo = to_minutes(time_from)
        hi = to_minutes(time_to)

        courts: list[dict[str, Any]] = []
        for idx, col in enumerate(raw_cols):
            name = (col.get("header") or "").strip() or (
                self.PADEL_COURTS[idx]
                if idx < len(self.PADEL_COURTS)
                else f"Bane {idx + 1}"
            )
            slots: list[dict[str, Any]] = []
            cursor = start_min
            for cell in col.get("cells", []):
                height = cell.get("h") or 40
                n_slots = max(1, int(height / 42 + 0.5))
                s_start = cursor
                s_end = cursor + n_slots * 30
                cursor = s_end

                # Keep the slot when it overlaps the requested window (if any).
                if lo is not None and s_end <= lo:
                    continue
                if hi is not None and s_start >= hi:
                    continue

                slots.append({
                    "time": fmt(s_start),
                    "end": fmt(s_end),
                    "status": "booked" if cell.get("booked") else "free",
                    "label": cell.get("label", ""),
                })

            courts.append({
                "bane": idx + 1,
                "name": name,
                "slots": slots,
                "free": [s["time"] for s in slots if s["status"] == "free"],
                "booked": [s["time"] for s in slots if s["status"] == "booked"],
            })
        return courts

    # -- helpers -------------------------------------------------------------
    def _screenshot(self, name: str) -> Path:
        path = SCREENSHOTS_DIR / f"{name}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True)
        except Exception:
            pass
        return path
