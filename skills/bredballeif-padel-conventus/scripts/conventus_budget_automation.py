"""Read-only extraction of Conventus income statements via browser automation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from conventus_group_automation import CONVENTUS_BASE, ConventusGroupAutomation


BUDGET_URL = (
    f"{CONVENTUS_BASE}/login/economy.php?"
    "page=economy/budget/start.php&subheader=1"
)
PADEL_DEPARTMENT_LABEL = "60: 116. Padel"


@dataclass
class BudgetReportRequest:
    """Parameters for a read-only Conventus income statement."""

    department: str = ""
    year_count: int = 3


class ConventusBudgetAutomation(ConventusGroupAutomation):
    """Fetch income-statement tables without changing Conventus data."""

    def fetch_report(self, request: BudgetReportRequest) -> dict[str, Any]:
        if request.year_count < 1:
            raise ValueError("year_count skal være mindst 1")

        page = self.page
        page.goto(BUDGET_URL, wait_until="networkidle")
        self._wait_for_stable(1000)

        form = None
        report_frame = None
        for frame in page.frames:
            candidate = frame.locator('form[name="accountform"]').first
            try:
                if candidate.is_visible(timeout=3_000):
                    form = candidate
                    report_frame = frame
                    break
            except Exception:
                continue
        if form is None or report_frame is None:
            raise RuntimeError("Formularen accountform blev ikke fundet på Conventus-økonomisiden")

        selected_years = form.evaluate(
            r"""(form, yearCount) => {
                const candidates = [...form.querySelectorAll('table tr')].map((row, index) => {
                    const checkbox = row.querySelector('input[type="checkbox"]');
                    const text = (row.innerText || '').replace(/\s+/g, ' ').trim();
                    const years = [...text.matchAll(/(?:19|20)\d{2}/g)].map(m => Number(m[0]));
                    return checkbox && years.length
                        ? { checkbox, year: Math.max(...years), index }
                        : null;
                }).filter(Boolean);
                candidates.sort((a, b) => b.year - a.year || a.index - b.index);
                const chosen = candidates.slice(0, yearCount);
                for (const item of candidates) item.checkbox.checked = false;
                for (const item of chosen) item.checkbox.checked = true;
                for (const item of chosen) {
                    item.checkbox.dispatchEvent(new Event('change', { bubbles: true }));
                }
                return chosen.map(item => item.year);
            }""",
            request.year_count,
        )
        if not selected_years:
            raise RuntimeError("Ingen regnskabsår med checkbokse blev fundet i accountform")

        department_select = None
        controls_frame = None
        for frame in page.frames:
            candidate = frame.locator(
                'select[name="soeg_afdelinger"]#soeg_afdelinger'
            ).first
            if candidate.count():
                department_select = candidate
                controls_frame = frame
                break
        if department_select is None or controls_frame is None:
            raise RuntimeError("Afdelingsfeltet soeg_afdelinger blev ikke fundet")

        selected_department = "Alle afdelinger"
        if request.department.strip():
            requested = request.department.strip()
            if requested.casefold() == "padel":
                requested = PADEL_DEPARTMENT_LABEL
            options = department_select.locator("option").evaluate_all(
                """(options) => options.map(o => ({ value: o.value, label: (o.textContent || '').trim() }))"""
            )
            match = next(
                (o for o in options if o["label"].casefold() == requested.casefold()),
                None,
            )
            if match is None:
                matches = [o for o in options if requested.casefold() in o["label"].casefold()]
                if len(matches) != 1:
                    labels = ", ".join(o["label"] for o in matches[:10]) or "ingen"
                    raise RuntimeError(
                        f"Afdelingen '{request.department}' kunne ikke vælges entydigt. Match: {labels}"
                    )
                match = matches[0]
            department_select.select_option(value=match["value"])
            selected_department = match["label"]
        show_button = controls_frame.locator(
            'button:has-text("Vis"), input[type="submit"][value="Vis"], input[type="button"][value="Vis"]'
        ).first
        if not show_button.count():
            raise RuntimeError("Knappen 'Vis' blev ikke fundet i accountform")
        show_button.click()
        self._wait_for_stable(1500)

        tables = []
        for frame in page.frames:
            try:
                frame_tables = frame.locator("table").evaluate_all(
                    r"""(tables) => tables.map(table => {
                        const rows = [...table.querySelectorAll('tr')].map(tr =>
                            [...tr.querySelectorAll(':scope > th, :scope > td')].map(cell =>
                                (cell.innerText || '').replace(/\s+/g, ' ').trim()
                            )
                        ).filter(row => row.some(Boolean));
                        return rows;
                    }).filter(rows => rows.length)"""
                )
                tables.extend(frame_tables)
            except Exception:
                continue
        if not tables:
            raise RuntimeError("Conventus returnerede ingen tabeldata efter klik på 'Vis'")

        return {
            "source": "Conventus",
            "report": "resultatopgoerelse",
            "department": selected_department,
            "years": sorted(set(int(year) for year in selected_years), reverse=True),
            "tables": tables,
        }


def fetch_budget_report(
    department: str = "", year_count: int = 3, headless: bool = True
) -> dict[str, Any]:
    """Log in and return a read-only income statement as JSON-compatible data."""
    automation = ConventusBudgetAutomation(headless=headless)
    try:
        automation.start()
        if not automation.login():
            raise RuntimeError("Login til Conventus fejlede")
        return automation.fetch_report(
            BudgetReportRequest(department=department, year_count=year_count)
        )
    finally:
        automation.stop()


def print_report(report: dict[str, Any]) -> None:
    """Write stable UTF-8 JSON to stdout for consumption by other skills."""
    print(json.dumps(report, ensure_ascii=False, indent=2))
