"""SignalPreviewVM (FU-13): supplies preview properties and a downsampled
waveform for a single signal shown in the SignalPreviewWindow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from valisync.core.downsampler.downsampler import Downsampler
from valisync.gui.display_names import display_names as _resolve_display_names

if TYPE_CHECKING:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

_PREVIEW_POINTS = 480  # target sample count for the read-only preview plot


class SignalPreviewVM:
    """Resolves the active file's signal by key and provides preview data.

    No Observable/notify: the window is the sole consumer and re-renders
    explicitly after set_signal (YAGNI)."""

    def __init__(self, app_vm: AppViewModel) -> None:
        self._app_vm = app_vm
        self._signal_key: str | None = None

    def set_signal(self, key: str | None) -> None:
        self._signal_key = key

    def _signal(self) -> Any | None:
        key = self._signal_key
        active_key = self._app_vm.active_file_key
        if not key or not active_key:
            return None
        try:
            for sig in self._app_vm.session.group_signals(active_key):
                if sig.name == key:
                    return sig
        except KeyError:
            return None
        return None

    def _all_loaded_signal_keys(self) -> list[str]:
        """Every signal_key across every currently loaded file (E-0 collision scope).

        Used to resolve display_name so the "名前" row and the windowTitle
        (same rule, spec §1.2) agree on whether a bare name needs qualifying —
        scoped to ALL loaded signals, not just the active file's.
        """
        keys: list[str] = []
        for group_key in self._app_vm.loaded_file_keys:
            try:
                keys.extend(
                    sig.name for sig in self._app_vm.session.group_signals(group_key)
                )
            except KeyError:
                continue
        return keys

    def display_name(self, key: str) -> str:
        """Resolve *key* to its display string (E-0), scoped to all loaded signals.

        *key* is included in the resolution population even when it is not
        itself a currently-loaded signal (e.g. "unknown" keys passed straight
        through from show_signal) so callers never get a KeyError — an
        unresolvable key simply never collides with anything and comes back
        as its own bare name.
        """
        keys = self._all_loaded_signal_keys()
        if key not in keys:
            keys = [*keys, key]
        return _resolve_display_names(keys)[key]

    def properties(self) -> list[tuple[str, str]]:
        sig = self._signal()
        if sig is None:
            return []
        md = sig.metadata or {}
        rows: list[tuple[str, str]] = [("名前", self.display_name(sig.name))]
        unit = str(md.get("unit", ""))
        if unit:
            rows.append(("単位", unit))
        rows.append(("サンプル数", str(len(sig.timestamps))))
        tr = sig.time_range()  # raw min/max -- must NOT use sorted_view (FU-20)
        if tr is not None:
            rows.append(("時間範囲", f"{tr[0]:.4g}–{tr[1]:.4g} s"))  # noqa: RUF001
        # Finite-value min/max computed from the raw values array (NOT
        # finite_view(), which internally calls sorted_view() and would
        # populate the FU-20 sorted-view cache -- see
        # test_time_range_does_not_materialize_sorted_view_cache).
        finite_mask = np.isfinite(sig.values)
        if np.any(finite_mask):
            fvs = sig.values[finite_mask]
            rows.append(("最小値", f"{float(fvs.min()):.6g}"))
            rows.append(("最大値", f"{float(fvs.max()):.6g}"))
        origin = " / ".join(
            b
            for b in (
                sig.bus_type,
                md.get("channel_group_name", ""),
                md.get("source_name", ""),
            )
            if b
        )
        if origin:
            rows.append(("由来", origin))
        comment = str(md.get("comment", ""))
        if comment:
            rows.append(("コメント", comment))
        labels = md.get("value_labels")
        if labels:
            rows.append(("ラベル", ", ".join(f"{k}={v}" for k, v in labels.items())))
        return rows

    def axis_label_parts(self) -> tuple[str, str | None]:
        """Left-axis label parts for the preview plot: (display_name, unit).

        Uses display_name() (E-0) so the raw namespaced key (e.g.
        "mf4_1::VehSpd") never leaks into the plot label -- same rule as the
        "名前" property row and windowTitle (spec §3). Returns ("", None)
        when no signal is resolved (mirrors properties()'s empty-list case).
        """
        sig = self._signal()
        if sig is None:
            return ("", None)
        md = sig.metadata or {}
        unit = str(md.get("unit", "")) or None
        return (self.display_name(sig.name), unit)

    def plot_data(self) -> tuple[np.ndarray, np.ndarray] | None:
        sig = self._signal()
        if sig is None or len(sig.timestamps) == 0:
            return None
        ds = Downsampler().downsample(sig, _PREVIEW_POINTS)
        ts, vs = ds.sorted_view()
        return ts, vs
