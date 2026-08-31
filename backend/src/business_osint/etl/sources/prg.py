"""Odczyt punktów adresowych z GML-a Państwowego Rejestru Granic.

PRG rozdziela adres na trzy obiekty: punkt niesie numer, kod pocztowy
i współrzędne, a nazwę miejscowości i ulicy trzyma jako **referencje `xlink`**
do osobnych obiektów w tym samym pliku. Bez ich rozwiązania punkt adresowy nie
ma nazwy i nie da się go z niczym dopasować.

Stąd dwa przebiegi po pliku zamiast jednego. Słowniki są małe — w lubuskim
1 403 miejscowości i 9 915 ulic na 203 347 punktów — więc mieszczą się w pamięci
bez trudu, ale ich kolejność w pliku nie jest zagwarantowana i nie można na nią
liczyć.

Świadomie nie używamy tu DuckDB ani GDAL-a, choć oba czytają GML. Żaden z nich
nie rozwiązuje referencji `xlink`, a to jest cała trudność tego formatu.

**Kolejność osi jest sprawdzona pomiarem, nie założona.** Plik deklaruje
`srsName="EPSG:2180"`, którego urzędowa kolejność to (northing, easting), ale
zapisuje współrzędne w konwencji GIS (easting, northing). Punkt
`205249.1 530976.79` odczytany zgodnie ze specyfikacją ląduje w Małopolsce,
350 km od miejscowości, którą opisuje. Odczytany jako (easting, northing) trafia
w Chyrzyno w lubuskim — czyli tam, gdzie ma być. Błąd tej klasy przechodzi przez
każdy test, który sprawdza tylko, czy punkt jest „gdzieś w Polsce".
"""

from __future__ import annotations

# S314: `ElementTree` jest podatny na bomby encji. Plik pochodzi z serwera
# danych otwartych GUGiK i pobieramy go świadomie, uruchamiając import ręcznie —
# nie jest to wejście od użytkownika. Ryzyko resztkowe: gdyby ten serwer został
# przejęty, spreparowany GML mógłby wyczerpać pamięć zadania wsadowego.
# Uznajemy je za akceptowalne; alternatywą jest `defusedxml`.
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from pyproj import Transformer

_PRGAD = "{https://geoportal.gov.pl/schemas/prgad/1.0}"
_GML = "{http://www.opengis.net/gml/3.2}"
_XLINK = "{http://www.w3.org/1999/xlink}"

#: `always_xy` mówi pyprojowi, żeby przyjmował i zwracał (x, y) niezależnie od
#: urzędowej kolejności osi układu — a plik właśnie tak zapisuje współrzędne.
_TRANSFORMER = Transformer.from_crs(2180, 4326, always_xy=True)


@dataclass(slots=True, frozen=True)
class PunktAdresowy:
    city: str
    street: str | None
    building: str
    postal_code: str | None
    latitude: float
    longitude: float
    teryt: str | None
    simc: str | None
    ulic: str | None


def _tekst(element: ET.Element, nazwa: str) -> str | None:
    znaleziony = element.find(f"{_PRGAD}{nazwa}")
    if znaleziony is None or not (znaleziony.text or "").strip():
        return None
    return znaleziony.text.strip()  # type: ignore[union-attr]


def _referencja(element: ET.Element, nazwa: str) -> str | None:
    """Identyfikator wskazywany przez `xlink:href`, bez wiodącego `#`."""
    znaleziony = element.find(f"{_PRGAD}{nazwa}")
    if znaleziony is None:
        return None
    href = znaleziony.get(f"{_XLINK}href")
    return href.lstrip("#") if href else None


def _wspolrzedne(element: ET.Element) -> tuple[float, float] | None:
    """Zwraca (szerokość, długość) w WGS84 albo ``None``."""
    pos = element.find(f".//{_GML}pos")
    if pos is None or not (pos.text or "").strip():
        return None
    czesci = pos.text.split()  # type: ignore[union-attr]
    if len(czesci) < 2:
        return None
    easting, northing = float(czesci[0]), float(czesci[1])
    lon, lat = _TRANSFORMER.transform(easting, northing)
    return lat, lon


def _wyczysc(element: ET.Element, korzen: ET.Element) -> None:
    """Zwalnia przetworzony węzeł razem z rodzeństwem, które już minęło.

    Bez tego `iterparse` trzyma w pamięci całe drzewo — przy pliku 690 MB
    oznacza to kilka gigabajtów zamiast kilkudziesięciu megabajtów.
    """
    element.clear()
    while korzen is not element and len(korzen) > 0:
        del korzen[0]
        break


def _slowniki(
    sciezka: Path,
) -> tuple[dict[str, tuple[str, str | None, str | None]], dict[str, tuple[str, str | None]]]:
    """Pierwszy przebieg: mapy identyfikatorów na nazwy i kody urzędowe.

    Zwraca (miejscowości: id -> (nazwa, SIMC, TERYT gminy),
    ulice: id -> (nazwa, ULIC)).
    """
    miejscowosci: dict[str, tuple[str, str | None, str | None]] = {}
    ulice: dict[str, tuple[str, str | None]] = {}

    kontekst = ET.iterparse(sciezka, events=("start", "end"))  # noqa: S314
    _, korzen = next(kontekst)
    for zdarzenie, element in kontekst:
        if zdarzenie != "end":
            continue
        if element.tag == f"{_PRGAD}AD_Miejscowosc":
            gml_id = element.get(f"{_GML}id")
            nazwa = _tekst(element, "nazwa")
            if gml_id and nazwa:
                miejscowosci[gml_id] = (
                    nazwa,
                    _tekst(element, "identyfikatorSIMC"),
                    _tekst(element, "TERYTGminy"),
                )
            _wyczysc(element, korzen)
        elif element.tag == f"{_PRGAD}AD_UlicaPlac":
            gml_id = element.get(f"{_GML}id")
            nazwa = _tekst(element, "nazwaPelna") or _tekst(element, "TERYTNazwa1")
            if gml_id and nazwa:
                ulice[gml_id] = (nazwa, _tekst(element, "identyfikatorULIC"))
            _wyczysc(element, korzen)
        elif element.tag == f"{_PRGAD}AD_PunktAdresowy":
            # Punktów w pierwszym przebiegu nie potrzebujemy, ale trzeba je
            # zwolnić — inaczej 200 tys. węzłów zostaje w pamięci.
            _wyczysc(element, korzen)

    return miejscowosci, ulice


def czytaj_punkty(sciezka: Path) -> Iterator[PunktAdresowy]:
    """Punkty adresowe z jednego pliku GML, z rozwiązanymi nazwami."""
    miejscowosci, ulice = _slowniki(sciezka)

    kontekst = ET.iterparse(sciezka, events=("start", "end"))  # noqa: S314
    _, korzen = next(kontekst)
    for zdarzenie, element in kontekst:
        if zdarzenie != "end" or element.tag != f"{_PRGAD}AD_PunktAdresowy":
            continue

        numer = _tekst(element, "numerPorzadkowy")
        wspolrzedne = _wspolrzedne(element)
        miejscowosc = miejscowosci.get(_referencja(element, "miejscowosc") or "")

        # Punkt bez numeru, bez współrzędnych albo bez miejscowości nie da się
        # z niczym dopasować — pomijamy zamiast wstawiać wiersz, który nigdy
        # nie trafi w żadne zapytanie.
        if numer and wspolrzedne and miejscowosc:
            nazwa_miejscowosci, simc, teryt = miejscowosc
            ulica = ulice.get(_referencja(element, "ulica2") or "")
            yield PunktAdresowy(
                city=nazwa_miejscowosci,
                street=ulica[0] if ulica else None,
                building=numer,
                postal_code=_tekst(element, "kodPocztowy"),
                latitude=round(wspolrzedne[0], 6),
                longitude=round(wspolrzedne[1], 6),
                teryt=teryt,
                simc=simc,
                ulic=ulica[1] if ulica else None,
            )
        _wyczysc(element, korzen)
