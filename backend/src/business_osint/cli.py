"""CLI operacyjne: seed, ETL, przeliczanie stopni węzłów."""

from __future__ import annotations

import asyncio

import typer

app = typer.Typer(help="business-osint — narzędzia operacyjne")


@app.command()
def seed(demo: bool = typer.Option(True, help="Załaduj syntetyczny zestaw demonstracyjny")) -> None:
    """Wypełnia bazę danymi startowymi (działa bez dostępu do rejestrów)."""
    from business_osint.etl.seed_demo import run_seed

    asyncio.run(run_seed(demo=demo))
    typer.echo("Seed zakończony.")


@app.command("refresh-degrees")
def refresh_degrees() -> None:
    """Przelicza zdenormalizowany stopień węzłów (entities.degree)."""
    from business_osint.etl.maintenance import recompute_degrees

    count = asyncio.run(recompute_degrees())
    typer.echo(f"Zaktualizowano {count} encji.")


@app.command("ingest-krs")
def ingest_krs(
    krs: str = typer.Argument(..., help="Numer KRS, np. 0000006865"),
    registry: str = typer.Option("P", help="P = przedsiębiorcy, S = stowarzyszenia"),
) -> None:
    """Pobiera odpis z API KRS i ładuje go do bazy wraz z provenance.

    Uwaga: publiczne API KRS zwraca dane osobowe zanonimizowane (pierwsza litera
    i długość nazwiska). Komenda służy do wzbogacania profilu pojedynczej firmy
    na żądanie, a nie do masowego przemiatania rejestru.
    """
    from business_osint.etl.pipeline import ingest_single_krs

    stats = asyncio.run(ingest_single_krs(krs, registry=registry))
    typer.echo(stats)


@app.command("import-gleif")
def import_gleif(
    country: str = typer.Option("PL", help="Kod kraju wg ISO 3166-1 alpha-2"),
    max_pages: int = typer.Option(0, help="Ogranicz liczbę stron (0 = wszystkie)"),
    relationships: bool = typer.Option(True, help="Pobierz też relacje właścicielskie"),
) -> None:
    """Importuje rekordy LEI i relacje właścicielskie z GLEIF (licencja CC0)."""
    from business_osint.etl.gleif_pipeline import (
        GleifImportStats,
        import_lei_records,
        import_relationships,
    )

    def show(stats: GleifImportStats) -> None:
        typer.echo(
            f"  strony: {stats.pages}, encje: +{stats.entities_created}"
            f" / ={stats.entities_matched}, relacje: +{stats.relationships_created}\r",
            nl=False,
        )

    async def run_all() -> None:
        # Oba kroki w jednej pętli zdarzeń: silnik bazy jest cache'owany globalnie,
        # więc drugie asyncio.run() dostałoby połączenia przypięte do już zamkniętej
        # pętli ("attached to a different loop").
        stats = await import_lei_records(
            country=country, max_pages=max_pages or None, progress=show
        )
        typer.echo(f"\nRekordy LEI: {stats.as_dict()}")
        if relationships:
            rel_stats = await import_relationships()
            typer.echo(f"Relacje właścicielskie: {rel_stats.as_dict()}")

    asyncio.run(run_all())


@app.command("enrich-whitelist")
def enrich_whitelist(
    limit: int = typer.Option(0, help="Ogranicz liczbę numerów NIP (0 = wszystkie)"),
) -> None:
    """Dopina REGON i KRS z białej listy VAT do podmiotów, które mają już NIP."""
    from business_osint.etl.whitelist_pipeline import WhitelistStats, enrich_identifiers

    def show(stats: WhitelistStats) -> None:
        typer.echo(
            f"  sprawdzone NIP-y: {stats.nips_checked}, "
            f"dopięte identyfikatory: {stats.identifiers_added}\r",
            nl=False,
        )

    stats = asyncio.run(enrich_identifiers(limit=limit or None, progress=show))
    typer.echo(f"\nBiała lista VAT: {stats.as_dict()}")


if __name__ == "__main__":
    app()
