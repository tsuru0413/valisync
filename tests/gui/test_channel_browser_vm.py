"""Tests for ChannelBrowserVM refactored for master-detail (Task 2.1).

Tests verify:
- tree_groups() reports one row per **physical channel** (E-2) and shown_count()
  counts the *columns* those rows present
- unit/tooltip data reaches the tree via column_names_for() (rows no longer
  carry their leaves — the tree model synthesizes children on demand)
- VM updates when AppViewModel.active_file_key changes
- set_filter() narrows what tree_groups()/shown_count()/column_names_for() report

Note (Task 0, deferred-column-expansion plan): the flat `ChannelBrowserVM.signals`
property and its `SignalItem` element type were production-dead (only
SignalTreeModel, driven by tree_groups(), backs the real channel-browser tree)
and have been deleted. Tests that used to enumerate `vm.signals` now assert
"which signals are shown" via `tree_groups()` instead.
"""

from __future__ import annotations

from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition, Signal
from valisync.gui import strings as S
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM

# ─── Helpers ────────────────────────────────────────────────────────────────


def _csv_format() -> FormatDefinition:
    return FormatDefinition(
        name="test",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )


def _write_csv(path: Path) -> Path:
    path.write_text("t,sig_a,sig_b\n0.0,1.0,4.0\n1.0,2.0,5.0\n", encoding="utf-8")
    return path


def _setup_vm(tmp_path: Path) -> tuple[ChannelBrowserVM, AppViewModel, str]:
    app_vm = AppViewModel()
    csv_file = _write_csv(tmp_path / "data.csv")
    key = app_vm.request_load(csv_file, _csv_format())
    vm = ChannelBrowserVM(app_vm)
    return vm, app_vm, key


def _cb_vm_with_signal(
    tmp_path: Path,
    key_orig: str,
    metadata: dict[str, object] | None = None,
    bus_type: str = "",
    n_samples: int = 10,
) -> ChannelBrowserVM:
    """Build a ChannelBrowserVM with one fake Signal active under "test_key".

    Follows the existing group_signals-injection pattern used elsewhere in
    this module: tooltip_for only needs Signal fields, so a real loaded file
    is unnecessary.
    """
    import numpy as np

    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    sig = Signal(
        name=f"test_key::{key_orig}",
        timestamps=np.arange(float(n_samples)),
        values=np.zeros(n_samples),
        file_format="MDF4",
        bus_type=bus_type,
        source_file="test.mf4",
        metadata=dict(metadata) if metadata else {},
    )

    app_vm.session.group_signals = lambda key: [sig]  # type: ignore[method-assign]
    app_vm.set_active_file("test_key")
    return vm


def _leaf_key(vm: ChannelBrowserVM, orig: str) -> str:
    """Look up a column's namespaced key by its original name.

    E-2: tree_groups() rows are physical channels and no longer carry their
    leaves, so the columns come from column_names_for() — the same API the
    tree model synthesizes children from.
    """
    for _name, _unit, base_key, _count, _single in vm.tree_groups():
        for o, _u, key in vm.column_names_for(base_key):
            if o == orig:
                return key
    raise AssertionError(f"column {orig!r} not found in tree_groups()")


# ─── Tests ──────────────────────────────────────────────────────────────────


def test_initial_tree_groups_is_empty() -> None:
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    assert vm.tree_groups() == []
    assert vm.shown_count() == 0


def test_signals_populated_when_file_active(tmp_path: Path) -> None:
    vm, app_vm, key = _setup_vm(tmp_path)

    app_vm.set_active_file(key)

    assert vm.shown_count() == 2
    bases = {name for name, *_rest in vm.tree_groups()}
    assert bases == {"sig_a", "sig_b"}


def test_tree_groups_includes_unit(tmp_path: Path) -> None:
    # We can't easily set unit in CSV yet via request_load without core changes,
    # but we can mock or use a fake signal in the session.
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    import numpy as np

    sig = Signal(
        name="test_key::speed",
        timestamps=np.array([0.0, 1.0]),
        values=np.array([10.0, 20.0]),
        file_format="MDF4",
        bus_type="",
        source_file="test.mf4",
        metadata={"unit": "km/h"},
    )

    # Inject a fake signal via the per-file public API the VM now uses.
    app_vm.session.group_signals = lambda key: [sig]
    app_vm.set_active_file("test_key")

    rows = vm.tree_groups()
    assert len(rows) == 1
    name, unit, base_key, count, single = rows[0]
    assert name == "speed"
    assert unit == "km/h"
    assert count == 1
    # 1 列の行は実列の identity を持つ (合成 base_key ではない)
    assert single == ("speed", "test_key::speed")
    assert vm.column_names_for(base_key) == [("speed", "km/h", "test_key::speed")]


def test_tooltip_for_lists_value_labels(tmp_path: Path) -> None:
    """value_labels 持ち信号の tooltip_for に『ラベル: 0=OFF, 1=LEFT, 2=RIGHT』(LD-07)."""
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    import numpy as np

    sig = Signal(
        name="test_key::TurnSig",
        timestamps=np.array([0.0, 1.0]),
        values=np.array([0.0, 1.0]),
        file_format="MDF4",
        bus_type="",
        source_file="test.mf4",
        metadata={"value_labels": {0.0: "OFF", 1.0: "LEFT", 2.0: "RIGHT"}},
    )

    app_vm.session.group_signals = lambda key: [sig]
    app_vm.set_active_file("test_key")

    key = _leaf_key(vm, "TurnSig")
    assert "ラベル: 0=OFF, 1=LEFT, 2=RIGHT" in vm.tooltip_for(key)


def test_tooltip_for_truncates_after_8(tmp_path: Path) -> None:
    """9 件以上は先頭 8 件 + 『… (全 n 件)』(LD-07)."""
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    import numpy as np

    value_labels = {float(i): f"S{i}" for i in range(10)}
    sig = Signal(
        name="test_key::Many",
        timestamps=np.array([0.0, 1.0]),
        values=np.array([0.0, 1.0]),
        file_format="MDF4",
        bus_type="",
        source_file="test.mf4",
        metadata={"value_labels": value_labels},
    )

    app_vm.session.group_signals = lambda key: [sig]
    app_vm.set_active_file("test_key")

    key = _leaf_key(vm, "Many")
    tip = vm.tooltip_for(key)
    assert tip.endswith("… (全 10 件)")
    assert "8=S8" not in tip.split("…")[0]


def test_tooltip_for_omits_labels_without_value_labels(tmp_path: Path) -> None:
    """value_labels が無い信号の tooltip_for に『ラベル:』行は無い。"""
    vm, app_vm, key = _setup_vm(tmp_path)
    app_vm.set_active_file(key)

    keys = [
        k
        for _n, _u, base_key, _c, _s in vm.tree_groups()
        for _o, _unit, k in vm.column_names_for(base_key)
    ]
    assert keys  # sanity: the file actually has signals
    assert all("ラベル:" not in vm.tooltip_for(k) for k in keys)


def test_tooltip_for_full_metadata(tmp_path: Path) -> None:
    # MDF 相当: unit + comment + channel_group_name + source_name + value_labels
    vm = _cb_vm_with_signal(
        tmp_path,
        key_orig="gear",
        metadata={
            "unit": "-",
            "comment": "現在のギア段",
            "channel_group_name": "PT_CAN",
            "source_name": "ECU1",
            "value_labels": {0: "N", 1: "D"},
        },
        bus_type="CAN",
        n_samples=1234,
    )
    key = _leaf_key(vm, "gear")
    tip = vm.tooltip_for(key)
    assert "単位: -" in tip
    assert "サンプル数: 1234" in tip
    assert "CAN" in tip and "PT_CAN" in tip and "ECU1" in tip  # 由来
    assert "現在のギア段" in tip  # コメント
    assert "N" in tip and "D" in tip  # value_labels (LD-07)


def test_tooltip_for_csv_omits_absent_rows(tmp_path: Path) -> None:
    # CSV 相当: unit のみ、bus_type 空、comment/group/source/labels なし
    vm = _cb_vm_with_signal(
        tmp_path,
        key_orig="speed",
        metadata={"unit": "km/h"},
        bus_type="",
        n_samples=50,
    )
    key = _leaf_key(vm, "speed")
    tip = vm.tooltip_for(key)
    assert "単位: km/h" in tip
    assert "サンプル数: 50" in tip
    assert "由来:" not in tip  # bus_type/group/source 全欠損 -> 由来行なし
    assert "コメント:" not in tip  # comment なし
    assert "ラベル:" not in tip  # value_labels なし


def test_tooltip_for_unknown_key_empty(tmp_path: Path) -> None:
    vm = _cb_vm_with_signal(tmp_path, key_orig="speed", metadata={"unit": "km/h"})
    assert vm.tooltip_for("nonexistent::key") == ""


def test_signals_clears_when_active_file_unset(tmp_path: Path) -> None:
    vm, app_vm, key = _setup_vm(tmp_path)
    app_vm.set_active_file(key)
    assert vm.shown_count() == 2

    app_vm.set_active_file(None)
    assert vm.shown_count() == 0
    assert vm.tree_groups() == []


def test_filter_narrows_flat_list(tmp_path: Path) -> None:
    vm, app_vm, key = _setup_vm(tmp_path)
    app_vm.set_active_file(key)

    vm.set_filter("sig_a")
    assert vm.shown_count() == 1
    assert [name for name, *_rest in vm.tree_groups()] == ["sig_a"]


def test_active_file_switch_fetches_only_active_group_no_full_scan(
    tmp_path: Path,
) -> None:
    """R5.2: switching the Active File reads only that file's signals via
    group_signals(active) and never scans the whole Session (session.signals).

    Guards the per-file mechanism (introduced in S1) that keeps the update cheap
    — O(active-file signals), not O(total signals) — against a regression that
    reintroduces a full scan. A robust, hardware-independent stand-in for the
    old unverifiable wall-clock "within 100ms".
    """
    vm, app_vm, key = _setup_vm(tmp_path)
    session = app_vm.session
    real_group_signals = session.group_signals

    full_scan_calls = 0
    group_calls: list[str] = []

    def spy_signals() -> list[Signal]:
        nonlocal full_scan_calls
        full_scan_calls += 1
        return []

    def spy_group_signals(k: str) -> list[Signal]:
        group_calls.append(k)
        return real_group_signals(k)

    session.signals = spy_signals  # type: ignore[method-assign]
    session.group_signals = spy_group_signals  # type: ignore[method-assign]

    app_vm.set_active_file(key)
    bases = {
        name for name, *_rest in vm.tree_groups()
    }  # the master-detail update the view consumes

    assert bases == {"sig_a", "sig_b"}
    assert group_calls == [key]  # only the active group was fetched
    assert full_scan_calls == 0  # the full Session was never scanned


# ─── Header / Empty State Tests (FB-05/09) ──────────────────────────────────


def _loaded_vm(tmp_path: Path) -> tuple[AppViewModel, ChannelBrowserVM, str]:
    fmt = FormatDefinition(
        name="fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )
    path = tmp_path / "d.csv"
    path.write_text("t,speed,brake\n0.0,1.0,0.0\n1.0,2.0,1.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    key = app_vm.request_load(path, fmt)
    return app_vm, ChannelBrowserVM(app_vm), key


def test_header_none_selected(tmp_path: Path) -> None:
    """#14: 未選択分岐も strings 経由 (S.CHANNEL_HEADER_NO_FILE) — 旧直書き
    "ファイル未選択" からの是正 (D-1 の非対称を解消)。"""
    app_vm, vm, _key = _loaded_vm(tmp_path)
    app_vm.set_active_file(None)
    assert vm.header_text() == S.CHANNEL_HEADER_NO_FILE
    assert vm.empty_state() == "none_selected"


def test_header_counts_and_has_rows(tmp_path: Path) -> None:
    """#14: ヘッダーはファイル名を含まず件数のみ。どのファイルかは右上
    ファイルブラウザの選択で判別 (spec §1)。"""
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    header = vm.header_text()
    assert header == S.CHANNEL_HEADER_COUNT_TMPL.format(total=2, shown=2)
    assert "d.csv" not in header
    assert vm.empty_state() == "has_rows"


def test_no_match_state_and_query(tmp_path: Path) -> None:
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    vm.set_filter("xyz123")
    assert vm.empty_state() == "no_match"
    assert vm.filter_query() == "xyz123"
    header = vm.header_text()
    assert header == S.CHANNEL_HEADER_COUNT_TMPL.format(total=2, shown=0)
    assert "d.csv" not in header


def test_no_channels_state(tmp_path: Path, monkeypatch) -> None:
    app_vm, vm, key = _loaded_vm(tmp_path)
    app_vm.set_active_file(key)
    # mdf_loader は全チャンネル skip 時に 0ch グループを登録し得る
    # (production 到達可能・catalog LD-05)。ここでは決定的な単体テストのため
    # session 面で直接再現する(spec §4.2)。
    monkeypatch.setattr(app_vm.session, "group_signals", lambda _key: [])
    assert vm.empty_state() == "no_channels"
    header = vm.header_text()
    assert header == S.CHANNEL_HEADER_EMPTY_TMPL
    assert "d.csv" not in header


# ─── FU-11 Performance: Precompute + Memo Tests ──────────────────────────────


def test_one_keystroke_fetches_group_at_most_once(tmp_path: Path) -> None:
    """FU-11: 1 打鍵(model reset + header_text + empty_state)で group_signals は
    高々 1 回(prep 構築時のみ)。同一 active_file の 2 打鍵目は 0 回。per-access
    再取得への回帰を防ぐ構造アサート(既存 no-full-scan spy パターンの延長)。"""
    vm, app_vm, key = _setup_vm(tmp_path)
    session = app_vm.session
    real_group_signals = session.group_signals
    calls: list[str] = []

    def spy(k: str) -> list[Signal]:
        calls.append(k)
        return real_group_signals(k)

    session.group_signals = spy  # type: ignore[method-assign]
    app_vm.set_active_file(key)  # 遅延ビルド: ここでは fetch しない

    calls.clear()
    # 1 打鍵目: View/Model 相当の 3 消費
    vm.set_filter("s")
    vm.tree_groups()  # SignalTreeModel._on_vm_change
    vm.header_text()  # _refresh_state 1
    vm.empty_state()  # _refresh_state 2
    assert len(calls) == 1  # prep を 1 度だけ構築し全消費で共有

    calls.clear()
    # 2 打鍵目: 同一 active_file → prep/memo で完全充足
    vm.set_filter("si")
    vm.tree_groups()
    vm.header_text()
    vm.empty_state()
    assert calls == []


def test_active_file_switch_invalidates_prep_no_leak(tmp_path: Path) -> None:
    """FU-11: active file 切替で precompute を作り直す。前ファイルの信号が stale
    キャッシュ経由で漏れないことを保証。"""
    app_vm = AppViewModel()
    fa = tmp_path / "a.csv"
    fa.write_text("t,alpha,gamma\n0,1,2\n1,3,4\n", encoding="utf-8")
    fb = tmp_path / "b.csv"
    fb.write_text("t,beta,delta\n0,1,2\n1,3,4\n", encoding="utf-8")
    ka = app_vm.request_load(fa, _csv_format())
    kb = app_vm.request_load(fb, _csv_format())
    vm = ChannelBrowserVM(app_vm)

    app_vm.set_active_file(ka)
    assert {name for name, *_rest in vm.tree_groups()} == {"alpha", "gamma"}

    app_vm.set_active_file(kb)
    assert {name for name, *_rest in vm.tree_groups()} == {
        "beta",
        "delta",
    }  # alpha/gamma を漏らさない


def _synth_sig(name: str, phys: str | None = None) -> Signal:
    """合成 Signal 1 本。

    E-2: 展開列はローダーが metadata['physical_channel'] を付けるので、合成
    フィクスチャでも *親を立てたいときは* phys を明示する。付けないと fallback
    (physical_channel 欠落 = 1 列 1 物理チャンネル) で各列が自分自身の物理
    チャンネルになり、親が 1 つも生まれず assert が vacuous 化する。
    """
    import numpy as np

    metadata: dict[str, object] = {"unit": "V"}
    if phys is not None:
        metadata["physical_channel"] = phys
    return Signal(
        name=name,
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata=metadata,
    )


def test_tree_groups_buckets_arrays_under_base(tmp_path: Path) -> None:
    """E-2: 列を metadata['physical_channel'] でグルーピング (1 行 = 1 物理チャンネル)。

    配列は 1 行 + 複数列 (子は column_names_for で要求時合成)・単一列は実列の
    identity を持つ葉。FU-22 B の base(最初の [ or . 以前)文字列解析からの
    意図的 supersede — ACC.Speed と P.x が文字列では区別できないため。
    """
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    app_vm.session.group_signals = lambda key: [
        _synth_sig("g::Arr[0]", phys="Arr"),
        _synth_sig("g::Arr[1]", phys="Arr"),
        _synth_sig("g::Arr[2]", phys="Arr"),
        _synth_sig("g::Scalar", phys="Scalar"),
        _synth_sig("g::Struct.field", phys="Struct"),
    ]
    app_vm.set_active_file("g")

    rows = vm.tree_groups()
    assert [r[0] for r in rows] == ["Arr", "Scalar", "Struct"]  # first-seen order
    by_name = {r[0]: r for r in rows}

    arr = by_name["Arr"]
    assert arr[3] == 3  # column_count
    assert arr[4] is None  # 複数列 -> 親
    assert vm.column_names_for(arr[2]) == [  # (orig, unit, key)
        ("Arr[0]", "V", "g::Arr[0]"),
        ("Arr[1]", "V", "g::Arr[1]"),
        ("Arr[2]", "V", "g::Arr[2]"),
    ]

    scalar = by_name["Scalar"]
    assert scalar[3] == 1
    assert scalar[4] == ("Scalar", "g::Scalar")
    assert vm.column_names_for(scalar[2]) == [("Scalar", "V", "g::Scalar")]

    # 単一フィールド構造化は「展開したのに 1 列」— 実列の identity を持つ葉 (C1)
    struct = by_name["Struct"]
    assert struct[3] == 1
    assert struct[4] == ("Struct.field", "g::Struct.field")
    assert vm.column_names_for(struct[2]) == [("Struct.field", "V", "g::Struct.field")]


def test_tree_groups_honors_filter(tmp_path: Path) -> None:
    """E-2: フィルタは **列名** にマッチし、一致列 0 の行は出ない。

    子レベルの検証 (絞り込んだ親を展開したら一致列だけ) は tree_groups() が葉を
    返さなくなったため column_names_for() 経由へ等価移送 (弱めていない)。
    """
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    app_vm.session.group_signals = lambda k: [
        _synth_sig("g::Arr[0]", phys="Arr"),
        _synth_sig("g::Arr[1]", phys="Arr"),
        _synth_sig("g::Speed", phys="Speed"),
        _synth_sig("g::Brake", phys="Brake"),
    ]
    app_vm.set_active_file("g")

    # no filter -> all rows
    assert [r[0] for r in vm.tree_groups()] == ["Arr", "Speed", "Brake"]

    # filter matches a channel name (prefix of its columns) -> that row, all columns
    vm.set_filter("arr")
    rows = vm.tree_groups()
    assert [r[0] for r in rows] == ["Arr"]
    assert [o for o, _u, _k in vm.column_names_for(rows[0][2])] == ["Arr[0]", "Arr[1]"]
    assert rows[0][4] is None  # 2 列を提示 -> 親のまま

    # filter matches a specific column -> only that row, only matching columns
    vm.set_filter("arr[1]")
    rows = vm.tree_groups()
    assert [r[0] for r in rows] == ["Arr"]
    assert [o for o, _u, _k in vm.column_names_for(rows[0][2])] == ["Arr[1]"]
    # 1 列に落ちた行は今日どおり葉 — 実列キーでドラッグできる
    assert rows[0][4] == ("Arr[1]", "g::Arr[1]")
    assert rows[0][3] == 2  # column_count はフィルタ非依存の実列数のまま

    # filter matches a scalar
    vm.set_filter("speed")
    assert [r[0] for r in vm.tree_groups()] == ["Speed"]

    # no match -> empty
    vm.set_filter("zzz")
    assert vm.tree_groups() == []


def test_non_contiguous_columns_stay_in_their_own_row(tmp_path: Path) -> None:
    """m1: 1 物理チャンネルの列が **非隣接** でも span が実測どおり分かれる。

    実 mf4 は今のところ列を連続で並べるが、連続性を仮定した実装 (span を常に
    伸ばす) はここで割り込んだ別チャンネルを巻き込む。
    sabotage: _ensure_prep の span 分岐を `spans[-1] = (last_start, i + 1)` 固定に
    すると X が Y を飲み込んで RED。
    """
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    app_vm.session.group_signals = lambda k: [
        _synth_sig("g::X[0]", phys="X"),
        _synth_sig("g::Y", phys="Y"),  # 割り込み
        _synth_sig("g::X[1]", phys="X"),
    ]
    app_vm.set_active_file("g")

    rows = {r[0]: r for r in vm.tree_groups()}
    assert set(rows) == {"X", "Y"}
    assert rows["X"][3] == 2  # column_count は 2 (Y を数えない)
    assert [o for o, _u, _k in vm.column_names_for(rows["X"][2])] == ["X[0]", "X[1]"]
    assert [o for o, _u, _k in vm.column_names_for(rows["Y"][2])] == ["Y"]
    assert vm.shown_count() == 3


def test_shown_count_matches_matched_column_total(tmp_path: Path) -> None:
    """E-2 (C2/C3): shown_count は **一致列の総数** で、木に出る子行の総数と一致する。

    「tree_groups() の全リーフ数」という概念が消えたので (行は葉を持たない)、
    総数側は _group_total() = sum(column_count) と突き合わせ、
    0 <= shown_count() <= _group_total() の不変条件を検証する。
    """
    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)

    app_vm.session.group_signals = lambda k: [
        _synth_sig("g::a"),
        _synth_sig("g::b"),
        _synth_sig("g::ab"),
    ]
    app_vm.set_active_file("g")

    def _matched_columns() -> int:
        return sum(
            len(vm.column_names_for(base_key))
            for _n, _u, base_key, _c, _s in vm.tree_groups()
        )

    assert vm._group_total() == 3  # フィルタ非依存の総列数
    assert vm.shown_count() == 3  # no filter -> total
    assert vm.shown_count() == _matched_columns()
    vm.set_filter("a")
    assert vm.shown_count() == 2  # "a", "ab"
    assert vm.shown_count() == _matched_columns()
    assert vm._group_total() == 3  # total はフィルタで動かない
    vm.set_filter("zzz")
    assert vm.shown_count() == 0
    assert vm.shown_count() == _matched_columns()
