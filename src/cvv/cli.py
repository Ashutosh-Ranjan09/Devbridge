"""The command line — `cvv verify cv.pdf`.

Thin by design: parse arguments, call the pipeline, print. No logic lives here, so
everything it does is equally reachable from a library call or an HTTP handler.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from cvv import __version__
from cvv.config import settings
from cvv.extract import extract
from cvv.gather import gather
from cvv.ingest import document_info, read, sections
from cvv.narrative import narrate
from cvv.providers import OllamaProvider
from cvv.report import assemble, coverage, render
from cvv.rules import REGISTRY
from cvv.worksheet import render_worksheet

app = typer.Typer(
    add_completion=False,
    help="Verify a developer CV against the systems it names. No score, no verdict.",
)


@app.command()
def verify(
    path: Annotated[Path, typer.Argument(help="The CV to verify (PDF or DOCX).")],
    model: Annotated[str | None, typer.Option(help="Ollama model id.")] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the report as JSON instead of prose.")
    ] = False,
    save: Annotated[
        Path | None, typer.Option(help="Directory to write the graph, bundle and report into.")
    ] = None,
    offline: Annotated[
        bool, typer.Option(help="Skip evidence gathering; run only the document-intrinsic checks.")
    ] = False,
    brief: Annotated[
        bool, typer.Option(help="Add a model-written briefing above the buckets.")
    ] = False,
    worksheet: Annotated[
        bool,
        typer.Option(help="Print the manual-check worksheet instead of the buckets."),
    ] = False,
) -> None:
    """Run a CV end to end and print the five buckets."""
    if not path.is_file():
        typer.secho(f"no such file: {path}", fg="red", err=True)
        raise typer.Exit(2)

    document = read(path)
    graph, _ = extract(
        document,
        provider=OllamaProvider(model),
        graph_id=f"cg_{document.document_id[4:]}",
    )

    if offline:
        # The invariant: a CV naming nothing still produces a complete, honest report.
        # Every check that needed a source abstains with a reason, and that is a real
        # path rather than a failure mode.
        import datetime

        from cvv.models import EvidenceBundle, Gap, GapReason

        bundle = EvidenceBundle(
            bundle_id=f"eb_{document.document_id[4:]}",
            graph_id=graph.graph_id,
            gathered_at=datetime.datetime.now(datetime.UTC),
            gaps=[
                Gap(
                    source=source,
                    reason=GapReason.NO_CONSENT,
                    detail="Run with --offline; no external source was consulted.",
                )
                for source in ("github", "codeforces")
            ],
        )
    else:
        bundle = gather(graph, bundle_id=f"eb_{document.document_id[4:]}")

    report = assemble(
        graph,
        bundle,
        report_id=f"fr_{document.document_id[4:]}",
        document=document_info(document),
    )

    if save:
        save.mkdir(parents=True, exist_ok=True)
        for name, artefact in (
            ("claim-graph", graph),
            ("evidence-bundle", bundle),
            ("findings-report", report),
        ):
            (save / f"{name}.json").write_text(artefact.model_dump_json(indent=2))
        typer.secho(f"wrote 3 artefacts to {save}/", fg="green", err=True)

    if as_json:
        typer.echo(report.model_dump_json(indent=2))
        return

    if worksheet:
        # What a person still has to do, prepared. Every line is derived from a claim
        # or a finding that exists — the worksheet invents no fact and no contact.
        typer.echo(render_worksheet(graph, report))
        return

    if brief:
        note = narrate(report, OllamaProvider(model))
        typer.echo("\n" + "=" * 78)
        typer.echo("  BRIEFING" + ("" if note.faithful else "  (model output rejected)"))
        typer.echo("=" * 78)
        typer.echo(note.text)
        if not note.faithful:
            typer.secho(
                f"\n  The model's prose was not used: {note.rejected_because}. Every "
                "number in a briefing must appear in the findings it was given, and "
                "every rule it cites must have fired. The deterministic summary is "
                "printed instead.",
                fg="yellow",
            )
    typer.echo(render(report, graph, bundle))


@app.command()
def rules() -> None:
    """The live rule catalogue.

    Every registered check with its tier and whether it may move a number. A rule
    declaring `scoring=false` is displayed and structurally barred from contributing
    to any total — that is visible here rather than buried in the source.
    """
    typer.echo(f"{len(REGISTRY)} registered\n")
    typer.echo(f"  {'ID':5} {'TIER':10} {'SCORES':7} SUMMARY")
    for rule in sorted(REGISTRY, key=lambda r: r.rule_id):
        typer.echo(
            f"  {rule.rule_id:5} {rule.tier.value:10} {rule.scoring!s:7} {rule.summary}"
        )


@app.command()
def inspect(path: Annotated[Path, typer.Argument(help="The CV to read.")]) -> None:
    """Read a document without calling a model — sections, metadata, and the text.

    Useful when extraction goes wrong: it separates "the document was read badly"
    from "the model read it badly", which are different problems with different fixes.
    """
    if not path.is_file():
        typer.secho(f"no such file: {path}", fg="red", err=True)
        raise typer.Exit(2)

    document = read(path)
    typer.echo(f"{document.document_id}   {document.pages} page(s)   {len(document.text)} chars")
    typer.echo(f"ingest      {document.ingest_method.value}")
    typer.echo(f"producer    {document.producer or '-'}")
    typer.echo(f"created     {document.created_at or '-'}")
    typer.echo("\nsections detected:")
    found = sections(document)
    if not found:
        typer.echo("  (none — every pass will read the whole document)")
    for section in found:
        typer.echo(f"  {section.heading:34} {section.start:5}..{section.end:<5} "
                   f"{section.end - section.start:5} chars")


@app.command()
def config() -> None:
    """Effective settings, with secrets redacted."""
    values = settings.model_dump()
    values["github_token"] = "set" if values.get("github_token") else None
    typer.echo(json.dumps(values, indent=2, default=str))
    provider = OllamaProvider()
    typer.echo(f"\nollama      {provider.loaded_split() or 'model not currently loaded'}")
    if settings.num_gpu is None:
        typer.secho(
            "\nCVV_NUM_GPU is unset. Ollama will pick the GPU/CPU layer split from "
            "whatever VRAM is free at load, which is the one measured source of "
            "non-determinism here. Pin it for reproducible runs.",
            fg="yellow",
            err=True,
        )


@app.callback(invoke_without_command=True)
def main(
    version: Annotated[bool, typer.Option("--version", help="Print the version.")] = False,
) -> None:
    if version:
        typer.echo(f"cvv {__version__}")
        raise typer.Exit


def _coverage_line(report: object) -> str:  # pragma: no cover - convenience for scripts
    cov = coverage(report)  # type: ignore[arg-type]
    return f"{cov.rules_evaluated}/{cov.rules_total} evaluated, coverage {cov.coverage:.0%}"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
