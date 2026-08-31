"use client";

import { useEffect, useState } from "react";

interface Location {
  latitude: number;
  longitude: number;
  label: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

/**
 * Mapa siedziby podmiotu.
 *
 * Współrzędne pobieramy z API, które geokoduje adres **raz** i zapamiętuje wynik —
 * Nominatim dopuszcza jedno zapytanie na sekundę, więc geokodowanie przy każdym
 * wyświetleniu byłoby nadużyciem cudzej usługi.
 *
 * Sama mapa to `iframe` do OpenStreetMap: bez klucza API, bez biblioteki
 * i bez śledzenia użytkownika przez zewnętrznego dostawcę map.
 */
export function AddressMap({ entityId }: { entityId: string }) {
  const [location, setLocation] = useState<Location | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}/entities/${entityId}/location`)
      .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
      .then((data: Location) => {
        if (!cancelled) setLocation(data);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [entityId]);

  if (failed) {
    return (
      <section>
        <h2>Lokalizacja</h2>
        <p className="hint">
          Nie udało się ustalić współrzędnych tego adresu. Część adresów z rejestru nie występuje w
          OpenStreetMap albo jest zapisana w postaci, której geokoder nie rozpoznaje.
        </p>
      </section>
    );
  }

  if (!location) return null;

  // Wycinek mapy wokół punktu — około 400 m w każdą stronę.
  const span = 0.004;
  const bbox = [
    location.longitude - span,
    location.latitude - span,
    location.longitude + span,
    location.latitude + span,
  ].join("%2C");

  return (
    <section>
      <h2>Lokalizacja</h2>
      <iframe
        className="map"
        loading="lazy"
        src={`https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${location.latitude}%2C${location.longitude}`}
        title={`Mapa: ${location.label}`}
      />
      <p className="hint">
        {location.label} ·{" "}
        <a
          href={`https://www.openstreetmap.org/?mlat=${location.latitude}&mlon=${location.longitude}#map=17/${location.latitude}/${location.longitude}`}
          rel="noreferrer noopener"
          target="_blank"
        >
          otwórz w OpenStreetMap
        </a>
      </p>
    </section>
  );
}
