"""Zrzuty zbiorcze CEIDG z hurtowni danych biznes.gov.pl.

Dlaczego raporty, a nie ``/firmy``:

* API ma limit **1000 żądań na 60 minut**, a ``/firmy`` zwraca najwyżej
  **25 rekordów na stronę**. Pełny przebieg przez 2,5 mln działalności to
  100 tys. żądań, czyli ponad cztery doby ciągłego pobierania.
* Endpoint ``/raporty`` udostępnia gotowe zrzuty w podziale na województwa.
  Siedemnaście plików pokrywa całą Polskę — **17 żądań zamiast 100 tysięcy**.

``/firmy`` zostaje do zapytań o pojedynczy podmiot, a ``/zmiana`` (zwraca
identyfikatory firm zmienionych w zakresie dat) do dociągania przyrostowego.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from business_osint.domain.enums import SourceKind
from business_osint.etl.fetching.client import ResilientClient
from business_osint.etl.fetching.profiles import PROFILES
from business_osint.etl.fetching.rate_limit import RateLimiter

BASE_URL = "https://dane.biznes.gov.pl/api/ceidg/v3"

#: Nazwa raportu, który zawiera zarejestrowane działalności (a nie wnioski).
REPORT_PREFIX = "Zarejestrowane działalności"
#: Format, w którym parsowanie jest najtańsze.
REPORT_FORMAT = ".csv"

USER_AGENT = "business-osint/0.1 (+https://github.com/ByteTrekker/business-osint)"


@dataclass(frozen=True, slots=True)
class ReportRef:
    id: str
    name: str
    url: str
    created_at: str

    @property
    def region(self) -> str:
        return self.name.removeprefix(REPORT_PREFIX).lstrip(" -")


class CeidgReportClient:
    """Czyta katalog raportów i pobiera archiwa ZIP."""

    def __init__(self, token: str, *, client: httpx.AsyncClient | None = None) -> None:
        if not token.strip():
            raise ValueError("brak tokenu CEIDG — ustaw BUSINESS_OSINT_CEIDG_TOKEN")
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(600.0, connect=15.0, read=600.0),
            headers={
                "Authorization": f"Bearer {token.strip()}",
                "User-Agent": USER_AGENT,
            },
            follow_redirects=True,
        )

    async def latest_reports(self) -> list[ReportRef]:
        """Najnowszy raport dla każdego regionu — jedno żądanie do katalogu."""
        response = await self._client.get(
            f"{BASE_URL}/raporty", headers={"Accept": "application/json"}
        )
        response.raise_for_status()
        newest: dict[str, ReportRef] = {}
        for item in response.json().get("raporty", []):
            if item.get("format") != REPORT_FORMAT:
                continue
            if not str(item.get("nazwa", "")).startswith(REPORT_PREFIX):
                continue
            ref = ReportRef(
                id=item["id"],
                name=item["nazwa"],
                url=item["raport"],
                created_at=item.get("data-utworzenia", ""),
            )
            current = newest.get(ref.name)
            if current is None or ref.created_at > current.created_at:
                newest[ref.name] = ref
        return sorted(newest.values(), key=lambda r: r.name)

    async def download(self, ref: ReportRef) -> bytes:
        response = await self._client.get(ref.url)
        response.raise_for_status()
        return response.content

    async def aclose(self) -> None:
        await self._client.aclose()


def iter_report_rows(payload: bytes) -> Iterator[dict[str, Any]]:
    """Strumieniuje wiersze CSV z archiwum — bez wczytywania całości do pamięci."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
        with archive.open(name) as handle:
            # utf-8-sig: pliki mają BOM, przez który pierwsza kolumna nazywałaby się "﻿Lp."
            text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
            yield from csv.DictReader(text, delimiter=";")


#: Pojedynczy wpis CEIDG. **Tylko ten punkt zwraca pole `spolki`** —
#: odpowiednik zbiorczy `/firmy` przyjmuje do pięciu NIP-ów naraz, ale
#: `spolki` w nim nie ma, więc partia niczego by nie przyspieszyła.
FIRMA_URL = f"{BASE_URL}/firma"


class CeidgEntryClient:
    """Odczyt pojedynczych wpisów CEIDG po numerze NIP.

    Istnieje wyłącznie po to, żeby dostać `spolki` — listę spółek cywilnych,
    w których wpis uczestniczy. Raport zbiorczy ma 24 kolumny i **żadna nie
    identyfikuje spółki**: `StatusDzialalnosci` mówi tylko, że ktoś działa
    wyłącznie w tej formie, nie mówi z kim. Bez tego punktu nie da się
    zbudować krawędzi między wspólnikami.

    Idzie przez `ResilientClient`, a nie przez gołego `httpx`. Pierwsza wersja
    tego klienta miała własne połączenie bez limitu tempa i bez obsługi
    `Retry-After` — dostała `429` po 930 zapytaniach i zatrzymała przebieg.
    Rejestr podaje swój limit w nagłówkach `x-rate-limit-*`: **1000 zapytań
    na 60 minut**.
    """

    def __init__(self, token: str, client: ResilientClient | None = None) -> None:
        self._client = client or self._domyslny(token)

    @staticmethod
    def _domyslny(token: str) -> ResilientClient:
        return ResilientClient(
            source=SourceKind.CEIDG.value,
            client=httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                headers={
                    "Authorization": f"Bearer {token.strip()}",
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                },
                follow_redirects=True,
            ),
            rate_limiter=RateLimiter(PROFILES[SourceKind.CEIDG].rate_per_second),
            retry_policy=PROFILES[SourceKind.CEIDG].retry,
        )

    async def fetch(self, nip: str) -> dict[str, Any] | None:
        """Wpis dla numeru NIP albo ``None``, gdy rejestr go nie zna."""
        document = await self._client.get_json(
            FIRMA_URL, external_id=f"ceidg/firma/{nip}", params={"nip": nip}
        )
        firma = document.payload.get("firma")
        if isinstance(firma, list):
            return firma[0] if firma else None
        return firma if isinstance(firma, dict) else None

    async def aclose(self) -> None:
        await self._client.aclose()


def spolki_z_wpisu(firma: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Pary (NIP, REGON) spółek cywilnych z wpisu. Bez NIP-u para jest bezużyteczna."""
    if not firma:
        return []
    wynik = []
    for spolka in firma.get("spolki") or []:
        nip = str(spolka.get("nip") or "").strip()
        if nip:
            wynik.append((nip, str(spolka.get("regon") or "").strip()))
    return wynik
