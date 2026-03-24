from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from carprice.models import PriceReport


def print_report(report: PriceReport, console: Console):
    """Print the full price report with listings and summary."""
    params = report.search_params
    trim_str = f" {params.trim}" if params.trim else ""

    # Group listings by source
    by_source: dict[str, list] = {}
    for listing in report.listings:
        by_source.setdefault(listing.source, []).append(listing)

    # Listings table — compact columns to fit terminal
    table = Table(
        title=f"{params.year} {params.make.title()} {params.model.title()}{trim_str} — {report.total_listings} Listings Found",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Source", style="cyan", width=10)
    table.add_column("Price", style="green bold", justify="right", width=10)
    table.add_column("Trim", width=8)
    table.add_column("Mileage", justify="right", width=10)
    table.add_column("Type", width=7)
    table.add_column("Location", width=15, overflow="ellipsis")
    table.add_column("Link", style="blue", overflow="ellipsis")

    idx = 1
    for source in sorted(by_source.keys()):
        listings = sorted(by_source[source], key=lambda l: l.price)
        for listing in listings:
            dealer_type = "Dealer" if listing.is_dealer else "Private"
            table.add_row(
                str(idx),
                listing.source,
                listing.price_str,
                listing.trim or "—",
                listing.mileage_str,
                dealer_type,
                listing.location or "—",
                listing.url or "—",
            )
            idx += 1

    console.print()
    console.print(table)
    console.print()

    # Summary panel
    summary_lines = []
    summary_lines.append(f"[bold]Total listings:[/bold] {report.total_listings}")
    summary_lines.append(f"[bold]Sources searched:[/bold] {', '.join(report.sources_searched)}")
    if report.sources_failed:
        summary_lines.append(f"[bold yellow]Sources failed:[/bold yellow] {', '.join(report.sources_failed)}")
    summary_lines.append("")
    summary_lines.append(f"[bold]Average price:[/bold]  ${report.average_price:,.0f}")
    summary_lines.append(f"[bold]Median price:[/bold]   ${report.median_price:,.0f}")
    summary_lines.append(f"[bold]Price range:[/bold]    ${report.price_low:,} — ${report.price_high:,}  (10th–90th percentile)")

    if report.kbb_value:
        summary_lines.append("")
        summary_lines.append("[bold underline]KBB Values:[/bold underline]")
        for key, val in report.kbb_value.items():
            summary_lines.append(f"  {key}: ${val:,.0f}")

    summary_lines.append("")
    summary_lines.append(f"[bold green]>>> Recommended price: ${report.recommended_price:,.0f}[/bold green]")

    if report.dealer_recommendation and report.private_recommendation:
        summary_lines.append(f"  [dim]Dealer: ${report.dealer_recommendation:,.0f}  |  Private party: ${report.private_recommendation:,.0f}[/dim]")

    console.print(Panel("\n".join(summary_lines), title="Price Summary", border_style="green"))
