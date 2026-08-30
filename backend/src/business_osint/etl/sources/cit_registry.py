"""Indywidualne dane podatników CIT (art. 27b ustawy o CIT).

Ministerstwo Finansów publikuje raz w roku, do 30 września, dane z zeznań
podatników o przychodzie powyżej 50 mln EUR, podatkowych grup kapitałowych
i spółek nieruchomościowych. To jedyne otwarte źródło **finansów** w projekcie.

Zakres jest wąski — kilka tysięcy największych podatników, nie cała gospodarka —
ale są to dokładnie te podmioty, które stoją na szczycie struktur właścicielskich
z GLEIF, więc uzupełniają obraz tam, gdzie ma on największe znaczenie.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import xlrd

#: Trzy zestawy publikowane co roku pod odrębnymi załącznikami.
DATASETS = ("pod", "pgk", "nier")

#: Indeksy kolumn ustalone na pliku za 2024 r. Nagłówek jest wielopoziomowy,
#: więc odczytujemy po pozycji, a nie po nazwie — z walidacją nagłówka niżej.
COLUMNS = {
    "name": 1,
    "nip": 2,
    "period_from": 3,
    "period_to": 4,
    "revenue": 5,
    "costs": 9,
    "income": 13,
    "loss": 17,
    "tax_base": 21,
    "tax_due": 23,
}
#: Fragmenty, które muszą znaleźć się w wierszu nagłówka. Jeżeli MF zmieni
#: układ kolumn, import ma się zatrzymać, a nie zapisać liczby w złych polach.
HEADER_MARKERS = ("Nazwa podatnika", "Numer NIP", "Przychód")


@dataclass(slots=True)
class CitRecord:
    name: str
    nip: str
    period_from: dt.date
    period_to: dt.date
    revenue: float | None = None
    costs: float | None = None
    income: float | None = None
    loss: float | None = None
    tax_base: float | None = None
    tax_due: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


class CitHeaderMismatchError(RuntimeError):
    """Układ kolumn w pliku MF nie zgadza się z oczekiwanym."""


def parse_cit_workbook(path: str, *, dataset: str) -> list[CitRecord]:
    """Czyta arkusz MF i zwraca rekordy z poprawnym NIP-em."""
    workbook = xlrd.open_workbook(path)
    sheet = workbook.sheet_by_index(0)

    header_row = _find_header_row(sheet)
    records: list[CitRecord] = []

    for row in range(header_row + 1, sheet.nrows):
        nip = _digits(sheet.cell_value(row, COLUMNS["nip"]))
        name = str(sheet.cell_value(row, COLUMNS["name"])).strip()
        if len(nip) != 10 or not name:
            continue
        period_from = _as_date(sheet.cell_value(row, COLUMNS["period_from"]), workbook)
        period_to = _as_date(sheet.cell_value(row, COLUMNS["period_to"]), workbook)
        if period_from is None or period_to is None or period_to < period_from:
            continue
        records.append(
            CitRecord(
                name=name,
                nip=nip,
                period_from=period_from,
                period_to=period_to,
                revenue=_as_amount(sheet.cell_value(row, COLUMNS["revenue"])),
                costs=_as_amount(sheet.cell_value(row, COLUMNS["costs"])),
                income=_as_amount(sheet.cell_value(row, COLUMNS["income"])),
                loss=_as_amount(sheet.cell_value(row, COLUMNS["loss"])),
                tax_base=_as_amount(sheet.cell_value(row, COLUMNS["tax_base"])),
                tax_due=_as_amount(sheet.cell_value(row, COLUMNS["tax_due"])),
                attributes={"dataset": dataset},
            )
        )
    return records


def _find_header_row(sheet: Any) -> int:
    for row in range(min(20, sheet.nrows)):
        values = " ".join(str(sheet.cell_value(row, c)) for c in range(sheet.ncols))
        if all(marker in values for marker in HEADER_MARKERS):
            return row
    raise CitHeaderMismatchError("nie znaleziono nagłówka z kolumnami " + ", ".join(HEADER_MARKERS))


def _digits(value: Any) -> str:
    if isinstance(value, float):
        value = f"{int(value):d}"
    return "".join(ch for ch in str(value) if ch.isdigit())


def _as_date(value: Any, workbook: Any) -> dt.date | None:
    if isinstance(value, float) and value > 0:
        parts = xlrd.xldate_as_tuple(value, workbook.datemode)
        return dt.date(parts[0], parts[1], parts[2])
    text = str(value).strip()[:10]
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def _as_amount(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    text = str(value).replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None
