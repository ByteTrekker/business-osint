"""Urzędowe nazwy spółek cywilnych z białej listy VAT.

CEIDG nie podaje nazwy spółki — w polu `spolki` są wyłącznie NIP i REGON.
Dotąd radziliśmy sobie heurystyką: wyłuskiwaliśmy nazwę z nazwy wpisu
wspólnika („JAN KOWALSKI wspólnik spółki cywilnej PLASTECH"). To działa dla
części wpisów i bywa trafne, ale pozostaje **domysłem**.

Biała lista VAT zna te podmioty po numerze NIP i zwraca nazwę zarejestrowaną.
Zmierzone na próbce trzydziestu: 27 trafień. Pozostałe to spółki, których
w wykazie VAT nie ma — wtedy zostaje etykieta wyprowadzona albo zastępcza,
i tak też jest oznaczona w danych.

Zapytań jest tyle, ile spółek podzielone przez trzydzieści — kilkaset, czyli
mieści się w dziennym limicie MF z zapasem. To nie jest ten sam przebieg co
most identyfikatorowy (`whitelist_pipeline`) i celuje w inny zbiór.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from business_osint.db.session import get_etl_sessionmaker
from business_osint.etl.fetching.errors import FetchError
from business_osint.etl.sources.mf_whitelist import MAX_NIPS_PER_REQUEST, WhitelistClient

#: Po tylu nieudanych partiach z rzędu przerywamy — źródło, które przestało
#: odpowiadać, ma zatrzymać przebieg, a nie mielić go bez efektu.
MAX_KOLEJNYCH_BLEDOW = 10


@dataclass(slots=True)
class NameStats:
    checked: int = 0
    named: int = 0
    not_in_register: int = 0
    errors: int = 0
    aborted: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "named": self.named,
            "not_in_register": self.not_in_register,
            "errors": self.errors,
            "aborted": self.aborted,
        }


#: Bierzemy zarówno spółki bez nazwy, jak i te z nazwą wyprowadzoną —
#: urzędowa bije heurystykę, więc jest czym nadpisać.
_DO_NAZWANIA = text("""
    SELECT i.value AS nip, e.id
    FROM companies c
    JOIN entities e ON e.id = c.entity_id AND e.merged_into_id IS NULL
    JOIN entity_identifiers i ON i.entity_id = c.entity_id AND i.scheme = 'nip'
    WHERE c.legal_form = 'spółka cywilna'
      AND (c.attributes ->> 'nazwa_zrodlo' IS DISTINCT FROM 'biała lista VAT')
    ORDER BY i.value
    LIMIT CAST(:limit AS bigint)
""")

_NAZWIJ = text("""
    UPDATE entities SET display_name = :nazwa, normalized_name = lower(:nazwa)
    WHERE id = :id
""")

_ZNACZ = text("""
    UPDATE companies
    SET attributes = attributes || '{"nazwa_zrodlo": "biała lista VAT"}'::jsonb
    WHERE entity_id = :id
""")


async def import_names(*, limit: int | None = None, progress: Any = None) -> NameStats:
    """Nadpisuje etykiety spółek cywilnych nazwami z rejestru."""
    stats = NameStats()
    factory = get_etl_sessionmaker()
    data = dt.date.today().isoformat()

    async with factory() as session:
        cele = (await session.execute(_DO_NAZWANIA, {"limit": limit})).all()
    if not cele:
        return stats

    po_nipie = {cel.nip: cel.id for cel in cele}
    nipy = list(po_nipie)
    client = WhitelistClient()
    pod_rzad = 0
    try:
        for start in range(0, len(nipy), MAX_NIPS_PER_REQUEST):
            partia = nipy[start : start + MAX_NIPS_PER_REQUEST]
            try:
                document = await client.fetch_batch(partia, date=data)
            except FetchError as blad:
                stats.errors += 1
                pod_rzad += 1
                if pod_rzad >= MAX_KOLEJNYCH_BLEDOW:
                    stats.aborted = f"{MAX_KOLEJNYCH_BLEDOW} nieudanych partii z rzędu: {blad}"
                    break
                continue
            pod_rzad = 0
            stats.checked += len(partia)

            znalezione = _nazwy_z_odpowiedzi(document.payload)
            async with factory() as session, session.begin():
                for nip in partia:
                    nazwa = znalezione.get(nip)
                    if not nazwa:
                        stats.not_in_register += 1
                        continue
                    await session.execute(_NAZWIJ, {"id": po_nipie[nip], "nazwa": nazwa})
                    await session.execute(_ZNACZ, {"id": po_nipie[nip]})
                    stats.named += 1
            if progress is not None:
                progress(stats)
    finally:
        await client.aclose()
    return stats


def _nazwy_z_odpowiedzi(payload: dict[str, Any]) -> dict[str, str]:
    """Mapa NIP → nazwa. Odpowiedź jest zagnieżdżona głębiej, niż się wydaje."""
    wynik: dict[str, str] = {}
    for wpis in (payload.get("result") or {}).get("entries") or []:
        for podmiot in wpis.get("subjects") or []:
            nip = str(podmiot.get("nip") or "").strip()
            nazwa = str(podmiot.get("name") or "").strip()
            if nip and nazwa:
                wynik[nip] = nazwa
    return wynik
