# E-4c: 衝突診断＋AST 構造ガード 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 遅延ロードシリーズ最終増分。残る 3 つの「サイレント破壊の穴」を閉じる — (1) 最長一致で**影に隠れた配列リーフ**を load 時 info 診断にし、到達不能性そのものを常設テストで固定する。(2) `signal_map()` の非対称 Mapping 契約を AST 構造ガードで `src/` 全域に強制する。(3) 鋳造列 LRU の evict 解放を `_resolved_lock` の外へ出す。加えて docs の stale 記述 1 点を正す。

**Architecture:** 最長一致規則は `column_names.owning_candidates`（新設ジェネレータ）に**単一実装**として置き、解決側（`SignalGroupManager._owning_channel`）と検出側（`mdf_loader._shadow_diagnostics` → `column_names.shadowed_leaf`）が同じ walk を通る。検出は `MdfLoader.load()` の末尾で `column_records` が**全グループ分揃ってから** 1 回だけ走り、既存の `LoadResult.diagnostics` → `LoadOutcome` → 診断ドックの plumbing にそのまま乗る。AST ガードは `tests/gui/test_theme_guard.py` と同型（ratchet allowlist ＋陳腐化 assert）で `tests/core/test_signal_map_guard.py` に置く。LRU の解放は `channel_cache._evict_oldest` と同型に「lock 内で外して返す・呼び出し側が lock を出てから捨てる」へ変える。

**Tech Stack:** Python 3.13 / uv / asammdf 8.8.22 / numpy / pytest（PySide6 は本増分の対象外 — GUI 挙動は不変）

## Global Constraints

- 作業ディレクトリ `D:/Programming/projects/valisync`、ブランチ `feature/e4c-collision-diag-ast-guard`（HEAD = spec コミット）。**main へ直接コミットしない**。
- 品質ゲートは **4 本を serial・パイプ無し**で実行し、それぞれ exit 0 を確認する（`| tail` に通すと exit code が隠れる — memory `feedback_gate_pipe_tail_masks_exit`）:

  ```
  uv run pytest
  uv run ruff check
  uv run ruff format --check
  uv run mypy src/
  ```

- **テスト実行は必ず同期・フォアグラウンド**。`run_in_background` は禁止（memory `subagent_background_wait_hang_sync_mandate`: 実装サブエージェントのバックグラウンド待ちハングが 6 回再発している）。
- コメント・文言は日本語。コメントは **WHAT ではなく WHY**。
- **core の診断はインライン日本語 f-string**（`mdf_loader.py:105-107` の展開 info と同型）。gui の `S.` 文言カタログ（`gui/strings.py`）は**使わない** — core は gui を import しない。全角括弧（`（）`）を含む行にだけ `# noqa: RUF001` を付ける。本増分が追加する文言は全角括弧を含まないので **noqa は不要**（`uv run ruff check` で確認済み）。
- **既存テストの期待値を書き換えない**。とくに `tests/core/loaders/test_resolver.py:269-353`（`signal_map()` 非対称 Mapping 契約の下段）と `tests/core/test_session_signal_map.py` は **byte-identical のまま**にする — 上段（AST ガード）と下段（挙動テスト）が独立オラクルであることが二層防御の前提（spec §4.2）。
- **最長一致規則の実装は 1 箇所だけ**（G5）。`owning_candidates` を唯一の walk とし、解決側と検出側がそれを参照する。**`SignalGroupManager.has_column`（`signal_group_manager.py:747-756`）の走査は対象外**（下の「G5 の境界」を参照）。
- `git checkout -- src/...` で sabotage を戻さない（過去に実装者が自分の未コミット作業を消した）。sabotage は編集 → 測定 → **手で元へ戻す**。
- コミットメッセージ末尾に必ず付ける:

  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
  ```

## G5 の境界（最長一致規則の「1 箇所」とは何か）

`src/valisync/core/loaders/` には表示名の最長一致ループが**今日 3 箇所**ある:

| # | 場所 | 役割 | 本増分での扱い |
|---|---|---|---|
| 1 | `signal_group_manager.py:775-794`（`_owning_channel`） | **解決**（鋳造器・`channel_key_of`・見積が共有） | `owning_candidates` へ抽出 |
| 2 | 本増分の検出（新設） | **検出**（衝突診断） | 同上（`shadowed_leaf` が `owning_candidates` を消費） |
| 3 | `signal_group_manager.py:747-756`（`has_column`） | **存在判定**（鋳造しない） | **触らない（意図的）** |

G5 の「1 箇所」は spec §8 の括弧書きどおり **「検出と解決が同一実装を参照」** の意味に限る。`has_column` を畳んではならない理由は `tests/core/loaders/test_column_roundtrip.py:611-616` が明文で記録している:

> `has_column` は代替にならない — 2 つは別実装で連動しない。has_column は表示名キーの記録だけを見る（`raw_base_name` を一切参照しない）のに対し、ここで狙っている変異クラス「生 selector 空間が表示空間へ漏れる」を橋渡しするのは `_mint_column` の raw_base_name 経路。つまり当該変異は resolve を動かしても has_column を動かさない。両方を残して初めて元の歯が保たれる。

`has_column` は**意図的な独立オラクル**であり、共有化はテストの歯を抜く。Task 1 の docstring にこの判断を記録すること。

## 発行地点についての spec 逸脱（実装前に必ず読むこと）

spec §3.4 は「`_load_group` の末尾（`column_records` と `diagnostics` の両方がスコープにある地点）」を指定しているが、**そこでは検出が成立しない**。`column_records` は `load()` が持つ**ファイル全体の累積辞書**を `_load_group` へ渡しているだけで、あるグループの末尾時点では「そこまでに処理したグループ分」しか入っていない（`mdf_loader.py:285` で生成 → `:299-310` で各グループへ引き渡し）。

asammdf の `mdf.append([sig])` は 1 チャンネル = 1 グループなので、衝突する 2 本（配列 `Mat` と実チャンネル `Mat[0]`）は**別グループに居るのが常態**である。`Mat[0]` を先に append した配置ではグループ末尾の走査が親 `Mat` をまだ知らず、**検出が append 順に依存して消える**。

→ 発行は **`load()` の末尾**（グループ走査の try/except 直後・`mdf_loader.py:329` と `:330` の間）で行う。ここは `column_records` が完成しており `diagnostics` もスコープにある唯一の地点。実測コストは prod 4,324 チャンネル × 名前長 ~30 の dict 参照 ≈ 13 万回で無視できる。

## 依存グラフ

```
[T1] 規則の単一実装 + 衝突 info + 到達不能性の負 assert  (G1/G2/G5)
[T2] AST 構造ガード                                      (G3)      ← T1 と独立
[T3] _evict_resolved の lock 外解放                      (G4)      ← T1/T2 と独立
                    ↓
[T4] docs 正誤 + フルゲート                              (G6/G7)
```

T1/T2/T3 は互いに独立（触るファイルが重ならない）。T4 は 3 つが揃ってから。

---

### Task 1: 最長一致判定の単一実装化＋衝突 info 診断＋到達不能性の負 assert（G1/G2/G5）

**Files:**

- Modify: `src/valisync/core/loaders/column_names.py` — 末尾（現行 `_consume` は `:254-285`）に `LeafHit` / `owning_candidates` / `shadowed_leaf` を追加
- Modify: `src/valisync/core/loaders/signal_group_manager.py` — import `:11-18`（`parse_leaf` を外し `owning_candidates` を足す）・`_owning_channel` `:758-794` の走査を差し替え
- Modify: `src/valisync/core/loaders/mdf_loader.py` — import `:4`（`Mapping` 追加）と `:11-16`（`shadowed_leaf` 追加）・`_shadow_diagnostics` を `_expansion_diagnostic`（`:80-114`）の直後に新設・`load()` の `:329`/`:330` の間で呼ぶ
- Modify: `tests/mdf4_helpers.py` — 末尾に fixture 3 本を追加
- Create: `tests/core/loaders/test_shadowed_columns.py`

**Interfaces:**

- Consumes（既存・シグネチャ確認済み）:
  - `column_names.ColumnRecord(raw_base_name: str, group_index: int, channel_index: int, spec: ColumnSpec, path_index: dict[str, ColumnPath])`
  - `column_names.parse_leaf(display_key: str, specs: Mapping[str, ColumnSpec]) -> tuple[str, ColumnSpec] | None`
  - `models.load_result.Diagnostic(level: str, message: str, line_number=None, column_number=None, signal_name: str | None = None, sample_index=None)`
  - `Session.load(file_path: Path, ...) -> LoadOutcome`（`LoadOutcome.key: str` / `LoadOutcome.diagnostics: tuple[Diagnostic, ...]`）
  - `Session.group_signals(key: str) -> list[Signal]` / `Session.column_names_of(key: str, display_name: str) -> tuple[str, ...]` / `Session.resolve_signal(key: str) -> Signal | None` / `Session.total_column_count(key: str) -> int` / `Session.remove_group(key: str)`
  - `SignalGroupManager.column_records(group_key: str) -> Mapping[str, ColumnRecord]`
- Produces（他タスク・将来の呼び出し側が依存してよい形）:
  - `column_names.LeafHit` — `frozen=True, slots=True` dataclass。フィールドは `display: str` / `rest: str` / `record: ColumnRecord`
  - `column_names.owning_candidates(display_key: str, records: Mapping[str, ColumnRecord]) -> Iterator[LeafHit]`
  - `column_names.shadowed_leaf(display_name: str, records: Mapping[str, ColumnRecord]) -> LeafHit | None`
  - `mdf_loader._shadow_diagnostics(column_records: Mapping[str, ColumnRecord], diagnostics: list[Diagnostic]) -> None`
  - `tests.mdf4_helpers.write_mdf4_shadowed_leaf(tmp_path: Path) -> Path` / `write_mdf4_out_of_range_leaf_name(tmp_path: Path) -> Path` / `write_mdf4_multistage_shadow(tmp_path: Path) -> Path`
- 不変（このタスクが壊してはならない契約）:
  - `_owning_channel` の返り値・打ち切り条件は**完全に不変**（`rest == ""` で即 return / `_leaf_path` が None なら次候補へ）
  - `SignalGroupManager.has_column` は**無改変**（上の「G5 の境界」）
  - `Diagnostic.signal_name` は**勝った側**（実チャンネル名）— 診断ドックの「対象」列とダブルクリックジャンプの既存挙動に整合する

---

- [ ] **Step 0: ベースラインを記録する**

```
uv run pytest --collect-only -q
```

→ 末尾行が `2593 tests collected` であること（2026-08-04 実測）。この数を控え、Task 4 で `2603` になることを確認する。

- [ ] **Step 1: 衝突 fixture 3 本を `tests/mdf4_helpers.py` へ追加する**

`tests/mdf4_helpers.py` の末尾（`write_mdf3` の後）へ追記する。作法は `test_column_roundtrip.py::_write_roundtrip_mf4` と同一 — **2-D は uint8 でなければ往復しない**（float64 の 2-D は読み戻しで潰れる。memory `mdf_authoring_2d_and_value2text_traps`）、追加順は契約の一部（配列を先・実チャンネルを後）。

```python
# ─── 影に隠れる列 (E-4c spec §3) ──────────────────────────────────────────────
#
# 「最長一致で実チャンネルが勝ち、配列側のその列が列キーでは指せなくなる」配置。
# **loud-fail (LD-08 の [i] 曖昧化が実チャンネル名と衝突する
# write_mdf4_display_name_collision) とは別レジーム**である: あちらは表示名が
# 完全一致してチャンネルが 1 本まるごと拒否されるが、こちらは表示名がすべて
# 一意で誰も拒否されず、**配列の 1 列だけが静かに到達不能になる**。

_SHADOW_TS = np.array([0.0, 0.1, 0.2, 0.3])
# 列 i の値は [i, i+10, i+20, i+30] (write_mdf4_2d と同じ規則)。
_SHADOW_MAT = np.array(
    [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]], dtype=np.uint8
)


def _shadow_file(tmp_path: Path, name: str, scalar_name: str) -> Path:
    """幅 3 の 2-D ``Mat`` + 1-D ``scalar_name`` + ``Clean`` を書く共有本体。

    ``scalar_name`` を ``Mat[0]`` にすると衝突、``Mat[7]`` にすると範囲外
    (到達不能列が存在しない) — 2 つの fixture の差はその 1 点だけなので、
    「衝突あり/なし」の対照が名前 1 つの差に凝縮される。

    1-D 側は dtype (float64 vs uint8)・unit (deg vs mm)・値をすべて親と別に
    しておく: どちらが勝ったかを取り違えたら必ず露見する。
    """
    mdf = MDF(version="4.10")
    try:
        # 追加順は契約の一部: 配列 ``Mat`` を**先**に置く。実チャンネルが後から
        # 来ても最長一致で勝つ (順序に依存しない) ことが検出側の前提。
        mdf.append(
            [ASignal(samples=_SHADOW_MAT, timestamps=_SHADOW_TS, name="Mat", unit="mm")]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([7.0, 8.0, 9.0, 10.0]),
                    timestamps=_SHADOW_TS,
                    name=scalar_name,
                    unit="deg",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]),
                    timestamps=_SHADOW_TS,
                    name="Clean",
                )
            ]
        )
        path = tmp_path / name
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_shadowed_leaf(tmp_path: Path) -> Path:
    """配列 ``Mat`` (3 列) と実チャンネル ``Mat[0]`` の共存 — 衝突 1 件の RED fixture."""
    return _shadow_file(tmp_path, "shadowed.mf4", "Mat[0]")


def write_mdf4_out_of_range_leaf_name(tmp_path: Path) -> Path:
    """配列 ``Mat`` (3 列) と実チャンネル ``Mat[7]`` — **範囲外なので衝突 0 件**.

    ``Mat[7]`` は字面こそ配列のリーフ名の形だが、幅 3 の配列に第 7 列は無い。
    到達不能になる列が存在しないので診断も出してはならない (spec §3.2)。
    """
    return _shadow_file(tmp_path, "out_of_range.mf4", "Mat[7]")


def write_mdf4_multistage_shadow(tmp_path: Path) -> Path:
    """多段名の衝突 2 件 — 判定が ``parse_leaf`` と同じ walk を使う証拠.

    1. ``W[0][1]``: 同名 ``W`` の 2-D が LD-08 で ``W[0]``/``W[1]`` へ曖昧化された
       うえで、文字どおり ``W[0][1]`` という 1-D 実チャンネルが同居する。親の
       **表示名** (``W[0]``) と **生名** (``W``) が食い違う唯一の腕で、判定が
       ``raw_base_name`` を使わずに表示名で ``parse_leaf`` を引くと解決不能に
       落ちて検出が消える (二重名の契約)。
    2. ``Nest.g[3]``: 構造化フィールド + 配列添字の **2 段**サフィックス。
       ``parse_leaf`` の struct 分岐と array 分岐を両方通らないと検出できない。

    ``Nest`` の (2,3) サブ配列が読み戻しで (6,) に潰れるのは asammdf の既知挙動
    (``test_column_roundtrip.py`` の同旨の注記) — リーフは ``Nest.g[0..5]`` の
    **1 段**になるので、``[3]`` は実在する位置である。
    """
    n = len(_SHADOW_TS)
    nested = np.zeros(n, dtype=np.dtype([("g", "<u1", (2, 3))]))
    for k in range(n):
        nested["g"][k] = np.arange(6, dtype=np.uint8).reshape(2, 3) + 10 * k
    mdf = MDF(version="4.10")
    try:
        mdf.append(
            [
                ASignal(
                    samples=np.array([5.0, 6.0, 7.0, 8.0]),
                    timestamps=_SHADOW_TS,
                    name="W[0][1]",
                    unit="deg",
                )
            ]
        )
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
            mdf.append(
                [ASignal(samples=samples, timestamps=_SHADOW_TS, name="W", unit="m")]
            )
        mdf.append([ASignal(nested, _SHADOW_TS, name="Nest")])
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.5, 2.5, 3.5, 4.5]),
                    timestamps=_SHADOW_TS,
                    name="Nest.g[3]",
                    unit="V",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]),
                    timestamps=_SHADOW_TS,
                    name="Clean",
                )
            ]
        )
        path = tmp_path / "multistage.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path
```

**fixture の実測（2026-08-04・本プランの起票時に実 asammdf で確認済み）** — 期待値は手計算でなくこの実測を貼ること:

| fixture | `column_records` のキー | 到達不能な (生成元, 列キー) |
|---|---|---|
| `write_mdf4_shadowed_leaf` | `['Mat', 'Mat[0]', 'Clean']` | `[('Mat', 'Mat[0]')]` |
| `write_mdf4_out_of_range_leaf_name` | `['Mat', 'Mat[7]', 'Clean']` | `[]` |
| `write_mdf4_multistage_shadow` | `['W[0][1]', 'W[0]', 'W[1]', 'Nest', 'Nest.g[3]', 'Clean']` | `[('W[0]', 'W[0][1]'), ('Nest', 'Nest.g[3]')]` |

- [ ] **Step 2: 失敗テストを書く**

`tests/core/loaders/test_shadowed_columns.py` を新規作成する:

```python
"""最長一致で影に隠れる列の検出と到達不能性 (E-4c spec §3・G1/G2)。

2-D チャンネル ``Mat`` と実在 1-D チャンネル ``Mat[0]`` が共存すると、最長一致規則
(E-3 の test-lock 済み意図的仕様) で実チャンネルが勝ち、**配列 ``Mat`` の第 0 列は
列キーでは二度と指せない**。データは正しく読めるので値のテストは全部緑のままで、
E-4c 以前は消えた列をユーザーが知る手段も、到達不能性そのものを assert する
テストも**存在しなかった**。

本モジュールは 2 つを**対で**固定する:

1. **到達不能性そのもの** (G2) — 全物理チャンネルの全列名を実際に resolve し、
   「生成元と別のチャンネルへ着地した列」を数え上げる。診断側が壊れても
   到達不能性側が壊れても、必ずどちらかが落ちる。
2. **info 診断** (G1) — 衝突ペアごとにちょうど 1 件。

**文言はテストへ直書きする**: production の f-string を import して組み立てると
文言変更で両側が同時に動き、assert が恒真化する (増分 D-1 で 4 件の silent
vacuous 化を実測した罠と同型)。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tests.mdf4_helpers import (
    write_mdf4_2d,
    write_mdf4_multistage_shadow,
    write_mdf4_out_of_range_leaf_name,
    write_mdf4_shadowed_leaf,
)
from valisync.core.loaders.column_names import owning_candidates, shadowed_leaf
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Diagnostic
from valisync.core.session import Session

#: 文言の**独立オラクル** (spec §3.3)。production の f-string を import しない。
_SHADOW_TMPL = (
    "信号 '{name}': 同名の実チャンネルが優先されるため、"
    "配列 '{parent}' の列 {position} は列キーでは参照できません"
)
#: 衝突 info を展開 info から選り分ける不変片 (文言が変われば expected 側と
#: 同時に落ちるので、ここが単独で恒真化することはない)。
_SHADOW_MARK = "列キーでは参照できません"


@dataclass(frozen=True)
class _Loaded:
    session: Session
    key: str
    diagnostics: tuple[Diagnostic, ...]


@contextmanager
def _loaded(path: Path) -> Iterator[_Loaded]:
    """``Session.load`` 経由で開く (ローダー直叩きでは診断 plumbing を通らない)。

    遅延ロードは MDF を開いたまま保持するので、必ず ``remove_group`` で閉じる —
    Windows は開いたままだと ``tmp_path`` の後始末がファイルロックで失敗しうる。
    """
    session = Session()
    outcome = session.load(path)
    try:
        yield _Loaded(
            session=session, key=outcome.key, diagnostics=outcome.diagnostics
        )
    finally:
        session.remove_group(outcome.key)


def _shadow_diags(diagnostics: tuple[Diagnostic, ...]) -> list[Diagnostic]:
    """衝突 info だけを取り出す (同じ level の展開 info と混ざらないように)。"""
    return [d for d in diagnostics if _SHADOW_MARK in d.message]


def _unreachable(loaded: _Loaded) -> list[tuple[str, str]]:
    """(生成元チャンネル, 列キー) — その列が **別の**チャンネルへ着地したもの。

    全物理チャンネルの全列名を実際に解決するので、「列が消えた」を主張でなく
    実測で数える。``column_names_of`` は鋳造を誘発せず列名だけを返し、
    ``physical_channel`` metadata は ``column_records`` のキー空間と同一なので、
    「生成元 != 着地先」がそのまま到達不能の定義になる。
    """
    session, key = loaded.session, loaded.key
    lost: list[tuple[str, str]] = []
    for sig in session.group_signals(key):
        physical = sig.metadata["physical_channel"]
        for column in session.column_names_of(key, physical):
            got = session.resolve_signal(f"{key}::{column}")
            owner = None if got is None else got.metadata.get("physical_channel")
            if owner != physical:
                lost.append((physical, column))
    return lost


def test_shadowed_leaf_emits_exactly_one_info(tmp_path: Path) -> None:
    """G1: 衝突ペアごとに info ちょうど 1 件 (level / signal_name / 文言まで固定)。"""
    with _loaded(write_mdf4_shadowed_leaf(tmp_path)) as loaded:
        hits = _shadow_diags(loaded.diagnostics)
        assert len(hits) == 1, [d.message for d in loaded.diagnostics]
        (diag,) = hits
        assert diag.level == "info"  # error ではない (データは正しく読める)
        assert diag.signal_name == "Mat[0]"  # 勝った側 = 診断ドックの「対象」列
        assert diag.message == _SHADOW_TMPL.format(
            name="Mat[0]", parent="Mat", position="[0]"
        )


def test_shadowed_leaf_is_actually_unreachable(tmp_path: Path) -> None:
    """G2: 到達不能性そのもの。

    **最後の 1 行だけが診断に依存する**: 上の 4 つは E-4c 以前から成立する
    characterization (最長一致の仕様そのもの) で、将来その規則を変えたら落ちる。
    最後の突き合わせが「診断の件数 == 実測した到達不能列の本数」を要求し、
    診断側だけ・実測側だけの片肺状態を落とす。
    """
    with _loaded(write_mdf4_shadowed_leaf(tmp_path)) as loaded:
        assert _unreachable(loaded) == [("Mat", "Mat[0]")]
        got = loaded.session.resolve_signal(f"{loaded.key}::Mat[0]")
        assert got is not None
        assert got.metadata["physical_channel"] == "Mat[0]"  # 親 "Mat" ではない
        assert got.metadata["unit"] == "deg"  # 親は "mm"
        assert got.values.dtype == np.float64  # 親の列は uint8
        # 母数 5 列 (Mat 3 + Mat[0] 1 + Clean 1) のうち 1 本が到達不能。
        assert loaded.session.total_column_count(loaded.key) == 5
        assert len(_shadow_diags(loaded.diagnostics)) == len(_unreachable(loaded))


def test_out_of_range_leaf_name_is_not_a_collision(tmp_path: Path) -> None:
    """範囲外 (幅 3 の配列に対する ``Mat[7]``) は到達不能列を作らない = 診断 0 件。"""
    with _loaded(write_mdf4_out_of_range_leaf_name(tmp_path)) as loaded:
        assert _shadow_diags(loaded.diagnostics) == []
        assert _unreachable(loaded) == []


def test_ordinary_file_emits_no_collision_info(tmp_path: Path) -> None:
    """非衝突ファイル (既存の 2-D fixture) では 1 件も出ない。"""
    with _loaded(write_mdf4_2d(tmp_path)) as loaded:
        assert _shadow_diags(loaded.diagnostics) == []
        assert _unreachable(loaded) == []
        # 反 vacuous: 展開 info そのものは出ている (診断経路が死んでいない)。
        assert any("本に展開" in d.message for d in loaded.diagnostics)


def test_multistage_names_are_detected_by_the_shared_walk(tmp_path: Path) -> None:
    """多段名も同一規則で検出する (``W[0][1]`` = dedup 済み親 / ``Nest.g[3]`` = 2 段)。"""
    with _loaded(write_mdf4_multistage_shadow(tmp_path)) as loaded:
        got = sorted(
            (d.signal_name, d.message) for d in _shadow_diags(loaded.diagnostics)
        )
        assert got == [
            (
                "Nest.g[3]",
                _SHADOW_TMPL.format(
                    name="Nest.g[3]", parent="Nest", position=".g[3]"
                ),
            ),
            (
                "W[0][1]",
                _SHADOW_TMPL.format(name="W[0][1]", parent="W[0]", position="[1]"),
            ),
        ]
        assert sorted(_unreachable(loaded)) == [
            ("Nest", "Nest.g[3]"),
            ("W[0]", "W[0][1]"),
        ]


def test_detection_and_resolution_share_one_walk(tmp_path: Path) -> None:
    """G5: 検出 (``shadowed_leaf``) と解決 (``_owning_channel``) が同じ walk を通る。

    ``owning_candidates`` は「長い順の候補列」で、解決側は**最初に受理された 1 本**で
    打ち切り、検出側は**自己ヒットの次**を取る。両者を同じ列に対して並べて固定して
    おくと、片方だけを書き換えた実装 (= 規則の二重化) が必ずここで落ちる。
    """
    result = MdfLoader().load(write_mdf4_shadowed_leaf(tmp_path))
    group = result.signal_group
    assert group is not None
    mgr = SignalGroupManager()
    key = mgr.add(group, column_records=result.column_records)
    try:
        records = mgr.column_records(key)
        hit = mgr._owning_channel(key, "Mat[0]")
        assert hit is not None
        assert (hit.display, hit.rest, hit.path) == ("Mat[0]", "", None)
        shadow = shadowed_leaf("Mat[0]", records)
        assert shadow is not None
        assert (shadow.display, shadow.rest) == ("Mat", "[0]")
        assert [(c.display, c.rest) for c in owning_candidates("Mat[0]", records)] == [
            ("Mat[0]", ""),
            ("Mat", "[0]"),
        ]
        # 実チャンネルでない名前は誰の影にもならない (呼び違いの防波堤)。
        assert shadowed_leaf("Mat[1]", records) is None
    finally:
        mgr.remove(key)
        if group.handle is not None:
            group.handle.close()
```

- [ ] **Step 3: RED を確認する**

```
uv run pytest tests/core/loaders/test_shadowed_columns.py -q
```

期待: **collection error**（`owning_candidates` / `shadowed_leaf` が `column_names` に無い）

```
ImportError: cannot import name 'owning_candidates' from 'valisync.core.loaders.column_names'
```

- [ ] **Step 4: 規則の単一実装を `column_names.py` へ足す（挙動は変えない）**

`src/valisync/core/loaders/column_names.py` の末尾（`_consume` の後）へ追記する:

```python
@dataclass(frozen=True, slots=True)
class LeafHit:
    """``display_key`` を「物理チャンネル + リーフサフィックス」へ分けた解釈 1 つ。

    ``rest`` が空文字 = 渡されたキーが **表示名そのもの** (物理チャンネルであって
    列ではない)。``SignalGroupManager._ChannelHit`` の先頭 3 フィールドと同名・同義
    で、**位置** (``ColumnPath``) だけがあちら側にある — 位置の解決は
    ``ColumnRecord.path_index`` を触るのでマネージャの責務である。
    """

    display: str
    rest: str
    record: ColumnRecord


def owning_candidates(
    display_key: str, records: Mapping[str, ColumnRecord]
) -> Iterator[LeafHit]:
    """*display_key* を所有しうる物理チャンネルを **長い順** に列挙する。

    **最長一致規則の単一実装** (E-4c G5)。解決側 (``SignalGroupManager.
    _owning_channel`` — 最初に受理した候補で打ち切る) と検出側
    (:func:`shadowed_leaf` — 自己ヒットの**次**を見る) がここだけを共有する。
    規則を 2 箇所に書くと「消えた」と診断が言う列と解決器が実際に返す列がずれ、
    **どちらも例外を出さずに**食い違う。

    ``records`` のキー空間は **LD-08 dedup 済み表示名**
    (``SignalGroupManager.column_records``)。``parse_leaf`` へ渡すのは
    ``ColumnRecord.raw_base_name`` から作る**単一エントリ Mapping** であって、
    表示名をそのまま生名キーの表へ渡してはならない (``parse_leaf`` の
    precondition = 二重名の契約)。

    ジェネレータなのは解決側が最初の受理で打ち切るため — 消費しなければ残りの
    候補は 1 つも評価されず、抽出前の逐次ループと仕事量が完全に一致する。
    """
    for i in range(len(display_key), 0, -1):
        record = records.get(display_key[:i])
        if record is None:
            continue
        rest = display_key[i:]
        if not rest:
            yield LeafHit(display_key[:i], "", record)
            continue
        # 二重名の契約: 表示名は dedup 済み名から、selector は **生チャンネル名**
        # から導く。両者は同じ suffix を共有する (ローダーの out_leaves と
        # sel_leaves は同一構造を同順に走査する)。dedup 済み表示名で parse_leaf を
        # 引くと "W[1][2]" の "[1]" を W 自身の配列インデックスとして消費し、
        # 解決不能になるか別チャンネルの列を返す。
        raw_leaf = f"{record.raw_base_name}{rest}"
        if parse_leaf(raw_leaf, {record.raw_base_name: record.spec}) is None:
            continue  # 消費しきれない / 非数値リーフ = この親では解決不能
        yield LeafHit(display_key[:i], rest, record)


def shadowed_leaf(
    display_name: str, records: Mapping[str, ColumnRecord]
) -> LeafHit | None:
    """*display_name* が実チャンネルとして勝つとき、影に隠れる配列リーフを返す。

    最長一致は長い方が勝つので、実チャンネル ``Mat[0]`` は配列 ``Mat`` の第 0 列に
    **必ず**優先する (E-3 の test-lock 済み意図的仕様)。負けた側の列は列キーでは
    二度と指せない = 到達不能になる。返すのは**負けた親**の解釈で、
    ``display``/``rest`` が「どの配列の・どの位置か」を表す。

    自己ヒット (``rest == ""``) を読み飛ばした**次の**候補を返すのが要点 — それが
    ちょうど「実チャンネルが居なければ勝っていた解釈」である。さらに短い候補は
    元々その次点にも負けているので、実チャンネル 1 本が隠す列は 1 本だけ
    (= 衝突ペアあたり診断も 1 件)。

    範囲外の添字 (幅 3 の配列に対する ``Mat[7]``) は ``parse_leaf`` の
    ``int(index_text) < spec.axis_len`` で自然に落ち、到達不能列が存在しないので
    None になる。*display_name* が ``records`` のキーでないとき (= 実チャンネル
    ではないとき) も None — 呼び違いで「列キーが親の影になった」という無い事実を
    作らないための防波堤。
    """
    if display_name not in records:
        return None
    for candidate in owning_candidates(display_name, records):
        if not candidate.rest:
            continue  # 自分自身 (最長一致で勝つ実チャンネル)
        return candidate
    return None
```

続けて `src/valisync/core/loaders/signal_group_manager.py` の import（`:11-18`）を差し替える。**`parse_leaf` は `_owning_channel` 以外で使われていないので必ず外す**（残すと `ruff check` が F401 で落ちる）:

```python
from valisync.core.loaders.column_names import (
    ColumnPath,
    ColumnRecord,
    leaf_count,
    leaf_names,
    leaf_paths,
    owning_candidates,
)
```

`_owning_channel`（`:758-794`）の本体だけを差し替える。現行:

```python
        records = self._column_records.get(group_key)
        if not records:
            return None
        for i in range(len(display_key), 0, -1):
            record = records.get(display_key[:i])
            if record is None:
                continue
            rest = display_key[i:]
            if not rest:
                return _ChannelHit(display_key[:i], "", record, None)
            # 二重名の契約: 表示名は dedup 済み名から、selector は **生チャンネル名**
            # から導く。両者は同じ suffix を共有する (ローダーの out_leaves と
            # sel_leaves は同一構造を同順に走査する)。dedup 済み表示名で parse_leaf を
            # 引くと "W[1][2]" の "[1]" を W 自身の配列インデックスとして消費し、
            # 解決不能になるか別チャンネルの列を返す。
            raw_leaf = f"{record.raw_base_name}{rest}"
            if parse_leaf(raw_leaf, {record.raw_base_name: record.spec}) is None:
                continue  # 消費しきれない / 非数値リーフ = この親では解決不能
            path = _leaf_path(record, rest)
            if path is None:
                continue  # 名前は通ったが位置が引けない = この親では解決不能
            return _ChannelHit(display_key[:i], rest, record, path)
        return None
```

差し替え後:

```python
        records = self._column_records.get(group_key)
        if not records:
            return None
        for candidate in owning_candidates(display_key, records):
            if not candidate.rest:
                return _ChannelHit(candidate.display, "", candidate.record, None)
            path = _leaf_path(candidate.record, candidate.rest)
            if path is None:
                continue  # 名前は通ったが位置が引けない = この親では解決不能
            return _ChannelHit(
                candidate.display, candidate.rest, candidate.record, path
            )
        return None
```

同メソッドの docstring 冒頭（`:759-770`）へ、規則の所在と `has_column` の除外を記録する 1 段落を足す:

```python
        """*display_key* を所有する物理チャンネルを最長一致で確定する。

        探索そのものは ``column_names.owning_candidates`` に**単一実装**として
        置いてある (E-4c G5) — 衝突検出 (``mdf_loader._shadow_diagnostics``) が
        同じ walk を通るので、「この列が消えた」と診断が言う列と鋳造器が実際に
        返す列が構造的にずれない。ここに残るのは**位置**の解決だけで、
        ``ColumnRecord.path_index`` を触るためマネージャの責務である。

        **``has_column`` の走査は畳まないこと** (意図的): あちらは
        ``raw_base_name`` を一切参照しない独立オラクルで、
        ``test_column_roundtrip.py`` の「生 selector 空間が表示空間へ漏れる」変異
        クラスを resolve とは別の観測点から殺している。共有化するとその歯が抜ける。
```

（以降の既存 docstring 本文はそのまま残す。）

- [ ] **Step 5: リファクタが挙動不変であることを実測する**

```
uv run pytest tests/core/loaders/test_shadowed_columns.py -q
```

期待: `3 failed, 3 passed`（赤の内訳: `test_shadowed_leaf_emits_exactly_one_info`（`len(hits) == 1` が 0 で失敗）・`test_shadowed_leaf_is_actually_unreachable`（最終行の `0 == 1` で失敗）・`test_multistage_names_are_detected_by_the_shared_walk`（`got == []`）。緑: `test_out_of_range_leaf_name_is_not_a_collision`・`test_ordinary_file_emits_no_collision_info`（0 件 assert は最初から成立）・`test_detection_and_resolution_share_one_walk`（Step 4 で成立））

続けて既存が 1 本も動いていないことを実測する:

```
uv run pytest tests/core -q
```

期待: 失敗は上の 3 本だけ（`3 failed, ...` で、`failed` の内訳が `test_shadowed_columns.py` の 3 本に限られること）。

**この 2 行が「解決側の挙動が 1 ミリも動いていない」ことの唯一の実証**なので、`test_shadowed_columns.py` 以外が 1 本でも赤なら次へ進まずここで直す。

- [ ] **Step 6: 衝突 info を `mdf_loader.py` へ配線する**

まず import 2 行を直す。`:4`:

```python
from collections.abc import Callable, Mapping
```

`:11-16`:

```python
from valisync.core.loaders.column_names import (
    ColumnRecord,
    ColumnSpec,
    leaf_count,
    shadowed_leaf,
    spec_from_probe,
)
```

`_expansion_diagnostic`（`:80-114`）の直後へ新しい関数を置く:

```python
def _shadow_diagnostics(
    column_records: Mapping[str, ColumnRecord],
    diagnostics: list[Diagnostic],
) -> None:
    """最長一致で影に隠れる配列リーフを info 診断にする (E-4c spec §3)。

    実チャンネル ``Mat[0]`` が配列 ``Mat`` の第 0 列と字面衝突すると、最長一致
    (E-3 の test-lock 済み意図的仕様) で実チャンネルが勝ち、**配列側のその列は
    列キーでは二度と指せなくなる**。値は正しく読めるので error ではないが、列が
    1 本消えたことをユーザーが知る手段が他に無い — info なら LD-12 の ``n_info``
    側に計上されアラームにならない (spec §3.1 案 C)。

    **判定は ``column_names.shadowed_leaf`` ただ 1 つ**。解決側
    (``SignalGroupManager._owning_channel``) と同じ walk (``owning_candidates``)
    を通るので、検出が「消えた」と言う列と解決器が実際に返す列は構造的に一致する。
    規則を 2 箇所に書いたらそこがずれ、どちらも例外を出さない (spec §3.2 / G5)。

    **``load()`` の末尾で呼ぶこと (``_load_group`` の末尾ではない)**: 衝突する
    2 本は別のチャンネルグループに居るのが常態で (asammdf の 1 append = 1 グループ)、
    ``_load_group`` の時点で ``column_records`` は**そこまでに処理したグループ分
    しか無い**。親が後のグループに居る配置 (``Mat[0]`` を先に append) では走査が
    親を見つけられず、**検出が append 順に依存して消える**。spec §3.4 の
    「``_load_group`` 末尾」からの意図的逸脱で、理由はこの 1 点。

    走査量は O(チャンネル数 x 名前長) の dict 参照 (prod 4,324 x ~30 = ~13 万回)。
    ``parse_leaf`` まで進むのは短いプレフィクスが**実在する表示名だった**ときだけ
    なので、通常ファイルではループの内側は 1 度も走らない。
    """
    for name in column_records:
        shadow = shadowed_leaf(name, column_records)
        if shadow is None:
            continue
        diagnostics.append(
            Diagnostic(
                level="info",
                message=(
                    f"信号 '{name}': 同名の実チャンネルが優先されるため、"
                    f"配列 '{shadow.display}' の列 {shadow.rest} は"
                    "列キーでは参照できません"
                ),
                signal_name=name,  # 勝った側 (診断ドックの「対象」列に整合)
            )
        )
```

`load()` のグループ走査 try/except 直後（現行 `:329` の空行と `:330` の `if not signals:` の間）へ呼び出しを挿入する:

```python
        # 全グループを読み終えてから 1 回だけ走らせる (理由は _shadow_diagnostics
        # の docstring — グループ末尾では表が未完成で、検出が append 順に消える)。
        _shadow_diagnostics(column_records, diagnostics)

        if not signals:
```

- [ ] **Step 7: GREEN を確認する**

```
uv run pytest tests/core/loaders/test_shadowed_columns.py -q
```

期待: `6 passed`

```
uv run pytest tests/core -q
```

期待: 既存も含めて全緑（`0 failed`）。

- [ ] **Step 8: sabotage A（恒偽化）→ 正 assert が RED**

`column_names.shadowed_leaf` の先頭（`if display_name not in records:` の直前）へ 1 行入れる:

```python
    return None  # SABOTAGE A
```

```
uv run pytest tests/core/loaders/test_shadowed_columns.py -q
```

- **predicted**: `3 failed, 3 passed` — 正 assert 3 本（`..._emits_exactly_one_info` / `..._is_actually_unreachable` / `..._multistage_names_...`）が RED、0 件 assert 2 本と G5 walk テストは緑のまま
- **measured**: （実行して貼る）

行を**手で削除して**元へ戻し、`uv run pytest tests/core/loaders/test_shadowed_columns.py -q` が `6 passed` へ戻ることを確認する。

- [ ] **Step 9: sabotage B（恒真化）→ 0 件 assert が RED**

`column_names.shadowed_leaf` のループ本体を書き換える:

```python
    for candidate in owning_candidates(display_name, records):
        return candidate  # SABOTAGE B (自己ヒットも返す)
    return None
```

```
uv run pytest tests/core/loaders/test_shadowed_columns.py -q
```

- **predicted**: `4 failed, 2 passed` — 0 件 assert 2 本（`..._out_of_range_...` / `..._ordinary_file_...`）が「衝突 3 件」で RED、`..._emits_exactly_one_info` は position が空文字になって文言不一致で RED、`..._multistage_names_...` も件数超過で RED。緑は `..._is_actually_unreachable`（`_unreachable` は診断を見ないが、最終行の件数突き合わせが 3 != 1 になるため実際は RED になりうる — measured で確定させる）と `..._share_one_walk`
- **measured**: （実行して貼る。predicted と食い違ったら**その差自体を記録する** — 0 件 assert 2 本が RED であることが本 sabotage の必須条件で、他は付随）

ループを**手で元へ戻し**、`6 passed` を確認する。

- [ ] **Step 10: ゲート＋コミット**

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

4 本すべて exit 0（`uv run pytest` は `2599 passed` 相当 = ベースライン 2593 + 6）。

```
git add -A
git commit -F - <<'EOF'
feat(core): 最長一致で影に隠れる列を info 診断化し規則を単一実装へ (E-4c G1/G2/G5)

配列チャンネル Mat と実在 1-D チャンネル Mat[0] が共存すると、最長一致
(E-3 の test-lock 済み意図的仕様) で実チャンネルが勝ち、配列側の第 0 列は
列キーでは二度と指せなくなる。値は正しく読めるため既存テストは全部緑のまま
で、消えた列をユーザーが知る手段も到達不能性を assert するテストも無かった。

- column_names に owning_candidates / shadowed_leaf / LeafHit を新設し、
  最長一致規則の実装を 1 箇所へ集約。_owning_channel はそれを消費する形へ
  (返り値・打ち切り条件は完全不変。has_column は独立オラクルとして据え置き)
- MdfLoader.load() 末尾で衝突ペアごとに info 診断を 1 件 emit
  (spec §3.4 の _load_group 末尾からは意図的逸脱 — そこでは column_records が
  未完成で、検出が append 順に依存して消えるため)
- tests/core/loaders/test_shadowed_columns.py を新設。到達不能性そのものを
  全列 resolve の実測で数え上げ、診断件数と突き合わせる

sabotage: 恒偽化で正 assert 3 本 RED / 恒真化で 0 件 assert 2 本 RED を実測。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
```

---

### Task 2: `signal_map()` 全列列挙の AST 構造ガード（G3）

**Files:**

- Create: `tests/core/test_signal_map_guard.py`
- Create（sabotage 用・**必ず削除する**）: `src/valisync/core/_signal_map_guard_sabotage.py`
- Modify: なし（`src/` は 1 行も変えない — 本タスクは常設ガードの追加のみ）

**Interfaces:**

- Consumes: 標準ライブラリ `ast` / `pathlib` のみ。scan 対象は `src/valisync/**/*.py`
- Produces（本ファイル内で閉じる）:
  - `_ALLOWLIST: tuple[tuple[str, str, str], ...]` — `(相対 path, 行内一致パターン, 理由)`。**初期値は空**（2026-08-04 実測で `src/` の違反は 0 件）
  - `_scan(allowlist) -> tuple[list[str], list[tuple[str, str, str]]]` — `(違反, 陳腐化 allowlist エントリ)`。本体テストと陳腐化テストが共有する唯一の実装
  - テスト 2 本: `test_no_signal_map_enumeration_in_src` / `test_stale_allowlist_entry_is_reported`
- 二層防御の下段（**無改変**）: `tests/core/loaders/test_resolver.py:269-353`（`test_signal_map_enumeration_does_not_mint` ほか）・`tests/core/test_session_signal_map.py`

---

- [ ] **Step 1: sabotage ファイルを先に置く（honest-RED の材料）**

`src/valisync/core/_signal_map_guard_sabotage.py` を新規作成する。**このファイルはガードの RED を実証したら必ず削除する**（Step 5）:

```python
"""E-4c Task 2 sabotage — AST ガードの検出形 1-4 を実証する一時ファイル (必ず削除)。"""

from __future__ import annotations

from typing import Any


def form1_direct(session: Any) -> dict[str, Any]:
    return dict(session.signal_map())


def form2_iteration(session: Any) -> list[str]:
    out: list[str] = []
    for name in session.signal_map():
        out.append(name)
    return out


def form3_view(session: Any) -> Any:
    return session.signal_map().items()


def form4_variable(session: Any) -> list[str]:
    signal_map = session.signal_map()
    return [name for name in signal_map]
```

どこからも import されないので production 挙動には触れない（`valisync.core` の `__init__` に載せないこと）。

- [ ] **Step 2: ガードを書く**

`tests/core/test_signal_map_guard.py` を新規作成する:

```python
"""``signal_map()`` 全列列挙ガード (常設 Layer A・E-4c spec §4)。

``SignalGroupManager.signal_map()`` は **非対称 Mapping** (E-1 の意図的逸脱):
``[]``/``get``/``in`` は列キーを解決器経由で鋳造しうるが、``__iter__``/``__len__``
は既存 (物理) キーしか返さない。全論理キーの列挙は prod の 330,004 列を鋳造して
~390 MB を再導入するので提供しない — つまり ``dict(session.signal_map())`` は
**例外も警告も出さずに「全列の顔をした物理チャンネルだけの map」**を返す。
E-4c 以前、この契約への防御は挙動テストだけで、``src/`` に 1 行書けば
コンパイルも CI も通ってしまった。

**二層防御の上段**がこのファイル: ``src/`` に書いた瞬間に落ちる。下段は
``tests/core/loaders/test_resolver.py:269-353`` と ``tests/core/test_session_signal_map.py``
の挙動テストで、そちらは「仕様そのものが壊れたら落ちる」。上段は false positive を
allowlist で吸収し、下段が false negative を実測で拾う — **2 つは独立オラクルなので
片方を他方に合わせて弱めてはならない**。

形は ``tests/gui/test_theme_guard.py`` と同型 (行内容 ratchet allowlist + 陳腐化
assert)。コメント/docstring は AST 上 ``Constant`` にしか現れず、ここでは
``Call``/``For``/``comprehension`` しか見ないので自然に対象外になる
(``signal_group_manager.py:393`` や ``session.py:276`` の禁止事項を書いた docstring が
自分自身を違反にしない理由)。
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "valisync"

# 列挙を強制する組み込み (spec §4.2-1)。
_ENUMERATORS = frozenset({"dict", "list", "set", "sorted", "tuple", "iter"})
# ビュー形 (spec §4.2-3)。
_VIEW_METHODS = frozenset({"keys", "items", "values"})
# ``x.signal_map()`` を名乗る呼び出し。``_signal_map`` を含めるのは spec §4.2-1 の
# 素直な広げ方であって緩めではない: ``GraphPanelVM._signal_map()`` は同じ非対称
# map (または列挙が TypeError になる ``_OffsetOverlay``) を返す実質同一の口で、
# ここを外すと prod で最も列挙されそうな 8 サイトが丸ごと盲点になる。
_SIGNAL_MAP_CALLS = frozenset({"signal_map", "_signal_map"})

_MESSAGE = (
    "signal_map() の全列列挙は禁止（列挙は物理キーのみ返る — E-1 の非対称 Mapping。"
    "全論理キーを列挙すると prod 330,004 列を鋳造して ~390 MB を再導入する）。"
    "列数は total_column_count() ／列名は column_names_of() ／存在確認は "
    "has_column() を使う"
)

# (相対 path, 行内一致パターン, 理由) — 行パターン ratchet (theme_guard と同型):
# ファイル単位だと同一ファイル内の新規違反を隠すため、行内容で絞る。
# どこにも一致しなくなったエントリは陳腐化として fail する。
# **空が目標**。2026-08-04 実測で src/ の違反は 0 件。
_ALLOWLIST: tuple[tuple[str, str, str], ...] = ()


def _iter_py_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _is_signal_map_call(node: ast.AST) -> bool:
    """``<x>.signal_map()`` / ``signal_map()`` そのものか (spec §4.2-1)。"""
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute):
        return fn.attr in _SIGNAL_MAP_CALLS
    return isinstance(fn, ast.Name) and fn.id in _SIGNAL_MAP_CALLS


def _is_signal_map_name(node: ast.AST) -> bool:
    """``signal_map`` を名前に含む変数 (spec §4.2-4 の**浅い**追跡)。

    データフロー解析はしない。false positive は allowlist で吸収し、false
    negative は下段の挙動テストが実測で拾う — それが二層である理由そのもの。
    """
    return isinstance(node, ast.Name) and "signal_map" in node.id


def _is_map_expr(node: ast.AST) -> bool:
    return _is_signal_map_call(node) or _is_signal_map_name(node)


def _violations_in(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    lines = source.splitlines()
    found: set[tuple[int, str]] = set()

    def record(node: ast.AST) -> None:
        lineno = getattr(node, "lineno", 0)
        line = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
        found.add((lineno, line))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            # 1. 直結形: dict(m) / list(m) / set(m) / sorted(m) / tuple(m) / iter(m)
            if (
                isinstance(fn, ast.Name)
                and fn.id in _ENUMERATORS
                and any(_is_map_expr(a) for a in node.args)
            ):
                record(node)
            # 3. ビュー形: m.keys() / m.items() / m.values()
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr in _VIEW_METHODS
                and _is_map_expr(fn.value)
            ):
                record(node)
        # 2. イテレーション形: for ... in m / 内包表記の iter
        if isinstance(node, (ast.For, ast.AsyncFor)) and _is_map_expr(node.iter):
            record(node)
        if isinstance(node, ast.comprehension) and _is_map_expr(node.iter):
            record(node.iter)  # comprehension 自体は lineno を持たない
    return sorted(found)


def _scan(
    allowlist: tuple[tuple[str, str, str], ...],
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """(違反, 陳腐化 allowlist エントリ) を返す — 2 本のテストが共有する唯一の実装。

    陳腐化テストが**同じ照合ロジック**を通ることが要点: allowlist を空のまま
    置くと本体側の陳腐化 assert は構造的に空回りするので、機構そのものは
    合成 allowlist で別途実証する。
    """
    used: set[int] = set()
    violations: list[str] = []
    for path in _iter_py_files():
        rel = path.relative_to(SRC).as_posix()
        for lineno, line in _violations_in(path.read_text(encoding="utf-8")):
            allowed = False
            for i, (a_path, a_pat, _reason) in enumerate(allowlist):
                if rel == a_path and a_pat in line:
                    used.add(i)
                    allowed = True
                    break
            if not allowed:
                violations.append(f"{rel}:{lineno}: {line}")
    stale = [allowlist[i] for i in range(len(allowlist)) if i not in used]
    return violations, stale


def test_no_signal_map_enumeration_in_src() -> None:
    violations, stale = _scan(_ALLOWLIST)
    assert not violations, _MESSAGE + ":\n" + "\n".join(violations)
    assert not stale, f"allowlist の陳腐化エントリ (どこにも一致しない): {stale}"


def test_stale_allowlist_entry_is_reported() -> None:
    """陳腐化検出の機構そのものを固定する (``_ALLOWLIST`` が空でも空回りしない)。"""
    fake = (("core/session.py", "この行は src に存在しない", "陳腐化検出の実証用"),)
    violations, stale = _scan(fake)
    assert violations == [], violations  # 合成 allowlist は違反を増やさない
    assert stale == list(fake)
```

- [ ] **Step 3: RED を確認する（offenders のファイル名特定つき）**

```
uv run pytest tests/core/test_signal_map_guard.py -q
```

期待: `1 failed, 1 passed`。失敗メッセージに **4 行すべて**が出ること（検出形 1-4 が 1 つずつ）:

```
core/_signal_map_guard_sabotage.py:9: return dict(session.signal_map())
core/_signal_map_guard_sabotage.py:14: for name in session.signal_map():
core/_signal_map_guard_sabotage.py:20: return session.signal_map().items()
core/_signal_map_guard_sabotage.py:25: return [name for name in signal_map]
```

4 行に満たない場合は**その検出形が実装されていない** — 進まずに `_violations_in` を直す。

- [ ] **Step 4: 検出形を 1 つずつ落として識別力を確かめる**

sabotage ファイルから `form1_direct` の関数定義だけを削除 →

```
uv run pytest tests/core/test_signal_map_guard.py -q
```

期待: 依然 `1 failed`、ただし RED の一覧が **3 行**（`dict(` の行が消える）。`form2` / `form3` / `form4` についても同様に 1 つずつ削って、**削るたびに RED の行数が 1 つずつ減る**ことを確認する。最後の 1 つを削ると `2 passed` になる。

- **predicted**: 4 行 → 3 → 2 → 1 → 0（`2 passed`）
- **measured**: （実行して貼る）

- [ ] **Step 5: sabotage ファイルを削除してクリーン GREEN**

```
git status --porcelain src/
```

期待: 出力が空（`src/valisync/core/_signal_map_guard_sabotage.py` が消えている）。残っていれば削除する。

```
uv run pytest tests/core/test_signal_map_guard.py -q
```

期待: `2 passed`

さらに下段が無改変であることを確認する:

```
git diff --stat HEAD -- tests/core/loaders/test_resolver.py tests/core/test_session_signal_map.py
```

期待: 出力が空（1 行も変えていない = 二層が独立）。

- [ ] **Step 6: ゲート＋コミット**

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

4 本すべて exit 0。

```
git add -A
git commit -F - <<'EOF'
test(core): signal_map() 全列列挙の AST 構造ガードを常設 (E-4c G3)

signal_map() は非対称 Mapping (ルックアップは列を鋳造するが列挙は物理キーの
み)。全論理キーの列挙は prod 330,004 列を鋳造して ~390 MB を再導入するため
提供しないが、dict(session.signal_map()) は例外も警告も出さず「全列の顔をした
物理チャンネルだけの map」を返す。防御が挙動テストだけだったので、src/ に
1 行書けばコンパイルも CI も通っていた。

theme_guard 同型の AST ガードを新設し、検出形 4 つ (直結 / イテレーション /
ビュー / 浅い変数追跡) を src/valisync/ 全域へ適用する。allowlist は空
(行内容 ratchet + 陳腐化 assert)。陳腐化検出は合成 allowlist で別途実証し、
空 allowlist でも空回りしないようにした。

下段 (test_resolver.py / test_session_signal_map.py の挙動テスト) は無改変 —
上段と下段は独立オラクルであることが二層防御の前提。

sabotage: 一時違反ファイルで検出形 4 つを 1 つずつ落とし、RED の行数が
4→3→2→1→0 と減ることを実測。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
```

---

### Task 3: `_evict_resolved` の lock 外解放（G4）

**Files:**

- Modify: `src/valisync/core/loaders/signal_group_manager.py` — `_evict_resolved` `:590-619`・呼び出し元 `resolve()` `:434-441`・`set_pinned_columns()` `:504-507`
- Modify: `tests/core/loaders/test_resolved_column_lru.py` — import 行と末尾へ追記（既存テストは無改変）

**Interfaces:**

- Consumes（既存・このタスクで意味が変わる）:
  - `SignalGroupManager._resolved_lock: threading.Lock` — 帳簿（`_resolved_order` / `_pinned` / `_resolved_by_key`）を守る小さな専用 lock。E-4b でエクスポートワーカー（`resolve_transient`）が同じ lock の取り手になった＝ spec F6 の defer 根拠が失効した
  - `SignalGroupManager.resolved_evictions: int` / `resolved_lru_keys() -> tuple[str, ...]` / `resolved_keys(group_key) -> frozenset[str]`
  - 手本: `channel_cache._evict_oldest`（`channel_cache.py:338-355`）と `put` / `set_reserved` の `del evicted`（`:154-176` / `:197-207`）
- Produces（シグネチャ変更・**呼び出し元は 2 箇所のみ**）:
  - `SignalGroupManager._evict_resolved(self) -> list[Signal]` — **返り値を捨ててはならない**。lock 内で帳簿から外して返し、呼び出し側が `with` を出てから `del evicted` する
- 不変（このタスクが壊してはならない契約）:
  - evict 順（古い順）・pin 不可侵・`_MIN_EVICTABLE_COLUMNS`・ヒステリシス（`_RESOLVED_EVICT_DIVISOR`）・`resolved_evictions` の数え方はすべて不変。既存 `test_resolved_column_lru.py` の 10 本が 1 本も動かないこと

---

- [ ] **Step 1: 失敗テストを書く**

`tests/core/loaders/test_resolved_column_lru.py` の import を差し替える（`:10-23`）:

```python
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.mdf4_helpers import write_mdf4_wide_2d
from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models.load_result import LoadResult
```

ファイル末尾（`test_evicted_column_reread_does_not_touch_the_file_again` の後）へ追記する:

```python
# ─── 解放は _resolved_lock の外 (E-4c §5・E-4 親 spec §12-2) ───────────────────


class _LockProbe:
    """解放される瞬間に「``_resolved_lock`` が握られていたか」を記録する番人。

    ``threading.Lock`` は非再帰なので、保持中のスレッドが ``acquire(blocking=False)``
    しても False が返る — これが「今 lock 下か」の直接観測になる
    (``test_channel_cache.py`` の ``_LockProbeArray`` と同型)。

    **ndarray サブクラスにしないのは取り付け口が違うから**: あちらは追い出される
    実体が ndarray そのものなので観測子になれる。こちらで落ちるのは **Signal** で、
    ``__slots__`` を持つため属性を足せず、値配列は ``LazyMdfValues`` の私有キャッシュ
    の中にあって差し替えられない。Signal と寿命が完全に一致して外から書ける唯一の
    口が ``metadata`` dict である (鋳造列の metadata は ``_mint_column`` が毎回
    新しく作るので、親チャンネルと共有していない)。

    参照は lock と記録用リストだけに留める (manager を参照すると循環になり、解放が
    refcount でなく gc 任せ = 非決定になる)。
    """

    def __init__(self, lock: threading.Lock, observed: list[bool]) -> None:
        self._lock = lock
        self._observed = observed

    def __del__(self) -> None:
        acquired = self._lock.acquire(blocking=False)
        self._observed.append(not acquired)
        if acquired:
            self._lock.release()


def _probe_column(mgr: SignalGroupManager, column_key: str) -> list[bool]:
    """*column_key* を鋳造し、その Signal へ観測子を仕込んで記録先を返す。"""
    observed: list[bool] = []
    sig = mgr.resolve(column_key)
    assert sig is not None
    sig.metadata["lock_probe"] = _LockProbe(mgr._resolved_lock, observed)
    del sig  # 帳簿だけが持つ状態にする (以後の解放は必ず evict 由来)
    return observed


def _drop_via_resolve_minting(wide: LoadResult) -> list[bool]:
    """**ホットパス**: 鋳造が容量を超えて古い列を落とす経路 (GUI の render)。"""
    mgr = SignalGroupManager(resolved_capacity=2)
    key = _register(mgr, wide)
    observed = _probe_column(mgr, f"{key}::Wide[0]")
    for i in range(1, 8):
        assert mgr.resolve(f"{key}::Wide[{i}]") is not None
    assert mgr.resolved_evictions > 0, "evict が起きていない (setup 失敗 = 反 vacuous)"
    return observed


def _drop_via_unpinning(wide: LoadResult) -> list[bool]:
    """pin 集合の差し替え (``Session.set_pinned_columns``) が落とす経路。

    ``resolve`` は鋳造のたびに evict するので、容量超過は **pin でしか作れない**:
    5 本を pin して帳簿を容量 2 の上へ押し上げ、pin を外した瞬間に
    ``set_pinned_columns`` 側の ``_evict_resolved`` が 4 本落とす。
    """
    mgr = SignalGroupManager(resolved_capacity=2)
    key = _register(mgr, wide)
    mgr.set_pinned_columns({f"{key}::Wide[{i}]" for i in range(5)})
    observed = _probe_column(mgr, f"{key}::Wide[0]")
    for i in range(1, 5):
        assert mgr.resolve(f"{key}::Wide[{i}]") is not None
    assert mgr.resolved_evictions == 0, "pin 中に落ちた (setup 前提が崩れている)"
    mgr.set_pinned_columns(set())
    assert mgr.resolved_evictions > 0, "unpin で落ちていない (反 vacuous)"
    return observed


@pytest.mark.parametrize(
    "drop",
    [_drop_via_resolve_minting, _drop_via_unpinning],
    ids=["resolve_minting", "unpinning"],
)
def test_evicted_columns_are_freed_outside_the_lock(
    drop: Callable[[LoadResult], list[bool]], wide: LoadResult
) -> None:
    """``_evict_resolved`` が外した列の解放は ``_resolved_lock`` の外で走る。

    lock 下で最後の参照が死ぬ形だと、列 1 本ぶんの実体 (値配列 + ``sorted_view``
    が作る float64 ビュー・prod 実測 ~108 KB/列) の dealloc がこの lock を握った
    まま走る。E-4b でエクスポートワーカーが同じ lock の取り手になった (spec F6 =
    defer 根拠の失効) ので、GUI の ``resolve()`` がその dealloc を待つ形になる。
    **症状は待ち時間だけ**で会計にも数字にも出ない — だから会計ではなく解放の
    瞬間そのものを観測する。

    **2 経路とも回す** (E-4a の同型テストが踏んだ轍 ``test_channel_cache.py:473-477``:
    最初に塞いだ 1 経路だけを見ていて、残り 2 経路は両方 ``[True]`` だった)。
    """
    observed = drop(wide)

    assert observed == [False], (
        f"鋳造列の解放が _resolved_lock 保持下で走った: {observed}"
    )
```

- [ ] **Step 2: RED を確認する**

```
uv run pytest tests/core/loaders/test_resolved_column_lru.py -q
```

期待: `2 failed, 9 passed`（既存 9 本は緑のまま）。両 param とも同じ形で落ちる:

```
AssertionError: 鋳造列の解放が _resolved_lock 保持下で走った: [True]
assert [True] == [False]
```

（2026-08-04 に本プランの起票時、両経路とも `[True]` を実測済み。片方が最初から `[False]` なら setup が evict を起こしていないので、そちらの `_drop_*` を直してから進む。）

- [ ] **Step 3: `_evict_resolved` を「外して返す」形へ変える**

`signal_group_manager.py:590-619` を差し替える。docstring 冒頭 1 行と本文を次の形にする（既存の pin / ヒステリシスの段落はそのまま残す）:

```python
    def _evict_resolved(self) -> list[Signal]:
        """非 pin の鋳造列を古い順に落として容量へ収め、**外した Signal を返す** (D4)。

        **返り値を捨ててはならない** — 呼び出し側は ``_resolved_lock`` の外まで
        参照を持ち越し、そこで初めて手放すこと (``resolve`` / ``set_pinned_columns``
        の ``del evicted``)。ここで参照を落とすと、鋳造列が抱える実体 (値配列 +
        ``sorted_view`` が作る float64 ビュー・prod 実測 ~108 KB/列) の dealloc が
        この lock の保持下で走る。E-4b でエクスポートワーカーが同じ lock を ~18 分
        取り続ける経路になった (E-4b spec F6 = defer 根拠の失効) ので、GUI の
        ``resolve()`` がその dealloc を待つ。ロック順は保たれるのでデッドロックには
        ならず、**症状は待ち時間だけで数字にも出ない** — ``channel_cache.
        _evict_oldest`` が同じ理由で同じ形をしている。test-lock は
        ``test_resolved_column_lru.py::test_evicted_columns_are_freed_outside_the_lock``
        (2 経路とも回す)。

        **pin は決して落とさない**。pin が予算を超えても拒否せず、超過は
        :attr:`pinned_overflow` で観測する (spec §5.5)。pin だけで予算が埋まった
        場合でも非 pin 用に ``_MIN_EVICTABLE_COLUMNS`` 本は確保するので、鋳造した
        列がその場で自分を落とす形にはならない。

        高水位/低水位のヒステリシスは走査回数の償却のため (定数のコメント参照)。
        pin が予算を超えている極端な状態では毎回 O(pin 数) の走査になるが、
        これは「プロット中の列を落とさない」ことの代価として受け入れる。

        呼び出し側が ``_resolved_lock`` を保持していること。
        """
        if len(self._resolved_order) <= self._resolved_capacity:
            return []  # 予算内 — pin の数え直しすらしない (鋳造ホットパスの O(n) 回避)
        pinned_live = sum(1 for k in self._resolved_order if k in self._pinned)
        room = max(self._resolved_capacity - pinned_live, _MIN_EVICTABLE_COLUMNS)
        slack = max(1, room // _RESOLVED_EVICT_DIVISOR)
        keep = max(room - slack, _MIN_EVICTABLE_COLUMNS)
        unpinned = [k for k in self._resolved_order if k not in self._pinned]
        excess = len(unpinned) - keep
        if excess <= 0:
            return []
        evicted: list[Signal] = []
        for column_key in unpinned[:excess]:  # dict は挿入順 = 古い順
            del self._resolved_order[column_key]
            table = self._resolved_by_key.get(column_key.split(KEY_SEPARATOR, 1)[0])
            if table is not None:
                dropped = table.pop(column_key, None)
                if dropped is not None:
                    evicted.append(dropped)
            self.resolved_evictions += 1
        return evicted
```

- [ ] **Step 4: 呼び出し元 2 箇所を lock 外へ持ち越す形にする**

`resolve()`（`:434-441`）の末尾。現行:

```python
            minted = self._mint_column(group_key, key)
            if minted is None:
                return None
            table[key] = minted
            self._resolved_order[key] = None
            self.mint_count += 1
            self._evict_resolved()
            return minted
```

差し替え後（最後の 2 行が `with` の**外**へ出る点に注意）:

```python
            minted = self._mint_column(group_key, key)
            if minted is None:
                return None
            table[key] = minted
            self._resolved_order[key] = None
            self.mint_count += 1
            evicted = self._evict_resolved()
        # 最後の参照は lock の**外**で死ぬ (理由は _evict_resolved の docstring)。
        # ここは GUI の render と E-4b のエクスポートワーカーが**両方**踏む最も
        # ホットな経路で、lock 下で dealloc すると互いに待つ。
        del evicted
        return minted
```

`set_pinned_columns()`（`:504-507`）。現行:

```python
        pinned = frozenset(keys)
        with self._resolved_lock:
            self._pinned = pinned
            self._evict_resolved()
```

差し替え後:

```python
        pinned = frozenset(keys)
        with self._resolved_lock:
            self._pinned = pinned
            evicted = self._evict_resolved()
        # channel_cache の put / set_reserved と同じ理由で lock の外まで持ち越す。
        del evicted
```

- [ ] **Step 5: GREEN を確認する**

```
uv run pytest tests/core/loaders/test_resolved_column_lru.py -q
```

期待: `11 passed`（既存 9 + 新規 2）。

```
uv run pytest tests/core -q
```

期待: 全緑（LRU の順序・pin・`resolved_evictions` の数え方が 1 つも動いていないこと）。

- [ ] **Step 6: sabotage（lock 内解放へ戻す）→ RED**

`resolve()` と `set_pinned_columns()` の `del evicted` を **`with` ブロックの内側**（`evicted = self._evict_resolved()` の直後）へ移す:

```python
            evicted = self._evict_resolved()
            del evicted  # SABOTAGE (lock 内解放へ逆戻り)
```

```
uv run pytest tests/core/loaders/test_resolved_column_lru.py -q
```

- **predicted**: `2 failed, 9 passed` — 両 param とも `observed == [True]`
- **measured**: （実行して貼る）

**片方だけ sabotage したときも**確認する（`resolve()` 側だけ・`set_pinned_columns()` 側だけ）:

- **predicted**: それぞれ `1 failed`（`resolve_minting` だけ / `unpinning` だけ）— これが「2 経路を回す」ことの識別力の実証
- **measured**: （実行して貼る）

`del evicted` を**手で** `with` の外へ戻し、`11 passed` を確認する。

- [ ] **Step 7: ゲート＋コミット**

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

4 本すべて exit 0。

```
git add -A
git commit -F - <<'EOF'
fix(core): 鋳造列 LRU の evict 解放を _resolved_lock の外へ (E-4c G4)

_evict_resolved は帳簿から外した Signal の最後の参照を lock 保持下で落として
いた。列 1 本ぶんの実体 (値配列 + sorted_view の float64・prod ~108 KB/列) の
dealloc がこの lock を握ったまま走るので、E-4b でエクスポートワーカーが同じ
lock の取り手になった今 (E-4b spec F6 = defer 根拠の失効)、GUI の resolve()
がその dealloc を待つ。デッドロックにはならず症状は待ち時間だけで数字にも
出ない。

channel_cache._evict_oldest と同型に「lock 内で外して返す・呼び出し側が with を
出てから del する」形へ変更。呼び出し元は resolve() と set_pinned_columns() の
2 箇所のみで、どちらも lock 外で捨てる。

LRU の順序・pin 不可侵・最低容量・ヒステリシス・resolved_evictions の数え方は
すべて不変 (既存 10 本は無改変で緑)。

sabotage: del を with の内側へ戻すと両経路とも observed == [True] で RED。
片方だけ戻すと対応する 1 param だけが RED になることも実測 (2 経路を回す
必要性の実証 — E-4a の同型テストは 1 経路だけ見ていて残り 2 経路が両方
壊れていた)。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
```

---

### Task 4: docs 正誤＋フルゲート（G6/G7）

**Files:**

- Modify: `CLAUDE.md` — 62 行目（「横断 / 遅延ロード（メモリ根治）」の行）の中の 1 文
- Modify: `docs/roadmap.md` — 112 行目（E-4b 段落）の中の同じ 1 文

**Interfaces:**

- Consumes: Task 1/2/3 のコミットが済んでいること（フルゲートは 3 つ揃った状態で回す）
- Produces: なし（ドキュメントのみ）
- 根拠（訂正内容の裏取り）:
  - `CacheKey` の `id(handle)` は E-4b spec §5.7-1 で **serial 化済み** — `tests/core/loaders/test_handle_serial.py` が production 経路で pin
  - 鋳造列 LRU の本数縛りは E-4c spec §2 で **defer 裁定** — 上限は構造的に有界（512 本 × prod 実測 ~108 KB/列 ≈ 55 MB）。バイトでなく本数なのは「未展開列は 0 バイトでバイト予算が効かない」ための意図的設計（`signal_group_manager.py:34-41` に明記）

---

- [ ] **Step 1: 裏取りを実測する（主張でなく grep）**

```
grep -rn "id(handle)" src/
```

期待: 出力なし（0 hits）。

```
uv run pytest tests/core/loaders/test_handle_serial.py -q
```

期待: 全緑（`serial` が production 経路で効いていること）。

- [ ] **Step 2: `CLAUDE.md` の 1 文を訂正する**

62 行目の中の**この文字列だけ**を置換する（前後の `／worker の BaseException …` 等には触らない）。

before（`）` の直前で終わる）:

```
E-4a からの `CacheKey` `id(handle)`・鋳造列 LRU 本数縛りは E-4c へ継続）
```

after:

```
E-4a からの `CacheKey` `id(handle)` は **E-4b で serial 化済み**（spec §5.7-1・`test_handle_serial.py` が production 経路で pin・`grep -rn "id(handle)" src/` = 0 hits）／鋳造列 LRU の本数縛り（512）は **E-4c で defer 裁定**（上限は構造的に有界＝512 本 × prod 実測 ~108 KB/列 ≈ 55 MB。バイトでなく本数なのは「未展開列は 0 バイトでバイト予算が効かない」ための意図的設計））
```

- [ ] **Step 3: `docs/roadmap.md` の同じ 1 文を訂正する**

112 行目の中の**この文字列だけ**を置換する（末尾が `。` である点だけが CLAUDE.md と違う）。

before:

```
E-4a からの `CacheKey` `id(handle)`・鋳造列 LRU 本数縛りは E-4c へ継続。
```

after:

```
E-4a からの `CacheKey` `id(handle)` は **E-4b で serial 化済み**（spec §5.7-1・`test_handle_serial.py` が production 経路で pin・`grep -rn "id(handle)" src/` = 0 hits）／鋳造列 LRU の本数縛り（512）は **E-4c で defer 裁定**（上限は構造的に有界＝512 本 × prod 実測 ~108 KB/列 ≈ 55 MB。バイトでなく本数なのは「未展開列は 0 バイトでバイト予算が効かない」ための意図的設計）。
```

- [ ] **Step 4: stale 記述が残っていないことを確認する**

```
grep -rn "E-4c へ継続" CLAUDE.md docs/
```

期待: 出力なし。

```
grep -c "E-4b で serial 化済み" CLAUDE.md docs/roadmap.md
```

期待: 両方 `1`。

- [ ] **Step 5: フルゲート（serial・パイプ無し）**

```
uv run pytest
```

期待: `2603 passed`（ベースライン 2593 + Task 1 の 6 + Task 2 の 2 + Task 3 の 2）。Step 0 で控えた実測値からの増分で確認すること。

```
uv run ruff check
```

期待: `All checks passed!`

```
uv run ruff format --check
```

期待: `N files already formatted`

```
uv run mypy src/
```

期待: `Success: no issues found in N source files`

- [ ] **Step 6: 既存テストの無改変を確認する**

```
git diff --stat main -- tests/core/loaders/test_resolver.py tests/core/test_session_signal_map.py tests/core/loaders/test_column_roundtrip.py
```

期待: 出力が空（下段の挙動テストと全数ラウンドトリップ・オラクルを 1 行も触っていない = G7）。

```
git diff --stat main -- src/valisync/gui/
```

期待: 出力が空（GUI は 1 行も変えていない。診断ドックへ info が 1 行増えるのは既存 plumbing の既検証経路なので realgui は不要 — spec §7.4）。

- [ ] **Step 7: コミット**

```
git add -A
git commit -F - <<'EOF'
docs: CacheKey の stale 記述を訂正し鋳造列 LRU の defer 裁定を記録 (E-4c G6)

CLAUDE.md / docs/roadmap.md の「E-4a からの CacheKey id(handle)・鋳造列 LRU
本数縛りは E-4c へ継続」は stale。CacheKey は E-4b spec §5.7-1 で serial 化
済みで (grep -rn "id(handle)" src/ = 0 hits・test_handle_serial.py が
production 経路で pin)、鋳造列 LRU の本数縛りは E-4c spec §2 で defer 裁定
(上限は構造的に有界＝512 本 × ~108 KB/列 ≈ 55 MB・「未展開列は 0 バイトで
バイト予算が効かない」ための意図的設計)。

フルゲート 4 本 clean。既存の下段挙動テスト (test_resolver.py /
test_session_signal_map.py) と全数ラウンドトリップ (test_column_roundtrip.py)
は無改変・gui/ は 1 行も変更なし。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
```

---

## 受け入れ基準の対応表（spec §8）

| # | 基準 | 担当 | 実証 |
|---|---|---|---|
| G1 | `Mat`/`Mat[0]` 共存で info ちょうど 1 件・非衝突/範囲外で 0 件・多段名でも検出 | T1 | `test_shadowed_leaf_emits_exactly_one_info` / `test_out_of_range_leaf_name_is_not_a_collision` / `test_ordinary_file_emits_no_collision_info` / `test_multistage_names_are_detected_by_the_shared_walk` ＋ sabotage A/B |
| G2 | shadow されたリーフが列キーで引けないことを直接 assert するテストが常設 | T1 | `test_shadowed_leaf_is_actually_unreachable`（`_unreachable` が全列 resolve の実測で数える） |
| G3 | 検出形 1–4 の一時違反ファイルが offenders 特定つき RED・クリーン tree で GREEN・陳腐化 assert 常設 | T2 | `test_no_signal_map_enumeration_in_src` / `test_stale_allowlist_entry_is_reported` ＋ Step 3-5 の sabotage（4→3→2→1→0） |
| G4 | `_evict_resolved` の解放が lock 外・両呼び出し経路・sabotage RED | T3 | `test_evicted_columns_are_freed_outside_the_lock[resolve_minting/unpinning]` ＋ Step 6 の sabotage（両方／片方ずつ） |
| G5 | 最長一致規則の実装が 1 箇所（検出と解決が同一実装を参照） | T1 | `test_detection_and_resolution_share_one_walk` ＋「G5 の境界」節（`has_column` は意図的除外） |
| G6 | CLAUDE.md/roadmap の CacheKey 行が是正 | T4 | Step 4 の grep（`E-4c へ継続` = 0 hits） |
| G7 | フルスイート・4 ゲート clean・既存挙動テスト（下段）無改変 | T4 | Step 5 の 4 ゲート ＋ Step 6 の `git diff --stat`（空） |

## 型・シグネチャの整合（タスク横断）

- `LeafHit.record: ColumnRecord` と `_ChannelHit.record: ColumnRecord` は**同じ型**。`_ChannelHit` は `LeafHit` に `path: ColumnPath | None` を足しただけの関係だが、**継承させない**（`NamedTuple` と `dataclass` で基底が違い、`_ChannelHit` の tuple 互換性を壊すと `channel_key_of` の呼び出し側に波及する）
- `_evict_resolved(self) -> list[Signal]` の `Signal` は `valisync.core.models.Signal`（`signal_group_manager.py:19` で既に import 済み・追加 import 不要）
- `_shadow_diagnostics` の第 1 引数は `Mapping[str, ColumnRecord]`。`load()` が渡すのは `dict[str, ColumnRecord]` なので共変で通る（`mypy src/` で確認）
- `owning_candidates` / `shadowed_leaf` は `column_names.py` の既存 import（`Iterator` / `Mapping` / `dataclass`）だけで書ける — 追加 import は不要
