"""``cio-advisory`` : the Typer CLI for the B3 CIO Advisory Assistant.

A thin presentation layer over the domain services. It owns no business logic: every
command builds the wiring from :func:`cio_advisory.config.build_container` and the factory
functions in :mod:`cio_advisory.api.deps`, invokes the advisory service, and pretty-prints
the cited, suitability-tagged result.

Design constraints honoured here:

* **Import-safe.** Importing this module (e.g. ``cio_advisory.cli.main:app`` as the
  ``[project.scripts]`` entry point, or ``--help``) must never pull in FastAPI, uvicorn,
  the Google Cloud SDKs, or even the domain services. All of those are imported *lazily
  inside command bodies*, so the on-prem/test profile : which installs no Google Cloud SDK
  : can still load the CLI and run ``--help``.
* **Profile-aware.** ``CIO_PROFILE`` selects the adapter stack. The ``onprem`` profile
  binds placeholder adapters that raise ``NotImplementedError`` from every method; when a
  command trips one of those, the CLI fails clearly (exit code 2).
* **Not advice, and cited.** Every briefing/talking-point is printed with its non-advice
  banner, suitability verdict, and house-view citations, because a private-bank artifact a
  reviewer cannot trace to a CIO house view is worthless.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime top level
    from ..config import Container
    from ..domain.models import (
        AdvisoryBriefing,
        Citation,
        SuitabilityAssessment,
        TalkingPoint,
    )

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "B3 CIO Advisory Assistant : grounded, suitability-checked, decision-support "
        "talking points for private-bank relationship managers, on the Gemini Enterprise "
        "Agent Platform (region asia-southeast1). Decision-support, NOT financial advice."
    ),
)

# Exit codes: 2 == the active profile cannot satisfy this command (e.g. on-prem stub);
# 1 == an unexpected adapter/runtime failure. 0 == success.
_PROFILE_EXIT = 2
_RUNTIME_EXIT = 1

# Identity the CLI acts as: a same-tenant (demo-bank) RM operator. The CLI is a local
# operator tool, so it resolves a fixed verified principal rather than an IdP assertion;
# object authorization (domain/entitlements.py) is still enforced against it.
_CLI_ACTOR = "cli:rm"
_CLI_TENANT = "demo-bank"


def _cli_principal() -> Any:
    """The verified principal the CLI operates as (a demo-bank advisory RM)."""
    from ..domain.identity import Principal

    return Principal(
        subject=_CLI_ACTOR,
        principals=("group:cio-analyst",),
        tenant=_CLI_TENANT,
        source="cli",
    )


# --------------------------------------------------------------------------- #
# Wiring helpers (all imports lazy, so this module stays import-safe)
# --------------------------------------------------------------------------- #
def _container() -> Container:
    from ..config import build_container

    return build_container()


def _deps() -> Any:
    try:
        from ..api import deps  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - defensive wiring guard
        _fail(
            f"Service factories (cio_advisory.api.deps) are unavailable: {exc}",
            code=_RUNTIME_EXIT,
        )
    return deps


def _fail(message: str, *, code: int = _RUNTIME_EXIT) -> Any:
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _run(action: str, fn: Any) -> Any:
    """Execute ``fn`` and translate adapter failures into clean CLI errors."""
    from ..config import Settings

    profile = Settings.load().profile
    try:
        return fn()
    except NotImplementedError as exc:
        detail = str(exc) or "method not implemented"
        _fail(
            f"'{action}' is not available under profile '{profile}'. "
            f"This profile uses placeholder adapters (on-prem migration target): {detail}",
            code=_PROFILE_EXIT,
        )
    except KeyError as exc:
        _fail(
            f"'{action}' has no adapter wired for profile '{profile}': {exc}",
            code=_PROFILE_EXIT,
        )
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI boundary: no tracebacks to operators
        _fail(f"'{action}' failed: {type(exc).__name__}: {exc}", code=_RUNTIME_EXIT)


# --------------------------------------------------------------------------- #
# Pretty-printing
# --------------------------------------------------------------------------- #
def _fmt_citation(c: Citation) -> str:
    src = c.source_type.value if hasattr(c.source_type, "value") else str(c.source_type)
    url = f" : {c.url}" if c.url else ""
    return f"[{c.source_id}, {src}] {c.title}{url}"


def _echo_citations(citations: tuple[Citation, ...], indent: str = "  ") -> None:
    if not citations:
        typer.secho(f"{indent}(no citations)", fg=typer.colors.YELLOW)
        return
    typer.secho(f"{indent}Citations:", bold=True)
    for c in citations:
        typer.echo(f"{indent}  - {_fmt_citation(c)}")


def _echo_not_advice(disclaimer: str) -> None:
    typer.secho(
        "  [NOT ADVICE] decision-support only; the RM is the human checker (P-06).",
        fg=typer.colors.YELLOW,
        bold=True,
    )
    if disclaimer:
        typer.secho(f"  {disclaimer}", fg=typer.colors.BRIGHT_BLACK)


def _echo_suitability(assessment: SuitabilityAssessment | None, indent: str = "    ") -> None:
    if assessment is None:
        return
    verdict = (
        assessment.verdict.value
        if hasattr(assessment.verdict, "value")
        else str(assessment.verdict)
    )
    color = {
        "suitable": typer.colors.GREEN,
        "review": typer.colors.YELLOW,
        "unsuitable": typer.colors.RED,
    }.get(verdict, typer.colors.WHITE)
    typer.secho(f"{indent}suitability: {verdict.upper()}", fg=color, bold=True)
    if assessment.rationale:
        typer.echo(f"{indent}  {assessment.rationale}")


def _print_talking_point(tp: TalkingPoint, n: int) -> None:
    typer.secho(f"  {n}. {tp.headline}", bold=True)
    typer.echo(f"     {tp.body}")
    if tp.linked_holdings:
        typer.echo(f"     linked holdings: {', '.join(tp.linked_holdings)}")
    _echo_suitability(tp.suitability)
    _echo_citations(tp.citations, indent="     ")


def _print_briefing(briefing: AdvisoryBriefing) -> None:
    typer.secho(
        f"Advisory briefing : client {briefing.client_id}", bold=True, fg=typer.colors.GREEN
    )
    _echo_not_advice(briefing.not_advice_disclaimer)
    typer.echo("")
    if not briefing.talking_points:
        typer.secho("  (no suitable talking points produced)", fg=typer.colors.YELLOW)
    for i, tp in enumerate(briefing.talking_points, start=1):
        _print_talking_point(tp, i)
    align = briefing.alignment
    typer.secho("  Portfolio alignment:", bold=True)
    typer.echo(f"    in line:    {', '.join(align.themes_in_line) or 'none'}")
    typer.echo(f"    gaps:       {', '.join(align.gaps) or 'none'}")
    typer.echo(f"    overweights:{', '.join(align.overweights) or 'none'}")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
@app.command()
def briefing(
    client_id: str = typer.Argument(..., help="Opaque client reference (no PII)."),
) -> None:
    """Build a suitability-checked advisory briefing for a client (not advice)."""

    def _do() -> AdvisoryBriefing:
        svc = _deps().build_advisory_service(_container())
        return svc.brief(client_id, _cli_principal())

    result = _run("briefing", _do)
    _print_briefing(result)


@app.command(name="talking-points")
def talking_points(
    client_id: str = typer.Argument(..., help="Opaque client reference (no PII)."),
) -> None:
    """Generate the suitability-checked talking points for a client (not advice)."""

    def _do() -> list[TalkingPoint]:
        svc = _deps().build_advisory_service(_container())
        return svc.talking_points(client_id, _cli_principal())

    points = _run("talking-points", _do)
    typer.secho(f"Talking points : client {client_id}", bold=True, fg=typer.colors.GREEN)
    from ..domain.models import NOT_ADVICE_DISCLAIMER

    _echo_not_advice(NOT_ADVICE_DISCLAIMER)
    typer.echo("")
    if not points:
        typer.secho("  (no suitable talking points produced)", fg=typer.colors.YELLOW)
    for i, tp in enumerate(points, start=1):
        _print_talking_point(tp, i)


@app.command()
def suitability(
    client_id: str = typer.Argument(..., help="Opaque client reference (no PII)."),
    theme: str = typer.Argument(..., help="The CIO house-view theme to assess."),
) -> None:
    """Assess the suitability of a CIO house-view theme for a client."""

    def _do() -> AdvisoryBriefing:
        svc = _deps().build_advisory_service(_container())
        return svc.brief(client_id, _cli_principal())

    result = _run("suitability", _do)
    wanted = theme.strip().lower()
    for tp in result.talking_points:
        a = tp.suitability
        if a is not None and a.theme.strip().lower() == wanted:
            typer.secho(f"Suitability : {a.theme}", bold=True, fg=typer.colors.GREEN)
            _echo_suitability(a, indent="  ")
            _echo_citations(a.citations, indent="  ")
            return
    typer.secho(
        f"No suitable, in-scope talking point matched theme '{theme}' for client {client_id}.",
        fg=typer.colors.YELLOW,
    )


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address for the API server."),
    port: int = typer.Option(8091, help="TCP port for the API server."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code change (dev only)."),
) -> None:
    """Run the FastAPI app (A2A card and REST endpoints) under uvicorn."""

    def _do() -> None:
        import uvicorn

        deps = _deps()
        if not hasattr(deps, "create_app"):
            _fail(
                "cio_advisory.api.deps does not expose create_app(); cannot start the server.",
                code=_RUNTIME_EXIT,
            )
        typer.secho(
            f"serving cio-advisory on http://{host}:{port} (profile={_profile_label()})",
            fg=typer.colors.GREEN,
        )
        uvicorn.run(
            "cio_advisory.api.deps:create_app",
            factory=True,
            host=host,
            port=port,
            reload=reload,
        )

    _run("serve", _do)


@app.command()
def eval(  # noqa: A001 : "eval" is the documented command name
    dataset: str | None = typer.Option(
        None,
        "--dataset",
        "-d",
        help="Path to the golden eval dataset (defaults to the gate's bundled set).",
    ),
) -> None:
    """Run the A4 promotion eval gate (groundedness / suitability / citations / no-advice)."""

    def _do() -> int:
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        script = repo_root / "eval" / "run_eval.py"
        if not script.exists():
            _fail(f"eval gate script not found at {script}", code=_RUNTIME_EXIT)
        cmd = [sys.executable, str(script)]
        if dataset:
            cmd += ["--dataset", dataset]
        typer.secho(f"running eval gate: {script}", fg=typer.colors.CYAN)
        completed = subprocess.run(cmd, check=False)  # noqa: S603 - trusted local script
        return completed.returncode

    code = _run("eval", _do)
    if code == 0:
        typer.secho("eval gate: PASS", fg=typer.colors.GREEN, bold=True)
    else:
        typer.secho("eval gate: FAIL", fg=typer.colors.RED, bold=True)
    raise typer.Exit(int(code))


def _profile_label() -> str:
    from ..config import Settings

    return Settings.load().profile


if __name__ == "__main__":  # pragma: no cover
    app()
