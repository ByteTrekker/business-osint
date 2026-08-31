import Link from "next/link";
import type { PageMeta } from "@/lib/api";

/**
 * Nawigacja między stronami wyników.
 *
 * Świadomie bez numerów stron. Wyszukiwarka nie zna liczby wszystkich
 * dopasowań — policzenie ich przy prefiksie „a" oznaczałoby przejście przez
 * 830 tys. wierszy — więc „strona 7 z 12" byłaby liczbą wziętą z sufitu.
 * Pokazujemy zakres, który faktycznie mamy, i mówimy wprost, czy jest dalej.
 */
type Props = {
  meta: PageMeta;
  /** Buduje adres dla podanego przesunięcia. */
  href: (offset: number) => string;
  /** Nazwa liczonych rzeczy w dopełniaczu, np. „wyników”. */
  noun?: string;
};

export default function Pager({ meta, href, noun = "wyników" }: Props) {
  const { limit, offset, returned, has_more, total } = meta;
  if (offset === 0 && !has_more) return null;

  const from = offset + 1;
  const to = offset + returned;
  const range =
    total === null ? `${from}–${to}` : `${from}–${to} z ${total.toLocaleString("pl-PL")}`;

  return (
    <nav className="pager" aria-label={`Strony ${noun}`}>
      {offset > 0 ? (
        <Link className="pager__link" href={href(Math.max(0, offset - limit))}>
          ← poprzednia
        </Link>
      ) : (
        <span className="pager__link pager__link--off">← poprzednia</span>
      )}

      <span className="pager__range">
        {range} {noun}
      </span>

      {has_more ? (
        <Link className="pager__link" href={href(offset + limit)}>
          następna →
        </Link>
      ) : (
        <span className="pager__link pager__link--off">następna →</span>
      )}
    </nav>
  );
}
