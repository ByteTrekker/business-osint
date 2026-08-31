"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Map as LeafletMap, CircleMarker } from "leaflet";

import { fetchMapClusters, fetchMapCoverage, type MapCluster, type MapCoverage } from "@/lib/api";

/**
 * Mapa zbiorcza wszystkich adresów w bazie.
 *
 * Grupowanie dzieje się **po stronie bazy**, nie w przeglądarce. Biblioteki
 * klastrujące po stronie klienta dostają pełną listę punktów i grupują ją
 * lokalnie — przy 1,9 mln adresów przeglądarka umrze, zanim cokolwiek narysuje.
 * API zwraca liczności komórek siatki, więc odpowiedź ma zawsze podobną
 * wielkość niezależnie od tego, czy widać cały kraj, czy jedną ulicę.
 *
 * Leaflet ładujemy dynamicznie, bo sięga do `window` przy imporcie i wywraca
 * renderowanie po stronie serwera.
 *
 * Kafle idą z serwerów OpenStreetMap. Przy aplikacji lokalnej to mieści się
 * w ich zasadach użycia; wystawienie tego publicznie wymaga własnego serwera
 * kafli albo dostawcy z umową — inaczej ruch zostanie zablokowany.
 */
/**
 * Zasięg danych. Wszystko, co mamy ze współrzędnymi, leży w Polsce, więc
 * pytanie o więcej to pytanie o pustkę — a przy szerokim oknie i małym
 * przybliżeniu widok potrafi objąć pół Europy i przekroczyć limit API.
 * Przycinamy prostokąt do tego obszaru, zamiast rozluźniać limit po stronie
 * serwera: limit chroni bazę, a nie utrudnia życie mapie.
 */
const OBSZAR_DANYCH = { south: 48.5, north: 55.5, west: 13.0, east: 25.5 };

export function ClusterMap() {
  // Leaflet ładujemy przez stan, a nie `await` wewnątrz efektu tworzącego mapę.
  // Przy `await` tworzenie mapy dzieje się asynchronicznie, a sprzątanie
  // synchronicznie — przy podwójnym montowaniu (React StrictMode, Fast Refresh)
  // te dwa przebiegi się rozjeżdżają i na jednym kontenerze powstaje druga,
  // osierocona instancja: nasłuchuje zdarzeń, dubluje żądania i przestaje
  // reagować na kliknięcia. Ze stanem tworzenie jest synchroniczne i paruje
  // się ze sprzątaniem jeden do jednego.
  const [L, setL] = useState<typeof import("leaflet") | null>(null);
  const kontener = useRef<HTMLDivElement>(null);
  const mapa = useRef<LeafletMap | null>(null);
  const znaczniki = useRef<CircleMarker[]>([]);
  const zadanie = useRef<AbortController | null>(null);
  const [pokrycie, setPokrycie] = useState<MapCoverage | null>(null);
  const [przyciete, setPrzyciete] = useState(false);
  const [blad, setBlad] = useState<string | null>(null);
  const [laduje, setLaduje] = useState(true);

  const odswiez = useCallback(async (L: typeof import("leaflet")) => {
    const instancja = mapa.current;
    if (!instancja) return;

    zadanie.current?.abort();
    const kontroler = new AbortController();
    zadanie.current = kontroler;
    setLaduje(true);

    const granice = instancja.getBounds();
    const wycinek = {
      south: Math.max(granice.getSouth(), OBSZAR_DANYCH.south),
      north: Math.min(granice.getNorth(), OBSZAR_DANYCH.north),
      west: Math.max(granice.getWest(), OBSZAR_DANYCH.west),
      east: Math.min(granice.getEast(), OBSZAR_DANYCH.east),
    };
    // Widok całkowicie poza obszarem danych — nie ma o co pytać.
    if (wycinek.north <= wycinek.south || wycinek.east <= wycinek.west) {
      znaczniki.current.forEach((m) => m.remove());
      znaczniki.current = [];
      setLaduje(false);
      return;
    }

    try {
      const widok = await fetchMapClusters(wycinek, instancja.getZoom(), kontroler.signal);

      const maks = Math.max(1, ...widok.clusters.map((c) => c.addresses));
      const promienKomorki = maksymalnyPromien(instancja, widok.cell_degrees);

      znaczniki.current.forEach((m) => m.remove());
      znaczniki.current = widok.clusters.map((skupisko) =>
        L.circleMarker([skupisko.latitude, skupisko.longitude], {
          radius: promien(skupisko.addresses, maks, promienKomorki),
          color: barwa(skupisko.addresses, maks),
          weight: 1,
          fillColor: barwa(skupisko.addresses, maks),
          fillOpacity: 0.65,
        })
          .bindTooltip(opis(skupisko, widok.cell_degrees), { direction: "top" })
          .addTo(instancja),
      );
      setPrzyciete(widok.truncated);
      setBlad(null);
    } catch (powod) {
      // Przerwanie własnego żądania przy szybkim przesuwaniu widoku nie jest
      // błędem — nie ma o czym informować użytkownika.
      if (kontroler.signal.aborted) return;
      setBlad(powod instanceof Error ? powod.message : "Nie udało się wczytać mapy");
    } finally {
      if (!kontroler.signal.aborted) setLaduje(false);
    }
  }, []);

  useEffect(() => {
    let zywy = true;
    void import("leaflet").then((modul) => {
      if (zywy) setL(modul);
    });
    fetchMapCoverage()
      .then((dane) => zywy && setPokrycie(dane))
      .catch(() => undefined);
    return () => {
      zywy = false;
    };
  }, []);

  useEffect(() => {
    if (!L || !kontener.current) return;

    const instancja = L.map(kontener.current, {
      center: [52.0, 19.4],
      zoom: 6,
      minZoom: 5,
      maxZoom: 18,
      // Bez tego przesunięcie widoku poza Polskę daje prostokąt szerszy niż
      // obszar danych — samych danych by nie przybyło, a żądanie rosłoby.
      maxBounds: [
        [OBSZAR_DANYCH.south, OBSZAR_DANYCH.west],
        [OBSZAR_DANYCH.north, OBSZAR_DANYCH.east],
      ],
      maxBoundsViscosity: 0.8,
    });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(instancja);

    mapa.current = instancja;
    instancja.on("moveend", () => void odswiez(L));
    void odswiez(L);

    return () => {
      zadanie.current?.abort();
      instancja.remove();
      mapa.current = null;
      znaczniki.current = [];
    };
  }, [L, odswiez]);

  return (
    <div>
      <div className="clustermap" ref={kontener} />
      <p className="hint" aria-live="polite">
        {blad ? `Błąd: ${blad}` : laduje ? "Wczytywanie…" : null}
        {przyciete ? " Widok przycięto do 2000 skupisk — przybliż, żeby zobaczyć resztę." : null}
      </p>
      {pokrycie ? <Pokrycie dane={pokrycie} /> : null}
    </div>
  );
}

/**
 * Czego na mapie **nie ma**. Pusty obszar wygląda identycznie jak brak firm,
 * więc bez tej informacji mapa obiecuje kompletność, której nie ma.
 */
function Pokrycie({ dane }: { dane: MapCoverage }) {
  const razem = dane.with_coordinates + dane.without_coordinates;
  const udzial = razem > 0 ? Math.round((dane.with_coordinates / razem) * 100) : 0;
  return (
    <p className="hint">
      Na mapie widać {dane.with_coordinates.toLocaleString("pl")} z {razem.toLocaleString("pl")}{" "}
      adresów ({udzial}%). {dane.without_coordinates.toLocaleString("pl")} adresów nie udało się
      dopasować do punktu w Państwowym Rejestrze Granic. Osobno: 714 771 przedsiębiorców nie ma w
      CEIDG żadnego adresu, bo zaznaczyli brak stałego miejsca wykonywania działalności — nie
      pojawią się tu nigdy.
      {dane.refreshed_at
        ? ` Siatkę przeliczono ${new Date(dane.refreshed_at).toLocaleString("pl")}.`
        : " Siatki nie przeliczono ani razu — mapa jest pusta z tego powodu, nie z braku firm."}
    </p>
  );
}

/**
 * Największy dopuszczalny promień: połowa boku komórki **w pikselach**.
 *
 * Promień w wartościach bezwzględnych nie działa, bo ten sam licznik oznacza
 * inną gęstość na każdym poziomie przybliżenia. Przy widoku całego kraju
 * komórka 0,25 stopnia ma na ekranie kilkanaście pikseli — koła o promieniu
 * trzydziestu pikseli zlewały się w jednolitą plamę i mapa nie pokazywała nic
 * poza kształtem Polski.
 */
function maksymalnyPromien(mapa: LeafletMap, bok: number | null): number {
  if (bok === null) return 6;
  const srodek = mapa.getCenter();
  const a = mapa.latLngToContainerPoint([srodek.lat, srodek.lng]);
  const b = mapa.latLngToContainerPoint([srodek.lat, srodek.lng + bok]);
  return Math.max(2.5, Math.min((b.x - a.x) / 2, 26));
}

/** Pole koła odpowiada liczbie adresów, więc promień idzie z pierwiastka. */
function promien(adresow: number, maks: number, maksymalny: number): number {
  return Math.max(1.5, maksymalny * Math.sqrt(adresow / maks));
}

/**
 * Barwa niesie tę samą informację co promień, ale czytelną przy najmniejszych
 * komórkach — te mają dwa piksele i różnicy wielkości na nich nie widać.
 */
function barwa(adresow: number, maks: number): string {
  const udzial = Math.sqrt(adresow / maks);
  if (udzial > 0.6) return "#b91c1c";
  if (udzial > 0.35) return "#ea580c";
  if (udzial > 0.15) return "#ca8a04";
  return "#2563eb";
}

function opis(skupisko: MapCluster, bok: number | null): string {
  if (bok === null) {
    return `1 adres · ${skupisko.entities.toLocaleString("pl")} podmiotów`;
  }
  return (
    `${skupisko.addresses.toLocaleString("pl")} adresów · ` +
    `około ${skupisko.entities.toLocaleString("pl")} podmiotów`
  );
}
