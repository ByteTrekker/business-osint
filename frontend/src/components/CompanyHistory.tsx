/**
 * Datowana historia podmiotu z odpisu KRS.
 *
 * To jedyne miejsce w aplikacji, gdzie widać, że coś **było inaczej**. CEIDG
 * i GLEIF dają wyłącznie stan bieżący, więc dla podmiotu bez odpisu ten
 * komponent świadomie nie pokazuje nic — pusta sekcja „historia" sugerowałaby,
 * że firma nigdy nic nie zmieniła, a to zwykle nieprawda.
 */

type HistoryEntry = {
  value: string;
  from: string | null;
  to: string | null;
};

type Props = {
  attributes: Record<string, unknown> | null | undefined;
};

function entries(attributes: Props["attributes"], key: string): HistoryEntry[] {
  const raw = attributes?.[key];
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (entry): entry is HistoryEntry =>
      typeof entry === "object" && entry !== null && "value" in entry,
  );
}

/** Kwota kapitału po polsku: `1 451 177 561,25 zł`. */
function money(value: string): string {
  const parsed = Number(value.replace(",", "."));
  if (!Number.isFinite(parsed)) return value;
  return `${parsed.toLocaleString("pl-PL", { maximumFractionDigits: 2 })} zł`;
}

function period(entry: HistoryEntry): string {
  if (!entry.from) return entry.to ? `do ${entry.to}` : "";
  // Wpis bez daty zamknięcia obowiązuje — mówimy to wprost, zamiast zostawiać
  // myślnik, który czyta się jak brak danych.
  return entry.to ? `${entry.from} – ${entry.to}` : `od ${entry.from}, obowiązuje`;
}

function Timeline({
  title,
  items,
  format,
}: {
  title: string;
  items: HistoryEntry[];
  format?: (value: string) => string;
}) {
  if (items.length < 2) return null;
  return (
    <div className="history__block">
      <h3 className="history__title">{title}</h3>
      <ol className="history__list">
        {items
          .slice()
          .reverse()
          .map((entry, index) => (
            <li
              key={`${entry.value}-${entry.from ?? index}`}
              className={
                entry.to === null ? "history__item history__item--current" : "history__item"
              }
            >
              <span className="history__value">{format ? format(entry.value) : entry.value}</span>
              <span className="history__period">{period(entry)}</span>
            </li>
          ))}
      </ol>
    </div>
  );
}

export default function CompanyHistory({ attributes }: Props) {
  const names = entries(attributes, "name_history");
  const capital = entries(attributes, "capital_history");
  const boardSize = attributes?.["board_size"];

  // Jedna nazwa i jeden kapitał to nie historia, tylko stan bieżący — jest już
  // pokazany wyżej w faktach.
  if (names.length < 2 && capital.length < 2) return null;

  return (
    <section className="history">
      <h2>Historia z KRS</h2>
      <Timeline title="Nazwa" items={names} />
      <Timeline title="Kapitał zakładowy" items={capital} format={money} />
      {typeof boardSize === "number" && boardSize > 0 && (
        <p className="history__note">
          W organie reprezentacji odnotowano {boardSize} wpisów. Rejestr maskuje dane osobowe, więc
          nie budujemy z nich węzłów osób.
        </p>
      )}
    </section>
  );
}
