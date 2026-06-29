# R14 時間オフセット（増分C）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** プロット内でアクティブ波形を水平ドラッグして時間オフセット（Δt）をライブプレビューし、リリース時の適用ダイアログ（信号のみ／同一グループ／キャンセル）で確定すると、その信号を表示する全パネルがオフセット適用後の波形に再描画される（親 R14 の受け入れ基準を満たす）。

**Architecture:** オフセットの真の状態は `AppViewModel` の 2 dict（`signal_offsets` / `file_offsets`）が一元保持し、`GraphAreaVM` が `'offsets'` 通知を全タブ・全パネルにブロードキャストして各 `GraphPanelVM.set_offsets()` → `refresh()` を駆動する。`GraphPanelVM._signal_map()` がレンダ時に `Session.apply_offset`（純粋関数・元信号は不変）でオフセットを適用する。ジェスチャは `GraphPanelView` の widget レベル mouse ハンドラの **空き枠 `ZONE_PLOT`** に載せ、カーソル線 D&D（pyqtgraph scene レベル・優先）と衝突しないよう曲線ヒットテストで判別する。

**Tech Stack:** Python 3.12+, PySide6 6.11.x, pyqtgraph, numpy, pytest / pytest-qt（Layer A/B は offscreen, Layer C は `--realgui` で実 OS 入力）。

## Global Constraints

各タスクの要件はこのセクションを暗黙に含む。値は設計 spec（`docs/superpowers/specs/2026-06-29-gui-analysis-cursor-offset-design.md`）と CLAUDE.md から逐語転記:

- **MVVM**: `src/valisync/gui/viewmodels/` は PySide6/Qt/pyqtgraph を import しない。コアへのアクセスは `Session` 経由のみ。
- **判定優先順位（ドラッグ開始時）**: カーソル線（許容ピクセル内）＞ 曲線（最近傍・許容ピクセル内）。空白上のクリック/ドラッグはカーソル操作に使わない（設置は廃止）。
- **R14.6 ツールチップ**: ドラッグ中に Δt を 3 桁（有効数字約 3 桁）でツールチップ表示。
- **R14.3 適用対象の Session マッピング**: (a) その信号のみ → `signal_offset` を `signal_key` に、(b) 同一 Signal_Group → 同グループ各信号へ `file_offset`。グループキーは `signal_key.split("::", 1)[0]`、グループ信号取得は `Session.group_signals(key)`。
- **R14.7/8 中断**: Escape／ダイアログのキャンセル → プレビューを破棄し開始前へ復元、**offset dict は変更しない**。
- **R14.5 全パネル更新**: その信号を表示する全パネル（全タブ）が再描画される。
- **AppViewModel がオフセット状態（`signal_offsets` / `file_offsets` dict）を保持**。オフセットは**元の Session 信号に対し加算式（累積）**で適用する（`Session.apply_offset` は純粋関数で元信号を変更しない）。
- **コミット trailer（毎コミット必須）**:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k
  ```
- **品質ゲート（各コミット前）**: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` を全て通す。
- **GUI テストレイヤー**: Layer A（VM/ロジック・headless）と Layer B（実イベント経路・`QApplication.sendEvent` headless）は CI 必須。Layer C（realgui・`@pytest.mark.realgui`・`--realgui` opt-in）は CI 除外で**ユーザーが実行**する（本セッションは bg で実 OS カーソルを動かせないため realgui は実行しない）。②実質性（実経路でしか証明できないことをアサート）と ①証拠ゲート（merge 前に realgui 実行＋証拠）を守る。

### §12 オープン項目の確定値（本プランの決定・ユーザーは上書き可）

| 項目 | 確定値 | 根拠 |
|---|---|---|
| 曲線ヒットテスト許容ピクセル | `CURVE_HIT_TOL_PX = 8`（scene px） | 細い線も掴め、かつ誤爆しにくい中庸値 |
| カーソル線ヒット許容ピクセル（曲線判定をスキップする近接帯） | `CURSOR_LINE_HIT_PX = 10`（scene px） | 曲線許容より**大きく**しカーソル線優先を保証（§4） |
| アクティブ波形ハイライト表現 | ドラッグ開始時に当該 `PlotDataItem` のペン幅を `width=3` に増やし、リリース／キャンセルで元ペンに戻す（色は不変） | PR #19 のアクティブ軸（太枠）と同系の最小実装 |
| Δt 表示桁 | `f"{delta_t:+.3g} s"`（有効数字 3 桁・符号付き） | R14.6「3 桁」 |
| オフセット累積セマンティクス | 加算式（同信号への再適用は累積）。**グループ適用時は同グループの per-signal `signal_offsets`（キーが `f"{group_key}::"` で始まる全エントリ）を破棄**し、グループ一律オフセットに揃える（ユーザー決定） | グループ操作の意図＝個別調整のリセット |

---

## File Structure

| ファイル | 区分 | 責務 |
|---|---|---|
| `src/valisync/gui/viewmodels/app_viewmodel.py` | Modify | オフセット 2 dict ＋ `apply_offset(signal_key, delta_t, scope)`（加算・通知）＋ アンロード時パージ ＋ `inspect()` 拡張 |
| `src/valisync/gui/viewmodels/graph_panel_vm.py` | Modify | `_signal_offsets`/`_file_offsets` 保持＋`set_offsets()`、`_signal_map()` でレンダ時オフセット適用、`set_offsets` でキャッシュ無効化 |
| `src/valisync/gui/viewmodels/graph_area_vm.py` | Modify | `_on_app_change` に `'offsets'` 分岐（全パネルへ `set_offsets`+`refresh`）＋ `apply_offset` プロキシ |
| `src/valisync/gui/views/graph_panel_view.py` | Modify | `_curve_at` ヒットテスト＋`_item_vb` 対応表、`ZONE_PLOT` press/move/release ジェスチャ、プレビュー（`setData`）、Δt ツールチップ、ハイライト、Escape、適用ダイアログ（`apply_dialog_fn` 注入＋`_default_apply_dialog`）、`offset_apply_requested` Signal |
| `src/valisync/gui/views/graph_area_view.py` | Modify | `_wire_panel` で `offset_apply_requested` → `GraphAreaVM.apply_offset` を配線 |
| `tests/gui/_panel_factory.py` | Modify | `make_single_signal_panel()` を追加（曲線中央を通る線形信号 1 本・Task 4 ヒットテスト/Task 5 ドラッグ用） |
| `tests/gui/test_app_viewmodel_offsets.py` | Create | Task 1 Layer A |
| `tests/gui/test_graph_panel_vm_offsets.py` | Create | Task 2 Layer A |
| `tests/gui/test_graph_area_vm_offsets.py` | Create | Task 3 Layer A |
| `tests/gui/test_graph_panel_offset_hittest.py` | Create | Task 4 Layer B |
| `tests/gui/test_graph_panel_offset_drag.py` | Create | Task 5 Layer B |
| `tests/gui/test_graph_area_offset_wiring.py` | Create | Task 6 Layer B |
| `tests/realgui/test_offset_drag.py` | Create | Task 7 Layer C — 実 GraphAreaView ＋ 2パネルのクロス再描画（ユーザー実行） |

---

## Task 1: AppViewModel — オフセット状態・apply_offset・アンロード時パージ

**Files:**
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py:29-35`（`__init__`）, `:57-72`（`unload_file`）, `:129-139`（`inspect`）
- Test: `tests/gui/test_app_viewmodel_offsets.py`（Create）

**Interfaces:**
- Produces:
  - `AppViewModel.signal_offsets -> dict[str, float]`（コピーを返す read-only property）
  - `AppViewModel.file_offsets -> dict[str, float]`（同上）
  - `AppViewModel.apply_offset(self, signal_key: str, delta_t: float, scope: str) -> None`（`scope in {"signal","group"}`、加算、`_notify("offsets")`）
  - `inspect()` の戻り dict に `"signal_offsets"` / `"file_offsets"` を追加

### gui-test-plan 分析（Task 1）
- **変更種別**: 純ロジック（dict 更新・通知）。Qt 入力経路なし。
- **Layer A（必須）**: scope 分岐・加算累積・グループキー抽出・通知発火・アンロード時パージを VM 単体で検証。
- **Layer B/C**: 不要（実イベント経路・描画に関与しない）。
- **②実質性**: 「assert 何もしない」を避け、(1) `signal`/`group` で**異なる dict**が更新される、(2) 同キー再適用が**累積**する、(3) `unload_file` 後に当該グループのオフセットが**消える**、(4) `'offsets'` 通知が**実際に飛ぶ**ことをアサートする。これらは VM の公開契約そのもの。
- **honest layering**: dict 操作はコア/Qt を介さないため Layer A で完結。realgui に持ち上げる必要なし。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_app_viewmodel_offsets.py`（新規）:

```python
"""Layer A: AppViewModel のオフセット状態 (R14)。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.viewmodels.app_viewmodel import AppViewModel


def _app_with_csv() -> tuple[AppViewModel, str]:
    """1 グループ (csv_1) を読み込んだ AppViewModel と、その名前空間付き信号キーを返す。"""
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1"] + [f"{i * 0.01:.3f},{i % 10}.0" for i in range(20)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    app = AppViewModel()
    key = app.request_load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    signal_key = sorted(s.name for s in app.signals())[0]
    return app, signal_key


def test_apply_offset_signal_scope_accumulates() -> None:
    app = AppViewModel()
    app.apply_offset("csv_1::speed", 0.10, "signal")
    app.apply_offset("csv_1::speed", 0.05, "signal")
    assert app.signal_offsets == {"csv_1::speed": 0.15}
    assert app.file_offsets == {}


def test_apply_offset_group_scope_keys_on_group_prefix() -> None:
    app = AppViewModel()
    app.apply_offset("csv_1::speed", 0.20, "group")
    assert app.file_offsets == {"csv_1": 0.20}
    assert app.signal_offsets == {}


def test_group_apply_resets_sibling_signal_offsets() -> None:
    app = AppViewModel()
    # A sibling in the same group already has a per-signal offset.
    app.apply_offset("csv_1::speed", 0.3, "signal")
    # Applying a group offset must discard sibling per-signal offsets (user
    # decision): the group lands on one uniform offset.
    app.apply_offset("csv_1::rpm", 0.2, "group")
    assert app.file_offsets == {"csv_1": 0.2}
    assert app.signal_offsets == {}


def test_apply_offset_notifies_offsets() -> None:
    app = AppViewModel()
    seen: list[str] = []
    app.subscribe(seen.append)
    app.apply_offset("csv_1::speed", 0.1, "signal")
    assert "offsets" in seen


def test_offset_properties_return_copies() -> None:
    app = AppViewModel()
    app.apply_offset("csv_1::speed", 0.1, "signal")
    snapshot = app.signal_offsets
    snapshot["csv_1::speed"] = 999.0
    assert app.signal_offsets == {"csv_1::speed": 0.1}


def test_unload_purges_offsets_for_group() -> None:
    app, signal_key = _app_with_csv()
    group_key = signal_key.split("::", 1)[0]
    app.apply_offset(signal_key, 0.1, "signal")
    app.apply_offset(signal_key, 0.2, "group")
    assert app.signal_offsets and app.file_offsets
    app.unload_file(group_key)
    assert app.signal_offsets == {}
    assert app.file_offsets == {}


def test_inspect_includes_offsets() -> None:
    app = AppViewModel()
    app.apply_offset("csv_1::speed", 0.1, "signal")
    snap = app.inspect()
    assert snap["signal_offsets"] == {"csv_1::speed": 0.1}
    assert snap["file_offsets"] == {}
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_app_viewmodel_offsets.py -v`
Expected: FAIL（`AttributeError: 'AppViewModel' object has no attribute 'apply_offset'` 等）

- [ ] **Step 3: 最小実装**

`app_viewmodel.py` の `__init__`（末尾、`self._active_file_key` の後）に追加:

```python
        # Time-offset state (R14) — transient, never persisted (Phase 3).
        # signal_offsets: keyed by namespaced signal name (e.g. "csv_1::speed").
        # file_offsets: keyed by group key (e.g. "csv_1"). Both are additive
        # deltas applied to the ORIGINAL session signal at render time.
        self._signal_offsets: dict[str, float] = {}
        self._file_offsets: dict[str, float] = {}
```

`session` property の後に property を追加:

```python
    @property
    def signal_offsets(self) -> dict[str, float]:
        """Per-signal time offsets (copy), keyed by namespaced signal name."""
        return dict(self._signal_offsets)

    @property
    def file_offsets(self) -> dict[str, float]:
        """Per-group time offsets (copy), keyed by group key."""
        return dict(self._file_offsets)

    def apply_offset(self, signal_key: str, delta_t: float, scope: str) -> None:
        """Accumulate a time offset for *signal_key* and notify ('offsets').

        ``scope="signal"`` adds ``delta_t`` to the per-signal offset; ``scope="group"``
        adds it to the per-group (file) offset keyed by the group prefix. Offsets are
        additive on the original session signal (R14.3); the render path applies them
        via Session.apply_offset (a pure function).
        """
        if scope == "signal":
            self._signal_offsets[signal_key] = (
                self._signal_offsets.get(signal_key, 0.0) + delta_t
            )
        elif scope == "group":
            group_key = signal_key.split("::", 1)[0]
            self._file_offsets[group_key] = (
                self._file_offsets.get(group_key, 0.0) + delta_t
            )
            # Group apply discards sibling per-signal adjustments so the whole
            # group lands on one uniform offset (user decision): drop every
            # signal_offset under this group's "<group>::" prefix.
            prefix = f"{group_key}::"
            for sk in [k for k in self._signal_offsets if k.startswith(prefix)]:
                del self._signal_offsets[sk]
        else:
            raise ValueError(f"scope must be 'signal' or 'group', got {scope!r}")
        self._notify("offsets")
```

`unload_file` の `self._notify("unloaded")` の直前にパージを追加:

```python
        # Drop any offsets tied to the removed group so stale dicts don't linger.
        self._file_offsets.pop(key, None)
        prefix = f"{key}::"
        for sk in [k for k in self._signal_offsets if k.startswith(prefix)]:
            del self._signal_offsets[sk]
```

`inspect()` の戻り dict に追加:

```python
            "signal_offsets": dict(self._signal_offsets),
            "file_offsets": dict(self._file_offsets),
```

- [ ] **Step 4: テスト合格を確認**

Run: `uv run pytest tests/gui/test_app_viewmodel_offsets.py -v`
Expected: PASS（7 件）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/gui/test_app_viewmodel_offsets.py -q
git add src/valisync/gui/viewmodels/app_viewmodel.py tests/gui/test_app_viewmodel_offsets.py
git commit
```
コミットメッセージ（trailer 必須）:
```
feat(gui): R14 AppViewModel にオフセット状態と apply_offset を追加

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k
```

---

## Task 2: GraphPanelVM — オフセット消費（set_offsets ＋ レンダ時適用）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py:105-128`（`__init__`）, `:776-778`（`_signal_map`）
- Test: `tests/gui/test_graph_panel_vm_offsets.py`（Create）

**Interfaces:**
- Consumes: `Session.apply_offset(signal, file_offset, signal_offset) -> Signal`（純粋関数）
- Produces:
  - `GraphPanelVM.set_offsets(self, signal_offsets: dict[str, float], file_offsets: dict[str, float]) -> None`（コピー保持＋キャッシュ無効化）
  - `_signal_map()` がオフセット適用後の Signal を返す

### gui-test-plan 分析（Task 2）
- **変更種別**: 純ロジック（レンダパイプラインのデータ変換）。Qt なし。
- **Layer A（必須）**: `set_offsets` 後に `render_data()` の timestamps が Δt だけシフトすること、グループスコープが同グループ全信号をシフトすること、ゼロオフセットが恒等（同一配列）であること、`set_offsets` がキャッシュを無効化し**陳腐な結果を返さない**ことを検証。
- **Layer B/C**: 不要（描画は View 側だが、VM 出力の数値が真実源。View 再描画は Task 5/6/7 でカバー）。
- **②実質性**: 「offset を入れたら render_data の x が変わる」「キャッシュ無効化が効く（同一 x_range でも新オフセットが反映）」という**観測可能な数値変化**をアサート。VM だけで証明可能かつ十分。
- **honest layering**: キャッシュ無効化バグは plain な再 render では隠れうる（[[feedback_gui_verify_real_input]] と同型の false-green 懸念）ので、**オフセット変更前に一度 render_data を呼んでキャッシュを温め**てから set_offsets→再 render で差分を見る（fast-path を踏ませてから無効化を強制）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_panel_vm_offsets.py`（新規）:

```python
"""Layer A: GraphPanelVM のオフセット適用 (R14)。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from valisync.core.models import Delimiter, FormatDefinition
from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM


def _vm_two_signals() -> tuple[GraphPanelVM, list[str], str]:
    """2 信号 (同一グループ csv_1) を持つ VM・信号キー列・グループキーを返す。"""
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1,s2"] + [f"{i * 0.01:.3f},{i}.0,{i * 2}.0" for i in range(30)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    session = Session()
    session.load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=2,
            has_header=True,
        ),
    )
    keys = sorted(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(keys[0], 0)
    vm.add_signal_to_axis(keys[1], 0)
    group_key = keys[0].split("::", 1)[0]
    return vm, keys, group_key


def _curve_x(vm: GraphPanelVM, key: str) -> np.ndarray:
    return next(c.timestamps for c in vm.render_data() if c.name == key)


def test_signal_offset_shifts_only_that_signal() -> None:
    vm, keys, _ = _vm_two_signals()
    base0 = _curve_x(vm, keys[0]).copy()
    base1 = _curve_x(vm, keys[1]).copy()
    vm.set_offsets({keys[0]: 0.5}, {})
    np.testing.assert_allclose(_curve_x(vm, keys[0]), base0 + 0.5)
    np.testing.assert_allclose(_curve_x(vm, keys[1]), base1)  # unchanged


def test_group_offset_shifts_all_signals_in_group() -> None:
    vm, keys, group_key = _vm_two_signals()
    base0 = _curve_x(vm, keys[0]).copy()
    base1 = _curve_x(vm, keys[1]).copy()
    vm.set_offsets({}, {group_key: 0.3})
    np.testing.assert_allclose(_curve_x(vm, keys[0]), base0 + 0.3)
    np.testing.assert_allclose(_curve_x(vm, keys[1]), base1 + 0.3)


def test_zero_offset_is_identity() -> None:
    vm, keys, _ = _vm_two_signals()
    base0 = _curve_x(vm, keys[0]).copy()
    vm.set_offsets({}, {})
    np.testing.assert_allclose(_curve_x(vm, keys[0]), base0)


def test_set_offsets_invalidates_cache() -> None:
    vm, keys, _ = _vm_two_signals()
    # Warm the cache (forces fast-path on the next identical-key render).
    base0 = _curve_x(vm, keys[0]).copy()
    vm.set_offsets({keys[0]: 1.0}, {})
    shifted = _curve_x(vm, keys[0])
    # If set_offsets did not invalidate, the stale cached (un-shifted) curve
    # would be returned and this would fail.
    np.testing.assert_allclose(shifted, base0 + 1.0)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm_offsets.py -v`
Expected: FAIL（`AttributeError: ... 'set_offsets'`）

- [ ] **Step 3: 最小実装**

`graph_panel_vm.py` の `__init__`（`visible_stat_cols` の後）に追加:

```python
        # Time offsets (R14) — applied at render time to the ORIGINAL session
        # signal. signal_offsets keyed by namespaced name, file_offsets by group
        # key. Pushed in by GraphAreaVM on 'offsets' events; the authoritative
        # source is AppViewModel.
        self._signal_offsets: dict[str, float] = {}
        self._file_offsets: dict[str, float] = {}
```

`set_offsets` を追加（`refresh` の近く、`_invalidate_cache` 利用が分かる位置で可。ここでは `refresh()` の直後に置く）:

```python
    def set_offsets(
        self, signal_offsets: dict[str, float], file_offsets: dict[str, float]
    ) -> None:
        """Store the current time offsets and invalidate the render cache (R14.5).

        Called by GraphAreaVM on every 'offsets' broadcast. The next render_data()
        applies them via Session.apply_offset. Cache invalidation (not a cache-key
        change) is what makes a new offset bust the stale curve — render_data's key
        intentionally omits offsets because they only change through this method.
        """
        self._signal_offsets = dict(signal_offsets)
        self._file_offsets = dict(file_offsets)
        self._invalidate_cache()
```

`_signal_map()` を差し替え:

```python
    def _signal_map(self) -> dict[str, Signal]:
        """Return {signal.name: signal} with stored time offsets applied (R14).

        Offsets are applied to the ORIGINAL session signal via the pure
        Session.apply_offset; a zero total returns the original object unchanged.
        Group key is the prefix before '::' (same convention as Session).
        """
        result: dict[str, Signal] = {}
        for sig in self._session.signals():
            group_key = sig.name.split("::", 1)[0]
            file_off = self._file_offsets.get(group_key, 0.0)
            sig_off = self._signal_offsets.get(sig.name, 0.0)
            if file_off or sig_off:
                result[sig.name] = self._session.apply_offset(
                    sig, file_offset=file_off, signal_offset=sig_off
                )
            else:
                result[sig.name] = sig
        return result
```

- [ ] **Step 4: テスト合格を確認**

Run: `uv run pytest tests/gui/test_graph_panel_vm_offsets.py -v`
Expected: PASS（4 件）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/gui/test_graph_panel_vm_offsets.py -q
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_panel_vm_offsets.py
git commit
```
```
feat(gui): R14 GraphPanelVM がレンダ時にオフセットを適用 (set_offsets)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k
```

---

## Task 3: GraphAreaVM — 'offsets' ブロードキャスト ＋ apply_offset プロキシ

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_area_vm.py:56-66`（`_on_app_change`）, アクセッサ近傍に proxy 追加
- Test: `tests/gui/test_graph_area_vm_offsets.py`（Create）

**Interfaces:**
- Consumes: `AppViewModel.apply_offset`, `AppViewModel.signal_offsets`, `AppViewModel.file_offsets`（Task 1）, `GraphPanelVM.set_offsets`（Task 2）
- Produces:
  - `GraphAreaVM._on_app_change` の `'offsets'` 分岐: 全パネルへ `set_offsets(app.signal_offsets, app.file_offsets)` → `refresh()`
  - `GraphAreaVM.apply_offset(self, signal_key: str, delta_t: float, scope: str) -> None`（`self._app_vm.apply_offset` への委譲プロキシ — View 層の配線先）

### gui-test-plan 分析（Task 3）
- **変更種別**: 純ロジック（app イベント → パネル調停・委譲）。Qt なし。
- **Layer A（必須）**: app が `'offsets'` を通知すると**全タブ・全パネル**がオフセット適用済みで再描画されること、`apply_offset` プロキシが `app_vm` の dict を更新すること（プロキシ→app→ブロードキャストの一巡）を検証。
- **Layer B/C**: 不要（実描画は Task 5-7）。
- **②実質性**: パネルを 2 枚（別タブにも 1 枚）用意し、`apply_offset` 呼び出し後に**各パネルの render_data の x がシフト**していることをアサート（`_for_each_panel` が全タブを巡るブロードキャスト先選定の正しさ＝R14.5 を直接証明）。空アサートや「通知が来た」だけにしない。
- **honest layering**: ブロードキャスト先選定（全タブ）はコアロジックで Layer A 完結。propagate_cursor（タブ内のみ）を誤用していない点もここで担保。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_area_vm_offsets.py`（新規）:

```python
"""Layer A: GraphAreaVM のオフセットブロードキャスト (R14.5)。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM


def _area_with_signal() -> tuple[GraphAreaVM, AppViewModel, str]:
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1"] + [f"{i * 0.01:.3f},{i}.0" for i in range(30)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    app = AppViewModel()
    app.request_load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    signal_key = sorted(s.name for s in app.signals())[0]
    area = GraphAreaVM(app)
    return area, app, signal_key


def _plot_signal_on(panel, key: str) -> None:
    panel.add_signal_to_axis(key, 0)


def _curve_x(panel, key: str) -> np.ndarray:
    return next(c.timestamps for c in panel.render_data() if c.name == key)


def test_offsets_event_rerenders_all_panels_across_tabs() -> None:
    area, app, signal_key = _area_with_signal()
    area.add_tab()  # second tab, second panel
    p0 = area.panels(0)[0]
    p1 = area.panels(1)[0]
    _plot_signal_on(p0, signal_key)
    _plot_signal_on(p1, signal_key)
    base0 = _curve_x(p0, signal_key).copy()
    base1 = _curve_x(p1, signal_key).copy()

    app.apply_offset(signal_key, 0.4, "signal")

    np.testing.assert_allclose(_curve_x(p0, signal_key), base0 + 0.4)
    np.testing.assert_allclose(_curve_x(p1, signal_key), base1 + 0.4)


def test_apply_offset_proxy_updates_app_state() -> None:
    area, app, signal_key = _area_with_signal()
    area.apply_offset(signal_key, 0.25, "signal")
    assert app.signal_offsets == {signal_key: 0.25}
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_area_vm_offsets.py -v`
Expected: FAIL（`'offsets'` 未処理で x が不変 / `apply_offset` 不在）

- [ ] **Step 3: 最小実装**

`graph_area_vm.py` の `_on_app_change` に分岐を追加:

```python
        if change == "loaded":
            self._for_each_panel(lambda p: p.refresh())
        elif change == "unloaded":
            self._for_each_panel(lambda p: p.prune_missing_signals())
        elif change == "offsets":
            # R14.5: push the latest offsets to EVERY panel (all tabs) and
            # re-render. _for_each_panel spans all tabs (propagate_cursor is
            # tab-local and must NOT be reused here).
            sig_off = self._app_vm.signal_offsets
            file_off = self._app_vm.file_offsets

            def _apply(p: GraphPanelVM) -> None:
                p.set_offsets(sig_off, file_off)
                p.refresh()

            self._for_each_panel(_apply)
```

アクセッサ群の近く（`tabs()` の前など）にプロキシを追加:

```python
    def apply_offset(self, signal_key: str, delta_t: float, scope: str) -> None:
        """Forward an offset request to the AppViewModel (View-layer wiring target).

        The resulting 'offsets' notification is handled by _on_app_change, which
        broadcasts to all panels. Keeps GraphPanelView decoupled from AppViewModel.
        """
        self._app_vm.apply_offset(signal_key, delta_t, scope)
```

- [ ] **Step 4: テスト合格を確認**

Run: `uv run pytest tests/gui/test_graph_area_vm_offsets.py -v`
Expected: PASS（2 件）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/gui/test_graph_area_vm_offsets.py -q
git add src/valisync/gui/viewmodels/graph_area_vm.py tests/gui/test_graph_area_vm_offsets.py
git commit
```
```
feat(gui): R14 GraphAreaVM の offsets ブロードキャストと apply_offset プロキシ

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k
```

---

## Task 4: GraphPanelView — 曲線ヒットテスト `_curve_at` ＋ `_item_vb` 対応表

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py:58-65`（定数）, `:599-631`（`__init__` 状態）, `:716-743`（`refresh` の追加/削除で `_item_vb` 同期）, `:1316-1325`（`_data_value` の隣に `_curve_at`）
- Modify: `tests/gui/_panel_factory.py`（`make_single_signal_panel` 追加）
- Test: `tests/gui/test_graph_panel_offset_hittest.py`（Create）

**Interfaces:**
- Consumes: `self._items: dict[str, pg.PlotDataItem]`, `self._view_boxes`, `pg.ViewBox.mapSceneToView/mapViewToScene`, カーソル線 `_cursor_lines()`
- Produces:
  - `GraphPanelView._item_vb: dict[str, pg.ViewBox]`（key→そのカーブが属する ViewBox）
  - `GraphPanelView._curve_at(self, pos: QPointF) -> str | None`（最近傍カーブのキー。可視カーソル線の近接帯内、または許容超なら None）
  - 定数 `CURVE_HIT_TOL_PX = 8`, `CURSOR_LINE_HIT_PX = 10`
  - `tests/gui/_panel_factory.make_single_signal_panel() -> GraphPanelView`

### gui-test-plan 分析（Task 4）
- **変更種別**: ヒットテストの座標ロジック（pyqtgraph scene 変換に依存）。実イベント経路ではないが**実ウィジェット/実 ViewBox 幾何**が必要。
- **Layer A**: 不可（`mapSceneToView` は実 ViewBox 幾何を要し、offscreen でも `show()`+expose が要る）。
- **Layer B（必須）**: 実描画済みパネル（offscreen, `qtbot.addWidget`+`show`+`waitExposed`）で、(1) カーブ上の点 → そのキー、(2) カーブから遠い点 → None、(3) 可視カーソル線近傍の点 → None（優先順位ガード）を検証。
- **Layer C**: ここでは不要（実 OS 入力経路は Task 7 のドラッグで検証）。座標変換の正しさは Layer B で十分。
- **②実質性**: 「曲線上＝キー / 空白＝None / カーソル線近傍＝None」という分類は実 scene 幾何でしか出ない値。VM では再現不能。
- **honest layering**: 線形信号がプロット中央を通る固定ジオメトリ（`make_single_signal_panel`）を使い、scene 矩形から点を採る（マジック比ではなく実幾何から座標を導出）。

- [ ] **Step 1: 失敗するテストを書く**

まず `tests/gui/_panel_factory.py` に factory を追加（実装ステップで本体を書く前提だが、テストが import するため先に追記してよい。ここでは Step 3 で追記する）。

`tests/gui/test_graph_panel_offset_hittest.py`（新規）:

```python
"""Layer B: 曲線ヒットテスト _curve_at (R14)。実 ViewBox 幾何で検証。"""

from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.gui._panel_factory import make_single_signal_panel


def _shown(qtbot: QtBot):
    view = make_single_signal_panel()
    qtbot.addWidget(view)
    view.resize(700, 500)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    return view


def _plot_center_widget_pos(view) -> QPointF:
    return view._plot_rect_in_widget().center()


def test_curve_at_hits_curve_center(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    key = sorted(view._items.keys())[0]
    hit = view._curve_at(_plot_center_widget_pos(view))
    assert hit == key


def test_curve_at_misses_empty_corner(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    rect = view._plot_rect_in_widget()
    # Top-left corner: the linear curve is at its minimum (bottom) here → far away.
    corner = QPointF(rect.left() + 3.0, rect.top() + 3.0)
    assert view._curve_at(corner) is None


def test_curve_at_yields_to_visible_cursor_line(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    # Cursor line A appears at the visible-width 50% — i.e. the plot centre x,
    # which is exactly where the curve centre is. The guard must return None so
    # the InfiniteLine D&D wins (priority: cursor line > curve, §4).
    view.vm.toggle_main_cursor(True)
    for _ in range(3):
        QApplication.processEvents()
    assert view.cursor_line_visible()
    assert view._curve_at(_plot_center_widget_pos(view)) is None
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_offset_hittest.py -v`
Expected: FAIL（`ImportError: make_single_signal_panel` / `AttributeError: _curve_at`）

- [ ] **Step 3: 最小実装**

`tests/gui/_panel_factory.py` の末尾に追加:

```python
def make_single_signal_panel() -> GraphPanelView:
    """Build a GraphPanelView with ONE linear signal on a single axis.

    The signal is ``v = t`` over ``t in [0, 1)`` so the curve passes through the
    plot's geometric centre (x=0.5 → y=0.5 = mid of the auto-fit y-range). That
    makes a click at the plot-rect centre land on the curve — ideal for hit-test
    and offset-drag tests (Layer B/C). Runs on the offscreen platform.
    """
    d = Path(tempfile.mkdtemp())
    csv = d / "lin.csv"
    rows = ["t,lin"] + [f"{i / 50.0:.4f},{i / 50.0:.4f}" for i in range(50)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")

    session = Session()
    session.load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    keys = sorted(s.name for s in session.signals())
    vm = GraphPanelVM(session)
    vm.add_signal_to_axis(keys[0], 0)
    return GraphPanelView(vm)
```

`graph_panel_view.py` の定数群（`ZONE_NONE` の後あたり）に追加:

```python
# R14 time-offset gesture tolerances (scene pixels). Cursor-line proximity is
# wider than the curve tolerance so the cursor line wins on overlap (§4).
CURVE_HIT_TOL_PX = 8.0
CURSOR_LINE_HIT_PX = 10.0
```

`__init__` の `self._items` の直後に `_item_vb` を追加:

```python
        # Which ViewBox each curve currently lives in (kept in sync by refresh).
        # Used by the R14 curve hit-test to map candidate data points to scene px.
        self._item_vb: dict[str, Any] = {}
```

`refresh()` のカーブ削除ブロック（key を pop する箇所）で対応表も掃除:

```python
        for key in list(self._items):
            if key not in desired:
                item = self._items.pop(key)
                self._item_vb.pop(key, None)
                # Find which ViewBox it was in and remove it
                for vb in self._view_boxes:
                    if item in vb.addedItems:
                        vb.removeItem(item)
                        break
```

`refresh()` のカーブ追加/更新ブロックで対応表を記録（`target_vb` 確定後）:

```python
            if item not in target_vb.addedItems:
                # Remove from previous ViewBox if any
                for vb in self._view_boxes:
                    if vb != target_vb and item in vb.addedItems:
                        vb.removeItem(item)
                target_vb.addItem(item)
            self._item_vb[curve.name] = target_vb
```

`_data_value` の直後に `_curve_at` を追加:

```python
    def _curve_at(self, pos: QPointF) -> str | None:
        """Return the signal key of the nearest curve within CURVE_HIT_TOL_PX of *pos*.

        Returns None when *pos* is within CURSOR_LINE_HIT_PX of a visible cursor
        line (priority: cursor line > curve, §4) or when no curve is close enough.
        Distance is measured in scene pixels via each item's own ViewBox, so the
        check is correct under multi-axis layouts and any LOD level.
        """
        if not self._view_boxes or not self._items:
            return None
        try:
            scene_pos = self.plot_widget.mapToScene(pos.toPoint())
        except Exception:
            return None

        # Cursor-line guard: yield to a nearby visible cursor line.
        vb0 = self._view_boxes[0]
        for line in self._cursor_lines():
            try:
                if not line.isVisible():
                    continue
                line_scene_x = vb0.mapViewToScene(QPointF(float(line.value()), 0.0)).x()
            except Exception:
                continue
            if abs(scene_pos.x() - line_scene_x) <= CURSOR_LINE_HIT_PX:
                return None

        best_key: str | None = None
        best_dist = CURVE_HIT_TOL_PX
        for key, item in self._items.items():
            vb = self._item_vb.get(key)
            if vb is None:
                continue
            xs, ys = item.getData()
            if xs is None or len(xs) == 0:
                continue
            data_x = vb.mapSceneToView(scene_pos).x()
            idx = int(np.searchsorted(xs, data_x))
            for cand in (idx - 1, idx):
                if cand < 0 or cand >= len(xs):
                    continue
                cand_scene = vb.mapViewToScene(
                    QPointF(float(xs[cand]), float(ys[cand]))
                )
                dx = scene_pos.x() - cand_scene.x()
                dy = scene_pos.y() - cand_scene.y()
                dist = (dx * dx + dy * dy) ** 0.5
                if dist <= best_dist:
                    best_dist = dist
                    best_key = key
        return best_key
```

`graph_panel_view.py` 冒頭に numpy import を追加（未 import の場合）:

```python
import numpy as np
```
（`from typing import Any` は既存。`np` の有無を確認し、無ければ `import pyqtgraph as pg` の前後に追加。）

- [ ] **Step 4: テスト合格を確認**

Run: `uv run pytest tests/gui/test_graph_panel_offset_hittest.py -v`
Expected: PASS（3 件）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/gui/test_graph_panel_offset_hittest.py -q
git add src/valisync/gui/views/graph_panel_view.py tests/gui/_panel_factory.py tests/gui/test_graph_panel_offset_hittest.py
git commit
```
```
feat(gui): R14 曲線ヒットテスト _curve_at とカーソル線優先ガード

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k
```

---

## Task 5: GraphPanelView — オフセットドラッグジェスチャ（プレビュー・ツールチップ・Escape・適用ダイアログ）

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py:594-631`（Signal＋`__init__` 引数/状態/フォーカス）, `:1329-1355`（press/move/release）, `keyPressEvent` 追加, `_default_apply_dialog` 追加
- Test: `tests/gui/test_graph_panel_offset_drag.py`（Create）

**Interfaces:**
- Consumes: `_curve_at`（Task 4）, `_data_value`, `_item_vb`, `_items`
- Produces:
  - `GraphPanelView.offset_apply_requested = Signal(str, float, str)`（signal_key, delta_t, scope）
  - `GraphPanelView.__init__(self, vm, parent=None, apply_dialog_fn: Callable[[str, float], str | None] | None = None)`
  - 状態: `_offset_drag_key: str | None`, `_offset_drag_start_x: float | None`, `_offset_orig_xy: tuple[Any, Any] | None`, `_offset_orig_pen: Any`, `_offset_last_delta: float`
  - `_default_apply_dialog(self, signal_key: str, delta_t: float) -> str | None`（実 QDialog、`'signal'`/`'group'`/None）
  - `keyPressEvent`（Escape でドラッグ取消）

### gui-test-plan 分析（Task 5）
- **変更種別**: GUI 入力経路機能（widget レベル mouse press/move/release＋key＋modal ダイアログ）。最重要かつ realgui で最も壊れやすい（設計 §10）。
- **Layer A**: 不可（イベントハンドラ・QToolTip・ペン操作は VM では再現不能）。
- **Layer B（必須）**: offscreen＋`QApplication.sendEvent` で実イベント経路を踏む。modal `exec()` を避けるため `apply_dialog_fn` を注入（`dir_chooser` 注入パターンの踏襲）。検証: (1) 曲線上 press → `_offset_drag_key` セット＋ペン幅増、(2) move → 当該カーブの `curve_xy` x が Δt シフト、(3) release＋fn→'signal' → `offset_apply_requested(key, Δt, 'signal')` emit、(4) fn→None（キャンセル） → 元 xy＋元ペンに復元・emit なし、(5) Escape → 復元＋状態クリア・emit なし、(6) ドラッグ中に当該信号が `_items` から消えたら取消。
- **Layer C**: 実 OS 入力＋**実 modal ダイアログ**は Task 7。Layer B は注入でダイアログ本体の exec を回避する（honest: 実 modal の OS 経路は Layer B では証明不可と明記）。
- **②実質性**: `sendEvent` で実ハンドラを通し、`curve_xy` の数値シフト・emit 引数・復元を観測。直叩きではなく実イベント経路（[[feedback_gui_verify_real_input]]）。
- **honest layering**: `apply_dialog_fn` 注入は「ダイアログの選択結果が正しく分岐配線される」ことの証明に限定し、**実 modal の表示・Enter 確定・OS 経路は Layer C 必須**と test docstring に明記。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_panel_offset_drag.py`（新規）:

```python
"""Layer B: オフセットドラッグジェスチャ (R14)。実イベント経路 (sendEvent)。"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from tests.gui._panel_factory import make_single_signal_panel
from valisync.gui.views.graph_panel_view import GraphPanelView


def _shown(qtbot: QtBot, apply_dialog_fn=None) -> GraphPanelView:
    base = make_single_signal_panel()
    # Rebuild with the injected dialog fn (factory builds the default panel).
    view = GraphPanelView(base.vm, apply_dialog_fn=apply_dialog_fn)
    qtbot.addWidget(view)
    view.resize(700, 500)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    qtbot.waitUntil(
        lambda: view._view_boxes[0].sceneBoundingRect().height() > 100, timeout=3000
    )
    return view


def _center(view) -> QPointF:
    return view._plot_rect_in_widget().center()


def _send(view, etype, local: QPointF) -> None:
    glob = view.mapToGlobal(local.toPoint())
    ev = QMouseEvent(
        etype,
        local,
        QPointF(glob),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view, ev)


def _press_drag(view, dx_px: float):
    start = _center(view)
    target = QPointF(start.x() + dx_px, start.y())
    _send(view, QEvent.Type.MouseButtonPress, start)
    _send(view, QEvent.Type.MouseMove, target)
    return start, target


def test_press_on_curve_activates_offset_drag(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    _send(view, QEvent.Type.MouseButtonPress, _center(view))
    assert view._offset_drag_key is not None


def test_drag_previews_horizontal_shift(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    key = sorted(view._items.keys())[0]
    x_before = np.asarray(view.curve_xy(key)[0]).copy()
    _press_drag(view, dx_px=120.0)
    x_after = np.asarray(view.curve_xy(key)[0])
    # Rightward drag → positive Δt → every x increased by the same amount.
    delta = x_after - x_before
    assert float(delta.min()) > 0.0
    np.testing.assert_allclose(delta, delta[0])


def test_release_signal_scope_emits_request(qtbot: QtBot) -> None:
    captured: list[tuple] = []
    view = _shown(qtbot, apply_dialog_fn=lambda key, dt: "signal")
    view.offset_apply_requested.connect(
        lambda k, dt, sc: captured.append((k, dt, sc))
    )
    key = sorted(view._items.keys())[0]
    _start, target = _press_drag(view, dx_px=120.0)
    _send(view, QEvent.Type.MouseButtonRelease, target)
    for _ in range(3):  # let the deferred (singleShot) dialog resolve
        QApplication.processEvents()
    assert len(captured) == 1
    k, dt, sc = captured[0]
    assert k == key and sc == "signal" and dt > 0.0
    assert view._offset_drag_key is None


def test_cancel_via_dialog_restores_and_no_emit(qtbot: QtBot) -> None:
    captured: list[tuple] = []
    view = _shown(qtbot, apply_dialog_fn=lambda key, dt: None)  # cancel
    view.offset_apply_requested.connect(
        lambda k, dt, sc: captured.append((k, dt, sc))
    )
    key = sorted(view._items.keys())[0]
    x_before = np.asarray(view.curve_xy(key)[0]).copy()
    _start, target = _press_drag(view, dx_px=120.0)
    _send(view, QEvent.Type.MouseButtonRelease, target)
    for _ in range(3):
        QApplication.processEvents()
    assert captured == []
    np.testing.assert_allclose(np.asarray(view.curve_xy(key)[0]), x_before)
    assert view._offset_drag_key is None


def test_escape_cancels_drag_and_restores(qtbot: QtBot) -> None:
    view = _shown(qtbot)
    key = sorted(view._items.keys())[0]
    x_before = np.asarray(view.curve_xy(key)[0]).copy()
    _press_drag(view, dx_px=120.0)
    esc = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(view, esc)
    np.testing.assert_allclose(np.asarray(view.curve_xy(key)[0]), x_before)
    assert view._offset_drag_key is None
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_panel_offset_drag.py -v`
Expected: FAIL（`GraphPanelView.__init__` が `apply_dialog_fn` を受けない / `_offset_drag_key` 不在）

- [ ] **Step 3: 最小実装**

`graph_panel_view.py` 冒頭 import に追加（`Callable`）:

```python
from collections.abc import Callable
```
`QToolTip` を `PySide6.QtWidgets` import に追加。`QKeyEvent` を `PySide6.QtGui` import に追加。

クラス Signal 定義に追加（`remove_panel_requested` の後）:

```python
    # Emitted on offset-drag release when the user confirms a scope in the apply
    # dialog. The GraphAreaView wires this to GraphAreaVM.apply_offset (R14).
    offset_apply_requested = Signal(str, float, str)
```

`__init__` シグネチャを変更し、状態を追加:

```python
    def __init__(
        self,
        vm: GraphPanelVM,
        parent: QWidget | None = None,
        apply_dialog_fn: Callable[[str, float], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.vm = vm
        self._apply_dialog_fn = apply_dialog_fn
        self._items: dict[str, pg.PlotDataItem] = {}
        self._item_vb: dict[str, Any] = {}
```
（既存の `self._items` 行は上に統合。`_item_vb` は Task 4 で既に追加済みなら重複させない。）

`__init__` の状態ブロック（`_suppress_cursor_signal` の近く）に追加:

```python
        # R14 offset-drag transient state (None when no drag is active).
        self._offset_drag_key: str | None = None
        self._offset_drag_start_x: float | None = None
        self._offset_orig_xy: tuple[Any, Any] | None = None
        self._offset_orig_pen: Any = None
        self._offset_last_delta: float = 0.0
```

`__init__` 末尾（plot 構築後）にフォーカス方針を設定（Escape 受信のため）:

```python
        # ClickFocus so keyPressEvent (Escape during offset drag) reaches us; the
        # offset drag always begins with a click, so focus is guaranteed then.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
```

`mousePressEvent` に `ZONE_PLOT` 分岐を追加:

```python
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            zone = self._zone_at(event.position())
            if zone in (ZONE_X_INNER, ZONE_X_OUTER):
                self._drag_zone = zone
                self._drag_start = event.position()
            elif zone == ZONE_PLOT:
                key = self._curve_at(event.position())
                if key is not None:
                    self._begin_offset_drag(key, event.position())
        super().mousePressEvent(event)
```

`mouseMoveEvent` を拡張:

```python
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._offset_drag_key is not None:
            self._update_offset_preview(event.position(), event.globalPosition())
            super().mouseMoveEvent(event)
            return
        if self._drag_zone is None:
            self.setCursor(cursor_for_zone(self._zone_at(event.position())))
        super().mouseMoveEvent(event)
```

`mouseReleaseEvent` を拡張（オフセット分岐を先頭に）:

```python
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._offset_drag_key is not None:
            self._end_offset_drag()
            super().mouseReleaseEvent(event)
            return
        if self._drag_zone is not None and self._drag_start is not None:
            axis = "x"
            start = self._data_value(self._drag_start, axis)
            end = self._data_value(event.position(), axis)
            if start is not None and end is not None:
                self.apply_zone_drag(self._drag_zone, start, end)
        self._drag_zone = None
        self._drag_start = None
        super().mouseReleaseEvent(event)
```

`keyPressEvent` を追加（mouse handlers の近く）:

```python
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() == Qt.Key.Key_Escape
            and self._offset_drag_key is not None
        ):
            self._cancel_offset_drag()
            event.accept()
            return
        super().keyPressEvent(event)
```

オフセットドラッグのヘルパ群を追加（`_curve_at` の後あたり）:

```python
    # ─── R14 offset drag ────────────────────────────────────────────────────────

    def _begin_offset_drag(self, key: str, pos: QPointF) -> None:
        """Activate offset drag on *key*: capture origin, highlight, set cursor."""
        start_x = self._data_value(pos, "x")
        if start_x is None:
            return
        item = self._items[key]
        xs, ys = item.getData()
        self._offset_drag_key = key
        self._offset_drag_start_x = start_x
        self._offset_orig_xy = (np.asarray(xs).copy(), np.asarray(ys).copy())
        self._offset_orig_pen = item.opts.get("pen")
        self._offset_last_delta = 0.0
        # Highlight the active waveform (wider pen, same colour) per §12.
        item.setPen(pg.mkPen(self.pen_color(key), width=3))
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def _update_offset_preview(self, pos: QPointF, global_pos: QPointF) -> None:
        """Shift the active curve by Δt = current_x - start_x and show the tooltip."""
        key = self._offset_drag_key
        if key is None or key not in self._items or self._offset_orig_xy is None:
            self._cancel_offset_drag()
            return
        cur_x = self._data_value(pos, "x")
        if cur_x is None or self._offset_drag_start_x is None:
            return
        delta_t = cur_x - self._offset_drag_start_x
        self._offset_last_delta = delta_t
        orig_xs, orig_ys = self._offset_orig_xy
        self._items[key].setData(orig_xs + delta_t, orig_ys)
        QToolTip.showText(global_pos.toPoint(), f"Δt = {delta_t:+.3g} s")

    def _end_offset_drag(self) -> None:
        """On release: stop tracking and defer the apply dialog (avoid exec in handler)."""
        key = self._offset_drag_key
        delta_t = self._offset_last_delta
        if key is None:
            return
        # Defer so QDialog.exec() does not run inside the mouse-event handler
        # (mirrors the axis-move deferred-drop pattern; avoids stale-scene hangs).
        QTimer.singleShot(0, lambda: self._finish_offset(key, delta_t))

    def _finish_offset(self, key: str, delta_t: float) -> None:
        """Show the apply dialog and emit / cancel based on the chosen scope."""
        if key not in self._items:
            self._reset_offset_state()
            return
        fn = self._apply_dialog_fn or self._default_apply_dialog
        scope = fn(key, delta_t)
        if scope in ("signal", "group"):
            # Restore the pen now; the broadcast refresh re-renders at the committed
            # offset (the pen is reset by refresh anyway, but be explicit on cancel).
            self.offset_apply_requested.emit(key, delta_t, scope)
            self._reset_offset_state(restore_data=False)
        else:
            self._cancel_offset_drag()

    def _cancel_offset_drag(self) -> None:
        """Discard the preview, restore original data + pen, clear state (R14.7/8)."""
        self._reset_offset_state(restore_data=True)

    def _reset_offset_state(self, restore_data: bool = True) -> None:
        key = self._offset_drag_key
        if key is not None and key in self._items:
            if restore_data and self._offset_orig_xy is not None:
                self._items[key].setData(*self._offset_orig_xy)
            if self._offset_orig_pen is not None:
                self._items[key].setPen(self._offset_orig_pen)
        QToolTip.hideText()
        self._offset_drag_key = None
        self._offset_drag_start_x = None
        self._offset_orig_xy = None
        self._offset_orig_pen = None
        self._offset_last_delta = 0.0

    def _default_apply_dialog(self, signal_key: str, delta_t: float) -> str | None:
        """Modal apply dialog: 'signal' / 'group' / None (cancel). Enter → signal."""
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QLabel,
            QRadioButton,
            QVBoxLayout,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("時間オフセットの適用")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"Δt = {delta_t:+.3g} s を適用します。対象を選択してください。"))
        sig_radio = QRadioButton("この信号のみ")
        grp_radio = QRadioButton("同じファイルグループ全体")
        sig_radio.setChecked(True)  # default → Enter applies signal scope
        lay.addWidget(sig_radio)
        lay.addWidget(grp_radio)
        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)
        ok_btn = box.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setDefault(True)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return "signal" if sig_radio.isChecked() else "group"
```

`refresh()` 内に「ドラッグ中に当該信号が消えた / プレビュー再適用」ガードを追加（カーブ更新ループの後、ジオメトリ同期の前）:

```python
        # R14: if a curve was rebuilt mid-offset-drag, keep the preview consistent.
        if self._offset_drag_key is not None:
            if self._offset_drag_key not in self._items:
                self._cancel_offset_drag()  # active waveform removed (§9)
            elif self._offset_orig_xy is not None:
                orig_xs, orig_ys = self._offset_orig_xy
                self._items[self._offset_drag_key].setData(
                    orig_xs + self._offset_last_delta, orig_ys
                )
```

- [ ] **Step 4: テスト合格を確認**

Run: `uv run pytest tests/gui/test_graph_panel_offset_drag.py -v`
Expected: PASS（5 件）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/gui/test_graph_panel_offset_drag.py -q
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_graph_panel_offset_drag.py
git commit
```
```
feat(gui): R14 オフセットドラッグジェスチャ（プレビュー/ツールチップ/Escape/適用ダイアログ）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k
```

---

## Task 6: GraphAreaView — offset_apply_requested の配線

**Files:**
- Modify: `src/valisync/gui/views/graph_area_view.py:122-136`（`_wire_panel`）
- Test: `tests/gui/test_graph_area_offset_wiring.py`（Create）

**Interfaces:**
- Consumes: `GraphPanelView.offset_apply_requested`（Task 5）, `GraphAreaVM.apply_offset`（Task 3）
- Produces: `_wire_panel` で `widget.offset_apply_requested.connect(...)` → `self.vm.apply_offset(key, dt, scope)`

### gui-test-plan 分析（Task 6）
- **変更種別**: GUI 配線（Signal→VM メソッド）。実イベント経路の結線。
- **Layer A**: 不可（Qt Signal の結線確認）。
- **Layer B（必須）**: `GraphAreaView` を実構築し、子 `GraphPanelView` の `offset_apply_requested` を emit（実 Signal）→ app_vm の dict 更新＋兄弟/全パネルの再描画が起きることを検証。
- **Layer C**: 不要（結線の正しさは Layer B で十分。実 OS 入力は Task 7）。
- **②実質性**: 実 Signal emit → app_vm.signal_offsets 更新 ＋ 同一信号を表示する別パネルの `curve_xy` がシフト、を end-to-end でアサート（R14.5 の View 層到達を実結線で証明）。
- **honest layering**: emit は Task 5 のジェスチャの代理（ジェスチャ自体は Task 5 で検証済み）。ここは「結線」だけを切り出して独立に accept/reject 可能にする。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_graph_area_offset_wiring.py`（新規）:

```python
"""Layer B: GraphAreaView が offset_apply_requested を VM に配線する (R14)。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from valisync.core.models import Delimiter, FormatDefinition
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
from valisync.gui.views.graph_area_view import GraphAreaView
from valisync.gui.views.graph_panel_view import GraphPanelView


def _area_view(qtbot: QtBot):
    d = Path(tempfile.mkdtemp())
    csv = d / "data.csv"
    rows = ["t,s1"] + [f"{i * 0.01:.3f},{i}.0" for i in range(30)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    app = AppViewModel()
    app.request_load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    signal_key = sorted(s.name for s in app.signals())[0]
    area_vm = GraphAreaVM(app)
    area_vm.panels(0)[0].add_signal_to_axis(signal_key, 0)
    view = GraphAreaView(area_vm)
    qtbot.addWidget(view)
    view.resize(700, 500)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()
    return view, app, area_vm, signal_key


def _first_panel_view(area_view) -> GraphPanelView:
    splitter = area_view.tabs.widget(0)
    for i in range(splitter.count()):
        w = splitter.widget(i)
        if isinstance(w, GraphPanelView):
            return w
    raise AssertionError("no GraphPanelView found")


def test_offset_request_updates_app_and_rerenders(qtbot: QtBot) -> None:
    view, app, area_vm, signal_key = _area_view(qtbot)
    panel_view = _first_panel_view(view)
    base = np.asarray(panel_view.curve_xy(signal_key)[0]).copy()

    panel_view.offset_apply_requested.emit(signal_key, 0.5, "signal")
    for _ in range(3):
        QApplication.processEvents()

    assert app.signal_offsets == {signal_key: 0.5}
    after = np.asarray(panel_view.curve_xy(signal_key)[0])
    np.testing.assert_allclose(after, base + 0.5)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_graph_area_offset_wiring.py -v`
Expected: FAIL（emit しても app_vm が更新されない／curve 不変）

- [ ] **Step 3: 最小実装**

`graph_area_view.py` の `_wire_panel` に結線を追加（`remove_panel_requested` の後）:

```python
        widget.offset_apply_requested.connect(
            lambda k, dt, sc: self.vm.apply_offset(k, dt, sc)
        )
```

- [ ] **Step 4: テスト合格を確認**

Run: `uv run pytest tests/gui/test_graph_area_offset_wiring.py -v`
Expected: PASS（1 件）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/gui/test_graph_area_offset_wiring.py -q
git add src/valisync/gui/views/graph_area_view.py tests/gui/test_graph_area_offset_wiring.py
git commit
```
```
feat(gui): R14 GraphAreaView が offset_apply_requested を VM へ配線

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k
```

---

## Task 7: realgui（Layer C）— 2パネルのクロス再描画（実 OS 入力＋実適用ダイアログ）

**Files:**
- Create: `tests/realgui/test_offset_drag.py`
- 再利用: `tests/realgui/test_global_cursor.py` の `_to_phys`/`_at`/`_skip_unless_real_display` 同形ヘルパ

**Interfaces:**
- Consumes: Task 5（ジェスチャ＋実 `_default_apply_dialog`）, Task 6（`offset_apply_requested` → `GraphAreaVM.apply_offset` 配線）, Task 3（`'offsets'` ブロードキャスト）, Task 1（`apply_offset`）

### gui-test-plan 分析（Task 7）
- **変更種別**: GUI 入力経路（実 OS マウス press/move/release ＋ 実 modal QDialog ＋ **実機クロスパネル再描画**）。設計 §10 が「realgui で最も壊れやすい」と名指す対象。
- **Layer A/B**: 不可（実 OS 入力経路・実 modal の表示と確定・**実 app→GraphAreaVM→panels の実機クロス再描画**は合成イベントでは証明不可。[[feedback_gui_verify_real_input]]）。
- **Layer C（必須・①証拠ゲート対象）**: 実 `GraphAreaView` ＋同一タブ2パネル（**両方が同一信号を表示**）。1枚目（可視）の曲線を実 OS で掴み右へ実ドラッグ → プレビュー → リリースで**実 modal ダイアログ** → 別 OS スレッドが Enter（既定＝この信号のみ）で確定（>3s で Escape ウォッチドッグ）→ **両パネルの `curve_xy` が同一 Δt だけシフト**。
- **②実質性**: 実ドラッグ結果として **1枚目だけでなく2枚目のパネルもシフト**することをアサート。これは実 `offset_apply_requested → GraphAreaVM.apply_offset → 'offsets' ブロードキャスト` が**実機経路**で動くことの証拠であり、単一パネルのジェスチャ＋実 modal 証明を**内包**する。**`set_offsets` シムは使わず実配線を通す**（縦 splitter なので2パネルは同幅＝同 LOD → 両カーブは同一配列で比較できる）。VM 直叩きや合成イベントでは迂回されるため Layer C 固有。
- **honest layering**: クロスパネル全更新を **realgui でも実証**する（Layer A/B の Task 3/6 は headless 証明として維持し、本タスクはそれを実機経路で裏打ち）。実適用ダイアログは Layer C のみ（Layer B は注入で回避）。
- **駆動の注意（メモリ準拠）**: オフセットドラッグ自体は QDrag ではなく通常 OS マウスなのでメインスレッド駆動可（[[gui_drag_drop_not_sendevent_reproducible]] の QDrag ハングとは別系）。ただし**リリース後の modal `exec()` はネスト event loop**で本スレッドをブロックするため、ダイアログ確定は**別 OS スレッド**から `keybd_event(VK_RETURN)` で送る＋3s ウォッチドッグで `VK_ESCAPE`（[[gui_realgui_drag_qtimer_hang]] の別スレッド＋watchdog 方針）。
- **掴み点**: マジック比でなく1枚目パネルの `sceneBoundingRect()` から採る（線形信号 `v=t` がプロット中央を通るので中央 press が確実にヒット）。
- **前提（offscreen spike 実測済み）**: 中央プロット（`ZONE_PLOT`）の実 press は `GraphPanelView.mousePressEvent` へ伝播する（ViewBox はマウス無効化で press を消費せず親へ伝播）。よって widget レベル `ZONE_PLOT` ジェスチャの前提は妥当。

- [ ] **Step 1: テストを書く（realgui）**

`tests/realgui/test_offset_drag.py`（新規）:

```python
"""Layer C: R14 時間オフセットのクロスパネル再描画を実 OS 入力で検証。--realgui で実行。

実 GraphAreaView＋同一タブ2パネル（両方が同一信号を表示）。1枚目(可視)の曲線を実 OS マウスで
掴み右へドラッグ→リリースで実 modal 適用ダイアログ→別スレッドが Enter で「この信号のみ」確定→
**両パネルの curve_xy が同一 Δt だけシフト**（②: 実 app→GraphAreaVM→panels の 'offsets' 配線が
実機経路で動く＝単一パネルのジェスチャ＋実 modal 証明を内包）。set_offsets シムは使わない。
縦 splitter なので2パネルは同幅＝同 LOD → 両カーブは同一配列で比較できる。
"""

from __future__ import annotations

import contextlib
import ctypes
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

pytestmark = pytest.mark.realgui
_MOVE, _LDOWN, _LUP = 0x0001, 0x0002, 0x0004
_KEYDOWN, _KEYUP = 0x0000, 0x0002
_VK_RETURN, _VK_ESCAPE = 0x0D, 0x1B


def _skip_unless_real_display() -> None:
    if sys.platform != "win32":
        pytest.skip("real OS input is Windows-only")
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.platformName() == "offscreen":
        pytest.skip("requires a real display — run: uv run pytest --realgui tests/realgui/")


def _to_phys(view, sx: float, sy: float) -> tuple[int, int]:
    from PySide6.QtCore import QPoint

    vp = view.plot_widget.mapFromScene(QPoint(int(sx), int(sy)))
    g = view.plot_widget.viewport().mapToGlobal(vp)
    dpr = view.devicePixelRatioF()
    return round(g.x() * dpr), round(g.y() * dpr)


def _at(x: float, y: float, flag: int) -> None:
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    user32.mouse_event(flag, 0, 0, 0, 0)


def _key(vk: int) -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, _KEYDOWN, 0)
    user32.keybd_event(vk, 0, _KEYUP, 0)


def _dialog_dismisser(stop: threading.Event) -> None:
    """別スレッド: 実 modal を Enter で確定（既定=この信号のみ）。3s で Escape ウォッチドッグ。"""
    time.sleep(0.6)
    if not stop.is_set():
        _key(_VK_RETURN)
    deadline = time.time() + 3.0
    while time.time() < deadline and not stop.is_set():
        time.sleep(0.2)
    if not stop.is_set():
        _key(_VK_ESCAPE)


def _two_panel_area(qtbot: QtBot):
    """実 app→GraphAreaVM→GraphAreaView を構築し、同一タブに同一信号を表示する2パネルを返す。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.core.models import Delimiter, FormatDefinition
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM
    from valisync.gui.views.graph_area_view import GraphAreaView
    from valisync.gui.views.graph_panel_view import GraphPanelView

    d = Path(tempfile.mkdtemp())
    csv = d / "lin.csv"
    rows = ["t,lin"] + [f"{i / 50.0:.4f},{i / 50.0:.4f}" for i in range(50)]
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    app = AppViewModel()
    app.request_load(
        csv,
        FormatDefinition(
            name="fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    signal_key = sorted(s.name for s in app.signals())[0]
    area_vm = GraphAreaVM(app)
    area_vm.add_panel(0)  # tab 0 now holds two panels (both visible in the splitter)
    for p in area_vm.panels(0):
        p.add_signal_to_axis(signal_key, 0)

    # Default factory builds real GraphPanelViews (real modal apply dialog) and
    # GraphAreaView._wire_panel connects offset_apply_requested → vm.apply_offset.
    view = GraphAreaView(area_vm)
    qtbot.addWidget(view)
    view.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    view.setGeometry(200, 100, 900, 800)
    view.show()
    qtbot.waitExposed(view)
    for _ in range(3):
        QApplication.processEvents()

    splitter = view.tabs.widget(0)
    panels = [
        splitter.widget(i)
        for i in range(splitter.count())
        if isinstance(splitter.widget(i), GraphPanelView)
    ]
    assert len(panels) == 2
    qtbot.waitUntil(
        lambda: all(
            p._view_boxes[0].sceneBoundingRect().height() > 100 for p in panels
        ),
        timeout=3000,
    )
    return view, panels, signal_key


def test_real_offset_drag_shifts_both_panels(qtbot: QtBot, tmp_path) -> None:
    _skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    view, panels, key = _two_panel_area(qtbot)
    p0, p1 = panels[0], panels[1]
    x0_before = np.asarray(p0.curve_xy(key)[0]).copy()
    x1_before = np.asarray(p1.curve_xy(key)[0]).copy()

    # Grab p0's curve at the plot centre (linear v=t passes through it) and drag right.
    vb = p0._view_boxes[0]
    rect = vb.sceneBoundingRect()
    start_sx = rect.x() + rect.width() * 0.5
    start_sy = rect.y() + rect.height() * 0.5
    target_sx = rect.x() + rect.width() * 0.75
    gx, gy = _to_phys(p0, start_sx, start_sy)
    tx, _ = _to_phys(p0, target_sx, start_sy)

    stop = threading.Event()
    dismisser = threading.Thread(target=_dialog_dismisser, args=(stop,), daemon=True)
    dismisser.start()

    _at(gx, gy, _LDOWN)
    time.sleep(0.05)
    steps = max(2, (abs(tx - gx) + 7) // 8)
    for k in range(1, steps + 1):
        _at(gx + (tx - gx) * k // steps, gy, _MOVE)
        QApplication.processEvents()
        time.sleep(0.02)
    _at(tx, gy, _LUP)
    # Pump the event loop so the deferred dialog opens and the thread confirms it.
    for _ in range(40):
        QApplication.processEvents()
        time.sleep(0.05)
    stop.set()
    dismisser.join(timeout=2.0)

    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(tmp_path / "offset_cross.png"))

    x0_after = np.asarray(p0.curve_xy(key)[0])
    x1_after = np.asarray(p1.curve_xy(key)[0])
    # p0 (dragged) re-rendered with the committed offset → leftmost x moved right.
    assert float(x0_after.min()) > float(x0_before.min()) + 1e-3
    # p1 (the OTHER panel) re-rendered identically via the real 'offsets' broadcast
    # (same width → same LOD → identical arrays). This is the cross-panel evidence.
    np.testing.assert_allclose(x1_after, x0_after, atol=1e-6)
    assert float(x1_after.min()) > float(x1_before.min()) + 1e-3
```

- [ ] **Step 2: ローカル（offscreen）で skip されることを確認**

Run: `uv run pytest tests/realgui/test_offset_drag.py -q`
Expected: SKIPPED（offscreen のため `_skip_unless_real_display` が skip）。本セッション（bg）は realgui を実行しない。

- [ ] **Step 3: コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/realgui/test_offset_drag.py -q
git add tests/realgui/test_offset_drag.py
git commit
```
```
test(gui): R14 realgui オフセットドラッグの2パネルクロス再描画（実 OS 入力＋実適用ダイアログ）

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k
```

> **注**: このテストは作成・コミットのみ。実 OS 入力での実行は Task 8 の ①証拠ゲート（ユーザー実行）で行う。

---

## Task 8: ドキュメント更新 ＋ merge ゲート（①realgui 証拠ゲート）

**Files:**
- Modify: `docs/superpowers/specs/2026-06-29-gui-analysis-cursor-offset-design.md`（ステータス行・§12 確定値）
- Modify: `CLAUDE.md`（Phase 状況表の valisync-gui-analysis 行）
- Modify: `docs/roadmap.md`（analysis の R14 完了反映）

### gui-test-plan 分析（Task 8）
- **変更種別**: ドキュメント＋検証ゲート（コード変更なし）。
- **テスト**: 新規テストなし。代わりに**全レイヤーの集約検証**（headless full ＋ realgui scoped）。
- **①証拠ゲート（必須・merge 前）**: realgui が `--realgui` opt-in や CI 自動 skip で「skipped＝検証済み」と誤認されないよう、**実 win32 で realgui を実行し PASS 証拠**を残す。**realgui の実行はユーザーのステップ**（本 bg セッションは実 OS カーソルを動かせない）。

- [ ] **Step 1: 設計 spec のステータスを更新**

`docs/.../2026-06-29-gui-analysis-cursor-offset-design.md` のステータス行（line 6）に「増分C=R14 実装完了」を追記し、§12「増分C（R14）で確定」ブロックに本プランの確定値（`CURVE_HIT_TOL_PX=8`/`CURSOR_LINE_HIT_PX=10`/ペン幅 3 ハイライト/累積セマンティクス）を反映。

- [ ] **Step 2: CLAUDE.md Phase 表を更新**

`valisync-gui-analysis` 行の「増分C(R14 時間オフセット) 未着手」を「増分C=R14 実装完了（realgui 証拠ゲートは /gui-verify 実行待ち）」へ。

- [ ] **Step 3: roadmap を更新**

`docs/roadmap.md` の analysis 記述に R14 完了を反映。

- [ ] **Step 4: headless full ＋ 全ゲート（本セッションで実行）**

Run:
```bash
uv run pytest -q          # realgui は offscreen skip。0 errors / 0 failed
uv run ruff check
uv run ruff format --check
uv run mypy src/
```
Expected: 全 pass（既存 + R14 新規）/ realgui は skipped。

- [ ] **Step 5: ①realgui 証拠ゲート（/gui-verify — ユーザー実行）**

`/gui-verify` を実行（**ユーザーのステップ**。bg セッションでは不可）:
```bash
uv run pytest --realgui tests/realgui/test_offset_drag.py -v
# 期待: test_real_offset_drag_shifts_both_panels PASSED（実 win32）
uv run pytest --realgui tests/realgui/test_global_cursor.py -v
# 既存 2 本の無回帰確認
```
- [ ] realgui `test_offset_drag` が実 win32 で **PASSED**（証拠＝PASS 出力＋ `offset_drag.png`）。
- [ ] realgui 既存（global_cursor / active_axis）が**無回帰**。
- [ ] headless full が **0 errors**。

- [ ] **Step 6: docs コミット**

```bash
git add docs/ CLAUDE.md
git commit
```
```
docs: R14 時間オフセット 実装完了を spec/CLAUDE/roadmap に反映

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K4DdRanCvZQufhtWTBmp3k
```

- [ ] **Step 7: finishing-a-development-branch**

①証拠ゲート充足後、`superpowers:finishing-a-development-branch` で push → PR → CI → merge。

---

## Self-Review（writing-plans）

**1. Spec coverage（設計 §2/§4/§5/§8 と親 R14.x）:**
- R14.1 アクティブ波形＋水平ドラッグでプレビュー → Task 5（`_begin/_update_offset_preview`）。
- R14.2 ライブプレビュー平行移動 → Task 5（`setData(orig+Δt)`）。
- R14.3 適用対象 Session マッピング（signal/group） → Task 1（dict 分岐）＋ Task 2（`_signal_map` 適用）。
- R14.4 Session 適用 → Task 2（`Session.apply_offset`）。
- R14.5 全パネル更新 → Task 3（`_for_each_panel` 全タブ headless）＋ Task 6（View 結線 headless）＋ Task 7（realgui 2パネル実機クロス再描画）。
- グループ適用のセマンティクス（兄弟 signal オフセットをリセット・ユーザー決定） → Task 1（group 分岐で `"<group>::"` prefix 一致を削除）＋ Layer A テスト `test_group_apply_resets_sibling_signal_offsets`。
- R14.6 ツールチップ Δt 3 桁 → Task 5（`f"{:+.3g}"`）。
- R14.7/8 Escape／キャンセルで復元・dict 不変 → Task 5（`_cancel_offset_drag`／cancel 分岐）。
- §4 優先順位（カーソル線＞曲線、空クリック不使用） → Task 4（`_curve_at` ガード）＋ Task 5（`ZONE_PLOT` のみ起動）。
- §9 ドラッグ中に信号除去 → Task 5（`refresh`/preview ガード）。
- §10 Layer A/B/C ＋ ②/① → 各 Task の gui-test-plan ブロック＋ Task 7/8。
- §12 オープン項目 → 冒頭の確定値表。
- 非永続（アンロードでパージ） → Task 1。

ギャップなし。

**2. Placeholder scan:** 「TBD/後で/同様に/適切なエラー処理」等なし。各コード step に完全コード。realgui の駆動も具体コードで明示。

**3. Type consistency:**
- `apply_offset(signal_key: str, delta_t: float, scope: str) -> None` を Task 1/3/5/6 で一貫使用。
- `set_offsets(signal_offsets: dict[str,float], file_offsets: dict[str,float]) -> None` を Task 2/3 で一貫。
- `_curve_at(pos: QPointF) -> str | None` を Task 4/5 で一貫。
- `offset_apply_requested = Signal(str, float, str)` を Task 5/6 で一貫（emit 引数順 key, delta_t, scope）。
- グループキー抽出 `split("::", 1)[0]` を Task 1/2 で統一（既存 `graph_panel_vm.py:191` の literal 分割と整合・新規コア import なし）。
- `apply_dialog_fn: Callable[[str, float], str | None]` の戻り `'signal'|'group'|None` を Task 5 内で一貫。

矛盾なし。

---

## Execution Handoff

> 本プランはユーザーレビュー gate を経て実装に進む。承認後、実装は **subagent-driven-development**（タスクごとに fresh subagent ＋ 2 段レビュー）を推奨。realgui（Task 7 実行＝Task 8 Step 5）は**ユーザーが実 win32 で実行**する（bg セッションは実 OS 入力不可）。
