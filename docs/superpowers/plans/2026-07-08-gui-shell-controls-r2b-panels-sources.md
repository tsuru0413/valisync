# gui-shell-controls 増分2b（パネル可視化・ファイル削除確認・データソース一覧）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存 VM ロジック（`add_panel`/`remove_panel`・`unload`・`add/remove_data_source`）へ**可視アフォーダンスと確認フロー**を配線し、SH-06（パネル追加/削除の可視ボタン）・SH-08（ファイル削除の確認）・SH-10/15（DataExplorer 登録ソース一覧＋選択作用）を解消する。

**Architecture:** 増分2a と同様、ドメインロジックは Phase 2 で実装済み。本増分は View 層3ファイル（`graph_panel_view.py`・`file_browser_view.py`・`data_explorer_view.py`）に、既存シグナル/メソッドへ配線する可視ボタン・確認ダイアログ・登録ソースリストを足す。新規 VM ロジックは無い。

**Tech Stack:** Python 3.12+ / PySide6 (Qt6) / pyqtgraph / pytest + pytest-qt。MVVM（View=Qt / ViewModel=純 Python・不変）。

## Global Constraints

- 設計 spec: [2026-07-08-gui-shell-controls-r2-tabs-panels-sources-design.md](../specs/2026-07-08-gui-shell-controls-r2-tabs-panels-sources-design.md) §4（増分2b）。親 spec §5。
- **MVVM 不変**: ViewModel（`graph_panel_vm.py`・`file_browser_vm.py`・`app_viewmodel.py`）は変更しない。既存メソッド/シグナルへ配線するのみ:
  - `GraphPanelView.add_panel_requested`/`remove_panel_requested`（Signal）・`set_removable(bool)`（既存: menu をグレーアウト）。
  - `FileBrowserVM.unload(index)`・`files`（プロパティ）。
  - `AppViewModel.add_data_source(path)`/`remove_data_source(path)`→ `_notify("data_sources")`・`inspect()["data_sources"]`。
- **右クリックメニューは併存**（冗長アフォーダンス）。可視ボタンを足しても既存メニュー経路を壊さない。
- **全角約物のみ禁止**（コード内・コメント/docstring）: `（）＋−` 等（ruff RUF002/003 が検出）を使わず ASCII `()` `+` `-`。**日本語カナ漢字・`。`・`・`・em dash `—` はコードベース標準で可（ruff 通過）**。日本語 UI 文字列リテラル（tooltip・ラベル・メッセージ）は可（RUF001 が当該行で出たら `# noqa: RUF001` を付す）。
- 品質ゲート（コミット前に全通過）: `uv run pytest` / `uv run ruff check`（exit 0・`| tail` 禁止）/ `uv run ruff format --check` / `uv run mypy src/`。
- GUI テストレイヤー: Layer A/B 必須（headless）＋新入力経路ごとに Layer C スケルトン。**モーダル（QMessageBox・QFileDialog）は注入フック（`_confirm_fn` 等）でテスト可能にする**（既存の `_dir_chooser`/`_save_path_provider` 慣習）。

---

## File Structure

| ファイル | 責務 | 種別 |
|---|---|---|
| `src/valisync/gui/views/graph_panel_view.py` | パネル chrome 行に「+」/「×」QToolButton・`set_removable` を button 連動へ拡張 | 変更 |
| `src/valisync/gui/views/file_browser_view.py` | 削除前 `QMessageBox.question` 確認（注入フック）・ヘッダに「閉じる」ボタン・メニューも確認経由 | 変更 |
| `src/valisync/gui/views/data_explorer_view.py` | 登録ソース `QListWidget`（splitter で tree と並置）・選択で root 切替・Remove は選択作用＋statusBar フィードバック | 変更 |
| `tests/gui/test_panel_chrome_buttons.py` | SH-06 Layer A/B | 新規 |
| `tests/gui/test_file_browser_delete_confirm.py` | SH-08 Layer A/B | 新規 |
| `tests/gui/test_data_explorer_source_list.py` | SH-10/15 Layer A/B | 新規 |
| `tests/realgui/test_panel_source_flow.py` | Layer C（パネルボタン・削除確認・ソース選択+Remove） | 新規 |
| `docs/audit-findings-catalog.md` / `docs/roadmap.md` | SH-06/08/10/15 解消反映 | 変更 |

**依存順**: Task 1（SH-06）・Task 2（SH-08）・Task 3（SH-10/15）は別ファイルで独立。Task 4（realgui）・Task 5（docs）は最後。

---

## Task 1: SH-06 パネル追加/削除の可視ボタン

**Files:**
- Modify: `src/valisync/gui/views/graph_panel_view.py`
- Test: `tests/gui/test_panel_chrome_buttons.py`

**Interfaces:**
- Consumes: 既存 `add_panel_requested`/`remove_panel_requested`（Signal・graph_panel_view.py:615-616）・`self._removable`（:653・初期 True）・`set_removable(bool)`（:1816）。
- Produces: chrome 行の `add_panel_button`（objectName・clicked→`add_panel_requested.emit()`）・`self._remove_panel_button`（objectName `remove_panel_button`・clicked→`remove_panel_requested.emit()`・`set_removable` で enable 連動）。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_panel_chrome_buttons.py
from __future__ import annotations

from PySide6.QtWidgets import QToolButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.session import Session
from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM


def _make_panel(qtbot: QtBot):  # type: ignore[no-untyped-def]
    from valisync.gui.views.graph_panel_view import GraphPanelView

    view = GraphPanelView(GraphPanelVM(Session()))
    qtbot.addWidget(view)
    return view


def _button(view: object, name: str) -> QToolButton:
    btn = view.findChild(QToolButton, name)  # type: ignore[attr-defined]
    assert isinstance(btn, QToolButton), f"{name} not found"
    return btn


def test_add_panel_button_emits_signal(qtbot: QtBot) -> None:
    view = _make_panel(qtbot)
    fired: list[bool] = []
    view.add_panel_requested.connect(lambda: fired.append(True))
    _button(view, "add_panel_button").click()
    assert fired == [True]


def test_remove_panel_button_emits_signal(qtbot: QtBot) -> None:
    view = _make_panel(qtbot)
    fired: list[bool] = []
    view.remove_panel_requested.connect(lambda: fired.append(True))
    _button(view, "remove_panel_button").click()
    assert fired == [True]


def test_set_removable_toggles_remove_button(qtbot: QtBot) -> None:
    view = _make_panel(qtbot)
    remove_btn = _button(view, "remove_panel_button")
    assert remove_btn.isEnabled()  # default removable
    view.set_removable(False)
    assert not remove_btn.isEnabled()
    view.set_removable(True)
    assert remove_btn.isEnabled()
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_panel_chrome_buttons.py -q`
Expected: FAIL（ボタン未生成・findChild None）

- [ ] **Step 3: 実装**

import に追加（既存 `from PySide6.QtWidgets import (...)` へ統合）:
```python
    QHBoxLayout,
    QToolButton,
```

`__init__` の末尾レイアウト（現状 `layout = QVBoxLayout(self)` / `addWidget(self.plot_widget)`・graph_panel_view.py:701-703）を、chrome 行を上に挿入する形へ変更:
```python
        # SH-06: パネル追加/削除の可視アフォーダンス (右クリックメニューと併存)。
        chrome = QHBoxLayout()
        chrome.setContentsMargins(2, 2, 2, 0)
        chrome.addStretch(1)
        add_panel_btn = QToolButton(self)
        add_panel_btn.setObjectName("add_panel_button")
        add_panel_btn.setText("+")
        add_panel_btn.setToolTip("パネルを追加")
        add_panel_btn.clicked.connect(lambda: self.add_panel_requested.emit())
        chrome.addWidget(add_panel_btn)
        self._remove_panel_button = QToolButton(self)
        self._remove_panel_button.setObjectName("remove_panel_button")
        self._remove_panel_button.setText("×")
        self._remove_panel_button.setToolTip("パネルを削除")
        self._remove_panel_button.setEnabled(self._removable)
        self._remove_panel_button.clicked.connect(
            lambda: self.remove_panel_requested.emit()
        )
        chrome.addWidget(self._remove_panel_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(chrome)
        layout.addWidget(self.plot_widget)
```
注: 「×」で `ruff check` が RUF001 を出したら当該行に `# noqa: RUF001` を付す（UI 文字列リテラルは許容）。

`set_removable`（:1816）を button 連動へ拡張:
```python
    def set_removable(self, removable: bool) -> None:
        """Set whether Remove Panel is available (R6.6) — menu action and visible button."""
        self._removable = removable
        self._remove_panel_button.setEnabled(removable)
```

- [ ] **Step 4: パス確認＋既存無回帰**

```bash
uv run pytest tests/gui/test_panel_chrome_buttons.py -q
uv run pytest tests/gui/test_graph_panel_cursor.py tests/gui/test_context_menus.py -q   # chrome 挿入で panel 幾何が壊れていないか
```
Expected: 新テスト PASS＋既存 GraphPanel テスト無回帰（chrome は plot_widget の内部座標系に影響しない）。

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/graph_panel_view.py tests/gui/test_panel_chrome_buttons.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/graph_panel_view.py tests/gui/test_panel_chrome_buttons.py
uv run mypy src/valisync/gui/views/graph_panel_view.py
git add src/valisync/gui/views/graph_panel_view.py tests/gui/test_panel_chrome_buttons.py
git commit -m "feat(gui): パネル追加/削除の可視ボタン — chrome 行に + / ×（SH-06）"
```

---

## Task 2: SH-08 ファイル削除の確認

**Files:**
- Modify: `src/valisync/gui/views/file_browser_view.py`
- Test: `tests/gui/test_file_browser_delete_confirm.py`

**Interfaces:**
- Consumes: `FileBrowserVM.unload(index)`（:59）・`self._vm.files`（プロパティ・:47）・既存 `build_context_menu(row)`（:97）・ヘッダ `QHBoxLayout`（:68-70）。
- Produces: 注入フック `self._confirm_fn: Callable[[str], bool]`（既定 `_default_confirm`=`QMessageBox.question`）・`_confirm_and_unload(row)`・ヘッダの `close_button`（objectName `file_browser_close`）→ 選択行を確認付き unload。メニュー「Remove File」も `_confirm_and_unload` 経由。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_file_browser_delete_confirm.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM


def _make_browser_with_file(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    from valisync.gui.views.file_browser_view import FileBrowserView

    app_vm = AppViewModel()
    vm = FileBrowserVM(app_vm)
    view = FileBrowserView(vm)
    qtbot.addWidget(view)
    return app_vm, vm, view


def test_confirm_yes_unloads(qtbot: QtBot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _app, vm, view = _make_browser_with_file(qtbot)
    calls: list[int] = []
    monkeypatch.setattr(vm, "unload", lambda i: calls.append(i))
    view._confirm_fn = lambda _name: True  # stub the modal
    view._confirm_and_unload(0)
    assert calls == [0]


def test_confirm_no_does_not_unload(qtbot: QtBot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _app, vm, view = _make_browser_with_file(qtbot)
    calls: list[int] = []
    monkeypatch.setattr(vm, "unload", lambda i: calls.append(i))
    view._confirm_fn = lambda _name: False
    view._confirm_and_unload(0)
    assert calls == []


def test_menu_remove_routes_through_confirm(qtbot: QtBot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _app, vm, view = _make_browser_with_file(qtbot)
    seen: list[str] = []
    view._confirm_fn = lambda name: (seen.append(name) or False)  # decline
    calls: list[int] = []
    monkeypatch.setattr(vm, "unload", lambda i: calls.append(i))
    # simulate FileBrowserVM having one file so files[0] is valid
    monkeypatch.setattr(type(vm), "files", property(lambda _self: ["log.mf4"]))
    menu = view.build_context_menu(0)
    menu.actions()[0].trigger()  # "Remove File"
    assert seen == ["log.mf4"] and calls == []  # confirm consulted, declined


def test_header_has_close_button(qtbot: QtBot) -> None:
    _app, _vm, view = _make_browser_with_file(qtbot)
    btn = view.findChild(QPushButton, "file_browser_close")
    assert isinstance(btn, QPushButton)
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_file_browser_delete_confirm.py -q`
Expected: FAIL（`_confirm_fn`/`_confirm_and_unload`/`file_browser_close` 未実装）

- [ ] **Step 3: 実装**

import に追加（既存 QtWidgets import へ `QMessageBox`・typing へ `Callable`）:
```python
from collections.abc import Callable
...
    QMessageBox,
```

`__init__` シグネチャに注入フックを追加（既存引数の後ろ・キーワード専用）:
```python
    def __init__(
        self,
        vm: FileBrowserVM,
        *,
        confirm_fn: Callable[[str], bool] | None = None,
    ) -> None:
```
（既存の `__init__` 本体先頭で）:
```python
        self._confirm_fn: Callable[[str], bool] = confirm_fn or self._default_confirm
```
ヘッダ（現状 open_button のみ・:64-70）へ「閉じる」ボタンを追加（`header.addStretch(1)` の後 or 前は任意・open の右）:
```python
        self.close_button = QPushButton("閉じる")
        self.close_button.setObjectName("file_browser_close")
        self.close_button.setToolTip("選択中のファイルを閉じる")
        self.close_button.clicked.connect(self._close_selected)
        header.addWidget(self.close_button)
```

メソッド追加:
```python
    def _default_confirm(self, filename: str) -> bool:
        reply = QMessageBox.question(
            self,
            "ファイルを閉じる",
            f"{filename} を閉じますか? プロット中の信号も消えます。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _confirm_and_unload(self, row: int) -> None:
        files = self._vm.files
        if row < 0 or row >= len(files):
            return
        if self._confirm_fn(files[row]):
            self._vm.unload(row)

    def _close_selected(self) -> None:
        index = self.list_view.currentIndex()
        if index.isValid():
            self._confirm_and_unload(index.row())
```

`build_context_menu`（:97-101）を確認経由へ:
```python
    def build_context_menu(self, row: int) -> QMenu:
        """Single-action menu ('Remove File') — confirms before unloading list *row*."""
        menu = QMenu(self)
        menu.addAction("Remove File").triggered.connect(
            lambda *_: self._confirm_and_unload(row)
        )
        return menu
```

- [ ] **Step 4: パス確認＋既存無回帰**

```bash
uv run pytest tests/gui/test_file_browser_delete_confirm.py tests/gui/test_file_browser_view.py -q
```
Expected: 新テスト PASS。既存 file_browser テストが直 `unload` 前提なら確認経由で無回帰（既存テストがメニュー経路で unload を検証している場合、confirm がデフォルト No で unload されず落ちる可能性 → その場合は既存テストが `_confirm_fn` を stub していないため、**既存テストの意図が「メニュー→unload」なら本 Task で確認を挟む仕様変更**。既存テストが落ちたら、そのテストに `view._confirm_fn = lambda _n: True` を足して意図を保つ（確認フローの追加は SH-08 の要件）。落ちた既存テスト名と修正を report に明記）。

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/file_browser_view.py tests/gui/test_file_browser_delete_confirm.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/file_browser_view.py tests/gui/test_file_browser_delete_confirm.py
uv run mypy src/valisync/gui/views/file_browser_view.py
git add src/valisync/gui/views/file_browser_view.py tests/gui/test_file_browser_delete_confirm.py
git commit -m "feat(gui): ファイル削除に確認ダイアログ＋可視の閉じる導線（SH-08）"
```

---

## Task 3: SH-10/15 DataExplorer 登録ソース一覧

**Files:**
- Modify: `src/valisync/gui/views/data_explorer_view.py`
- Test: `tests/gui/test_data_explorer_source_list.py`

**Interfaces:**
- Consumes: `AppViewModel.add_data_source`/`remove_data_source`→`_notify("data_sources")`・`self.sources()`（:113）・`self.remove_source(path)`（:123）・`self._root_at(folder)`（:137）・`self.tree`。
- Produces: `self.source_list: QListWidget`（objectName `data_source_list`・splitter で tree と並置）・`_refresh_source_list()`・`_on_source_row_changed(row)`→root 切替・`_on_remove_source_clicked` を選択作用＋statusBar フィードバックへ改修・`_on_app_change("data_sources")`→refresh。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_data_explorer_source_list.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QListWidget
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel


def _make_explorer(qtbot: QtBot, tmp_path: Path):  # type: ignore[no-untyped-def]
    from valisync.gui.views.data_explorer_view import DataExplorerView

    view = DataExplorerView(AppViewModel(), sources_file=None)
    qtbot.addWidget(view)
    return view


def test_source_list_exists(qtbot: QtBot, tmp_path: Path) -> None:
    view = _make_explorer(qtbot, tmp_path)
    assert isinstance(view.source_list, QListWidget)
    assert view.source_list.objectName() == "data_source_list"


def test_add_source_appears_in_list(qtbot: QtBot, tmp_path: Path) -> None:
    view = _make_explorer(qtbot, tmp_path)
    d = tmp_path / "src_a"
    d.mkdir()
    view.add_source(d)
    labels = [view.source_list.item(i).text() for i in range(view.source_list.count())]
    assert str(d) in labels


def test_selecting_source_roots_tree(qtbot: QtBot, tmp_path: Path) -> None:
    view = _make_explorer(qtbot, tmp_path)
    d = tmp_path / "src_b"
    d.mkdir()
    view.add_source(d)
    row = [
        i for i in range(view.source_list.count())
        if view.source_list.item(i).text() == str(d)
    ][0]
    view.source_list.setCurrentRow(row)
    rooted = Path(view.fs_model.filePath(view.tree.rootIndex()))
    assert rooted == d


def test_remove_acts_on_selected_source(qtbot: QtBot, tmp_path: Path) -> None:
    view = _make_explorer(qtbot, tmp_path)
    d = tmp_path / "src_c"
    d.mkdir()
    view.add_source(d)
    view.source_list.setCurrentRow(0)
    view._on_remove_source_clicked()
    assert str(d) not in view.sources()


def test_remove_without_selection_gives_feedback(qtbot: QtBot, tmp_path: Path) -> None:
    view = _make_explorer(qtbot, tmp_path)
    view.source_list.setCurrentRow(-1)  # no selection
    view._on_remove_source_clicked()  # must not raise; shows a status message
    assert view.statusBar().currentMessage() != ""
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_data_explorer_source_list.py -q`
Expected: FAIL（`source_list` 未実装）

- [ ] **Step 3: 実装**

import に追加（既存 QtWidgets import へ）:
```python
    QListWidget,
    QSplitter,
```

`__init__` の tree 構築後・`setCentralWidget(self.tree)`（:79）を splitter へ置換。tree 生成はそのまま残し、central を splitter に:
```python
        # SH-10: 登録データソースの可視リスト (tree の左に並置)。
        self.source_list = QListWidget(self)
        self.source_list.setObjectName("data_source_list")
        self.source_list.currentRowChanged.connect(self._on_source_row_changed)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.source_list)
        splitter.addWidget(self.tree)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)  # replaces setCentralWidget(self.tree)
```
`add_data_source` 通知で list を更新するため、**restore ループより前**に購読を張る（restore の add_data_source が notify → refresh される）:
```python
        # data_sources 変更でリストを再投影 (restore の add もこれで反映)。
        self._app_unsub = self._app_vm.subscribe(self._on_app_change)
        self.destroyed.connect(lambda *_: self._app_unsub())
```
（この2ブロックは既存 restore ブロック `if self._sources_file is not None:`（:90-93）より前に置く。）

メソッド追加/改修:
```python
    def _on_app_change(self, change: str) -> None:
        if change == "data_sources":
            self._refresh_source_list()

    def _refresh_source_list(self) -> None:
        current = self.source_list.currentItem()
        keep = current.text() if current is not None else None
        self.source_list.blockSignals(True)  # rebuild without spurious root switches
        self.source_list.clear()
        for path in self.sources():
            self.source_list.addItem(path)
        if keep is not None:
            matches = self.source_list.findItems(keep, Qt.MatchFlag.MatchExactly)
            if matches:
                self.source_list.setCurrentItem(matches[0])
        self.source_list.blockSignals(False)

    def _on_source_row_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self.source_list.item(row)
        if item is not None:
            self._root_at(Path(item.text()))
```
既存 `_on_remove_source_clicked`（:105-109）を選択作用＋フィードバックへ差し替え:
```python
    def _on_remove_source_clicked(self, *_: object) -> None:
        """Remove the source selected in the list (SH-15: not the invisible tree root)."""
        item = self.source_list.currentItem()
        if item is None:
            self.statusBar().showMessage(
                "削除するデータソースをリストから選択してください", 4000
            )
            return
        self.remove_source(Path(item.text()))
```

- [ ] **Step 4: パス確認＋既存無回帰**

```bash
uv run pytest tests/gui/test_data_explorer_source_list.py tests/gui/test_data_explorer_view.py -q
```
Expected: 新テスト PASS。既存 DataExplorer テストは `self.tree`（splitter 内に移動しても参照は有効）・`sources()`・`remove_source` を使うので無回帰。`centralWidget() is self.tree` を仮定する既存テストがあれば splitter 化で落ちる → その名と、`self.tree` は splitter の子として健在である旨を report に記し、テストを `view.tree` 直接参照へ更新（構造変更に伴う妥当な追随）。

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/data_explorer_view.py tests/gui/test_data_explorer_source_list.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/data_explorer_view.py tests/gui/test_data_explorer_source_list.py
uv run mypy src/valisync/gui/views/data_explorer_view.py
git add src/valisync/gui/views/data_explorer_view.py tests/gui/test_data_explorer_source_list.py
git commit -m "feat(gui): DataExplorer 登録ソース一覧＋選択作用の Remove（SH-10/15）"
```

---

## Task 4: Layer C realgui スケルトン

**Files:**
- Create: `tests/realgui/test_panel_source_flow.py`

**Interfaces:**
- Consumes: `GraphPanelView`（add/remove ボタン）・`FileBrowserView`（閉じるボタン＋確認）・`DataExplorerView`（source_list 選択＋Remove）。
- 目的: headless が迂回する実ボタン/実選択操作を実 OS 入力で検証（honest gate・`skip_unless_real_display` で CI skip）。

- [ ] **Step 1: スケルトンを書く**

```python
# tests/realgui/test_panel_source_flow.py
"""Layer C: パネル/ファイル/ソースの可視アフォーダンス実 OS 入力 (SH-06/08/10/15)。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_panel_add_button_click_emits(qtbot: QtBot) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QToolButton

    from valisync.core.session import Session
    from valisync.gui.viewmodels.graph_panel_vm import GraphPanelVM
    from valisync.gui.views.graph_panel_view import GraphPanelView

    view = GraphPanelView(GraphPanelVM(Session()))
    qtbot.addWidget(view)
    view.resize(500, 400)
    view.show()
    qtbot.waitExposed(view)
    fired: list[bool] = []
    view.add_panel_requested.connect(lambda: fired.append(True))
    btn = view.findChild(QToolButton, "add_panel_button")
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert fired == [True], "パネル追加ボタンの実クリックでシグナルが飛ばない"


def test_data_source_list_select_roots_tree(qtbot: QtBot, tmp_path: Path) -> None:
    skip_unless_real_display()
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.data_explorer_view import DataExplorerView

    view = DataExplorerView(AppViewModel(), sources_file=None)
    qtbot.addWidget(view)
    view.resize(700, 400)
    view.show()
    qtbot.waitExposed(view)
    d = tmp_path / "src"
    d.mkdir()
    view.add_source(d)
    view.source_list.setCurrentRow(0)
    QApplication.processEvents()
    rooted = Path(view.fs_model.filePath(view.tree.rootIndex()))
    assert rooted == d, "ソースリスト選択で tree の root が切り替わらない"
```

- [ ] **Step 2: 収集確認**

Run: `uv run pytest tests/realgui/test_panel_source_flow.py --collect-only -q`
Expected: 2 tests collected（`--realgui` 無しでは skip）

- [ ] **Step 3: ゲート＋コミット**

```bash
uv run ruff check tests/realgui/test_panel_source_flow.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format tests/realgui/test_panel_source_flow.py
git add tests/realgui/test_panel_source_flow.py
git commit -m "test(realgui): パネル/ソース可視アフォーダンスの honest gate スケルトン（SH-06/10/15）"
```

---

## Task 5: docs 反映（catalog / roadmap）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（SH-06/08/10/15 解消）
- Modify: `docs/roadmap.md`（gui-shell-controls に増分2b＝完了）

- [ ] **Step 1: catalog の SH-06/08/10/15 に解消注記**

既存の ✅解消 行の書式（増分2a の SH-02/04/13・PC 系）に倣い、各行の優先度を `✅解消` にし本文先頭へ太字注記（元本文は残す）:
- SH-06: `**✅解消（2026-07-08・増分2b）: パネル chrome 行に「+」/「×」QToolButton を追加し add_panel_requested/remove_panel_requested に配線。set_removable が「×」を連動 disable。右クリックメニュー併存。**`
- SH-08: `**✅解消（2026-07-08・増分2b）: 削除前に QMessageBox.question 確認（注入フック _confirm_fn）＋ヘッダに「閉じる」ボタン。メニュー「Remove File」も確認経由。**`
- SH-10: `**✅解消（2026-07-08・増分2b）: DataExplorer に登録ソース QListWidget（splitter で tree と並置）。選択で tree root 切替。**`
- SH-15: `**✅解消（2026-07-08・増分2b）: Remove Source が不可視ルートでなく選択リスト項目に作用。未選択は statusBar フィードバック。**`

- [ ] **Step 2: roadmap 更新**

gui-shell-controls 行に「増分2b（パネル/削除確認/ソース一覧: SH-06/08/10/15）実装済み」を追記、SH-06/08/10/15 を ✅解消 に。増分2完了（2a＋2b）を明記。残り増分3（SH-05/11/12/14）を次段に。

- [ ] **Step 3: コミット**

```bash
git add docs/audit-findings-catalog.md docs/roadmap.md
git commit -m "docs: gui-shell-controls 増分2b（SH-06/08/10/15）解消を catalog/roadmap に反映"
```

---

## Self-Review（プラン→spec 突合）

**1. Spec カバレッジ**（設計 spec §4）:
- SH-06 パネル可視ボタン（右クリック併存・last-panel 無効）→ Task 1。✓
- SH-08 削除確認（QMessageBox.question・可視導線）→ Task 2。✓
- SH-10 登録ソース一覧（QListWidget・選択で root）→ Task 3。✓
- SH-15 Remove は選択作用・no-op 無反応解消（feedback）→ Task 3。✓
- Layer C（パネルボタン・ソース選択）→ Task 4。削除確認の実ダイアログは realgui でモーダル注意のため Layer B の注入フックで代替（Task 4 は主要2経路）。✓
- docs → Task 5。✓

**2. プレースホルダ走査**: TBD/TODO なし。全コード実挙動。

**3. 型整合**: `add_panel_requested`/`remove_panel_requested`（Signal）・`set_removable(bool)`・`_remove_panel_button: QToolButton`／`_confirm_fn: Callable[[str], bool]`・`_confirm_and_unload(row: int)`・`_close_selected()`／`source_list: QListWidget`・`_refresh_source_list()`・`_on_source_row_changed(row: int)`・`_on_app_change(change: str)` — Produces と後続 Consumes 一致。

**留意（実装時）**: (a) MVVM 不変 — 3 VM ファイルを触らない（View のみ）。(b) 既存テストが「メニュー→即 unload」「centralWidget is tree」を仮定していれば確認/splitter 化に伴い妥当に追随更新し report に明記。(c) 「×」の RUF001 は当該行 noqa。(d) DataExplorer の app_vm 購読は restore ループより前に張る（restore の add が notify で反映されるため）。(e) `_refresh_source_list` は `blockSignals` で再投影中の偽 root 切替を防ぐ。
