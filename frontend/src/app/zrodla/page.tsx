import Link from "next/link";

import { fetchSources } from "@/lib/api";

export const metadata = {
  title: "Źródła danych — business-osint",
  description: "Z jakich rejestrów pochodzą dane i czego w nich nie ma.",
};

// Liczniki mają odpowiadać stanowi bazy, a nie chwili budowania strony.
export const dynamic = "force-dynamic";

export default async function ZrodlaPage() {
  const dane = await fetchSources().catch(() => null);

  if (!dane) {
    return (
      <>
        <h1>Źródła danych</h1>
        <p className="hint">Nie udało się pobrać spisu źródeł z API.</p>
      </>
    );
  }

  return (
    <>
      <h1>Skąd są te dane</h1>
      <p className="lead">
        Wyłącznie rejestry publiczne i dane otwarte. Liczby poniżej pochodzą wprost z bazy — nie są
        przepisane z dokumentacji, więc nie rozjadą się z rzeczywistością po kolejnym imporcie.
      </p>

      <h2>Pobrane</h2>
      <div className="sources">
        {dane.active.map((z) => (
          <article key={z.kind} className="source">
            <header>
              <h3>{z.name}</h3>
              <span className="source__kind">{z.kind}</span>
            </header>
            <p>{z.what}</p>
            {z.caveat && (
              <p className="source__caveat">
                <strong>Czego tu nie ma:</strong> {z.caveat}
              </p>
            )}
            <dl className="source__figures">
              <div>
                <dt>krawędzi w grafie</dt>
                <dd>{z.relationships.toLocaleString("pl")}</dd>
              </div>
              <div>
                <dt>dokumentów źródłowych</dt>
                <dd>{z.documents.toLocaleString("pl")}</dd>
              </div>
              <div>
                <dt>ostatnie pobranie</dt>
                <dd>{z.last_fetch ? new Date(z.last_fetch).toLocaleDateString("pl") : "—"}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>

      <h2>Planowane</h2>
      <p className="hint">
        Kolejność nie jest przypadkowa: pierwsze pozycje nie wymagają żadnej decyzji, dalsze czekają
        na rozstrzygnięcie prawne albo na rozpoznanie techniczne.
      </p>
      <div className="sources">
        {dane.planned.map((z) => (
          <article key={z.name} className="source source--planned">
            <header>
              <h3>{z.name}</h3>
              {z.blocker ? (
                <span className="source__chip source__chip--held">czeka</span>
              ) : (
                <span className="source__chip source__chip--free">gotowe do wzięcia</span>
              )}
            </header>
            <p>{z.what}</p>
            {z.blocker && (
              <p className="source__caveat">
                <strong>Blokada:</strong> {z.blocker}
              </p>
            )}
          </article>
        ))}
      </div>

      <p className="hint">
        Każda krawędź w grafie ma zapisane pochodzenie — konkretny dokument, z którego wynika.{" "}
        <Link href="/">Wróć do wyszukiwarki</Link>.
      </p>
    </>
  );
}
