"""FileBrowserVM — manages the list of loaded files for master selection.

This ViewModel provides a flat list of filenames to the FileBrowserView
and communicates selection changes back to the AppViewModel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from valisync.gui import strings as S
from valisync.gui.theme import tokens
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
        self._loaded_count = 0
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

    # ─── E-2a: reference file ───────────────────────────────────────────────

    def key_at(self, row: int) -> str | None:
        """The group key for a LOADED row (None for releasing/out-of-range rows).

        Same index guard as :meth:`select_file`/:meth:`unload` — releasing rows
        sit past ``loaded_file_keys`` (see :meth:`_refresh`), so this is
        non-interactive for them by construction.
        """
        keys = self._app_vm.loaded_file_keys
        if 0 <= row < len(keys):
            return keys[row]
        return None

    def is_reference(self, row: int) -> bool:
        """True when *row* is the current reference file's row."""
        key = self.key_at(row)
        return key is not None and key == self._app_vm.reference_file_key

    def is_comparison_mode(self) -> bool:
        """True with 2+ loaded files — the condition for the badge/'重ねる' menu item.

        Delegates to AppViewModel.is_comparison_mode() (spec §4.1): the single
        predicate shared with file_hue_resolver(), so "when does comparison
        mode start" is never checked two different ways.
        """
        return self._app_vm.is_comparison_mode()

    def chip_color(self, row: int) -> str | None:
        """Hex color chip for *row*'s file-hue family (E-2c, spec §4.3).

        None outside comparison mode (chip hidden — same predicate as the
        reference badge) or for an out-of-range/releasing row.
        """
        if not self.is_comparison_mode():
            return None
        key = self.key_at(row)
        if key is None:
            return None
        hue = self._app_vm.file_hue_index.get(key)
        if hue is None:
            return None
        palette = tokens.active().colors.signal_palette
        return palette[hue % len(palette)].hex

    def set_reference(self, row: int) -> None:
        """Set *row*'s file as the reference (no-op for releasing/out-of-range rows)."""
        key = self.key_at(row)
        if key is not None:
            self._app_vm.set_reference_file(key)

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
                f"時間範囲: {info.t_min:.3f}–{info.t_max:.3f} s（{duration:.1f} s）"  # noqa: RUF001
            )
        else:
            lines.append("時間範囲: —")
        lines.append(f"チャンネル: {info.n_channels} ch ・ 形式: {info.file_format}")
        return "\n".join(lines)

    def _on_app_change(self, change: str) -> None:
        """Handle notifications from AppViewModel."""
        if change in ("loaded", "unloaded", "releasing", "reference"):
            self._refresh()

    def _refresh(self) -> None:
        """Rebuild the row list: loaded files first, then still-releasing files.

        Releasing rows sit AFTER loaded rows so the existing index guards in
        select_file/unload (index < len(loaded_file_keys)) make them no-op —
        i.e. non-interactive by construction (FU-16).

        The reference file's row gets a badge suffix (E-2a, spec §2), but only
        in comparison mode (2+ loaded files) — a single loaded file is always
        implicitly "the reference" and showing the badge then would be noise
        (and break the frozen single-file catalogue).
        """
        comparison_mode = self.is_comparison_mode()
        reference_key = self._app_vm.reference_file_key
        loaded: list[str] = []
        for key in self._app_vm.loaded_file_keys:
            try:
                name = self._app_vm.session.source_name(key)
            except KeyError:
                # Fallback to the key if the name cannot be recovered.
                name = key
            if comparison_mode and key == reference_key:
                name += S.FILE_REFERENCE_BADGE_SUFFIX
            loaded.append(name)
        releasing = [name for _key, name in self._app_vm.releasing_files]
        self._loaded_count = len(loaded)
        self._files = loaded + releasing
        self._notify("files")

    def is_releasing(self, row: int) -> bool:
        """True when the row at *row* is a still-releasing (spinner) placeholder."""
        return row >= self._loaded_count
