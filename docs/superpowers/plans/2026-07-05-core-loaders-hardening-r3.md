# core-loaders-hardening 第3弾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MDF4 読み取りパスを `select()` ベースに刷新して LD-13（enum 消滅）と LD-10（メモリ膨張）を解消し、LD-12（多次元チャンネルの要素展開）と LD-07（value_labels 保持＋GUI 併記）を実装する。

**Architecture:** `mdf4_loader.load()` を「①メタデータ走査で重複名カウント → ②グループ単位 `select(ignore_value2text_conversions=True, copy_master=False)` → ③グループの時刻軸を float64 read-only で1本実体化し全信号で共有 → ④チャンネル逐次変換（`astype(copy=False)`＋writeable=False で `Signal.__post_init__` のゼロコピー経路）」に置換。多次元は同ループ内で `Name[i]`/`Name.field` へ展開。value2text 変換表は `Signal.metadata["value_labels"]` に保持し、CursorReadout と ChannelBrowser ツールチップが併記する。

**Tech Stack:** asammdf 8.8.11（uv.lock 固定）・numpy・PySide6。既存の診断/キャンセル契約は不変。

**Spec:** [docs/superpowers/specs/2026-07-05-core-loaders-hardening-r3-design.md](../specs/2026-07-05-core-loaders-hardening-r3-design.md)

## Global Constraints

- 品質ゲート（各タスクのコミット前・全体スコープ）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過。
- **既存診断の契約を変えない**: 非有限 ts の error skip（メッセージ文言不変）・非単調/重複 warning（LD-03・**チャンネルごとに1件**emit）・重複名 `name[idx]`・0ch warning・`LoadCancelled` 協調キャンセル（チャンネル単位チェックポイント）。既存テスト群がそのまま回帰網 — 1本も書き換えずに green が原則（例外: LD-12 で挙動が仕様として変わる demo/2D 系テストのみ、該当タスクで更新）。
- **asammdf API は実装時にソース確認**（`.venv/Lib/site-packages/asammdf/`）: `select()` の引数形式（`(name, group, index)` タプル）・`copy_master=False` の共有実態・`masters_db`・conversion ブロックの value/text 取得。HILS Task 2 と同じ流儀で確認結果を report に記録。**LD-13 が解決しない代替実装は不可**（spec §3.1）。
- **GUI タスク（Task 5/6）の Layer 判定**: 表示テキストの追加のみで新規の実 OS 入力経路なし → Layer A（VM/model 直検証）＋既存 View 経由の Layer B。realgui 追加は不要（merge 前の ①ゲートは既存 realgui suite の無回帰確認 `/gui-verify` で充足）。
- コメントは WHY のみ・全角括弧 RUF002/003 注意（docstring/コメントは半角括弧）。
- hils 2GB のロード実測（Task 7）は**ローカルのみ**・CI には quick/smoke 級テストだけを入れる。
- demo_data の実生成ファイルはコミットしない（`.gitignore` 済み）。

---

## File Structure

- Modify: `src/valisync/core/loaders/mdf4_loader.py` — 読み取りパス刷新＋展開＋value_labels（本増分の中核・1ファイルに集約）
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py` — `CursorReading`/`DeltaReading` に `label`
- Modify: `src/valisync/gui/views/cursor_readout.py` — ラベル併記フォーマット
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py` — `SignalItem.tooltip`
- Modify: `src/valisync/gui/adapters/qt_signal_models.py` — `ToolTipRole`
- Modify: `scripts/generate_demo_mf4.py` — TurnSig の value2text 復活
- Modify: `tests/mdf4_helpers.py`（ヘルパ追加）・`tests/test_loaders.py`・`tests/test_demo_mf4.py`・`tests/gui/…`（各タスク記載）
- Modify: `docs/audit-findings-catalog.md`・`docs/roadmap.md`・`CLAUDE.md`・HILS デモ spec §4.4（Task 4/7）

---

## Task 1: テストヘルパ拡張（value2text / 共有グループ / 2D / 構造化）

**Files:**
- Modify: `tests/mdf4_helpers.py`
- Test: `tests/test_loaders.py`（ヘルパの roundtrip 前提を最小 assert — 後続タスクの土台）

**Interfaces:**
- Produces: `write_mdf4_value2text(tmp_path) -> Path`（`TurnSig`=int値[0,1,2,1]＋TABX 変換 {0:OFF,1:LEFT,2:RIGHT}、`Clean`=float 通常ch）／`write_mdf4_shared_group(tmp_path) -> Path`（`A`/`B` 2ch を**同一チャンネルグループ**に格納・同一時刻軸）／`write_mdf4_2d(tmp_path) -> Path`（`Mat`=uint8 (4,3) 既知値＋`Clean`。uint8 は asammdf で 2D が往復保存できる実証済み方式 — HILS Task 2 の知見）／`write_mdf4_structured(tmp_path) -> Path`（`Pt`=dtype `[('x','<f8'),('y','<f8')]`）

- [ ] **Step 1: ヘルパ4本を追加**

`tests/mdf4_helpers.py` 末尾:

```python
def write_mdf4_value2text(tmp_path: Path) -> Path:
    """TABX (value2text) 変換付き enum チャンネル + 通常チャンネル.

    現行ローダーは value2text をテキスト化して 'non-numeric, skipped' で
    チャンネルごと落とす (LD-13)。刷新後は生値 [0,1,2,1] で生存し、
    metadata['value_labels'] に対応表が入るのが新契約。
    """
    from asammdf.blocks.conversion_utils import from_dict

    conv = from_dict(
        {
            "val_0": 0, "text_0": "OFF",
            "val_1": 1, "text_1": "LEFT",
            "val_2": 2, "text_2": "RIGHT",
        }
    )
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(
                    samples=np.array([0, 1, 2, 1], dtype=np.int16),
                    timestamps=ts,
                    name="TurnSig",
                    conversion=conv,
                )
            ]
        )
        mdf.append(
            [ASignal(samples=np.array([1.0, 2.0, 3.0, 4.0]), timestamps=ts, name="Clean")]
        )
        path = tmp_path / "v2t.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_shared_group(tmp_path: Path) -> Path:
    """同一チャンネルグループに 2ch (A/B, 同一時刻軸) — 共有マスタ検証用."""
    ts = np.arange(0.0, 1.0, 0.1)
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(samples=np.arange(10.0), timestamps=ts, name="A"),
                ASignal(samples=np.arange(10.0) * 2.0, timestamps=ts, name="B"),
            ]
        )  # 1回の append = 1グループ
        path = tmp_path / "shared.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_2d(tmp_path: Path) -> Path:
    """2D (Nx3) uint8 配列チャンネル + 通常チャンネル — LD-12 展開検証用.

    列 i の値は [i, i+10, i+20, i+30] で列ごとに識別可能。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mat = np.array(
        [[0, 1, 2], [10, 11, 12], [20, 21, 22], [30, 31, 32]], dtype=np.uint8
    )
    mdf = MDF()
    try:
        mdf.append([ASignal(samples=mat, timestamps=ts, name="Mat")])
        mdf.append(
            [ASignal(samples=np.array([1.0, 2.0, 3.0, 4.0]), timestamps=ts, name="Clean")]
        )
        path = tmp_path / "mat2d.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_structured(tmp_path: Path) -> Path:
    """構造化 dtype (x,y) チャンネル — フィールド展開検証用."""
    ts = np.array([0.0, 0.1, 0.2])
    rec = np.array(
        [(1.0, 10.0), (2.0, 20.0), (3.0, 30.0)], dtype=[("x", "<f8"), ("y", "<f8")]
    )
    mdf = MDF()
    try:
        mdf.append([ASignal(samples=rec, timestamps=ts, name="Pt")])
        path = tmp_path / "struct.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path
```

- [ ] **Step 2: roundtrip 前提テストを追加し実行**

`tests/test_loaders.py` に追加（ヘルパが「意図した形で書けている」ことだけを asammdf 直読みで固定 — ローダー挙動は後続タスク）:

```python
def test_helper_value2text_roundtrip(tmp_path):
    from tests.mdf4_helpers import write_mdf4_value2text
    from asammdf import MDF

    path = write_mdf4_value2text(tmp_path)
    with MDF(str(path)) as mdf:
        sig = mdf.get("TurnSig")  # 既定 (raw=False) では変換適用でテキスト化する
        assert sig.conversion is not None


def test_helper_2d_roundtrip(tmp_path):
    from tests.mdf4_helpers import write_mdf4_2d
    from asammdf import MDF

    path = write_mdf4_2d(tmp_path)
    with MDF(str(path)) as mdf:
        sig = mdf.get("Mat")
        assert sig.samples.ndim == 2 and sig.samples.shape[1] == 3
```

Run: `uv run pytest tests/test_loaders.py -k helper -v` → PASS（ヘルパのみなので RED フェーズなし。**構造化ヘルパの roundtrip 形状（親のみ/成分併存）はここで `print` 確認し report に記録** — Task 3 の実装分岐の一次情報）。

- [ ] **Step 3: 全体ゲート → Commit**

```bash
git add tests/mdf4_helpers.py tests/test_loaders.py
git commit -m "test(loaders): value2text/共有グループ/2D/構造化の mdf4 書込ヘルパ（第3弾の土台）"
```

---

## Task 2: 読み取りパス刷新 — select() ベース・共有マスタ・逐次変換（LD-13＋LD-10 コア）

**Files:**
- Modify: `src/valisync/core/loaders/mdf4_loader.py`（`load()` を全面書換え・`_extract_metadata`/`_detect_bus_type` は不変）
- Test: `tests/test_loaders.py`

**Interfaces:**
- Consumes: Task 1 の `write_mdf4_value2text`/`write_mdf4_shared_group`
- Produces: 刷新後も `Mdf4Loader.load(file_path, cancel=None) -> LoadResult` のシグネチャ・診断文言・キャンセル挙動は完全互換。内部に `_master_index(mdf, gi) -> int | None`・`_count_names(mdf) -> dict[str, int]`・`_load_group(...)` が生まれる（Task 3/4 が同ループに追記する）

- [ ] **Step 1: asammdf API 実装時確認（コード変更なし・report 記録）**

`.venv/Lib/site-packages/asammdf/mdf.py` で確認: (a) `select()` が `(name, group, index)` タプルの channels リストを受けること、(b) `ignore_value2text_conversions`/`copy_master` パラメータの存在と意味、(c) `copy_master=False` 時に同一グループの戻り Signal 群がマスタ配列を共有するか（**共有しない場合でも設計は成立** — 先頭チャンネルの timestamps から共有マスタを自作して配るため。確認結果だけ記録）、(d) グループのマスタチャンネル index の取得方法（`mdf.masters_db[gi]` 相当）。

- [ ] **Step 2: Write the failing tests**

`tests/test_loaders.py`:

```python
def test_value2text_channel_survives_as_raw(tmp_path):
    """LD-13: value2text 付きチャンネルが生値で生存する (現行は消滅=RED)."""
    from tests.mdf4_helpers import write_mdf4_value2text

    path = write_mdf4_value2text(tmp_path)
    result = Mdf4Loader().load(path)
    names = {s.name for s in result.signal_group.signals}
    assert "TurnSig" in names
    turn = next(s for s in result.signal_group.signals if s.name == "TurnSig")
    assert np.array_equal(turn.values, [0.0, 1.0, 2.0, 1.0])
    assert not any(
        "non-numeric" in d.message and "TurnSig" in d.message
        for d in result.diagnostics
    )


def test_same_group_signals_share_master(tmp_path):
    """LD-10: 同一グループの信号はマスタ時刻軸を共有し read-only (現行は複製=RED)."""
    from tests.mdf4_helpers import write_mdf4_shared_group

    path = write_mdf4_shared_group(tmp_path)
    result = Mdf4Loader().load(path)
    a = next(s for s in result.signal_group.signals if s.name == "A")
    b = next(s for s in result.signal_group.signals if s.name == "B")
    assert np.shares_memory(a.timestamps, b.timestamps)
    assert not a.timestamps.flags.writeable
    assert np.array_equal(a.timestamps, b.timestamps)
```

- [ ] **Step 3: RED 確認**

Run: `uv run pytest tests/test_loaders.py -k "survives_as_raw or share_master" -v`
Expected: FAIL（TurnSig 不在 / shares_memory False）。

- [ ] **Step 4: 実装 — 読み取りパス置換**

`mdf4_loader.py` の `_READ_OPTIONS` と `load()` 本体（`iter_channels` ループ〜変換ループ）を置換:

```python
    _READ_OPTIONS: ClassVar[dict[str, Any]] = {
        "time_from_zero": False,
    }
    # ignore_value2text_conversions は MDF() には無効な dead オプションだった
    # (LD-13)。select() では有効 — enum は生値で届き、変換表は conversion に残る。
    _SELECT_OPTIONS: ClassVar[dict[str, Any]] = {
        "ignore_value2text_conversions": True,
        "copy_master": False,  # マスタ複製の排除 (LD-10)
    }
```

```python
    def load(self, file_path, cancel=None) -> LoadResult:
        # (ファイル存在チェック・MDF() open・except は現行どおり)
        signals: list[Signal] = []
        diagnostics: list[Diagnostic] = []
        try:
            name_total = self._count_names(mdf)
            name_seen: dict[str, int] = {}
            for gi in range(len(mdf.groups)):
                self._load_group(
                    mdf, gi, file_path, name_total, name_seen,
                    signals, diagnostics, cancel,
                )
        except LoadCancelled:
            raise
        except Exception as exc:
            return LoadResult(
                signal_group=None,
                diagnostics=(
                    Diagnostic(
                        level="error",
                        message=f"Failed to read channels from '{file_path.name}': {exc}",
                    ),
                ),
            )
        finally:
            mdf.close()
        # (0ch warning・SignalGroup 構築・return は現行どおり)
```

```python
    def _master_index(self, mdf: Any, gi: int) -> int | None:
        """グループ gi のマスタチャンネル index (Step 1 の確認結果で実装)."""
        return mdf.masters_db.get(gi)

    def _count_names(self, mdf: Any) -> dict[str, int]:
        """重複名 [idx] 曖昧化のための事前カウント (メタデータ走査のみ)."""
        totals: dict[str, int] = {}
        for gi, group in enumerate(mdf.groups):
            m_idx = self._master_index(mdf, gi)
            for ci, ch in enumerate(group.channels):
                if ci == m_idx:
                    continue
                totals[ch.name] = totals.get(ch.name, 0) + 1
        return totals

    def _load_group(
        self, mdf, gi, file_path, name_total, name_seen, signals, diagnostics, cancel
    ) -> None:
        group = mdf.groups[gi]
        m_idx = self._master_index(mdf, gi)
        entries = [
            (ch.name, gi, ci)
            for ci, ch in enumerate(group.channels)
            if ci != m_idx
        ]
        if not entries:
            return
        if cancel is not None and cancel():
            raise LoadCancelled(f"load cancelled: {file_path.name}")
        asigs = mdf.select(entries, **self._SELECT_OPTIONS)

        master: np.ndarray | None = None
        master_bad = False
        master_diffs_warn: tuple[int, int] | None = None  # (非単調, 重複) を1回だけ計算
        for (base_name, _g, _c), asig in zip(entries, asigs, strict=True):
            if cancel is not None and cancel():
                raise LoadCancelled(f"load cancelled: {file_path.name}")
            idx = name_seen.get(base_name, 0)
            name_seen[base_name] = idx + 1
            signal_name = (
                f"{base_name}[{idx}]" if name_total[base_name] > 1 else base_name
            )

            if master is None and not master_bad:
                ts64 = asig.timestamps.astype(np.float64, copy=False)
                if len(ts64) > 0 and not np.all(np.isfinite(ts64)):
                    master_bad = True
                else:
                    ts64.flags.writeable = False
                    master = ts64
                    diffs = np.diff(master)
                    master_diffs_warn = (
                        int(np.sum(diffs < 0)),
                        int(np.sum(diffs == 0)),
                    )
            if master_bad:
                # 文言は現行と同一 (チャンネルごとに emit — 既存テスト互換)
                diagnostics.append(
                    Diagnostic(
                        level="error",
                        message=(
                            f"Signal '{base_name}': 非有限タイムスタンプを含むため"
                            " skip（時刻軸が破損）"  # noqa: RUF001
                        ),
                        signal_name=base_name,
                    )
                )
                continue

            samples = asig.samples
            if samples.ndim != 1 or samples.dtype.names:
                # Task 3 で展開に置換 — 本タスクでは現行どおり skip
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"Signal '{base_name}' has {samples.ndim}D samples"
                            " (expected 1D), skipped"
                        ),
                    )
                )
                continue

            try:
                values = samples.astype(np.float64, copy=False)
            except (ValueError, TypeError) as exc:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=f"Signal '{base_name}' has non-numeric values, skipped: {exc}",
                    )
                )
                continue
            values.flags.writeable = False

            n_backward, n_dup = master_diffs_warn or (0, 0)
            if n_backward or n_dup:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"Signal '{base_name}': 非単調 {n_backward} 箇所・"
                            f"重複タイムスタンプ {n_dup} 点"
                            "（表示/演算は整列ビューで補正）"  # noqa: RUF001
                        ),
                        signal_name=base_name,
                    )
                )

            signals.append(
                Signal(
                    name=signal_name,
                    timestamps=master,
                    values=values,
                    file_format="MDF4",
                    bus_type=_detect_bus_type(getattr(asig, "source", None)),
                    source_file=str(file_path.resolve()),
                    metadata=_extract_metadata(asig),
                )
            )
```

注意点（WHY）: 非単調/重複はマスタで**1回だけ**計算し、警告はチャンネルごとに emit（既存の UX/テスト互換のまま O(n)×ch → O(n)×1 に短縮）。`astype(copy=False)` は float64 なら無コピー・int（DBC raw）は必然の1コピーのみ。`writeable=False` により `Signal.__post_init__`（`signal.py:32-45`）の防御コピーが発動しないゼロコピー経路に乗る。

- [ ] **Step 5: GREEN＋既存回帰の確認**

Run: `uv run pytest tests/test_loaders.py -v` → 新2本 PASS＋既存全 PASS（非単調 LD-03・非有限・重複名・0ch・キャンセル系がそのまま緑＝契約維持の証明）。
Run: `uv run pytest -q` → demo 統合含め全緑（TurnSig はまだ conversion 無しなので demo テスト不変）。

- [ ] **Step 6: 全体ゲート → Commit**

```bash
git add src/valisync/core/loaders/mdf4_loader.py tests/test_loaders.py
git commit -m "feat(core): MDF4 読み取りを select() ベースに刷新（LD-13 enum 生存・LD-10 共有マスタ/ゼロコピー）"
```

---

## Task 3: LD-12 — 多次元/構造化チャンネルの要素展開

**Files:**
- Modify: `src/valisync/core/loaders/mdf4_loader.py`（Task 2 の skip 分岐を展開に置換）
- Modify: `src/valisync/core/models/diagnostic.py`（`level` が Literal なら "info" を追加 — 実装時にファイル位置を確認。`Diagnostic` は `valisync.core.models` から import されている）
- Test: `tests/test_loaders.py`・`tests/test_demo_mf4.py`（挙動変更の契約更新）

**Interfaces:**
- Consumes: Task 1 の `write_mdf4_2d`/`write_mdf4_structured`、Task 2 の `_load_group` ループ
- Produces: `_explode_samples(base_name, samples, diagnostics) -> list[tuple[str, np.ndarray]]`（展開不能時は [] を返し診断を emit 済み）。展開信号は共有マスタ参照・`level="info"` の展開診断

- [ ] **Step 1: 実装時確認（Task 1 Step 2 の記録を参照）**

構造化チャンネルが select 結果で「親のみ」か「親＋成分チャンネル併存」か確認（HILS Task 2 では structured 書込で成分 siblings が生成された）。**併存する場合**: 成分側が通常経路で載るため、構造化親は `level="info"`「成分チャンネルとして展開済みのため親はスキップ」で skip し、フィールド展開コードは「親のみ届くケース」用に残す。確認結果と採った分岐を report に記録し、Step 2 のテストを実態に合わせて確定（2D 展開のテストは実態に依存しない）。

- [ ] **Step 2: Write the failing tests**

```python
def test_2d_channel_explodes_into_columns(tmp_path):
    """LD-12: 2D (Nx3) が Mat[0..2] の 1D 信号群へ展開され共有マスタを参照する."""
    from tests.mdf4_helpers import write_mdf4_2d

    result = Mdf4Loader().load(write_mdf4_2d(tmp_path))
    names = {s.name for s in result.signal_group.signals}
    assert {"Mat[0]", "Mat[1]", "Mat[2]", "Clean"} <= names
    m0 = next(s for s in result.signal_group.signals if s.name == "Mat[0]")
    m2 = next(s for s in result.signal_group.signals if s.name == "Mat[2]")
    assert np.array_equal(m0.values, [0.0, 10.0, 20.0, 30.0])
    assert np.array_equal(m2.values, [2.0, 12.0, 22.0, 32.0])
    assert np.shares_memory(m0.timestamps, m2.timestamps)
    infos = [d for d in result.diagnostics if d.level == "info" and "Mat" in d.message]
    assert len(infos) == 1 and "3 本に展開" in infos[0].message
    assert not any("skipped" in d.message and "Mat" in d.message for d in result.diagnostics)


def test_structured_channel_fields_visible(tmp_path):
    """LD-12: 構造化 (x,y) がフィールド単位で見える (Pt.x / Pt.y ないし成分ch)."""
    from tests.mdf4_helpers import write_mdf4_structured

    result = Mdf4Loader().load(write_mdf4_structured(tmp_path))
    names = {s.name for s in result.signal_group.signals}
    # Step 1 の確認結果に応じて期待名を確定する (Pt.x/Pt.y または成分チャンネル名)。
    # いずれの経路でも「x の値 [1,2,3] が何らかの 1D 信号として取得できる」ことが契約。
    xs = [s for s in result.signal_group.signals if np.array_equal(s.values, [1.0, 2.0, 3.0])]
    assert xs, f"x 成分が信号として見えない: {sorted(names)}"
    assert not any(d.level == "error" for d in result.diagnostics)
```

- [ ] **Step 3: RED 確認** → `uv run pytest tests/test_loaders.py -k "explodes or structured_channel" -v` FAIL（現行は skip 警告のみ）。

- [ ] **Step 4: 実装 — 展開関数と分岐差し替え**

```python
def _explode_samples(
    base_name: str,
    samples: np.ndarray,
    diagnostics: list[Diagnostic],
) -> list[tuple[str, np.ndarray]]:
    """多次元/構造化 samples を 1D 列へ展開 (LD-12・列数上限なし=ユーザー決定).

    展開不能 (3D 超・ネスト超過) は診断を emit して [] を返す。
    """
    if samples.dtype.names:  # 構造化 dtype: フィールドごとに Name.field
        out: list[tuple[str, np.ndarray]] = []
        for field in samples.dtype.names:
            sub = samples[field]
            if sub.ndim == 1:
                out.append((f"{base_name}.{field}", sub))
            elif sub.ndim == 2:  # サブ配列フィールドは 1 段だけ展開
                out.extend(
                    (f"{base_name}.{field}[{i}]", np.ascontiguousarray(sub[:, i]))
                    for i in range(sub.shape[1])
                )
            else:
                diagnostics.append(
                    Diagnostic(
                        level="warning",
                        message=(
                            f"Signal '{base_name}.{field}' has {sub.ndim}D nested"
                            " samples, skipped"
                        ),
                    )
                )
        if out:
            diagnostics.append(
                Diagnostic(
                    level="info",
                    message=f"Signal '{base_name}': 構造化チャンネルを {len(out)} 本に展開",
                    signal_name=base_name,
                )
            )
        return out
    if samples.ndim == 2:
        n_cols = samples.shape[1]
        diagnostics.append(
            Diagnostic(
                level="info",
                message=(
                    f"Signal '{base_name}': 2D ({samples.shape[0]}x{n_cols}) を"
                    f" {n_cols} 本に展開"
                ),
                signal_name=base_name,
            )
        )
        return [
            (f"{base_name}[{i}]", np.ascontiguousarray(samples[:, i]))
            for i in range(n_cols)
        ]
    diagnostics.append(
        Diagnostic(
            level="warning",
            message=(
                f"Signal '{base_name}' has {samples.ndim}D samples"
                " (expected 1D), skipped"
            ),
        )
    )
    return []
```

`_load_group` の skip 分岐を置換（展開後の各列は既存の astype/警告/Signal 構築ループを再利用するため、`(signal_name, values_1d)` ペアのリストに正規化してから共通処理に流す — 1D 通常チャンネルは `[(signal_name, samples)]` の単一要素として同じ経路を通す）:

```python
            samples = asig.samples
            if samples.ndim != 1 or samples.dtype.names:
                pairs = [
                    (name, col)
                    for name, col in _explode_samples(signal_name, samples, diagnostics)
                ]
            else:
                pairs = [(signal_name, samples)]
            for out_name, col in pairs:
                try:
                    values = col.astype(np.float64, copy=False)
                except (ValueError, TypeError) as exc:
                    diagnostics.append(... non-numeric 警告は out_name で ...)
                    continue
                values.flags.writeable = False
                ...(非単調警告・Signal 構築は Task 2 のコードを out_name/values で)...
```

（列スライス `samples[:, i]` は非連続ビューのため `np.ascontiguousarray` で1回だけ実体化 — 展開列の必然コピー。`Diagnostic.level` に "info" が無ければ Literal へ追加し、`DiagnosticsView`/VM のフィルタが error/warning カウントベースで info を落とさないこと（All に表示）を既存テストで確認。）

- [ ] **Step 5: demo テストの契約更新（同コミット）**

`tests/test_demo_mf4.py`: (a) `test_2d_channels_yield_skip_diagnostics_in_valisync` → `test_2d_channels_explode_in_valisync` に改名し「`Radar.ObjMatrix[0]`〜`[7]` が信号リストに存在・info 展開診断2件・skip 警告 0件」へ、(b) `test_valisync_loads_smoke_profile` の「ObjMatrix 不在」assert を「`Radar.ObjMatrix[0]` 存在」へ、(c) `test_clean_multichunk_load_yields_only_2d_warnings` → 「warning 0 件（info のみ）」へ。HILS デモ spec §4.2 の「skip 警告になる（意図どおり・LD-12）」行にも「→ 第3弾で展開表示に変更（本 spec の記述は歴史）」を追記。

- [ ] **Step 6: GREEN＋全体ゲート → Commit**

```bash
git add src/valisync/core/loaders/mdf4_loader.py src/valisync/core/models/diagnostic.py tests/ docs/superpowers/specs/2026-07-04-hils-demo-mf4-generator-design.md
git commit -m "feat(core): 多次元/構造化チャンネルを要素展開して表示可能に（LD-12・上限なし・info 診断）"
```

---

## Task 4: LD-07 ローダー側 — value_labels 抽出＋generator TurnSig 復活

**Files:**
- Modify: `src/valisync/core/loaders/mdf4_loader.py`（`_extract_metadata` 拡張）
- Modify: `scripts/generate_demo_mf4.py`（TurnSig の conversion 復活）
- Test: `tests/test_loaders.py`・`tests/test_demo_mf4.py`

**Interfaces:**
- Consumes: Task 2 の刷新パス（conversion オブジェクトが asammdf Signal に残る）
- Produces: `Signal.metadata["value_labels"]: dict[float, str]`（value2text を持つチャンネルのみ・text は str に decode 済み）。Task 5/6 はこのキーだけに依存

- [ ] **Step 1: Write the failing tests**

```python
def test_value_labels_extracted_to_metadata(tmp_path):
    """LD-07: TABX 変換表が metadata['value_labels'] に構造化保持される."""
    from tests.mdf4_helpers import write_mdf4_value2text

    result = Mdf4Loader().load(write_mdf4_value2text(tmp_path))
    turn = next(s for s in result.signal_group.signals if s.name == "TurnSig")
    assert turn.metadata.get("value_labels") == {0.0: "OFF", 1.0: "LEFT", 2.0: "RIGHT"}
    clean = next(s for s in result.signal_group.signals if s.name == "Clean")
    assert "value_labels" not in clean.metadata
```

`tests/test_demo_mf4.py` の `test_turn_sig_survives_load_with_raw_enum_values` に追記:

```python
    # LD-07: 復活させた value2text がラベルとして構造化保持される
    assert turn_sig.metadata.get("value_labels") == {
        0.0: "OFF", 1.0: "LEFT", 2.0: "RIGHT"
    }
```

- [ ] **Step 2: RED 確認** → 両テスト FAIL（value_labels 不在／generator は conversion 未埋込）。

- [ ] **Step 3: 実装**

(a) `mdf4_loader.py` — 抽出関数。**重要（Task 2 レビューで実測確定）**: `select()` の戻り Signal は `conversion` が**常に None**（ignore_value2text の真偽に依らず）。抽出元は **`mdf.groups[gi].channels[ci].conversion`**（select を経ない生チャンネルメタデータ — TABX テーブルが残ることを対比確認済み）。`_load_group` は `_group_entries` の (name, gi, ci) を持っているので、そこからチャンネルオブジェクトを引いて `_extract_value_labels` に渡し、結果を `_extract_metadata` の meta に合流させる。（**ChannelConversion の val/text ペアの公開形は実装時にソース確認** — 確認した取得方法を report に記録し、失敗時は labels なしで続行）:

```python
def _extract_value_labels(conversion: Any) -> dict[float, str] | None:
    """value2text (TABX 系) の値→ラベル表を抽出。取れなければ None (生値で続行)."""
    if conversion is None:
        return None
    try:
        # Step 3 冒頭の API 確認結果で実装 (例: val_N/text_N ブロックフィールドの走査)
        labels: dict[float, str] = {}
        ...
        return labels or None
    except Exception:
        return None  # 抽出失敗はチャンネル生存を妨げない (spec §3.3)
```

`_extract_metadata` に追記:

```python
    labels = _extract_value_labels(conversion)
    if labels:
        meta["value_labels"] = labels
```

(b) `scripts/generate_demo_mf4.py` — TurnSig の SigDef を「comment ラベルのみ」から「value2text conversion 埋込＋comment 維持」へ（第2弾 Task 2 fix で見送った箇所の復活。`from_dict({"val_0": 0, "text_0": "OFF", ...})` を渡す）。HILS デモ spec §4.4 の見送り注記を「第3弾 (LD-13 解消) で復活」へ更新。

- [ ] **Step 4: GREEN＋全体ゲート → Commit**

```bash
git add src/valisync/core/loaders/mdf4_loader.py scripts/generate_demo_mf4.py tests/ docs/superpowers/specs/2026-07-04-hils-demo-mf4-generator-design.md
git commit -m "feat(core): value2text を metadata.value_labels に保持（LD-07）＋デモ TurnSig の変換埋込復活"
```

---

## Task 5: カーソル readout のラベル併記（GUI・Layer A/B）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py`（`CursorReading`/`DeltaReading` に `label` フィールド＋解決ロジック）
- Modify: `src/valisync/gui/views/cursor_readout.py`（`_fmt` 併記）
- Test: `tests/gui/test_graph_panel_cursor.py`（既存カーソルテストのファイルに追加）

**Interfaces:**
- Consumes: `Signal.metadata["value_labels"]`（Task 4）・既存 `cursor_readings()`/`delta_readings()`
- Produces: `CursorReading.label: str | None = None`（`DeltaReading.label` も同様・value_a に対するラベル）。View は `label` が非 None のとき「`2 (ACTIVE)`」形式

- [ ] **Step 1: Write the failing tests**

```python
def _enum_signal(session, key_name="f::TurnSig"):
    """value_labels 付き enum 信号を Session に直接登録するテストヘルパ."""
    ...既存テストの信号登録パターンに従い、metadata={"value_labels": {0.0: "OFF", 1.0: "LEFT", 2.0: "RIGHT"}}
    values=[0, 1, 2, 1] / timestamps=[0, 1, 2, 3] の Signal を登録...


def test_cursor_reading_label_on_exact_integer(...):
    """カーソルがサンプル上 (値=1.0 ちょうど) のとき label='LEFT' が付く."""
    vm.set_cursor(1.0)  # 補間方式は step/linear どちらでもサンプル点上は厳密値
    r = next(r for r in vm.cursor_readings() if "TurnSig" in r.name)
    assert r.value == 1.0 and r.label == "LEFT"


def test_cursor_reading_no_label_between_samples(...):
    """線形補間の中間値 (1.5) には嘘ラベルを付けない."""
    vm.interp_method = "linear"; vm.set_cursor(1.5)
    r = next(r for r in vm.cursor_readings() if "TurnSig" in r.name)
    assert r.value == 1.5 and r.label is None


def test_cursor_reading_no_label_without_metadata(...):
    """value_labels を持たない通常信号は label=None."""
```

（引数・登録ヘルパは同ファイルの既存 fixture パターンに完全に合わせる — 実装者はまず既存テストの信号登録方法を読むこと。）

- [ ] **Step 2: RED 確認**（`CursorReading` に label なし → TypeError/AttributeError）。

- [ ] **Step 3: 実装**

`graph_panel_vm.py`:

```python
@dataclass
class CursorReading:
    name: str
    color: str
    value: float | None
    in_range: bool
    label: str | None = None  # value_labels 命中時のみ (LD-07)


def _resolve_value_label(sig: Any, value: float | None) -> str | None:
    """整数に厳密一致し value_labels に載る値のみラベル化 (補間途中に嘘を付けない)."""
    if value is None or sig is None or not sig.metadata:
        return None
    labels = sig.metadata.get("value_labels")
    if not labels:
        return None
    r = round(value)
    if abs(value - r) < 1e-9:
        return labels.get(float(r))
    return None
```

`cursor_readings()` の CursorReading 構築を `label=_resolve_value_label(sig, val)` 付きに変更（sig=None 分岐は label=None のまま）。`delta_readings()`（DeltaReading 構築箇所）も `label=_resolve_value_label(sig, value_a)` を追加。

`cursor_readout.py`:

```python
def _fmt_labeled(v: float | None, label: str | None) -> str:
    base = _fmt(v)
    return f"{base} ({label})" if label else base
```

行構築の `[_fmt(r.value if r.in_range else None)]` を `[_fmt_labeled(r.value if r.in_range else None, r.label)]` に（cursor 表・delta 表の value_a 列とも）。

- [ ] **Step 4: GREEN＋View 層の表示テスト1本（rows に "1 (LEFT)" が現れる）→ 全体ゲート → Commit**

```bash
git add src/valisync/gui/viewmodels/graph_panel_vm.py src/valisync/gui/views/cursor_readout.py tests/gui/test_graph_panel_cursor.py
git commit -m "feat(gui): カーソル readout に enum ラベル併記（整数厳密一致時のみ・LD-07）"
```

---

## Task 6: ChannelBrowser ツールチップのラベル行（GUI・Layer A）

**Files:**
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py`（`SignalItem.tooltip`＋生成）
- Modify: `src/valisync/gui/adapters/qt_signal_models.py`（`ToolTipRole`）
- Test: `tests/gui/test_channel_browser_vm.py`・`tests/gui/test_channel_browser_view.py`（既存の VM/model テストファイルに追加）

**Interfaces:**
- Consumes: `Signal.metadata["value_labels"]`
- Produces: `SignalItem.tooltip: str = ""`（labels なしは空 → model は None を返しツールチップ非表示）

- [ ] **Step 1: Write the failing tests**

```python
def test_signal_item_tooltip_lists_value_labels(...):
    """value_labels 持ち信号の tooltip に『ラベル: 0=OFF, 1=LEFT, 2=RIGHT』."""
    item = next(i for i in vm.signals if i.name == "TurnSig")
    assert item.tooltip == "ラベル: 0=OFF, 1=LEFT, 2=RIGHT"


def test_signal_item_tooltip_truncates_after_8(...):
    """9 件以上は先頭 8 件＋『… (全 n 件)』."""
    # value_labels = {float(i): f"S{i}" for i in range(10)}
    assert item.tooltip.endswith("… (全 10 件)")
    assert "8=S8" not in item.tooltip.split("…")[0]


def test_model_returns_tooltip_role(...):
    """SignalTableModel が ToolTipRole で item.tooltip を返す (空なら None)."""
```

- [ ] **Step 2: RED 確認**（tooltip フィールド不在）。

- [ ] **Step 3: 実装**

`channel_browser_vm.py`:

```python
@dataclass(frozen=True)
class SignalItem:
    name: str
    unit: str
    key: str
    visible: bool = True
    tooltip: str = ""  # value_labels のラベル行 (LD-07・空=ツールチップなし)


def _labels_tooltip(metadata: dict | None) -> str:
    labels = (metadata or {}).get("value_labels")
    if not labels:
        return ""
    items = sorted(labels.items())
    head = ", ".join(f"{v:g}={t}" for v, t in items[:8])
    if len(items) > 8:
        return f"ラベル: {head}, … (全 {len(items)} 件)"
    return f"ラベル: {head}"
```

`signals` プロパティの `SignalItem(...)` に `tooltip=_labels_tooltip(sig.metadata)` を追加。

`qt_signal_models.py` の `data()` に追記:

```python
        if role == Qt.ItemDataRole.ToolTipRole:
            return item.tooltip or None
```

- [ ] **Step 4: GREEN＋全体ゲート → Commit**

```bash
git add src/valisync/gui/viewmodels/channel_browser_vm.py src/valisync/gui/adapters/qt_signal_models.py tests/gui/
git commit -m "feat(gui): ChannelBrowser ツールチップに enum ラベル行（先頭8件・LD-07）"
```

---

## Task 7: LD-10 実測（before/after）＋catalog/roadmap/docs 同期

**Files:**
- Modify: `docs/audit-findings-catalog.md`・`docs/roadmap.md`・`CLAUDE.md`
- ローカル実測のみ（コード変更なし・テスト追加なし）

- [ ] **Step 1: hils 実測（after）**

`D:/Programming/projects/valisync/demo_data/hils_demo.mf4`（2.01GB・存在しなければ `uv run python scripts/generate_demo_mf4.py --profile hils --out <同パス>` で再生成）を、前回の計測スクリプト方式（`Session.load` の wall clock＋`K32GetProcessMemoryInfo` の PeakWorkingSet）で計測。**受け入れ基準（spec §3.1）: ピーク増分 ≤ +3.0GB・ロード時間 ≤ 7.8 秒**。満たさない場合は原因をプロファイルして fix（多くは残存コピー — `np.shares_memory` で犯人特定）してから再計測。quick も同様に記録。

- [ ] **Step 2: docs 同期**

- catalog: **LD-07/LD-12/LD-13 を ✅解消（PR 番号は draft PR 作成後に確定）**・**LD-10 を ✅解消＋after 実測併記**（「実測 before 7.8s/+7.3GB → after X s/+Y GB」）・**LD-11 を「✅ 仕様と判断（2026-07-05 ユーザー決定 — 同一パス再読込は別グループとして許容。再読込操作は必要になれば別途起票）」**
- roadmap: core-loaders-hardening の残りを「第2弾（LD-01/02・開く経路）のみ」に更新
- CLAUDE.md 57 行付近の第3弾記述を「第3弾（LD-07/10/12/13 解消・LD-11 仕様判断）実装済み」へ

- [ ] **Step 3: 全体ゲート → Commit**

```bash
git add docs/audit-findings-catalog.md docs/roadmap.md CLAUDE.md
git commit -m "docs: 第3弾の catalog/roadmap 同期（LD-07/10/12/13 解消・LD-11 仕様判断・LD-10 実測 after）"
```

---

## Self-Review

**1. Spec coverage:** §3.1 読み取りパス→T2（受け入れ基準の shares_memory=T2 テスト・+3.0GB/時間=T7）✓、§3.2 展開→T3（上限なし・info 診断・共有マスタ・demo テスト契約更新・構造化の実装時分岐）✓、§3.3 value_labels→T4（抽出）＋T5（readout 整数厳密一致）＋T6（tooltip 8件切詰め）✓、§3.4 generator 復活→T4 ✓、§3.5 LD-11 記録→T7 ✓、§4 検証（既存回帰網=T2 Step5・GUI Layer 判定=Global Constraints・hils ローカル実測=T7）✓、§5 キャンセル粒度→T2 実装に per-channel チェック維持（select 一括読みの粗さは §5 どおり許容・応答性問題が出たら T7 実測時に検出）✓。
**2. Placeholder scan:** `_extract_value_labels` の本体と `_master_index` は「実装時 asammdf ソース確認」を明示した意図的な確認付き骨子（HILS Task 2 で確立した流儀・確認手順と失敗時挙動を明記済み）。Task 5 Step 1 のテストは既存 fixture パターン準拠を明示（該当ファイルの既存テストが一次情報）。他に TBD なし。
**3. Type consistency:** `_explode_samples(base_name, samples, diagnostics) -> list[tuple[str, np.ndarray]]`（T3 定義=T3 使用）・`CursorReading.label`/`_resolve_value_label`（T5 内で完結）・`SignalItem.tooltip`（T6 内で完結）・`metadata["value_labels"]: dict[float, str]`（T4 産出=T5/T6 消費）— 一貫。
