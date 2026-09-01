import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import Link from "next/link";
import "leaflet/dist/leaflet.css";
import "./globals.css";

// IBM Plex, bo ma komplet polskiej diakrytyki narysowany, a nie doklejony,
// i techniczny charakter pasujący do danych z rejestrów. `next/font` hostuje
// je u nas — bez zapytania do Google przy każdym wejściu i bez skoku układu,
// gdy krój dojedzie.
//
// Mono nie jest ozdobnikiem: NIP, KRS, REGON i daty to ciągi cyfr, które mają
// się wyrównywać w kolumnie. W kroju proporcjonalnym jedynka jest węższa od
// ósemki i numery przestają być porównywalne wzrokiem.
const plexSans = IBM_Plex_Sans({
  subsets: ["latin-ext"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin-ext"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "business-osint — graf powiązań polskich firm",
  description:
    "Wyszukaj firmę i zobacz, jak jest powiązana z innymi firmami i osobami. Dane z rejestrów publicznych.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pl" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body>
        <header className="topbar">
          <Link href="/" className="topbar__brand">
            business-osint
          </Link>
          <nav className="topbar__nav">
            <Link href="/mapa">mapa</Link>
          </nav>
          <span className="topbar__tag">dane z rejestrów publicznych</span>
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
