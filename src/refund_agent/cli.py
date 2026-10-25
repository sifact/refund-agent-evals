"""Command-line entry point (``refund-agent``)."""

from typing import Annotated

import typer

from refund_agent.config import get_settings
from refund_agent.data import render_seed_sql

app = typer.Typer(help="Refund agent tools.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Keeps ``seed-sql`` a named subcommand even while it is the only one."""


@app.command("seed-sql")
def seed_sql(
    timezone: Annotated[
        str | None,
        typer.Option(help="Business timezone for purchase dates [default: TIMEZONE setting]."),
    ] = None,
) -> None:
    """Print the demo seed SQL (redirect into supabase/seed.sql)."""
    typer.echo(render_seed_sql(timezone or get_settings().timezone), nl=False)


if __name__ == "__main__":
    app()
