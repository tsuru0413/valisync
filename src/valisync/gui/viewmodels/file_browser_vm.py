"""FileBrowserVM — manages the list of loaded files for master selection.

This ViewModel provides a flat list of filenames to the FileBrowserView
and communicates selection changes back to the AppViewModel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from valisync.gui.viewmodels.observable import Observable

if TYPE_CHECKING:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel


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
