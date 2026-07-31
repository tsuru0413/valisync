# E-4a: チャンネル単位サンプルキャッシュ（読み経路）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 同一物理チャンネルの複数列を **1 回の `select` ＋ k スライス**で満たし、広幅チャンネルの隣接 5 列プロットを **1,584 ms → 380 ms 以下**にする。

**Architecture:** デコード済み 2-D `samples` をプロセス単位のバイト上限 LRU (`ChannelSampleCache`) で共有する。`Session` が 1 個だけ所有し `MdfLoader` → `MdfHandle` へ注入するので、`LazyMdfValues` は `self._handle.cache` の 1 段で届く。列の切り出しは名前引き (`_flatten`) から**位置パス** (`ColumnPath`) へ移し、命中パスは**必ず基底を持たない独立配列**を返す。鋳造列 (`_resolved_by_key`) は GUI が push する pin 集合で保護し、pin 外を予算に応じて evict する。

**Tech Stack:** Python 3.13 / uv / PySide6 6.x / asammdf 8.8.22 / numpy / pytest ＋ pytest-qt

## Global Constraints

- 作業ディレクトリ `D:/Programming/projects/valisync`、ブランチ `feature/e4-channel-cache`。**main へ直接コミットしない**。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` すべて exit 0。
- 新規テストは **`demo_data/` に依存させない**（gitignore 済み・CI に生成ステップが無く module-level skipif で丸ごと skip される）。fixture は `tests/mdf4_helpers` ＋ `tmp_path`。
- **既存 assert を弱めない**。保存すべき契約: `handle.lock` はキャッシュヒットで取らない／`_closed` は読み直列化 lock の**外**で立てる／teardown の三軸ペーシング（64 MiB・8,000 信号・8ms・クロックは 32 信号ごと）と identity dedup 会計／records↔signals の 1:1／LD-14 リーフ名は永続キー。
- **各タスクは sabotage 必須**。到達範囲は主張でなく**実測**で確かめる。
- **`git checkout -- src/...` で sabotage を戻さない**（過去に実装者が自分の未コミット作業を消した）。pristine copy を保つか隔離コピーで行う。

## この増分で最も壊しやすい点（spec §5.4 = 敵対的レビュー Critical 1）

`_freeze`（`src/valisync/core/models/sample_source.py`）は `frozen = array.copy() if array.flags.writeable else array` で **read-only 入力を素通しする**。現行の miss パスが安全なのは `_flatten` の `np.ascontiguousarray` が必ず実コピーするからであって `_freeze` が守っているからではない。

共有キャッシュを read-only で持つと命中パスのスライスが **view のまま `_cache` に焼き付き**:

1. LRU が evict しても列 Signal が `base` 経由で保持し **RSS が 1 バイトも下がらない**
2. `nbytes_if_materialized` が実体の 1/1000 を返し **64 MiB のバイト軸が黙って死ぬ**
3. **「値一致」テストは view でも通る**ので両軸とも構造的に盲目

**命中パスは必ず `base is None` の独立配列を返すこと。**

## 確定事項（設計 spec より・全タスク遵守）

| # | 内容 |
|---|---|
| キー空間 | **`(id(handle), group_index, channel_index)`**。名前はキーに使わない（生名は LD-08 重複で一意でなく、表示名はファイル間で一意でない） |
| dtype | 広幅 1 本は **uint8 12000×1100 = 13.2 MB**（初版の float64 96 MB は 7.3× の誤り）。256 MB には ~19 本入るので **①gate は予算注入で evict を起こす**（D6） |
| pin | **GUI が push する**（`weakref` は使えない — VM は `signal_key: str` しか持たない）。対象は**全タブ・全パネル**の plotted entries。pin 済み鋳造列が抱える実体バイトは `Session.set_pinned_columns` が `ChannelSampleCache.set_reserved()` へ渡す（T3・下の D3 と同じ「裁定者は 1 人」） |
| pin 拒否 | **しない**。LRU の最低容量（1 チャンネル分）を無条件確保し、超過分は introspection に出す |
| oversize | 1 エントリ > 予算なら**キャッシュしない**が `skipped_oversize` で観測可能にする（D7） |
| D4 supersede | `_resolved_by_key` の「同一キー → 同一オブジェクト」を **「pin 中のみ保証」**へ。test-lock と docstring の更新を伴う**意図的 supersede** |
| D3 | エクスポートの作業予算は U3 の 256 MB と**同一**（裁定者は 1 人） |

## 位置パスが持ち込む帰結（T1 が担う）

位置パスを入れると**読み経路が `_flatten` を呼ばなくなる**。すると E-3 の全数ラウンドトリップ・オラクル（`tests/core/loaders/test_column_roundtrip.py`）が依拠していた「`_flatten` は production が使い続けるので反転を跨いで生き残る」という論拠が失われ、**誰も使わない関数と解決器を突き合わせる**形になる。

**橋渡しとして「`ColumnPath` の走査結果が `_flatten` の出力と順序込み・値込みで一致する」テストを T1 に置く。** これが `_flatten` と読み経路を繋ぎ止める唯一の紐なので、削除・弱体化してはならない。

## T0/T1 が新設する共有 API（シグネチャ厳守）

```python
# src/valisync/core/loaders/channel_cache.py （新規・T0）
CacheKey = tuple[int, int, int]  # (id(handle), group_index, channel_index)

class ChannelSampleCache:
    def __init__(self, budget_bytes: int = 256 * 1024 * 1024) -> None: ...
    def get(self, key: CacheKey) -> np.ndarray | None: ...
    def put(self, key: CacheKey, samples: np.ndarray) -> bool: ...
    def drop_handle(self, handle_id: int) -> tuple[np.ndarray, ...]: ...
    def set_reserved(self, reserved_bytes: int) -> None: ...   # 本番の呼び出し元は T3
    @property
    def hits(self) -> int: ...
    @property
    def misses(self) -> int: ...        # select 回数と 1:1（①gate の観測点）
    @property
    def evictions(self) -> int: ...
    @property
    def skipped_oversize(self) -> int: ...
    @property
    def bytes_held(self) -> int: ...

# src/valisync/core/loaders/column_names.py に追加（T1）
@dataclass(frozen=True, slots=True)
class ColumnPath:
    steps: tuple[str | int, ...]  # str = 構造化フィールド名 / int = 配列添字

def leaf_paths(spec: ColumnSpec) -> Iterator[tuple[str, ColumnPath]]: ...
    # (リーフ名サフィックス, 経路) を **_flatten と同一順序**で返す（全リーフ）
def apply_path(samples: np.ndarray, path: ColumnPath) -> np.ndarray: ...
    # **必ず base を持たない独立配列を返す**（spec §5.4）。さらに
    # **read-only で返す** — sample_source._freeze は read-only 入力を素通しするので、
    # ここで凍結しておくと列読みのコピーが 1 回で済む（writeable のまま返すと
    # apply_path の copy と _freeze の copy で毎列 2 回コピーする）
```

## タスクの依存順

```
[T0] ChannelSampleCache 単体 ─┐
                              ├─→ [T2] 読み経路をキャッシュ＋位置パスへ ─┬─→ [T3] pin 供給と evict
[T1] ColumnPath / apply_path ─┘   （C1 の所有権不変条件をここで pin）    ├─→ [T4] teardown 会計
                                                                        ├─→ [T5] 計測器＋実測
                                                                        └─→ [T6] realgui ①gate
```

T0/T1 は **production 未配線＝挙動不変**なので単独 merge 可。T2 が両者を配線して初めて値が動く（ただし**値は不変**であることが受け入れ条件）。

---

### Task 0: `ChannelSampleCache` 単体（production 未配線）

**Files:**
- Create: `src/valisync/core/loaders/channel_cache.py`
- Test: `tests/core/loaders/test_channel_cache.py`
- Modify: なし（`src/valisync/core/loaders/__init__.py:1-13` は**触らない** — `column_names` 同様、キュレートされた `__all__` に載せず T2 が完全パスで import する。ここを触ると「未配線」の構造的証明が弱まる）

**Interfaces:**
- Consumes: なし（T0 は依存グラフの起点。`numpy` / `threading` / `collections.OrderedDict` のみ）
- Produces（T2/T3/T4/T5/T6 がこれに対して書かれる・シグネチャ厳守）:
  - `CacheKey = tuple[int, int, int]` — `(id(handle), group_index, channel_index)`
  - `ChannelSampleCache(budget_bytes: int = 256 * 1024 * 1024)`
  - `ChannelSampleCache.get(key: CacheKey) -> np.ndarray | None`
  - `ChannelSampleCache.put(key: CacheKey, samples: np.ndarray) -> bool`
  - `ChannelSampleCache.drop_handle(handle_id: int) -> tuple[np.ndarray, ...]`
  - `ChannelSampleCache.set_reserved(reserved_bytes: int) -> None`
  - `ChannelSampleCache.hits / misses / evictions / skipped_oversize / bytes_held / reserved`（すべて `-> int` の read-only property）。`reserved` は T3 の pin 配線（`Session.set_pinned_columns` → `set_reserved`）が実際に効いているかの唯一の直接観測点
- 後続タスクへの契約（本タスクが docstring で固定する）:
  - `misses` は **select 呼び出し回数と 1:1**。ただし**等式が成り立つのはキャッシュが配線された経路（`Session` 経由）に限る** — `MdfLoader()`（引数なし）で作った handle は `cache is None` なので `get()` が呼ばれず `misses` は増えないまま `select` は毎回走る（T6 ①gate はこの数を観測点にするので、`Session` 経由であることが前提条件）
  - `drop_handle` は `MdfHandle.close()` の**前**に呼ぶ（T4 の close 順序・`id()` 再利用の前提条件）
  - `set_reserved` の **production の呼び出し元は T3 の `Session.set_pinned_columns`** ただ 1 つ（pin 済み鋳造列の実体バイト合計を渡す）。T0 の時点では未配線なので、本タスクのテストが唯一の執行点である
  - キャッシュは**コピーも凍結もしない**。所有権不変条件（spec §5.4）は切り出す側（T1 `apply_path` / T2 命中パス）の責務

---

- [ ] **Step 1: 失敗テストを書く**

まず**ベースラインを記録する**（Step 6 の「挙動不変」を主張でなく実測で示すため）:

```
uv run pytest -q 2>&1 | tail -3
```
→ 出た「N passed, M skipped」を控える。Step 6 で `N + 16 passed` になることを確認する。

`tests/core/loaders/test_channel_cache.py` を新規作成:

```python
"""ChannelSampleCache の LRU / 予算 / キー空間 / スレッド契約 (E-4a T0)。

**demo_data に依存しない**: 自然な宛先に見える ``test_lazy_mdf_values.py`` は
module-level の demo skipif (``demo_data/quick_demo.mf4``) を持ち、``demo_data/`` は
gitignore 済み・CI に生成ステップが無いため**丸ごと skip される** (同じ gate を持つ
ファイルは 5 本)。予算・LRU・キー空間はどれも ndarray を直接投入すれば検証でき、
実 mf4 を要さないので、CI 執行力のあるここに置く
(``test_mdf_handle_concurrency.py`` が同じ罠への既存対処)。

このファイルの時点でキャッシュは **production 未配線** — したがってここが
唯一の執行点であり、緑であることが「実装が効いている」の唯一の根拠になる。
"""

from __future__ import annotations

import threading
import time

import numpy as np

from valisync.core.loaders.channel_cache import CacheKey, ChannelSampleCache

_BOUND_S = 2.0  # 全ての待ちは有界 (デッドロック時にハングでなく失敗させる)


def _arr(nbytes: int) -> np.ndarray:
    """*nbytes* ちょうどの uint8 配列。

    uint8 は prod の広幅チャンネルと同じ dtype (spec §5.1: 12000x1100 = 13.2 MB。
    初版の float64 96 MB は 7.3 倍の誤り)。1 要素 = 1 バイトなので予算の境界を
    1 バイト単位で狙える。
    """
    return np.zeros(nbytes, dtype=np.uint8)


# ─── 基本 (ヒット/ミスと同一性) ────────────────────────────────────────────────


def test_get_on_absent_key_returns_none_and_counts_a_miss() -> None:
    cache = ChannelSampleCache(budget_bytes=1024)
    assert cache.get((1, 0, 0)) is None
    assert cache.misses == 1
    assert cache.hits == 0
    assert cache.bytes_held == 0


def test_put_then_get_returns_the_identical_array_and_counts_a_hit() -> None:
    """キャッシュはコピーしない — コピーすると予算が実質半分になる。

    同一性 (``is``) で pin するのが要点: 値一致だけだと「毎回コピーを返す」実装が
    緑のまま通り、予算の意味が消える。
    """
    cache = ChannelSampleCache(budget_bytes=1024)
    arr = _arr(64)
    assert cache.put((1, 0, 0), arr) is True
    assert cache.get((1, 0, 0)) is arr
    assert cache.hits == 1
    assert cache.misses == 0
    assert cache.bytes_held == 64


# ─── キー空間 (spec §5.3 / レビュー C2) ────────────────────────────────────────


def test_key_separates_handle_group_and_channel() -> None:
    """キーの 3 成分すべてが効いていること。

    生名は LD-08 重複で一意でなく (既存 fixture ``Mat2`` がその形)、表示名は
    ファイル間で一意でない。どれか 1 成分でも落とすと「別チャンネルの値を返す」=
    長さが同じなら sample_source の長さ検証も通り例外も出ない**サイレント誤データ**
    になる。3 つの変種はそれぞれ 1 成分だけを base から変えてある。
    """
    cache = ChannelSampleCache(budget_bytes=4096)
    keys: list[CacheKey] = [(7, 1, 2), (8, 1, 2), (7, 9, 2), (7, 1, 9)]
    arrays = {k: _arr(16) for k in keys}
    for key, arr in arrays.items():
        assert cache.put(key, arr) is True
    for key, arr in arrays.items():
        assert cache.get(key) is arr, key
    assert cache.bytes_held == 64


# ─── LRU 順序 ─────────────────────────────────────────────────────────────────


def test_lru_evicts_least_recently_used_not_first_inserted() -> None:
    """FIFO と LRU を区別する: ``get`` で温めた古いエントリは生き残る。

    予算 200 に 100 バイトが 2 本ちょうど入る形にしてある (3 本目で必ず 1 本落ちる)。
    """
    cache = ChannelSampleCache(budget_bytes=200)
    a, b, c = _arr(100), _arr(100), _arr(100)
    assert cache.put((1, 0, 0), a) is True
    assert cache.put((1, 0, 1), b) is True
    assert cache.get((1, 0, 0)) is a  # A を最近使用へ (FIFO ならここが効かない)
    assert cache.put((1, 0, 2), c) is True
    assert cache.evictions == 1
    assert cache.bytes_held == 200
    assert cache.get((1, 0, 1)) is None  # 最も長く使われていない B が落ちた
    assert cache.get((1, 0, 0)) is a  # 温めた A は残る


# ─── reserved (pin 済み分) ────────────────────────────────────────────────────


def test_reserved_bytes_shrink_the_lru_capacity() -> None:
    """pin 済みを引いた残りだけが LRU の容量 (spec §5.5)。

    ``set_reserved`` は登録と同時に縮める — 次の ``put`` まで待つと「プロットしたまま
    放置」のワークフローで超過が残り続け、飽和後 USS +256 MB 以内 (spec §9) が破れる。
    """
    cache = ChannelSampleCache(budget_bytes=300)
    a, b = _arr(100), _arr(100)
    cache.put((1, 0, 0), a)
    cache.put((1, 0, 1), b)
    assert cache.bytes_held == 200
    assert cache.evictions == 0

    cache.set_reserved(150)  # LRU が使えるのは 300-150 = 150

    assert cache.reserved == 150  # T3 の pin 配線が効いたかを見る唯一の直接観測点
    assert cache.evictions == 1
    assert cache.bytes_held == 100
    assert cache.get((1, 0, 0)) is None  # 古い方から落ちる
    assert cache.get((1, 0, 1)) is b


def test_reserved_bytes_also_bound_the_capacity_at_put_time() -> None:
    """``put`` 側も reserved を見る (set_reserved 時の trim だけでは不十分)。

    pin が先に立っている状態で新しい列を読む = プロット中にブラウザで別列を覗く
    経路であり、production ではこちらの方が多い。
    """
    cache = ChannelSampleCache(budget_bytes=300)
    cache.set_reserved(150)
    a, b = _arr(100), _arr(100)
    assert cache.put((1, 0, 0), a) is True
    assert cache.put((1, 0, 1), b) is True  # 容量 150 -> A を落として載る
    assert cache.evictions == 1
    assert cache.bytes_held == 100
    assert cache.get((1, 0, 0)) is None
    assert cache.get((1, 0, 1)) is b


def test_reserved_never_starves_the_lru_below_one_channel() -> None:
    """pin が予算を食い尽くしても LRU 容量を 0 にしない (spec §5.5: pin は拒否しない)。

    容量 0 にすると「載せて即落とす」無駄な往復になり、再描画ごとのフルチャンネル
    再読み (実測 316 ms/列) が復活する。最低容量の定義は「今 LRU が保持しようと
    している最も新しい 1 エントリ」。
    """
    cache = ChannelSampleCache(budget_bytes=300)
    cache.set_reserved(300)  # 予算を pin が使い切った

    first = _arr(100)
    assert cache.put((1, 0, 0), first) is True  # 拒否しない
    assert cache.skipped_oversize == 0  # oversize でもない
    assert cache.get((1, 0, 0)) is first  # 即落としもしない
    assert cache.bytes_held == 100

    second = _arr(100)
    assert cache.put((1, 0, 1), second) is True
    assert cache.bytes_held == 100  # 常に 1 本ぶんだけ
    assert cache.get((1, 0, 0)) is None
    assert cache.get((1, 0, 1)) is second


def test_set_reserved_keeps_the_newest_entry_even_when_pins_eat_the_budget() -> None:
    """最低容量の規則は ``set_reserved`` 側でも同じ (その時点の最新エントリ)。"""
    cache = ChannelSampleCache(budget_bytes=300)
    a, b = _arr(100), _arr(100)
    cache.put((1, 0, 0), a)
    cache.put((1, 0, 1), b)

    cache.set_reserved(1_000)  # 予算そのものを超える pin

    assert cache.bytes_held == 100
    assert cache.get((1, 0, 1)) is b  # 最近使用の 1 本は残る
    assert cache.get((1, 0, 0)) is None


# ─── oversize (D7) ───────────────────────────────────────────────────────────


def test_oversize_entry_is_not_cached_and_is_counted() -> None:
    """1 エントリが予算超なら載せない (D7)。

    載せると他を全部追い出したうえで自分も次の put で落ちるだけで、キャッシュを
    空にする代償に何も得られない。ただし静かに遅いままにするのは罠なので
    ``skipped_oversize`` で観測可能にする。
    """
    cache = ChannelSampleCache(budget_bytes=100)
    big = _arr(101)
    assert cache.put((1, 0, 0), big) is False
    assert cache.skipped_oversize == 1
    assert cache.bytes_held == 0
    assert cache.evictions == 0
    assert cache.get((1, 0, 0)) is None


def test_oversize_put_does_not_evict_the_existing_contents() -> None:
    """oversize は「入らない」だけ — 既にある席を空けさせてはならない。

    最低容量が「今入れようとしているエントリ」である以上、D7 のガードが無いと
    oversize が capacity を自分のサイズまで押し上げて既存を全部追い出す。
    """
    cache = ChannelSampleCache(budget_bytes=100)
    kept = _arr(60)
    cache.put((1, 0, 0), kept)
    assert cache.put((1, 0, 1), _arr(400)) is False
    assert cache.get((1, 0, 0)) is kept
    assert cache.bytes_held == 60
    assert cache.evictions == 0


# ─── バイト会計 ───────────────────────────────────────────────────────────────


def test_reput_of_the_same_key_replaces_without_double_counting() -> None:
    """同一キーの再投入は「引いてから足す」(差分加算でない)。

    素朴な ``self._bytes_held += size`` は、サイズの違う配列で上書きされた瞬間に
    会計が実体から乖離し、以後 evict が過剰/過少になる。
    """
    cache = ChannelSampleCache(budget_bytes=1000)
    first, second = _arr(100), _arr(250)
    cache.put((1, 0, 0), first)
    cache.put((1, 0, 0), second)
    assert cache.bytes_held == 250
    assert cache.get((1, 0, 0)) is second
    assert cache.evictions == 0


def test_hit_and_miss_counters_move_only_on_get() -> None:
    """hits/misses を動かすのは ``get`` だけ。

    「miss 数 == select 回数」が T6 ①gate の観測点なので、put/drop が混ざると
    数が読めなくなる (evictions は逆に put 側でだけ動く)。
    """
    cache = ChannelSampleCache(budget_bytes=100)
    cache.put((1, 0, 0), _arr(40))
    cache.put((1, 0, 1), _arr(40))
    cache.put((1, 0, 2), _arr(40))  # ここで 1 本落ちる
    cache.drop_handle(1)
    assert cache.hits == 0
    assert cache.misses == 0
    assert cache.evictions == 1


# ─── drop_handle (unload・spec §5.7) ─────────────────────────────────────────


def test_drop_handle_returns_the_arrays_and_leaves_other_files_alone() -> None:
    """unload は 2-D 配列を**捨てず返す** (spec §5.7)。

    1 本 13.2 MB を同期解放すると FU-16 のフリーズに戻るので、呼び出し側 (T4) が
    ``RemovalResult.cached_arrays`` 経由で teardown の三軸ペーシングへ渡す。
    予算圧ではないので ``evictions`` は増やさない (混ぜると予算の効きが読めなくなる)。
    """
    cache = ChannelSampleCache(budget_bytes=4096)
    a0, a1, other = _arr(16), _arr(32), _arr(64)
    cache.put((7, 0, 0), a0)
    cache.put((7, 1, 5), a1)
    cache.put((8, 0, 0), other)

    dropped = cache.drop_handle(7)

    assert {id(arr) for arr in dropped} == {id(a0), id(a1)}
    assert cache.bytes_held == 64
    assert cache.evictions == 0
    assert cache.get((8, 0, 0)) is other  # 別ファイルは無傷
    assert cache.get((7, 0, 0)) is None


def test_drop_handle_of_unknown_file_is_a_no_op() -> None:
    cache = ChannelSampleCache(budget_bytes=4096)
    kept = _arr(16)
    cache.put((7, 0, 0), kept)
    assert cache.drop_handle(9) == ()
    assert cache.bytes_held == 16
    assert cache.get((7, 0, 0)) is kept


def test_drop_handle_makes_a_recycled_handle_id_safe() -> None:
    """``id()`` は生存中のオブジェクト間でのみ一意 — 閉じたハンドルの id は次の
    ロードが再利用しうる (実測 100% 再利用・memory gui_id_reuse_flake_object_recreation)。

    キー一意性の前提条件は「close の**前**に drop_handle で外す」であり、これが
    T4 の close 順序を要求する理由。外さないと、新しいハンドルが同じ id を得た
    瞬間に別ファイルのデコード結果を返す。
    """
    cache = ChannelSampleCache(budget_bytes=1000)
    old = _arr(32)
    cache.put((7, 0, 0), old)

    dropped = cache.drop_handle(7)
    assert len(dropped) == 1
    assert dropped[0] is old
    assert cache.bytes_held == 0

    fresh = _arr(32)  # 同じ id を得た別ファイル
    cache.put((7, 0, 0), fresh)
    assert cache.get((7, 0, 0)) is fresh
    assert cache.bytes_held == 32


# ─── スレッド契約 (spec §5.8 / レビュー I6) ──────────────────────────────────


class _InterleavedCache(ChannelSampleCache):
    """``_bytes_held`` の「読み」と「書き」の間に決定的な引き渡し点を作る。

    lock が無いと 2 スレッドの read-modify-write が同じ古い値を読み、片方の加算が
    消える (lost update)。素朴な並行 put ではこの窓に落ちない — 同型の
    ``_InterleavedHandle`` (test_mdf_handle_concurrency.py) が 17,000 試行 0 ヒットを
    実測しており、Windows の GIL 引き渡しは数バイトコードの窓に入らない。だから
    窓を明示的に開ける。

    罠 (a): yield は基底スロットを**読んだ後**に置く。先頭で yield すると壊れた
            実装でも合計が合ってしまう。
    罠 (b): 引き渡しは**有界待ち**にする。素の wait() だと修正後の実装が
            デッドロックしたときテストがハングする。
    """

    def __init__(
        self, gate: threading.Event, resumed: threading.Event, budget_bytes: int
    ) -> None:
        # 基底 __init__ が _bytes_held を書く (= setter が走る) 前に用意する。
        self._gate = gate
        self._resumed = resumed
        self._yielded = False
        super().__init__(budget_bytes=budget_bytes)

    @property  # type: ignore[override]
    def _bytes_held(self) -> int:
        value: int = ChannelSampleCache._bytes_held.__get__(self)  # type: ignore[attr-defined] # ← 先に読む
        if not self._yielded:
            self._yielded = True
            self._gate.set()
            self._resumed.wait(0.5)
        return value

    @_bytes_held.setter
    def _bytes_held(self, value: int) -> None:
        ChannelSampleCache._bytes_held.__set__(self, value)  # type: ignore[attr-defined]


def test_byte_accounting_survives_concurrent_puts() -> None:
    """予算の増減はキャッシュ自身の lock で守る (spec §5.8)。

    予算は**プロセス単位**・``handle.lock`` は**ファイル単位**なので後者では守れない。
    かつ「キャッシュヒットは handle.lock を取らない」は E-3 の test-lock (spec §11)
    なので、ここで handle.lock を取る選択肢は最初から無い。
    """
    gate, resumed = threading.Event(), threading.Event()
    cache = _InterleavedCache(gate, resumed, budget_bytes=10_000)
    a, b = _arr(100), _arr(250)

    ta = threading.Thread(target=cache.put, args=((1, 0, 0), a))
    ta.start()
    assert gate.wait(1.0), "A が _bytes_held を読む前に止まった (setup 失敗)"
    tb = threading.Thread(target=cache.put, args=((1, 0, 1), b))
    tb.start()
    time.sleep(0.05)  # lock が無ければ B はここで加算まで走り抜ける
    resumed.set()
    ta.join(timeout=_BOUND_S)
    tb.join(timeout=_BOUND_S)

    assert not ta.is_alive() and not tb.is_alive(), (
        "引き渡しがハングした — 有界待ちが効いていない"
    )
    assert cache.bytes_held == 350, "lost update (A か B の加算が消えた)"
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_channel_cache.py -q`

Expected: 収集エラーで FAIL —
`ModuleNotFoundError: No module named 'valisync.core.loaders.channel_cache'`
（`ERROR tests/core/loaders/test_channel_cache.py` の 1 error。個々のテストは 1 件も実行されない）

- [ ] **Step 3: 実装**

`src/valisync/core/loaders/channel_cache.py` を新規作成:

```python
"""デコード済みチャンネル samples のプロセス単位 LRU (E-4a・spec §5)。

E-3 は Signal オブジェクト数を根治した (264,004 -> 4,324) が、列読みの対話コストは
1 ミリ秒も動いていない: LazyMdfValues.array() が列ごとに「全チャンネル select ＋
全リーフ _flatten」をやり直すままだから (実測 309-327 ms/列・5 列で 1,584 ms)。
兄弟列の比較 (Radar.ObjList.dx[0..k]) は同じ 1 本の物理チャンネルを何度も
デコードする形なので、デコード結果そのものをプロセス単位で持ち回す。

上限は時間でなく**バイト**にする (ユーザー決定 U2/U3・256 MB): 時間ベースは
テストが時計依存になる。**予算の裁定者はこのクラス 1 つだけ**にする (spec §5.2) —
2 人いると互いの解放を当てにして両方が上限を超える。
"""

from __future__ import annotations

import threading
from collections import OrderedDict

import numpy as np

CacheKey = tuple[int, int, int]
"""キー = ``(id(handle), group_index, channel_index)``。

**名前をキーにしない** (spec §5.3): 生名は LD-08 重複で一意でなく (mdf_loader の
``name_total[base_name] > 1`` — 既存 fixture ``Mat2`` がその形)、表示名はファイル間で
一意でない。``Session`` は 1 キャッシュを全ファイルで共有するので、handle を含めないと
2 ファイル比較で同じ曲線が 2 本描かれる (長さが同じなら sample_source の長さ検証も
通り、例外も出ない = サイレント誤データ)。

**前提条件**: ``id()`` は生存中のオブジェクト間でのみ一意で、閉じたハンドルの id は
次のロードが再利用しうる (実測 100% 再利用・memory gui_id_reuse_flake_object_recreation)。
``MdfHandle.close()`` の**前**に ``drop_handle()`` でそのファイルのエントリを外すことが
キー一意性の前提になる。
"""

_DEFAULT_BUDGET_BYTES = 256 * 1024 * 1024  # ユーザー決定 U3


class ChannelSampleCache:
    """デコード済みチャンネル samples のバイト予算つき LRU。

    **コピーも凍結もしない** — 呼び出し側が渡した配列そのものを保持し、そのまま返す
    (コピーすると予算が実質半分になる)。したがって載せた配列を呼び出し側が書き換えて
    はならない。命中パスのスライスが view を焼き付けないための所有権不変条件
    (spec §5.4) は**切り出す側** (``apply_path`` / 命中パス) の責務であって、ここではない。

    **``handle.lock`` は絶対に取らない** (spec §11 の保存契約: 「キャッシュヒットは
    handle.lock を取らない」は E-3 の test-lock)。予算はプロセス単位・``handle.lock`` は
    ファイル単位なので後者では守れない。このクラスが見るのは ``id(handle)`` の int だけで
    ハンドル自体を参照しないため、構造的に取りようがない。予算の増減は自前の小さな
    lock で守る (``MdfHandle._close_lock`` と同型・読み直列化 lock とは別物)。
    ロック順は ``handle.lock`` -> ``_lock`` の一方向のみで、逆順を作る API は置かない
    (このクラスは ndarray しか触らないので I/O を lock 下で呼ぶ経路が無い)。

    evict した配列は**その場で同期解放する** (unload の ``drop_handle`` と違い teardown へ
    渡さない): 1 エントリ 13.2 MB で 1 ms 未満と見込まれる (spec §5.7 — **実測は T4
    Step 5**。T5 の飽和計測はそこで確定した値を実 GUI 経路でも刷る)。
    """

    __slots__ = (
        "_budget",
        "_bytes_held",
        "_entries",
        "_evictions",
        "_hits",
        "_lock",
        "_misses",
        "_reserved",
        "_skipped_oversize",
    )

    def __init__(self, budget_bytes: int = _DEFAULT_BUDGET_BYTES) -> None:
        self._budget = budget_bytes
        # OrderedDict が LRU 順序そのもの (末尾 = 最近使用)。
        self._entries: OrderedDict[CacheKey, np.ndarray] = OrderedDict()
        self._bytes_held = 0
        self._reserved = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._skipped_oversize = 0
        self._lock = threading.Lock()

    def get(self, key: CacheKey) -> np.ndarray | None:
        """命中なら配列 (最近使用へ更新)、不在なら None。

        不在は ``misses`` を 1 増やす。**miss 数と select 呼び出し回数は 1:1** —
        production が select を呼ぶ唯一の理由がここの None であり、miss の後は必ず
        1 回だけデコードするため (oversize で ``put`` が False を返しても、その
        チャンネルは次回また miss + select になるので 1:1 は保たれる)。
        T6 の ①gate はこの数を観測点にする (spec §8)。

        **等式が成り立つのはキャッシュが配線された経路 (``Session`` 経由) に限る**:
        ``MdfLoader()`` を引数なしで使う構成では ``MdfHandle.cache`` が None になり、
        ``LazyMdfValues.array()`` はここを一度も通らない — ``misses`` は 0 のまま
        ``select`` だけが毎回走る。観測点として使う側はその構成でないことを
        setup で確かめること (T6 は ``Session`` 経由・T3 の ``wide`` fixture は
        ``MdfLoader(cache=ChannelSampleCache())`` を明示的に渡している)。
        """
        with self._lock:
            arr = self._entries.get(key)
            if arr is None:
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return arr

    def put(self, key: CacheKey, samples: np.ndarray) -> bool:
        """*samples* を載せる。載せたら True、oversize で見送ったら False。

        1 エントリが予算 (reserved を引く前の全体) を超える場合は**載せない** (D7):
        載せると他を全部追い出したうえで自分も次の put で落ちるだけで、キャッシュを
        空にする代償に何も得られない。静かに遅いままにするのは罠なので
        ``skipped_oversize`` で観測可能にする。
        """
        size = int(samples.nbytes)  # 会計は nbytes のみ (lock の外で済ませる)
        with self._lock:
            if size > self._budget:
                self._skipped_oversize += 1
                return False
            old = self._entries.pop(key, None)
            if old is not None:
                # 同一キーの入れ替え。差分加算でなく「引いてから足す」— サイズの違う
                # 配列で上書きされたときに会計が実体から乖離しないため。
                self._bytes_held -= int(old.nbytes)
            capacity = self._capacity_for(size)
            while self._entries and self._bytes_held + size > capacity:
                self._evict_oldest()
            self._entries[key] = samples
            self._bytes_held += size
            return True

    def set_reserved(self, reserved_bytes: int) -> None:
        """pin 済み (``_resolved_by_key`` が保持中) のバイト数を登録する。

        **production の呼び出し元は ``Session.set_pinned_columns`` ただ 1 つ** (T3)。
        pin した鋳造列は所有権不変条件 (spec §5.4) により**自前の独立配列**を抱えて
        おり、それは ``bytes_held`` とは別に同じ U3 256 MB を食う。予算の裁定者を
        1 人にする (spec §5.2) とは、その両方をこのクラスが同時に見るということで
        あり、pin 側を渡さなければ「2 人が互いの解放を当てにして両方が上限を超える」
        形に戻る。

        LRU が使えるのは ``budget - reserved``。**最低容量は「今 LRU が保持しようと
        している最も新しい 1 エントリ」のサイズ**で、reserved が予算を食い尽くしても
        そこまでは落とさない (spec §5.5: pin は拒否しない・LRU の最低容量 1 物理
        チャンネル分は無条件確保)。容量 0 にすると「載せて即落とす」往復になり、
        再描画ごとのフルチャンネル再読み (316 ms/列) が復活する。

        登録と同時に縮めるのは、次の ``put`` まで待つと「プロットしたまま放置」で
        超過が残り続け、飽和後 USS +256 MB 以内 (spec §9) が破れるから。
        """
        with self._lock:
            self._reserved = max(0, reserved_bytes)
            if not self._entries:
                return
            newest = int(next(reversed(self._entries.values())).nbytes)
            capacity = self._capacity_for(newest)
            while self._entries and self._bytes_held > capacity:
                self._evict_oldest()

    def drop_handle(self, handle_id: int) -> tuple[np.ndarray, ...]:
        """*handle_id* のファイルのエントリを外して**返す** (捨てない・spec §5.7)。

        返すのは teardown へ渡すため: 2-D 配列は 1 本 13.2 MB あり、ここで参照を
        落とすと unload の同期解放へ戻る (FU-16 のフリーズ)。呼び出し側が
        ``RemovalResult.cached_arrays`` に載せ ``TeardownService`` の三軸ペーシングへ通す。

        **``MdfHandle.close()`` より前に呼ぶこと**: 逆順だと teardown へ渡す前に
        キャッシュだけが取り残され会計から漏れる。加えて ``CacheKey`` の一意性自体が
        「close 前に外すこと」を前提にしている (id 再利用)。

        eviction ではないので ``evictions`` は増やさない — 予算圧と unload を混ぜると
        予算の効きが読めなくなる。
        """
        with self._lock:
            hit = [key for key in self._entries if key[0] == handle_id]
            dropped = []
            for key in hit:
                arr = self._entries.pop(key)
                self._bytes_held -= int(arr.nbytes)
                dropped.append(arr)
            return tuple(dropped)

    # ─── introspection (非侵襲・spec §8) ──────────────────────────────────────
    # LRU 順序を動かさず lock も取らない: int の読みは GIL 下で atomic であり、
    # lock を取ると in-flight な put を待つ = 観測が挙動を変える。

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        """キャッシュミス回数 = **select 呼び出し回数** (``get`` の docstring 参照)。

        1:1 が成り立つのは cache が配線された経路のみ (``cache is None`` の構成では
        ``get`` を通らないので 0 のまま select だけが走る)。
        """
        return self._misses

    @property
    def evictions(self) -> int:
        """予算圧で落とした本数 (``drop_handle`` の unload は含まない)."""
        return self._evictions

    @property
    def skipped_oversize(self) -> int:
        """予算超で載せなかった回数 (D7 — 静かに遅いままにしないための観測点)."""
        return self._skipped_oversize

    @property
    def reserved(self) -> int:
        """pin 済み分として登録されているバイト数 (``set_reserved`` の最後の値)。

        T3 が ``Session.set_pinned_columns`` からここへ配線したことを**直接**見る口。
        効果 (LRU 容量の縮み) だけを観測しようとすると、pin が予算に対して小さい
        production 相当の構成では何も起きず、配線が外れても緑のまま通る。
        """
        return self._reserved

    @property
    def bytes_held(self) -> int:
        """保持中のバイト数 (= 各エントリの ``samples.nbytes`` の総和)。

        **identity dedup (teardown の ``seen`` set) は要らない**: teardown があれを
        持つのは 1 グループの master 配列が全信号で identity 共有されるからで
        (prod_demo で実体 0.2 MiB を 10,316 MiB と誤計上した)、ここに載るのは
        物理チャンネル 1 本を select して得た専用の配列であり、キー (handle, gi, ci) が
        その 1 本を一意に指す。異なるキーが同じ配列オブジェクトを指す経路は
        production に無い。同一キーの再 put だけは起こりうるので ``put`` が
        「引いてから足す」で二重計上を防ぐ。
        """
        return self._bytes_held

    # ─── 内部 (すべて _lock 保持前提) ────────────────────────────────────────

    def _capacity_for(self, floor_bytes: int) -> int:
        """LRU が使ってよいバイト数。``floor_bytes`` は無条件に確保する最低容量。"""
        return max(self._budget - self._reserved, floor_bytes)

    def _evict_oldest(self) -> None:
        """LRU の先頭 (最も長く使われていない 1 本) を落とす。"""
        _key, arr = self._entries.popitem(last=False)
        self._bytes_held -= int(arr.nbytes)
        self._evictions += 1
```

- [ ] **Step 4: 通ることを確認**

```
uv run pytest tests/core/loaders/test_channel_cache.py -q
```
Expected: `16 passed`

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

**まず pristine copy を取る。`git checkout -- src/...` で戻してはならない**（過去に実装者が自分の未コミット作業を消している）:

```
cp src/valisync/core/loaders/channel_cache.py "$SCRATCH/channel_cache.py.orig"
```
（`$SCRATCH` = `C:/Users/trtrm/AppData/Local/Temp/claude/D--Programming-projects-valisync/<session>/scratchpad`）
各 sabotage 後は `cp "$SCRATCH/channel_cache.py.orig" src/valisync/core/loaders/channel_cache.py` で復元し、
復元直後に `uv run pytest tests/core/loaders/test_channel_cache.py -q` が 16 passed に戻ることを確認してから次へ進む。

**到達範囲は主張でなく実測で確かめる**: 各 sabotage で「予測 RED 集合」を先に書き、
`uv run pytest tests/core/loaders/test_channel_cache.py -q -rf` の**実際の failed 一覧**と突き合わせる。
一致しなければ**予測かテストのどちらかが誤り**なので、そのまま進めず原因を特定して報告に書く
（このリポジトリでは「到達範囲の主張が誤っていた sabotage」を過去 3 件実測で摘出している）。

| # | 壊す箇所（正確な編集） | 予測 RED |
|---|---|---|
| S1 | `get` 内の `self._entries.move_to_end(key)` を削除（LRU -> FIFO） | `test_lru_evicts_least_recently_used_not_first_inserted` の**1 件のみ**（他は get を最後にしか呼ばないので順序に依存しない） |
| S2 | `set_reserved` の本体を `with self._lock: pass` にする（reserved を記録も trim もしない） | `test_reserved_bytes_shrink_the_lru_capacity` / `test_reserved_bytes_also_bound_the_capacity_at_put_time` / `test_reserved_never_starves_the_lru_below_one_channel` / `test_set_reserved_keeps_the_newest_entry_even_when_pins_eat_the_budget` の **4 件**（最後の 1 件は「予算超 pin でも 1 本残す」が消えて 200 バイト残る形で落ちる） |
| S3 | `put` の `if size > self._budget:` ブロック（3 行）を丸ごと削除（oversize を載せる） | `test_oversize_entry_is_not_cached_and_is_counted` / `test_oversize_put_does_not_evict_the_existing_contents` の **2 件**。後者は D7 の失敗モードそのもの — 最低容量が oversize 自身のサイズまで押し上がり既存 60 バイトが追い出される |
| S4 | `put` の `with self._lock:` を削除し本体を 1 段デデント（lock を外す） | `test_byte_accounting_survives_concurrent_puts` の**1 件のみ**（残り 15 件は単一スレッドなので無関係）。B が古い 0 を読んで加算し A が上書きするため `bytes_held == 100`（350 でない） |
| S5 | `get` と `put` の先頭にそれぞれ `key = (0, key[1], key[2])` を挿入（キーから handle を落とす） | `test_key_separates_handle_group_and_channel` / `test_drop_handle_returns_the_arrays_and_leaves_other_files_alone` / `test_drop_handle_makes_a_recycled_handle_id_safe` の **3 件**。`test_drop_handle_of_unknown_file_is_a_no_op` と `test_hit_and_miss_counters_move_only_on_get` は**緑のまま**（前者は正規化後も get が同じキーに落ち、後者は drop の結果を見ていない）— この 2 件が緑であることまで含めて実測と一致させる |

**「production 未配線」の実測**（T0 の独立受理の根拠そのもの・主張で済ませない）:

```
grep -rn "channel_cache\|ChannelSampleCache" src/ scripts/ | grep -v "^src/valisync/core/loaders/channel_cache.py"
```
Expected: **0 件**（新ファイル自身以外に参照が無い = 挙動不変の構造的証明）。
加えて S1 を当てた状態で `uv run pytest -q 2>&1 | tail -3` を回し、
**failed が `tests/core/loaders/test_channel_cache.py` 内だけ**であることを確認する
（新ファイル外に 1 件でも RED が出たら「未配線」が偽 = 直ちに調査）。

- [ ] **Step 6: ゲート＋コミット**

sabotage をすべて復元した状態で:

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

`uv run pytest -q` の passed 数が **Step 1 で控えたベースライン + 16** になっていること
（増減があれば挙動不変が破れている — skip 数も含めて突き合わせる）。

```
git add src/valisync/core/loaders/channel_cache.py tests/core/loaders/test_channel_cache.py
git commit -m "$(cat <<'EOF'
feat(core): ChannelSampleCache (バイト予算つき LRU) を新設 (production 未配線)

E-4a の土台。デコード済みチャンネル samples をプロセス単位で持ち回す LRU を
単体で先に作る (この時点では誰も import しないので挙動は完全に不変)。

キー空間は (id(handle), group_index, channel_index) で固定 (spec §5.3)。名前は
キーにしない — 生名は LD-08 重複で一意でなく (fixture Mat2 がその形)、表示名は
ファイル間で一意でないので、handle を含めないと 2 ファイル比較で同じ曲線が 2 本
描かれる (長さが同じなら長さ検証も通り例外も出ないサイレント誤データ)。id は
生存中のみ一意なので「close の前に drop_handle」がキー一意性の前提条件になる。

予算規則: バイト上限 LRU (ユーザー決定 U2/U3)。set_reserved で pin 済み分を引き、
LRU が使えるのは budget - reserved。ただし**最低容量 = 今保持しようとしている最も
新しい 1 エントリ**を無条件に確保する (spec §5.5: pin は拒否しない — 容量 0 は
「載せて即落とす」往復になり再描画ごと 316 ms 停止が復活する)。1 エントリが予算超
なら載せず skipped_oversize を増やす (D7)。

drop_handle は配列を捨てず返す (spec §5.7) — 1 本 13.2 MB を同期解放すると FU-16 の
フリーズに戻るので、呼び出し側が teardown の三軸ペーシングへ渡す。unload は予算圧
ではないので evictions には数えない。

スレッド契約 (spec §5.8): 予算の増減は自前の小さな lock で守る (MdfHandle._close_lock
と同型)。handle.lock は取らない — 予算はプロセス単位・handle.lock はファイル単位で
守れず、かつ「キャッシュヒットは handle.lock を取らない」は E-3 の test-lock (spec §11)。
このクラスは id(handle) の int しか見ないので構造的に取りようがない。

コピーも凍結もしない (コピーすると予算が実質半分)。命中パスの所有権不変条件
(spec §5.4) は切り出す側の責務であり、ここではない。

テスト 16 本 (Qt 非依存・demo_data 非依存で CI 執行力あり)。sabotage 実測:
LRU->FIFO=1 RED / set_reserved 無視=4 RED / oversize 受理=2 RED / lock 除去=1 RED /
キーから handle 除去=3 RED。lock の検証は _InterleavedHandle と同型の決定的
引き渡し点で行う (素朴な並行 put は Windows の GIL 引き渡し粒度では窓に落ちない)。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 1: `ColumnPath` / `leaf_paths` / `apply_path`（位置ベース selector の基盤・production 未配線）

**Files:**
- Modify: `src/valisync/core/loaders/column_names.py:8`（モジュール docstring に位置の軸を追記）
- Modify: `src/valisync/core/loaders/column_names.py:96`（`leaf_count` の直後・`parse_leaf` の直前へ挿入）
- Test: `tests/core/loaders/test_column_names.py:12`（import 追加）＋末尾へ合成ケースの 3 本を追加
- Test: `tests/core/loaders/test_column_paths.py`（新規・実 mf4 の紐と所有権）

本タスクは **production を一切配線しない**（`sample_source.py` / `mdf_loader.py` は無変更）。挙動不変＝既存テストは全数そのまま緑でなければならない。
`tests/core/loaders/test_column_roundtrip.py` は **触らない** — 読み経路が `_flatten` を呼ばなくなるのは T2 であり、現時点では同モジュールの「`_flatten` は production が使い続ける」という論拠はまだ真である。その論拠を引き継ぐ紐を先に置くのが本タスクの役割で、roundtrip 側の docstring 更新は T2 が持つ。

**Interfaces:**
- Consumes: T0 とは**独立**（依存無し・並行実行可）。既存の `ColumnSpec` / `spec_from_probe(arr: np.ndarray) -> ColumnSpec` / `leaf_names(base: str, spec: ColumnSpec) -> Iterator[str]`（`core/loaders/column_names.py`）と、テストのオラクルとして `_flatten(name: str, arr: np.ndarray) -> list[tuple[str, np.ndarray]]`（`core/loaders/mdf_loader.py`）。
- Produces（T2 が against して書く）:
  - `ColumnPath`（`@dataclass(frozen=True, slots=True)`・フィールド `steps: tuple[str | int, ...]`・hashable）
  - `leaf_paths(spec: ColumnSpec) -> Iterator[tuple[str, ColumnPath]]` — `(リーフ名サフィックス, 経路)` を `_flatten` と同一順序・**全リーフ空間**で生成。列キー全体は `base + suffix`。
  - `apply_path(samples: np.ndarray, path: ColumnPath) -> np.ndarray` — **必ず `base is None`** の配列を返す。さらに自分が作った配列は **read-only にして返す**（`sample_source._freeze` が read-only 入力を素通しするので、列読みのコピーが **1 回**で済む。writeable のまま返すと `apply_path` の copy と `_freeze` の copy で毎列 2 回コピーする — T2 が縮めようとしているホットパスそのもの）。

---

- [ ] **Step 1: 失敗テストを書く**

**(a) `tests/core/loaders/test_column_names.py`** — import 行（現在 5–12 行目）を差し替える。

```python
from valisync.core.loaders.column_names import (
    ColumnPath,
    ColumnSpec,
    apply_path,
    leaf_count,
    leaf_names,
    leaf_paths,
    parse_leaf,
    spec_from_probe,
)
from valisync.core.loaders.mdf_loader import _all_leaf_count, _flatten
```

同ファイルの末尾（`test_all_leaf_count_counts_all_leaves_including_non_numeric` の後）へ追加する。

```python
def test_leaf_paths_walk_all_leaves_in_flatten_order() -> None:
    """``leaf_paths`` は ``_flatten`` と同じ**全リーフ**空間・同じ順序 (数値だけではない)。

    ``test_leaf_names_order_matches_flatten`` と同じ case リストを使うのが要点 —
    非数値を含むケースで両者は**意図的にずれる** (spec §5.6)。パスから数値列を
    得るときは経路ではなく**引いた配列の dtype** で判定する。

    ``base is None`` を全ケースで見るのは、1 サンプルの合成配列ではどの
    リーフスライスも自明に連続 = view になり (実測)、copy を外すと全ケースが
    赤くなるため — 実 mf4 側 (4 サンプル) では view になるリーフが 2 本しか
    無いので、合成側は独立した第 2 の検出器になる。
    """
    cases = [
        np.zeros(1, dtype=np.float64),
        np.zeros((1, 3), dtype=np.uint8),
        np.zeros((1, 2, 2), dtype=np.int16),
        np.zeros(1, dtype=[("x", "<f8"), ("y", "<f8")]),
        np.zeros(1, dtype=[("v", "<f8", (2,))]),
        np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")]),
        np.zeros(1, dtype=[("Radar.ObjList", "<u1"), ("Radar.ObjList.dx", "<f8")]),
        np.zeros((1, 0), dtype=np.float64),
    ]
    for arr in cases:
        spec = spec_from_probe(arr)
        walked = list(leaf_paths(spec))
        assert ["B" + suffix for suffix, _p in walked] == [
            name for name, _c in _flatten("B", arr)
        ], arr.dtype
        for suffix, path in walked:
            got = apply_path(arr, path)
            np.testing.assert_array_equal(got, dict(_flatten("B", arr))["B" + suffix])
            assert got.base is None, (arr.dtype, suffix)
        numeric = [
            "B" + suffix
            for suffix, path in walked
            if apply_path(arr, path).dtype.kind in "iufb"
        ]
        assert numeric == list(leaf_names("B", spec)), arr.dtype

    # 反 vacuous: 非数値を含むケースで 2 つの空間が実際にずれている
    mixed = spec_from_probe(np.zeros(1, dtype=[("ok", "<f8"), ("txt", "S4")]))
    assert len(list(leaf_paths(mixed))) == 2
    assert len(list(leaf_names("B", mixed))) == 1


def test_apply_path_peels_the_non_sample_axis() -> None:
    """整数 step は**軸 1** (非サンプル軸) を剥がす — 軸 0 はサンプル軸である。

    ``samples[i]`` へ取り違えると「1 サンプル分の横断面」が返る。長さが変わるので
    ``LazyMdfValues`` の長さ検証が拾える形もあるが、行数と列数がたまたま等しい
    チャンネルでは黙って別データになる (例外の出ない誤波形)。
    """
    arr = np.array(
        [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]], dtype=np.uint8
    )
    out = apply_path(arr, ColumnPath((1,)))
    np.testing.assert_array_equal(out, [1, 11, 21, 31])
    assert len(out) == len(arr)  # サンプル数 4 (列数 3 ではない)


def test_nested_array_path_steps_are_indices_in_peel_order() -> None:
    """``Name[i][j]`` は asammdf の public write API で往復できない (既存の記録と同根)。

    多段配列の経路だけは合成 ndarray で固定する — 実データで裏取りできていない
    事実として明示する (``test_column_roundtrip`` の
    ``test_nested_index_arm_is_synthetic_because_asammdf_flattens_subarrays`` と同じ扱い)。
    """
    arr = np.zeros((4, 2, 3), dtype=np.uint8)
    for k in range(4):
        arr[k] = np.arange(6, dtype=np.uint8).reshape(2, 3) + 10 * k
    walked = list(leaf_paths(spec_from_probe(arr)))
    assert [(suffix, path.steps) for suffix, path in walked] == [
        (f"[{i}][{j}]", (i, j)) for i in range(2) for j in range(3)
    ]
    # 値も剥がし順どおり (arr[:, 1][:, 2] = 5 + 10k) — サンプル軸の取り違えも落ちる
    np.testing.assert_array_equal(apply_path(arr, ColumnPath((1, 2))), [5, 15, 25, 35])
```

**(b) `tests/core/loaders/test_column_paths.py`（新規）**

```python
"""位置パス (ColumnPath) と LD-14 列名文法の同一性を実 mf4 で固定する (E-4a T1)。

T2 が読み経路をキャッシュ + 位置パスへ移すと ``LazyMdfValues.array()`` は
``_flatten`` を呼ばなくなる。すると ``test_column_roundtrip.py`` が独立オラクルの
根拠にしていた「``_flatten`` は反転後も production が使い続ける」という論拠が失われ、
全数ラウンドトリップは**誰も使わない関数と解決器を突き合わせる**形になる。

本モジュールがその橋渡しである — ``leaf_paths`` の走査が ``_flatten`` の出力と
**順序込み・値込み**で一致することを実データで pin する。``_flatten`` と読み経路を
繋ぎ止める唯一の紐なので、削除・弱体化してはならない。

**所有権 (spec §5.4)**: ``apply_path`` は必ず ``base`` を持たない配列を返す。共有
キャッシュのスライスが view のまま ``LazyMdfValues._cache`` へ焼き付くと、evict しても
RSS が下がらず ``nbytes_if_materialized`` が実体の 1/1000 を返す。**値一致の検証は
view でも全部通る** (実測: copy を外しても本モジュールの値比較 26 リーフは全て緑) ため、
所有権は独立の assert でしか捕まらない。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from asammdf import MDF
from asammdf import Signal as ASignal

from tests.mdf4_helpers import (
    write_mdf4_2d,
    write_mdf4_all_non_numeric_struct,
    write_mdf4_single_column_shapes,
    write_mdf4_structured,
)
from valisync.core.loaders.column_names import (
    apply_path,
    leaf_names,
    leaf_paths,
    spec_from_probe,
)
from valisync.core.loaders.mdf_loader import _flatten

_ARRAY_CHANNEL = "Radar.ObjList"  # フィールド名が '.' を含む CABLOCK 配列チャンネル
_AXIS_LEN = 3
# 遅延読み (LazyMdfValues.array()) と同一の正準オプション。オラクルが production と
# 別の側 (raw=True 等) を読むと「両方同じだけ壊れている」を見逃す。
_SELECT_OPTIONS: dict[str, Any] = {
    "raw": False,
    "ignore_value2text_conversions": True,
    "copy_master": False,
}


def _write_nested_array_mf4(tmp_path: Path) -> Path:
    """構造化 × 配列の入れ子を持つ CABLOCK 配列チャンネルを 1 本書く。

    ``tests/mdf4_helpers`` の既存 fixture はすべて struct か array の**片方**しか
    持たない。両方が入れ子になって初めて経路が (フィールド名 str, 添字 int) の
    混在列になり、「整数序数では位置を表現できない」(spec §5.6) が実データで見える。
    サブ配列付きフィールドで渡すのが要点 — スカラーフィールドの構造化 Signal だと
    asammdf は別表現に落とし、このハザードを再現しない。
    """
    n = 4
    ts = np.arange(n, dtype=np.float64)
    dtype = np.dtype(
        [
            (_ARRAY_CHANNEL, "<u1", (_AXIS_LEN,)),
            (f"{_ARRAY_CHANNEL}.dx", "<f8", (_AXIS_LEN,)),
        ]
    )
    samples = np.zeros(n, dtype=dtype)
    for k in range(n):
        for i in range(_AXIS_LEN):
            samples[_ARRAY_CHANNEL][k, i] = 10 * k + i + 1
            samples[f"{_ARRAY_CHANNEL}.dx"][k, i] = 100 * (i + 1) + k
    out = tmp_path / "nested_array.mf4"
    with MDF(version="4.10") as mdf:
        mdf.append([ASignal(samples, ts, name=_ARRAY_CHANNEL, unit="m")])
        mdf.save(out, overwrite=True)
    return out


def _channel_samples(path: Path) -> dict[str, np.ndarray]:
    """{生チャンネル名: samples} を asammdf 直叩きで読む (production を経由しない)。

    LD-08 の dedup 済み表示名を使わないのは ``leaf_paths`` が base 非依存
    (サフィックスと位置しか返さない) だからである — base の決め方は呼び出し側の
    責務で、ここで dedup 規則を写しても契約の被覆は 1 つも増えない。
    """
    out: dict[str, np.ndarray] = {}
    with MDF(str(path), time_from_zero=False) as mdf:
        entries = [
            (mdf.groups[phys_gi].channels[ci].name, phys_gi, ci)
            for vgi in mdf.virtual_groups
            for phys_gi, channel_indexes in mdf.included_channels(vgi)[vgi].items()
            for ci in channel_indexes
        ]
        for raw_name, gi, ci in entries:
            asig = mdf.select([(raw_name, gi, ci)], **_SELECT_OPTIONS)[0]
            # copy_master=False は asammdf 内部を指しうる — MDF を閉じた後も
            # 参照が生きるようここでコピーする。
            out[raw_name] = np.array(asig.samples)
    return out


@pytest.mark.parametrize(
    ("writer", "expected_leaves"),
    [
        (write_mdf4_2d, 4),  # 2-D 幅 3 (非連続スライス) + スカラー
        (write_mdf4_structured, 2),  # 構造化 (x, y)
        (write_mdf4_single_column_shapes, 5),  # (N,1) 2-D / 単一フィールド / 混在 Q
        (write_mdf4_all_non_numeric_struct, 3),  # 全リーフ非数値 R + スカラー
        (_write_nested_array_mf4, 12),  # 入れ子 6 + 併存する要素チャンネル 6
    ],
)
def test_leaf_paths_walk_matches_flatten_on_real_mf4(
    writer: Callable[[Path], Path], expected_leaves: int, tmp_path: Path
) -> None:
    """全リーフ: 走査順・列名・dtype・値が ``_flatten`` と一致する (実 mf4)。

    **これが位置パスと LD-14 列名文法を繋ぐ唯一の紐**である (モジュール docstring)。
    母数 (``expected_leaves``) を明示するのは、走査が空でもループ内の assert が
    すべて空回りして緑になるため — 手計算せず実測して貼ること。
    """
    leaves = 0
    for raw_name, samples in _channel_samples(writer(tmp_path)).items():
        spec = spec_from_probe(samples)
        expected = _flatten(raw_name, samples)
        walked = list(leaf_paths(spec))
        assert [raw_name + suffix for suffix, _p in walked] == [
            name for name, _c in expected
        ], raw_name
        for (_suffix, path), (name, column) in zip(walked, expected, strict=True):
            got = apply_path(samples, path)
            assert got.dtype == column.dtype, name
            np.testing.assert_array_equal(got, column, err_msg=name)
            assert got.base is None, name  # spec §5.4 (詳細は専用テスト)
            leaves += 1
    assert leaves == expected_leaves, writer.__name__


@pytest.mark.parametrize(
    ("raw_name", "suffix", "naive"),
    [
        ("Mono", "[0]", lambda a: a[:, 0]),  # (N,1) の 2-D 列は**連続** view
        ("P", ".x", lambda a: a["x"]),  # 単一フィールド構造化も**連続** view
    ],
)
def test_apply_path_returns_an_independent_array_for_view_shaped_leaves(
    raw_name: str,
    suffix: str,
    naive: Callable[[np.ndarray], np.ndarray],
    tmp_path: Path,
) -> None:
    """spec §5.4: 命中パスは ``base`` を持たない独立配列を返す。

    ``write_mdf4_single_column_shapes`` を使うのが必須 — 実測で **base が残りうるのは
    ``Mono[0]`` と ``P.x`` の 2 リーフだけ**である。幅 3 以上の 2-D や複数フィールド
    構造化はスライスが非連続で ``ascontiguousarray`` が必ず実コピーするため、copy を
    外しても ``base is None`` のまま通る (= ``write_mdf4_2d`` だけで書いたテストは
    この所有権違反に構造的に盲目)。
    """
    samples = _channel_samples(write_mdf4_single_column_shapes(tmp_path))[raw_name]
    path = dict(leaf_paths(spec_from_probe(samples)))[suffix]

    # 前提の実証: 素の走査は **view を返す** (この fixture が本当にガードを
    # 踏んでいることの証拠。踏んでいなければ下の assert は空虚な緑になる)。
    plain = naive(samples)
    assert np.ascontiguousarray(plain).base is not None, raw_name

    out = apply_path(samples, path)
    assert out.base is None, raw_name
    # 二重コピー防止 (spec §5.4 の付随契約): 自分が作った配列は read-only で返すので
    # ``sample_source._freeze`` が素通しする。writeable のまま返すと同じ列を
    # **2 回**コピーする (E-4a が縮めようとしている列読みのホットパス)。
    assert out.flags.writeable is False, raw_name
    np.testing.assert_array_equal(out, plain)


def test_leaf_paths_covers_non_numeric_leaves_that_leaf_names_drops(
    tmp_path: Path,
) -> None:
    """列挙空間の明示 (spec §5.6): パスは全リーフ・``leaf_names`` は数値リーフのみ。

    ずれる形は 2 つあり、片方だけでは片肺になる: 混在構造 ``Q`` (x: f8 + tag: S2 —
    数値が残る) と全非数値構造 ``R`` (tag: S2 + code: S3 — 数値が 1 本も無い)。
    パスを数値で間引くと 2 本目以降が 1 つずつ手前へずれ、**別の列を黙って返す**。
    """
    mixed = _channel_samples(write_mdf4_single_column_shapes(tmp_path))["Q"]
    q_spec = spec_from_probe(mixed)
    assert [suffix for suffix, _p in leaf_paths(q_spec)] == [".x", ".tag"]
    assert list(leaf_names("Q", q_spec)) == ["Q.x"]  # 非数値は列キー空間に無い

    all_text = _channel_samples(write_mdf4_all_non_numeric_struct(tmp_path))["R"]
    r_spec = spec_from_probe(all_text)
    assert [suffix for suffix, _p in leaf_paths(r_spec)] == [".tag", ".code"]
    assert list(leaf_names("R", r_spec)) == []

    # 数値判定は経路でなく**引いた配列の dtype**で行う (ColumnPath は dtype を持たない)
    numeric = [
        "Q" + suffix
        for suffix, path in leaf_paths(q_spec)
        if apply_path(mixed, path).dtype.kind in "iufb"
    ]
    assert numeric == list(leaf_names("Q", q_spec))
    assert apply_path(mixed, dict(leaf_paths(q_spec))[".tag"]).dtype.kind == "S"


def test_nested_array_paths_are_field_names_and_indices(tmp_path: Path) -> None:
    """``_flatten`` を一切通さない手書きオラクル — steps と値を直接固定する。

    全数テストは参照側も ``_flatten`` なので、**順序規則そのもの**が両側同時に
    変わると盲目になる (``test_column_roundtrip`` の
    ``test_literal_values_pin_the_key_to_column_mapping`` と同じ理由)。
    位置が整数序数で表せないこと (spec §5.6) もここで直接見える — steps は
    (フィールド名 str, 添字 int) の混在列である。
    """
    samples = _channel_samples(_write_nested_array_mf4(tmp_path))[_ARRAY_CHANNEL]
    walked = list(leaf_paths(spec_from_probe(samples)))
    assert [(suffix, path.steps) for suffix, path in walked] == [
        (f".{_ARRAY_CHANNEL}[0]", (_ARRAY_CHANNEL, 0)),
        (f".{_ARRAY_CHANNEL}[1]", (_ARRAY_CHANNEL, 1)),
        (f".{_ARRAY_CHANNEL}[2]", (_ARRAY_CHANNEL, 2)),
        (f".{_ARRAY_CHANNEL}.dx[0]", (f"{_ARRAY_CHANNEL}.dx", 0)),
        (f".{_ARRAY_CHANNEL}.dx[1]", (f"{_ARRAY_CHANNEL}.dx", 1)),
        (f".{_ARRAY_CHANNEL}.dx[2]", (f"{_ARRAY_CHANNEL}.dx", 2)),
    ]
    # fixture の値定義 (10*k+i+1 / 100*(i+1)+k) から手で書き下した期待値
    by_suffix = dict(walked)
    np.testing.assert_array_equal(
        apply_path(samples, by_suffix[f".{_ARRAY_CHANNEL}[1]"]), [2, 12, 22, 32]
    )
    np.testing.assert_array_equal(
        apply_path(samples, by_suffix[f".{_ARRAY_CHANNEL}.dx[2]"]),
        [300.0, 301.0, 302.0, 303.0],
    )
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_column_paths.py tests/core/loaders/test_column_names.py -q`

Expected: 両モジュールが **collection error**（import が module-level のため）。
実測済みの文言:

```
ImportError: cannot import name 'ColumnPath' from 'valisync.core.loaders.column_names' (D:\Programming\projects\valisync\src\valisync\core\loaders\column_names.py)
```

- [ ] **Step 3: 実装**

(a) `src/valisync/core/loaders/column_names.py` のモジュール docstring 末尾（現 8–9 行目の段落）を差し替える。

```python
生成 (``spec_from_probe`` / ``leaf_names`` / ``leaf_count``) と逆変換
(``parse_leaf``) を対で持つ。E-4a からは **位置** (``ColumnPath`` /
``leaf_paths`` / ``apply_path``) も同じ順序規則の上に載る — 名前で引く経路と
位置で引く経路が別々の順序を持つと、同じ列キーが読みごとに別の列を返す。
"""
```

(b) `leaf_count`（95 行目で終わる）と `parse_leaf` の間へ挿入する。import 追加は不要（`Iterator` / `dataclass` / `np` は既にある）。

```python
@dataclass(frozen=True, slots=True)
class ColumnPath:
    """全リーフ空間における 1 リーフへの経路 (フィールド名と添字の列)。

    **整数序数では表現できない** — 構造化 × 配列の入れ子 (``Name.field[i]`` /
    ``Name[i][j]``) があるため「n 番目のリーフ」という 1 個の数では位置が定まらない。
    ``str`` = 構造化フィールド名 / ``int`` = 配列の添字 (剥がすのは常に軸 1。
    軸 0 はサンプル軸である)。

    名前 (列キー) は永続キーのまま (LD-14)。位置は**ロードごとに導出する派生値**で
    あり保存しない — チャンネル構造が変わればロード時に作り直される。
    """

    steps: tuple[str | int, ...]


def leaf_paths(spec: ColumnSpec) -> Iterator[tuple[str, ColumnPath]]:
    """(リーフ名サフィックス, 経路) を _flatten と同じ順序で生成する (ジェネレータ)。

    **列挙空間は _flatten と同じ「全リーフ」** — ``leaf_names`` が返すのは数値リーフ
    だけで、混在構造 (``Q``: x=f8 + tag=S2) では両者がずれる。位置は「デコード済み
    配列のどこを引くか」なので dtype で間引いてはならない (間引くと後続のリーフが
    1 つずつ手前へずれ、**別の列を黙って返す**)。数値判定は経路ではなく引いた配列の
    dtype で行う。

    **base を取らない**のは、サフィックスが base 非依存だからである。列キーは LD-08
    dedup 済み表示名から作り (``leaf_names(display, spec)``)、読みは生名を使う
    (``_flatten(raw, samples)``) — 2 つのキー空間で base は違うが、サフィックスと
    位置は共通なので、ここで dedup 規則を写す必要が無い。

    ジェネレータなのは ``leaf_names`` と同じ理由 — 広幅チャンネル (prod は 1,100 列)
    で全サフィックスを常に実体化しないため。
    """
    yield from _leaf_paths("", (), spec)


def _leaf_paths(
    suffix: str, steps: tuple[str | int, ...], spec: ColumnSpec
) -> Iterator[tuple[str, ColumnPath]]:
    """leaf_paths の再帰本体。名前と経路を**同時に**伸ばして順序の一致を構造的に保つ。"""
    if spec.kind == "struct":
        for name, sub in spec.fields:
            yield from _leaf_paths(f"{suffix}.{name}", (*steps, name), sub)
    elif spec.kind == "array":
        assert spec.child is not None
        for i in range(spec.axis_len):
            yield from _leaf_paths(f"{suffix}[{i}]", (*steps, i), spec.child)
    else:
        yield (suffix, ColumnPath(steps))


def apply_path(samples: np.ndarray, path: ColumnPath) -> np.ndarray:
    """samples (axis 0 = サンプル) から経路のリーフ列を **独立配列**で取り出す。

    **必ず base を持たない配列を返す (E-4 spec §5.4 の所有権の不変条件)**: 共有
    キャッシュの 2-D 配列を view のまま返すと、``_freeze`` が read-only 入力を素通し
    する性質と相まって view が ``LazyMdfValues._cache`` へ焼き付く。すると (1) LRU が
    evict しても列 Signal が base 経由で 2-D 全体を保持し RSS が 1 バイトも下がらず
    (2) ``nbytes_if_materialized`` が view の nbytes を返して teardown のバイト軸が
    黙って死ぬ。**値一致の検証は view でも全部通る**ので、ここを緩めても値のテストは
    緑のままである。

    連続スライス (幅 1 の 2-D・単一フィールド構造化) では ``ascontiguousarray`` が
    コピーを作らないため、明示的な copy が要る。経路が空 (スカラーチャンネル) かつ
    入力が既に独立配列なら入力そのものを返す — 列 = チャンネル全体で余分に生かす親が
    無く、不変条件 (base is None) は満たされる。

    **自分が作った配列は read-only にして返す**: 呼び出し側 (``LazyMdfValues.
    _column_of``) が通す ``sample_source._freeze`` は ``writeable`` を見て
    ``array.copy()`` するので、writeable のまま返すと**同じ列を 2 回コピーする**
    (実測: 非連続スライスへの ``ascontiguousarray`` は writeable=True のコピーを
    返し、``_freeze`` がもう 1 回コピーする)。E-4a が縮めようとしている列読みの
    ホットパスで毎列 2x のアロケーション + memcpy になるため、**ここで凍結して
    ``_freeze`` を素通しにするのが正**。この 2 行を「凍結は ``_freeze`` の仕事」と
    考えて消さないこと — 消すと二重コピーが黙って戻る。
    """
    out = samples
    for step in path.steps:
        # int は軸 1 を剥がす (_flatten の arr[:, i] と同一) — 軸 0 はサンプル軸
        out = out[step] if isinstance(step, str) else out[:, step]
    out = np.ascontiguousarray(out)
    if out.base is not None:
        out = out.copy()
    if out is not samples:
        # 凍結するのは **この関数が作った配列だけ**。経路が空で入力そのものを返す
        # 場合まで凍結すると、呼び出し側が渡した配列の可変性を横から奪う
        # (production ではその配列は共有前に read-only 化済みなので、この分岐でも
        # _freeze は素通しし、やはりコピーは 0 回である)。
        out.flags.writeable = False
    return out
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/core/loaders/ -q`
Expected: 新規 8 ケース（`test_column_paths.py` は parametrize 展開で 5 + 2 + 1 + 1 = 9 テスト）が pass し、`test_column_names.py` / `test_column_records.py` / `test_column_roundtrip.py` / `test_column_names_asammdf.py` の既存テストは全数そのまま pass（production 未配線なので挙動不変であること自体が受理条件）。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

**`git checkout -- src/...` で戻さないこと**（過去に実装者が自分の未コミット作業を消している）。sabotage は 1 つずつ手で戻すか、`column_names.py` の pristine copy をスクラッチへ退避してから当てる。

以下の到達範囲は**本プラン執筆時に実測した値**である。実装者は自分の手でも再測し、食い違ったら実装かテストのどちらかが違う（主張を信じない）。

1. **copy ガードを外す**（`if out.base is not None: out = out.copy()` を削除）
   - RED（実測）: `test_column_paths.py::test_apply_path_returns_an_independent_array_for_view_shaped_leaves`（`Mono`/`P` の 2 パラメータとも）／`test_column_paths.py::test_leaf_paths_walk_matches_flatten_on_real_mf4[write_mdf4_single_column_shapes]`（漏れるのは `Mono[0]` と `P.x` の **2 リーフのみ**）／`test_column_names.py::test_leaf_paths_walk_all_leaves_in_flatten_order`（合成は 1 サンプルなのでどのリーフも連続 view = 全ケース RED）。
   - **GREEN のまま（実測）**: 実 mf4 5 fixture の**値・dtype 比較は 26/26 リーフすべて緑**、他 4 fixture の `base is None` も緑。→ spec §5.4-3「値一致テストは view でも通る」の実証。所有権テストを消すと、この破壊はスイート全体から見えなくなる。
2. **配列の走査順を反転**（`for i in reversed(range(spec.axis_len))`）
   - RED（実測）: `test_leaf_paths_walk_matches_flatten_on_real_mf4` の `write_mdf4_2d`（`Mat`）と `_write_nested_array_mf4`（`Radar.ObjList`）／`test_leaf_paths_walk_all_leaves_in_flatten_order`／`test_nested_array_path_steps_are_indices_in_peel_order`／`test_nested_array_paths_are_field_names_and_indices`。
   - **GREEN のまま（実測）**: `write_mdf4_single_column_shapes`（`Mono` は `axis_len == 1` で反転が恒等）・`write_mdf4_structured`・`write_mdf4_all_non_numeric_struct`。→ 幅 2 以上の配列を持つ fixture が母数から落ちると順序は守られない。
3. **全リーフ空間を数値リーフ空間へ取り違え**（`else:` を `elif spec.dtype_kind in _NUMERIC_KINDS:` にする）
   - RED（実測）: `test_leaf_paths_walk_matches_flatten_on_real_mf4[write_mdf4_single_column_shapes]`（`Q`）と `[write_mdf4_all_non_numeric_struct]`（`R`）の順序 assert／`test_leaf_paths_covers_non_numeric_leaves_that_leaf_names_drops`／`test_leaf_paths_walk_all_leaves_in_flatten_order`（`("ok","txt")` ケース）。
   - **GREEN のまま（実測）**: 全リーフが数値の 3 fixture。
4. **整数 step をサンプル軸へ当てる**（`out[:, step]` を `out[step]` にする）
   - RED（実測）: `test_apply_path_peels_the_non_sample_axis`（`arr[1]` は `[10, 11, 12]`・長さ 3 で、期待 `[1, 11, 21, 31]`・長さ 4 と形も値も違う）／2-D を含む全 fixture の値比較／`test_nested_array_path_steps_are_indices_in_peel_order`。
5. **凍結を外す**（`if out is not samples: out.flags.writeable = False` の 2 行を削除＝二重コピーへ戻す）
   - RED: `test_apply_path_returns_an_independent_array_for_view_shaped_leaves`（`Mono`/`P` の 2 パラメータとも `out.flags.writeable is False` が RED）。
   - **GREEN のまま**: 値・dtype・`base is None` の assert は全数緑（コピー回数は値に現れない）。→ 「凍結は `_freeze` の仕事だから消してよい」と読んだ変更が、この 1 assert 以外どこにも当たらないことの実証。

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

（`| tail` に通さない — exit code が隠れる。4 本すべて exit 0 を目視すること。）

```bash
git add src/valisync/core/loaders/column_names.py \
        tests/core/loaders/test_column_names.py \
        tests/core/loaders/test_column_paths.py
git commit -m "$(cat <<'EOF'
feat(core): 列の位置パス ColumnPath/leaf_paths/apply_path を追加 (E-4a T1・production 未配線)

位置は整数序数では表せない (構造化 × 配列の入れ子) ため、フィールド名と添字の列で表す。
列挙空間は _flatten と同じ全リーフ (leaf_names の数値リーフのみとは意図的に別)。
apply_path は spec §5.4 の所有権の不変条件を満たす — 連続スライスでも base を持たない
独立配列を返す (view が _cache へ焼き付くと evict しても RSS が下がらず会計も死ぬ)。
返す配列は read-only にする: sample_source._freeze は read-only 入力を素通しするので、
これで列読みのコピーが 1 回で済む (writeable のまま返すと apply_path と _freeze で
毎列 2 回コピーする = E-4a が縮めようとしているホットパスそのもの)。

T2 が読み経路から _flatten を外すと test_column_roundtrip.py の独立性の論拠が失われる
ので、その橋渡しとして「leaf_paths の走査 == _flatten の出力 (順序込み・値込み)」を
実 mf4 5 fixture・26 リーフで pin する (tests/core/loaders/test_column_paths.py)。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 2: 読み経路をチャンネル単位キャッシュ＋位置パスへ（E-4a の本体）

**Files:**
- Modify: `src/valisync/core/models/sample_source.py:102-213`（`LazyMdfValues` — `__slots__`:108 / `__init__`:110 / `array()`:156）
- Modify: `src/valisync/core/loaders/mdf_handle.py:14-27`（`__slots__` と `__init__` に `cache`）
- Modify: `src/valisync/core/loaders/mdf_loader.py:182`（`MdfLoader.__init__` 新設）・`:270`（`MdfHandle(...)` へ注入）
- Modify: `src/valisync/core/loaders/column_names.py:33-46`（`ColumnRecord` に位置索引フィールドを追加・I-2）
- Modify: `src/valisync/core/loaders/signal_group_manager.py:6-11`（import）・`:359-378`（`_mint_column` が位置パスを渡す）・モジュール末尾（`_leaf_path` ヘルパ）
- Modify: `src/valisync/core/session.py:121-131`（`__init__`＝キャッシュ所有＋予算注入口）・**その直後**（`channel_cache` プロパティ）・`:367`（close 前に `drop_handle`）
- Modify: `tests/core/loaders/test_column_roundtrip.py:1-20`（module docstring のみ — 読み経路が `_flatten` を呼ばなくなるのは本タスクなので、独立オラクルの論拠をここで引き継ぐ・I-4）
- Test: `tests/core/loaders/test_channel_cache_read_path.py`（新規）

**Interfaces:**
- Consumes（T0）: `ChannelSampleCache(budget_bytes: int = 256*1024*1024)` / `get(key: CacheKey) -> np.ndarray | None` / `put(key: CacheKey, samples: np.ndarray) -> bool` / `drop_handle(handle_id: int) -> tuple[np.ndarray, ...]` / `hits` / `misses` / `bytes_held`（`CacheKey = tuple[int, int, int]`）
- Consumes（T1）: `ColumnPath(steps: tuple[str | int, ...])` / `leaf_paths(spec: ColumnSpec) -> Iterator[tuple[str, ColumnPath]]`（**リーフ名サフィックス**と経路を `_flatten` と同順で返す）/ `apply_path(samples: np.ndarray, path: ColumnPath) -> np.ndarray`（**base を持たない独立配列**を返し、かつ**自分が作った配列は read-only で返す**契約 — 本タスクの `_freeze` はそれを素通しするので、列読みのコピーは 1 回）
- Produces（T3/T4/T5/T6 が依存）:
  - `MdfHandle(mdf: Any, source_path: str = "", cache: ChannelSampleCache | None = None)` と公開属性 `handle.cache`
  - `MdfLoader(cache: ChannelSampleCache | None = None)`（`load()` のシグネチャは不変）
  - `Session(cache_budget_bytes: int | None = None)` — **予算の注入口はコンストラクタ引数**（T3 が足す `column_capacity` と対称）。`Session.channel_cache` に **setter は置かない**: `__init__` が `MdfLoader(cache=self._channel_cache)` で旧オブジェクトを捕捉し、`MdfHandle` はロード時に `MdfLoader._cache` を提げるので、後から差し替えても `LazyMdfValues.array()` が見る `self._handle.cache` は旧インスタンスのまま＝注入した新キャッシュを**誰も書かない**（counters が全て 0 のまま ①gate の脚 3 が構造的に成立しない）
  - `Session.channel_cache -> ChannelSampleCache`（getter のみ・非鋳造 introspection。T5 の計測器と T6 の ①gate の観測点）
  - `ColumnRecord.path_index: dict[str, ColumnPath]`（**遅延構築の位置索引**・`compare=False`。`_column_records` と同寿命で、鋳造ごとの `leaf_paths` 全走査＝全列鋳造の O(n²) を潰す・I-2）
  - `LazyMdfValues(handle, name, gi, ci, length, selector=None, path=None)` — **`selector` と `path` は対**（片方だけ渡すと `ValueError`）
  - `Session.remove_group()` が `handle.close()` の**前**に `channel_cache.drop_handle(id(handle))` を呼ぶ順序（T4 はこの戻り値を `RemovalResult.cached_arrays` へ載せてペーシングへ渡す。T2 の時点では参照を落とすだけ＝同期解放）

---

- [ ] **Step 1: 失敗テストを書く**

`tests/core/loaders/test_channel_cache_read_path.py` を新規作成する。

```python
"""E-4a 読み経路: チャンネル単位キャッシュ + 位置パスの契約。

**demo_data に依存しない**: 自然な宛先に見える ``test_lazy_mdf_values.py`` /
``test_mdf_loader_lazy.py`` は module-level の demo skipif を持ち、``demo_data/`` は
gitignore 済み・CI に生成ステップが無いため丸ごと skip される。読み経路の所有権
不変条件 (spec §5.4) とキー空間 (spec §5.3) はサイレント破壊の入口なので、
``tests/mdf4_helpers`` + ``tmp_path`` で CI 実行できる形にする
(``test_mdf_handle_concurrency.py`` の module docstring と同じ理由)。
"""

from __future__ import annotations

import gc
import threading
import weakref
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from tests.mdf4_helpers import (
    write_mdf4,
    write_mdf4_2d,
    write_mdf4_dup_2d,
    write_mdf4_shared_group,
    write_mdf4_single_column_shapes,
)
from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.loaders.mdf_handle import MdfHandle
from valisync.core.models.sample_source import LazyMdfValues, SampleReadError
from valisync.core.session import Session

# WHY (core テストから gui を引く): teardown のバイト軸は gui 側の関数が持つが、
# 会計が正しくなる条件 (列が 2-D のビューを掴んでいないこと) は core の不変条件
# である。会計式そのものを写経すると、実装が変わったときに写経側だけが緑になる。
from valisync.gui.workers.teardown_service import _retained_bytes


class _CountingLock:
    """acquire を数える lock ラッパ (``MdfHandle.__slots__`` の "lock" へ差し替える)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.acquires = 0

    def __enter__(self) -> _CountingLock:
        self.acquires += 1
        self._lock.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._lock.release()


class _StubMdf:
    """select が n サンプルの 1-D を返す最小 MDF スタブ.

    宣言 length と実読み列の不一致は実 mf4 では作れない (v4.20+ の
    remote-master/column-storage が要る) ので、``test_mdf_handle_concurrency.py`` と
    同じくスタブで作る。
    """

    def __init__(self, n: int) -> None:
        self.n = n
        self.select_calls = 0

    def select(self, entries: Any, **kwargs: Any) -> list[Any]:
        self.select_calls += 1
        return [SimpleNamespace(samples=np.arange(self.n, dtype=np.float64))]


def _handle_of(session: Session, key: str) -> MdfHandle:
    """ロード済みグループの MdfHandle (test_handle_release.py と同じ入口)."""
    handle = session._groups.group(key).handle
    assert handle is not None, "MDF グループなのに handle が無い (setup 失敗)"
    return handle


def _records(session: Session, key: str) -> Any:
    """{表示名: ColumnRecord} — fixture が持つ (gi, ci) の実測に使う."""
    return session._groups.column_records(key)


# ─── 1 チャンネル 1 デコード (spec §9 の select 回数 / §5.8 の lock 契約) ──────


def test_sibling_column_hits_the_cache_without_select_or_lock(tmp_path: Path) -> None:
    """同一物理チャンネルの 2 本目の列は select も handle.lock も要らない。

    E-4a の出口 (5 列 1,584ms / select 5 回 -> select 1 回) の Layer A オラクル。
    lock を見るのは spec §5.8 — 「ヒット = ファイルに触らない」なので、別スレッドの
    in-flight select (prod 実測 316 ms) を待ってはならない。ヒットを lock 内へ
    入れる実装は値のテストでは緑のまま通る (だから acquires を数える)。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    try:
        handle = _handle_of(session, key)
        cache = session.channel_cache
        assert cache.misses == 0, "ロード自体がキャッシュ経路を通っている (setup 失敗)"

        lock = _CountingLock()
        handle.lock = lock  # type: ignore[assignment]
        real_select = handle.mdf.select
        selected: list[Any] = []

        def _counting_select(entries: Any, **kwargs: Any) -> Any:
            selected.append(entries)
            return real_select(entries, **kwargs)

        handle.mdf.select = _counting_select  # type: ignore[assignment]

        first = session.resolve_signal(f"{key}::Mat[0]")
        assert first is not None
        np.testing.assert_array_equal(first.values, [0, 10, 20, 30])
        assert len(selected) == 1, "初回読みで select が 1 回でない"
        assert lock.acquires == 1, "初回読みが lock を取っていない (setup 失敗)"
        assert (cache.hits, cache.misses) == (0, 1)

        second = session.resolve_signal(f"{key}::Mat[2]")
        assert second is not None
        np.testing.assert_array_equal(second.values, [2, 12, 22, 32])
        assert len(selected) == 1, "2 本目の列で select が再実行されている"
        assert cache.hits == 1, "2 本目の列がキャッシュヒットしていない"
        assert cache.misses == 1, "miss 数 == select 回数 が崩れている"
        assert lock.acquires == 1, "キャッシュヒットが handle.lock を取っている"
    finally:
        session.remove_group(key)


def test_column_read_never_builds_the_leaf_name_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """読み経路は ``_flatten`` を通らない (位置パスで引く・spec §5.6)。

    名前引きは全リーフ辞書を作るので、幅 1,100 のチャンネルでは 1 列読むために
    1,100 本の f-string と 1,100 本の ascontiguousarray を払う。E-4a の出口
    「_flatten 呼び出し回数 1 -> 0」の直接の観測点。
    """
    from valisync.core.loaders import mdf_loader

    def _boom(name: str, arr: np.ndarray) -> Any:
        raise AssertionError(f"読み経路が _flatten を呼んだ: {name}")

    monkeypatch.setattr(mdf_loader, "_flatten", _boom)

    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    try:
        col = session.resolve_signal(f"{key}::Mat[1]")
        assert col is not None
        np.testing.assert_array_equal(col.values, [1, 11, 21, 31])
    finally:
        session.remove_group(key)


# ─── キー空間 (spec §5.3): handle / gi / ci の 3 軸を別々に殺す ───────────────


def test_cache_key_separates_channels_that_share_a_raw_name(tmp_path: Path) -> None:
    """生名を共有する 2 チャンネル (LD-08) が同じキーに落ちない — **gi 軸**。

    ``write_mdf4_dup_2d`` は生名 "W" の 2-D を 2 本持つ (roundtrip fixture の
    ``Mat2`` と同じ形をヘルパにしたもの)。名前をキーにする実装・gi を落とす実装は
    2 本目に 1 本目の配列を配り、長さも dtype も一致するので例外は出ない。
    """
    session = Session()
    key = session.load(write_mdf4_dup_2d(tmp_path)).key
    try:
        records = _records(session, key)
        # 変異の到達範囲を fixture の実測で固定する: 生名は同じ・ci は同じ・gi だけ違う
        # (= このテストが殺せるのは gi 軸)。ci 軸は別テストが担当する。
        assert records["W[0]"].raw_base_name == records["W[1]"].raw_base_name == "W"
        assert records["W[0]"].channel_index == records["W[1]"].channel_index
        assert records["W[0]"].group_index != records["W[1]"].group_index

        first = session.resolve_signal(f"{key}::W[0][0]")
        second = session.resolve_signal(f"{key}::W[1][0]")
        assert first is not None and second is not None
        np.testing.assert_array_equal(first.values, [0, 2, 4, 6])
        np.testing.assert_array_equal(second.values, [100, 102, 104, 106])
    finally:
        session.remove_group(key)


def test_cache_key_separates_two_channels_in_one_group(tmp_path: Path) -> None:
    """同一グループの 2 チャンネルが同じキーに落ちない — **ci 軸**。

    ``write_mdf4_dup_2d`` は gi が違うので ci を落とす変異に盲目である
    (fixture の実測を下の assert で固定する)。同一グループ 2ch の fixture が
    ci 軸の唯一の観測点。
    """
    session = Session()
    key = session.load(write_mdf4_shared_group(tmp_path)).key
    try:
        records = _records(session, key)
        assert records["A"].group_index == records["B"].group_index
        assert records["A"].channel_index != records["B"].channel_index

        a = session.resolve_signal(f"{key}::A")
        b = session.resolve_signal(f"{key}::B")
        assert a is not None and b is not None
        np.testing.assert_array_equal(a.values, np.arange(10.0))
        np.testing.assert_array_equal(b.values, np.arange(10.0) * 2.0)
    finally:
        session.remove_group(key)


def test_cache_key_separates_two_files_with_identical_positions(
    tmp_path: Path,
) -> None:
    """同じ (name, gi, ci) を持つ 2 ファイルが混ざらない — **handle 軸**。

    Session は 1 個のキャッシュを全ファイルで共有する。handle をキーに含めないと
    2 ファイル比較で同じ曲線が 2 本描かれる (長さが同じなので長さ検証も通り、
    例外は出ない — spec §5.3)。
    """
    first_path = write_mdf4(
        tmp_path / "a.mf4",
        [{"name": "Spd", "timestamps": [0.0, 1.0], "values": [1.0, 2.0]}],
    )
    second_path = write_mdf4(
        tmp_path / "b.mf4",
        [{"name": "Spd", "timestamps": [0.0, 1.0], "values": [11.0, 12.0]}],
    )
    session = Session()
    key_a = session.load(first_path).key
    key_b = session.load(second_path).key
    try:
        rec_a, rec_b = _records(session, key_a)["Spd"], _records(session, key_b)["Spd"]
        # 到達範囲の実測: 2 ファイルは (gi, ci) が完全に一致する = handle だけが
        # 両者を分けている。ここが違うと本テストは handle 軸に盲目になる。
        assert (rec_a.group_index, rec_a.channel_index) == (
            rec_b.group_index,
            rec_b.channel_index,
        )

        a = session.resolve_signal(f"{key_a}::Spd")
        b = session.resolve_signal(f"{key_b}::Spd")
        assert a is not None and b is not None
        np.testing.assert_array_equal(a.values, [1.0, 2.0])
        np.testing.assert_array_equal(b.values, [11.0, 12.0])
    finally:
        session.remove_group(key_a)
        session.remove_group(key_b)


# ─── 所有権の不変条件 (spec §5.4 = レビュー Critical 1) ───────────────────────


def test_leaf_view_of_these_shapes_is_already_contiguous() -> None:
    """下 2 本の fixture 選択が「歯」である理由を numpy レベルで固定する。

    ``ascontiguousarray`` は非連続スライスなら必ずコピーするので、幅 3 の
    ``Mat[1]`` (stride 3) では copy を外す変異が **RED にならない**。共有 2-D の
    ビューが素通りできるのは「リーフのビューが既に連続」= 幅 1 の配列と単一
    フィールド構造体だけである。``write_mdf4_single_column_shapes`` の
    ``Mono`` / ``P`` がまさにその 2 形状。

    **このテストは実装前から緑**である (numpy の性質の pin であって挙動テストでは
    ない)。役割は、下の 2 本が別の fixture へ書き換えられたときに、その書き換えが
    「歯を抜いた」ことを説明できる形で残すこと。
    """
    width_one = np.zeros((4, 1), dtype=np.uint8)
    assert np.ascontiguousarray(width_one[:, 0]).base is not None  # コピーされない
    single_field = np.zeros(4, dtype=[("x", "<f8")])
    assert np.ascontiguousarray(single_field["x"]).base is not None
    width_three = np.zeros((4, 3), dtype=np.uint8)
    assert np.ascontiguousarray(width_three[:, 1]).base is None  # 必ずコピー


def test_minted_column_owns_its_values_on_the_cache_hit_path(tmp_path: Path) -> None:
    """命中パスが返す列は base を持たない独立配列 (spec §5.4)。

    ``_freeze`` は **read-only 入力を素通しする** (docstring が機能として明記) ので、
    read-only な共有 2-D のビューは凍結を通り抜けて ``_cache`` に焼き付く。すると
    evict しても列 Signal がチャンネル全体を生かし、``nbytes_if_materialized`` は
    ビュー自身の nbytes を返して teardown のバイト軸が実体の 1/1000 を計上する。

    容器を先に読んでからその列を読むことで **必ず命中パスを通す** (``cache.hits``
    でそれを実証する)。単一リーフのチャンネルには兄弟列が無く、素直に列だけ読むと
    ミスパスしか踏めない。
    """
    session = Session()
    key = session.load(write_mdf4_single_column_shapes(tmp_path)).key
    try:
        cache = session.channel_cache
        container = session.resolve_signal(f"{key}::Mono")
        assert container is not None
        assert container.values.ndim == 2  # 2-D をここで 1 回だけデコードする
        assert (cache.hits, cache.misses) == (0, 1)

        col = session.resolve_signal(f"{key}::Mono[0]")
        assert col is not None
        values = col.values
        assert cache.hits == 1, "命中パスを通っていない (このテストの前提が崩れた)"
        np.testing.assert_array_equal(values, [0, 1, 2, 3])
        assert col._values_source.array_if_materialized() is values
        # 会計の形の pin。**この等式だけでは copy 除去に盲目**である
        # (ビューの .nbytes はコピーと同値) — 歯は下の base assert と
        # 下の weakref テストが持つ。ここが守るのは「列が 2-D 丸ごとを
        # _cache に入れていない」という別の変異。
        # **base assert より前に置く**: S1 (apply_path の copy ガード除去) を当てた
        # とき「等式は通ったうえで base assert だけが落ちる」= 等式の盲目性が同じ
        # 実行で観測できる。後ろに置くと base で止まって到達せず、盲点の実測が
        # できない (順序を入れ替えないこと)。
        assert _retained_bytes(col, set()) == values.nbytes + col.timestamps.nbytes
        assert values.base is None, "列が共有 2-D のビューのまま焼き付いている"

        # 単一フィールド構造体でも同じ (ビューが連続になる 2 つ目の形)。
        struct_col = session.resolve_signal(f"{key}::P.x")
        assert struct_col is not None
        assert struct_col.values.base is None
        np.testing.assert_array_equal(struct_col.values, [1.0, 2.0, 3.0, 4.0])
    finally:
        session.remove_group(key)


def test_dropping_the_channel_frees_the_2d_because_the_column_is_independent(
    tmp_path: Path,
) -> None:
    """evict でチャンネル 2-D が**実際に解放される** (spec §5.4 の帰結 1)。

    「値が一致する」テストはビューでも通る。RSS が下がるかどうかを CI で見られる
    唯一の honest observable が weakref の生死である (ビューなら base 経由で
    2-D が生き続ける)。id() ではなく参照で見るのは、死んだオブジェクトの
    アドレス再利用による非決定フレークを避けるため。
    """
    session = Session()
    key = session.load(write_mdf4_single_column_shapes(tmp_path)).key
    try:
        handle = _handle_of(session, key)
        col = session.resolve_signal(f"{key}::Mono[0]")
        assert col is not None
        np.testing.assert_array_equal(col.values, [0, 1, 2, 3])

        dropped = session.channel_cache.drop_handle(id(handle))
        assert len(dropped) == 1, "読んだチャンネルの 2-D が載っていない (setup 失敗)"
        ref = weakref.ref(dropped[0])
        del dropped
        gc.collect()
        assert ref() is None, "列が 2-D を生かしている (evict しても RSS が下がらない)"
        # 列自身は生きている (解放したのはチャンネルだけ)
        np.testing.assert_array_equal(col.values, [0, 1, 2, 3])
    finally:
        session.remove_group(key)


# ─── 保存すべき契約: 長さ検証・アンロード ────────────────────────────────────


def test_a_length_mismatch_is_not_burned_into_the_shared_cache() -> None:
    """長さ不変条件は共有キャッシュへ載せる **前** に執行する。

    後ろに置くと、壊れた読みが 1 度でも起きたチャンネルの全列が以後その配列を
    見る (miss しないので再読みの余地も無い)。

    **診断の宛先も同時に固定する** (spec §5.6): 位置パス化で読みは名前を使わなく
    なったので、``SampleReadError`` に載る ``signal_key`` / ``source_file`` だけが
    診断の宛先になった。両者が落ちても例外の型と文言は変わらないため、app レベルの
    excepthook の「1 信号 1 診断」dedup と診断ラベルが**黙って**壊れる — 文言だけを
    見る ``match=`` では捕まらないので、値そのものを assert する。
    """
    cache = ChannelSampleCache()
    # source_path を渡すのが要点: 既定の "" だと source_file の assert が
    # 「空文字と空文字の比較」= 恒真になり、宛先を落とす変異に盲目になる。
    handle = MdfHandle(_StubMdf(3), "C:/x.mf4", cache=cache)  # select は 3 サンプル
    src = LazyMdfValues(handle, "ch", 0, 1, length=4)  # 宣言は 4

    with pytest.raises(SampleReadError, match="サンプル数") as exc:
        src.array()

    assert exc.value.signal_key == "ch", "診断の宛先 (信号名) が失われている"
    assert exc.value.source_file == "C:/x.mf4", "診断の宛先 (ファイル) が失われている"
    assert cache.bytes_held == 0, "長さ検証を通らない読みが共有キャッシュに載った"
    assert src.array_if_materialized() is None


def test_unload_drops_the_channel_entries_before_close(tmp_path: Path) -> None:
    """アンロードでキャッシュのエントリが残らない。

    キーは ``id(handle)`` を含むだけでハンドルを**所有しない**ので、残したまま
    ハンドルが死ぬと、新しいファイルのハンドルが同じアドレスを再利用したときに
    古いファイルの 2-D を引き当てる (値が黙って入れ替わる)。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    col = session.resolve_signal(f"{key}::Mat[1]")
    assert col is not None
    np.testing.assert_array_equal(col.values, [1, 11, 21, 31])
    assert session.channel_cache.bytes_held > 0, "読んだのに載っていない (setup 失敗)"

    session.remove_group(key)
    assert session.channel_cache.bytes_held == 0


def test_selector_and_path_must_be_given_as_a_pair() -> None:
    """片方だけの構築を loud-fail させる。

    ``selector`` だけを渡せる形にすると、列 Signal が容器分岐 (2-D 丸ごと) を
    通って「例外の出ない誤データ」になる。片側だけの構築サイトは production に
    無いので、ここは将来の追加を止めるための構造ガード。
    """
    handle = MdfHandle(_StubMdf(4))
    with pytest.raises(ValueError, match="selector"):
        LazyMdfValues(handle, "ch", 0, 1, length=4, selector=("ch[0]",))
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_channel_cache_read_path.py -q`

Expected: **10 failed / 1 passed**（合計 11 件。`-rf` の集計とこの内訳を突き合わせること）。
- `ModuleNotFoundError: No module named 'valisync.core.loaders.channel_cache'`（T0 が未マージなら先に T0 を入れる。この場合は収集エラーになり内訳が出ないので、先に T0 を入れる）
- `AttributeError: 'Session' object has no attribute 'channel_cache'`（キャッシュ系 8 本）
- `TypeError: MdfHandle.__init__() got an unexpected keyword argument 'cache'`（`test_a_length_mismatch_is_not_burned_into_the_shared_cache` / `test_selector_and_path_must_be_given_as_a_pair`）
- `AssertionError: 読み経路が _flatten を呼んだ: Mat`（`test_column_read_never_builds_the_leaf_name_dict`）

`test_leaf_view_of_these_shapes_is_already_contiguous` の **1 本だけ**は実装前から PASS（numpy の性質の pin・docstring に明記済み）。この 1 本を failed の内訳から差し引いた 10 が上の期待値であり、`-rf` の一覧が 10 行でなければ**予測かテストのどちらかが誤り**（そのまま進めない）。

- [ ] **Step 3: 実装**

**(a) `src/valisync/core/loaders/mdf_handle.py`** — `cache` を提げる。

```python
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # 実行時 import は不要 (注釈は from __future__ で文字列化済み)。
    from valisync.core.loaders.channel_cache import ChannelSampleCache


class MdfHandle:
    """開いたままの asammdf MDF と直列化ロックを包む。

    asammdf の select/get は単一の共有 self._file を seek+read するためスレッド
    非安全。グループ内の全 LazyMdfValues はこの lock で読みを直列化する。ハンドルは
    SignalGroup が 1 個所有し、unload/エラー経路で close() する (増分B/M3)。"""

    __slots__ = ("_close_lock", "_closed", "cache", "lock", "mdf", "source_path")

    def __init__(
        self,
        mdf: Any,
        source_path: str = "",
        cache: ChannelSampleCache | None = None,
    ) -> None:
        self.mdf = mdf
        self.lock = threading.Lock()
        # close の check-and-set 専用の小さい lock。読み直列化用の self.lock とは
        # **別物**にする — 同じ lock を使うと、二重 close かどうかを判定するだけの
        # ために in-flight な select の完了を待つことになり GUI が固まる。
        self._close_lock = threading.Lock()
        self._closed = False
        # 遅延読みの失敗診断を「どのファイルの話か」で出すために保持する。
        # ハンドルは 1 ファイル 1 個なので、26 万個の LazyMdfValues 各々に
        # 持たせるより安い (信号側は既に Signal.source_file を持つ)。
        self.source_path = source_path
        # E-4a: デコード済みチャンネル 2-D のプロセス単位 LRU (所有は Session)。
        # ハンドルに提げるのは、LazyMdfValues が既に handle しか持たないから —
        # 信号 26 万個に別の参照を配らずに全列へ届く唯一の場所である。
        # None ならキャッシュ無し = E-3 と同一挙動 (MdfLoader を直接使う経路)。
        self.cache = cache
```

`is_closed` / `close()` は無変更。

**(b) `src/valisync/core/models/sample_source.py`** — `LazyMdfValues` を位置パス＋共有キャッシュへ。

冒頭の `TYPE_CHECKING` ブロックに `ColumnPath` を足す:

```python
if TYPE_CHECKING:
    from valisync.core.loaders.column_names import ColumnPath
    from valisync.core.loaders.mdf_handle import MdfHandle
```

クラス本体（docstring / `__slots__` / `__init__` / `array()` を置換、`_closed_error` は無変更）:

```python
class LazyMdfValues:
    """MDF から値配列をオンデマンド読みする SampleSource。

    初回 array() で現行 eager と同一意味論の単一チャンネル select を lock 下で実行し、
    LD-14 の位置パスがあれば該当リーフ列を抽出、native dtype 凍結してキャッシュする。
    デコード済みのチャンネル 2-D は handle が持つ ChannelSampleCache で同一
    チャンネルの全列が共有する (E-4a) — 兄弟列の 2 本目以降は select を呼ばない。"""

    __slots__ = (
        "_cache",
        "_ci",
        "_gi",
        "_handle",
        "_length",
        "_name",
        "_path",
        "_selector",
    )

    def __init__(
        self,
        handle: MdfHandle,
        name: str,
        gi: int,
        ci: int,
        length: int,
        selector: tuple[str, ...] | None = None,
        path: ColumnPath | None = None,
    ) -> None:
        if (selector is None) != (path is None):
            # 片方だけ渡せる形にすると、列が容器分岐 (2-D 丸ごと) を通って
            # 「例外の出ない誤データ」になる。名前 (永続キー) と位置 (ロードごとに
            # 導出) は同じ 1 本のリーフの両面なので、対でしか受けない。
            raise ValueError("selector と path は対で渡すこと (列の名前と位置)")
        self._handle = handle
        self._name = name
        self._gi = gi
        self._ci = ci
        self._length = length
        # 名前は **永続キーのまま**保つ (LD-14 リーフ名・spec §5.6)。読みには使わ
        # なくなったが、診断とオラクル (test_mdf_loader_lazy) の宛先として残す。
        self._selector = selector
        # リーフへの位置。位置引きにすると読みが _flatten の全リーフ辞書を作らずに
        # 済む (幅 1,100 のチャンネルで 1/1,100 の仕事)。
        self._path = path
        self._cache: np.ndarray | None = None
```

`array()` を以下で置換する:

```python
    def array(self) -> np.ndarray:
        cached = self._cache
        if cached is not None:
            return cached  # ヒットは lock 不要 (代入は 1 回だけ・GIL 下で atomic)
        if self._handle.is_closed:
            # 先行 bail: close() の GUI 最悪待ちを「残り全列のループ」から
            # 「in-flight select 1 本」に縮める (belt-and-braces)。
            raise self._closed_error()
        channel_cache = self._handle.cache
        key = (id(self._handle), self._gi, self._ci)
        # E-4a: デコード済みチャンネル 2-D は同一チャンネルの全列で共有する。
        # ここで **lock を取らない** のが要点 (spec §5.8) — ヒットの意味は
        # 「ファイルに触らない」なので、他スレッドの in-flight select
        # (prod 実測 316 ms) を待つ理由が無い。取るとエクスポート中の再描画が
        # キャッシュに載っている列でも固まる。
        if channel_cache is not None:
            shared = channel_cache.get(key)
            if shared is not None:
                return self._column_of(shared)
        with self._handle.lock:
            if self._cache is not None:  # ← 削除禁止 (double-checked の "second check")
                return self._cache
            if self._handle.is_closed:  # ← lock 内判定も **維持** (外へ出すと TOCTOU)
                raise self._closed_error()
            # lock 内で channel_cache を引き直さないのは、1 回の読みで miss を
            # 二重計上しないため (misses == select 回数 が ①gate の観測点)。
            # 代償は「同一チャンネルの別列を **同時に** 読み始めた」稀なケースで
            # select が 1 本余分に走ること (値は同じ・正しさには影響しない)。
            try:
                asig = self._handle.mdf.select(
                    [(self._name, self._gi, self._ci)],
                    raw=False,
                    ignore_value2text_conversions=True,
                    copy_master=False,
                )[0]
                samples = asig.samples
            except Exception as exc:  # I/O・破損・閉鎖後アクセス等
                raise SampleReadError(
                    f"信号 '{self._name}' のサンプル読み取りに失敗しました: {exc}",
                    signal_key=self._name,
                    source_file=self._handle.source_path,
                ) from exc
            # 共有する前に read-only 化する: 以後この配列は同一チャンネルの全列が
            # 同時に見るので、書ける配列を配ると 1 列の in-place 変更が全列へ伝播
            # する。キャッシュ未配線の構成でも同じ経路を通す (分岐を作ると、テストが
            # production と違う道を測ることになる)。
            samples.flags.writeable = False
            col = self._column_of(samples)  # 長さ不変条件もこの中で執行する
            if channel_cache is not None:
                # put は **長さ検証を通った後**。壊れた読みを共有キャッシュへ
                # 焼き付けると、同じチャンネルの全列が以後その配列を見る。
                # 予算超のエントリは載らない (put が False・spec D7) が、
                # 呼び出し側から見た値の意味は変わらない。
                channel_cache.put(key, samples)
            return col

    def _column_of(self, samples: np.ndarray) -> np.ndarray:
        """チャンネルの 2-D から自分の列を切り出し、検証・凍結してキャッシュする。

        **返す配列は共有 2-D のビューであってはならない** (spec §5.4)。ビューを
        ``_cache`` へ焼き付けると (a) LRU が evict しても列 Signal が base 経由で
        チャンネル全体を生かし RSS が 1 バイトも下がらず (b)
        ``nbytes_if_materialized`` がビュー自身の nbytes を返すので teardown の
        バイト軸が実体の 1/1000 を計上する。``_freeze`` は **read-only 入力を
        素通しする** ので、この責務は ``apply_path`` 側の copy (T1 の契約) が負う
        — 凍結は守ってくれない。

        逆に、その素通し性のおかげで**列読みのコピーは 1 回で済む**: ``apply_path``
        は自分が作った配列を read-only にして返す契約なので、下の ``_freeze(col)``
        は**何もコピーしない**。ここを「凍結していない配列が来るかもしれない」と
        読んで明示 copy を足したり、``apply_path`` 側の凍結を外したりすると、
        E-4a が縮めようとしているホットパスで毎列 2x のアロケーション + memcpy に
        戻る (値のテストは両方とも緑のままなので、数字にも現れない)。
        """
        try:
            if self._path is not None:
                # 遅延 import: sample_source(model) -> loaders の循環を避ける
                from valisync.core.loaders.column_names import apply_path

                col = apply_path(samples, self._path)
            else:
                # 容器 (物理チャンネル全体) を読む器。連続なら共有実体をそのまま
                # 指すが、これは「チャンネル全部を持つ Signal」なので会計は正しい
                # (列の 1/1000 計上とは別物)。
                col = np.ascontiguousarray(samples)
            if len(col) != self._length:
                # 長さ不変条件の**唯一の執行点**: Signal.__post_init__ は展開を
                # 避けるため source.length (= 宣言値 len(master)) しか見ないので、
                # follower のレコード数が master とずれる仮想グループ (v4.20+
                # remote-master/column-storage) は構築時検証を通り抜ける。render の
                # ts[lo:hi] / vs[lo:hi] は numpy が黙って clamp するため、ここで
                # 止めないと「エラーにならない誤った波形」になる。**2 つのキャッシュ
                # のどちらへ入れるより前**に投げて、壊れた列も壊れたチャンネルも
                # 焼き付けない。try 内に置くのは、想定外の形状 (0-d 等) で len() が
                # TypeError になっても下の except Exception が SampleReadError へ
                # 包み、degrade 機構の外へ漏らさないため。
                raise SampleReadError(
                    f"信号 '{self._name}' のサンプル数が宣言と一致しません "
                    f"(宣言 {self._length} / 読み取り {len(col)})",
                    signal_key=self._name,
                    source_file=self._handle.source_path,
                )
        except SampleReadError:
            raise
        except Exception as exc:  # 形状不整合・パス不整合等
            raise SampleReadError(
                f"信号 '{self._name}' のサンプル読み取りに失敗しました: {exc}",
                signal_key=self._name,
                source_file=self._handle.source_path,
            ) from exc
        col = _freeze(col)
        self._cache = col
        return col
```

**(c) `src/valisync/core/loaders/mdf_loader.py`** — キャッシュを handle へ注入する。

import に追加:

```python
from valisync.core.loaders.channel_cache import ChannelSampleCache
```

`class MdfLoader:` の docstring 直後（`_READ_OPTIONS` の前）へ:

```python
    def __init__(self, cache: ChannelSampleCache | None = None) -> None:
        # 生成する MdfHandle へ渡すだけ (所有は Session — 予算の裁定者は 1 人・
        # spec §5.2)。None はキャッシュ無し = E-3 と同一挙動。
        self._cache = cache
```

`load()` 内の handle 生成（現 270 行）を差し替え:

```python
        handle = MdfHandle(mdf, str(resolved_path), cache=self._cache)
```

`LazyMdfValues(handle, base_name, _g, _c, length=len(master))`（現 553-555 行）は無変更（`selector`/`path` とも None＝容器）。

**(d) 鋳造時に位置を導出する（`column_names.py` ＋ `signal_group_manager.py`）**

まず `src/valisync/core/loaders/column_names.py` の import 行（現 15-16 行目）に `field` を足す:

```python
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
```

`ColumnRecord`（現 33-46 行）へ**位置索引フィールド**を追加する（他の 4 フィールドは不変）:

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
    # E-4a: {リーフ名サフィックス: ColumnPath} の **遅延構築** 索引 (I-2)。
    # 引くたびに leaf_paths を頭から回すと 1 鋳造が O(全リーフ) になり、幅 1,100 の
    # チャンネルの全列鋳造で 1.2M ステップ = **O(n^2)**。E-4b の「すべて選択 ->
    # エクスポート」は E-4a 完了に依存する (spec §4) ので、そこで律速になる。
    # **レコードに持たせる**のが要点: 寿命が _column_records と完全に一致するので、
    # remove(key) でレコードごと落ちて別の掃除経路を要らない。
    # frozen なのは属性の再束縛を禁じるためで、dict の in-place 更新は許される。
    # compare=False: 索引は導出値であって同一性の一部ではない (== と hash を
    # 現状のまま保つ — ロードごとに索引の有無が違うだけで別レコード扱いになると、
    # 表の突き合わせテストが理由なく落ちる)。
    # **eager に埋めない**: ブラウザの閲覧だけで 264k 本の ColumnPath を作ると
    # E-3 が潰したオブジェクト数の回帰になる。埋めるのは実際に列を鋳造した
    # チャンネルだけ (_leaf_path が初回に 1 度)。
    path_index: dict[str, ColumnPath] = field(
        default_factory=dict, compare=False, repr=False
    )
```

（`ColumnPath` は同モジュールの後方で定義されるが、`from __future__ import annotations` により注釈は文字列化されるので前方参照で問題ない。構築サイトは `mdf_loader.py:541` の 1 箇所のみで、そこは keyword 引数なので無変更。）

次に `src/valisync/core/loaders/signal_group_manager.py`。import を差し替え:

```python
from valisync.core.loaders.column_names import (
    ColumnPath,
    ColumnRecord,
    leaf_count,
    leaf_names,
    leaf_paths,
    parse_leaf,
)
```

（`ColumnSpec` は足さない — `_leaf_path` が `ColumnRecord` を受けるようになったので
このモジュールに `ColumnSpec` の参照は 1 つも無く、足すと ruff `F401` で落ちる。）

モジュール末尾（`_ResolvingMap` の前）へヘルパを追加:

```python
def _leaf_path(record: ColumnRecord, suffix: str) -> ColumnPath | None:
    """リーフ名サフィックスから **位置** を引く (E-4a・解決不能なら None)。

    サフィックス (``[2]`` / ``.xa``) は 2 つのキー空間 (LD-08 dedup 済み表示名 /
    生チャンネル名) が共有する唯一の部分なので、位置は dedup のずれを受けない —
    生名側でしか引けない ``parse_leaf`` (docstring の precondition) と対照的に、
    ここは表示名側の残余をそのまま使える。``leaf_paths`` は ``_flatten`` と同順で
    **全**リーフを返す (非数値も含む) ので、数値ゲートは呼び出し側の
    ``parse_leaf`` に残す — ここで数値判定を兼ねると混在構造 ``Q`` の
    ``Q.tag`` が裏口から列になる。

    **索引は ``record`` 側に 1 度だけ作る** (I-2): 引くたびに ``leaf_paths`` を頭から
    回すと 1 鋳造が O(全リーフ) になり、幅 1,100 のチャンネルを全列鋳造すると
    1.2M ステップ = **O(n^2)** になる。E-4b の「すべて選択 -> エクスポート」は
    E-4a 完了に依存する (spec §4) ので、そこで律速するのはここ。初回の 1 回だけ
    全リーフを歩く (= 従来の**最悪 1 回分**と同じコスト) ので、単発の鋳造は遅く
    ならない。索引を持つのは実際に列を鋳造したチャンネルだけで、閲覧しかしない
    チャンネルには 1 バイトも作らない。

    書き込みは dict への代入 1 発 (GIL 下で atomic) で、二重に走っても同じ内容を
    作り直すだけ。T3 以降は ``resolve`` が ``_resolved_lock`` 下で ``_mint_column``
    を呼ぶので、そもそも重ならない。
    """
    index = record.path_index
    if not index:
        # 0 リーフのチャンネル (幅 0 軸) は毎回空走査になるが、その走査自体が
        # O(1) (leaf_paths が 1 件も yield しない) なので償却の意味がない。
        index.update(leaf_paths(record.spec))
    return index.get(suffix)
```

`_mint_column` の `raw_leaf` 以降（現 359-378 行）を差し替え:

```python
            raw_leaf = f"{record.raw_base_name}{rest}"
            if parse_leaf(raw_leaf, {record.raw_base_name: record.spec}) is None:
                continue  # 消費しきれない / 非数値リーフ = この親では解決不能
            path = _leaf_path(record, rest)
            if path is None:
                continue  # 名前は通ったが位置が引けない = この親では解決不能
            parent = self._physical_signal(group_key, display_key[:i])
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
                    # 名前は永続キー・位置は読み経路。両方渡すのが列の契約。
                    selector=(raw_leaf,),
                    path=path,
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
```

**(e) `src/valisync/core/session.py`** — キャッシュを 1 個所有し、close の前に落とす。

import に追加:

```python
from valisync.core.loaders.channel_cache import ChannelSampleCache
```

`__init__`（現 121-131 行）を差し替え（**生成順が重要** — `MdfLoader` へ渡す前に作る）:

```python
    def __init__(self, cache_budget_bytes: int | None = None) -> None:
        self._groups = SignalGroupManager()
        self._csv_loader = CsvLoader()
        # E-4a: デコード済みチャンネル 2-D の LRU。**Session が 1 個だけ持つ** —
        # 予算 (U3: 256 MB) の裁定者を 1 人にするため (spec §5.2)。ローダーは
        # これを MdfHandle へ提げるだけで所有しない。
        #
        # cache_budget_bytes は予算の注入口 (テスト / realgui ①gate 用・D6
        # 「予算を注入して小さくする」)。**setter ではなくコンストラクタ引数**に
        # するのが要点: この __init__ が MdfLoader へ渡した時点で MdfLoader._cache が
        # このオブジェクトを捕捉し、MdfHandle はロード時にそれを提げる。
        # LazyMdfValues.array() が見るのは self._handle.cache なので、後から
        # session.channel_cache へ別インスタンスを差し込んでも **誰もそれを書かない**
        # (misses も bytes_held も 0 のまま = 予算注入が構造的に成立しない)。
        # 同じ理由で channel_cache に setter は置かない。
        self._channel_cache = (
            ChannelSampleCache()
            if cache_budget_bytes is None
            else ChannelSampleCache(budget_bytes=cache_budget_bytes)
        )
        self._mdf_loader = MdfLoader(cache=self._channel_cache)
        self._formula = FormulaEngine()
        self._synchronizer = TimeSynchronizer()
        self._interpolator = Interpolator()
        self._statistics = RangeStatistics()
        self._downsampler = Downsampler()
        self._exporter = CsvExporter()
        self._derived: list[_DerivedRecord] = []

    @property
    def channel_cache(self) -> ChannelSampleCache:
        """チャンネル 2-D の共有 LRU (鋳造も読みも誘発しない introspection)。

        hits/misses/evictions/skipped_oversize/bytes_held は計測器 (E-4a の
        出口表) と realgui ①gate の観測点。「select 回数」を数える口は他に無い。

        **setter は無い** (``__init__`` の WHY 参照): 差し替えても既にロード済み /
        これからロードする ``MdfHandle`` は ``MdfLoader`` が捕捉した旧インスタンスを
        提げるので、注入した新キャッシュには 1 バイトも載らない。予算を変えたい
        呼び出し側は ``Session(cache_budget_bytes=...)`` を使う。
        """
        return self._channel_cache
```

`remove_group` の close 部分（現 367-368 行）を差し替え:

```python
        if group.handle is not None:
            # **close の前**に落とす (spec §5.7)。キーは id(handle) を含むだけで
            # ハンドルを所有しないので、エントリを残したままハンドルが死ぬと、
            # 次のロードが同じアドレスを再利用したときに古いファイルの 2-D を
            # 引き当てる (長さが合えば例外も出ない = 値の無言すり替え)。
            self._channel_cache.drop_handle(id(group.handle))
            group.handle.close()
```

**(f) `tests/core/loaders/test_column_roundtrip.py`** — 独立オラクルの論拠を書き替える（I-4）。

本タスクで読み経路が `_flatten` を呼ばなくなるので、同モジュール冒頭の
「`_flatten` は反転後も `LazyMdfValues.array()` が使い続ける（`sample_source.py` の遅延 import）ため、**反転を跨いで同一のオラクル**になる」は
**事実として偽になる**（放置すると「誰も使わない関数と解決器を突き合わせているだけ」の構造に見え、次の読者が「なら消してよい」と判断する）。
module docstring の第 2 段落を次へ差し替える（他の段落・テスト本体・assert は 1 行も変えない）:

```python
**なぜ独立参照を eager ローダーに置かないか**: E-3 でローダーは物理チャンネル 1 本に
つき Signal 1 個しか発行しなくなる。eager 展開の結果を参照にすると、参照そのものが
反転で消えてテストが書き換え対象になる。代わりに asammdf の ``select`` と ``_flatten``
の直叩きを参照に置く。

**E-4a 以降、``_flatten`` は読み経路から外れた** (位置パス ``ColumnPath`` /
``apply_path`` へ移行・spec §5.6)。したがって本モジュールが突き合わせているのは
「production が今も呼ぶ関数」ではなく、**列キー文法の独立した第 2 実装**である。
production の位置引きと ``_flatten`` を繋ぎ止める紐は
``tests/core/loaders/test_column_paths.py`` が持つ (``leaf_paths`` の走査が
``_flatten`` の出力と順序込み・値込みで一致することを実 mf4 で pin している)。
**その紐と本モジュールは対で意味を持つ**ので、片方だけを削除・弱体化してはならない
— 紐が切れると「両方同じだけ壊れている」を全数テストが見逃す。
```

- [ ] **Step 4: 通ることを確認**

```
uv run pytest tests/core/loaders/test_channel_cache_read_path.py -q
uv run pytest tests/core/loaders/test_column_roundtrip.py tests/core/loaders/test_mint_column.py \
              tests/core/loaders/test_mdf_handle_concurrency.py tests/core/loaders/test_resolver.py \
              tests/core/test_handle_release.py tests/test_loaders.py tests/test_session.py -q
uv run pytest -q
```

**受け入れ条件**: 既存テストは **1 行も書き換えずに全部緑**であること（例外は Step 3 (f) の `test_column_roundtrip.py` module docstring だけ — assert は 1 つも触らない）。特に

- `test_column_roundtrip.py`（全数 36 列の値・dtype・master identity・metadata）
- `test_loaders.py::test_lazy_selector_column_matches_eager_flatten_synthetic`
- `test_mdf_handle_concurrency.py::test_concurrent_first_reads_select_once`（select 1 回・両スレッドが同一オブジェクト＝ミスパスの抽出を lock の外へ出すと落ちる）
- `test_mdf_handle_concurrency.py::test_cache_hit_takes_no_lock` / `test_lazy_read_length_mismatch_raises_sample_read_error`

**書き換えが要ると分かった時点で止めて報告する**（契約が変わったということなので、勝手に直さない）。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

**`git checkout -- src/...` で戻さないこと**（過去に実装者が自分の未コミット作業を消している）。`git stash` も使わない。各 sabotage の前に対象ファイルを `cp` で退避し、確認後にコピーで戻す。

各 sabotage で「どのテストが RED になったか」を**実際に走らせて確認し、結果を報告に貼る**。到達範囲は主張でなく実測で確かめる。

| # | 壊す場所 | 期待 RED | 期待どおり**緑のまま**（＝そのテストは当該変異に盲目） |
|---|---|---|---|
| S1 | `column_names.apply_path` の `if out.base is not None: out = out.copy()` を削除 | `test_minted_column_owns_its_values_on_the_cache_hit_path`（`values.base is None`）／`test_dropping_the_channel_frees_the_2d_because_the_column_is_independent`（weakref が生きたまま） | `_retained_bytes` の等式（ビューの `.nbytes` はコピーと同値）／全ての値一致テスト（ビューでも値は正しい）／幅 3 の `Mat[1]` を使うテスト（`ascontiguousarray` が必ずコピーするので変異が届かない — `test_leaf_view_of_these_shapes_is_already_contiguous` が根拠） |
| S2 | `array()` の `shared = channel_cache.get(key)` ブロックを削除（常に miss） | `test_sibling_column_hits_the_cache_without_select_or_lock`（`len(selected) == 1` が 2・`cache.hits == 1` が 0） | 値の一致テスト全部 |
| S3 | `key = (0, self._gi, self._ci)`（handle 軸を外す） | `test_cache_key_separates_two_files_with_identical_positions` | 同一ハンドル内の 2 本（`..._share_a_raw_name` / `..._in_one_group`） |
| S4 | `key = (id(self._handle), self._gi, 0)`（ci 軸を外す） | `test_cache_key_separates_two_channels_in_one_group` | `..._share_a_raw_name`（fixture の gi が違うので届かない — テスト内の `group_index != ` assert がその根拠） |
| S5 | `key = (id(self._handle), 0, self._ci)`（gi 軸を外す） | `test_cache_key_separates_channels_that_share_a_raw_name` | `..._in_one_group`（gi が同じなので届かない） |
| S6 | `_column_of` の **`if self._path is not None:` の分岐だけ**を `dict(_flatten(self._name, samples))[self._selector[-1]]` へ戻す（`else:` の容器分岐＝`np.ascontiguousarray(samples)` は**そのまま残す**。関数まるごと名前引きにすると `self._selector is None` の容器読みで `None[-1]` の `TypeError` になり、RED の理由が「位置パスを外した」ではなく「sabotage の書き方が壊れている」にすり替わる） | `test_column_read_never_builds_the_leaf_name_dict` | 値の一致テスト（名前引きでも同じ列が返るため） |
| S7 | `channel_cache.put(key, samples)` を長さ検証より前（`col = self._column_of(...)` の前）へ移す | `test_a_length_mismatch_is_not_burned_into_the_shared_cache` | 他全部 |
| S8 | `remove_group` の `self._channel_cache.drop_handle(...)` を削除 | `test_unload_drops_the_channel_entries_before_close` | 他全部 |
| S9 | `channel_cache.get(key)` を `with self._handle.lock:` の中へ移す | `test_sibling_column_hits_the_cache_without_select_or_lock`（`lock.acquires == 1` が 2） | 値・select 回数（ヒット自体は成立するため） |
| S10 | `__init__` の `(selector is None) != (path is None)` ガードを削除 | `test_selector_and_path_must_be_given_as_a_pair` | 他全部 |

S1 は本増分で最も壊しやすい点（spec §5.4）なので、**RED になった 2 本のうち weakref の方が「evict しても RSS が下がらない」の直接証拠**であることを報告に明記する。

`_retained_bytes` の等式が S1 で緑のままであることも（盲点の記録として）実測で確かめて書く。**これは同じ実行の中で観測できる**: Step 1 の `test_minted_column_owns_its_values_on_the_cache_hit_path` は等式を `assert values.base is None` より**前**に置いてあるので、S1 を当てると「等式は通過し、その次行の base assert が落ちる」形になる（pytest の失敗行番号が base assert 側であることが、等式が変異に盲目だった証拠そのもの）。もし失敗行が等式側だったら、順序が入れ替わっているか等式の意味が変わっている — そのまま進めず調べる。

- [ ] **Step 6: ゲート＋コミット**

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

4 つとも exit 0 を確認してから（`| tail` に通さない — exit code が隠れる）:

```
git add src/valisync/core/models/sample_source.py \
        src/valisync/core/loaders/mdf_handle.py \
        src/valisync/core/loaders/mdf_loader.py \
        src/valisync/core/loaders/column_names.py \
        src/valisync/core/loaders/signal_group_manager.py \
        src/valisync/core/session.py \
        tests/core/loaders/test_channel_cache_read_path.py \
        tests/core/loaders/test_column_roundtrip.py
git commit -m "perf(core): 列読みをチャンネル単位キャッシュ＋位置パスへ (E-4a T2)

同一物理チャンネルの兄弟列が select と _flatten をやり直していた経路を、
Session が 1 個持つ ChannelSampleCache 経由へ変える。キーは
(id(handle), gi, ci) — 名前は LD-08 重複で一意でなく、表示名はファイル間で
一意でないため (spec §5.3)。読みは名前引きをやめ、鋳造時に導出した ColumnPath で
位置引きする (幅 1,100 のチャンネルで 1/1,100 の仕事・spec §5.6)。

所有権の不変条件 (spec §5.4) を pin: 命中パスは base を持たない独立配列を返す。
_freeze は read-only 入力を素通しするので、共有 2-D のビューを焼き付けると
evict しても RSS が下がらず、teardown のバイト軸が実体の 1/1000 を計上する。
同じ素通し性により、apply_path が read-only で返すぶん列読みのコピーは 1 回で済む。

位置の引き当ては ColumnRecord.path_index (遅延構築・_column_records と同寿命) で
償却する — 毎回 leaf_paths を頭から回すと全列鋳造が O(n^2) になり、E-4b の
「すべて選択 -> エクスポート」がそこで律速する。

予算の注入口は Session(cache_budget_bytes=...) — channel_cache に setter は置かない。
MdfLoader が __init__ 時点のインスタンスを捕捉し MdfHandle がそれを提げるので、
後から差し替えても読み経路は旧インスタンスを見続ける (注入が無言で効かない)。

保存した契約: キャッシュヒットは handle.lock を取らない (§5.8)／_closed は
読み直列化 lock の外／lock 内の is_closed 再判定 (TOCTOU)／double-checked の
second check／長さ不変条件は 2 つのキャッシュのどちらより前に執行。"
```

---

### Task 3: pin 供給と `_resolved_by_key` の evict（D4 supersede を含む）

**Files:**
- Modify: `src/valisync/core/loaders/signal_group_manager.py:1`（import）/ `:25`（定数追加）/ `:39-58`（`__init__`）/ `:85-102`（`remove`）/ `:150-157`（`_invalidate_namespaced` の NOTE）/ `:213-240`（`resolve` / `resolved_keys`）/ `:281-287`（`has_column` docstring）/ `:320-326`（`_mint_column` docstring）＋ LRU/pin API 新設
- Modify: `src/valisync/core/session.py:3`（import）/ `:121-131`（`__init__` — T2 が入れた `cache_budget_bytes` と**併存**させる）/ `:250-272`（`resolve_signal` 近傍へ pin API 追加・`has_column` docstring。`set_pinned_columns` は pin 済み鋳造列の実体バイトを `self._channel_cache.set_reserved()` へ渡す＝ spec §5.2「裁定者は 1 人」の配線）
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py:168-174`（`set_teardown` の直後に `set_pinned_columns`）
- Modify: `src/valisync/gui/viewmodels/graph_area_vm.py:140-144`（`_for_each_panel` の直後に pin セクション）/ `:161-184`（`_on_panel_change`）/ `:221-238`（`remove_tab`）/ `:282-296`（`remove_panel`）
- Modify（docstring supersede のみ・挙動変更なし）: `src/valisync/gui/reference_overlay.py:64`・`:130` / `src/valisync/gui/viewmodels/channel_browser_vm.py:461` / `src/valisync/gui/viewmodels/signal_preview_vm.py:63` / `src/valisync/gui/views/main_window.py:748`
- Create: `tests/core/loaders/test_resolved_column_lru.py`
- Create: `tests/gui/test_column_pin_push.py`
- Test（修正）: `tests/core/loaders/test_resolver.py:140-160`（D4 test-lock 更新）

**Interfaces:**
- Consumes（T2 完了が前提）: 読み経路の `ChannelSampleCache` — 同一 `(id(handle), group_index, channel_index)` の 2 度目の読みで `handle.mdf.select` が呼ばれないこと。`select` の呼び出し回数を観測点にする（T2 がキャッシュをどこに置いたかに依存しない）。**ただし観測が成立するのは cache が配線された経路だけ**なので、`wide` fixture は `MdfLoader(cache=ChannelSampleCache())` を明示的に渡す（`MdfLoader()` だと `handle.cache is None` で読みが常に `select` へ落ち、`test_evicted_column_reread_does_not_touch_the_file_again` は実装が正しくても必ず RED）。
- Consumes（T0）: `ChannelSampleCache.set_reserved(reserved_bytes: int) -> None` — pin 済み鋳造列が抱える実体バイトを予算の裁定者へ渡す唯一の口（spec §5.2 / §5.5）。
- Consumes: `SignalGroupManager.resolve(key) -> Signal | None` / `resolved_keys(group_key) -> frozenset[str]` / `mint_count`（既存）、`GraphPanelVM.plotted_signal_keys() -> list[str]`（既存・重複除去済み）、`SampleSource.nbytes_if_materialized`（未展開は 0・展開を誘発しない）。
- Produces（後続タスクが依存）:
  - `SignalGroupManager.__init__(self, resolved_capacity: int = 512)`
  - `SignalGroupManager.set_pinned_columns(keys: Iterable[str]) -> None`
  - `SignalGroupManager.pinned_columns() -> frozenset[str]`
  - `SignalGroupManager.pinned_column_bytes() -> int`（pin 済み鋳造列が**今**保持している値バイト合計・鋳造も展開も誘発しない）
  - `SignalGroupManager.pinned_overflow -> int`（property）
  - `SignalGroupManager.resolved_capacity -> int`（property）
  - `SignalGroupManager.resolved_lru_keys() -> tuple[str, ...]`（古い順）
  - `SignalGroupManager.resolved_evictions: int`（`mint_count` と同型の公開カウンタ）
  - `Session.__init__(self, cache_budget_bytes: int | None = None, column_capacity: int | None = None)`（T2 の引数を**残したまま**拡張する）
  - `Session.set_pinned_columns(keys: Iterable[str]) -> None` — `SignalGroupManager` へ配ったうえで **`self._channel_cache.set_reserved(self._groups.pinned_column_bytes())` を呼ぶ**（spec §5.2「予算の裁定者は 1 人」の実配線。ここを繋がないと `set_reserved` は誰も呼ばない dead API になり、spec §5.5 が半分だけ実装された状態で出荷される）
  - `Session.pinned_columns() -> frozenset[str]` / `Session.pinned_column_overflow() -> int`
  - `AppViewModel.set_pinned_columns(keys: frozenset[str]) -> None`
  - `GraphAreaVM.pinned_signal_keys() -> frozenset[str]`
- T4（teardown 会計）への影響: `remove(key)` の戻り値（`tuple[SignalGroup, tuple[Signal, ...]]`）と `RemovalResult.removed_columns` の意味は**不変** — evict 済みの列は既に表から外れているので返らない（正しい: 参照が無いので teardown へ渡す必要も無い）。

---

- [ ] **Step 1: 失敗テストを書く**

**(a) `tests/core/loaders/test_resolved_column_lru.py`（新規）**

```python
"""鋳造列 LRU と pin の規則 (E-4a spec §5.5 / D4)。

E-3 は `_resolved_by_key` を無制限に持っていた (決定 C-g で E-4 送り)。E-4a で
バイト予算つき LRU を入れる以上、「同一キー → 同一オブジェクト」は **pin 中のみ**
保証へ supersede される (D4)。本ファイルはその新しい機構 —— 古い順の evict・
pin の不可侵・pin 過多でも拒否しない・remove(key) での帳簿掃除 —— を固定する。
identity 契約そのものの supersede は test_resolver.py が担う。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.mdf4_helpers import write_mdf4_wide_2d
from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models.load_result import LoadResult


@pytest.fixture
def wide(tmp_path: Path) -> Iterator[LoadResult]:
    """幅 8 の 2-D uint8 チャンネル ``Wide`` を 1 本持つ実 mf4 のロード結果。

    列 j の値は ``[j, j, j]`` (write_mdf4_wide_2d の規則) なので、どの列を読んだかが
    値だけで判別できる。実ロードを使うのは、テストダブルで鋳造を偽装すると寿命は
    緑のまま鋳造の中身が壊れていても気づけないから (test_resolver.py と同じ方針)。

    **チャンネルキャッシュを明示的に渡す**のが必須 (T2 の配線): ``MdfLoader()`` を
    引数なしで作ると ``handle.cache is None`` になり、``LazyMdfValues.array()`` は
    キャッシュ分岐を 1 度も通らずに毎回 ``select`` する。すると
    ``test_evicted_column_reread_does_not_touch_the_file_again`` の
    ``assert calls == []`` は**実装が完全に正しくても成立しえず**、同テストを狙う
    sabotage S9 も「壊す前から RED」で識別力ゼロになる。production では
    ``Session.__init__`` がこの注入をしている (ここはその最小再現)。

    ハンドルは teardown で必ず閉じる — Windows は開いたままだと tmp_path の後始末が
    ファイルロックで失敗しうる。
    """
    result = MdfLoader(cache=ChannelSampleCache()).load(
        write_mdf4_wide_2d(tmp_path, cols=8)
    )
    assert result.signal_group is not None
    handle = result.signal_group.handle
    assert handle is not None and handle.cache is not None, (
        "fixture 前提: 読みがチャンネルキャッシュへ配線されていない"
    )
    yield result
    handle.close()


def _register(mgr: SignalGroupManager, result: LoadResult) -> str:
    """``column_records`` ごと登録する (渡さないと鋳造が常に None = 偽緑になる)。"""
    group = result.signal_group
    assert group is not None
    assert {s.name for s in group.signals} == {"Wide", "Clean"}, "反転後の形 (setup 前提)"
    return mgr.add(group, column_records=result.column_records)


def test_unpinned_columns_are_evicted_oldest_first(wide: LoadResult) -> None:
    mgr = SignalGroupManager(resolved_capacity=4)
    key = _register(mgr, wide)
    keys = [f"{key}::Wide[{i}]" for i in range(8)]
    for k in keys:
        assert mgr.resolve(k) is not None

    live = mgr.resolved_keys(key)
    assert keys[-1] in live, "直近に鋳造した列が自分自身を落とした"
    assert keys[0] not in live, "最古の列が落ちていない (evict していない)"
    assert len(live) <= mgr.resolved_capacity
    # 鋳造した 8 本は「生きている」か「evict された」かのどちらかしかない。
    assert mgr.resolved_evictions == len(keys) - len(live)


def test_pinned_columns_survive_eviction_pressure(wide: LoadResult) -> None:
    """pin は予算に関係なく残る (spec §5.5) —— これが 316 ms/列 停止の再発防止。"""
    mgr = SignalGroupManager(resolved_capacity=2)
    key = _register(mgr, wide)
    pinned = f"{key}::Wide[0]"
    first = mgr.resolve(pinned)
    assert first is not None
    mgr.set_pinned_columns({pinned})

    for i in range(1, 8):
        assert mgr.resolve(f"{key}::Wide[{i}]") is not None

    assert mgr.resolved_evictions > 0, "圧力が掛かっていない (setup 失敗 = 反 vacuous)"
    assert pinned in mgr.resolved_keys(key)
    assert mgr.resolve(pinned) is first, "pin 中の列が再鋳造された (D4 の保証違反)"
    assert mgr.mint_count == 8, "pin 済みの列を鋳造し直している"


def test_pins_are_never_refused_and_overflow_is_observable(wide: LoadResult) -> None:
    """pin は拒否しない。予算超過は落とすのではなく **観測可能** にする (D7 と同型)。"""
    mgr = SignalGroupManager(resolved_capacity=2)
    key = _register(mgr, wide)
    pins = {f"{key}::Wide[{i}]" for i in range(5)}
    mgr.set_pinned_columns(pins)
    for k in sorted(pins):
        assert mgr.resolve(k) is not None

    assert pins <= mgr.resolved_keys(key), "予算超で pin を拒否した"
    assert mgr.pinned_overflow == len(pins) - mgr.resolved_capacity

    # pin が予算を食い尽くしていても、LRU の最低容量は無条件に確保される
    # (0 にすると探索した列がその場で自分を落とし、毎回フル再読みになる)。
    probe = f"{key}::Wide[7]"
    assert mgr.resolve(probe) is not None
    assert probe in mgr.resolved_keys(key), "非 pin 用の最低容量が確保されていない"


def test_pinned_column_bytes_counts_only_what_is_materialized(wide: LoadResult) -> None:
    """pin が抱える **実体** バイトだけを数える (Session が予算の裁定者へ渡す値)。

    鋳造しただけの列は 1 バイトも保持していない。「鋳造したから食っている」と
    数えると、ブラウザで覗いただけの列がチャンネルキャッシュの容量を削り、最低容量
    まで痩せて再描画ごとのフルチャンネル再読み (316 ms/列) が復活する。
    introspection が**展開を誘発しない**ことも同時に固定する — 誘発すると、
    pin を push するたびに全 pin 列のフル読みが走る。
    """
    mgr = SignalGroupManager(resolved_capacity=8)
    key = _register(mgr, wide)
    pinned, unpinned = f"{key}::Wide[0]", f"{key}::Wide[1]"
    first, second = mgr.resolve(pinned), mgr.resolve(unpinned)
    assert first is not None and second is not None
    mgr.set_pinned_columns({pinned})

    assert mgr.pinned_column_bytes() == 0, "未展開の pin が予算を食っている"
    assert first._values_source.is_materialized is False, (
        "introspection が展開を誘発した"
    )

    values = np.asarray(first.values)  # ここで初めて実体を持つ (render 相当)
    assert values.nbytes == 3, values.nbytes  # 3 サンプル x uint8 (fixture の規則)
    assert mgr.pinned_column_bytes() == values.nbytes

    _ = second.values  # 非 pin を展開しても reserved は動かない
    assert mgr.pinned_column_bytes() == values.nbytes, "非 pin の実体を数えている"


def test_lru_order_is_recency_not_insertion(wide: LoadResult) -> None:
    """ヒットは recency を更新する (プロット中の列は render のたびにここを通る)。"""
    mgr = SignalGroupManager(resolved_capacity=3)
    key = _register(mgr, wide)
    a, b, c, d = (f"{key}::Wide[{i}]" for i in range(4))
    first_a = mgr.resolve(a)
    mgr.resolve(b)
    mgr.resolve(c)
    assert mgr.resolve(a) is first_a  # ヒット = touch

    mgr.resolve(d)
    live = mgr.resolved_keys(key)
    assert a in live, "最近触れた列が最古扱いで落ちた (touch が効いていない)"
    assert b not in live, "最古の列が残っている (evict 順が recency でない)"


def test_removing_a_group_drops_its_columns_from_the_lru(wide: LoadResult) -> None:
    """remove(key) は recency 表からも外す (残すとアンロード済みキーが枠を食う)。"""
    mgr = SignalGroupManager(resolved_capacity=4)
    key = _register(mgr, wide)
    col = f"{key}::Wide[0]"
    minted = mgr.resolve(col)
    assert mgr.resolved_lru_keys() == (col,)

    _group, columns = mgr.remove(key)
    assert columns == (minted,)  # teardown 会計 (T4) の入口は不変
    assert mgr.resolved_lru_keys() == (), "アンロード済みキーが recency 表に残った"


def test_evicted_column_reread_does_not_touch_the_file_again(wide: LoadResult) -> None:
    """evict された列は **新しい Signal** になるが、読みは T2 のチャンネル
    キャッシュに当たるので ``select`` は 1 回も増えない。

    これが「pin されなかった列を落として良い」根拠そのもの: 落としたコストは
    「オブジェクトの作り直し」だけで、ファイル I/O は戻ってこない。
    """
    mgr = SignalGroupManager(resolved_capacity=2)
    key = _register(mgr, wide)
    group = wide.signal_group
    assert group is not None
    handle = group.handle
    assert handle is not None

    col = f"{key}::Wide[0]"
    first = mgr.resolve(col)
    assert first is not None
    expected = np.asarray(first.values)  # 1 回目の実読み (ここで select が走る)

    calls: list[Any] = []
    real_select = handle.mdf.select

    def counting_select(entries: Any, **kwargs: Any) -> Any:
        calls.append(entries)
        return real_select(entries, **kwargs)

    handle.mdf.select = counting_select  # type: ignore[method-assign]

    for i in range(1, 8):
        assert mgr.resolve(f"{key}::Wide[{i}]") is not None
    again = mgr.resolve(col)
    assert again is not None
    assert again is not first, "evict されていない (setup 失敗 = 反 vacuous)"
    assert np.array_equal(np.asarray(again.values), expected)
    assert calls == [], f"再鋳造がファイルを読み直した: {calls}"
```

**(b) `tests/gui/test_column_pin_push.py`（新規）**

```python
"""pin の供給機構 —— GUI が push する (E-4a spec §5.5)。

``weakref.WeakValueDictionary`` は使えない: VM は ``signal_key: str`` しか持たず
Signal オブジェクトを持たないので、弱参照にすると **何も pin されず** 毎回再鋳造 =
フルチャンネル再読みになる (敵対的レビューで REFUTED 済み)。よって
GraphAreaVM -> AppViewModel -> Session -> SignalGroupManager の一方向 push で配る。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tests.mdf4_helpers import write_mdf4_wide_2d
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM


def _session_with_wide(tmp_path: Path, capacity: int | None = None) -> tuple[Session, str]:
    """幅 8 の 2-D チャンネル ``Wide`` を持つ実 mf4 をロードした Session と group key。

    *capacity* は鋳造列 LRU の容量注入 (D6「予算を注入して小さくする」と同型) —
    実データで evict を起こすには広幅を何十本も触る必要があり、テストの実行時間を
    圧迫するため。
    """
    session = Session() if capacity is None else Session(column_capacity=capacity)
    outcome = session.load(write_mdf4_wide_2d(tmp_path, cols=8))
    return session, outcome.key


def test_pins_span_all_tabs_and_panels(tmp_path: Path) -> None:
    """pin 対象は **全タブ・全パネル**。

    アクティブパネル/アクティブタブに絞ると 2 タブ目の列が evict され、タブを
    戻した最初の再描画で 316 ms/列 停止する (spec §5.5)。
    """
    session, key = _session_with_wide(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    area.active_panel().add_signal(f"{key}::Wide[0]")  # タブ 1 / パネル 1
    area.add_tab()
    area.active_panel().add_signal(f"{key}::Wide[1]")  # タブ 2 / パネル 1
    area.add_panel()
    area.active_panel().add_signal(f"{key}::Wide[2]")  # タブ 2 / パネル 2

    expected = frozenset(
        {f"{key}::Wide[0]", f"{key}::Wide[1]", f"{key}::Wide[2]"}
    )
    assert area.pinned_signal_keys() == expected
    assert session.pinned_columns() == expected


def test_adding_a_signal_pushes_the_pin_to_the_session(tmp_path: Path) -> None:
    session, key = _session_with_wide(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    assert session.pinned_columns() == frozenset()

    area.active_panel().add_signal(f"{key}::Wide[0]")
    assert session.pinned_columns() == frozenset({f"{key}::Wide[0]"})


def test_removing_a_signal_narrows_the_pushed_pin_set(tmp_path: Path) -> None:
    session, key = _session_with_wide(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    panel = area.active_panel()
    panel.add_signal(f"{key}::Wide[0]")
    panel.add_signal(f"{key}::Wide[1]")

    panel.remove_signal(f"{key}::Wide[0]")
    assert session.pinned_columns() == frozenset({f"{key}::Wide[1]"})


def test_removing_a_tab_drops_its_pins(tmp_path: Path) -> None:
    """タブ削除はどのパネルからも "signals" 通知が来ない = 専用の push が要る。"""
    session, key = _session_with_wide(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    area.active_panel().add_signal(f"{key}::Wide[0]")
    area.add_tab()
    area.active_panel().add_signal(f"{key}::Wide[1]")

    area.remove_tab(1)
    assert session.pinned_columns() == frozenset({f"{key}::Wide[0]"})


def test_removing_a_panel_drops_its_pins(tmp_path: Path) -> None:
    session, key = _session_with_wide(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    area.active_panel().add_signal(f"{key}::Wide[0]")
    area.add_panel()
    area.active_panel().add_signal(f"{key}::Wide[1]")

    area.remove_panel(0, 1)
    assert session.pinned_columns() == frozenset({f"{key}::Wide[0]"})


def test_app_viewmodel_forwards_pins_to_the_session(tmp_path: Path) -> None:
    session, key = _session_with_wide(tmp_path)
    app_vm = AppViewModel(session)
    app_vm.set_pinned_columns(frozenset({f"{key}::Wide[3]"}))
    assert session.pinned_columns() == frozenset({f"{key}::Wide[3]"})


def test_plotted_column_survives_browsing_pressure(tmp_path: Path) -> None:
    """プロット中の列は「他の列を覗く」圧力で evict されない (pin の存在理由)。

    非 pin の対照 (browsed) を同じ圧力に置くのが要点 —— これが無いと、圧力が
    そもそも掛かっていないだけの偽緑と区別できない。
    """
    session, key = _session_with_wide(tmp_path, capacity=2)
    area = GraphAreaVM(AppViewModel(session))
    plotted = f"{key}::Wide[0]"
    browsed = f"{key}::Wide[1]"
    area.active_panel().add_signal(plotted)

    pinned_sig = session.resolve_signal(plotted)
    browsed_sig = session.resolve_signal(browsed)
    assert pinned_sig is not None and browsed_sig is not None
    for i in range(2, 8):
        assert session.resolve_signal(f"{key}::Wide[{i}]") is not None

    assert session.resolve_signal(browsed) is not browsed_sig, (
        "非 pin が落ちていない — 圧力不足で pin の効果を検証できていない (setup 失敗)"
    )
    assert session.resolve_signal(plotted) is pinned_sig


def test_pins_reserve_their_bytes_in_the_channel_cache(tmp_path: Path) -> None:
    """pin した列の実体は **チャンネルキャッシュと同じ予算** から引かれる (spec §5.2)。

    「予算の裁定者は 1 人」の実配線そのもの。pin した列は所有権不変条件 (spec §5.4)
    により自前の独立配列を抱えるので、チャンネル 2-D と同じ U3 256 MB を食う。
    繋がないと ``ChannelSampleCache.set_reserved`` は誰も呼ばない dead API になり、
    「プロット中の列 + キャッシュ」の合計が静かに 256 MB を超える —
    **どちらの側も自分の帳簿では予算内に見える**ので、症状は数字に出ない。

    ``reserved`` を直接見るのは、効果 (LRU 容量の縮み) だけを観測しようとすると
    pin が予算に対して小さい構成では何も起きず、配線が外れても緑のまま通るため。
    """
    session, key = _session_with_wide(tmp_path)
    plotted = f"{key}::Wide[0]"
    area = GraphAreaVM(AppViewModel(session))
    area.active_panel().add_signal(plotted)
    assert session.channel_cache.reserved == 0, "未展開の pin が予算を食っている"

    sig = session.resolve_signal(plotted)
    assert sig is not None
    values = np.asarray(sig.values)  # render 相当 — 実体化は pin の **後** に起きる
    area.active_panel().add_signal(f"{key}::Wide[1]")  # 次の pin push で反映される

    assert session.channel_cache.reserved == values.nbytes, (
        "pin の実体バイトが予算の裁定者へ渡っていない (set_reserved が未配線)"
    )
```

**(c) `tests/core/loaders/test_resolver.py` の D4 test-lock 更新**

既存の `test_resolved_table_survives_unrelated_add_and_remove`（行 140-159）を**丸ごと**次で置き換え、直後に supersede の反面テストを追加する。

```python
def test_pinned_column_survives_unrelated_add_and_remove(tmp_path: Path) -> None:
    """(D4 supersede) 「同一キー → 同一オブジェクト」は **pin 中のみ** 保証する。

    Critical 1 (無関係なファイルの load/remove で副テーブルを捨てない) は不変。
    変わったのは保証の**範囲**で、E-4a が `_resolved_by_key` に LRU を入れた以上
    「無条件に同一オブジェクト」は成立しえない (evict を入れる以上ほかに無い)。
    したがってこのテストは **pin を張ってから** 同一性を主張する —— 張らずに緑
    なのは容量に余裕があるという偶然であって、契約の証明にならない。
    失われた保証は test_unpinned_column_identity_is_not_guaranteed_after_eviction
    が明示的に固定する。
    """
    mgr = SignalGroupManager()
    k1 = _add_real(mgr, tmp_path)
    col_key = f"{k1}::Mat[2]"  # 既存 map に無い列キー -> 鋳造経路
    first = mgr.resolve(col_key)
    assert first is not None
    assert mgr.mint_count == 1
    mgr.set_pinned_columns({col_key})  # GUI がプロット中として push した状態
    _ = first.values  # 実際に読ませる (再鋳造されると読み直しになる)
    assert first._values_source.is_materialized is True

    k2 = mgr.add(_group("Other"))  # 2 ファイル目ロード相当
    again = mgr.resolve(col_key)
    assert again is first  # pin 中は同一オブジェクト
    assert again._values_source.is_materialized is True  # 読み直していない
    assert mgr.mint_count == 1  # 再鋳造していない

    mgr.remove(k2)  # 2 ファイル目 unload 相当
    assert mgr.resolve(col_key) is first
    assert mgr.mint_count == 1

    _close(mgr, k1)


def test_unpinned_column_identity_is_not_guaranteed_after_eviction(
    tmp_path: Path,
) -> None:
    """(D4 supersede・失われた保証の明示) pin されていない列は evict されうる。

    **保証されるもの**: 値・名前・時刻軸は同じ (再鋳造は同じ ColumnRecord から
    同じ Signal を作り直す)。読みも T2 のチャンネルキャッシュに当たるので安い。
    **保証されなくなったもの**: オブジェクト同一性と `LazyMdfValues._cache` の
    引き継ぎ。よって `is` 比較で列 Signal を追跡するコードを書いてはならない。
    """
    mgr = SignalGroupManager(resolved_capacity=1)
    k1 = _add_real(mgr, tmp_path)
    first = mgr.resolve(f"{k1}::Mat[1]")
    assert first is not None
    assert mgr.resolve(f"{k1}::Mat[2]") is not None  # 予算超 -> 最古を落とす

    again = mgr.resolve(f"{k1}::Mat[1]")
    assert again is not None
    assert again is not first  # ← 旧契約ではここが `is` だった (意図的 supersede)
    assert again.name == first.name
    assert np.array_equal(np.asarray(again.values), np.asarray(first.values))
    assert mgr.resolved_evictions >= 1

    _close(mgr, k1)
```

上の 2 本が使う後始末ヘルパを `_add_real` の直後（行 60 付近）へ追加する:

```python
def _close(mgr: SignalGroupManager, key: str) -> None:
    """*key* を外してハンドルを閉じる (実 mf4 を開いたまま終わらない)。

    ``_add_real`` は実ファイルを開く。Windows は開いたままだと ``tmp_path`` の
    後始末が mmap ロックで失敗しうる (``test_mdf_handle_concurrency.py`` の
    ``_cleanup`` が同じ罠を記録している)。列の値を**読む**テスト
    (D4 supersede の 2 本) は読み終わるまでハンドルが要るので、fixture の
    finalizer ではなくテスト末尾で明示的に閉じる。

    NOTE: 本モジュールの**既存**テストは開いたまま終わる (先例)。それらは値を
    読まないので今回の変更対象に含めない — 一斉に直すのは別スコープ。
    """
    group, _columns = mgr.remove(key)
    if group.handle is not None:
        group.handle.close()
```

（`test_resolver.py` は既に `import numpy as np` 済み・`_add_real` / `_group` も既存。追加 import は不要。）

- [ ] **Step 2: 失敗を確認**

Run:
```
uv run pytest tests/core/loaders/test_resolved_column_lru.py tests/gui/test_column_pin_push.py tests/core/loaders/test_resolver.py -q
```

Expected: FAIL。代表的な文言:
- `TypeError: SignalGroupManager.__init__() got an unexpected keyword argument 'resolved_capacity'`
- `AttributeError: 'SignalGroupManager' object has no attribute 'set_pinned_columns'`
- `TypeError: Session.__init__() got an unexpected keyword argument 'column_capacity'`
- `AttributeError: 'Session' object has no attribute 'pinned_columns'`
- `AttributeError: 'SignalGroupManager' object has no attribute 'pinned_column_bytes'`
- `AttributeError: 'GraphAreaVM' object has no attribute 'pinned_signal_keys'`

- [ ] **Step 3: 実装**

**3-1. `src/valisync/core/loaders/signal_group_manager.py`**

先頭 import（行 1-13）を次にする（`threading` と `Iterable` の追加のみ）:

```python
from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from types import MappingProxyType

from valisync.core.loaders.column_names import (
    ColumnRecord,
    leaf_count,
    leaf_names,
    parse_leaf,
)
from valisync.core.models import Signal, SignalGroup
from valisync.core.models.sample_source import LazyMdfValues
```

`_UNINHERITED_METADATA`（行 25）の直後に定数を追加:

```python
# 鋳造列 LRU の既定容量 (**列数**)。1 列 ~96 KB (float64 実体化後) なので ~48 MB 相当。
# バイトでなく本数で持つのは、鋳造直後の列がまだ未展開 (nbytes 0) で、バイト予算だと
# 「まだ読んでいない列は無料」に見えて上限が一切効かないため。
_DEFAULT_RESOLVED_CAPACITY = 512

# pin が容量を食い尽くしても非 pin 用に必ず残す枠 (spec §5.5 の「LRU の最低容量を
# 無条件確保」)。0 にすると pin 過多のとき、鋳造した列が evict 走査の中で **自分自身を**
# 落としてしまい、ブラウザのプレビュー 1 本ごとにフルチャンネル再読みが復活する。
_MIN_EVICTABLE_COLUMNS = 1

# 高水位 (容量) を超えたら低水位まで一気に空けるヒステリシスの分母。予算ちょうどへ
# 削ると鋳造 1 本ごとに O(現存列) の走査が要り、E-4b の全列エクスポート (264k 鋳造)
# がそこで律速する。1/8 ずつ空ければ走査は鋳造 8 本に 1 度で済む。
_RESOLVED_EVICT_DIVISOR = 8
```

`__init__`（行 39-58）を次にする:

```python
    def __init__(self, resolved_capacity: int = _DEFAULT_RESOLVED_CAPACITY) -> None:
        self._groups: dict[str, SignalGroup] = {}
        self._counters: dict[str, int] = {}
        self._namespaced_list: list[Signal] | None = None
        self._namespaced_map: dict[str, Signal] | None = None
        self._namespaced_by_key: dict[str, list[Signal]] = {}
        # 鋳造した列 Signal (E-1)。**_invalidate_namespaced() に相乗りさせない** —
        # 相乗りすると 2 ファイル目のロードごとに全プロット列がフルチャンネル再読み
        # (実測 0.73-1.18 s/列) になる純粋な回帰。切り離しは remove(key) と
        # E-4a の LRU evict のみ (どちらもグループ寿命/予算という明示の理由を持つ)。
        self._resolved_by_key: dict[str, dict[str, Signal]] = {}
        # 列鋳造の材料 (E-3)。_resolved_by_key と同じく **_invalidate_namespaced() に
        # 相乗りさせない** — グループの寿命 (add/remove) にだけ従う。相乗りさせると
        # 2 ファイル目のロードで表が消え、鋳造がファイル全体の再走査に落ちる。
        self._column_records: dict[str, dict[str, ColumnRecord]] = {}
        # {group_key: {physical_channel 表示名: 代表 Signal}} — 鋳造の継承元索引。
        # _column_records と同じ寿命 (add/remove のみ・_invalidate_namespaced では
        # 触らない)。索引にするのは、線形走査だと鋳造 1 本あたり O(n_channels)
        # (prod 4,324) を払うから。
        self._physical_by_name: dict[str, dict[str, Signal]] = {}
        self.mint_count = 0
        # ─── 鋳造列 LRU (E-4a・D4) ────────────────────────────────────────────
        self._resolved_capacity = max(1, resolved_capacity)
        # 名前空間つき列キーの recency 順 (dict の挿入順 = 古い順)。値は使わない。
        self._resolved_order: dict[str, None] = {}
        # GUI が push した「今プロットされている列」(spec §5.5)。evict 対象外。
        self._pinned: frozenset[str] = frozenset()
        self.resolved_evictions = 0
        # LRU の帳簿 (順序表・pin 集合) は GUI スレッドと E-4b のエクスポートワーカー
        # が同時に触りうる。MdfHandle._close_lock と同型の**小さい専用 lock** で守る —
        # 読み直列化用の handle.lock とは別物で、この下では I/O を一切しないので
        # 入れ子にならない (spec §5.8)。
        self._resolved_lock = threading.Lock()
```

`remove`（行 85-102）の本体を次にする（docstring は既存のまま・`columns` の取り出しだけ変更）:

```python
        try:
            group = self._groups.pop(key)
        except KeyError:
            raise KeyError(f"no Signal_Group registered under key: {key!r}") from None
        with self._resolved_lock:
            table = self._resolved_by_key.pop(key, {})
            # recency 表からも外す。残すとアンロード済みキーが LRU の枠を食い続け、
            # 生きている列が理由なく落ちる (帳簿の静かなリーク)。
            for column_key in table:
                self._resolved_order.pop(column_key, None)
            columns = tuple(table.values())
        self._column_records.pop(key, None)
        self._physical_by_name.pop(key, None)
        self._invalidate_namespaced()
        return group, columns
```

`_invalidate_namespaced` の NOTE（行 155-157）を次に差し替え:

```python
        # NOTE: _resolved_by_key はここで**捨てない** (Critical 1)。捨てると 2 ファイル目の
        # ロードごとに全プロット列が新オブジェクト (空キャッシュ) となり、次の render で
        # フルチャンネル再読み (実測 0.73-1.18 s/列) が走る。切り離しは remove(key) と
        # E-4a の LRU evict のみ。
```

`resolve`（行 213-236）を次にする:

```python
    def resolve(self, key: str) -> Signal | None:
        """名前空間つきキーを Signal へ解決する (無ければ列として鋳造を試みる)。

        グループ未ロードなら None (正当な不在)。ローダーが列を展開している間は
        全キーが既存 map で解決でき、鋳造経路はテストからのみ exercise される。

        **同一キー → 同一オブジェクトは pin 中のみ保証** (E-4a D4 の意図的
        supersede)。pin されていない列は :meth:`set_pinned_columns` が設定する
        予算に応じて古い順に落ちるので、再解決で**別オブジェクト**が返りうる。
        値・名前・時刻軸は同じで、読みも T2 のチャンネルキャッシュに当たるため
        安い。列 Signal を ``is`` で追跡するコードを書いてはならない。
        """
        self._ensure_namespaced()
        assert self._namespaced_map is not None
        hit = self._namespaced_map.get(key)
        if hit is not None:
            return hit
        group_key = key.split(KEY_SEPARATOR, 1)[0]
        if group_key not in self._groups:
            return None
        with self._resolved_lock:
            table = self._resolved_by_key.setdefault(group_key, {})
            cached = table.get(key)
            if cached is not None:
                # ヒットは recency を更新する。プロット中の列は render のたびに
                # ここを通る (GraphPanelVM が sig_map.get を引き直す) ので、
                # pin 済みの列は放っておいても MRU 側へ寄る。
                self._touch(key)
                return cached
            minted = self._mint_column(group_key, key)
            if minted is None:
                return None
            table[key] = minted
            self._resolved_order[key] = None
            self.mint_count += 1
            self._evict_resolved()
            return minted
```

`resolved_keys`（行 238-240）を lock 下の読みにする:

```python
    def resolved_keys(self, group_key: str) -> frozenset[str]:
        """鋳造済み列キーの集合 (鋳造を誘発しない introspection)."""
        with self._resolved_lock:
            return frozenset(self._resolved_by_key.get(group_key, {}))
```

`resolved_keys` の直後に LRU/pin の公開 API を追加:

```python
    # ─── 鋳造列 LRU と pin (E-4a spec §5.5 / D4) ──────────────────────────────

    def set_pinned_columns(self, keys: Iterable[str]) -> None:
        """今 pin すべき列キー集合を差し替える (GUI が push する)。

        weakref では何も pin されない (VM は ``signal_key: str`` しか持たない)
        ため、GUI 側が明示的に押し込む。集合は**置き換え**であって追加ではない —
        差分更新にすると、パネル削除やクロスパネル軸移動のように「どの経路から
        通知が来るか」が変わる操作で漏れが出る。

        アンロード済みグループのキーが残っていても無害 (グループ key の連番は
        減らないので、外れたキーが後から別の列に当たることはない)。
        """
        pinned = frozenset(keys)
        with self._resolved_lock:
            self._pinned = pinned
            self._evict_resolved()

    def pinned_columns(self) -> frozenset[str]:
        """現在 pin されている列キー集合 (introspection・鋳造しない)."""
        return self._pinned

    def pinned_column_bytes(self) -> int:
        """pin 済みの鋳造列が **今** 保持している値バイトの合計 (spec §5.5)。

        ``Session.set_pinned_columns`` がこれを ``ChannelSampleCache.set_reserved``
        へ渡す (spec §5.2「予算の裁定者は 1 人」)。pin した列は所有権不変条件
        (spec §5.4) により自前の独立配列を抱えるので、チャンネル 2-D と**同じ**
        U3 256 MB を食う — 渡さないと 2 つの帳簿が互いの解放を当てにして両方が
        上限を超える。

        **未展開の列は 0**: 鋳造しただけの列は 1 バイトも保持していない
        (``nbytes_if_materialized`` は展開を誘発しない)。「鋳造したから食っている」
        と数えると、ブラウザで覗いただけの列がチャンネルキャッシュの容量を削り、
        最低容量まで痩せて再描画ごとのフルチャンネル再読みが復活する。

        pin 集合には物理チャンネルのキーも混ざる (プロットしたのがスカラー信号なら
        鋳造列ではない) が、ここには載らない — 走査するのは ``_resolved_by_key``
        (鋳造列の表) だけで、物理チャンネルの実体はグループ側の会計に属するから。

        **タイミング (仕様として受け入れる)**: 実体化は pin の**後**に起きる
        (追加 -> pin push -> render で読み) ので、この値は次の pin 変化まで更新
        されない。過小申告は LRU の容量を広めに見せるだけで、実際の超過は ``put``
        側の evict が吸収する (``bytes_held`` は常に真の値)。

        lock 下で数え切るのは、表のコピーを外へ持ち出すと反復中に別スレッドの
        鋳造で ``dict changed size`` になるから。``nbytes_if_materialized`` は int の
        読みだけで I/O も ``handle.lock`` も触らないので、ロック順の危険は無い。
        """
        with self._resolved_lock:
            return sum(
                int(signal._values_source.nbytes_if_materialized)
                for table in self._resolved_by_key.values()
                for column_key, signal in table.items()
                if column_key in self._pinned
            )

    @property
    def resolved_capacity(self) -> int:
        """鋳造列 LRU の容量 (列数)."""
        return self._resolved_capacity

    @property
    def pinned_overflow(self) -> int:
        """予算を超えて pin されている鋳造列の数 (0 なら予算内)。

        pin は**拒否しない** (拒否するとプロット中の列が落ち、再描画ごとに
        316 ms 停止が復活する) ので、超過は落とすのではなくここで観測する。
        """
        with self._resolved_lock:
            pinned_live = sum(1 for k in self._resolved_order if k in self._pinned)
        return max(0, pinned_live - self._resolved_capacity)

    def resolved_lru_keys(self) -> tuple[str, ...]:
        """鋳造列の recency 順 (**古い順**) — 鋳造を誘発しない introspection."""
        with self._resolved_lock:
            return tuple(self._resolved_order)

    def _touch(self, key: str) -> None:
        """*key* を MRU 側へ移す (呼び出し側が ``_resolved_lock`` を保持していること)."""
        self._resolved_order.pop(key, None)
        self._resolved_order[key] = None

    def _evict_resolved(self) -> None:
        """非 pin の鋳造列を古い順に落として容量へ収める (D4)。

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
            return  # 予算内 — pin の数え直しすらしない (鋳造ホットパスの O(n) 回避)
        pinned_live = sum(1 for k in self._resolved_order if k in self._pinned)
        room = max(self._resolved_capacity - pinned_live, _MIN_EVICTABLE_COLUMNS)
        slack = max(1, room // _RESOLVED_EVICT_DIVISOR)
        keep = max(room - slack, _MIN_EVICTABLE_COLUMNS)
        unpinned = [k for k in self._resolved_order if k not in self._pinned]
        excess = len(unpinned) - keep
        if excess <= 0:
            return
        for column_key in unpinned[:excess]:  # dict は挿入順 = 古い順
            del self._resolved_order[column_key]
            table = self._resolved_by_key.get(column_key.split(KEY_SEPARATOR, 1)[0])
            if table is not None:
                table.pop(column_key, None)
            self.resolved_evictions += 1
```

**3-2. `src/valisync/core/session.py`**

行 3 の import を `from collections.abc import Callable, Iterable, Mapping` にする。

`__init__`（T2 が `cache_budget_bytes` を入れた形）のシグネチャと先頭 2 行を次にする（T2 が足したキャッシュ生成以降は不変 — **`cache_budget_bytes` を消さないこと**）:

```python
    def __init__(
        self,
        cache_budget_bytes: int | None = None,
        column_capacity: int | None = None,
    ) -> None:
        # column_capacity は鋳造列 LRU の容量注入 (テスト/①gate 用・T2 の
        # cache_budget_bytes と同型で、D6 の「予算を注入して小さくする」)。
        # None は production 既定。
        if column_capacity is None:
            self._groups = SignalGroupManager()
        else:
            self._groups = SignalGroupManager(resolved_capacity=column_capacity)
        self._csv_loader = CsvLoader()
```

`has_column`（行 266-272）の直後に pin API を追加:

```python
    def set_pinned_columns(self, keys: Iterable[str]) -> None:
        """今 pin すべき列キー集合を差し替える (GUI が push する・E-4a spec §5.5)。

        pin 済みの鋳造列は LRU の evict 対象外になる。予算を超えても**拒否しない**
        (拒否するとプロット中の列が落ちて再描画ごとに 316 ms 停止が復活する) —
        超過は :meth:`pinned_column_overflow` で観測する。
        """
        self._groups.set_pinned_columns(keys)
        # spec §5.2「予算の裁定者は 1 人」の実配線。pin した列は所有権不変条件
        # (spec §5.4) により**自前の独立配列**を抱えるので、チャンネル 2-D と同じ
        # U3 256 MB を食う。ここを繋がないと ChannelSampleCache.set_reserved は
        # 誰も呼ばない dead API になり、「プロット中の列 + キャッシュ」の合計が
        # 静かに上限を超える — どちらの帳簿でも自分だけは予算内に見えるので、
        # 症状はメモリ以外のどの数字にも出ない。
        # **順序が重要**: 先に set_pinned_columns で pin 集合を確定させてから
        # 数える (逆だと古い pin 集合のバイト数を渡す)。
        self._channel_cache.set_reserved(self._groups.pinned_column_bytes())

    def pinned_columns(self) -> frozenset[str]:
        """現在 pin されている列キー集合 (introspection・鋳造しない)."""
        return self._groups.pinned_columns()

    def pinned_column_overflow(self) -> int:
        """予算を超えて pin されている鋳造列の数 (0 なら予算内)."""
        return self._groups.pinned_overflow
```

**3-3. `src/valisync/gui/viewmodels/app_viewmodel.py`**

`set_teardown`（行 168-174）の直後に追加:

```python
    def set_pinned_columns(self, keys: frozenset[str]) -> None:
        """GraphAreaVM が集めた「今 pin すべき列キー」を Session へ push する。

        E-4a spec §5.5: VM は ``signal_key: str`` しか持たないので weakref では
        何も pin されない。したがって GUI から明示的に押し込む。ここに素通しの
        1 段を置くのは、GraphAreaVM が Session を直接触らない (AppViewModel が
        唯一のアプリ状態の口である) という既存の依存の向きを崩さないため。
        """
        self._session.set_pinned_columns(keys)
```

**3-4. `src/valisync/gui/viewmodels/graph_area_vm.py`**

`_for_each_panel`（行 140-144）の直後に新セクションを追加:

```python
    # ─── Column pins (E-4a spec §5.5) ─────────────────────────────────────────

    def pinned_signal_keys(self) -> frozenset[str]:
        """全タブ・全パネルの plotted entries の signal_key 集合。

        **アクティブパネル/アクティブタブに絞ってはならない** — 2 タブ目の列が
        evict されると、タブを戻した最初の再描画がフルチャンネル再読み
        (実測 316 ms/列) になる (spec §5.5)。
        """
        keys: set[str] = set()
        for tab in self._tabs:
            for panel in tab.panels:
                keys.update(panel.plotted_signal_keys())
        return frozenset(keys)

    def _push_pins(self) -> None:
        """今 pin すべき列キー集合を core へ押し込む (GUI -> core の一方向)。

        core が VM を覗きに行くのではなく GUI が push するのは依存の向きを保つため
        (spec §5.5)。毎回全タブぶん数え直すのは、パネル/タブ削除やクロスパネル軸移動
        のように「どの panel から通知が来るか」が経路ごとに違う変化でも 1 つの計算で
        正しい全体像になるから (差分更新だと経路ごとに漏れる)。
        """
        self._app_vm.set_pinned_columns(self.pinned_signal_keys())
```

`_on_panel_change`（行 161-184）の `_propagating` ガードの直後に push を挿す:

```python
    def _on_panel_change(self, panel: GraphPanelVM, change: str) -> None:
        """Propagate a panel's X-range (when synced) or cursor/delta (always) to siblings."""
        if self._propagating:
            return
        if change == "signals":
            # プロット集合が動いた = pin 集合が動いた (E-4a spec §5.5)。"range" や
            # "cursor" に相乗りさせない — ズーム/パンのたびに全タブを数え直すことに
            # なり、pin が変わらない経路でホットパスを踏む。
            self._push_pins()
        for tab_index, tab in enumerate(self._tabs):
```

（以降は既存のまま。）

`remove_tab`（行 221-238）の末尾、`self._notify("tabs")` の直前に 1 行:

```python
        elif index < self.active_tab_index:
            self.active_tab_index -= 1
        # タブ削除はどのパネルからも "signals" が飛ばない (パネルごと消えるだけ)
        # ので、ここで明示的に押し直す。
        self._push_pins()
        self._notify("tabs")
```

`remove_panel`（行 282-296）の末尾、`self._notify("panels")` の直前に 1 行:

```python
        elif panel_index < tab.active_panel_index:
            tab.active_panel_index -= 1
        self._push_pins()  # remove_tab と同じ理由 (パネルの通知は飛ばない)
        self._notify("panels")
```

**3-5. D4 supersede の docstring 掃除（挙動変更なし・実測 11 サイト）**

「鋳造列は恒久滞留する / LRU は入れない (C-g)」という記述が全て**偽**になる。次の全サイトを「LRU で落ちるようになったが、非 pin 枠を食って本当に必要な列を押し出すので依然として使ってはならない」という**正しい理由**へ書き替える。実施後に

```
uv run python -c "import subprocess,sys; sys.exit(0)"   # 置き換え不要
```
ではなく、次の grep で残存ゼロを確認する:

```
grep -rn --include=*.py "LRU は E-3 では入れない\|LRU なし\|恒久登録\|恒久的に\*\*登録\|恒久滞留\|恒久キャッシュ\|C-g" src/ tests/
```

**`C-g` と `恒久キャッシュ` をパターンに足すのが要点**（実測）: 素朴なパターンだけだと
`src/valisync/gui/views/export_csv_dialog.py:295`（「C-g と同じ理由で E-3 では増やさない」）・
`src/valisync/gui/reference_overlay.py:73`・`tests/gui/test_channel_browser_physical.py:535` `:569`・
`tests/gui/test_main_window.py:580`（assert メッセージ）・`tests/gui/test_reference_overlay.py:555` を**取りこぼす**。
なお `reference_overlay.py:73` と `test_reference_overlay.py:555` の「恒久キャッシュ」は
**別の主張**（容器チャンネルを重ねると `sorted_view()` が float64 へ 8 倍膨張した 2-D を
Signal 側にキャッシュする）で、`_resolved_by_key` の LRU とは無関係のため **書き替えない**
（grep の残存確認で毎回引っ掛かるので、その旨をコミットメッセージに 1 行残す）。

書き替えの雛形（各サイトで文脈に合わせて 1〜2 行）:

> 旧: `_resolved_by_key` へ**恒久的に**登録される (LRU は E-3 では入れない = C-g)
> 新: `_resolved_by_key` へ登録される。E-4a で LRU が入ったので恒久滞留はしなく
>     なったが、**非 pin の枠を食ってプロット中でない列を押し出す**ため、表示や
>     存在判定のためだけに鋳造してはならない (spec §5.5)。

対象（1〜5 は本タスクで既に触るファイル・6〜11 はコメント行のみ）:

1. `signal_group_manager.py` `__init__` の `_resolved_by_key` コメント → 3-1 で差し替え済み
2. `signal_group_manager.py` `_invalidate_namespaced` の NOTE → 3-1 で差し替え済み
3. `signal_group_manager.py` `resolve` docstring → 3-1 で差し替え済み
4. `signal_group_manager.py:281-287` `has_column` docstring（「寿命いっぱい滞留する」）
5. `signal_group_manager.py:320-326` `_mint_column` docstring —— 「列キーの**正典**であり (resolve は同じキーに同じオブジェクトを返す)」を次にする:
   ```
        鋳造した Signal は **pin 中に限り**その列キーの正典 (resolve が同じ
        オブジェクトを返す) であり、namespaced ラッパーと違って別の元 Signal を
        持たない -- ``_sorted_view_delegate`` は付けない。pin されていない列は
        E-4a の LRU で落ちうるので、再解決で別オブジェクトが返る (D4 supersede)。
   ```
6. `src/valisync/core/session.py:266-272` `has_column` docstring
7. `src/valisync/gui/reference_overlay.py:64` 付近（step 2 の説明）
8. `src/valisync/gui/reference_overlay.py:130` 付近（インラインコメント）
9. `src/valisync/gui/viewmodels/channel_browser_vm.py:461` 付近（`_signal_by_key` の警告）
10. `src/valisync/gui/viewmodels/signal_preview_vm.py:63` 付近
11. `src/valisync/gui/views/main_window.py:748` 付近（インラインコメント）
12. `src/valisync/gui/views/export_csv_dialog.py:295`（「C-g と同じ理由で E-3 では増やさない」— 拡張しない理由が C-g への参照になっているので、根拠を spec §5.5 の非 pin 枠へ差し替える）

同じ主張をしている**テスト側の docstring**も同じ文言で直す（挙動 assert は不変・1 行ずつ）:
`tests/gui/test_channel_browser_physical.py:413` `:535` `:537` `:569`（`:569` は assert メッセージ）`:618` /
`tests/gui/test_main_window.py:564` `:580`（`:580` は assert メッセージ）/
`tests/gui/test_reference_overlay.py:496` / `tests/gui/test_signal_preview_vm.py:234`。

**書き替えない（意図的に残す）**: `src/valisync/gui/reference_overlay.py:73` と
`tests/gui/test_reference_overlay.py:555` の「恒久キャッシュ」— 容器チャンネルの
`sorted_view()` が float64 へ 8 倍膨張した 2-D を Signal 側に持つ話であり、
`_resolved_by_key` の LRU とは別の機構。E-4a でも真のまま。

- [ ] **Step 4: 通ることを確認**

```
uv run pytest tests/core/loaders/test_resolved_column_lru.py tests/gui/test_column_pin_push.py tests/core/loaders/test_resolver.py -q
uv run pytest tests/core tests/gui tests/test_session.py tests/test_signal_group_manager_cache.py -q
```

`test_resolver.py` の既存 9 本（`test_removing_own_group_drops_its_resolved_table` 等）と
`test_mint_column.py:309` の `assert mgr.resolve(col_key) is got` が緑のままであることを確認する
（既定容量 512 では evict が起きないので不変であるべき）。落ちたら実装のバグであって
テストを緩めてはならない。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

**手順の決まりごと**: 各 sabotage の前に `git stash` ではなく `git diff > /tmp/e4a-t3.patch` 相当の
pristine copy を取るか、`src/` を別ディレクトリへコピーしてから壊すこと。
**`git checkout -- src/...` で戻してはならない**（未コミットの実装を消した事故が過去にある）。
戻すときは編集で元へ戻し、`git diff --stat` が sabotage 前と一致することを確認する。

**到達範囲は主張でなく実測で確かめる**: 各 sabotage で必ず
```
uv run pytest tests/core/loaders/test_resolved_column_lru.py tests/gui/test_column_pin_push.py tests/core/loaders/test_resolver.py -q
```
を**全部**回し、RED になったテスト名の**全集合**を記録する。「このテストが落ちるはず」を書くのではなく
「実際に落ちた集合」を報告に書く。期待テストが集合に含まれなければ、その機構は誰もテストしていない
（＝テストを直す）。

| # | 壊す場所 | 壊し方 | 期待 RED |
|---|---|---|---|
| S1 | `_evict_resolved` の pin ガード | `if column_key in ...` ではなく `unpinned = list(self._resolved_order)`（pin を除外しない）に変える | `test_pinned_columns_survive_eviction_pressure` / `test_plotted_column_survives_browsing_pressure` / `test_resolver.py::test_pinned_column_survives_unrelated_add_and_remove` |
| S2 | `GraphAreaVM._push_pins` の走査範囲 | `self._tabs` を `[self.active_tab()]` に狭める（＝アクティブタブのみ） | `test_pins_span_all_tabs_and_panels`（`Wide[0]` が欠ける＝「2 タブ目」ケースの実証） |
| S2' | 同上 | さらに `panel.plotted_signal_keys()` を `self.active_panel().plotted_signal_keys()` に狭める | `test_pins_span_all_tabs_and_panels`（`Wide[1]` も欠ける） |
| S3 | `_touch` の recency 更新 | `self._resolved_order.pop(key, None)` の 1 行を削除（＝挿入順のまま） | `test_lru_order_is_recency_not_insertion` |
| S4 | `remove()` の recency 掃除 | `for column_key in table: self._resolved_order.pop(...)` のループを削除 | `test_removing_a_group_drops_its_columns_from_the_lru` |
| S5 | LRU の最低容量 | `_MIN_EVICTABLE_COLUMNS = 0` にする | `test_pins_are_never_refused_and_overflow_is_observable`（probe が自分自身を落として RED。5 本の pin 側は落ちないので、**この 1 assert だけが機構の唯一の防波堤**であることも同時に確認できる） |
| S6 | `_on_panel_change` の push | `if change == "signals": self._push_pins()` を削除 | `test_adding_a_signal_pushes_the_pin_to_the_session` / `test_removing_a_signal_narrows_the_pushed_pin_set` / `test_pins_span_all_tabs_and_panels` / `test_plotted_column_survives_browsing_pressure` |
| S7 | `remove_tab` / `remove_panel` の push | 追加した `self._push_pins()` をそれぞれ削除 | `test_removing_a_tab_drops_its_pins` / `test_removing_a_panel_drops_its_pins` |
| S8 | `AppViewModel.set_pinned_columns` | 本体を `return` (no-op) にする | `test_app_viewmodel_forwards_pins_to_the_session` ほか GUI 側ほぼ全部 |
| S9 | T2 との相互作用 | `LazyMdfValues.array()` の**チャンネルキャッシュ参照**を外す（T2 が入れた分岐を落として常に `select` へ落とす） | `test_evicted_column_reread_does_not_touch_the_file_again`（`calls == []` が RED）。これが「evict しても安い」という主張の唯一の実測点。**前提**: `wide` fixture が `MdfLoader(cache=ChannelSampleCache())` を渡していること — `MdfLoader()` のままだと分岐が最初から効いておらず、壊す前から RED で識別力ゼロになる（sabotage を当てる前に「復元状態で緑」を必ず確認する） |
| S10 | 予算の裁定者の配線 | `Session.set_pinned_columns` から `self._channel_cache.set_reserved(...)` の 1 行を削除 | `test_column_pin_push.py::test_pins_reserve_their_bytes_in_the_channel_cache` の**1 本のみ**。manager 側の pin/LRU テストは**全数緑のまま**＝「裁定者は 1 人」を守っているのがこの 1 assert だけであることを実測で記録する |
| S11 | 予約バイトの数え方 | `pinned_column_bytes` の `nbytes_if_materialized` を `1` （または固定値）に置換して「鋳造しただけで食っている」形にする | `test_pinned_column_bytes_counts_only_what_is_materialized`（`== 0` が RED）。他は緑のまま — 過大申告は LRU 容量を最低容量まで痩せさせるが、`bytes_held` にも値にも現れない失敗モードであることの実証 |

S1 と S6 は production の停止時間に直結するので、RED 集合を報告に**全て**書くこと。
S5 のように「壊しても大半が緑のまま」の項目は、**緑のまま通ったテスト名も**記録する
（過去に「構造的に空虚な sabotage」を摘出しているため、被覆の狭さ自体が成果物）。

- [ ] **Step 6: ゲート＋コミット**

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

4 つとも exit 0 を目視（`| tail` に通さない — exit code が隠れる）。

```
git add src/valisync/core/loaders/signal_group_manager.py \
        src/valisync/core/session.py \
        src/valisync/gui/viewmodels/app_viewmodel.py \
        src/valisync/gui/viewmodels/graph_area_vm.py \
        src/valisync/gui/reference_overlay.py \
        src/valisync/gui/viewmodels/channel_browser_vm.py \
        src/valisync/gui/viewmodels/signal_preview_vm.py \
        src/valisync/gui/views/main_window.py \
        src/valisync/gui/views/export_csv_dialog.py \
        tests/core/loaders/test_resolved_column_lru.py \
        tests/core/loaders/test_resolver.py \
        tests/gui/test_column_pin_push.py \
        tests/gui/test_channel_browser_physical.py \
        tests/gui/test_main_window.py \
        tests/gui/test_reference_overlay.py \
        tests/gui/test_signal_preview_vm.py
git commit -m "$(cat <<'EOF'
feat(core): 鋳造列 LRU と GUI からの pin push (E-4a T3・D4 supersede)

_resolved_by_key に容量つき LRU (既定 512 列) を入れ、GraphAreaVM ->
AppViewModel -> Session -> SignalGroupManager の一方向 push で「今プロット
されている列」を pin する。pin 対象は全タブ・全パネル (アクティブパネルだけ
だと 2 タブ目の列が evict され、タブを戻した最初の再描画で 316 ms/列 停止する)。
pin は拒否せず、予算超過は pinned_overflow で観測可能にする (spec §5.5)。

予算の裁定者を 1 人にする (spec §5.2): Session.set_pinned_columns は pin 済み鋳造列の
実体バイト合計 (pinned_column_bytes — 未展開は 0) を ChannelSampleCache.set_reserved へ
渡す。pin した列は所有権不変条件により自前の独立配列を抱えるので、チャンネル 2-D と
同じ U3 256 MB を食う。繋がないと 2 つの帳簿が互いの解放を当てにして両方が上限を
超える (どちらの側も自分だけは予算内に見えるので数字に出ない)。

D4 の意図的 supersede: 「同一キー -> 同一オブジェクト」を **pin 中のみ保証** へ
変更。evict を入れる以上ほかに無い。test_resolver.py の test-lock を pin つきへ
更新し、失われた保証 (オブジェクト同一性と LazyMdfValues._cache の引き継ぎ) を
反面テストで明示。値・名前・時刻軸は不変で、読みは T2 のチャンネルキャッシュに
当たるため再解決は安い (test_evicted_column_reread_does_not_touch_the_file_again
が select 呼び出し 0 回で実測)。

「LRU は入れない (E-3 C-g)」と書いていた src/ 12 サイト + tests/ 9 サイトの
docstring/assert メッセージを実態へ更新 (残存確認の grep は C-g と恒久キャッシュを
含める)。reference_overlay.py:73 / test_reference_overlay.py:555 の「恒久キャッシュ」は
容器チャンネルの sorted_view の話で LRU とは別機構なので**意図的に残す**。
EOF
)"
```

---

### Task 4: teardown 会計（`cached_arrays`・close 順序）

**Files:**
- Modify: `src/valisync/core/session.py:71-87`（`RemovalResult`）・`src/valisync/core/session.py:332-374`（`remove_group`）
- Modify: `src/valisync/core/loaders/mdf_handle.py:33-48`（`close`）
- Modify: `src/valisync/gui/workers/teardown_service.py:26-34`（import）・`:98`（`_groups`）・`:122-157`（`enqueue`）・`:186-207`（`_drain` 内側ループ）・`:219-254`（`_retained_bytes`）
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py:61`・`:168-174`（`set_teardown` docstring）・`:270-279`（`unload_file` の enqueue）
- Modify: `src/valisync/gui/views/main_window.py:647-651`（`_discard`）
- Test: `tests/test_session.py`（`test_remove_group_reports_minted_columns` = `:237-252` の直後に追記）
- Test: `tests/gui/test_teardown_service.py`（`:161` の後・`_CountingArr` クラス `:163` の前に追記）
- Test: `tests/gui/test_teardown_pacing.py`（末尾 `:277` に追記）
- Test: `tests/gui/test_discard_teardown.py:108-118`（`_DummyTeardown`）・`:176`（unpack）・末尾に追記
- Modify: `tests/gui/test_file_browser_vm.py:146`・`:227`／`tests/gui/test_file_browser_view.py:57`／`tests/gui/test_app_viewmodel.py:291`（duck-typed ダブルの署名）
- Modify: `docs/superpowers/specs/2026-07-30-e4-channel-cache-design.md`（§5.7 と §9 表へ実測値を記録）

**Interfaces:**

- Consumes（T0 `src/valisync/core/loaders/channel_cache.py`）:
  - `CacheKey = tuple[int, int, int]`
  - `ChannelSampleCache.drop_handle(handle_id: int) -> tuple[np.ndarray, ...]`（当該ファイルのエントリを外して**返す**）
  - `ChannelSampleCache.put(key: CacheKey, samples: np.ndarray) -> bool`
  - `ChannelSampleCache.bytes_held -> int`
- Consumes（T2）: **`MdfHandle.cache: ChannelSampleCache | None`** — `Session` 経由で作られたハンドルは全て**プロセス共有 1 インスタンス**を指す（`LazyMdfValues` は `self._handle.cache` で辿るので、遅延ソース 1 個ごとに参照を持たせない）。T4 のコードとテストはこの属性名に対して書かれている。**型が `| None` であることが本タスクの実装制約**: `MdfLoader()`（引数なし）や `MdfHandle(_FakeMdf())` で作られたハンドルは `cache is None` で、既存テスト（`tests/test_loaders.py:522` `:560` のエラー/キャンセル経路・`tests/core/loaders/test_mdf_handle_concurrency.py` の `_cleanup`・T3 の `wide` fixture）がそれらに対して `close()` を呼ぶ。`close()` に None ガードを置かないと**既存テストが大量に `AttributeError`** になる。
- Consumes（既存）: `RemovalResult`（`session.py:71`）・`TeardownService.enqueue(key, group, columns=())`（`teardown_service.py:122`）・`AppViewModel.set_teardown`（`app_viewmodel.py:168`）
- Produces（T5/T6 と GUI が依存）:
  - `RemovalResult.cached_arrays: tuple[np.ndarray, ...]`（既定 `()`）
  - `TeardownService.enqueue(key: str, group: SignalGroup, columns: tuple[Signal, ...] = (), cached_arrays: tuple[np.ndarray, ...] = ()) -> None`
  - `_retained_bytes(obj: Signal | np.ndarray, seen: set[int]) -> int`（型エイリアス `_Freeable = Signal | np.ndarray`）
  - `MdfHandle.close()` が **`self.cache` が None でなければ** `self.cache.drop_handle(id(self))` で自ハンドルのエントリを解放する契約
  - **LRU evict 1 回の同期解放時間の実測値**（spec §9 表の空欄を埋める・T5 の計測器が参照する数値）

---

- [ ] **Step 1: 失敗テストを書く**

**(1-a) `tests/gui/test_teardown_service.py`** — `test_columns_alone_do_not_take_the_empty_group_shortcut`（`:144-160`）の直後、`class _CountingArr` の前に追記:

```python
def test_cached_channel_arrays_drain_in_the_same_entry_and_finish_once(qtbot) -> None:
    """E-4a: ChannelSampleCache から回収した生 ndarray も同じペーシングで解放され、
    on_finished は 1 回だけ発火する。

    ``columns`` (鋳造 Signal) に相乗りさせられないのは型が違うから: キャッシュが
    持つのは Signal の皮を持たない 2-D チャンネル配列そのもの。だが**エントリは
    同じ**でなければならない — 同一 key を 2 エントリに割ると 1 本目の完了で
    on_finished が撃たれ、AppViewModel.mark_released が初回 pop で確定するので、
    配列がまだ残っているのに「解放完了」に見える (列と同じ罠)。
    """
    done: list[str] = []
    svc = TeardownService(on_finished=done.append, byte_budget=1 * 1024 * 1024)
    arr = np.zeros((4096, 64), dtype=np.uint8)  # 2-D チャンネル配列相当 (256 KB)
    ref = weakref.ref(arr)
    grp = _group((_sig("s", 500_000),))

    svc.enqueue("g", grp, cached_arrays=(arr,))

    assert svc.pending_signals() == 2  # グループ 1 本 + キャッシュ配列 1 本
    assert done == []  # まだ 1 本も解放していない
    del grp, arr
    _drain_all(svc, qtbot)
    gc.collect()
    assert done == ["g"]  # エントリが 1 つ = 発火も 1 回
    assert ref() is None  # 会計だけでなく実際の解放も通っている


def test_cached_arrays_alone_do_not_take_the_empty_group_shortcut(qtbot) -> None:
    """signals も columns も空でキャッシュ配列だけ残るグループを即時 finish にしない。

    pin しているのは実データの形ではなく **extend が空判定より前にあること**そのもの:
    順序が逆だと 13.2 MB/本 の配列がペーシングを迂回して同期解放される。
    エクスポートだけが触ったファイル (列を 1 本も鋳造しない) がまさにこの形。
    """
    done: list[str] = []
    svc = TeardownService(on_finished=done.append)
    arr = np.zeros((256, 8), dtype=np.uint8)

    svc.enqueue("g", _group(()), cached_arrays=(arr,))

    assert done == []
    assert svc.pending_signals() == 1
    del arr
    qtbot.waitUntil(lambda: svc.pending_signals() == 0, timeout=5000)
    assert done == ["g"]


def test_zero_cached_arrays_leave_the_existing_pacing_untouched(qtbot) -> None:
    """キャッシュ配列ゼロ = 反転前と挙動が 1 ビットも変わらない。

    空タプルでも幽霊エントリを積まない (pending_signals が増えない) ことと、
    ドレイン前に「解放完了」を宣言しないことを対で見る。列ゼロが production の
    既定経路であるのと同じく、**キャッシュ配列ゼロは CSV/Derived の既定経路**。
    """
    done: list[str] = []
    svc = TeardownService(on_finished=done.append, byte_budget=1 * 1024 * 1024)

    svc.enqueue("g", _group((_sig("a", 500_000),)), columns=(), cached_arrays=())

    assert done == []
    assert svc.pending_signals() == 1  # グループ信号 1 本ちょうど
    _drain_all(svc, qtbot)
    assert done == ["g"]
```

**(1-b) `tests/gui/test_teardown_pacing.py`** — 末尾に追記:

```python
def test_cached_channel_array_bytes_are_counted_by_the_byte_axis(qtbot) -> None:  # type: ignore[no-untyped-def]
    """生 ndarray (Signal の皮を持たない) が会計のバイト軸に載る。

    載らないと 13.2 MB のチャンネル配列が 0 バイト扱いになり、1 ティックに何本でも
    詰め込まれて 64 MiB 予算が黙って効かなくなる — 未展開シェルで一度踏んだ
    「バイト会計が正直でないと予算が死ぬ」regime そのもの (FU-16)。
    """
    svc = TeardownService()
    group = _lazy_group(1)
    m = group.signals[0].timestamps.nbytes
    arr = np.zeros((1024, 16), dtype=np.uint8)

    svc.enqueue("k", group, cached_arrays=(arr,))

    assert svc.pending_bytes() == m + arr.nbytes  # m のみ (= 0 バイト扱い) は不合格


def test_a_cached_array_shared_with_a_signal_is_counted_once(qtbot) -> None:  # type: ignore[no-untyped-def]
    """identity dedup は新しい ndarray 分岐にも効く (会計の保存すべき契約)。

    今日の production は C1 の所有権不変条件により列の値配列とキャッシュ配列が
    別オブジェクトなので、これは再現ではなく**契約ガード**である: 分岐が共通の
    ``seen`` を使わなくなる変異 (C1 の copy を外す / 非セレクタ経路をキャッシュ
    配列の素通しにする) を入れた瞬間に二重計上が始まり、ティックが予算へ早く
    到達してペーシングの実効粒度が黙って粗くなる。
    """
    arr = np.zeros(4096, dtype=np.uint8)
    # _freeze は read-only 入力を素通しする (sample_source.py) ので、凍結してから
    # 渡さないと EagerValues がコピーを持ち、同一オブジェクトの共有を作れない。
    arr.flags.writeable = False
    src = EagerValues(arr)
    assert src.array_if_materialized() is arr, "fixture 前提: 値配列が共有されていない"
    ts = np.arange(4096, dtype=np.float64)
    ts.flags.writeable = False
    sig = Signal(
        name="s",
        timestamps=ts,
        values_source=src,
        file_format="MDF4",
        bus_type="",
        source_file="/x.mf4",
    )
    svc = TeardownService()

    svc.enqueue("k", _group_of((sig,)), cached_arrays=(arr,))

    assert svc.pending_bytes() == ts.nbytes + arr.nbytes  # 2*arr.nbytes は不合格
```

**(1-c) `tests/test_session.py`** — import に `MdfHandle` を追加。挿入位置は `from valisync.core.interpolation import InterpolationMethod` の**直後**（= `from valisync.core.models import ...` の直前）。isort（ruff `I`）はモジュールパスの辞書順なので `valisync.core.interpolation` < `valisync.core.loaders.mdf_handle` < `valisync.core.models` — 「前」に置くと `ruff check` が RED になる:

```python
from valisync.core.loaders.mdf_handle import MdfHandle
```

`test_remove_group_reports_minted_columns`（`:237-252`）の直後に追記:

```python
def _loaded_2d_with_a_cached_channel(tmp_path: Path) -> tuple[Session, str, MdfHandle]:
    """2-D チャンネルの列を 1 本読んで ChannelSampleCache を温めた Session を返す。

    列読みは物理チャンネルの 2-D 配列をデコードしてキャッシュへ載せる (E-4a)。
    温まっていない状態で会計を検証すると全 assert が「空タプル同士の比較」に化けて
    恒真になるので、前提そのものを assert しておく。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    col = session.resolve_signal(f"{key}::Mat[0]")
    assert col is not None
    np.testing.assert_array_equal(col.values, [0, 10, 20, 30])
    handle = session._groups.group(key).handle
    assert handle is not None
    # 「ハンドルが提げているキャッシュ」と「Session が裁定しているキャッシュ」が
    # **同一オブジェクト**であること。別物なら以下の会計は 2 つの帳簿を跨いで
    # 比較することになり、順序テストが偶然通る/偶然落ちるどちらにもなりうる。
    assert handle.cache is session.channel_cache, "ローダーへの注入が効いていない"
    assert handle.cache.bytes_held > 0, "前提が壊れている: 列読みがキャッシュを温めない"
    return session, key, handle


def test_remove_group_recovers_the_cached_channel_arrays(tmp_path: Path) -> None:
    """デコード済みチャンネル配列は RemovalResult 経由で呼び出し側へ渡る (spec §5.7)。

    渡さないと 13.2 MB/本 (prod の広幅チャンネル) が teardown の三軸ペーシングを
    通らず、close() の中で GUI スレッドが同期解放する。``removed_columns`` に
    相乗りできないのは型が違うから (Signal ではなく生 ndarray)。
    """
    session, key, handle = _loaded_2d_with_a_cached_channel(tmp_path)

    result = session.remove_group(key)

    assert result.removed is True
    assert len(result.cached_arrays) == 1
    # 列 1 本 (長さ 4) ではなくチャンネル全体 (4 行 x 3 列) が渡る = キャッシュの実体。
    assert result.cached_arrays[0].shape == (4, 3)
    assert handle.cache.bytes_held == 0  # 予算からは外れている (回収 = 所有権の移譲)


def test_cached_arrays_are_recovered_before_the_handle_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回収は close() より**前**。順序が逆だと会計から丸ごと消える (spec §5.7)。

    close() は自ハンドルのエントリをキャッシュから落とす (= その場で解放する) ので、
    「close 時点で予算に残っていない」が順序の直接の観測点になる。cached_arrays の
    非空だけを見る形は、close 側の解放を将来やめたときに「順序は逆のまま偶然通る」
    テストへ劣化する。
    """
    session, key, _handle = _loaded_2d_with_a_cached_channel(tmp_path)
    held_at_close: list[int] = []
    real_close = MdfHandle.close

    def _spy(self: MdfHandle) -> None:
        assert self.cache is not None  # Session 経由のハンドルなので必ず配線済み
        held_at_close.append(self.cache.bytes_held)
        real_close(self)

    # MdfHandle は __slots__ なのでインスタンス属性の差し替えはできない (クラス側で patch)。
    monkeypatch.setattr(MdfHandle, "close", _spy)

    result = session.remove_group(key)

    assert held_at_close == [0], "close 時点でまだ予算に載っている = 回収が close の後"
    assert len(result.cached_arrays) == 1  # 消えたのではなく移譲された


def test_close_releases_the_handles_cached_arrays_from_the_budget(
    tmp_path: Path,
) -> None:
    """回収されない close 経路 (ローダーのエラー/キャンセル) でも予算が返る。

    キーは id(handle) なので、閉じたハンドルのエントリを残すと害が 2 つある:
    予算が恒久的に目減りし、かつ id が再利用されたとき新しいハンドルが別ファイルの
    配列を引く (memory gui_id_reuse_flake_object_recreation の形)。
    """
    session, _key, handle = _loaded_2d_with_a_cached_channel(tmp_path)
    assert handle.cache is not None and handle.cache.bytes_held > 0

    handle.close()

    assert handle.cache.bytes_held == 0
    assert session.signals()  # グループは残ったまま = close 単独の効果を見ている


def test_close_without_a_cache_is_still_a_plain_close(tmp_path: Path) -> None:
    """``cache is None`` のハンドルを閉じても落ちない (T2 が cache を任意にした帰結)。

    ``MdfLoader()`` を引数なしで使う経路 (ローダー単体テスト・エラー/キャンセル経路の
    finally・T3 の fixture) は ``cache=None`` のハンドルを作り、その全てが
    ``close()`` を呼ぶ。None ガードが無いと ``AttributeError: 'NoneType' object has
    no attribute 'drop_handle'`` が**既存テストの広範囲**で出る — 本タスクの RED と
    区別できなくなるので、ここで正面から固定する。
    """
    handle = MdfLoader().load(write_mdf4_2d(tmp_path)).signal_group.handle
    assert handle is not None and handle.cache is None

    handle.close()  # 例外を出さないこと自体が assert

    assert handle.is_closed is True
```

（`tests/test_session.py` は `MdfLoader` を import していないので、上の 1 本のために
`from valisync.core.loaders.mdf_loader import MdfLoader` を `mdf_handle` の import の
**直後**へ足す＝`loaders.mdf_handle` < `loaders.mdf_loader` < `models`。）

**(1-d) `tests/gui/test_discard_teardown.py`** — `_DummyTeardown`（`:108-117`）を 4-tuple 記録へ差し替え、`test_minted_columns_are_handed_to_the_teardown_service` の unpack（`:176`）を追随させ、末尾に 2 本追記:

```python
class _DummyTeardown:
    """duck-typed teardown — enqueue の実引数 (columns / cached_arrays) をそのまま記録する。"""

    def __init__(self) -> None:
        self.calls: list[
            tuple[str, SignalGroup, tuple[Signal, ...], tuple[np.ndarray, ...]]
        ] = []

    def enqueue(
        self,
        key: str,
        group: SignalGroup,
        columns: tuple[Signal, ...] = (),
        cached_arrays: tuple[np.ndarray, ...] = (),
    ) -> None:
        self.calls.append((key, group, columns, cached_arrays))
```

`:176` の 1 行を差し替え（他の assert はそのまま）:

```python
    got_key, got_group, got_columns, _got_cached = dummy.calls[0]
```

末尾へ追記:

```python
def test_cached_channel_arrays_are_handed_to_the_teardown_service(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """E-4a: ChannelSampleCache から回収した配列も同じ enqueue で渡る。

    渡さないと RemovalResult のスコープアウトで GUI スレッドの同期解放になる
    (1 本 13.2 MB = ペーシングを迂回した瞬間に FU-16 のフリーズ regime へ戻る)。
    """
    app_vm, key, handle = _loaded(tmp_path)
    dummy = _DummyTeardown()
    app_vm.set_teardown(dummy)
    arr = np.zeros((256, 8), dtype=np.uint8)
    # 実在しない group_index を使う (実読みが載せたエントリを踏まない)。
    assert handle.cache.put((id(handle), 999, 0), arr) is True

    app_vm.unload_file(key)

    assert len(dummy.calls) == 1  # 同一 key を 2 エントリに割らない
    _key, got_group, _columns, got_cached = dummy.calls[0]
    assert got_group is not None  # グループ本体は従来どおり渡る
    assert len(got_cached) == 1 and got_cached[0] is arr


def test_discard_also_hands_the_cached_arrays(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """2 サイト目 (_discard) もキャッシュ配列を渡す。

    _discard は AppViewModel を経由しないので、unload_file 側の配線では 1 バイトも
    カバーされない (鋳造列と同じ二重配線の事情)。
    """
    win, outcome, n_signals, discard = _loaded_but_discarded_setup(qtbot, tmp_path)
    # 注意: enqueue はタイマーを再始動する。決定的なのは stop() ではなく
    # 「assert までイベントループを回さない」ことによる。
    win.teardown_service._timer.stop()
    handle = win.app_vm.session._groups.group(outcome.key).handle
    assert handle is not None
    arr = np.zeros((256, 8), dtype=np.uint8)
    assert handle.cache.put((id(handle), 999, 0), arr) is True

    discard(outcome)

    assert win.teardown_service.pending_signals() == n_signals + 1
    entries = win.teardown_service._groups
    assert len(entries) == 1, f"1 キー = 1 エントリのはず ({len(entries)} エントリ)"
    # ndarray に `in` を使うと要素ごとの == で真理値が曖昧になる — identity で探す。
    assert any(item is arr for item in entries[-1][1])
```

**(1-e) duck-typed ダブルの署名追随**（これを Step 1 でやらないと既存テストが `TypeError` で落ち、実装の RED と区別できなくなる）:

`tests/gui/test_file_browser_vm.py:146` と `:227`、`tests/gui/test_file_browser_view.py:57` の 3 箇所を同一形へ:

```python
        def enqueue(
            self,
            key: str,
            group: object,
            columns: object = (),
            cached_arrays: object = (),
        ) -> None:
            pass
```

`tests/gui/test_app_viewmodel.py:291`:

```python
    def enqueue(self, key, group, columns=(), cached_arrays=()) -> None:
```

- [ ] **Step 2: 失敗を確認**

Run:
```
uv run pytest tests/gui/test_teardown_service.py tests/gui/test_teardown_pacing.py tests/test_session.py tests/gui/test_discard_teardown.py -q
```

Expected: 以下が FAIL/ERROR。
- `test_cached_channel_arrays_drain_in_the_same_entry_and_finish_once` / `test_cached_arrays_alone_do_not_take_the_empty_group_shortcut` / `test_zero_cached_arrays_leave_the_existing_pacing_untouched` / `test_cached_channel_array_bytes_are_counted_by_the_byte_axis` / `test_a_cached_array_shared_with_a_signal_is_counted_once`
  → `TypeError: TeardownService.enqueue() got an unexpected keyword argument 'cached_arrays'`
- `test_remove_group_recovers_the_cached_channel_arrays` / `test_cached_arrays_are_recovered_before_the_handle_is_closed`
  → `AttributeError: 'RemovalResult' object has no attribute 'cached_arrays'`
- `test_cached_channel_arrays_are_handed_to_the_teardown_service` / `test_discard_also_hands_the_cached_arrays`
  → 前者は `assert 0 == 1`（`got_cached` が既定の空タプル）、後者は `assert 1 == 2`（`pending_signals` が配列ぶん増えない）
- `test_close_releases_the_handles_cached_arrays_from_the_budget`
  → `assert 24 == 0` 相当の値ずれ（**T2 は `close()` を一切変更しない**ので、この時点では必ず RED。「T2 が先に入れていれば GREEN になりうる」という条件分岐は無い）
- `test_close_without_a_cache_is_still_a_plain_close`
  → **Step 2 の時点では GREEN**（`close()` はまだキャッシュを触らない）。RED になるのは Step 3 で None ガードを忘れたときで、それが本テストの役割そのもの

- [ ] **Step 3: 実装**

**(3-a) `src/valisync/gui/workers/teardown_service.py`**

import ブロック（`:26-34`）を差し替え、型エイリアスを追加:

```python
from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QObject, QTimer

from valisync.core.models import Signal, SignalGroup

# teardown が解放する対象。E-4a で ChannelSampleCache から回収した**生 ndarray**
# (RemovalResult.cached_arrays) が加わった — Signal の皮を持たないので、会計は
# 型で分岐する (_retained_bytes)。同じキューへ載せるのは、ペーシングの三軸
# (バイト / 信号数 / 経過時間) を配列にもそのまま適用したいから。
_Freeable = Signal | np.ndarray
```

`_groups` の宣言（`:98`）:

```python
        self._groups: deque[tuple[str, list[_Freeable]]] = deque()
```

`enqueue`（`:122-157`）を差し替え:

```python
    def enqueue(
        self,
        key: str,
        group: SignalGroup,
        columns: tuple[Signal, ...] = (),
        cached_arrays: tuple[np.ndarray, ...] = (),
    ) -> None:
        """*key* のグループ信号 + 鋳造列 (E-3) + キャッシュ配列 (E-4a) を 1 エントリで積む。

        ``columns`` は ``SignalGroup.signals`` の外に居る鋳造列
        (``RemovalResult.removed_columns``)。``cached_arrays`` は
        ``ChannelSampleCache`` から回収したデコード済みチャンネル配列
        (``RemovalResult.cached_arrays``) で、``columns`` に相乗りできない —
        こちらは Signal の皮を持たない**生 ndarray** だから (spec §5.7)。

        **同一エントリへ連結する**のが要点: ``on_finished`` はエントリごとに発火し、
        その宛先の ``AppViewModel.mark_released`` は初回 pop で確定するため、同じ key を
        2 エントリに分けると 1 本目の完了で releasing 行が消え、まだ残っているのに
        「解放完了」に見える。

        O(1) 契約は維持する: ``list(group.signals)`` も ``extend`` も C レベルの
        ポインタコピーだけで、信号の配列にも ndarray の ``nbytes`` にも一切触らない
        (会計と解放は _drain の担当のまま)。``cached_arrays`` の本数は予算で上界が
        つく (256 MB / 13.2 MB ≈ 19 本) ので、そもそも支配項にならない。
        """
        items: list[_Freeable] = list(group.signals)  # single C-level copy
        # extend は**空判定より前**に置く。後ろだと「signals が空で列/配列だけ残る」
        # グループが下の即時 finish 分岐に落ち、ペーシングを迂回して同期解放される
        # (実体化済みの列も 13.2 MB のチャンネル配列もバイトが重い)。
        # エントリ内の順序は無関係 — _drain は末尾から pop する。
        items.extend(columns)
        items.extend(cached_arrays)
        if not items:
            if self._on_finished is not None:
                self._on_finished(key)
            return
        self._pending_signals += len(items)
        self._groups.append((key, items))
        # NOTE: caller must not keep a ref to `group` / `columns` / `cached_arrays`
        # after this (it does not -- all three hang off the RemovalResult local that
        # falls out of scope); `items` becomes the sole owner, so popping from it
        # frees the arrays.
        if not self._timer.isActive():
            self._timer.start()
```

`_drain` の内側ループ（`:186-207`）で pop した対象は Signal とは限らないので名前を改める:

```python
            while (
                sigs
                and freed_bytes < self._budget
                and freed_signals < self._signal_budget
            ):
                item = sigs.pop()
                # カウンタを pop の直後に更新するのは、会計が raise してもキューと
                # pending_signals() が乖離しないための安価な保険。
                self._pending_signals -= 1
                freed_signals += 1
                freed_bytes += _retained_bytes(item, seen)
                del item  # drop the last strong ref -> the arrays free here
```

`_retained_bytes`（`:219-254`）を差し替え:

```python
def _retained_bytes(obj: _Freeable, seen: set[int]) -> int:
    """この対象が保持しているバイト数 (既に数えた配列は id で除外).

    *obj* が生 ndarray のときは ChannelSampleCache から回収したデコード済み
    チャンネル配列 (E-4a)。Signal の皮を持たないので直接数える。**id dedup は
    Signal 側と同じ ``seen`` を共有する** — 分岐ごとに別集合を持つと、共有された
    配列が二重計上されてティックが予算へ早く到達し、ペーシングの実効粒度が
    黙って粗くなる。

    master はグループ内で identity 共有されるので、信号ごとに数えると prod_demo で
    実体 0.2 MiB に対し 10,316 MiB (約 5 万倍) を計上してしまう。
    未展開信号の sig.values は絶対に読まない (読むと遅延ロードを再誘発する) —
    値は array_if_materialized() で「展開済みのときだけ」取る。

    `_range_stat_index_cache` (RangeStatIndex のブロック配列 5 本) は計上しない:
    ブロック配列は √n スケールで小さく、元の ts/vs は finite_view と共有されるため
    二重計上になる。ただしこれは時間問題の解決ではない — 実測で RSI を持たせても
    バイト計上は変わらないままティックが 24→36ms に増える (だから第 3 軸の
    デッドラインが要る)。
    """
    if isinstance(obj, np.ndarray):
        if id(obj) in seen:
            return 0
        seen.add(id(obj))
        return int(obj.nbytes)
    total = 0
    ts = obj.timestamps
    if id(ts) not in seen:
        seen.add(id(ts))
        total += int(ts.nbytes)
    # getattr フォールバックは使わない — 名前がドリフトしたら実ソースで dedup が
    # 無言で消えるので、AttributeError で loud-fail させる。
    val = obj._values_source.array_if_materialized()
    if val is not None and id(val) not in seen:
        seen.add(id(val))
        total += int(val.nbytes)
    for pair in (
        getattr(obj, "_sorted_view_cache", None),
        getattr(obj, "_finite_view_cache", None),
    ):
        if pair is None:
            continue
        for arr in pair:  # (timestamps, values) タプル
            if id(arr) not in seen:
                seen.add(id(arr))
                total += int(arr.nbytes)
    return total
```

**(3-b) `src/valisync/core/session.py`**

`RemovalResult`（`:71-87`）の docstring 末尾と フィールドを追加:

```python
@dataclass(frozen=True)
class RemovalResult:
    """Outcome of a remove_group request (Req 4.5).

    ``removed`` is False when dependent Derived_Signals exist and removal was not
    forced; ``dependent_signals`` then names the blocking Derived_Signals.
    ``removed_group`` carries the popped Signal_Group on success so the GUI can
    defer its dealloc off the UI thread (FU-16); None when removal was refused.
    ``removed_columns`` carries the group's minted column Signals (E-1), which
    live outside ``SignalGroup.signals`` and would otherwise escape the teardown
    accounting.
    ``cached_arrays`` carries the decoded channel arrays recovered from the
    ``ChannelSampleCache`` (E-4a). ``removed_columns`` cannot carry them: those
    are raw ndarrays, not Signals. 1 本 13.2 MB (prod の広幅チャンネル) なので、
    ここで渡さないと teardown の三軸ペーシングを丸ごと迂回する。
    """

    removed: bool
    dependent_signals: tuple[str, ...] = ()
    removed_group: SignalGroup | None = None
    removed_columns: tuple[Signal, ...] = ()
    cached_arrays: tuple[np.ndarray, ...] = ()
```

`remove_group` の末尾（`:367-374`・既存の長い WHY コメントは残す）:

```python
        cached: tuple[np.ndarray, ...] = ()
        handle = group.handle
        if handle is not None:
            # E-4a: 回収は close() の**前**。close() は自ハンドルのエントリを
            # ChannelSampleCache から落として**その場で同期解放**するので、順序を
            # 逆にすると teardown へ渡す実体が消え、13.2 MB/本 のチャンネル配列が
            # 三軸ペーシングを迂回して GUI スレッドで解放される (会計上は「配列は
            # 1 本も無かった」ように見えるので、症状はフリーズだけで数字に出ない)。
            #
            # 引くのは handle.cache ではなく **self._channel_cache**: Session が
            # 作ったハンドルなら同一オブジェクトだが、handle.cache は型として
            # None を取りうる (MdfLoader を引数なしで使う経路)。ここで Session 側を
            # 使えば None 分岐が構造的に要らず、かつ「予算の裁定者は Session が
            # 持つ 1 個」(spec §5.2) がコード上でも読める。
            cached = self._channel_cache.drop_handle(id(handle))
            handle.close()
        return RemovalResult(
            removed=True,
            dependent_signals=dependents,
            removed_group=group,
            removed_columns=columns,
            cached_arrays=cached,
        )
```

**(3-c) `src/valisync/core/loaders/mdf_handle.py`** — `close()` の `with self.lock:` の直前に追加（T2 は `close()` を一切変更しないので、この 3 行は必ず本タスクで入る）:

```python
        # 予算の返却は読み直列化 lock の**外**で行う: キャッシュは自前の lock で
        # 守られているので、in-flight な select の完了を待つ理由が無い。
        # 通常の unload はここへ来る前に remove_group が drop_handle() で回収済み
        # なので空振りする — 回収されない close (ローダーのエラー/キャンセル経路)
        # でエントリが恒久滞留するのを防ぐのがここの役目。キーは id(self) なので、
        # 残すと予算が目減りするだけでなく id 再利用時に別ファイルの配列を引く。
        #
        # **None ガードは必須** (省略不可): cache は任意 (T2) で、MdfLoader を
        # 引数なしで使う経路 — ローダー単体テスト・load() のエラー/キャンセル経路の
        # finally (tests/test_loaders.py:522 :560)・MdfHandle(_FakeMdf())
        # (test_mdf_handle_concurrency.py) — が全て cache=None のまま close() を
        # 呼ぶ。落とすと既存テストが広範囲に AttributeError になる。
        if self.cache is not None:
            self.cache.drop_handle(id(self))
        with self.lock:
            self.mdf.close()
```

**(3-d) `src/valisync/gui/viewmodels/app_viewmodel.py`**

`:61`:

```python
        # duck-typed: enqueue(key, group, columns, cached_arrays)
        self._teardown: object | None = None
```

`set_teardown` docstring（`:168-174`）:

```python
    def set_teardown(self, service: object) -> None:
        """Inject the GUI-thread teardown service.

        duck-typed ``enqueue(key, group, columns=(), cached_arrays=())`` —
        ``columns`` は鋳造列 (``RemovalResult.removed_columns``)、``cached_arrays``
        は ChannelSampleCache から回収したチャンネル配列
        (``RemovalResult.cached_arrays``)。どちらもグループ信号と同じペーシングに乗せる。
        """
        self._teardown = service
```

`unload_file` の enqueue（`:270-279`）:

```python
            # 鋳造列 (E-1) は SignalGroup.signals の外に居るので、渡さないと result の
            # スコープアウトで GUI スレッドの同期解放になる (プロット済み列は実体化済み
            # = バイトが重い → FU-16 のフリーズが戻る)。キャッシュ配列 (E-4a) も同じ
            # 理由で渡す (1 本 13.2 MB)。columns / cached_arrays は**常に**渡す: 空の
            # ときだけ省く形にすると、実データが載るまでこの実引数が一度も評価されず、
            # テストダブルの署名ドリフトが無音で残る。MainWindow._discard の
            # remove_group(force=True) も同じ配線を持つ (AppViewModel を経由しない
            # 2 サイト目)。
            self._teardown.enqueue(  # type: ignore[attr-defined]
                key,
                result.removed_group,
                columns=result.removed_columns,
                cached_arrays=result.cached_arrays,
            )
```

**(3-e) `src/valisync/gui/views/main_window.py`** `_discard`（`:647-651`）:

```python
            result = session.remove_group(outcome.key, force=True)
            if result.removed_group is not None:
                self.teardown_service.enqueue(
                    outcome.key,
                    result.removed_group,
                    columns=result.removed_columns,
                    cached_arrays=result.cached_arrays,
                )
```

- [ ] **Step 4: 通ることを確認**

Run:
```
uv run pytest tests/gui/test_teardown_service.py tests/gui/test_teardown_pacing.py tests/gui/test_teardown_lazy.py tests/test_session.py tests/gui/test_discard_teardown.py tests/gui/test_app_viewmodel.py tests/gui/test_file_browser_vm.py tests/gui/test_file_browser_view.py -q
```
その後フルスイート: `uv run pytest -q`

- [ ] **Step 5: LRU evict の同期解放時間を実測して記録**

LRU の evict は unload と違いペーシングを通らない（`put` の中で同期解放される）。spec §9 の
表が「実測して記録」のまま空いているので、**数値を作るのがこのステップの成果物**。予想
（1 ms 未満）は書かない — 出た値を採る。

Run（Bash ツール）:
```bash
uv run python - <<'PY'
import time

import numpy as np

from valisync.core.loaders.channel_cache import ChannelSampleCache

WIDE = (12000, 1100)  # prod の広幅 1 本 = uint8 13.2 MB (spec §5.1)


def wide() -> np.ndarray:
    return np.zeros(WIDE, dtype=np.uint8)


entry = np.zeros(WIDE, dtype=np.uint8).nbytes
cache = ChannelSampleCache(budget_bytes=3 * entry)
for i in range(3):
    assert cache.put((1, i, 0), wide()) is True

samples = []
for i in range(3, 23):
    arr = wide()  # 確保は計測の外 (evict の解放だけを測る)
    t0 = time.perf_counter()
    cache.put((1, i, 0), arr)
    samples.append((time.perf_counter() - t0) * 1000.0)
    del arr

samples.sort()
print(f"entry = {entry / 1024 / 1024:.1f} MB, n = {len(samples)}")
print(f"median = {samples[len(samples) // 2]:.3f} ms, max = {samples[-1]:.3f} ms")
PY
```

出た `max` を 2 箇所へ記録する（数値だけを差し替え、他の文は変えない）:
- `docs/superpowers/specs/2026-07-30-e4-channel-cache-design.md` §5.7 の「**実測して spec の数値を確定する**」の直後に「（T4 実測: 最大 X.XXX ms / 中央値 Y.YYY ms・1 エントリ 13.2 MB・20 回）」を追記
- 同 §9 表の行「| LRU evict 1 回の同期解放時間 | — | **実測して記録**（1 エントリ 13.2 MB） |」の右欄を「**実測 X.XXX ms**（最大・20 回・1 エントリ 13.2 MB）」へ

**実測が 1 ms を大きく超えた場合も数値を採る**（予想に合わせて測り直さない）。その場合は
§5.7 に「ペーシング対象へ回すかは E-4b で再検討」と 1 文だけ添える。

- [ ] **Step 6: sabotage で honest-RED を確認（必須）**

各 sabotage の前に対象ファイルの pristine copy を取り、**`git checkout -- src/...` では戻さない**
（過去に実装者が自分の未コミット作業を消している）:

```bash
mkdir -p /tmp/e4t4 && cp src/valisync/gui/workers/teardown_service.py src/valisync/core/session.py src/valisync/core/loaders/mdf_handle.py src/valisync/gui/viewmodels/app_viewmodel.py src/valisync/gui/views/main_window.py /tmp/e4t4/
# 戻すときは cp /tmp/e4t4/<file> <元のパス>
```

**到達範囲は主張でなく実測で確かめる** — 各 sabotage で「RED になると書いた本」と「GREEN の
まま残ると書いた本」の**両方**を実際に走らせ、結果を報告に転記する。

1. **S1a（loud-fail 形）**: `_retained_bytes` の `isinstance(obj, np.ndarray)` ブロックを丸ごと削除
   → `test_cached_channel_array_bytes_are_counted_by_the_byte_axis` が
   `AttributeError: 'numpy.ndarray' object has no attribute 'timestamps'` で ERROR。
2. **S1b（黙って死ぬ形・こちらが本命）**: 同ブロックを `return 0` に置換（分岐は残す）
   → 同テストが `assert 32 == 16416` 相当の値ずれで RED。**S1a だけでは「バイト軸が黙って
   死ぬ」変異を殺せていないので、S1b を必ず実測する**。
3. **S2**: ndarray 分岐から `seen` の出入りを外す（`return int(obj.nbytes)` だけにする）
   → `test_a_cached_array_shared_with_a_signal_is_counted_once` のみ RED、
   `test_cached_channel_array_bytes_are_counted_by_the_byte_axis` は GREEN のまま
   （= dedup を守っているのはこの 1 本だけ）を実測して記録。
4. **S3**: `enqueue` の `items.extend(cached_arrays)` を `if not items:` ブロックの**後ろ**へ移動
   → `test_cached_arrays_alone_do_not_take_the_empty_group_shortcut` が RED
   （`done == ["g"]` が即時・`pending_signals() == 0`）。他は GREEN のまま。
5. **S4**: `enqueue` から `items.extend(cached_arrays)` を削除
   → teardown 系 4 本 + `test_discard_also_hands_the_cached_arrays` が RED。
6. **S5（順序・spec §5.7 の本命）**: `remove_group` の `cached = self._channel_cache.drop_handle(...)` を
   `handle.close()` の**後ろ**へ移動
   → `test_cached_arrays_are_recovered_before_the_handle_is_closed` が
   `assert [13200000] == [0]` 相当で RED、`test_remove_group_recovers_the_cached_channel_arrays`
   も空タプルで RED。**この RED は close 側の drop が効いていることに依存する**ので、S6 と
   対で確認する。
7. **S6（close 側の解放）**: `MdfHandle.close()` の `if self.cache is not None: self.cache.drop_handle(id(self))` を削除
   → `test_close_releases_the_handles_cached_arrays_from_the_budget` のみ RED。
   `test_cached_arrays_are_recovered_before_the_handle_is_closed` は **GREEN のまま**
   （回収が先にあるため）— これを実測し、「close 側を守っているのはこの 1 本だけ」と報告に記す。
7'. **S6'（None ガードの除去）**: 同じ 2 行を `self.cache.drop_handle(id(self))` の 1 行へ潰す
   → `test_close_without_a_cache_is_still_a_plain_close` が `AttributeError: 'NoneType'
   object has no attribute 'drop_handle'` で RED。**併せて `uv run pytest -q` を全数回し**、
   `tests/test_loaders.py` / `tests/core/loaders/test_mdf_handle_concurrency.py` /
   `tests/core/loaders/test_resolved_column_lru.py` にも同じ AttributeError が出ることを
   実測して報告に貼る（ガードが「念のため」ではなく既存経路の実要件であることの実証）。
8. **S7（2 サイト独立）**: `app_viewmodel.unload_file` から `cached_arrays=` を落とす
   → `test_cached_channel_arrays_are_handed_to_the_teardown_service` のみ RED。
   戻して `main_window._discard` から落とす → `test_discard_also_hands_the_cached_arrays` のみ RED。
   （片方の配線でもう片方が守られていないことの実証）

- [ ] **Step 7: ゲート＋コミット**

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```
（4 つとも exit 0。`| tail` に通さない — exit code が隠れる）

```
git add src/valisync/core/session.py src/valisync/core/loaders/mdf_handle.py src/valisync/gui/workers/teardown_service.py src/valisync/gui/viewmodels/app_viewmodel.py src/valisync/gui/views/main_window.py tests/test_session.py tests/gui/test_teardown_service.py tests/gui/test_teardown_pacing.py tests/gui/test_discard_teardown.py tests/gui/test_app_viewmodel.py tests/gui/test_file_browser_vm.py tests/gui/test_file_browser_view.py docs/superpowers/specs/2026-07-30-e4-channel-cache-design.md
git commit
```

コミットメッセージ:
```
feat(core): teardown 会計へキャッシュ配列を載せる (E-4a T4)

RemovalResult.cached_arrays を新設し、ChannelSampleCache から回収した
デコード済みチャンネル配列 (1 本 13.2 MB) を TeardownService の三軸
ペーシングへ乗せる。removed_columns に相乗りできないのは型が違うため
(Signal ではなく生 ndarray) — _retained_bytes に ndarray 分岐を足し、
id dedup は Signal 側と同じ seen を共有する。

回収は handle.close() の**前**に行う: close() は自ハンドルのエントリを
キャッシュから落として同期解放するので、順序が逆だと teardown へ渡す
実体が消え、会計上は「配列が無かった」ように見えたままフリーズだけが戻る。
close() 側の解放は、回収されない経路 (ローダーのエラー/キャンセル) で
エントリが恒久滞留し id(handle) 再利用で別ファイルの配列を引くのを防ぐ。
cache は任意 (MdfLoader を引数なしで使う経路は None) なので close() は None ガード
つき — 落とすとローダー単体テストとハンドル並行テストが軒並み AttributeError になる。
回収そのものは handle.cache でなく Session が持つ 1 個 (_channel_cache) から引く。

LRU evict 1 回の同期解放は実測 X.XXX ms (最大・20 回・1 エントリ 13.2 MB)
— spec §5.7 / §9 に記録。
```
（`X.XXX` は Step 5 の実測値へ差し替える）

---

### Task 5: 計測器の修正＋実測（キャッシュ冷熱の明示制御・飽和 USS・evict 同期解放時間）

**Files:**
- Modify: `scripts/measure_lazy_footprint.py:346-359`（`DrainResult` に cache バイト 2 軸）
- Modify: `scripts/measure_lazy_footprint.py:518-524`（`materialize_leaves` の鋳造ループが pin を張る・T3 の LRU 対策）・`:536-548`（母数 assert）
- Modify: `scripts/measure_lazy_footprint.py:551-595`（`drain_after_unload` が unload 前後の `bytes_held` を記録）
- Modify: `scripts/measure_lazy_footprint.py:598-665`（`report_drain` に 1 行追加）
- Modify: `scripts/measure_lazy_footprint.py:668-733`（`LATENCY_COLUMNS` ＋ `column_read_latency` を丸ごと置換し、キャッシュ観測の段を新設）
- Modify: `scripts/measure_lazy_footprint.py:736-812`（`core_footprint` に非回帰 verdict ＋ 新しい段 ＋ remove_group の回収確認）
- Modify: `scripts/measure_lazy_footprint.py:916-920`（`main` の呼び出し口）
- Test: `tests/test_measure_lazy_footprint.py`（新規）

**Interfaces:**
- Consumes（T0 `src/valisync/core/loaders/channel_cache.py`）: `ChannelSampleCache(budget_bytes: int = 256*1024*1024)` / `get(key: CacheKey) -> np.ndarray | None` / `put(key: CacheKey, samples: np.ndarray) -> bool` / `drop_handle(handle_id: int) -> tuple[np.ndarray, ...]` / `hits` / `misses` / `evictions` / `skipped_oversize` / `bytes_held`。`CacheKey = tuple[int, int, int]`（`(id(handle), group_index, channel_index)`）。
- Consumes（T2）: **`Session.channel_cache -> ChannelSampleCache`** — 全ファイルで共有する 1 インスタンス（spec §5.3）。本タスクはこの名前の**唯一の消費者**。T2 が別名にしたなら `_channel_cache()` の 1 行だけを合わせる（`assert isinstance(...)` が loud-fail するので取り違えは静かに通らない）。
- Consumes（T3・**相互作用あり**）: 鋳造列 LRU（`_DEFAULT_RESOLVED_CAPACITY = 512`）と `Session.set_pinned_columns(keys)` / `SignalGroupManager.resolved_keys(group_key)`。`materialize_leaves` は `MATERIALIZE_TARGET = 8_000` 本を鋳造するので、**pin を張らないと LRU が ~512 本まで削る** — 母数 assert が必ず失敗するだけでなく、`RemovalResult.removed_columns` が 8,000 → ~512 になって E-3 が測った「展開済み regime」自体を踏まなくなる。pin は拒否されない（spec §5.5）ので、鋳造の**前**に張れば容量超でも全列が残る。
- Consumes（既存）: `Session.resolve_signal` / `Session.column_names_of` / `Session.group_signals` / `SignalGroupManager.column_records` / `resolved_keys` / `mint_count`、`valisync.core.loaders.column_names.leaf_count` / `leaf_names`、`valisync.core.loaders.mdf_loader._flatten`、`MdfHandle.mdf`。
- Produces: 計測器の公開関数 `column_read_latency(session, key, *, cold_every_column: bool) -> LatencyResult` / `cache_saturation(session, key, max_channels: int = 64) -> SaturationResult` / `evict_release_ms(cache, entry_bytes: int, samples: int = 5) -> tuple[float, ...]` / `report_latency(results: list[LatencyResult])` / `report_cache(sat: SaturationResult)` と、**spec §9 の出口数値そのもの**（Step 4 の表）。T6（realgui ①gate）は `cache.misses` を観測点に使うが、本スクリプトには依存しない。

---

- [ ] **Step 1: 失敗テストを書く**

`tests/test_measure_lazy_footprint.py`（新規）:

```python
"""計測器 (scripts/measure_lazy_footprint.py) の E-4a 段が「ゼロ件でも合格」しないことの test-lock.

E-3 T9 のレビューで「``fresh`` の本数 assert が無いと ``TOTAL 0 columns = 0 ms`` を
刷って黙って合格する」が実際に指摘されている。E-4a で足す段 (キャッシュ冷熱の制御・
飽和・evict 解放時間) にも同じ穴が開きうる — かつ計測器は CI で回らないので、
**測定対象がゼロ件のときに loud-fail する**ことと、**計測器自身が数えられること**だけは
ここで固定する。

demo_data (gitignore・CI に無い) には依存しない: 冷熱と件数の判定は列構造だけで決まる
ので、合成 mf4 (幅広 2-D チャンネル 1 本) で全経路を踏める。

psutil は本番/dev いずれの依存にも無い (計測器は ``uv run --with psutil`` で回す) ため、
未インストールのときだけ import が通る最小スタブを差し込む。**その差し込みも
``sys.path`` への scripts 追加も module import 時にやってはならない** — どちらも
``sys.modules`` / ``sys.path`` を**セッション全体**に残す副作用で、実際に本環境では
psutil が未インストールなので (実測)、module-level でスタブを置くと
``tests/core/loaders/test_mdf_loader_master_retention.py`` の
``pytest.importorskip("psutil")`` が**スタブで成功し**、RSS 0 を実測値として読む
(今は VALISYNC_MEMTEST と prod_demo.mf4 の二重 gate に救われているだけで、gate が
1 つ外れた瞬間に「メモリ検証が常に合格する」形になる)。したがって差し込みは
``monkeypatch`` を使う ``mlf`` fixture に閉じ、テスト終了で必ず巻き戻す。
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.mdf4_helpers import write_mdf4_wide_2d
from valisync.core.loaders import mdf_loader
from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.session import Session


@pytest.fixture
def mlf(monkeypatch: pytest.MonkeyPatch) -> Any:
    """計測器モジュールを **このテストの間だけ** import 可能にして返す。

    ``monkeypatch.setitem(sys.modules, ...)`` と ``monkeypatch.syspath_prepend`` は
    どちらもテスト終了で自動的に巻き戻る (module-level の ``sys.modules[...] = stub``
    / ``sys.path.insert`` は巻き戻らない — module docstring の WHY 参照)。

    実 psutil があるならスタブは**作らない**。無いときだけ差し込み、その差し替えも
    このテストの外へは漏れない。
    """
    try:
        import psutil  # noqa: F401
    except ImportError:
        stub = types.ModuleType("psutil")

        class _StubProcess:
            def memory_info(self) -> types.SimpleNamespace:
                return types.SimpleNamespace(rss=0)

            def memory_full_info(self) -> types.SimpleNamespace:
                return types.SimpleNamespace(uss=0)

        stub.Process = _StubProcess  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "psutil", stub)

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    # NOTE: import した計測器モジュール自身は sys.modules に残る (残しても他テストへ
    # 影響しない — 影響するのは psutil という **共有された名前** の方だった)。
    # 残すことで 2 本目以降のテストが再 import のコストを払わずに済む。
    return importlib.import_module("measure_lazy_footprint")


def _loaded(tmp_path: Path, cols: int) -> tuple[Session, str]:
    session = Session()
    key = session.load(write_mdf4_wide_2d(tmp_path, cols=cols)).key
    return session, key


def test_widest_channel_is_the_array_channel(mlf, tmp_path):
    """「同一広幅チャンネルの隣接 5 列」の主語 — 勝者が別チャンネルなら測定が別物になる。"""
    session, key = _loaded(tmp_path, cols=12)
    assert mlf._widest_channel(session, key) == ("Wide", 12)


def test_read_counters_count_and_restore(mlf, tmp_path):
    """計測器そのものの健全性 — 数えられないなら「select 1 回」は主張であって観測ではない。"""
    session, key = _loaded(tmp_path, cols=12)
    handle = mlf._handle_of(session, key)
    original_flatten = mdf_loader._flatten

    with mlf._ReadCounters(handle) as counters:
        col = session.resolve_signal(f"{key}::Wide[0]")
        assert col is not None and len(col.values) == 3
        mdf_loader._flatten("probe", np.zeros((3, 2)))

    assert counters.select_calls == 1, counters.select_calls
    assert counters.flatten_calls >= 1, counters.flatten_calls
    # 窓の外へ漏らさない (漏らすと以降の全計測が二重に数える)。
    assert mdf_loader._flatten is original_flatten
    assert "select" not in vars(handle.mdf)


def test_the_psutil_stub_does_not_leak_into_the_session():
    """スタブがセッションに残っていないこと (I-9 の回帰ガード)。

    残ると ``test_mdf_loader_master_retention.py`` の ``importorskip("psutil")`` が
    スタブで成功し、RSS 0 を実測値として読む。``mlf`` fixture を**要求しない**のが
    要点 — 要求すると差し込んだ状態で観測することになり、恒真になる。
    """
    stubbed = sys.modules.get("psutil")
    assert stubbed is None or getattr(stubbed, "__file__", None) is not None, (
        "テスト由来の psutil スタブが sys.modules に残っている"
    )


def test_latency_starts_cold_even_when_the_channel_is_already_cached(mlf, tmp_path):
    """M5: 「未鋳造」は「キャッシュが冷たい」ではない — 測定側が明示的に冷やす。"""
    session, key = _loaded(tmp_path, cols=12)
    warm = session.resolve_signal(f"{key}::Wide[11]")  # 未鋳造の列を減らさずに温める
    assert warm is not None and len(warm.values) == 3
    assert session.channel_cache.bytes_held > 0  # 温まっていることの独立確認

    result = mlf.column_read_latency(session, key, cold_every_column=False)

    # 冷やし忘れると select は 1 度も呼ばれない (全列がキャッシュヒットで済む)。
    assert result.select_calls == 1, result
    assert result.misses >= 1, result
    assert result.hits >= mlf.LATENCY_COLUMNS - 1, result
    assert len(result.per_column_ms) == mlf.LATENCY_COLUMNS
    assert result.base_is_none  # C1: 命中パスが view を返していない


def test_latency_control_pays_one_decode_per_column(mlf, tmp_path):
    """対照 (E-4a 以前の経路) が本当に列ごとに冷たいこと — でなければ A/B が同じ物になる。"""
    session, key = _loaded(tmp_path, cols=12)

    result = mlf.column_read_latency(session, key, cold_every_column=True)

    assert result.select_calls == mlf.LATENCY_COLUMNS, result
    assert result.hits == 0, result


def test_latency_refuses_when_fewer_than_five_fresh_columns_remain(mlf, tmp_path):
    """ゼロ件 (件数不足) で「TOTAL 0 columns = 0 ms」を刷らず loud-fail する。"""
    session, key = _loaded(tmp_path, cols=6)
    for i in range(2):
        assert session.resolve_signal(f"{key}::Wide[{i}]") is not None

    with pytest.raises(AssertionError, match="未鋳造かつ隣接の列が"):
        mlf.column_read_latency(session, key, cold_every_column=False)


def test_evict_release_measures_only_puts_that_evicted(mlf):
    """evict が起きた put だけを標本にし、合成エントリを後始末する。"""
    cache = ChannelSampleCache(budget_bytes=4 * 1024)

    out = mlf.evict_release_ms(cache, entry_bytes=1024, samples=3)

    assert len(out) == 3
    assert all(ms >= 0.0 for ms in out)
    assert cache.bytes_held == 0  # 合成エントリはキャッシュに残さない


def test_evict_release_refuses_when_nothing_is_evicted(mlf):
    """予算に余裕があり 1 件も追い出せなかった実行を「解放は速い」と読ませない。"""
    cache = ChannelSampleCache(budget_bytes=64 * 1024 * 1024)

    with pytest.raises(AssertionError, match="evict を 1 度も起こせなかった"):
        mlf.evict_release_ms(cache, entry_bytes=1024, samples=3)


def test_cache_saturation_refuses_when_the_budget_is_never_reached(mlf, tmp_path):
    """飽和しなかった実行は USS 天井を検証できない — 満点で通してはならない。"""
    session, key = _loaded(tmp_path, cols=12)

    with pytest.raises(AssertionError, match="予算に到達しなかった"):
        mlf.cache_saturation(session, key)
```

> **`match=` は飾りではない**: `pytest.raises(AssertionError)` だけにすると、飽和 assert を消したときに後段の `evict_release_ms` の AssertionError が代わりに条件を満たし、**sabotage しても緑のまま**になる（この系列で実際に摘出済みの失敗モード）。文言一致で「どの前提が守られているか」を固定する。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_measure_lazy_footprint.py -q`

Expected: **9 件中 8 件 FAIL / 1 件 PASS**。実際に出るエラー:
- `AttributeError: module 'measure_lazy_footprint' has no attribute '_widest_channel'`（同様に `_handle_of` / `_ReadCounters` / `evict_release_ms` / `cache_saturation`）
- `TypeError: column_read_latency() got an unexpected keyword argument 'cold_every_column'`（`pytest.raises(AssertionError)` の 2 本も、期待した `AssertionError` ではなくこの `TypeError` / `AttributeError` が出るので FAIL）

PASS するのは `test_the_psutil_stub_does_not_leak_into_the_session` の**1 本だけ**（実装に依存せず「スタブがセッションへ漏れていない」という環境の性質を pin するテスト）。`-rf` の一覧が 8 行でなければ**予測かテストのどちらかが誤り**なので、そのまま進めない。

（T0/T2 未完了の状態で走らせると `ImportError: cannot import name 'ChannelSampleCache'` / `AttributeError: 'Session' object has no attribute 'channel_cache'` になる。その場合は先行タスクの未完了であって本タスクの RED ではない。）

- [ ] **Step 3: 実装**

**3-1. `LATENCY_COLUMNS = 5`（:668）と `column_read_latency`（:671-733）を丸ごと次で置換する**（`_bulk_columns` / `_select_samples` / `materialize_leaves` は触らない）:

```python
# ─── E-4a: チャンネル単位キャッシュの観測 ─────────────────────────────────────
LATENCY_COLUMNS = 5
LATENCY_TARGET_MS = 380.0  # spec §9 (5 列合計)
# U3: キャッシュ合計の追加メモリ予算 (spec §5.1)。飽和後の USS 天井の判定に使う。
CACHE_BUDGET_MB = 256
# evict の同期解放時間を測るための合成エントリの handle id。実オブジェクトの id() は
# 0 にならないので、実ファイルのエントリと絶対に衝突しない。
_SYNTH_HANDLE_ID = 0
# M5: E-3 の獲得 (core 297 MB / USS +15 MB / load 1.43 s) の非回帰帯。
CORE_RESIDENT_LIMIT_MB = 310.0
CORE_USS_DELTA_LIMIT_MB = 20.0
CORE_LOAD_LIMIT_S = 1.6


class _ReadCounters:
    """1 回の測定窓で production が何回 select / ``_flatten`` したかを**直接**数える。

    ``cache.misses`` は「キャッシュが数えた miss」であって「select を呼んだ回数」では
    ない — 先に select してから cache を見る実装でも miss は 1 になりうるので、観測点
    1 本では中途半端実装 (M4) を区別できない。``_flatten`` は ``sample_source`` が
    **呼び出しのたびに module から import** する (循環回避の遅延 import) ため、module
    属性の差し替えで読み経路の呼び出しを捕まえられる。
    """

    def __init__(self, handle: Any) -> None:
        self._mdf = handle.mdf
        self._real_select: Any = None
        self._real_flatten: Any = None
        self._had_own_select = False
        self.select_calls = 0
        self.flatten_calls = 0

    def __enter__(self) -> _ReadCounters:
        from valisync.core.loaders import mdf_loader

        self._real_select = self._mdf.select
        self._had_own_select = "select" in vars(self._mdf)
        self._real_flatten = mdf_loader._flatten

        def counting_select(*args: Any, **kwargs: Any) -> Any:
            self.select_calls += 1
            return self._real_select(*args, **kwargs)

        def counting_flatten(*args: Any, **kwargs: Any) -> Any:
            self.flatten_calls += 1
            return self._real_flatten(*args, **kwargs)

        self._mdf.select = counting_select
        mdf_loader._flatten = counting_flatten
        return self

    def __exit__(self, *exc: object) -> None:
        from valisync.core.loaders import mdf_loader

        mdf_loader._flatten = self._real_flatten
        if self._had_own_select:
            self._mdf.select = self._real_select
        else:
            del self._mdf.select  # クラス側の実装へ戻す


def _channel_cache(session: Any) -> Any:
    """Session が全ファイルで共有する 1 個の ChannelSampleCache (spec §5.3)。"""
    from valisync.core.loaders.channel_cache import ChannelSampleCache

    cache = session.channel_cache
    assert isinstance(cache, ChannelSampleCache), type(cache)
    return cache


def _handle_of(session: Any, key: str) -> Any:
    """グループの MdfHandle (キャッシュキー ``(id(handle), gi, ci)`` の第 1 成分)。"""
    return session.group_signals(key)[0]._values_source._handle


def _widest_channel(session: Any, key: str) -> tuple[str, int]:
    """列数が最大の物理チャンネルとその列数 (**名前を 1 本も生成しない**)。

    探索は ColumnRecord の spec を数えるだけ (leaf_count は名前を 1 本も生成しない)。
    ここで column_names_of を全チャンネルに回すと prod では 330k 本の文字列を作って
    捨てることになり、計測器自身が測ろうとしているコストを踏む。
    """
    from valisync.core.loaders.column_names import leaf_count

    records = session._groups.column_records(key)
    widest_n, widest_display = 0, ""
    for display, record in records.items():
        n = leaf_count(record.spec)
        if n > widest_n:
            widest_n, widest_display = n, display
    assert widest_display, "ロード済みグループに列レコードが無い"
    return widest_display, widest_n


@dataclass
class LatencyResult:
    label: str
    channel: str
    columns_in_channel: int
    per_column_ms: tuple[float, ...]
    hits: int
    misses: int
    select_calls: int
    flatten_calls: int
    minted: int
    entries_left: int
    base_is_none: bool


def column_read_latency(
    session: Any, key: str, *, cold_every_column: bool
) -> LatencyResult:
    """同一広幅チャンネルの隣接 5 列を production 経路で読み、対話コストを実測する。

    **キャッシュの冷熱を測定側で決める** (レビュー M5): E-4a 以降「未鋳造」は
    「キャッシュが冷たい」を意味しない — 未鋳造の列でも同じ物理チャンネルが
    ``ChannelSampleCache`` に載っていれば読みはスライスだけで終わる。冷熱を制御
    しないと 1,584 ms → 380 ms がキャッシュの効果なのか呼び出し順序の偶然なのかを
    区別できない (先行する段が同じチャンネルを温めていれば 0 ms すら出せる)。

    ``cold_every_column=False``: 測定開始時だけ冷たい = ユーザーが広幅チャンネルの
    隣接 5 列をまとめて載せる journey。期待は select 1 回 / hit 4。
    ``cold_every_column=True``: 列ごとに冷たい = E-4a **以前**が構造的に踏んでいた
    経路。同一実行内の対照であり、これが無いと 380 ms に比較対象が無い (別マシンで
    測った 1,584 ms との A/B は環境差を吸えない)。
    """
    mgr = session._groups
    cache = _channel_cache(session)
    handle = _handle_of(session, key)
    hid = id(handle)

    display, width = _widest_channel(session, key)
    col_keys = _column_keys_of(session, key, display)
    # 安い数え方 (leaf_count) と、列キーを実際に作る唯一の真実 (column_names_of →
    # leaf_names) が食い違ったら「勝者チャンネル」の主張が黙って嘘になる。
    assert len(col_keys) == width, (len(col_keys), width, display)
    already = mgr.resolved_keys(key)
    fresh = [k for k in col_keys if k not in already][:LATENCY_COLUMNS]
    # 呼び出し位置が動いて先頭列が既に鋳造済みになるとループが 0 回になり
    # 「TOTAL 0 columns = 0 ms」を刷って**黙って合格**する (E-3 T9 の指摘)。
    assert len(fresh) == LATENCY_COLUMNS, (
        f"未鋳造かつ隣接の列が {len(fresh)} 本しかない (channel={display} / "
        f"鋳造済み {len(already)}) — 測定対象ゼロ件での黙った合格を防ぐ前提"
    )

    # 冷たい状態を作る唯一の行。drop_handle は落としたエントリを **返す** ので、
    # 戻り値を捨てた時点でキャッシュ側の参照は消える。
    cache.drop_handle(hid)
    # カウンタは drop の**後**に読む: 冷熱の確認に cache.get を使うと hits/misses が
    # 動いて測定対象そのものを汚すので、観測点は drop_handle の戻り本数側に置く。
    hits_before, misses_before = cache.hits, cache.misses
    mint_before = mgr.mint_count

    per_column: list[float] = []
    base_is_none = True
    with _ReadCounters(handle) as counters:
        for col_key in fresh:
            if cold_every_column:
                cache.drop_handle(hid)  # 解放は計測窓の外 (測るのは読みのコスト)
            t0 = time.perf_counter()
            col = session.resolve_signal(col_key)  # 鋳造 (production 経路)
            assert col is not None, f"列キーが解決できない: {col_key}"
            arr = col.values  # 実読み: miss なら select・hit ならスライス + コピー
            per_column.append((time.perf_counter() - t0) * 1000.0)
            assert len(arr) > 0
            # C1 所有権不変条件 (spec §5.4): 命中パスが view を焼き付けると evict しても
            # RSS が下がらず _retained_bytes も実体の 1/1000 になる。値一致は view でも
            # 通るので、ここが計測器側の唯一の観測点になる。
            base_is_none = base_is_none and arr.base is None

    dropped = cache.drop_handle(hid)
    label = "列ごとに冷 (E-4a 以前の経路・対照)"
    if not cold_every_column:
        label = "測定開始時のみ冷 (E-4a の journey)"
    return LatencyResult(
        label=label,
        channel=display,
        columns_in_channel=width,
        per_column_ms=tuple(per_column),
        hits=cache.hits - hits_before,
        misses=cache.misses - misses_before,
        select_calls=counters.select_calls,
        flatten_calls=counters.flatten_calls,
        minted=mgr.mint_count - mint_before,
        entries_left=len(dropped),
        base_is_none=base_is_none,
    )


def report_latency(results: list[LatencyResult]) -> None:
    print(
        "\n=== COLUMN READ latency (同一広幅チャンネルの隣接 5 列・E-4a 受け入れ) ==="
    )
    for r in results:
        total = sum(r.per_column_ms)
        print(f"  --- {r.label} ---")
        print(f"  channel={r.channel}  columns in channel={r.columns_in_channel:,}")
        for i, ms in enumerate(r.per_column_ms):
            print(f"    column #{i}  {ms:,.0f} ms")
        verdict = "OK" if total <= LATENCY_TARGET_MS else "OVER"
        print(
            f"  TOTAL {len(r.per_column_ms)} columns = {total:,.0f} ms   [{verdict}]"
            f"   (目標 <= {LATENCY_TARGET_MS:,.0f} ms)"
        )
        print(
            f"  select calls = {r.select_calls}   _flatten calls = {r.flatten_calls}"
            "   (目標 select 1 / _flatten <= 1 — 位置パス経路なら 0)"
        )
        print(
            f"  cache hits/misses = {r.hits}/{r.misses}   "
            f"entries left for this file = {r.entries_left}   minted = {r.minted}"
        )
        own = "OK" if r.base_is_none else "VIEW LEAK"
        print(f"  minted values.base is None = {r.base_is_none}   [{own}]")
    print(
        "  reference (E-3 実測・キャッシュ無し): 309-327 ms/列・5 列 1,584 ms。\n"
        "  対照 (列ごとに冷) が cached 側と同程度なら、キャッシュが効いていないか\n"
        "  冷やす側が壊れている — どちらでも受け入れは成立しない。",
        flush=True,
    )


@dataclass
class SaturationResult:
    channels_read: int
    wall_s: float
    bytes_held_mb: float
    hits: int
    misses: int
    evictions: int
    skipped_oversize: int
    base_rss_mb: float
    base_uss_mb: float
    rss_mb: float
    uss_mb: float
    evict_ms: tuple[float, ...]
    evict_entry_mb: float


def evict_release_ms(
    cache: Any, entry_bytes: int, samples: int = 5
) -> tuple[float, ...]:
    """予算超の put が 1 エントリを追い出すときの**同期**解放時間 (ms)。

    LRU の evict は unload と違い TeardownService のペーシングを通らない (spec §5.7)
    ので、1 回の解放が呼び出しスレッドを止める時間そのものが受け入れ対象になる。
    合成配列で追加するのは、実チャンネルを読むと select のデコード時間が同じ窓に
    入って解放だけを取り出せないから。測っているのは **追い出される側** の解放で、
    ``np.ones`` で埋めるのは ``np.zeros``/``np.empty`` が OS の遅延マップで触られて
    いないページを返し、解放が実測より安く出るため。
    """
    import numpy as np

    out: list[float] = []
    for i in range(samples * 8):
        if len(out) >= samples:
            break
        arr = np.ones(max(1, entry_bytes), dtype=np.uint8)
        before = cache.evictions
        t0 = time.perf_counter()
        accepted = cache.put((_SYNTH_HANDLE_ID, 0, i), arr)
        elapsed = (time.perf_counter() - t0) * 1000.0
        del arr  # キャッシュを唯一の参照者にする (次の evict が実解放になる)
        if not accepted:
            break  # oversize: この予算では evict を起こせない
        if cache.evictions - before == 1:
            out.append(elapsed)
    cache.drop_handle(_SYNTH_HANDLE_ID)
    # 測定対象がゼロ件でも「解放は速い」と読めてしまう経路を塞ぐ。
    assert out, (
        "evict を 1 度も起こせなかった — 解放時間の測定対象がゼロ件 "
        f"(bytes_held={cache.bytes_held / MB:,.0f} MB / "
        f"entry={entry_bytes / MB:,.2f} MB)"
    )
    return tuple(out)


def cache_saturation(
    session: Any, key: str, max_channels: int = 64
) -> SaturationResult:
    """広い順にチャンネルを読んで予算を飽和させ、飽和後の USS と evict を実測する。

    広い順に読むのは D6 の裏返し: prod の広幅は 13.2 MB/本なので 256 MB を埋めるには
    ~19 本要る一方、スカラー (1.9 KB) から読むと 13 万本読んでも飽和しない。
    """
    from valisync.core.loaders.column_names import leaf_count, leaf_names
    from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR

    cache = _channel_cache(session)
    hid = id(_handle_of(session, key))
    records = session._groups.column_records(key)
    widest = sorted(
        ((leaf_count(rec.spec), display) for display, rec in records.items()),
        reverse=True,
    )[:max_channels]
    assert widest, "ロード済みグループに列レコードが無い"

    cache.drop_handle(hid)
    gc.collect()
    base_rss, base_uss = rss_mb(), uss_mb()
    hits0, misses0 = cache.hits, cache.misses
    ev0, over0 = cache.evictions, cache.skipped_oversize

    channels = 0
    t0 = time.perf_counter()
    for _n, display in widest:
        # 列名は 1 本だけ生成する: _column_keys_of は広幅 1 本で 1,100 本の f-string を
        # 作るので、64 チャンネルぶん回すと計測器自身が測ろうとしているコストを踏む。
        first = next(leaf_names(display, records[display].spec), None)
        if first is None:
            continue
        col = session.resolve_signal(f"{key}{KEY_SEPARATOR}{first}")
        if col is None:
            continue
        arr = col.values  # 1 列読む = そのチャンネル全体が 1 エントリとして載る
        if first != display:
            # C1 (spec §5.4): **列を読んだときだけ** 所有権を要求する。
            # first == display は「リーフが 1 本しかない物理チャンネル」(スカラーや
            # 単一フィールド) で、返るのは列ではなく**容器 Signal そのもの**。
            # 容器分岐は np.ascontiguousarray(samples) を返し、連続な samples では
            # 同一オブジェクトが返って _freeze も (read-only 済みなので) コピー
            # しない — したがって **values.base は非 None になりうる** (実測:
            # Clean (3,) float64 base=ndarray)。ここを裸で assert すると、広い順
            # 64 本の走査が最初のスカラーチャンネルに到達した瞬間に落ち、しかも
            # メッセージが無いので test_cache_saturation_refuses_when_the_budget_
            # is_never_reached の match= が「別の理由で」満たされなくなる。
            assert arr.base is None, first
        channels += 1
        if cache.evictions > ev0:
            break  # 予算超過 = 飽和した
    wall = time.perf_counter() - t0
    gc.collect()
    rss, uss = rss_mb(), uss_mb()
    held = cache.bytes_held

    # 測定対象がゼロ件でも「USS は予算内」に見える経路を塞ぐ (この 2 本が無いと
    # 1 本も載らなかった実行が満点で通る)。
    assert channels > 0, "1 チャンネルも読めていない (飽和計測が空)"
    assert cache.evictions > ev0, (
        "予算に到達しなかった — この入力では飽和後の天井を検証できない "
        f"(bytes_held={held / MB:,.0f} MB / 読んだチャンネル {channels})"
    )
    return SaturationResult(
        channels_read=channels,
        wall_s=wall,
        bytes_held_mb=held / MB,
        hits=cache.hits - hits0,
        misses=cache.misses - misses0,
        evictions=cache.evictions - ev0,
        skipped_oversize=cache.skipped_oversize - over0,
        base_rss_mb=base_rss,
        base_uss_mb=base_uss,
        rss_mb=rss,
        uss_mb=uss,
        # 追加サイズは実エントリと同程度にする: 小さすぎると 1 回の evict のあと
        # 何度 put しても予算に触れず、標本が集まらない。
        evict_ms=evict_release_ms(cache, int(held / channels)),
        evict_entry_mb=held / channels / MB,
    )


def report_cache(sat: SaturationResult) -> None:
    delta_uss = sat.uss_mb - sat.base_uss_mb
    verdict = "OK" if delta_uss <= CACHE_BUDGET_MB else "OVER"
    held_verdict = "OK" if sat.bytes_held_mb <= CACHE_BUDGET_MB else "OVER"
    print("\n=== CHANNEL CACHE saturation (U3 予算 256 MB・spec §9 の USS 天井) ===")
    print(
        f"  channels read (widest first) = {sat.channels_read}  in {sat.wall_s:,.1f}s"
        f"   hits/misses = {sat.hits}/{sat.misses}"
    )
    print(
        f"  cache bytes_held = {sat.bytes_held_mb:,.1f} MB   [{held_verdict}]   "
        f"evictions = {sat.evictions}   skipped_oversize = {sat.skipped_oversize}"
    )
    print(
        f"  baseline (cache empty) = {sat.base_rss_mb:,.0f} MB RSS / "
        f"{sat.base_uss_mb:,.0f} MB USS"
    )
    print(
        f"  saturated              = {sat.rss_mb:,.0f} MB RSS / {sat.uss_mb:,.0f} MB USS"
    )
    print(
        f"  USS delta [PRIMARY]    = +{delta_uss:,.0f} MB   [{verdict}]   "
        f"(目標 <= {CACHE_BUDGET_MB} MB)"
    )
    print(
        f"  LRU evict 同期解放 ({sat.evict_entry_mb:,.1f} MB/エントリ): "
        f"max {max(sat.evict_ms):,.2f} ms / "
        f"mean {sum(sat.evict_ms) / len(sat.evict_ms):,.2f} ms  (n={len(sat.evict_ms)})"
    )
    print(
        "    (unload と違い evict はペーシングを通らない = この値がそのまま\n"
        "     呼び出しスレッドの停止時間。1 frame @60fps = 16.7 ms)",
        flush=True,
    )
```

**3-2. 冒頭の import に `Any` を足す**（:44 `from dataclasses import dataclass` の直後）:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any
```

**3-3a. `materialize_leaves` の鋳造ループが pin を張る**（T3 の LRU との相互作用）。`:516-522`（`done = 0` から `col_keys = _column_keys_of(...)` まで）を次で**置き換える**（以降のループ本体 `table = _bulk_columns(...)` 以下は無変更）:

```python
    done = 0
    # E-4a: T3 の鋳造列 LRU (既定容量 512 列) は非 pin の列を古い順に落とす。
    # ここは 8,000 本を鋳造するが 1 本もプロットしないので、pin を張らないと
    # _resolved_by_key に残るのは ~512 本だけになり、(b) のドレインが測る対象が
    # 消える (下の母数 assert が必ず失敗する) だけでなく、RemovalResult.removed_columns
    # が 8,000 -> ~512 になって E-3 が測った「展開済み regime」そのものを踏まなくなる。
    # pin は拒否されない (spec §5.5) ので、**鋳造の前**に張れば容量超でも全列が残る。
    # GUI がプロット中の列を push するのと同じ API を、測定側が「今から触る列」へ
    # 使うだけ (集合は置き換えなので、チャンネルごとに累積して押し直す)。
    pins: set[str] = set()
    t0 = time.perf_counter()
    for sig in physical:
        if done >= target:
            break
        psrc = sig._values_source
        col_keys = _column_keys_of(session, key, _orig(sig.name))
        pins.update(col_keys)
        session.set_pinned_columns(pins)
```

（`session.set_pinned_columns` はチャンネルごとに 1 回だけ呼ぶ — 列ごとに呼ぶと
`_evict_resolved` の O(現存列) 走査を 8,000 回払う。副作用として
`pinned_column_bytes` が大きくなりチャンネルキャッシュが最低容量まで縮むが、
この関数の読みは `_bulk_columns` 経由でキャッシュを通らないので測定には影響しない。
`drain_after_unload` が刷る `cache bytes at unload` が 1 エントリぶんに見えるのは
この帰結であり、**予算の裁定が正しく効いている**ことの表れである。）

**3-3b. `materialize_leaves` の母数 assert**（:538-543 の `print(...)` の直後、`# 参照は関数の return で…` コメントの直前に挿入）:

```python
    # (b) のドレインは「展開済み信号が実在すること」を前提にした計測なので、母数が
    # 目標に届かなかった実行を「MAX tick OK」と読ませない。E-4a では _resolved_by_key の
    # evict (D4) で鋳造列が測定中に消えうるため、この 1 本が唯一の観測点になる
    # (3-3a の pin が効いていないと、ここが最初に鳴る)。
    assert materialized >= target, (
        f"展開済み列が {materialized:,} 本しかない (目標 {target:,}) — "
        "(b) のドレインが測る対象が存在しない (鋳造列が evict された可能性)"
    )
```

**3-4. `DrainResult` に 2 軸追加**（:358-359 の `top_ticks` の直後）:

```python
    # (index, ms, signals, bytes, gc passes)
    top_ticks: tuple[tuple[int, float, int, int, int], ...]
    # T4: remove_group が close の前にキャッシュを回収して teardown へ渡す (spec §5.7)。
    cache_mb_before: float = 0.0
    cache_mb_after: float = 0.0
```

**3-5. `drain_after_unload`**: `materialized = len(_materialized_names(session, key))` と `gc.collect()` の間に

```python
    cache = _channel_cache(session)
    cache_before = cache.bytes_held
```

を入れ、`total = time.perf_counter() - t0` の直後に `cache_after = cache.bytes_held` を足し、`DrainResult(...)` の `top_ticks=...` の後ろに

```python
        cache_mb_before=cache_before / MB,
        cache_mb_after=cache_after / MB,
```

を足す。`report_drain` の `print(f"  sync close (UI thread)  = {r.sync_close_ms:,.1f} ms")` の直後に:

```python
        print(
            f"  cache bytes at unload   = {r.cache_mb_before:,.1f} -> "
            f"{r.cache_mb_after:,.1f} MB  (T4: close の前に回収して teardown へ渡す)"
        )
```

**3-6. `core_footprint` の末尾**（`CORE RESIDENT (final)` の print から `session.remove_group(key)` までを次で置換）:

```python
    # M5: E-4a が E-3 の獲得を削っていないことを同じ実行で読めるようにする。
    res_verdict = "OK" if s3_rss <= CORE_RESIDENT_LIMIT_MB else "OVER"
    uss_verdict = "OK" if s3_uss - base_uss <= CORE_USS_DELTA_LIMIT_MB else "OVER"
    load_verdict = "OK" if load_wall <= CORE_LOAD_LIMIT_S else "OVER"
    print(
        f"  CORE RESIDENT (final)  = {s3_rss:,.0f} MB RSS  [{res_verdict}]  "
        f"[eager 590 -> E-3 297 -> limit {CORE_RESIDENT_LIMIT_MB:,.0f} MB]"
    )
    print(
        f"  CORE USS delta         = +{s3_uss - base_uss:,.0f} MB  [{uss_verdict}]  "
        f"[eager +281 MiB -> E-3 +15 -> limit +{CORE_USS_DELTA_LIMIT_MB:,.0f} MB]"
        "  **primary metric**"
    )
    print(
        f"  CORE load wall         = {load_wall:.2f} s  [{load_verdict}]   "
        f"(E-3 1.43 s -> limit {CORE_LOAD_LIMIT_S:.1f} s)",
        flush=True,
    )
    # 列挙の戻り値を先に落とす: 抱えたままだと以下の USS がキャッシュ以外の分だけ
    # 底上げされ、飽和天井の判定が甘くなる。
    del sigs, smap
    gc.collect()

    # ── E-4a: 列読みの対話コストとキャッシュ会計 (Qt を構築しない同じ土俵) ──
    report_latency(
        [
            column_read_latency(session, key, cold_every_column=False),
            column_read_latency(session, key, cold_every_column=True),
        ]
    )
    report_cache(cache_saturation(session, key))

    cache = _channel_cache(session)
    held_before = cache.bytes_held
    session.remove_group(
        key
    )  # ハンドルを閉じる (計測プロセスがファイルを掴んだまま終わらない)
    leak = "OK" if cache.bytes_held == 0 else "LEAK"
    print(
        f"\n  cache bytes at remove_group = {held_before / MB:,.1f} -> "
        f"{cache.bytes_held / MB:,.1f} MB   [{leak}]"
    )
    print(
        "    (T4: remove_group は close の**前**に回収して teardown へ渡す。残ると\n"
        "     閉じたハンドルのデコード済み配列がプロセス寿命まで居座る)",
        flush=True,
    )
```

**3-7. `main` の呼び出し口**（:918-920 の 3 行を置換）:

```python
    # E-4a 受け入れ: 広幅チャンネルの隣接 5 列の実時間 (温 / 列ごと冷の対照つき) と
    # キャッシュ飽和後の USS。ドレイン計測より前に置く (ドレインはグループを消すため)。
    session = win.app_vm.session
    report_latency(
        [
            column_read_latency(session, keys[0], cold_every_column=False),
            column_read_latency(session, keys[0], cold_every_column=True),
        ]
    )
    report_cache(cache_saturation(session, keys[0]))
```

- [ ] **Step 4: 通ることを確認**

```
uv run pytest tests/test_measure_lazy_footprint.py -q
uv run pytest -q
```

続いて **実測**（`demo_data/prod_demo.mf4` が無ければ先に
`uv run python scripts/generate_demo_mf4.py --profile prod`）:

```
PYTHONUTF8=1 uv run --with psutil python scripts/measure_lazy_footprint.py --core
PYTHONUTF8=1 uv run --with psutil python scripts/measure_lazy_footprint.py
```

**両方の出力から次の表を埋めてタスク報告に貼る**（spec §9 の出口。埋まらない欄があるなら
それは「測れていない」であって「達成」ではない）:

| 項目 | 目標 | `--core` 実測 | 実 GUI 実測 |
|---|---|---|---|
| 隣接 5 列 (測定開始時のみ冷) | ≤ 380 ms |  |  |
| 同・対照 (列ごとに冷) | 参考 (E-3 は 1,584 ms) |  |  |
| `select` 呼び出し回数 | 1 |  |  |
| `_flatten` 呼び出し回数 | ≤ 1（位置パスなら 0） |  |  |
| 鋳造列 `values.base is None` | True |  |  |
| 飽和後 USS delta [PRIMARY] | ≤ +256 MB |  |  |
| 飽和後 `bytes_held` / evictions | ≤ 256 MB / ≥ 1 |  |  |
| **LRU evict 1 回の同期解放** | 実測値を記録 |  |  |
| core 常駐 / USS delta / load | ≤ 310 MB / ≤ +20 MB / ≤ 1.6 s |  | (`--core` のみ) |
| unload 時 cache bytes (b) | 回収されて 0 付近へ |  |  |

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

> **やり方**: `src/` と `scripts/` の pristine copy を作ってから壊す（`git checkout -- …` で
> 戻すと自分の未コミット作業ごと消える事故が過去にある）。**「このテストが RED になるはず」
> ではなく、毎回 `uv run pytest tests/test_measure_lazy_footprint.py -q` を全数実行し、
> RED になった集合と GREEN のままの集合を実測で書き出す**（到達範囲の主張が誤っていた
> sabotage を 3 件摘出済み）。

1. `column_read_latency` 冒頭の `cache.drop_handle(hid)`（カウンタ読み取りの直前）を削除
   → `test_latency_starts_cold_even_when_the_channel_is_already_cached` が RED
   （`select_calls` が 1 → 0）。他 7 件は GREEN のまま＝この 1 行だけがコールドを作る。
2. ループ内の `if cold_every_column: cache.drop_handle(hid)` を削除
   → `test_latency_control_pays_one_decode_per_column` が RED（`select_calls` 5 → 1）。
3. `assert len(fresh) == LATENCY_COLUMNS, (...)` を削除
   → `test_latency_refuses_when_fewer_than_five_fresh_columns_remain` が RED
   （例外が出ず `DID NOT RAISE`）。
4. `evict_release_ms` の `assert out, (...)` を削除
   → `test_evict_release_refuses_when_nothing_is_evicted` が RED（`()` が返る）。
5. `cache_saturation` の `assert cache.evictions > ev0, (...)` を削除
   → `test_cache_saturation_refuses_when_the_budget_is_never_reached` が RED。
   **ここが `match=` の効き所**: 削除すると後段の `evict_release_ms` が別の
   AssertionError を投げるので、`match=` が無ければ緑のまま通る。実際に
   `match="予算に到達しなかった"` を外した状態も 1 度試し、緑になることを実測で確認して
   から戻す（このテストが偶然合格でないことの証明）。
   **前提**: 所有権 assert が `if first != display:` で列に限定されていること（C-4）。
   裸の `assert arr.base is None` に戻すと、走査が最初のスカラーチャンネル（`Clean`）に
   到達した時点で**別の** AssertionError が出て、このテストは sabotage の有無に関わらず
   RED になる（`match=` があるので偽緑にはならないが、原因の帰属を誤らせる）。
5'. `cache_saturation` の `if first != display:` を外して裸の `assert arr.base is None` へ戻す
   → `test_cache_saturation_refuses_when_the_budget_is_never_reached` が
   **`match=` 不一致の RED**（`AssertionError: Clean` が出て「予算に到達しなかった」に
   一致しない）。C-4 の失敗モードそのものを 1 度実測しておく（容器チャンネルの
   `values.base` は非 None になりうる — 実測: `Clean (3,) float64 base=ndarray`）。
6. `_ReadCounters.__exit__` の `mdf_loader._flatten = self._real_flatten` を削除
   → `test_read_counters_count_and_restore` が RED（`is original_flatten` が False）。
   同様に `del self._mdf.select` を削除すると `"select" not in vars(handle.mdf)` が RED。
7. `materialize_leaves` の母数 assert（3-3b）は CI 入力では踏めないので**実 GUI 実行で**
   実証する: `_materialized_names` の 2 つの `if ... .is_materialized` を一時的に
   `if False` にして `uv run --with psutil python scripts/measure_lazy_footprint.py` を
   走らせ、`materialized 0 / 264,004` を刷って (b) のドレインが「MAX tick OK」で
   通る**旧挙動が assert で止まる**ことを確認する（1 回の実行で足りる）。
   **前提**: 3-3a の pin が入っていること。入っていないと T3 の LRU が鋳造列を
   ~512 本まで削るので、sabotage を当てなくても同じ assert が落ちる＝この sabotage の
   識別力がゼロになる。壊す前に「pin あり・sabotage なしで母数 assert が通る」を
   1 度実測してから当てること。
8. `materialize_leaves` の `session.set_pinned_columns(pins)` を削除（3-3a を戻す）
   → 同じ実 GUI 実行で `展開済み列が 512 本しかない (目標 8,000)` 相当の loud-fail。
   `materialized N / 264,004` と `minted N` の実測値を報告に貼り、「pin 無しで残るのは
   概ね `_DEFAULT_RESOLVED_CAPACITY` 本」であることを数字で示す（T3 の LRU と T5 の
   計測が相互作用することの実証であり、C-5 の再発防止そのもの）。

- [ ] **Step 6: ゲート＋コミット**

```
uv run ruff format
uv run ruff check
uv run mypy src/
uv run pytest
git add scripts/measure_lazy_footprint.py tests/test_measure_lazy_footprint.py
git commit
```

コミットメッセージ:

```
chore(scripts): 計測器を E-4a のキャッシュ会計へ更新 (冷熱の明示制御・飽和 USS・evict 解放)

column_read_latency は「未鋳造の列を選ぶ」実装だったが、E-4a 以降「未鋳造」は
「キャッシュが冷たい」を意味しない (レビュー M5)。先行する段が同じ物理チャンネルを
温めていれば未鋳造の列でも読みはスライスだけで終わり、380 ms 到達がキャッシュの
効果なのか呼び出し順序の偶然なのかを区別できない。冷熱を測定側で決める形へ直し、
同一実行内に「列ごとに冷」の対照 (E-4a 以前の経路) を並べた。

観測点を追加: select/_flatten の呼び出し回数を production の呼び出し自身で直接数える
(cache.misses だけでは「先に select してから cache を見る」中途半端実装を弾けない)。
鋳造列の values.base is None (C1)・キャッシュ飽和後の USS 天井 (U3 256 MB)・LRU evict
1 回の同期解放時間 (ペーシングを通らないので UI 停止時間そのもの)・remove_group が
close の前にキャッシュを回収したか (T4) を刷る。--core にも同じ段を通し、E-3 の獲得
(core 常駐/USS/load) の非回帰 verdict を追加 (M5)。

T3 の鋳造列 LRU との相互作用も配線した: materialize_leaves は 8,000 本を鋳造するが
1 本もプロットしないので、pin を張らないと LRU が ~512 本まで削り、(b) のドレインが
E-3 の測った「展開済み regime」を踏まなくなる。鋳造の前にチャンネル単位で pin を
押し直す (pin は拒否されない・spec §5.5)。所有権 assert は「列を読んだときだけ」に
限定した — 容器 (リーフ 1 本の物理チャンネル) は ascontiguousarray が同一オブジェクトを
返すので values.base が非 None になりうる (実測)。

ゼロ件で黙って合格する経路を全て塞ぎ、CI で回るテストで test-lock した:
未鋳造列が 5 本未満 / 1 チャンネルも読めていない / 予算に到達せず evict ゼロ /
展開済み列が目標未満 (ドレイン (b) の母数が消える) — いずれも loud-fail。
テストは demo_data ではなく合成 mf4 と実 Session を使い、psutil が無い CI でも走る。
psutil スタブと scripts の sys.path 追加は fixture (monkeypatch) に閉じる — module
import 時にやると sys.modules へ恒久的に残り、test_mdf_loader_master_retention.py の
importorskip("psutil") がスタブで成功して RSS 0 を実測値として読む。
```

---

### Task 6: realgui ①ゲート（受け入れ）— まとめ追加は 1 デコード / 探索的追加はヒット / 予算超で evict

**Files:**
- Create: `tests/realgui/test_channel_cache_realclick.py`
- Modify: `tests/mdf4_helpers.py`（末尾に `write_mdf4_two_wide_channels` を追加。既存 fixture は触らない）
- Test: `tests/realgui/test_channel_cache_realclick.py`

**Interfaces:**

- Consumes:
  - **T0**: `valisync.core.loaders.channel_cache.ChannelSampleCache`
    — `__init__(self, budget_bytes: int = 256 * 1024 * 1024)` /
    `hits: int` / `misses: int` / `evictions: int` / `skipped_oversize: int` / `bytes_held: int`。
    `misses` は **select 回数と 1:1**（T0 の契約）。
  - **T2**: `Session.channel_cache: ChannelSampleCache`（**getter のみ**）
    — 読み経路（`LazyMdfValues.array()`）が実際に使う**唯一の共有インスタンス**を返すプロパティ。
    T5 の計測器も同じ口を使う。
  - **T2**: `Session(cache_budget_bytes: int | None = None)` — **D6 の予算注入口はコンストラクタ引数**
    （`TeardownService(byte_budget=…)` と同型）。**setter ではない**: `Session.__init__` が
    `MdfLoader(cache=self._channel_cache)` で旧オブジェクトを捕捉し、`MdfHandle` はロード時に
    `MdfLoader._cache` を提げるので、`session.channel_cache = ...` で差し替えても
    `LazyMdfValues.array()` が見る `self._handle.cache` は旧インスタンスのまま＝**注入した
    新キャッシュを誰も書かない**（`misses == 0` / `bytes_held == 0` のまま脚 3 の全 assert が RED）。
    これが無いと ①ゲートの脚 3（予算超 evict）は書けない。
  - **T3**: `Session(column_capacity: int | None = None)`（本タスクでは使わないが、`Session` の
    シグネチャが 2 引数になっていること自体は前提。`cache_budget_bytes` は**キーワードで渡す**）。
  - **T2**: miss パスは `handle.mdf.select(...)` を **チャンネルあたり 1 回**だけ呼び、
    命中パスも miss パスも `mdf_loader._flatten` を**呼ばない**（位置パス `apply_path` へ移行済み）。
  - **T2/§5.4**: 鋳造列の値は基底を持たない独立配列（`sig._values_source.array_if_materialized().base is None`）。
  - **T3**: pin は LRU の最低容量（1 物理チャンネル分）を割り込まない
    （= 単一エントリが `skipped_oversize` へ落ちない・spec §5.5）。
  - 既存: `Session.resolve_signal(key)` / `session._groups.group(key).handle`
    （C-e により `Session` には出さない introspection。realgui が直接触る先例＝
    `tests/realgui/test_unload_releases_file_realclick.py:388`）。
  - 既存 GUI: `MainWindow._load_file` / `window.app_vm.loaded_file_keys` /
    `window.busy_overlay` / `window.channel_browser_view.{tree, model, selected_signal_keys()}` /
    `window.graph_area_vm.panels(tab)` / `GraphPanelVM.plotted_signal_keys()` /
    `GraphPanelView.{signal_keys_drawn(), entry_id_for(), curve_xy()}` /
    `valisync.gui.strings.ACTION_ADD_TO_ACTIVE_PANEL`。
  - 既存 realgui 共有: `tests/realgui/_realgui_input` の
    `at` / `key` / `click_with_modifier` / `skip_unless_real_display` /
    `LDOWN` / `LUP` / `RDOWN` / `RUP` / `VK_ESCAPE` / `VK_SHIFT`。
    **実マウスドラッグ（`drive_qdrag` / 手動 MOVE 駆動）は使わない**（共有マシンでハング・
    memory `gui_realgui_drag_qtimer_hang`）。
- Produces:
  - `tests/mdf4_helpers.write_mdf4_two_wide_channels(tmp_path: Path, rows: int = 1000, cols: int = 64) -> Path`
    — 幅 `cols` の 2-D uint8 チャンネル 2 本（`WideA` / `WideB`）。1 エントリ実体 = `rows * cols` バイト（既知）。
  - `tests/realgui/test_channel_cache_realclick.py::test_bulk_add_of_five_columns_decodes_the_channel_once`
  - `…::test_exploring_columns_one_by_one_hits_the_channel_cache`
  - `…::test_injected_small_budget_evicts_the_older_channel`
  - 後続タスクは無い（本タスクが E-4a の出口）。**レイテンシの数値は主張しない** —
    合成 fixture の壁時計で spec §9 の「5 列 ≤ 380 ms」を名乗ってはならない（それは T5 の計測器が
    prod データで出す数値）。ここが固定するのは**回数と会計**である。

---

- [ ] **Step 1: 失敗テストを書く**

`tests/realgui/test_channel_cache_realclick.py` を新規作成する。

```python
"""Layer C: E-4a チャンネル単位サンプルキャッシュの ①ゲート (実ディスプレイ・実 OS 入力)。

E-4a の主張は「同じ物理チャンネルの列を何本読んでも **デコードは 1 回**」である。
headless (Layer A/B) では ``ChannelSampleCache`` を直叩きできてしまうため、
その主張がユーザーの実操作 (行の実選択 -> 実右クリック -> メニューの実クリック) を
貫通することは証明できない。ここでは実 MainWindow に実 mf4 をロードし、実 OS 入力で

  1. 5 列を **まとめて** 追加 -> チャンネルのデコードは 1 回 (miss 1 / select 1)、
     かつ読み経路が ``_flatten`` を 1 度も呼ばない (位置パスへ移行済み)、
  2. 1 列ずつ **探索的に** 追加 -> 2 本目以降はキャッシュヒット (miss は増えない)、
  3. **予算を注入して小さくすると** 古いチャンネルが落ちる (evict され、再訪は冷える)、

を実測する。3 は spec D6: 実データでは 256 MB に広幅 (uint8 12000x1100 = 13.2 MB) が
~19 本入るため evict をほぼ発火させられないので、予算そのものを注入して小さくする
(``TeardownService(byte_budget=...)`` と同型の注入)。

**恒真化させないための設計** (E-3 の ①ゲートは、反転で「未展開」が自明に真になり、
しかも会計が鋳造列を列挙外にしていたという二重の穴を踏んだ):

  * 観測は 2 系統を **独立** に持つ。``cache.misses`` は実装自身が書く数値なので、
    それとは別に asammdf の ``MDF.select`` へラッパを載せて **実際に何回デコードしたか**
    を数える。両者が食い違えば counters が嘘をついている。
  * ``_flatten`` の呼び出しも数える。0 であることが空虚に通らないよう、
    差し替えが「呼び出し時 import」から見えることを positive control で確かめ、
    ``sample_source`` がモジュール直下に別名を持たないことも assert する
    (別名を持たれるとカウンタが盲目になる)。
  * **対照 assert**: 「まとめ追加が実は 1 列も追加していなかった」「クリックが no-op
    だった」のどちらでも RED になるよう、選択キー集合・プロット済みキー集合・
    実描画カーブ (RenderCurve 非空) を各段で固定する。
  * 値そのものを fixture の規則と突き合わせる。位置パスが隣の列や別チャンネルを
    返す誤りは「読めている」だけでは検出できない (長さも dtype も一致するので
    ``LazyMdfValues`` の長さ検証も素通りする)。

実マウスドラッグは使わない (共有マシンでハング・memory
``gui_realgui_drag_qtimer_hang``)。複数選択は実クリック + 実 Shift+クリックで行う。
demo_data には依存しない (gitignore・CI に生成ステップが無い) — 合成 fixture で
幅 64 の 2-D uint8 チャンネルを 2 本作る。
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QModelIndex, QPoint
from pytestqt.qtbot import QtBot

from tests.mdf4_helpers import write_mdf4_two_wide_channels
from tests.realgui._realgui_input import (
    LDOWN,
    LUP,
    RDOWN,
    RUP,
    VK_ESCAPE,
    VK_SHIFT,
    at,
    click_with_modifier,
    skip_unless_real_display,
)
from tests.realgui._realgui_input import key as key_input
from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.session import Session
from valisync.gui import strings as S

pytestmark = pytest.mark.realgui

_LOAD_TIMEOUT_MS = 30_000
_PLOT_TIMEOUT_MS = 10_000
_ROWS = 1000
_COLS = 64
# uint8 (ROWS, COLS) = デコード済み 2-D チャンネル 1 本の実体サイズ。
_ENTRY_BYTES = _ROWS * _COLS
# D6: 1 本は載り 2 本は載らない予算。1.5 倍にしておけば、pin 由来の set_reserved が
# 多少食っても「2 本同時滞在」は構造的に成立しない (2 本 = 2.0 倍 > 1.5 倍)。
# 実数: エントリ 64,000 B / 予算 96,000 B。T3 の pin は列 1 本 = _ROWS = 1,000 B しか
# 予約しない (プロットするのは高々 3 列 = 3,000 B) ので、LRU 容量は
# max(96,000 - 3,000, 最新エントリ 64,000) = 93,000 B — 1 本は必ず載り 2 本は載らない。
_SMALL_BUDGET = _ENTRY_BYTES + _ENTRY_BYTES // 2


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _pump_n(n: int) -> None:
    for _ in range(n):
        _pump(0.02)


def _real_click(x: int, y: int) -> None:
    at(x, y, LDOWN)
    _pump()
    at(x, y, LUP)
    _pump_n(4)


def _phys(w: Any, local: QPoint) -> tuple[int, int]:
    gp = w.mapToGlobal(local)
    dpr = w.devicePixelRatioF()
    return round(gp.x() * dpr), round(gp.y() * dpr)


def _shot(tmp_path: Path, name: str) -> Path:
    from PySide6.QtWidgets import QApplication

    p = tmp_path / f"{name}.png"
    with contextlib.suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(str(p))
    return p


def _build_window(qtbot: QtBot, session: Session | None = None) -> Any:
    """実ディスプレイ上の本物の MainWindow (画面内へ配置・前面化)。

    オフスクリーン配置だと右クリックが OS のシステムメニューを開く
    (memory: gui_realgui_offscreen_target_opens_os_system_menu)。

    *session* は D6 の予算注入用 (脚 3 のみ)。``AppViewModel(None)`` は自前で
    ``Session()`` を作るので、既定の 2 本は今までどおり production 既定の予算で走る。
    **ロード後に session.channel_cache を差し替える形は使えない** — MdfLoader が
    __init__ 時点のインスタンスを捕捉するので、差し替えても読み経路は旧インスタンスを
    見続ける (counters が全て 0 のまま脚 3 が構造的に成立しない)。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel(session))
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


def _load_and_settle(qtbot: QtBot, window: Any, path: Path) -> str:
    """実ロード経路 (off-thread LoadController + BusyOverlay) を通し group key を返す。

    オーバーレイが引くまで待つ — 引いていないと以後の実クリックが全てオーバーレイに
    当たり、テストは「クリックしたつもり」で無音に流れる。
    """
    window._load_file(path)
    qtbot.waitUntil(
        lambda: bool(window.app_vm.loaded_file_keys), timeout=_LOAD_TIMEOUT_MS
    )
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=_LOAD_TIMEOUT_MS)
    _pump_n(6)
    return str(window.app_vm.loaded_file_keys[0])


def _panel_widget(window: Any, tab: int, panel: int) -> Any:
    return window.graph_area_view.tabs.widget(tab).widget(panel)


def _top_names(model: Any) -> list[str]:
    """トップレベル行の Name 列 (子は触らない = 合成も鋳造も誘発しない)。"""
    return [model.data(model.index(r, 0)) for r in range(model.rowCount())]


def _child_names(model: Any, parent: QModelIndex) -> list[str]:
    return [
        model.data(model.index(r, 0, parent)) for r in range(model.rowCount(parent))
    ]


def _row_of(model: Any, name: str) -> int:
    names = _top_names(model)
    assert name in names, f"トップ行に {name!r} が無い: {names}"
    return names.index(name)


def _row_point(tree: Any, index: QModelIndex) -> tuple[int, int]:
    """行を可視域へスクロールし、その行の掴み点 (物理ピクセル) を返す。"""
    tree.scrollTo(index)
    _pump_n(3)
    rect = tree.visualRect(index)
    assert rect.height() > 0, "対象行が可視域に無い (実クリックできない)"
    vp = tree.viewport()
    local = QPoint(min(rect.center().x(), vp.width() - 8), rect.center().y())
    return _phys(vp, local)


def _click_index(tree: Any, index: QModelIndex) -> None:
    _real_click(*_row_point(tree, index))


def _click_expand_arrow(tree: Any, index: QModelIndex) -> None:
    """展開アフォーダンス (ブランチインジケータ) を実クリックする。

    QTreeView は rootIsDecorated の矢印を item 矩形の **左** の ``indentation()``
    幅の帯に描く。``visualRect`` はテキスト側の矩形なので、その左端から半インデント
    戻った点がユーザーが実際に叩く三角形の中心。
    """
    tree.scrollTo(index)
    _pump_n(3)
    rect = tree.visualRect(index)
    assert rect.height() > 0, "展開対象行が可視域に無い"
    indent = tree.indentation()
    assert indent > 0, "indentation が 0 — 展開矢印が存在しない"
    arrow_x = rect.left() - indent // 2
    # 負値を黙って丸めると、ジオメトリ計算の誤りが「どこか別の場所への誤クリック」
    # として静かに揉み消される。丸めず失敗させる。
    assert arrow_x > 0, (
        f"展開矢印の想定 x が負 (rect.left()={rect.left()}, indent={indent}, "
        f"x={arrow_x}) — インデント計算が壊れている"
    )
    _real_click(*_phys(tree.viewport(), QPoint(arrow_x, rect.center().y())))


def _real_right_click_add(view: Any, px: int, py: int) -> dict[str, Any]:
    """物理点 (px, py) を実右クリックし「アクティブパネルに追加」を実クリックする。

    **左クリックはしない** — 複数行を選んだ状態でメニューを開くのが「まとめ追加」の
    実経路で、ここで選択し直すと選択が 1 行へ潰れ、テストがまとめ追加を検証できなく
    なる (ChannelBrowserView._show_context_menu は意図的に選択を変えない)。
    メニューが開いている瞬間の選択キーも記録する — 右クリックが選択を壊していない
    ことの対照であり、これが無いと「1 列しか追加されなかった」原因を帰属できない。

    ESC の watchdog を挟み、クリックを外した場合でも popup を閉じてから assert で
    落ちるようにする (共有マシンを開いたメニューで塞がない)。タイマは exec() 復帰後に
    明示 stop する — 生き残ると後続の waitUntil 中に本物の ESC を送りかねない。
    """
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication, QMenu

    loop = QEventLoop()
    seen: dict[str, Any] = {}

    def right_click() -> None:
        at(px, py, RDOWN)
        at(px, py, RUP)

    def click_item() -> None:
        menu = QApplication.activePopupWidget()
        seen["popup"] = type(menu).__name__ if menu is not None else None
        if isinstance(menu, QMenu):
            seen["selection"] = view.selected_signal_keys()
            seen["actions"] = [a.text() for a in menu.actions()]
            act = next(
                (a for a in menu.actions() if a.text() == S.ACTION_ADD_TO_ACTIVE_PANEL),
                None,
            )
            seen["action_found"] = act is not None
            seen["action_enabled"] = act is not None and act.isEnabled()
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

    timers = []
    for delay, slot in (
        (300, right_click),
        (1000, click_item),
        (1600, watchdog),
        (5000, loop.quit),
    ):
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(slot)
        timer.start(delay)
        timers.append(timer)
    loop.exec()
    for timer in timers:
        timer.stop()
    _pump_n(4)

    assert seen.get("popup") == "QMenu", (
        f"実右クリックでコンテキストメニューが出ない: {seen}"
    )
    assert seen.get("action_found"), (
        f"メニューに {S.ACTION_ADD_TO_ACTIVE_PANEL!r} が無い: {seen}"
    )
    assert seen.get("action_enabled"), (
        f"「追加」が disabled = 選択が空 (以後の assert が空虚に通る): {seen}"
    )
    return seen


def _add_single_row(view: Any, index: QModelIndex) -> dict[str, Any]:
    """1 行だけを実クリック選択し、実右クリックメニューから追加する。"""
    _click_index(view.tree, index)
    return _real_right_click_add(view, *_row_point(view.tree, index))


def _cache(session: Any) -> ChannelSampleCache:
    cache = session.channel_cache
    assert isinstance(cache, ChannelSampleCache), (
        f"Session が共有チャンネルキャッシュを公開していない: {cache!r}"
    )
    return cache


def _count_selects(handle: Any, request: pytest.FixtureRequest) -> list[Any]:
    """``handle.mdf.select`` の実呼び出しを数える (counters とは独立のオラクル)。

    ``LazyMdfValues`` は ``self._handle.mdf.select(...)`` を呼ぶので、MDF インスタンスへ
    ラッパを載せれば **実際に何回デコードしたか** を production 経路で数えられる。
    ``cache.misses`` だけを見ると「counters は動くが select も毎回走る」実装を見逃す —
    counters は実装自身が書く数値、select は asammdf 側の事実である。
    **ロード完了後に載せる** (ローダー自身の probe/select を数えないため)。

    **必ず復元する** (T5 の ``_ReadCounters`` と対称)。元の状態は「インスタンス属性が
    無い」なので、復元は ``setattr`` ではなく ``__dict__`` からの削除 — bound method を
    焼き付けると、閉じた MDF への参照がクラス実装を隠したまま残り、同じハンドルを別の
    計測が掴んだときにラッパが二重に積み重なる。assert が途中で落ちても finalizer なら
    必ず走る。
    """
    assert "select" not in vars(handle.mdf), (
        "handle.mdf に select のインスタンス属性が既にある (前の計測が復元されていない)"
    )
    calls: list[Any] = []
    original = handle.mdf.select

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(args[0] if args else None)
        return original(*args, **kwargs)

    handle.mdf.select = counting
    request.addfinalizer(lambda: vars(handle.mdf).pop("select", None))
    return calls


def _records(session: Any, key: str) -> Any:
    """{表示名: ColumnRecord} — fixture の (gi, ci) を setup precondition に使う。"""
    return session._groups.column_records(key)


def _count_flatten(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """``mdf_loader._flatten`` の実呼び出しを数える (読み経路から消えたことの観測点)。

    ``sample_source`` は ``array()`` の中で **呼び出し時 import** するので、モジュール
    属性を差し替えれば読み経路からの呼び出しは必ずここを通る。逆にモジュール直下へ
    別名を持たれるとこのカウンタは盲目になる (0 が空虚に通る) ので、その形で無いことも
    確かめてから数える。
    """
    import valisync.core.loaders.mdf_loader as mdf_loader
    import valisync.core.models.sample_source as sample_source

    assert not hasattr(sample_source, "_flatten"), (
        "sample_source がモジュール直下に _flatten の別名を持っている — "
        "mdf_loader 側の差し替えが読み経路に届かず、このカウンタは盲目になる"
    )
    calls: list[str] = []
    original = mdf_loader._flatten

    def counting(name: str, arr: Any) -> Any:
        calls.append(name)
        return original(name, arr)

    monkeypatch.setattr(mdf_loader, "_flatten", counting)
    from valisync.core.loaders.mdf_loader import _flatten as resolved

    assert resolved is counting, (
        "呼び出し時 import から差し替えが見えない (カウンタが盲目)"
    )
    return calls


def _expected_column(channel: str, j: int) -> np.ndarray:
    """fixture の列 j の期待値 (write_mdf4_two_wide_channels と同じ規則)。"""
    base = 0 if channel == "WideA" else 128
    return ((np.arange(_ROWS, dtype=np.int64) + 7 * j + base) % 251).astype(np.uint8)


def _expand_channel(qtbot: QtBot, window: Any, name: str) -> QModelIndex:
    """物理チャンネル *name* の行を実クリックで展開し、その親 index を返す。"""
    view = window.channel_browser_view
    tree, model = view.tree, view.model
    qtbot.waitUntil(lambda: model.rowCount() > 0, timeout=_LOAD_TIMEOUT_MS)
    _pump_n(4)
    parent = model.index(_row_of(model, name), 0)
    assert not model.has_materialized_children(parent), (
        f"{name} の子が展開前に合成されている (葉の事前保持へ回帰)"
    )
    _click_expand_arrow(tree, parent)
    assert tree.isExpanded(parent), f"{name} が実クリックで展開されない"
    return parent


def test_bulk_add_of_five_columns_decodes_the_channel_once(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """5 列まとめて実追加 -> デコード 1 回・``_flatten`` 0 回 (spec §9 の出口 2 行)。"""
    skip_unless_real_display()

    path = write_mdf4_two_wide_channels(tmp_path, rows=_ROWS, cols=_COLS)
    window = _build_window(qtbot)
    loaded_key = _load_and_settle(qtbot, window, path)
    session = window.app_vm.session
    cache = _cache(session)
    # C-e: Session には出さない introspection (realgui は直接触る先例あり)。
    handle = session._groups.group(loaded_key).handle
    assert handle is not None and handle.is_closed is False

    view = window.channel_browser_view
    tree, model = view.tree, view.model
    # 既定キャッシュは **プロセス単位でありうる** (別テストの残留が乗る) ので、
    # 絶対値ではなく差分で見る。予算注入をするのは 3 本目のテストだけ。
    selects = _count_selects(handle, request)
    flattens = _count_flatten(monkeypatch)
    hits_before, misses_before = cache.hits, cache.misses

    parent = _expand_channel(qtbot, window, "WideA")
    children = _child_names(model, parent)
    assert children[:5] == [f"WideA[{j}]" for j in range(5)], (
        f"子行が列になっていない: {children[:8]}"
    )
    # 展開はデコードしない (E-3 の契約・無回帰)。
    assert selects == [] and cache.misses == misses_before, (
        f"ツリーの展開がチャンネルをデコードしている: selects={selects} "
        f"misses+{cache.misses - misses_before}"
    )
    _shot(tmp_path, "01_expanded")

    # ── 5 列を実選択 (先頭を実クリック -> 5 行目を実 Shift+クリック) ──────────
    _click_index(tree, model.index(0, 0, parent))
    click_with_modifier(*_row_point(tree, model.index(4, 0, parent)), VK_SHIFT)
    _pump_n(6)
    expected = [f"{loaded_key}::WideA[{j}]" for j in range(5)]
    selected = view.selected_signal_keys()
    assert sorted(selected) == sorted(expected), (
        f"実 Shift+クリックで 5 列が選択されていない (まとめ追加を検証できない): "
        f"{selected}。{_shot(tmp_path, '02_selection')}"
    )

    # ── 選択内の 3 行目を実右クリック -> 「追加」を実クリック ────────────────
    seen = _real_right_click_add(view, *_row_point(tree, model.index(2, 0, parent)))
    assert sorted(seen.get("selection") or []) == sorted(expected), (
        f"メニューを開いた時点で選択が壊れている (まとめ追加になっていない): {seen}"
    )

    panel_vm = window.graph_area_vm.panels(0)[0]
    qtbot.waitUntil(
        lambda: len(panel_vm.plotted_signal_keys()) == 5, timeout=_PLOT_TIMEOUT_MS
    )
    _pump_n(6)
    shot = _shot(tmp_path, "03_five_plotted")

    # ── 対照: 5 列が実際に載り、実際に描かれた (no-op クリックを排除) ────────
    panel = _panel_widget(window, 0, 0)
    assert sorted(panel_vm.plotted_signal_keys()) == sorted(expected), (
        f"5 列がまとめて追加されていない: {panel_vm.plotted_signal_keys()}。{shot}"
    )
    for key in expected:
        assert key in panel.signal_keys_drawn(), (
            f"追加した列が実描画されない: {key!r}。{shot}"
        )
        xs, _ys = panel.curve_xy(panel.entry_id_for(key))
        assert xs is not None and len(xs) > 0, (
            f"描画カーブが空 (値が読まれていない): {key!r}。{shot}"
        )

    # ── 本題: 5 列 = デコード 1 回 ───────────────────────────────────────────
    assert cache.misses - misses_before == 1, (
        f"5 列の追加でチャンネルを {cache.misses - misses_before} 回デコードしている "
        f"(キャッシュ未命中 == select 回数・目標 1)。{shot}"
    )
    assert len(selects) == 1, (
        f"asammdf select の実呼び出しが {len(selects)} 回 (目標 1) — "
        f"counters と実デコード回数が乖離している: {selects}。{shot}"
    )
    assert cache.hits - hits_before >= 4, (
        f"2 列目以降がキャッシュヒットになっていない (hits+"
        f"{cache.hits - hits_before})。{shot}"
    )
    assert flattens == [], (
        f"読み経路がまだ _flatten を呼んでいる (位置パスへ移っていない): "
        f"{flattens[:5]} (計 {len(flattens)})。{shot}"
    )

    # ── 値の照合: 位置パスが「その列」を返している ───────────────────────────
    misses_at_check = cache.misses
    for j, key in enumerate(expected):
        sig = session.resolve_signal(key)
        assert sig is not None, f"プロット済みの列が解決できない: {key!r}"
        got = np.asarray(sig.values)
        assert np.array_equal(got, _expected_column("WideA", j)), (
            f"列 {j} の値が違う (位置パスが別の列を返している疑い): 先頭 {got[:4]}"
        )
        # spec §5.4 (C1): 命中パスが view を返すと evict しても RSS が下がらず、
        # nbytes_if_materialized も実体の 1/1000 を返してバイト軸が黙って死ぬ。
        # **ただしこの assert は幅 64 の 2-D 列では構造的に恒真**である (実測:
        # apply_path の copy ガードを外しても、幅 3 以上の 2-D スライスは非連続なので
        # ascontiguousarray が必ず実コピーする)。C1 の**一次ゲートは T1/T2** —
        # 連続 view になる 2 形状 (write_mdf4_single_column_shapes の Mono[0] / P.x)
        # を使う test_column_paths.py と test_channel_cache_read_path.py が持つ。
        # ここは「実 GUI 経路でも所有権が崩れていない」ことの**回帰ガード**であって、
        # 所有権違反を検出する歯ではない (歯だと誤解して T1/T2 側を削らないこと)。
        held = sig._values_source.array_if_materialized()
        assert held is not None and held.base is None, (
            f"鋳造列の値が共有 2-D 配列の view になっている (所有権不変条件の違反): "
            f"{key!r}"
        )
    assert cache.misses == misses_at_check, (
        "値の照合が新しいデコードを誘発した (観測が対象を変えている)"
    )


def test_exploring_columns_one_by_one_hits_the_channel_cache(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """1 列ずつ探索的に実追加 -> 2 本目以降はキャッシュヒット (U1 のもう半分)。"""
    skip_unless_real_display()

    path = write_mdf4_two_wide_channels(tmp_path, rows=_ROWS, cols=_COLS)
    window = _build_window(qtbot)
    loaded_key = _load_and_settle(qtbot, window, path)
    session = window.app_vm.session
    cache = _cache(session)
    handle = session._groups.group(loaded_key).handle
    assert handle is not None

    view = window.channel_browser_view
    model = view.model
    selects = _count_selects(handle, request)
    flattens = _count_flatten(monkeypatch)
    hits_before, misses_before = cache.hits, cache.misses

    parent = _expand_channel(qtbot, window, "WideB")
    panel_vm = window.graph_area_vm.panels(0)[0]
    panel = _panel_widget(window, 0, 0)

    for step, j in enumerate((0, 1, 2)):
        _add_single_row(view, model.index(j, 0, parent))
        key = f"{loaded_key}::WideB[{j}]"
        qtbot.waitUntil(
            lambda k=key: k in panel_vm.plotted_signal_keys(), timeout=_PLOT_TIMEOUT_MS
        )
        _pump_n(4)
        shot = _shot(tmp_path, f"1{step}_added_{j}")

        # 対照: この 1 回で 1 本だけ増え、実際に描かれた。
        assert len(panel_vm.plotted_signal_keys()) == step + 1, (
            f"{step + 1} 回目の追加でプロット数が {len(panel_vm.plotted_signal_keys())} "
            f"— クリックが no-op / 二重発火。{shot}"
        )
        assert key in panel.signal_keys_drawn(), f"実描画されない: {key!r}。{shot}"
        xs, _ys = panel.curve_xy(panel.entry_id_for(key))
        assert xs is not None and len(xs) > 0, f"描画カーブが空: {key!r}。{shot}"

        # 本題: 何本目でもデコードは最初の 1 回だけ。
        assert cache.misses - misses_before == 1, (
            f"{step + 1} 本目でチャンネルを再デコードしている "
            f"(misses+{cache.misses - misses_before})。{shot}"
        )
        assert len(selects) == 1, (
            f"{step + 1} 本目で asammdf select が再度走った: {len(selects)} 回。{shot}"
        )
        if step > 0:
            assert cache.hits - hits_before >= step, (
                f"{step + 1} 本目がキャッシュヒットになっていない "
                f"(hits+{cache.hits - hits_before})。{shot}"
            )

    assert flattens == [], (
        f"読み経路がまだ _flatten を呼んでいる: {flattens[:5]} (計 {len(flattens)})"
    )

    # 3 本が **それぞれ別の列** を返している (同じ列を配り回していない)。
    misses_at_check = cache.misses
    for j in (0, 1, 2):
        sig = session.resolve_signal(f"{loaded_key}::WideB[{j}]")
        assert sig is not None
        got = np.asarray(sig.values)
        assert np.array_equal(got, _expected_column("WideB", j)), (
            f"WideB[{j}] の値が違う (キャッシュが別の列を返している疑い): 先頭 {got[:4]}"
        )
    assert cache.misses == misses_at_check, (
        "値の照合が新しいデコードを誘発した (観測が対象を変えている)"
    )


def test_injected_small_budget_evicts_the_older_channel(
    qtbot: QtBot, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    """予算を注入して小さくすると古いチャンネルが落ちる (D6・spec §5.1 の LRU)。"""
    skip_unless_real_display()

    path = write_mdf4_two_wide_channels(tmp_path, rows=_ROWS, cols=_COLS)
    # D6: 予算は **Session のコンストラクタ**で注入する。実データでは 256 MB に
    # 広幅 (13.2 MB/本) が ~19 本入るので evict を起こせず、予算そのものを小さく
    # するのが唯一の実験手段。
    # **後から session.channel_cache へ代入する形は使えない** (property に setter が
    # 無いだけでなく、あっても効かない): Session.__init__ が MdfLoader へ渡した
    # 時点で MdfLoader._cache が旧オブジェクトを捕捉し、MdfHandle はロード時に
    # それを提げる。LazyMdfValues.array() が見るのは self._handle.cache なので、
    # 注入した新キャッシュは**誰も書かない** = misses も bytes_held も 0 のまま
    # 以下の全 assert が RED になる (脚 3 が構造的に成立しない)。
    session = Session(cache_budget_bytes=_SMALL_BUDGET)
    window = _build_window(qtbot, session=session)
    cache = _cache(session)

    loaded_key = _load_and_settle(qtbot, window, path)
    # open はチャンネルをデコードしない (E-3 の契約) — ここが 0 でないと以下の
    # 絶対値の会計が読めなくなるので、先に固定する。
    assert (cache.misses, cache.bytes_held) == (0, 0), (
        f"open がチャンネルをデコードしている: misses={cache.misses} "
        f"bytes_held={cache.bytes_held}"
    )
    handle = session._groups.group(loaded_key).handle
    assert handle is not None
    selects = _count_selects(handle, request)

    # 変異の到達範囲を fixture の実測で固定する (T2 の 3 軸 sabotage と同型)。
    # 実測: WideA=(gi=0, ci=1) / WideB=(gi=1, ci=1) — **ci は同じで gi が違う**
    # (ci=0 は各グループの時間マスターチャンネル)。したがって本テストが殺せるのは
    # **gi 軸**であって ci 軸ではない: ci を定数 0 にしても (h,0,0) と (h,1,0) は
    # 別キーのままで衝突せず RED にならない。ci 軸の被覆は core 側
    # (test_channel_cache_read_path.py::test_cache_key_separates_two_channels_in_one_group)
    # が持つ。この 3 本の assert が無いと「どの軸に盲目か」を自己証明できない。
    recs = _records(session, loaded_key)
    positions = {n: (recs[n].group_index, recs[n].channel_index) for n in ("WideA", "WideB")}
    assert positions["WideA"] != positions["WideB"], positions
    assert recs["WideA"].channel_index == recs["WideB"].channel_index, (
        f"fixture の ci が違う — 本テストは gi 軸ではなく ci 軸を殺している: {positions}"
    )
    assert recs["WideA"].group_index != recs["WideB"].group_index, positions

    view = window.channel_browser_view
    model = view.model
    panel_vm = window.graph_area_vm.panels(0)[0]
    panel = _panel_widget(window, 0, 0)

    # ── (a) WideA[0] を実追加 -> A の 2-D 配列が載る ─────────────────────────
    parent_a = _expand_channel(qtbot, window, "WideA")
    _add_single_row(view, model.index(0, 0, parent_a))
    key_a0 = f"{loaded_key}::WideA[0]"
    qtbot.waitUntil(
        lambda: key_a0 in panel_vm.plotted_signal_keys(), timeout=_PLOT_TIMEOUT_MS
    )
    _pump_n(4)
    shot_a = _shot(tmp_path, "20_a0")
    assert key_a0 in panel.signal_keys_drawn(), f"実描画されない: {key_a0!r}。{shot_a}"
    assert cache.misses == 1 and len(selects) == 1, (
        f"1 本目のデコード回数が 1 でない: misses={cache.misses} "
        f"selects={len(selects)}。{shot_a}"
    )
    assert cache.bytes_held == _ENTRY_BYTES, (
        f"デコード済み 2-D チャンネル配列そのものが載っていない "
        f"(列だけ/upcast の疑い): bytes_held={cache.bytes_held} "
        f"期待 {_ENTRY_BYTES}。{shot_a}"
    )
    assert cache.evictions == 0, f"1 本目で evict が起きている。{shot_a}"
    assert cache.skipped_oversize == 0, (
        f"1 エントリ ({_ENTRY_BYTES} B) が予算超 (D7) と判定された — 注入した予算 "
        f"{_SMALL_BUDGET} B との比較が壊れている。**oversize 判定は reserved を見ない**"
        f" (put は size > budget だけで決める) ので、ここは pin の影響を受けない。"
        f"{shot_a}"
    )
    # pin (T3 の set_reserved) が LRU の最低容量 (1 物理チャンネル分・spec §5.5) を
    # 割り込んでいないことの観測点は **bytes_held**: 割り込んでいれば 1 本目が
    # 載った直後に自分自身を落として 0 になる。上の bytes_held == _ENTRY_BYTES が
    # その assert であり、skipped_oversize ではこの機構を殺せない。

    # ── (b) WideB[0] を実追加 -> 予算超で A が落ちる ─────────────────────────
    parent_b = _expand_channel(qtbot, window, "WideB")
    _add_single_row(view, model.index(0, 0, parent_b))
    key_b0 = f"{loaded_key}::WideB[0]"
    qtbot.waitUntil(
        lambda: key_b0 in panel_vm.plotted_signal_keys(), timeout=_PLOT_TIMEOUT_MS
    )
    _pump_n(4)
    shot_b = _shot(tmp_path, "21_b0")
    assert key_b0 in panel.signal_keys_drawn(), f"実描画されない: {key_b0!r}。{shot_b}"
    assert cache.misses == 2 and len(selects) == 2, (
        f"別チャンネルの読みがデコードになっていない: misses={cache.misses} "
        f"selects={len(selects)}。{shot_b}"
    )
    assert cache.evictions == 1, (
        f"予算超なのに evict が起きていない (evictions={cache.evictions}) — "
        f"注入した予算 {_SMALL_BUDGET} が効いていない。{shot_b}"
    )
    assert cache.bytes_held == _ENTRY_BYTES, (
        f"2 本が同時に載っている (bytes_held={cache.bytes_held}) — "
        f"バイト予算が執行されていない。{shot_b}"
    )

    # ── (c) 落ちた WideA へ戻る -> 冷えているので再デコード ─────────────────
    _add_single_row(view, model.index(1, 0, parent_a))
    key_a1 = f"{loaded_key}::WideA[1]"
    qtbot.waitUntil(
        lambda: key_a1 in panel_vm.plotted_signal_keys(), timeout=_PLOT_TIMEOUT_MS
    )
    _pump_n(4)
    shot_c = _shot(tmp_path, "22_a1")
    assert key_a1 in panel.signal_keys_drawn(), f"実描画されない: {key_a1!r}。{shot_c}"
    assert cache.misses == 3 and len(selects) == 3, (
        f"evict 済みチャンネルの再訪がヒット扱いになっている "
        f"(misses={cache.misses} selects={len(selects)}) — 落ちていないか、"
        f"落ちたのに会計が追随していない。{shot_c}"
    )
    assert cache.evictions == 2, (
        f"再ロードで B が落ちていない (evictions={cache.evictions})。{shot_c}"
    )
    assert cache.bytes_held == _ENTRY_BYTES, (
        f"bytes_held={cache.bytes_held} (期待 {_ENTRY_BYTES})。{shot_c}"
    )

    # evict を挟んでも値は正しい (キャッシュの再構築が別の列にならない)。
    for key, channel, j in (
        (key_a0, "WideA", 0),
        (key_b0, "WideB", 0),
        (key_a1, "WideA", 1),
    ):
        sig = session.resolve_signal(key)
        assert sig is not None
        got = np.asarray(sig.values)
        assert np.array_equal(got, _expected_column(channel, j)), (
            f"{key} の値が違う (evict 後の再デコードが別の列/別チャンネル): "
            f"先頭 {got[:4]}。{shot_c}"
        )
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest --realgui tests/realgui/test_channel_cache_realclick.py -q`

Expected: 収集時に FAIL with
`ImportError: cannot import name 'write_mdf4_two_wide_channels' from 'tests.mdf4_helpers'`
（Step 3 で追加する fixture がまだ無い。これは本タスク自身の実装物に対する RED であって、
E-4a の主張に対する RED ではない — **主張側の証拠は Step 5 の sabotage が出す**。
そのことをこの Step の報告にも明記すること）

T2/T3 が未着地の環境で走らせた場合は
`AttributeError: 'Session' object has no attribute 'channel_cache'` または
`TypeError: Session.__init__() got an unexpected keyword argument 'cache_budget_bytes'`
になる（本タスクが T2 の露出口と**予算注入口**に依存していることの直接の現れ。回避せず、T2 を先に着地させる。
とくに後者を「setter で差し替える」形へ迂回してはならない — 差し替えても読み経路は
`MdfLoader` が捕捉した旧インスタンスを見続けるので、脚 3 の counters が全て 0 のまま
「注入が効いていないだけ」の RED になる）。

- [ ] **Step 3: 実装**

`tests/mdf4_helpers.py` の末尾（`write_mdf4_structured` の後、`write_mdf3` の前）へ fixture を追加する。

```python
def write_mdf4_two_wide_channels(
    tmp_path: Path, rows: int = 1000, cols: int = 64
) -> Path:
    """幅 cols の 2D uint8 チャンネル 2 本 (WideA / WideB) — E-4a ①ゲート用.

    デコード済み 2-D 配列 1 本 = ``rows * cols`` バイト (uint8) と **実体サイズが既知**
    になるのが要点。E-4a の ①ゲートは LRU 予算を注入して evict を起こす (実データでは
    256 MB に広幅が ~19 本入り発火しない・spec D6) ので、予算を「1 本は載り 2 本は
    載らない」値に決めるにはエントリの実体サイズが要る。2 本あるのは「別チャンネルを
    読むと古い方が落ちる」を観測するため。

    値は ``WideA[j][r] = (r + 7j) % 251`` / ``WideB[j][r] = (r + 7j + 128) % 251``。
    どの **チャンネルのどの列** を読んだかが値だけで判別でき、位置パスが隣の列や別
    チャンネルを返す誤りを値で捕まえられる (長さも dtype も一致するので、LazyMdfValues
    の長さ検証は素通りする = 値でしか捕まらない)。251 は素数で 7 とも rows/cols とも
    互いに素なので、列間・チャンネル間の値列が偶然一致しない。
    """
    ts = np.arange(rows, dtype=np.float64) * 0.01
    r = np.arange(rows, dtype=np.int64)[:, None]
    j = np.arange(cols, dtype=np.int64)[None, :]
    mdf = MDF()
    try:
        for name, base in (("WideA", 0), ("WideB", 128)):
            samples = ((r + 7 * j + base) % 251).astype(np.uint8)
            mdf.append([ASignal(samples=samples, timestamps=ts, name=name, unit="m")])
        path = tmp_path / "twowide.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return Path(path)
```

（実 asammdf 7.3.18 のラウンドトリップで検証済み: 物理チャンネル `WideA` / `WideB`、
列名 `WideA[0..63]`、`select` の `samples.shape == (1000, 64)` / `dtype == uint8` /
`nbytes == 64000`、列値は上式と一致、`total_column_count == 128`）

- [ ] **Step 4: 通ることを確認**

```
uv run pytest --realgui tests/realgui/test_channel_cache_realclick.py -q
uv run pytest --realgui tests/realgui/test_lazy_load_realclick.py -q
uv run pytest --realgui tests/realgui/test_channel_tree_flatten_realclick.py -q
uv run pytest --realgui tests/realgui/ -q          # フル realgui (無回帰)
uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/
uv run pytest -q tests/gui/test_realgui_layer_c_contract.py   # Layer C 契約ガード
```

報告に記録する（主張ではなく実測値）:

1. 3 テストそれぞれの `cache.hits / misses / evictions / skipped_oversize / bytes_held` と
   `len(selects)`（各テストは失敗時にこれらを assert メッセージへ出す。成功時の値は
   `-s` 付き実行か一時 print で採る）。
2. `bytes_held == 64000` が実際に成立したか（成立しないなら asammdf の dtype/shape が
   想定と違う＝ **fixture の定数を実測値へ更新してコミットし、旧値と新値の両方を報告する**。
   黙って `>=` へ緩めない — この等式が「2-D 配列そのものが載っている」の唯一の防波堤）。
3. フル realgui の pass/fail 数。既知フレーク（51 ファイル一括実行でのみ出るフォント計量
   由来の 3 件・CLAUDE.md に記録済み）に当たったら、**単体で再実行して 100% pass することを
   確かめてから**「既知・本増分と無関係」と書く。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

**手順の前提**: sabotage の前に対象ファイルを scratchpad へコピーして pristine copy を保つ。
確認後はそのコピーから書き戻す。`git checkout -- src/...` は**使わない**（自分の未コミット作業を
消した実例がある）。各 sabotage は「どの assert が、どんな実測値で RED になったか」を
**実行して確かめ**、assert 文言と観測値を報告に貼る（到達範囲は主張でなく実測で確かめる）。

1. **キャッシュを効かせない（本題・controller 指定）**: `ChannelSampleCache.get` の先頭に
   `return None` を入れる。
   → test 1 が `5 列の追加でチャンネルを 5 回デコードしている` で RED、同時に
   `asammdf select の実呼び出しが 5 回` でも RED（counters と実 select の**両系統**が
   落ちることを確かめる — 片方しか落ちないならもう一方の観測が空虚）。
   test 2 は 2 本目で `2 本目でチャンネルを再デコードしている` で RED。
2. **`_flatten` の観測が空虚でないこと**: `LazyMdfValues.array()` の列抽出を T2 以前の形
   （`from valisync.core.loaders.mdf_loader import _flatten` ＋ `dict(_flatten(...))[...]`）へ
   戻す（キャッシュ自体は残す）。
   → test 1 の `読み経路がまだ _flatten を呼んでいる` だけが RED になり、`misses == 1` は
   通ったままになる。**この 2 つが独立に落ちることが、脚 1 の 2 本の assert が別のことを
   測っている証拠**。
3. **キー空間から `group_index` を落とす**: `LazyMdfValues.array()` の `key = (id(self._handle), self._gi, self._ci)`
   を `key = (id(self._handle), 0, self._ci)` にする（spec §5.3 の C2）。
   → test 3 が `別チャンネルの読みがデコードになっていない: misses=1 selects=1` で RED、
   さらに末尾の値照合（`WideB[0] の値が違う`）でも RED。**WideA の 2-D 配列が WideB として
   配られる**ことを値で確かめる（長さも dtype も一致するので `LazyMdfValues` の長さ検証は
   素通りし、例外は 1 つも出ない = 値でしか捕まらない failure mode）。
   test 1 / test 2 は**緑のまま**（どちらも単一チャンネルしか読まないので gi 軸にも
   ci 軸にも盲目）— この非対称も実測して報告に書く。
   - **`channel_index` を落とす形にしてはならない**（実測で識別力ゼロ）: 本 fixture の
     レコードは `WideA=(gi=0, ci=1)` / `WideB=(gi=1, ci=1)` で **ci が同じ**なので、
     `ci` を定数 0 にしても `(h,0,0)` と `(h,1,0)` は別キーのまま衝突せず、どのテストも
     RED にならない。ci 軸を殺せるのは同一グループに 2 チャンネルを持つ core 側の
     fixture（`write_mdf4_shared_group`）だけで、その被覆は T2 が持つ。
     test 3 の setup precondition（`recs["WideA"].channel_index == recs["WideB"].channel_index`）は
     この事実をテスト自身に証明させるために置いてある。
4. **バイト予算を執行しない**: `put` の evict ループ（または予算比較）を外す。
   → test 3 が `予算超なのに evict が起きていない (evictions=0)` と
   `2 本が同時に載っている (bytes_held=128000)` で RED。test 1/2 は通ったまま
   （＝ evict の証拠は脚 3 だけが持っている）。
5. **対照 assert が「クリック no-op」を殺すこと**: `_real_right_click_add` の
   `at(mx, my, LDOWN)` / `at(mx, my, LUP)`（メニュー項目の実クリック）をコメントアウト。
   → `qtbot.waitUntil` のタイムアウトで RED（「何も追加されていないのにカウンタだけ 0 で通る」
   形になっていないことの実証）。
6. **対照 assert が「まとめ追加が実は 1 列」を殺すこと**: test 1 の
   `click_with_modifier(..., VK_SHIFT)` を `_real_click(...)` に変える（Shift 無し）。
   → `実 Shift+クリックで 5 列が選択されていない` で RED。ここが落ちないと
   `misses == 1` は「1 列しか追加していない」でも通る＝脚 1 が空虚になる。

- [ ] **Step 6: ゲート＋コミット**

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
uv run pytest --realgui tests/realgui/ -q
git add tests/mdf4_helpers.py tests/realgui/test_channel_cache_realclick.py
git commit
```

コミットメッセージ:

```
test(realgui): E-4a の ①ゲート (まとめ追加 1 デコード / 探索的ヒット / 予算超 evict)

U1 の両方の使い方を実 OS 入力で固定する。(1) 実クリック + 実 Shift+クリックで 5 列を
選び、実右クリックメニューからまとめて追加 -> チャンネルのデコードは 1 回
(cache.misses 1・asammdf select 1) で、読み経路は _flatten を 1 度も呼ばない。
(2) 1 列ずつ探索的に追加 -> 2 本目以降はキャッシュヒット。(3) D6 に従い予算を
Session(cache_budget_bytes=...) で注入して小さくし (1 本は載り 2 本は載らない)、別チャンネルの
読みで古い方が evict され、再訪が冷える (misses が増える) ことを実測。注入をコンストラクタ
引数にするのは、MdfLoader が __init__ 時点のインスタンスを捕捉して MdfHandle へ提げるため
— 後から差し替えると読み経路は旧インスタンスを見続け、注入が無言で効かない。

恒真化対策: cache の counters とは独立に MDF.select のラッパで実デコード回数を数え、
_flatten の差し替えが呼び出し時 import から見えることを positive control で確かめる。
対照 assert (選択キー集合・プロット済みキー集合・RenderCurve 非空・値の突き合わせ) を
各段に置き、「まとめ追加が 1 列だった」「クリックが no-op だった」のどちらでも RED に
なるようにした。値は fixture の規則 (r + 7j + base) % 251 と突き合わせ、位置パスが
隣の列や別チャンネルを返す誤り (長さ検証を素通りする) を捕まえる。

fixture: write_mdf4_two_wide_channels — 幅 64 の 2D uint8 を 2 本。1 エントリの実体
サイズが rows*cols で既知になるので、予算注入の値を根拠つきで決められる。
demo_data には依存しない (CI に生成ステップが無く module 丸ごと skip になるため)。
```

---
