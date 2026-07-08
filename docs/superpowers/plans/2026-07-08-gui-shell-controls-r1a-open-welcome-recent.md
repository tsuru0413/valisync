# gui-shell-controls 増分1a（入口: Open / Welcome / Recent / ShellActions）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 初回ユーザーが確実にデータを開けるよう、File>Open / Ctrl+O / Welcome 空状態 CTA / File Browser ボタン / Recent Files の各経路を、既存の堅牢な `_load_file` パイプラインへ配線する。

**Architecture:** 薄い MainWindow を維持。コマンドを1回定義する `ShellActions`（QAction レジストリ）を新設し、メニュー/ツールバーがそこから構築される。中央領域を `QStackedWidget`（Welcome / GraphArea）化し、初回ロードで GraphArea へ永続スワップ。Recent Files は QSettings MRU。すべての Open 経路は MainWindow の単一 `open_file()` スロットに集約し、既存 `_load_file(path)`（オフスレッド・CSV フォーマット解決・診断）を呼ぶ。

**Tech Stack:** Python 3.12+ / PySide6 (Qt6) / pyqtgraph / pytest + pytest-qt。MVVM（View=Qt / ViewModel=純 Python）。

## Global Constraints

- **設計 spec**: `docs/superpowers/specs/2026-07-07-gui-shell-controls-design.md`（§4 アーキテクチャ・§6 増分1 詳細）。
- **品質ゲート**（コミット前に全通過）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。ruff の実 exit は `echo "exit: ${PIPESTATUS[0]}"` で確認（パイプが exit code を隠す）。
- **全角文字禁止（コード内）**: `（）＋−` 等は RUF001/002/003 で落ちる。コメント/文字列は半角、日本語 UI 文字列はそのまま可（既存踏襲）。
- **worktree**: `gui-shell-controls`。作業前に `uv sync --extra dev`。
- **GUI テストレイヤー**: Layer A/B（headless）必須・CI。新入力経路は Layer C（realgui）スケルトンを追加（`pytest.mark.realgui`・`skip_unless_real_display()`）。詳細 `docs/gui-testing-layers.md`。
- **MVVM 不変**: ViewModel は Qt を import しない。View がスレッドを跨いで VM を変更しない。
- **QSettings 定数**: `_ORG = "ValiSync"` / `_APP = "ValiSync"`（`main_window.py` 既定）。
- **既存 Open パイプライン**: `MainWindow._load_file(path: str | Path)` は CSV フォーマット解決（LD-01）・オフスレッド・BusyOverlay・診断・FB-01 失敗可視化を既に行う。**再実装しない**。
- **複数選択**: v1 は単一ファイル（`getOpenFileName`）。
- **最後の1件アンロード**: Welcome へ戻さない（workbench 維持）。

---

## File Structure

| ファイル | 責務 | 種別 |
|---|---|---|
| `src/valisync/gui/views/recent_files.py` | Recent Files MRU（QSettings 永続化・追加/列挙/存在剪定） | 新規 |
| `src/valisync/gui/views/shell_actions.py` | QAction レジストリ（open / open_folder / export）＋メニュー/ツールバー構築ヘルパ | 新規 |
| `src/valisync/gui/views/welcome_view.py` | Welcome 空状態（CTA・ドロップヒント・Recent リスト）・`open_requested` シグナル | 新規 |
| `src/valisync/gui/views/file_browser_view.py` | Open ボタン付きヘッダ行＋`open_requested` シグナル追加 | 変更 |
| `src/valisync/gui/views/main_window.py` | QStackedWidget 化・ShellActions/メニュー/ツールバー・`open_file` スロット・Recent 配線 | 変更 |
| `tests/gui/test_recent_files.py` 他 | 各コンポーネントの Layer A/B テスト | 新規 |
| `tests/realgui/test_open_flow.py` | Open 経路の Layer C スケルトン | 新規 |

**注**: Export（ExportCsvDialog・CsvExporter オプション・ExportController）は **増分1b**（別プラン）で扱う。本プランで作る `ShellActions` は `export` アクションの id を予約するが、その `triggered` 配線と実装は 1b。

---

## Task 1: RecentFiles（MRU・QSettings）

**Files:**
- Create: `src/valisync/gui/views/recent_files.py`
- Test: `tests/gui/test_recent_files.py`

**Interfaces:**
- Produces:
  - `RecentFiles(max_items: int = 10, settings: QSettings | None = None)`
  - `.add(path: str | Path) -> None` — 先頭挿入・重複除去・上限切り詰め・QSettings 保存
  - `.items() -> list[str]` — 新しい順のパス文字列（保存順のまま・存在検証はしない）
  - `.existing() -> list[str]` — `items()` のうち `Path(p).exists()` のみ
  - `.clear() -> None`

QSettings はプラットフォーム保存（テストでは一時 INI を注入して分離する）。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_recent_files.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from valisync.gui.views.recent_files import RecentFiles


def _settings(tmp_path: Path) -> QSettings:
    # INI 形式でテスト分離（レジストリ/既定を汚さない）
    return QSettings(str(tmp_path / "recent.ini"), QSettings.Format.IniFormat)


def test_add_prepends_dedups_and_caps(tmp_path: Path) -> None:
    rf = RecentFiles(max_items=3, settings=_settings(tmp_path))
    for p in ["a.mf4", "b.mf4", "c.mf4", "a.mf4", "d.mf4"]:
        rf.add(p)
    # a は再追加で先頭へ、上限3で b が押し出される
    assert rf.items() == ["d.mf4", "a.mf4", "c.mf4"]


def test_persists_across_instances(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    RecentFiles(settings=s).add("x.mf4")
    assert RecentFiles(settings=s).items() == ["x.mf4"]


def test_existing_filters_missing(tmp_path: Path) -> None:
    real = tmp_path / "real.csv"
    real.write_text("t,v\n0,1\n", encoding="utf-8")
    rf = RecentFiles(settings=_settings(tmp_path))
    rf.add(str(real))
    rf.add(str(tmp_path / "gone.csv"))
    assert rf.existing() == [str(real)]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_recent_files.py -q`
Expected: FAIL（`ModuleNotFoundError: valisync.gui.views.recent_files`）

- [ ] **Step 3: 最小実装**

```python
# src/valisync/gui/views/recent_files.py
"""Recent Files MRU (SH-01). QSettings-backed; no Qt widgets."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

_KEY = "recent_files"
_ORG = "ValiSync"
_APP = "ValiSync"


class RecentFiles:
    """Most-recently-used file paths, persisted to QSettings.

    Newest first, de-duplicated, capped at *max_items*. `existing()` drops
    paths that no longer resolve on disk (files get moved/deleted).
    """

    def __init__(self, max_items: int = 10, settings: QSettings | None = None) -> None:
        self._max = max_items
        self._settings = settings if settings is not None else QSettings(_ORG, _APP)

    def items(self) -> list[str]:
        raw = self._settings.value(_KEY, [])
        # QSettings は単一要素リストを str に潰すことがある; 常に list[str] へ正規化
        if isinstance(raw, str):
            return [raw]
        return [str(p) for p in raw] if raw else []

    def existing(self) -> list[str]:
        return [p for p in self.items() if Path(p).exists()]

    def add(self, path: str | Path) -> None:
        p = str(path)
        items = [x for x in self.items() if x != p]
        items.insert(0, p)
        del items[self._max :]
        self._settings.setValue(_KEY, items)

    def clear(self) -> None:
        self._settings.remove(_KEY)
```

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_recent_files.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/recent_files.py tests/gui/test_recent_files.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/recent_files.py tests/gui/test_recent_files.py
uv run mypy src/valisync/gui/views/recent_files.py
git add src/valisync/gui/views/recent_files.py tests/gui/test_recent_files.py
git commit -m "feat(gui): RecentFiles MRU（QSettings 永続化・存在剪定・SH-01）"
```

---

## Task 2: ShellActions（QAction レジストリ）

**Files:**
- Create: `src/valisync/gui/views/shell_actions.py`
- Test: `tests/gui/test_shell_actions.py`

**Interfaces:**
- Consumes: なし（QAction は parent QWidget を取るのみ）
- Produces:
  - `ShellActions(parent: QWidget)` — 構築時に QAction を生成し `self.actions: dict[str, QAction]` に格納
  - キー: `"open"`（Ctrl+O）・`"open_folder"`・`"export"`（Ctrl+E・初期 `setEnabled(False)`）
  - 各 QAction は `text` / `QStyle` 標準アイコン / `toolTip`（ショートカット併記）/ `statusTip` を持つ
  - `.action(id: str) -> QAction`

QAction はアイコンに `QStyle.StandardPixmap`（アセット不要）を使う。`triggered` の接続は **MainWindow 側**（本クラスは定義のみ・純粋）。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_shell_actions.py
from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.views.shell_actions import ShellActions


def test_registry_defines_core_commands(qtbot: QtBot) -> None:
    w = QWidget()
    qtbot.addWidget(w)
    sa = ShellActions(w)
    assert set(sa.actions) >= {"open", "open_folder", "export"}
    assert sa.action("open").shortcut() == QKeySequence("Ctrl+O")
    assert sa.action("export").shortcut() == QKeySequence("Ctrl+E")
    # ツールチップにショートカットが載る（発見性）
    assert "Ctrl+O" in sa.action("open").toolTip()
    # export はデータ無し時 disabled（出口を予告するが押せない）
    assert sa.action("export").isEnabled() is False
    assert sa.action("open").isEnabled() is True
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_shell_actions.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 最小実装**

```python
# src/valisync/gui/views/shell_actions.py
"""ShellActions — central QAction registry (SH-05/06/14 foundation).

Each shell command is defined ONCE here (text + standard icon + shortcut +
tooltip-with-shortcut + statusTip). Menus, toolbars and context menus mount
these same QAction objects. `triggered` is connected by the owner (MainWindow),
so this class stays a pure definition layer and is testable without a window.
"""

from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QStyle, QWidget


class ShellActions:
    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        style = parent.style()
        self.actions: dict[str, QAction] = {}

        self._add(
            "open",
            "開く…",
            style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton),
            "Ctrl+O",
            "計測ファイルを開く",
        )
        self._add(
            "open_folder",
            "フォルダを開く…",
            style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon),
            None,
            "データソースフォルダを登録する",
        )
        exp = self._add(
            "export",
            "エクスポート…",
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton),
            "Ctrl+E",
            "表示中の信号を CSV に書き出す",
        )
        exp.setEnabled(False)  # データ読込まで無効（1b で状態連動）

    def _add(
        self,
        key: str,
        text: str,
        icon: object,
        shortcut: str | None,
        status: str,
    ) -> QAction:
        act = QAction(icon, text, self._parent)  # type: ignore[arg-type]
        tip = status
        if shortcut is not None:
            act.setShortcut(QKeySequence(shortcut))
            tip = f"{status} ({shortcut})"
        act.setToolTip(tip)
        act.setStatusTip(status)
        self.actions[key] = act
        return act

    def action(self, key: str) -> QAction:
        return self.actions[key]
```

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_shell_actions.py -q`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/shell_actions.py tests/gui/test_shell_actions.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/shell_actions.py tests/gui/test_shell_actions.py
uv run mypy src/valisync/gui/views/shell_actions.py
git add src/valisync/gui/views/shell_actions.py tests/gui/test_shell_actions.py
git commit -m "feat(gui): ShellActions QAction レジストリ（open/open_folder/export・SH-05/14 土台）"
```

---

## Task 3: WelcomeView（空状態）

**Files:**
- Create: `src/valisync/gui/views/welcome_view.py`
- Test: `tests/gui/test_welcome_view.py`

**Interfaces:**
- Consumes: `RecentFiles`（Task 1）
- Produces:
  - `WelcomeView(recent: RecentFiles, parent=None)` — QWidget
  - シグナル `open_requested = Signal(object)` — CTA クリックで `None`、Recent 行クリックでその `str` パスを emit
  - `.refresh() -> None` — Recent リストを `recent.existing()` で再構築
  - CTA ボタンは `objectName("welcome_open_cta")`（Layer C から探せるよう）

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_welcome_view.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.views.recent_files import RecentFiles
from valisync.gui.views.welcome_view import WelcomeView


def _recent(tmp_path: Path) -> RecentFiles:
    return RecentFiles(settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat))


def test_cta_emits_open_requested_none(qtbot: QtBot, tmp_path: Path) -> None:
    view = WelcomeView(_recent(tmp_path))
    qtbot.addWidget(view)
    got: list[object] = []
    view.open_requested.connect(got.append)
    view.findChild(type(view.cta), "welcome_open_cta").click()
    assert got == [None]


def test_recent_row_emits_its_path(qtbot: QtBot, tmp_path: Path) -> None:
    real = tmp_path / "run.mf4"
    real.write_bytes(b"x")
    rf = _recent(tmp_path)
    rf.add(str(real))
    view = WelcomeView(rf)
    qtbot.addWidget(view)
    view.refresh()
    got: list[object] = []
    view.open_requested.connect(got.append)
    view._emit_recent(str(real))  # 行クリックの内部ハンドラを直叩き（Layer A）
    assert got == [str(real)]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_welcome_view.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 最小実装**

```python
# src/valisync/gui/views/welcome_view.py
"""WelcomeView — central empty-state onboarding (SH-01).

The single highest-leverage fix for "a first-time engineer can't find how to
open data": the blank central area becomes an Open call-to-action plus a
Recent Files list. Emits open_requested(None) for the CTA and
open_requested(path) for a recent entry; MainWindow performs the actual load.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.views.recent_files import RecentFiles


class WelcomeView(QWidget):
    open_requested = Signal(object)  # None=CTA / str=recent path

    def __init__(self, recent: RecentFiles, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._recent = recent

        title = QLabel("計測ファイルを開く")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("mf4 / mdf / dat / csv をドラッグ＆ドロップ、または下のボタンから")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)

        self.cta = QPushButton("計測ファイルを開く  (Ctrl+O)")
        self.cta.setObjectName("welcome_open_cta")
        self.cta.clicked.connect(lambda: self.open_requested.emit(None))

        self._recent_box = QVBoxLayout()

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.cta, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(self._recent_box)
        layout.addStretch(2)

        self.refresh()

    def _emit_recent(self, path: str) -> None:
        self.open_requested.emit(path)

    def refresh(self) -> None:
        # Recent 行を作り直す（存在するもののみ）
        while self._recent_box.count():
            item = self._recent_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for path in self._recent.existing():
            btn = QPushButton(path)
            btn.setFlat(True)
            btn.clicked.connect(lambda _=False, p=path: self._emit_recent(p))
            self._recent_box.addWidget(btn)
```

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_welcome_view.py -q`
Expected: PASS

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/welcome_view.py tests/gui/test_welcome_view.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/welcome_view.py tests/gui/test_welcome_view.py
uv run mypy src/valisync/gui/views/welcome_view.py
git add src/valisync/gui/views/welcome_view.py tests/gui/test_welcome_view.py
git commit -m "feat(gui): WelcomeView 空状態（Open CTA＋Recent・open_requested・SH-01）"
```

---

## Task 4: FileBrowserView に Open ボタン

**Files:**
- Modify: `src/valisync/gui/views/file_browser_view.py`
- Test: `tests/gui/test_file_browser_open.py`

**Interfaces:**
- Produces: `FileBrowserView.open_requested = Signal()` — ヘッダの Open ボタンクリックで emit。ボタンは `objectName("file_browser_open")`。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_file_browser_open.py
from __future__ import annotations

from PySide6.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
from valisync.gui.views.file_browser_view import FileBrowserView


def test_open_button_emits_open_requested(qtbot: QtBot) -> None:
    view = FileBrowserView(FileBrowserVM(AppViewModel()))
    qtbot.addWidget(view)
    fired: list[int] = []
    view.open_requested.connect(lambda: fired.append(1))
    btn = view.findChild(QPushButton, "file_browser_open")
    assert btn is not None
    btn.click()
    assert fired == [1]
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_file_browser_open.py -q`
Expected: FAIL（`open_requested` 属性なし / ボタン None）

- [ ] **Step 3: 最小実装**

`file_browser_view.py` の import に `QHBoxLayout, QPushButton, Signal` を追加し、`FileBrowserView` に `open_requested = Signal()` を宣言。`__init__` のレイアウト構築を、Open ボタン付きヘッダ行を先頭に持つよう変更する:

```python
# import 変更（抜粋）
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
```

```python
class FileBrowserView(QWidget):
    open_requested = Signal()  # ヘッダの Open ボタン
    # ... 既存 docstring ...

    def __init__(self, vm: FileBrowserVM) -> None:
        super().__init__()
        self._vm = vm
        self.model = FileListModel(vm, self)

        self.list_view = QListView()
        self.list_view.setModel(self.model)
        self.list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.placeholder_label = QLabel(
            "ファイルが読み込まれていません\n\nウィンドウへファイルをドロップして追加",
            self,
        )
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setWordWrap(True)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self.list_view)
        self._stack.addWidget(self.placeholder_label)

        # ヘッダ行: Open ボタン（空リストからでも前進できる・SH-07）
        self.open_button = QPushButton("開く…")
        self.open_button.setObjectName("file_browser_open")
        self.open_button.clicked.connect(self.open_requested)
        header = QHBoxLayout()
        header.addWidget(self.open_button)
        header.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self._stack)

        self.list_view.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )
        self.list_view.customContextMenuRequested.connect(self._show_context_menu)

        unsubscribe = self._vm.subscribe(self._on_vm_change)
        self.destroyed.connect(lambda *_: unsubscribe())
        self._refresh_state()
```

（`_on_selection_changed` 以降の既存メソッドは不変。）

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_file_browser_open.py tests/gui/test_file_browser_view.py -q`
Expected: PASS（新テスト＋既存 file browser テスト無回帰）

- [ ] **Step 5: ゲート＋コミット**

```bash
uv run ruff check src/valisync/gui/views/file_browser_view.py tests/gui/test_file_browser_open.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/file_browser_view.py tests/gui/test_file_browser_open.py
uv run mypy src/valisync/gui/views/file_browser_view.py
git add src/valisync/gui/views/file_browser_view.py tests/gui/test_file_browser_open.py
git commit -m "feat(gui): File Browser に開くボタン（open_requested・SH-07）"
```

---

## Task 5: MainWindow を QStackedWidget 化（Welcome / GraphArea スワップ）

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（`__init__` の中央widget設定・新規メソッド `_update_central`）
- Test: `tests/gui/test_main_window_central.py`

**Interfaces:**
- Consumes: `WelcomeView`（Task 3）・`RecentFiles`（Task 1）
- Produces:
  - `MainWindow.central_stack: QStackedWidget`（index 0=WelcomeView / index 1=GraphAreaView）
  - `MainWindow.welcome_view: WelcomeView`
  - `MainWindow.recent_files: RecentFiles`
  - `MainWindow._workbench_started: bool`（初回ロードで True・以後 False へ戻らない）
  - `MainWindow.showing_welcome() -> bool`（テスト向け: 現在 Welcome を表示中か）
  - スワップ規則: 初期は Welcome。`_workbench_started` が True になったら以後 GraphArea を表示（unload で戻らない）。

**注**: `setCentralWidget(self.graph_area_view)` を `QStackedWidget` へ置換する。既存の cross-view 配線（`file_dropped` 等）は不変。

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_main_window_central.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.main_window import MainWindow


def _mw(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    mw = MainWindow(AppViewModel())
    # Recent/永続化をテスト分離
    mw.recent_files = mw.recent_files.__class__(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(mw)
    return mw


def test_starts_on_welcome(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    assert mw.showing_welcome() is True


def test_first_load_swaps_to_graph_and_unload_keeps_it(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    # 初回ロードを模擬（app_vm の loaded 通知が届くと workbench へスワップ）
    mw.app_vm.register_loaded("csv_1")
    assert mw.showing_welcome() is False
    # 最後の1件アンロードでも Welcome へ戻さない
    mw.app_vm.unload_file("csv_1")
    assert mw.showing_welcome() is False
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_main_window_central.py -q`
Expected: FAIL（`showing_welcome` なし / 中央が stack でない）

- [ ] **Step 3: 最小実装**

`main_window.py` の import に `QStackedWidget`・`WelcomeView`・`RecentFiles` を追加。`__init__` の「Graph Area (Central Widget)」節を差し替える:

```python
# import 追加
from PySide6.QtWidgets import QDockWidget, QMainWindow, QMessageBox, QStackedWidget, QToolBar
from valisync.gui.views.recent_files import RecentFiles
from valisync.gui.views.welcome_view import WelcomeView
```

```python
        # ── Central: Welcome / Graph Area を QStackedWidget で切替 ──────────────
        self.recent_files = RecentFiles()
        self._workbench_started = False
        self.welcome_view = WelcomeView(self.recent_files)
        self.welcome_view.open_requested.connect(self._on_open_requested)
        self.central_stack = QStackedWidget(self)
        self.central_stack.addWidget(self.welcome_view)      # index 0
        self.central_stack.addWidget(self.graph_area_view)   # index 1
        self.setCentralWidget(self.central_stack)
        self._update_central()
```

`_on_app_change` の `loaded` 分岐末尾で `_update_central()` を呼ぶよう変更（既存の `refresh()` はそのまま）:

```python
    def _on_app_change(self, change: str) -> None:
        if change == "loaded":
            self.channel_browser_vm.refresh()
            self._workbench_started = True
            self._update_central()
        if change in ("active_file", "loaded", "unloaded"):
            self._update_window_title()
```

新規メソッド（`_update_window_title` の近くに追加）:

```python
    def _update_central(self) -> None:
        """Welcome か GraphArea を表示。初回ロードで GraphArea へ永続スワップ。

        _workbench_started が True になったら、最後の1件をアンロードしても
        Welcome へは戻さない（workbench を奪わない・spec §4.2）。
        """
        widget = self.graph_area_view if self._workbench_started else self.welcome_view
        self.central_stack.setCurrentWidget(widget)

    def showing_welcome(self) -> bool:
        return self.central_stack.currentWidget() is self.welcome_view

    def _on_open_requested(self, path: object) -> None:
        """WelcomeView からの Open 要求。None=ダイアログ / str=そのパスを直接ロード。"""
        if path is None:
            self.open_file()
        else:
            self._load_file(str(path))
```

（`open_file` は Task 7 で実装。本タスクでは `_on_open_requested` が参照するが、Task 7 まで `open_file` は未定義 → Task 5 のテストは `register_loaded` 経由でスワップのみ検証し、`open_file` は呼ばない。**Task 5 と Task 7 は連続実行**し、間で `open_file` 未定義の中間状態を残さないこと。）

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_main_window_central.py -q`
Expected: PASS

- [ ] **Step 5: コミットは Task 7 とまとめる**

（`_on_open_requested` が Task 7 の `open_file` に依存するため、Task 5–7 を連続実装し、Task 7 末尾で一括ゲート＋コミット。中間で壊れた状態を push しない。）

---

## Task 6: メニューバー＋ツールバー（ShellActions から構築）

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（`__init__` の View メニュー/ツールバー節）
- Test: `tests/gui/test_main_window_menus.py`

**Interfaces:**
- Consumes: `ShellActions`（Task 2）
- Produces:
  - `MainWindow.shell_actions: ShellActions`
  - File メニュー（Open / Open Folder / Recent Files 空サブメニュー / Export / — / Exit）
  - ツールバーに Open・Export・（既存）Data Explorer
  - メニュータイトルは `File` / `View` / `Analyze` / `Help`（Analyze/Help は増分2/3 で中身追加・本タスクでは空でも作る）

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_main_window_menus.py
from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.main_window import MainWindow


def _menu_titles(mw: MainWindow) -> list[str]:
    return [a.text() for a in mw.menuBar().actions()]


def test_menubar_has_file_view_analyze_help(qtbot: QtBot) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    titles = _menu_titles(mw)
    assert titles[0] == "File"
    assert {"File", "View", "Analyze", "Help"} <= set(titles)


def test_toolbar_exposes_open_and_export(qtbot: QtBot) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    assert "open" in mw.shell_actions.actions
    # ツールバーに open アクションが載っている
    tb_actions = {a for tb in mw.findChildren(type(mw.findChild(type(mw), None) or mw)) for a in []}  # noqa: placeholder
    assert mw.shell_actions.action("open") is not None
```

（2つ目のテストのツールバー走査は下記実装後に `mw.findChildren(QToolBar)` で厳密化する。まず1つ目でメニュー構成を駆動する。）

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_main_window_menus.py::test_menubar_has_file_view_analyze_help -q`
Expected: FAIL（menuBar 先頭が "View"・"File" なし）

- [ ] **Step 3: 最小実装**

`main_window.py` の import に `ShellActions` を追加。既存「View menu」「Toolbar」節を次で置換（`shell_actions` を先に構築）:

```python
from valisync.gui.views.shell_actions import ShellActions
```

```python
        # ── ShellActions（QAction レジストリ）────────────────────────────────
        self.shell_actions = ShellActions(self)
        self.shell_actions.action("open").triggered.connect(self.open_file)
        self.shell_actions.action("open_folder").triggered.connect(
            self.open_data_explorer
        )
        # export の triggered は増分1b で接続

        # ── メニューバー ─────────────────────────────────────────────────────
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.shell_actions.action("open"))
        file_menu.addAction(self.shell_actions.action("open_folder"))
        self.recent_menu = file_menu.addMenu("Recent Files")
        file_menu.addAction(self.shell_actions.action("export"))
        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self.file_dock.toggleViewAction())
        view_menu.addAction(self.channel_dock.toggleViewAction())
        view_menu.addAction(self.diagnostics_dock.toggleViewAction())

        self.menuBar().addMenu("Analyze")  # 増分2 で中身
        help_menu = self.menuBar().addMenu("Help")
        about = help_menu.addAction("About ValiSync")
        about.triggered.connect(self._show_about)

        # ── ツールバー ───────────────────────────────────────────────────────
        toolbar: QToolBar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")
        toolbar.addAction(self.shell_actions.action("open"))
        toolbar.addAction(self.shell_actions.action("export"))
        toolbar.addSeparator()
        self.action_data_explorer = QAction("Data Explorer", self)
        self.action_data_explorer.triggered.connect(self.open_data_explorer)
        toolbar.addAction(self.action_data_explorer)
```

`_show_about` を追加:

```python
    def _show_about(self) -> None:
        QMessageBox.about(
            self, "About ValiSync", "ValiSync — ADAS 信号解析デスクトップ"
        )
```

（この節は既存の「View menu (dock toggles, R1.4)」「Toolbar (R1.5)」ブロックを置き換える。`self.action_data_explorer` の定義は維持。）

- [ ] **Step 4: パス確認**

`test_main_window_menus.py` の2つ目テストを `QToolBar` 走査へ確定:

```python
from PySide6.QtWidgets import QToolBar

def test_toolbar_exposes_open_and_export(qtbot: QtBot) -> None:
    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    tb = mw.findChild(QToolBar, "main_toolbar")
    assert tb is not None
    acts = set(tb.actions())
    assert mw.shell_actions.action("open") in acts
    assert mw.shell_actions.action("export") in acts
```

Run: `uv run pytest tests/gui/test_main_window_menus.py -q`
Expected: PASS

- [ ] **Step 5: コミットは Task 7 とまとめる**（Task 5–7 連続）

---

## Task 7: open_file スロット＋全 Open 経路の配線

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（`open_file` スロット追加・Recent 更新・FileBrowser/Welcome 配線）
- Test: `tests/gui/test_main_window_open.py`

**Interfaces:**
- Consumes: `ShellActions.open`（Task 2/6）・`WelcomeView.open_requested`（Task 3/5）・`FileBrowserView.open_requested`（Task 4）
- Produces:
  - `MainWindow.open_file(*_: object) -> None` — `QFileDialog.getOpenFileName`（単一・フィルタ mf4/mdf/dat/csv）→ 空でなければ `_load_file(path)`
  - `_on_loaded` 末尾で `recent_files.add(path)` ＋ `_rebuild_recent_menu()` ＋ `welcome_view.refresh()`
  - `_rebuild_recent_menu()` — `recent_menu` を `recent_files.existing()` で再構築（各項目 `triggered` → `_load_file(path)`）
  - `_file_dialog` フックポイント: テストが `QFileDialog.getOpenFileName` を monkeypatch できるよう、`open_file` は `QFileDialog.getOpenFileName(self, ...)` を直接呼ぶ

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/gui/test_main_window_open.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.main_window import MainWindow


def _mw(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    mw = MainWindow(AppViewModel())
    mw.recent_files = mw.recent_files.__class__(
        settings=QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat)
    )
    qtbot.addWidget(mw)
    return mw


def test_open_file_dialog_cancel_does_not_load(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    mw = _mw(qtbot, tmp_path)
    called: list[str] = []
    monkeypatch.setattr(mw, "_load_file", lambda p: called.append(str(p)))
    # ダイアログがキャンセル（空文字）を返す
    monkeypatch.setattr(
        "valisync.gui.views.main_window.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: ("", "")),
    )
    mw.open_file()
    assert called == []


def test_open_file_dialog_selection_loads(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    mw = _mw(qtbot, tmp_path)
    called: list[str] = []
    monkeypatch.setattr(mw, "_load_file", lambda p: called.append(str(p)))
    monkeypatch.setattr(
        "valisync.gui.views.main_window.QFileDialog.getOpenFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "run.mf4"), "")),
    )
    mw.open_file()
    assert called == [str(tmp_path / "run.mf4")]


def test_loaded_updates_recent(qtbot: QtBot, tmp_path: Path) -> None:
    mw = _mw(qtbot, tmp_path)
    p = tmp_path / "run.mf4"
    p.write_bytes(b"x")
    # _on_loaded は LoadOutcome を受ける。source_name をスタブし、Recent 追加のみ検証。
    class _Outcome:
        key = "mf4_1"
        diagnostics = ()
    mw.app_vm.session.source_name = lambda k: str(p)  # type: ignore[assignment]
    mw._on_loaded(_Outcome())  # type: ignore[arg-type]
    assert str(p) in mw.recent_files.items()
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_main_window_open.py -q`
Expected: FAIL（`open_file` なし / Recent 未更新）

- [ ] **Step 3: 最小実装**

`main_window.py` の import に `QFileDialog` を追加。`open_data_explorer` の近くに新規スロットを追加:

```python
from PySide6.QtWidgets import QDockWidget, QFileDialog, QMainWindow, QMessageBox, QStackedWidget, QToolBar
```

```python
    _OPEN_FILTER = "計測ファイル (*.mf4 *.mdf *.dat *.csv);;すべてのファイル (*)"

    def open_file(self, *_: object) -> None:
        """File>Open / Ctrl+O / Welcome CTA / File Browser ボタンの集約先。

        v1 は単一ファイル。選択されたら既存 _load_file（オフスレッド・CSV
        フォーマット解決・診断）へ委譲する。
        """
        path, _sel = QFileDialog.getOpenFileName(
            self, "計測ファイルを開く", "", self._OPEN_FILTER
        )
        if path:
            self._load_file(path)
```

`_on_loaded` の末尾（`self.statusBar().showMessage(msg)` の後）に Recent 更新を追加:

```python
        # SH-01: 読み込み成功を Recent に記録し UI へ反映
        self.recent_files.add(source)
        self._rebuild_recent_menu()
        self.welcome_view.refresh()
```

（注: `source = self.app_vm.session.source_name(outcome.key)` は既存行で取得済み。`source_name` はパス/表示名を返す。Recent はこの `source` を保持する。）

`_rebuild_recent_menu` を追加:

```python
    def _rebuild_recent_menu(self) -> None:
        """File>Recent Files を現在の MRU（存在するもの）で作り直す。"""
        self.recent_menu.clear()
        paths = self.recent_files.existing()
        if not paths:
            empty = self.recent_menu.addAction("（履歴なし）")
            empty.setEnabled(False)
            return
        for p in paths:
            act = self.recent_menu.addAction(p)
            act.triggered.connect(lambda _=False, path=p: self._load_file(path))
```

`__init__` の cross-view 配線（`self.graph_area_view.file_dropped.connect(...)` の近く）に File Browser の Open を接続、初回の Recent メニュー構築:

```python
        self.file_browser_view.open_requested.connect(self.open_file)
        self._rebuild_recent_menu()
```

- [ ] **Step 4: パス確認**

Run: `uv run pytest tests/gui/test_main_window_open.py tests/gui/test_main_window_central.py tests/gui/test_main_window_menus.py -q`
Expected: PASS（Task 5/6/7 の MainWindow テスト全通過）

- [ ] **Step 5: フルゲート＋コミット（Task 5–7 まとめ）**

```bash
uv run pytest -q 2>&1 | tail -3   # 全体無回帰
uv run ruff check src/valisync/gui/views/main_window.py tests/gui/test_main_window_central.py tests/gui/test_main_window_menus.py tests/gui/test_main_window_open.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format src/valisync/gui/views/main_window.py tests/gui/test_main_window_*.py
uv run mypy src/valisync/gui/views/main_window.py
git add src/valisync/gui/views/main_window.py tests/gui/test_main_window_central.py tests/gui/test_main_window_menus.py tests/gui/test_main_window_open.py
git commit -m "feat(gui): File メニュー/ツールバー/Welcome スワップ/open_file 集約/Recent 配線（SH-01/07）"
```

---

## Task 8: Layer C realgui スケルトン（Open 経路）

**Files:**
- Create: `tests/realgui/test_open_flow.py`

**Interfaces:**
- Consumes: `MainWindow`・`ShellActions`・`WelcomeView`
- 目的: headless では実イベント経路を迂回する（`open_file` を直接呼ぶだけで QFileDialog は開かない）ため、**Ctrl+O が実際に `open_file` を発火するか**を実 OS 入力で検証する honest gate。QFileDialog 自体はモーダルなので、テストは `open_file` を monkeypatch して「ショートカット→スロット到達」を確認する（ファイル選択はモック）。

- [ ] **Step 1: スケルトンを書く**

```python
# tests/realgui/test_open_flow.py
"""Layer C: Ctrl+O が open_file スロットへ到達するか（実 OS キー入力）。

headless の QTest.keyClick でも配線は検証できるが、ショートカットの
context / focus は実ウィンドウでしか正確に出ない。QFileDialog はモーダルなので
open_file をスタブし「ショートカット→スロット発火」を確認する。

honest RED: File メニュー/ツールバーに open アクションを載せ忘れる、または
shortcut を外すと Ctrl+O がスロットに届かず fired が空になる。
"""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import skip_unless_real_display

pytestmark = pytest.mark.realgui


def test_ctrl_o_triggers_open(qtbot: QtBot, monkeypatch) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    mw = MainWindow(AppViewModel())
    qtbot.addWidget(mw)
    fired: list[int] = []
    monkeypatch.setattr(mw, "open_file", lambda *a: fired.append(1))
    mw.show()
    qtbot.waitExposed(mw)
    QApplication.processEvents()

    qtbot.keyClick(mw, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()

    assert fired == [1], "Ctrl+O が open_file に届かない（open アクションの shortcut/配線を確認）"
```

- [ ] **Step 2: 収集確認（skip 前提）**

Run: `uv run pytest tests/realgui/test_open_flow.py --collect-only -q`
Expected: 1 test collected（`--realgui` 無しでは skip）

- [ ] **Step 3: ゲート＋コミット**

```bash
uv run ruff check tests/realgui/test_open_flow.py; echo "exit: ${PIPESTATUS[0]}"
uv run ruff format tests/realgui/test_open_flow.py
git add tests/realgui/test_open_flow.py
git commit -m "test(realgui): Ctrl+O→open_file 到達の honest gate スケルトン（SH-01）"
```

---

## Task 9: docs 反映（catalog / roadmap）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（SH-01 部分解消・SH-07 解消の注記）
- Modify: `docs/roadmap.md`（gui-shell-controls 行に増分1a 進捗）

**注**: SH-01 の Recent は本増分で実装済みだが、`File>Open`/Welcome/Recent/File Browser を配線した一方、Export（SH-03）は増分1b。SH-01 は「Open+Recent 解消・Export 導線は 1b」と記す。SH-07 は解消。

- [ ] **Step 1: catalog の SH-01 / SH-07 行に解消注記を前置**（`PR #<n>` は PR 作成後に確定）

SH-01 行頭の優先度を `✅解消（増分1a）` にし、本文先頭へ:
`**✅解消（2026-07-08・増分1a・PR #<n>）: File>Open＋Ctrl+O＋Welcome 空状態 CTA＋File Browser ボタン＋Recent Files（QSettings MRU・存在剪定）を既存 _load_file へ集約配線。ShellActions QAction レジストリ新設。** 〔元課題〕...`

SH-07 も同様に `✅解消（増分1a）` ＋ 注記。

- [ ] **Step 2: roadmap の gui-shell-controls 行を更新**

`gui-shell-controls` 行の状況に「増分1a（入口: SH-01/07・Open/Welcome/Recent/ShellActions）実装済み」を追記。

- [ ] **Step 3: コミット**

```bash
git add docs/audit-findings-catalog.md docs/roadmap.md
git commit -m "docs: gui-shell-controls 増分1a（Open/Welcome/Recent）解消を catalog/roadmap に反映"
```

---

## Self-Review（プラン→spec 突合）

**1. Spec カバレッジ**（spec §6.1–6.3・6.5 = 増分1a 範囲）:
- SH-01 Open 3+1 経路 → Task 6（メニュー/ツールバー）＋Task 7（open_file・Welcome/FileBrowser 配線）。✓
- SH-01 Recent Files MRU → Task 1（RecentFiles）＋Task 7（更新/メニュー）＋Task 3（Welcome 表示）。✓
- SH-07 File Browser Open → Task 4。✓
- Welcome 空状態＋スワップ規則（unload-last 維持） → Task 3＋Task 5。✓
- ShellActions レジストリ → Task 2。✓
- Layer C（新入力経路） → Task 8（Ctrl+O）。Welcome CTA / File Browser ボタンの realgui は Task 8 に追記可（同ファイル）。
- SH-03 Export は **増分1b**（別プラン）。本プラン範囲外を明記済み。✓

**2. プレースホルダ走査**: Task 6 Step 1 の2つ目テストに `# noqa: placeholder` の仮走査があるが、Step 4 で `QToolBar` 走査に確定させる手順を明示済み（実行時に置換）。他に TBD/TODO なし。

**3. 型整合**: `RecentFiles`（`items`/`existing`/`add`/`clear`）・`ShellActions.action(id)`/`actions`・`WelcomeView.open_requested(object)`/`refresh`/`_emit_recent`・`FileBrowserView.open_requested()`・`MainWindow.open_file`/`showing_welcome`/`_update_central`/`_rebuild_recent_menu`/`recent_files`/`welcome_view`/`central_stack`/`_workbench_started` — 各タスクの Produces と後続 Consumes が一致。

**依存順**: Task 1 → 2 → 3 → 4 は独立。Task 5–7 は連続（中間で `open_file` 未定義状態を残さない）。Task 8/9 は最後。
