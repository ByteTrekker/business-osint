/**
 * Polska odmiana liczebnika.
 *
 * „1 powiązań" jest błędem, którego nie widać w testach ani w typach, a widzi
 * go każdy użytkownik. Reguła polska ma trzy formy, nie dwie jak angielska:
 * jeden, dwa–cztery, pięć i więcej — z wyjątkiem nastek, które zawsze biorą
 * formę trzecią (12 powiązań, nie „12 powiązania").
 */
export function plural(count: number, one: string, few: string, many: string): string {
  const abs = Math.abs(count);
  if (abs === 1) return one;

  const lastTwo = abs % 100;
  // 12, 13, 14 to nastki — mimo końcówki 2–4 biorą formę mnogą.
  if (lastTwo >= 12 && lastTwo <= 14) return many;

  const last = abs % 10;
  return last >= 2 && last <= 4 ? few : many;
}

/** Liczba razem z odmienionym rzeczownikiem: `1 powiązanie`, `22 powiązania`. */
export function counted(count: number, one: string, few: string, many: string): string {
  return `${count.toLocaleString("pl-PL")} ${plural(count, one, few, many)}`;
}
