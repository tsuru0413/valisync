"""ブラウザは物理チャンネル単位で行を作る (1 行 = 1 物理チャンネル)。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tests.mdf4_helpers import (
    CAN,
    write_mdf4,
    write_mdf4_2d,
    write_mdf4_interleaved_arrays,
    write_mdf4_single_column_shapes,
)
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
from valisync.core.models import Delimiter, FormatDefinition, Signal
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM


def _vm_for(path: Path) -> tuple[ChannelBrowserVM, AppViewModel]:
    app_vm = AppViewModel()
    key = app_vm.request_load(path)  # MDF4 は format_def 不要
    app_vm.set_active_file(key)
    return ChannelBrowserVM(app_vm), app_vm


def _vm(tmp_path: Path) -> ChannelBrowserVM:
    # write_mdf4_2d = Mat 3 列 + Clean 1 列 -> 2 行 / 4 列
    return _vm_for(write_mdf4_2d(tmp_path))[0]


def test_tree_groups_is_one_row_per_physical_channel(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    rows = vm.tree_groups()
    names = [name for name, _unit, _key, _n, _single in rows]
    assert names == ["Mat", "Clean"]
    assert not any(n.startswith("Mat[") for n in names)  # 列は行にならない
    mat = next(r for r in rows if r[0] == "Mat")
    assert mat[3] == 3  # column_count
    assert mat[4] is None  # 複数列 -> 親 (single_column なし)


def test_dotted_channel_name_is_not_split(tmp_path: Path) -> None:
    # ACC.Speed は「ACC の下の Speed」ではなく 1 本の物理チャンネル (平坦化)
    path = write_mdf4(
        tmp_path / "dot.mf4",
        [
            {
                "name": "ACC.Speed",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [1.0, 2.0],
            },
            {
                "name": "ACC.Accel",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [3.0, 4.0],
            },
        ],
    )
    vm, _app_vm = _vm_for(path)
    names = [name for name, _u, _k, _n, _s in vm.tree_groups()]
    assert names == ["ACC.Speed", "ACC.Accel"]  # "ACC" 1 行ではない


def test_column_names_for_returns_only_that_channels_columns(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    mat = next(r for r in vm.tree_groups() if r[0] == "Mat")
    cols = vm.column_names_for(mat[2])
    assert [c[0] for c in cols] == ["Mat[0]", "Mat[1]", "Mat[2]"]


def test_shown_count_counts_columns_not_rows(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    # Mat の 3 列 + Clean の 1 列 = 4 (行数 2 ではない)
    assert vm.shown_count() == 4


def test_group_total_counts_columns_not_rows(tmp_path: Path) -> None:
    """C2: total も shown も「列」で数える。

    行数を total にすると prod で「4,324 ch 中 264,004 ch を表示」= shown > total
    の自己矛盾になる (ユーザー決定 2)。
    sabotage: _group_total() を len(self._prep) に戻すと RED。
    """
    vm = _vm(tmp_path)  # Mat 3 列 + Clean 1 列 = 2 行 / 4 列
    rows = vm.tree_groups()
    total_cols = sum(r[3] for r in rows)
    assert total_cols > len(rows)  # fixture が配列を含む担保 (assert の vacuous 化防止)
    assert vm._group_total() == total_cols
    for q in ("", "mat", "mat[1", "zzz"):
        vm.set_filter(q)
        # 不変条件: 0 <= shown <= total (単位混在なら成り立たない)
        assert 0 <= vm.shown_count() <= total_cols
        assert vm._group_total() == total_cols  # total はフィルタ非依存


def test_single_column_rows_carry_the_real_column_identity(tmp_path: Path) -> None:
    """C1: 「展開したのに 1 列」の行は、合成 base_key ではなく実列の identity を持つ。

    sabotage: single_column の代わりに base_key/physical_name を返すと 3 本とも RED。
    """
    vm, app_vm = _vm_for(write_mdf4_single_column_shapes(tmp_path))
    rows = {
        name: (base_key, n, single)
        for name, _u, base_key, n, single in vm.tree_groups()
    }
    assert set(rows) == {"Mono", "P", "Q", "Clean"}
    sig_map = app_vm.session.signal_map()
    for phys, expected_orig in (
        ("Mono", "Mono[0]"),
        ("P", "P.x"),
        ("Q", "Q.x"),
        ("Clean", "Clean"),
    ):
        base_key, n, single = rows[phys]
        assert n == 1, f"{phys} should have exactly one column"
        assert single is not None, f"{phys}: single_column must carry the real column"
        orig, ns_name = single
        assert orig == expected_orig
        assert sig_map.get(ns_name) is not None, f"{ns_name} must resolve to a Signal"
        if phys != "Clean":
            # 合成ハンドルは実在しない — これを葉キーにするのが C1 のバグ
            assert sig_map.get(base_key) is None


def test_duplicate_raw_names_stay_two_rows(tmp_path: Path) -> None:
    """I1: LD-08 同名チャンネルは 2 行 (現行 _base_of の融合挙動の意図的 supersede)。"""
    path = write_mdf4(
        tmp_path / "dup.mf4",
        [
            {
                "name": "sig",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [1.0, 2.0],
            },
            {
                "name": "sig",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [3.0, 4.0],
            },
        ],
    )
    vm, app_vm = _vm_for(path)
    rows = vm.tree_groups()
    assert [name for name, *_rest in rows] == ["sig[0]", "sig[1]"]
    sig_map = app_vm.session.signal_map()
    for _name, _u, _bk, n, single in rows:
        assert n == 1 and single is not None
        assert sig_map.get(single[1]) is not None


def test_column_spans_do_not_assume_contiguity(tmp_path: Path) -> None:
    """m1: 配列 / スカラー / 配列 の順でも各行が自分の列だけを返す。"""
    vm, _app_vm = _vm_for(write_mdf4_interleaved_arrays(tmp_path))
    by_name = {name: base_key for name, _u, base_key, _n, _s in vm.tree_groups()}
    assert [c[0] for c in vm.column_names_for(by_name["A"])] == ["A[0]", "A[1]"]
    assert [c[0] for c in vm.column_names_for(by_name["B"])] == ["B[0]", "B[1]"]
    assert [c[0] for c in vm.column_names_for(by_name["S"])] == ["S"]


def test_every_exposed_key_resolves(tmp_path: Path) -> None:
    """恒久ガード: VM が外へ出す全キーが実 Signal に当たる (葉キーの不変条件)。"""
    vm, app_vm = _vm_for(write_mdf4_single_column_shapes(tmp_path))
    sig_map = app_vm.session.signal_map()
    for _name, _u, base_key, _n, single in vm.tree_groups():
        if single is not None:
            assert sig_map.get(single[1]) is not None
        for _orig, _unit, key in vm.column_names_for(base_key):
            assert sig_map.get(key) is not None


# ─── 件数表示 (ch 単位) とフィルタメモ (Task 4) ────────────────────────────────


def test_header_counts_columns_in_ch_units(tmp_path: Path) -> None:
    vm = _vm(tmp_path)  # Mat 3 列 + Clean 1 列 = 2 行 / 4 列
    assert vm.header_text() == "4 ch 中 4 ch を表示"


def test_header_total_is_columns_not_rows(tmp_path: Path) -> None:
    """C2: total も shown も「列」。行数を total にすると shown > total になる。"""
    vm = _vm(tmp_path)
    rows = vm.tree_groups()
    total_cols = sum(r[3] for r in rows)  # r[3] = column_count
    assert total_cols > len(rows)  # fixture が配列を含むことの担保
    assert vm.header_text() == f"{total_cols} ch 中 {total_cols} ch を表示"
    for q in ("", "mat", "mat[1", "zzz"):
        vm.set_filter(q)
        assert 0 <= vm.shown_count() <= total_cols


def test_filter_matches_column_names_and_keeps_parent(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    vm.set_filter("mat")
    rows = vm.tree_groups()
    assert [r[0] for r in rows] == ["Mat"]  # Clean は落ちる
    assert vm.shown_count() == 3
    assert vm.header_text() == "4 ch 中 3 ch を表示"


def test_column_names_for_honors_filter(tmp_path: Path) -> None:
    """C3: 絞り込んだ親を展開しても **一致列だけ** が出る
    (test_channel_browser_vm.py:504-508 の子レベル assert の等価移送先)。"""
    vm = _vm(tmp_path)
    vm.set_filter("mat[1")
    mat = next(r for r in vm.tree_groups() if r[0] == "Mat")
    assert [c[0] for c in vm.column_names_for(mat[2])] == ["Mat[1]"]
    assert vm.shown_count() == 1  # ヘッダーと木が同じ基準
    assert vm.header_text() == "4 ch 中 1 ch を表示"


def test_row_filtered_down_to_one_column_becomes_a_real_leaf(tmp_path: Path) -> None:
    """コントローラ決定 3: 絞って 1 列に落ちた行は今日どおり葉 (実キーでドラッグ可)。

    column_count は実列数 (3) のまま = _group_total の単位が壊れない。
    """
    vm, app_vm = _vm_for(write_mdf4_2d(tmp_path))
    vm.set_filter("mat[1")
    mat = next(r for r in vm.tree_groups() if r[0] == "Mat")
    assert mat[3] == 3  # column_count はフィルタ非依存
    assert mat[4] is not None  # single_column = 提示している唯一の列
    orig, ns_name = mat[4]
    assert orig == "Mat[1]"
    assert app_vm.session.signal_map().get(ns_name) is not None


def test_filter_matching_nothing_yields_no_rows(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    vm.set_filter("zzz")
    assert vm.tree_groups() == []
    assert vm.shown_count() == 0
    assert vm.empty_state() == "no_match"


def test_one_filter_application_scans_columns_once(tmp_path: Path) -> None:
    """I3/I2-4: 入力停止 1 回で走る 3 パス (tree_groups / header_text / empty_state) が
    列名走査を 1 回に畳めていること。これが崩れると受け入れの perf 前提が壊れる。"""
    vm = _vm(tmp_path)
    vm.set_filter("mat")
    before = vm.inspect()["filter_scans"]
    vm.tree_groups()
    vm.header_text()
    vm.empty_state()
    assert vm.inspect()["filter_scans"] == before + 1
    vm.tree_groups()  # 同じフィルタの再問い合わせは 0 回
    assert vm.inspect()["filter_scans"] == before + 1
    vm.set_filter("mat[1")
    vm.tree_groups()
    assert vm.inspect()["filter_scans"] == before + 2


def test_filter_memo_does_not_hold_per_column_names(tmp_path: Path) -> None:
    """メモは行数ぶんしか持たない (名前キャッシュ 33 MB の再導入を構造で禁じる)。"""
    vm = _vm(tmp_path)
    vm.set_filter("mat")
    rows = vm.tree_groups()
    assert len(rows) == 1 and rows[0][3] == 3  # 1 行 / 実列数 3
    memo = vm._filter_memo
    assert memo is not None
    assert len(memo[1]) == len(rows)  # 保持は行単位 — 列単位ではない


def test_filter_memo_dropped_on_prep_lifecycle(tmp_path: Path) -> None:
    vm, _app_vm = _vm_for(write_mdf4_2d(tmp_path))
    vm.set_filter("mat")
    vm.tree_groups()
    assert vm._filter_memo is not None
    vm.refresh()
    assert vm._filter_memo is None


def test_vm_never_holds_column_signals(tmp_path: Path) -> None:
    """M5 の強化: VM は列 Signal を **一度も掴まない**。

    E-2 の _group_sigs はファイル 1 本ぶんの列 Signal 実体を掴んでいたので、
    「無効化点で手放す」ことが TeardownService の解放条件だった (掴んだまま
    pending_signals() だけが減ると、ドレインは健全に見えたままメモリが残る)。
    E-3 で列ソースが ColumnRecord になり prep は文字列しか持たなくなるため、
    条件は「無効化で手放す」から「そもそも掴まない」へ強化される。

    id() は使わない (CPython のアドレス再利用で非決定・memory
    gui_id_reuse_flake_object_recreation) — 保持コンテナの中身を直接見る。
    走査は**再帰**にする: トップレベル要素だけを見るオラクルは「行タプルに Signal を
    混ぜ戻す」「dict の値として持つ」という最も現実的な回帰形 (どちらも _prep が
    list[tuple[...]] なので 2 段目に隠れる) を素通りする。
    """
    vm, _app_vm = _vm_for(write_mdf4_2d(tmp_path))
    vm.tree_groups()
    assert vm._prep  # 前提: prep を作れている (assert の vacuous 化防止)

    def _has_signal(obj: object, depth: int = 0) -> bool:
        # depth 3 = 属性 -> list -> tuple -> 要素。VM が持ちうる入れ子はここまでで、
        # 無制限再帰にすると Signal 内部 (values/timestamps) まで潜って遅くなる。
        if isinstance(obj, Signal):
            return True
        if depth < 3 and isinstance(obj, list | tuple | set):
            return any(_has_signal(x, depth + 1) for x in obj)
        if depth < 3 and isinstance(obj, dict):
            return any(_has_signal(x, depth + 1) for x in obj.values())
        return False

    held = [name for name, value in vars(vm).items() if _has_signal(value)]
    assert held == [], f"VM が Signal を保持している: {held}"
    # prep が持つのは列の表示名だけ (Signal でも小文字化コピーでもない)
    assert all(isinstance(c, str) for _n, _u, _bk, cols in vm._prep for c in cols)

    vm.refresh()  # = _invalidate_prep (ライフサイクルは従来どおり)
    assert vm._prep == []
    assert vm._row_by_base_key == {}
    # 手放しても次の問い合わせは _ensure_prep が作り直す (機能は不変)
    assert [row[0] for row in vm.tree_groups()] == ["Mat", "Clean"]


# ─── 列ソースは ColumnRecord (E-3 T4 / spec 追補 S1) ──────────────────────────


def _invert_to_physical_signals(app_vm: AppViewModel, key: str) -> None:
    """session.group_signals を「1 物理チャンネル = Signal 1 個」へ寄せる (T6 の擬似反転)。

    反転後のローダーは列 Signal を 1 つも発行しない。列を group_signals から
    数えている実装は、この差し替えだけで全行が 1 列の葉に潰れる (Mat[1]/Mat[2] が
    木・フィルタ・D&D・プレビュー・エクスポートから同時に消える) — T6 を待たずに
    T4 の受理条件を判定できる唯一の手段。

    差し替えるのは **VM の行/列ソースだけ**: signal_map()/resolve_signal() は実
    ローダーのまま残す (列キーが実 Signal に当たる不変条件を既存 assert が
    そのまま使えるようにするため)。値は読まない — 長さだけ合わせたゼロ配列を
    渡し、元 Signal の遅延ソースには一切触れない (遅延契約)。
    """
    physical: list[Signal] = []
    seen: set[str] = set()
    for sig in app_vm.session.group_signals(key):
        md = sig.metadata or {}
        phys = str(md.get("physical_channel") or sig.name.split(KEY_SEPARATOR, 1)[-1])
        if phys in seen:
            continue
        seen.add(phys)
        physical.append(
            Signal(
                name=f"{key}{KEY_SEPARATOR}{phys}",
                timestamps=sig.timestamps,
                values=np.zeros(len(sig.timestamps)),
                file_format=sig.file_format,
                bus_type=sig.bus_type,
                source_file=sig.source_file,
                metadata=sig.metadata,
            )
        )

    def _physical_only(k: str) -> list[Signal]:
        return list(physical) if k == key else []

    app_vm.session.group_signals = _physical_only  # type: ignore[method-assign]


def test_columns_survive_the_loader_inversion(tmp_path: Path) -> None:
    """S1: 列 Signal が 1 つも無くなっても行は自分の列を全部提示する。

    :65-95 (Mat[0..2] / total_cols > len(rows)) の反転版。
    sabotage: _ensure_prep の列ソースを観測列 (group_signals) へ戻すと Mat が
    1 列の葉に潰れて RED (= 反転で Mat[1]/Mat[2] が UI から消える実バグ)。
    """
    vm, app_vm = _vm_for(write_mdf4_2d(tmp_path))
    key = app_vm.active_file_key or ""
    _invert_to_physical_signals(app_vm, key)
    vm.refresh()

    rows = vm.tree_groups()
    assert [r[0] for r in rows] == ["Mat", "Clean"]
    mat = next(r for r in rows if r[0] == "Mat")
    assert mat[3] == 3  # column_count
    assert mat[4] is None  # 複数列 -> 親 (single_column なし)
    cols = vm.column_names_for(mat[2])
    assert [c[0] for c in cols] == ["Mat[0]", "Mat[1]", "Mat[2]"]

    total_cols = sum(r[3] for r in rows)
    assert total_cols > len(rows)  # 反 vacuous: fixture が配列を含む担保
    assert vm._group_total() == total_cols == 4
    assert vm.shown_count() == 4

    # 合成した列キーは実キー空間に当たる (葉キーの不変条件)
    sig_map = app_vm.session.signal_map()
    for _orig, _unit, col_key in cols:
        assert sig_map.get(col_key) is not None


def test_inverted_filter_still_matches_column_names(tmp_path: Path) -> None:
    """S1: 反転後もフィルタは **列名** に当たる (:194-211 / :203-211 の反転版)。

    sabotage: column_names_for の _matches フィルタを外すと 3 列出て RED。
    """
    vm, app_vm = _vm_for(write_mdf4_2d(tmp_path))
    key = app_vm.active_file_key or ""
    _invert_to_physical_signals(app_vm, key)
    vm.refresh()

    vm.set_filter("mat")
    assert [r[0] for r in vm.tree_groups()] == ["Mat"]  # Clean は落ちる
    assert vm.shown_count() == 3
    assert vm.header_text() == "4 ch 中 3 ch を表示"

    vm.set_filter("mat[1")
    mat = next(r for r in vm.tree_groups() if r[0] == "Mat")
    assert [c[0] for c in vm.column_names_for(mat[2])] == ["Mat[1]"]
    assert vm.shown_count() == 1  # ヘッダーと木が同じ基準 (C3)
    assert vm.header_text() == "4 ch 中 1 ch を表示"
    assert mat[3] == 3  # column_count はフィルタ非依存の実列数のまま
    assert mat[4] == ("Mat[1]", f"{key}{KEY_SEPARATOR}Mat[1]")


def test_inverted_single_column_rows_carry_the_real_column_identity(
    tmp_path: Path,
) -> None:
    """C1 の反転版: 「展開したのに 1 列」は反転後も実列 identity を持つ (:97-124)。

    反転後の group_signals では Signal 名が物理チャンネル名 (Mono/P/Q) になる。
    観測名をそのまま葉キーにすると実在しないキー (mf4_1::Mono) を晒す =
    「見えるのに永久に描かれない行」。記録由来の列名でなければならない。
    sabotage: _columns_of を「常に None (観測を採る)」に変えると 3 本とも RED。
    """
    vm, app_vm = _vm_for(write_mdf4_single_column_shapes(tmp_path))
    key = app_vm.active_file_key or ""
    _invert_to_physical_signals(app_vm, key)
    vm.refresh()

    rows = {
        name: (base_key, n, single)
        for name, _u, base_key, n, single in vm.tree_groups()
    }
    assert set(rows) == {"Mono", "P", "Q", "Clean"}
    sig_map = app_vm.session.signal_map()
    for phys, expected_orig in (
        ("Mono", "Mono[0]"),
        ("P", "P.x"),
        ("Q", "Q.x"),
        ("Clean", "Clean"),
    ):
        base_key, n, single = rows[phys]
        assert n == 1, f"{phys} should have exactly one column"
        assert single == (
            expected_orig,
            f"{key}{KEY_SEPARATOR}{expected_orig}",
        ), f"{phys}: single_column must carry the real column"
        assert sig_map.get(single[1]) is not None
        if phys != "Clean":
            # 合成ハンドルは実在しない — これを葉キーにするのが C1 のバグ
            assert sig_map.get(base_key) is None


def test_group_total_agrees_with_session_total_column_count(tmp_path: Path) -> None:
    """U2: ヘッダー母数と session.total_column_count() は同じ「列数」を指す。

    _group_total() は prep 由来 (shown_count と同一ソース) だが、T1 の
    total_column_count() と乖離してはならない — 乖離すると「ブラウザは 4 ch と
    言い、ファイル情報 (source_info.n_channels) は別の数を言う」になる。
    反転前後の両方で突き合わせる。
    """
    vm, app_vm = _vm_for(write_mdf4_2d(tmp_path))
    key = app_vm.active_file_key or ""
    assert vm._group_total() == app_vm.session.total_column_count(key) == 4

    _invert_to_physical_signals(app_vm, key)
    vm.refresh()
    assert vm._group_total() == app_vm.session.total_column_count(key) == 4


def test_csv_group_falls_back_to_the_observed_columns(tmp_path: Path) -> None:
    """CSV/Derived は ColumnRecord を持たない — 観測した Signal がそのまま 1 列。

    _columns_of() が None (= 記録なし) を返し、それでも行/列/件数が正しく出る
    ことを直接 pin する。ここが壊れると CSV のチャンネルブラウザが空になる。
    T1 の column_names_of が未知グループに対し KeyError を投げても
    (display_name,) を返しても、どちらでも None に落ちなければならない。
    """
    path = tmp_path / "d.csv"
    path.write_text("t,speed,brake\n0.0,1.0,0.0\n1.0,2.0,1.0\n", encoding="utf-8")
    fmt = FormatDefinition(
        name="fmt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=2,
        has_header=True,
    )
    app_vm = AppViewModel()
    key = app_vm.request_load(path, fmt)
    app_vm.set_active_file(key)
    vm = ChannelBrowserVM(app_vm)

    assert vm._columns_of(key, "speed") is None  # 記録を持たないグループ
    assert [r[0] for r in vm.tree_groups()] == ["speed", "brake"]
    assert vm.column_names_for(f"{key}{KEY_SEPARATOR}speed") == [
        ("speed", "", f"{key}{KEY_SEPARATOR}speed")
    ]
    assert vm._group_total() == 2
    assert vm.shown_count() == 2


def test_tooltip_resolves_a_column_key_after_inversion(tmp_path: Path) -> None:
    """反転後は列 Signal が group_signals に居ない — tooltip は resolve 経由で当てる。

    tooltip_for は現状 production 消費者ゼロ (PC-19 が FU-22 B で退行済み) だが、
    テスト被覆つきで生きているメソッドなので、反転で無言の空文字に変わる罠を
    ここで閉じる。
    sabotage: _signal_by_key の resolve フォールバックを外すと空文字で RED。

    **このテストは resolve 経由を「推奨形」として祝福していない** — resolve は
    鋳造列を _resolved_by_key へ恒久登録する (C-g で LRU なし) ので、ホバーごとに
    列 Signal が滞留する。許容できるのは production 消費者がゼロだからで、
    PC-19 を復活させるときは鋳造しないメタデータ取得口が要る
    (_signal_by_key の docstring 参照)。
    """
    vm, app_vm = _vm_for(write_mdf4_2d(tmp_path))
    key = app_vm.active_file_key or ""
    _invert_to_physical_signals(app_vm, key)
    vm.refresh()

    tip = vm.tooltip_for(f"{key}{KEY_SEPARATOR}Mat[1]")
    assert "サンプル数: 4" in tip
