import Link from "next/link";
import { counted } from "@/lib/plural";
import { api } from "@/lib/api";
import Pager from "@/components/Pager";

/**
 * Podmioty dzielące adres z oglądanym.
 *
 * Wspólny adres to najczęstszy widoczny ślad powiązania między spółkami, których
 * nie łączy ani wspólnik, ani nazwa. Jest też najczęstszym źródłem fałszywych
 * tropów — dlatego sekcja mówi wprost, ile ich jest, i nie sugeruje wniosku.
 */
type Props = {
  entityId: string;
  offset: number;
  /** Buduje adres strony dla podanego przesunięcia. */
  href: (offset: number) => string;
};

/**
 * Powyżej tylu sąsiadów adres jest niemal na pewno biurem wirtualnym,
 * skrzynką pocztową albo wsią, w której wszyscy mają ten sam numer domu.
 * Liczba jest z obserwacji: 456 podmiotów pod jednym adresem w Warszawie,
 * 434 w Sromowcach Wyżnych — tam akurat to 427 flisaków, nie oszustwo.
 */
const CROWDED = 25;

export default async function CoLocated({ entityId, offset, href }: Props) {
  const page = await api.coLocated(entityId, offset).catch(() => null);
  if (!page || page.meta.total === 0) return null;

  const total = page.meta.total ?? 0;

  return (
    <section>
      <h2>Pod tym samym adresem: {counted(total, "podmiot", "podmioty", "podmiotów")}</h2>

      {total > CROWDED && (
        <p className="hint">
          Adres z tak dużą liczbą podmiotów to zwykle biuro wirtualne albo miejscowość, w której
          numeracja jest wspólna. Sama liczba niczego nie dowodzi.
        </p>
      )}

      <ul className="hits">
        {page.items.map((item) => (
          <li key={item.id}>
            <Link href={`/entity/${item.id}`}>
              <span className={`badge badge--${item.type}`}>{item.type}</span>
              <strong>{item.name}</strong>
              {item.nip && <span className="hits__sub">NIP {item.nip}</span>}
              {/* Zakończony wpis oznaczamy datą, a nie samym wyszarzeniem:
                  „już tu nie siedzi” to inna informacja niż „siedzi”. */}
              {item.valid_to && <span className="hits__sub">do {item.valid_to}</span>}
            </Link>
          </li>
        ))}
      </ul>

      <Pager meta={page.meta} href={href} noun="podmiotów" />
    </section>
  );
}
