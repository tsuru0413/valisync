# 列展開遅延化 E-2（ブラウザ）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** チャンネルブラウザが「展開後の列」ではなく「物理チャンネル」を消費するようにし、per-列の VM/モデル残渣（実測 87 MB）を落とす。**ローダーはまだ列を展開する**ので、合成した列キーは必ず実 Signal に当たり、ブラウザ単独で検証できる。

**Architecture:** ローダーが各列 Signal に**物理チャンネル名**を metadata として付ける（加算的・挙動不変）。`ChannelBrowserVM` はそれで物理チャンネル単位に prep を作り、`tree_groups()` は葉のリストでなく `(base, unit, base_key, column_count)` を返す。`SignalTreeModel` は子ノードを**要求時に合成**する。ツリーは**1 行＝1 物理チャンネル**へ平坦化し、件数は列を ch 単位で数え、フィルタは列名にマッチしつつ名前キャッシュで賄う。

**Tech Stack:** Python 3.13 / PySide6 / numpy / pytest。

**設計 spec:** [2026-07-24-deferred-column-expansion-design.md](../specs/2026-07-24-deferred-column-expansion-design.md)（E-2 の節が一次情報源）。前提: [E-0/E-1 プラン](2026-07-24-deferred-expansion-e0-e1.md) 完了済み。

## Global Constraints

- 品質ゲート全通過: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- **ローダーは列展開を続ける**（反転は E-3）。合成した列キーは既存 `signal_map()` で必ず解決できる。
- **文字列解析で物理チャンネルを推測してはならない**。`ACC.Speed`（ドット入りチャンネル名）と `P.x`（構造化フィールド）は文字列では区別できない（Critical 2 と同型・quick_demo は 173 中 156 がドット付き）。物理チャンネル名は**ローダー由来の metadata** を使う。
- **ユーザー決定（変更不可）**: ツリーは 1 行＝1 物理チャンネルへ**平坦化**（モジュール階層は廃止）／件数は**列を ch 単位**で「`{total} ch 中 {shown} ch を表示`」／フィルタは**列名にマッチ**し**名前キャッシュ**で賄う。
- GUI 変更は Layer A/B（CI）必須・Layer C（`--realgui`）で ①ゲート。
- コメントは WHY を書く。DRY / YAGNI / TDD。
- 実装はブランチ `feature/lazy-load-samples` 上。main 直接編集禁止。

## E2E 受け入れ設計（/gui-test-plan）

| 効果 | E2E タイプ | 実 observable | prod スケール | 実経路 exercise |
|---|---|---|---|---|
| ツリーが 1 行＝1 物理チャンネルへ平坦化 | 描画＋入力経路(C) | 実ディスプレイでトップレベル行数＝物理チャンネル数（quick_demo で 24→173）・**配列チャンネルを実クリックで展開すると列が出る** | 不要（quick_demo で構造が出る） | 実 MainWindow＋実クリック |
| 件数表示が列を ch 単位で出る | 描画 | 実ヘッダー文字列（フィルタ前後） | 不要 | 実 VM→実ラベル |
| 列名フィルタが効く | 入力経路(C) | 実タイピングで `0000[5` が親を絞り込む | 不要 | 実キー入力 |
| **VM/モデル残渣の削減** | perf | **psutil 実測（prep＋tree_groups 後の RSS）で −約 87 MB** | **必須（prod_demo）** | 実 GUI ロード経路 |

- **必要レイヤー**: A=必須／B=要（VM の prep・tree_groups・フィルタ・件数）／入力経路 E2E(C)=要（平坦化とフィルタは実ツリーでしか確認できない）／perf E2E=**要（prod スケール）**／描画 E2E=要。
- **①証拠ゲート**: `uv run pytest --realgui tests/realgui/test_channel_tree_flatten_realclick.py` ＋証拠添付。
- **honest layering note**: 「行数が減った」だけでは残渣削減の証拠にならない（`is_materialized` と RSS の関係と同じ）。**psutil 実測**と**行数/構造の実機確認**の両方が要る。
- **凍結カタログ**: ツリー行構造が変わるため `screenshots_catalog_{dark,light}` の該当状態が変わる。**プロット面（viewport）は不変**であることを `--crop-meta` で機械証明し、差分がツリー内に限定されることを示してからベースライン更新する。

---

## Task 1: ローダーが物理チャンネル名を metadata に付ける（加算的・挙動不変）

**Files:**
- Modify: `src/valisync/core/loaders/mdf_loader.py`（Signal 構築部）
- Test: `tests/core/loaders/test_physical_channel_metadata.py`（新規）

**Interfaces:**
- Produces: 展開列の Signal は `metadata["physical_channel"]` に**生の物理チャンネル名**（`base_name`・`[idx]` 曖昧化前）を持つ。非展開（1D）チャンネルも同じキーを持つ（値は自身の base 名）。

- [ ] **Step 1: 失敗テストを書く**

`tests/core/loaders/test_physical_channel_metadata.py`:

```python
"""列 Signal は自分がどの物理チャンネル由来かを metadata で持つ。

ブラウザが「1 行＝1 物理チャンネル」を作るのに文字列解析を使えないため
(ドットはチャンネル名にもフィールド区切りにも現れる・Critical 2 と同型)、
グループ化キーはローダー由来の真の同一性でなければならない。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.loaders.mdf_loader import MdfLoader


def test_expanded_columns_carry_physical_channel_name(tmp_path: Path) -> None:
    path = tmp_path / "arr.mf4"
    write_mdf4_2d(path, name="Mat", values=np.arange(12, dtype=np.uint8).reshape(4, 3))
    sg = MdfLoader().load(path, confirm_expansion=None).signal_group
    assert sg is not None
    cols = [s for s in sg.signals if s.name.startswith("Mat[")]
    assert len(cols) == 3
    assert {s.metadata["physical_channel"] for s in cols} == {"Mat"}


def test_scalar_channel_carries_its_own_name(tmp_path: Path) -> None:
    from tests.mdf4_helpers import CAN, write_mdf4

    path = tmp_path / "scalar.mf4"
    write_mdf4(path, [("Spd", CAN, np.arange(4, dtype=np.float64))])
    sg = MdfLoader().load(path, confirm_expansion=None).signal_group
    assert sg is not None
    sig = next(s for s in sg.signals if s.name == "Spd")
    assert sig.metadata["physical_channel"] == "Spd"
```

> 実装者へ: `tests/mdf4_helpers.py` の既存ヘルパ名（`write_mdf4` / `write_mdf4_2d` 等）を確認し、
> 実際にあるものへ合わせること。2D を書くヘルパが別名なら、その名前を使う。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_physical_channel_metadata.py -q`
Expected: FAIL（`KeyError: 'physical_channel'`）

- [ ] **Step 3: ローダーで metadata を付ける**

`mdf_loader.py` の Signal 構築ループ（`out_metadata` を組み立てている箇所）に 1 行追加:

```python
                # ブラウザが「1 行=1 物理チャンネル」を作るためのグループ化キー。
                # 文字列解析では ACC.Speed (チャンネル名) と P.x (構造化フィールド) を
                # 区別できないため、ローダーが知っている生の base_name を渡す。
                out_metadata["physical_channel"] = base_name
```

- [ ] **Step 4: 通ることを確認 + 既存ローダーテスト全通過**

Run: `uv run pytest tests/core/loaders/ tests/test_loaders.py -q`
Expected: PASS（metadata の追加は加算的で既存の診断・命名・展開規約に影響しない）

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/core/loaders/mdf_loader.py tests/core/loaders/test_physical_channel_metadata.py
git commit -m "feat(core): 列 Signal に物理チャンネル名 metadata を付与 (ブラウザのグループ化キー)"
```

---

## Task 2: VM の prep を物理チャンネル単位にし、`tree_groups()` が仕様を返す

**Files:**
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py`
- Test: `tests/gui/test_channel_browser_vm.py`（既存を追随）＋`tests/gui/test_channel_browser_physical.py`（新規）

**Interfaces:**
- Consumes: `metadata["physical_channel"]`（Task 1）
- Produces:
  - `ChannelBrowserVM._prep: list[tuple[str, str, str, str, int]]` — `(physical_name, lower, unit, base_key, column_count)`
  - `tree_groups() -> list[tuple[str, str, str, int]]` — `(physical_name, unit, base_key, column_count)`（**葉のリストは返さない**）
  - `column_names_for(base_key: str) -> list[tuple[str, str, str]]` — `(orig, unit, key)`。要求時に**その物理チャンネルの列だけ**を返す（モデルの子合成用）
  - `shown_count() -> int` — **一致した列の総数**（件数表示が列基準のため）

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_channel_browser_physical.py`:

```python
"""ブラウザは物理チャンネル単位で行を作る (1 行 = 1 物理チャンネル)。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tests.mdf4_helpers import CAN, write_mdf4, write_mdf4_2d
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM


def _vm(tmp_path: Path) -> ChannelBrowserVM:
    path = tmp_path / "mix.mf4"
    write_mdf4_2d(path, name="Mat", values=np.arange(12, dtype=np.uint8).reshape(4, 3))
    session = Session()
    app_vm = AppViewModel(session)
    key = session.load(path, confirm_expansion=None).key
    app_vm.register_loaded(key)
    app_vm.set_active_file(key)
    return ChannelBrowserVM(app_vm)


def test_tree_groups_is_one_row_per_physical_channel(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    rows = vm.tree_groups()
    names = [name for name, _unit, _key, _n in rows]
    assert "Mat" in names
    assert not any(n.startswith("Mat[") for n in names)  # 列は行にならない
    mat = next(r for r in rows if r[0] == "Mat")
    assert mat[3] == 3  # column_count


def test_dotted_channel_name_is_not_split(tmp_path: Path) -> None:
    # ACC.Speed は「ACC の下の Speed」ではなく 1 本の物理チャンネル (平坦化)
    path = tmp_path / "dot.mf4"
    write_mdf4(path, [("ACC.Speed", CAN, np.arange(4, dtype=np.float64))])
    session = Session()
    app_vm = AppViewModel(session)
    key = session.load(path, confirm_expansion=None).key
    app_vm.register_loaded(key)
    app_vm.set_active_file(key)
    vm = ChannelBrowserVM(app_vm)
    names = [name for name, _u, _k, _n in vm.tree_groups()]
    assert names == ["ACC.Speed"]  # "ACC" ではない


def test_column_names_for_returns_only_that_channels_columns(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    mat = next(r for r in vm.tree_groups() if r[0] == "Mat")
    cols = vm.column_names_for(mat[2])
    assert [c[0] for c in cols] == ["Mat[0]", "Mat[1]", "Mat[2]"]


def test_shown_count_counts_columns_not_rows(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    # Mat の 3 列がそのまま件数に出る (行数 1 ではない)
    assert vm.shown_count() == 3
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_channel_browser_physical.py -q`
Expected: FAIL（`tree_groups()` が 2-tuple を返す・`column_names_for` 未定義）

- [ ] **Step 3: VM を書き換える**

`channel_browser_vm.py`:

1. `_base_of` と `_BASE_RE` を**削除**（文字列解析は使わない）。
2. `_ensure_prep` を物理チャンネル単位に:

```python
    def _ensure_prep(self) -> None:
        """物理チャンネル単位の (name, lower, unit, base_key, column_count) を作る。

        グループ化キーはローダー由来の metadata['physical_channel'] — 文字列解析では
        ACC.Speed (チャンネル名) と P.x (構造化フィールド) を区別できないため。
        E-2 時点ではローダーがまだ列を展開するので、ここで列を物理チャンネルへ畳む。
        """
        active_key = self._app_vm.active_file_key
        if self._prep_valid and self._prep_key == active_key:
            return
        if not active_key:
            self._prep = []
            self._prep_key = active_key
            self._prep_valid = True
            return
        group_sigs = self._app_vm.session.group_signals(active_key)
        by_phys: dict[str, tuple[str, str, str, int]] = {}
        order: list[str] = []
        for sig in group_sigs:
            ns_name = sig.name
            orig = (
                ns_name.split(KEY_SEPARATOR, 1)[1] if KEY_SEPARATOR in ns_name else ns_name
            )
            md = sig.metadata or {}
            phys = str(md.get("physical_channel") or orig)
            unit = str(md.get("unit", ""))
            if phys not in by_phys:
                base_key = ns_name if phys == orig else ns_name[: ns_name.rindex(orig)] + phys
                by_phys[phys] = (phys, phys.lower(), unit, 1)
                self._base_key_by_phys[phys] = base_key
                order.append(phys)
            else:
                name, low, u, n = by_phys[phys]
                by_phys[phys] = (name, low, u or unit, n + 1)
        self._prep = [(*by_phys[p], self._base_key_by_phys[p]) for p in order]
        self._prep_key = active_key
        self._prep_valid = True
```

> 実装者へ: `_prep` のタプル並びは自分で決めてよいが、**`tree_groups()` の戻り
> `(physical_name, unit, base_key, column_count)` と `shown_count()` の「列数」意味論**を守ること。
> `base_key` は `"{group_key}::{physical_name}"`（列キーと同じ名前空間）で作る。

3. `tree_groups()` は葉を作らず上記 4-tuple のリストを返す（フィルタ適用は Task 4）。
4. `column_names_for(base_key)` を新設し、その物理チャンネルの列だけを
   `(orig, unit, key)` で返す（`group_signals` から `physical_channel` 一致で絞る）。
5. `shown_count()` は**列数**を返す（フィルタ無しなら全列数）。

- [ ] **Step 4: 通ることを確認 + 既存 VM テストを追随**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py tests/gui/test_channel_browser_physical.py -q`
Expected: PASS。既存テストで `tree_groups()` の 2-tuple 形を前提にしているものは
**新しい契約へ書き換える**（葉の中身を見ていたテストは `column_names_for()` を使う形に）。
**assert を弱めないこと** — 「どの信号が見えるか」を検証しているテストは必ず等価に保つ。

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/gui/viewmodels/channel_browser_vm.py tests/gui/
git commit -m "feat(gui): チャンネルブラウザの prep を物理チャンネル単位へ (葉の事前生成を廃止)"
```

---

## Task 3: `SignalTreeModel` が子を要求時に合成する（平坦化）

**Files:**
- Modify: `src/valisync/gui/adapters/signal_tree_model.py`
- Test: `tests/gui/test_signal_tree_model.py`（既存を追随）＋新規ケース

**Interfaces:**
- Consumes: `tree_groups() -> [(name, unit, base_key, column_count)]`・`column_names_for(base_key)`（Task 2）

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_signal_tree_model.py` に追記:

```python
def test_top_level_rows_are_physical_channels(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # 1 行 = 1 物理チャンネル。配列チャンネルは 1 行で、展開して初めて列が出る。
    vm = _vm_with_array_channel(tmp_path)  # 既存ヘルパに合わせる
    model = SignalTreeModel(vm)
    tops = [model.index(r, 0).data() for r in range(model.rowCount())]
    assert "Mat" in tops
    assert not any(str(t).startswith("Mat[") for t in tops)


def test_children_are_synthesized_on_demand(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_array_channel(tmp_path)
    model = SignalTreeModel(vm)
    row = next(r for r in range(model.rowCount()) if model.index(r, 0).data() == "Mat")
    parent = model.index(row, 0)
    assert model.hasChildren(parent) is True     # column_count > 1 で判定
    assert model.rowCount(parent) == 3           # ここで初めて合成される
    assert model.index(0, 0, parent).data() == "Mat[0]"


def test_scalar_channel_has_no_children(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_array_channel(tmp_path)
    model = SignalTreeModel(vm)
    row = next(r for r in range(model.rowCount()) if model.index(r, 0).data() == "t")
    assert model.hasChildren(model.index(row, 0)) is False
```

> 実装者へ: 既存テストのフィクスチャ（`_vm_...`）の実名に合わせること。無ければ
> Task 2 の `_vm()` と同型のヘルパをこのファイルにも作る。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_signal_tree_model.py -q`
Expected: FAIL

- [ ] **Step 3: モデルを書き換える**

`signal_tree_model.py`:
1. `_Node` の `leaves`（事前生成した葉リスト）を廃し、代わりに `base_key: str | None` と
   `column_count: int` を持たせる。
2. `_rebuild()` は `tree_groups()` の 4-tuple から**トップレベル行だけ**を作る
   （`column_count == 1` なら葉ノード＝そのチャンネル自身がプロット可能・
   `column_count > 1` なら展開可能な親）。
3. `_materialize(node)` は `self._vm.column_names_for(node.base_key)` を呼んで子ノードを作る
   （**呼ばれるまで作らない**）。
4. `hasChildren` は `node.column_count > 1` で判定する。

- [ ] **Step 4: 通ることを確認 + 既存モデル/ビューテスト全通過**

Run: `uv run pytest tests/gui/ -q`
Expected: PASS。落ちたテストは新契約へ追随させる（**被覆を落とさない**）。

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/gui/adapters/signal_tree_model.py tests/gui/
git commit -m "feat(gui): ツリーを物理チャンネル 1 行へ平坦化し子を要求時合成 (葉の事前保持を廃止)"
```

---

## Task 4: 件数表示（列を ch 単位）とフィルタ（列名＋名前キャッシュ）

**Files:**
- Modify: `src/valisync/gui/strings.py`, `src/valisync/gui/viewmodels/channel_browser_vm.py`
- Test: `tests/gui/test_channel_browser_vm.py`・`tests/gui/test_strings*.py`（該当があれば）

**Interfaces:**
- Produces: `CHANNEL_HEADER_COUNT_TMPL` が `"{total} ch 中 {shown} ch を表示"`。`tree_groups()` はフィルタ適用後（一致列を持つ物理チャンネルのみ）。

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_channel_browser_physical.py` に追記:

```python
def test_header_counts_columns_in_ch_units(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    assert vm.header_text() == "3 ch 中 3 ch を表示"


def test_filter_matches_column_names_and_keeps_parent(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    vm.set_filter("mat[1")
    rows = vm.tree_groups()
    assert [r[0] for r in rows] == ["Mat"]     # 親は残る
    assert vm.shown_count() == 1               # 一致した列は 1 本
    assert vm.header_text() == "3 ch 中 1 ch を表示"


def test_filter_matching_nothing_yields_no_rows(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    vm.set_filter("zzz")
    assert vm.tree_groups() == []
    assert vm.shown_count() == 0
    assert vm.empty_state() == "no_match"
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_channel_browser_physical.py -q`
Expected: FAIL

- [ ] **Step 3: 文言と列名キャッシュを実装**

1. `strings.py`: `CHANNEL_HEADER_COUNT_TMPL: Final = "{total} ch 中 {shown} ch を表示"`
   （`CHANNEL_HEADER_EMPTY_TMPL` も `"0 ch"` へ揃える）。
2. `channel_browser_vm.py` に**列名キャッシュ**を追加:

```python
    def _ensure_column_names(self) -> None:
        """物理チャンネルごとの (小文字化した) 列名リストを一度だけ作る。

        フィルタは列名にマッチするが、production は 1 打鍵で 3 パス走る
        (model reset / header / empty_state)。都度生成だと実測 ~450 ms で現行
        (170-213 ms) より遅くなるため、名前だけをキャッシュする (実測 41.7 MB で
        1 打鍵 ~130 ms)。値は一切保持しない。
        """
```

   キャッシュは `_prep` と同じライフサイクル（`_prep_valid` が落ちたら捨てる）。
3. `tree_groups()` はフィルタ時、**一致列を 1 本以上持つ物理チャンネルのみ**返す。
4. `shown_count()` はフィルタ時、**一致した列の総数**を返す。

- [ ] **Step 4: 通ることを確認 + 文言/カタログ影響の確認**

Run: `uv run pytest tests/gui/ -q`
Expected: PASS。ヘッダー文言を assert している既存テストは新文言へ更新する。

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/gui/strings.py src/valisync/gui/viewmodels/channel_browser_vm.py tests/gui/
git commit -m "feat(gui): 件数を列の ch 単位表示へ・フィルタを列名マッチ＋名前キャッシュ化"
```

---

## Task 5: ①gate realgui ＋ 残渣削減の実測（受け入れ）

**Files:**
- Create: `tests/realgui/test_channel_tree_flatten_realclick.py`
- Modify: `scripts/measure_lazy_footprint.py`（prep/tree_groups 後の RSS を出力）

- [ ] **Step 1: realgui テストを書く（実 OS 入力）**

実ディスプレイで実 mf4 をロードし、(a) トップレベル行が**物理チャンネル**であること、
(b) 配列チャンネルの行を**実クリックで展開**すると列が現れること、(c) 検索ボックスに
**実タイピング**した `[1` で親が絞り込まれること、を assert する。共有
`tests/realgui/_realgui_input` を使い、**実マウスドラッグは使わない**（共有マシンでハング）。

- [ ] **Step 2: 実行して実機 pass を確認**

Run: `uv run pytest --realgui tests/realgui/test_channel_tree_flatten_realclick.py -q`
Expected: PASS（スクショ目視/AI 判定つき）

- [ ] **Step 3: 残渣削減を実測**

`scripts/measure_lazy_footprint.py` に「ロード → `signal_map()` → `group_signals()` →
**prep＋tree_groups**」の各段 RSS を出す段を足し、prod_demo で実行する。

Run: `uv run --with psutil python scripts/measure_lazy_footprint.py`
Expected: E-2 前の実測（`_prep` 68 MB＋`_Node.leaves` 19 MB ≒ 87 MB）が消えていること。
**数値を報告と PR 本文に記録する。**

- [ ] **Step 4: 凍結カタログの差分確認**

Run: 撮影と比較を実行し、**プロット面（viewport）が `--crop-meta` で完全一致**すること、
差分がチャンネルドック内に限定されることを機械証明してからベースラインを更新する。

- [ ] **Step 5: フルゲート＋コミット**

```bash
uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add tests/realgui/test_channel_tree_flatten_realclick.py scripts/measure_lazy_footprint.py
git commit -m "test(gui): E-2 の ①gate realgui ＋残渣削減の実測"
```

---

## E-3 への申し送り（E-1/E-2 のレビューが残したもの）

- **`RemovalResult.removed_columns` を `TeardownService` へ配線する**（E-1 Task 5 で生成のみ・
  未消費）。配線せずに E-3 で鋳造が生きると、鋳造列が teardown 会計から漏れる。
- **`dict(signal_map())` の AST/ratchet ガードを入れる**（E-1 Task 6）。E-3 で鋳造が生きると
  390 MB 回帰の防波堤が docstring だけになる。`tests/gui/test_theme_guard.py` に同型の前例がある。
- **Critical 1 の寿命ガードを production 鋳造経路にも張る**（E-1 Task 5 は test double 依存）。
- `metadata["physical_channel"]`（本プラン Task 1）は E-3 で `ColumnSpec` に置き換わる可能性が
  あるが、**キーは維持する**（ブラウザの契約になるため）。

## Self-Review（プラン著者チェック）

- **Spec coverage（E-2）**: 物理チャンネル単位の prep＝Task 2／ツリー平坦化と子の要求時合成＝Task 3／
  件数の ch 単位表示とフィルタ＝Task 4／①gate と残渣実測＝Task 5。**spec に無い Task 1 を追加**した
  理由: E-2 は「ローダーがまだ展開する」ため VM は文字列しか持たず、`ACC.Speed`（チャンネル名）と
  `P.x`（構造化フィールド）を区別できない（Critical 2 と同型）。ローダー由来の metadata が無いと
  平坦化が構造化チャンネルを壊す。加算的・挙動不変で E-3 の前段にもなる。
- **型整合**: `tree_groups() -> [(name, unit, base_key, column_count)]`・`column_names_for(base_key)
  -> [(orig, unit, key)]`・`shown_count()` は列数、で全 Task 一貫。
- **Placeholder**: 無し。テストのフィクスチャ名だけは既存ヘルパへの追随を明示的に指示している
  （リポジトリの実名に合わせる必要があるため）。
