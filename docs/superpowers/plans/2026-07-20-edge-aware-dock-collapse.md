# 辺対応の折りたたみ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ドックを畳む方向を「接している辺」に合わせる（左/右=幅を詰めて全高の縦レール＋縦タブ・下=高さを詰めて全幅の横帯＋横チップ）。畳んだドックは hide し、辺ごとの `DockCollapseRail` に content サイズのタブを出す。

**Architecture:** 畳み機構を「タイトルバーの高さクランプ」から「dock.hide()＋辺ごとレールにタブ」へ差し替える。レールの**配置方式**（中央 widget を包むエッジストリップ）は Task 1 実機スパイクで確定。レールの**内部**（タブのレイアウト/描画/API）は配置非依存で Task 4 が実装。MainWindow が collapse/expand・辺判定・永続を配線。

**Tech Stack:** PySide6（QDockWidget・setAllowedAreas・dockWidgetArea・resizeDocks・QGridLayout・カスタム paintEvent の縦書きラベル）・既存 `theme/icons.py`（Lucide 着色）・既存 QSettings 永続・realgui Layer C。

**Spec:** [docs/superpowers/specs/2026-07-20-edge-aware-dock-collapse-design.md](../specs/2026-07-20-edge-aware-dock-collapse-design.md)

## Global Constraints

- **トークン/エクスポート変更なし** — tokens.py/export は触らない。色は既存 chrome トークン（`chrome_text` 等・chevron 着色は `icons.icon()` 経由で自動）。追加は `chevron_left`/`chevron_up` アイコンの vendoring のみ。
- **畳む方向は `dockWidgetArea(dock)` で動的決定** — 左/右=縦レール（幅クランプ）・下=横帯（高さクランプ）。ドックを別辺へ動かせば追従。
- **上端配置を構造的に禁止** — 3ドックに `setAllowedAreas(Left|Right|Bottom)`。対応辺 = {左・右・下}。上用レールは作らない。
- **畳んだタブはクリックで展開のみ** — フロート/閉じるは載せない（展開後のタイトルバーで操作）。**ツールチップ（ホバー説明）なし**。
- **タブは content サイズ**（全幅/全高に引き伸ばさない）。左/右=**上寄せ**・下=**左寄せ**。複数はドックの位置順で積む（クリック順で入れ替わらない）。
- **レールは辺ごと遅延** — 畳んだドックが出たとき現れ、空になったら隠す。
- **既存 `dockCollapsed`（`{objectName: bool}`）永続を継承** — `_restore_state()`/`_reset_layout()` の後に再適用。QSettings は conftest 隔離済み（`_ORG/_APP`）。
- **フロート中は畳みトグル無効化（グレーアウト）** — 再ドッキングで有効化。
- コミット前ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全て exit 0（全リポジトリ実行・出力そのまま報告）。
- **Task 1 の spike で採用配置方式が候補(b) 以外に決まった場合、影響は Task 5 の配置配線のみ**（`DockCollapseRail` 内部＝Task 4 と辺判定＝Task 3 は配置非依存で不変）。

---

### Task 1: レール配置方式の実機スパイク（コントローラ・実ディスプレイ必須）

**Files:**
- Create: `src/valisync/gui/views/central_with_rails.py`（採用方式(b)の場合）
- Modify: `src/valisync/gui/views/main_window.py`（`setCentralWidget` を差し替え）

コード整備・実 `--realgui`/実機観察ともコントローラ駆動（スパイクは TDD でなく実機観察で検証）。

**目的:** 「dock を hide したとき中央が実際にスペースを取り戻し、辺沿いに全長のレール枠を出せるか」を実機で確かめ、レール配置方式を確定する。QDockWidget レイアウトの finicky さ（FU-14 defer の所以）と `setCorner`（FU-10）干渉があるため机上で決めない。

- [ ] **Step 1: 候補(b) の最小実装を作る（推奨・中央 widget を包むエッジストリップ）**

`src/valisync/gui/views/central_with_rails.py`:

```python
"""中央 widget をエッジレール枠で包むコンテナ (edge-aware-dock-collapse Task 1)。

畳んだドックのレールを「dock リングの外」でなく「中央 widget の内側の縁」に置く。
ドックを hide すると dock 領域が畳まれて中央がそのぶん拡張し、拡張した中央の縁に
レールが乗る = レールが窓の縁に一致する。setCorner (FU-10・dock 用) と無干渉。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget


class CentralWithRails(QWidget):
    """center を中央に据え、左/右=縦・下=横のレールスロットを縁に持つ。"""

    def __init__(self, center: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._center = center
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        # row0: [left(0,0)] [center(0,1 stretch)] [right(0,2)]
        # row1: [bottom(1, 0..2 span)]
        grid.addWidget(center, 0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        self._grid = grid
        self._rails: dict[Qt.DockWidgetArea, QWidget] = {}

    def set_rail(self, edge: Qt.DockWidgetArea, rail: QWidget) -> None:
        """辺に対応するグリッドセルへレール widget を据える (1回限り)。"""
        cell = {
            Qt.DockWidgetArea.LeftDockWidgetArea: (0, 0, 1, 1),
            Qt.DockWidgetArea.RightDockWidgetArea: (0, 2, 1, 1),
            Qt.DockWidgetArea.BottomDockWidgetArea: (1, 0, 1, 3),
        }[edge]
        self._grid.addWidget(rail, *cell)
        self._rails[edge] = rail
```

`main_window.py` の `setCentralWidget(self.central_stack)`（165行付近）を差し替え:

```python
        from valisync.gui.views.central_with_rails import CentralWithRails

        self._central_with_rails = CentralWithRails(self.central_stack)
        self.setCentralWidget(self._central_with_rails)
```

- [ ] **Step 2: スタブレールで実機検証（コントローラ・実ディスプレイ）**

一時的に、右辺スロットへ色付きスタブ（`QWidget` に `setStyleSheet("background:#c0392b")` ＋固定幅 24）を `set_rail(RightDockWidgetArea, stub)` で据え、`file_dock.hide()` を実行するデバッグ起動を用意（`scripts/` に一時スクリプト or Python REPL で `build_main_window()` → show → `win.file_dock.hide()`）。実ディスプレイ（`QT_QPA_PLATFORM=windows`）で次を目視/実測:
  1. `file_dock.hide()` で中央プロットが**右へ実際に広がる**（`win._central_with_rails.width()` が増える）
  2. 右スタブレールが**中央の右縁に全高で出る**
  3. 下スタブ（`set_rail(BottomDockWidgetArea, stub2)`）が全幅で出る
  4. 既存 `_apply_dock_corners`（FU-10）と競合しない（File/Channel が全高のまま）

Run（実測の例）:
```bash
uv run python -c "import os; os.environ['QT_QPA_PLATFORM']='windows'; from PySide6.QtWidgets import QApplication; import sys; app=QApplication(sys.argv); from valisync.gui.app import build_main_window; w=build_main_window(); w.show(); c0=w._central_with_rails.width(); w.file_dock.hide(); app.processEvents(); print('central width', c0, '->', w._central_with_rails.width())"
```
Expected: central width が hide 後に増加（右ドックぶんを回収）。増えなければ配置方式(b)は不成立 → Step 3 のフォールバックへ。

- [ ] **Step 3: 判定とフォールバック記録**

(b) が上記4点を満たせば採用。満たさなければフォールバック候補 (a) QToolBar 領域（`addToolBar(RightToolBarArea, ...)` の縦ツールバー＋`BottomToolBarArea`）を同手順で検証し採用。**採用方式と観察結果を `.superpowers/sdd/progress.md`（incrC2 セクション）へ決定ノートとして記録**（Task 5 の配置配線がこの決定に従う）。スタブは撤去（`set_rail` 呼び出しは Task 5 で本物に差し替えるため、この時点では `CentralWithRails` 導入と `setCentralWidget` 差し替えのみ残す）。

- [ ] **Step 4: ゲート＋コミット**

```bash
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/central_with_rails.py src/valisync/gui/views/main_window.py
git commit -m "feat(gui): 中央エッジレール枠 CentralWithRails 導入 (edge-aware-collapse Task 1 spike)"
```

Expected: 既存テスト全 green（`setCentralWidget` 差し替えは central_stack を包むだけで表示挙動不変）。

---

### Task 2: chevron_left / chevron_up アイコンの vendoring

**Files:**
- Create: `src/valisync/gui/theme/icons/lucide/chevron-left.svg`・`chevron-up.svg`
- Modify: `src/valisync/gui/theme/icons.py`（ICONS）
- Test: `tests/gui/test_theme_icons.py`

**Interfaces:**
- Produces: `icons.icon("chevron_left") -> QIcon`・`icons.icon("chevron_up") -> QIcon`（Task 4 が消費）

- [ ] **Step 1: SVG を pinned unpkg から取得（無改変・増分C Task 1 と同手順）**

```bash
curl -fsSL https://unpkg.com/lucide-static@1.24.0/icons/chevron-left.svg \
  -o src/valisync/gui/theme/icons/lucide/chevron-left.svg
curl -fsSL https://unpkg.com/lucide-static@1.24.0/icons/chevron-up.svg \
  -o src/valisync/gui/theme/icons/lucide/chevron-up.svg
```

取得後、両ファイルが `stroke="currentColor"` を含み固定色を持たないことを目視確認（Lucide 標準形）。`package-data` glob は `icons/**/*.svg` で自動包含・pyproject 変更不要。LICENSES.md は Lucide ISC を既に網羅・追記不要。

- [ ] **Step 2: 失敗するテストを書く**

`tests/gui/test_theme_icons.py` に追加（既存 `test_chevron_icons_registered_and_render` と同書式）:

```python
def test_chevron_left_up_registered_and_render(qapp):
    from valisync.gui.theme import icons

    for name in ("chevron_left", "chevron_up"):
        ico = icons.icon(name)
        assert not ico.isNull(), name
```

- [ ] **Step 3: RED 確認**

Run: `uv run pytest tests/gui/test_theme_icons.py::test_chevron_left_up_registered_and_render -v`
Expected: FAIL（KeyError: 'chevron_left'）

- [ ] **Step 4: ICONS に登録**

`src/valisync/gui/theme/icons.py` の `ICONS` に追加:

```python
    "chevron_left": "lucide/chevron-left.svg",
    "chevron_up": "lucide/chevron-up.svg",
```

- [ ] **Step 5: GREEN＋ゲート＋コミット**

```bash
uv run pytest tests/gui/test_theme_icons.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/icons/lucide/chevron-left.svg src/valisync/gui/theme/icons/lucide/chevron-up.svg src/valisync/gui/theme/icons.py tests/gui/test_theme_icons.py
git commit -m "feat(theme): chevron_left/up アイコン vendoring (edge-aware-collapse Task 2)"
```

---

### Task 3: 上配置禁止（setAllowedAreas）＋辺判定ヘルパ

**Files:**
- Create: `src/valisync/gui/views/dock_collapse_rail.py`（`RailKind` enum ＋ `rail_kind_for_area` ＋ `EXPAND_ICON` のみ・widget は Task 4 で追加）
- Modify: `src/valisync/gui/views/main_window.py`（3ドックに `setAllowedAreas`）
- Test: `tests/gui/test_dock_collapse_rail.py`・`tests/gui/test_main_window.py`

**Interfaces:**
- Produces: `RailKind`（`VERTICAL`/`HORIZONTAL`）・`rail_kind_for_area(area) -> RailKind | None`・`EXPAND_ICON: dict[Qt.DockWidgetArea, str]`（Task 4/5 が消費）

- [ ] **Step 1: 失敗するテストを書く（辺判定＝純関数）**

`tests/gui/test_dock_collapse_rail.py`:

```python
"""DockCollapseRail — 辺対応の折りたたみレール (edge-aware-collapse)。"""

from __future__ import annotations

from PySide6.QtCore import Qt


def test_rail_kind_for_area_maps_edges():
    from valisync.gui.views.dock_collapse_rail import RailKind, rail_kind_for_area

    assert rail_kind_for_area(Qt.DockWidgetArea.LeftDockWidgetArea) is RailKind.VERTICAL
    assert rail_kind_for_area(Qt.DockWidgetArea.RightDockWidgetArea) is RailKind.VERTICAL
    assert (
        rail_kind_for_area(Qt.DockWidgetArea.BottomDockWidgetArea)
        is RailKind.HORIZONTAL
    )


def test_rail_kind_for_area_unsupported_is_none():
    from valisync.gui.views.dock_collapse_rail import rail_kind_for_area

    assert rail_kind_for_area(Qt.DockWidgetArea.TopDockWidgetArea) is None
    assert rail_kind_for_area(Qt.DockWidgetArea.NoDockWidgetArea) is None
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_dock_collapse_rail.py -v`
Expected: ImportError（モジュール未作成）

- [ ] **Step 3: 実装（enum＋純関数）**

`src/valisync/gui/views/dock_collapse_rail.py`:

```python
"""辺対応の折りたたみレール (edge-aware-dock-collapse)。

畳んだドックは hide され、その辺のレールに content サイズのタブが出る。左/右=縦
レール(縦書きタブ・幅を詰める)、下=横帯(横チップ・高さを詰める)。上は対象外。
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt


class RailKind(Enum):
    VERTICAL = "vertical"  # 左/右ドック — 縦レール・縦書きタブ
    HORIZONTAL = "horizontal"  # 下ドック — 横帯・横チップ


def rail_kind_for_area(area: Qt.DockWidgetArea) -> RailKind | None:
    """ドック領域からレール種別を引く。対応外 (上/なし) は None。"""
    if area in (
        Qt.DockWidgetArea.LeftDockWidgetArea,
        Qt.DockWidgetArea.RightDockWidgetArea,
    ):
        return RailKind.VERTICAL
    if area == Qt.DockWidgetArea.BottomDockWidgetArea:
        return RailKind.HORIZONTAL
    return None


# 展開シェブロンは「開く方向」を指す。
EXPAND_ICON: dict[Qt.DockWidgetArea, str] = {
    Qt.DockWidgetArea.LeftDockWidgetArea: "chevron_right",
    Qt.DockWidgetArea.RightDockWidgetArea: "chevron_left",
    Qt.DockWidgetArea.BottomDockWidgetArea: "chevron_up",
}
```

- [ ] **Step 4: GREEN 確認**

Run: `uv run pytest tests/gui/test_dock_collapse_rail.py -v`
Expected: PASS（2件）

- [ ] **Step 5: 上配置禁止のテストを書く**

`tests/gui/test_main_window.py` に追加:

```python
def test_docks_forbid_top_area(qtbot):
    from PySide6.QtCore import Qt

    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    for dock in (win.file_dock, win.channel_dock, win.diagnostics_dock):
        areas = dock.allowedAreas()
        assert not (areas & Qt.DockWidgetArea.TopDockWidgetArea), dock.objectName()
        assert areas & Qt.DockWidgetArea.RightDockWidgetArea
        assert areas & Qt.DockWidgetArea.LeftDockWidgetArea
        assert areas & Qt.DockWidgetArea.BottomDockWidgetArea
```

- [ ] **Step 6: RED 確認**

Run: `uv run pytest tests/gui/test_main_window.py::test_docks_forbid_top_area -v`
Expected: FAIL（既定 allowedAreas は AllDockWidgetAreas で Top を含む）

- [ ] **Step 7: 実装（3ドックに setAllowedAreas）**

`main_window.py` の各ドック生成直後（`setFeatures` の隣）に追加。3ドックとも同じ:

```python
        self.file_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
```

同様に `self.channel_dock.setAllowedAreas(...)`・`self.diagnostics_dock.setAllowedAreas(...)` を各生成直後に追加（diagnostics_dock は `DiagnosticsView.__init__` 後の 140行付近）。

- [ ] **Step 8: GREEN＋ゲート＋コミット**

```bash
uv run pytest tests/gui/test_main_window.py::test_docks_forbid_top_area tests/gui/test_dock_collapse_rail.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/dock_collapse_rail.py src/valisync/gui/views/main_window.py tests/gui/test_dock_collapse_rail.py tests/gui/test_main_window.py
git commit -m "feat(gui): 上配置禁止+辺判定ヘルパ (edge-aware-collapse Task 3)"
```

---

### Task 4: DockCollapseRail widget（配置非依存・タブ内部）

**Files:**
- Modify: `src/valisync/gui/views/dock_collapse_rail.py`（`_VerticalLabel`・`_CollapsedDockTab`・`DockCollapseRail` を追加）
- Test: `tests/gui/test_dock_collapse_rail.py`

**Interfaces:**
- Consumes: `RailKind`・`rail_kind_for_area`・`EXPAND_ICON`（Task 3）・`icons.icon`（Task 2）
- Produces: `DockCollapseRail(edge: Qt.DockWidgetArea, parent=None)` with
  `expand_requested = Signal(QDockWidget)`・`add_tab(dock: QDockWidget, title: str, order: int) -> None`・
  `remove_tab(dock: QDockWidget) -> None`・`is_empty() -> bool`（Task 5 が消費）

- [ ] **Step 1: 失敗するテストを書く（レールの内部挙動）**

`tests/gui/test_dock_collapse_rail.py` に追加:

```python
def _make_dock(qtbot, name: str):
    from PySide6.QtWidgets import QDockWidget

    dock = QDockWidget(name)
    dock.setObjectName(name)
    qtbot.addWidget(dock)
    return dock


def test_rail_hidden_when_empty_shown_when_tab_added(qtbot):
    from valisync.gui.views.dock_collapse_rail import DockCollapseRail

    rail = DockCollapseRail(Qt.DockWidgetArea.RightDockWidgetArea)
    qtbot.addWidget(rail)
    rail.show()
    assert rail.is_empty()
    assert rail.isHidden()  # 空なら隠れる
    dock = _make_dock(qtbot, "file_dock")
    rail.add_tab(dock, "File Browser", 0)
    assert not rail.is_empty()
    assert not rail.isHidden()


def test_rail_remove_tab_hides_when_last_removed(qtbot):
    from valisync.gui.views.dock_collapse_rail import DockCollapseRail

    rail = DockCollapseRail(Qt.DockWidgetArea.RightDockWidgetArea)
    qtbot.addWidget(rail)
    rail.show()
    dock = _make_dock(qtbot, "file_dock")
    rail.add_tab(dock, "File Browser", 0)
    rail.remove_tab(dock)
    assert rail.is_empty()
    assert rail.isHidden()


def test_rail_tab_click_emits_expand_requested_with_dock(qtbot):
    from valisync.gui.views.dock_collapse_rail import DockCollapseRail

    rail = DockCollapseRail(Qt.DockWidgetArea.RightDockWidgetArea)
    qtbot.addWidget(rail)
    dock = _make_dock(qtbot, "file_dock")
    rail.add_tab(dock, "File Browser", 0)
    seen: list = []
    rail.expand_requested.connect(seen.append)
    rail._tabs[dock].clicked.emit()  # タブ本体クリック相当
    assert seen == [dock]


def test_rail_tabs_ordered_by_order_index(qtbot):
    from valisync.gui.views.dock_collapse_rail import DockCollapseRail

    rail = DockCollapseRail(Qt.DockWidgetArea.RightDockWidgetArea)
    qtbot.addWidget(rail)
    ch = _make_dock(qtbot, "channel_dock")
    fi = _make_dock(qtbot, "file_dock")
    rail.add_tab(ch, "Channel Browser", 1)  # 先に order=1 を入れても
    rail.add_tab(fi, "File Browser", 0)  # order=0 が上に来る
    lay = rail._layout
    idx_fi = lay.indexOf(rail._tabs[fi])
    idx_ch = lay.indexOf(rail._tabs[ch])
    assert idx_fi < idx_ch
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_dock_collapse_rail.py -v`
Expected: FAIL（`DockCollapseRail` 未定義）

- [ ] **Step 3: 実装（縦書きラベル＋タブ＋レール）**

`dock_collapse_rail.py` に追加（先頭 import を拡張）:

```python
from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QBoxLayout,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from valisync.gui.theme import icons

_TAB_ICON_PX = 14


class _VerticalLabel(QLabel):
    """テキストを 90° 回転して描く縦書きラベル (縦タブ用)。"""

    def paintEvent(self, event: object) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.translate(self.width(), 0)
        painter.rotate(90)
        painter.drawText(
            QRect(0, 0, self.height(), self.width()),
            Qt.AlignmentFlag.AlignCenter,
            self.text(),
        )

    def sizeHint(self) -> QSize:
        s = super().sizeHint()
        return QSize(s.height(), s.width())  # 縦横入替

    def minimumSizeHint(self) -> QSize:
        s = super().minimumSizeHint()
        return QSize(s.height(), s.width())


class _CollapsedDockTab(QWidget):
    """畳んだドック 1 個ぶんのタブ (クリックで展開のみ)。"""

    clicked = Signal()

    def __init__(
        self,
        title: str,
        kind: RailKind,
        expand_icon_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        chevron = QLabel()
        chevron.setPixmap(icons.icon(expand_icon_name).pixmap(_TAB_ICON_PX, _TAB_ICON_PX))
        lay: QBoxLayout
        if kind is RailKind.VERTICAL:
            lay = QVBoxLayout(self)
            label: QLabel = _VerticalLabel(title)
        else:
            lay = QHBoxLayout(self)
            label = QLabel(title)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(3)
        lay.addWidget(chevron, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(label, 0, Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("CollapsedDockTab")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()


class DockCollapseRail(QWidget):
    """1 辺ぶんの畳みレール。content サイズのタブを位置順に積む。空なら隠れる。"""

    expand_requested = Signal(QDockWidget)

    def __init__(
        self, edge: Qt.DockWidgetArea, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._edge = edge
        self._kind = rail_kind_for_area(edge) or RailKind.VERTICAL
        self._expand_icon = EXPAND_ICON.get(edge, "chevron_left")
        self._tabs: dict[QDockWidget, _CollapsedDockTab] = {}
        self._orders: dict[QDockWidget, int] = {}
        self.setObjectName("DockCollapseRail")
        layout: QBoxLayout
        if self._kind is RailKind.VERTICAL:
            layout = QVBoxLayout(self)  # 上寄せ (末尾 stretch)
        else:
            layout = QHBoxLayout(self)  # 左寄せ (末尾 stretch)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)
        layout.addStretch(1)
        self._layout = layout
        self.setVisible(False)  # 空なので隠す

    def is_empty(self) -> bool:
        return not self._tabs

    def add_tab(self, dock: QDockWidget, title: str, order: int) -> None:
        if dock in self._tabs:
            return
        tab = _CollapsedDockTab(title, self._kind, self._expand_icon)
        tab.clicked.connect(lambda: self.expand_requested.emit(dock))
        self._tabs[dock] = tab
        self._orders[dock] = order
        # order 昇順で挿入位置を決める (末尾 stretch の手前)。
        insert_at = 0
        for existing, existing_tab in self._tabs.items():
            if existing is dock:
                continue
            if self._orders[existing] < order:
                insert_at = max(insert_at, self._layout.indexOf(existing_tab) + 1)
        self._layout.insertWidget(insert_at, tab)
        self.setVisible(True)

    def remove_tab(self, dock: QDockWidget) -> None:
        tab = self._tabs.pop(dock, None)
        if tab is None:
            return
        self._orders.pop(dock, None)
        self._layout.removeWidget(tab)
        tab.deleteLater()
        if self.is_empty():
            self.setVisible(False)
```

（配色は app-wide Fusion palette＋既存 chrome トークンを継承。gutter の境界線やタブ hover が必要なら Task 5 で `qss.py` に `#DockCollapseRail`/`#CollapsedDockTab` セレクタを**既存 chrome トークン値のみ**で追加＝新トークンなし。）

- [ ] **Step 4: GREEN＋ゲート＋コミット**

```bash
uv run pytest tests/gui/test_dock_collapse_rail.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/dock_collapse_rail.py tests/gui/test_dock_collapse_rail.py
git commit -m "feat(gui): DockCollapseRail widget+縦書きタブ (edge-aware-collapse Task 4)"
```

（`event: object` の noqa/型は既存 realgui/view の paintEvent 群と同様。mypy が `event.button()`/`position()` に文句を言う場合は `from PySide6.QtGui import QMouseEvent` で型注釈。）

---

### Task 5: MainWindow 配線 — 畳み機構を hide＋レールへ差し替え

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`・`src/valisync/gui/views/collapsible_dock_title_bar.py`
- Test: `tests/gui/test_main_window.py`・`tests/gui/test_collapsible_dock_title_bar.py`

**Interfaces:**
- Consumes: `CentralWithRails`（Task 1）・`DockCollapseRail`/`rail_kind_for_area`/`RailKind`（Task 3/4）
- Produces: MainWindow の3ドックが辺対応で畳める（hide＋レールタブ）・`dockCollapsed` 永続が新機構

- [ ] **Step 1: CollapsibleDockTitleBar を「collapse 要求を出す」役へ改修（失敗するテスト）**

`tests/gui/test_collapsible_dock_title_bar.py` に追加:

```python
def test_chevron_emits_collapse_requested(qtbot):
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, _content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    win.show()
    seen: list = []
    bar.collapse_requested.connect(lambda: seen.append(True))
    bar._toggle_button.click()
    assert seen == [True]


def test_chevron_disabled_while_floating(qtbot):
    from valisync.gui.views.collapsible_dock_title_bar import CollapsibleDockTitleBar

    win, dock, _content = _dock_in_window(qtbot)
    bar = CollapsibleDockTitleBar(dock, win, "D")
    dock.setTitleBarWidget(bar)
    win.show()
    assert bar._toggle_button.isEnabled()
    dock.setFloating(True)
    assert not bar._toggle_button.isEnabled()  # フロート中は無効
    dock.setFloating(False)
    assert bar._toggle_button.isEnabled()
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_collapsible_dock_title_bar.py -k "collapse_requested or floating" -v`
Expected: FAIL（`collapse_requested` 未定義・フロートで無効化しない）

- [ ] **Step 3: CollapsibleDockTitleBar 改修**

`collapsible_dock_title_bar.py`: `collapse_requested` Signal 追加・chevron を「クランプ」でなく `collapse_requested.emit()` に変更・`topLevelChanged` でフロート中グレーアウト。`set_collapsed`/`is_collapsed`/`collapsed_changed`/maxHeight クランプは撤去（畳み機構は MainWindow が担う）。差し替え後の全文:

```python
"""ドック共通の展開時タイトルバー (edge-aware-dock-collapse で辺対応レールへ移行)。

QDockWidget に最小化フラグは無いため setTitleBarWidget で差す。既定タイトルバー
(フロート/閉じる)を置換するので自前で持つ。chevron は「畳み要求」を出すだけで、
実際の畳み (dock.hide()+辺レールにタブ) は MainWindow が担う。フロート中は送り先の
辺が無いので chevron を無効化する。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QToolButton,
    QWidget,
)

from valisync.gui.theme import icons


class CollapsibleDockTitleBar(QWidget):
    """chevron(畳み要求)+タイトル+フロート+閉じるを持つ展開時タイトルバー。"""

    collapse_requested = Signal()

    def __init__(
        self,
        dock: QDockWidget,
        main_window: QMainWindow,
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dock = dock
        self._main_window = main_window

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)

        self._toggle_button = QToolButton()
        self._toggle_button.setAutoRaise(True)
        self._toggle_button.setIcon(icons.icon("chevron_right"))
        self._toggle_button.setToolTip("折りたたむ")
        self._toggle_button.clicked.connect(self.collapse_requested.emit)
        lay.addWidget(self._toggle_button)

        self._title = QLabel(title)
        lay.addWidget(self._title)
        lay.addStretch(1)

        self._float_button = QToolButton()
        self._float_button.setAutoRaise(True)
        self._float_button.setText("❐")
        self._float_button.setToolTip("フロート")
        self._float_button.clicked.connect(
            lambda: self._dock.setFloating(not self._dock.isFloating())
        )
        lay.addWidget(self._float_button)

        self._close_button = QToolButton()
        self._close_button.setAutoRaise(True)
        self._close_button.setText("✕")
        self._close_button.setToolTip("閉じる")
        self._close_button.clicked.connect(self._dock.close)
        lay.addWidget(self._close_button)

        # フロート中は畳み先の辺が無いので無効化 (再ドッキングで有効化)。
        dock.topLevelChanged.connect(self._on_floating_changed)

    def _on_floating_changed(self, floating: bool) -> None:
        self._toggle_button.setEnabled(not floating)
```

- [ ] **Step 4: GREEN 確認（タイトルバー単体）**

Run: `uv run pytest tests/gui/test_collapsible_dock_title_bar.py -v`
Expected: `collapse_requested`/`floating` は PASS。**旧 API 依存テスト（`set_collapsed`/`is_collapsed`/`collapsed_changed`/`resizeDocks` spy）は FAIL/エラーになる** → Step 5 で MainWindow 側テストへ意味論を移し、タイトルバー単体からは撤去 API のテストを削除（honest 更新・隠蔽でなく機能移管）。この時点の FAIL 一覧を記録。

- [ ] **Step 5: MainWindow 配線のテストを書く（新機構）**

`tests/gui/test_main_window.py` の増分C由来テスト（`test_docks_have_collapsible_title_bars`/`test_collapse_state_roundtrips_through_qsettings`/`test_reset_layout_expands_all_docks`）を新機構へ honest 更新＋新規追加:

```python
def test_collapse_hides_dock_and_adds_rail_tab(qtbot):
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    win._collapse_dock(win.file_dock)
    assert win.file_dock.isHidden()  # ドックは hide
    rail = win._collapse_rails[win.dockWidgetArea(win.file_dock)]
    assert not rail.is_empty()  # 対応辺レールにタブ


def test_expand_from_rail_shows_dock(qtbot):
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    edge = win.dockWidgetArea(win.file_dock)
    win._collapse_dock(win.file_dock)
    win._expand_dock(win.file_dock)
    assert not win.file_dock.isHidden()
    assert win._collapse_rails[edge].is_empty()


def test_collapse_state_roundtrips_through_qsettings(qtbot):
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    win._collapse_dock(win.file_dock)
    win.save_state()
    win2 = build_main_window()
    qtbot.addWidget(win2)
    win2.show()
    assert win2.file_dock.isHidden()
    assert not win2.channel_dock.isHidden()


def test_reset_layout_expands_all_docks(qtbot):
    from valisync.gui.app import build_main_window

    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    win._collapse_dock(win.diagnostics_dock)
    win._reset_layout()
    assert not win.diagnostics_dock.isHidden()
```

- [ ] **Step 6: RED 確認**

Run: `uv run pytest tests/gui/test_main_window.py -k "collapse or reset_layout_expands or rail" -v`
Expected: FAIL（`_collapse_dock`/`_collapse_rails`/`_expand_dock` 未定義）

- [ ] **Step 7: MainWindow 実装（レール生成＋配線＋永続差し替え）**

`main_window.py`:

(a) Task 1 の `CentralWithRails` にレールを据え、辞書に保持。増分C由来の `_collapsible_bars` 構築ブロック（145-155行）を次に差し替え:

```python
        # ── 辺対応の折りたたみ (edge-aware-dock-collapse) ────────────────────
        from valisync.gui.views.dock_collapse_rail import DockCollapseRail

        self._collapse_rails: dict[Qt.DockWidgetArea, DockCollapseRail] = {}
        for edge in (
            Qt.DockWidgetArea.LeftDockWidgetArea,
            Qt.DockWidgetArea.RightDockWidgetArea,
            Qt.DockWidgetArea.BottomDockWidgetArea,
        ):
            rail = DockCollapseRail(edge)
            rail.expand_requested.connect(self._expand_dock)
            self._central_with_rails.set_rail(edge, rail)
            self._collapse_rails[edge] = rail

        self._collapsible_bars: dict[str, CollapsibleDockTitleBar] = {}
        self._collapsed_docks: set[str] = set()
        self._expanded_extent: dict[str, int] = {}
        self._dock_rail_order = {  # 辺上の位置順 (File 上/Channel 下)
            "file_dock": 0,
            "channel_dock": 1,
            "diagnostics_dock": 0,
        }
        for dock, title in (
            (self.file_dock, "File Browser"),
            (self.channel_dock, "Channel Browser"),
            (self.diagnostics_dock, "Diagnostics"),
        ):
            bar = CollapsibleDockTitleBar(dock, self, title)
            dock.setTitleBarWidget(bar)
            bar.collapse_requested.connect(
                lambda d=dock: self._collapse_dock(d)
            )
            self._collapsible_bars[dock.objectName()] = bar
```

注意: この配線ブロックは `self._central_with_rails` 生成（Task 1・165行付近の setCentralWidget 差し替え）**より後**に置く必要がある。増分C同様、`_restore_state()` 呼び出しより前であること。→ `setCentralWidget` を先に実行し、その直後にこの配線を置く（順序を実装時に確認）。

(b) collapse/expand メソッドを追加（`_apply_saved_collapse` 近く）:

```python
    def _dock_extent(self, dock: QDockWidget) -> int:
        area = self.dockWidgetArea(dock)
        from valisync.gui.views.dock_collapse_rail import RailKind, rail_kind_for_area

        kind = rail_kind_for_area(area)
        return dock.width() if kind is RailKind.VERTICAL else dock.height()

    def _collapse_dock(self, dock: QDockWidget) -> None:
        if dock.isFloating():
            return  # フロート中は畳まない (chevron も無効)
        area = self.dockWidgetArea(dock)
        rail = self._collapse_rails.get(area)
        if rail is None:
            return  # 対応外の辺 (通常起きない — 上は禁止済み)
        name = dock.objectName()
        self._expanded_extent[name] = self._dock_extent(dock)
        dock.hide()
        title = {
            "file_dock": "File Browser",
            "channel_dock": "Channel Browser",
            "diagnostics_dock": "Diagnostics",
        }[name]
        rail.add_tab(dock, title, self._dock_rail_order.get(name, 0))
        self._collapsed_docks.add(name)
        self._save_dock_collapsed()

    def _expand_dock(self, dock: QDockWidget) -> None:
        from valisync.gui.views.dock_collapse_rail import RailKind, rail_kind_for_area

        name = dock.objectName()
        for rail in self._collapse_rails.values():
            rail.remove_tab(dock)
        dock.show()
        area = self.dockWidgetArea(dock)
        extent = self._expanded_extent.get(name)
        kind = rail_kind_for_area(area)
        if extent is not None and kind is not None:
            orient = (
                Qt.Orientation.Horizontal
                if kind is RailKind.VERTICAL
                else Qt.Orientation.Vertical
            )
            self.resizeDocks([dock], [extent], orient)
        self._collapsed_docks.discard(name)
        self._save_dock_collapsed()
```

(c) 永続を新機構へ差し替え（559-581行の `_dock_collapsed_map`/`_apply_saved_collapse`）:

```python
    def _dock_collapsed_map(self) -> dict[str, bool]:
        return {
            name: (name in self._collapsed_docks)
            for name in self._collapsible_bars
        }

    def _save_dock_collapsed(self, *_: object) -> None:
        settings = QSettings(_ORG, _APP)
        settings.setValue("dockCollapsed", self._dock_collapsed_map())

    def _apply_saved_collapse(self) -> None:
        """QSettings の collapse 状態を新機構 (hide+レール) で再適用。

        restoreState はドックの配置/サイズを戻すが「畳み=hide+レールタブ」は
        runtime 状態で乗らないため、_restore_state/_reset_layout の後に再適用する
        (corner 再適用と同型)。
        """
        settings = QSettings(_ORG, _APP)
        saved = settings.value("dockCollapsed") or {}
        if not isinstance(saved, dict):
            return
        docks = {d.objectName(): d for d in self._collapsible_bars_docks()}
        for name, dock in docks.items():
            if bool(saved.get(name, False)):
                self._collapse_dock(dock)

    def _collapsible_bars_docks(self) -> list[QDockWidget]:
        return [self.file_dock, self.channel_dock, self.diagnostics_dock]
```

(d) `_reset_layout`（592行付近）を新機構へ:

```python
    def _reset_layout(self) -> None:
        """Restore the default dock/toolbar arrangement captured at startup (SH-11)."""
        for dock in list(self._collapsible_bars_docks()):
            if dock.objectName() in self._collapsed_docks:
                self._expand_dock(dock)
        self.restoreState(self._default_state)
        self._apply_dock_corners()  # restoreState reset the FU-10 corner; re-apply
```

- [ ] **Step 8: GREEN＋full suite＋ゲート＋コミット**

```bash
uv run pytest tests/gui/test_main_window.py tests/gui/test_collapsible_dock_title_bar.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
```

増分C由来の旧テストで撤去 API（`titleBarWidget().set_collapsed`/`is_collapsed`）を参照するものは新機構（`_collapse_dock`/`isHidden`）へ honest 更新。realgui の旧 collapsible テスト（`tests/realgui/test_collapsible_docks_realclick.py`）は Task 6 で新機構へ移行するため、この Task では **collect が通ること**のみ確認（実 --realgui は Task 6）。full suite が green になったらコミット:

```bash
git add src/valisync/gui/views/main_window.py src/valisync/gui/views/collapsible_dock_title_bar.py tests/gui/test_main_window.py tests/gui/test_collapsible_dock_title_bar.py
git commit -m "feat(gui): 畳み機構を hide+辺レールへ差し替え+永続 (edge-aware-collapse Task 5)"
```

---

### Task 6: realgui（実機で辺対応に畳む・中央が実際に広がる）

**Files:**
- Modify/Replace: `tests/realgui/test_collapsible_docks_realclick.py`（新機構へ移行）

コード整備はサブエージェント、実 `--realgui` 実行はコントローラ（実機・警告要）。

- [ ] **Step 1: realgui を新機構へ書き換え（コレクションまで確認）**

`tests/realgui/test_collapsible_docks_realclick.py` を新機構で書き直す: build_main_window→表示→file_dock のタイトルバー chevron を**実クリック**→ file_dock が hide＋右レールに縦タブ出現＋**中央（`_central_with_rails`）幅が実際に増加**（`width()` を実測・畳む前後で有意増加）。レールの縦タブを**実クリック**→ file_dock 再表示＋中央幅が元へ。下は diagnostics_dock で横帯を同様（中央高さ増加）。フロートボタン実クリックで chevron 無効化を確認。実 OS 入力は `tests/realgui/_realgui_input` の `at`/`LDOWN`/`LUP`、chevron/タブの物理座標はそれぞれの widget geometry から算出。`skip_unless_real_display`。**内容非可視は `dock.isHidden()`＋中央幅実測で判定**（memory gui_isvisible_true_for_offscreen_hidden_dock・gui_dock_toggle_width_change_needs_real_display_and_layout）。

collect 確認（実入力なし・安全）:
```bash
uv run pytest tests/realgui --collect-only -q
```

- [ ] **Step 2: ゲート＋コミット**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/
git add tests/realgui/test_collapsible_docks_realclick.py
git commit -m "test(realgui): 辺対応の折りたたみを実機検証へ移行 (edge-aware-collapse Task 6)"
```

- [ ] **Step 3: 実 --realgui（コントローラ）**

```bash
uv run pytest tests/realgui --realgui
```

Expected: 全 PASS。**特に「右ドックを畳むと縦レールに縦タブが出て中央が実際に広がる」「タブクリックで元幅復元」「下ドックは横帯」を実機で確認**（畳みの実効＝中央のスペース回収が効くか）。効かなければ Task 1 の配置方式を realgui 駆動で調整。

---

### Task 7: 成果物更新＋design.md（コントローラ）

コード変更なし（撮影スクリプトの `09_collapsed` は Task 1 の `_collapsible_bars` API 変更に追随する軽微修正のみ・下記）。実ディスプレイ必須。

- [ ] **Step 1: 撮影スクリプトの 09_collapsed を新機構へ追随**

`scripts/capture_ui_screenshots.py` の `09_collapsed` ブロック（増分Cで追加）は `window._collapsible_bars["diagnostics_dock"].set_collapsed(True)` を呼ぶが、`set_collapsed` は撤去された。新機構の `window._collapse_dock(window.diagnostics_dock)` ＋右ドックも畳んで縦レールを見せる形へ:

```python
        # --- 09: 辺対応の折りたたみ (右=縦レール / 下=横帯) --------------------
        window._collapse_dock(window.file_dock)
        window._collapse_dock(window.channel_dock)
        window._collapse_dock(window.diagnostics_dock)
        settle()
        grab("09_collapsed")
        window._expand_dock(window.file_dock)
        window._expand_dock(window.channel_dock)
        window._expand_dock(window.diagnostics_dock)
        settle()
```

- [ ] **Step 2: 前後差分（畳み表現の変化確認・コントローラ実機）**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_incrC2_dark --theme dark
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_incrC2_dark
```

Expected: exit 1。差分が**タイトルバー領域（chevron アイコンが chevron_right へ変更）に限定**され、展開時の通常状態（01-05）の他領域は不変であることを確認。

- [ ] **Step 3: ベースライン/カタログ/エクスポート再生成（コントローラ実機）**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_baseline --theme dark
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_dark --theme dark --catalog
uv run python scripts/export_design_tokens.py --theme dark --out design_export
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_light --theme light --catalog
uv run python scripts/export_design_tokens.py --theme light --out design_export
```

`09_collapsed` が**右=縦レール＋縦タブ / 下=横帯＋左寄せチップ**の新しい畳み姿になっていることを目視確認（Diagnostics だけでなく File/Channel も畳んだ状態）。トークン不変なので export の tokens.css/json/cards は不変。

- [ ] **Step 4: 撮影スクリプト変更のコミット**

```bash
uv run ruff check scripts/capture_ui_screenshots.py && uv run ruff format --check scripts/capture_ui_screenshots.py
git add scripts/capture_ui_screenshots.py
git commit -m "chore(capture): 09_collapsed を辺対応の畳み姿へ更新 (edge-aware-collapse Task 7)"
```

- [ ] **Step 5: docs/design.md 決定履歴へ追記**

```markdown
- 2026-07-20: 折りたたみを辺対応化（増分C 手直し・トークン変更なし）。畳む方向を
  ドックの接する辺で動的決定（左右=幅を詰めて縦レール＋縦書きタブ・下=高さを詰めて
  横帯＋左寄せチップ）。畳んだドックは hide し `DockCollapseRail` に content サイズの
  タブ。上端配置は `setAllowedAreas` で禁止。出典: 増分C(PR #131) の実機確認で
  「右ドックが横のまま薄くなるのは想定と違う」とユーザー指摘。設計は
  [edge-aware-dock-collapse spec](superpowers/specs/2026-07-20-edge-aware-dock-collapse-design.md)。PR #TBD。
```

（PR 番号は作成後に記入。DesignSync 再同期＝Ground Truth 更新＋09_collapsed 新姿・トークン不変。最終ブランチレビューは fable — memory feedback_important_reviews_use_fable。CLAUDE.md 更新は merge 後 docs PR。これらはコントローラが subagent-driven の最終フェーズで実施。）
