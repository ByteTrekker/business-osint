/**
 * Numery LEI podmiotu razem ze stanem rejestracji.
 *
 * GLEIF nie gwarantuje jednego LEI na podmiot i nie wycofuje starych numerów.
 * Bez stanu rejestracji dwa LEI-e przy jednej spółce wyglądają jak błąd
 * scalania po naszej stronie — a są normalnym stanem rejestru: 22 spółki w bazie
 * mają po dwa numery, każda przy jednym KRS-ie.
 *
 * Ważniejsza liczba: **15 424 spółek ma LEI oznaczony `LAPSED`**, czyli numer,
 * którego nikt już nie utrzymuje. To informacja o podmiocie, nie o naszych
 * danych, i dotąd leżała nieużywana w pobranych dokumentach.
 */

type LeiRecord = {
  lei: string;
  status: string | null;
  name: string | null;
};

type Props = {
  attributes: Record<string, unknown> | null | undefined;
  /** Nazwa, pod którą podmiot występuje dzisiaj — do wykrycia dawnych nazw. */
  currentName: string;
};

/** Etykiety po polsku; stan nieznany zostaje w oryginale, żeby nie zmyślać. */
const LABELS: Record<string, string> = {
  ISSUED: "aktualny",
  LAPSED: "wygasły",
  DUPLICATE: "duplikat",
  RETIRED: "wycofany",
  ANNULLED: "unieważniony",
  MERGED: "po połączeniu",
};

function records(attributes: Props["attributes"]): LeiRecord[] {
  const raw = attributes?.["lei_records"];
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (item): item is LeiRecord => typeof item === "object" && item !== null && "lei" in item,
  );
}

export default function LeiRecords({ attributes, currentName }: Props) {
  const items = records(attributes);
  // Jeden aktualny numer nie wymaga tłumaczenia — pokazujemy go tam, gdzie
  // resztę identyfikatorów. Sekcja ma sens, gdy jest co wyjaśnić.
  if (items.length === 0) return null;
  if (items.length === 1 && items[0].status === "ISSUED") return null;

  return (
    <section className="lei">
      <h2>Numery LEI</h2>
      <ul className="lei__list">
        {items.map((item) => {
          const label = item.status ? (LABELS[item.status] ?? item.status.toLowerCase()) : null;
          const formerName = item.name && item.name !== currentName ? item.name : null;
          return (
            <li key={item.lei} className="lei__item">
              <code className="lei__code">{item.lei}</code>
              {label && (
                <span
                  className={
                    item.status === "ISSUED" ? "lei__status lei__status--current" : "lei__status"
                  }
                >
                  {label}
                </span>
              )}
              {formerName && <span className="lei__name">wydany na: {formerName}</span>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
