import Link from "next/link";

import { ClusterMap } from "@/components/ClusterMap";

export const metadata = {
  title: "Mapa firm — business-osint",
  description: "Rozmieszczenie zarejestrowanych podmiotów w Polsce.",
};

export default function MapaPage() {
  return (
    <>
      <h1>Mapa firm</h1>
      <p className="hint">
        Skupiska adresów zarejestrowanych podmiotów. Przybliż, żeby rozdzielić grupę na mniejsze; od
        czternastego poziomu widać pojedyncze adresy. <Link href="/">Wróć do wyszukiwarki</Link>.
      </p>
      <ClusterMap />
    </>
  );
}
