"""FileBrowserVM — manages the list of loaded files for master selection.

This ViewModel provides a flat list of filenames to the FileBrowserView
and communicates selection changes back to the AppViewModel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from valisync.gui.viewmodels.observable import Observable

if TYPE_CHECKING:
    from valisync.core.session import SourceInfo
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel


def _fmt_size(size_bytes: int) -> str:
    """Human-readable size, one decimal (B/KB/MB/GB)."""
    value = float(size_bytes)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


class FileBrowserVM(Observable):
    """ViewModel for the FileBrowser component.

    Parameters
    ----------
    app_vm:
        The parent application ViewModel, which holds the global loaded state.
    """

    def __init__(self, app_vm: AppViewModel) -> None:
        super().__init__()
        self._app_vm = app_vm
        self._files: list[str] = []
        self._refresh()

        # Subscribe to AppViewModel events to stay in sync
        self._unsubscribe = self._app_vm.subscribe(self._on_app_change)

    @property
    def files(self) -> list[str]:
        """List of filenames (basenames) of all loaded files."""
        return self._files

    def select_file(self, index: int) -> None:
        """Update the Active File in AppViewModel based on selection index."""
        keys = self._app_vm.loaded_file_keys
        if 0 <= index < len(keys):
            self._app_vm.set_active_file(keys[index])
        else:
            self._app_vm.set_active_file(None)

    def unload(self, index: int) -> None:
        """Unload the file at list *index* (no-op when out of range).

        Delegates to ``AppViewModel.unload_file``; the resulting ``"unloaded"``
        notification refreshes this VM's list via :meth:`_on_app_change`.
        """
        keys = self._app_vm.loaded_file_keys
        if 0 <= index < len(keys):
            self._app_vm.unload_file(keys[index])

    # ─── FB-10 tooltip ───────────────────────────────────────────────────────

    def file_info(self, index: int) -> SourceInfo | None:
        """SourceInfo for the file at *index*, or None when out of range/unknown."""
        keys = self._app_vm.loaded_file_keys
        if not (0 <= index < len(keys)):
            return None
        try:
            return self._app_vm.session.source_info(keys[index])
        except KeyError:
            return None

    def tooltip_text(self, index: int) -> str | None:
        """Multi-line hover text: path / size / time range / channels+format."""
        info = self.file_info(index)
        if info is None:
            return None
        lines = [str(info.full_path)]
        if info.size_bytes is not None:
            lines.append(f"サイズ: {_fmt_size(info.size_bytes)}")
        if info.t_min is not None and info.t_max is not None:
            duration = info.t_max - info.t_min
            lines.append(
                f"時間範囲: {info.t_min:.3f} – {info.t_max:.3f} s（{duration:.1f} s）"  # noqa: RUF001
            )
        else:
            lines.append("時間範囲: —")
        lines.append(f"チャンネル: {info.n_channels} ch ・ 形式: {info.file_format}")
        return "\n".join(lines)

    def _on_app_change(self, change: str) -> None:
        """Handle notifications from AppViewModel."""
        if change in ("loaded", "unloaded"):
            self._refresh()

    def _refresh(self) -> None:
        """Rebuild the filenames list from the AppViewModel state.

        Recovers each file's display name via the Session public API
        (``source_name``) — never reaching into Session internals.
        """
        files: list[str] = []
        for key in self._app_vm.loaded_file_keys:
            try:
                files.append(self._app_vm.session.source_name(key))
            except KeyError:
                # Fallback to the key if the name cannot be recovered.
                files.append(key)

        self._files = files
        self._notify("files")
