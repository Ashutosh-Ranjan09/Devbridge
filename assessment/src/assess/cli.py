"""`assess` — thin by design: parse, call, print. Nothing here decides anything."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from assess.config import ROOT, settings
from assess.models import Job
from assess.patterns import PatternError, all_patterns, load
from assess.scoring import render
from assess.sessions import SessionError, start, submit
from assess.store import Store

app = typer.Typer(add_completion=False, help="Unique, equally hard, sandboxed coding tasks. No verdicts.")
sandbox_app = typer.Typer(help="The Docker image candidate code runs in.")
app.add_typer(sandbox_app, name="sandbox")
jd_app = typer.Typer(help="Job descriptions: extract skills, edit, confirm, export.")
app.add_typer(jd_app, name="jd")


def fail(message: str) -> NoReturn:
    typer.secho(message, fg="red", err=True)
    raise typer.Exit(1)


@app.command()
def patterns() -> None:
    """Every pattern, with its skill, level and how many variants it can produce."""
    for p in all_patterns():
        typer.echo(f"{p.id:20} v{p.version}  {p.level.value:6}  skill {p.skill:16} "
                   f"{p.combinations} variants  {p.time_limit_minutes} min   {p.title}")


@app.command()
def validate(pattern_id: str) -> None:
    """Prove a pattern's tests: the reference passes every combination, every mutant fails."""
    from assess.validation import validate as run_validation

    try:
        p = load(pattern_id)
    except PatternError as exc:
        fail(str(exc))
        return
    r = run_validation(p)
    typer.echo(f"{p.id} v{p.version}: {r.combinations} combinations, reference "
               f"{r.reference_cases - len(r.reference_failures)}/{r.expected_cases} cases passed")
    for f in r.reference_failures[:10]:
        typer.secho(f"  reference FAILED {f}", fg="red")
    for name, escapes in r.escapes.items():
        state = "caught everywhere" if not escapes else f"ESCAPES in {len(escapes)}"
        typer.secho(f"  mutant {name:36} {state:22} by {', '.join(sorted(r.caught_by[name])) or '-'}",
                    fg="green" if not escapes else "red")
    typer.secho("valid" if r.ok else "NOT VALID — no task will be issued from this pattern",
                fg="green" if r.ok else "red", bold=True)
    if not r.ok:
        raise typer.Exit(1)


@sandbox_app.command("build")
def sandbox_build() -> None:
    """Build the sandbox image from sandbox/Dockerfile."""
    raise typer.Exit(subprocess.call(["docker", "build", "-t", settings.sandbox_image, str(ROOT / "sandbox")]))


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    # 8070: cvv serves on 8080 and the Claude Code wrapper listens on 8000.
    port: Annotated[int, typer.Option(help="Port.")] = 8070,
) -> None:
    """Run the HTTP surface the web layer calls. Localhost unless told otherwise."""
    import uvicorn

    from assess.api import API_KEY
    from assess.api import app as api

    if settings.api_key is None:
        typer.secho("ASSESS_API_KEY is unset, so one was generated for this run:", fg="yellow", err=True)
        typer.secho(f"    {API_KEY}", fg="yellow", bold=True, err=True)
    uvicorn.run(api, host=host, port=port)


def _write_task(folder: Path, title: str, session_id: str, deadline: str, variant_story: str,
                variant_requirements: str, starter: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "TASK.md").write_text(
        f"# {title}\n\nSession `{session_id}` · deadline {deadline} UTC\n\n"
        f"{variant_story}\n\n{variant_requirements}"
    )
    (folder / "solution.py").write_text(starter)


@app.command("start")
def start_cmd(
    candidate: Annotated[str, typer.Option(help="Candidate reference — the same subject_ref M6 uses.")],
    pattern_id: Annotated[str | None, typer.Argument(help="Pattern to draw the task from.")] = None,
    job: Annotated[str | None, typer.Option(help="A confirmed job: one task per assessable must-have.")] = None,
    seed: Annotated[int | None, typer.Option(help="Fix the variant; random if unset.")] = None,
    model: Annotated[bool, typer.Option(help="With --job, let the model fit tasks to the JD.")] = True,
    out: Annotated[Path | None, typer.Option(help="Folder for the task files.")] = None,
) -> None:
    """Issue a task — from a pattern, or for every assessable must-have of a confirmed job."""
    from assess.providers import default_provider
    from assess.sessions import start_for_job

    if (pattern_id is None) == (job is None):
        fail("give a pattern, or --job, not both")
    store = Store()
    try:
        if job is not None:
            # Begun at once: an operator issuing a task here means to take it now.
            issued, missing = start_for_job(store, job, candidate,
                                            provider=default_provider() if model else None, begin=True)
        else:
            assert pattern_id is not None
            issued, missing = [start(store, pattern_id, candidate, seed=seed)], []
    except (PatternError, ValueError) as exc:
        fail(str(exc))
    for session, variant in issued:
        folder = (out or Path(".")) / f"task-{session.session_id}"
        _write_task(folder, load(variant.pattern_id).title, session.session_id,
                    f"{session.deadline:%Y-%m-%d %H:%M}", variant.story, variant.requirements, variant.starter)
        fitted = "fitted to the JD by the model" if variant.chosen_by == "model" else "seeded"
        typer.secho(f"session {session.session_id} · {variant.pattern_id} · variant {variant.variant_id} "
                    f"({fitted}; story: {variant.story_by}) · deadline {session.deadline:%H:%M} UTC", fg="green")
        typer.echo(f"  task in {folder}/   submit:  assess submit {session.session_id} {folder}/solution.py")
        if job is not None and model and variant.chosen_by == "seed" and variant.story_by == "template":
            typer.secho("  the model was asked but not used — unreachable, or nothing usable came back. "
                        "The task is valid, just not fitted to the JD.", fg="yellow")
    for skill in missing:
        typer.secho(f"  not assessable: {skill} — no pattern tests it yet", fg="yellow")
    if not issued:
        fail("no task issued: none of the must-have skills has a pattern")


@app.command("submit")
def submit_cmd(session_id: str, solution: Path) -> None:
    """Run a solution in the sandbox and print the report."""
    if not solution.is_file():
        fail(f"no such file: {solution}")
    try:
        result = submit(Store(), session_id, solution.read_text())
    except SessionError as exc:
        fail(str(exc))
        return
    typer.echo(render(result))
    if not result.scored:
        raise typer.Exit(2)


@app.command()
def report(session_id: str, as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """The stored result of a session."""
    result = Store().result(session_id)
    if result is None:
        fail(f"no result for {session_id}")
        return
    typer.echo(result.model_dump_json(indent=2) if as_json else render(result))


# ── job descriptions ───────────────────────────────────────────────────────


def _job(store: Store, job_id: str) -> Job:
    job = store.job(job_id)
    if job is None:
        fail(f"no job {job_id}")
    return job


@jd_app.command("new")
def jd_new(
    text_file: Annotated[Path, typer.Argument(help="The job description, as plain text.")],
    model: Annotated[bool, typer.Option(help="Use the model; --no-model uses rules only.")] = True,
) -> None:
    """Enter a job description and propose the skills it asks for."""
    from assess.jd import extract
    from assess.jd import render as render_job
    from assess.providers import default_provider

    if not text_file.is_file():
        fail(f"no such file: {text_file}")
    job = extract(text_file.read_text(), default_provider() if model else None)
    Store().save_job(job)
    typer.echo(render_job(job))
    typer.echo(f"\nreview, then:  assess jd edit {job.job_id} --must ID[:BAR] --nice ID --drop ID"
               f"\n               assess jd confirm {job.job_id} --by NAME")


@jd_app.command("show")
def jd_show(job_id: str) -> None:
    from assess.jd import render as render_job

    typer.echo(render_job(_job(Store(), job_id)))


@jd_app.command("list")
def jd_list() -> None:
    for job in Store().jobs():
        first = " ".join(job.text.split())[:60]
        typer.echo(f"{job.job_id}  {job.status.value:9}  {len(job.skills)} skills  {first}…")


@jd_app.command("edit")
def jd_edit(
    job_id: str,
    must: Annotated[list[str] | None, typer.Option(help="ID or ID:BAR, e.g. rate_limiting:0.4")] = None,
    nice: Annotated[list[str] | None, typer.Option(help="Skill id to make a nice-to-have.")] = None,
    drop: Annotated[list[str] | None, typer.Option(help="Skill id to remove.")] = None,
) -> None:
    """Change priorities, bars and skills of a proposed job."""
    from assess.jd import JobError, edit
    from assess.jd import render as render_job

    store = Store()
    bars: dict[str, float | None] = {}
    for item in must or []:
        sid, _, bar = item.partition(":")
        try:
            bars[sid] = float(bar) if bar else None
        except ValueError:
            fail(f"bar must be a number between 0 and 1: {item}")
    try:
        job = edit(_job(store, job_id), must=bars, nice=nice or [], drop=drop or [])
        store.save_job(job)
    except (JobError, ValueError) as exc:
        fail(str(exc))
        return
    typer.echo(render_job(job))


@jd_app.command("confirm")
def jd_confirm(job_id: str, by: Annotated[str, typer.Option(help="Who confirmed it.")]) -> None:
    """Lock the job's skills. A confirmed job is never edited."""
    from assess.jd import JobError, confirm
    from assess.jd import render as render_job

    store = Store()
    try:
        job = confirm(_job(store, job_id), by)
        store.save_job(job)
    except JobError as exc:
        fail(str(exc))
        return
    typer.echo(render_job(job))


@jd_app.command("export")
def jd_export(job_id: str, out: Annotated[Path | None, typer.Option(help="Write here, else print.")] = None) -> None:
    """The confirmed requirements, for M6's shortlist (schemas/job-requirements.schema.json)."""
    from assess.jd import JobError, dumps

    try:
        text = dumps(_job(Store(), job_id))
    except JobError as exc:
        fail(str(exc))
        return
    if out:
        out.write_text(text + "\n")
        typer.secho(f"wrote {out}", fg="green", err=True)
    else:
        typer.echo(text)


@app.command()
def events(
    session_id: str,
    out: Annotated[Path | None, typer.Option(help="Write the batch here, else print it.")] = None,
) -> None:
    """The result as evidence for the skill graph (schemas/evidence-event.schema.json)."""
    import json

    from assess.events import NotEvidenceError, batch

    result = Store().result(session_id)
    if result is None:
        fail(f"no result for {session_id}")
    try:
        doc = batch(result)
    except NotEvidenceError as exc:
        fail(str(exc))
    text = json.dumps(doc, indent=2)
    if out:
        out.write_text(text + "\n")
        typer.secho(f"wrote {out} — ingest with: python -m m6_ingestor ingest {out} --db evidence.db",
                    fg="green", err=True)
    else:
        typer.echo(text)


@app.command()
def calibrate(pattern_id: str) -> None:
    """Pass rates per test and per twist; flags a twist that is not as hard as the others."""
    from assess.calibration import calibrate as run_calibration
    from assess.calibration import render as render_calibration

    try:
        p = load(pattern_id)
    except PatternError as exc:
        fail(str(exc))
    typer.echo(render_calibration(run_calibration(p, Store().results_for(p.id, p.version))))
