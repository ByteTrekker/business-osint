"""Skąd pochodzą dane — z licznikami z bazy, nie z opisu w dokumentacji.

Strona o źródłach napisana ręcznie rozjeżdża się z rzeczywistością przy
pierwszym imporcie i nikt tego nie zauważa. Liczniki idą stąd, żeby „co mamy"
było stwierdzeniem o bazie, a nie obietnicą sprzed pół roku.

Opisy są stałe w kodzie: liczby mówią *ile*, ale nie *co to znaczy* ani czego
w danym rejestrze **nie ma** — a to drugie jest zwykle ważniejsze.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from business_osint.api.deps import SessionDep

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceOut(BaseModel):
    kind: str
    name: str
    what: str = Field(description="Co z tego źródła bierzemy")
    caveat: str | None = Field(default=None, description="Czego w nim nie ma albo co zawodzi")
    documents: int
    relationships: int
    last_fetch: dt.datetime | None


class SourcesOut(BaseModel):
    active: list[SourceOut]
    planned: list[PlannedOut]


class PlannedOut(BaseModel):
    name: str
    what: str
    blocker: str | None


#: Co dane źródło wnosi i czego w nim nie ma. Kolejność jak w
#: `docs/02-zrodla-danych.md`.
OPISY: dict[str, tuple[str, str | None]] = {
    "ceidg": (
        "Jednoosobowe działalności gospodarcze: przedsiębiorca, firma, adres, "
        "PKD, status, dane kontaktowe.",
        "714 771 przedsiębiorców nie podało żadnego adresu — zaznaczyli brak "
        "stałego miejsca wykonywania działalności, więc nie pojawią się na mapie.",
    ),
    "gleif": (
        "Identyfikatory LEI oraz powiązania kapitałowe między spółkami — "
        "jedyne w tej bazie powiązania spółka–spółka.",
        "Obejmuje wyłącznie podmioty, które wystąpiły o LEI: duże i te "
        "handlujące na rynkach finansowych.",
    ),
    "bzp": (
        "Zamówienia publiczne: krawędź wykonawca ↔ zamawiający.",
        "Wczytany fragment, nie całe archiwum.",
    ),
    "krs": (
        "Odpisy spółek na żądanie: forma prawna, kapitał, PKD, skład organów.",
        "Publiczne API maskuje imię, nazwisko i PESEL do pierwszego znaku, "
        "więc nie powstaje z niego ani jedna encja osoby.",
    ),
    "mf_whitelist": (
        "Most identyfikatorowy: NIP, REGON i KRS tego samego podmiotu w jednym "
        "rekordzie, plus status VAT i numery rachunków.",
        "Dzienny limit zapytań na adres IP (WL-191) wyczerpuje się po kilku "
        "tysiącach numerów — pełny przebieg tą drogą jest nierealny.",
    ),
    "manual": ("Wykaz podatników CIT (art. 27b): przychód, koszty, podatek.", None),
}

#: Źródła, których jeszcze nie mamy. Trzymane tu, a nie w bazie, bo to plan,
#: a nie stan — patrz `docs/10-plan-pobierania.md`.
PLANOWANE: list[tuple[str, str, str | None]] = [
    (
        "PRG — Państwowy Rejestr Granic",
        "Punkty adresowe: współrzędne, TERYT, SIMC, ULIC. Wczytane jednorazowo, "
        "poza tabelą źródeł — stąd brak go na liście wyżej.",
        None,
    ),
    (
        "Spółki cywilne z CEIDG",
        "3 328 wpisów prowadzonych wyłącznie w formie spółki cywilnej — jedyna "
        "droga do powiązania osoba–osoba z danych, które już mamy.",
        None,
    ),
    (
        "REGON / BIR1",
        "Pełna lista podmiotów wraz z PKD, w tym takich bez numeru NIP.",
        None,
    ),
    (
        "KRS masowo",
        "Zarządy, wspólnicy i historia wszystkich spółek — bez nazwisk, ale "
        "z formą prawną, kapitałem, składem organów i datami zmian.",
        "Wymaga opinii prawnej co do art. 60a ustawy o KRS.",
    ),
    (
        "CRBR",
        "Beneficjenci rzeczywiści: kto faktycznie kontroluje spółkę. Tego nie ma w KRS w ogóle.",
        "Model wyłącznie na żądanie — rejestr nie ma eksportu zbiorczego i nie "
        "budujemy jego kopii.",
    ),
    (
        "KRZ",
        "Upadłości, restrukturyzacje i zakazy prowadzenia działalności.",
        "Brak rozpoznanego API — do zbadania.",
    ),
    (
        "MSiG",
        "Monitor Sądowy i Gospodarczy: wpisy do KRS z pełnymi nazwiskami, "
        "publikowane od 1996 roku.",
        "Wymaga opinii prawnej: publikacja w dzienniku urzędowym to nie to samo "
        "co podstawa do zbudowania wyszukiwarki po nazwisku.",
    ),
]

# Grupujemy po rodzaju rejestru, nie po wierszu w `sources`. GLEIF ma dwa
# wpisy — API i zrzut zbiorczy — a krawędzie liczymy po rodzaju, więc rozbicie
# na wiersze przypisywałoby całą sumę każdemu z nich osobno.
_ZRODLA = text("""
    SELECT s.kind,
           string_agg(DISTINCT s.name, ', ' ORDER BY s.name) AS nazwa,
           count(DISTINCT rd.id) AS dokumentow,
           max(rd.fetched_at) AS ostatnie
    FROM sources s
    LEFT JOIN raw_documents rd ON rd.source_id = s.id
    GROUP BY s.kind
    ORDER BY count(DISTINCT rd.id) DESC
""")

# Krawędzie liczymy osobno: złączenie z `relationship_sources` w tym samym
# zapytaniu mnożyłoby dokumenty przez krawędzie i obie liczby byłyby fałszywe.
_KRAWEDZIE = text("""
    SELECT s.kind, count(*) AS krawedzi
    FROM relationship_sources rs
    JOIN raw_documents rd ON rd.id = rs.raw_document_id
    JOIN sources s ON s.id = rd.source_id
    GROUP BY s.kind
""")


@router.get("", response_model=SourcesOut, summary="Rejestry, z których pochodzą dane")
async def get_sources(session: SessionDep) -> SourcesOut:
    krawedzie = {row.kind: int(row.krawedzi) for row in (await session.execute(_KRAWEDZIE)).all()}
    rows = (await session.execute(_ZRODLA)).all()
    return SourcesOut(
        active=[
            SourceOut(
                kind=row.kind,
                name=row.nazwa,
                what=OPISY.get(row.kind, ("", None))[0],
                caveat=OPISY.get(row.kind, ("", None))[1],
                documents=int(row.dokumentow),
                relationships=krawedzie.get(row.kind, 0),
                last_fetch=row.ostatnie,
            )
            for row in rows
        ],
        planned=[PlannedOut(name=n, what=w, blocker=b) for n, w, b in PLANOWANE],
    )
