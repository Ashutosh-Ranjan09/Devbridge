"""`chat serve` and `chat keygen`."""

from __future__ import annotations

from typing import Annotated

import typer

from chat.config import settings
from chat.crypto import MissingKeyError, load_key, new_key

app = typer.Typer(help="DevBridge chat: a recruiter and a candidate, one thread per application.",
                  no_args_is_help=True)


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    # 8090: cvv is on 8080, assessment on 8070, M6 on 8300.
    port: Annotated[int, typer.Option(help="Port.")] = 8090,
) -> None:
    """Run the HTTP surface the web calls. Localhost unless told otherwise."""
    try:
        load_key(settings.encryption_key)
    except MissingKeyError as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(1) from exc
    import uvicorn

    from chat.api import API_KEY
    from chat.api import app as api

    if settings.api_key is None:
        typer.secho("CHAT_API_KEY is unset, so one was generated for this run:", fg="yellow", err=True)
        typer.secho(f"    {API_KEY}", fg="yellow", bold=True, err=True)
    uvicorn.run(api, host=host, port=port)


@app.command()
def keygen() -> None:
    """Print a new encryption key, for CHAT_ENCRYPTION_KEY in chat/.env."""
    typer.echo(new_key())
