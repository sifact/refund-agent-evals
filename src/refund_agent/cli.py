"""Command-line entry point (``refund-agent``)."""

import typer

from refund_agent.data.seed_sql import render_seed_sql

app = typer.Typer(help="Refund agent tools.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Keeps ``seed-sql`` a named subcommand even while it is the only one."""


@app.command("seed-sql")
def seed_sql() -> None:
    """Print the demo seed SQL (redirect into supabase/seed.sql)."""
    typer.echo(render_seed_sql(), nl=False)


if __name__ == "__main__":
    app()
