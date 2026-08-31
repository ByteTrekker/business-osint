"use client";

import { useState } from "react";
import { describePkd, splitPkdList } from "@/lib/pkd";

/**
 * Lista kodów PKD z opisem działu. Zwinięta domyślnie, bo JDG potrafi mieć
 * kilkadziesiąt kodów pobocznych i rozwinięta zepchnęłaby graf poniżej ekranu.
 */
export function PkdList({ main, other }: { main: string | null; other: unknown }) {
  const [open, setOpen] = useState(false);
  const others = splitPkdList(other).filter((code) => code !== main);

  if (!main && others.length === 0) return null;

  return (
    <div className="pkd">
      {main && (
        <div className="pkd__row pkd__row--main">
          <code className="pkd__code">{main}</code>
          <span className="pkd__desc">{describePkd(main) ?? "kod nierozpoznany"}</span>
        </div>
      )}

      {others.length > 0 && (
        <>
          <button className="pkd__toggle" onClick={() => setOpen(!open)} type="button">
            {open ? "▾ ukryj" : "▸ pokaż"} {others.length} pozostałych kodów
          </button>
          {open && (
            <div className="pkd__list">
              {others.map((code) => (
                <div className="pkd__row" key={code}>
                  <code className="pkd__code">{code}</code>
                  <span className="pkd__desc">{describePkd(code) ?? "kod nierozpoznany"}</span>
                </div>
              ))}
              <p className="pkd__note">
                Opisy na poziomie działu PKD 2007 — GUS nie publikuje klasyfikacji klas jako danych,
                a zgadywanie opisów byłoby wprowadzaniem w błąd.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
