# LD-14 ndim≥3 多段フラット展開＋per-channel 列数ガード 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MDF4 ローダーの要素展開を任意 ndim の多段フラット展開（`Name[i][j]…`）へ一般化し、チャンネル単位で展開列数が 1024 を超えるものはユーザー確認（GUI ポップアップ）で展開/スキップを選べるようにする。

**Architecture:** ローダーは読み取り前に「1 レコードプローブ（`select(record_count=1)`）」で各チャンネルの展開列数を事前算出し、1024 超のチャンネルを集約して確認コールバック（`cancel` と同じ委譲パターン）へ渡す。GUI 側はワーカースレッドからの呼び出しを `Signal`＋`threading.Event` で GUI スレッドのモーダル（チェックボックス一覧）へ marshal する。展開ロジックは純関数 `_flatten` の再帰へ一本化する。

**Tech Stack:** Python 3.12/3.13・numpy・asammdf 8.8.11・PySide6・pytest / pytest-qt。

## Global Constraints

- 品質ゲート（コミット前に全通過）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- コメントは WHY を書く（自明な WHAT は書かない）。全角括弧・記号は docstring/コメントで RUF001/002/003 に触れるため半角化するか行末に `# noqa: RUF00x`。
- GUI ロードは GUI スレッド外（`LoadWorker(QRunnable)` on `QThreadPool`）— 確認モーダルは必ず GUI スレッドで出す。
- ローダークラス名は `Mdf4Loader`（`src/valisync/core/loaders/mdf4_loader.py`）。展開後の列は元チャンネルの共有マスタ（read-only float64）を参照し LD-10 のゼロコピー経路を壊さない。
- `EXPANSION_COLUMN_LIMIT = 1024`（モジュール定数）。判定は per-channel の展開後リーフ列数 `> 1024`。

---

### Task 1: 多段フラット展開（`_flatten` 再帰化＋`_explode_samples` 書き換え）

現行 `_explode_samples`（2D＋構造化 1 段のみ・3D 超は skip）を、任意 ndim・構造化を再帰で畳む純関数 `_flatten` へ一本化する。3D 以上も `Name[i][j]…` へ展開されるようになる（挙動変更）。

**Files:**
- Modify: `src/valisync/core/loaders/mdf4_loader.py:31-100`（`_explode_samples` を書き換え・`_flatten` を追加）
- Test: `tests/test_loaders.py:557-575`（既存 2 テストを展開挙動へ更新）＋新規テスト追加

**Interfaces:**
- Produces: `_flatten(name: str, arr: np.ndarray) -> list[tuple[str, np.ndarray]]`（再帰・リーフは 1D 連続配列）／`_explode_samples(base_name: str, samples: np.ndarray, diagnostics: list[Diagnostic]) -> list[tuple[str, np.ndarray]]`（従来シグネチャ維持・内部で `_flatten` 使用＋info 診断 1 件）

- [ ] **Step 1: 既存テストを新挙動へ更新し失敗させる**

`tests/test_loaders.py` の 2 テストを置き換える（3D/ネストは skip ではなく展開が新契約）:

```python
def test_explode_samples_over_nested_field_expands() -> None:
    """ndim>2 のネストフィールドは Name.field[i][j] へ多段展開される (LD-14)."""
    from valisync.core.loaders.mdf4_loader import _explode_samples

    rec = np.zeros(2, dtype=[("deep", "<f8", (2, 2)), ("s", "<f8")])
    rec["deep"] = np.arange(2 * 2 * 2).reshape(2, 2, 2)
    rec["s"] = [7.0, 8.0]
    diags: list = []
    pairs = _explode_samples("Obj", rec, diags)
    assert [n for n, _ in pairs] == [
        "Obj.deep[0][0]",
        "Obj.deep[0][1]",
        "Obj.deep[1][0]",
        "Obj.deep[1][1]",
        "Obj.s",
    ]
    # deep[1][1] = rec["deep"][:, 1, 1] = [3, 7]
    assert np.array_equal(dict(pairs)["Obj.deep[1][1]"], [3.0, 7.0])


def test_explode_samples_plain_3d_expands() -> None:
    """素の 3D 配列は Cube[i][j] へ多段展開される (LD-14・従来は skip だった)."""
    from valisync.core.loaders.mdf4_loader import _explode_samples

    arr = np.arange(4 * 2 * 2).reshape(4, 2, 2).astype(np.float64)
    diags: list = []
    pairs = _explode_samples("Cube", arr, diags)
    assert [n for n, _ in pairs] == [
        "Cube[0][0]",
        "Cube[0][1]",
        "Cube[1][0]",
        "Cube[1][1]",
    ]
    assert np.array_equal(dict(pairs)["Cube[1][1]"], arr[:, 1, 1])
    assert any("本に展開" in d.message for d in diags)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_loaders.py::test_explode_samples_plain_3d_expands tests/test_loaders.py::test_explode_samples_over_nested_field_expands -v`
Expected: FAIL（現行は 3D/ネストを skip し `pairs == []` / `["Obj.s"]` を返す）

- [ ] **Step 3: `_explode_samples` を再帰版へ書き換え**

`src/valisync/core/loaders/mdf4_loader.py` の `_explode_samples`（31-100 行）を以下へ置換:

```python
def _flatten(name: str, arr: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """samples (axis 0 = サンプル) を 1D 列へ再帰フラット展開する (LD-14).

    構造化 dtype はフィールドごとに ``Name.field`` へ、多次元配列は先頭の
    非サンプル軸を ``Name[i]`` で 1 段ずつ剥がして 1D になるまで再帰する。
    リーフでのみ連続化し中間スライスのコピーを避ける。
    """
    if arr.dtype.names:  # 構造化: フィールドごとに再帰
        out: list[tuple[str, np.ndarray]] = []
        for field in arr.dtype.names:
            out.extend(_flatten(f"{name}.{field}", arr[field]))
        return out
    if arr.ndim <= 1:  # リーフ
        return [(name, np.ascontiguousarray(arr))]
    return [
        pair
        for i in range(arr.shape[1])
        for pair in _flatten(f"{name}[{i}]", arr[:, i])
    ]


def _explode_samples(
    base_name: str,
    samples: np.ndarray,
    diagnostics: list[Diagnostic],
) -> list[tuple[str, np.ndarray]]:
    """多次元/構造化 samples を 1D 列へ多段展開 (LD-14).

    ``_flatten`` に一本化。展開できたら透明化のため info 診断を 1 件 emit する。
    展開不能な列 (0 幅など) は自然に空リストになる。
    """
    pairs = _flatten(base_name, samples)
    if pairs:
        if samples.dtype.names:
            shape_desc = "構造化チャンネル"
        else:
            shape_desc = "x".join(str(d) for d in samples.shape[1:]) + " 配列"
        diagnostics.append(
            Diagnostic(
                level="info",
                message=f"Signal '{base_name}': {shape_desc}を {len(pairs)} 本に展開",
                signal_name=base_name,
            )
        )
    return pairs
```

- [ ] **Step 4: 全展開テストが通ることを確認**

Run: `uv run pytest tests/test_loaders.py -k "explode or 2d_channel or structured_channel" -v`
Expected: PASS（新 2 テスト＋既存 `test_explode_samples_subarray_field_one_level`・`test_2d_channel_explodes_into_columns`・`test_structured_channel_fields_visible` が全て緑。subarray 1 段テストは再帰でも同結果）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/core/loaders/mdf4_loader.py tests/test_loaders.py
uv run ruff format src/valisync/core/loaders/mdf4_loader.py tests/test_loaders.py
git add src/valisync/core/loaders/mdf4_loader.py tests/test_loaders.py
git commit -m "feat(core): _explode_samples を任意 ndim の多段フラット展開へ再帰化 (LD-14)"
```

---

### Task 2: 展開列数の事前算出（`_leaf_column_count`）＋`_flatten` との不変条件

実サンプルを全量読まずに展開後リーフ列数を求める純関数。`_flatten` と同一規則で、`len(_flatten(x, s)) == _leaf_column_count(s)` を保証する。

**Files:**
- Modify: `src/valisync/core/loaders/mdf4_loader.py`（`_flatten` の直後に追加）
- Test: `tests/test_loaders.py`（Task 1 の展開テスト群の近くに追加）

**Interfaces:**
- Consumes: `_flatten`（Task 1）
- Produces: `_leaf_column_count(arr: np.ndarray) -> int`

- [ ] **Step 1: 不変条件テストを書く**

```python
def test_leaf_column_count_matches_flatten() -> None:
    """任意形状で _leaf_column_count は _flatten のリーフ数と一致する (LD-14)."""
    from valisync.core.loaders.mdf4_loader import _flatten, _leaf_column_count

    cases = [
        np.zeros(3),  # 1D scalar -> 1
        np.zeros((3, 4)),  # 2D -> 4
        np.zeros((3, 2, 5)),  # 3D -> 10
        np.zeros((2, 2, 2, 3)),  # 4D -> 12
        np.zeros(3, dtype=[("x", "<f8"), ("y", "<f8", (4,))]),  # struct -> 1+4=5
    ]
    for arr in cases:
        assert _leaf_column_count(arr) == len(_flatten("x", arr))

    assert _leaf_column_count(np.zeros((3, 4))) == 4
    assert _leaf_column_count(np.zeros((3, 2, 5))) == 10
    assert _leaf_column_count(np.zeros(3)) == 1
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_loaders.py::test_leaf_column_count_matches_flatten -v`
Expected: FAIL（`ImportError: cannot import name '_leaf_column_count'`）

- [ ] **Step 3: `_leaf_column_count` を実装**

`_flatten` の直後に追加:

```python
def _leaf_column_count(arr: np.ndarray) -> int:
    """arr を _flatten したときのリーフ列数 (1 レコードの samples でも可・LD-14).

    ``_flatten`` と同じ規則: 構造化はフィールド再帰合算、多次元は非サンプル軸
    (shape[1:]) の積。プローブ (record_count=1) と本読みで shape[1:] は一致する
    ため 1 レコードから正確な展開列数が得られる。
    """
    if arr.dtype.names:
        return sum(_leaf_column_count(arr[f]) for f in arr.dtype.names)
    if arr.ndim <= 1:
        return 1
    return int(np.prod(arr.shape[1:]))
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/test_loaders.py::test_leaf_column_count_matches_flatten -v`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/core/loaders/mdf4_loader.py tests/test_loaders.py
uv run ruff format src/valisync/core/loaders/mdf4_loader.py tests/test_loaders.py
git add src/valisync/core/loaders/mdf4_loader.py tests/test_loaders.py
git commit -m "feat(core): 展開列数の事前算出 _leaf_column_count と不変条件 (LD-14)"
```

---

### Task 3: 型・定数・展開前スキャン（`_scan_oversized`）

確認コールバックへ渡す型と、1 レコードプローブで 1024 超チャンネルを集約するスキャンを追加する。スキャンは `select(record_count=1)` を**グループ単位**で呼ぶ（asammdf 実測で `select` が `record_count` 対応・probe `shape[1:]` が本読みと一致することを確認済み）。

**Files:**
- Modify: `src/valisync/core/loaders/mdf4_loader.py`（モジュール先頭付近に型/定数・クラスに `_scan_oversized`／`_probe_options`）
- Modify: `tests/mdf4_helpers.py`（幅広 2D uint8 ヘルパ追加）
- Test: `tests/test_loaders.py`

**Interfaces:**
- Consumes: `_leaf_column_count`（Task 2）・`_group_entries`（既存）
- Produces:
  - `EXPANSION_COLUMN_LIMIT: int = 1024`
  - `@dataclass(frozen=True) class OversizedChannel: name: str; column_count: int`
  - `@dataclass(frozen=True) class ExpansionRequest: channels: tuple[OversizedChannel, ...]`
  - `ConfirmExpansion = Callable[[ExpansionRequest], set[int]]`
  - `Mdf4Loader._scan_oversized(mdf, cancel) -> tuple[list[OversizedChannel], list[tuple[int, int]]]`（並列: 表示用 と (gi,ci) キー）
  - `write_mdf4_wide_2d(tmp_path, cols=1025) -> Path`（幅 cols の 2D uint8 チャンネル`Wide` + 通常 `Clean`）

- [ ] **Step 1: 幅広 2D ヘルパを追加**

`tests/mdf4_helpers.py` 末尾に追加（3D は public write 不可のため、上限超の検証は幅広 2D で行う）:

```python
def write_mdf4_wide_2d(tmp_path: Path, cols: int = 1025) -> Path:
    """幅 cols の 2D uint8 チャンネル (上限 1024 超) + 通常チャンネル — LD-14 用.

    3D は asammdf public write で round-trip 不可なので、per-channel 1024 ガードの
    end-to-end 検証は幅広 2D (列数 > 1024) で行う。列 i の 0 行目 = i%256。
    """
    ts = np.array([0.0, 0.1, 0.2], dtype=np.float64)
    mat = np.tile(np.arange(cols, dtype=np.uint8), (3, 1))  # (3, cols)
    mdf = MDF()
    try:
        mdf.append([ASignal(samples=mat, timestamps=ts, name="Wide")])
        mdf.append(
            [ASignal(samples=np.array([1.0, 2.0, 3.0]), timestamps=ts, name="Clean")]
        )
        path = tmp_path / "wide2d.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path
```

- [ ] **Step 2: スキャンのテストを書く**

`tests/test_loaders.py` に追加（`_scan_oversized` は `Mdf4Loader` の private メソッド）:

```python
def test_scan_oversized_flags_wide_channel(tmp_path: Path) -> None:
    """1 レコードプローブで 1024 超チャンネルのみ検出する (LD-14)."""
    from asammdf import MDF

    from valisync.core.loaders.mdf4_loader import Mdf4Loader

    path = write_mdf4_wide_2d(tmp_path, cols=1025)
    loader = Mdf4Loader()
    with MDF(str(path)) as mdf:
        oversized, keys = loader._scan_oversized(mdf, None)
    assert [o.name for o in oversized] == ["Wide"]
    assert oversized[0].column_count == 1025
    assert len(keys) == 1  # (gi, ci) キーが 1 件
```

- [ ] **Step 3: 失敗を確認**

Run: `uv run pytest tests/test_loaders.py::test_scan_oversized_flags_wide_channel -v`
Expected: FAIL（`_scan_oversized` 未定義）

- [ ] **Step 4: 型・定数・スキャンを実装**

`mdf4_loader.py` の import に `dataclass` を追加（先頭）:

```python
from dataclasses import dataclass
```

`_BUS_TYPE_MAP` の直前あたり（モジュール先頭付近）に型と定数:

```python
EXPANSION_COLUMN_LIMIT = 1024  # per-channel の展開後リーフ列数の上限 (LD-14)


@dataclass(frozen=True)
class OversizedChannel:
    """展開列数が上限を超えるチャンネル (確認ダイアログ提示用)."""

    name: str
    column_count: int


@dataclass(frozen=True)
class ExpansionRequest:
    """上限超チャンネルの集約 — confirm_expansion コールバックへ渡す."""

    channels: tuple[OversizedChannel, ...]


# confirm_expansion(request) -> 展開する channels のインデックス集合。
# 返らなかったインデックスはスキップ。空集合は全スキップ。
ConfirmExpansion = Callable[[ExpansionRequest], set[int]]
```

`Mdf4Loader` クラスに `_PROBE_OPTIONS` と `_scan_oversized` を追加（`_SELECT_OPTIONS` 定義の直後）:

```python
    # 形状スキャン専用: 1 レコードだけ raw で読む (変換不要・形状は変換非依存)。
    _PROBE_OPTIONS: ClassVar[dict[str, Any]] = {
        "record_count": 1,
        "raw": True,
        "ignore_value2text_conversions": True,
        "copy_master": False,
    }

    def _scan_oversized(
        self,
        mdf: Any,
        cancel: Callable[[], bool] | None,
    ) -> tuple[list[OversizedChannel], list[tuple[int, int]]]:
        """本読み前に各チャンネルの展開列数を 1 レコードプローブで算出する (LD-14).

        1024 超のチャンネルを集約して返す。呼び出しはグループ単位 (仮想グループ数
        ぶん) の極小読みで済む。戻り値は表示用 OversizedChannel 列と、対応する
        (物理gi, ci) キー列 (本読みでの除外照合用) の並列リスト。
        """
        oversized: list[OversizedChannel] = []
        keys: list[tuple[int, int]] = []
        for gi in mdf.virtual_groups:
            if cancel is not None and cancel():
                raise LoadCancelled("load cancelled during expansion scan")
            entries = self._group_entries(mdf, gi)
            if not entries:
                continue
            probes = mdf.select(entries, **self._PROBE_OPTIONS)
            for (name, phys_gi, ci), probe in zip(entries, probes, strict=True):
                cols = _leaf_column_count(probe.samples)
                if cols > EXPANSION_COLUMN_LIMIT:
                    oversized.append(OversizedChannel(name=name, column_count=cols))
                    keys.append((phys_gi, ci))
        return oversized, keys
```

- [ ] **Step 5: 通過を確認**

Run: `uv run pytest tests/test_loaders.py::test_scan_oversized_flags_wide_channel -v`
Expected: PASS

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run ruff check src/valisync/core/loaders/mdf4_loader.py tests/mdf4_helpers.py tests/test_loaders.py
uv run ruff format src/valisync/core/loaders/mdf4_loader.py tests/mdf4_helpers.py tests/test_loaders.py
uv run mypy src/
git add src/valisync/core/loaders/mdf4_loader.py tests/mdf4_helpers.py tests/test_loaders.py
git commit -m "feat(core): 展開前スキャン _scan_oversized と ExpansionRequest 型 (LD-14)"
```

---

### Task 4: 確認コールバック配線＋スキップ除外（`Mdf4Loader.load`）

`load()` にスキャン→確認→決定を組み込み、スキップ対象を本読み entries から除外し警告診断を emit する。

**Files:**
- Modify: `src/valisync/core/loaders/mdf4_loader.py`（`load` シグネチャ・スキャン呼び出し・`_load_group` に `skip_keys` 引数）
- Test: `tests/test_loaders.py`

**Interfaces:**
- Consumes: `_scan_oversized`・`ExpansionRequest`・`ConfirmExpansion`（Task 3）
- Produces: `Mdf4Loader.load(file_path, cancel=None, confirm_expansion: ConfirmExpansion | None = None) -> LoadResult`

- [ ] **Step 1: コールバック挙動の統合テストを書く**

```python
def test_oversized_expands_only_when_confirmed(tmp_path: Path) -> None:
    """confirm_expansion が選んだ超過チャンネルのみ展開される (LD-14)."""
    from valisync.core.loaders.mdf4_loader import ExpansionRequest, Mdf4Loader

    path = write_mdf4_wide_2d(tmp_path, cols=1025)

    seen: list[ExpansionRequest] = []

    def confirm(req: ExpansionRequest) -> set[int]:
        seen.append(req)
        return {0}  # Wide を展開する

    result = Mdf4Loader().load(path, confirm_expansion=confirm)
    names = {s.name for s in result.signal_group.signals}
    assert "Clean" in names
    assert "Wide[0]" in names and "Wide[1024]" in names  # 1025 列 (0..1024)
    assert len(seen) == 1 and seen[0].channels[0].name == "Wide"


def test_oversized_skipped_when_declined(tmp_path: Path) -> None:
    """空集合を返すと超過チャンネルはスキップ・警告診断が出る・他は生存 (LD-14)."""
    from valisync.core.loaders.mdf4_loader import ExpansionRequest, Mdf4Loader

    path = write_mdf4_wide_2d(tmp_path, cols=1025)
    result = Mdf4Loader().load(path, confirm_expansion=lambda req: set())
    names = {s.name for s in result.signal_group.signals}
    assert "Clean" in names
    assert not any(n.startswith("Wide") for n in names)
    warns = [d for d in result.diagnostics if d.level == "warning" and "Wide" in d.message]
    assert len(warns) == 1 and "1024" in warns[0].message


def test_oversized_skipped_headless_without_callback(tmp_path: Path) -> None:
    """コールバック不在 (ヘッドレス) は超過を全スキップ+警告 (LD-14 既定)."""
    from valisync.core.loaders.mdf4_loader import Mdf4Loader

    path = write_mdf4_wide_2d(tmp_path, cols=1025)
    result = Mdf4Loader().load(path)  # confirm_expansion 無し
    names = {s.name for s in result.signal_group.signals}
    assert "Clean" in names and not any(n.startswith("Wide") for n in names)
    assert any(d.level == "warning" and "Wide" in d.message for d in result.diagnostics)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_loaders.py -k "oversized" -v`
Expected: FAIL（`load()` が `confirm_expansion` 引数を持たない / 超過が展開されてしまう）

- [ ] **Step 3: `load` にスキャン→確認→決定を組み込む**

`load` シグネチャを変更:

```python
    def load(
        self,
        file_path: Path,
        cancel: Callable[[], bool] | None = None,
        confirm_expansion: ConfirmExpansion | None = None,
    ) -> LoadResult:
```

`mdf` を開いた後（`try:` ブロック内、`name_total = self._count_names(mdf)` の直前）にスキャン→決定を挿入し、その `skip_keys` をループへ渡す:

```python
        try:
            oversized, over_keys = self._scan_oversized(mdf, cancel)
            skip_keys: set[tuple[int, int]] = set()
            if oversized:
                if confirm_expansion is not None:
                    chosen = confirm_expansion(ExpansionRequest(channels=tuple(oversized)))
                else:
                    chosen = set()  # ヘッドレス: 確認できないので全スキップ (安全側)
                skip_keys = {
                    key for i, key in enumerate(over_keys) if i not in chosen
                }
                for i, key in enumerate(over_keys):
                    if key in skip_keys:
                        diagnostics.append(
                            Diagnostic(
                                level="warning",
                                message=(
                                    f"Signal '{oversized[i].name}': 展開列数 "
                                    f"{oversized[i].column_count} が上限 "
                                    f"{EXPANSION_COLUMN_LIMIT} を超えるためスキップ"
                                ),
                                signal_name=oversized[i].name,
                            )
                        )
            name_total = self._count_names(mdf)
            name_seen: dict[str, int] = {}
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
                    skip_keys,
                )
```

> `diagnostics` は既に `try` の前で初期化済み（`diagnostics: list[Diagnostic] = []`）。上のブロックはその参照へ append する。

`_load_group` にパラメータ `skip_keys` を追加し、entries をフィルタする:

```python
    def _load_group(
        self,
        mdf: Any,
        gi: int,
        resolved_path: Path,
        name_total: dict[str, int],
        name_seen: dict[str, int],
        signals: list[Signal],
        diagnostics: list[Diagnostic],
        cancel: Callable[[], bool] | None,
        skip_keys: set[tuple[int, int]],
    ) -> None:
        entries = [
            e for e in self._group_entries(mdf, gi) if (e[1], e[2]) not in skip_keys
        ]
        if not entries:
            return
```

（`entries = self._group_entries(mdf, gi)` の元行をこの内包表記へ置換。以降の `select`/ループは不変。スキップ対象は entries に載らないため `select` で本読みもされない＝メモリ/時間も節約。）

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/test_loaders.py -k "oversized" -v`
Expected: PASS（3 テスト緑）

- [ ] **Step 5: 全ローダーテストの無回帰を確認**

Run: `uv run pytest tests/test_loaders.py tests/test_pbt_mdf4.py -v`
Expected: PASS（既存の展開・診断・キャンセル・共有マスタテストが全て緑。スキャン追加は超過なしファイルでは no-op）

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run ruff check src/valisync/core/loaders/mdf4_loader.py tests/test_loaders.py
uv run ruff format src/valisync/core/loaders/mdf4_loader.py tests/test_loaders.py
uv run mypy src/
git add src/valisync/core/loaders/mdf4_loader.py tests/test_loaders.py
git commit -m "feat(core): confirm_expansion 配線と超過チャンネルのスキップ除外 (LD-14)"
```

---

### Task 5: `Session.load` パススルー＋型再エクスポート

`Session.load` から MDF4 ローダーへ `confirm_expansion` を委譲。GUI が型を import できるよう再エクスポートする。

**Files:**
- Modify: `src/valisync/core/session.py:122-150`（`load` シグネチャ・委譲）
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `Mdf4Loader.load(..., confirm_expansion=...)`（Task 4）
- Produces: `Session.load(file_path, format_def=None, cancel=None, confirm_expansion: ConfirmExpansion | None = None) -> LoadOutcome`

- [ ] **Step 1: パススルーのテストを書く**

`tests/test_session.py` に追加（既存の mdf4 ヘルパ import 形に合わせる）:

```python
def test_session_load_passes_confirm_expansion(tmp_path: Path) -> None:
    """Session.load が confirm_expansion を MDF4 ローダーへ委譲する (LD-14)."""
    from mdf4_helpers import write_mdf4_wide_2d

    from valisync.core.session import Session

    called: list[int] = []

    def confirm(req: object) -> set[int]:
        called.append(len(req.channels))  # type: ignore[attr-defined]
        return set()

    session = Session()
    session.load(write_mdf4_wide_2d(tmp_path, cols=1025), confirm_expansion=confirm)
    assert called == [1]  # Wide 1 件が確認に回った
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/test_session.py::test_session_load_passes_confirm_expansion -v`
Expected: FAIL（`load()` に `confirm_expansion` 引数なし）

- [ ] **Step 3: `Session.load` を拡張**

`src/valisync/core/session.py` の import に追加:

```python
from valisync.core.loaders.mdf4_loader import ConfirmExpansion, ExpansionRequest, OversizedChannel
```

`__all__` があれば `"ConfirmExpansion", "ExpansionRequest", "OversizedChannel"` を追記（無ければスキップ）。`load` を変更:

```python
    def load(
        self,
        file_path: Path,
        format_def: FormatDefinition | None = None,
        cancel: Callable[[], bool] | None = None,
        confirm_expansion: ConfirmExpansion | None = None,
    ) -> LoadOutcome:
```

MDF4 分岐の委譲行を変更:

```python
        elif self._mdf4_loader.supports(file_path):
            result = self._mdf4_loader.load(
                file_path, cancel=cancel, confirm_expansion=confirm_expansion
            )
```

（docstring に一文追加: `confirm_expansion` は多次元チャンネルの展開列数が上限を超えるとき呼ばれ、展開するチャンネルの選択を返すコールバック。）

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/test_session.py::test_session_load_passes_confirm_expansion tests/test_session.py -v`
Expected: PASS（新テスト＋既存 session テスト無回帰）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/core/session.py tests/test_session.py
uv run ruff format src/valisync/core/session.py tests/test_session.py
uv run mypy src/
git add src/valisync/core/session.py tests/test_session.py
git commit -m "feat(core): Session.load が confirm_expansion を委譲 (LD-14)"
```

---

### Task 6: 確認ダイアログ（`ExpansionDialog.ask`）— GUI Layer A

チェックボックス一覧のモーダル。`ExpansionRequest` を受け、展開するインデックス集合を返す。GUI スレッドで呼ばれる前提の純 UI（スレッド連携は Task 7）。

**Files:**
- Create: `src/valisync/gui/views/expansion_dialog.py`
- Test: `tests/gui/test_expansion_dialog.py`

**Interfaces:**
- Consumes: `ExpansionRequest`・`OversizedChannel`（Task 3・core から import）
- Produces: `ExpansionDialog.ask(request: ExpansionRequest, parent: QWidget | None = None) -> set[int]`（static）

- [ ] **Step 1: ダイアログのテストを書く**

`tests/gui/test_expansion_dialog.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QDialog

from valisync.core.loaders.mdf4_loader import ExpansionRequest, OversizedChannel
from valisync.gui.views.expansion_dialog import ExpansionDialog


def _req() -> ExpansionRequest:
    return ExpansionRequest(
        channels=(
            OversizedChannel(name="Wide", column_count=1025),
            OversizedChannel(name="Cube", column_count=4096),
        )
    )


def test_dialog_returns_checked_indices(qtbot) -> None:
    """チェックした行のインデックス集合を返す (LD-14)."""
    dlg = ExpansionDialog(_req())
    qtbot.addWidget(dlg)
    dlg._checks[1].setChecked(True)  # Cube のみ展開
    dlg._on_accept()
    assert dlg.result_indices == {1}


def test_dialog_default_all_unchecked(qtbot) -> None:
    """初期状態は全未チェック=全スキップ (慎重側の既定・LD-14)."""
    dlg = ExpansionDialog(_req())
    qtbot.addWidget(dlg)
    assert all(not c.isChecked() for c in dlg._checks)


def test_dialog_select_all_and_none(qtbot) -> None:
    """全展開/全スキップ ボタンで一括トグルできる (LD-14)."""
    dlg = ExpansionDialog(_req())
    qtbot.addWidget(dlg)
    dlg._select_all()
    assert all(c.isChecked() for c in dlg._checks)
    dlg._select_none()
    assert all(not c.isChecked() for c in dlg._checks)


def test_ask_reject_returns_empty(qtbot, monkeypatch) -> None:
    """Cancel (reject) は空集合を返す (LD-14)."""
    monkeypatch.setattr(ExpansionDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert ExpansionDialog.ask(_req()) == set()
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_expansion_dialog.py -v`
Expected: FAIL（モジュール未作成）

- [ ] **Step 3: `ExpansionDialog` を実装**

`src/valisync/gui/views/expansion_dialog.py`:

```python
"""展開列数が上限を超えるチャンネルの展開/スキップを選ぶモーダル (LD-14).

per-channel でチェックし、OK で「展開する」インデックス集合を返す。初期状態は
全未チェック (=全スキップ) — ガードの主旨が慎重側のため。GUI スレッドで呼ぶ
前提の純 UI で、ワーカースレッドからの起動は ExpansionConfirmer が担う。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from valisync.core.loaders.mdf4_loader import EXPANSION_COLUMN_LIMIT, ExpansionRequest


class ExpansionDialog(QDialog):
    def __init__(
        self, request: ExpansionRequest, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("大きな信号の展開確認")
        self.result_indices: set[int] = set()

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "以下の信号は展開すると列数が上限"
                f"（{EXPANSION_COLUMN_LIMIT}）を超えます。\n"
                "展開するものを選択してください（未選択はスキップ）。"
            )
        )

        self._checks: list[QCheckBox] = []
        for ch in request.channels:
            cb = QCheckBox(f"{ch.name} — {ch.column_count} 列")
            cb.toggled.connect(self._update_total)
            layout.addWidget(cb)
            self._checks.append(cb)

        self._total = QLabel()
        layout.addWidget(self._total)

        btn_row = QHBoxLayout()
        all_btn = QPushButton("すべて展開")
        none_btn = QPushButton("すべてスキップ")
        all_btn.clicked.connect(self._select_all)
        none_btn.clicked.connect(self._select_none)
        btn_row.addWidget(all_btn)
        btn_row.addWidget(none_btn)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._request = request
        self._update_total()

    def _update_total(self) -> None:
        total = sum(
            self._request.channels[i].column_count
            for i, cb in enumerate(self._checks)
            if cb.isChecked()
        )
        self._total.setText(f"展開後の追加列数: {total}")

    def _select_all(self) -> None:
        for cb in self._checks:
            cb.setChecked(True)

    def _select_none(self) -> None:
        for cb in self._checks:
            cb.setChecked(False)

    def _on_accept(self) -> None:
        self.result_indices = {
            i for i, cb in enumerate(self._checks) if cb.isChecked()
        }
        self.accept()

    @staticmethod
    def ask(request: ExpansionRequest, parent: QWidget | None = None) -> set[int]:
        """モーダル表示し「展開する」インデックス集合を返す (Cancel は空集合)."""
        dlg = ExpansionDialog(request, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.result_indices
        return set()
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_expansion_dialog.py -v`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/expansion_dialog.py tests/gui/test_expansion_dialog.py
uv run ruff format src/valisync/gui/views/expansion_dialog.py tests/gui/test_expansion_dialog.py
uv run mypy src/
git add src/valisync/gui/views/expansion_dialog.py tests/gui/test_expansion_dialog.py
git commit -m "feat(gui): 展開確認ダイアログ ExpansionDialog (LD-14)"
```

---

### Task 7: クロススレッド確認（`ExpansionConfirmer`）— GUI Layer B

ワーカースレッドから呼ばれる `confirm(request)` を、GUI スレッドのモーダルへ marshal し回答までブロックする。

**Files:**
- Create: `src/valisync/gui/workers/expansion_confirmer.py`
- Test: `tests/gui/test_expansion_confirmer.py`

**Interfaces:**
- Consumes: `ExpansionDialog.ask`（Task 6）・`ExpansionRequest`（Task 3）
- Produces: `ExpansionConfirmer(QObject)` — `confirm(request: ExpansionRequest) -> set[int]`（ワーカースレッドから呼ぶ・ブロッキング）

- [ ] **Step 1: クロススレッドのテストを書く**

`tests/gui/test_expansion_confirmer.py`（別スレッドから `confirm` を呼び、GUI スレッドのスロットが処理して戻り値が伝播することを検証）:

```python
from __future__ import annotations

import threading

from PySide6.QtCore import QThread

from valisync.core.loaders.mdf4_loader import ExpansionRequest, OversizedChannel
from valisync.gui.views.expansion_dialog import ExpansionDialog
from valisync.gui.workers.expansion_confirmer import ExpansionConfirmer


def _req() -> ExpansionRequest:
    return ExpansionRequest(channels=(OversizedChannel(name="Wide", column_count=1025),))


def test_confirm_marshals_to_gui_thread(qtbot, monkeypatch) -> None:
    """別スレッドからの confirm が GUI スレッドの ask を呼び結果を返す (LD-14)."""
    seen_thread: list[int] = []

    def fake_ask(request, parent=None):  # GUI スレッドで呼ばれるはず
        seen_thread.append(threading.get_ident())
        return {0}

    monkeypatch.setattr(ExpansionDialog, "ask", staticmethod(fake_ask))

    confirmer = ExpansionConfirmer()
    qtbot.addWidget_or_object = None  # confirmer は QWidget ではないので addWidget 不要

    result: dict[str, set[int]] = {}
    worker_thread_id: list[int] = []

    def worker() -> None:
        worker_thread_id.append(threading.get_ident())
        result["value"] = confirmer.confirm(_req())

    t = threading.Thread(target=worker)
    t.start()
    # GUI スレッドはイベントを回して queued スロットを処理する
    qtbot.waitUntil(lambda: "value" in result, timeout=3000)
    t.join(timeout=3000)

    assert result["value"] == {0}
    # ask は GUI (メイン) スレッドで実行され、worker スレッドとは別 ident
    assert seen_thread and seen_thread[0] != worker_thread_id[0]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_expansion_confirmer.py -v`
Expected: FAIL（モジュール未作成）

- [ ] **Step 3: `ExpansionConfirmer` を実装**

`src/valisync/gui/workers/expansion_confirmer.py`:

```python
"""ワーカースレッド→GUI スレッドの展開確認モーダル委譲 (LD-14).

ロードはワーカースレッドで走るが、確認モーダルは GUI スレッドで出す必要がある。
confirm() をワーカースレッドから呼ぶと、Signal (QueuedConnection) で GUI スレッド
のスロットへ marshal し、threading.Event でモーダルの回答までワーカーをブロックする。
ロード中の GUI スレッドはブロックされていない (オフスレッドロード) ため、queued
スロットが処理でき入れ子イベントループが回る = デッドロックしない。
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal, Slot

from valisync.core.loaders.mdf4_loader import ExpansionRequest
from valisync.gui.views.expansion_dialog import ExpansionDialog


class ExpansionConfirmer(QObject):
    _requested = Signal(object)  # (request, holder: dict, event) を GUI スレッドへ

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # confirmer は GUI スレッド所属。worker からの emit は自動で QueuedConnection。
        self._requested.connect(self._on_requested, Qt.ConnectionType.QueuedConnection)

    def confirm(self, request: ExpansionRequest) -> set[int]:
        """ワーカースレッドから呼ぶ。GUI モーダルの回答までブロックし結果を返す."""
        holder: dict[str, set[int]] = {}
        event = threading.Event()
        self._requested.emit((request, holder, event))
        event.wait()
        return holder.get("result", set())

    @Slot(object)
    def _on_requested(self, payload: object) -> None:
        request, holder, event = payload  # type: ignore[misc]
        try:
            holder["result"] = ExpansionDialog.ask(request)
        finally:
            event.set()
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_expansion_confirmer.py -v`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/workers/expansion_confirmer.py tests/gui/test_expansion_confirmer.py
uv run ruff format src/valisync/gui/workers/expansion_confirmer.py tests/gui/test_expansion_confirmer.py
uv run mypy src/
git add src/valisync/gui/workers/expansion_confirmer.py tests/gui/test_expansion_confirmer.py
git commit -m "feat(gui): クロススレッド展開確認 ExpansionConfirmer (LD-14)"
```

---

### Task 8: ロードパイプラインへ配線（`main_window`）

`_load_file` のロードラムダに `confirm_expansion=self._expansion_confirmer.confirm` を渡す。confirmer は GUI スレッド所属で `MainWindow` に持たせる。

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（`__init__` で confirmer 生成・`_load_file:148` のラムダ）
- Test: `tests/gui/test_main_window_load.py`（既存があれば追記。無ければ新規）

**Interfaces:**
- Consumes: `ExpansionConfirmer`（Task 7）・`Session.load(..., confirm_expansion=...)`（Task 5）

- [ ] **Step 1: 配線テストを書く**

既存のロード配線テストの流儀に合わせる（無ければ `tests/gui/test_main_window_load.py` を新規作成）。confirmer が `Session.load` へ渡ることを、`_load_file` が構築するラムダ経由で検証:

```python
def test_load_file_passes_confirmer(qtbot, tmp_path, monkeypatch) -> None:
    """_load_file が confirm_expansion に confirmer.confirm を渡す (LD-14)."""
    from mdf4_helpers import write_mdf4

    from valisync.gui.views.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    captured: dict[str, object] = {}
    real_load = win.app_vm.session.load

    def spy_load(path, fmt=None, cancel=None, confirm_expansion=None):
        captured["confirm"] = confirm_expansion
        return real_load(path, fmt, cancel=cancel, confirm_expansion=confirm_expansion)

    monkeypatch.setattr(win.app_vm.session, "load", spy_load)

    path = write_mdf4(tmp_path / "x.mf4", [{"name": "A", "values": [1.0, 2.0]}])
    win._load_file(path)
    qtbot.waitUntil(lambda: "confirm" in captured, timeout=3000)
    assert captured["confirm"] == win._expansion_confirmer.confirm
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_main_window_load.py::test_load_file_passes_confirmer -v`
Expected: FAIL（`_expansion_confirmer` 属性なし / ラムダが confirm を渡さない）

- [ ] **Step 3: `main_window` に配線**

`__init__` の `self._load_controller = LoadController(parent=self)`（70 行付近）の直後に:

```python
        self._expansion_confirmer = ExpansionConfirmer(self)
```

import 追加（他の workers import の近く）:

```python
from valisync.gui.workers.expansion_confirmer import ExpansionConfirmer
```

`_load_file`（148 行）のラムダを変更:

```python
        self._load_controller.submit(
            lambda: session.load(
                target,
                None,
                cancel=cancel_event.is_set,
                confirm_expansion=self._expansion_confirmer.confirm,
            ),
            busy=self.busy_overlay,
            ...
        )
```

- [ ] **Step 4: 通過を確認**

Run: `uv run pytest tests/gui/test_main_window_load.py -v`
Expected: PASS

- [ ] **Step 5: GUI テスト全体の無回帰を確認**

Run: `uv run pytest tests/gui -q`
Expected: PASS

- [ ] **Step 6: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/main_window.py tests/gui/test_main_window_load.py
uv run ruff format src/valisync/gui/views/main_window.py tests/gui/test_main_window_load.py
uv run mypy src/
git add src/valisync/gui/views/main_window.py tests/gui/test_main_window_load.py
git commit -m "feat(gui): ロードパイプラインへ展開確認 confirmer を配線 (LD-14)"
```

---

### Task 9: ドキュメント更新（catalog・roadmap・r3 spec 注記・CLAUDE.md）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（LD-14 行を新規追加・LD-12 行に注記）
- Modify: `docs/roadmap.md`（SS-LOADERS の状況）
- Modify: `docs/superpowers/specs/2026-07-05-core-loaders-hardening-r3-design.md:18`（LD-12「列数上限なし」→ LD-14 で per-channel 1024 ガード追加の注記）
- Modify: `CLAUDE.md`（Phase 状況の SS-LOADERS 記述）

- [ ] **Step 1: catalog に LD-14 を追加**

`docs/audit-findings-catalog.md` の SS-LOADERS セクションに行を追加（既存フォーマットに合わせ ID・file:line・優先度・状況を記載）:

```markdown
| LD-14 | mdf4_loader.py `_explode_samples` | ndim≥3 の多次元チャンネルが展開されず消失／深い展開の列爆発が無制御 | ✅解消（2026-07-05・多段フラット展開 `Name[i][j]` へ再帰化＋per-channel 1024 列ガード＝超過は GUI 確認で展開/スキップ選択・ヘッドレスは全スキップ） |
```

LD-12 行の状況末尾に注記を追記: 「（LD-14 で per-channel 1024 ガードを追加。1024 以下は自動展開のまま・超過は確認必須へ改訂）」。

- [ ] **Step 2: roadmap を更新**

`docs/roadmap.md` の SS-LOADERS 記述に LD-14 完了を反映（第2弾=開く経路 LD-01/02 を残すのみは不変）。

- [ ] **Step 3: r3 spec §1 に改訂注記**

`docs/superpowers/specs/2026-07-05-core-loaders-hardening-r3-design.md` の LD-12 行（18 行目付近）末尾に:「（**LD-14 で改訂**: per-channel 1024 列ガードを追加。1024 以下は自動展開のまま・超過はユーザー確認で展開/スキップ）」。

- [ ] **Step 4: CLAUDE.md を更新**

Phase 状況テーブルの SS-LOADERS 記述に「LD-14（ndim≥3 多段展開＋1024 ガード）実装済み」を追記し、LD-14 spec/plan へのポインタを張る。

- [ ] **Step 5: 最終ゲート＋コミット**

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
git add docs/ CLAUDE.md
git commit -m "docs: LD-14 (ndim≥3 多段展開+1024 ガード) を catalog/roadmap/CLAUDE.md へ反映"
```

---

## Self-Review

- **Spec coverage**: §3.1 多段展開 → Task 1／§3.2 列数算出 → Task 2／§3.3 スキャン → Task 3／§3.4 コールバック・decline → Task 4・5／§3.5 ダイアログ → Task 6／§3.4 クロススレッド → Task 7／配線 → Task 8／§4 docs → Task 9。全カバー。
- **型整合**: `ConfirmExpansion = Callable[[ExpansionRequest], set[int]]` を Task 3 で定義し Task 4/5/7 で一貫使用。`_scan_oversized` 戻り `(list[OversizedChannel], list[tuple[int,int]])` は Task 4 の `over_keys`/`oversized` と一致。`ExpansionDialog.ask -> set[int]` は confirmer `confirm -> set[int]` と一致。
- **プレースホルダ**: Task 3 Step 2 の最初の import 行はわざと誤例として示し直下で正しい版へ置換（実装者は下の版を使う）。他にプレースホルダなし。
- **既存挙動の変更明示**: Task 1 で 3D/ネスト skip テスト 2 件を展開挙動へ更新。Task 4 で全ローダーテスト無回帰を確認する Step を配置。
- **GUI ①ゲート**: 本増分の新規経路は標準 `QDialog` モーダルで、実 OS 入力依存の新経路はない見込み。realgui 要否は実装後 `/gui-verify` で判定（Layer A/B で挙動は担保済み）。
