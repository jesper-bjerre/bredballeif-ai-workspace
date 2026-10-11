"""Read-only Conventus budget reports, including fresh headless sessions."""

from __future__ import annotations

import io
import json
import os
import re
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from playwright.sync_api import Error as BrowserError
from conventus_group_automation import CONVENTUS_BASE, ConventusGroupAutomation

ECONOMY_URL = f"{CONVENTUS_BASE}/login/economy.php"
BUDGET_URL = f"{ECONOMY_URL}?page=economy/budget/start.php&subheader=1"
TIMEZONE = "Europe/Copenhagen"


def current_time() -> datetime:
    try:
        return datetime.now(ZoneInfo(TIMEZONE))
    except ZoneInfoNotFoundError:
        raise ValueError("Tidszonedata mangler; installer skillens requirements (tzdata) i runtime-Python") from None


def normalized_name(value: str) -> str:
    """Ignore punctuation/spacing, but do not guess or change spelling."""
    return re.sub(r"[\W_]+", "", value.casefold())


def match_department(options: list[dict[str, str]], requested: str) -> dict[str, str]:
    key = normalized_name(requested)
    if key in {"", "all", "alle", "alleafdelinger", "total"}:
        raise ValueError("Angiv én konkret afdeling; opslag på alle afdelinger er ikke tilladt")
    candidates = [o for o in options if o["label"].strip() and o["value"] != "0"]
    exact = [o for o in candidates if normalized_name(o["label"]) == key]
    if not exact:
        names = [(o, normalized_name(re.sub(r"^\d+\s*:\s*\d+\.\s*", "", o["label"])))
                 for o in candidates]
        exact = [o for o, name in names if name == key]
        if not exact:
            exact = [o for o, name in names if key in name]
    if len(exact) != 1:
        labels = ", ".join(o["label"] for o in exact[:10]) or "ingen"
        raise ValueError(f"Afdelingen '{requested}' kunne ikke vælges entydigt. Match: {labels}")
    return exact[0]


@dataclass
class BudgetReportRequest:
    department: str
    year_count: int = 3
    year: int | None = None
    account: str = "Bredballe IF"

    def __post_init__(self) -> None:
        if not 1 <= self.year_count <= 3:
            raise ValueError("year_count skal være mellem 1 og 3")
        if normalized_name(self.department) in {"", "all", "alle", "alleafdelinger", "total"}:
            raise ValueError("Angiv én konkret afdeling; opslag på alle afdelinger er ikke tilladt")
        if self.year is not None and not 1900 <= self.year <= 2099:
            raise ValueError("Regnskabsår skal være mellem 1900 og 2099")
        if not self.account.strip():
            raise ValueError("Regnskabsnavnet må ikke være tomt")


class ConventusBudgetAutomation(ConventusGroupAutomation):
    """Select report context; never edit budgets, accounts or transactions."""

    def _open(self, section: str) -> None:
        self.page.goto(f"{ECONOMY_URL}?page=economy/{section}/start.php", wait_until="networkidle")

    def _select_context(self, request: BudgetReportRequest, year: int) -> None:
        # Direct budget navigation in a fresh session leaves regnskab_id empty.
        self._report_stage = "regnskabsvalg"
        self._open("regnskaber")
        overlay = self.page.locator("#olwin1")
        if overlay.is_visible():
            # Dismiss the failed account-picker popup, then use the normal list.
            overlay.locator("td[onclick]").first.click()
        buttons = self.page.get_by_role("button", name="Vælg", exact=True)
        entries = buttons.evaluate_all("""buttons => buttons.map((button, index) => ({
            index, cells: [...button.closest('tr').querySelectorAll(':scope > td')]
                .map(cell => (cell.innerText || '').trim())
        }))""")
        matches = [e for e in entries if any(
            normalized_name(cell) == normalized_name(request.account) for cell in e["cells"]
        )]
        if len(matches) != 1:
            raise RuntimeError(f"Regnskabet '{request.account}' kunne ikke vælges entydigt")
        button = buttons.nth(matches[0]["index"])
        if button.is_enabled():
            with self.page.expect_navigation(wait_until="networkidle"):
                button.click()
        self._report_stage = "valg af regnskabsår"
        self._open("regnskabsaar")
        buttons = self.page.get_by_role("button", name="Vælg", exact=True)
        entries = buttons.evaluate_all("""buttons => buttons.map((button, index) => ({
            index, cells: [...button.closest('tr').querySelectorAll(':scope > td')]
                .map(cell => (cell.innerText || '').trim())
        }))""")
        matches = [e for e in entries if str(year) in e["cells"]]
        if len(matches) != 1:
            raise RuntimeError(f"Regnskabsår {year} findes ikke entydigt i det valgte regnskab")
        button = buttons.nth(matches[0]["index"])
        if button.is_enabled():
            with self.page.expect_navigation(wait_until="networkidle"):
                button.click()

    def fetch_report(self, request: BudgetReportRequest) -> dict[str, Any]:
        now = current_time()
        year = request.year if request.year is not None else now.year
        self._select_context(request, year)
        self._report_stage = "indlæsning af rapportkontroller"
        page = self.page
        page.goto(BUDGET_URL, wait_until="networkidle")
        # Wait for report controls, not the visibility of a popup form.
        page.wait_for_function("""() => {
            const frame = document.querySelector('iframe[name="regnskab"]');
            return !!frame?.contentDocument?.querySelector('form[name="accountform"]');
        }""", timeout=20_000)
        frame = page.frame(name="regnskab")
        if frame is None:
            raise RuntimeError("Regnskabsrammen blev ikke indlæst")
        form = frame.locator('form[name="accountform"]')
        comparison_years = form.evaluate(r"""(form, params) => {
            const candidates = [...form.querySelectorAll('input[type="checkbox"]')].map(checkbox => {
                const text = checkbox.closest('tr')?.innerText || '';
                const years = [...text.matchAll(/\b(?:19|20)\d{2}\b/g)].map(m => Number(m[0]));
                return years.length ? {checkbox, year: Math.max(...years)} : null;
            }).filter(Boolean);
            candidates.sort((a,b) => b.year-a.year);
            const chosen = candidates.filter(item => item.year < params.year).slice(0,params.count);
            for (const item of candidates) item.checkbox.checked = false;
            for (const item of chosen) {
                item.checkbox.checked = true;
                item.checkbox.dispatchEvent(new Event('change', {bubbles:true}));
            }
            return chosen.map(item => item.year);
        }""", {"year": year, "count": request.year_count - 1})
        page.wait_for_function("""() => [...document.querySelectorAll(
            'select[name="soeg_afdelinger"] option'
        )].some(option => option.value !== '0' && option.textContent.trim())""", timeout=20_000)
        department_select = page.locator('select[name="soeg_afdelinger"]')
        options = department_select.locator("option").evaluate_all(
            "options => options.map(o => ({value:o.value,label:o.textContent.trim()}))"
        )
        self._report_stage = "afdelingsvalg og rapportvisning"
        department = match_department(options, request.department)
        department_select.select_option(value=department["value"])
        with page.expect_navigation(wait_until="networkidle"):
            page.get_by_role("button", name="Vis", exact=True).click()
        query = parse_qs(urlsplit(page.url).query)
        if query.get("afdeling") != [department["value"]]:
            raise RuntimeError("Rapportens afdelingsfilter kunne ikke verificeres")
        if department_select.input_value() != department["value"]:
            raise RuntimeError("Rapporten viser en anden afdeling end den bestilte")
        # Exclude navigation, duplicate parent tables, selectors and balance accounts.
        tables = page.locator("table").evaluate_all(r"""tables => tables
            .filter(table => !table.querySelector('table'))
            .map(table => [...table.querySelectorAll('tr')].map(tr =>
                [...tr.querySelectorAll(':scope > th, :scope > td')].map(cell =>
                    (cell.innerText || '').replace(/\s+/g,' ').trim()
                )).filter(row => row.some(Boolean)))
            .filter(rows => rows.some(row => row.includes('Resultatopgørelse')))
            .map(rows => {
                const first = rows.findIndex(row => row.includes('Resultatopgørelse'));
                const balance = rows.findIndex((row,index) => index>first && row.includes('Balance'));
                return rows.slice(Math.max(0,first-1),balance<0 ? rows.length : balance);
            })""")
        if len(tables) != 1:
            raise RuntimeError("Resultatopgørelsens tabel blev ikke fundet entydigt efter 'Vis'")
        headers = tables[0][0]
        actual_years = sorted({int(cell) for cell in headers if re.fullmatch(r"(?:19|20)\d{2}",cell)},reverse=True)
        if year not in actual_years or actual_years != sorted([year,*comparison_years],reverse=True):
            raise RuntimeError("Rapportens regnskabsår matcher ikke de valgte år")
        has_budget = any(normalized_name(cell) == f"{year}budget" for cell in headers)
        warnings = [
            "Budgetkolonnen er helårsbudget, ikke periodebudget.",
            "Bogføringens skæringsdato og ajourføring er ikke verificeret; udtræksdato er ikke skæringsdato.",
        ]
        if len(actual_years) < request.year_count:
            warnings.append("Færre historiske regnskabsår er tilgængelige end bestilt.")
        if not has_budget:
            warnings.append(f"Rapporten indeholder ikke en budgetkolonne for {year}.")
        return {
            "source": "Conventus", "report": "resultatopgoerelse",
            "account": request.account, "department": department["label"],
            "year": year, "years": actual_years, "comparison_years": comparison_years,
            "retrieved_at": current_time().isoformat(timespec="seconds"),
            "period": {"from": f"{year}-01-01", "to": f"{year}-12-31",
                       "bookkeeping_cutoff": None, "budget_basis": "full_year"},
            "has_budget": has_budget, "tables": tables, "warnings": warnings,
        }


def fetch_budget_report(department: str, year_count: int = 3, headless: bool = True,
                        year: int | None = None, account: str = "Bredballe IF") -> dict[str, Any]:
    """Return report data without login/debug output contaminating JSON."""
    request = BudgetReportRequest(department, year_count, year, account)
    current_time()  # Check runtime dependencies before launching/login.
    if not os.getenv("CONVENTUS_USERNAME") or not os.getenv("CONVENTUS_PASSWORD"):
        raise ValueError("CONVENTUS_USERNAME og CONVENTUS_PASSWORD skal sættes i runtime-miljøet")
    automation = ConventusBudgetAutomation(headless=headless)
    automation._report_stage = "browserstart"
    try:
        # The shared login helper prints debugging. Do not expose that output.
        with redirect_stdout(io.StringIO()):
            automation.start()
            automation._report_stage = "login"
            if not automation.login():
                raise RuntimeError("Login til Conventus fejlede")
            return automation.fetch_report(request)
    except BrowserError as exc:
        if "Executable doesn't exist" in str(exc):
            raise RuntimeError(
                "Playwright Chromium mangler i runtime-miljøet. Kør Python-miljøets "
                "'python -m playwright install chromium' som OpenClaw-brugeren."
            ) from None
        raise RuntimeError(
            f"Conventus-budgetudtrækket fejlede under {automation._report_stage} "
            f"({type(exc).__name__}). "
            "Kontrollér login/adgang, regnskabsvalg og installation af Playwright Chromium. "
            "Brug headless på OpenClaw; en X-server er ikke nødvendig."
        ) from None
    finally:
        automation.stop()


def print_report(report: dict[str, Any]) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2))
