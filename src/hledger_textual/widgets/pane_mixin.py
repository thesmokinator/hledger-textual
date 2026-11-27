"""Shared mixin for pane widgets backed by a DataTable."""

from __future__ import annotations

from collections.abc import Callable

from textual import work
from textual.widgets import DataTable

from hledger_textual.error_messages import humanize_error
from hledger_textual.period import PeriodSelection, current_month_selection
from hledger_textual.widgets import distribute_column_widths
from hledger_textual.widgets.empty_state import EmptyState
from hledger_textual.widgets.loading import show_loading_overlay


def get_period(widget) -> PeriodSelection:
    """Return the shared period selection *widget* should display.

    Widgets mounted inside :class:`~hledger_textual.app.HledgerTuiApp` read
    the app-owned reactive; anything else (standalone widgets, tests with a
    bare ``App``) falls back to a widget-local period, and finally to the
    current calendar month.

    Args:
        widget: The pane or table widget asking for its period.
    """
    try:
        app = widget.app
    except Exception:
        app = None
    shared = getattr(app, "period_selection", None)
    if shared is not None:
        return shared
    fallback = getattr(widget, "_period_fallback", None)
    return fallback if fallback is not None else current_month_selection()


def get_global_query(widget) -> str:
    """Return the app-owned global query *widget* should compose with its scope.

    Widgets mounted inside :class:`~hledger_textual.app.HledgerTuiApp` read
    the app-owned ``active_query``; anything else falls back to ``""``
    (no global filter).

    Args:
        widget: The pane or table widget asking for the global query.
    """
    try:
        app = widget.app
    except Exception:
        return ""
    query = getattr(app, "active_query", "")
    return query if isinstance(query, str) else ""


def set_period(widget, selection: PeriodSelection) -> bool:
    """Apply a new shared period selection.

    When the app owns the shared state (``HledgerTuiApp``), the reactive is
    updated and its watcher refreshes the visible pane; the caller must not
    reload itself.  Otherwise the widget-local fallback is updated and the
    caller is responsible for refreshing.

    Args:
        widget: The widget initiating the period change.
        selection: The new selection.

    Returns:
        ``True`` when the app watcher will refresh the pane, ``False`` when
        the caller must refresh locally.
    """
    try:
        app = widget.app
    except Exception:
        app = None
    if getattr(app, "period_selection", None) is not None:
        app.period_selection = selection
        return True
    widget._period_fallback = selection
    return False


def set_empty_state_visible(
    widget, empty_id: str, table_id: str, visible: bool
) -> None:
    """Toggle an empty-state message and its DataTable visibility.

    Args:
        widget: The pane or table widget owning both elements.
        empty_id: CSS id of the :class:`EmptyState` message.
        table_id: CSS id of the :class:`DataTable` to hide when empty.
        visible: Show the empty-state message when True.
    """
    widget.query_one(f"#{empty_id}", EmptyState).display = visible
    widget.query_one(f"#{table_id}", DataTable).display = not visible


READ_ONLY_MESSAGE = "Read-only mode: editing is disabled (started with --read-only)"


def is_read_only(widget) -> bool:
    """Return True when the app was started in read-only mode.

    Safe to call from a worker thread or after teardown.

    Args:
        widget: The widget attempting a mutation.
    """
    try:
        app = widget.app
    except Exception:
        return False
    # Strict identity check: mocks and truthy-but-not-True values must not
    # enable the mode accidentally.
    return getattr(app, "read_only", None) is True


def refuse_read_only(widget, *, from_worker: bool = False) -> bool:
    """Notify the user and return True when mutation is refused (issue #271).

    Args:
        widget: The widget attempting the mutation.
        from_worker: True when called from a worker thread (the toast is
            then dispatched with ``call_from_thread``).

    Returns:
        ``True`` when read-only mode blocks the mutation.
    """
    if not is_read_only(widget):
        return False
    try:
        if from_worker:
            widget.app.call_from_thread(
                widget.notify, READ_ONLY_MESSAGE, severity="warning", timeout=5
            )
        else:
            widget.notify(READ_ONLY_MESSAGE, severity="warning", timeout=5)
    except Exception:
        pass
    return True


def run_mutation(
    widget,
    mutate: Callable[[], object],
    *,
    success_message: str | Callable[[], str],
    error_cls: type[Exception],
    guard: object = True,
    after: Callable[[], None] | None = None,
    humanize_errors: bool = False,
) -> None:
    """Run a journal mutation from a ``@work`` thread with standard handling.

    Shared implementation behind :meth:`DataTablePaneMixin._run_mutation`,
    also usable by table widgets that do not inherit the mixin
    (e.g. ``TransactionsTable``).

    Args:
        widget: The widget owning the mutation (provides ``app``/``notify``).
        mutate: Zero-arg callable performing the mutation.
        success_message: Toast on success, or a zero-arg callable
            returning it (for messages computed from the result).
        error_cls: Exception type caught and reported as an error toast.
        guard: Falsy values skip the mutation entirely.
        after: Optional refresh callback run before the success toast.
        humanize_errors: Report failures via :func:`humanize_error`
            (title + body, longer timeout) instead of ``str(exc)``.
    """
    if not guard:
        return
    if refuse_read_only(widget, from_worker=True):
        return
    try:
        mutate()
        message = success_message() if callable(success_message) else success_message
        if after is not None:
            widget.app.call_from_thread(after)
        widget.app.call_from_thread(widget.notify, message, timeout=3)
    except error_cls as exc:
        if humanize_errors:
            title, body = humanize_error(exc)
            widget.app.call_from_thread(
                widget.notify, body, title=title, severity="error", timeout=10
            )
        else:
            widget.app.call_from_thread(
                widget.notify, str(exc), severity="error", timeout=8
            )


def request_initial_load(
    widget, section: str, loader: Callable[[], None]
) -> None:
    """Start a pane's initial load, deferring it on the main app if requested.

    Panes mounted outside :class:`~hledger_textual.app.HledgerTuiApp` (for
    example in tests) load immediately.

    Args:
        widget: Pane or table widget owning the load.
        section: Tab section the widget belongs to.
        loader: Zero-argument callable starting the load.
    """
    request = getattr(widget.app, "request_initial_load", None)
    if request is None:
        loader()
    else:
        request(section, loader)


def run_pane_load(
    widget,
    load: Callable[[], object],
    apply: Callable[[object], None],
    *,
    loading_message: str | None = None,
    on_error: Callable[[Exception], object] | None = None,
) -> None:
    """Load pane data on a worker thread with standard overlay/error handling.

    Runs ``load()`` and dispatches ``apply(result)`` on the app thread.
    Shows *loading_message* in a loading overlay first (when given) and, on
    failure, a :func:`humanize_error` toast. When *on_error* is given,
    ``apply(on_error(exc))`` still runs so the pane can render its
    empty/fallback state; otherwise ``apply`` is skipped on failure.

    Must be called from a worker thread (``call_from_thread`` is used).

    Args:
        widget: The pane or table widget owning the load.
        load: Zero-arg callable computing the payload (may raise).
        apply: Called on the app thread with the payload (or the
            ``on_error`` fallback) to refresh the UI.
        loading_message: Overlay text, or None for no overlay.
        on_error: Maps the exception to a fallback payload; None skips
            ``apply`` on failure.
    """
    try:
        app = widget.app
    except Exception:
        # The app is shutting down: no point in loading anything.
        return
    if loading_message is not None:
        app.call_from_thread(show_loading_overlay, widget, loading_message)
    try:
        result = load()
    except Exception as exc:
        title, body = humanize_error(exc)
        try:
            widget.app.call_from_thread(
                widget.notify, body, title=title, severity="error", timeout=10
            )
        except Exception:
            return  # app shut down while the worker was running
        if on_error is None:
            return
        result = on_error(exc)
    try:
        widget.app.call_from_thread(apply, result)
    except Exception:
        # The app shut down between load() and the UI update.
        pass


class DataTablePaneMixin:
    """Mixin providing on_show, on_resize, cursor navigation, and export for DataTable panes.

    Subclasses must set ``_main_table_id`` (the CSS id of their DataTable)
    and ``_fixed_column_widths`` (a dict of column-index to fixed width).

    Panes with several tables may set ``_additional_tables`` (a dict of
    CSS id to fixed widths) to have their widths recalculated on resize
    too, and panes whose tables must not receive keyboard focus may set
    ``_focus_on_show`` to ``False``.

    To support export, subclasses should override ``get_export_data()``.
    """

    _main_table_id: str
    _fixed_column_widths: dict[int, int] = {}
    _flex_column_weights: dict[int, int] = {}
    _additional_tables: dict[str, dict[int, int]] = {}
    _focus_on_show: bool = True

    def _get_main_table(self) -> DataTable:
        """Return the pane's primary DataTable."""
        return self.query_one(f"#{self._main_table_id}", DataTable)

    def on_show(self) -> None:
        """Restore focus to the table when the pane becomes visible."""
        if self._focus_on_show:
            self._get_main_table().focus()

    def on_resize(self) -> None:
        """Recalculate column widths when the pane is resized."""
        distribute_column_widths(
            self._get_main_table(), self._fixed_column_widths, self._flex_column_weights
        )
        for table_id, widths in self._additional_tables.items():
            distribute_column_widths(self.query_one(f"#{table_id}", DataTable), widths)

    def action_cursor_down(self) -> None:
        """Move cursor down in the table."""
        self._get_main_table().action_cursor_down()

    def action_cursor_up(self) -> None:
        """Move cursor up in the table."""
        self._get_main_table().action_cursor_up()

    def action_cursor_left(self) -> None:
        """Move cursor left in the table."""
        self._get_main_table().action_cursor_left()

    def action_cursor_right(self) -> None:
        """Move cursor right in the table."""
        self._get_main_table().action_cursor_right()

    def get_export_data(self):
        """Return an :class:`ExportData` for the currently visible table data.

        Subclasses should override this to provide pane-specific export content.

        Returns:
            An ExportData instance, or None if export is not supported.
        """
        return None

    def action_export(self) -> None:
        """Open the export modal and export visible data to CSV or PDF."""
        from hledger_textual.config import load_export_dir
        from hledger_textual.export import default_filename

        data = self.get_export_data()
        if data is None:
            self.notify("Export not available for this pane", severity="warning", timeout=3)
            return

        from hledger_textual.screens.export_modal import ExportModal

        filename = default_filename(data.pane_name, "csv")
        export_dir = str(load_export_dir())

        def on_result(result: tuple[str, str, str] | None) -> None:
            if result is not None:
                fmt, fname, directory = result
                self.notify(f"Exporting to {fname}…", timeout=5)
                self._run_export(data, fmt, fname, directory)

        self.app.push_screen(
            ExportModal(default_filename=filename, default_directory=export_dir),
            callback=on_result,
        )

    def _run_mutation(
        self,
        mutate: Callable[[], object],
        *,
        success_message: str | Callable[[], str],
        error_cls: type[Exception],
        guard: object = True,
        after: Callable[[], None] | None = None,
        humanize_errors: bool = False,
    ) -> None:
        """Run a journal mutation from a ``@work`` thread with standard handling.

        Calls *mutate*, then refreshes via *after* and notifies success;
        a *error_cls* failure notifies an error instead. Must be called
        from a worker thread (``call_from_thread`` is used throughout).

        Args:
            mutate: Zero-arg callable performing the mutation.
            success_message: Toast on success, or a zero-arg callable
                returning it (for messages computed from the result).
            error_cls: Exception type caught and reported as an error toast.
            guard: Falsy values skip the mutation entirely (e.g. a missing
                ``Path`` for panes backed by an optional rule file).
            after: Optional refresh callback run before the success toast.
            humanize_errors: Report failures via :func:`humanize_error`
                (title + body, longer timeout) instead of ``str(exc)``.
        """
        run_mutation(
            self,
            mutate,
            success_message=success_message,
            error_cls=error_cls,
            guard=guard,
            after=after,
            humanize_errors=humanize_errors,
        )

    @work(thread=True)
    def _run_export(self, data, fmt: str, filename: str, directory: str) -> None:
        """Execute the export in a background thread.

        Args:
            data: The ExportData to export.
            fmt: Export format ("csv" or "pdf").
            filename: The target filename.
            directory: The target directory path.
        """
        from pathlib import Path

        from hledger_textual.export import export_csv, export_pdf

        export_dir = Path(directory).expanduser().resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / filename

        try:
            if fmt == "pdf":
                export_pdf(data, path)
            else:
                export_csv(data, path)
            self.app.call_from_thread(
                self.notify, f"Exported to {path}", timeout=5
            )
        except Exception as exc:
            title, body = humanize_error(exc)
            self.app.call_from_thread(
                self.notify,
                f"Export failed: {body}",
                title=title,
                severity="error",
                timeout=10,
            )
