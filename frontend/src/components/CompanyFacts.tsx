import type { EntityProfile } from "@/lib/api";
import { PkdList } from "@/components/PkdList";
import { AddressMap } from "@/components/AddressMap";

/** CEIDG podaje pozostałe kody PKD sklejone separatorem `$##$`. */
function splitPkd(value: unknown): string[] {
  if (typeof value !== "string" || !value) return [];
  return value.split("$##$").filter(Boolean);
}

function attr(profile: EntityProfile, key: string): string | null {
  const attributes = (profile.company?.attributes ?? {}) as Record<string, unknown>;
  const value = attributes[key];
  return typeof value === "string" && value ? value : null;
}

const STATUS_LABELS: Record<string, { label: string; tone: string }> = {
  active: { label: "aktywna", tone: "ok" },
  suspended: { label: "zawieszona", tone: "warn" },
  deleted: { label: "wykreślona", tone: "bad" },
  pending: { label: "oczekuje na rozpoczęcie", tone: "warn" },
  partnership_only: { label: "tylko w formie spółki cywilnej", tone: "warn" },
};

/** Zdarzenia z życia podmiotu, w kolejności chronologicznej. */
function lifecycle(profile: EntityProfile): { date: string; label: string }[] {
  const company = profile.company as Record<string, unknown> | null;
  if (!company) return [];
  const events: { date: string; label: string }[] = [];
  const push = (date: unknown, label: string) => {
    if (typeof date === "string" && date) events.push({ date: date.slice(0, 10), label });
  };
  push(company.registered_on, "rozpoczęcie działalności");
  push(attr(profile, "suspended_on"), "zawieszenie");
  push(attr(profile, "resumed_on"), "wznowienie");
  push(company.deregistered_on, "zakończenie");
  return events.sort((a, b) => a.date.localeCompare(b.date));
}

function money(value: number | null): string {
  if (value === null) return "—";
  const millions = value / 1_000_000;
  if (Math.abs(millions) >= 1000) return `${(millions / 1000).toFixed(1)} mld zł`;
  if (Math.abs(millions) >= 1) return `${millions.toFixed(1)} mln zł`;
  return `${value.toLocaleString("pl-PL")} zł`;
}

export function CompanyFacts({ profile }: { profile: EntityProfile }) {
  const company = profile.company as Record<string, unknown> | null;
  if (!company) return null;

  const status = typeof company.status === "string" ? STATUS_LABELS[company.status] : undefined;
  const events = lifecycle(profile);
  const otherPkd = splitPkd(attr(profile, "pkd_other"));
  // Odpowiedź z cache'u może pochodzić sprzed dodania pola — komponent nie
  // ma prawa wywalić strony z powodu brakującej sekcji.
  const financials = profile.financials ?? [];
  const address = [
    attr(profile, "city"),
    attr(profile, "gmina") !== attr(profile, "city") ? attr(profile, "gmina") : null,
    // W miastach na prawach powiatu powiat powtarza nazwę miasta — wtedy milczy.
    attr(profile, "powiat") !== attr(profile, "city") ? attr(profile, "powiat") : null,
    attr(profile, "wojewodztwo"),
  ].filter(Boolean);

  const phone = attr(profile, "phone");
  const email = attr(profile, "email");
  const www = attr(profile, "www");

  return (
    <>
      <section className="facts">
        <h2>Dane podstawowe</h2>
        <dl className="facts__grid">
          {status && (
            <>
              <dt>Status</dt>
              <dd>
                <span className={`status status--${status.tone}`}>{status.label}</span>
              </dd>
            </>
          )}
          {(typeof company.pkd_main === "string" || otherPkd.length > 0) && (
            <>
              <dt>PKD</dt>
              <dd>
                <PkdList
                  main={typeof company.pkd_main === "string" ? company.pkd_main : null}
                  other={attr(profile, "pkd_other")}
                />
              </dd>
            </>
          )}
          {address.length > 0 && (
            <>
              <dt>Lokalizacja</dt>
              <dd>{address.join(", ")}</dd>
            </>
          )}
          {(phone || email || www) && (
            <>
              <dt>Kontakt</dt>
              <dd className="facts__contact">
                {phone && <span>{phone}</span>}
                {email && <a href={`mailto:${email}`}>{email}</a>}
                {www && (
                  <a
                    href={www.startsWith("http") ? www : `https://${www}`}
                    rel="noreferrer noopener"
                    target="_blank"
                  >
                    {www}
                  </a>
                )}
              </dd>
            </>
          )}
        </dl>
      </section>

      <AddressMap entityId={profile.id} />

      {events.length > 0 && (
        <section>
          <h2>Oś życia podmiotu</h2>
          <ol className="timeline">
            {events.map((event) => (
              <li key={`${event.date}-${event.label}`}>
                <span className="timeline__date">{event.date}</span>
                <span className="timeline__label">{event.label}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {financials.length > 0 && (
        <section>
          <h2>Dane finansowe</h2>
          <p className="hint">
            Z wykazu podatników CIT (art. 27b) — podmioty o przychodzie powyżej 50 mln EUR.
          </p>
          <table className="rels">
            <thead>
              <tr>
                <th>Rok</th>
                <th>Przychód</th>
                <th>Koszty</th>
                <th>Dochód</th>
                <th>Podatek należny</th>
              </tr>
            </thead>
            <tbody>
              {financials.map((report) => (
                <tr key={report.period_to}>
                  <td>{report.period_from.slice(0, 4)}</td>
                  <td>{money(report.revenue)}</td>
                  <td>{money(report.costs)}</td>
                  <td>{money(report.income)}</td>
                  <td>{money(report.tax_due)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
