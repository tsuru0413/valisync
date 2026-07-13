# FU-22 (A) active-file 同一キーガード 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `AppViewModel.set_active_file` に同一キーガードを入れ、ChannelBrowser の 264k リビルドの無条件 same-key re-fire (prod 実測 ~5,230ms) を根絶する。

**Architecture:** source 側 1 行ガード (`if key == self._active_file_key: return`)。副作用ゼロは Phase 1 実証済み ("active_file" 購読者は cbvm リビルド〔消したい対象〕と main_window タイトル〔冪等〕のみ)。

**Tech Stack:** PySide6/pyqtgraph, MVVM (Observable), pytest-qt。

## Global Constraints

- core (session.py / Signal / VM) は Qt 非依存を維持。`AppViewModel` は既存の Observable のまま。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過。
- Python コメント/文字列に全角約物 `（）：＋＝` 禁止 (RUF001/002/003)。ASCII `()`, `:`, `+`, `=` を使う (矢印 `->`/`→` と `・` は可)。
- gui-test-plan 分類: **VM 純ロジック -> Layer A/B・realgui 不要**。honest observable = `SignalTableModel.modelReset` 発火回数 (ユーザーの 5s フリーズ源)。prod 5,230ms->2.8ms は Phase 1 repro で実測済み (spec に記録)。
- スコープは (A) のみ。(B) view 仮想化は本プラン対象外 (別サブスペック)。

---

### Task 1: set_active_file 同一キーガード (Layer A + Layer B honest-RED)

**Files:**
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py:120-123` (`set_active_file`)
- Test: `tests/gui/test_app_viewmodel.py` (Layer A), `tests/gui/test_qt_signal_models.py` (Layer B)

**Interfaces:**
- Consumes: 既存 `AppViewModel._active_file_key`, `AppViewModel._notify`, `AppViewModel.subscribe`。`SignalTableModel(vm)` は `vm "signals"` 購読で `beginResetModel`/`endResetModel` -> `modelReset` シグナル発火。`app_vm.session.group_signals = lambda key: [...]` 注入パターン (既存)。
- Produces: `set_active_file` は同一キーで no-op (state 不変・notify 無し)、genuine 変更で従来どおり notify。

- [ ] **Step 1: Layer A の失敗テストを書く**

`tests/gui/test_app_viewmodel.py` に追加:

```python
def test_set_active_file_same_key_is_noop() -> None:
    """FU-22: 同一キー再選択は state 不変・'active_file' notify 無し (264k リビルド重複の根絶)."""
    vm = AppViewModel()
    vm.set_active_file("k")  # None -> k (genuine change)
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    vm.set_active_file("k")  # same key -> guarded no-op

    assert notifications == []  # no 'active_file' re-fire
    assert vm.active_file_key == "k"  # state unchanged


def test_set_active_file_genuine_change_still_notifies() -> None:
    """FU-22 ガードが genuine 変更 (None->key, key->other, key->None) を塞がない無回帰."""
    vm = AppViewModel()
    notifications: list[str] = []
    vm.subscribe(notifications.append)

    vm.set_active_file("a")  # None -> a
    vm.set_active_file("b")  # a -> b
    vm.set_active_file(None)  # b -> None

    assert notifications.count("active_file") == 3
```

- [ ] **Step 2: Layer B の失敗テストを書く**

`tests/gui/test_qt_signal_models.py` に追加 (import は既存の `QModelIndex`, `Signal`, `AppViewModel`, `ChannelBrowserVM`, `SignalTableModel`, `numpy` を使う):

```python
def test_same_key_activation_does_not_rebuild_model(qtbot: QtBot) -> None:
    """FU-22: 同一キー再 activate は model reset を起こさない (5s フリーズ源の除去).

    honest observable = SignalTableModel.modelReset の発火回数。ガードを外すと
    同一キー再 activate で reset が再発火し RED (sabotage 検証)。
    """
    import numpy as np

    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    model = SignalTableModel(vm)

    sig = Signal(
        name="k::a",
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={},
    )
    app_vm.session.group_signals = lambda key: [sig]

    resets: list[int] = []
    model.modelReset.connect(lambda: resets.append(1))

    app_vm.set_active_file("k")  # genuine activate -> 1 rebuild
    assert len(resets) == 1
    assert model.rowCount(QModelIndex()) == 1

    app_vm.set_active_file("k")  # same key -> guarded -> NO rebuild
    assert len(resets) == 1  # unchanged (no second reset)


def test_genuine_switch_rebuilds_model(qtbot: QtBot) -> None:
    """FU-22 ガード下でも別キーへの切替は model reset される (無回帰)."""
    import numpy as np

    app_vm = AppViewModel()
    vm = ChannelBrowserVM(app_vm)
    model = SignalTableModel(vm)

    def _sig(name: str) -> Signal:
        return Signal(
            name=name,
            timestamps=np.array([0.0]),
            values=np.array([1.0]),
            file_format="MDF4",
            bus_type="",
            source_file="",
            metadata={},
        )

    app_vm.session.group_signals = lambda key: [_sig(f"{key}::a")]

    resets: list[int] = []
    model.modelReset.connect(lambda: resets.append(1))

    app_vm.set_active_file("ka")  # reset 1
    app_vm.set_active_file("kb")  # reset 2 (genuine switch)
    assert len(resets) == 2
```

- [ ] **Step 3: テストを走らせて RED を確認**

Run: `uv run pytest tests/gui/test_app_viewmodel.py::test_set_active_file_same_key_is_noop tests/gui/test_qt_signal_models.py::test_same_key_activation_does_not_rebuild_model -v`
Expected: 両方 FAIL (現状は同一キーでも notify -> `notifications == ["active_file"]` で assert 失敗、reset が 2 回で assert 失敗)。genuine テスト2件は現状でも PASS (無回帰ベースライン)。

- [ ] **Step 4: ガードを実装**

`src/valisync/gui/viewmodels/app_viewmodel.py` の `set_active_file` を:

```python
    def set_active_file(self, key: str | None) -> None:
        """Set the active file and notify subscribers ('active_file')."""
        if key == self._active_file_key:
            # FU-22: 同一キー再選択は state 不変。無条件 notify は ChannelBrowser の
            # 264k 行モデルを重複リビルドする (prod 実測 ~5s)。同一キーは no-op で根絶。
            return
        self._active_file_key = key
        self._notify("active_file")
```

- [ ] **Step 5: テストを走らせて GREEN を確認**

Run: `uv run pytest tests/gui/test_app_viewmodel.py tests/gui/test_qt_signal_models.py tests/gui/test_channel_browser_vm.py -v`
Expected: 新規4件含め全 PASS (same-key no-op / genuine notify / same-key no-rebuild / genuine switch rebuild)。既存の channel-browser/qt-model テストも無回帰。

- [ ] **Step 6: 品質ゲート**

Run: `uv run pytest`; `uv run ruff check`; `uv run ruff format --check`; `uv run mypy src/`
Expected: 全通過。

- [ ] **Step 7: コミット**

```bash
git add src/valisync/gui/viewmodels/app_viewmodel.py tests/gui/test_app_viewmodel.py tests/gui/test_qt_signal_models.py
git commit -m "fix(gui): FU-22(A) set_active_file 同一キーガードで ChannelBrowser 264k 重複リビルドを根絶"
```

---

### Task 2: catalog 反映 (FU-22 (A) ✅ / (B) 別サブスペック)

**Files:**
- Modify: `docs/audit-findings-catalog.md` (FU-22 行 + Tier 3 ナラティブ)

- [ ] **Step 1: FU-22 行を (A) 解消・(B) 分離へ更新**

FU-22 行のステータス列を `✅ (A) 解消 / (B) 別サブスペック (2026-07-13・feature/fu22-channel-rebuild-perf)` にし、本文に Phase 1 実測の内訳 ((A) 5,230ms->2.8ms・(B) の支配コストは QTreeView 264k reset ~2,750ms + proxy ~1,550ms・VM SignalItem は 484ms のみ・deferred 3ms) と、(A)=source ガードの副作用ゼロ根拠、(B)=view 仮想化の別サブスペック分離 (ユーザー合意) を記録。file:line は `gui/viewmodels/app_viewmodel.py:120` (guard)。

- [ ] **Step 2: Tier 3 ナラティブに反映**

Tier 3 行の「新規 FU-22 (優先度はユーザー判断待ち)」を「FU-22 (A) ✅解消・(B) view 仮想化は別サブスペックへ」に更新。

- [ ] **Step 3: コミット**

```bash
git add docs/audit-findings-catalog.md
git commit -m "docs(fu22): (A) 同一キーガード解消を catalog 反映・(B) view 仮想化を別サブスペックへ"
```

---

## Self-Review

- **Spec coverage**: (A) ガード (spec §設計) = Task 1。catalog 反映 (spec §catalog) = Task 2。(B) は spec で明示除外。ギャップなし。
- **Placeholder scan**: 全 step に実コード/実コマンド。プレースホルダなし。
- **Type consistency**: `set_active_file(key: str | None)` シグネチャ不変。`modelReset` は PySide6 QAbstractItemModel の標準シグナル。`group_signals` 注入は既存テストパターン。
