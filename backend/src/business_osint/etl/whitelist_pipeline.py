"""Wzbogacanie encji o identyfikatory z białej listy VAT.

Cel: dopiąć brakujące numery REGON i KRS do podmiotów, które mamy już z GLEIF
(gdzie jest LEI i jeden krajowy numer). Dzięki temu ten sam podmiot pochodzący
z trzech różnych źródeł trafia w jeden węzeł grafu, a nie w trzy.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from business_osint.config import get_settings
from business_osint.db.models import EntityIdentifier
from business_osint.db.session import get_etl_sessionmaker
from business_osint.domain.enums import IdentifierScheme, SourceKind
from business_osint.domain.normalization import is_valid_krs, is_valid_regon, zahaszuj_pesele
from business_osint.etl.fetching.errors import FetchError
from business_osint.etl.loaders import store_raw_document
from business_osint.etl.pipeline import get_or_create_source
from business_osint.etl.sources.mf_whitelist import (
    MAX_NIPS_PER_REQUEST,
    WhitelistClient,
    extract_identifier_bridges,
)

#: Po tylu nieudanych partiach z rzędu przerywamy przebieg.
#:
#: Pierwszy pełny przebieg „zakończył się powodzeniem" z wynikiem
#: `errors: 118501`: po wyczerpaniu dziennego limitu MF (`WL-191`) pętla
#: przemieliła wszystkie pozostałe partie, nie robiąc nic, i zameldowała
#: sukces. Źródło, które przestało odpowiadać, ma zatrzymać przebieg — inaczej
#: licznik błędów jest szumem, a nie sygnałem.
MAX_KOLEJNYCH_BLEDOW = 20


@dataclass(slots=True)
class WhitelistStats:
    nips_checked: int = 0
    #: Ostatni przetworzony NIP — punkt wznowienia po przerwaniu przebiegu.
    last_nip: str = ""
    identifiers_added: int = 0
    vat_active: int = 0
    not_found: int = 0
    errors: int = 0
    #: Wypełniane, gdy przebieg przerwano — puste znaczy „doszedł do końca".
    aborted: str = ""

    def as_dict(self) -> dict[str, int]:
        return {
            "nips_checked": self.nips_checked,
            "last_nip": self.last_nip,  # type: ignore[dict-item]
            "identifiers_added": self.identifiers_added,
            "vat_active": self.vat_active,
            "not_found": self.not_found,
            "errors": self.errors,
            "aborted": self.aborted,  # type: ignore[dict-item]
        }


async def enrich_identifiers(
    *, limit: int | None = None, after: str | None = None, progress: Any = None
) -> WhitelistStats:
    """Dla każdego znanego NIP-u dopina REGON i KRS z białej listy.

    `after` wznawia przebieg od podanego NIP-u. Pełny przebieg to 118 676
    zapytań i kilkanaście godzin; bez punktu wznowienia każde przerwanie
    oznaczałoby zaczynanie od zera, co jest wprost sprzeczne z regułą warstwy
    pobierania: przerwany przebieg wznawia się, nie startuje na nowo.
    Kolejność po `value` jest stabilna, więc ostatni przetworzony NIP wystarczy
    za cały stan.
    """
    stats = WhitelistStats()
    factory = get_etl_sessionmaker()
    date = dt.date.today().isoformat()

    async with factory() as session:
        # LIMIT jako parametr, nie sklejanie napisu: NULL oznacza brak limitu,
        # a zapytanie zostaje jedną, niezmienną stałą (bez ryzyka wstrzyknięcia).
        rows = await session.execute(
            text(
                """
                SELECT i.value AS nip, i.entity_id
                FROM entity_identifiers i
                WHERE i.scheme = 'nip'
                  AND (CAST(:after AS text) IS NULL OR i.value > CAST(:after AS text))
                ORDER BY i.value
                LIMIT CAST(:limit AS bigint)
                """
            ),
            {"limit": limit, "after": after},
        )
        targets = {row.nip: row.entity_id for row in rows}

    client = WhitelistClient()
    nips = list(targets)
    pod_rzad = 0
    try:
        for start in range(0, len(nips), MAX_NIPS_PER_REQUEST):
            batch = nips[start : start + MAX_NIPS_PER_REQUEST]
            try:
                document = await client.fetch_batch(batch, date=date)
            except FetchError as blad:
                stats.errors += 1
                pod_rzad += 1
                if pod_rzad >= MAX_KOLEJNYCH_BLEDOW:
                    stats.aborted = f"{MAX_KOLEJNYCH_BLEDOW} nieudanych partii z rzędu: {blad}"
                    break
                continue
            pod_rzad = 0

            stats.nips_checked += len(batch)
            stats.last_nip = batch[-1]
            async with factory() as session, session.begin():
                source_id = await get_or_create_source(
                    session, SourceKind.MF_WHITELIST, "wl-api.mf.gov.pl", "https://wl-api.mf.gov.pl"
                )
                raw_id, _ = await store_raw_document(
                    session,
                    source_id=source_id,
                    external_id=document.external_id,
                    url=document.url,
                    fetched_at=document.fetched_at,
                    content_sha256=document.content_sha256,
                    # Biała lista zwraca `pesel` osób fizycznych prowadzących
                    # działalność. Haszujemy **przed** zapisem: `raw_documents`
                    # są niezmienne, więc jawny PESEL zapisany tu raz zostaje
                    # na zawsze. Suma kontrolna dotyczy odpowiedzi, jaką
                    # dostaliśmy, więc liczymy ją przed podmianą — inaczej
                    # przestałaby cokolwiek świadczyć o źródle.
                    payload=zahaszuj_pesele(document.payload, get_settings().pesel_pepper),
                )
                for bridge in extract_identifier_bridges(document.payload):
                    entity_id = targets.get(bridge["nip"])
                    if entity_id is None:
                        stats.not_found += 1
                        continue
                    if bridge["status_vat"].lower().startswith("czynny"):
                        stats.vat_active += 1
                    stats.identifiers_added += await _attach(session, entity_id, bridge, raw_id)
            if progress is not None:
                progress(stats)
    finally:
        await client.aclose()
    return stats


async def _attach(session: Any, entity_id: Any, bridge: dict[str, str], raw_id: Any) -> int:
    """Dopina REGON i KRS, jeśli przechodzą walidację. Konflikt oznacza, że numer
    należy już do innej encji — wtedy NIE scalamy, tylko pomijamy i zostawiamy
    ślad, bo to sygnał sprzeczności między źródłami (niezmiennik N4)."""
    added = 0
    candidates = [
        (IdentifierScheme.REGON, bridge["regon"], is_valid_regon),
        (IdentifierScheme.KRS, bridge["krs"], is_valid_krs),
    ]
    for scheme, value, validator in candidates:
        if not value or not validator(value):
            continue
        result = await session.execute(
            pg_insert(EntityIdentifier)
            .values(entity_id=entity_id, scheme=scheme.value, value=value)
            .on_conflict_do_nothing(constraint="uq_entity_identifiers_scheme_value")
            .returning(EntityIdentifier.id)
        )
        if result.scalars().first() is not None:
            added += 1
    return added
