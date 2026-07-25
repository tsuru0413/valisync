# 列展開遅延化 E-0（準備）＋E-1（解決器）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 列展開を遅延化する土台を作る — LD-14 の命名文法を単一モジュールへ抽出し（dtype 認識・逆変換つき）、列キーを要求時に解決する resolver と遅延解決 `signal_map()` を導入する。**ローダーはまだ展開したまま**なので、ユーザーから見た挙動もメモリも変わらない。

**Architecture:** `column_names.py` が「物理チャンネル 1 本の列構造」を表す `ColumnSpec` と、その上の `leaf_names`（ジェネレータ・数値リーフのみ）／`leaf_count`／`parse_leaf`（**最長一致の逆変換**）を持つ。`SignalGroupManager` は `resolve(key)` で列 Signal を鋳造し **per-group 副テーブル**に保持、`signal_map()` は**列挙は物理のみ・ルックアップは列も解決**する非対称 Mapping を返す。

**Tech Stack:** Python 3.13 / numpy / asammdf 8.8.22 / pytest。

**設計 spec:** [2026-07-24-deferred-column-expansion-design.md](../specs/2026-07-24-deferred-column-expansion-design.md)（E-0/E-1 の節が一次情報源）。

## Global Constraints

- 品質ゲート全通過: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- **E-0/E-1 は挙動不変**（ローダーはまだ列展開する）。既存テストが全て通ることが主要な受け入れ条件。
- **`parse_leaf` は文字列を '.' で split してはならない**。asammdf のフィールド名はチャンネル名そのもので '.' を含む（`quick_demo` は 173 中 156 がドット付き）。逆変換は**既知集合への最長一致**で行う。
- **鋳造した列 Signal のキャッシュを `_invalidate_namespaced()` に相乗りさせてはならない**。相乗りは 2 ファイル目ロードごとに全プロット列をフル再読みさせる（実測 0.73–1.18 s/列）。per-group 副テーブルで `remove(key)` のときだけ切り離す。
- **`leaf_names` は数値リーフのみを返す**（`dtype.kind in "iufb"`）。チャンネル単位の一括判定は禁止（構造化はフィールドごとに dtype が異なりうる）。
- **demo-gate 依存の禁止**: `demo_data/*.mf4` は gitignore され CI に存在しない。主要不変条件は非 demo-gate のテストで守る。
- コメントは WHY を書く。DRY / YAGNI / TDD。
- 実装はブランチ `feature/lazy-load-samples`（既存）上。main 直接編集禁止。

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `src/valisync/core/loaders/column_names.py` | `ColumnSpec`・`leaf_names`・`leaf_count`・`parse_leaf`（LD-14 命名文法の単一の真実） | 新規 |
| `src/valisync/core/loaders/mdf_loader.py` | `_flatten`/`_leaf_column_count` を `column_names` の上に再実装（挙動不変） | 変更 |
| `src/valisync/gui/viewmodels/graph_panel_vm.py` | `_signal_map` の offset overlay を O(offset信号) 化 | 変更 |
| `src/valisync/core/loaders/signal_group_manager.py` | `resolve()`・per-group 副テーブル・非対称 `signal_map()`・introspection | 変更 |
| `src/valisync/core/session.py` | `resolve_signal()` 委譲・`RemovalResult.removed_columns` | 変更 |

---

## Task 0: 死蔵コードの整理（E-3 の爆風半径を先に縮める）

production から呼ばれていない信号列挙 API とフラットモデルを削除する。**偽の保証が 1 つ消え**
（D&D テストが production に存在しないモデルを検証している）、**E-3 の「公開 API の意味縮小」が
1 件不要になり**、`inspect()` の 264k 構築が消える。

**production 参照の実測（削除の根拠）**:

| 対象 | production での使用 |
|---|---|
| `SignalTableModel` | **構築ゼロ**（class 定義と `adapters/__init__.py` の export のみ） |
| `SignalItem` | `SignalTableModel` と `ChannelBrowserVM.signals` のみ |
| `ChannelBrowserVM.signals`（プロパティ） | `SignalTableModel`（死蔵）と `inspect()` の `len(self.signals)` のみ |
| `AppViewModel.signals()` | **ゼロ** |
| `Session.unified_timeline_signals()` | **ゼロ**（かつ全信号に offset を適用＝遅延化と正面から衝突） |

**Files:**
- Delete: `src/valisync/gui/adapters/qt_signal_models.py`（`SignalTableModel`）, `tests/gui/test_qt_signal_models.py`
- Modify: `src/valisync/gui/adapters/__init__.py`, `src/valisync/gui/viewmodels/channel_browser_vm.py`（`SignalItem`・`signals`・`inspect`）, `src/valisync/gui/viewmodels/app_viewmodel.py`（`signals()`）, `src/valisync/core/session.py`（`unified_timeline_signals`）
- Modify(tests): `tests/gui/test_dnd_workflow.py`, `tests/gui/test_channel_browser_vm.py`, `tests/gui/test_data_explorer_view.py`, `tests/test_pbt_sync.py`, `tests/test_session.py`

**Interfaces:**
- Produces: `ChannelBrowserVM.inspect()["signal_count"]` は `shown_count()` 由来になる（値の意味は不変＝フィルタ後の件数）。

- [ ] **Step 1: 実 D&D 被覆が realgui にあることを確認（削除の前提）**

Run: `grep -n "def test_" tests/realgui/test_signal_dnd_realclick.py`
Expected: 実 QDrag による signal D&D が 5 本（新軸作成 / Y 帯上書き / Ctrl 結合 / **マルチセレクト** /
ドロップ直後ジェスチャ）。これが `tests/gui/test_dnd_workflow.py::TestSignalDragSource` と
`TestSignalDropToPanel::test_dropping_model_mime_adds_curves` の実経路版である。
**確認できない場合は削除せず報告する**（被覆を落としてはならない）。

- [ ] **Step 2: `inspect()` を `shown_count()` ベースへ（先に依存を外す）**

`src/valisync/gui/viewmodels/channel_browser_vm.py` の `inspect()`:

```python
            "signal_count": self.shown_count(),
```

（`shown_count()` は既存。`len(self.signals)` は 264k 個の `SignalItem` を構築していた。）

- [ ] **Step 3: 死蔵 API を削除**

1. `src/valisync/gui/adapters/qt_signal_models.py` から `SignalTableModel` を削除
   （ファイル内に他のクラスが残らなければファイルごと削除）。
2. `src/valisync/gui/adapters/__init__.py` から `SignalTableModel` の import と `__all__` 項目を削除。
3. `channel_browser_vm.py` から `SignalItem` dataclass と `signals` プロパティを削除
   （`_filtered()` が `SignalItem` を返す唯一の経路なので `_filtered()` も削除。`shown_count()` /
   `tree_groups()` / `_ensure_prep()` は残す）。
4. `app_viewmodel.py` の `signals()` メソッドを削除。
5. `session.py` の `unified_timeline_signals()` を削除。

- [ ] **Step 4: テストを追随させる**

1. `tests/gui/test_dnd_workflow.py`: `TestSignalDragSource` クラス全体と
   `TestSignalDropToPanel::test_dropping_model_mime_adds_curves` を削除し、
   `SignalTableModel`/`ChannelBrowserVM` の import を落とす。**`TestFileDropToGraphArea` /
   `TestFileDropToDataExplorer` / `test_drag_enter_highlights_panel` は残す**（QUrl mime と
   ハイライトの検証で死蔵モデルに依存しない）。モジュール docstring の
   「SignalTableModel as drag source」を、実経路は `tests/realgui/test_signal_dnd_realclick.py`
   が押さえる旨に書き換える。
2. `tests/gui/test_qt_signal_models.py` を削除。
3. `tests/gui/test_channel_browser_vm.py`: `SignalItem` / `vm.signals` を使うテストを
   `shown_count()` / `tree_groups()` ベースへ書き換えるか、`tree_groups()` に等価な被覆が
   あるものは削除する（**フィルタの挙動を検証しているテストは必ず残す** — 文言でなく
   「どの信号が残るか」を `tree_groups()` で assert する形にする）。
4. `tests/gui/test_data_explorer_view.py:138` の `app_vm.signals()` を
   `app_vm.session.signals()` へ。
5. `tests/test_pbt_sync.py` の Property 14（`unified_timeline_signals`）と
   `tests/test_session.py:274` の該当テストを削除。**offset 意味論の被覆は
   `tests/core/sync/` に残ることを確認してから消す**（`grep -n "def test_" tests/core/sync/*.py`）。

- [ ] **Step 5: 全テスト通過を確認**

Run: `uv run pytest tests/gui/ tests/core/ tests/test_session.py tests/test_pbt_sync.py -q`
Expected: PASS。削除漏れの import エラーが出たら潰す。

- [ ] **Step 6: 死蔵が本当に消えたことを確認**

Run: `grep -rn "SignalTableModel\|SignalItem\|unified_timeline_signals" src/ tests/ --include=*.py`
Expected: ヒット 0 件（docs/ のヒットは可。設計 spec の「公開 API の意味縮小」記述は
E-3 プランで更新する）。

- [ ] **Step 7: ゲート＋コミット**

Run: `uv run ruff check && uv run ruff format --check && uv run mypy src/`
```bash
git add -A
git commit -m "refactor: 死蔵の信号列挙 API を削除 (SignalTableModel/SignalItem/signals()/unified_timeline_signals)"
```

---

## Task 1: `ColumnSpec` と `leaf_names` / `leaf_count`（命名文法の抽出・dtype 認識）

**Files:**
- Create: `src/valisync/core/loaders/column_names.py`
- Test: `tests/core/loaders/test_column_names.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ColumnSpec` — `kind: str`（`"leaf"|"array"|"struct"`）／`dtype_kind: str`／`axis_len: int`／`child: ColumnSpec | None`／`fields: tuple[tuple[str, ColumnSpec], ...]`
  - `spec_from_probe(arr: np.ndarray) -> ColumnSpec`
  - `leaf_names(base: str, spec: ColumnSpec) -> Iterator[str]`（**数値リーフのみ**）
  - `leaf_count(spec: ColumnSpec) -> int`（数値リーフ数）

- [ ] **Step 1: 失敗テストを書く**

`tests/core/loaders/test_column_names.py`:

```python
from __future__ import annotations

import numpy as np

from valisync.core.loaders.column_names import (
    ColumnSpec,
    leaf_count,
    leaf_names,
    spec_from_probe,
)


def test_scalar_channel_has_single_leaf() -> None:
    spec = spec_from_probe(np.zeros(1, dtype=np.float64))
    assert spec.kind == "leaf"
    assert list(leaf_names("Spd", spec)) == ["Spd"]
    assert leaf_count(spec) == 1


def test_2d_channel_expands_per_column() -> None:
    spec = spec_from_probe(np.zeros((1, 3), dtype=np.uint8))
    assert list(leaf_names("Mat", spec)) == ["Mat[0]", "Mat[1]", "Mat[2]"]
    assert leaf_count(spec) == 3


def test_3d_channel_peels_axes_left_to_right() -> None:
    spec = spec_from_probe(np.zeros((1, 2, 2), dtype=np.int16))
    assert list(leaf_names("M", spec)) == ["M[0][0]", "M[0][1]", "M[1][0]", "M[1][1]"]
    assert leaf_count(spec) == 4


def test_structured_channel_uses_field_names() -> None:
    arr = np.zeros(1, dtype=[("x", "<f8"), ("y", "<f8")])
    spec = spec_from_probe(arr)
    assert list(leaf_names("P", spec)) == ["P.x", "P.y"]


def test_structured_field_names_may_contain_dots() -> None:
    # asammdf のフィールド名はチャンネル名そのもので '.' を含む (Critical 2)
    arr = np.zeros(1, dtype=[("Radar.ObjList", "<u1"), ("Radar.ObjList.dx", "<f8")])
    spec = spec_from_probe(arr)
    assert list(leaf_names("Radar.ObjList", spec)) == [
        "Radar.ObjList.Radar.ObjList",
        "Radar.ObjList.Radar.ObjList.dx",
    ]


def test_non_numeric_leaves_are_excluded() -> None:
    # 非数値リーフは Signal を作れないので列キー空間から外す (LD-12 と整合)
    arr = np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")])
    spec = spec_from_probe(arr)
    assert list(leaf_names("C", spec)) == ["C.ok"]
    assert leaf_count(spec) == 1


def test_struct_of_array_composes() -> None:
    arr = np.zeros(1, dtype=[("v", "<f8", (2,))])
    spec = spec_from_probe(arr)
    assert list(leaf_names("S", spec)) == ["S.v[0]", "S.v[1]"]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_column_names.py -q`
Expected: FAIL（`ModuleNotFoundError: column_names`）

- [ ] **Step 3: `column_names.py` を実装**

```python
"""LD-14 の列名文法の単一の真実 (ColumnSpec とその上の生成/逆変換).

従来は mdf_loader の ``_flatten`` と ``_leaf_column_count`` が同じ規則を 2 箇所で
手写ししており、共有コードも突合 assert も無かった。列展開を遅延化すると
「名前を生成する側」と「名前から列を引く側」が分離するため、乖離はサイレントに
誤った列を返す。本モジュールを唯一の実装とし、順序は _flatten と一致させる。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np

_NUMERIC_KINDS = "iufb"  # Signal が扱える dtype (それ以外は列キー空間に載せない)


@dataclass(frozen=True)
class ColumnSpec:
    """1 物理チャンネルの列構造 (値を持たない・1 レコードプローブから作る)."""

    kind: str  # "leaf" | "array" | "struct"
    dtype_kind: str = ""  # leaf のみ: numpy dtype.kind
    axis_len: int = 0  # array のみ: 先頭の非サンプル軸の長さ
    child: ColumnSpec | None = None  # array のみ: 1 段剥がした後の構造
    fields: tuple[tuple[str, ColumnSpec], ...] = ()  # struct のみ (順序保存)


def spec_from_probe(arr: np.ndarray) -> ColumnSpec:
    """samples (axis 0 = サンプル) から列構造を作る。_flatten と同じ規則・同じ順序。

    構造化を ndim より先に判定するのは _flatten と同一 (構造化 1D は struct 扱い)。
    """
    if arr.dtype.names:
        return ColumnSpec(
            kind="struct",
            fields=tuple((f, spec_from_probe(arr[f])) for f in arr.dtype.names),
        )
    if arr.ndim <= 1:
        return ColumnSpec(kind="leaf", dtype_kind=arr.dtype.kind)
    return ColumnSpec(kind="array", axis_len=int(arr.shape[1]), child=spec_from_probe(arr[:, 0]))


def leaf_names(base: str, spec: ColumnSpec) -> Iterator[str]:
    """数値リーフの列名を _flatten と同じ順序で生成する (ジェネレータ)."""
    if spec.kind == "struct":
        for name, sub in spec.fields:
            yield from leaf_names(f"{base}.{name}", sub)
    elif spec.kind == "array":
        assert spec.child is not None
        for i in range(spec.axis_len):
            yield from leaf_names(f"{base}[{i}]", spec.child)
    elif spec.dtype_kind in _NUMERIC_KINDS:
        yield base


def leaf_count(spec: ColumnSpec) -> int:
    """数値リーフの本数 (名前を生成せずに数える)."""
    if spec.kind == "struct":
        return sum(leaf_count(sub) for _n, sub in spec.fields)
    if spec.kind == "array":
        assert spec.child is not None
        return spec.axis_len * leaf_count(spec.child)
    return 1 if spec.dtype_kind in _NUMERIC_KINDS else 0
```

（`field` の import は未使用なら削除する。ruff が指摘する。）

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/core/loaders/test_column_names.py -q`
Expected: PASS（7 件）

- [ ] **Step 5: `_flatten` との順序一致を固定するテストを書く**

`tests/core/loaders/test_column_names.py` に追記:

```python
from valisync.core.loaders.mdf_loader import _flatten


def _numeric_flatten_names(base: str, arr: np.ndarray) -> list[str]:
    # _flatten は dtype 盲目なので、比較のため数値リーフだけに絞る
    return [n for n, col in _flatten(base, arr) if col.dtype.kind in "iufb"]


def test_leaf_names_order_matches_flatten() -> None:
    cases = [
        np.zeros(1, dtype=np.float64),
        np.zeros((1, 3), dtype=np.uint8),
        np.zeros((1, 2, 2), dtype=np.int16),
        np.zeros(1, dtype=[("x", "<f8"), ("y", "<f8")]),
        np.zeros(1, dtype=[("v", "<f8", (2,))]),
        np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")]),
        np.zeros(1, dtype=[("Radar.ObjList", "<u1"), ("Radar.ObjList.dx", "<f8")]),
    ]
    for arr in cases:
        spec = spec_from_probe(arr)
        assert list(leaf_names("B", spec)) == _numeric_flatten_names("B", arr)
        assert leaf_count(spec) == len(_numeric_flatten_names("B", arr))
```

- [ ] **Step 6: 実行して一致を確認**

Run: `uv run pytest tests/core/loaders/test_column_names.py -q`
Expected: PASS。不一致が出たら `column_names` 側を `_flatten` に合わせる（`_flatten` は正・既存の永続キー文法）。

- [ ] **Step 7: ゲート＋コミット**

Run: `uv run ruff check && uv run ruff format --check && uv run mypy src/`
```bash
git add src/valisync/core/loaders/column_names.py tests/core/loaders/test_column_names.py
git commit -m "feat(core): LD-14 列名文法を column_names.py へ抽出 (ColumnSpec・dtype 認識・_flatten 順序一致)"
```

---

## Task 2: `parse_leaf`（最長一致の逆変換）＋ asammdf 往復 fixture

列キー `grp::Radar.ObjList.Radar.ObjList.dx[0]` から (base, 列パス) を復元する。**'.' で split しない**。

**Files:**
- Modify: `src/valisync/core/loaders/column_names.py`
- Test: `tests/core/loaders/test_column_names.py`（往復）＋ `tests/core/loaders/test_column_names_asammdf.py`（実書き出し往復・新規）

**Interfaces:**
- Consumes: `ColumnSpec`, `leaf_names`（Task 1）
- Produces:
  - `def parse_leaf(display_key: str, specs: Mapping[str, ColumnSpec]) -> tuple[str, ColumnSpec] | None`
    — `specs` は「物理表示名 → ColumnSpec」。戻り値は (base 名, そのリーフの ColumnSpec)。解決不能は `None`。

- [ ] **Step 1: 失敗テストを書く**

`tests/core/loaders/test_column_names.py` に追記:

```python
from valisync.core.loaders.column_names import parse_leaf


def _specs(*pairs):  # type: ignore[no-untyped-def]
    return {name: spec_from_probe(arr) for name, arr in pairs}


def test_parse_leaf_round_trips_every_generated_name() -> None:
    cases = {
        "Spd": np.zeros(1, dtype=np.float64),
        "Mat": np.zeros((1, 3), dtype=np.uint8),
        "M": np.zeros((1, 2, 2), dtype=np.int16),
        "P": np.zeros(1, dtype=[("x", "<f8"), ("y", "<f8")]),
        "Radar.ObjList": np.zeros(
            1, dtype=[("Radar.ObjList", "<u1"), ("Radar.ObjList.dx", "<f8")]
        ),
    }
    specs = {n: spec_from_probe(a) for n, a in cases.items()}
    for base, spec in specs.items():
        for name in leaf_names(base, spec):
            got = parse_leaf(name, specs)
            assert got is not None, name
            assert got[0] == base, name


def test_parse_leaf_prefers_the_real_channel_on_collision() -> None:
    # 2D の Mat の第0列と、"Mat[0]" という名前の 1D チャンネルが衝突する
    specs = _specs(
        ("Mat", np.zeros((1, 2), dtype=np.uint8)),
        ("Mat[0]", np.zeros(1, dtype=np.float64)),
    )
    got = parse_leaf("Mat[0]", specs)
    assert got is not None
    assert got[0] == "Mat[0]"  # 最長一致 = 実チャンネルが勝つ


def test_parse_leaf_returns_none_for_unknown_base_or_bad_index() -> None:
    specs = _specs(("Mat", np.zeros((1, 2), dtype=np.uint8)))
    assert parse_leaf("Nope[0]", specs) is None
    assert parse_leaf("Mat[9]", specs) is None  # 範囲外
    assert parse_leaf("Mat", specs) is None  # 親そのものは列ではない
    assert parse_leaf("Mat[0]x", specs) is None  # 残余を消費しきれない


def test_parse_leaf_rejects_non_numeric_leaf() -> None:
    specs = _specs(("C", np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")])))
    assert parse_leaf("C.ok", specs) is not None
    assert parse_leaf("C.txt", specs) is None  # 非数値は列キー空間に無い
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_column_names.py -q`
Expected: FAIL（`parse_leaf` 未定義）

- [ ] **Step 3: `parse_leaf` を実装**

`column_names.py` に追記:

```python
from collections.abc import Mapping


def parse_leaf(
    display_key: str, specs: Mapping[str, ColumnSpec]
) -> tuple[str, ColumnSpec] | None:
    """列キーを (物理表示名, リーフの ColumnSpec) へ復元する。解決不能なら None。

    **'.' で split しない** — asammdf のフィールド名はチャンネル名そのもので '.' を
    合法に含む (例 dtype.names == ('Radar.ObjList', 'Radar.ObjList.dx'))。逆変換は
    既知集合への最長一致で行う: (1) 物理表示名の最長プレフィクスで base を確定
    (最長優先 = Mat[0] 衝突時は実チャンネルが勝つ)、(2) 残余を ColumnSpec が持つ
    実フィールド名と [i] トークンで消費する。曖昧・消費しきれない場合は None を返し、
    決して別の列を返さない。
    """
    for base in sorted(
        (n for n in specs if display_key.startswith(n)), key=len, reverse=True
    ):
        leaf = _consume(display_key[len(base) :], specs[base])
        if leaf is not None:
            return (base, leaf)
    return None


def _consume(rest: str, spec: ColumnSpec) -> ColumnSpec | None:
    """spec を辿って rest を消費する。消費しきってリーフに達したらそのリーフを返す。"""
    if spec.kind == "struct":
        # フィールド名は '.' を含みうるので、既知フィールドの最長一致で消費する
        for name, sub in sorted(spec.fields, key=lambda p: len(p[0]), reverse=True):
            token = f".{name}"
            if rest.startswith(token):
                got = _consume(rest[len(token) :], sub)
                if got is not None:
                    return got
        return None
    if spec.kind == "array":
        assert spec.child is not None
        if not rest.startswith("["):
            return None
        end = rest.find("]")
        if end < 0:
            return None
        index_text = rest[1:end]
        if not index_text.isdigit():
            return None
        if not (0 <= int(index_text) < spec.axis_len):
            return None
        return _consume(rest[end + 1 :], spec.child)
    # leaf: 残余が空で、かつ数値リーフのときだけ成立
    if rest:
        return None
    return spec if spec.dtype_kind in _NUMERIC_KINDS else None
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/core/loaders/test_column_names.py -q`
Expected: PASS

- [ ] **Step 5: asammdf 実往復 fixture のテストを書く（Critical 2 の要）**

`tests/core/loaders/test_column_names_asammdf.py`（新規・**非 demo-gate**）:

```python
"""asammdf で実書き出し→実読み戻ししたドット付きフィールド名で往復を固定する。

手書きの合成 dtype 名では再現しない: asammdf は配列チャンネルの第 0 フィールド名に
チャンネル名そのものを使うため、フィールド名が '.' を含む (Critical 2)。両 demo
ファイルは構造化チャンネル 0 本でこの不変条件を一切被覆しない。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from asammdf import MDF, Signal as ASignal

from valisync.core.loaders.column_names import leaf_names, parse_leaf, spec_from_probe


def _write_struct_mf4(tmp_path: Path) -> Path:
    ts = np.arange(4, dtype=np.float64)
    samples = np.zeros(4, dtype=[("Radar.ObjList", "<u1"), ("Radar.ObjList.dx", "<f8")])
    sig = ASignal(samples=samples, timestamps=ts, name="Radar.ObjList")
    out = tmp_path / "struct.mf4"
    with MDF() as mdf:
        mdf.append([sig])
        mdf.save(out, overwrite=True)
    return out


def test_dotted_field_names_round_trip(tmp_path: Path) -> None:
    path = _write_struct_mf4(tmp_path)
    with MDF(str(path)) as mdf:
        probe = mdf.select(
            [("Radar.ObjList", 0, None)],
            record_count=1,
            raw=True,
            ignore_value2text_conversions=True,
            copy_master=False,
        )[0]
        arr = probe.samples
    spec = spec_from_probe(arr)
    specs = {"Radar.ObjList": spec}
    names = list(leaf_names("Radar.ObjList", spec))
    assert names, "structured channel produced no leaves"
    # フィールド名がドットを含むことをまず実証 (合成 dtype では再現しない性質)
    assert any("." in f for f, _s in spec.fields)
    for name in names:
        got = parse_leaf(name, specs)
        assert got is not None, f"could not parse {name!r}"
        assert got[0] == "Radar.ObjList"
```

- [ ] **Step 6: 実行して通ることを確認**

Run: `uv run pytest tests/core/loaders/test_column_names_asammdf.py -q`
Expected: PASS。asammdf が実際に出す dtype 名が想定と違う場合は、**テストを弱めず**、
実際の `spec.fields` を print して確認し、`parse_leaf` 側を実データに合わせる。

- [ ] **Step 7: sabotage で honest-RED を確認**

`_consume` の struct 分岐を「`rest.split('.')` で先頭トークンを取る」素朴実装に一時的に
差し替え、Step 6 のテストが **FAIL** することを確認してから元に戻す。結果を報告に記す。

- [ ] **Step 8: ゲート＋コミット**

```bash
git add src/valisync/core/loaders/column_names.py tests/core/loaders/test_column_names.py tests/core/loaders/test_column_names_asammdf.py
git commit -m "feat(core): parse_leaf を最長一致で実装 (ドット付きフィールド名の往復を asammdf 実往復で固定)"
```

---

## Task 3: `_flatten` / `_leaf_column_count` を `column_names` の上に再実装（挙動不変）

同じ規則の 2 実装を 1 つに畳む。**既存ローダーテストが全て通ること**が受け入れ条件。

**Files:**
- Modify: `src/valisync/core/loaders/mdf_loader.py:54-88`
- Test: 既存 `tests/core/loaders/` 全て＋`tests/test_loaders.py`

**Interfaces:**
- Consumes: `spec_from_probe`, `leaf_count`（Task 1）

- [ ] **Step 1: 現行の挙動を固定するテストを書く（リファクタ前の安全網）**

`tests/core/loaders/test_column_names.py` に追記:

```python
from valisync.core.loaders.mdf_loader import _leaf_column_count


def test_leaf_column_count_counts_all_leaves_including_non_numeric() -> None:
    # _leaf_column_count は LD-14 の 1024 ガード用で dtype 盲目 (全リーフを数える)。
    # leaf_count (数値のみ) とは意図的に別物である。
    arr = np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")])
    assert _leaf_column_count(arr) == 2
    assert leaf_count(spec_from_probe(arr)) == 1
```

- [ ] **Step 2: 実行（現行実装で通るはず＝安全網の確認）**

Run: `uv run pytest tests/core/loaders/test_column_names.py -q`
Expected: PASS（現行の `_leaf_column_count` はリーフを dtype 無関係に数える）

- [ ] **Step 3: `_leaf_column_count` を `column_names` 上に再実装**

`mdf_loader.py` の `_leaf_column_count`（77-88 行）を置換:

```python
def _leaf_column_count(arr: np.ndarray) -> int:
    """arr を _flatten したときのリーフ列数 (1 レコードの samples でも可・LD-14).

    1024 ガードの母数なので **dtype 非依存に全リーフを数える** (数値のみを数える
    column_names.leaf_count とは意図的に別物)。構造は column_names の ColumnSpec に
    委譲し、規則の二重実装を避ける。
    """
    return _all_leaf_count(spec_from_probe(arr))


def _all_leaf_count(spec: ColumnSpec) -> int:
    if spec.kind == "struct":
        return sum(_all_leaf_count(sub) for _n, sub in spec.fields)
    if spec.kind == "array":
        assert spec.child is not None
        return spec.axis_len * _all_leaf_count(spec.child)
    return 1
```

`mdf_loader.py` の import に追加:

```python
from valisync.core.loaders.column_names import ColumnSpec, spec_from_probe
```

（`_flatten` は値配列を返す実データ操作であり `column_names` の責務外なので**そのまま残す**。
順序一致は Task 1 のテストが固定している。）

- [ ] **Step 4: 既存ローダーテスト全通過を確認**

Run: `uv run pytest tests/core/loaders/ tests/test_loaders.py -q`
Expected: PASS（LD-01〜14 の挙動不変）

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/core/loaders/mdf_loader.py tests/core/loaders/test_column_names.py
git commit -m "refactor(core): _leaf_column_count を ColumnSpec 上へ (規則の二重実装を解消)"
```

---

## Task 4: offset overlay を O(offset信号) 化

`_signal_map` が offset 有効時に base map 全体（264k）を走査して dict を作り直すのをやめる。
**遅延解決 Mapping（Task 6）の前提**であり、単体でも perf 改善。

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py:1588-1611`
- Test: `tests/gui/viewmodels/test_signal_map_overlay.py`（新規）

**Interfaces:**
- Produces: `_signal_map()` は offset 有効時、**offset を持つキーだけ**を上書きする overlay Mapping を返す（base は参照のまま）。

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/viewmodels/test_signal_map_overlay.py`:

```python
"""offset overlay が O(loaded) でなく O(offset信号) であることを固定する。"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from valisync.core.models import Signal


class _CountingMap(Mapping):
    """items()/__iter__ が呼ばれたら記録する base map スタブ."""

    def __init__(self, data: dict[str, Signal]) -> None:
        self._data = data
        self.full_scans = 0

    def __getitem__(self, k: str) -> Signal:
        return self._data[k]

    def __iter__(self):  # type: ignore[no-untyped-def]
        self.full_scans += 1
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def _sig(name: str) -> Signal:
    ts = np.arange(3, dtype=np.float64)
    return Signal(
        name=name, timestamps=ts, values=np.zeros(3),
        file_format="MDF4", bus_type="", source_file="/x.mf4",
    )


def test_offset_overlay_does_not_scan_the_whole_base_map(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from valisync.gui.viewmodels import graph_panel_vm as mod

    base = _CountingMap({f"g::s{i}": _sig(f"g::s{i}") for i in range(500)})
    vm = mod.GraphPanelVM.__new__(mod.GraphPanelVM)  # 生成コストを避けた最小組立て
    vm._session = type("S", (), {
        "signal_map": staticmethod(lambda: base),
        "apply_offset": staticmethod(lambda sig, file_offset=0.0, signal_offset=0.0: sig),
    })()
    vm._file_offsets = {"g": 1.0}
    vm._signal_offsets = {}

    result = vm._signal_map()
    assert result["g::s3"] is not None  # ルックアップは通る
    assert base.full_scans == 0  # base 全走査をしていない
```

> 実装者へ: `GraphPanelVM` の実コンストラクタが重い場合は上記のように `__new__`＋必要属性の
> 直接設定で最小組立てしてよい（このテストは `_signal_map` の走査特性だけを見る）。実際の
> 属性名が異なる場合は現行コードに合わせること。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/viewmodels/test_signal_map_overlay.py -q`
Expected: FAIL（`base.full_scans == 1`）

- [ ] **Step 3: overlay を実装**

`graph_panel_vm.py` の `_signal_map`（1588-1611）を置換:

```python
    def _signal_map(self) -> Mapping[str, Signal]:
        """Return {signal.name: signal} with stored time offsets applied (R14).

        Fast path (no offsets, the norm): return the Session's cached read-only
        map unchanged. With offsets set, wrap it in an overlay that applies
        Session.apply_offset ON LOOKUP for the affected keys only — copying the
        whole 264k-entry base map here was O(loaded) per call, and it is also
        structurally incompatible with a lazily-resolving base map (E-1).
        """
        base = self._session.signal_map()
        if not self._file_offsets and not self._signal_offsets:
            return base
        return _OffsetOverlay(
            base, dict(self._file_offsets), dict(self._signal_offsets), self._session
        )
```

同ファイル末尾（クラス外）に追加:

```python
class _OffsetOverlay(Mapping[str, Signal]):
    """base map の上に時間オフセットをルックアップ時適用する読み取り専用ビュー.

    base を丸ごとコピーしないので O(offset信号)。列キーを遅延解決する base map
    (E-1) とも両立する — 列挙は base に委譲し、鋳造を誘発しない。
    """

    __slots__ = ("_base", "_file_offsets", "_signal_offsets", "_session", "_cache")

    def __init__(
        self,
        base: Mapping[str, Signal],
        file_offsets: dict[str, float],
        signal_offsets: dict[str, float],
        session: Session,
    ) -> None:
        self._base = base
        self._file_offsets = file_offsets
        self._signal_offsets = signal_offsets
        self._session = session
        self._cache: dict[str, Signal] = {}

    def _offset_for(self, key: str) -> tuple[float, float]:
        group_key = key.split(KEY_SEPARATOR, 1)[0]
        return (self._file_offsets.get(group_key, 0.0), self._signal_offsets.get(key, 0.0))

    def __getitem__(self, key: str) -> Signal:
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        sig = self._base[key]
        file_off, sig_off = self._offset_for(key)
        if file_off or sig_off:
            sig = self._session.apply_offset(
                sig, file_offset=file_off, signal_offset=sig_off
            )
        self._cache[key] = sig
        return sig

    def __iter__(self) -> Iterator[str]:
        return iter(self._base)

    def __len__(self) -> int:
        return len(self._base)
```

必要な import（ファイル冒頭に無ければ追加）: `from collections.abc import Iterator, Mapping`、
`KEY_SEPARATOR`（既存の import 元に合わせる）、`Session`（型のみなら TYPE_CHECKING 下）。

- [ ] **Step 4: 通ることを確認 + 既存 offset テスト全通過**

Run: `uv run pytest tests/gui/viewmodels/test_signal_map_overlay.py tests/gui/ -q`
Expected: PASS（offset 適用の既存挙動が不変であること）

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/viewmodels/test_signal_map_overlay.py
git commit -m "perf(gui): offset overlay を O(offset信号) 化 (base 全走査を廃止・遅延 Mapping の前提)"
```

---

## Task 5: `resolve()` と per-group 副テーブル（**ローダーはまだ展開する**）

列キーを要求時に鋳造する解決器を入れる。ローダーは未変更なので**全キーが既存 map で解決でき**、
解決器はテストからのみ exercise される。ここで**キャッシュ寿命**（Critical 1）を固定する。

**Files:**
- Modify: `src/valisync/core/loaders/signal_group_manager.py`
- Modify: `src/valisync/core/session.py`（`resolve_signal` 委譲・`RemovalResult.removed_columns`）
- Test: `tests/core/loaders/test_resolver.py`（新規・**非 demo-gate**）

**Interfaces:**
- Consumes: `parse_leaf`, `ColumnSpec`（Task 1/2）
- Produces:
  - `SignalGroupManager.resolve(key: str) -> Signal | None`
  - `SignalGroupManager.resolved_keys(group_key: str) -> frozenset[str]`（**鋳造を誘発しない introspection**）
  - `SignalGroupManager.mint_count` — 鋳造回数（テスト用カウンタ）
  - `Session.resolve_signal(key: str) -> Signal | None`
  - `RemovalResult.removed_columns: tuple[Signal, ...]`（既定 `()`）

- [ ] **Step 1: 失敗テストを書く（キャッシュ寿命が本丸）**

`tests/core/loaders/test_resolver.py`:

```python
"""列キー解決器と per-group 副テーブルの寿命 (Critical 1 の回帰ガード)。

無関係なファイルの load/remove で鋳造済み列 Signal が捨てられると、次の描画で
フルチャンネル再読み (実測 0.73-1.18 s/列) が走る純粋な回帰になる。
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup


def _sig(name: str) -> Signal:
    ts = np.arange(3, dtype=np.float64)
    return Signal(
        name=name, timestamps=ts, values=np.zeros(3),
        file_format="MDF4", bus_type="", source_file="/x.mf4",
    )


def _group(*names: str) -> SignalGroup:
    return SignalGroup(
        signals=tuple(_sig(n) for n in names),
        source_path=Path("/x.mf4").resolve(),
        file_format="MDF4",
        loaded_at=datetime.datetime.now(),
    )


def test_resolve_returns_existing_signal_without_minting() -> None:
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))
    got = mgr.resolve(f"{key}::Mat[0]")
    assert got is not None
    assert mgr.mint_count == 0  # 既存キーは鋳造しない


def test_resolve_returns_none_for_unloaded_group() -> None:
    mgr = SignalGroupManager()
    assert mgr.resolve("mf4_9::Nope") is None


def test_resolved_table_survives_unrelated_add_and_remove() -> None:
    # Critical 1: 無関係なファイルの load/remove で副テーブルを捨ててはならない
    mgr = SignalGroupManager()
    k1 = mgr.add(_group("Mat[0]"))
    first = mgr.resolve(f"{k1}::Mat[0]")
    k2 = mgr.add(_group("Other"))          # 2 ファイル目ロード相当
    assert mgr.resolve(f"{k1}::Mat[0]") is first  # 同一オブジェクト
    mgr.remove(k2)                          # 2 ファイル目 unload 相当
    assert mgr.resolve(f"{k1}::Mat[0]") is first


def test_removing_own_group_drops_its_resolved_table() -> None:
    mgr = SignalGroupManager()
    k1 = mgr.add(_group("Mat[0]"))
    mgr.resolve(f"{k1}::Mat[0]")
    assert mgr.resolved_keys(k1) != frozenset()
    mgr.remove(k1)
    assert mgr.resolve(f"{k1}::Mat[0]") is None


def test_resolved_keys_does_not_mint() -> None:
    mgr = SignalGroupManager()
    k1 = mgr.add(_group("Mat[0]"))
    before = mgr.mint_count
    _ = mgr.resolved_keys(k1)
    assert mgr.mint_count == before
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_resolver.py -q`
Expected: FAIL（`resolve` / `resolved_keys` / `mint_count` 未定義）

- [ ] **Step 3: `SignalGroupManager` に解決器と副テーブルを実装**

`signal_group_manager.py` の `__init__` に追加:

```python
        # 鋳造した列 Signal (E-1)。**_invalidate_namespaced() に相乗りさせない** —
        # 相乗りすると 2 ファイル目のロードごとに全プロット列がフルチャンネル再読み
        # (実測 0.73-1.18 s/列) になる純粋な回帰。remove(key) でだけ切り離す。
        self._resolved_by_key: dict[str, dict[str, Signal]] = {}
        self.mint_count = 0
```

同クラスに追加:

```python
    def resolve(self, key: str) -> Signal | None:
        """名前空間つきキーを Signal へ解決する (無ければ列として鋳造を試みる)。

        グループ未ロードなら None (正当な不在)。ローダーが列を展開している間は
        全キーが既存 map で解決でき、鋳造経路はテストからのみ exercise される。
        """
        self._ensure_namespaced()
        assert self._namespaced_map is not None
        hit = self._namespaced_map.get(key)
        if hit is not None:
            return hit
        group_key = key.split(KEY_SEPARATOR, 1)[0]
        if group_key not in self._groups:
            return None
        table = self._resolved_by_key.setdefault(group_key, {})
        cached = table.get(key)
        if cached is not None:
            return cached
        minted = self._mint_column(group_key, key)
        if minted is None:
            return None
        table[key] = minted
        self.mint_count += 1
        return minted

    def resolved_keys(self, group_key: str) -> frozenset[str]:
        """鋳造済み列キーの集合 (鋳造を誘発しない introspection)."""
        return frozenset(self._resolved_by_key.get(group_key, {}))

    def _mint_column(self, group_key: str, key: str) -> Signal | None:
        """列キーから Signal を鋳造する。E-1 では ColumnSpec 未配線のため None。

        E-3 でローダーが per-channel Signal + ColumnSpec を発行したら、ここで
        parse_leaf → LazyMdfValues(selector) → Signal 構築を行う。
        """
        return None
```

`remove()` に 1 行追加（`self._invalidate_namespaced()` の直前）:

```python
        self._resolved_by_key.pop(key, None)
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/core/loaders/test_resolver.py -q`
Expected: PASS（5 件）

- [ ] **Step 5: sabotage で寿命ガードの弁別力を確認**

`_invalidate_namespaced()` に `self._resolved_by_key.clear()` を一時的に足し、
`test_resolved_table_survives_unrelated_add_and_remove` が **FAIL** することを確認して戻す。
結果を報告に記す。

- [ ] **Step 6: `Session` に委譲と `removed_columns` を追加**

`session.py` の `RemovalResult` に追加:

```python
    removed_columns: tuple[Signal, ...] = ()
```

`Session` に追加（`group_signals` の近く）:

```python
    def resolve_signal(self, key: str) -> Signal | None:
        """名前空間つきキーを Signal へ解決する (列キーは要求時に鋳造・E-1)."""
        return self._groups.resolve(key)
```

`remove_group` の成功経路で、`SignalGroupManager.remove` が返す副テーブルを
`RemovalResult(removed_columns=...)` へ載せる。そのため `SignalGroupManager.remove` を
`pop` してから返す形に変える:

```python
    def remove(self, key: str) -> tuple[SignalGroup, tuple[Signal, ...]]:
        """グループと、そのグループで鋳造済みの列 Signal を取り出して返す。

        列 Signal は SignalGroup.signals の外に居るため、ここで返さないと
        TeardownService の会計・解放から漏れる。
        """
        try:
            group = self._groups.pop(key)
        except KeyError:
            raise KeyError(f"no Signal_Group registered under key: {key!r}") from None
        columns = tuple(self._resolved_by_key.pop(key, {}).values())
        self._invalidate_namespaced()
        return group, columns
```

`session.py` の `remove_group` 内の `self._groups.remove(key)` 呼び出しを
`group, columns = self._groups.remove(key)` に合わせて更新し、`RemovalResult` へ渡す。

- [ ] **Step 7: 既存の remove 系テストを含めて通ることを確認**

Run: `uv run pytest tests/core/ tests/test_session.py tests/gui/ -q`
Expected: PASS（`remove` の戻り値変更に追随できているか。呼び出し元は `session.py` のみのはず — grep で確認する）

- [ ] **Step 8: ゲート＋コミット**

```bash
git add src/valisync/core/loaders/signal_group_manager.py src/valisync/core/session.py tests/core/loaders/test_resolver.py
git commit -m "feat(core): 列キー解決器と per-group 副テーブル (Critical 1 の寿命ガードつき)"
```

---

## Task 6: 遅延解決 `signal_map()`（非対称 Mapping）

`signal_map()` を「**列挙は物理のみ・`[]`/`get`/`in` は列も解決**」する Mapping にする。
これが約 20 箇所の `sig_map.get()` を無改造にする要。

**Files:**
- Modify: `src/valisync/core/loaders/signal_group_manager.py`
- Test: `tests/core/loaders/test_resolver.py`

**Interfaces:**
- Consumes: `resolve()`（Task 5）
- Produces: `signal_map()` は `Mapping[str, Signal]` を返す（`get`/`__getitem__`/`__contains__` が解決器へフォールバック・`__iter__`/`__len__` は既存マップのみ）

- [ ] **Step 1: 失敗テストを書く**

`tests/core/loaders/test_resolver.py` に追記:

```python
def test_signal_map_lookup_falls_through_to_resolver() -> None:
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))
    m = mgr.signal_map()
    assert m.get(f"{key}::Mat[0]") is not None
    assert m.get(f"{key}::Nope") is None       # 解決不能は None (例外にしない)
    assert m.get("mf4_9::Nope") is None        # 未ロードグループも None


def test_signal_map_enumeration_does_not_mint() -> None:
    # 列挙は物理のみ: dict(m) が 330k 列を鋳造したら 390 MB を再導入してしまう
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))
    m = mgr.signal_map()
    before = mgr.mint_count
    assert list(m) == [f"{key}::Mat[0]"]
    assert len(m) == 1
    assert mgr.mint_count == before


def test_signal_map_is_read_only() -> None:
    mgr = SignalGroupManager()
    mgr.add(_group("Mat[0]"))
    m = mgr.signal_map()
    assert not hasattr(m, "__setitem__") or isinstance(m, Mapping)
```

冒頭の import に `from collections.abc import Mapping` を追加。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_resolver.py -q`
Expected: FAIL（`m.get(...::Nope)` が KeyError 相当、または解決器を通らない）

- [ ] **Step 3: 非対称 Mapping を実装**

`signal_group_manager.py` の `signal_map()` を置換:

```python
    def signal_map(self) -> Mapping[str, Signal]:
        """読み取り専用 ``{namespaced_name: Signal}`` ビュー (FU-08 でキャッシュ)。

        **非対称 Mapping** (E-1・意図的逸脱): ``[]``/``get``/``in`` は列キーを解決器
        経由で鋳造しうるが、``__iter__``/``len`` は既存 (物理) キーのみを返す。全論理
        キーの列挙は 330k 列を鋳造して ~390 MB を再導入するため提供しない —
        ``dict(signal_map())`` は使ってはならない。
        """
        self._ensure_namespaced()
        assert self._namespaced_map is not None
        return _ResolvingMap(self._namespaced_map, self.resolve)
```

ファイル末尾に追加:

```python
class _ResolvingMap(Mapping[str, Signal]):
    """既存マップ + 未知キーの解決器フォールバック (列挙は既存キーのみ)."""

    __slots__ = ("_base", "_resolve")

    def __init__(
        self, base: dict[str, Signal], resolve: Callable[[str], Signal | None]
    ) -> None:
        self._base = base
        self._resolve = resolve

    def __getitem__(self, key: str) -> Signal:
        hit = self._base.get(key)
        if hit is not None:
            return hit
        got = self._resolve(key)
        if got is None:
            raise KeyError(key)
        return got

    def get(self, key: str, default: Signal | None = None) -> Signal | None:  # type: ignore[override]
        hit = self._base.get(key)
        if hit is not None:
            return hit
        got = self._resolve(key)
        return default if got is None else got

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return key in self._base or self._resolve(key) is not None

    def __iter__(self) -> Iterator[str]:
        return iter(self._base)

    def __len__(self) -> int:
        return len(self._base)
```

import に `from collections.abc import Callable, Iterator, Mapping` を追加。

- [ ] **Step 4: 通ることを確認 + 全既存テスト**

Run: `uv run pytest tests/core/ tests/gui/ tests/test_session.py tests/test_loaders.py -q`
Expected: PASS（`signal_map()` の戻り型が `MappingProxyType` から変わるため、`dict` 前提の
呼び出し元がいないかを実行で確認する。落ちた箇所は**呼び出し元を Mapping 前提へ直す**。）

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/core/loaders/signal_group_manager.py tests/core/loaders/test_resolver.py
git commit -m "feat(core): signal_map を非対称 Mapping 化 (ルックアップは列解決・列挙は物理のみ)"
```

---

## Self-Review（プラン著者チェック）

- **Spec coverage（E-0/E-1）**: 命名文法抽出＋dtype 認識＝Task 1／`parse_leaf` 最長一致＋asammdf 往復＝Task 2／二重実装の解消＝Task 3／offset overlay O(n)＝Task 4／resolver＋per-group 副テーブル＋`removed_columns`＝Task 5／遅延解決 Mapping＋非鋳造 introspection＝Task 6。**E-1 の 3 値契約の診断化は E-2 で GUI 側の `_diagnostic_sink` と繋ぐ**（E-1 時点では解決器が None を返すだけで、鋳造経路自体が未配線のため診断の出しどころが無い）ことを明記した。
- **死蔵コード整理＝Task 0**（ユーザー決定で本プランに含める）。production 参照ゼロを実測で確認済み。実 D&D の被覆は `tests/realgui/test_signal_dnd_realclick.py`（実 QDrag 5 本）が押さえており、削除しても被覆は落ちない — むしろ `test_dnd_workflow.py` が production に存在しないモデルを検証していた**偽の保証が 1 つ消える**。E-3 の「公開 API の意味縮小」も 1 件不要になる。
- **型整合**: `ColumnSpec`（kind/dtype_kind/axis_len/child/fields）・`spec_from_probe`・`leaf_names`・`leaf_count`・`parse_leaf(display_key, specs)`・`resolve`・`resolved_keys`・`mint_count`・`removed_columns` は全 Task で一貫。
- **Placeholder**: 無し。Task 4 のテストは実コンストラクタが重い場合の最小組立てを明示的に許可している（実属性名は現行コードに合わせる指示つき）。

> **実装上の注意（増分A の教訓）**: テストは**変異耐性**を持たせること。Task 2 Step 7 と
> Task 5 Step 5 は sabotage による honest-RED の実証を**必須ステップ**にしてある。
