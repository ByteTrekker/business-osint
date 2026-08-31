"""CLI operacyjne: seed, ETL, przeliczanie stopni węzłów."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

import typer

from business_osint.etl.quality import QualityReport

app = typer.Typer(help="business-osint — narzędzia operacyjne")


# Kontrole jakości danych mają sens tylko wtedy, gdy ktoś je odpala. Moduł
# `etl.quality` powstał z opisem „uruchamiane po imporcie", a przez chwilę nie
# wołała go żadna komenda — dokładnie tak jak wcześniej nikt nie pisał zapytania,
# które wykryłoby 69 tys. fałszywych scaleń. Teraz każdy import kończy się
# raportem.
#
# Uruchamiamy je **w tej samej pętli zdarzeń** co import. Drugie `asyncio.run()`
# dostałoby połączenia przypięte do już zamkniętej pętli — ta pułapka kosztowała
# już raz debugowanie przy imporcie GLEIF.


async def _with_data_check[T](work: Awaitable[T]) -> tuple[T, QualityReport]:
    from business_osint.etl.quality import run_checks

    result = await work
    return result, await run_checks()


def _echo_data_check(report: QualityReport) -> None:
    """Wypisuje werdykt kontroli. **Nie** przerywa procesu kodem błędu.

    Kontrole mierzą stan całej bazy, nie tylko tego, co właśnie doszło. Import,
    który zrobił swoje, nie może wyglądać na nieudany z powodu długu sprzed
    tygodnia. Od twardej bramki jest `check-data`.
    """
    if report.ok:
        typer.echo(f"Kontrole danych: {len(report.results)}/{len(report.results)} OK")
        return
    typer.secho(
        f"Kontrole danych: {len(report.failed)} z {len(report.results)} NIEUDANE",
        fg=typer.colors.RED,
    )
    for result in report.failed:
        typer.echo(f"  [{result.check.invariant}] {result.check.name}: {result.violations}")
    typer.echo("Szczegóły: make data-check")


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

    def show(done: int) -> None:
        typer.echo(f"  zaktualizowano: {done:,}\r", nl=False)

    count = asyncio.run(recompute_degrees(progress=show))
    typer.echo(f"Zaktualizowano {count} encji.")


@app.command("check-data")
def check_data(
    deep: bool = typer.Option(
        False, "--deep", help="Dołącz kontrole pełnoprzeglądowe (wolne, minuty)"
    ),
) -> None:
    """Sprawdza niezmienniki na danych. Kod wyjścia 1, gdy któraś kontrola padnie."""
    from business_osint.etl.quality import format_report, run_checks

    report = asyncio.run(run_checks(deep=deep))
    for line in format_report(report):
        typer.echo(line)
    if not report.ok:
        raise typer.Exit(code=1)


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

    stats, report = asyncio.run(_with_data_check(ingest_single_krs(krs, registry=registry)))
    _echo_data_check(report)
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
        import_missing_counterparties,
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
            # Najpierw dociągamy podmioty, na które wskazują relacje — najczęściej
            # zagraniczne spółki matki. Bez nich krawędź traci jeden koniec
            # i przepada (3567 krawędzi przy pierwszym przebiegu).
            missing = await import_missing_counterparties()
            typer.echo(f"Dociągnięte kontrahenty: {missing.as_dict()}")
            rel_stats = await import_relationships()
            typer.echo(f"Relacje właścicielskie: {rel_stats.as_dict()}")
        from business_osint.etl.quality import run_checks

        _echo_data_check(await run_checks())

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

    stats, report = asyncio.run(
        _with_data_check(enrich_identifiers(limit=limit or None, progress=show))
    )
    typer.echo(f"\nBiała lista VAT: {stats.as_dict()}")
    _echo_data_check(report)


@app.command("import-bzp")
def import_bzp(days: int = typer.Option(30, help="Ile dni wstecz pobrać")) -> None:
    """Importuje ogłoszenia o zamówieniach publicznych (BZP, bez klucza)."""
    from business_osint.etl.bzp_pipeline import BzpStats, import_notices

    def show(stats: BzpStats) -> None:
        typer.echo(
            f"  strony: {stats.pages}, encje: +{stats.entities_created}, "
            f"relacje: +{stats.relationships_created}\r",
            nl=False,
        )

    stats, report = asyncio.run(_with_data_check(import_notices(days_back=days, progress=show)))
    typer.echo(f"\nBZP: {stats.as_dict()}")
    _echo_data_check(report)


@app.command("import-cit")
def import_cit(
    path: str = typer.Argument(..., help="Ścieżka do pliku .xls z wykazu MF"),
    dataset: str = typer.Option("pod", help="pod | pgk | nier"),
) -> None:
    """Importuje dane finansowe z wykazu podatników CIT (art. 27b)."""
    from business_osint.etl.cit_pipeline import import_cit_file

    stats, report = asyncio.run(_with_data_check(import_cit_file(path, dataset=dataset)))
    typer.echo(f"CIT [{dataset}]: {stats.as_dict()}")
    _echo_data_check(report)


@app.command("import-ceidg")
def import_ceidg(
    region: str = typer.Option("", help="Tylko jedno województwo (pusty = wszystkie)"),
) -> None:
    """Importuje CEIDG ze zrzutów zbiorczych hurtowni danych.

    Używa endpointu /raporty (17 żądań na całą Polskę), a nie /firmy, który
    przy limicie 25 rekordów na stronę wymagałby 100 tys. żądań.
    """
    from business_osint.config import get_settings
    from business_osint.etl.ceidg_pipeline import CeidgStats, import_all_regions

    settings = get_settings()
    if not settings.has_ceidg_access:
        typer.echo("Brak tokenu: ustaw BUSINESS_OSINT_CEIDG_TOKEN w .env", err=True)
        raise typer.Exit(1)

    def show(stats: CeidgStats, region_name: str) -> None:
        typer.echo(
            f"  [{stats.regions:2}] {region_name[:24]:26} "
            f"firmy={stats.companies:>7} osoby={stats.people:>7} "
            f"relacje={stats.relationships:>8}"
        )

    stats, report = asyncio.run(
        _with_data_check(
            import_all_regions(settings.ceidg_token, only_region=region or None, progress=show)
        )
    )
    typer.echo(f"\nCEIDG: {stats.as_dict()}")
    _echo_data_check(report)
    for err in stats.errors[:5]:
        typer.echo(f"  blad: {err}", err=True)


if __name__ == "__main__":
    app()
