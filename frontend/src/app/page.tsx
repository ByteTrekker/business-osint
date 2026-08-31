import Link from "next/link";
import { api } from "@/lib/api";
import Pager from "@/components/Pager";

export const dynamic = "force-dynamic";

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; offset?: string }>;
}) {
  const { q, offset: rawOffset } = await searchParams;
  const offset = Math.max(0, Number.parseInt(rawOffset ?? "0", 10) || 0);
  const results = q && q.length >= 2 ? await api.search(q, { offset }).catch(() => null) : null;

  return (
    <>
      <h1>Kto stoi za tą firmą?</h1>
      <p className="lead">
        Wyszukaj po nazwie, NIP, KRS lub REGON, a następnie klikaj kolejne węzły grafu, żeby
        prześledzić powiązania osobowe i kapitałowe.
      </p>

      <form action="/" method="get" className="search">
        <input
          type="search"
          name="q"
          defaultValue={q ?? ""}
          placeholder="np. ALFA TECHNOLOGIE albo 5252445170"
          minLength={2}
          required
          autoFocus
        />
        <button type="submit">Szukaj</button>
      </form>

      {results && results.hits.length === 0 && <p>Brak wyników dla „{q}”.</p>}

      {results && results.hits.length > 0 && (
        <ul className="hits">
          {results.hits.map((hit) => (
            <li key={hit.id}>
              <Link href={`/entity/${hit.id}`}>
                <span className={`badge badge--${hit.type}`}>{hit.type}</span>
                <strong>{hit.name}</strong>
                {hit.subtitle && <span className="hits__sub">{hit.subtitle}</span>}
                <span className="hits__degree">{hit.degree} powiązań</span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {results && (
        <Pager
          meta={results.meta}
          href={(next) => `/?q=${encodeURIComponent(q ?? "")}&offset=${next}`}
        />
      )}
    </>
  );
}
