"""Entry point for hledger-textual."""

import sys

from hledger_textual.app import HledgerTuiApp
from hledger_textual.config import parse_args, resolve_journal_file
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


def main() -> None:
    """Run the hledger-textual application."""
    _check_textual_version()
    args = parse_args()
    journal_file = resolve_journal_file(cli_file=args.file)
    app = HledgerTuiApp(journal_file=journal_file)
    app.run()


if __name__ == "__main__":
    main()
