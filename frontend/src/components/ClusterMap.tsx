"use client";

import { useEffect, useRef, useState } from "react";
import type { Map as LeafletMap, CircleMarker } from "leaflet";

import {
  api,
  fetchMapClusters,
  fetchMapCoverage,
  type CoLocated,
  type MapCluster,
  type MapCoverage,
} from "@/lib/api";

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
  // osierocona instancja. Ze stanem tworzenie jest synchroniczne i paruje się
  // ze sprzątaniem jeden do jednego.
  const [L, setL] = useState<typeof import("leaflet") | null>(null);
  const kontener = useRef<HTMLDivElement>(null);
  const [pokrycie, setPokrycie] = useState<MapCoverage | null>(null);
  const [przyciete, setPrzyciete] = useState(false);
  const [blad, setBlad] = useState<string | null>(null);
  const [laduje, setLaduje] = useState(true);

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

    // Stan mapy żyje **w domknięciu tego efektu**, nie w `useRef`.
    //
    // Wcześniej mapa siedziała w refie, a odświeżanie czytało `mapa.current`.
    // Ref jest wspólny dla wszystkich przebiegów efektu, a sprzątanie ustawiało
    // go na `null` — przy podwójnym montowaniu zerowanie po pierwszym przebiegu
    // trafiało w mapę utworzoną przez drugi. Odświeżanie **cicho wychodziło**
    // przez `if (!instancja) return`, więc mapa przestawała reagować na
    // przesuwanie i na kliknięcia, nie zgłaszając żadnego błędu.
    let znaczniki: CircleMarker[] = [];
    let zadanie: AbortController | null = null;

    const odswiez = async (): Promise<void> => {
      zadanie?.abort();
      const kontroler = new AbortController();
      zadanie = kontroler;
      setLaduje(true);

      const granice = instancja.getBounds();
      const wycinek = {
        south: Math.max(granice.getSouth(), OBSZAR_DANYCH.south),
        north: Math.min(granice.getNorth(), OBSZAR_DANYCH.north),
        west: Math.max(granice.getWest(), OBSZAR_DANYCH.west),
        east: Math.min(granice.getEast(), OBSZAR_DANYCH.east),
      };
      // Prostokąt pusty: albo widok jest poza obszarem danych, albo mapa nie
      // zna jeszcze swojego rozmiaru i `getBounds()` zwraca punkt. Drugi
      // przypadek naprawia `invalidateSize()` niżej — tutaj tylko nie pytamy
      // o pustkę.
      if (wycinek.north <= wycinek.south || wycinek.east <= wycinek.west) {
        znaczniki.forEach((m) => m.remove());
        znaczniki = [];
        setLaduje(false);
        return;
      }

      try {
        const widok = await fetchMapClusters(wycinek, instancja.getZoom(), kontroler.signal);

        // Na poziomie zgrubnym niesie informację liczba adresów, na
        // szczegółowym zawsze równa jeden — tam liczy się, ile podmiotów siedzi
        // pod tym jednym adresem. Skalowanie po `addresses` dawało na poziomie
        // szczegółowym same jednakowe, czerwone kropki: maksimum równe jeden,
        // więc każdy znacznik wychodził największy i najgorętszy.
        const waga = (c: MapCluster) => (widok.cell_degrees === null ? c.entities : c.addresses);
        const maks = Math.max(1, ...widok.clusters.map(waga));
        const promienKomorki = maksymalnyPromien(instancja, widok.cell_degrees);

        znaczniki.forEach((m) => m.remove());
        znaczniki = widok.clusters.map((skupisko) =>
          L.circleMarker([skupisko.latitude, skupisko.longitude], {
            radius: promien(waga(skupisko), maks, promienKomorki),
            color: barwa(waga(skupisko), maks),
            weight: 1,
            fillColor: barwa(waga(skupisko), maks),
            fillOpacity: 0.65,
          })
            .bindTooltip(opis(skupisko, widok.cell_degrees), { direction: "top" })
            .on("click", () => klikniecie(L, instancja, skupisko))
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
    };

    instancja.on("moveend", () => void odswiez());

    // Leaflet mierzy kontener w momencie tworzenia mapy. Przy pierwszym
    // renderowaniu wysokość z arkusza stylów bywa jeszcze nienałożona, więc
    // mapa zapamiętuje rozmiar bliski zeru: `getBounds()` zwraca wtedy niemal
    // punkt, prostokąt widoku wychodzi pusty i **nic się nie dzieje** — bez
    // żądania, bez znaczników i bez błędu. Widać tylko wąski pasek kafli.
    //
    // `ResizeObserver` zamiast jednorazowego `invalidateSize()`, bo ten sam
    // problem wraca przy każdej zmianie rozmiaru okna, której dotąd nie
    // obsługiwaliśmy wcale.
    const obserwator = new ResizeObserver(() => {
      instancja.invalidateSize();
    });
    obserwator.observe(instancja.getContainer());

    // `resize` leci z `invalidateSize()`; `moveend` nie zawsze, bo środek mapy
    // się nie zmienia — a prostokąt widoku owszem.
    instancja.on("resize", () => void odswiez());
    void odswiez();

    return () => {
      obserwator.disconnect();
      zadanie?.abort();
      instancja.remove();
    };
  }, [L]);

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
 * Kliknięcie w znacznik.
 *
 * Na poziomie zgrubnym skupisko obejmuje setki adresów i lista podmiotów nie
 * miałaby sensu — przybliżamy, czyli robimy to, po co użytkownik kliknął.
 * Dopiero pojedynczy adres ma o czym opowiadać.
 */
function klikniecie(L: typeof import("leaflet"), mapa: LeafletMap, skupisko: MapCluster): void {
  if (!skupisko.address_id) {
    mapa.flyTo([skupisko.latitude, skupisko.longitude], Math.min(mapa.getZoom() + 3, 17));
    return;
  }

  const dymek = L.popup({ maxWidth: 340, maxHeight: 320 })
    .setLatLng([skupisko.latitude, skupisko.longitude])
    .setContent(`<strong>${escapuj(skupisko.label ?? "Adres")}</strong><p>Wczytywanie…</p>`)
    .openOn(mapa);

  void api
    .coLocated(skupisko.address_id)
    .then((odpowiedz) => {
      dymek.setContent(trescDymka(skupisko, odpowiedz.items, odpowiedz.meta.total));
    })
    .catch(() => {
      dymek.setContent(
        `<strong>${escapuj(skupisko.label ?? "Adres")}</strong>` +
          `<p>Nie udało się wczytać podmiotów pod tym adresem.</p>`,
      );
    });
}

function trescDymka(skupisko: MapCluster, podmioty: CoLocated[], razem: number | null): string {
  const naglowek = `<strong>${escapuj(skupisko.label ?? "Adres")}</strong>`;
  if (podmioty.length === 0) {
    // Adres bez podmiotów istnieje: mógł zostać dodany przez scalanie albo
    // wszystkie wpisy pod nim zostały wykreślone.
    return `${naglowek}<p>Brak podmiotów zarejestrowanych pod tym adresem.</p>`;
  }

  const wiersze = podmioty
    .map((p) => {
      const opisy = [p.nip ? `NIP ${p.nip}` : null, p.krs ? `KRS ${p.krs}` : null, p.status]
        .filter(Boolean)
        .join(" · ");
      return (
        `<li><a href="/entity/${p.id}">${escapuj(p.name)}</a>` +
        (opisy ? `<span>${escapuj(opisy)}</span>` : "") +
        `</li>`
      );
    })
    .join("");

  const brakuje = razem !== null && razem > podmioty.length ? razem - podmioty.length : 0;
  const stopka = brakuje
    ? `<p><a href="/entity/${skupisko.address_id}">Pokaż wszystkie ${razem}</a></p>`
    : "";
  return `${naglowek}<ul class="dymek">${wiersze}</ul>${stopka}`;
}

/**
 * Treść dymka składamy z napisów, więc nazwa podmiotu z bazy trafia do HTML-a.
 * Nazwy firm bywają dowolnym tekstem z rejestru i nie są przez nikogo
 * sanityzowane — bez tego jedna nazwa z nawiasem kątowym psuje dymek, a w gorszym
 * przypadku wstrzykuje znacznik.
 */
function escapuj(tekst: string): string {
  const element = document.createElement("div");
  element.textContent = tekst;
  return element.innerHTML;
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

/** Pole koła odpowiada liczbie, więc promień idzie z pierwiastka. */
function promien(ile: number, maks: number, maksymalny: number): number {
  return Math.max(1.5, maksymalny * Math.sqrt(ile / maks));
}

/**
 * Barwa niesie tę samą informację co promień, ale czytelną przy najmniejszych
 * komórkach — te mają dwa piksele i różnicy wielkości na nich nie widać.
 */
function barwa(ile: number, maks: number): string {
  const udzial = Math.sqrt(ile / maks);
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
