"""SignalPreviewVM (FU-13): supplies preview properties and a downsampled
waveform for a single signal shown in the SignalPreviewWindow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from valisync.core.downsampler.downsampler import Downsampler
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
from valisync.gui.display_names import display_names as _resolve_display_names
from valisync.gui.display_names import split_key

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
        if not key:
            return None
        # E-3: 列キー (Mat[0] / Pos.x) は反転後 group_signals に載らない。線形走査の
        # ままだと解決できず、プレビュー窓が「この信号はプレビューできません」で
        # 静かに真っ白になる — 設計された空状態と見分けがつかない。解決器は物理
        # チャンネルをそのまま返し、列は最長一致で鋳造する。
        group_key, bare = split_key(key)
        sig = self._app_vm.session.resolve_signal(key)
        if sig is None:
            return None
        if group_key and self._app_vm.session.is_container_channel(group_key, bare):
            # 配列/構造体チャンネルの親は 1 本の波形を持たない。ここで弾かないと
            # properties() の np.isfinite(sig.values) がチャンネル全読み (prod で
            # 96 MB/本) を誘発し、Downsampler が 2-D 配列に出くわす。判定は列構造
            # (名前) だけで済むので、値には触れない。
            return None
        return sig

    def display_name(self, key: str) -> str:
        """Resolve *key* to its display string (E-0), scoped to all loaded signals.

        衝突判定に必要なのは「他の読み込み済みファイルに同じ bare 名の列があるか」
        だけなので、母数は全ファイルの全列ではなく **他ファイルごとの同名 1 本**へ
        縮約する (prod 264k 列を呼び出しのたびに列挙しない)。distinct group_key の
        数だけが結果を決めるので、``display_names`` の規則そのものは変わらない。

        判定に ``resolve_signal`` を使わないのが要点: 鋳造した列は
        ``_resolved_by_key`` へ入る。E-4a で LRU が入ったので恒久滞留はしなく
        なったが、**非 pin の枠を食ってプロット中でない列を押し出す** (spec §5.5)
        ため、プレビュー窓のタイトルやプロパティの「名前」を出すだけで他ファイル
        ぶんの列を鋳造してはならない。``has_column`` (列の存在) と
        ``is_container_channel`` (親チャンネルの存在) はどちらも ColumnRecord の
        列構造だけを見るので、1 本も鋳造しない。2 つを OR するのは旧実装
        (``resolve_signal is not None``) の母数を厳密に保つため — 解決できるキーは
        「列」か「物理チャンネル (容器を含む)」のどちらかである。

        *key* は読み込み済み信号でなくても (show_signal から素通しされた未知キー等)
        常に母数に含めるので KeyError にはならない — 何とも衝突せず bare 名で返る。
        """
        group_key, bare = split_key(key)
        if not group_key:
            # 名前空間なしのキーは所属ファイルが無く、衝突判定の対象にならない。
            return bare
        session = self._app_vm.session
        population = [key]
        for other in self._app_vm.loaded_file_keys:
            if other == group_key:
                continue
            if session.has_column(other, bare) or session.is_container_channel(
                other, bare
            ):
                population.append(f"{other}{KEY_SEPARATOR}{bare}")
        return _resolve_display_names(population)[key]

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
