from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import click
from rich.console import Console

from carprice.models import SearchParams
from carprice.normalizer import normalize_listings
from carprice.analyzer import analyze
from carprice.output import print_report

console = Console()

# All available scrapers, lazily imported
SCRAPER_REGISTRY = {
    "cargurus": "carprice.scrapers.cargurus:CarGurusScraper",
    "craigslist": "carprice.scrapers.craigslist:CraigslistScraper",
    "carscom": "carprice.scrapers.carscom:CarsComScraper",
    "autotrader": "carprice.scrapers.autotrader:AutoTraderScraper",
    "kbb": "carprice.scrapers.kbb:KBBScraper",
    "carfax": "carprice.scrapers.carfax:CarFaxScraper",
    "facebook": "carprice.scrapers.facebook:FacebookScraper",
}

# Default sources (excludes facebook which is opt-in)
DEFAULT_SOURCES = ["cargurus", "craigslist", "carscom", "autotrader", "carfax"]


def _load_scraper(name: str):
    """Dynamically import and instantiate a scraper by registry name."""
    module_path, class_name = SCRAPER_REGISTRY[name].rsplit(":", 1)
    import importlib
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls()


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose):
    """Car Price Lookup — find what to pay across multiple sources."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


@cli.command()
@click.option("--year", required=True, type=int, help="Vehicle year")
@click.option("--make", required=True, type=str, help="Vehicle make (e.g. toyota)")
@click.option("--model", required=True, type=str, help="Vehicle model (e.g. camry)")
@click.option("--trim", default=None, type=str, help="Vehicle trim (e.g. SE, XLE)")
@click.option("--mileage", required=True, type=int, help="Target mileage")
@click.option("--zip", "zip_code", required=True, type=str, help="Your zip code")
@click.option("--radius", default=100, type=int, help="Search radius in miles (default: 100)")
@click.option("--sources", default=None, type=str, help="Comma-separated sources (e.g. cargurus,craigslist)")
@click.option("--include-facebook", is_flag=True, help="Include Facebook Marketplace (requires login)")
@click.option("--include-kbb", is_flag=True, help="Include KBB valuation (requires Chrome)")
def search(year, make, model, trim, mileage, zip_code, radius, sources, include_facebook, include_kbb):
    """Search for car prices across multiple sources."""
    params = SearchParams(
        year=year,
        make=make,
        model=model,
        trim=trim,
        mileage=mileage,
        zip_code=zip_code,
        radius_miles=radius,
    )

    # Determine which sources to use
    if sources:
        source_list = [s.strip().lower() for s in sources.split(",")]
        invalid = [s for s in source_list if s not in SCRAPER_REGISTRY]
        if invalid:
            console.print(f"[red]Unknown sources: {', '.join(invalid)}[/red]")
            console.print(f"Available: {', '.join(SCRAPER_REGISTRY.keys())}")
            return
    else:
        source_list = list(DEFAULT_SOURCES)
        if include_facebook:
            source_list.append("facebook")
        if include_kbb:
            source_list.append("kbb")

    trim_str = f" {trim}" if trim else ""
    console.print(
        f"\n[bold]Searching for {year} {make} {model}{trim_str}[/bold] "
        f"({mileage:,} mi) within {radius} mi of {zip_code}\n"
    )

    # Load and run scrapers concurrently
    all_listings = []
    sources_searched = []
    sources_failed = []

    scrapers = {}
    for name in source_list:
        try:
            scrapers[name] = _load_scraper(name)
        except Exception as e:
            console.print(f"[yellow]⚠ Could not load {name}: {e}[/yellow]")
            sources_failed.append(name)

    with console.status("[bold green]Scraping sources...") as status:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(scraper.search, params): name
                for name, scraper in scrapers.items()
            }

            for future in as_completed(futures):
                name = futures[future]
                try:
                    listings = future.result(timeout=120)
                    all_listings.extend(listings)
                    sources_searched.append(name)
                    status.update(f"[bold green]Got {len(listings)} from {name} ({len(all_listings)} total)")
                except Exception as e:
                    console.print(f"[yellow]⚠ {name} failed: {e}[/yellow]")
                    sources_failed.append(name)

    if not all_listings:
        console.print("[red]No listings found from any source.[/red]")
        return

    # Normalize and analyze
    normalized = normalize_listings(all_listings, params)
    report = analyze(normalized, params, sources_searched, sources_failed)
    print_report(report, console)


def main():
    cli()


if __name__ == "__main__":
    main()
