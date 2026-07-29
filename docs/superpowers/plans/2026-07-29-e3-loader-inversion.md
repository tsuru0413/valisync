# E-3 ローダー反転（物理チャンネル 1 本＝Signal 1 個）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MDF ローダーが発行する `Signal` を「1 列につき 1 個」（prod 264,004 個）から「1 物理チャンネルにつき 1 個」（4,324 個）へ反転し、列は既存の解決器が要求時に鋳造する形にして core メモリ 590 MB → ~310 MB（USS +281 MiB → +15 MiB）を着地させる。

**Architecture:** E-1/E-2 が敷いた解決器（`SignalGroupManager.resolve()` ＋ per-group 副テーブル `_resolved_by_key`）と非対称 Mapping（`Session.signal_map()` はルックアップで列を解決し、列挙は物理キーのみ）は**既に完成しており、`_mint_column` が hard-return `None` のため使われていない**。本プランはその鋳造経路を実装して有効化し、列挙に依存していた消費者（チャンネルブラウザ・エクスポートダイアログ・比較オーバーレイ・信号プレビュー・`source_info`）を `ColumnRecord` 表と解決器へ移し替える。反転は T6 で一度だけ行い、その前後を独立にレビュー可能なタスクへ分割する。

**Tech Stack:** Python 3.13 / uv / PySide6 6.x / pyqtgraph / asammdf 8.8.22 / numpy / pytest ＋ pytest-qt

## Global Constraints

- 作業ディレクトリ `D:/Programming/projects/valisync`、ブランチ `feature/e3-loader-inversion`。**main へ直接コミットしない**。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` すべて exit 0。
- 新規テストは **`demo_data/` に依存させない**（gitignore 済み・CI に生成ステップが無く module-level skipif で丸ごと skip される）。fixture は `tests/mdf4_helpers.write_mdf4` ＋ `tmp_path`、または各タスクが定義する専用 fixture。
- **遅延契約**: 未展開 `Signal` の `sig.values` を読まない。`array_if_materialized()` は materialize しない。判定に `sig.values.ndim` を使わない（チャンネル全読み＝本増分の勝利を自ら潰す）。
- **既存 assert を弱めない**。既存契約を保存: ハンドル close の全経路／teardown の三軸ペーシング（64 MiB・8,000 信号・8ms デッドライン・クロックは 32 信号ごと）／会計の identity dedup／`SampleReadError` の集中 degrade。
- **各タスクは sabotage 必須**（実装を壊すと当該テストが RED になることを実証し、結果を報告に記す）。このブランチ系列は「実装が効いていることを証明できないテスト」を過去 6 回踏んでいる。
- **LD-14 リーフ名の文法は永続キー**（`Name.field` / `Name[i]` / `Name[i][j]` / `Name.field[i]`）。変更は全保存の無言リネームになる。
- `parse_leaf` へ渡す Mapping は **生チャンネル名キー**（LD-08 dedup 前）。dedup 済み表示名を渡すと `W[1][2]` の `[1]` を W 自身の配列インデックスとして消費し、解決不能または**別チャンネルの列を返す**。

## 確定事項（設計 spec の「E-3 着手時の確定事項」節・全て遵守）

| # | 内容 |
|---|---|
| S1 | `ChannelBrowserVM` の列ソースを `ColumnRecord` 由来へ（spec の E-3 行が名指していない必須項目）。無修正で反転すると `Mat[0]`/`Pos.x` が UI から完全消失し、2-D 親がドラッグ可能になって `sorted_view()` の `astype(float64)` が 8 倍膨張して恒久キャッシュされる |
| S2 | 数値ゲートをリーフ単位へ（`leaf_count(spec) > 0`）。構造化チャンネルの親 probe は `dtype.kind == "V"` なので、現行ゲートを親に当てると**全構造化チャンネルが消滅**する。dtype-blind の `_all_leaf_count` は「N 本に展開」info 診断の byte-identical 維持のため残す |
| S3 | 全数ラウンドトリップ・オラクルを**反転より前**に置く。独立参照は eager ローダーではなく asammdf `select` ＋ `_flatten` の直叩き（`_flatten` は `LazyMdfValues.array()` が使い続けるため反転を跨いで生き残る） |
| U1 | `ExportCsvDialog` は**遅延展開（QTreeWidget 維持）**。親＝物理チャンネル行にプレースホルダ子、`itemExpanded` で列を合成、`expandAll()` 廃止、チェック状態は VM 側の集合 |
| U2 | `source_info.n_channels` は**列数を維持**（264,004）。ChannelBrowser ヘッダと同一単位 |
| C-a | 物理チャンネル行は**チェック不可の三態コンテナ**（部分チェック表示のみ） |
| C-b | 「すべて選択」は**鋳造しない** — 選択は列キーの集合、キーは `ColumnSpec` から名前だけ生成 |
| C-c | `reference_overlay` のマッチは**列レベル**（`already_present` が列キーで作られているため物理レベルだと重複追加になる） |
| C-d | 2-D 親の拒否は **core**（`Session.export_csv` / `CsvExporter`）。scripted/realgui の直呼びまで守れる唯一の層 |
| C-e | `mint_count` / `resolved_keys` は `Session` に公開しない（realgui は `session._groups` へ直接触れる先例あり） |
| C-f | `W[0]`→`W[1]` は**意図的リネーム・移行なし**として test-lock |
| C-g | `_resolved_by_key` の LRU は E-3 では入れない（E-4） |
| C-h | 幅閾値の二重経路（安全弁）は**採らない** |
| C-i | 1024 ガード退役は**反転の後** |

## 反転より前に着地していなければならないもの

```
[T0] 全数ラウンドトリップ・オラクル   ← 独立参照は eager 実装が同居する間だけ作れる
  ↓
[T1] ColumnRecord 表 ＋ 共有 API      ← 生名キー ⇄ dedup 済み表示名 の橋渡し。T2 の前提
  ↓
[T2] _mint_column 実装                ← production 無影響（_namespaced_map が先に当たる）
  ↓
[T3] teardown 配線  ┐
[T4] ブラウザ列ソース ├ 3 つとも反転**前**に単独 merge 可（両 fixture GREEN / removed_columns が空）
[T5] エクスポート遅延展開 ┘
  ↓
[T6] ★反転★
  ↓
[T7] 消費者回復 ＋ 2-D 親の core 拒否
  ↓
[T8] 1024 ガード退役
  ↓
[T9] 計測器改修 ＋ 実測 ＋ realgui ①ゲート
```

**T3 が硬い blocker である理由**: T2 が非 `None` を返した瞬間、列を 1 本でもプロットしたファイルの unload が production で `AssertionError` を投げる。しかも raise は `self._releasing[key] = name` の**後**・`enqueue` の**前**なので `result` がスコープアウトし、**~10 GB が GUI スレッドで同期解放**される（FU-16 回帰）。excepthook は `SampleReadError` 以外を前 hook へ委譲するため**ユーザーには無音でフリーズだけ**が起きる。

## Task 1 が新設する共有 API（全タスクが依存・シグネチャ厳守）

```python
# src/valisync/core/loaders/column_names.py
@dataclass(frozen=True, slots=True)
class ColumnRecord:
    """物理チャンネル 1 本の鋳造に必要な最小情報。"""
    raw_base_name: str   # asammdf のチャンネル名 (LD-08 dedup 前の生名)
    group_index: int
    channel_index: int
    spec: ColumnSpec

# src/valisync/core/loaders/signal_group_manager.py
def column_records(self, group_key: str) -> Mapping[str, ColumnRecord]: ...
    # キー = LD-08 dedup 済みの表示名 (= metadata["physical_channel"] と同一キー空間)
def column_names_of(self, group_key: str, display_name: str) -> tuple[str, ...]: ...
    # 数値リーフの表示名タプル。スカラーは (display_name,) を返す
def total_column_count(self, group_key: str) -> int: ...
    # グループの数値列総数 (U2 の n_channels と ChannelBrowser ヘッダ母数)
def has_column(self, group_key: str, display_name: str) -> bool: ...
    # *display_name* がこのグループの **列** として実在するか (鋳造しない存在判定)。
    # スカラー/列キーは True、配列・構造体の親 (容器) と未知名は False

# src/valisync/core/session.py — GUI 向け pass-through
def column_names_of(self, key: str, display_name: str) -> tuple[str, ...]: ...
def total_column_count(self, key: str) -> int: ...
def has_column(self, key: str, display_name: str) -> bool: ...
```

---

### Task 0: 全数ラウンドトリップ・オラクル（反転より前に着地させる）

**Files:**
- Create: `tests/core/loaders/test_column_roundtrip.py`
- Modify: （なし — production コードは一切触らない）
- Test: `tests/core/loaders/test_column_roundtrip.py`

**Interfaces:**
- Consumes（すべて既存・T1 以降の新 API には依存しない）:
  - `valisync.core.loaders.mdf_loader._flatten(name: str, arr: np.ndarray) -> list[tuple[str, np.ndarray]]` — 反転後も `LazyMdfValues.array()` が遅延 import して使い続ける（`sample_source.py:164-165`）ため、**反転を跨いで生き残る唯一のオラクル**。
  - `valisync.core.loaders.column_names.spec_from_probe(arr) -> ColumnSpec` / `leaf_names(base: str, spec: ColumnSpec) -> Iterator[str]` / `parse_leaf(display_key: str, specs: Mapping[str, ColumnSpec]) -> tuple[str, ColumnSpec] | None`
  - `valisync.core.session.Session.load(file_path) -> LoadOutcome`（`.key`）/ `Session.resolve_signal(key: str) -> Signal | None` / `Session.remove_group(key: str) -> RemovalResult`
  - asammdf: `MDF.virtual_groups` / `MDF.included_channels(gi)` / `MDF.select(entries, raw=False, ignore_value2text_conversions=True, copy_master=False)`
- Produces（後続タスクが依存する）:
  - `tests/core/loaders/test_column_roundtrip.py` — **T6（反転）の合否判定そのもの**。T6 はこのファイルを**1 行も書き換えずに GREEN** にしなければならない。書き換えが必要になったら、それは「反転で契約が変わった」ことの検出であり、変更前にユーザー確認が要る。
  - モジュール内ヘルパ（T6/T7 が再利用してよい）:
    - `_write_roundtrip_mf4(tmp_path: Path) -> Path` — 全腕を 1 ファイルに詰めた実 mf4 を書く
    - `_oracle_columns(path: Path) -> dict[str, _Col]` — `{列キー: 独立オラクル}`
    - `_numeric(columns: dict[str, _Col]) -> dict[str, _Col]` — 数値リーフのみ
    - `_Col`（frozen dataclass: `values` / `timestamps` / `unit` / `comment` / `virtual_group` / `physical` / `deduplicated` / `exploded`）
    - `_Loaded`（frozen dataclass: `session` / `key` / `columns`・メソッド `resolve(column_key: str) -> Signal | None`）と module-scope fixture `loaded`

- [ ] **Step 1: 失敗テストを書く**

`tests/core/loaders/test_column_roundtrip.py` を新規作成する（全文。実測で GREEN・ruff check/format 通過を確認済み）。

**fixture の実測事実（この 3 つは asammdf の書き出し挙動に依存するので先に確定させた）**:
数値列キーは **29 本**、非数値リーフは 1 本（`Mix.tag`）、仮想グループは **10 個**。
`Radar.ObjList` を構造化サブ配列で書くと、asammdf は親チャンネルに加えて
**要素チャンネル** `Radar.ObjList[0..2]` と `Radar.ObjList.dx[0..2]` を同一グループへ
実在させる（`included_channels` に現れる 1-D の実チャンネル。展開列ではない）ため、
`test_oracle_covers_every_naming_arm` と `test_literal_values_pin_the_key_to_column_mapping`
の `Radar.ObjList[1]` の腕はこの実チャンネルを指す。母数は `>=` の下限ではなく
**全数一致**で凍結する — 下限だと「腕が 1 つ静かに消えた」を隠す。

```python
"""列キー ↔ 列データの全数ラウンドトリップ・オラクル (E-3 反転より前に固定する)。

**なぜ独立参照を eager ローダーに置かないか**: E-3 でローダーは物理チャンネル 1 本に
つき Signal 1 個しか発行しなくなる。eager 展開の結果を参照にすると、参照そのものが
反転で消えてテストが書き換え対象になる。代わりに asammdf の ``select`` と ``_flatten``
の直叩きを参照に置く — ``_flatten`` は反転後も ``LazyMdfValues.array()`` が使い続ける
(``sample_source.py`` の遅延 import) ため、**反転を跨いで同一のオラクル**になる。

**二重名の契約**は間接に固定される: 表示キーは LD-08 dedup 済み名から、selector は生
チャンネル名から導く。前者を誤ると ``dup[0]``/``dup[1]`` が解決できず、後者を誤ると
遅延読みが ``SampleReadError`` になるので、どちらの取り違えも本モジュールが RED にする。

**反転前は「鋳造テストとしては」vacuous** である: ``_mint_column`` が None を返す現状、
``resolve()`` は既存の ``_namespaced_map`` (eager 展開済み列) が答えている。それは想定内で、
本モジュールの反転前の役割は「反転後に満たすべき全数の期待値を、実装非依存の形で先に
凍結する」こと。鋳造経路の honest-RED は反転タスク (T6) 側で sabotage により実証する。

**構造的な弱点 (記録)**: ``Name[i][j]`` だけは asammdf の public write API で往復できない
(``tests/mdf4_helpers.py`` の 3-D 不可の注記と同根)。(2,3) サブ配列フィールドを書いても
読み戻しは (6,) へ潰れる — 本モジュールはその実測自体をテストで固定したうえで、
``[i][j]`` の腕のみ合成 ndarray で確認する。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from asammdf import MDF
from asammdf import Signal as ASignal

from valisync.core.loaders.column_names import leaf_names, parse_leaf, spec_from_probe
from valisync.core.loaders.mdf_loader import _flatten
from valisync.core.models import Signal
from valisync.core.session import Session

_TS = np.array([0.0, 0.1, 0.2, 0.3])
_ARRAY_CHANNEL = "Radar.ObjList"  # フィールド名が '.' を含む CABLOCK 配列チャンネル
_AXIS_LEN = 3
# 遅延読み (LazyMdfValues.array()) と同一の正準オプション。オラクルが production と
# 別の側 (raw=True 等) を読むと、値の比較が「両方同じだけ壊れている」を見逃す。
_SELECT_OPTIONS: dict[str, Any] = {
    "raw": False,
    "ignore_value2text_conversions": True,
    "copy_master": False,
}
# 実測で凍結した数値列キーの全数 (29 本・sorted 順)。下限 (>=) では「腕が 1 つ
# 消えた」を隠すので全数一致で固定する。末尾寄りの Radar.ObjList[i] /
# Radar.ObjList.dx[i] は展開列ではなく、asammdf が CABLOCK 配列に対して同一
# グループへ実在させる **要素チャンネル** (1-D の実チャンネル)。
_EXPECTED_COLUMN_KEYS = [
    "Mat[0]",
    "Mat[1]",
    "Mat[2]",
    "Mix.x",
    "Nest.g[0]",
    "Nest.g[1]",
    "Nest.g[2]",
    "Nest.g[3]",
    "Nest.g[4]",
    "Nest.g[5]",
    "Pos.xa",
    "Pos.xb",
    "Radar.ObjList.Radar.ObjList.dx[0]",
    "Radar.ObjList.Radar.ObjList.dx[1]",
    "Radar.ObjList.Radar.ObjList.dx[2]",
    "Radar.ObjList.Radar.ObjList[0]",
    "Radar.ObjList.Radar.ObjList[1]",
    "Radar.ObjList.Radar.ObjList[2]",
    "Radar.ObjList.dx[0]",
    "Radar.ObjList.dx[1]",
    "Radar.ObjList.dx[2]",
    "Radar.ObjList[0]",
    "Radar.ObjList[1]",
    "Radar.ObjList[2]",
    "Scaled",
    "ShA",
    "ShB",
    "dup[0]",
    "dup[1]",
]


def _write_roundtrip_mf4(tmp_path: Path) -> Path:
    """全腕を 1 ファイルに詰めた fixture を asammdf で実書き出しする。

    ``tests/mdf4_helpers`` の既存ヘルパを使わないのは、この fixture が
    (a) 名前が意図的に衝突する複数チャンネルを **同一ファイル** に持つ必要があり、
    (b) 反転タスクが触る約 20 の fixture サイトと寿命を共有したくないため。

    追加順は契約の一部: 2-D ``Mat`` の**後に** 1-D ``Mat[0]`` を置く。反転前の
    ``_namespaced_map`` は last-wins なので、この順序でのみ「実チャンネルが勝つ」
    (反転後は最長一致で構造的に勝つ) 期待値が両側で一致する。
    """
    from asammdf.blocks.conversion_utils import from_dict

    n = len(_TS)
    array_samples = np.zeros(
        n,
        dtype=np.dtype(
            [
                (_ARRAY_CHANNEL, "<u1", (_AXIS_LEN,)),
                (f"{_ARRAY_CHANNEL}.dx", "<f8", (_AXIS_LEN,)),
            ]
        ),
    )
    for k in range(n):
        for i in range(_AXIS_LEN):
            array_samples[_ARRAY_CHANNEL][k, i] = 10 * k + i + 1
            array_samples[f"{_ARRAY_CHANNEL}.dx"][k, i] = 100 * (i + 1) + k

    nested = np.zeros(n, dtype=np.dtype([("g", "<u1", (2, 3))]))
    for k in range(n):
        nested["g"][k] = np.arange(6, dtype=np.uint8).reshape(2, 3) + 10 * k

    mdf = MDF(version="4.10")
    try:
        # Name[i]: 2-D uint8 (列 i = [i, 10+i, 20+i, 30+i])
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]],
                        dtype=np.uint8,
                    ),
                    timestamps=_TS,
                    name="Mat",
                    unit="mm",
                )
            ]
        )
        # Mat[0] 衝突: 上の第 0 列と字面が同じ 1-D 実チャンネル (dtype も unit も別物)
        mdf.append(
            [
                ASignal(
                    samples=np.array([7.0, 8.0, 9.0, 10.0]),
                    timestamps=_TS,
                    name="Mat[0]",
                    unit="deg",
                )
            ]
        )
        # Name.field: 数値のみの構造化
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0)],
                        dtype=[("xa", "<f8"), ("xb", "<f8")],
                    ),
                    timestamps=_TS,
                    name="Pos",
                    unit="m",
                )
            ]
        )
        # 非数値混在: x は数値・tag は S2 (列キー空間に載ってはならない)
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [(1.0, b"ab"), (2.0, b"cd"), (3.0, b"ef"), (4.0, b"gh")],
                        dtype=[("x", "<f8"), ("tag", "S2")],
                    ),
                    timestamps=_TS,
                    name="Mix",
                )
            ]
        )
        # LD-08: 同名チャンネル 2 本 (別グループ = 別 master)
        for base in (100.0, 200.0):
            mdf.append(
                [
                    ASignal(
                        samples=np.array([base, base + 1, base + 2, base + 3]),
                        timestamps=_TS,
                        name="dup",
                        unit="V",
                    )
                ]
            )
        # Name.field[i]: フィールド名が '.' を含む配列チャンネル
        # (要素チャンネル Radar.ObjList[i] が同グループに併存する)
        mdf.append([ASignal(array_samples, _TS, name=_ARRAY_CHANNEL, unit="m")])
        # サブ配列 (2,3) — 読み戻しで (6,) に潰れることの実測用
        mdf.append([ASignal(nested, _TS, name="Nest")])
        # 線形変換つきスカラー: 非 raw 読み (物理値) と conversion_info の正の対照
        mdf.append(
            [
                ASignal(
                    samples=np.array([0, 7980, -1234, 32767], dtype=np.int16),
                    timestamps=_TS,
                    name="Scaled",
                    unit="km/h",
                    conversion=from_dict({"a": 0.01, "b": 0.0}),
                )
            ]
        )
        # 1 グループに 2 チャンネル: master identity 共有をチャンネル跨ぎで被覆
        mdf.append(
            [
                ASignal(samples=np.arange(4.0), timestamps=_TS, name="ShA"),
                ASignal(samples=np.arange(4.0) * 2.0, timestamps=_TS, name="ShB"),
            ]
        )
        path = tmp_path / "roundtrip.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


@dataclass(frozen=True)
class _Col:
    """列キー 1 本ぶんの独立オラクル (production のローダーを一切経由しない)."""

    values: np.ndarray
    timestamps: np.ndarray
    unit: str
    comment: str
    virtual_group: int
    physical: str  # LD-08 dedup 済みの物理チャンネル表示名
    deduplicated: bool
    exploded: bool


def _oracle_columns(path: Path) -> dict[str, _Col]:
    """asammdf 直叩きで {列キー: オラクル} を作る (production の出力を見ない)。

    列挙は ``included_channels`` (構造化チャンネルの成分と master を除外済み)、
    表示名は LD-08 の dedup 規則、列名は ``_flatten`` — production と同じ規則を
    **独立に組み立てる**。衝突キーは実チャンネル優先 (最長一致と同規則) にするため、
    展開列を先に入れてから 1-D 実チャンネルで上書きする。
    """
    expanded: dict[str, _Col] = {}
    physical: dict[str, _Col] = {}
    with MDF(str(path), time_from_zero=False) as mdf:
        entries: list[tuple[str, int, int, int]] = []
        for vgi in mdf.virtual_groups:
            included = mdf.included_channels(vgi)[vgi]
            entries.extend(
                (mdf.groups[phys_gi].channels[ci].name, phys_gi, ci, vgi)
                for phys_gi, channel_indexes in included.items()
                for ci in channel_indexes
            )
        totals = Counter(name for name, _g, _c, _v in entries)
        seen: Counter[str] = Counter()
        for raw_name, phys_gi, ci, vgi in entries:
            idx = seen[raw_name]
            seen[raw_name] += 1
            deduplicated = totals[raw_name] > 1
            display = f"{raw_name}[{idx}]" if deduplicated else raw_name
            asig = mdf.select([(raw_name, phys_gi, ci)], **_SELECT_OPTIONS)[0]
            leaves = _flatten(display, asig.samples)
            exploded = asig.samples.ndim != 1 or bool(asig.samples.dtype.names)
            target = physical if not exploded else expanded
            for column_key, column in leaves:
                target[column_key] = _Col(
                    # copy_master=False は asammdf 内部を指しうる — MDF を閉じた後も
                    # 参照が生きるようここでコピーする。
                    values=np.array(column),
                    timestamps=np.array(asig.timestamps),
                    unit=asig.unit,
                    comment=asig.comment,
                    virtual_group=vgi,
                    physical=display,
                    deduplicated=deduplicated,
                    exploded=exploded,
                )
    return {**expanded, **physical}


def _numeric(columns: dict[str, _Col]) -> dict[str, _Col]:
    """列キー空間に載る (数値リーフの) 列だけを返す — _flatten は dtype 盲目."""
    return {k: c for k, c in columns.items() if c.values.dtype.kind in "iufb"}


@dataclass(frozen=True)
class _Loaded:
    session: Session
    key: str
    columns: dict[str, _Col]

    def resolve(self, column_key: str) -> Signal | None:
        return self.session.resolve_signal(f"{self.key}::{column_key}")


@pytest.fixture(scope="module")
def loaded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Loaded]:
    path = _write_roundtrip_mf4(tmp_path_factory.mktemp("roundtrip"))
    columns = _oracle_columns(path)
    session = Session()
    key = session.load(path).key
    try:
        yield _Loaded(session=session, key=key, columns=columns)
    finally:
        # 遅延ロードは MDF を開いたまま保持する。閉じないと Windows では
        # tmp_path の後始末がファイルロックで失敗しうる。
        session.remove_group(key)


def test_oracle_covers_every_naming_arm(loaded: _Loaded) -> None:
    """母数と各腕の代表キーを先に固定する (オラクルが空でも通る vacuous 化の防止)."""
    numeric = _numeric(loaded.columns)
    assert sorted(numeric) == _EXPECTED_COLUMN_KEYS, sorted(numeric)  # 全数で凍結
    for column_key in (
        "Mat[1]",  # Name[i]
        "Pos.xa",  # Name.field
        "Nest.g[3]",  # Name.field[i]
        f"{_ARRAY_CHANNEL}.{_ARRAY_CHANNEL}.dx[2]",  # ドット付きフィールドの Name.field[i]
        f"{_ARRAY_CHANNEL}[1]",  # 併存する要素チャンネル (実チャンネル)
        "dup[0]",  # LD-08 dedup
        "dup[1]",
        "Mat[0]",  # Mat[0] 衝突
        "Scaled",  # 変換つきスカラー
        "ShA",  # master 共有グループ
        "ShB",
    ):
        assert column_key in numeric, sorted(numeric)
    # 非数値リーフが実在する (非数値の腕が空集合になっていない)
    assert loaded.columns["Mix.tag"].values.dtype.kind == "S"


def test_every_numeric_column_key_resolves_with_matching_values(
    loaded: _Loaded,
) -> None:
    """全数: 各列キーが解決でき、値・dtype・時刻列がオラクルと厳密一致する."""
    for column_key, col in sorted(_numeric(loaded.columns).items()):
        sig = loaded.resolve(column_key)
        assert sig is not None, f"列キーが解決できない: {column_key!r}"
        assert sig.values.dtype == col.values.dtype, column_key
        np.testing.assert_array_equal(sig.values, col.values, err_msg=column_key)
        np.testing.assert_array_equal(
            sig.timestamps, col.timestamps, err_msg=column_key
        )


def test_group_master_is_shared_by_identity(loaded: _Loaded) -> None:
    """同一仮想グループの列は master ndarray を **同一オブジェクト** で共有する。

    ``source_info`` の ``id(s.timestamps)`` dedup がこの identity に依存しており、
    列ごとにコピーすると 264k 本ぶんの時刻列が実体化して会計も壊れる。
    """
    by_group: dict[int, list[tuple[str, Signal]]] = {}
    for column_key, col in sorted(_numeric(loaded.columns).items()):
        sig = loaded.resolve(column_key)
        assert sig is not None
        by_group.setdefault(col.virtual_group, []).append((column_key, sig))

    for items in by_group.values():
        ref_key, ref = items[0]
        assert ref.timestamps.flags.writeable is False, ref_key
        for column_key, sig in items[1:]:
            # id() の集合でなく参照を保持したまま `is` で比較する
            # (死んだオブジェクトのアドレス再利用による非決定フレークを避ける)。
            assert sig.timestamps is ref.timestamps, f"{column_key} vs {ref_key}"

    # 共有の 2 形態をどちらも被覆していること (同一チャンネルの列間 / 別チャンネル間)
    assert (
        loaded.columns["Mat[1]"].virtual_group == loaded.columns["Mat[2]"].virtual_group
    )
    assert loaded.columns["ShA"].virtual_group == loaded.columns["ShB"].virtual_group


def test_metadata_matches_oracle_for_every_column(loaded: _Loaded) -> None:
    """全数: physical_channel・unit・comment・name_deduplicated と LD-07 の非継承."""
    for column_key, col in sorted(_numeric(loaded.columns).items()):
        sig = loaded.resolve(column_key)
        assert sig is not None
        meta = sig.metadata
        assert meta["physical_channel"] == col.physical, column_key
        assert meta.get("unit", "") == col.unit, column_key
        assert meta.get("comment", "") == col.comment, column_key
        assert meta.get("name_deduplicated", False) == col.deduplicated, column_key
        if col.exploded:
            # LD-07: 展開列は value_labels も conversion_info も継承しない
            assert "value_labels" not in meta, column_key
            assert "conversion_info" not in meta, column_key
    # 正の対照 — 1-D チャンネルは conversion_info を持つ。これが無いと上の
    # 「継承しない」assert は「誰も持っていない」だけで通る vacuous な否定になる。
    scaled = loaded.resolve("Scaled")
    assert scaled is not None
    assert "conversion_info" in scaled.metadata


def test_non_numeric_leaf_is_not_a_column_key(loaded: _Loaded) -> None:
    """``_flatten`` は dtype 盲目だが、列キー空間には数値リーフしか載らない。

    S2 フィールドが列キーになると「見えるのに永久に描かれない行」になる。判定は
    リーフ単位であり、同じチャンネルの数値リーフは巻き添えにしてはならない。
    """
    assert loaded.resolve("Mix.tag") is None
    assert loaded.resolve("Mix.x") is not None


def test_element_channel_wins_over_parent_column_key(loaded: _Loaded) -> None:
    """``Mat[0]`` は 2-D ``Mat`` の第 0 列と 1-D 実チャンネルの両方が名乗る。

    最長一致 = 実チャンネル優先。dtype (float64 vs uint8)・unit (deg vs mm)・値が
    すべて違うので、取り違えると必ず RED になる。
    """
    sig = loaded.resolve("Mat[0]")
    assert sig is not None
    assert sig.metadata["physical_channel"] == "Mat[0]"  # 親 "Mat" ではない
    assert sig.metadata["unit"] == "deg"  # 親は "mm"
    assert sig.values.dtype == np.float64  # 親の列は uint8
    np.testing.assert_array_equal(sig.values, [7.0, 8.0, 9.0, 10.0])
    assert loaded.columns["Mat[0]"].physical == "Mat[0]"  # オラクル側も実チャンネル


def test_literal_values_pin_the_key_to_column_mapping(loaded: _Loaded) -> None:
    """手書きの期待値 — ``_flatten`` を一切通さない独立オラクル。

    全数テストは参照側も ``_flatten`` を使うため、列の**順序規則そのもの**が
    反転すると両側が同じだけ壊れて盲目になる。ここだけは fixture の値定義から
    手で書き下した配列で固定する。
    """
    expected: dict[str, list[float]] = {
        "Mat[1]": [1, 11, 21, 31],
        "Mat[2]": [2, 12, 22, 32],
        "Pos.xa": [1.0, 3.0, 5.0, 7.0],
        "Pos.xb": [2.0, 4.0, 6.0, 8.0],
        "Mix.x": [1.0, 2.0, 3.0, 4.0],
        "Nest.g[3]": [3, 13, 23, 33],
        "dup[0]": [100.0, 101.0, 102.0, 103.0],
        "dup[1]": [200.0, 201.0, 202.0, 203.0],
        f"{_ARRAY_CHANNEL}.{_ARRAY_CHANNEL}[1]": [2, 12, 22, 32],
        f"{_ARRAY_CHANNEL}.{_ARRAY_CHANNEL}.dx[2]": [300.0, 301.0, 302.0, 303.0],
        f"{_ARRAY_CHANNEL}[1]": [2, 12, 22, 32],
    }
    for column_key, values in expected.items():
        sig = loaded.resolve(column_key)
        assert sig is not None, column_key
        np.testing.assert_array_equal(sig.values, values, err_msg=column_key)


def test_scaled_channel_is_read_as_physical_values(loaded: _Loaded) -> None:
    """非 raw 読みの固定 — raw=True へ倒れると生カウント (100 倍ずれ) が返る."""
    sig = loaded.resolve("Scaled")
    assert sig is not None
    np.testing.assert_allclose(sig.values, [0.0, 79.8, -12.34, 327.67])


def test_ld08_duplicate_names_resolve_to_distinct_columns(loaded: _Loaded) -> None:
    """同名 2 本は別の物理チャンネル — 表示キーは dedup 済み名から作る."""
    first, second = loaded.resolve("dup[0]"), loaded.resolve("dup[1]")
    assert first is not None and second is not None
    assert first.metadata["name_deduplicated"] is True
    assert second.metadata["name_deduplicated"] is True
    np.testing.assert_array_equal(first.values, [100.0, 101.0, 102.0, 103.0])
    np.testing.assert_array_equal(second.values, [200.0, 201.0, 202.0, 203.0])
    assert first.timestamps is not second.timestamps  # 別グループ = 別 master


def test_nested_index_arm_is_synthetic_because_asammdf_flattens_subarrays(
    loaded: _Loaded,
) -> None:
    """``Name[i][j]`` は asammdf の public write API で往復できない (弱点の記録)。

    (2,3) のサブ配列フィールドを書いても読み戻しは (6,) へ潰れ、実測リーフは
    ``Nest.g[0..5]`` の **1 段**である。よってこの腕だけはファイル往復ではなく
    合成 ndarray で固定する — 実データで裏取りできていない事実を明示する。
    """
    assert sorted(k for k in loaded.columns if k.startswith("Nest.")) == [
        f"Nest.g[{i}]" for i in range(6)
    ]

    arr = np.zeros((4, 2, 3), dtype=np.uint8)
    arr[:] = np.arange(6, dtype=np.uint8).reshape(2, 3)
    spec = spec_from_probe(arr)
    names = list(leaf_names("W", spec))
    assert names == [f"W[{i}][{j}]" for i in range(2) for j in range(3)]
    # 生成順が _flatten と一致する (列キー空間の単一の真実)
    assert [name for name, _col in _flatten("W", arr)] == names
    for name in names:
        got = parse_leaf(name, {"W": spec})
        assert got is not None, name
        assert got[0] == "W", name
```

- [ ] **Step 2: 失敗を確認**

T0 は production を変更しないので「未実装ゆえの RED」は存在しない。代わりに**オラクル自身の honest-RED をここで先に見る** — `src/valisync/core/loaders/mdf_loader.py:71-75` の `_flatten` に 1 文字の非対称を入れる（**ソース編集なのでオラクル側の `_flatten` も同時に壊れる**＝最も検出しにくい対称的破壊）:

```python
    return [
        pair
        for i in range(arr.shape[1])
        for pair in _flatten(f"{name}({i})", arr[:, i])  # ← [i] を (i) に変える
    ]
```

Run: `uv run pytest tests/core/loaders/test_column_roundtrip.py -q`

Expected: FAIL — 実測で 4 failed / 6 passed。

```
FAILED ...::test_oracle_covers_every_naming_arm - AssertionError: ['Mat(1)', 'Ma...
  E   AssertionError: ['Mat(1)', 'Mat(2)', 'Mat[0]', 'Mix.x', 'Nest.g(0)', ...]
  E   assert ['Mat(1)', 'Mat(2)', ...] == _EXPECTED_COLUMN_KEYS
  E     (2-D 由来の列だけが Name(i) へ化け、1-D 実チャンネルはそのまま = 全数一致が崩れる)
FAILED ...::test_group_master_is_shared_by_identity - KeyError: 'Mat[1]'
FAILED ...::test_literal_values_pin_the_key_to_column_mapping - AssertionError: Mat[1] / assert None is not None
FAILED ...::test_nested_index_arm_is_synthetic_because_asammdf_flattens_subarrays
  E   AssertionError: assert ['Nest.g(0)',..., 'Nest.g(5)'] == ['Nest.g[0]',..., 'Nest.g[5]']
```

**この 4 本が RED になる／全数 2 本（`test_every_numeric_column_key_resolves_with_matching_values`・`test_metadata_matches_oracle_for_every_column`）は GREEN のままである**ことを必ず目視する。全数ループは参照側も `_flatten` を使うため対称的破壊に構造的に盲目であり、ハードコードしたキー列（腕の代表・手書き期待値・`Nest.g[i]` の実測）だけが防波堤になっている — この非対称を理解せずに「全数があるから安心」と読むのがこのファイル最大の誤読ポイント。

- [ ] **Step 3: 実装**

production の変更は無い。Step 2 の sabotage を戻すことが本タスクの「実装」に相当する:

```bash
git checkout -- src/valisync/core/loaders/mdf_loader.py
git diff --stat   # src/ に差分が無いこと (T0 は tests/ だけを足す)
```

この時点で凍結されている契約（T6 が壊してはならないもの）:

| 契約 | 固定するテスト |
|---|---|
| 列キー 29 本すべてが `Session.resolve_signal` で解決でき、値・dtype・時刻列が一致 | `test_every_numeric_column_key_resolves_with_matching_values` |
| 数値列キーの全数（`_EXPECTED_COLUMN_KEYS` と厳密一致・腕の代表キー・非数値リーフの実在） | `test_oracle_covers_every_naming_arm` |
| 仮想グループの master ndarray を identity 共有（read-only） | `test_group_master_is_shared_by_identity` |
| `physical_channel` / `unit` / `comment` / `name_deduplicated`、展開列は `value_labels`・`conversion_info` 非継承（LD-07） | `test_metadata_matches_oracle_for_every_column` |
| 非数値リーフは列キー空間に載らない・同一チャンネルの数値リーフは巻き添えにしない | `test_non_numeric_leaf_is_not_a_column_key` |
| `Mat[0]` 衝突は実チャンネル優先 | `test_element_channel_wins_over_parent_column_key` |
| LD-08 dedup 表示名（`dup[0]`/`dup[1]`）と生名 selector の二重名 | `test_ld08_duplicate_names_resolve_to_distinct_columns` |
| 非 raw 読み（物理値） | `test_scaled_channel_is_read_as_physical_values` |
| `Name[i][j]` 文法（合成のみ・弱点として記録） | `test_nested_index_arm_is_synthetic_because_asammdf_flattens_subarrays` |

- [ ] **Step 4: 通ることを確認**

```
uv run pytest tests/core/loaders/test_column_roundtrip.py -q
```
Expected: `10 passed`（実測: 実質処理時間はモジュール setup 0.06s ＋ call 合計 0.02s。fixture は module-scope で mf4 書き出しとオラクル構築を 1 回だけ行う）。

母数の実測値（`_EXPECTED_COLUMN_KEYS` の裏付け）: 数値列キー **29 本** / 非数値リーフ **1 本**（`Mix.tag`, dtype `S2`）/ 仮想グループ **10 個**。うち 6 本（`Radar.ObjList[0..2]` / `Radar.ObjList.dx[0..2]`）は asammdf が CABLOCK 配列に対して実在させる**要素チャンネル**（展開列ではない）。`demo_data/` に一切依存しないので CI で実行される。

隣接テストの無回帰も確認する:
```
uv run pytest tests/core/loaders tests/test_loaders.py -q
```

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

**(a) `_flatten` の索引トークン非対称（Step 2 で実施済み・再掲）** — `mdf_loader.py:71-75` の `f"{name}[{i}]"` → `f"{name}({i})"`。実測: 4 failed / 6 passed（上記のエラー文）。ソース編集なので参照側も同時に壊れる最悪ケースであり、それでも RED になることを確認済み。

**(b) LD-08 dedup を殺す（オラクルの独立性の実証）** — `MdfLoader._count_names` の戻りを全件 1 にすると（`unittest.mock.patch` で実測済み）、production の表示名が両方 `dup` になり `dup[0]`/`dup[1]` が解決不能になる。実測: `unresolvable = ['dup[0]', 'dup[1]']` → `test_oracle_covers_every_naming_arm` / `test_every_numeric_column_key_resolves_with_matching_values` / `test_literal_values_pin_the_key_to_column_mapping` / `test_ld08_duplicate_names_resolve_to_distinct_columns` が RED。**このケースは全数ループも RED になる**（オラクルは自前の `Counter` で dedup を独立に計算しているため）。

**(c) master identity を殺す** — `mdf_loader.py:472-473` の `master` を列ごとにコピーする（例: `Signal(..., timestamps=master.copy(), ...)`）と `test_group_master_is_shared_by_identity` が `assert sig.timestamps is ref.timestamps` で RED。

**(d) 数値ゲートを殺す** — `mdf_loader.py:547-558` の `if gate_dtype.kind not in "iufb": ... continue` を外すと `Mix.tag` が Signal になり `test_non_numeric_leaf_is_not_a_column_key` の `assert loaded.resolve("Mix.tag") is None` が RED。

**T6（反転）着地時に必ず追加で実施する 2 つ（本タスクでは実施しない・T6 の受入条件）**:
1. `column_names.parse_leaf` に 1 文字の非対称を入れる（例: `_consume` の array 分岐で `rest.startswith("[")` → `rest.startswith("(")`）。反転後は `_mint_column` が `parse_leaf` を通るので、**全数テストが RED になる**ことを確認する。反転前は `resolve` が `_namespaced_map` で答えるため `test_nested_index_arm_is_synthetic_...`（`parse_leaf` を直呼び）しか赤くならない — この差そのものが「反転で鋳造経路が本当に生きた」ことの証拠になる。
2. `Mat[0]` 衝突キーを引く（`parse_leaf` の最長一致を短い方優先に反転させる）。`test_element_channel_wins_over_parent_column_key` が dtype/unit/値の 3 箇所で RED になることを確認する。

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add tests/core/loaders/test_column_roundtrip.py
git commit -m "test(core): 列キーの全数ラウンドトリップ・オラクルを追加 (E-3 反転前の凍結)

asammdf の select + _flatten 直叩きを独立参照に置き、Name.field / Name[i] /
Name.field[i] / LD-08 dedup / Mat[0] 衝突 / 非数値混在の全腕について
Session.resolve_signal の値・dtype・master identity・metadata を固定する。
_flatten は反転後も LazyMdfValues.array() が使い続けるため、この参照は
E-3 の反転を跨いで生き残る。demo_data 非依存 (CI 実行)。

Name[i][j] だけは asammdf の public write API で往復できない ((2,3) サブ配列は
読み戻しで (6,) に潰れる) ため合成 ndarray でのみ確認する — 構造的な弱点として
テスト内に記録した。"
```

`src/` に差分が無いこと（`git status --short` が `tests/core/loaders/test_column_roundtrip.py` 1 件のみ）を commit 前に確認する。

---

### Task 1: `ColumnRecord` 表＋共有 API（ローダーはまだ eager 展開＝挙動不変）

**Files:**
- Modify: `src/valisync/core/loaders/column_names.py:22-30`（`ColumnSpec` 定義の直後に `ColumnRecord` を追加）
- Modify: `src/valisync/core/loaders/signal_group_manager.py:3`（import）・`:22-32`（`__init__`）・`:34-46`（`add`）・`:48-63`（`remove`）・`:199-201`（`resolved_keys` の直後に 4 API を追加）
- Modify: `src/valisync/core/models/load_result.py:1-31`（`LoadResult` に `column_records` フィールド）
- Modify: `src/valisync/core/loaders/mdf_loader.py:12`（import）・`:315-316`（表の器）・`:356-368`（`_load_group` 呼び出し）・`:396-403`（`LoadResult` 返却）・`:434-446`（`_load_group` シグネチャ）・`:506`（表への記録）
- Modify: `src/valisync/core/session.py:169-170`（`add` への引き渡し）・`:257-259`（`resolve_signal` の直後に pass-through 3 本）
- Test: `tests/core/loaders/test_column_records.py`（新規・CI-live／`demo_data` 非依存）

**Interfaces:**
- Consumes: 既存 `valisync.core.loaders.column_names` の `ColumnSpec` / `spec_from_probe(arr: np.ndarray) -> ColumnSpec` / `leaf_names(base: str, spec: ColumnSpec) -> Iterator[str]` / `leaf_count(spec: ColumnSpec) -> int`（数値リーフのみを数える。dtype-blind の `mdf_loader._all_leaf_count` とは**別物**）。T0 の成果物には依存しない。
- Produces:
  - `valisync.core.loaders.column_names.ColumnRecord`（`@dataclass(frozen=True, slots=True)`・フィールド `raw_base_name: str` / `group_index: int` / `channel_index: int` / `spec: ColumnSpec`）
  - `SignalGroupManager.column_records(self, group_key: str) -> Mapping[str, ColumnRecord]`（キー = LD-08 dedup 済み表示名＝`metadata["physical_channel"]` と同一キー空間。未知 key/CSV は空）
  - `SignalGroupManager.column_names_of(self, group_key: str, display_name: str) -> tuple[str, ...]`
  - `SignalGroupManager.total_column_count(self, group_key: str) -> int`（未知 key は `KeyError`）
  - `SignalGroupManager.has_column(self, group_key: str, display_name: str) -> bool`（*display_name* がそのグループの**列**として実在するか。スカラー・列キーは True／配列・構造体の親（容器）・未知名・未知 key は False。**鋳造しない**）
  - `Session.column_names_of(self, key: str, display_name: str) -> tuple[str, ...]`
  - `Session.total_column_count(self, key: str) -> int`
  - `Session.has_column(self, key: str, display_name: str) -> bool`
  - `SignalGroupManager.add(self, group: SignalGroup, column_records: Mapping[str, ColumnRecord] | None = None) -> str`（第 2 引数は追加・既存の 1 引数呼び出しは無改造）
  - `LoadResult.column_records: Mapping[str, ColumnRecord]`（既定は空 dict）
  - 後続の依存: T2 は `column_records(group_key)[display_name]` から `(raw_base_name, group_index, channel_index, spec)` を得て `LazyMdfValues(selector=...)` を組む。T4/T5 は `column_names_of` / `total_column_count` を列の唯一の出所にする。T7 は `total_column_count` を `source_info.n_channels`（U2）へ繋ぐ。`has_column` は T5（`_row_matches` のスカラー行ショートサーキット）と T7（`display_name` の衝突判定＝鋳造せずに他ファイルの同名列の有無だけを見る）が使う。

- [ ] **Step 1: 失敗テストを書く**

`tests/core/loaders/test_column_records.py` を新規作成する。

```python
"""ColumnRecord 表: 列の鋳造に要る (生名, gi, ci, ColumnSpec) をローダーが残す (E-3 T1)。

鋳造器 _mint_column は列キー 1 本しか受け取らないが、列キーは LD-08 dedup 済みの
**表示名**由来 (metadata['physical_channel'] と同一キー空間) で、asammdf の select は
**生チャンネル名と (gi, ci)** を要求する。この 2 つのキー空間を橋渡しするレコードが
無いと鋳造そのものが書けない。

反転 (T6) 前なのでローダーはまだ列を展開している。よって「表から生成した列名」と
「実際にロードされた Signal 名」を突き合わせられる — この一致が T6 の受け入れ条件に
なり、反転後も同じ assert が生き残る。
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from tests.mdf4_helpers import (
    CAN,
    write_mdf4,
    write_mdf4_2d,
    write_mdf4_all_channels_bad,
    write_mdf4_flatten_fixture,
    write_mdf4_single_column_shapes,
)
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup
from valisync.core.session import Session


def _loaded(path: Path) -> tuple[SignalGroupManager, str, SignalGroup]:
    """実 mf4 をロードし、ローダーが出した表ごと manager へ登録する。

    ``confirm_expansion`` は既定 None なので**渡さない** — Task 8 が引数ごと退役させる
    ときに、このファイルが取りこぼされて ``TypeError`` で落ちるのを構造的に防ぐ。
    """
    result = MdfLoader().load(path)
    sg = result.signal_group
    assert sg is not None
    mgr = SignalGroupManager()
    key = mgr.add(sg, column_records=result.column_records)
    return mgr, key, sg


def _sig(name: str) -> Signal:
    ts = np.arange(3, dtype=np.float64)
    return Signal(
        name=name,
        timestamps=ts,
        values=np.zeros(3),
        file_format="CSV",
        bus_type="",
        source_file="/x.csv",
    )


def _group(*names: str) -> SignalGroup:
    return SignalGroup(
        signals=tuple(_sig(n) for n in names),
        source_path=Path("/x.csv").resolve(),
        file_format="CSV",
        loaded_at=datetime.datetime.now(),
    )


def test_record_carries_raw_name_group_channel_and_spec(tmp_path: Path) -> None:
    """(1) ロード後に (生名, gi, ci, ColumnSpec) が引ける。"""
    mgr, key, sg = _loaded(write_mdf4_2d(tmp_path))
    records = mgr.column_records(key)
    # キーは物理チャンネル (列ではない) — Mat[0..2] は 1 レコードに畳まれる
    assert set(records) == {"Mat", "Clean"}

    mat = records["Mat"]
    assert mat.raw_base_name == "Mat"
    assert mat.spec.kind == "array"
    assert mat.spec.axis_len == 3
    clean = records["Clean"]
    assert clean.spec.kind == "leaf"
    assert clean.spec.dtype_kind == "f"

    # (gi, ci) は select の実引数。実ファイルで指し先を確認する
    # (int が 2 つ入っているだけでは何も保証しない)。
    handle = sg.handle
    assert handle is not None
    for name, record in records.items():
        channel = handle.mdf.groups[record.group_index].channels[record.channel_index]
        assert channel.name == record.raw_base_name, name

    # 表の構築は 1 レコードプローブ由来 — 値を展開してはならない (遅延契約)
    assert all(s._values_source.is_materialized is False for s in sg.signals)


def test_duplicate_raw_names_are_two_records_with_distinct_locations(
    tmp_path: Path,
) -> None:
    """(2) LD-08 の重複名 2 本が別レコードとして区別される。

    表を生名でキーすると 2 本が 1 レコードへ融合し、片方の構造/位置が黙って
    消える (どちらが勝つかは走査順まかせ)。
    """
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
    mgr, key, sg = _loaded(path)
    records = mgr.column_records(key)

    assert set(records) == {"sig[0]", "sig[1]"}
    assert {r.raw_base_name for r in records.values()} == {"sig"}  # 生名は共有
    locations = {(r.group_index, r.channel_index) for r in records.values()}
    assert len(locations) == 2, locations  # 指し先は別々

    handle = sg.handle
    assert handle is not None
    for record in records.values():
        channel = handle.mdf.groups[record.group_index].channels[record.channel_index]
        assert channel.name == "sig"

    # 列名の base は **表示名** (生名ではない) — 列キーは dedup 済み名から作る契約
    assert mgr.column_names_of(key, "sig[1]") == ("sig[1]",)


def test_column_names_of_scalar_is_the_display_name_itself(tmp_path: Path) -> None:
    """(3) スカラーは (display_name,) を返す。"""
    mgr, key, _sg = _loaded(write_mdf4_2d(tmp_path))
    assert mgr.column_names_of(key, "Clean") == ("Clean",)


def test_column_names_of_array_and_struct(tmp_path: Path) -> None:
    mgr, key, _sg = _loaded(write_mdf4_flatten_fixture(tmp_path))
    assert mgr.column_names_of(key, "Mat") == ("Mat[0]", "Mat[1]", "Mat[2]")
    assert mgr.column_names_of(key, "Pos") == ("Pos.xa", "Pos.xb", "Pos.yc")
    assert mgr.column_names_of(key, "ACC.Speed") == ("ACC.Speed",)


def test_has_column_distinguishes_columns_from_container_channels(
    tmp_path: Path,
) -> None:
    """(3b) 列の**存在判定**だけを鋳造せずに答える (T5 の行フィルタ / T7 の衝突判定)。

    列名タプルを作らずに済むのが要点: 広幅チャンネルで `column_names_of` を呼ぶと
    1,000 本の f-string が出る。呼び出し側 (フィルタ 1 打鍵ごと・表示名 1 件ごと) は
    「あるか」しか要らない。
    """
    mgr, key, _sg = _loaded(write_mdf4_flatten_fixture(tmp_path))
    assert mgr.has_column(key, "ACC.Speed") is True  # スカラー = 物理チャンネル兼列
    assert mgr.has_column(key, "Mat[1]") is True  # 展開列
    assert mgr.has_column(key, "Pos.xb") is True  # 構造化フィールド
    assert mgr.has_column(key, "Mat") is False  # 容器 (配列の親) は列ではない
    assert mgr.has_column(key, "Pos") is False  # 容器 (構造体の親)
    assert mgr.has_column(key, "Mat[9]") is False  # 幅の範囲外
    assert mgr.has_column(key, "Nope") is False  # 未知の物理チャンネル
    assert mgr.has_column("mf4_9", "Mat[1]") is False  # 未ロードグループ

    # 非数値リーフは列キー空間に載らない (leaf_names は数値リーフのみを生む)
    mgr2, key2, _sg2 = _loaded(write_mdf4_single_column_shapes(tmp_path))
    assert mgr2.has_column(key2, "Q.x") is True
    assert mgr2.has_column(key2, "Q.tag") is False


def test_has_column_falls_back_to_observed_signals_without_records() -> None:
    """CSV/Derived は表を持たない — 観測した Signal 名がそのまま列。"""
    mgr = SignalGroupManager()
    key = mgr.add(_group("Spd", "Arr[0]"))
    assert mgr.has_column(key, "Spd") is True
    assert mgr.has_column(key, "Arr[0]") is True  # 形だけを根拠に畳まない
    assert mgr.has_column(key, "Arr") is False  # 実在しない親を捏造しない


def test_generated_column_names_match_eager_expansion(tmp_path: Path) -> None:
    """反転前にしかできない突合: 表から作った列名 == 実際に載っている Signal 名。

    順序も含めて一致すること (leaf_names は _flatten と同順・ローダーはその順で
    Signal を append する)。T6 はこの一致を保ったまま Signal 側だけを減らす。
    """
    for path in (
        write_mdf4_flatten_fixture(tmp_path),
        write_mdf4_single_column_shapes(tmp_path),
    ):
        mgr, key, sg = _loaded(path)
        expected: dict[str, list[str]] = {}
        for s in sg.signals:
            phys = str((s.metadata or {}).get("physical_channel") or s.name)
            expected.setdefault(phys, []).append(s.name)
        assert expected, path.name
        for phys, names in expected.items():
            assert mgr.column_names_of(key, phys) == tuple(names), (path.name, phys)


@pytest.mark.parametrize(
    "writer",
    [
        write_mdf4_2d,
        write_mdf4_flatten_fixture,
        write_mdf4_single_column_shapes,
        write_mdf4_all_channels_bad,
    ],
)
def test_total_column_count_equals_eager_signal_count(
    writer: Callable[[Path], Path], tmp_path: Path
) -> None:
    """(4) 数値列総数が eager 展開後の Signal 数と一致する。

    single_column_shapes は非数値リーフ (Q.tag) を、all_channels_bad は非数値
    チャンネルのみを含む — dtype-blind に数えると両方 RED になる (数えるのは
    **数値リーフのみ** = leaf_count であって _all_leaf_count ではない)。
    """
    mgr, key, sg = _loaded(writer(tmp_path))
    assert mgr.total_column_count(key) == len(sg.signals)


def test_group_without_records_falls_back_to_one_column_per_signal() -> None:
    """CSV/Derived は列構造を持たない = 1 信号 1 列 (表が無くても答えを返す)。"""
    mgr = SignalGroupManager()
    key = mgr.add(_group("Spd", "Arr[0]"))
    assert mgr.column_records(key) == {}
    # 名前の形だけを根拠に畳まない: CSV の Arr[0] は展開列ではなく 1 本のチャンネル
    assert mgr.column_names_of(key, "Arr[0]") == ("Arr[0]",)
    assert mgr.total_column_count(key) == 2


def test_records_follow_group_lifetime(tmp_path: Path) -> None:
    """表の寿命は add/remove のみ — namespaced 無効化に相乗りさせない。

    相乗りさせると 2 ファイル目のロードごとに表が消え、鋳造 (T2) が
    ファイル全体の再走査に落ちる (_resolved_by_key と同じ機序)。
    """
    mgr, key, _sg = _loaded(write_mdf4_2d(tmp_path))
    other = mgr.add(_group("Other"))  # 2 ファイル目ロード相当
    assert "Mat" in mgr.column_records(key)
    mgr.remove(other)  # 2 ファイル目 unload 相当
    assert "Mat" in mgr.column_records(key)

    mgr.remove(key)  # 自グループの unload で捨てる
    assert mgr.column_records(key) == {}
    with pytest.raises(KeyError):
        mgr.total_column_count(key)


def test_column_records_view_is_read_only(tmp_path: Path) -> None:
    mgr, key, _sg = _loaded(write_mdf4_2d(tmp_path))
    view = mgr.column_records(key)
    assert not hasattr(view, "__setitem__")
    assert mgr.column_records("mf4_9") == {}  # 未知 key は空 (KeyError にしない)


def test_session_exposes_column_names_and_total(tmp_path: Path) -> None:
    """GUI 側 (T4/T5) が触るのは Session の 2 本だけ。"""
    session = Session()
    key = session.load(write_mdf4_flatten_fixture(tmp_path)).key
    assert session.column_names_of(key, "Mat") == ("Mat[0]", "Mat[1]", "Mat[2]")
    assert session.total_column_count(key) == len(session.group_signals(key))
    # U2: n_channels の単位は列数のまま (T7 がこの一致を保つ)
    assert session.source_info(key).n_channels == session.total_column_count(key)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_column_records.py::test_record_carries_raw_name_group_channel_and_spec -q`
Expected: FAIL with `AttributeError: 'LoadResult' object has no attribute 'column_records'`

Run: `uv run pytest tests/core/loaders/test_column_records.py::test_group_without_records_falls_back_to_one_column_per_signal -q`
Expected: FAIL with `AttributeError: 'SignalGroupManager' object has no attribute 'column_records'`

Run: `uv run pytest tests/core/loaders/test_column_records.py::test_session_exposes_column_names_and_total -q`
Expected: FAIL with `AttributeError: 'Session' object has no attribute 'column_names_of'`

- [ ] **Step 3: 実装**

**3-1. `src/valisync/core/loaders/column_names.py`** — `ColumnSpec` 定義（`fields` 行の直後）に追加する。

```python
@dataclass(frozen=True, slots=True)
class ColumnRecord:
    """物理チャンネル 1 本の鋳造に必要な最小情報 (値は持たない)。

    ローダーが持つ 2 つのキー空間を橋渡しする唯一の置き場: 列キー / 表示名は
    LD-08 dedup 済み (同名 2 本なら ``sig[0]`` / ``sig[1]``) だが、asammdf の
    ``select`` は**生チャンネル名と (gi, ci)** を要求する。表示名からは生名も
    位置も復元できない (dedup は非可逆) ため、ロード時にここへ残す。
    """

    raw_base_name: str  # asammdf のチャンネル名 (LD-08 dedup 前の生名)
    group_index: int
    channel_index: int
    spec: ColumnSpec
```

**3-2. `src/valisync/core/models/load_result.py`** — 先頭の import と `LoadResult` を差し替える。

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from valisync.core.models.signal_group import SignalGroup

if TYPE_CHECKING:
    # 実行時 import は循環する: core.models -> core.loaders.column_names は
    # パッケージ core.loaders の __init__ (csv_loader/mdf_loader) を起動し、
    # そこから core.models へ戻る。注釈は from __future__ で文字列化済み。
    from valisync.core.loaders.column_names import ColumnRecord
```

```python
@dataclass(frozen=True)
class LoadResult:
    """Result of a file load operation."""

    signal_group: SignalGroup | None
    diagnostics: tuple[Diagnostic, ...] = ()
    # E-3: 列鋳造の材料 {LD-08 dedup 済み表示名: ColumnRecord}。ローダーが 1 レコード
    # プローブから作り、Session が SignalGroupManager へ引き渡す。列構造を持たない
    # CSV は空のまま (1 信号 1 列として扱われる)。
    column_records: Mapping[str, ColumnRecord] = field(default_factory=dict)
```

**3-3. `src/valisync/core/loaders/signal_group_manager.py`**

import を差し替える（先頭 3-5 行目）。

```python
from collections.abc import Callable, Iterator, Mapping
from types import MappingProxyType

from valisync.core.loaders.column_names import ColumnRecord, leaf_count, leaf_names
from valisync.core.models import Signal, SignalGroup
```

`KEY_SEPARATOR = "::"` の下にモジュール定数を置く。

```python
# 表を持たないグループ (CSV/Derived・未知 key) が返す共有の空ビュー。
_NO_COLUMN_RECORDS: Mapping[str, ColumnRecord] = MappingProxyType({})
```

`__init__` の末尾（`self.mint_count = 0` の直前）に表を追加する。

```python
        # 列鋳造の材料 (E-3)。_resolved_by_key と同じく **_invalidate_namespaced() に
        # 相乗りさせない** — グループの寿命 (add/remove) にだけ従う。相乗りさせると
        # 2 ファイル目のロードで表が消え、鋳造がファイル全体の再走査に落ちる。
        self._column_records: dict[str, dict[str, ColumnRecord]] = {}
```

`add` を差し替える。

```python
    def add(
        self,
        group: SignalGroup,
        column_records: Mapping[str, ColumnRecord] | None = None,
    ) -> str:
        """Register a Signal_Group and return its assigned key.

        Duplicate source paths are allowed; each load receives a distinct key.
        ``column_records`` はローダーが 1 レコードプローブから作った
        {表示名: ColumnRecord} (MDF のみ)。CSV/Derived は列構造を持たないので None。
        """
        prefix = _FORMAT_KEY_PREFIX.get(group.file_format)
        if prefix is None:
            raise ValueError(f"unsupported file_format: {group.file_format!r}")
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        key = f"{prefix}_{self._counters[prefix]}"
        self._groups[key] = group
        if column_records:
            # 呼び出し側の dict と縁を切る (ローダーの一時表が後から変わっても
            # 登録済みグループの列構造は動かない)。物理チャンネル数ぶんなので安い。
            self._column_records[key] = dict(column_records)
        self._invalidate_namespaced()
        return key
```

`remove` の `columns = ...` 行の直後に 1 行足す。

```python
        columns = tuple(self._resolved_by_key.pop(key, {}).values())
        self._column_records.pop(key, None)
```

`resolved_keys` と `_mint_column` の間に 3 API を追加する。

```python
    def column_records(self, group_key: str) -> Mapping[str, ColumnRecord]:
        """{LD-08 dedup 済み表示名: ColumnRecord} の読み取り専用ビュー (E-3)。

        キー空間は Signal の ``metadata['physical_channel']`` と同一 — ブラウザや
        エクスポートの「物理チャンネル行」から列を引くのはこの表。未知 key と
        CSV/Derived は空を返す (``resolved_keys`` と同じ introspection 契約で、
        鋳造も KeyError も起こさない)。
        """
        table = self._column_records.get(group_key)
        return _NO_COLUMN_RECORDS if table is None else MappingProxyType(table)

    def column_names_of(self, group_key: str, display_name: str) -> tuple[str, ...]:
        """物理チャンネル 1 本の数値リーフ列名を _flatten と同じ順序で返す。

        base に**表示名**を渡すのが要点 (二重名の契約): 列キーは dedup 済み名から
        作り (``sig[1][0]``)、selector は生名から作る。ここで生名を base にすると
        UI/永続キーが黙って別物になる。
        表に無い物理チャンネル (CSV/Derived・未知 key) は 1 信号 1 列なので
        ``(display_name,)`` を返す。
        """
        record = self._column_records.get(group_key, {}).get(display_name)
        if record is None:
            return (display_name,)
        return tuple(leaf_names(display_name, record.spec))

    def total_column_count(self, group_key: str) -> int:
        """グループの数値列総数 (未知 key は ``group()`` と同じく KeyError)。

        ``source_info.n_channels`` とブラウザヘッダの母数 (U2: 単位は列数のまま)。
        名前を 1 本も生成せず、鋳造も誘発せずに数える。数えるのは**数値リーフのみ**
        — 非数値リーフでは Signal を作らないので、dtype-blind に数えると
        表示件数が実在しない列を含んでしまう。
        """
        group = self._groups[group_key]
        records = self._column_records.get(group_key)
        if not records:
            return len(group.signals)  # CSV/Derived: 1 信号 1 列
        return sum(leaf_count(record.spec) for record in records.values())

    def has_column(self, group_key: str, display_name: str) -> bool:
        """*display_name* がこのグループの **列** として実在するか (鋳造しない)。

        「あるか」しか要らない呼び出し側 (T5 の行フィルタ・T7 の表示名衝突判定) の
        ための存在判定。``resolve_signal`` で代用すると、ヒットした列が
        ``_resolved_by_key`` へ**恒久的に**登録される (LRU は E-3 では入れない = C-g)
        ため、表示のためだけに列 Signal が寿命いっぱい滞留する。

        物理チャンネル名そのものが渡された場合は ``spec`` の形だけで決まる
        (列名を 1 本も生成しない — 広幅チャンネルで 1,000 本の f-string を作らない)。
        列キー (``Mat[1]`` / ``Pos.xb``) は表示名の最長一致で親を探し、その親の
        数値リーフ名に含まれるかを見る。``leaf_names`` は数値リーフしか生まないので、
        非数値リーフ (``Q.tag``) は自動的に False になる。
        未知 key / 未知名は False (``column_records`` と同じ introspection 契約)。
        """
        records = self._column_records.get(group_key)
        if not records:
            # 表を持たないグループ (CSV/Derived・未知 key) は 1 信号 1 列。
            group = self._groups.get(group_key)
            return group is not None and any(
                sig.name == display_name for sig in group.signals
            )
        record = records.get(display_name)
        if record is not None:
            # 物理チャンネル名そのもの。列でもあるのは「数値スカラー」= 1 本の
            # リーフが自分自身と同名になるときだけで、容器 (配列/構造体の親) は
            # 列ではない (親を列扱いすると 2-D 値がプロット/出力へ流れる)。
            return record.spec.kind == "leaf" and leaf_count(record.spec) == 1
        for i in range(len(display_name) - 1, 0, -1):
            parent = records.get(display_name[:i])
            if parent is None:
                continue
            names = leaf_names(display_name[:i], parent.spec)
            if any(name == display_name for name in names):
                return True
            # ここで打ち切らない: Mat[0] (1-D 実チャンネル) と Mat (3-D) のように
            # 長い方が別チャンネルとして実在しても、短い方が正しい親でありうる。
        return False
```

**3-4. `src/valisync/core/loaders/mdf_loader.py`**

import を差し替える（12 行目）。

```python
from valisync.core.loaders.column_names import ColumnRecord, ColumnSpec, spec_from_probe
```

`load()` の器を追加する（`diagnostics: list[Diagnostic] = []` の直後）。

```python
        diagnostics: list[Diagnostic] = []
        # 物理チャンネル 1 本につき 1 レコード (列数ではない) — prod 4,324 件。
        column_records: dict[str, ColumnRecord] = {}
```

`_load_group` 呼び出しの引数末尾（`handle,` の後）に `column_records,` を足す。

```python
                self._load_group(
                    mdf,
                    gi,
                    resolved_path,
                    name_total,
                    name_seen,
                    signals,
                    diagnostics,
                    cancel,
                    skip_keys,
                    handle,
                    column_records,
                )
```

`load()` の成功時の返却を差し替える。

```python
        return LoadResult(
            signal_group=signal_group,
            diagnostics=tuple(diagnostics),
            column_records=column_records,
        )
```

`_load_group` のシグネチャ末尾（`handle: MdfHandle,` の後）に引数を足す。

```python
        handle: MdfHandle,
        column_records: dict[str, ColumnRecord],
    ) -> None:
```

probe ループ内、`signal_name = ...` の直後に記録する。

```python
            signal_name = f"{base_name}[{idx}]" if deduplicated else base_name
            # E-3: 鋳造 (要求時の列生成) の材料はここでしか確定できない。表示名からは
            # 生名も (gi, ci) も復元できず、後から引き直すとファイル全体の再走査に
            # なる。spec は既に読んだ 1 レコードプローブ由来で値を持たない。
            column_records[signal_name] = ColumnRecord(
                raw_base_name=base_name,
                group_index=_g,
                channel_index=_c,
                spec=spec_from_probe(probe.samples),
            )
```

**3-5. `src/valisync/core/session.py`**

`load()` の登録を差し替える。

```python
            key = self._groups.add(
                result.signal_group, column_records=result.column_records
            )
```

`resolve_signal` の直後に pass-through を追加する。

```python
    def column_names_of(self, key: str, display_name: str) -> tuple[str, ...]:
        """物理チャンネル 1 本の列名を順序どおり返す (名前空間なし・E-3)。

        GUI が「その物理チャンネルにどんな列があるか」を知る唯一の口。
        鋳造 (``resolve_signal``) を誘発しないので、展開していない親にも使える。
        """
        return self._groups.column_names_of(key, display_name)

    def total_column_count(self, key: str) -> int:
        """グループの数値列総数 (KeyError if unknown)。表示件数の母数 (U2)。"""
        return self._groups.total_column_count(key)

    def has_column(self, key: str, display_name: str) -> bool:
        """*display_name* の列がこのグループに実在するか (鋳造しない存在判定)。

        ``resolve_signal`` と違い副テーブルへ何も残さない — 「表示のためだけに列を
        恒久登録する」経路を作らないための口 (E-3 C-g)。
        """
        return self._groups.has_column(key, display_name)
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/core/loaders/test_column_records.py -q`
Expected: 全 pass。

続けて回帰（挙動不変の実証）:
Run: `uv run pytest tests/core -q`
Run: `uv run pytest -q`
Expected: 反転前なのでローダーは従来どおり列を展開しており、既存テストは 1 件も変えずに全 pass（`add` の第 2 引数は既定 None・`LoadResult` の新フィールドは既定空）。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

1. `signal_group_manager.column_names_of` の `leaf_names(display_name, record.spec)` を `leaf_names(record.raw_base_name, record.spec)` に変える（生名を base にする）
   → `test_duplicate_raw_names_are_two_records_with_distinct_locations` が RED（`("sig",) != ("sig[1]",)`）。
2. `total_column_count` の `leaf_count` を dtype-blind な数え方（`mdf_loader._all_leaf_count` 相当）に変える
   → `test_total_column_count_equals_eager_signal_count[write_mdf4_all_channels_bad]`（1 != 0）と `[write_mdf4_single_column_shapes]`（5 != 4・`Q.tag` を数えてしまう）が RED。
3. `mdf_loader` の記録キーを `column_records[signal_name]` → `column_records[base_name]` に変える
   → `test_duplicate_raw_names_are_two_records_with_distinct_locations` が RED（`set(records) == {"sig"}` に融合）。
4. `SignalGroupManager._invalidate_namespaced()` の末尾に `self._column_records = {}` を足す（`_resolved_by_key` と同じ相乗りの罠を再現）
   → `test_records_follow_group_lifetime` が「無関係な 2 ファイル目 add の直後」で RED。
5. `add()` の `self._column_records[key] = dict(column_records)` を削る
   → `test_record_carries_raw_name_group_channel_and_spec` ほか MDF 系が軒並み RED、CSV フォールバック系は GREEN のまま（フォールバックが本物の分岐であることの確認）。
6. `mdf_loader` の `spec_from_probe(probe.samples)` を `spec_from_probe(probe.samples[:0])`（空プローブ）に変える
   → `test_generated_column_names_match_eager_expansion` が RED（構造化は残るが配列の `axis_len` が 0 になり `Mat[0..2]` が消える）。
7. `has_column` の物理チャンネル分岐を `return True` に変える（容器も列扱い）
   → `test_has_column_distinguishes_columns_from_container_channels` が RED（`Mat` / `Pos` が True になる＝2-D 親がプロット/出力へ流れる形）。
8. `has_column` の最長一致ループを削って `return False` にする
   → 同テストが `Mat[1]` / `Pos.xb` で RED（列キーが一切見えなくなる）。CSV フォールバック側（`test_has_column_falls_back_to_observed_signals_without_records`）は GREEN のまま＝2 経路が独立に被覆されていることの実証。

各 sabotage の RED 出力を実行して報告に記す（実行後は必ず戻す）。

- [ ] **Step 6: ゲート＋コミット**

Run: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`（全て exit 0。`| tail` に通さない — exit code が隠れる）

```bash
git add src/valisync/core/loaders/column_names.py \
        src/valisync/core/loaders/signal_group_manager.py \
        src/valisync/core/loaders/mdf_loader.py \
        src/valisync/core/models/load_result.py \
        src/valisync/core/session.py \
        tests/core/loaders/test_column_records.py
git commit -m "$(cat <<'EOF'
feat(core): ColumnRecord 表と列名の共有 API を追加 (E-3 T1・挙動不変)

鋳造器 _mint_column は列キー 1 本しか受け取らないが、列キーは LD-08 dedup 済みの
表示名由来で、asammdf の select は生チャンネル名と (gi, ci) を要求する。この 2 つの
キー空間を橋渡しする ColumnRecord (生名/gi/ci/ColumnSpec・値を持たない) をローダーの
1 レコードプローブから作り、LoadResult -> Session -> SignalGroupManager と引き渡す。

表は manager 側に持たせ、寿命は add/remove のみ (_invalidate_namespaced には
_resolved_by_key と同じ理由で相乗りさせない)。共有 API は column_records /
column_names_of / total_column_count / has_column の 4 本で、Session に後ろ 3 本を
pass-through。column_names_of の base は表示名 (二重名の契約: 列キーは dedup 済み名から
・selector は生名から)。total_column_count は数値リーフのみを数える (非数値リーフは
Signal を作らないため・U2 の単位は列数のまま)。has_column は「あるか」しか要らない
消費者 (行フィルタ・表示名の衝突判定) 向けの存在判定で、resolve_signal と違い
_resolved_by_key へ何も残さない (表示のためだけの恒久登録を構造的に禁じる)。

ローダーはまだ eager 展開なので挙動不変。反転前しかできない突合として「表から作った
列名 == 実際に載っている Signal 名 (順序込み)」「数値列総数 == Signal 数」を
非 demo-gate の実 mf4 で固定した (T6 の受け入れ条件・反転後も同じ assert が残る)。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 2: `_mint_column` の実装（production 無影響）

**Files:**
- Modify: `src/valisync/core/loaders/signal_group_manager.py:1-8`（import と module 定数の追加）
- Modify: `src/valisync/core/loaders/signal_group_manager.py:203-213`（hard-return `None` の本体を実装へ）
- Create: `tests/core/loaders/test_mint_column.py`
- Modify: `tests/mdf4_helpers.py:342`（`write_mdf4_wide_2d` の直後に `write_mdf4_dup_2d` を追記）
- Modify: `tests/core/loaders/test_resolver.py:41-52, 68-74, 91-134, 140-215`（テストダブル `_MintingManager` を実装へ差し替え）
- Modify: `tests/gui/viewmodels/test_signal_map_overlay.py:12-20, 213-234, 237-279`（同上）

**Interfaces:**

- Consumes（Task 1 が新設・シグネチャ厳守）:
  - `SignalGroupManager.column_records(self, group_key: str) -> Mapping[str, ColumnRecord]`
    — キーは **LD-08 dedup 済み表示名**（`metadata["physical_channel"]` と同一キー空間）。
    **記録を持たないグループ（CSV・テストの合成 `SignalGroup`）に対しては空 Mapping を返すこと**
    （例外を投げない）。
  - `ColumnRecord(raw_base_name: str, group_index: int, channel_index: int, spec: ColumnSpec)`
    （`@dataclass(frozen=True, slots=True)`・`column_names.py`）。
  - `SignalGroupManager.add(self, group: SignalGroup, column_records: Mapping[str, ColumnRecord] | None = None) -> str`
    — 列表は **manager 側**（`SignalGroup` のフィールドではない）。本タスクのテストは
    `dataclasses.replace(sg, signals=...)` で「代表列だけを残したグループ」を組み直すが、
    表は `LoadResult.column_records` から**別途** `add(..., column_records=...)` で渡す
    （渡し忘れると `_mint_column` の先頭で表が空になり、正しい実装でも鋳造が常に `None` になる）。
- Consumes（E-1 既存）:
  - `column_names.parse_leaf(display_key: str, specs: Mapping[str, ColumnSpec]) -> tuple[str, ColumnSpec] | None`
  - `LazyMdfValues(handle: MdfHandle, name: str, gi: int, ci: int, length: int, selector: tuple[str, ...] | None = None)`
  - `SignalGroupManager.resolve` / `_resolved_by_key` / `mint_count` / `resolved_keys`（呼び出し側は無改造）
- Produces（T4/T5/T6/T7 が依存）:
  - `SignalGroupManager._mint_column(self, group_key: str, key: str) -> Signal | None` が実際に列 Signal を返す。
    帰結として `resolve(key)` / `signal_map()[key]` / `Session.resolve_signal(key)` が**列キー**で Signal を返す
    （T6 反転後は**これが列 Signal の唯一の供給経路**）。
  - 鋳造 Signal の契約: `name` は namespaced 全体キー／`timestamps` は親と**同一オブジェクト**／
    `metadata` は親の継承（`conversion_info`・`value_labels` は除外）／native dtype 保持／
    `_sorted_view_delegate` を持たない／構築だけでは読まない（`is_materialized is False`）。

---

- [ ] **Step 1: 失敗テストを書く**

まず fixture を 1 つ足す。`tests/mdf4_helpers.py` の `write_mdf4_wide_2d` の直後に追記:

```python
def write_mdf4_dup_2d(tmp_path: Path) -> Path:
    """同名 (W) の 2D uint8 チャンネル 2 本 — LD-08 dedup と LD-14 展開の合成.

    ローダーの規則から、表示名は dedup 済みの ``W[0]`` / ``W[1]``、selector 側の
    リーフ名は生名由来の ``W[0]`` / ``W[1]`` (= 列インデックス) になる。**2 つのキー
    空間が同じ文字列に見えて別物**になる唯一のケースであり、鋳造がキー空間を
    取り違えると解決不能になるか別チャンネルの列を返す。

    列の値は
    ``W[0][0]=[0,2,4,6]`` / ``W[0][1]=[1,3,5,7]`` /
    ``W[1][0]=[100,102,104,106]`` / ``W[1][1]=[101,103,105,107]``
    で、どのチャンネルのどの列を読んだかが値だけで判別できる。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        for base in (0, 100):
            samples = np.array(
                [
                    [base + 0, base + 1],
                    [base + 2, base + 3],
                    [base + 4, base + 5],
                    [base + 6, base + 7],
                ],
                dtype=np.uint8,
            )
            mdf.append([ASignal(samples=samples, timestamps=ts, name="W", unit="m")])
        path = tmp_path / "dup2d.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path
```

`tests/core/loaders/test_mint_column.py`（新規）:

```python
"""列キーから Signal を鋳造する経路 (_mint_column) の契約。

T6 の反転後は **これが列 Signal の唯一の供給経路**になる。eager ローダーがまだ
全列を発行している今のうちに「鋳造した列 == eager が発行した列」を固定する
(反転後は独立オラクルが失われる)。
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from tests.mdf4_helpers import (
    write_mdf4_2d,
    write_mdf4_dup_2d,
    write_mdf4_single_column_shapes,
    write_mdf4_structured,
)
from valisync.core.loaders.column_names import ColumnRecord
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import (
    KEY_SEPARATOR,
    SignalGroupManager,
)
from valisync.core.models import Signal, SignalGroup

#: (SignalGroup, ColumnRecord 表) — 鋳造の材料は **両方**が要る。表は manager 側に
#: 持たせる設計 (Task 1) なので、group だけを持ち回すと add() で表が落ちて
#: _mint_column が常に None を返す (正しい実装でも全テストが RED のまま)。
_Loaded = tuple[SignalGroup, Mapping[str, ColumnRecord]]


def _load(path: Path) -> _Loaded:
    """実 mf4 をロードし (group, 列表) を返す。

    ``confirm_expansion`` は既定 None なので**渡さない** — Task 8 が引数ごと退役
    させるときに、このファイルが取りこぼされて ``TypeError`` で落ちるのを防ぐ。
    """
    result = MdfLoader().load(path)
    sg = result.signal_group
    assert sg is not None
    return sg, result.column_records


def _manager(loaded: _Loaded) -> tuple[SignalGroupManager, str]:
    sg, records = loaded
    mgr = SignalGroupManager()
    return mgr, mgr.add(sg, column_records=records)


def _ns(key: str, name: str) -> str:
    return f"{key}{KEY_SEPARATOR}{name}"


def _mint(mgr: SignalGroupManager, key: str, name: str) -> Signal:
    got = mgr._mint_column(key, _ns(key, name))
    assert got is not None, f"{name} が鋳造されなかった"
    return got


def _only(loaded: _Loaded, keep: str) -> _Loaded:
    """物理チャンネルの代表列 1 本だけを残した (group, 列表) (T6 反転後の形の近似)。

    反転前の eager ローダーは全列を発行するので、そのまま add すると列キーが既存の
    namespaced map に当たり resolve() が鋳造経路へ落ちない。代表を 1 本だけ残すと
    残りの列キーが「map に無い実在の列キー」になり、resolve() 経由の鋳造
    (mint_count・副テーブルの寿命) を **実装のまま** 踏める。代表列は物理チャンネルの
    metadata (master・physical_channel) を運ぶ。列表は**物理チャンネル単位**なので
    signals を絞っても `Mat` のレコードはそのまま残る (絞る対象は signals だけ)。
    """
    sg, records = loaded
    return (
        dataclasses.replace(sg, signals=tuple(s for s in sg.signals if s.name == keep)),
        records,
    )


def test_minted_column_equals_the_eager_column(tmp_path: Path) -> None:
    """鋳造列は eager ローダーの列と等価 (値・dtype・metadata)。

    metadata を丸ごと突き合わせるのは、physical_channel/unit/source 系の継承と
    変換系キーの非継承を 1 本の独立参照で同時に固定するため。
    """
    loaded = _load(write_mdf4_2d(tmp_path))
    sg, _records = loaded
    mgr, key = _manager(loaded)
    eager = {s.name: s for s in sg.signals}
    assert {"Mat[0]", "Mat[1]", "Mat[2]", "Clean"} <= set(eager)

    for name in ("Mat[0]", "Mat[1]", "Mat[2]"):
        minted = _mint(mgr, key, name)
        assert minted.name == _ns(key, name)
        assert minted._values_source.is_materialized is False  # 構築は読まない
        np.testing.assert_array_equal(minted.values, eager[name].values)
        # native dtype 保持 (float64 へ upcast すると uint8 の 8 倍膨張が戻る)
        assert minted.values.dtype == np.uint8
        assert minted.values.dtype == eager[name].values.dtype
        assert minted.metadata == eager[name].metadata


def test_minted_column_shares_the_group_master_object(tmp_path: Path) -> None:
    """timestamps は親と同一オブジェクト。

    コピーすると source_info の id(s.timestamps) dedup (session.py) が静かに劣化し、
    時間範囲の算出が unique master ごと 1 回から列ごと 1 回へ戻る。
    """
    loaded = _load(write_mdf4_2d(tmp_path))
    sg, _records = loaded
    mgr, key = _manager(loaded)
    parent = next(s for s in sg.signals if s.metadata["physical_channel"] == "Mat")

    minted = _mint(mgr, key, "Mat[1]")
    assert minted.timestamps is parent.timestamps
    # 鋳造列は自分自身がその列の正典 -- namespaced ラッパーのような委譲を持たない
    assert getattr(minted, "_sorted_view_delegate", None) is None


def test_container_keys_are_not_columns(tmp_path: Path) -> None:
    """2-D / 構造化の**親**キーは列ではない (None)。

    親を鋳造すると 2-D 全体の float64 キャッシュ (prod で 96 MB/本) を掴む Signal が
    「プロットできる顔」で出てくる。
    """
    mgr, key = _manager(_load(write_mdf4_2d(tmp_path)))
    assert mgr._mint_column(key, _ns(key, "Mat")) is None
    # スカラーは「物理チャンネル == 列」なので鋳造対象にならない (map が先に当たる)
    assert mgr._mint_column(key, _ns(key, "Clean")) is None

    mgr2, key2 = _manager(_load(write_mdf4_structured(tmp_path)))
    assert mgr2._mint_column(key2, _ns(key2, "Pt")) is None


def test_structured_field_columns_are_minted(tmp_path: Path) -> None:
    loaded = _load(write_mdf4_structured(tmp_path))
    sg, _records = loaded
    mgr, key = _manager(loaded)
    eager = {s.name: s for s in sg.signals}
    for name in ("Pt.x", "Pt.y"):
        np.testing.assert_array_equal(
            _mint(mgr, key, name).values, eager[name].values
        )


def test_non_numeric_leaf_is_not_minted(tmp_path: Path) -> None:
    """非数値リーフで Signal を作らない (Q.tag は S2)。

    数値ゲートは parse_leaf/_consume が持つ -- 鋳造側で作れてしまうと eager が
    「非数値型のためスキップ」した列が裏口から復活する。
    """
    mgr, key = _manager(_load(write_mdf4_single_column_shapes(tmp_path)))
    assert mgr._mint_column(key, _ns(key, "Q.tag")) is None
    assert mgr._mint_column(key, _ns(key, "Q.x")) is not None


def test_dedup_display_names_mint_from_the_right_channel(tmp_path: Path) -> None:
    """LD-08 dedup + LD-14 展開の合成: 表示名 W[1] の列 [1] は **生名** W の列 [1]。

    dedup 済み表示名のまま parse_leaf へ引くと "W[1][1]" の先頭 "[1]" を W 自身の
    配列インデックスとして消費し、解決不能になるか **別チャンネルの列** を返す。
    値だけでどのチャンネルのどの列かが判る fixture で直接殺す。
    """
    loaded = _load(write_mdf4_dup_2d(tmp_path))
    sg, _records = loaded
    mgr, key = _manager(loaded)
    eager = {s.name: s for s in sg.signals}
    assert set(eager) == {"W[0][0]", "W[0][1]", "W[1][0]", "W[1][1]"}

    for name in eager:
        np.testing.assert_array_equal(
            _mint(mgr, key, name).values, eager[name].values
        )
    np.testing.assert_array_equal(
        _mint(mgr, key, "W[1][1]").values,
        np.array([101, 103, 105, 107], dtype=np.uint8),
    )


def test_minted_column_inherits_the_dedup_flag(tmp_path: Path) -> None:
    """physical_channel と name_deduplicated を継承する。

    落とすと E-2 比較モードが「同名信号」を跨ファイルで誤ペアリングする
    (name_deduplicated は自動重ねからの除外根拠)。
    """
    mgr, key = _manager(_load(write_mdf4_dup_2d(tmp_path)))
    minted = _mint(mgr, key, "W[1][0]")
    assert minted.metadata["physical_channel"] == "W[1]"
    assert minted.metadata["name_deduplicated"] is True

    mgr2, key2 = _manager(_load(write_mdf4_2d(tmp_path)))
    plain = _mint(mgr2, key2, "Mat[0]")
    assert plain.metadata["physical_channel"] == "Mat"
    assert "name_deduplicated" not in plain.metadata


def test_minted_column_does_not_inherit_conversion_metadata(tmp_path: Path) -> None:
    """LD-07: 変換情報と値ラベルは配列成分へ継承しない。

    展開チャンネルは raw_conversion=None で読まれるため、自然な fixture では親が
    そもそも変換 metadata を持たず assert が vacuous になる。契約を直接確かめる
    ために親の metadata dict へ強制的に載せる (metadata は可変 dict)。
    """
    loaded = _load(write_mdf4_2d(tmp_path))
    sg, _records = loaded
    mgr, key = _manager(loaded)
    parent = next(s for s in sg.signals if s.metadata["physical_channel"] == "Mat")
    parent.metadata["conversion_info"] = "<ChannelConversion linear>"
    parent.metadata["value_labels"] = {0.0: "OFF", 1.0: "ON"}

    minted = _mint(mgr, key, "Mat[2]")
    assert "conversion_info" not in minted.metadata
    assert "value_labels" not in minted.metadata
    assert minted.metadata["physical_channel"] == "Mat"  # 他は継承する
    assert minted.metadata is not parent.metadata  # dict を共有しない


def test_resolve_mints_a_column_missing_from_the_map(tmp_path: Path) -> None:
    """E-1 の「未配線ゆえ None」(test_resolver の旧 test_e1_mint_is_not_wired_yet) の反転。

    map に無い実在の列キーは鋳造され、同じキーは同じオブジェクトを返す。
    """
    mgr, key = _manager(_only(_load(write_mdf4_2d(tmp_path)), "Mat[0]"))

    col_key = _ns(key, "Mat[2]")
    got = mgr.resolve(col_key)
    assert got is not None
    assert mgr.mint_count == 1
    assert mgr.resolved_keys(key) == frozenset({col_key})
    assert mgr.resolve(col_key) is got  # 副テーブル経由で同一オブジェクト
    assert mgr.mint_count == 1
    np.testing.assert_array_equal(
        got.values, np.array([2, 12, 22, 32], dtype=np.uint8)
    )


def test_resolve_still_returns_none_for_unresolvable_keys(tmp_path: Path) -> None:
    mgr, key = _manager(_only(_load(write_mdf4_2d(tmp_path)), "Mat[0]"))
    assert mgr.resolve(_ns(key, "Mat[7]")) is None  # 幅 3 の範囲外
    assert mgr.resolve(_ns(key, "Nope")) is None  # 未知の物理チャンネル
    assert mgr.resolve(_ns(key, "Mat")) is None  # 親コンテナ
    assert mgr.mint_count == 0
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_mint_column.py -q`
Expected: FAIL — `_mint_column` は現在 hard-return `None` なので
`AssertionError: Mat[0] が鋳造されなかった`（`test_minted_column_equals_the_eager_column`）を筆頭に
鋳造系 8 本が RED。`test_container_keys_are_not_columns` /
`test_non_numeric_leaf_is_not_minted` / `test_resolve_still_returns_none_for_unresolvable_keys`
は**負の契約なので実装前も GREEN**（Step 5 の sabotage で歯があることを示す）。

> Task 1 が未 merge の場合は、ヘルパが表を渡す時点で
> `TypeError: SignalGroupManager.add() got an unexpected keyword argument 'column_records'`
> が先に出る（`column_records()` の `AttributeError` まで到達しない）。その場合は
> Task 1 を先に入れる（本タスクは T1 に依存）。

- [ ] **Step 3: 実装**

`src/valisync/core/loaders/signal_group_manager.py` の import と module 定数（1-8 行目付近）。
**置換ではなく追記**である — Task 1 が入れた `MappingProxyType` と
`ColumnRecord` / `leaf_count` / `leaf_names` を巻き戻すと、`_NO_COLUMN_RECORDS`・
`column_records`・`column_names_of`・`total_column_count`・`has_column` が同時に
`NameError` で全滅する。本タスクが**足すのは `parse_leaf` と `LazyMdfValues` の 2 語だけ**:

```python
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from types import MappingProxyType

from valisync.core.loaders.column_names import (
    ColumnRecord,
    leaf_count,
    leaf_names,
    parse_leaf,  # ← T2 で追加
)
from valisync.core.models import Signal, SignalGroup
from valisync.core.models.sample_source import LazyMdfValues  # ← T2 で追加

_FORMAT_KEY_PREFIX: dict[str, str] = {"MDF4": "mf4", "CSV": "csv"}
KEY_SEPARATOR = "::"
# 鋳造列が親から**継承してはならない** metadata (LD-07)。value2text と変換情報は
# スカラー enum の概念で、配列成分/構造化フィールドへ写すと「その列の値ラベル」と
# いう偽の意味を与える。eager ローダーも展開時は raw_conversion=None で継承を
# 止めている (mdf_loader._load_group) ので、鋳造側をそれに一致させる。
_UNINHERITED_METADATA = frozenset({"conversion_info", "value_labels"})
```

`_mint_column`（203-213 行目）を丸ごと置換し、直後にヘルパを追加:

```python
    def _mint_column(self, group_key: str, key: str) -> Signal | None:
        """列キーから Signal を鋳造する (解決できなければ None)。

        鋳造した Signal は列キーの**正典**であり (resolve は同じキーに同じオブジェクトを
        返す)、namespaced ラッパーと違って別の元 Signal を持たない --
        ``_sorted_view_delegate`` は付けない。
        """
        _prefix, sep, display_key = key.partition(KEY_SEPARATOR)
        if not sep:
            return None  # 名前空間の無いキーは列キーではない
        group = self._groups[group_key]
        handle = group.handle
        if handle is None:
            return None  # CSV/Derived は LD-14 の列文法を持たない
        records = self.column_records(group_key)
        # 親は **表示名** (LD-08 dedup 済み) の最長一致で確定する。表示名は物理
        # チャンネルごとに一意なので、parse_leaf 単体では避けられない生名衝突
        # (同名 2 チャンネルが同じ spec キーを共有する・column_names.parse_leaf の
        # precondition) をここで断てる。
        for i in range(len(display_key), 0, -1):
            record = records.get(display_key[:i])
            if record is None:
                continue
            rest = display_key[i:]
            if not rest:
                continue  # 表示名そのもの = 物理チャンネル (容器) であって列ではない
            # 二重名の契約: 表示名は dedup 済み名から、selector は **生チャンネル名**
            # から導く。両者は同じ suffix を共有する (ローダーの out_leaves と
            # sel_leaves は同一構造を同順に走査する)。dedup 済み表示名で parse_leaf を
            # 引くと "W[1][2]" の "[1]" を W 自身の配列インデックスとして消費し、
            # 解決不能になるか別チャンネルの列を返す。
            raw_leaf = f"{record.raw_base_name}{rest}"
            if parse_leaf(raw_leaf, {record.raw_base_name: record.spec}) is None:
                continue  # 消費しきれない / 非数値リーフ = この親では解決不能
            parent = self._physical_signal(group, display_key[:i])
            if parent is None:
                return None
            return Signal(
                name=key,
                # master は親と**同一オブジェクト**を渡す (source_info の
                # id(s.timestamps) dedup が同一性に依存する)。ローダーが read-only
                # 化済みなので Signal.__init__ はコピーしない。
                timestamps=parent.timestamps,
                values_source=LazyMdfValues(
                    handle,
                    record.raw_base_name,
                    record.group_index,
                    record.channel_index,
                    length=len(parent.timestamps),
                    selector=(raw_leaf,),
                ),
                file_format=parent.file_format,
                bus_type=parent.bus_type,
                source_file=parent.source_file,
                metadata={
                    k: v
                    for k, v in parent.metadata.items()
                    if k not in _UNINHERITED_METADATA
                },
            )
        return None

    @staticmethod
    def _physical_signal(group: SignalGroup, display_name: str) -> Signal | None:
        """物理チャンネル ``display_name`` を代表する Signal (継承元)。

        反転後は「物理チャンネル 1 本 = Signal 1 個」なので name 一致でも当たるが、
        反転前 (ローダーが列を発行している間) はその名前の Signal が存在しない。
        どちらでも同じ答え (master・file_format・bus_type・source_file・unit 等は
        チャンネル単位で不変) が要るので ``metadata['physical_channel']`` で引く。
        走査は列キーごとに 1 回だけ (結果は ``_resolved_by_key`` が保持する)。
        """
        for sig in group.signals:
            if sig.metadata.get("physical_channel") == display_name:
                return sig
        return None
```

続けてテストダブルを実装へ差し替える。

`tests/core/loaders/test_resolver.py`:

1. import に `import dataclasses` と
   `from tests.mdf4_helpers import write_mdf4_2d` /
   `from valisync.core.loaders.mdf_loader import MdfLoader` を追加（`_sig` / `_group` は残す）。
2. `_MintingManager`（41-52 行）を削除し、代わりに（`SignalGroup` の import は
   `_group` が返り値注釈で使い続けるので残す）:

```python
def _add_real(mgr: SignalGroupManager, tmp_path: Path) -> str:
    """実 mf4 (Mat 3 列 + Clean) を読み、代表列 Mat[0] だけを残して **表ごと** 登録する。

    反転前の eager ローダーは全列を発行するので、そのまま add すると列キーが既存 map に
    当たり鋳造経路を踏めない。代表 1 本だけ残すと Mat[1]/Mat[2] が「map に無い実在の
    列キー」になり、副テーブルの寿命を **実装の鋳造** で検証できる。テストダブルで
    鋳造を偽装すると、寿命は緑のまま鋳造の中身が壊れていても気づけない。

    ``column_records`` を渡すのが要点: 表は manager 側にあり、渡さないと
    ``_mint_column`` の先頭で表が空になって**正しい実装でも常に None** を返す
    (寿命テストが「鋳造できないから空」で通ってしまう)。``confirm_expansion`` は
    既定 None なので渡さない (Task 8 の引数退役で取りこぼさないため)。
    """
    result = MdfLoader().load(write_mdf4_2d(tmp_path))
    sg = result.signal_group
    assert sg is not None
    return mgr.add(
        dataclasses.replace(
            sg, signals=tuple(s for s in sg.signals if s.name == "Mat[0]")
        ),
        column_records=result.column_records,
    )
```

3. `test_e1_mint_is_not_wired_yet`（68-74 行）を差し替え:

```python
def test_synthetic_group_without_records_never_mints() -> None:
    """ColumnRecord 表もハンドルも無いグループ (CSV / 合成) は列を鋳造しない。

    E-1 では「実装が常に None を返す」ことの pin だったが、鋳造が配線された今は
    「MDF の列文法を持たないグループには当てない」という契約になる。
    """
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))
    assert mgr.resolve(f"{key}::Mat[7]") is None
    assert mgr.mint_count == 0
    assert mgr.resolved_keys(key) == frozenset()
```

4. `_MintingManager` を使っていた 6 本を実 manager へ。列キーは実在する `Mat[2]` にする
   （登録は必ず `_add_real` 経由 — 素の `mgr.add(sg)` は列表を落として鋳造を殺す）:

```python
def test_resolved_table_survives_unrelated_add_and_remove(tmp_path: Path) -> None:
    # Critical 1: 無関係なファイルの load/remove で副テーブルを捨ててはならない
    mgr = SignalGroupManager()
    k1 = _add_real(mgr, tmp_path)
    col_key = f"{k1}::Mat[2]"  # 既存 map に無い列キー -> 鋳造経路
    first = mgr.resolve(col_key)
    assert first is not None
    assert mgr.mint_count == 1
    _ = first.values  # 実際に読ませる (再鋳造されると読み直しになる)
    assert first._values_source.is_materialized is True

    k2 = mgr.add(_group("Other"))  # 2 ファイル目ロード相当
    again = mgr.resolve(col_key)
    assert again is first  # 同一オブジェクト
    assert again._values_source.is_materialized is True  # 読み直していない
    assert mgr.mint_count == 1  # 再鋳造していない

    mgr.remove(k2)  # 2 ファイル目 unload 相当
    assert mgr.resolve(col_key) is first
    assert mgr.mint_count == 1


def test_removing_own_group_drops_its_resolved_table(tmp_path: Path) -> None:
    mgr = SignalGroupManager()
    k1 = _add_real(mgr, tmp_path)
    col_key = f"{k1}::Mat[2]"
    mgr.resolve(col_key)
    assert mgr.resolved_keys(k1) == frozenset({col_key})
    mgr.remove(k1)
    assert mgr.resolve(col_key) is None
    assert mgr.resolved_keys(k1) == frozenset()


def test_remove_returns_minted_columns_for_teardown(tmp_path: Path) -> None:
    """列 Signal は SignalGroup.signals の外に居るため remove() が返さないと
    TeardownService の会計・解放から漏れる。"""
    mgr = SignalGroupManager()
    k1 = _add_real(mgr, tmp_path)
    minted = mgr.resolve(f"{k1}::Mat[2]")
    group, columns = mgr.remove(k1)
    assert group.signals[0].name == "Mat[0]"
    assert columns == (minted,)


def test_resolved_keys_does_not_mint(tmp_path: Path) -> None:
    mgr = SignalGroupManager()
    k1 = _add_real(mgr, tmp_path)
    before = mgr.mint_count
    _ = mgr.resolved_keys(k1)
    assert mgr.mint_count == before


def test_signal_map_lookup_falls_through_to_resolver(tmp_path: Path) -> None:
    """`[]`/`get` は既存 map に無いキーを解決器へ落とす (約20箇所の呼出を無改造にする要)。"""
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    m = mgr.signal_map()

    assert m.get(f"{key}::Mat[0]") is not None  # 物理キー
    assert mgr.mint_count == 0  # 物理キーは解決器を通さない

    minted = m.get(f"{key}::Mat[2]")  # 既存 map に無い列キー
    assert minted is not None
    assert mgr.mint_count == 1  # 解決器を通った
    assert m[f"{key}::Mat[2]"] is minted  # `[]` も同じ経路・同一オブジェクト
    assert mgr.mint_count == 1


def test_signal_map_contains_falls_through_but_not_for_physical_keys(
    tmp_path: Path,
) -> None:
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    m = mgr.signal_map()

    assert f"{key}::Mat[0]" in m
    assert mgr.mint_count == 0  # 既存キーの `in` は鋳造しない
    assert f"{key}::Mat[2]" in m  # 列キーは解決器へ落ちる
    assert mgr.mint_count == 1
    assert "mf4_9::Nope" not in m  # 未ロードグループ


def test_signal_map_enumeration_does_not_mint(tmp_path: Path) -> None:
    # 列挙は物理のみ: dict(m) が 330k 列を鋳造したら 390 MB を再導入してしまう
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    m = mgr.signal_map()
    before = mgr.mint_count
    assert list(m) == [f"{key}::Mat[0]"]
    assert len(m) == 1
    assert set(m.keys()) == {f"{key}::Mat[0]"}
    assert set(dict(m)) == {f"{key}::Mat[0]"}
    assert mgr.mint_count == before


def test_signal_map_enumeration_excludes_already_minted_columns(
    tmp_path: Path,
) -> None:
    """鋳造済みの列も列挙には現れない (物理キーのみ)。"""
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    m = mgr.signal_map()
    assert m.get(f"{key}::Mat[2]") is not None  # 鋳造させる
    assert mgr.mint_count == 1
    assert list(m) == [f"{key}::Mat[0]"]
    assert len(m) == 1
```

`tests/gui/viewmodels/test_signal_map_overlay.py`:

1. `import datetime` を削除し `import dataclasses` を追加、
   `from valisync.core.models import Signal, SignalGroup` を
   `from valisync.core.models import Signal` へ（`SignalGroup` は未使用になる）、
   `from tests.mdf4_helpers import write_mdf4_2d` と
   `from valisync.core.loaders.mdf_loader import MdfLoader` を追加。`Path` は型注釈で使うので残す。
2. `_MintingManager` と `_manager_with`（213-234 行）を置換:

```python
def _resolving_manager(tmp_path: Path) -> tuple[SignalGroupManager, str]:
    """実 mf4 の代表列 1 本だけを持つ manager (Mat[1]/Mat[2] が鋳造経路)。

    E-1 のテストダブル (常に Signal を返す `_mint_column` の上書き) は overlay の
    合成しか見ておらず、鋳造そのものが壊れても緑のままだった。T2 で実装が入ったので
    実 mf4 の鋳造へ差し替える。

    ``column_records`` を渡し忘れると表が空になり、正しい実装でも `_mint_column` が
    常に None を返す (overlay 側のテストが「解決できないだけ」で緑にならず全 RED)。
    """
    result = MdfLoader().load(write_mdf4_2d(tmp_path))
    sg = result.signal_group
    assert sg is not None
    mgr = SignalGroupManager()
    key = mgr.add(
        dataclasses.replace(
            sg, signals=tuple(s for s in sg.signals if s.name == "Mat[0]")
        ),
        column_records=result.column_records,
    )
    return mgr, key
```

3. 続く 3 本を `tmp_path` 受け取りに変え、列キーを `Mat[7]` → `Mat[2]`、
   タイムスタンプ期待値を fixture の実値へ:

```python
def test_overlay_over_resolving_base_enumerates_physical_keys_only(
    tmp_path: Path,
) -> None:
    """`len()`/`iter()` は overlay 越しでも「物理キー」のままで鋳造しない。"""
    mgr, key = _resolving_manager(tmp_path)
    vm, _session = _vm(mgr.signal_map(), {key: 1.0}, {})
    sm = vm._signal_map()  # type: ignore[attr-defined]

    before = mgr.mint_count
    assert len(sm) == 1
    assert list(sm) == [f"{key}::Mat[0]"]
    assert mgr.mint_count == before  # 列挙は鋳造しない

    # 鋳造済みの列があっても列挙は物理キーのみ
    assert sm[f"{key}::Mat[2]"] is not None
    assert mgr.mint_count == before + 1
    assert len(sm) == 1
    assert list(sm) == [f"{key}::Mat[0]"]


def test_overlay_over_resolving_base_applies_offset_to_minted_column(
    tmp_path: Path,
) -> None:
    """overlay 越しのルックアップは列を解決し、その列にもオフセットを適用する。"""
    mgr, key = _resolving_manager(tmp_path)
    vm, session = _vm(mgr.signal_map(), {key: 1.0}, {})
    sm = vm._signal_map()  # type: ignore[attr-defined]

    col_key = f"{key}::Mat[2]"
    col = sm.get(col_key)
    assert col is not None  # 解決器へフォールスルーした
    np.testing.assert_allclose(col.timestamps, np.array([0.0, 0.1, 0.2, 0.3]) + 1.0)
    assert session.offset_calls == [(col_key, 1.0, 0.0)]


def test_overlay_over_resolving_base_returns_none_for_unresolvable_key(
    tmp_path: Path,
) -> None:
    """解決不能キーは overlay 越しでも None (KeyError を漏らさない)。"""
    mgr, key = _resolving_manager(tmp_path)
    vm, _session = _vm(mgr.signal_map(), {key: 1.0}, {})
    sm = vm._signal_map()  # type: ignore[attr-defined]

    assert sm.get("mf4_9::Nope") is None  # 未ロードグループ
    assert "mf4_9::Nope" not in sm
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/core/loaders/test_mint_column.py tests/core/loaders/test_resolver.py tests/gui/viewmodels/test_signal_map_overlay.py -q`
Expected: PASS（全 25 本前後）。

続けて production 無影響を確認:

Run: `uv run pytest tests/core tests/gui tests/test_session.py -q`
Expected: PASS。特に既存の
`tests/gui/test_channel_browser_physical.py::test_single_column_rows_carry_the_real_column_identity`
は「合成した親キー (`g::Mono` / `g::P` / `g::Q`) が `signal_map().get()` で **None**」を
production 側から要求する第 2 の防波堤になる — ここが赤くなったら親コンテナの
`if not rest: continue` を落としている。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

1. `parse_leaf(raw_leaf, {record.raw_base_name: record.spec})` を
   `parse_leaf(display_key, {k: r.spec for k, r in records.items()})` に替え、返り値の
   base をそのまま selector の生名に使う（= 表示名キー空間での逆変換）→
   `test_dedup_display_names_mint_from_the_right_channel` が RED
   （`W[1][1]` の selector が `_flatten("W", ...)` に無く `SampleReadError`）。
2. `timestamps=parent.timestamps` → `timestamps=parent.timestamps.copy()` →
   `test_minted_column_shares_the_group_master_object` が RED（`is` が False）。
3. `metadata={...}` の内包表記を `metadata=dict(parent.metadata)` に →
   `test_minted_column_does_not_inherit_conversion_metadata` が RED。
4. `if not rest: continue` を削除（親も鋳造する）→
   `test_container_keys_are_not_columns` と既存の
   `test_single_column_rows_carry_the_real_column_identity` が RED。
5. `parse_leaf(...) is None` の `continue` を削除（数値ゲート無視）→
   `test_non_numeric_leaf_is_not_minted` が RED。
6. 鋳造 Signal に `object.__setattr__(sig, "_sorted_view_delegate", parent)` を足す →
   `test_minted_column_shares_the_group_master_object` の delegate assert が RED。

各 sabotage は 1 つずつ入れて RED を確認し、必ず戻す（`git diff` が空であることを確認）。

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

すべて exit 0 を確認してから:

```bash
git add src/valisync/core/loaders/signal_group_manager.py \
        tests/core/loaders/test_mint_column.py \
        tests/mdf4_helpers.py \
        tests/core/loaders/test_resolver.py \
        tests/gui/viewmodels/test_signal_map_overlay.py
git commit -m "$(cat <<'EOF'
feat(core): 列キーからの Signal 鋳造を実装 (_mint_column)

表示名 (LD-08 dedup 済み) の最長一致で親 ColumnRecord を確定し、生チャンネル名の
1 エントリだけを parse_leaf へ渡して列を逆変換する (表示名キー空間で引くと
"W[1][2]" の "[1]" を W 自身の配列インデックスとして消費し別チャンネルの列を返す)。
鋳造 Signal は master を親と同一オブジェクトで共有し (source_info の id() dedup)、
physical_channel/name_deduplicated を継承しつつ変換情報と値ラベルは継承しない
(LD-07)。native dtype 保持・_sorted_view_delegate なし。

反転前は _namespaced_map が先に当たるため production 挙動は不変。eager 実装が
同居している間に「鋳造列 == eager の列」(値・dtype・metadata) を独立オラクルとして
固定し、テストダブル _MintingManager を実 mf4 の鋳造へ差し替えた。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 3: teardown 配線（E-3 tripwire 撤去＋2 サイト＋`enqueue` の列受け口）

> **なぜ反転より前か**: T2 が `_mint_column` から非 None を返した瞬間、列を 1 本でも解決したファイルの
> unload が production で raise する。しかも raise は `self._releasing[key] = name`（`app_viewmodel.py:265`）の
> **後**・`enqueue`（`:276`）の**前**なので、`result` がスコープアウトして removed_group + 鋳造列が
> **GUI スレッドで同期解放**される（FU-16 の再来）。excepthook は `SampleReadError` 以外を前フックへ委譲する
> （`main_window.py:553-563`）ため、ユーザーには例外もダイアログも出ず**無音のフリーズだけ**が残る。
> 反転前は `removed_columns` が常に `()` なので production 挙動は不変＝単独 merge 可。

**Files:**
- Modify: `src/valisync/gui/workers/teardown_service.py:122-133`（`enqueue` に `columns` 引数）
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py:61`・`:168-170`・`:264-278`（tripwire 撤去→実配線）
- Modify: `src/valisync/gui/views/main_window.py:637-653`（`_discard` = 2 サイト目）
- Test: `tests/gui/test_teardown_service.py`（`test_empty_group_finishes_immediately`＝現行 94-99 行の直後に 3 本追加）
- Test: `tests/gui/test_discard_teardown.py:14`（`import pytest` 削除）・`:109-117`（`_DummyTeardown`）・`:158-177`（書き換え）＋新規 1 本
- Test: `tests/gui/test_app_viewmodel.py:287-292`（`_FakeTeardown` 署名追随）
- Test: `tests/gui/test_file_browser_vm.py:145-147`・`:226-228`（`_Fake` 署名追随）
- Test: `tests/gui/test_file_browser_view.py:56-58`（`_Fake` 署名追随）

**Interfaces:**
- Consumes: `RemovalResult.removed_columns: tuple[Signal, ...]`（E-1 で新設済み・`session.py:91`／`remove_group` が
  `SignalGroupManager.remove(key) -> tuple[SignalGroup, tuple[Signal, ...]]` から詰めて返す `session.py:325,341-346`）
- Produces: `TeardownService.enqueue(key: str, group: SignalGroup, columns: tuple[Signal, ...] = ()) -> None`
  （**duck-typed 注入先の契約**。`AppViewModel._teardown` に注入される全テストダブルもこの署名に従う。
  T6 の反転後にこの `columns` が初めて非空になる — T6 は本タスクの配線を前提にしてよい）

- [ ] **Step 1: 失敗テストを書く**

**(1-a)** `tests/gui/test_teardown_service.py` — `test_empty_group_finishes_immediately`（現行 94-99 行）の直後に 3 本追加する。
`gc` / `weakref` / `_sig` / `_group` / `_drain_all` は同ファイルの既存定義をそのまま使う:

```python
def test_minted_columns_drain_in_the_same_entry_and_finish_once(qtbot) -> None:
    """E-3: 鋳造列 (SignalGroup.signals の外) も同じペーシングで解放され、
    on_finished は 1 回だけ発火する。

    同一 key を 2 エントリに分けると 1 本目の完了で on_finished が撃たれ、その宛先の
    AppViewModel.mark_released は初回 pop で確定する (app_viewmodel.py:212-215) ので、
    列がまだ残っているのに releasing 行が消える。だから列は同じエントリへ連結する。
    """
    done: list[str] = []
    svc = TeardownService(on_finished=done.append, byte_budget=1 * 1024 * 1024)
    col = _sig("mf4_1::W[1]", 500_000)
    ref = weakref.ref(col.values)
    grp = _group((_sig("s", 500_000),))

    svc.enqueue("g", grp, columns=(col,))

    assert svc.pending_signals() == 2  # グループ 1 本 + 列 1 本
    assert done == []  # まだ 1 本も解放していない
    del grp, col
    _drain_all(svc, qtbot)
    gc.collect()
    assert done == ["g"]  # エントリが 1 つ = 発火も 1 回
    assert ref() is None  # 列の配列が実際に解放された (会計だけでなく解放も通っている)


def test_zero_columns_do_not_finish_a_still_draining_group_early(qtbot) -> None:
    """列ゼロの通常ファイルで on_finished が早期発火しない。

    列を「もう 1 つのエントリ」として積む実装だと、空タプルが即時 finish 分岐
    (enqueue の `if not sigs`) に落ち、グループがまだドレイン中なのに releasing
    スピナーが消える。列ゼロは production の既定経路なので、ここが本命の回帰点。
    """
    done: list[str] = []
    svc = TeardownService(on_finished=done.append, byte_budget=1 * 1024 * 1024)

    svc.enqueue("g", _group((_sig("a", 500_000), _sig("b", 500_000))), columns=())

    assert done == []  # ドレイン前に「解放完了」を宣言していない
    _drain_all(svc, qtbot)
    assert done == ["g"]


def test_columns_alone_do_not_take_the_empty_group_shortcut(qtbot) -> None:
    """signals が空で列だけ残るグループも即時 finish にしない。

    pin しているのは実データの形ではなく **extend が空判定より前にあること**そのもの:
    順序が逆だと列がペーシングを迂回して同期解放される (列は実体化済み = バイトが重い)。
    """
    done: list[str] = []
    svc = TeardownService(on_finished=done.append)
    col = _sig("mf4_1::W[1]", 1_000)

    svc.enqueue("g", _group(()), columns=(col,))

    assert done == []
    assert svc.pending_signals() == 1
    del col
    qtbot.waitUntil(lambda: svc.pending_signals() == 0, timeout=5000)
    assert done == ["g"]
```

**(1-b)** `tests/gui/test_discard_teardown.py` — `_DummyTeardown`（109-117 行）を引数記録型に置換:

```python
class _DummyTeardown:
    """duck-typed teardown — enqueue(key, group, columns=...) の実引数をそのまま記録する。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, SignalGroup, tuple[Signal, ...]]] = []

    def enqueue(
        self, key: str, group: SignalGroup, columns: tuple[Signal, ...] = ()
    ) -> None:
        self.calls.append((key, group, columns))
```

**(1-c)** 同ファイル 158-177 行の `test_minted_columns_trip_the_e3_wire` を**丸ごと**次の 2 本に置換する
（tripwire は本タスクで役目を終える。`pytest.raises` が消えるので**ファイル冒頭 14 行の `import pytest` も削除**する
— 他に `pytest.` の使用は無く、残すと ruff F401）:

```python
def test_minted_columns_are_handed_to_the_teardown_service(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """E-3 本命: 鋳造列も同じ enqueue で TeardownService へ渡る。

    渡さないと result のスコープアウトで GUI スレッドの同期解放になる (プロット済み列は
    実体化済み = バイトが重い → FU-16 のフリーズが戻る)。E-1 では loud-fail の tripwire で
    代用していたが、本タスクで実配線に置き換える。
    """
    # _loaded は tests/gui/test_unload_export_guard.py と同型
    app_vm, key, _handle = _loaded(tmp_path)
    dummy = _DummyTeardown()
    app_vm.set_teardown(dummy)
    column = _minted_column(f"{key}::Spd[7]")
    app_vm.session._groups._resolved_by_key.setdefault(key, {})[column.name] = column

    app_vm.unload_file(key)

    assert len(dummy.calls) == 1  # 同一 key を 2 エントリに割らない
    got_key, got_group, got_columns = dummy.calls[0]
    assert got_key == key
    assert got_group is not None  # グループ本体は従来どおり渡る
    assert got_columns == (column,)  # 鋳造列が同じ呼び出しに乗る


def test_discard_also_hands_the_minted_columns(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """2 サイト目 (_discard) も列を渡す。

    session.load はグループ登録 (session.py:170) の**後**にキャンセルが確定するので、その窓で
    resolve された列は実在しうる。_discard は AppViewModel を経由しないため、unload_file 側の
    配線では 1 バイトもカバーされない。
    """
    win, outcome, n_signals, discard = _loaded_but_discarded_setup(qtbot, tmp_path)
    win.teardown_service._timer.stop()  # ドレインを止めて手渡しだけを見る
    column = _minted_column(f"{outcome.key}::Sig0[1]")
    resolved = win.app_vm.session._groups._resolved_by_key
    resolved.setdefault(outcome.key, {})[column.name] = column

    discard(outcome)

    assert win.teardown_service.pending_signals() == n_signals + 1
```

**(1-d)** duck-type 注入は型検査が効かない（`_teardown: object` ＋ `# type: ignore[attr-defined]`）ので、
**全テストダブルを新署名へ追随させる**。追随を怠ると当該テストは `TypeError: ... unexpected keyword argument 'columns'` で落ちる:

`tests/gui/test_app_viewmodel.py:287-292`:

```python
class _FakeTeardown:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def enqueue(self, key, group, columns=()) -> None:
        self.calls.append((key, group))
```

`tests/gui/test_file_browser_vm.py:145-147` と `:226-228`（2 箇所とも）・`tests/gui/test_file_browser_view.py:56-58`:

```python
    class _Fake:
        def enqueue(self, key: str, group: object, columns: object = ()) -> None:
            pass
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_teardown_service.py -q`
Expected: 追加 3 本が FAIL with `TypeError: TeardownService.enqueue() got an unexpected keyword argument 'columns'`
（既存 6 本は PASS のまま＝回帰ロック）。

Run: `uv run pytest tests/gui/test_discard_teardown.py -q`
Expected:
- `test_minted_columns_are_handed_to_the_teardown_service` が FAIL with
  `AssertionError: E-3: 鋳造列は TeardownService へ渡すこと (未配線のまま鋳造を有効化するとペーシングを迂回する)`
  （tripwire がまだ生きている）。
- `test_discard_also_hands_the_minted_columns` が FAIL with `assert 5 == 6`
  （`_discard` が `removed_columns` を捨てている）。
- 既存 3 本（`test_discard_hands_the_group_to_the_teardown_service` 他）は PASS。

- [ ] **Step 3: 実装**

**(3-a)** `src/valisync/gui/workers/teardown_service.py:122-133` の `enqueue` を置換:

```python
    def enqueue(
        self, key: str, group: SignalGroup, columns: tuple[Signal, ...] = ()
    ) -> None:
        """*key* のグループ信号 + 鋳造列 (E-3) を 1 エントリとして積む。

        `columns` は `SignalGroup.signals` の外に居る鋳造列
        (`RemovalResult.removed_columns`)。**同一エントリへ連結する**のが要点:
        `on_finished` はエントリごとに発火し、その宛先の `AppViewModel.mark_released`
        は初回 pop で確定する (app_viewmodel.py:212-215) ため、同じ key を 2 エントリに
        分けると 1 本目の完了で releasing 行が消え、列がまだ残っているのに「解放完了」に
        見える。

        O(1) 契約は維持する: `list(group.signals)` も `extend(columns)` も C レベルの
        ポインタコピーだけで、信号の配列には一切触れない (nbytes 走査と解放は _drain の
        担当のまま)。`columns` は解決済み列 = プロット/読み値/エクスポートで触れた列だけで、
        全論理列ではない。
        """
        sigs = list(group.signals)  # single C-level copy -- no per-signal loop
        # extend は**空判定より前**に置く。後ろだと「signals が空で列だけ残る」グループが
        # 下の即時 finish 分岐に落ち、列がペーシングを迂回して同期解放される (実体化済みの
        # 列はバイトが重い)。エントリ内の順序は無関係 — _drain は末尾から pop する。
        sigs.extend(columns)
        if not sigs:
            if self._on_finished is not None:
                self._on_finished(key)
            return
        self._pending_signals += len(sigs)
        self._groups.append((key, sigs))
        # NOTE: caller must not keep a ref to `group` / `columns` after this (it does
        # not -- both hang off the RemovalResult local that falls out of scope);
        # `sigs` becomes the sole owner, so popping from it frees the arrays.
        if not self._timer.isActive():
            self._timer.start()
```

**(3-b)** `src/valisync/gui/viewmodels/app_viewmodel.py:264-278` の tripwire ブロックを実配線に置換:

```python
        if result.removed_group is not None and self._teardown is not None:
            self._releasing[key] = name
            # 鋳造列 (E-1) は SignalGroup.signals の外に居るので、渡さないと result の
            # スコープアウトで GUI スレッドの同期解放になる (プロット済み列は実体化済み
            # = バイトが重い → FU-16 のフリーズが戻る)。columns は**常に**渡す: 空の
            # ときだけ省く形にすると、鋳造が生きるまでこの実引数が一度も評価されず、
            # テストダブルの署名ドリフトが無音で残る。MainWindow._discard の
            # remove_group(force=True) も同じ配線を持つ (AppViewModel を経由しない
            # 2 サイト目)。
            self._teardown.enqueue(  # type: ignore[attr-defined]
                key, result.removed_group, columns=result.removed_columns
            )
            self._notify("releasing")
        # else: removed_group falls out of scope here -> immediate sync free.
```

同ファイル 61 行のコメントと 169 行の docstring も新署名へ:

```python
        self._teardown: object | None = None  # duck-typed: enqueue(key, group, columns)
```

```python
    def set_teardown(self, service: object) -> None:
        """Inject the GUI-thread teardown service.

        duck-typed ``enqueue(key, group, columns=())`` — ``columns`` は鋳造列
        (``RemovalResult.removed_columns``) で、グループ信号と同じペーシングに乗せる。
        """
        self._teardown = service
```

**(3-c)** `src/valisync/gui/views/main_window.py:637-653` の `_discard`。末尾 4 行のコメント
（「E-3 の 2 サイト目: 鋳造列が生きたら…」＝逆参照の警告）を実配線の WHY に置き換える:

```python
        def _discard(outcome: LoadOutcome) -> None:
            # 増分B: 手遅れ完走のロールバック。Task 1 で handle は remove_group が
            # 閉じるが、シェルの解放を放置すると GUI スレッドで同期実行される
            # (330k シェルで実測 649ms)。AppViewModel は経由しない — このファイルは
            # loaded_keys に載っていないので releasing スピナー行を出してはいけない。
            # _discard は LoadController._finish (queued 接続スロット) から呼ばれる
            # = GUI スレッドなので、QTimer を持つ enqueue をここで呼んでよい。
            # なお本経路はエクスポートガードの対象外: このグループは register_loaded を
            # 通らず、エクスポートツリーの唯一のソース (app_vm.loaded_file_keys ->
            # export_csv_dialog.py:114) に載らないためエクスポート中になり得ない。
            # 鋳造列も渡す (E-3 の 2 サイト目): session.load はグループ登録の**後**に
            # キャンセルが確定するので、その窓で resolve された列は実在しうる。
            result = session.remove_group(outcome.key, force=True)
            if result.removed_group is not None:
                self.teardown_service.enqueue(
                    outcome.key, result.removed_group, columns=result.removed_columns
                )
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/gui/test_teardown_service.py tests/gui/test_teardown_pacing.py tests/gui/test_teardown_lazy.py tests/gui/test_discard_teardown.py -q`
Expected: PASS（ペーシング 3 軸・identity dedup・遅延非展開の既存契約は無改造で通る）。

Run: `uv run pytest tests/gui/ tests/test_session.py -q`
Expected: PASS（署名追随を漏らしたダブルがあると
`TypeError: ... unexpected keyword argument 'columns'` で落ちるので、ここで全数を洗う）。

- [ ] **Step 5: sabotage で honest-RED を確認（必須・結果を報告に記す）**

4 種を順に実施し、確認したら戻す:

1. `app_viewmodel.py` の `columns=result.removed_columns` を落として `enqueue(key, result.removed_group)` に戻す →
   `test_minted_columns_are_handed_to_the_teardown_service` が `got_columns == ()` で **RED**
   （他は緑＝ VM サイトが単独で被覆されている証明）。
2. `main_window.py::_discard` の `columns=` を落とす → `test_discard_also_hands_the_minted_columns` が
   `assert 5 == 6` で **RED**（1 の VM 側テストは緑のまま＝ 2 サイトが独立に被覆されている証明）。
3. `enqueue` の `sigs.extend(columns)` を `if not sigs:` ブロックの**後ろ**へ移す →
   `test_columns_alone_do_not_take_the_empty_group_shortcut` が `assert done == []` で **RED**
   （即時 finish 分岐に落ちて列が積まれない）。
4. `enqueue` の連結を「key ごと 2 エントリ」に変える
   （`for batch in (list(group.signals), list(columns)):` の中で空 batch を即時 finish・非空 batch を
   `self._groups.append((key, batch))`）→
   `test_zero_columns_do_not_finish_a_still_draining_group_early` が enqueue 直後に `done == ["g"]` で **RED**、
   かつ `test_minted_columns_drain_in_the_same_entry_and_finish_once` が `done == ["g", "g"]` で **RED**。

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add src/valisync/gui/workers/teardown_service.py \
        src/valisync/gui/viewmodels/app_viewmodel.py \
        src/valisync/gui/views/main_window.py \
        tests/gui/test_teardown_service.py tests/gui/test_discard_teardown.py \
        tests/gui/test_app_viewmodel.py tests/gui/test_file_browser_vm.py \
        tests/gui/test_file_browser_view.py
git commit -m "feat(gui): 鋳造列を TeardownService へ配線 (E-3 tripwire 撤去・unload/_discard の 2 サイト・enqueue に columns)"
```

---

### Task 4: ChannelBrowserVM の列ソースを `ColumnRecord` 由来へ（spec 追補 S1）

**Files:**
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py:1-7`（モジュール docstring）, `:11-19`（import）, `:21-24`（`_PrepRow`）, `:75-103`（`__init__`）, `:105-128`（`_invalidate_prep`）, `:130-190`（`_ensure_prep`）, `:192-221`（`_ensure_filter_memo` docstring）, `:223-262`（`_scan_filter`）, `:291-320`（`column_names_for`）, `:324-345`（`_group_total`）, `:408-419`（`_signal_by_key`）
- Test: `tests/gui/test_channel_browser_physical.py:274-297`（`test_invalidate_prep_releases_the_column_signals` を強化版へ置換）＋末尾に新セクション追記
- Test（無回帰のみ・**T4 では編集しない**）: `tests/gui/test_channel_browser_vm.py`, `tests/gui/test_channel_browser_view.py`, `tests/gui/test_signal_tree_model.py` — いずれも T6 が反転後の形へ fixture を flip する（T4 の受理根拠は「flip 前のこれらが無改造で GREEN」であること）

**Interfaces:**
- Consumes（Task 1 が新設）:
  - `Session.column_names_of(key: str, display_name: str) -> tuple[str, ...]` — 数値リーフの表示名タプル。スカラーは `(display_name,)`。**本タスクは追加で 2 つの振る舞いに依存する**: (a) ColumnRecord 表を持たないローダー（CSV/Derived）でも `(display_name,)` を返すか `KeyError` を投げるかのどちらかであること（両方を Task 4 側で同一に扱う）、(b) セッション未登録のグループキーに対しても例外は `KeyError` に限ること。この依存は Step 1 の `test_csv_group_falls_back_to_the_observed_columns` が直接 pin する。
  - `Session.total_column_count(key: str) -> int` — U2 の母数。**production コードからは呼ばない**（理由は下の `_group_total` docstring）。`_group_total()` と一致することを契約テストで pin する用途にのみ使う。
  - `Session.resolve_signal(key: str) -> Signal | None`（既存 E-1）。
  - `Session.group_signals(key: str) -> list[Signal]`（既存）— 行（物理チャンネル）の出所として残す。**列の出所ではなくなる**。
- Produces（後続タスクが依存）:
  - `ChannelBrowserVM.tree_groups() -> list[tuple[str, str, str, int, tuple[str, str] | None]]` — 契約不変（`SignalTreeModel._rebuild` `src/valisync/gui/adapters/signal_tree_model.py:92-108` はそのまま）。
  - `ChannelBrowserVM.column_names_for(base_key: str) -> list[tuple[str, str, str]]` — 契約不変（`(orig, unit, key)`）。`SignalTreeModel._materialize` `:112-128` の唯一の子供源。
  - 新設の private: `ChannelBrowserVM._columns_of(group_key: str, display_name: str) -> tuple[str, ...] | None` / `._column_key(column_name: str) -> str` / `._total_columns() -> int`。
  - 内部型変更: `_PrepRow = tuple[str, str, str, tuple[str, ...]]`（旧 6 要素・`spans` と `first_column` を廃止）。`_group_sigs` フィールドは削除。

---

- [ ] **Step 1: 失敗テストを書く**

まず `tests/gui/test_channel_browser_physical.py` の import を差し替える（先頭 1-15 行）:

```python
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
```

次に `:274-297` の `test_invalidate_prep_releases_the_column_signals` を**丸ごと**以下へ置換する（元の assert は「列 Signal を掴んだ後に手放す」を見ていた。列ソースが ColumnRecord になると VM は列 Signal を一度も掴まないので、条件は「掴まない」へ**強まる** — 弱めていない）:

```python
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
```

最後に、ファイル末尾へ新セクションを追記する:

```python
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
    観測名をそのまま葉キーにすると実在しないキー (mf4_1::Mono) を晒す＝
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
    """
    vm, app_vm = _vm_for(write_mdf4_2d(tmp_path))
    key = app_vm.active_file_key or ""
    _invert_to_physical_signals(app_vm, key)
    vm.refresh()

    tip = vm.tooltip_for(f"{key}{KEY_SEPARATOR}Mat[1]")
    assert "サンプル数: 4" in tip
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_channel_browser_physical.py -q`

Expected: 以下 6 本が FAIL。

- `test_columns_survive_the_loader_inversion` → `AssertionError: assert 1 == 3`（`mat[3]`。現行 `_ensure_prep` は観測列を数えるので、擬似反転で Mat が 1 列になる）
- `test_inverted_filter_still_matches_column_names` → `AssertionError: assert [] == ['Mat']`（"mat" は物理 Signal 名 `Mat` にマッチするが `"mat[1"` は落ちるため、後半で `StopIteration`／件数不一致）
- `test_inverted_single_column_rows_carry_the_real_column_identity` → `AssertionError: Mono: single_column must carry the real column`（`('Mono', 'mf4_1::Mono')` が返る）
- `test_group_total_agrees_with_session_total_column_count` → 反転後に `assert 2 == 4`
- `test_csv_group_falls_back_to_the_observed_columns` → `AttributeError: 'ChannelBrowserVM' object has no attribute '_columns_of'`
- `test_tooltip_resolves_a_column_key_after_inversion` → `AssertionError: assert 'サンプル数: 4' in ''`
- `test_vm_never_holds_column_signals` → `AssertionError: VM が Signal を保持している: ['_group_sigs']`（属性名で出る＝再帰オラクル）

- [ ] **Step 3: 実装**

`src/valisync/gui/viewmodels/channel_browser_vm.py` を以下のとおり書き換える。

モジュール docstring（`:1-7`）:

```python
"""ChannelBrowserVM — physical-channel browser for the active file.

Presents the currently selected file as one row per **physical channel** (E-2).
その行が提示する **列** (LD-14 の ``Name[i]`` / ``.field``) の出所は
``session.column_names_of()`` — ローダーの ``ColumnRecord`` が唯一の正典で、
列 Signal の列挙には依存しない (E-3 / spec 追補 S1)。反転後 (T6) はローダーが
列 Signal を発行しないため、列を group_signals から数える実装は全行が 1 列の葉に
潰れ ``Mat[1]`` 以降が木・フィルタ・D&D・プレビュー・エクスポートから同時に消える。
Supports incremental substring filtering (matched against *column* names) and
selection.
"""
```

import 節（`:11-19`）— `Signal` の TYPE_CHECKING import は `_group_sigs` 廃止で未使用になるので削除する:

```python
from typing import TYPE_CHECKING, Any

from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
from valisync.gui import strings as S
from valisync.gui.viewmodels.observable import Observable

if TYPE_CHECKING:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
```

型エイリアス（`:21-30`）:

```python
# (physical_name, unit, base_key, columns) — filter independent。columns はその
# 物理チャンネルが提示する列の表示名タプル (ColumnRecord 由来、記録の無い
# グループでは観測した Signal 名)。**列 Signal への参照は一切持たない** —
# 反転後は列 Signal 自体が存在しない。
_PrepRow = tuple[str, str, str, tuple[str, ...]]

# (physical_name, unit, base_key, column_count, single_column) — what the tree
# model consumes. column_count stays the *real* column count (filter
# independent); single_column is non-None only while the row presents exactly
# one column, and then carries that column's real identity.
_TreeRow = tuple[str, str, str, int, tuple[str, str] | None]
```

`__init__` の `:96-98`（`_group_sigs` の宣言）を差し替える:

```python
        self._prep_key: str | None = None
        self._prep_valid: bool = False
        self._prep: list[_PrepRow] = []
        self._row_by_base_key: dict[str, int] = {}
```

`_invalidate_prep`（`:105-128`）:

```python
    def _invalidate_prep(self) -> None:
        """prep とフィルタメモをまとめて捨てる (両者は不可分)。

        メモは prep が指す列名タプルの上でしか意味を持たない。_ensure_prep も
        再構築時にメモを落とすので**現状はどちらか一方でも結果は正しい**が、
        それは「_ensure_filter_memo が必ず _ensure_prep の後にメモを読む」という
        順序への暗黙依存で、順序が変われば静かに stale を配り始める。無効化点
        (refresh / active_file 切替) を単一の入口に寄せ、「_prep_valid が False
        なのにメモが生きている」中間状態自体を作らない。

        E-3: 旧 _group_sigs (ファイル 1 本ぶんの列 Signal 実体への強参照) は
        廃止した。列は ColumnRecord 由来の文字列なので、VM は Signal を **一度も
        掴まない** — TeardownService._drain が「何も解放できないのに
        pending_signals() だけ減る」最も観測しづらい壊れ方が構造的に起きない。
        """
        self._prep_valid = False
        self._filter_memo = None
        self._prep = []
        self._row_by_base_key = {}
```

`_ensure_prep`（`:130-190`）を全面置換し、直前に `_columns_of` を追加:

```python
    def _columns_of(self, group_key: str, display_name: str) -> tuple[str, ...] | None:
        """物理チャンネル *display_name* の列名 (ColumnRecord 由来)。記録が無ければ None。

        ``session.column_names_of()`` は「記録が無い」を返り値で表現できない —
        記録を持たないローダー (CSV/Derived) と真のスカラーは、どちらも
        ``(display_name,)`` になる。**両者を区別する必要はない**: どちらの場合も
        「観測した Signal がそのまま 1 列」なので、呼び出し側が観測列名を使えば
        必ず正しい (真のスカラーでは観測名 == display_name で一致する)。

        逆に記録から実リーフ名が出た場合 (``Mat`` -> ``Mat[0]…`` / ``Mono`` ->
        ``Mono[0]``) は記録が正典で、観測より優先しなければならない。反転後は
        観測が物理チャンネル 1 本しか無いため、観測を優先すると ``Mono`` /
        ``P`` / ``Q`` のような「展開したのに 1 列」の行が、実在しない合成キーを
        葉として晒す (C1 のバグそのもの)。

        KeyError を握るのは**注入セッション**のため — production の
        ``Session.column_names_of`` は表を ``dict.get`` で引くので未知 key でも
        ``(display_name,)`` を返し、ここへ KeyError は来ない。一方
        ``column_names_of`` を差し替えた単体テストの偽 session は投げうるので、
        その場合も行を作れるように握る (観測列がそのまま列になる)。
        """
        try:
            cols = self._app_vm.session.column_names_of(group_key, display_name)
        except KeyError:
            return None
        if not cols or cols == (display_name,):
            return None
        return cols

    def _ensure_prep(self) -> None:
        """物理チャンネル単位の (name, unit, base_key, columns) を active file ごとに
        1 度だけ作る。

        行のグループ化キーはローダー由来の metadata['physical_channel'] — 文字列
        解析では ACC.Speed (チャンネル名) と P.x (構造化フィールド) を区別できない。
        **列は session.column_names_of() (ColumnRecord) から取る**: 反転後は
        1 物理チャンネル = Signal 1 個になり、列 Signal を数える実装は全行が
        1 列の葉に潰れる (S1)。

        列名タプルは prep と同寿命で保持する。E-2 が拒否したのは「Signal.name が
        別に存在する状態で作る **小文字化した重複コピー**」(旧 _prep の 68 MB /
        名前キャッシュ案の ≈33 MB) であって、反転後はこのタプルが列名の唯一の
        実体になる。捨てると入力停止のたびに全列ぶんの f-string を作り直すことに
        なり、フィルタ 1 回のコストが構造的に悪化する (実測は T9)。フィルタは
        _matches() が都度 lower() するので、小文字化コピーは今後も持たない。

        記録を持たない行 (CSV/Derived・注入セッション) だけが観測列名を溜める。
        prod の配列行は記録が最初の 1 本で確定するので、264k 本の一時リストは
        作らない。

        session.group_signals は遅延アクセス時に読むので、monkeypatch した session
        (テスト) も初回アクセスで尊重される。
        """
        active_key = self._app_vm.active_file_key
        if self._prep_valid and self._prep_key == active_key:
            return
        self._filter_memo = None  # prep が変われば絞り込み結果も無効
        if not active_key:
            self._prep = []
            self._row_by_base_key = {}
            self._prep_key = active_key
            self._prep_valid = True
            return
        prep: list[_PrepRow] = []
        row_by_base_key: dict[str, int] = {}
        # row -> 観測列名。_columns_of が None を返した行だけが入る。
        observed: dict[int, list[str]] = {}
        for sig in self._app_vm.session.group_signals(active_key):
            orig = _orig_of(sig.name)
            md = sig.metadata or {}
            # CSV/Derived は physical_channel を持たない = 1 列 1 物理チャンネル
            # (意図的逸脱・コントローラ決定 2)。直接添字は CSV で KeyError になる。
            phys = str(md.get("physical_channel") or orig)
            # base_key は「親をグループ化するための合成ハンドル」であって Signal キー
            # ではない (Mono / P / Q は実在しない)。葉の key には決して使わない。
            base_key = f"{active_key}{KEY_SEPARATOR}{phys}"
            row = row_by_base_key.get(base_key)
            if row is None:
                row = len(prep)
                row_by_base_key[base_key] = row
                cols = self._columns_of(active_key, phys)
                if cols is None:
                    observed[row] = [orig]
                    cols = ()  # ループ後に観測列で差し替える
                # unit は物理チャンネル 1 本につき 1 つ — ローダーは同一プローブの
                # metadata を全列へ配る (mdf_loader の pairs ループ) ので「列ごとの
                # unit」は存在しない。親行の Unit を空にするのは tree model の責務
                # (UX-29)。
                prep.append((phys, str(md.get("unit", "")), base_key, cols))
            elif row in observed:
                observed[row].append(orig)
        for row, names in observed.items():
            phys, unit, base_key, _placeholder = prep[row]
            prep[row] = (phys, unit, base_key, tuple(names))
        self._prep = prep
        self._row_by_base_key = row_by_base_key
        self._prep_key = active_key
        self._prep_valid = True

    def _column_key(self, column_name: str) -> str:
        """列の表示名を名前空間つき Signal キーへ。

        反転後は「Signal がまだ存在しない時点」で組み立てるので、Signal から
        読み出すことはできない (鋳造は session.resolve_signal が要求時に行う)。
        _prep_key は _ensure_prep 後は必ず active_file_key と一致する。
        """
        return f"{self._prep_key}{KEY_SEPARATOR}{column_name}"

    def _total_columns(self) -> int:
        """prep が提示する列の総数 (フィルタ非依存)。"""
        return sum(len(row[3]) for row in self._prep)
```

`_ensure_filter_memo`（`:192-221`）は本体不変。docstring 末尾 2 段落だけ差し替える:

```python
        追加メモリは実質ゼロ: 保持するのは生存行のタプル (prod 4,324 行) と int
        だけで、**列ごとの小文字名は持たない** (それが旧 _prep の 68 MB /
        名前キャッシュ案の ≈33 MB の本体)。列名そのものは prep が 1 部だけ持ち
        (_ensure_prep の docstring)、子行も件数もそこから賄う。
```

`_scan_filter`（`:223-262`）:

```python
    def _scan_filter(self, fl: str) -> tuple[list[_TreeRow], int]:
        """メモが無いときの実走査 (生存行, 一致列総数)。fl は小文字化済み。"""
        rows: list[_TreeRow] = []
        if not fl:
            # フィルタ空 = 実列数がそのまま提示列数 (列名の照合はしない)。
            for name, unit, base_key, cols in self._prep:
                single = (
                    (cols[0], self._column_key(cols[0])) if len(cols) == 1 else None
                )
                rows.append((name, unit, base_key, len(cols), single))
            return rows, self._total_columns()
        # ここから先だけが列名走査。メモが効いていれば入力停止 1 回につき 1 度しか
        # 増えない — テストはこの数を見る。
        self._filter_scans += 1
        matched_total = 0
        for name, unit, base_key, cols in self._prep:
            hits = 0
            single: tuple[str, str] | None = None
            for col in cols:
                if not _matches(col, fl):
                    continue
                hits += 1
                if hits == 1:
                    single = (col, self._column_key(col))
            if hits == 0:
                continue  # 一致列 0 の行は出さない
            matched_total += hits
            # column_count は **フィルタ非依存の実列数** のまま (_group_total の供給元)。
            # 葉/親の判定に使わないこと — 使うと「絞って 1 列に落ちた行」がドラッグ
            # 不能な親のままになり、今日できる「絞って→ドラッグ」を壊す。
            rows.append(
                (name, unit, base_key, len(cols), single if hits == 1 else None)
            )
        return rows, matched_total
```

`column_names_for`（`:291-320`）— docstring の前半と本体を差し替え（`try/except KeyError` のガードとコメントはそのまま残す）:

```python
    def column_names_for(self, base_key: str) -> list[tuple[str, str, str]]:
        """base_key の物理チャンネルの列を (orig, unit, key) で返す。

        走査はその行の列名タプルだけ — group_signals 全走査 (prod 264,004) を
        展開のたびに走らせない (O(n^2) 回避)。返すのは **現在のフィルタに一致する
        列だけ** (フィルタ空なら全列) で、述語は _matches() に一本化 — 件数と
        子行が乖離できない構造にする (C3)。unit は行 (物理チャンネル) のもの —
        列ごとの unit は存在しない (_ensure_prep の docstring)。
        """
        try:
            self._ensure_prep()
        except KeyError:
            # Mirrors tree_groups(): reached from _materialize() -> index()/
            # rowCount() inside Qt virtuals (SignalTreeModel), so a notify can
            # still be in flight for a key the session already dropped. An
            # exception escaping into the C++ event loop here is worse than an
            # empty result (FU-22 A/B).
            return []
        row = self._row_by_base_key.get(base_key)
        if row is None:
            return []
        _name, unit, _bk, cols = self._prep[row]
        fl = self._filter_text.lower()
        return [(c, unit, self._column_key(c)) for c in cols if _matches(c, fl)]
```

`_group_total`（`:324-345`）:

```python
    def _group_total(self) -> int | None:
        """Return the active file's filter-independent total **column** count, or
        None (no file active, or its key was already dropped from the session —
        FU-22 B).

        値は prep の列数和。T1 の ``session.total_column_count()`` を production
        から**直接は呼ばない**: (a) shown_count() と別ソースにすると「total <
        shown」の自己矛盾を構造的に許してしまう (C2 — prod で「4,324 ch 中
        264,004 ch を表示」に相当する壊れ方)、(b) 全チャンネル skip の 0ch
        グループや、group_signals だけを差し替えた単体セッションで total と行が
        食い違う。両者が一致することは実ファイルの契約テスト
        (test_group_total_agrees_with_session_total_column_count) が pin する。

        shown_count() が列を数える以上 total も列で数える (C2)。empty_state() の
        total == 0 分岐は変更不要 — チャンネルは必ず 1 列以上持つので「列 0」と
        「チャンネル 0」は同値。

        #14: this no longer resolves the file's display name — the header
        (the only former consumer of it) dropped the filename prefix, and
        which file is active is now shown by the FileBrowser's own selection
        highlight instead.
        """
        active_key = self._app_vm.active_file_key
        if not active_key:
            return None
        try:
            self._ensure_prep()  # prep hit なら追加 fetch なし
        except KeyError:
            return None
        return self._total_columns()
```

`_signal_by_key`（`:408-419`）:

```python
    def _signal_by_key(self, key: str) -> Any | None:
        """Look up the Signal for *key* (namespaced column key)。

        反転後は列 Signal が group_signals に居ない (1 物理チャンネル = Signal 1 個)
        ため、走査で外れたら session.resolve_signal へ落とす — 列キーはそこで
        要求時に鋳造される (E-1)。値は読まないので遅延契約は保たれる
        (tooltip が見るのは timestamps の長さと metadata だけ)。
        """
        active_key = self._app_vm.active_file_key
        if not active_key:
            return None
        session = self._app_vm.session
        try:
            for sig in session.group_signals(active_key):
                if sig.name == key:
                    return sig
        except KeyError:
            return None
        return session.resolve_signal(key)
```

- [ ] **Step 4: 通ることを確認**

Run（この順で全て exit 0）:

```
uv run pytest tests/gui/test_channel_browser_physical.py -q
uv run pytest tests/gui/test_channel_browser_vm.py tests/gui/test_channel_browser_view.py tests/gui/test_signal_tree_model.py -q
uv run pytest -q
```

2 本目が本タスクの「両 fixture GREEN」の実証になる。`test_channel_browser_vm.py:482-513`（`g::Arr[0..2]` + `g::Struct.field`）・`:525-558`・`:572-584`・`:597-619`、`test_channel_browser_view.py:124/179/772`、`test_signal_tree_model.py:45/125` は**セッションに登録されていないグループキー**（`"g"` / `"test_key"`）へ列 Signal を注入する fixture で、`_columns_of` が None を返す経路（観測列がそのまま列）を通る。1 本目の反転 fixture は記録が正典になる経路を通る。**両経路が同じ production コードで同時に GREEN** であることが独立受理の根拠。

`test_channel_browser_vm.py:383` / `test_channel_browser_view.py:391`（`group_signals` を `[]` に差し替えて "no_channels" を見る）は `_group_total()` が prep 由来のままなので**無改変で GREEN**。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

1 つずつ入れて該当テストが RED になることを確認し、必ず元に戻す。

1. `_columns_of` を `return None`（常に観測を採る＝反転前の実装へ後退）
   → `test_columns_survive_the_loader_inversion`（`assert 1 == 3`）・`test_inverted_single_column_rows_carry_the_real_column_identity`・`test_inverted_filter_still_matches_column_names`・`test_group_total_agrees_with_session_total_column_count` が RED。既存の非反転テストは GREEN のまま＝**反転 fixture だけが差を検出できる**ことの実証。
2. `_columns_of` の `if not cols or cols == (display_name,): return None` を消す（記録が無いグループでも `(display_name,)` を採る）
   → `tests/gui/test_channel_browser_vm.py::test_tree_groups_buckets_arrays_under_base`（`Arr` が 1 列に潰れる）・`::test_tree_groups_honors_filter`・`tests/gui/test_signal_tree_model.py::test_array_parent_has_children_scalar_leaf_does_not`（`rowCount(arr) == 3` が 1 に）が RED。
3. `column_names_for` の `if _matches(c, fl)` を落とす
   → `test_column_names_for_honors_filter`・`test_inverted_filter_still_matches_column_names` が RED（3 列返る）。
4. `_ensure_prep` の末尾に `self._group_sigs = list(...)` 相当の保持を復活（`self._prep_signals = self._app_vm.session.group_signals(active_key)` を足す）
   → `test_vm_never_holds_column_signals` が RED。
5. `_group_total` を `return len(self._prep)` に戻す
   → `test_group_total_counts_columns_not_rows`・`test_header_total_is_columns_not_rows`・`test_group_total_agrees_with_session_total_column_count` が RED。
6. `_signal_by_key` の末尾を `return None` に（resolve フォールバック撤去）
   → `test_tooltip_resolves_a_column_key_after_inversion` が RED、既存 tooltip テスト（注入セッション）は GREEN のまま。

- [ ] **Step 6: ゲート＋コミット**

```
uv run ruff format
uv run ruff check
uv run mypy src/
uv run pytest
git add src/valisync/gui/viewmodels/channel_browser_vm.py tests/gui/test_channel_browser_physical.py
git commit -m "feat(gui): チャンネルブラウザの列ソースを ColumnRecord 由来へ (S1)

列 (Name[i]/.field) を session.column_names_of() から取り、group_signals の
列 Signal 列挙に依存しないようにする。反転後 (T6) はローダーが列 Signal を
発行しないため、無修正だと全行が 1 列の葉に潰れ Mat[0]/Pos.x が木・フィルタ・
D&D・プレビュー・エクスポートから同時に消える。

- _prep から spans/first_column/_group_sigs を撤去し列名タプル 1 本へ
  (VM は Signal を一度も掴まない = teardown 会計の前提が構造化)
- _columns_of: 記録が (display_name,) / 不在なら観測列へフォールバック
  (CSV/Derived と注入セッションを同一経路で扱う)
- _group_total は prep 由来のまま維持 (shown との自己矛盾を構造で禁止)。
  session.total_column_count() との一致は契約テストで pin
- _signal_by_key に resolve_signal フォールバック (列キーは要求時鋳造)
- 擬似反転 fixture (_invert_to_physical_signals) で T6 前に受理条件を判定"
```

---

### Task 5: ExportCsvDialog の列を遅延展開へ（U1 / C-a / C-b）

**Files:**
- Modify: `src/valisync/gui/views/export_csv_dialog.py:106-133`（ツリー構築）・`:233-270`（選択/フィルタ）・`:314-368`（`_offset_active_for_checked` / `_validate`）・`:379-398`（`_on_accept`）
- Modify: `src/valisync/gui/strings.py:113`（`EXPORT_SELECTION_COUNT_TMPL` の直後に 2 定数を追加）
- Test: `tests/gui/test_export_csv_dialog.py`（既存テストは **1 行も変更しない**。`_FakeSession` へ後方互換の追加 API と新 fixture・新テストを足す）

**Interfaces:**
- Consumes（T1 が新設）:
  - `Session.column_names_of(key: str, display_name: str) -> tuple[str, ...]` — 数値リーフの表示名タプル。**スカラー／レコード未登録（CSV・Derived はそもそも `ColumnRecord` を持たない）は `(display_name,)` を返す**。この「未登録は `(display_name,)`」が本タスクの CSV 経路の前提であり、例外を投げてはならない。
  - `Session.has_column(key: str, display_name: str) -> bool` — 物理チャンネル名が**それ自身 1 本の列**か（スカラー/CSV は True・配列/構造体の親は False）。列名を 1 本も生成せずに答えるので、フィルタ 1 打鍵ごとの列名再生成をスカラー行では完全に回避できる（`_row_matches`）。
  - 既存: `Session.group_signals(key) -> list[Signal]`（要素の `metadata["physical_channel"]` が物理チャンネル名。CSV/Derived は非保持＝1 列 1 物理チャンネル）・`Session.resolve_signal(key) -> Signal | None`（列キーを要求時に鋳造）・`Session.source_name(key) -> str`。
  - `AppViewModel.loaded_file_keys -> list[str]`。
- Produces（後続が依存）:
  - `ExportCsvDialog._iter_rows() -> Iterator[QTreeWidgetItem]` — ファイル行の下の**物理チャンネル行**を全て返す（T9 の realgui ①ゲートが実クリック後の行構造を読む）。
  - `ExportCsvDialog._iter_children() -> Iterator[QTreeWidgetItem]` — **チェック可能な葉のみ**（1 列行＋合成済みの列）。名前と意味は既存テストの契約を保つ。
  - `ExportCsvDialog._checked_keys() -> list[str]` — 出力集合。**木の並び順**（ファイル順→ローダー順→列順）で返す。
  - 不変条件: **ダイアログを開いても列 `Signal` は 1 本も鋳造されない**（`Session.resolve_signal` は `_on_accept` からのみ呼ばれる）。T9 の鋳造カウンタ計測はこれを前提にする。

- [ ] **Step 1: 失敗テストを書く**

まず**実装前に**凍結カタログのベースラインを撮る（実ディスプレイ必須・offscreen 不可）。06 は CSV fixture のみで撮られる（`scripts/capture_ui_screenshots.py:233-260`）ので、構造変更が無ければ後で 0 差分になるはずのもの:

```
uv run python scripts/capture_ui_screenshots.py --catalog --theme dark  --out design_export/e3_t5_before_dark
uv run python scripts/capture_ui_screenshots.py --catalog --theme light --out design_export/e3_t5_before_light
```

`tests/gui/test_export_csv_dialog.py` の `_FakeSession`（`:16-25`）を**後方互換で拡張**する（既存の `_FakeSession(groups=..., names=...)` 呼び出しは無変更で通る）:

```python
class _FakeSession:
    """列展開の前後どちらのローダー形にもなれる最小 Session。

    group_signals が返す Signal は「反転前 = 列 1 本ごと」「反転後 = 物理チャンネル
    1 本」の 2 形を取りうる (T6)。ダイアログはどちらでも同じ行を出さなければ
    ならないので fixture 側でこの 2 形を切り替える。column_names_of は T1 の契約
    (未登録キー / スカラーは (display_name,)) をそのまま写す — CSV グループは
    ColumnRecord を持たないので、この既定分岐が CSV 経路そのものになる。
    """

    def __init__(
        self,
        groups: dict[str, list[Signal]],
        names: dict[str, str],
        columns: dict[tuple[str, str], tuple[str, ...]] | None = None,
        resolvable: dict[str, Signal] | None = None,
    ) -> None:
        self._groups = groups
        self._names = names
        self._columns = columns or {}
        # 反転後は列 Signal が group_signals に居ないので、鋳造先を別に持つ。
        self.resolvable = resolvable or {
            sig.name: sig for sigs in groups.values() for sig in sigs
        }
        self.resolve_calls = 0

    def source_name(self, key: str) -> str:
        return self._names[key]

    def group_signals(self, key: str) -> list[Signal]:
        return self._groups[key]

    def column_names_of(self, key: str, display_name: str) -> tuple[str, ...]:
        return self._columns.get((key, display_name), (display_name,))

    def has_column(self, key: str, display_name: str) -> bool:
        # T1 と同じ契約: 物理チャンネル名がそれ自身 1 本の列なら True、
        # 複数列へ展開される親 (容器) なら False。
        return self._columns.get((key, display_name), (display_name,)) == (
            display_name,
        )

    def resolve_signal(self, key: str) -> Signal | None:
        self.resolve_calls += 1
        return self.resolvable.get(key)
```

`_sig`（`:34-42`）へ metadata 引数を足す（既定 None＝既存呼び出しは無変更）:

```python
def _sig(name: str, phys: str | None = None) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="CSV",
        bus_type="",
        source_file="",
        metadata={"physical_channel": phys} if phys else None,
    )
```

ファイル末尾へ新 fixture・ヘルパ・テストを追加:

```python
# --- E-3/U1: 列の遅延展開 -----------------------------------------------------


def _array_app_vm(*, expanded: bool) -> _FakeAppVM:
    """Mat (3 列) + Clean (1 列) の 1 ファイル。

    expanded=True  … 反転前のローダー (列 Signal を 3 + 1 本)
    expanded=False … 反転後のローダー (物理チャンネル Signal を 1 + 1 本)
    どちらでもダイアログは「Mat (親・3 列) / Clean (葉)」を出さねばならない。
    この 2 形を両方 GREEN にできることが、T6 の反転を跨いでこのテストが
    生き残る根拠 (反転時に fixture を書き換えなくてよい)。
    """
    columns = {("mf4_1", "Mat"): ("Mat[0]", "Mat[1]", "Mat[2]")}
    clean = _sig("mf4_1::Clean", phys="Clean")
    if expanded:
        group = [
            _sig("mf4_1::Mat[0]", phys="Mat"),
            _sig("mf4_1::Mat[1]", phys="Mat"),
            _sig("mf4_1::Mat[2]", phys="Mat"),
            clean,
        ]
        resolvable = {s.name: s for s in group}
    else:
        group = [_sig("mf4_1::Mat", phys="Mat"), clean]
        resolvable = {
            "mf4_1::Mat[0]": _sig("mf4_1::Mat[0]", phys="Mat"),
            "mf4_1::Mat[1]": _sig("mf4_1::Mat[1]", phys="Mat"),
            "mf4_1::Mat[2]": _sig("mf4_1::Mat[2]", phys="Mat"),
            "mf4_1::Clean": clean,
        }
    sess = _FakeSession(
        {"mf4_1": group}, {"mf4_1": "mat2d.mf4"}, columns, resolvable
    )
    return _FakeAppVM(sess, ["mf4_1"])


def _row_named(dlg: ExportCsvDialog, text: str) -> QTreeWidgetItem:
    return next(r for r in dlg._iter_rows() if r.text(0) == text)


def _child_texts(item: QTreeWidgetItem) -> list[str]:
    return [item.child(i).text(0) for i in range(item.childCount())]


@pytest.mark.parametrize("expanded", [True, False])
def test_container_row_synthesizes_columns_on_expand(
    qtbot: QtBot, expanded: bool
) -> None:
    """U1: 親は未展開のままプレースホルダ 1 個だけを持ち、展開した瞬間に列が出る。

    prod は 4,324 行 / 264,004 列。expandAll() で全列アイテムを同期構築するのが
    ダイアログを開くだけで固まる原因だった。
    """
    dlg = ExportCsvDialog(_array_app_vm(expanded=expanded), initial_selected=set())
    qtbot.addWidget(dlg)
    mat = _row_named(dlg, "Mat")
    assert mat.childCount() == 1  # プレースホルダのみ
    assert mat.child(0).data(0, Qt.ItemDataRole.UserRole) is None  # 実列ではない

    dlg._tree.expandItem(mat)

    assert _child_texts(mat) == ["Mat[0]", "Mat[1]", "Mat[2]"]
    assert [
        mat.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(mat.childCount())
    ] == ["mf4_1::Mat[0]", "mf4_1::Mat[1]", "mf4_1::Mat[2]"]


@pytest.mark.parametrize("expanded", [True, False])
def test_select_all_does_not_mint_any_column(qtbot: QtBot, expanded: bool) -> None:
    """C-b: 「すべて選択」は列キーを **名前だけ** で組む (resolve を呼ばない)。

    ここで鋳造すると prod で 264k 本の Signal = ~390 MB の一撃になる
    (E-3 が剥がしているコストそのもの)。
    """
    app_vm = _array_app_vm(expanded=expanded)
    dlg = ExportCsvDialog(app_vm, initial_selected=set())
    qtbot.addWidget(dlg)
    assert app_vm.session.resolve_calls == 0  # 開くだけでは鋳造しない

    dlg._select_all()

    assert set(dlg._checked_keys()) == {
        "mf4_1::Mat[0]",
        "mf4_1::Mat[1]",
        "mf4_1::Mat[2]",
        "mf4_1::Clean",
    }
    assert app_vm.session.resolve_calls == 0


@pytest.mark.parametrize("expanded", [True, False])
def test_initial_selection_expands_the_owning_row(
    qtbot: QtBot, expanded: bool
) -> None:
    """initial_selected の列を持つ親は開いた状態で開く (従来の「開いたら選択済み」)。"""
    dlg = ExportCsvDialog(
        _array_app_vm(expanded=expanded), initial_selected={"mf4_1::Mat[1]"}
    )
    qtbot.addWidget(dlg)
    mat = _row_named(dlg, "Mat")
    assert mat.isExpanded()
    assert _child_texts(mat) == ["Mat[0]", "Mat[1]", "Mat[2]"]
    assert [
        mat.child(i).text(0)
        for i in range(mat.childCount())
        if mat.child(i).checkState(0) == Qt.CheckState.Checked
    ] == ["Mat[1]"]
    assert dlg._checked_keys() == ["mf4_1::Mat[1]"]
    # C-a: 一部だけ選択されている親は部分チェック表示になる
    assert mat.checkState(0) == Qt.CheckState.PartiallyChecked
    # 他の行 (Clean) は開かない = 巻き込みで列を作らない
    assert _row_named(dlg, "Clean").childCount() == 0


@pytest.mark.parametrize("expanded", [True, False])
def test_channel_row_is_a_tristate_container_not_checkable(
    qtbot: QtBot, expanded: bool
) -> None:
    """C-a: 物理チャンネル行はチェック **不可**。三態表示だけを持つ。

    「親をチェック = 全列エクスポート」を許すと 264k 鋳造の一撃になる。
    """
    dlg = ExportCsvDialog(_array_app_vm(expanded=expanded), initial_selected=set())
    qtbot.addWidget(dlg)
    mat = _row_named(dlg, "Mat")
    clean = _row_named(dlg, "Clean")
    assert not (mat.flags() & Qt.ItemFlag.ItemIsUserCheckable)
    assert mat.data(0, Qt.ItemDataRole.UserRole) is None  # 親は列キーを持たない
    assert mat.checkState(0) == Qt.CheckState.Unchecked  # 三態表示自体は持つ
    # 1 列の物理チャンネルは従来どおり葉 (チェック可能・実列キー)
    assert clean.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert clean.data(0, Qt.ItemDataRole.UserRole) == "mf4_1::Clean"


@pytest.mark.parametrize("expanded", [True, False])
def test_filter_matches_column_names_of_unexpanded_rows(
    qtbot: QtBot, expanded: bool
) -> None:
    """フィルタは列名にマッチする — 親が未展開でも (ChannelBrowser と同じ規則)。"""
    dlg = ExportCsvDialog(_array_app_vm(expanded=expanded), initial_selected=set())
    qtbot.addWidget(dlg)

    dlg._filter.setText("mat[1")

    mat = _row_named(dlg, "Mat")
    assert not mat.isHidden()  # 未展開でも列名で生き残る
    assert _row_named(dlg, "Clean").isHidden()
    dlg._tree.expandItem(mat)
    assert [
        mat.child(i).text(0)
        for i in range(mat.childCount())
        if not mat.child(i).isHidden()
    ] == ["Mat[1]"]


@pytest.mark.parametrize("expanded", [True, False])
def test_accept_resolves_only_the_selected_columns(
    qtbot: QtBot, tmp_path: Path, expanded: bool
) -> None:
    """C-b: 実体化は出口で 1 列ずつ。選んでいない列は鋳造しない。"""
    app_vm = _array_app_vm(expanded=expanded)
    dlg = ExportCsvDialog(app_vm, initial_selected={"mf4_1::Mat[1]"})
    qtbot.addWidget(dlg)
    target = tmp_path / "out.csv"
    dlg._save_path_provider = lambda: str(target)

    dlg._on_accept()

    req = dlg._result
    assert isinstance(req, ExportRequest)
    assert [s.name for s in req.signals] == ["mf4_1::Mat[1]"]
    assert app_vm.session.resolve_calls == 1


def test_unresolvable_column_reports_instead_of_raising(
    qtbot: QtBot,
) -> None:
    """旧実装は self._sig_by_key[k] が素の KeyError でダイアログごと落ちた
    (spec「壊れる消費者」3 = 唯一のハード失敗)。無言で列を落とすのも
    「選んだのに出ていない CSV」になるので、出力せず理由を出す。
    """
    app_vm = _array_app_vm(expanded=False)
    app_vm.session.resolvable.pop("mf4_1::Mat[1]")
    dlg = ExportCsvDialog(app_vm, initial_selected={"mf4_1::Mat[1]"})
    qtbot.addWidget(dlg)
    asked: list[str] = []

    def _never() -> str:
        asked.append("asked")
        return ""

    dlg._save_path_provider = _never

    dlg._on_accept()

    assert dlg._result is None
    assert asked == []  # 保存先を訊く前に落とす
    assert "Mat[1]" in dlg._error.text()


def test_checked_keys_follow_tree_order_not_hash_order(qtbot: QtBot) -> None:
    """出力列順は木の並び (ファイル順 -> ローダー順 -> 列順)。

    選択の真実が set になったので、素の sorted()/ハッシュ順で出すと CSV の
    列順がアルファベット順に化ける (Clean が Mat より前に来る) — 実行ごとに
    変わる形にもなりうる。
    """
    dlg = ExportCsvDialog(_array_app_vm(expanded=False), initial_selected=set())
    qtbot.addWidget(dlg)
    dlg._select_all()
    assert dlg._checked_keys() == [
        "mf4_1::Mat[0]",
        "mf4_1::Mat[1]",
        "mf4_1::Mat[2]",
        "mf4_1::Clean",
    ]


def test_real_mdf_array_channel_is_one_row_with_lazy_columns(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """実ローダー経路 (合成 fake ではない) で行構造と列合成を固定する。

    T6 の反転前は group_signals が列 Signal を、反転後は物理チャンネル Signal を
    返すが、どちらでも 2 行 (Mat 親 / Clean 葉) にならねばならない。
    """
    app_vm = AppViewModel()
    app_vm.request_load(write_mdf4_2d(tmp_path))  # MDF4 は format_def 不要
    dlg = ExportCsvDialog(app_vm, initial_selected=set())
    qtbot.addWidget(dlg)

    assert [r.text(0) for r in dlg._iter_rows()] == ["Mat", "Clean"]
    mat = _row_named(dlg, "Mat")
    assert mat.childCount() == 1  # 未展開
    dlg._tree.expandItem(mat)
    assert _child_texts(mat) == ["Mat[0]", "Mat[1]", "Mat[2]"]

    dlg._select_all()
    keys = dlg._checked_keys()
    assert keys == [
        "mf4_1::Mat[0]",
        "mf4_1::Mat[1]",
        "mf4_1::Mat[2]",
        "mf4_1::Clean",
    ]
    for k in keys:  # 合成したキーは全て実 Signal に当たる (葉キーの不変条件)
        assert app_vm.session.resolve_signal(k) is not None


def test_real_csv_file_stays_flat(qtbot: QtBot, tmp_path: Path) -> None:
    """CSV は ColumnRecord を持たない = 1 列 1 物理チャンネル (E-2 と同じ扱い)。

    T1 の「未登録キーは (display_name,)」契約を消費者側から固定する
    (ここが崩れると CSV ファイルの行が丸ごと消えるか例外になる)。
    """
    csv = tmp_path / "run.csv"
    csv.write_text("t,speed\n0.0,10.0\n1.0,20.0\n", encoding="utf-8")
    app_vm = AppViewModel()
    app_vm.request_load(
        csv,
        FormatDefinition(
            name="t5_fmt",
            delimiter=Delimiter.COMMA,
            timestamp_column=0,
            timestamp_unit="sec",
            signal_start_column=1,
            signal_end_column=1,
            has_header=True,
        ),
    )
    dlg = ExportCsvDialog(app_vm, initial_selected=set())
    qtbot.addWidget(dlg)

    rows = list(dlg._iter_rows())
    assert [r.text(0) for r in rows] == ["speed"]
    assert rows[0].childCount() == 0  # 葉 = 展開矢印を出さない
    assert rows[0].data(0, Qt.ItemDataRole.UserRole) == "csv_1::speed"
```

追加 import（テストファイル冒頭へ）:

```python
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTreeWidgetItem

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.models import Delimiter, FormatDefinition, Signal
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_export_csv_dialog.py -q`

Expected: 新規テストが FAIL —
`AttributeError: 'ExportCsvDialog' object has no attribute '_iter_rows'`
（`test_unresolvable_column_reports_instead_of_raising` は旧 `_on_accept` の
`KeyError: 'mf4_1::Mat[1]'` で FAIL。既存 20 テストは全て PASS のままであること
＝ここが「既存 assert を弱めていない」ことの確認点）。

- [ ] **Step 3: 実装**

**(a) `src/valisync/gui/strings.py`** — `EXPORT_SELECTION_COUNT_TMPL`（`:113`）の直後へ追加:

```python
# ── ダイアログ: CSV エクスポート — 列の遅延展開 (E-3・U1) ────────────────────
# 未展開の物理チャンネル行に置くダミー子。展開した瞬間に実列へ置換されるので
# ユーザーにはほぼ見えないが、これが無いと Qt が展開矢印を描かない
# (= 列があることに気付けない)。
EXPORT_COLUMN_PLACEHOLDER: Final = "…"
EXPORT_UNRESOLVED_ERROR_TMPL: Final = "選択した列を読み出せません（{n} 件・例: {name}）"
```

**(b) `src/valisync/gui/views/export_csv_dialog.py`** — import へ 1 行追加:

```python
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
```

`_DECIMALS` の下（`:50` の直後）へモジュール定数・行レコード・物理チャンネル走査を追加:

```python
# ツリーアイテムのロール割り当て。UserRole (葉の列キー) は E-0 以前からの契約
# なので動かさない — 既存テストと realgui が選択キーとしてこれを読む。
# int() で包むのは +1/+2/+3 の派生ロールを作るためだけで、値は enum と同一。
# 読み出し側 (既存テスト・realgui の `data(0, Qt.ItemDataRole.UserRole)`) は
# **enum 表記のままでよい** — 書き込みと読み出しで同じ整数を指す。
_KEY_ROLE = int(Qt.ItemDataRole.UserRole)  # 葉のみ: 名前空間つき列キー
_ROW_ROLE = _KEY_ROLE + 1  # 物理チャンネル行と葉: _rows の添字
_COL_ROLE = _KEY_ROLE + 2  # 葉のみ: その行の中での列インデックス
_PLACEHOLDER_ROLE = _KEY_ROLE + 3  # 未展開コンテナのダミー子の目印


@dataclass(slots=True)
class _ChannelRow:
    """1 物理チャンネル行が展開前に知っている全て。**列名は保持しない**。

    列名を抱えないのが本増分の核心: prod は 4,324 行 / 264,004 列で、名前を
    持つだけでダイアログを開く限り数十 MB が常駐する (E-3 が剥がしたコスト
    そのもの)。必要になった瞬間に session.column_names_of() から作り直す。
    """

    file_key: str
    phys: str
    count: int
    single_key: str | None  # count == 1 のときだけ実列キー (合成ハンドルではない)
    # 直近に評価したフィルタ文字列とその結果 (_row_matches のメモ)。同一クエリの
    # 再評価で列名を作り直さないためだけの覚え書きで、行の同一性には関与しない。
    matched: str | None = None
    hit: bool = False


def _physical_channels(signals: list[Signal]) -> list[str]:
    """ローダー順の物理チャンネル名 (重複は最初の出現へ畳む)。

    グループ化キーは metadata['physical_channel'] — 文字列解析では ACC.Speed
    (チャンネル名) と P.x (構造化フィールド) を区別できない (E-2 と同じ根拠)。
    ローダーが列を展開している間は同じ物理チャンネルが複数回現れるので畳む
    必要があり、反転後は 1 回しか現れないので畳んでも同じ結果になる — この
    1 本の走査だけで新旧どちらのローダーでも同じ行が出る。
    CSV/Derived は physical_channel を持たない = 1 列 1 物理チャンネル。
    """
    out: list[str] = []
    seen: set[str] = set()
    for sig in signals:
        name = sig.name
        orig = name.split(KEY_SEPARATOR, 1)[1] if KEY_SEPARATOR in name else name
        phys = str((sig.metadata or {}).get("physical_channel") or orig)
        if phys not in seen:
            seen.add(phys)
            out.append(phys)
    return out
```

`__init__` で `self._offset_for = offset_for` の直後（`:96` の後・`layout = QVBoxLayout(self)` の前）へ選択状態を用意:

```python
        # 選択の真実は **ダイアログ側の集合** (U1)。未展開の列は QTreeWidgetItem を
        # 持たないので「木を数えて選択集合を作る」実装は原理的に成立しない。
        # 値は (行, 列) — 出力列順を木の並びに保つための添字で、ハッシュ順に
        # 依存すると PYTHONHASHSEED ごとに CSV の列順が変わる。
        self._selected: dict[str, tuple[int, int]] = {}
        # 行ごとの選択列数。三態表示を O(1) で出すため (未展開の 262k 列を
        # 数え直さない唯一の手段)。
        self._selected_per_row: dict[int, int] = {}
        self._rows: list[_ChannelRow] = []
        # 表示同期中フラグ: 自分で setCheckState/setFlags した分を「ユーザー操作」
        # として拾い戻さないための門。複数経路から入るので受け口 1 箇所で弾く。
        self._syncing = False
```

`:106-133`（`# 信号ツリー(...)` から `layout.addWidget(self._tree)` まで）を丸ごと差し替え:

```python
        # 信号ツリー(ファイル > 物理チャンネル > 列・チェックボックス)
        self._tree = QTreeWidget(self)
        self._tree.setObjectName("export_tree")
        self._tree.setHeaderHidden(True)
        # 接続は構築の **後**。構築中の setFlags/setCheckState は itemChanged を
        # 発火させるがユーザー操作ではない (先に繋ぐと、まだ CheckState を書いて
        # いない葉の setFlags が「未チェックにされた」と誤読され初期選択が消える)。
        self._build_tree(initial_selected)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        layout.addWidget(self._tree)
```

`# --- 選択 ---` セクション（`:232-270`）を丸ごと差し替え:

```python
    # --- ツリー構築 ---------------------------------------------------------
    def _build_tree(self, initial_selected: set[str]) -> None:
        """ファイル行と物理チャンネル行までを作る (列アイテムは要求時)。

        列の QTreeWidgetItem は作らない — prod 264,004 個の同期構築が
        「ダイアログを開くだけで固まる」の正体だった (U1)。
        ここで走る column_names_of は「列数」と「初期選択の所在」を確定する
        ための **一過性** の生成で、名前は 1 つも保持しない (行あたり int 1 個)。
        物理チャンネルごとの列数を返す API があれば消せる一過性コストだが、
        C-g と同じ理由で E-3 では増やさない。
        """
        session = self._app_vm.session
        items: list[QTreeWidgetItem] = []  # _rows と同じ添字
        # 表示名の衝突判定は **行の identity** で行う。列まで母集団に入れると
        # 264k 名の生成/保持が要り E-3 の成果が消える。1 列行は実列キーを
        # identity にするので、1 列 = 1 信号のファイル (CSV 等) では E-0 の
        # 従来挙動がそのまま保たれる。複数列の親配下の列テキストは裸名のまま
        # (親が既に qualified なので所属ファイルは文脈で一意) — 意図的逸脱。
        # identity は行ごとに一意とは限らない: 物理チャンネル名が文字どおり
        # "Mono[0]" のファイルと、"Mono" の 1 列展開が同居すると両行が同じ
        # identity になる (T0 が固定している Mat[0] 衝突と同型の配置)。影響は
        # **表示テキストだけ**で、選択キー (_KEY_ROLE = 実列キー) は常に一意。
        identities: list[str] = []
        tops: list[QTreeWidgetItem] = []
        auto_expand: list[int] = []
        for file_key in self._app_vm.loaded_file_keys:
            top = QTreeWidgetItem(self._tree, [session.source_name(file_key)])
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            tops.append(top)
            prefix = f"{file_key}{KEY_SEPARATOR}"
            # 初期選択はファイルごとに裸名へ落として突き合わせる (列 1 本ごとに
            # f"{prefix}{name}" を作ると prod で 264k 個の一過性文字列になる)。
            wanted = {k[len(prefix) :] for k in initial_selected if k.startswith(prefix)}
            for phys in _physical_channels(session.group_signals(file_key)):
                names = session.column_names_of(file_key, phys)
                row_index = len(self._rows)
                single = prefix + names[0] if len(names) == 1 else None
                self._rows.append(_ChannelRow(file_key, phys, len(names), single))
                if wanted:
                    for col_index, name in enumerate(names):
                        if name in wanted:
                            self._add_selection(row_index, col_index, prefix + name)
                    if self._selected_per_row.get(row_index):
                        auto_expand.append(row_index)
                item = QTreeWidgetItem(top, [""])  # テキストは display_names 確定後
                item.setData(0, _ROW_ROLE, row_index)
                items.append(item)
                identities.append(single if single is not None else prefix + phys)
        shown = display_names(identities)
        for row_index, item in enumerate(items):
            row = self._rows[row_index]
            item.setText(0, shown[identities[row_index]])
            if row.single_key is not None:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setData(0, _KEY_ROLE, row.single_key)
                item.setData(0, _COL_ROLE, 0)
            else:
                # C-a: 親はチェック **不可** の三態コンテナ。CheckStateRole を
                # 持つので部分チェックは描かれるが ItemIsUserCheckable が無いので
                # クリックでは変わらない (「親をチェック = 全列」は 264k 鋳造の一撃)。
                placeholder = QTreeWidgetItem(item, [S.EXPORT_COLUMN_PLACEHOLDER])
                placeholder.setData(0, _PLACEHOLDER_ROLE, True)
            self._refresh_row_state(item)
        for row_index in auto_expand:
            # itemExpanded はまだ繋がっていないので明示的に合成する
            # (プロット中の列を「開いたら選択済み」で見せる従来挙動の維持)。
            self._materialize(items[row_index], row_index)
            items[row_index].setExpanded(True)
        for top in tops:
            top.setExpanded(True)  # expandAll() の置き換え: ファイル行だけ開く

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        """コンテナ行を初めて開いた瞬間に列アイテムを合成する (U1)。"""
        row_index = item.data(0, _ROW_ROLE)
        if row_index is None:  # ファイル行 (子は構築済み)。0 は正当な行番号なので
            return  # 真偽値ではなく None で判定すること
        if self._needs_columns(item):
            self._materialize(item, row_index)

    @staticmethod
    def _needs_columns(item: QTreeWidgetItem) -> bool:
        first = item.child(0)
        return first is not None and bool(first.data(0, _PLACEHOLDER_ROLE))

    def _materialize(self, item: QTreeWidgetItem, row_index: int) -> None:
        """この行の列だけをアイテム化する (1 回だけ・他の行には触らない)。"""
        row = self._rows[row_index]
        prefix = f"{row.file_key}{KEY_SEPARATOR}"
        names = self._column_names(row_index)
        was, self._syncing = self._syncing, True
        try:
            children: list[QTreeWidgetItem] = []
            for col_index, name in enumerate(names):
                key = prefix + name
                child = QTreeWidgetItem([name])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setData(0, _KEY_ROLE, key)
                child.setData(0, _ROW_ROLE, row_index)
                child.setData(0, _COL_ROLE, col_index)
                child.setCheckState(
                    0,
                    Qt.CheckState.Checked
                    if key in self._selected
                    else Qt.CheckState.Unchecked,
                )
                children.append(child)
            placeholder = item.child(0)
            assert placeholder is not None and placeholder.data(0, _PLACEHOLDER_ROLE)
            # 先に実列を足してからプレースホルダを外す — 子 0 個の瞬間を作ると
            # Qt が展開中の行を畳んでしまう。
            item.addChildren(children)
            item.takeChild(0)
        finally:
            self._syncing = was
        self._apply_filter_to_children(item, self._filter_query())

    # --- 選択 ---------------------------------------------------------
    def _iter_rows(self) -> Iterator[QTreeWidgetItem]:
        """全ファイルの物理チャンネル行 (トップレベルはファイル行)。"""
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            assert top is not None
            for j in range(top.childCount()):
                row_item = top.child(j)
                assert row_item is not None
                yield row_item

    def _iter_children(self) -> Iterator[QTreeWidgetItem]:
        """チェック可能な葉 (1 列行 + 合成済みの列)。

        **未展開の列は含まれない** — 選択の真実が _selected へ移ったのはこれが
        理由で、ここを数えて出力集合を作ってはならない。
        """
        for row_item in self._iter_rows():
            if row_item.data(0, _KEY_ROLE) is not None:
                yield row_item
            for j in range(row_item.childCount()):
                child = row_item.child(j)
                assert child is not None
                if child.data(0, _KEY_ROLE) is not None:
                    yield child

    def _column_names(self, row_index: int) -> tuple[str, ...]:
        """行の列名 (裸名・要求時生成)。"""
        row = self._rows[row_index]
        return self._app_vm.session.column_names_of(row.file_key, row.phys)

    def _column_keys(self, row_index: int) -> tuple[str, ...]:
        """行の列キー。**鋳造しない** (C-b) — 名前を組むだけで resolve は呼ばない。"""
        row = self._rows[row_index]
        if row.single_key is not None:
            return (row.single_key,)
        prefix = f"{row.file_key}{KEY_SEPARATOR}"
        return tuple(prefix + n for n in self._column_names(row_index))

    def _add_selection(self, row_index: int, col_index: int, key: str) -> None:
        if key in self._selected:
            return
        self._selected[key] = (row_index, col_index)
        self._selected_per_row[row_index] = self._selected_per_row.get(row_index, 0) + 1

    def _drop_selection(self, key: str) -> None:
        pos = self._selected.pop(key, None)
        if pos is None:
            return
        self._selected_per_row[pos[0]] -= 1

    def _set_state(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        was, self._syncing = self._syncing, True
        try:
            item.setCheckState(0, state)
        finally:
            self._syncing = was

    def _refresh_row_state(self, item: QTreeWidgetItem) -> None:
        """行のチェック表示を選択数カウンタから作り直す (表示専用・O(1))。"""
        row_index = item.data(0, _ROW_ROLE)
        row = self._rows[row_index]
        n = self._selected_per_row.get(row_index, 0)
        if n == 0:
            state = Qt.CheckState.Unchecked
        elif n >= row.count:
            state = Qt.CheckState.Checked
        else:
            state = Qt.CheckState.PartiallyChecked
        self._set_state(item, state)

    def _sync_widget_states(self) -> None:
        """実在するアイテムの表示だけを _selected から作り直す。

        未展開の列にはアイテムが無い — そこが「ウィジェットは表示専用」の所以。
        """
        for row_item in self._iter_rows():
            for j in range(row_item.childCount()):
                child = row_item.child(j)
                assert child is not None
                key = child.data(0, _KEY_ROLE)
                if key is None:
                    continue  # プレースホルダ
                self._set_state(
                    child,
                    Qt.CheckState.Checked
                    if key in self._selected
                    else Qt.CheckState.Unchecked,
                )
            self._refresh_row_state(row_item)

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        """ユーザーがチェックを触ったときだけ選択集合へ反映する。"""
        if self._syncing:
            return
        key = item.data(0, _KEY_ROLE)
        if key is None:
            return  # ファイル行 (Qt の三態伝播) / コンテナ行 (C-a: 選択できない)
        if item.checkState(0) == Qt.CheckState.Checked:
            self._add_selection(item.data(0, _ROW_ROLE), item.data(0, _COL_ROLE), key)
        else:
            self._drop_selection(key)
        parent = item.parent()
        if parent is not None and parent.data(0, _ROW_ROLE) is not None:
            # コンテナの三態を更新 (そこから先はファイル行へ Qt が伝播する)。
            self._refresh_row_state(parent)
        self._validate()

    def _checked_keys(self) -> list[str]:
        """出力集合 (フィルタ非依存・木の並び順)。

        並びは (行, 列) = ファイル順 -> ローダー順 -> 列順。set のハッシュ順で
        並べると PYTHONHASHSEED ごとに CSV の列順が変わる。
        """
        return sorted(self._selected, key=lambda k: self._selected[k])

    def _select_all(self) -> None:
        """全列を選択する — **鋳造しない** (C-b)。

        列キーは名前だけを組む。ここで resolve_signal を呼ぶと prod で 264k 本の
        Signal 鋳造 = ~390 MB の一撃になる。実際の読みは _on_accept が
        選択列 1 本ずつ行う。
        """
        for row_index in range(len(self._rows)):
            for col_index, key in enumerate(self._column_keys(row_index)):
                self._add_selection(row_index, col_index, key)
        self._sync_widget_states()
        self._validate()

    def _select_none(self) -> None:
        self._selected.clear()
        self._selected_per_row.clear()
        self._sync_widget_states()
        self._validate()

    def _filter_query(self) -> str:
        return self._filter.text().strip().lower()

    def _apply_filter(self, text: str) -> None:
        """行と (合成済みの) 列を絞り込む。

        照合は **表示テキスト** — E-0 の qualified 形 ("speed (csv_1)") ごと
        引っかかる従来挙動を保つ。加えて未展開のコンテナは自分の列名も見る
        (「フィルタは列名にマッチ」= ChannelBrowser と同じ規則)。列名走査は
        _row_matches だけで、名前は保持しない (行が覚えるのは直近のクエリ文字列と
        真偽値だけ)。
        """
        t = text.strip().lower()
        for row_item in self._iter_rows():
            row_item.setHidden(not self._row_matches(row_item, t))
            self._apply_filter_to_children(row_item, t)

    def _apply_filter_to_children(self, row_item: QTreeWidgetItem, t: str) -> None:
        for j in range(row_item.childCount()):
            child = row_item.child(j)
            assert child is not None
            child.setHidden(bool(t) and t not in child.text(0).lower())

    def _row_matches(self, row_item: QTreeWidgetItem, t: str) -> bool:
        """*t* がこの行 (表示テキスト または その列名) に当たるか。

        列名の再生成コストを 2 段で抑える。`_filter` の textChanged にはデバウンスが
        無く (ChannelBrowserView の 200ms シングルショットに相当するものがこの
        ダイアログには無い)、prod は 4,324 行 / 264,004 列なので、素直に書くと
        1 打鍵あたり 26 万本の f-string になる:

        1. 行テキストで決まるならそこで終わり。
        2. 物理チャンネル名が **それ自身 1 本の列** (スカラー / CSV) なら、その列名は
           行テキストそのものなので列名走査は要らない。`session.has_column()` は
           列名を 1 本も生成せずにこれを答える (T1)。
        3. 残る複数列の行だけが `column_names_of` を引き、結果を行へメモする
           (同一クエリの再評価では作り直さない)。

        それでも「複数列の行の列名は打鍵ごとに再生成される」コストは残る —
        **意図的受容**であり T9 の実測対象に含める。列名を保持すると E-3 が剥がした
        常駐メモリ (行あたり int 1 個で済ませている設計) がそのまま戻るため、ここは
        時間側で払う。
        """
        if not t:
            return True
        row_index = row_item.data(0, _ROW_ROLE)
        row = self._rows[row_index]
        if row.matched == t:
            return row.hit
        if t in row_item.text(0).lower():
            hit = True
        elif self._app_vm.session.has_column(row.file_key, row.phys):
            hit = False  # 1 列行: 列名は行テキストに含まれる = 上で決着済み
        else:
            hit = any(t in name.lower() for name in self._column_names(row_index))
        row.matched, row.hit = t, hit
        return hit
```

`_offset_active_for_checked`（`:326`）の最終行を差し替え（`_checked_keys()` の
ソートを毎 `_validate()` で払わない）:

```python
        return any(self._offset_for(k) != 0.0 for k in self._selected)
```

`_validate`（`:356-368`）の本体を差し替え:

```python
    def _validate(self) -> None:
        self._update_range_radios()
        opts = self._current_options()
        n = len(self._selected)
        if opts is not None:
            self._error.setText("" if n else S.EXPORT_NO_SELECTION_ERROR)
        ok = opts is not None and bool(n)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        # F-0/UX-28: N = 総選択数 (フィルタ非依存)。選択の真実が _selected に
        # あるので、フィルタで隠れた行も未展開の列も等しく数に入る = 実出力集合
        # (_on_accept の keys) と常に一致する。
        self._selection_label.setText(S.EXPORT_SELECTION_COUNT_TMPL.format(n=n))
```

`_on_accept`（`:379-398`）を差し替え:

```python
    def _on_accept(self) -> None:
        opts = self._current_options()
        keys = self._checked_keys()
        if opts is None or not keys:
            return
        # 選択列を **ここで初めて** 実体化する (C-b: 選択は名前だけ・実体は出口で
        # 1 本ずつ)。鋳造は Signal オブジェクトを作るだけで値は読まない
        # (LazyMdfValues) ので、保存先を訊く前に失敗を確定させてよい。
        signals: list[Signal] = []
        missing: list[str] = []
        for k in keys:
            sig = self._app_vm.session.resolve_signal(k)
            if sig is None:
                missing.append(k)
            else:
                signals.append(sig)
        if missing:
            # 旧実装はここが素の KeyError でダイアログごとクラッシュしていた。
            # 無言で落とすと「選んだのに出ていない CSV」になるので、出力せずに
            # 理由を出す。
            self._error.setText(
                S.EXPORT_UNRESOLVED_ERROR_TMPL.format(
                    n=len(missing), name=display_names(missing)[missing[0]]
                )
            )
            return
        path = self._save_path_provider()
        if not path:
            return  # 保存ダイアログをキャンセル
        # E-0: CSV ヘッダ名は選択集合(+ "timestamp" 母集団注入)内の衝突時のみ
        # qualified — core(csv_exporter)は名前を計算せず、渡された名前をそのまま
        # 書くだけ(core→gui import の層違反を作らない・spec §1.2)。
        header_map = csv_header_names(keys)
        opts = replace(opts, header_names=tuple(header_map[k] for k in keys))
        self._result = ExportRequest(
            signals=signals,
            output_path=Path(path),
            use_unified_timeline=self._unified.isChecked(),
            options=opts,
        )
        self.accept()
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/gui/test_export_csv_dialog.py -q`（新規 15＋既存 20 が全て GREEN）
Run: `uv run pytest tests/gui -q`

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

1 つずつ壊して**そのテストだけ**が RED になることを確かめ、報告に記す（確認後は必ず戻す）:

1. `self._tree.itemExpanded.connect(self._on_item_expanded)` をコメントアウト →
   `test_container_row_synthesizes_columns_on_expand`（2 パラメータ）が RED（子が `"…"` のまま）。
2. `_select_all` のループ内へ `self._app_vm.session.resolve_signal(key)` を挿入 →
   `test_select_all_does_not_mint_any_column` が RED（`resolve_calls == 4`）。
3. `_build_tree` の `else:` 分岐でコンテナにも `ItemIsUserCheckable` を付ける →
   `test_channel_row_is_a_tristate_container_not_checkable` が RED。
4. `_build_tree` 末尾の `auto_expand` ループを削除 →
   `test_initial_selection_expands_the_owning_row` が RED（`isExpanded()` False・子が未合成）。
5. `_row_matches` の最終分岐（`_column_names` 走査）を `hit = False` に →
   `test_filter_matches_column_names_of_unexpanded_rows` が RED（Mat が hidden）。
   併せて `has_column` の短絡を反転（`if not self._app_vm.session.has_column(...)`）すると
   同テストが「Clean が生き残る」で RED になる（短絡が**どちら向きか**まで pin されている確認）。
6. `_checked_keys` を `sorted(self._selected)` に戻す →
   `test_checked_keys_follow_tree_order_not_hash_order` が RED（`Clean` が先頭）。
7. `_on_accept` の `missing` 分岐を `continue` による無言スキップに変える →
   `test_unresolvable_column_reports_instead_of_raising` が RED（`_result` が入る）。

- [ ] **Step 6: 凍結カタログ 0 差分 → ゲート＋コミット**

撮影 fixture は 2 列 CSV（`t,EngineSpeed,VehSpd`）で配列チャンネルを含まないため、
全行が 1 列＝葉になり展開矢印も出ない。**ファイル行を `setExpanded(True)` で開き続ける**
以上、06 を含む全カタログはピクセル不変であるはず（差分が出たら `expandAll()` 廃止の
副作用＝実装バグなので、ベースラインを更新せず原因を潰すこと）:

```
uv run python scripts/capture_ui_screenshots.py --catalog --theme dark  --out design_export/e3_t5_after_dark
uv run python scripts/capture_ui_screenshots.py --catalog --theme light --out design_export/e3_t5_after_light
uv run python scripts/compare_screenshots.py design_export/e3_t5_before_dark  design_export/e3_t5_after_dark
uv run python scripts/compare_screenshots.py design_export/e3_t5_before_light design_export/e3_t5_after_light
```

Expected: 両テーマとも **exit 0（全ファイル完全一致）**。出力を報告に貼ること。

品質ゲート:

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

コミット:

```
git add src/valisync/gui/views/export_csv_dialog.py src/valisync/gui/strings.py tests/gui/test_export_csv_dialog.py
git commit -m "feat(gui): ExportCsvDialog を列の遅延展開へ (U1/C-a/C-b)

親=物理チャンネル行にプレースホルダ子を置き itemExpanded で列を合成し
expandAll() を廃止。選択の真実をダイアログ側の集合へ移し (未展開の列は
アイテムを持たないため木を数える実装は成立しない)、親はチェック不可の
三態コンテナ (C-a)、「すべて選択」は列名だけを組んで鋳造しない (C-b)。
_on_accept の素の KeyError を「保存先を訊く前に理由を出して中止」へ根治。
凍結カタログは両テーマ 0 差分。"
```

---

### Task 6: 反転本体（ローダー・数値ゲート・診断集約・鋳造契約）

**Files:**
- Create: `tests/core/loaders/test_loader_inversion.py`
- Create: `tests/gui/_physical_fixtures.py`
- Modify: `src/valisync/core/loaders/mdf_loader.py:12`（import）/ `:97-120`（`_explode_samples` → `_expansion_diagnostic`）/ `:499-608`（per-entry ループ = 反転本体）
- Modify: `tests/mdf4_helpers.py:341`（`write_mdf4_wide_2d` の直後に `write_mdf4_non_monotonic_2d` を追加）
- Test（意図された大音量 RED の書き換え）: `tests/test_loaders.py:22,719-733,736-749,752-765,787-835,851-889,895-905,946-979` / `tests/core/loaders/test_physical_channel_metadata.py:13-27` / `tests/core/loaders/test_mdf_loader_lazy.py:156-197` / `tests/test_native_dtype_memory.py:9-26` / `tests/test_demo_mf4.py:197-231,266-282` / `tests/realgui/test_channel_tree_flatten_realclick.py:449-457` / `tests/gui/test_channel_browser_physical.py:30-38`
- Test（fixture 追随）: `tests/gui/test_channel_browser_vm.py:448-470,482,525,572,597` / `tests/gui/test_channel_browser_view.py:144-190,753-775` / `tests/gui/test_signal_tree_model.py:19-51,122-136`

**Interfaces:**
- Consumes（Task 1）: `ColumnRecord(raw_base_name: str, group_index: int, channel_index: int, spec: ColumnSpec)`（`valisync.core.loaders.column_names`）／`SignalGroupManager.column_records(group_key) -> Mapping[str, ColumnRecord]`／`Session.column_names_of(key: str, display_name: str) -> tuple[str, ...]`／`Session.total_column_count(key: str) -> int`。**Task 1 がローダーの per-entry ループに置いた `ColumnRecord` 表の構築点は移動も削除もしない**（本タスクは「どこに置くか」だけを、Signal を発行する分岐の内側へ揃える）。
- Consumes（Task 2）: `SignalGroupManager._mint_column` — 本タスクで初めて **production 経路**になる（`Session.resolve_signal(f"{key}::Mat[1]")` が唯一の列取得口）。
- Consumes（Task 0）: `tests/core/loaders/test_column_roundtrip.py`（全数ラウンドトリップ・オラクル）。反転後は鋳造経路を通る。
- Consumes（既存）: `column_names.spec_from_probe` / `column_names.leaf_count`（数値リーフのみ）/ `mdf_loader._all_leaf_count`（dtype-blind）/ `LazyMdfValues(handle, name, gi, ci, length, selector=None)`。
- Produces（後続タスクが依存）:
  - **ローダーの新契約**: 1 物理チャンネル = `Signal` 1 個。`name` = LD-08 dedup 済み表示名、`metadata["physical_channel"] == name`、`values_source = LazyMdfValues(..., selector=None)`（値は 2-D/構造化のまま）、`column_records(group_key)` のキー集合 == `{s.name for s in group.signals}`（1:1・skip したチャンネルは両方に無い）。
  - `_expansion_diagnostic(display_name: str, samples: np.ndarray, leaf_total: int, diagnostics: list[Diagnostic]) -> None`（`_explode_samples` の置換・「N 本に展開」info の唯一の発行点）。
  - **診断集約契約**: 非単調/重複 warning・非数値 warning は物理チャンネル 1 件。1-D チャンネルは文言・件数・`signal_name` が byte-identical。
  - `tests/gui/_physical_fixtures.inject_physical_channels(app_vm, key, channels) -> list[Signal]`（Task 7 以降の GUI テストが反転後の形を注入する共有口）。

---

- [ ] **Step 1: 失敗テストを書く**

まず fixture を 1 本追加する（`tests/mdf4_helpers.py`・`write_mdf4_wide_2d` の直後）。

```python
def write_mdf4_non_monotonic_2d(tmp_path: Path) -> Path:
    """非単調/重複タイムスタンプの 2D (Nx3) チャンネル + 同時刻軸の通常チャンネル.

    診断 fan-out 集約 (E-3) の RED fixture。列展開時代は Mat[0..2] の 3 件へ増幅
    されていた非単調警告が物理チャンネル 1 件へ畳まれること、同じ時刻軸を持つ
    1-D チャンネル (Clean) の 1 件は文言ごと不変であることを、1 ファイルで対に
    固定する (prod では 1 グループ最大 96,000 件の増幅だった)。
    """
    ts = np.array([0.0, 2.0, 1.0, 1.0], dtype=np.float64)
    mat = np.array(
        [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]], dtype=np.uint8
    )
    mdf = MDF()
    try:
        mdf.append([ASignal(samples=mat, timestamps=ts, name="Mat")])
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]), timestamps=ts, name="Clean"
                )
            ]
        )
        path = tmp_path / "messy2d.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path
```

新規テストファイル `tests/core/loaders/test_loader_inversion.py`:

```python
# ruff: noqa: RUF002
"""E-3 反転: ローダーは物理チャンネル 1 本につき Signal を 1 個だけ発行する。

判定軸は 2 つ (spec の E-3 行):
  - **オブジェクト数**: 展開列は Signal にならない (prod 264,004 -> 4,324)。列は
    Session の解決器が ColumnRecord から要求時に鋳造する。
  - **診断**: 列ごとに増幅されていた warning を物理チャンネル 1 件へ集約し、
    1-D チャンネルの文言/件数/signal_name は byte-identical のまま。

demo_data 非依存 (CI 実行) — fixture は tests.mdf4_helpers の実 asammdf 往復。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tests.mdf4_helpers import (
    write_mdf4,
    write_mdf4_2d,
    write_mdf4_all_channels_bad,
    write_mdf4_non_monotonic,
    write_mdf4_non_monotonic_2d,
    write_mdf4_single_column_shapes,
    write_mdf4_structured,
    write_mdf4_value2text,
    write_mdf4_wide_2d,
)
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.session import Session


def _loaded(path: Path) -> tuple[Session, str, tuple]:
    """Session 経由でロードし (session, group_key, diagnostics) を返す。

    反転後は「列を見る」唯一の入口が鋳造つきの Session (resolve_signal) になる —
    SignalGroup.signals には物理チャンネルしか居ない。
    """
    session = Session()
    outcome = session.load(path)
    return session, outcome.key, outcome.diagnostics


def _orig_names(session: Session, key: str) -> list[str]:
    """グループの Signal 名を名前空間接頭辞なしで出現順に返す。"""
    return [s.name.split("::", 1)[1] for s in session.group_signals(key)]


def test_array_channel_is_one_signal_and_columns_are_minted(tmp_path: Path) -> None:
    """2D (Nx3) は Signal 1 個 (Mat)。列 Mat[0..2] は鋳造で同じ値を返す。"""
    session, key, _diags = _loaded(write_mdf4_2d(tmp_path))
    assert _orig_names(session, key) == ["Mat", "Clean"]
    parent = session.resolve_signal(f"{key}::Mat")
    assert parent is not None and parent.metadata["physical_channel"] == "Mat"

    m0 = session.resolve_signal(f"{key}::Mat[0]")
    m2 = session.resolve_signal(f"{key}::Mat[2]")
    assert m0 is not None and m2 is not None
    np.testing.assert_array_equal(m0.values, [0, 10, 20, 30])
    np.testing.assert_array_equal(m2.values, [2, 12, 22, 32])
    assert m0.values.dtype == np.uint8  # native dtype (FU-20) は鋳造経路でも保持
    assert np.shares_memory(m0.timestamps, m2.timestamps)  # 共有 master


def test_signal_count_is_physical_channels_not_columns(tmp_path: Path) -> None:
    """反転の主判定軸 (オブジェクト数): 1000 列の配列でも Signal は 2 個。

    prod の 264,004 -> 4,324 の CI 実行可能なプロキシ。母数 (列数) は U2 どおり
    列のまま残るので、両方を同時に見て「列が消えたから 2 個」ではないことを示す。
    """
    session, key, _d = _loaded(write_mdf4_wide_2d(tmp_path, cols=1000))
    assert len(session.group_signals(key)) == 2  # Wide + Clean
    assert session.total_column_count(key) == 1001  # 1000 列 + Clean
    assert session.resolve_signal(f"{key}::Wide[999]") is not None


def test_structured_channel_survives_leaf_level_numeric_gate(tmp_path: Path) -> None:
    """S2: 構造化の親 probe は dtype.kind == 'V' — 親でゲートすると全滅する。

    列単位ゲートをそのまま親に当てると「非数値型のためスキップ」で全構造化
    チャンネルが消える (この fixture では Pt が丸ごと消滅する)。
    """
    session, key, diags = _loaded(write_mdf4_structured(tmp_path))
    assert _orig_names(session, key) == ["Pt"]
    assert not any("非数値型" in d.message for d in diags)
    x = session.resolve_signal(f"{key}::Pt.x")
    y = session.resolve_signal(f"{key}::Pt.y")
    assert x is not None and y is not None
    np.testing.assert_array_equal(x.values, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(y.values, [10.0, 20.0, 30.0])


def test_expansion_info_counts_all_leaves_not_only_numeric_ones(
    tmp_path: Path,
) -> None:
    """混在構造 Q (x: f8 / tag: S2) の info は「2 本に展開」のまま (dtype-blind)。

    件数を column_names.leaf_count (数値のみ) へ替えると「1 本に展開」に変わる —
    _all_leaf_count を残す理由そのもの。列キー空間には数値リーフだけが載る。
    """
    session, key, diags = _loaded(write_mdf4_single_column_shapes(tmp_path))
    q_infos = [d for d in diags if d.level == "info" and d.signal_name == "Q"]
    assert [d.message for d in q_infos] == ["信号 'Q': 構造化チャンネルを 2 本に展開"]
    assert session.column_names_of(key, "Q") == ("Q.x",)
    assert session.resolve_signal(f"{key}::Q.x") is not None
    assert session.resolve_signal(f"{key}::Q.tag") is None  # 非数値リーフは列でない
    # 意図的 supersede (ここで固定する): 混在構造の非数値リーフ (Q.tag) は列単位の
    # warning を出さない — 列を作らないので「スキップ」を報告する主体が無い。反転前は
    # リーフ単位ループが「信号 'Q.tag': 非数値型のためスキップ（dtype |S2）」を 1 件
    # 出していた。1-D 非数値チャンネルの警告は不変
    # (test_non_numeric_channel_is_skipped_with_the_same_warning が別途固定)。
    assert not [d for d in diags if "非数値型" in d.message]


def test_non_numeric_channel_is_skipped_with_the_same_warning(tmp_path: Path) -> None:
    """1-D 非数値は今日どおり Signal ゼロ + 警告 1 件 (文言も据え置き)。"""
    result = MdfLoader().load(write_mdf4_all_channels_bad(tmp_path))
    assert result.signal_group is not None
    assert result.signal_group.signals == ()
    warns = [
        d for d in result.diagnostics if d.level == "warning" and "非数値型" in d.message
    ]
    assert len(warns) == 1
    assert warns[0].message.startswith("信号 'raw_bytes': 非数値型のためスキップ（dtype ")


def test_one_dimensional_diagnostics_stay_byte_identical(tmp_path: Path) -> None:
    """保存契約: 1-D チャンネルの非単調警告は文言・件数・signal_name とも不変。"""
    result = MdfLoader().load(write_mdf4_non_monotonic(tmp_path))
    warns = [d for d in result.diagnostics if d.signal_name == "messy"]
    assert len(warns) == 1
    assert warns[0].level == "warning"
    assert warns[0].message == (
        "信号 'messy': 非単調 1 箇所・重複タイムスタンプ 1 点"
        "（表示/演算は整列ビューで補正）"
    )
    assert not [d for d in result.diagnostics if d.signal_name == "clean"]


def test_array_channel_emits_one_warning_not_one_per_column(tmp_path: Path) -> None:
    """診断 fan-out の集約: 3 列の配列でも非単調警告は物理チャンネル 1 件。"""
    session, key, diags = _loaded(write_mdf4_non_monotonic_2d(tmp_path))
    # 反 vacuous 前置: 列は 3 本実在する (列が消えたから 1 件、ではない)
    assert session.column_names_of(key, "Mat") == ("Mat[0]", "Mat[1]", "Mat[2]")

    mat_warns = [d for d in diags if d.level == "warning" and d.signal_name == "Mat"]
    assert len(mat_warns) == 1
    assert mat_warns[0].message == (
        "信号 'Mat': 非単調 1 箇所・重複タイムスタンプ 1 点"
        "（表示/演算は整列ビューで補正）"
    )
    assert not [d for d in diags if d.signal_name in ("Mat[0]", "Mat[1]", "Mat[2]")]
    # 同じ時刻軸の 1-D チャンネルは byte-identical のまま 1 件
    clean_warns = [d for d in diags if d.signal_name == "Clean"]
    assert len(clean_warns) == 1


def test_column_records_are_one_to_one_with_emitted_signals(tmp_path: Path) -> None:
    """表と SignalGroup.signals の 1:1。skip したチャンネルは表にも載らない。

    ブラウザ/エクスポートの母数はこの表なので、Signal を作らなかったチャンネルが
    表に残ると「見えるのに永久に描かれない行」が復活する (C1 と同じ壊れ方)。
    """
    session, key, _d = _loaded(write_mdf4_single_column_shapes(tmp_path))
    assert set(session._groups.column_records(key)) == {"Mono", "P", "Q", "Clean"}
    assert set(session._groups.column_records(key)) == set(_orig_names(session, key))

    bad_session = Session()
    bad_key = bad_session.load(write_mdf4_all_channels_bad(tmp_path)).key
    assert bad_session._groups.column_records(bad_key) == {}
    assert bad_session.total_column_count(bad_key) == 0


def test_duplicate_names_stay_two_physical_signals_with_their_own_values(
    tmp_path: Path,
) -> None:
    """LD-08: 同名 2 本は sig[0]/sig[1] の 2 Signal。値は (gi, ci) ごとに正しい。"""
    session, key, _d = _loaded(
        write_mdf4(
            tmp_path / "dup.mf4",
            [
                {"name": "sig", "timestamps": [0.0, 1.0], "values": [1.0, 2.0]},
                {"name": "sig", "timestamps": [0.0, 1.0], "values": [3.0, 4.0]},
            ],
        )
    )
    assert _orig_names(session, key) == ["sig[0]", "sig[1]"]
    s0 = session.resolve_signal(f"{key}::sig[0]")
    s1 = session.resolve_signal(f"{key}::sig[1]")
    assert s0 is not None and s1 is not None
    np.testing.assert_array_equal(s0.values, [1.0, 2.0])
    np.testing.assert_array_equal(s1.values, [3.0, 4.0])
    assert s0.metadata["name_deduplicated"] is True


def test_exploded_parent_carries_no_conversion_metadata(tmp_path: Path) -> None:
    """LD-07: exploded 述語の帰結は不変 — 展開対象チャンネルは変換情報を持たず、
    1-D の enum チャンネルは従来どおり value_labels を持つ。"""
    session, key, _d = _loaded(write_mdf4_2d(tmp_path))
    mat = session.resolve_signal(f"{key}::Mat")
    assert mat is not None
    assert "value_labels" not in mat.metadata
    assert "conversion_info" not in mat.metadata

    enum_session = Session()
    enum_key = enum_session.load(write_mdf4_value2text(tmp_path)).key
    turn = enum_session.resolve_signal(f"{enum_key}::TurnSig")
    assert turn is not None
    assert turn.metadata["value_labels"] == {0.0: "OFF", 1.0: "LEFT", 2.0: "RIGHT"}
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_loader_inversion.py -q`

Expected: 10 件中 8 件が FAIL（`test_non_numeric_channel_is_skipped_with_the_same_warning` と `test_one_dimensional_diagnostics_stay_byte_identical` は反転前から GREEN = 1-D の byte-identical 契約が「変えてはいけない側」であることの前置）。代表:

- `test_array_channel_is_one_signal_and_columns_are_minted`:
  `AssertionError: assert ['Mat[0]', 'Mat[1]', 'Mat[2]', 'Clean'] == ['Mat', 'Clean']`
- `test_signal_count_is_physical_channels_not_columns`:
  `AssertionError: assert 1001 == 2`
- `test_structured_channel_survives_leaf_level_numeric_gate`:
  `AssertionError: assert ['Pt.x', 'Pt.y'] == ['Pt']`
- `test_array_channel_emits_one_warning_not_one_per_column`:
  `AssertionError: assert 0 == 1`（今日の warning は `signal_name` が `Mat[0]`/`Mat[1]`/`Mat[2]` の 3 件）
- `test_column_records_are_one_to_one_with_emitted_signals`:
  `AssertionError: assert {'Mono','P','Q','Clean'} == {'Mono[0]','P.x','Q.x','Clean'}`

- [ ] **Step 3: 実装**

**3a. ローダーの反転（`src/valisync/core/loaders/mdf_loader.py`）**

import 行（`:12`）を差し替える（`ColumnRecord` は Task 1 が既に足しているならそのまま）:

```python
from valisync.core.loaders.column_names import (
    ColumnRecord,
    ColumnSpec,
    leaf_count,
    spec_from_probe,
)
```

`_explode_samples`（`:97-120`）を **診断専用**の関数へ置き換える（`_flatten` / `_leaf_column_count` / `_all_leaf_count` は 3 つとも残す — `_flatten` は `LazyMdfValues.array()` が使い続け、`_leaf_column_count` は 1024 ガードの母数、`_all_leaf_count` は info 件数の dtype-blind カウンタ）:

```python
def _expansion_diagnostic(
    display_name: str,
    samples: np.ndarray,
    leaf_total: int,
    diagnostics: list[Diagnostic],
) -> None:
    """「N 本に展開」info を物理チャンネル 1 件だけ emit する (E-3 反転).

    列を実際に作らなくなったので、件数は **dtype 非依存の全リーフ数**
    (_all_leaf_count) を渡す — 数値リーフだけを数える column_names.leaf_count に
    替えると混在構造 (Q.x + Q.tag) の表示が「2 本」->「1 本」に変わり、列展開
    時代の文言と非互換になる。文言と signal_name は旧 _explode_samples と同一。
    """
    if samples.dtype.names:
        shape_desc = "構造化チャンネル"
    else:
        shape_desc = "x".join(str(d) for d in samples.shape[1:]) + " 配列"
    diagnostics.append(
        Diagnostic(
            level="info",
            message=f"信号 '{display_name}': {shape_desc}を {leaf_total} 本に展開",
            signal_name=display_name,
        )
    )
```

`_load_group` の per-entry ループ（`:500-608` — `for (base_name, _g, _c), probe in zip(...)` の本体全部）を次で置き換える。`master`/`diffs`/`n_backward`/`n_dup`/`probes` の算出（`:472-499`）は無変更:

```python
        for (base_name, _g, _c), probe in zip(entries, probes, strict=True):
            if cancel is not None and cancel():
                raise LoadCancelled(f"load cancelled: {resolved_path.name}")
            idx = name_seen.get(base_name, 0)
            name_seen[base_name] = idx + 1
            deduplicated = name_total[base_name] > 1
            signal_name = f"{base_name}[{idx}]" if deduplicated else base_name

            samples = probe.samples
            spec = spec_from_probe(samples)
            exploded = samples.ndim != 1 or bool(samples.dtype.names)
            # E-3 反転: 展開列は Signal にしない。作るのは **物理チャンネル 1 本に
            # つき Signal 1 個** で、列は SignalGroupManager が ColumnRecord から
            # 要求時に鋳造する (264,004 -> 4,324)。
            all_leaves = _all_leaf_count(spec)
            if exploded and all_leaves:
                _expansion_diagnostic(signal_name, samples, all_leaves, diagnostics)
            if all_leaves == 0:
                # 0 幅軸の展開不能列。列展開時代も pairs が空でループが 1 度も回らず
                # Signal も診断も出なかった — その沈黙をそのまま保つ。
                continue

            # 数値性は **リーフ単位** で判定する (spec S2)。構造化チャンネルの親
            # probe は dtype.kind == 'V' なので、親の dtype をゲートに使うと全ての
            # 構造化チャンネルが「非数値型のためスキップ」で消滅する。probe は非 raw
            # (= 本読みと同じ側) なので、その dtype がそのままゲートの根拠になる
            # (raw 側で判定すると TTAB が消える・_PROBE_OPTIONS のコメント参照)。
            if leaf_count(spec) == 0:
                # signal_name を Diagnostic に載せないのは列展開時代と同一
                # (1-D 非数値の診断を byte-identical に保つ)。
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"信号 '{signal_name}': 非数値型のためスキップ"
                            f"（dtype {samples.dtype}）"  # noqa: RUF001
                        ),
                    )
                )
                continue

            # 非単調/重複はグループ master の性質なので **物理チャンネル 1 件**。
            # 列ごとの emit は prod で 1 グループ最大 96,000 件の水増しだった
            # (配列/構造化チャンネルの列単位 warning 集約は意図的 supersede・
            # 1-D チャンネルの文言/件数/signal_name は不変)。
            if n_backward or n_dup:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"信号 '{signal_name}': 非単調 {n_backward} 箇所・"
                            f"重複タイムスタンプ {n_dup} 点"
                            "（表示/演算は整列ビューで補正）"  # noqa: RUF001
                        ),
                        signal_name=signal_name,
                    )
                )

            # value_labels (value2text) は 1D 通常チャンネルのみ継承する —
            # value2text はスカラー enum の概念で、展開対象チャンネル (2D/構造化)
            # には意味を持たない (LD-07)。取得元を生チャンネルにしているのは、
            # 展開時に None を渡して継承を止められる唯一の口だから (probe は非 raw
            # なので conversion が常に None)。
            raw_conversion = (
                None if exploded else mdf.groups[_g].channels[_c].conversion
            )
            metadata = _extract_metadata(probe, raw_conversion)
            # ブラウザの「1 行=1 物理チャンネル」グループ化キー。生 base_name では
            # なく signal_name を使う: LD-08 で name_total>1 のとき base_name は別の
            # 物理チャンネル (別 gi/ci・別 shape/unit) と共有され同一性を失う。
            metadata["physical_channel"] = signal_name
            if deduplicated:
                # E-2b: LD-08 の [idx] 曖昧化を経た名前だけに立てる旗 (cross-file の
                # 同名重ねから除外する唯一の根拠)。展開名 "Mat[0]" は文字列として
                # 同じ形でも立てない — 判定は name_total[base_name] だから。
                metadata["name_deduplicated"] = True
            # Task 1 が導入した ColumnRecord 表の構築点 (load() のローカルから
            # _load_group へ渡される引数名は Task 1 のとおり column_records)。
            # **Signal を作る分岐の内側**に置くこと — skip したチャンネルを表に
            # 残すと「行はあるが Signal が無い」死にキーが復活する。
            column_records[signal_name] = ColumnRecord(
                raw_base_name=base_name,
                group_index=_g,
                channel_index=_c,
                spec=spec,
            )
            signals.append(
                Signal(
                    name=signal_name,
                    timestamps=master,
                    # selector=None: 物理チャンネル全体を読む器。列は鋳造側が
                    # ColumnRecord から selector 付き LazyMdfValues で作る (LD-14)。
                    values_source=LazyMdfValues(
                        handle, base_name, _g, _c, length=len(master)
                    ),
                    file_format=self._format_label(mdf),  # LD-02: MDF3/MDF4
                    bus_type=_detect_bus_type(getattr(probe, "source", None)),
                    source_file=str(resolved_path),
                    metadata=metadata,
                )
            )
```

**3b. 意図された大音量 RED の書き換え（削除しない）**

`tests/test_loaders.py:22` の import を `from valisync.core.session import LoadCancelled, Session` にしたうえで:

```python
def test_2d_channel_is_one_signal_with_minted_columns(tmp_path: Path) -> None:
    """LD-12/E-3: 2D (Nx3) は Signal 1 個 — 列 Mat[0..2] は鋳造で引ける.

    旧 test_2d_channel_explodes_into_columns の等価移送。値・共有 master・info 1 件・
    skip 無しは全て保存し、**列 Signal がどこに居るか**だけが変わる。
    """
    session = Session()
    outcome = session.load(write_mdf4_2d(tmp_path))
    names = {s.name.split("::", 1)[1] for s in session.group_signals(outcome.key)}
    assert names == {"Mat", "Clean"}
    m0 = session.resolve_signal(f"{outcome.key}::Mat[0]")
    m2 = session.resolve_signal(f"{outcome.key}::Mat[2]")
    assert m0 is not None and m2 is not None
    assert np.array_equal(m0.values, [0.0, 10.0, 20.0, 30.0])
    assert np.array_equal(m2.values, [2.0, 12.0, 22.0, 32.0])
    assert np.shares_memory(m0.timestamps, m2.timestamps)
    infos = [d for d in outcome.diagnostics if d.level == "info" and "Mat" in d.message]
    assert len(infos) == 1 and "3 本に展開" in infos[0].message
    assert not any(
        "スキップ" in d.message and "Mat" in d.message for d in outcome.diagnostics
    )


def test_2d_channel_expansion_names_are_not_flagged_deduplicated(
    tmp_path: Path,
) -> None:
    """E-2b: LD-14 array-expansion names ("Mat[0]" etc.) look textually like a
    LD-08 dedup suffix but must NOT carry metadata["name_deduplicated"] — they
    are deterministic/cross-file comparable, unlike the per-file [idx]
    disambiguation. E-3: 鋳造列と親の両方で確認する (旗の継承点が増えたため)。"""
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    for orig in ("Mat", "Mat[0]", "Mat[1]", "Mat[2]", "Clean"):
        sig = session.resolve_signal(f"{key}::{orig}")
        assert sig is not None, orig
        assert "name_deduplicated" not in sig.metadata


def test_structured_channel_fields_visible(tmp_path: Path) -> None:
    """LD-12: 構造化 (x,y) がフィールド単位で見える (Pt.x / Pt.y の列キーで引ける)."""
    session = Session()
    outcome = session.load(write_mdf4_structured(tmp_path))
    x = session.resolve_signal(f"{outcome.key}::Pt.x")
    assert x is not None, "x 成分が列として引けない"
    assert np.array_equal(x.values, [1.0, 2.0, 3.0])
    assert not any(d.level == "error" for d in outcome.diagnostics)
```

`_explode_samples` 3 本（`:787-835`）は、名前/値の生成を担う **production 関数**（`_flatten` — `LazyMdfValues.array()` が使い続ける）へ照準変更する。assert は 1 つも落とさない:

```python
def test_flatten_subarray_field_one_level() -> None:
    """構造化フィールドが (N,k) サブ配列のとき Name.field[i] に1段展開される."""
    from valisync.core.loaders.mdf_loader import _flatten

    rec = np.zeros(3, dtype=[("mat", "<f8", (2,)), ("s", "<f8")])
    rec["mat"] = [[1, 2], [3, 4], [5, 6]]
    rec["s"] = [7, 8, 9]
    pairs = _flatten("Obj", rec)
    assert [n for n, _ in pairs] == ["Obj.mat[0]", "Obj.mat[1]", "Obj.s"]
    assert np.array_equal(dict(pairs)["Obj.mat[1]"], [2.0, 4.0, 6.0])


def test_flatten_over_nested_field_expands() -> None:
    """ndim>2 のネストフィールドは Name.field[i][j] へ多段展開される (LD-14)."""
    from valisync.core.loaders.mdf_loader import _flatten

    rec = np.zeros(2, dtype=[("deep", "<f8", (2, 2)), ("s", "<f8")])
    rec["deep"] = np.arange(2 * 2 * 2).reshape(2, 2, 2)
    rec["s"] = [7.0, 8.0]
    pairs = _flatten("Obj", rec)
    assert [n for n, _ in pairs] == [
        "Obj.deep[0][0]",
        "Obj.deep[0][1]",
        "Obj.deep[1][0]",
        "Obj.deep[1][1]",
        "Obj.s",
    ]
    # deep[1][1] = rec["deep"][:, 1, 1] = [3, 7]
    assert np.array_equal(dict(pairs)["Obj.deep[1][1]"], [3.0, 7.0])


def test_flatten_plain_3d_expands_and_reports_one_info() -> None:
    """素の 3D は Cube[i][j] へ多段展開され、info は物理チャンネル 1 件 (LD-14/E-3).

    旧 test_explode_samples_plain_3d_expands の等価移送: 名前/値は _flatten が、
    「本に展開」診断は _expansion_diagnostic が担うようになった (E-3 で
    _explode_samples は列を作らなくなったため 2 つに分離)。
    """
    from valisync.core.loaders.column_names import spec_from_probe
    from valisync.core.loaders.mdf_loader import (
        _all_leaf_count,
        _expansion_diagnostic,
        _flatten,
    )

    arr = np.arange(4 * 2 * 2).reshape(4, 2, 2).astype(np.float64)
    pairs = _flatten("Cube", arr)
    assert [n for n, _ in pairs] == [
        "Cube[0][0]",
        "Cube[0][1]",
        "Cube[1][0]",
        "Cube[1][1]",
    ]
    assert np.array_equal(dict(pairs)["Cube[1][1]"], arr[:, 1, 1])

    diags: list = []
    _expansion_diagnostic("Cube", arr, _all_leaf_count(spec_from_probe(arr)), diags)
    assert len(diags) == 1
    assert diags[0].message == "信号 'Cube': 2x2 配列を 4 本に展開"
```

1024 ガードの 3 本（`:851-889`）— **反 vacuous 前置**を足す（反転で「Wide で始まる名前が 1 つも無い」が構造的に成立しやすくなるため）:

```python
def test_oversized_expands_only_when_confirmed(tmp_path: Path) -> None:
    """confirm_expansion が選んだ超過チャンネルのみ展開される (LD-14)."""
    from valisync.core.loaders.mdf_loader import ExpansionRequest

    path = write_mdf4_wide_2d(tmp_path, cols=1025)
    seen: list[ExpansionRequest] = []

    def confirm(req: ExpansionRequest) -> set[int]:
        seen.append(req)
        return {0}  # Wide を展開する

    session = Session()
    key = session.load(path, confirm_expansion=confirm).key
    names = {s.name.split("::", 1)[1] for s in session.group_signals(key)}
    assert names == {"Wide", "Clean"}  # E-3: 行は物理チャンネル
    # 承認された 1025 列 (0..1024) は鋳造で引ける
    assert session.resolve_signal(f"{key}::Wide[0]") is not None
    assert session.resolve_signal(f"{key}::Wide[1024]") is not None
    assert session.total_column_count(key) == 1026
    assert len(seen) == 1 and seen[0].channels[0].name == "Wide"


def test_oversized_skipped_when_declined(tmp_path: Path) -> None:
    """空集合を返すと超過チャンネルはスキップ・警告診断が出る・他は生存 (LD-14)."""
    path = write_mdf4_wide_2d(tmp_path, cols=1025)
    # 反 vacuous 前置: 承認すれば "Wide" は現れる。E-3 で列 Signal が消えたので
    # 「Wide で始まる名前が無い」だけでは間違った理由の PASS と区別できない。
    approved = MdfLoader().load(path, confirm_expansion=lambda req: {0})
    assert "Wide" in {s.name for s in approved.signal_group.signals}

    result = MdfLoader().load(path, confirm_expansion=lambda req: set())
    names = {s.name for s in result.signal_group.signals}
    assert "Clean" in names
    assert not any(n.startswith("Wide") for n in names)
    warns = [
        d for d in result.diagnostics if d.level == "warning" and "Wide" in d.message
    ]
    assert len(warns) == 1 and "1024" in warns[0].message


def test_oversized_skipped_headless_without_callback(tmp_path: Path) -> None:
    """コールバック不在 (ヘッドレス) は超過を全スキップ+警告 (LD-14 既定)."""
    path = write_mdf4_wide_2d(tmp_path, cols=1025)
    approved = MdfLoader().load(path, confirm_expansion=lambda req: {0})
    assert "Wide" in {s.name for s in approved.signal_group.signals}  # 反 vacuous 前置

    result = MdfLoader().load(path)  # confirm_expansion 無し
    names = {s.name for s in result.signal_group.signals}
    assert "Clean" in names and not any(n.startswith("Wide") for n in names)
    assert any(d.level == "warning" and "Wide" in d.message for d in result.diagnostics)
```

native dtype（`:895-905`）と selector 経路（`:946-979`）:

```python
def test_loader_preserves_native_uint8_dtype(tmp_path: Path) -> None:
    # write_mdf4_2d: 4x3 uint8 の "Mat" (3 列) + float64 の "Clean"。
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    mat_cols = [session.resolve_signal(f"{key}::Mat[{i}]") for i in range(3)]
    assert all(s is not None for s in mat_cols)
    # native uint8 を保持 — astype(float64) なら float64 になり FAIL。
    assert all(s.values.dtype == np.uint8 for s in mat_cols)
    clean = session.resolve_signal(f"{key}::Clean")
    assert clean is not None and clean.values.dtype == np.float64
```

`test_lazy_selector_column_matches_eager_flatten_synthetic` は先頭の取得だけ差し替える（以降の eager 突合は無変更）:

```python
    path = write_mdf4_2d(tmp_path)
    session = Session()
    key = session.load(path).key
    mat1 = session.resolve_signal(f"{key}::Mat[1]")  # E-3: 列は鋳造で得る
    assert mat1 is not None
    assert mat1._values_source.is_materialized is False  # 鋳造直後は未展開で待機
```

`tests/core/loaders/test_physical_channel_metadata.py`（`from valisync.core.session import Session` を追加）:

```python
def test_expanded_columns_carry_physical_channel_name(tmp_path: Path) -> None:
    # E-3: 行は物理チャンネル (Mat / Clean)。列 Mat[0..2] は鋳造で得る。
    # 鋳造列も physical_channel を継承する (ブラウザのグループ化キー)。
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    cols = [session.resolve_signal(f"{key}::Mat[{i}]") for i in range(3)]
    assert all(c is not None for c in cols)
    assert {c.metadata["physical_channel"] for c in cols} == {"Mat"}
    parent = session.resolve_signal(f"{key}::Mat")
    assert parent is not None and parent.metadata["physical_channel"] == "Mat"
    clean = session.resolve_signal(f"{key}::Clean")
    assert clean is not None and clean.metadata["physical_channel"] == "Clean"
```

`tests/core/loaders/test_mdf_loader_lazy.py`（demo-gated・`Session` を import）:

```python
def test_lazy_selector_column_equals_eager_flatten() -> None:
    """LD-14: 鋳造列 (selector 付き) の遅延値が eager select+_flatten と一致する.

    E-3 反転後、展開列は SignalGroup に居ない — ColumnRecord からの鋳造が
    selector 分岐の production 経路になった。quick_demo の Radar.ObjMatrix
    (uint8・8 列) をその実カバレッジに使う。
    """
    session = Session()
    key = session.load(DEMO, confirm_expansion=None).key
    base_name = "Radar.ObjMatrix"
    leaf_name = f"{base_name}[3]"
    col = session.resolve_signal(f"{key}::{leaf_name}")
    assert col is not None, "配列列が鋳造できない"
    assert col._values_source.is_materialized is False

    got = col.values  # 遅延展開 (selector リーフ抽出)
    assert got.flags.writeable is False

    m = MDF(str(DEMO))
    try:
        asig = m.select(
            [base_name],
            raw=False,
            ignore_value2text_conversions=True,
            copy_master=False,
        )[0]
        expected = dict(_flatten(base_name, asig.samples))[leaf_name]
    finally:
        m.close()
    np.testing.assert_array_equal(got, expected)
```

`tests/test_native_dtype_memory.py`（`MdfLoader` import を `Session` へ）:

```python
def test_wide_uint8_channel_keeps_native_footprint(tmp_path):
    cols = 1000  # < EXPANSION_COLUMN_LIMIT(1024): 全列が展開対象
    path = write_mdf4_wide_2d(tmp_path, cols=cols)
    session = Session()
    key = session.load(path).key
    # E-3: 列は事前生成されない — 鋳造して値の footprint を測る。
    assert session.column_names_of(key, "Wide") == tuple(
        f"Wide[{i}]" for i in range(cols)
    )
    wide = [session.resolve_signal(f"{key}::Wide[{i}]") for i in range(cols)]
    assert all(s is not None for s in wide)

    # 各列は 3 サンプル (write_mdf4_wide_2d の ts は 3 点) の uint8。
    assert all(s.values.dtype == np.uint8 for s in wide)
    native_bytes = sum(s.values.nbytes for s in wide)
    # native: cols * 3 * 1。float64 に膨張していれば *8 になり FAIL。
    assert native_bytes == cols * 3 * 1
```

`tests/test_demo_mf4.py`（CI 実行・smoke プロファイル生成）— `test_2d_channels_explode_in_valisync` の名前判定ブロックを置換:

```python
    names = {sig.name.split("::", 1)[1] for sig in session.group_signals(outcome.key)}
    # E-3 反転: 2D チャンネルは **物理チャンネル 1 行** として現れ、列は解決器が
    # 鋳造する。旧 assert（親名が信号として現れない）は意図的 supersede — 親は
    # 2-D 値の器で、プロット/エクスポートには載らない (Task 4/7 が拒否する)。
    assert "Radar.ObjMatrix" in names and "Cam.ObjMatrix" in names
    for i in range(8):
        assert session.resolve_signal(f"{outcome.key}::Radar.ObjMatrix[{i}]") is not None
        assert session.resolve_signal(f"{outcome.key}::Cam.ObjMatrix[{i}]") is not None
    assert session.column_names_of(outcome.key, "Radar.ObjMatrix") == tuple(
        f"Radar.ObjMatrix[{i}]" for i in range(8)
    )
```

（`infos`/`skips` の assert は無変更で残す。）`test_valisync_loads_smoke_profile` の該当 1 行:

```python
    assert "Radar.ObjMatrix" in names  # (b) 2D チャンネルは親行として見える (E-3)
    assert session.resolve_signal(f"{outcome.key}::Radar.ObjMatrix[0]") is not None
```

`tests/realgui/test_channel_tree_flatten_realclick.py:455-458` — `len(phys) < len(group_sigs)` は反転後**構造的に成立不能**（両者が同数になる）。独立オラクルを ColumnSpec 由来の列総数へ照準変更する:

```python
    total_cols = window.app_vm.session.total_column_count(key)
    assert len(phys) < total_cols, (
        f"列が畳まれていない (物理 {len(phys)} == 列 {total_cols})。{shot}"
    )
```

`tests/gui/test_channel_browser_physical.py:30-38` — 反 vacuous 前置:

```python
def test_tree_groups_is_one_row_per_physical_channel(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    rows = vm.tree_groups()
    names = [name for name, _unit, _key, _n, _single in rows]
    assert names == ["Mat", "Clean"]
    mat = next(r for r in rows if r[0] == "Mat")
    # 反 vacuous 前置: 列は 3 本実在する。E-3 で列 Signal が消えたので、
    # 「Mat[ で始まる行が無い」だけでは間違った理由の PASS と区別できない。
    assert [c[0] for c in vm.column_names_for(mat[2])] == ["Mat[0]", "Mat[1]", "Mat[2]"]
    assert not any(n.startswith("Mat[") for n in names)  # 列は行にならない
    assert mat[3] == 3  # column_count
    assert mat[4] is None  # 複数列 -> 親 (single_column なし)
```

**3c. GUI fixture の追随（サイトごとの意図判断）**

共有ヘルパ `tests/gui/_physical_fixtures.py` を新設（`_panel_factory.py` と同じ配置規約）:

```python
"""反転後の production 形 (1 Signal = 1 物理チャンネル + 列名表) を注入する。

反転前は ``session.group_signals`` に **列 Signal** を並べれば済んだが、反転後の
production はそこに物理チャンネルしか置かず、列名は ColumnRecord 由来の
``Session.column_names_of`` から来る。偽物 session がその 2 面を揃えないと、
「今日の production では起きない形」を検証し続けることになる。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from valisync.core.models import Signal

# (物理チャンネル表示名, unit, 列名タプル)
Channel = tuple[str, str, tuple[str, ...]]


def physical_signal(key: str, display_name: str, unit: str, n_columns: int) -> Signal:
    """ローダーが反転後に発行する形の Signal 1 本。

    複数列のチャンネルは values も 2-D にする — 「親 Signal をそのままプロット/
    エクスポートへ流す」壊れ方が値の形として現れるようにするため (1-D の偽物に
    すると誤配線がテストを素通りする)。
    """
    values = np.zeros((1, n_columns)) if n_columns > 1 else np.zeros(1)
    return Signal(
        name=f"{key}::{display_name}",
        timestamps=np.array([0.0]),
        values=values,
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={"unit": unit, "physical_channel": display_name},
    )


def inject_physical_channels(
    app_vm: Any, key: str, channels: Sequence[Channel]
) -> list[Signal]:
    """*app_vm* の session を「反転後のローダー出力」で差し替える。

    group_signals は物理チャンネルのみ、column_names_of / total_column_count は
    ColumnRecord 由来の列名表 (Task 1 の Session API) を返す。
    """
    sigs = [
        physical_signal(key, name, unit, len(cols)) for name, unit, cols in channels
    ]
    columns = {name: cols for name, _unit, cols in channels}
    total = sum(len(cols) for cols in columns.values())
    app_vm.session.group_signals = lambda _k: list(sigs)  # type: ignore[method-assign]
    app_vm.session.column_names_of = lambda _k, display: columns[display]  # type: ignore[method-assign]
    app_vm.session.total_column_count = lambda _k: total  # type: ignore[method-assign]
    return sigs
```

サイトごとの判断（機械置換しない）:

| ファイル:行 | 注入していたもの | 判断 |
|---|---|---|
| `test_channel_browser_vm.py:83,141,172,197` | スカラー 1 本（tooltip/unit） | **変更しない** — スカラーは反転後も 1 Signal = 1 物理チャンネルで production と同型 |
| `test_channel_browser_vm.py:383` / `test_channel_browser_view.py:391` | 空リスト | **変更しない**（0 チャンネル経路） |
| `test_channel_browser_vm.py:299-314,399-406` | 実 `group_signals` の spy | **変更しない**（呼出回数の pin であって形に依存しない） |
| `test_channel_browser_vm.py:482,525,572,597` | 列 Signal（`Arr[0]`/`X[0]`/`Struct.field`） | **flip** |
| `test_channel_browser_view.py:124` | スカラー（Unit 列幅） | **変更しない** |
| `test_channel_browser_view.py:179,772` | 列 Signal（親を立てる） | **flip** |
| `test_signal_tree_model.py:45,125` | 列 Signal | **flip** |
| `test_signal_preview_vm.py:29,72-78,100,140,159-165,184` | スカラーのみ | **変更しない**（列プレビューの新経路は Task 7 が持つ） |
| `test_export_csv_dialog.py:24` | `_FakeSession`（CSV スカラー） | **変更しない** — CSV は 1 列 = 1 物理チャンネル（spec の意図的逸脱）。Task 5 が `column_names_of`/`total_column_count` を `_FakeSession` に足していなければ、そこで足す |
| `test_reference_overlay.py:61,128` | 実 `Session` + CSV グループ | **変更しない**（CSV に展開の概念が無い。列レベルのマッチは Task 7 の新テスト） |

flip の具体形（`from tests.gui._physical_fixtures import inject_physical_channels` を各ファイルへ追加し、既存の `app_vm.set_active_file(...)` 行はそのまま残す）:

```python
# test_channel_browser_vm.py:482  test_tree_groups_buckets_arrays_under_base
    inject_physical_channels(
        app_vm,
        "g",
        [
            ("Arr", "V", ("Arr[0]", "Arr[1]", "Arr[2]")),
            ("Scalar", "V", ("Scalar",)),
            ("Struct", "V", ("Struct.field",)),
        ],
    )

# test_channel_browser_vm.py:525  test_tree_groups_honors_filter
    inject_physical_channels(
        app_vm,
        "g",
        [
            ("Arr", "V", ("Arr[0]", "Arr[1]")),
            ("Speed", "V", ("Speed",)),
            ("Brake", "V", ("Brake",)),
        ],
    )

# test_channel_browser_vm.py:572  test_non_contiguous_columns_stay_in_their_own_row
    inject_physical_channels(
        app_vm, "g", [("X", "V", ("X[0]", "X[1]")), ("Y", "V", ("Y",))]
    )

# test_channel_browser_vm.py:597  test_shown_count_matches_matched_column_total
    inject_physical_channels(
        app_vm,
        "g",
        [("a", "V", ("a",)), ("b", "V", ("b",)), ("ab", "V", ("ab",))],
    )

# test_channel_browser_view.py:179  _make_view_with_arrays（ローカル _sig は削除）
    inject_physical_channels(
        app_vm, "g", [("Arr", "V", ("Arr[0]", "Arr[1]")), ("Scalar", "V", ("Scalar",))]
    )

# test_channel_browser_view.py:772（ローカル _sig は削除）
    inject_physical_channels(
        app_vm,
        "g",
        [("Arr", long_unit, ("Arr[0]", "Arr[1]")), ("Scalar", "V", ("Scalar",))],
    )

# test_signal_tree_model.py:45  _model
    inject_physical_channels(
        app_vm,
        "g",
        [("Arr", "V", ("Arr[0]", "Arr[1]", "Arr[2]")), ("Scalar", "V", ("Scalar",))],
    )

# test_signal_tree_model.py:125  _sort_model（列順は未ソートのまま = 子ソートの母数）
    inject_physical_channels(
        app_vm,
        "g",
        [
            ("Zeta", "V", ("Zeta",)),
            ("alpha", "V", ("alpha",)),
            ("Mid", "V", ("Mid",)),
            ("Arr", "V", ("Arr[2]", "Arr[0]", "Arr[1]")),
        ],
    )
```

`test_channel_browser_vm.py:572` の docstring は挙動に合わせて更新する（span 機構は E-3 で消えるので、旧 sabotage 文（`spans[-1] = (last_start, i + 1)` 固定）はもう存在しない）:

```python
    """m1: 1 物理チャンネルの列は必ず **自分の ColumnRecord** から来る。

    E-3 前は列 Signal の並びから span を切り出していたため、割り込んだ別チャンネル
    を巻き込む壊れ方があった (旧 sabotage: span を常に伸ばす)。反転後は行ごとに
    列名表を引くので構造的に起きないが、「行が他行の列を返さない」不変条件自体は
    ドラッグ/フィルタ/エクスポートの土台なのでここで固定し続ける。
    """
```

flip 後に呼び出しが無くなった `_synth_sig`（`test_channel_browser_vm.py:448-470`）・`_sig`（`test_signal_tree_model.py:19-39` と `test_channel_browser_view.py` のローカル 2 つ）は `grep -n "_synth_sig\|_sig(" <file>` で残存参照ゼロを確認してから削除する（ruff は未使用関数を検出しない）。

- [ ] **Step 4: 通ることを確認**

```
uv run pytest tests/core/loaders/test_loader_inversion.py -q
uv run pytest tests/test_loaders.py tests/core/loaders tests/test_native_dtype_memory.py tests/test_demo_mf4.py tests/test_session.py -q
uv run pytest tests/gui -q
uv run pytest -q
```

確認ポイント: 反転の判定 2 軸（`test_signal_count_is_physical_channels_not_columns` = オブジェクト数、`test_array_channel_emits_one_warning_not_one_per_column` + `test_one_dimensional_diagnostics_stay_byte_identical` = 診断）が両方 GREEN であること。demo_data がローカルにあるなら `uv run pytest tests/core/loaders/test_mdf_loader_lazy.py -q` も走らせる（CI では skip されるため、ここでしか確認できない）。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

1. **数値ゲートを親 dtype へ戻す**: `if leaf_count(spec) == 0:` を `if samples.dtype.kind not in "iufb":` に置換 →
   `test_structured_channel_survives_leaf_level_numeric_gate` が RED（`Pt` が消え `_orig_names == []`）、
   `test_expansion_info_counts_all_leaves_not_only_numeric_ones` も RED（`Q` 消滅）。S2 の実証。
2. **info 件数を数値リーフのみへ**: `_expansion_diagnostic(..., all_leaves, ...)` を `leaf_count(spec)` に置換 →
   `test_expansion_info_counts_all_leaves_not_only_numeric_ones` が RED（`信号 'Q': 構造化チャンネルを 1 本に展開`）。`_all_leaf_count` を残す理由の実証。
3. **診断集約を戻す**: 非単調 warning を `for col_name in leaf_names(signal_name, spec):` のループ内で `signal_name=col_name` として emit →
   `test_array_channel_emits_one_warning_not_one_per_column` が RED（`Mat` 宛 0 件・`Mat[0..2]` 宛 3 件）。1-D 側（`test_one_dimensional_diagnostics_stay_byte_identical`）は GREEN のまま＝集約が 1-D の文言を巻き込んでいないことも同時に示す。
4. **表を Signal より先に埋める**: `column_records[signal_name] = ...` をゲート（`leaf_count(spec) == 0` の `continue`）より前へ移動 →
   `test_column_records_are_one_to_one_with_emitted_signals` が RED（all-bad ファイルで `{'raw_bytes': ...} != {}`）。
5. **Task 0 オラクルの sabotage（controller 指定・ここで初めて鋳造経路を通る）**:
   (a) `column_names.py:144` の `_consume(rest[end + 1 :], spec.child)` を `_consume(rest[end:], spec.child)` に（1 文字の非対称）→ `uv run pytest tests/core/loaders/test_column_roundtrip.py -q` が RED。
   (b) 物理チャンネル名が `Mat[0]` のファイル（Task 0 の衝突 fixture）で `Mat[0]` を引くケースが、最長一致を先頭一致へ落とす（`parse_leaf` の `range(len(display_key), 0, -1)` を `range(1, len(display_key) + 1)`）と RED。
   いずれも sabotage を戻して GREEN に復帰することを確認する。

各 sabotage の RED 出力（テスト名 + assertion 行）を実行報告に記す。

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

```bash
git add src/valisync/core/loaders/mdf_loader.py \
        tests/core/loaders/test_loader_inversion.py tests/gui/_physical_fixtures.py \
        tests/mdf4_helpers.py tests/test_loaders.py \
        tests/core/loaders/test_physical_channel_metadata.py \
        tests/core/loaders/test_mdf_loader_lazy.py \
        tests/test_native_dtype_memory.py tests/test_demo_mf4.py \
        tests/gui/test_channel_browser_physical.py tests/gui/test_channel_browser_vm.py \
        tests/gui/test_channel_browser_view.py tests/gui/test_signal_tree_model.py \
        tests/realgui/test_channel_tree_flatten_realclick.py
git commit -m "feat(core)!: ローダーを物理チャンネル 1 本 = Signal 1 個へ反転 (列は要求時に鋳造・診断は 1 件へ集約)"
```

---

### Task 7: 消費者の回復＋2-D 親の core 拒否

**Files:**
- Modify: `src/valisync/gui/reference_overlay.py:25-38`（`OverlayResult` に `container` 追加）, `:41-130`（列レベル解決へ）, `:147-169`（要約に節を追加）
- Modify: `src/valisync/gui/strings.py:183`（`OVERLAY_CLAUSE_AMBIGUOUS_TMPL` の直後に節テンプレート追加）
- Modify: `src/valisync/gui/viewmodels/signal_preview_vm.py:32-74`（線形走査 → 解決器・E-0 母数の縮約）
- Modify: `src/valisync/core/session.py:14-20`（import）, `:261-285`（`source_info.n_channels`）, `:371-378`（`export_csv` のガード＋新メソッド）
- Modify: `src/valisync/core/export/csv_exporter.py:12-15`（文言定数）, `:84-96`（`export` の入口ガード）
- Modify: `src/valisync/gui/views/main_window.py:49-56`（import）, `:740-750`（診断アクティベート fallback）
- Create: `tests/core/test_export_container_guard.py`
- Test: `tests/gui/test_reference_overlay.py`（追記）, `tests/gui/test_main_window_reference_overlay.py`（追記）, `tests/gui/test_signal_preview_vm.py`（**全面書き換え**）, `tests/gui/test_signal_preview_window.py`（fixture 書き換え）, `tests/test_session.py`（追記）, `tests/gui/test_main_window.py`（追記）

> **文言の置き場所についての意図的逸脱（記録）**: 2-D 親の拒否文言は `gui/strings.py` ではなく
> `core/export/csv_exporter.py` に置く。拒否点が core（C-d）である以上、`core → gui` の import は
> 層違反であり、`csv_exporter.py` 自身が「本モジュールは core であり gui.display_names を
> import しない」と明記している（`csv_exporter.py:29-31`）。core 側に日本語文言を持つのは
> 既存の共有タイムライン `ValueError`（`csv_exporter.py:144-147`）と core 診断 27 訳の先例に従う。
> GUI 側は `MainWindow._on_export_error`（`main_window.py:963-968`）が例外文をそのまま
> モーダルへ出すため、ユーザーに届く文言は 1 箇所で決まる。

**Interfaces:**
- Consumes（T1）: `Session.column_names_of(key: str, display_name: str) -> tuple[str, ...]` —
  物理チャンネル名なら数値リーフ表示名タプル、**スカラー・列キー・未知名は `(display_name,)`**
  （＝「1 列しか無い」と同義。T7 はこの同一性で親を判定する）／
  `Session.total_column_count(key: str) -> int` — グループの数値列総数（ColumnRecord を持たない
  CSV/Derived グループは `len(group.signals)`）／
  `Session.has_column(key: str, display_name: str) -> bool` — その名前の**列**が実在するか
  （**鋳造しない**＝副テーブルに何も残さない。`display_name` の衝突判定はこれで行う）。
- Consumes（E-1 既存）: `Session.resolve_signal(key: str) -> Signal | None`（列キーは要求時鋳造・
  未ロードグループは None）／`SignalGroupManager.mint_count`（テストの非鋳造オラクル・C-e により
  Session には公開しない）。
- Consumes（T6）: 反転後 `Session.group_signals(key)` は**物理チャンネルのみ**を返し、配列/構造体
  チャンネルは 2-D/構造化サンプルを持つ「親」Signal 1 個として現れる。
- Produces:
  - `Session.is_container_channel(key: str, display_name: str) -> bool` — 列へ展開される親か
    （**値を読まない**唯一の判定点。T8/T9 もここを使う）。
  - `OverlayResult.container: int`（既定 0）＋ `strings.OVERLAY_CLAUSE_CONTAINER_TMPL`。
  - `csv_exporter.EXPORT_CONTAINER_CHANNEL_ERROR_TMPL` / `EXPORT_MULTI_COLUMN_VALUES_ERROR_TMPL`。

- [ ] **Step 1: 失敗テストを書く**

**(1-a) `tests/gui/test_reference_overlay.py` — 末尾に追記（import 行も更新）**

冒頭の import ブロックへ次を追加する:

```python
from tests.mdf4_helpers import write_mdf4, write_mdf4_2d
```

ファイル末尾へ追記:

```python
# ─── E-3: 列レベルのマッチ (spec C-c) ───────────────────────────────────────


def _mat2d_in(tmp_path: Path, sub: str) -> Path:
    """write_mdf4_2d は固定名 mat2d.mf4 を書くので 2 本目は別ディレクトリへ置く。"""
    directory = tmp_path / sub
    directory.mkdir()
    return write_mdf4_2d(directory)


def test_overlay_matches_expanded_column_across_files(tmp_path: Path) -> None:
    """反転後 group_signals は物理チャンネルしか返さない。列レベルで引かないと
    Mat[0] が全て no_match になり「0 件重ねました（同名なし 1）」という
    **正常に見える嘘**が出る (真の不一致と区別できない)。"""
    session = Session()
    ref_key = session.load(_mat2d_in(tmp_path, "ref")).key
    tgt_key = session.load(_mat2d_in(tmp_path, "tgt")).key
    ref_col = f"{ref_key}::Mat[0]"

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_col, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.added == 1
    assert result.no_match == 0
    assert {(sk, ax) for _eid, sk, ax in panel.plotted_entries()} == {
        (ref_col, 0),
        (f"{tgt_key}::Mat[0]", 0),
    }


def test_overlay_column_key_collision_prefers_real_channel(tmp_path: Path) -> None:
    """`Mat[0]` 衝突の pin: 参照側の配列列 `Mat[0]` は、対象ファイルに実在する
    1-D チャンネル `Mat[0]` と単位一致で偶然ペアリングされる。どちらが選ばれるかは
    parse_leaf の最長一致規則 (実チャンネルが展開列に優先) で決まる — 規則を変えると
    重ねる相手が黙って別物になるので、値まで含めて固定する。"""
    session = Session()
    ref_key = session.load(_mat2d_in(tmp_path, "ref")).key
    tgt_path = write_mdf4(
        tmp_path / "tgt.mf4",
        [
            {
                "name": "Mat[0]",
                "timestamps": [0.0, 0.1, 0.2, 0.3],
                "values": [7.0, 8.0, 9.0, 10.0],
            }
        ],
    )
    tgt_key = session.load(tgt_path).key
    ref_col = f"{ref_key}::Mat[0]"

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(ref_col, 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    added_key = f"{tgt_key}::Mat[0]"
    assert result.added == 1
    assert (added_key, 0) in {(sk, ax) for _eid, sk, ax in panel.plotted_entries()}
    # 実チャンネル (物理) が勝つ — 鋳造された展開列ではない
    assert added_key in {s.name for s in session.group_signals(tgt_key)}
    got = session.resolve_signal(added_key)
    assert got is not None
    assert got.sorted_view()[1].tolist() == [7.0, 8.0, 9.0, 10.0]


def test_overlay_skips_container_channel_candidate(tmp_path: Path) -> None:
    """参照が 1-D スカラー `Mat`、対象が 2-D 配列チャンネル `Mat` のとき、候補は列
    ではなく **配列の親**。載せると sorted_view() が float64 へ 8 倍膨張した 2-D 配列を
    恒久キャッシュし (prod で 96 MB/本)、そもそも描画できない。"""
    session = Session()
    ref_path = write_mdf4(
        tmp_path / "ref.mf4",
        [
            {
                "name": "Mat",
                "timestamps": [0.0, 0.1, 0.2, 0.3],
                "values": [1.0, 2.0, 3.0, 4.0],
            }
        ],
    )
    ref_key = session.load(ref_path).key
    tgt_key = session.load(_mat2d_in(tmp_path, "tgt")).key

    panel = GraphPanelVM(session)
    panel.add_signal_to_axis(f"{ref_key}::Mat", 0)

    result = overlay_reference_signals(panel, session, ref_key, tgt_key)

    assert result.container == 1
    assert result.added == 0
    assert len(panel.plotted_entries()) == 1  # 親は載らない
    # 拒否は **値を読まずに** 決める (チャンネル全読みは遅延展開の利得を捨てる)
    parent = session.resolve_signal(f"{tgt_key}::Mat")
    assert parent is not None
    assert parent._values_source.is_materialized is False


def test_format_summary_container_clause() -> None:
    result = OverlayResult(
        total=1,
        added=0,
        no_match=0,
        unit_mismatch=0,
        already_present=0,
        ambiguous=0,
        container=1,
    )
    msg = format_overlay_summary(result, "b.mf4")
    assert msg == "b.mf4 の同名信号を 0 件重ねました（構造不一致 1）"
```

**(1-b) `tests/gui/test_main_window_reference_overlay.py` — 追記（import 更新）**

`from tests.mdf4_helpers import CAN, write_mdf4` を
`from tests.mdf4_helpers import CAN, write_mdf4, write_mdf4_2d` に変え、末尾へ追記:

```python
def _mat2d_in(tmp_path: Path, sub: str) -> Path:
    directory = tmp_path / sub
    directory.mkdir()
    return write_mdf4_2d(directory)


def test_overlay_request_matches_expanded_columns(qtbot: QtBot, tmp_path: Path) -> None:
    """実配線 (FileBrowserView.overlay_reference_requested -> MainWindow) の上で、
    展開列が重なることを確認する (Layer A は Session 直叩き)。"""
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)

    key1 = mw.app_vm.request_load(_mat2d_in(tmp_path, "a"))
    key2 = mw.app_vm.request_load(_mat2d_in(tmp_path, "b"))

    vm = mw.graph_area_vm
    panel = vm.panels(vm.active_tab_index)[vm.active_panel_index()]
    panel.add_signal(f"{key1}::Mat[0]")

    mw.file_browser_view.overlay_reference_requested.emit(key2)

    entries = {(sk, ax) for _eid, sk, ax in panel.plotted_entries()}
    assert (f"{key2}::Mat[0]", 0) in entries
    assert "1 件重ねました" in mw.status_message()
```

**(1-c) `tests/gui/test_signal_preview_vm.py` — 全面書き換え（新しい内容）**

```python
"""Tests for SignalPreviewVM (FU-13): preview properties + downsampled waveform.

E-3 で信号解決が「アクティブファイルの線形走査」から Session の解決器へ移ったため、
fixture は ``group_signals`` の monkeypatch ではなく **実際に SignalGroup を登録する**
(monkeypatch では解決器に到達せず、全テストが空の VM を見ることになる)。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from pytestqt.qtbot import QtBot

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.models import Signal, SignalGroup
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM

_BASE_DIR = Path(__file__).resolve().parent


def _sig(
    name: str,
    ts: np.ndarray,
    vs: np.ndarray,
    metadata: dict[str, object] | None = None,
) -> Signal:
    return Signal(
        name=name,
        timestamps=ts,
        values=vs,
        file_format="MDF4",
        bus_type="CAN",
        source_file="",
        metadata=(
            {"unit": "km/h", "comment": "veh speed"} if metadata is None else metadata
        ),
    )


def _register(app_vm: AppViewModel, file_name: str, *signals: Signal) -> str:
    """1 ファイル分の SignalGroup を登録して group key を返す (信号名は bare)。"""
    key = app_vm.session._groups.add(
        SignalGroup(
            signals=tuple(signals),
            source_path=_BASE_DIR / file_name,
            file_format="MDF4",
            loaded_at=datetime.now(),
        )
    )
    app_vm.register_loaded(key)  # E-0: display_name scope = loaded_file_keys
    return key


def _vm(qtbot: QtBot) -> tuple[SignalPreviewVM, str]:
    app_vm = AppViewModel()
    ts = np.arange(0.0, 100.0, 1.0)
    key = _register(app_vm, "a.mf4", _sig("Speed", ts, np.sin(ts)))
    app_vm.set_active_file(key)
    return SignalPreviewVM(app_vm), key


def test_properties_include_name_unit_samples_timerange_minmax(qtbot: QtBot) -> None:
    vm, key = _vm(qtbot)
    vm.set_signal(f"{key}::Speed")
    props = dict(vm.properties())
    # E-0 (UX-19): "名前" は bare 表示名 — 生の名前空間つきキーではない
    assert props["名前"] == "Speed"
    assert props["単位"] == "km/h"
    assert props["サンプル数"] == "100"
    assert "時間範囲" in props and "s" in props["時間範囲"]
    assert "最小値" in props and "最大値" in props
    assert props["コメント"] == "veh speed"


def test_properties_empty_for_unknown_or_none(qtbot: QtBot) -> None:
    vm, key = _vm(qtbot)
    assert vm.properties() == []  # no signal set
    vm.set_signal(f"{key}::Missing")
    assert vm.properties() == []


# ─── display_name (E-0, spec §1.2) ────────────────────────────────────────


def test_display_name_bare_when_no_collision(qtbot: QtBot) -> None:
    vm, key = _vm(qtbot)
    assert vm.display_name(f"{key}::Speed") == "Speed"


def test_display_name_qualified_when_two_loaded_files_share_bare_name(
    qtbot: QtBot,
) -> None:
    """Scope = ALL loaded signals, not just the active file's (spec §1.2)."""
    app_vm = AppViewModel()
    ts = np.arange(0.0, 10.0, 1.0)
    k1 = _register(app_vm, "a.mf4", _sig("Speed", ts, np.sin(ts)))
    k2 = _register(app_vm, "b.mf4", _sig("Speed", ts, np.sin(ts)))
    app_vm.set_active_file(k1)
    vm = SignalPreviewVM(app_vm)
    assert vm.display_name(f"{k1}::Speed") == f"Speed ({k1})"
    assert vm.display_name(f"{k2}::Speed") == f"Speed ({k2})"


def test_display_name_unresolvable_key_falls_back_to_bare_name(
    qtbot: QtBot,
) -> None:
    """読み込み済み信号に無いキー (stale/unknown) でも落ちない — 何とも衝突しない。"""
    vm, key = _vm(qtbot)
    assert vm.display_name(f"{key}::TotallyUnknown") == "TotallyUnknown"


def test_plot_data_downsampled_within_range(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    ts = np.arange(0.0, 10000.0, 1.0)  # 10k points
    key = _register(app_vm, "big.mf4", _sig("Big", ts, np.cos(ts)))
    app_vm.set_active_file(key)
    vm = SignalPreviewVM(app_vm)
    vm.set_signal(f"{key}::Big")
    data = vm.plot_data()
    assert data is not None
    x, y = data
    assert 0 < len(x) <= 480  # downsampled to <= _PREVIEW_POINTS
    assert len(x) == len(y)
    assert x[0] >= 0.0 and x[-1] <= 9999.0  # within original range


def test_plot_data_none_for_unknown(qtbot: QtBot) -> None:
    vm, key = _vm(qtbot)
    vm.set_signal(f"{key}::Missing")
    assert vm.plot_data() is None


# ─── axis_label_parts (UX-43, spec §3) ────────────────────────────────────


def test_axis_label_parts_returns_display_name_and_unit(qtbot: QtBot) -> None:
    vm, key = _vm(qtbot)
    vm.set_signal(f"{key}::Speed")
    assert vm.axis_label_parts() == ("Speed", "km/h")


def test_axis_label_parts_unit_none_when_missing(qtbot: QtBot) -> None:
    app_vm = AppViewModel()
    ts = np.arange(0.0, 10.0, 1.0)
    key = _register(app_vm, "nounit.mf4", _sig("NoUnit", ts, np.sin(ts), metadata={}))
    app_vm.set_active_file(key)
    vm = SignalPreviewVM(app_vm)
    vm.set_signal(f"{key}::NoUnit")
    assert vm.axis_label_parts() == ("NoUnit", None)


def test_axis_label_parts_empty_when_no_signal_set(qtbot: QtBot) -> None:
    vm, _key = _vm(qtbot)
    assert vm.axis_label_parts() == ("", None)


def test_axis_label_parts_qualified_name_on_collision(qtbot: QtBot) -> None:
    """Scope = ALL loaded signals (same rule as display_name, spec §1.2)."""
    app_vm = AppViewModel()
    ts = np.arange(0.0, 10.0, 1.0)
    k1 = _register(app_vm, "a.mf4", _sig("Speed", ts, np.sin(ts)))
    _register(app_vm, "b.mf4", _sig("Speed", ts, np.sin(ts)))
    app_vm.set_active_file(k1)
    vm = SignalPreviewVM(app_vm)
    vm.set_signal(f"{k1}::Speed")
    name, unit = vm.axis_label_parts()
    assert name == f"Speed ({k1})"
    assert "::" not in name
    assert unit == "km/h"


def test_time_range_does_not_materialize_sorted_view_cache(qtbot: QtBot) -> None:
    """properties() は Signal.time_range() (生 min/max) で時間範囲を読むこと。
    sorted_view()[0][0]/[-1] だと FU-20 の float64 キャッシュを膨らませる
    (memory signal_range_via_sorted_view_materializes_float64_cache)。"""
    app_vm = AppViewModel()
    ts = np.arange(0.0, 50.0, 1.0)
    sig = _sig("S", ts, np.sin(ts))
    key = _register(app_vm, "s.mf4", sig)
    app_vm.set_active_file(key)
    vm = SignalPreviewVM(app_vm)
    vm.set_signal(f"{key}::S")
    # namespaced ラッパーは sorted_view を元 Signal へ委譲するので、元を見れば足りる。
    _ = vm.properties()
    assert getattr(sig, "_sorted_view_cache", None) is None


# ─── E-3: 列キー / 親チャンネル ─────────────────────────────────────────────


def test_column_key_resolves_to_expanded_column(qtbot: QtBot, tmp_path: Path) -> None:
    """反転後 group_signals は物理チャンネルしか返さない。線形走査のままだと列キーが
    解決できず、プレビュー窓が「この信号はプレビューできません」で真っ白になる —
    設計された空状態と見分けがつかないサイレント破壊。"""
    app_vm = AppViewModel()
    key = app_vm.request_load(write_mdf4_2d(tmp_path))
    app_vm.set_active_file(key)
    vm = SignalPreviewVM(app_vm)

    vm.set_signal(f"{key}::Mat[0]")

    props = dict(vm.properties())
    assert props["名前"] == "Mat[0]"
    assert props["サンプル数"] == "4"
    assert vm.plot_data() is not None
    assert vm.axis_label_parts()[0] == "Mat[0]"


def test_column_display_name_qualified_when_two_files_share_column(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """E-0 の母数から他ファイルの列が消えると Mat[0] の修飾が静かに落ちる
    (2 ファイルとも同名の列を持つのに「Mat[0]」と表示され出所が分からなくなる)。"""
    app_vm = AppViewModel()
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    k1 = app_vm.request_load(write_mdf4_2d(d1))
    k2 = app_vm.request_load(write_mdf4_2d(d2))
    app_vm.set_active_file(k1)
    vm = SignalPreviewVM(app_vm)

    assert vm.display_name(f"{k1}::Mat[0]") == f"Mat[0] ({k1})"
    assert vm.display_name(f"{k2}::Mat[0]") == f"Mat[0] ({k2})"


def test_display_name_does_not_mint_any_column(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """表示名の衝突判定は **1 本も鋳造しない** (列構造だけで決まる)。

    「全ファイルの全列を舐めない」だけでは足りない: 鋳造した列は _resolved_by_key へ
    恒久的に入る (C-g で LRU なし) ので、他ファイル 1 本ずつでも「プレビューを開いた
    ぶんだけ列 Signal が滞留する」経路が残る。上限 (<= 1) ではなく **0** を要求する。
    """
    app_vm = AppViewModel()
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    k1 = app_vm.request_load(write_mdf4_2d(d1))
    k2 = app_vm.request_load(write_mdf4_2d(d2))
    vm = SignalPreviewVM(app_vm)
    before = app_vm.session._groups.mint_count

    # 反 vacuous 前置: この呼び出しは実際に衝突を検出している (母数が縮んで
    # いるだけなら "Mat[0]" が返り、鋳造 0 は自明に通る)。
    assert vm.display_name(f"{k1}::Mat[0]") == f"Mat[0] ({k1})"

    assert app_vm.session._groups.mint_count == before
    assert app_vm.session._groups.resolved_keys(k2) == frozenset()


def test_container_channel_is_not_previewable(qtbot: QtBot, tmp_path: Path) -> None:
    """配列チャンネルの親 (`Mat`) は 1 本の波形を持たない。プレビューしようとすると
    値を全読み (prod で 96 MB/本) したうえで Downsampler が 2-D 配列に出くわす —
    名前 (列構造) だけで弾く。"""
    app_vm = AppViewModel()
    key = app_vm.request_load(write_mdf4_2d(tmp_path))
    app_vm.set_active_file(key)
    vm = SignalPreviewVM(app_vm)

    vm.set_signal(f"{key}::Mat")

    assert vm.properties() == []
    assert vm.plot_data() is None
    parent = app_vm.session.resolve_signal(f"{key}::Mat")
    assert parent is not None
    assert parent._values_source.is_materialized is False
```

**(1-d) `tests/gui/test_signal_preview_window.py` — fixture 書き換え（新しい内容）**

```python
"""Tests for SignalPreviewWindow (FU-13): 2-tab preview + properties window."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from pytestqt.qtbot import QtBot

from valisync.core.models import Signal, SignalGroup
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.signal_preview_vm import SignalPreviewVM
from valisync.gui.views.signal_preview_window import SignalPreviewWindow

_BASE_DIR = Path(__file__).resolve().parent


def _sig(name: str) -> Signal:
    ts = np.arange(0.0, 200.0, 1.0)
    return Signal(
        name=name,
        timestamps=ts,
        values=np.sin(ts),
        file_format="MDF4",
        bus_type="CAN",
        source_file="",
        metadata={"unit": "V"},
    )


def _window(qtbot: QtBot) -> tuple[SignalPreviewWindow, str]:
    """E-3: プレビューは解決器経由になったので、実際に SignalGroup を登録する
    (group_signals の monkeypatch では信号に到達できない)。"""
    app_vm = AppViewModel()
    key = app_vm.session._groups.add(
        SignalGroup(
            signals=(_sig("A"), _sig("B")),
            source_path=_BASE_DIR / "w.mf4",
            file_format="MDF4",
            loaded_at=datetime.now(),
        )
    )
    app_vm.set_active_file(key)
    app_vm.register_loaded(key)  # E-0: display_name scope = loaded_file_keys
    win = SignalPreviewWindow(SignalPreviewVM(app_vm))
    qtbot.addWidget(win)
    return win, key


def test_two_tabs_present_with_titles(qtbot: QtBot) -> None:
    win, _key = _window(qtbot)
    titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert titles == ["プレビュー", "信号プロパティ"]


def test_show_signal_populates_plot_and_properties(qtbot: QtBot) -> None:
    win, key = _window(qtbot)
    win.show_signal(f"{key}::A")
    # Preview tab: a curve is drawn.
    assert len(win.preview_plot.listDataItems()) == 1
    # Properties tab: rows populated (name row present).
    assert win.property_row_count() >= 1


def test_show_signal_replaces_content_single_instance(qtbot: QtBot) -> None:
    win, key = _window(qtbot)
    win.show_signal(f"{key}::A")
    win.show_signal(f"{key}::B")  # same window, content swapped
    assert len(win.preview_plot.listDataItems()) == 1  # not accumulated
    # E-0 (UX-19): windowTitle は bare 表示名 "B" (生キーではない)
    assert win.windowTitle().endswith("B")


def test_show_signal_unknown_shows_no_curve(qtbot: QtBot) -> None:
    win, key = _window(qtbot)
    win.show_signal(f"{key}::Missing")
    assert len(win.preview_plot.listDataItems()) == 0
    assert win.property_row_count() == 0


# ─── axis labels (UX-43, spec §3) ──────────────────────────────────────────


def test_preview_axis_labels_bottom_time_left_display_name_unit(qtbot: QtBot) -> None:
    win, key = _window(qtbot)
    win.show_signal(f"{key}::A")
    bottom = win.preview_plot.getAxis("bottom")
    left = win.preview_plot.getAxis("left")
    assert bottom.labelText == "Time"
    assert bottom.labelUnits == "s"
    # E-0: display name only -- 生の名前空間つきキーが軸ラベルへ漏れてはならない
    assert left.labelText == "A"
    assert "::" not in left.labelText
    assert left.labelUnits == "V"  # from _sig()'s metadata unit


def test_preview_axis_label_swaps_with_shown_signal(qtbot: QtBot) -> None:
    win, key = _window(qtbot)
    win.show_signal(f"{key}::A")
    win.show_signal(f"{key}::B")  # same window instance -- label must not be stale
    left = win.preview_plot.getAxis("left")
    assert left.labelText == "B"
```

**(1-e) `tests/test_session.py` — 追記（import 更新）**

`import pytest` の下に `from tests.mdf4_helpers import write_mdf4_2d` を追加し、
`test_source_info_ignores_empty_signals_but_counts_them` の直後に追記:

```python
def test_source_info_n_channels_counts_expanded_columns(tmp_path):
    """U2: 表示件数の単位は **列数**。反転後 group.signals は物理チャンネルのみ
    なので len(group.signals) では Mat の 3 列が 1 と数えられ、ChannelBrowser の
    「N ch 中 M ch を表示」と単位が食い違う (FileBrowser ツールチップも同様)。"""
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    info = session.source_info(key)
    assert info.n_channels == 4  # Mat[0..2] + Clean
```

**(1-f) `tests/gui/test_main_window.py` — 追記（import 更新）**

import ブロックへ `from tests.mdf4_helpers import write_mdf4_2d` を追加し、
`TestDiagnosticActivatedJump` クラスへメソッドを追加:

```python
    def test_jumps_by_expanded_column_name(self, qtbot, tmp_path):
        """診断が載せる signal_name は素の列名 ("Mat[0]")。反転後 group_signals は
        物理チャンネルしか返さないので、名前の線形比較では二度と一致せず、行を
        ダブルクリックしても無反応になる (無音の機能喪失)。"""
        window = _make_window(qtbot)
        key_csv = window.app_vm.request_load(_write_csv(tmp_path), _csv_format())
        key_mf4 = window.app_vm.request_load(write_mdf4_2d(tmp_path))
        window.app_vm.set_active_file(key_csv)

        window._on_diagnostic_activated("Mat[0]")

        assert window.app_vm.active_file_key == key_mf4
```

**(1-g) `tests/core/test_export_container_guard.py` — 新規**

```python
"""2-D 親 (配列/構造体チャンネル本体) を CSV に書き出させない core の拒否 (E-3 C-d)。

拒否点を core に置くのは、GUI ダイアログを通らない直呼び (scripted / realgui の
``session.export_csv``) まで守れる唯一の層だから。素の numpy TypeError
("float() argument must be a string or a real number, not 'list'") は
ExportWorker -> QMessageBox にそのまま出て、ユーザーには何を選び直せばよいか
分からない。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.export import CsvExporter
from valisync.core.models import Signal
from valisync.core.session import Session


def _2d_signal(name: str = "Mat") -> Signal:
    ts = np.arange(4.0, dtype=np.float64)
    return Signal(
        name=name,
        timestamps=ts,
        values=np.arange(12, dtype=np.uint8).reshape(4, 3),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={},
    )


def _scalar_signal(name: str = "Plain") -> Signal:
    ts = np.arange(3.0, dtype=np.float64)
    return Signal(
        name=name,
        timestamps=ts,
        values=np.array([1.0, 2.0, 3.0]),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata={},
    )


def test_exporter_rejects_multi_column_values_shared_timeline(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="配列チャンネル"):
        CsvExporter().export([_2d_signal()], tmp_path / "out.csv")


def test_exporter_rejects_multi_column_values_unified_timeline(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="配列チャンネル"):
        CsvExporter().export(
            [_2d_signal()], tmp_path / "out.csv", use_unified_timeline=True
        )


def test_exporter_writes_nothing_when_rejected(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    with pytest.raises(ValueError):
        CsvExporter().export([_2d_signal(), _scalar_signal()], out)
    assert not out.exists()


def test_session_rejects_container_channel_without_reading_values(
    tmp_path: Path,
) -> None:
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    parent = next(s for s in session.group_signals(key) if s.name == f"{key}::Mat")

    with pytest.raises(ValueError, match=r"Mat\[0\]"):
        session.export_csv([parent], tmp_path / "out.csv")

    # 判定に sig.values.ndim を使うとここが materialized になる
    # (prod では 1 本 96 MB のチャンネル全読み = 遅延展開の利得を捨てる)。
    assert parent._values_source.is_materialized is False


def test_session_exports_expanded_column(tmp_path: Path) -> None:
    """過剰拒否の pin: 列そのものは今までどおり書き出せる。"""
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    col = session.resolve_signal(f"{key}::Mat[0]")
    assert col is not None

    out = tmp_path / "col.csv"
    session.export_csv([col], out)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == f"timestamp,{key}::Mat[0]"
    assert len(lines) == 5  # ヘッダ + 4 行


def test_session_export_allows_signal_without_loaded_group(tmp_path: Path) -> None:
    """名前空間なし (Derived) は所属グループを引けない = 列構造を知りようがない。
    判定不能を拒否に倒すと Derived_Signal のエクスポートが全滅する。"""
    session = Session()
    out = tmp_path / "derived.csv"
    session.export_csv([_scalar_signal()], out)
    assert out.read_text(encoding="utf-8").splitlines()[0] == "timestamp,Plain"
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_reference_overlay.py tests/gui/test_signal_preview_vm.py tests/gui/test_signal_preview_window.py tests/core/test_export_container_guard.py tests/test_session.py::test_source_info_n_channels_counts_expanded_columns "tests/gui/test_main_window.py::TestDiagnosticActivatedJump" tests/gui/test_main_window_reference_overlay.py -q`

Expected: FAIL（代表例）
- `test_format_summary_container_clause` → `TypeError: OverlayResult.__init__() got an unexpected keyword argument 'container'`
- `test_overlay_matches_expanded_column_across_files` → `assert 0 == 1`（`result.added`。実際は `no_match == 1`）
- `test_overlay_skips_container_channel_candidate` → `AttributeError: 'OverlayResult' object has no attribute 'container'`
- `test_column_key_resolves_to_expanded_column` → `KeyError: '名前'`（`properties()` が `[]`）
- `test_container_channel_is_not_previewable` → `assert [('名前', 'Mat'), ...] == []`
- `test_display_name_does_not_mint_any_column` → 旧 `_all_loaded_signal_keys` 経路は反転後の `group_signals` に `Mat[0]` が居ないため衝突を検出できず、反 vacuous 前置の `assert 'Mat[0]' == 'Mat[0] (mf4_1)'` で RED（同じ理由で `test_column_display_name_qualified_when_two_files_share_column` も RED）
- `test_source_info_n_channels_counts_expanded_columns` → `assert 2 == 4`
- `test_jumps_by_expanded_column_name` → `assert 'csv_1' == 'mf4_1'`
- `tests/core/test_export_container_guard.py` の拒否 3 件 → `TypeError: only length-1 arrays can be converted to Python scalars`（unified は `TypeError: float() argument must be a string or a real number, not 'list'`）が `pytest.raises(ValueError)` を素通りしてエラー

- [ ] **Step 3: 実装**

**(3-a) `src/valisync/core/export/csv_exporter.py`**

`_TIMESTAMP_UNIT` の直後に追加:

```python
#: 配列チャンネルの親を書き出そうとしたときのエラー文言。core に置くのは、GUI
#: ダイアログを通らない直呼び (scripted / realgui の Session.export_csv) まで守れる
#: 唯一の層だから (E-3 C-d)。gui.strings へは置かない — 本モジュールは core であり
#: gui を import しない (header_names の注記と同じ理由)。
EXPORT_MULTI_COLUMN_VALUES_ERROR_TMPL = (
    "信号 '{name}' は 1 時刻につき複数の値を持つ配列チャンネルのため CSV に"
    "書き出せません。展開された列を選択してください。"
)
EXPORT_CONTAINER_CHANNEL_ERROR_TMPL = (
    "信号 '{name}' は配列/構造体チャンネル本体のため CSV に書き出せません。"
    "展開された列 (例: '{example}') を選択してください。"
)
```

`CsvExporter.export` を差し替え、直下にヘルパを追加:

```python
    def export(
        self,
        signals: list[Signal],
        output_path: Path,
        use_unified_timeline: bool = False,
        options: CsvExportOptions | None = None,
    ) -> None:
        opts = options if options is not None else CsvExportOptions()
        self._require_single_value_columns(signals)
        if use_unified_timeline:
            rows = self._rows_unified_timeline(signals, opts)
        else:
            rows = self._rows_shared_timeline(signals, opts)
        self._atomic_write(Path(output_path), rows)

    @staticmethod
    def _require_single_value_columns(signals: list[Signal]) -> None:
        """1 時刻 1 値でない Signal (配列チャンネルの親) を拒否する (E-3 C-d)。

        **値を読まずに**親を弾くのは ``Session.export_csv`` の役目 (ColumnRecord
        由来)。ここは CsvExporter を直接呼ぶ経路の最後の砦で、numpy の生 TypeError
        を意味の分かる日本語エラーへ変える。判定を ``sorted_view()`` の結果で行うのは、
        直後に同じ (キャッシュされた) ビューを読むため健全な経路には追加コストが
        無いから — 拒否される側だけが一度の読みを払う。
        """
        for sig in signals:
            if sig.sorted_view()[1].ndim != 1:
                raise ValueError(
                    EXPORT_MULTI_COLUMN_VALUES_ERROR_TMPL.format(name=sig.name)
                )
```

**(3-b) `src/valisync/core/session.py`**

import を差し替え:

```python
from valisync.core.export.csv_exporter import (
    EXPORT_CONTAINER_CHANNEL_ERROR_TMPL,
    CsvExporter,
    CsvExportOptions,
)
```

`source_info` の `n_channels` 行を差し替え:

```python
            # U2: 件数の単位は **列数** (264,004)。ChannelBrowser ヘッダの
            # 「N ch 中 M ch を表示」と揃える — 反転後 group.signals は物理
            # チャンネルのみなので len() では単位が食い違う。
            n_channels=self._groups.total_column_count(key),
```

`resolve_signal` の直後（`source_info` の前）へ 1 メソッド追加:

```python
    def is_container_channel(self, key: str, display_name: str) -> bool:
        """*display_name* が複数列 (または改名列) へ展開される「親」チャンネルか。

        判定は ColumnRecord の列構造から引く — ``sig.values.ndim`` を見ると
        チャンネル全読み (prod で 1 本 96 MB) を誘発し、遅延展開の利得をその場で
        捨てることになる。列キー・スカラー・未知名は ``(display_name,)`` が返るので
        いずれも False (E-3 C-d)。
        """
        return self.column_names_of(key, display_name) != (display_name,)
```

`export_csv` を差し替え、直下にガードを追加:

```python
    def export_csv(
        self,
        signals: list[Signal],
        output_path: Path,
        use_unified_timeline: bool = False,
        options: CsvExportOptions | None = None,
    ) -> None:
        self._reject_container_channels(signals)
        self._exporter.export(signals, output_path, use_unified_timeline, options)

    def _reject_container_channels(self, signals: list[Signal]) -> None:
        """配列/構造体チャンネルの親を、値を読む前に拒否する (E-3 C-d)。

        GUI のダイアログは親行をチェック不可にしている (C-a) が、scripted /
        realgui は ``session.export_csv`` を直呼びするため、ここが実効的な唯一の
        防波堤になる。所属グループが引けない Signal (Derived・アンロード済み) は
        列構造を知りようがないので通す — 判定不能を拒否に倒すと Derived_Signal の
        エクスポートが全滅する (最後の砦は CsvExporter 側の 1 時刻 1 値検査)。
        """
        loaded = set(self.group_keys())
        for sig in signals:
            group_key, sep, bare = sig.name.partition(KEY_SEPARATOR)
            if not sep or group_key not in loaded:
                continue
            columns = self.column_names_of(group_key, bare)
            if columns == (bare,):
                continue
            raise ValueError(
                EXPORT_CONTAINER_CHANNEL_ERROR_TMPL.format(
                    name=bare, example=columns[0] if columns else bare
                )
            )
```

**(3-c) `src/valisync/gui/strings.py`**

`OVERLAY_CLAUSE_AMBIGUOUS_TMPL` の直後に追加:

```python
# E-3: 対象ファイル側の候補が配列/構造体チャンネル**本体**だった件数
# (スカラー vs 配列の構造ミスマッチ — 単位不一致と同じ粒度の語彙に揃える)。
OVERLAY_CLAUSE_CONTAINER_TMPL: Final = "構造不一致 {n}"
```

**(3-d) `src/valisync/gui/reference_overlay.py`**

import ブロックへ追加:

```python
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
```

`OverlayResult` を差し替え:

```python
@dataclass(frozen=True)
class OverlayResult:
    """Outcome counts, partitioning the reference-file entries scanned.

    ``total`` is the denominator (spec §3: 母数=基準エントリ) and always
    equals ``added + no_match + unit_mismatch + already_present + ambiguous
    + container``.

    ``container`` は既定 0 — E-2b 期に書かれた 6 分類の等値 assert をそのまま
    生かすため (それらのケースでは実測値も 0 になる)。
    """

    total: int
    added: int
    no_match: int
    unit_mismatch: int
    already_present: int
    ambiguous: int
    container: int = 0
```

`overlay_reference_signals` を全置換:

```python
def overlay_reference_signals(
    panel: GraphPanelVM,
    session: Session,
    reference_key: str,
    target_key: str,
) -> OverlayResult:
    """Overlay *target_key*'s same-named signals onto *panel*'s reference entries.

    5 steps (spec §3, verbatim):

    1. Scan ``panel.plotted_entries()`` for entries whose group is
       *reference_key* (母数=基準エントリ — snapshotted upfront so the scan is
       unaffected by entries this same call adds).
    2. For each, resolve the bare name **as a column key** inside *target_key*
       (E-3 C-c — マッチ粒度は列レベル)。``session.resolve_signal`` が既存の
       最長一致を再利用し、一致した 1 本だけを鋳造する。物理チャンネル単位で
       突き合わせてはならない: ``already_present`` 判定は plotted entries の
       **列キー**で作られているため、再実行で重複追加になる。
    3. A match is added to the SAME axis via ``panel.add_signal_to_axis``.
    4. Skips (all counted, nothing raises):
       - no bare-name match → ``no_match``
       - 候補が配列/構造体チャンネル**本体** → ``container``（spec E-3
         「2-D 親を重ね対象から除外」。載せると sorted_view() が float64 へ
         8 倍膨張した 2-D 配列を恒久キャッシュし、そもそも描画できない）
       - unit mismatch (``sig.metadata`` exact string compare, missing
         treated as ``""`` — so both-empty passes, one-empty-one-not fails)
         → ``unit_mismatch``
       - an entry already at that exact ``(key, axis)`` pair → ``already_present``
       - the reference entry's OR the candidate's name involved a LD-08
         dedup suffix (``metadata["name_deduplicated"]``) → ``ambiguous``.
         The ``[idx]`` disambiguation is assigned independently per file, so
         the same literal suffix in two files is not safely comparable —
         checked on BOTH sides (matching this literal string can happen
         with the reference's own name un-flagged, purely by coincidence,
         while the target's candidate IS flagged) since a silent bad pairing
         would be undetectable by any later gate (spec §3 step 5 — 安全側)。
    """
    reference_entries = [
        (signal_key, axis_index)
        for _entry_id, signal_key, axis_index in panel.plotted_entries()
        if split_key(signal_key)[0] == reference_key
    ]
    total = len(reference_entries)

    signal_map = session.signal_map()
    existing_pairs = {
        (signal_key, axis_index)
        for _eid, signal_key, axis_index in panel.plotted_entries()
    }

    added = no_match = unit_mismatch = already_present = ambiguous = container = 0
    for signal_key, axis_index in reference_entries:
        _, bare = split_key(signal_key)
        ref_sig = signal_map.get(signal_key)
        if ref_sig is not None and ref_sig.metadata.get("name_deduplicated"):
            ambiguous += 1
            continue

        # 追加は解決した Signal の .name ではなく、この構成キーで行う — 鋳造列の
        # 命名規約に依存せず、already_present の集合 (plotted entries のキー) と
        # 同じ文字列で突き合わせられる。
        candidate_key = f"{target_key}{KEY_SEPARATOR}{bare}"
        candidate = session.resolve_signal(candidate_key)
        if candidate is None:
            # 未ロードの target_key もここで全件 no_match になる (旧 group_signals の
            # KeyError 経路と同じ結果)。この順序 (解決 -> 構造判定) にするのは
            # container の母数を「実在する候補」だけに限るため — 解決できない候補まで
            # 構造を見ると、単に名前が無いケースが「構造不一致」として要約に出る。
            # なお is_container_channel 自体は未ロード key でも例外を投げない
            # (column_names_of は表を dict.get で引き (display_name,) を返す)。
            no_match += 1
            continue
        if session.is_container_channel(target_key, bare):
            container += 1
            continue
        if candidate.metadata.get("name_deduplicated"):
            ambiguous += 1
            continue

        ref_unit = ref_sig.metadata.get("unit", "") if ref_sig is not None else ""
        cand_unit = candidate.metadata.get("unit", "")
        if ref_unit != cand_unit:
            unit_mismatch += 1
            continue

        pair = (candidate_key, axis_index)
        if pair in existing_pairs:
            already_present += 1
            continue

        panel.add_signal_to_axis(candidate_key, axis_index)
        existing_pairs.add(pair)
        added += 1

    return OverlayResult(
        total=total,
        added=added,
        no_match=no_match,
        unit_mismatch=unit_mismatch,
        already_present=already_present,
        ambiguous=ambiguous,
        container=container,
    )
```

`format_overlay_summary` の節組み立てに 1 行追加（既存 4 節の**後ろ**に置く — 併記順が変わると
E-2b 期の複合節テストが無関係に落ちる）:

```python
    if result.ambiguous:
        clauses.append(S.OVERLAY_CLAUSE_AMBIGUOUS_TMPL.format(n=result.ambiguous))
    if result.container:
        clauses.append(S.OVERLAY_CLAUSE_CONTAINER_TMPL.format(n=result.container))
```

**(3-e) `src/valisync/gui/viewmodels/signal_preview_vm.py`**

import ブロックを差し替え:

```python
from valisync.core.downsampler.downsampler import Downsampler
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
from valisync.gui.display_names import display_names as _resolve_display_names
from valisync.gui.display_names import split_key
```

`_signal` / `_all_loaded_signal_keys` / `display_name` を次で置き換える（`_all_loaded_signal_keys`
は削除）:

```python
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
        ``_resolved_by_key`` へ **恒久的に** 入る (LRU は E-3 では入れない = C-g) ため、
        プレビュー窓のタイトルやプロパティの「名前」を出すだけで、他ファイルぶんの
        列 Signal が寿命いっぱい滞留する。``has_column`` (列の存在) と
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
```

**(3-f) `src/valisync/gui/views/main_window.py`**

import ブロックへ追加:

```python
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
from valisync.gui.display_names import split_key
```

`_on_diagnostic_activated` の 2 番目のループを差し替え:

```python
        # Defensive: no current emitter sends a signal name here, but this
        # fallback stays ready for a future signal-name emit / signal-row
        # selection without another _on_diagnostic_activated rewrite.
        #
        # E-3: 診断が載せる signal_name は **素の列名** ("Mat[0]")。反転後
        # group_signals は物理チャンネルしか返さないので、名前の線形比較では
        # 列名の診断が二度と一致しない (ダブルクリックしても無反応)。解決器なら
        # 列キーを最長一致で引ける。名前空間つきキーがそのまま来た場合は所属
        # グループへ絞ってから引く (二重接頭辞にしない)。
        group_key, bare = split_key(target)
        for key in self.app_vm.loaded_file_keys:
            if group_key and group_key != key:
                continue
            if self.app_vm.session.resolve_signal(f"{key}{KEY_SEPARATOR}{bare}"):
                self.app_vm.set_active_file(key)
                return
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/gui/test_reference_overlay.py tests/gui/test_main_window_reference_overlay.py tests/gui/test_signal_preview_vm.py tests/gui/test_signal_preview_window.py tests/core/test_export_container_guard.py tests/test_session.py tests/gui/test_main_window.py tests/test_export.py tests/test_csv_export_options.py -q`

その後、全体: `uv run pytest -q`（T6 で書き換えた fixture 群も含めて無回帰であること）

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

1 つずつ戻して RED を確認し、必ず元に戻す。

1. `reference_overlay`: `candidate = session.resolve_signal(candidate_key)` を旧実装
   （`session.group_signals(target_key)` から作った bare 名 dict の lookup）へ戻す →
   `test_overlay_matches_expanded_column_across_files` が `added == 0 / no_match == 1` で RED
   （＝**現状のままなら「0 件重ねました（同名なし 1）」が出る**ことの実証）。
2. `reference_overlay`: `is_container_channel` の分岐を削除 →
   `test_overlay_skips_container_channel_candidate` が `container == 0` かつ親が
   `add_signal_to_axis` されて `plotted_entries()` が 2 件になり RED。
3. `signal_preview_vm._signal`: 解決器を旧線形走査へ戻す →
   `test_column_key_resolves_to_expanded_column` が `KeyError: '名前'` で RED。
4. `signal_preview_vm._signal`: `is_container_channel` の分岐を削除 →
   `test_container_channel_is_not_previewable` が RED（`properties() != []` かつ
   `is_materialized is False` も落ちる＝全読みが起きたことの実証）。
5. `signal_preview_vm.display_name`: 存在判定を `has_column(...) or is_container_channel(...)` から
   `session.resolve_signal(other_key) is not None` へ戻す（＝表示のために鋳造する）→
   `test_display_name_does_not_mint_any_column` が `mint_count` 差 1 で RED
   （**表示だけで列 Signal が恒久登録される**ことの直接証明。`resolved_keys(k2)` も
   非空になる）。さらに母数を「全ファイルの全列を `column_names_of` で列挙して
   `resolve_signal`」へ広げると同テストが差 3 で RED。逆に母数を旧 `group_signals`
   列挙へ戻すと `test_column_display_name_qualified_when_two_files_share_column` が RED。
6. `session.source_info`: `n_channels=len(group.signals)` へ戻す →
   `test_source_info_n_channels_counts_expanded_columns` が `assert 2 == 4` で RED。
7. `session._reject_container_channels`: 判定を `sig.values.ndim != 1` に置き換える →
   `test_session_rejects_container_channel_without_reading_values` の
   `is_materialized is False` が RED（拒否自体は通るため、**値を読んだこと**だけを捕まえる
   honest observable であることの確認）。
8. `csv_exporter._require_single_value_columns` の呼び出しを削除 →
   `test_exporter_rejects_multi_column_values_*` が `ValueError` ではなく生 `TypeError` で RED。
9. `main_window._on_diagnostic_activated`: 旧 `any(sig.name == target for sig in group_sigs)` へ
   戻す → `test_jumps_by_expanded_column_name` が RED（既存の
   `test_jumps_by_signal_name`（名前空間つき target）は新旧どちらでも GREEN であることも確認し、
   互換が保たれていることを示す）。

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

```bash
git add src/valisync/gui/reference_overlay.py \
        src/valisync/gui/strings.py \
        src/valisync/gui/viewmodels/signal_preview_vm.py \
        src/valisync/gui/views/main_window.py \
        src/valisync/core/session.py \
        src/valisync/core/export/csv_exporter.py \
        tests/core/test_export_container_guard.py \
        tests/gui/test_reference_overlay.py \
        tests/gui/test_main_window_reference_overlay.py \
        tests/gui/test_signal_preview_vm.py \
        tests/gui/test_signal_preview_window.py \
        tests/gui/test_main_window.py \
        tests/test_session.py
git commit -m "$(cat <<'EOF'
feat(core,gui): E-3 T7 消費者の回復＋2-D 親の core 拒否

- reference_overlay: 対象候補を列レベル解決へ (C-c)。物理名マップのままだと
  Mat[0] が全て no_match になり「0 件重ねました（同名なし N）」という正常に
  見える嘘が出る。Mat[0] 衝突 (実チャンネル優先) を衝突 fixture で test-lock
- reference_overlay: 配列/構造体チャンネル本体を container として除外・要約に
  「構造不一致 N」節を追加
- signal_preview_vm: 線形走査 -> 解決器 (列キーで真っ白になる症状の根治)。
  E-0 母数を「他ファイルごとの同名 1 本」へ縮約し 264k 列の列挙を回避。親は
  値を読まずに非プレビューへ
- session: source_info.n_channels を列数へ (U2)・export_csv で 2-D 親を
  ColumnRecord から判定して拒否 (C-d・値は読まない)・is_container_channel 新設
- csv_exporter: 直呼び経路の最後の砦 (生 TypeError -> 日本語 ValueError)
- main_window: 診断アクティベートの信号名 fallback を解決器経由へ

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 8: 1024 展開ガードの退役（C-i）＋ `W[0]`→`W[1]` の test-lock（C-f）

**Files:**
- Create: `tests/core/loaders/test_expansion_guard_retirement.py`
- Modify: `tests/mdf4_helpers.py`（末尾に `write_mdf4_duplicate_wide` を追加。`write_mdf4_wide_2d:323-341` の直後が定位置）
- Modify: `src/valisync/core/loaders/mdf_loader.py:5`（`dataclass` import）・`:18`（定数）・`:21-38`（`OversizedChannel`/`ExpansionRequest`/`ConfirmExpansion`）・`:246-275`（`_scan_oversized`）・`:277-282`（`load` 署名）・`:319-345`（スキャン＋確認ブロック）・`:356-368`（`_load_group` 呼び出し）・`:442-453`（`_load_group` 署名＋`skip_keys` フィルタ）
- Modify: `src/valisync/core/session.py:14-19`（import）・`:26-37`（`__all__`）・`:137-164`（`load` 署名・docstring・委譲）
- Modify: `src/valisync/gui/views/main_window.py:85`（import）・`:205-206`（confirmer 生成）・`:655-661`（`session.load` の kwarg）
- Modify: `src/valisync/gui/strings.py:115-119`（`EXPANSION_OVER_LIMIT_TMPL`）
- Delete: `src/valisync/gui/workers/expansion_confirmer.py`（全体）
- Delete: `src/valisync/gui/views/expansion_dialog.py`（全体）
- Delete: `tests/gui/test_expansion_dialog.py`・`tests/gui/test_expansion_confirmer.py`・`tests/realgui/test_expansion_dialog_realinput.py`（全体）
- Modify: `tests/test_loaders.py:39`（import）・`:768-784`（`test_leaf_column_count_matches_flatten` を `_all_leaf_count` へ移送）・`:838-889`（LD-14 4 テスト）
- Modify: `tests/core/loaders/test_column_names.py:12`（import）・`:159-164`（同上の移送）
- Modify: `tests/test_session.py:335-347`（`test_session_load_passes_confirm_expansion`）
- Modify: `tests/gui/test_main_window.py:679-689`・`:732`
- Modify（`confirm_expansion=None` 実引数の一括除去・18 サイト）: `tests/core/loaders/test_mdf_loader_lazy.py:17,37,96,151,166`・`tests/core/loaders/test_mdf_loader_master_retention.py:72`・`tests/core/loaders/test_namespaced_lazy.py:57,81`・`tests/core/loaders/test_physical_channel_metadata.py:21,42,68`・`tests/core/sync/test_offset_lazy.py:60,71`・`tests/core/test_handle_release.py:46,195,225`・`tests/gui/test_discard_teardown.py:88`・`tests/gui/test_unload_export_guard.py:47`
- Modify（`_expansion_confirmer` への実行時アクセス除去・4 サイト）: `tests/realgui/test_lazy_load_realclick.py:174-176`・`tests/realgui/test_channel_tree_flatten_realclick.py:435-436`・`scripts/fu16_teardown_bench.py:94-99`・`scripts/measure_lazy_footprint.py:587-589`
- Modify: `docs/audit-findings-catalog.md:124`（LD-14 行の状態セル）・`docs/development.md:119-120`
- Test: `tests/core/loaders/test_expansion_guard_retirement.py`（新規・CI-live）

**Interfaces:**
- Consumes（T1）: `Session.column_names_of(key: str, display_name: str) -> tuple[str, ...]` ／ `Session.total_column_count(key: str) -> int` ／ 既存 `Session.resolve_signal(key: str) -> Signal | None`
- Consumes（T6）: 反転後のローダー契約 — `SignalGroup.signals` は**物理チャンネル 1 本につき Signal 1 個**、列は `resolve_signal` で要求時に鋳造される
- Produces: `MdfLoader.load(file_path: Path, cancel: Callable[[], bool] | None = None) -> LoadResult` ／ `Session.load(file_path: Path, format_def: FormatDefinition | None = None, cancel: Callable[[], bool] | None = None) -> LoadOutcome`（いずれも `confirm_expansion` 消滅）。T9 の計測器（`scripts/measure_lazy_footprint.py` / `scripts/fu16_teardown_bench.py`）と realgui はこの署名・`MainWindow` に `_expansion_confirmer` が無いことを前提にする
- Produces: `tests/mdf4_helpers.write_mdf4_duplicate_wide(tmp_path: Path, cols: int = 1025) -> Path`（重複名＋広幅の唯一の fixture）

---

- [ ] **Step 1: 失敗テストを書く**

まず fixture。`tests/mdf4_helpers.py` の `write_mdf4_wide_2d`（`:323-341`）の直後に追加する（`np` / `MDF` / `ASignal` は既に import 済み）。

```python
def write_mdf4_duplicate_wide(tmp_path: Path, cols: int = 1025) -> Path:
    """同名 "W" の 2 チャンネル (先=幅 cols の 2D / 後=スカラー) + Clean — C-f 用.

    1024 ガードが生きている間は先頭の広幅 "W" がヘッドレスで丸ごとスキップされ、
    生き残るスカラー側が LD-08 の idx 0 を取って ``W[0]`` になる。ガード退役後は
    両方が載るのでスカラーは ``W[1]`` へ動く — この永続キーの移動 (spec C-f:
    意図的リネーム・移行パスなし) を固定するための fixture。prod_demo には重複名が
    無い (scripts/generate_demo_mf4.py の全チャンネル名は一意) ため、実データでは
    この組み合わせを作れず、合成 fixture が唯一の観測点になる。

    列 j の値は j % 256 (write_mdf4_wide_2d と同じ規則) で列ごとに識別できる。
    先に append したチャンネルが小さい gi を取ることに依存する — 順序が入れ替わると
    dedup インデックスが逆になり、テストは (無言の pass ではなく) FAIL する。
    """
    ts = np.array([0.0, 0.1, 0.2], dtype=np.float64)
    mat = np.tile(np.arange(cols, dtype=np.uint8), (3, 1))  # (3, cols)
    mdf = MDF()
    try:
        mdf.append([ASignal(samples=mat, timestamps=ts, name="W")])
        mdf.append(
            [ASignal(samples=np.array([7.0, 8.0, 9.0]), timestamps=ts, name="W")]
        )
        mdf.append(
            [ASignal(samples=np.array([1.0, 2.0, 3.0]), timestamps=ts, name="Clean")]
        )
        path = tmp_path / "dupwide.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path
```

次に新規テストファイル `tests/core/loaders/test_expansion_guard_retirement.py`。

```python
"""1024 展開ガードの退役 (C-i) と LD-08 dedup インデックスの移動 (C-f) の test-lock.

E-3 の反転でローダーは物理チャンネル 1 本につき Signal 1 個を発行し、列は要求時に
鋳造される。列が Signal にならない以上「per-channel の展開列数上限」を設ける理由
(オブジェクト爆発とメモリ) が消えたので、1024 ガードと確認モーダルを退役させた。

退役は LD-08 の [idx] を動かす: ガードが生きている間はスキップされた広幅チャンネルが
インデックスを消費しないため、同名の生存チャンネルが W[0] を取っていた。退役後は
広幅も載るので生存側は W[1] へ動く。**意図的リネーム・移行パスなし** (spec C-f) —
プロット/軸/オフセットのセッション永続化は未実装 (F-1 defer 中) ゆえ実害はない。
本ファイルはその契約を凍結し、ガードの無言の復活を RED にする。

demo_data には依存しない (重複名が無く、そもそも CI で生成されない)。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np

from tests.mdf4_helpers import write_mdf4_duplicate_wide
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
from valisync.core.session import Session


def test_wide_channel_loads_without_any_confirmation(tmp_path: Path) -> None:
    """ヘッドレスでも広幅チャンネルが載る (旧: コールバック不在 = 全スキップ + 警告)."""
    path = write_mdf4_duplicate_wide(tmp_path, cols=1025)
    result = MdfLoader().load(path)  # 確認コールバックという概念自体が無い

    sg = result.signal_group
    assert sg is not None
    # 物理チャンネル 3 本 (広幅 W / スカラー W / Clean) が全て生存する。
    assert {s.name for s in sg.signals} == {"W[0]", "W[1]", "Clean"}
    # fixture は完全に健全なデータなので、退役後は警告/エラー診断がゼロになる。
    # 退役前はここに「展開列数 1025 が上限 1024 を超えるためスキップ」が 1 件出る。
    assert not [d for d in result.diagnostics if d.level in ("error", "warning")], [
        d.message for d in result.diagnostics
    ]


def test_dedup_index_shifts_when_wide_channel_is_no_longer_skipped(
    tmp_path: Path,
) -> None:
    """C-f: 生存スカラーの永続キーが W[0] -> W[1] へ動く (意図的・移行なし)."""
    path = write_mdf4_duplicate_wide(tmp_path, cols=1025)
    session = Session()
    key = session.load(path).key

    # 先に載る広幅チャンネルが idx 0 を取る。列名は dedup の [0] と展開の [i] が
    # 同じ角括弧で連なる — この文法 (W[0][i]) も併せて凍結する。
    wide_cols = session.column_names_of(key, "W[0]")
    assert len(wide_cols) == 1025
    assert wide_cols[0] == "W[0][0]"
    assert wide_cols[-1] == "W[0][1024]"

    # 生存スカラーは idx 1 へ動いた (ガードが生きていた頃はこれが W[0] だった)。
    assert session.column_names_of(key, "W[1]") == ("W[1]",)
    scalar = session.resolve_signal(f"{key}{KEY_SEPARATOR}W[1]")
    assert scalar is not None
    np.testing.assert_array_equal(scalar.values, [7.0, 8.0, 9.0])

    # U2 の母数 (列数) にも退役が波及する: 1025 (広幅) + 1 (スカラー) + 1 (Clean)。
    assert session.total_column_count(key) == 1027


def test_column_of_duplicated_wide_channel_resolves_to_the_right_channel(
    tmp_path: Path,
) -> None:
    """重複生名 + 構造相違でも鋳造が正しい方のチャンネルを引く (退役で初到達).

    生名 "W" は 2 つの物理チャンネル (2D 1025 列 / スカラー) が共有しており、
    parse_leaf の docstring が言う「健全性の限界」そのものの配置になる。ガードが
    あった頃は広幅側がスキップされて到達不能だった経路。
    """
    path = write_mdf4_duplicate_wide(tmp_path, cols=1025)
    session = Session()
    key = session.load(path).key

    col = session.resolve_signal(f"{key}{KEY_SEPARATOR}W[0][5]")
    assert col is not None
    np.testing.assert_array_equal(col.values, [5, 5, 5])  # 列 j の値は j % 256


def test_load_signatures_no_longer_take_confirm_expansion() -> None:
    """退役の構造ロック: 引数だけ復活する部分的な巻き戻しを RED にする."""
    assert "confirm_expansion" not in inspect.signature(MdfLoader.load).parameters
    assert "confirm_expansion" not in inspect.signature(Session.load).parameters
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_expansion_guard_retirement.py -q`

Expected: 4 tests とも FAIL。

- `test_wide_channel_loads_without_any_confirmation`:
  `AssertionError: assert {'Clean', 'W[0]'} == {'Clean', 'W[0]', 'W[1]'}`（コールバック不在 → 広幅は全スキップ）
- `test_dedup_index_shifts_when_wide_channel_is_no_longer_skipped`:
  `AssertionError: assert 1 == 1025`（`column_names_of(key, "W[0]")` が生き残ったスカラーの `("W[0]",)` を返す）
- `test_column_of_duplicated_wide_channel_resolves_to_the_right_channel`:
  `AssertionError: assert None is not None`（`W[0]` はスカラーなので `W[0][5]` は解決不能）
- `test_load_signatures_no_longer_take_confirm_expansion`:
  `AssertionError: assert 'confirm_expansion' not in mappingproxy({...})`

- [ ] **Step 3: 実装**

**3a. `src/valisync/core/loaders/mdf_loader.py`**

`:5` の import を削除（`@dataclass` はこのファイルでは `OversizedChannel`/`ExpansionRequest` の 2 箇所だけ。T6 が新たな `@dataclass` を足していた場合は残す — 判定は `uv run ruff check` の F401 のみ）。

```python
from dataclasses import dataclass
```

`:18-38` を丸ごと削除（定数 → `OversizedChannel` → `ExpansionRequest` → `ConfirmExpansion`）。削除後は `from valisync.core.models.sample_source import LazyMdfValues` の次が `_BUS_TYPE_MAP` のコメントになる。

`:246-275` の `_scan_oversized` メソッド全体を削除（`_format_label` と `load` の間）。

`_leaf_column_count`（`:78-85`）も**関数ごと削除する**。唯一の production 呼び出し元が
`_scan_oversized`（`:271`）であり、退役後は誰も呼ばない — ruff は未使用のモジュール関数を
検出しないので、残すと黙って死にコードになる。**`_all_leaf_count`（`:88-94`）は残す** —
spec S2 のとおり「N 本に展開」info 診断の dtype-blind な母数として T6 の
`_expansion_diagnostic` が使う（数値リーフのみ数える `column_names.leaf_count` とは別物）。
`_leaf_column_count(arr)` は定義上 `_all_leaf_count(spec_from_probe(arr))` と同値なので、
テスト側は呼び出しをそのまま置換すれば挙動は 1 ビットも変わらない（下の 3f）。

`load` の署名（`:277-282`）:

```python
    def load(
        self,
        file_path: Path,
        cancel: Callable[[], bool] | None = None,
    ) -> LoadResult:
```

`:319-347` のスキャン＋確認ブロックを削除し、`try:` の直後を `name_total` から始める:

```python
        try:
            name_total = self._count_names(mdf)
            name_seen: dict[str, int] = {}
```

`_load_group` 呼び出し（`:356-368`）から `skip_keys,` を落とす:

```python
            for gi in mdf.virtual_groups:
                self._load_group(
                    mdf,
                    gi,
                    resolved_path,
                    name_total,
                    name_seen,
                    signals,
                    diagnostics,
                    cancel,
                    handle,
                )
```

`_load_group` の署名末尾とフィルタ（`:443-453`。T6 で本体が変わっている可能性があるため、**この 2 箇所だけ**を差し替える）:

```python
        cancel: Callable[[], bool] | None,
        handle: MdfHandle,
    ) -> None:
        entries = self._group_entries(mdf, gi)
        if not entries:
            return
```

**3b. `src/valisync/core/session.py`**

import（`:14-19`）:

```python
from valisync.core.loaders.mdf_loader import MdfLoader
```

`__all__`（`:26-37`）:

```python
__all__ = [
    "LoadCancelled",
    "LoadError",
    "LoadManyResult",
    "LoadOutcome",
    "RemovalResult",
    "Session",
    "SourceInfo",
]
```

`load`（`:137-162`）— 署名から `confirm_expansion` を、docstring から最終文（「``confirm_expansion`` は…（LD-14・CSV では無視）」）を、委譲から kwarg を落とす:

```python
    def load(
        self,
        file_path: Path,
        format_def: FormatDefinition | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> LoadOutcome:
        """Load a file and return the group key plus any loader diagnostics.

        Dispatches to the CSV or MDF4 loader by file type. Raises LoadError when
        the loader reports failure. ``cancel`` is a cooperative callback the
        loader polls at checkpoints; when it returns True the loader raises
        LoadCancelled and no group is registered (FB-04 — user-initiated, not
        an error).
        """
        file_path = Path(file_path)
        if self._csv_loader.supports(file_path):
            if format_def is None:
                raise ValueError("CSV の読み込みにはフォーマット定義が必要です")
            result = self._csv_loader.load(file_path, format_def, cancel=cancel)
        elif self._mdf_loader.supports(file_path):
            result = self._mdf_loader.load(file_path, cancel=cancel)
```

**3c. `src/valisync/gui/views/main_window.py`**

`:85` の import 行を削除:

```python
from valisync.gui.workers.expansion_confirmer import ExpansionConfirmer
```

`:205-206`（コメント＋生成）を削除:

```python
        # GUI スレッド所属 — ワーカーからの展開確認をモーダルへ marshal (LD-14)。
        self._expansion_confirmer = ExpansionConfirmer(self)
```

`:655-661` の lambda から kwarg を落とす:

```python
        self._load_controller.submit(
            lambda: session.load(
                target,
                fmt,
                cancel=cancel_event.is_set,
            ),
```

**3d. `src/valisync/gui/strings.py:115-119`** — 節ごと削除:

```python
# ── ダイアログ: 展開確認 (expansion_dialog・R-02 半角括弧) ────────────────────
EXPANSION_OVER_LIMIT_TMPL: Final = (
    "以下の信号は展開すると列数が上限 ({limit}) を超えます。\n"
    "展開するものを選択してください（未選択はスキップ）。"
)
```

**3e. ファイル削除**

```bash
git rm src/valisync/gui/workers/expansion_confirmer.py \
       src/valisync/gui/views/expansion_dialog.py \
       tests/gui/test_expansion_dialog.py \
       tests/gui/test_expansion_confirmer.py \
       tests/realgui/test_expansion_dialog_realinput.py
```

`gui/workers/__init__.py` / `gui/views/__init__.py` は `ExpansionConfirmer`/`ExpansionDialog` を再エクスポートしていないので変更不要（確認済み）。realgui の allowlist（`tests/gui/test_realgui_layer_c_contract.py:_KNOWN_SYNTHETIC`）は空集合なので削除で陳腐化しない。

**3f. 呼び出しサイトの一括掃除**

実引数 18 サイトはすべて `, confirm_expansion=None)` の形（実測確認済み）なので機械置換でよい:

```bash
sed -i 's/, confirm_expansion=None)/)/' \
  tests/core/loaders/test_mdf_loader_lazy.py \
  tests/core/loaders/test_mdf_loader_master_retention.py \
  tests/core/loaders/test_namespaced_lazy.py \
  tests/core/loaders/test_physical_channel_metadata.py \
  tests/core/sync/test_offset_lazy.py \
  tests/core/test_handle_release.py \
  tests/gui/test_discard_teardown.py \
  tests/gui/test_unload_export_guard.py
```

`tests/test_loaders.py`: `:39` の `write_mdf4_wide_2d,` を import リストから削除（この 4 テスト以外に使用箇所が無く、残すと F401）。`:838-889` の 4 テスト（`test_scan_oversized_flags_wide_channel` / `test_oversized_expands_only_when_confirmed` / `test_oversized_skipped_when_declined` / `test_oversized_skipped_headless_without_callback`）を削除。

`_leaf_column_count` は 3a で消えるので、それを呼んでいるテスト **2 本**を
`_all_leaf_count` へ移送する（不変条件そのものは 1 つも落とさない）。

`tests/test_loaders.py:768-784` を置換:

```python
def test_all_leaf_count_matches_flatten() -> None:
    """任意形状で _all_leaf_count は _flatten のリーフ数と一致する (LD-14)."""
    from valisync.core.loaders.column_names import spec_from_probe
    from valisync.core.loaders.mdf_loader import _all_leaf_count, _flatten

    cases = [
        np.zeros(3),  # 1D scalar -> 1
        np.zeros((3, 4)),  # 2D -> 4
        np.zeros((3, 2, 5)),  # 3D -> 10
        np.zeros((2, 2, 2, 3)),  # 4D -> 12
        np.zeros(3, dtype=[("x", "<f8"), ("y", "<f8", (4,))]),  # struct -> 1+4=5
    ]
    for arr in cases:
        assert _all_leaf_count(spec_from_probe(arr)) == len(_flatten("x", arr))

    assert _all_leaf_count(spec_from_probe(np.zeros((3, 4)))) == 4
    assert _all_leaf_count(spec_from_probe(np.zeros((3, 2, 5)))) == 10
    assert _all_leaf_count(spec_from_probe(np.zeros(3))) == 1
```

`tests/core/loaders/test_column_names.py`: `:12` の import を
`from valisync.core.loaders.mdf_loader import _all_leaf_count, _flatten` に変え、
`:159-164` を置換（この 1 本を落とすと「info の母数は dtype 盲目」という S2 の根拠が
テストから消える）:

```python
def test_all_leaf_count_counts_all_leaves_including_non_numeric() -> None:
    # _all_leaf_count は「N 本に展開」info 診断の母数で dtype 盲目 (全リーフを数える)。
    # leaf_count (数値のみ) とは意図的に別物である。
    arr = np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")])
    assert _all_leaf_count(spec_from_probe(arr)) == 2
    assert leaf_count(spec_from_probe(arr)) == 1
```

`tests/test_session.py:335-347` の `test_session_load_passes_confirm_expansion` を削除（内部で `write_mdf4_wide_2d` を local import しているので追加の import 掃除は不要）。

`tests/gui/test_main_window.py`: `:679-681` の fake_load から引数と記録を落とし、`:688-689` の配線 assert を退役ガードへ置換する。

```python
    def fake_load(path, fmt, cancel=None):
        seen["cancel"] = cancel
        raise RuntimeError("stop before real load")

    monkeypatch.setattr(window.app_vm.session, "load", fake_load)
    with contextlib.suppress(RuntimeError):
        captured["load_callable"]()
    assert seen["cancel"] == event.is_set  # 同一 Event の bound method
    # 1024 ガード退役 (E-3): 展開確認モーダルは存在しない。fake_load が
    # confirm_expansion を受け取らないこと自体が「production が渡していない」の
    # 証明 (渡していれば TypeError で RED)。confirmer が残っていないことも見る。
    assert not hasattr(window, "_expansion_confirmer")
```

`:732` も同様に `def fake_load(path, f, cancel=None):` へ。

realgui 2 サイト — `tests/realgui/test_lazy_load_realclick.py:174-176` と `tests/realgui/test_channel_tree_flatten_realclick.py:435-436` の「全スキップ差し替え」コメント＋代入行を削除する（属性が消えるため残すと `AttributeError`）。反転後は列が Signal にならないので、全列が載っても両テストの前提（未プロット列が未展開のまま）は変わらない。

scripts 2 サイト — 実行時に `AttributeError` になる行だけを外す:

`scripts/fu16_teardown_bench.py:94-99`:

```python
    # ExpansionConfirmer を全展開に差し替え (330k 到達に必須・小データ false-green 防止)。
    def _expand_all(request):
        return set(range(len(request.channels)))

    window._expansion_confirmer.confirm = _expand_all  # type: ignore[method-assign]
```

`scripts/measure_lazy_footprint.py:587-589`:

```python
    # Skip every oversized array expansion (empty set = skip all).
    win._expansion_confirmer.confirm = lambda request: set()  # type: ignore[assignment]
```

両スクリプトの docstring（`fu16_teardown_bench.py:3,5` の「ExpansionConfirmer 全展開」「confirmer 未 patch」／`measure_lazy_footprint.py:17-18` の "Array expansion is skipped"）は**本タスクでは触らない** — 計測器の文言と数値の再ベースラインは T9（計測器改修＋実測）の担当。

**3g. 記録（docs）**

`docs/audit-findings-catalog.md:124`（LD-14 行の状態セル・文字列は一意）:

```
| LD-14 | 🟠 | ✅**解消（LD-14）**
```
→
```
| LD-14 | 🟠 | ✅**解消（LD-14）／1024 ガードと確認モーダルは E-3 反転後に退役（2026-07-29・列は Signal にならないため上限の根拠が消滅・`W[0]`→`W[1]` の意図的リネームは `tests/core/loaders/test_expansion_guard_retirement.py` で test-lock）**
```

`docs/development.md:119` の実機確認手順から (i) を落とす:

```
- 実機確認: `uv run valisync` でロード → (i) 広幅アレイの LD-14 展開ダイアログがチェックボックス多数でスクロール不能（FU-01）・(ii) ロード後にドック表示切替がフリーズ気味（FU-03）を `/run`・`/verify` で観測。
```
→
```
- 実機確認: `uv run valisync` でロード → ロード後にドック表示切替がフリーズ気味（FU-03）を `/run`・`/verify` で観測。（旧 (i) の LD-14 展開ダイアログは E-3 で退役）
```

`docs/development.md:120` の実測値行から、存在しない UI への参照だけを外す:

```
・GUI では ExpansionDialog で選択）
```
→
```
。E-3 で 1024 ガードを退役したため現在の数値は T9 の再実測で更新）
```

**3h.（必要な場合のみ）鋳造の重複生名衝突**

`test_column_of_duplicated_wide_channel_resolves_to_the_right_channel` が RED のまま残る場合、`signal_group_manager._mint_column`（T2）が `parse_leaf` を**生名キー**の Mapping で引いている。生名 `"W"` は構造の異なる 2 チャンネル（2D 1025 列 / スカラー）へ衝突する（`column_names.parse_leaf` docstring の「健全性の限界」）。`column_records(group_key)`（T1・キーは LD-08 dedup 済み表示名）から `{display_name: record.spec}` を組んで `parse_leaf` に渡し、セレクタには当該 `ColumnRecord.raw_base_name` を使う形へ直す。退役前はこの配置に到達できなかった（広幅がスキップされていた）ため、本タスクで初めて露出する。

- [ ] **Step 4: 通ることを確認**

```
uv run pytest tests/core/loaders/test_expansion_guard_retirement.py -q
uv run pytest tests/test_loaders.py tests/test_session.py tests/core -q
uv run pytest tests/gui -q
rg -n "confirm_expansion|ExpansionConfirmer|ExpansionDialog|EXPANSION_COLUMN_LIMIT|OversizedChannel|ExpansionRequest" src/ tests/ scripts/
rg -n "_leaf_column_count" src/ tests/ scripts/
```

2 本の rg はどちらも**ゼロ件**であること（コメント/docstring も含む。`_leaf_column_count` の側は 3a の関数削除と 3f のテスト移送の両方が済んでいることの検証で、`docs/` の歴史記述は対象外）。既知の残存候補は `tests/test_native_dtype_memory.py` の module docstring（「展開上限 1024 を超えると headless では全スキップされる…」）と `cols = 1000  # < EXPANSION_COLUMN_LIMIT(1024)` のコメント — ヒットしたら、ガード退役後は `cols` が任意（1000 のままで速い）であることを述べる文へ書き換える。`build/` 配下はビルド成果物なので対象外。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

3 つとも実行し、RED を確認してから戻す。

1. **ガードの復活**（退役そのもののロック）: `mdf_loader._load_group` の `entries = self._group_entries(mdf, gi)` を
   `entries = [e for e in self._group_entries(mdf, gi) if _all_leaf_count(spec_from_probe(mdf.select([e], **self._PROBE_OPTIONS)[0].samples)) <= 1024]`
   に差し替える（`_leaf_column_count` は 3a で削除済みなので、その中身をそのまま展開した形）→ `test_wide_channel_loads_without_any_confirmation`（名前集合が `{'Clean','W[0]'}`）と `test_dedup_index_shifts_...`（`1 == 1025`）と `test_column_of_duplicated_wide_channel_...`（`None is not None`）が RED。
2. **dedup インデックスの向き**（C-f の中身のロック）: `mdf_loader.load` の `for gi in mdf.virtual_groups:` を `for gi in reversed(list(mdf.virtual_groups)):` に変える → 広幅が `W[1]`、スカラーが `W[0]` になり `test_dedup_index_shifts_...` が RED（`W[0]` の列数 1 / `W[1]` が 1025）。「名前がどれか 1 つ存在する」ではなく**どの物理チャンネルがどの idx を取るか**を pin していることの証明。
3. **引数だけの巻き戻し**: `MdfLoader.load` に `confirm_expansion: object | None = None` を足す → `test_load_signatures_no_longer_take_confirm_expansion` が RED。

realgui（実機でモーダルが二度と出ないこと）は T9 の ①ゲートで実証する — 本タスクの削除面は Layer A/B の上記 3 サボタージュで機械的に閉じる。

- [ ] **Step 6: ゲート＋コミット**

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

（`ruff check` は 3a の `dataclass` import 残骸と `tests/test_loaders.py:39` の `write_mdf4_wide_2d` 残骸を F401 で拾う唯一の判定点。`| tail` に通さない — exit code が隠れる。）

```bash
git add src/valisync/core/loaders/mdf_loader.py \
        src/valisync/core/session.py \
        src/valisync/gui/views/main_window.py \
        src/valisync/gui/strings.py \
        tests/mdf4_helpers.py \
        tests/core/loaders/test_expansion_guard_retirement.py \
        tests/core/loaders/test_column_names.py \
        tests/core/loaders/test_mdf_loader_lazy.py \
        tests/core/loaders/test_mdf_loader_master_retention.py \
        tests/core/loaders/test_namespaced_lazy.py \
        tests/core/loaders/test_physical_channel_metadata.py \
        tests/core/sync/test_offset_lazy.py \
        tests/core/test_handle_release.py \
        tests/gui/test_discard_teardown.py \
        tests/gui/test_unload_export_guard.py \
        tests/gui/test_main_window.py \
        tests/test_loaders.py \
        tests/test_session.py \
        tests/realgui/test_lazy_load_realclick.py \
        tests/realgui/test_channel_tree_flatten_realclick.py \
        scripts/fu16_teardown_bench.py \
        scripts/measure_lazy_footprint.py \
        docs/audit-findings-catalog.md \
        docs/development.md
git add -A src/valisync/gui/workers/expansion_confirmer.py \
           src/valisync/gui/views/expansion_dialog.py \
           tests/gui/test_expansion_dialog.py \
           tests/gui/test_expansion_confirmer.py \
           tests/realgui/test_expansion_dialog_realinput.py
git commit -m "$(cat <<'EOF'
refactor(core)!: 1024 展開ガードを退役し確認モーダルを撤去 (C-i)

反転後は列が Signal にならないため per-channel 展開列数の上限を設ける根拠
(オブジェクト爆発とメモリ) が消えた。ガード・確認モーダル (ExpansionDialog /
ExpansionConfirmer)・confirm_expansion 引数を全経路から撤去する。副次に probe の
select 1 パス (実測 +1.35s) と worker→GUI で唯一のブロッキングモーダルが消える。

BREAKING: 退役は LD-08 dedup インデックスを動かす。スキップされていた広幅
チャンネルがインデックスを消費するようになり、同名の生存チャンネルの永続キーが
W[0] -> W[1] へ動く。spec C-f のとおり意図的リネーム・移行パスなし (セッション
永続化は F-1 defer 中で実害なし)。tests/core/loaders/test_expansion_guard_retirement.py
で test-lock。

_all_leaf_count は「N 本に展開」info 診断の dtype-blind な母数として存続 (S2)。
_leaf_column_count は唯一の呼び出し元 (_scan_oversized) を失うため関数ごと削除し、
不変条件テスト 2 本は _all_leaf_count(spec_from_probe(arr)) の直接検証へ移送した
(定義上の同値変換なので assert は 1 つも落としていない)。
EOF
)"
```

---

### Task 9: 計測器改修＋psutil 実測＋realgui ①ゲート（受け入れ）

**Files:**
- Modify: `tests/realgui/test_lazy_load_realclick.py`（`:84-157` ヘルパ群 / `:160-248` 既存テスト・末尾に新テスト追加）
- （`tests/realgui/test_channel_tree_flatten_realclick.py` の `_expansion_confirmer` patch 除去は **T8 で完了済み** — 本タスクでは触らない。無回帰確認だけ Step 4 で走らせる）
- Modify: `scripts/measure_lazy_footprint.py`（`:53-83` 計測プリミティブ / `:93-130` `load_one_more` / `:159-265` `browser_residue` / `:268-280` `DrainResult` / `:364-449` `materialize_leaves` / `:452-493` `drain_after_unload` / `:496-555` `report_drain` / `:558-663` `main`）
- Modify: `scripts/fu16_teardown_bench.py:30,95-99,111-123,161-166`
- Modify: `scripts/fu16_prune_bench.py:41`
- Test: `tests/realgui/test_lazy_load_realclick.py`

**Interfaces:**
- Consumes:
  - `Session.column_names_of(key: str, display_name: str) -> tuple[str, ...]`（T1）— 物理チャンネルの数値リーフ表示名。**鋳造しない**。
  - `Session.total_column_count(key: str) -> int`（T1）— グループの数値列総数（U2 の `n_channels` と同単位）。
  - `Session.resolve_signal(key: str) -> Signal | None`（既存 E-1）— 列キーの鋳造経路（production）。
  - `SignalGroupManager.mint_count: int` / `SignalGroupManager.resolved_keys(group_key) -> frozenset[str]`（既存 E-1・**C-e により `Session` には出さない**ので `session._groups` へ直接触る。realgui の先例＝`tests/realgui/test_close_release_spinner.py:66`）。
  - T6 反転後の `Session.group_signals(key)`＝**物理チャンネルのみ**。
  - T8 の 1024 ガード退役により `MainWindow._expansion_confirmer` は**存在しない**（`confirm_expansion` フックごと削除済み）。
- Produces:
  - `tests/realgui/test_lazy_load_realclick.py::test_expanding_parent_and_plotting_one_column_mints_only_that_column` — ①ゲートの鋳造オラクル。
  - `_count_materialized(session, key) -> list[str]`（同ファイル内・**物理チャンネル＋鋳造列**の両方を走査）。
  - `scripts/measure_lazy_footprint.py` の出口数値（RSS / **USS＝主指標** / オブジェクト数 / ドレインティック / 列読みレイテンシ）。後続タスクは無し（本タスクが E-3 の出口）。

---

- [ ] **Step 1: 失敗テストを書く**

`tests/realgui/test_lazy_load_realclick.py` のモジュール docstring 末尾に以下を追記する。

```python
E-3 (列展開の遅延化) 以後、「未展開」オラクルだけでは**恒真**になる: 列 Signal は
ロード時に存在せず、鋳造された列は ``SignalGroup.signals`` の外 (副テーブル
``SignalGroupManager._resolved_by_key``) に居るため ``session.group_signals()`` の
走査に**現れない**。そこで本ファイルは非鋳造 introspection (``mint_count`` /
``resolved_keys()``) を併用し、「親を展開しても鋳造 0・列を 1 本プロットして初めて
**その列だけ**が鋳造される」を実 OS 入力で assert する
(``test_expanding_parent_and_plotting_one_column_mints_only_that_column``)。
```

import ブロックへ fixture を追加する（`from pathlib import Path` の下、`import pytest` 群のあと）。

```python
from tests.mdf4_helpers import write_mdf4_flatten_fixture
```

`:84-157` のヘルパ群を次の内容へ置き換える（`_build_window` の抽出＝退役した
`_expansion_confirmer` patch の除去、`_real_select_and_menu_add` の index 化、
展開/行探索ヘルパの追加）。

```python
def _build_window(qtbot: QtBot):  # type: ignore[no-untyped-def]
    """実ディスプレイ上の本物の MainWindow (画面内へ配置・前面化)。

    1024 ガード (LD-14 の展開確認モーダル) は E-3 で退役したので
    ``_expansion_confirmer`` の差し替えは行わない — 全チャンネルが無条件に
    ロードされる (そもそも列は展開されない)。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    w = min(1200, screen.width() - 120)
    h = min(800, screen.height() - 120)
    window.setGeometry(screen.x() + 60, screen.y() + 60, w, h)
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    _pump_n(3)
    return window


def _panel_widget(window, tab: int, panel: int):  # type: ignore[no-untyped-def]
    return window.graph_area_view.tabs.widget(tab).widget(panel)


def _top_names(model) -> list[str]:  # type: ignore[no-untyped-def]
    """トップレベル行の Name 列 (子は触らない = 合成も鋳造も誘発しない)。"""
    return [model.data(model.index(r, 0)) for r in range(model.rowCount())]


def _child_names(model, parent) -> list[str]:  # type: ignore[no-untyped-def]
    return [
        model.data(model.index(r, 0, parent)) for r in range(model.rowCount(parent))
    ]


def _row_of(model, name: str) -> int:  # type: ignore[no-untyped-def]
    names = _top_names(model)
    assert name in names, f"トップ行に {name!r} が無い: {names}"
    return names.index(name)


def _first_scalar_leaf_row(model) -> int:  # type: ignore[no-untyped-def]
    """First top-level row that is a scalar leaf (signal_key_at not None).

    Array bases (LD-14) collapse under parent rows whose ``signal_key_at`` is
    None; scalars stay top-level leaves. Scanning only top-level indexes is
    lazy-safe — it never materializes a group's children (FU-22 B).
    """
    for row in range(model.rowCount()):
        if model.signal_key_at(model.index(row, 0)) is not None:
            return row
    raise AssertionError("チャンネルツリーにスカラー葉が無い")


def _click_expand_arrow(tree, index) -> None:  # type: ignore[no-untyped-def]
    """展開アフォーダンス (ブランチインジケータ) を実クリックする。

    QTreeView は rootIsDecorated の矢印を item 矩形の **左** の
    ``indentation()`` 幅の帯に描く。``visualRect`` はテキスト側の矩形なので、
    その左端から半インデント戻った点がユーザーが実際に叩く三角形の中心。
    """
    from PySide6.QtCore import QPoint

    tree.scrollTo(index)
    _pump_n(3)
    rect = tree.visualRect(index)
    assert rect.height() > 0, "展開対象行が可視域に無い"
    indent = tree.indentation()
    assert indent > 0, "indentation が 0 — 展開矢印が存在しない"
    arrow_x = rect.left() - indent // 2
    # 負値を黙って 2px へ丸めると、ジオメトリ計算の誤りが「どこか別の場所への
    # 誤クリック」として静かに揉み消される。丸めず失敗させる。
    assert arrow_x > 0, (
        f"展開矢印の想定 x が負 (rect.left()={rect.left()}, indent={indent}, "
        f"x={arrow_x}) — インデント計算が壊れている"
    )
    local = QPoint(arrow_x, rect.center().y())
    _real_click(*_phys_center(tree.viewport(), local))


def _count_materialized(group_sigs) -> list[str]:  # type: ignore[no-untyped-def]
    """Namespaced names of signals whose value source is materialized."""
    return [s.name for s in group_sigs if s._values_source.is_materialized]


def _real_select_and_menu_add(window, index) -> None:  # type: ignore[no-untyped-def]
    """Scroll *index* into view, real-click to select, then real right-click and
    real-click the "アクティブパネルに追加" menu item (nested QMenu.exec).

    An ESC watchdog closes a stuck popup so a missed click fails on an
    assertion rather than hanging the shared machine.
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    tree = window.channel_browser_view.tree
    tree.scrollTo(index)
    _pump_n(3)
    rect = tree.visualRect(index)
    assert rect.height() > 0, "対象行が可視域に無い (実クリックできない)"
    vp = tree.viewport()
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    px, py = _phys_center(vp, local)
    _real_click(px, py)  # select the row → "アクティブパネルに追加" enabled

    loop = QEventLoop()
    seen: dict[str, object] = {}

    def right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)

    def click_item() -> None:
        menu = QApplication.activePopupWidget()
        seen["popup"] = type(menu).__name__ if menu is not None else None
        if isinstance(menu, QMenu):
            act = next(
                (a for a in menu.actions() if a.text() == S.ACTION_ADD_TO_ACTIVE_PANEL),
                None,
            )
            seen["action_found"] = act is not None
            if act is not None:
                gc = menu.mapToGlobal(menu.actionGeometry(act).center())
                dpr = menu.devicePixelRatioF()
                mx, my = round(gc.x() * dpr), round(gc.y() * dpr)
                at(mx, my, LDOWN)
                at(mx, my, LUP)
        loop.quit()

    def watchdog() -> None:
        if isinstance(QApplication.activePopupWidget(), QMenu):
            key_input(VK_ESCAPE)
        loop.quit()

    QTimer.singleShot(300, right_click)
    QTimer.singleShot(1000, click_item)
    QTimer.singleShot(1600, watchdog)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()

    assert seen.get("popup") == "QMenu", (
        f"実右クリックでコンテキストメニューが出ない: {seen}"
    )
    assert seen.get("action_found"), (
        f"メニューに {S.ACTION_ADD_TO_ACTIVE_PANEL!r} が無い: {seen}"
    )
```

既存テスト `test_lazy_load_keeps_unplotted_unmaterialized`（`:160-248`）の本体を、
`_build_window` 利用・列単位の規模 assert・`_real_select_and_menu_add` の index 化へ
書き換える（差し替える箇所のみ・以下がテスト関数の全文）。

```python
def test_lazy_load_keeps_unplotted_unmaterialized(qtbot: QtBot, tmp_path: Path) -> None:
    """実 mf4 ロード → 1 本実プロット → 未プロットは全数未展開 (実 OS 入力・prod スケール)。"""
    skip_unless_real_display()
    if not _PROD_MF4.exists():
        pytest.skip(f"prod スケール mf4 が無い: {_PROD_MF4}")

    window = _build_window(qtbot)

    # ── 実ロード経路 (LoadController off-thread + busy overlay) を駆動 ──
    window._load_file(_PROD_MF4)
    qtbot.waitUntil(
        lambda: bool(window.app_vm.loaded_file_keys), timeout=_LOAD_TIMEOUT_MS
    )
    loaded_key = window.app_vm.loaded_file_keys[0]
    session = window.app_vm.session
    mgr = session._groups  # C-e: Session には出さない introspection
    group_sigs = session.group_signals(loaded_key)
    n_physical = len(group_sigs)
    n_columns = session.total_column_count(loaded_key)
    # 反転後 group_signals() は **物理チャンネル** — 規模の主張は列数側でも張る
    # (物理 4,324 だけを見て「prod スケール」と言うと桁を 60 倍取り違える)。
    assert n_physical > 1000 and n_columns > 100_000, (
        f"prod スケールで無い (物理 {n_physical:,} / 列 {n_columns:,})"
    )
    _shot(tmp_path, "01_loaded")

    # (b) open = メタ+master のみ: プロット前は全信号が未展開。
    materialized_before = _count_materialized(session, loaded_key)
    assert materialized_before == [], (
        f"開いた直後に値が展開されている (open が eager の疑い): "
        f"{materialized_before[:5]} ... 計 {len(materialized_before)}"
    )
    assert mgr.mint_count == 0, (
        f"開いた直後に列が鋳造されている (open が列を触っている): {mgr.mint_count}"
    )

    # ── チャンネルツリーが reset を終えるのを待つ ──
    model = window.channel_browser_view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=_LOAD_TIMEOUT_MS)
    _pump_n(6)
    leaf_row = _first_scalar_leaf_row(model)
    plotted_key = model.signal_key_at(model.index(leaf_row, 0))
    assert plotted_key is not None

    # ── 実クリックで行選択 → 実右クリックメニュー「追加」を実クリック ──
    vm = window.graph_area_vm
    _real_select_and_menu_add(window, model.index(leaf_row, 0))

    panel = _panel_widget(window, 0, 0)  # 既定 1 パネル (active) へ着地
    panel_vm = vm.panels(0)[0]
    qtbot.waitUntil(lambda: plotted_key in panel_vm.plotted_signal_keys(), timeout=5000)
    _pump_n(4)
    shot = _shot(tmp_path, "02_one_plotted")

    # (a) プロットした信号が実際に描画される (RenderCurve が非空)。
    assert plotted_key in panel.signal_keys_drawn(), (
        f"プロットした信号がパネルに実描画されない: {plotted_key!r}。{shot}"
    )
    entry_id = panel.entry_id_for(plotted_key)
    xs, _ys = panel.curve_xy(entry_id)
    assert xs is not None and len(xs) > 0, (
        f"描画カーブが空 (値が読まれていない疑い): {plotted_key!r}。{shot}"
    )

    # (c) プロット後も未プロットは全数未展開 — 展開されたのはプロットした 1 本のみ。
    materialized_after = _count_materialized(session, loaded_key)
    leaked = [name for name in materialized_after if name != plotted_key]
    assert leaked == [], (
        f"未プロット信号が展開された (遅延が実 GUI を貫通していない): "
        f"{leaked[:5]} ... 計 {len(leaked)} 展開 (plotted={plotted_key!r})。{shot}"
    )
    # プロットした信号は展開済み = レンダが実際に値を読んだ (no-op pass を排除)。
    assert plotted_key in materialized_after, (
        f"プロットした信号が展開されていない (レンダが値を読んでいない疑い): "
        f"{plotted_key!r}。{shot}"
    )
    # スカラー葉は物理チャンネルそのもの = 鋳造経路を **通らない**。この経路が
    # 鋳造していたら、それは解決器が物理キーを副テーブルへ横流ししている印。
    assert mgr.mint_count == 0, (
        f"スカラー葉のプロットで列が鋳造された: {mgr.mint_count} "
        f"(keys={sorted(mgr.resolved_keys(loaded_key))[:5]})"
    )
```

ファイル末尾に新テストを追加する。

```python
def test_expanding_parent_and_plotting_one_column_mints_only_that_column(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """親を実展開 → 列を実プロット → **その列だけ**が鋳造される (E-3 ①ゲート)。

    E-3 反転後、「未展開」オラクル (上のテスト) は列 Signal が存在しないため
    自明に真になりうる。鋳造は非鋳造 introspection でしか観測できない
    (``mint_count`` / ``resolved_keys()`` — どちらも列を作らない)。ここで固定するのは:

      1. open は列を 1 本も鋳造しない、
      2. **ツリーの展開も鋳造しない** (展開が鋳造するなら prod 4,324 行の一括展開が
         264k 鋳造の一撃になる — C-b が塞いだ footgun そのもの)、
      3. 列を 1 本プロットすると **その列だけ** が鋳造され実描画される、
      4. 2-D 親 Signal の値は読まれない (親を実体化すると sorted_view() の
         astype(float64) が 8 倍膨張した恒久キャッシュになる)。

    demo_data には依存しない (gitignore・非コミット) — 合成 fixture で 3 列の
    配列チャンネル ``Mat`` と構造化チャンネル ``Pos`` を作る。
    """
    skip_unless_real_display()

    path = write_mdf4_flatten_fixture(tmp_path)
    window = _build_window(qtbot)
    window._load_file(path)
    qtbot.waitUntil(
        lambda: bool(window.app_vm.loaded_file_keys), timeout=_LOAD_TIMEOUT_MS
    )
    loaded_key = window.app_vm.loaded_file_keys[0]
    session = window.app_vm.session
    mgr = session._groups  # C-e: Session には公開しない (realgui は直接触る先例あり)

    view = window.channel_browser_view
    tree, model = view.tree, view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=_LOAD_TIMEOUT_MS)
    _pump_n(4)
    _shot(tmp_path, "10_loaded_flat")

    # (1) open は鋳造しない。
    assert mgr.mint_count == 0, f"ロードだけで列が鋳造された: {mgr.mint_count}"
    assert mgr.resolved_keys(loaded_key) == frozenset(), (
        f"ロード直後に副テーブルが空でない: {sorted(mgr.resolved_keys(loaded_key))}"
    )

    # (2) 親 (Mat = 3 列) を実クリックで展開 — 列名だけで賄われ鋳造しない。
    mat_idx = model.index(_row_of(model, "Mat"), 0)
    assert not model.has_materialized_children(mat_idx), (
        "展開前に子が合成されている (葉の事前保持へ回帰)"
    )
    _click_expand_arrow(tree, mat_idx)
    assert tree.isExpanded(mat_idx), (
        f"展開アフォーダンスの実クリックで展開されない。{_shot(tmp_path, '11_expand_fail')}"
    )
    assert _child_names(model, mat_idx) == ["Mat[0]", "Mat[1]", "Mat[2]"], (
        f"展開しても列が現れない: {_child_names(model, mat_idx)}"
    )
    first_child = model.index(0, 0, mat_idx)
    assert tree.visualRect(first_child).height() > 0, (
        "子行がモデルにはあるが画面に出ていない (展開が view に届いていない)"
    )
    assert mgr.mint_count == 0, (
        f"ツリーの展開が列 Signal を鋳造している (C-b 違反): "
        f"mint_count={mgr.mint_count} keys={sorted(mgr.resolved_keys(loaded_key))}"
    )
    _shot(tmp_path, "12_expanded")

    # (3) 2 番目の列を実選択 → 実右クリック → 「アクティブパネルに追加」を実クリック。
    #     先頭 (Mat[0]) を避けるのは、LD-08 dedup の `Mat[0]` 衝突規則と紛れないため。
    child = model.index(1, 0, mat_idx)
    child_key = model.signal_key_at(child)
    assert child_key is not None and child_key.endswith("::Mat[1]"), (
        f"子行の葉キーが列の実キーでない: {child_key!r}"
    )
    _real_select_and_menu_add(window, child)

    panel_vm = window.graph_area_vm.panels(0)[0]
    qtbot.waitUntil(lambda: child_key in panel_vm.plotted_signal_keys(), timeout=5000)
    _pump_n(4)
    shot = _shot(tmp_path, "13_column_plotted")

    panel = _panel_widget(window, 0, 0)
    assert child_key in panel.signal_keys_drawn(), (
        f"列を選んで追加したのに実描画されない: {child_key!r}。{shot}"
    )
    xs, _ys = panel.curve_xy(panel.entry_id_for(child_key))
    assert xs is not None and len(xs) > 0, (
        f"描画カーブが空 (鋳造列の値が読まれていない): {child_key!r}。{shot}"
    )

    # その列 **だけ** が鋳造された。
    assert mgr.resolved_keys(loaded_key) == frozenset({child_key}), (
        f"プロットした列以外も鋳造された: "
        f"{sorted(mgr.resolved_keys(loaded_key))} (plotted={child_key!r})。{shot}"
    )
    assert mgr.mint_count == 1, (
        f"鋳造回数が 1 でない (同一キーの再鋳造 = 副テーブルのキャッシュが効いて"
        f"いない疑い): {mgr.mint_count}。{shot}"
    )

    # 恒真化対策: 展開済み走査が **鋳造列を含む** こと自体を固定する。
    # group_signals() だけを歩くと鋳造列は列挙外なので、いくら鋳造しても
    # 「leak ゼロ」が通ってしまう (このファイルの ①ゲートが無力化する)。
    assert _count_materialized(session, loaded_key) == [child_key], (
        f"展開済み走査が鋳造列を見ていない / 余計な信号が展開された: "
        f"{_count_materialized(session, loaded_key)}。{shot}"
    )

    # (4) 2-D 親の値は読まれていない (読むと float64 8 倍膨張の恒久キャッシュ)。
    parent = session.resolve_signal(f"{loaded_key}::Mat")
    assert parent is not None, "物理チャンネル Mat が解決できない"
    assert not parent._values_source.is_materialized, (
        f"2-D 親 Signal の値が展開された (列の読みが親経由になっている疑い)。{shot}"
    )
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest --realgui "tests/realgui/test_lazy_load_realclick.py::test_expanding_parent_and_plotting_one_column_mints_only_that_column" -q`

Expected: FAIL with `TypeError: _count_materialized() takes 1 positional argument but 2 were given`
（`_count_materialized(session, loaded_key)` の行。ヘルパはまだ `group_sigs` 1 引数で、
**鋳造列を一切見ない** — この盲目さ自体が恒真化の正体で、Step 5 の sabotage が
「2 引数化しても中身を戻すと `[] == ['mf4_1::Mat[1]']` で RED」として実証する）

計測器側の RED（`demo_data/prod_demo.mf4` がある環境でのみ・CI 非対象）。
T8 が `_expansion_confirmer` への代入行を既に落としているので、**`AttributeError` は出ない**
（この 2 つが T8 の後に実際に到達する失敗）:

Run: `uv run --with psutil python scripts/measure_lazy_footprint.py`
Expected: FAIL with `KeyError: None` — `materialize_leaves` の
`table[None if src._selector is None else src._selector[-1]]`。反転後は **物理 Signal の
`_selector` が全て None** なので、2-D チャンネルに対してスカラー分岐のキーを引きにいく。

Run: `VALISYNC_PROD_MF4=demo_data/prod_demo.mf4 QT_QPA_PLATFORM=windows uv run python scripts/fu16_teardown_bench.py`
Expected: FAIL with `SystemExit: reached 4324 ch (expected 330004 -- expand-all 未達。…)`
（`EXPECTED_CHANNELS` は単一軸のまま＝T8 は数値の再ベースをしない。`session.signals()` が
物理チャンネルのみを返すようになったので、下の (3-4) で物理／列の 2 軸へ再ベースする）

- [ ] **Step 3: 実装**

**(3-1) `tests/realgui/test_lazy_load_realclick.py`** — `_count_materialized` を
「物理チャンネル＋鋳造列」の走査へ変える。

```python
def _count_materialized(session, key: str) -> list[str]:  # type: ignore[no-untyped-def]
    """値が展開済みの Signal 名 (**物理チャンネル + 鋳造列**)。

    反転後、鋳造した列 Signal は ``SignalGroup.signals`` の外 —
    ``SignalGroupManager._resolved_by_key`` の副テーブル — に居るので、
    ``group_signals()`` だけを走査すると鋳造列の展開が丸ごと会計から落ちる
    (「何列鋳造して読んでも leak ゼロ」が通る恒真テストになる)。

    副テーブルの列挙は ``resolved_keys()`` (鋳造を誘発しない introspection) で行い、
    実体は ``resolve()`` で取る — 既に鋳造済みのキーなのでキャッシュヒットであり、
    観測が新たな鋳造を作らない (観測が対象を変えない)。
    """
    mgr = session._groups
    names = [s.name for s in session.group_signals(key) if s._values_source.is_materialized]
    for col_key in sorted(mgr.resolved_keys(key)):
        col = mgr.resolve(col_key)
        if col is not None and col._values_source.is_materialized:
            names.append(col.name)
    return names
```

**(3-2) `tests/realgui/test_channel_tree_flatten_realclick.py`** — 変更なし。
退役した `_expansion_confirmer` patch の除去は **T8 で完了済み**（T8 の Files
「`_expansion_confirmer` への実行時アクセス除去・4 サイト」）。ここで二重に触らない
— Step 4 の無回帰実行だけを行う。

**(3-3) `scripts/measure_lazy_footprint.py`** — USS 追加・列モデルへの再ベース・
列読みレイテンシ計測の追加。

`rss_mb()`（`:53-54`）の直後に USS を追加する。

```python
def uss_mb() -> float:
    """Unique Set Size (このプロセス固有の物理メモリ) = **E-3 の主指標**。

    RSS は mmap 済みの共有ページ (asammdf が開いたファイルのページキャッシュ) を
    含むので、遅延化の勝ち負けを RSS だけで読むと mmap フロア (~205 MiB) に埋もれる。
    memory_full_info() は working set を歩くぶん高価 — 20ms 周期の peak サンプラーでは
    使わず、settle 済みの計測点でだけ読む。
    """
    return PROC.memory_full_info().uss / MB
```

`LoadResult`（`:76-83`）と `load_one_more`（`:93-130`）を差し替える。

```python
@dataclass
class LoadResult:
    n_files: int
    peak_mb: float
    steady_mb: float
    steady_uss_mb: float
    load_wall_s: float
    physical: int
    columns: int
```

```python
def load_one_more(app: object, win: object, expect_files: int) -> LoadResult:
    """Load prod_demo once more into *win*; sample peak/steady for that state.

    Waits until ``loaded_file_keys`` reaches *expect_files* (the off-thread
    load has completed and been registered on the GUI thread), lets the model
    reset / paint settle, then reads the settled RSS/USS after a gc.
    """
    sampler = PeakSampler()
    sampler.start()
    t0 = time.perf_counter()
    win._load_file(TARGET)  # type: ignore[attr-defined]

    deadline = t0 + LOAD_TIMEOUT_S
    while (
        len(win.app_vm.loaded_file_keys) < expect_files  # type: ignore[attr-defined]
        and time.perf_counter() < deadline
    ):
        app.processEvents()  # type: ignore[attr-defined]
        time.sleep(0.03)
    load_wall = time.perf_counter() - t0

    _pump(app, SETTLE_S)  # settle model reset / paint before reading steady
    sampler.stop()
    sampler.join(timeout=1.0)

    gc.collect()
    steady = rss_mb()
    steady_uss = uss_mb()
    keys = win.app_vm.loaded_file_keys  # type: ignore[attr-defined]
    session = win.app_vm.session  # type: ignore[attr-defined]
    # 反転後 group_signals() は物理チャンネルのみ。列数は総数 API で別に取る
    # (この 2 つが 1 桁以上ずれるのが E-3 の勝ちそのもの)。
    physical = len(session.group_signals(keys[-1])) if keys else 0
    columns = session.total_column_count(keys[-1]) if keys else 0
    return LoadResult(
        n_files=expect_files,
        peak_mb=sampler.peak,
        steady_mb=steady,
        steady_uss_mb=steady_uss,
        load_wall_s=load_wall,
        physical=physical,
        columns=columns,
    )
```

`browser_residue`（`:159-265`）の直前に、鋳造しない列キー生成ヘルパ群を追加する。

```python
def _orig(ns_name: str) -> str:
    """``mf4_1::Prod10_0000`` -> ``Prod10_0000`` (namespaced 名 → 表示名)。"""
    from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR

    return ns_name.split(KEY_SEPARATOR, 1)[1] if KEY_SEPARATOR in ns_name else ns_name


def _column_keys_of(session: object, key: str, display: str) -> list[str]:
    """物理チャンネル *display* の列キー (**名前だけで作る = 鋳造しない**)。

    ExportCsvDialog の「すべて選択」(C-b) と同じ規約: 列の列挙は ColumnSpec 由来の
    名前で行い、``resolve()`` は実際に値が要るときまで呼ばない。ここで鋳造すると
    計測器自身が測ろうとしている 264k オブジェクトを再導入する。
    """
    from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR

    return [
        f"{key}{KEY_SEPARATOR}{col}"
        for col in session.column_names_of(key, display)  # type: ignore[attr-defined]
    ]


def _materialized_names(session: object, key: str) -> list[str]:
    """値が展開済みの Signal 名 (**物理チャンネル + 鋳造列**)。

    鋳造列は ``SignalGroup.signals`` の外 (``_resolved_by_key``) に居るので、
    ``group_signals()`` だけを走査すると「8,000 列を展開したのに materialized=0」と
    いう静かに嘘の会計になる。副テーブルの列挙は ``resolved_keys()`` (非鋳造)、
    実体取得は ``resolve()`` (鋳造済みキーなのでキャッシュヒット)。
    """
    mgr = session._groups  # type: ignore[attr-defined]
    names = [
        s.name
        for s in session.group_signals(key)  # type: ignore[attr-defined]
        if s._values_source.is_materialized
    ]
    for col_key in mgr.resolved_keys(key):
        col = mgr.resolve(col_key)
        if col is not None and col._values_source.is_materialized:
            names.append(col.name)
    return names
```

`browser_residue` 本体（`:189-265` の計測〜print 部）を差し替える。

```python
    session = win.app_vm.session  # type: ignore[attr-defined]

    gc.collect()
    s1 = rss_mb()

    smap = session.signal_map()
    n_physical_keys = len(smap)  # enumeration is physical-keys-only by contract
    gc.collect()
    s2 = rss_mb()

    group_sigs = session.group_signals(key)
    n_physical = len(group_sigs)
    # 反転後は列 Signal が存在しない — 列数は ColumnSpec 由来の総数 API から取る
    # (len(group_sigs) を「列数」と読むと 61 倍の取り違えになる)。
    n_columns = session.total_column_count(key)
    gc.collect()
    s3 = rss_mb()

    vm = ChannelBrowserVM(win.app_vm)  # type: ignore[attr-defined]
    rows = vm.tree_groups()
    n_rows = len(rows)
    n_prep_columns = sum(row[3] for row in rows)
    gc.collect()
    s4a = rss_mb()

    model = SignalTreeModel(vm)  # eager top level only; children stay lazy
    n_top = model.rowCount()
    gc.collect()
    s4 = rss_mb()

    scans_before = vm.inspect()["filter_scans"]
    t0 = time.perf_counter()
    # set_filter notifies -> the model above rebuilds (tree_groups); the three
    # explicit calls are the other production consumers of the same notify
    # (header_text/empty_state both go through shown_count).
    vm.set_filter(BROWSER_FILTER_QUERY)
    shown = vm.shown_count()
    filtered_rows = len(vm.tree_groups())
    header = vm.header_text()
    filter_wall_ms = (time.perf_counter() - t0) * 1000.0
    scans = vm.inspect()["filter_scans"] - scans_before
    gc.collect()
    s5 = rss_mb()

    vm.set_filter("")
    vm.tree_groups()
    vm.shown_count()
    vm.header_text()
    gc.collect()
    s6 = rss_mb()

    # ブラウザの列数はローダーの列総数と一致していなければならない。ずれたら
    # ヘッダーの「N ch 中 M ch を表示」が静かに嘘になっている (U2 の単位契約)。
    assert n_prep_columns == n_columns, (n_prep_columns, n_columns)
    # ブラウザ行 = 物理チャンネル = group_signals の要素数 (反転後は 1:1)。
    assert n_rows == n_physical == n_top, (n_rows, n_physical, n_top)

    print("\n=== CHANNEL BROWSER residue (fresh VM+model over loaded session) ===")
    print(
        f"  columns={n_columns:,}  physical channels={n_physical:,}  "
        f"rows={n_rows:,}  model top rows={n_top:,}"
    )
    print(f"  signal_map keys (physical only)={n_physical_keys:,}")
    print(f"  1 loaded (settled)          = {s1:,.0f} MB")
    print(f"  2 + signal_map()            = {s2:,.0f} MB   (+{s2 - s1:,.1f} MB)")
    print(f"  3 + group_signals() [phys]  = {s3:,.0f} MB   (+{s3 - s2:,.1f} MB)")
    print(f"  4a+ VM prep/tree_groups()   = {s4a:,.0f} MB   (+{s4a - s3:,.1f} MB)")
    print(f"  4 + SignalTreeModel         = {s4:,.0f} MB   (+{s4 - s4a:,.1f} MB)")
    print(
        f"  5 + filter {BROWSER_FILTER_QUERY!r} x3 consumers = {s5:,.0f} MB   (+{s5 - s4:,.1f} MB)"
    )
    print(f"  6 + filter cleared          = {s6:,.0f} MB   (+{s6 - s5:,.1f} MB)")
    print(f"  BROWSER PREP RESIDUE  (stage 4 - stage 3) = {s4 - s3:,.1f} MB")
    print("    (pre-E-2 measured: _prep 68 MB + _Node.leaves 19 MB = ~87 MB)")
    print(f"  FILTER MECHANISM COST (stage 5 - stage 4) = {s5 - s4:,.1f} MB")
    print("    (target ~0 MB: no per-column lowercased name cache is kept)")
    print(f"  ONE FILTER APPLICATION wall = {filter_wall_ms:,.1f} ms  (scans={scans})")
    print("    (pre-E-2 measured 170-213 ms; scans==1 means the memo collapsed")
    print("     the 3 consumers of one notify into a single column-name pass)")
    print(f"  filter result: shown={shown:,} columns / rows={filtered_rows:,}")
    print(f"  header: {header}")

    del model, vm, rows, group_sigs, smap
    gc.collect()
    print(f"  released (browser objects dropped) = {rss_mb():,.0f} MB", flush=True)
```

`DrainResult`（`:268-280`）の `signals` を 2 軸へ割る。

```python
@dataclass
class DrainResult:
    label: str
    physical: int
    minted: int
    materialized: int
    sync_close_ms: float
    ticks: int
    max_tick_ms: float
    mean_tick_ms: float
    total_drain_s: float
    # (index, ms, signals, bytes, gc passes)
    top_ticks: tuple[tuple[int, float, int, int, int], ...]
```

`materialize_leaves`（`:364-449`）を鋳造経路へ書き換える。

```python
def materialize_leaves(win: object, key: str, target: int) -> int:
    """>= *target* 列を「プロット済み + 範囲統計」状態にし、その列数を返す。

    反転後 (E-3) は列 Signal がロード時に存在しないので、まず production の解決器
    (``Session.resolve_signal``) で列を **鋳造** してから値を入れる。列キーは
    ColumnSpec の名前だけから作る (``_column_keys_of``) — 列挙のために鋳造しない。

    WHY not one ``sig.values`` per leaf (the literal production route): prod_demo's
    array channels carry 1,000+ leaves each and ``LazyMdfValues.array()`` re-selects
    (and re-decompresses) the WHOLE channel per leaf -- measured 383 ms per leaf,
    i.e. ~51 minutes for 8,000. Here each physical channel is selected ONCE and its
    leaves are built from that one read through the same ``_flatten``/``_freeze``
    production helpers, so every retained array is byte-identical to the lazy route
    (asserted below on BOTH branches -- scalar and LD-14 leaf -- against arrays
    materialized through the real ``sig.values``). ``range_stat_index()`` is then
    called through the production API, which also builds
    ``sorted_view``/``finite_view`` -- exactly the state a plotted signal with range
    statistics holds, which is the regime this input exists to measure.
    """
    import numpy as np

    session = win.app_vm.session  # type: ignore[attr-defined]
    physical = session.group_signals(key)
    handle = physical[0]._values_source._handle

    # 等価性の対照実験用の候補を 2 分岐ぶんだけ先に拾う (全チャンネルぶんの列キーを
    # 事前生成すると 330k 文字列を計測中ずっと抱えることになる)。
    single_col: str | None = None
    multi_col: str | None = None
    for sig in physical:
        cols = _column_keys_of(session, key, _orig(sig.name))
        if single_col is None and len(cols) == 1:
            single_col = cols[0]
        if multi_col is None and len(cols) > 1:
            multi_col = cols[0]
        if single_col is not None and multi_col is not None:
            break

    # Equivalence control: one signal per branch goes through the REAL lazy read
    # and the bulk route must reproduce that array exactly. Without it the fast
    # route could silently retain a differently shaped/typed array and the drain
    # numbers would describe a state the app never reaches.
    for col_key in (single_col, multi_col):
        if col_key is None:
            continue
        probe = session.resolve_signal(col_key)  # production の鋳造経路
        assert probe is not None, f"列キーが解決できない: {col_key}"
        src = probe._values_source
        branch = "scalar" if src._selector is None else "ld14-leaf"
        prod_arr = probe.values  # production LazyMdfValues.array()
        table = _bulk_columns(
            src._name, _select_samples(handle, src._name, src._gi, src._ci)
        )
        bulk_arr = table[None if src._selector is None else src._selector[-1]]
        assert prod_arr.dtype == bulk_arr.dtype, (prod_arr.dtype, bulk_arr.dtype)
        assert prod_arr.shape == bulk_arr.shape, (prod_arr.shape, bulk_arr.shape)
        assert prod_arr.flags.writeable == bulk_arr.flags.writeable is False
        assert prod_arr.flags.c_contiguous and bulk_arr.flags.c_contiguous
        assert np.array_equal(prod_arr, bulk_arr)
        # 測定の意味を決めるのはここ: dtype/shape/内容が一致していても、bulk 側の
        # リーフが 1 つの base 配列をエイリアスしていたら「解放」が桁違いに安くなり、
        # ティック時間を無言で低く見せる (上の 4 つはその失敗モードに盲目)。
        # production は _flatten の ascontiguousarray + _freeze でリーフごとに
        # 独立バッファを持つので、bulk 側にも同じ所有権を要求する。
        assert prod_arr.flags.owndata and bulk_arr.flags.owndata, (
            "リーフが base をエイリアスしている — 解放コストが production と違う"
        )
        print(
            f"  EQUIVALENCE ok [{branch}]: bulk route reproduces the lazy array "
            f"({prod_arr.dtype}, {prod_arr.shape}, {prod_arr.nbytes / 1024:,.0f} KiB)"
        )
        del table, bulk_arr, prod_arr

    done = 0
    t0 = time.perf_counter()
    for sig in physical:
        if done >= target:
            break
        psrc = sig._values_source
        col_keys = _column_keys_of(session, key, _orig(sig.name))
        table = _bulk_columns(
            psrc._name, _select_samples(handle, psrc._name, psrc._gi, psrc._ci)
        )
        for col_key in col_keys:
            col = session.resolve_signal(col_key)
            if col is None:
                continue
            src = col._values_source
            if src._cache is None:
                src._cache = table[None if src._selector is None else src._selector[-1]]
            col.range_stat_index()  # production API: sorted_view + finite_view + RSI
            done += 1
        del table, col_keys
    wall = time.perf_counter() - t0

    materialized = len(_materialized_names(session, key))
    print(
        f"  materialized {materialized:,} / {session.total_column_count(key):,} columns "
        f"(minted {len(session._groups.resolved_keys(key)):,}) "
        f"(+range_stat_index) in {wall:,.1f}s"
    )
    # 参照は関数の return で全て落ちるが、下の集計と gc を正しい状態で行うため
    # 明示的に落とす (ドレインは唯一の参照者でなければならない)。
    del physical
    gc.collect()
    return materialized
```

`drain_after_unload`（`:452-493` 冒頭部）の会計を 2 軸へ。

```python
    session = win.app_vm.session  # type: ignore[attr-defined]
    mgr = session._groups
    # リストを名前に束縛しない: 束縛すると全 Signal を掴んだままになり、ドレインが
    # 何も解放できない (ティックが不当に速く見える)。
    n_physical = len(session.group_signals(key))
    n_minted = len(mgr.resolved_keys(key))
    materialized = len(_materialized_names(session, key))
    gc.collect()
```

`return DrainResult(...)` の該当フィールドを差し替える。

```python
    return DrainResult(
        label=label,
        physical=n_physical,
        minted=n_minted,
        materialized=materialized,
        sync_close_ms=sync_close * 1000.0,
        ticks=len(ticks),
        max_tick_ms=max(durations) * 1000.0 if durations else 0.0,
        mean_tick_ms=(sum(durations) / len(durations)) * 1000.0 if durations else 0.0,
        total_drain_s=total,
        top_ticks=tuple((i, s * 1000.0, n, b, g) for i, (s, n, b, g) in top),
    )
```

`report_drain`（`:516`）の 1 行を差し替え、regime 注記を足す。

```python
        print(
            f"  physical={r.physical:,}  minted columns={r.minted:,}  "
            f"materialized at unload={r.materialized:,}"
        )
```

同関数末尾の NOTE 群の先頭に 1 行追加する。

```python
    print(
        "  NOTE: E-3 反転後、(a) は 264k の未展開シェルではなく **4.3k の物理チャンネル**\n"
        "        ぶんしか無い (シェル 1 本 1.6us regime の母数が 61 分の 1)。ペーシングの\n"
        "        証拠は (b) — 鋳造列 + range stats — 側でしか取れない。"
    )
```

`report_drain` の直後に列読みレイテンシ計測を追加する。

```python
LATENCY_COLUMNS = 5


def column_read_latency(win: object, key: str) -> None:
    """同一チャンネルの 5 列を production 経路で読み、対話コストを実測する。

    E-4 (チャンネル単位デコード済みキャッシュ + 位置ベース selector) の要否を
    判断するための数値。E-3 は「オブジェクト数」を削るが **読み方は変えない**:
    ``LazyMdfValues.array()`` は列ごとに全チャンネル select + 全リーフ flatten を
    やり直す (sample_source.py)。したがって想定は「メモリは勝ち・対話レイテンシは
    据え置き (鋳造ぶん微増)」であり、その据え置きの実測値そのものを残す。

    未鋳造の列だけを測る — 既に触れた列はキャッシュヒットで 0 ms になり測定が
    無意味になる。
    """
    session = win.app_vm.session  # type: ignore[attr-defined]
    mgr = session._groups
    # 最も列数の多い物理チャンネル (1024 ガード退役で初めて開ける広幅チャンネル)。
    # 探索は **列数だけ** を見て、名前空間つき列キーの生成は勝者 1 本に限る —
    # 全チャンネルぶんのキーを作ると prod 330k 本の文字列を計測中ずっと抱えることに
    # なり、計測器自身がこの増分で剥がしたコストを再導入する。鋳造は 1 本もしない。
    widest_n, widest_display = 0, ""
    for sig in session.group_signals(key):
        display = _orig(sig.name)
        n = len(session.column_names_of(key, display))  # type: ignore[attr-defined]
        if n > widest_n:
            widest_n, widest_display = n, display
    assert widest_display, "ロード済みグループに列が無い"
    widest_keys = _column_keys_of(session, key, widest_display)
    already = mgr.resolved_keys(key)
    fresh = [k for k in widest_keys if k not in already][:LATENCY_COLUMNS]

    mint_before = mgr.mint_count
    per_column: list[float] = []
    for col_key in fresh:
        t0 = time.perf_counter()
        col = session.resolve_signal(col_key)  # 鋳造 (production 経路)
        assert col is not None, f"列キーが解決できない: {col_key}"
        arr = col.values  # 実読み: select -> _flatten -> _freeze
        per_column.append((time.perf_counter() - t0) * 1000.0)
        assert len(arr) > 0

    print("\n=== COLUMN READ latency (E-4 の要否判断のための実測) ===")
    print(f"  channel={widest_display}  columns in channel={widest_n:,}")
    print(f"  minted here = {mgr.mint_count - mint_before} columns")
    for i, ms in enumerate(per_column):
        print(f"    column #{i}  {ms:,.0f} ms")
    print(f"  TOTAL {len(per_column)} columns = {sum(per_column):,.0f} ms")
    print(
        "  reference (spec §列読みコスト): 333-386 ms/列・5 列 2,105 ms。\n"
        "  E-4 (チャンネル単位デコード済みキャッシュ + 位置ベース selector) の目標は\n"
        "  5 列 448 ms。E-3 は読み方を変えないので据え置き = E-4 は依然必要、が想定。",
        flush=True,
    )
```

`main`（`:558-663`）を差し替える（確認モーダル patch の除去・USS 出力・レイテンシ計測の配線）。

```python
def main() -> None:
    # QSettings isolation (never touch the real registry) — must happen before
    # build_main_window reads any setting.
    from valisync.gui.views import main_window as mw

    mw._ORG = "ValiSync-Measure"
    mw._APP = "ValiSync-Measure"

    from PySide6.QtWidgets import QApplication

    from valisync.gui.app import build_main_window

    if not TARGET.exists():
        print(f"MISSING: {TARGET} (run scripts/generate_demo_mf4.py --profile hils)")
        raise SystemExit(1)

    # 増分B: ティック計測はサービス構築より前に仕掛ける (bound method 捕捉のため)。
    tick_log = instrument_teardown_ticks()

    gc.collect()
    base = rss_mb()

    app = QApplication.instance() or QApplication([])
    win = build_main_window()
    win._tick_log = tick_log
    win.resize(1400, 900)
    win.show()
    app.processEvents()
    after_win = rss_mb()
    after_win_uss = uss_mb()

    # E-3: 1024 ガード (展開確認モーダル) は退役済み — 差し替える confirmer は無く、
    # 全チャンネルが無条件にロードされる (そもそも列は展開されない)。

    disk_mb = TARGET.stat().st_size / MB
    print(
        f"baseline={base:,.0f}MB  after window+show={after_win:,.0f}MB "
        f"(USS {after_win_uss:,.0f}MB)  target={TARGET.name} ({disk_mb:,.0f}MB on disk)",
        flush=True,
    )

    r1 = load_one_more(app, win, expect_files=1)
    print(
        f"[1 file ] physical={r1.physical:,} columns={r1.columns:,}  "
        f"load_wall={r1.load_wall_s:.2f}s",
        flush=True,
    )
    # E-2: the browser-side residue, measured on the 1-file state (the objects
    # are dropped again before the 2nd load so the 2-file numbers stay
    # comparable with previous runs).
    browser_residue(win, win.app_vm.loaded_file_keys[0])

    r2 = load_one_more(app, win, expect_files=2)
    print(
        f"[2 files] physical(2nd)={r2.physical:,} columns={r2.columns:,}  "
        f"load_wall={r2.load_wall_s:.2f}s",
        flush=True,
    )

    print("\n=== REAL GUI process memory (prod_demo.mf4, real load path) ===", flush=True)
    print(f"  Qt+window baseline   = {after_win:,.0f} MB (USS {after_win_uss:,.0f} MB)")
    print("  --- 1 file ---", flush=True)
    print(f"  PEAK during load     = {r1.peak_mb:,.0f} MB", flush=True)
    print(f"  steady RSS (settled) = {r1.steady_mb:,.0f} MB", flush=True)
    print(
        f"  steady USS  [主指標] = {r1.steady_uss_mb:,.0f} MB  "
        f"(baseline 比 +{r1.steady_uss_mb - after_win_uss:,.0f} MB)",
        flush=True,
    )
    print(f"  load wall            = {r1.load_wall_s:.2f} s", flush=True)
    print("  --- 2 files (compare) ---", flush=True)
    print(f"  PEAK during 2nd load = {r2.peak_mb:,.0f} MB", flush=True)
    print(f"  steady RSS (settled) = {r2.steady_mb:,.0f} MB", flush=True)
    print(
        f"  steady USS  [主指標] = {r2.steady_uss_mb:,.0f} MB  "
        f"(baseline 比 +{r2.steady_uss_mb - after_win_uss:,.0f} MB)",
        flush=True,
    )
    print(f"  2nd load wall        = {r2.load_wall_s:.2f} s", flush=True)
    print(
        "\n  OLD eager baseline (pre-lazy, 1 file): "
        "steady 1,201 MB / peak 1,369 MB / load 13.1s",
        flush=True,
    )
    print(
        "  pre-E-2 baseline   (1 file): steady   868 MB / peak 1,366 MB / load 13.1s",
        flush=True,
    )
    print(
        "  E-3 target: core 590 -> ~310 MB / objects 264,004 -> 4,324 / "
        "USS +281 MiB -> +15 MiB",
        flush=True,
    )

    keys = list(win.app_vm.loaded_file_keys)

    # E-4 判断材料: 広幅チャンネルの 5 列を production 経路で読む実時間。
    # ドレイン計測より前に置く (ドレインはグループを消すため)。
    column_read_latency(win, keys[0])

    # ── 増分B: unload -> teardown ドレインの最大ティック時間 (2 入力必須) ──
    #
    # (a) だけでは足りない: ロードは値を展開しないので (増分A の遅延契約)、
    # (a) は「全信号が未展開シェル」= 1 信号 1.6us regime しか踏まない。展開済み
    # 信号は 3 倍重く、かつ**バイト予算と信号数予算を両方満たしたまま**デッドラインを
    # 超えうる — 第 3 軸 (経過時間) が存在する理由そのものなので、両方測る。
    drains = [
        drain_after_unload(app, win, keys[1], "(a) loaded only (all columns lazy)")
    ]
    _pump(app, 0.5)

    materialize_leaves(win, keys[0], MATERIALIZE_TARGET)
    drains.append(
        drain_after_unload(
            app,
            win,
            keys[0],
            f"(b) >= {MATERIALIZE_TARGET:,} columns minted+materialized (+range stats)",
        )
    )
    report_drain(drains)

    # Hold the window briefly for on-screen / Task Manager confirmation.
    _pump(app, 3.0)
    win.close()
```

**(3-4) `scripts/fu16_teardown_bench.py`** — 定数を「物理／列」の 2 軸へ再ベースし、
退役した confirmer patch を落とす。`:30` を差し替える。

```python
# E-3 反転後の到達値 (小データ / 部分ロードでの false-green を落とすための固定値)。
# session.signals() は **物理チャンネル** のみを返すようになったので、列数は
# total_column_count() で別途検証する — 物理だけを見ると 61 分の 1 の規模で
# 「到達した」と誤判定し、6 秒フリーズを隠す元の false-green が戻る。
EXPECTED_PHYSICAL = 4_324
EXPECTED_COLUMNS = 330_004
```

`:95-99`（confirmer 差し替え）を削除し、コメントを置き換える。

```python
    # E-3: 1024 ガード (展開確認モーダル) は退役済み — 全チャンネルが無条件に
    # ロードされる。差し替える ExpansionConfirmer はもう存在しない。
```

`:111-123`（settle と到達検証）を差し替える。

```python
    # session が namespaced view を張り終えるまで settle。
    while len(app_vm.session.signals()) == 0:
        app.processEvents()
        time.sleep(0.02)

    key = app_vm.loaded_file_keys[0]
    reached_physical = len(app_vm.session.signals())
    reached_columns = app_vm.session.total_column_count(key)
    if (reached_physical, reached_columns) != (EXPECTED_PHYSICAL, EXPECTED_COLUMNS):
        raise SystemExit(
            f"reached physical={reached_physical} columns={reached_columns} "
            f"(expected {EXPECTED_PHYSICAL}/{EXPECTED_COLUMNS} -- 小データ/部分ロードで"
            "フリーズを隠す false-green のため中止)"
        )
    print(
        f"loaded: physical={reached_physical} columns={reached_columns} "
        f"ws={_working_set_mb():.0f}MB",
        flush=True,
    )
```

`:141`（`key = app_vm.loaded_file_keys[0]`）は上で確定済みなので削除し、`:161` の print を差し替える。

```python
    print(f"reached_physical={reached_physical}")
    print(f"reached_columns={reached_columns}")
```

**(3-5) `scripts/fu16_prune_bench.py:41`** — プロット対象を列キーへ再ベースする。
モジュール先頭の import 群へ `KEY_SEPARATOR` を足す。

```python
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
```

`:41` を差し替える。

```python
    # 反転後 session.signals() は **物理チャンネル** を返す。2-D 親をそのまま
    # add_signal すると sorted_view() の astype(float64) が 8 倍膨張した恒久
    # キャッシュを作る (spec「壊れる消費者」3) ので、必ず列キーを採る。
    # 列キーは ColumnSpec の名前だけから作る = ここでは 1 本も鋳造しない
    # (prune の遅さは「セッション全走査」に支配され、プロット数には支配されない)。
    names: list[str] = []
    for sig in app_vm.session.signals():
        display = sig.name.split(KEY_SEPARATOR, 1)[1]
        for col in app_vm.session.column_names_of(key, display):
            names.append(f"{key}{KEY_SEPARATOR}{col}")
        if len(names) >= SIGNALS_PER_PANEL:
            break
    names = names[:SIGNALS_PER_PANEL]
    assert len(names) == SIGNALS_PER_PANEL, (
        f"プロット対象の列キーが足りない ({len(names)}) — 小データで prune の"
        "コストを過小評価する"
    )
```

- [ ] **Step 4: 通ることを確認**

```
uv run pytest --realgui tests/realgui/test_lazy_load_realclick.py -q
uv run pytest --realgui tests/realgui/test_channel_tree_flatten_realclick.py -q
uv run pytest --realgui tests/realgui/ -q          # フル realgui (無回帰)
uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/
```

計測（`demo_data/prod_demo.mf4` 必須・ローカル実測。**出力全文を保存し PR 本文へ貼る**）:

```
uv run --with psutil python scripts/measure_lazy_footprint.py
VALISYNC_PROD_MF4=demo_data/prod_demo.mf4 QT_QPA_PLATFORM=windows uv run python scripts/fu16_teardown_bench.py
VALISYNC_PROD_MF4=demo_data/prod_demo.mf4 QT_QPA_PLATFORM=offscreen uv run python scripts/fu16_prune_bench.py
```

記録する数値（報告と PR 本文の両方）:

1. **主指標 USS**: `steady USS (baseline 比)` — 目標 `+281 MiB → +15 MiB`。
2. RSS: `steady (settled)` — 目標 `590 MB → ~310 MB`（core 相当）／実 GUI は `868 MB` から。
3. オブジェクト数: `physical` / `columns` — 目標 `264,004 → 4,324`（列は `330,004`）。
4. ロード wall（`13.1s` から短縮しているか）。
5. ブラウザ residue と 1 フィルタ適用の wall（E-2 の値からの無回帰）。あわせて **T5 が
   意図的に受容した ExportCsvDialog 側のフィルタ残コスト**（複数列の行だけが 1 打鍵ごとに
   列名を再生成する — スカラー行は `has_column` で短絡済み）を、この wall と同じ
   「`column_names_of` 1 パスの実時間」として読み替えて報告に残す（両者は同じ経路を
   通り、母数となる行数だけが違う）。
6. ドレイン: `(a)` / `(b)` の `MAX tick`（受理帯 `<= 12 ms`）・`minted columns`・`materialized at unload`。
7. **列読みレイテンシ**: 広幅チャンネル 5 列の per-column ms と TOTAL。E-3 は読み方を
   変えないので `2,105 ms` 前後（据え置き or 鋳造ぶん微増）になるはず。この数値を
   もって **E-4（チャンネル単位デコード済みキャッシュ）の要否**を判断材料として残す。

`EXPECTED_PHYSICAL` / `EXPECTED_COLUMNS` が実測と食い違ったら、**定数を実測値へ更新して
コミットし、旧値と新値の両方を報告に書く**（黙って緩めない — この定数が false-green の
唯一の防波堤）。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

1. **恒真化対策の実証（最重要）**: `_count_materialized`（`tests/realgui/test_lazy_load_realclick.py`）の
   `for col_key in sorted(mgr.resolved_keys(key)):` ループを削除（＝反転前と同じ
   `group_signals()` 走査だけに戻す）→
   `test_expanding_parent_and_plotting_one_column_mints_only_that_column` が
   `assert [] == ['mf4_1::Mat[1]']` で RED。
   **これが「鋳造列は列挙外だから leaked == [] が自明に通る」の直接証明**。
   同じ改変を `scripts/measure_lazy_footprint.py` の `_materialized_names` に入れると
   ドレイン (b) が `materialized at unload=0` を印字する（8,000 列を展開済みなのに 0）。
2. **展開が鋳造しない契約**: `ChannelBrowserVM.column_names_for()` の返却ループで
   各列に `self._app_vm.session.resolve_signal(ns_name)` を呼ぶ（＝列名の代わりに
   Signal を鋳造する）→ 新テストが
   `ツリーの展開が列 Signal を鋳造している (C-b 違反): mint_count=3` で RED。
3. **「その列だけ」の契約**: `SignalGroupManager.resolve()` の
   `table[key] = minted` を消す（毎回鋳造し直す）→ 新テストが `mint_count == 1` で
   RED（値は 2 以上）。副テーブルのキャッシュが効いていないことを掴む。
4. **2-D 親の非展開**: `SignalGroupManager._mint_column` が selector を渡さない
   （`selector=None`）ようにする → 新テストの `Mat[1]` の描画値が親の 2-D 配列に
   なり `curve_xy` / `is_materialized` 側で RED。
5. **false-green ガードの実証**: `VALISYNC_PROD_MF4=demo_data/quick_demo.mf4` で
   `fu16_teardown_bench.py` を走らせる → `SystemExit: reached physical=173 columns=…
   (expected 4324/330004 …)` で停止する（小データがベンチを通り抜けない）。

- [ ] **Step 6: ゲート＋コミット**

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
grep -rn "_expansion_confirmer" scripts/ tests/     # 0 hit であること (T8 で退役済み)
git add tests/realgui/test_lazy_load_realclick.py \
        tests/realgui/test_channel_tree_flatten_realclick.py \
        scripts/measure_lazy_footprint.py \
        scripts/fu16_teardown_bench.py \
        scripts/fu16_prune_bench.py
git commit
```

コミットメッセージ:

```
test(realgui): E-3 の鋳造①ゲート追加＋計測器を反転後の列モデルへ再ベース

反転後は「未展開」オラクルが自明に真になる (列 Signal が存在せず、鋳造列は
group_signals() の列挙外)。非鋳造 introspection (mint_count / resolved_keys) で
「親を実展開しても鋳造 0・列を 1 本実プロットしてその列だけが鋳造される」を
実 OS 入力で固定し、_count_materialized を物理チャンネル + 鋳造列の走査へ広げて
恒真化を閉じた。

計測器: measure_lazy_footprint を USS (主指標) 対応・列数を total_column_count
由来へ・materialize_leaves を解決器経由の鋳造へ・ドレイン会計を副テーブル込みへ。
E-4 の要否判断のための列読みレイテンシ計測 (広幅チャンネル 5 列) を追加。
fu16_teardown_bench は EXPECTED を物理/列の 2 軸へ再ベース (削除しない —
小データ false-green を落とす唯一の防波堤)。fu16_prune_bench は 2-D 親でなく
列キーをプロットするよう是正。1024 ガード退役に伴う ExpansionConfirmer の
差し替えは全経路から除去。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
```

---
