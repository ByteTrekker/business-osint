"""Wydobycie z zapisanych wpisów CEIDG tego, czego import nie brał.

Pojedynczy wpis `/firma` niesie znacznie więcej niż pole `spolki`, dla którego
go pobieramy. Dokumenty leżą już w `raw_documents`, więc to jest przebieg po
bazie, nie po sieci — zero nowego ruchu i zero nowego ryzyka.

Co dokładamy i dlaczego:

* **TERYT, SIMC, ULIC** — urzędowe kody adresu **wprost z rejestru**. Nasze
  dotychczasowe kody pochodzą z dopasowania do PRG po znormalizowanym napisie,
  które nie powiodło się dla 475 707 adresów. Tutaj przychodzą bez zgadywania.
* **adres korespondencyjny** — u 22% wpisów różny od adresu działalności, a nie
  mamy go wcale.
* **nazwa spółki cywilnej** — CEIDG jej nie podaje, ale bywa w nazwie wpisu
  wspólnika. Etykieta wyprowadzona, nie urzędowa; patrz `nazwa_zrodlo`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, text

from business_osint.db.session import get_etl_sessionmaker
from business_osint.domain.normalization import uzgodnij_nazwe_spolki


@dataclass(slots=True)
class BackfillStats:
    addresses_coded: int = 0
    correspondence_added: int = 0
    partnerships_named: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "addresses_coded": self.addresses_coded,
            "correspondence_added": self.correspondence_added,
            "partnerships_named": self.partnerships_named,
        }


# Kody urzędowe trafiają do adresu podmiotu. `teryt` uzupełniamy tylko tam,
# gdzie go nie ma — kod z rejestru jest lepszy od naszego dopasowania, ale
# nadpisywanie już ustalonej wartości byłoby zmianą faktu bez powodu.
_KODY = text("""
    UPDATE addresses a
    SET teryt = COALESCE(a.teryt, nullif(d.terc, '')),
        simc = nullif(d.simc, ''),
        ulic = nullif(d.ulic, '')
    FROM (
        SELECT (regexp_match(rd.external_id, 'ceidg/firma/(.+)'))[1] AS nip,
               rd.payload -> 'adresDzialalnosci' ->> 'terc' AS terc,
               rd.payload -> 'adresDzialalnosci' ->> 'simc' AS simc,
               rd.payload -> 'adresDzialalnosci' ->> 'ulic' AS ulic
        FROM raw_documents rd
        WHERE rd.external_id LIKE 'ceidg/firma/%'
    ) d
    JOIN entity_identifiers i ON i.scheme = 'nip' AND i.value = d.nip
    JOIN relationships r ON r.source_entity_id = i.entity_id
                        AND r.relationship_type = 'registered_at'
                        AND r.superseded_at IS NULL
    WHERE a.entity_id = r.target_entity_id
      AND (d.terc IS NOT NULL OR d.simc IS NOT NULL OR d.ulic IS NOT NULL)
""")

# Adres korespondencyjny jako atrybut podmiotu, nie osobny węzeł grafu.
# Węzeł znaczyłby „podmiot jest tu zarejestrowany", a to nieprawda — to jest
# adres do doręczeń. Osobna krawędź wymagałaby własnego typu i decyzji, co
# ona znaczy przy pytaniu o powiązania; atrybut niczego nie przesądza.
_KORESPONDENCJA = text("""
    UPDATE companies c
    SET attributes = c.attributes || jsonb_build_object(
            'adres_korespondencyjny', d.adres,
            'adres_korespondencyjny_inny', d.inny)
    FROM (
        SELECT (regexp_match(rd.external_id, 'ceidg/firma/(.+)'))[1] AS nip,
               concat_ws(' ',
                   nullif(rd.payload -> 'adresKorespondencyjny' ->> 'ulica', ''),
                   nullif(rd.payload -> 'adresKorespondencyjny' ->> 'budynek', ''),
                   nullif(rd.payload -> 'adresKorespondencyjny' ->> 'kod', ''),
                   nullif(rd.payload -> 'adresKorespondencyjny' ->> 'miasto', '')
               ) AS adres,
               (rd.payload -> 'adresKorespondencyjny' ->> 'kod'
                IS DISTINCT FROM rd.payload -> 'adresDzialalnosci' ->> 'kod') AS inny
        FROM raw_documents rd
        WHERE rd.external_id LIKE 'ceidg/firma/%'
          AND rd.payload ? 'adresKorespondencyjny'
    ) d
    JOIN entity_identifiers i ON i.scheme = 'nip' AND i.value = d.nip
    WHERE c.entity_id = i.entity_id AND d.adres <> ''
""")

# Nazwy wpisów wspólników każdej spółki — materiał na etykietę.
_NAZWY_WSPOLNIKOW = text("""
    SELECT r.target_entity_id AS spolka, array_agg(e.display_name) AS nazwy
    FROM relationships r
    JOIN relationships sp ON sp.source_entity_id = r.source_entity_id
                         AND sp.relationship_type = 'sole_proprietor_of'
                         AND sp.superseded_at IS NULL
    JOIN entities e ON e.id = sp.target_entity_id
    JOIN entities s ON s.id = r.target_entity_id
    WHERE r.relationship_type = 'partner_in' AND r.superseded_at IS NULL
      AND s.display_name LIKE 'Spółka cywilna NIP%'
    GROUP BY r.target_entity_id
""")

# Etykieta jest **wyprowadzona z nazw wspólników**, nie wzięta z rejestru —
# CEIDG nazwy spółki nie podaje. Zapisujemy to wprost, żeby interfejs mógł
# powiedzieć prawdę, a urzędowa nazwa z białej listy mogła ją później nadpisać
# bez zastanawiania się, co wolno nadpisać.
_NAZWIJ = text("""
    UPDATE entities SET display_name = :nazwa, normalized_name = :norm WHERE id = :id
""")

_ZNACZ_ZRODLO = text("""
    UPDATE companies
    SET attributes = attributes || '{"nazwa_zrodlo": "wyprowadzona z nazw wspólników"}'::jsonb
    WHERE entity_id = :id
""")


async def backfill(*, progress: Any = None) -> BackfillStats:
    """Uzupełnia bazę z dokumentów, które już mamy."""
    stats = BackfillStats()
    factory = get_etl_sessionmaker()

    async with factory() as session, session.begin():
        await session.execute(text("SET LOCAL statement_timeout = '30min'"))
        # `Result[Any]` nie ma `rowcount` — potrzebny jest rzut na `CursorResult`.
        stats.addresses_coded = cast(CursorResult[Any], await session.execute(_KODY)).rowcount or 0
        stats.correspondence_added = (
            cast(CursorResult[Any], await session.execute(_KORESPONDENCJA)).rowcount or 0
        )

    async with factory() as session, session.begin():
        wiersze = (await session.execute(_NAZWY_WSPOLNIKOW)).all()
        for wiersz in wiersze:
            nazwa = uzgodnij_nazwe_spolki(list(wiersz.nazwy))
            if not nazwa:
                continue
            etykieta = f"{nazwa} s.c."
            await session.execute(
                _NAZWIJ,
                {"id": wiersz.spolka, "nazwa": etykieta, "norm": etykieta.lower()},
            )
            await session.execute(_ZNACZ_ZRODLO, {"id": wiersz.spolka})
            stats.partnerships_named += 1
            if progress is not None:
                progress(stats)
    return stats
