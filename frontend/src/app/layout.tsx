import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "business-osint — graf powiązań polskich firm",
  description:
    "Wyszukaj firmę i zobacz, jak jest powiązana z innymi firmami i osobami. Dane z rejestrów publicznych.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pl">
      <body>
        <header className="topbar">
          <Link href="/" className="topbar__brand">
            business-osint
          </Link>
          <span className="topbar__tag">dane z rejestrów publicznych</span>
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
