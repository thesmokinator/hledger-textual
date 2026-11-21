"""Entry point for hledger-textual."""

import sys

from hledger_textual.app import HledgerTuiApp
from hledger_textual.config import (
    load_default_period,
    parse_args,
    resolve_journal_file,
)
from hledger_textual.textual_compat import (
    MIN_TEXTUAL_VERSION,
    is_supported_textual,
)


def _check_textual_version() -> None:
    """Abort with an actionable message when Textual is unsupported.

    An outdated Textual produces confusing crashes deep inside widget code
    (for example ``AttributeError: type object 'Select' has no attribute
    'NULL'``), so the version declared in ``pyproject.toml`` is enforced here.

    Raises:
        SystemExit: If the installed Textual version is outside the supported
            range.
    """
    import textual

    version = getattr(textual, "__version__", "")
    if is_supported_textual(version):
        return

    required = ".".join(str(part) for part in MIN_TEXTUAL_VERSION)
    print(
        f"hledger-textual requires Textual >= {required},<9 but found "
        f"{version or 'an unknown version'}.\n"
        "Upgrade it with `pipx upgrade hledger-textual`, "
        "`uv tool upgrade hledger-textual`, or `uv sync` in a development "
        "checkout.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _resolve_initial_period(args, journal_file):
    """Resolve the startup period from CLI flags and config (issue #268).

    Precedence: CLI ``-p``/``-b``/``-e`` > ``default_period`` config key >
    journal-span heuristic (the landing logic in the app).

    The resolved period is validated with hledger itself (``hledger print
    -p``), so a mistyped expression aborts with a clear message and a
    non-zero status instead of opening an empty UI.

    Args:
        args: The parsed CLI arguments.
        journal_file: Path to the journal file.

    Returns:
        The initial :class:`PeriodSelection`, or ``None`` when no period was
        requested (the app then lands on the current month / latest data).

    Raises:
        ValueError: If a flag or config value is invalid, or hledger rejects
            the period expression.
        SystemExit: Propagated by resolve_journal_file on bad paths.
    """
    from hledger_textual.hledger import HledgerError, run_hledger
    from hledger_textual.period import parse_period, period_from_flags

    if args.period or args.begin or args.end:
        selection = period_from_flags(args.period, args.begin, args.end)
    else:
        default_period = load_default_period()
        if default_period is None:
            return None
        selection = parse_period(default_period)
        if selection is None:
            raise ValueError(
                f"Invalid default_period in config: {default_period!r}"
            )

    expr = selection.period_expr
    if not expr:
        return selection
    try:
        run_hledger("print", "-p", expr, file=journal_file)
    except HledgerError as exc:
        raise ValueError(f"hledger rejected period {expr!r}: {exc}") from exc
    return selection


def main() -> None:
    """Run the hledger-textual application."""
    _check_textual_version()
    args = parse_args()
    journal_file = resolve_journal_file(cli_file=args.file)
    try:
        initial_period = _resolve_initial_period(args, journal_file)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    app = HledgerTuiApp(journal_file=journal_file, initial_period=initial_period)
    app.run()


if __name__ == "__main__":
    main()
