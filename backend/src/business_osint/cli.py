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
    krs: str = typer.Argument(..., help="Numer KRS, np. 0000030897"),
    registry: str = typer.Option("P", help="P = przedsiębiorcy, S = stowarzyszenia"),
) -> None:
    """Pobiera odpis z API KRS i ładuje go do bazy wraz z provenance."""
    from business_osint.etl.pipeline import ingest_single_krs

    stats = asyncio.run(ingest_single_krs(krs, registry=registry))
    typer.echo(stats)


if __name__ == "__main__":
    app()
