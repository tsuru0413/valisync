# デザイントークン増分4「テーマ三態（ライト/ダーク/オート）」実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LIGHT（Catppuccin Latte）値セット・View>テーマ radio（QSettings 永続・既定オート）・起動時 OS 検出を実装し、全面「再起動反映」でテーマ三態を成立させる。

**Architecture:** spec §11（2026-07-16 brainstorming＋アドバーサリアルレビュー確定）。`tokens.py` に `LIGHT`/`ThemeMode`/`resolve_theme`（純関数）、`apply.py` に `os_prefers_dark`/`load_theme_mode`/`save_theme_mode`/`apply_startup_theme(forced)`（Qt/IO 隔離）、`theme/settings.py`（org/app 共有・conftest 隔離対象）。撮影/エクスポートは `--theme` でテーマ別サブツリー出力。メニュー選択は保存のみ（画面不変）。

**Tech Stack:** Python 3.12 / PySide6（QStyleHints.colorScheme・QSettings・QActionGroup）/ pytest(+pytest-qt)

## Global Constraints

- **全面「再起動反映」**: メニュー選択ハンドラは `save_theme_mode` のみ呼ぶ — `set_active`/`apply_theme` を呼ばない。オートも起動時1回検出（`colorSchemeChanged` 非購読）。
- **判定不能は一律 dark**: `os_prefers_dark` は Unknown／QApplication 不在／非対応で `True`（spec §11.2）。
- **プロット面据え置きトークン**（spec §11.4）: `plot_background`/`plot_foreground`/`signal_palette`/`cursor_a`/`cursor_b`/`accent_active`/`accent_active_dark`/`grip_fill`/`drop_highlight`/`axis_move_indicator`/`axis_move_fill`/`preview_curve` は **LIGHT でも DARK と同値**。
- **メニューの二重発火回避**: `setChecked` は `triggered` 配線の**前**・`toggled` でなく `triggered` に配線（既存規約）。メニュー構築が `save_theme_mode` を呼ばないことをテストで保証。
- **QSettings 隔離**: `theme/settings.py` の `_ORG`/`_APP` を `tests/gui/conftest.py`・`tests/realgui/conftest.py` の隔離 fixture に追加（追加しないと realgui が実レジストリを汚す — spec §11.6 C2）。キーは `"theme_mode"`。
- **tokens.py は pure Python 維持**（ThemeMode/resolve_theme/LIGHT は Qt 非依存）。
- **品質ゲート（コミット毎）**: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過。
- **ブランチ**: `feature/design-tokens-r4-themes`（spec §11 コミット済み・Task 1 BASE=f53cbc1）。

## GUI テスト分析（/gui-test-plan 判定）

- T1/T2/T3/T5: 純ロジック＋Qt 設定層 → Layer A/B・E2E 不要（起動解決は Layer B のインプロセス実証）。
- T4（メニュー）: 入力イベント→ハンドラ（新規経路）→ Layer A/B 必須＋**入力経路 E2E(C) 必須**（T6 realgui: 実クリック→ステータス＋保存＋**画面即変化なし**）。
- T7（実機検証）: 描画 E2E — **dark 既定で旧ベースライン完全一致**（増分4 が既定環境の見た目を変えない凍結証明・自動アサート）＋ light 起動スクショ目視（LIGHT Ground Truth・prod スケール不要=色は規模非依存）。
- T8: realgui **全数**（起動経路 `apply_startup_theme` が全テストの `build_main_window` を通るため）＋ジャーニースモーク（無条件）。

## LIGHT（Catppuccin Latte）対応表 — テーマ化するトークンのみ（他は DARK 同値据え置き）

| トークン | LIGHT 値 | Latte 名（DARK は Mocha 対応名） |
|---|---|---|
| `surface_chip` | `Color(220, 224, 232, 230)` | Crust（alpha 維持） |
| `border_chip` | `#bcc0cc` | Surface1 |
| `text_primary` | `#4c4f69` | Text |
| `text_secondary` | `#8c8fa1` | Overlay1 |
| `close_hover` | `#d20f39` | Red |
| `busy_spinner` | `Color(30, 102, 245)` | Blue（ライト地の視認性） |
| `chrome_window` / `chrome_alternate_base` | `#eff1f5` | Base |
| `chrome_base` / `chrome_tooltip_base` | `#e6e9ef` | Mantle |
| `chrome_text` / `chrome_window_text` / `chrome_button_text` / `chrome_tooltip_text` | `#4c4f69` | Text |
| `chrome_button` | `#ccd0da` | Surface0 |
| `chrome_highlight` | `#1e66f5` | Blue |
| `chrome_highlight_text` | `#dce0e8` | Crust |
| `chrome_placeholder` | `#8c8fa1` | Overlay1 |
| `chrome_disabled_text` | `#9ca0b0` | Overlay0 |
| `error` / `text_releasing` | DARK 同値（`#c0392b`・`Color(128,128,128)`）| 両地で機能する共通値 |
| spacing / radii / typography / grid_alpha | `DARK.spacing` 等の**同一インスタンスを共有** | テーマ非依存の明示 |

---

### Task 1: tokens.py — ThemeMode / resolve_theme / LIGHT

**Files:**
- Modify: `src/valisync/gui/theme/tokens.py`
- Test: `tests/gui/test_theme_tokens.py`（追記）

**Interfaces:**
- Produces: `ThemeMode(Enum)`（`LIGHT="light"` / `DARK="dark"` / `AUTO="auto"`）／`resolve_theme(mode: ThemeMode, os_prefers_dark: bool) -> ThemeTokens`／`LIGHT: ThemeTokens`（上表＋据え置き値）。

- [ ] **Step 1: 失敗するテストを書く（test_theme_tokens.py へ追記）**

```python
def test_theme_mode_values_are_settings_strings():
    assert ThemeMode.LIGHT.value == "light"
    assert ThemeMode.DARK.value == "dark"
    assert ThemeMode.AUTO.value == "auto"


def test_resolve_theme_all_branches():
    """AUTO のみ os を参照・LIGHT/DARK は os 無視 (spec §11.2)。"""
    assert resolve_theme(ThemeMode.AUTO, os_prefers_dark=True) is DARK
    assert resolve_theme(ThemeMode.AUTO, os_prefers_dark=False) is LIGHT
    assert resolve_theme(ThemeMode.LIGHT, os_prefers_dark=True) is LIGHT
    assert resolve_theme(ThemeMode.LIGHT, os_prefers_dark=False) is LIGHT
    assert resolve_theme(ThemeMode.DARK, os_prefers_dark=True) is DARK
    assert resolve_theme(ThemeMode.DARK, os_prefers_dark=False) is DARK


def test_light_plot_pinned_tokens_match_dark():
    """プロット面据え置きトークンは両テーマ同値 (spec §11.4 — 黒キャンバス上の視認性)。"""
    pinned = [
        "plot_background",
        "plot_foreground",
        "signal_palette",
        "cursor_a",
        "cursor_b",
        "accent_active",
        "accent_active_dark",
        "grip_fill",
        "drop_highlight",
        "axis_move_indicator",
        "axis_move_fill",
        "preview_curve",
    ]
    for name in pinned:
        assert getattr(LIGHT.colors, name) == getattr(DARK.colors, name), name
    assert LIGHT.spacing is DARK.spacing
    assert LIGHT.radii is DARK.radii
    assert LIGHT.typography is DARK.typography
    assert LIGHT.grid_alpha == DARK.grid_alpha


def test_light_values_frozen_snapshot():
    """LIGHT 全テーマ化トークンの意図的 test-lock (Latte 初期値・再デザイン反復で更新)。"""
    c = LIGHT.colors
    golden = {
        "surface_chip": Color(220, 224, 232, 230),
        "border_chip": Color.from_hex("#bcc0cc"),
        "text_primary": Color.from_hex("#4c4f69"),
        "text_secondary": Color.from_hex("#8c8fa1"),
        "close_hover": Color.from_hex("#d20f39"),
        "error": Color.from_hex("#c0392b"),
        "busy_spinner": Color(30, 102, 245),
        "text_releasing": Color(128, 128, 128),
        "chrome_window": Color.from_hex("#eff1f5"),
        "chrome_window_text": Color.from_hex("#4c4f69"),
        "chrome_base": Color.from_hex("#e6e9ef"),
        "chrome_alternate_base": Color.from_hex("#eff1f5"),
        "chrome_text": Color.from_hex("#4c4f69"),
        "chrome_button": Color.from_hex("#ccd0da"),
        "chrome_button_text": Color.from_hex("#4c4f69"),
        "chrome_tooltip_base": Color.from_hex("#e6e9ef"),
        "chrome_tooltip_text": Color.from_hex("#4c4f69"),
        "chrome_highlight": Color.from_hex("#1e66f5"),
        "chrome_highlight_text": Color.from_hex("#dce0e8"),
        "chrome_placeholder": Color.from_hex("#8c8fa1"),
        "chrome_disabled_text": Color.from_hex("#9ca0b0"),
    }
    for name, expected in golden.items():
        assert getattr(c, name) == expected, name
```

import 行へ `LIGHT, ThemeMode, resolve_theme` を追加。

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_theme_tokens.py -v` — 新規4件 FAIL（ImportError）

- [ ] **Step 3: tokens.py に実装**

import へ `from enum import Enum` を追加。`_active: ThemeTokens = DARK` の**前**に:

```python
LIGHT = ThemeTokens(
    colors=Colors(
        # ── プロット面据え置き (spec §11.4 — 黒キャンバス上の視認性・両テーマ共通) ──
        plot_background=DARK.colors.plot_background,
        plot_foreground=DARK.colors.plot_foreground,
        signal_palette=DARK.colors.signal_palette,
        cursor_a=DARK.colors.cursor_a,
        cursor_b=DARK.colors.cursor_b,
        accent_active=DARK.colors.accent_active,
        accent_active_dark=DARK.colors.accent_active_dark,
        grip_fill=DARK.colors.grip_fill,
        drop_highlight=DARK.colors.drop_highlight,
        axis_move_indicator=DARK.colors.axis_move_indicator,
        axis_move_fill=DARK.colors.axis_move_fill,
        preview_curve=DARK.colors.preview_curve,
        # ── テーマ化 (Catppuccin Latte — Mocha との役割対応で写像) ──────────────
        surface_chip=Color(220, 224, 232, 230),
        border_chip=Color.from_hex("#bcc0cc"),
        text_primary=Color.from_hex("#4c4f69"),
        text_secondary=Color.from_hex("#8c8fa1"),
        close_hover=Color.from_hex("#d20f39"),
        error=Color.from_hex("#c0392b"),
        busy_spinner=Color(30, 102, 245),
        text_releasing=Color(128, 128, 128),
        chrome_window=Color.from_hex("#eff1f5"),
        chrome_window_text=Color.from_hex("#4c4f69"),
        chrome_base=Color.from_hex("#e6e9ef"),
        chrome_alternate_base=Color.from_hex("#eff1f5"),
        chrome_text=Color.from_hex("#4c4f69"),
        chrome_button=Color.from_hex("#ccd0da"),
        chrome_button_text=Color.from_hex("#4c4f69"),
        chrome_tooltip_base=Color.from_hex("#e6e9ef"),
        chrome_tooltip_text=Color.from_hex("#4c4f69"),
        chrome_highlight=Color.from_hex("#1e66f5"),
        chrome_highlight_text=Color.from_hex("#dce0e8"),
        chrome_placeholder=Color.from_hex("#8c8fa1"),
        chrome_disabled_text=Color.from_hex("#9ca0b0"),
    ),
    spacing=DARK.spacing,
    radii=DARK.radii,
    typography=DARK.typography,
    grid_alpha=DARK.grid_alpha,
)


class ThemeMode(Enum):
    """テーマ選択 (値は QSettings 保存形の文字列・spec §11.2)。"""

    LIGHT = "light"
    DARK = "dark"
    AUTO = "auto"


def resolve_theme(mode: ThemeMode, os_prefers_dark: bool) -> ThemeTokens:
    """mode と OS スキームからテーマセットを解決する純関数 (spec §11.2)。

    AUTO のみ os_prefers_dark を参照する。LIGHT/DARK は明示選択なので無視。
    """
    if mode is ThemeMode.LIGHT:
        return LIGHT
    if mode is ThemeMode.DARK:
        return DARK
    return DARK if os_prefers_dark else LIGHT
```

（注: `Colors` はフィールド順で定義する必要はないが、上記はプロット据え置き→テーマ化の意図順。フィールドは keyword 指定なので順序自由。DARK 側の `Colors` 定義順は変更しない。）

- [ ] **Step 4: GREEN → full → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_tokens.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/tokens.py tests/gui/test_theme_tokens.py
git commit -m "feat(theme): LIGHT(Latte)値セット+ThemeMode+resolve_theme 純関数 (r4 Task 1)"
```

---

### Task 2: theme/settings.py＋apply.py（mode 永続・OS 検出・起動時解決）＋conftest 隔離

**Files:**
- Create: `src/valisync/gui/theme/settings.py`
- Modify: `src/valisync/gui/theme/apply.py`
- Modify: `tests/gui/conftest.py` / `tests/realgui/conftest.py`（隔離対象に theme.settings 追加）
- Test: `tests/gui/test_theme_apply.py`（追記）

**Interfaces:**
- Produces: `settings._ORG`/`settings._APP`（`"ValiSync"`/`"ValiSync"` — main_window.py:60-61 と同値の複製・循環 import 回避）／`apply.os_prefers_dark() -> bool`／`apply.load_theme_mode() -> ThemeMode`／`apply.save_theme_mode(mode) -> None`／`apply.apply_startup_theme(forced: ThemeMode | ThemeTokens | None = None) -> None`（`ThemeTokens` 直接注入は `--debug-theme` 用・spec §11.3 の強制注入口）。

- [ ] **Step 1: 失敗するテストを書く（test_theme_apply.py へ追記）**

```python
def test_os_prefers_dark_maps_color_scheme(qapp, monkeypatch):
    """Light のみ False・Dark/Unknown は True (判定不能は一律 dark・spec §11.2)。"""
    from PySide6.QtCore import Qt

    from valisync.gui.theme import apply as apply_mod

    class _Hints:
        def __init__(self, scheme):
            self._scheme = scheme

        def colorScheme(self):
            return self._scheme

    for scheme, expected in [
        (Qt.ColorScheme.Light, False),
        (Qt.ColorScheme.Dark, True),
        (Qt.ColorScheme.Unknown, True),
    ]:
        monkeypatch.setattr(
            type(qapp), "styleHints", lambda self, s=scheme: _Hints(s)
        )
        assert apply_mod.os_prefers_dark() is expected, scheme


def test_theme_mode_roundtrip_and_unknown_fallback(qapp):
    from valisync.gui.theme.apply import load_theme_mode, save_theme_mode
    from valisync.gui.theme.tokens import ThemeMode

    assert load_theme_mode() is ThemeMode.AUTO  # 未保存 → AUTO 既定
    save_theme_mode(ThemeMode.LIGHT)
    assert load_theme_mode() is ThemeMode.LIGHT
    # 未知値 (手編集/旧バージョン) は AUTO へ silent フォールバック
    from PySide6.QtCore import QSettings

    from valisync.gui.theme import settings as theme_settings

    QSettings(theme_settings._ORG, theme_settings._APP).setValue(
        "theme_mode", "solarized"
    )
    assert load_theme_mode() is ThemeMode.AUTO


def test_apply_startup_theme_resolves_saved_mode(qapp, monkeypatch):
    """再起動反映のインプロセス実証: 保存 light → 起動解決で LIGHT active＋Latte パレット。"""
    from PySide6.QtGui import QColor, QPalette

    from valisync.gui.theme import apply as apply_mod
    from valisync.gui.theme.apply import apply_startup_theme, save_theme_mode
    from valisync.gui.theme.tokens import DARK, LIGHT, ThemeMode, active, set_active

    save_theme_mode(ThemeMode.LIGHT)
    monkeypatch.setattr(apply_mod, "os_prefers_dark", lambda: True)  # os は無視されるはず
    try:
        apply_startup_theme()
        assert active() is LIGHT
        assert qapp.palette().color(QPalette.ColorRole.Window) == QColor(
            *LIGHT.colors.chrome_window.rgba
        )
    finally:
        set_active(DARK)
        apply_mod.apply_theme()


def test_apply_startup_theme_forced_ignores_settings(qapp):
    """forced は QSettings を読まない (spec §11.3 — 撮影スクリプトの強制注入口)。"""
    from valisync.gui.theme import apply as apply_mod
    from valisync.gui.theme.apply import apply_startup_theme, save_theme_mode
    from valisync.gui.theme.tokens import DARK, LIGHT, ThemeMode, active, set_active

    save_theme_mode(ThemeMode.DARK)
    try:
        apply_startup_theme(forced=ThemeMode.LIGHT)
        assert active() is LIGHT
        # ThemeTokens 直接注入 (--debug-theme 経路)
        import dataclasses

        alt = dataclasses.replace(DARK)
        apply_startup_theme(forced=alt)
        assert active() is alt
    finally:
        set_active(DARK)
        apply_mod.apply_theme()
```

- [ ] **Step 2: RED 確認**

Run: `uv run pytest tests/gui/test_theme_apply.py -v` — 新規4件 FAIL

- [ ] **Step 3: 実装**

`src/valisync/gui/theme/settings.py`:

```python
"""QSettings の org/app 定数 — theme 層の共有点 (spec §11.2)。

main_window.py / recent_files.py の _ORG/_APP と同一値の複製 (それらから
import すると main_window → apply → main_window の循環になるため)。
テスト隔離: tests/{gui,realgui}/conftest.py が本モジュールを monkeypatch する
— ここを経由しない QSettings 書き込みを theme 層に作らないこと。
"""

from __future__ import annotations

_ORG = "ValiSync"
_APP = "ValiSync"
```

`apply.py` — import へ `from PySide6.QtCore import QSettings, Qt` と `from valisync.gui.theme import settings as theme_settings` を追加し、末尾に:

```python
_THEME_MODE_KEY = "theme_mode"


def os_prefers_dark() -> bool:
    """OS カラースキーム検出 — 判定不能 (Unknown/QApplication 不在) は一律 dark
    (現行 DARK 運用との連続性・CI の Unknown でも安定・spec §11.2)。"""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return True
    return app.styleHints().colorScheme() != Qt.ColorScheme.Light


def load_theme_mode() -> tokens.ThemeMode:
    """保存 mode を読む。未保存・未知値は AUTO (silent — _restore_state と同パターン)。"""
    raw = QSettings(theme_settings._ORG, theme_settings._APP).value(
        _THEME_MODE_KEY, tokens.ThemeMode.AUTO.value
    )
    try:
        return tokens.ThemeMode(str(raw))
    except ValueError:
        return tokens.ThemeMode.AUTO


def save_theme_mode(mode: tokens.ThemeMode) -> None:
    QSettings(theme_settings._ORG, theme_settings._APP).setValue(
        _THEME_MODE_KEY, mode.value
    )


def apply_startup_theme(
    forced: tokens.ThemeMode | tokens.ThemeTokens | None = None,
) -> None:
    """起動時テーマ確定 (spec §11.3)。

    forced は撮影スクリプト等の強制注入口 — QSettings/OS を読まない
    (--debug-theme の set_active 事前注入が起動解決に上書きされる衝突を構造回避)。
    ThemeTokens 直接注入はデバッグテーマ用。
    """
    if isinstance(forced, tokens.ThemeTokens):
        tokens.set_active(forced)
    else:
        mode = forced if forced is not None else load_theme_mode()
        tokens.set_active(tokens.resolve_theme(mode, os_prefers_dark()))
    apply_theme()
```

`tests/gui/conftest.py` — 既存 `rf` monkeypatch の後に追加（`tests/realgui/conftest.py` も同様の位置に同じ3行）:

```python
    import valisync.gui.theme.settings as theme_settings

    monkeypatch.setattr(theme_settings, "_ORG", test_org)
    monkeypatch.setattr(theme_settings, "_APP", test_app)
```

- [ ] **Step 4: GREEN → full → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_apply.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/settings.py src/valisync/gui/theme/apply.py tests/gui/conftest.py tests/realgui/conftest.py tests/gui/test_theme_apply.py
git commit -m "feat(theme): mode 永続/OS 検出/apply_startup_theme(forced) — 再起動反映の起動解決 (r4 Task 2)"
```

---

### Task 3: app.py の theme override 配線＋撮影スクリプトの --theme 化

**Files:**
- Modify: `src/valisync/gui/app.py`
- Modify: `scripts/capture_ui_screenshots.py`
- Test: `tests/gui/test_theme_apply.py`（追記）

**Interfaces:**
- Produces: `build_main_window(app_vm=None, *, theme: ThemeMode | ThemeTokens | None = None)`。撮影スクリプトは `--theme {dark,light}`（既定 dark — **ホスト OS 非依存の決定的撮影**）と `--debug-theme`（base を --theme から導出）を `build_main_window(theme=...)` 経由で注入。

- [ ] **Step 1: 失敗するテストを書く（test_theme_apply.py へ追記）**

```python
def test_build_main_window_theme_override(qtbot):
    """build_main_window(theme=...) が QSettings より優先される (spec §11.3)。"""
    from valisync.gui.app import build_main_window
    from valisync.gui.theme import apply as apply_mod
    from valisync.gui.theme.apply import save_theme_mode
    from valisync.gui.theme.tokens import DARK, LIGHT, ThemeMode, active, set_active

    save_theme_mode(ThemeMode.DARK)
    try:
        window = build_main_window(theme=ThemeMode.LIGHT)
        qtbot.addWidget(window)
        assert active() is LIGHT
    finally:
        set_active(DARK)
        apply_mod.apply_theme()
```

- [ ] **Step 2: RED 確認 → 実装**

`app.py` — import へ `from valisync.gui.theme.apply import apply_startup_theme` と `from valisync.gui.theme.tokens import ThemeMode, ThemeTokens` を追加（既存 `apply_theme` import は削除）。`build_main_window` を:

```python
def build_main_window(
    app_vm: AppViewModel | None = None,
    *,
    theme: ThemeMode | ThemeTokens | None = None,
) -> MainWindow:
    """(既存 docstring に追記) theme: テーマの強制注入 (撮影スクリプト/テスト用 —
    None なら QSettings+OS で解決・spec §11.3)。"""
    apply_startup_theme(forced=theme)
    if app_vm is None:
        session = Session()
        app_vm = AppViewModel(session)
    return MainWindow(app_vm)
```

`scripts/capture_ui_screenshots.py`:
- argparse に追加: `parser.add_argument("--theme", choices=["dark", "light"], default="dark", help="撮影テーマ (ホスト OS 設定に依存しない決定的撮影のため必須既定 dark)")`
- `_debug_theme()` を base 引数化: `def _debug_theme(base):` とし、内部の `DARK` 参照 2 箇所（`dataclasses.fields(c)` の `c = DARK.colors` と `dataclasses.replace(DARK, ...)`）を `base` に変更。
- 既存の `if args.debug_theme: set_active(_debug_theme())` ブロックを**削除**し、`build_main_window()` 呼び出しを:

```python
    from valisync.gui.theme.tokens import ThemeMode

    mode = ThemeMode.LIGHT if args.theme == "light" else ThemeMode.DARK
    if args.debug_theme:
        from valisync.gui.theme.tokens import DARK, LIGHT

        base = LIGHT if args.theme == "light" else DARK
        window = build_main_window(theme=_debug_theme(base))
    else:
        window = build_main_window(theme=mode)
```

- [ ] **Step 3: GREEN → full → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_apply.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/app.py scripts/capture_ui_screenshots.py tests/gui/test_theme_apply.py
git commit -m "feat(theme): build_main_window(theme=) 強制注入口と撮影 --theme 化 (r4 Task 3)"
```

---

### Task 4: View>テーマ メニュー（radio・保存のみ・再起動反映）

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（View メニュー・:174-181 の dock toggles と Reset Layout の間）
- Test: `tests/gui/test_main_window.py` があればそこへ、無ければ `tests/gui/test_theme_menu.py` 新規

**Interfaces:**
- Produces: `MainWindow._theme_group: QActionGroup`（テスト用アクセス）／`MainWindow._on_theme_selected(mode)`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_theme_menu.py`:

```python
"""View>テーマ radio — 排他・現 mode checked・保存のみ (再起動反映・spec §11)。"""

from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.app import build_main_window
from valisync.gui.theme import apply as apply_mod
from valisync.gui.theme.apply import load_theme_mode, save_theme_mode
from valisync.gui.theme.tokens import DARK, ThemeMode, active, set_active


def _theme_actions(window):
    return {a.text(): a for a in window._theme_group.actions()}


def test_menu_reflects_saved_mode_without_saving(qtbot: QtBot, monkeypatch):
    """構築時 checked 同期が save_theme_mode を誘発しない (二重発火ガード)。

    注意: 事前保存は patch の**前**に本物で行う (patch 後の re-import は
    patched 版を掴むため)。
    """
    save_theme_mode(ThemeMode.LIGHT)  # 本物で事前保存
    calls: list[object] = []
    monkeypatch.setattr(apply_mod, "save_theme_mode", lambda m: calls.append(m))
    window = build_main_window()
    qtbot.addWidget(window)
    acts = _theme_actions(window)
    assert acts["ライト"].isChecked()
    assert not acts["ダーク"].isChecked()
    assert calls == []  # 構築では保存が一度も呼ばれない
    set_active(DARK)
    apply_mod.apply_theme()


def test_select_saves_but_does_not_change_active(qtbot: QtBot):
    """選択は保存＋ステータスのみ — active()/画面は不変 (再起動反映)。"""
    window = build_main_window()  # 未保存 → AUTO 既定
    qtbot.addWidget(window)
    before = active()
    acts = _theme_actions(window)
    acts["ライト"].trigger()
    assert load_theme_mode() is ThemeMode.LIGHT
    assert active() is before  # 即適用しない
    assert "再起動" in window.statusBar().currentMessage()
    # 排他: ライトを選ぶとオートが unchecked
    assert acts["ライト"].isChecked()
    assert not acts["オート (OS に合わせる)"].isChecked()
    set_active(DARK)
    apply_mod.apply_theme()
```

（注: `test_menu_reflects_saved_mode_without_saving` の monkeypatch は **main_window が参照する側**を patch する必要がある — main_window.py が `from valisync.gui.theme.apply import save_theme_mode` と関数を直接 import している場合は `valisync.gui.views.main_window.save_theme_mode` を patch する。実装（Step 2）を module 参照形 `apply_mod.save_theme_mode(...)` にするか、テストの patch 先を main_window 側にするか、**実装とテストで一貫させること**。推奨: main_window は `from valisync.gui.theme import apply as theme_apply` で module import し `theme_apply.save_theme_mode(mode)` と呼ぶ — patch は `apply_mod` 側で効く。上記テストはこの推奨実装を前提とする。）

- [ ] **Step 2: RED 確認 → 実装**

`main_window.py` — import へ `from PySide6.QtGui import QActionGroup`（既存 QtGui import 群へ）と `from valisync.gui.theme import apply as theme_apply`・`from valisync.gui.theme.tokens import ThemeMode` を追加。View メニューの dock toggles の後（`view_menu.addSeparator()` の前）に:

```python
        # 増分4: テーマ三態 (再起動反映 — 選択は QSettings 保存のみ・spec §11)。
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("テーマ")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        current_mode = theme_apply.load_theme_mode()
        for label, mode in (
            ("ライト", ThemeMode.LIGHT),
            ("ダーク", ThemeMode.DARK),
            ("オート (OS に合わせる)", ThemeMode.AUTO),
        ):
            act = theme_menu.addAction(label)
            act.setCheckable(True)
            self._theme_group.addAction(act)
            # setChecked は triggered 配線の前 (排他カスケード誤発火の構造回避 —
            # gui_qactiongroup_exclusive_radio_menu の既存規約)
            act.setChecked(mode is current_mode)
            act.triggered.connect(lambda _=False, m=mode: self._on_theme_selected(m))
```

メソッド追加（`_reset_layout` の近く）:

```python
    def _on_theme_selected(self, mode: ThemeMode) -> None:
        """テーマ radio 選択 — 保存のみ。set_active/apply_theme は呼ばない (再起動反映)。"""
        theme_apply.save_theme_mode(mode)
        labels = {
            ThemeMode.LIGHT: "ライト",
            ThemeMode.DARK: "ダーク",
            ThemeMode.AUTO: "オート",
        }
        self.statusBar().showMessage(
            f"テーマを「{labels[mode]}」に変更しました。再起動で反映されます", 8000
        )
```

- [ ] **Step 3: GREEN → full → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_menu.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/views/main_window.py tests/gui/test_theme_menu.py
git commit -m "feat(gui): View>テーマ radio (保存のみ・再起動反映・排他/二重発火ガード) (r4 Task 4)"
```

---

### Task 5: エクスポートの二テーマ対応（サブツリー・グループ名・ラッパー配色）

**Files:**
- Modify: `src/valisync/gui/theme/export.py`（`_card`/`build_token_cards`/`build_ground_truth_card` に theme_label・ラッパー配色を t 由来に）
- Modify: `scripts/export_design_tokens.py`（`--theme`・サブツリー出力・purge スコープ）
- Test: `tests/gui/test_theme_export.py`（追記＋既存グループ assert 更新）

**Interfaces:**
- Produces:
  - `export.build_token_cards(t, theme_label: str) -> dict[str, str]` — group は `f"Tokens / {theme_label}"`。ラッパー `_card` の body 配色は `t.colors.chrome_window.hex`/`chrome_text.hex` 由来（固定 `#1e1e2e`/`#cdd6f4` を廃止）。
  - `export.build_ground_truth_card(name, png_bytes, theme_label: str)` — group `f"Ground Truth / {theme_label}"`。
  - `export.build_manifest(sha, tokens_json, paths, theme_label: str)` — group `f"Meta / {theme_label}"`。
  - CLI: `--theme {dark,light}`（既定 dark）→ 出力 root＝`--out/<theme>/`（例 `design_export/dark/tokens.css`）。**purge は root 配下の自テーマ subdirs のみ**。`--screenshots` 既定は `--out/screenshots_catalog_<theme>`。
- 既存テストの更新: `test_build_token_cards_structure` の group assert を `"Tokens / Dark"` に・`test_cli_writes_full_bundle` のパス期待を `out/dark/...` に・`test_build_ground_truth_card`/`test_build_manifest` に theme_label 引数。

- [ ] **Step 1: 既存テストを新シグネチャへ更新＋新テスト追記（RED）**

`test_theme_export.py` の変更点（全て明示）:
- `export.build_token_cards(DARK)` → `export.build_token_cards(DARK, "Dark")`・first_line assert を `'<!-- @dsCard group="Tokens / Dark" -->'` に。
- `export.build_ground_truth_card("02_plotted", png)` → `(..., "Dark")`・marker assert を `"Ground Truth / Dark"` に。
- `export.build_manifest("abc1234", tokens_json, [...])` → `(..., "Dark")`・marker assert を `"Meta / Dark"` に。
- `test_cli_writes_full_bundle`: 期待相対パスをすべて `dark/` 接頭（`dark/tokens.css` 等）に・stale ファイルは `out/dark/cards/stale_old_card.html` に置く。
- 追記:

```python
def test_card_wrapper_uses_theme_chrome_colors():
    """カードラッパー配色はテーマ由来 (LIGHT カードはライトな地・spec §11.5)。"""
    from valisync.gui.theme.tokens import LIGHT

    dark_cards = export.build_token_cards(DARK, "Dark")
    light_cards = export.build_token_cards(LIGHT, "Light")
    assert DARK.colors.chrome_window.hex in dark_cards["tokens/colors.html"]
    assert LIGHT.colors.chrome_window.hex in light_cards["tokens/colors.html"]
    assert '<!-- @dsCard group="Tokens / Light" -->' in light_cards["tokens/colors.html"]


def test_cli_light_theme_writes_to_light_subtree_and_keeps_dark(tmp_path):
    """--theme light は light/ サブツリーへ出力し dark/ を purge しない (spec §11.5)。"""
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    out = tmp_path / "export"
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "01_welcome.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
    base = [sys.executable, str(repo / "scripts" / "export_design_tokens.py"),
            "--out", str(out), "--screenshots", str(shots), "--sha", "deadbee"]
    assert subprocess.run([*base, "--theme", "dark"], capture_output=True).returncode == 0
    assert subprocess.run([*base, "--theme", "light"], capture_output=True).returncode == 0
    assert (out / "dark" / "tokens.css").is_file()  # light 実行後も dark が残る
    assert (out / "light" / "tokens.css").is_file()
    light_colors = (out / "light" / "tokens" / "colors.html").read_text(encoding="utf-8")
    assert "Tokens / Light" in light_colors
```

- [ ] **Step 2: RED 確認 → 実装**

`export.py` の変更（該当関数のみ・全文）:

```python
def _card(group: str, title: str, body: str, t: ThemeTokens) -> str:
    c = t.colors
    template = (
        f'<!-- @dsCard group="{group}" -->\n'
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8">\n'
        f"<title>{title}</title>\n"
        "<!-- @TOKENS_CSS -->\n"
        f"<style>body{{background:{c.chrome_window.hex};color:{c.chrome_text.hex};"
        "font-family:sans-serif;margin:16px} table{border-collapse:collapse} "
        "td,th{padding:4px 10px;text-align:left;font-size:13px}</style>\n"
        f"</head><body>\n<h2>{title}</h2>\n{body}\n</body></html>\n"
    )
    return inject_tokens_css(template, t)
```

`build_token_cards(t: ThemeTokens, theme_label: str)` — `_card("Tokens", ...)` 3 箇所を `_card(f"Tokens / {theme_label}", ...)` に（他は不変）。
`build_ground_truth_card(name, png_bytes, theme_label: str)` — marker を `f'<!-- @dsCard group="Ground Truth / {theme_label}" -->'` に。
`build_manifest(sha, tokens_json, paths, theme_label: str)` — marker を `f'<!-- @dsCard group="Meta / {theme_label}" -->'` に。

`scripts/export_design_tokens.py`:
- argparse: `parser.add_argument("--theme", choices=["dark", "light"], default="dark")`・`--screenshots` の default を `None` にし、`args.screenshots = args.screenshots or (args.out / f"screenshots_catalog_{args.theme}")` を main 冒頭で解決。
- `theme_label = "Light" if args.theme == "light" else "Dark"`・`t = LIGHT if args.theme == "light" else DARK`（`from valisync.gui.theme.tokens import DARK, LIGHT`）。
- `root = args.out / args.theme` を導入し、purge と全 `_write` の基点を `args.out` → `root` に変更（purge 対象 subdirs は root 配下のみ — 他テーマ subtree・screenshots を消さない）。
- ビルダー呼び出しへ `t`/`theme_label` を配線（`build_css(t)`/`build_json(t)`/`build_token_cards(t, theme_label)`/`inject_tokens_css(tpl_text, t)`/`build_ground_truth_card(png.stem, ..., theme_label)`/`build_manifest(sha, tokens_json, written, theme_label)`）。
- `written` の相対パスは root 相対のまま（manifest は自テーマ subtree の一覧）。

- [ ] **Step 3: GREEN → full → 品質ゲート → コミット**

```bash
uv run pytest tests/gui/test_theme_export.py -v
uv run pytest && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add src/valisync/gui/theme/export.py scripts/export_design_tokens.py tests/gui/test_theme_export.py
git commit -m "feat(design): エクスポートの二テーマ対応 (テーマ別サブツリー/グループ/ラッパー配色) (r4 Task 5)"
```

---

### Task 6: realgui — テーマ radio の実クリック（新規1本）

**Files:**
- Create: `tests/realgui/test_theme_menu_realclick.py`

**Interfaces:**
- Consumes: `tests/realgui/_realgui_input.at()`（実 OS クリック）・既存 realgui の組立て/待機イディオム（`test_graph_panel_menu_realclick.py` 等のメニュー系を参照）・QSettings 隔離（conftest — Task 2 で theme.settings も隔離済み）。

- [ ] **Step 1: realgui テストを書く**

```python
"""Layer C: View>テーマ radio の実 OS クリック (r4・spec §11.6)。

検証: (1) 実クリックで「ライト」を選ぶと QSettings に light が保存される
      (2) ステータスバーに「再起動で反映」が出る
      (3) 画面は即変化しない (active() 不変 = 再起動反映)
実マウスでメニューバー View → テーマ → ライト を辿る。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui


def _click(x: int, y: int) -> None:
    at(x, y, LDOWN)
    time.sleep(0.05)
    at(x, y, LUP)


def _phys_center(widget, rect) -> tuple[int, int]:
    dpr = widget.devicePixelRatioF()
    gp = widget.mapToGlobal(rect.center())
    return round(gp.x() * dpr), round(gp.y() * dpr)


def test_theme_radio_real_click_saves_without_repaint(
    qtbot: QtBot, tmp_path: Path
) -> None:
    skip_unless_real_display()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from valisync.gui.app import build_main_window
    from valisync.gui.theme import apply as theme_apply
    from valisync.gui.theme.tokens import ThemeMode, active

    window = build_main_window()
    qtbot.addWidget(window)
    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(screen.x() + 60, screen.y() + 60, 1120, 760)
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    for _ in range(3):
        QApplication.processEvents()

    before_active = active()
    assert theme_apply.load_theme_mode() is ThemeMode.AUTO  # 隔離済み初期状態

    # View メニューを実クリックで開く
    menubar = window.menuBar()
    view_action = next(a for a in menubar.actions() if "View" in a.text())
    _click(*_phys_center(menubar, menubar.actionGeometry(view_action)))
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None, timeout=3000)
    view_menu = QApplication.activePopupWidget()

    # テーマ submenu を実クリックで開く
    theme_action = next(a for a in view_menu.actions() if a.text() == "テーマ")
    _click(*_phys_center(view_menu, view_menu.actionGeometry(theme_action)))
    theme_menu = theme_action.menu()
    qtbot.waitUntil(lambda: theme_menu.isVisible(), timeout=3000)

    # 「ライト」を実クリック
    light_action = next(a for a in theme_menu.actions() if a.text() == "ライト")
    _click(*_phys_center(theme_menu, theme_menu.actionGeometry(light_action)))
    qtbot.waitUntil(
        lambda: theme_apply.load_theme_mode() is ThemeMode.LIGHT, timeout=3000
    )

    for _ in range(3):
        QApplication.processEvents()
    assert active() is before_active, "再起動反映のはずが active が即変化した"
    assert "再起動" in window.statusBar().currentMessage()
    with __import__("contextlib").suppress(Exception):
        QApplication.primaryScreen().grabWindow(0).save(
            str(tmp_path / "theme_menu.png")
        )
```

（`_realgui_input` の実プリミティブ名（`at`/`LDOWN`/`LUP`/`skip_unless_real_display`）は既存 realgui の import に合わせる — 差異があれば既存メニュー系テストの import 行をそのまま踏襲。合成 `qtbot.mouseClick`/`trigger()` への置き換えは禁止（Layer C 契約ガードが CI で落とす）。）

- [ ] **Step 2: 実行（実ディスプレイ）**

```bash
uv run pytest --realgui tests/realgui/test_theme_menu_realclick.py -v
```
Expected: PASS＋スクショにテーマメニューが写る。**honest-RED 検証**: `_on_theme_selected` の `theme_apply.save_theme_mode(mode)` を一時 no-op 化して FAIL（保存されない）を確認 → 戻す。

- [ ] **Step 3: 品質ゲート → コミット**

```bash
uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add tests/realgui/test_theme_menu_realclick.py
git commit -m "test(realgui): テーマ radio 実クリック — 保存+ステータス+画面不変 (r4 Task 6)"
```

---

### Task 7: 実機検証（dark 無回帰の凍結証明＋LIGHT 初撮影＋両テーマカタログ）

**Files:** なし（実行・検証・成果物差し替えのみ）

- [ ] **Step 1: dark 既定の無回帰（凍結証明・自動アサート）**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_r4_dark --theme dark
uv run python scripts/compare_screenshots.py design_export/screenshots_baseline design_export/screenshots_r4_dark
```
Expected: **全5状態 OK 完全一致 exit 0** — 増分4 が既定（AUTO→OS ダーク→DARK 相当を --theme dark で固定撮影）の見た目を一切変えない証明。NG なら本増分にリグレッション — 修正まで先へ進まない。

- [ ] **Step 2: LIGHT 初撮影＋目視（描画 E2E）**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_r4_light --theme light
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_r4_light_debug --theme light --debug-theme
```
`01_welcome`/`03_cursor`/`06_export_dialog_error` を Read で開き目視:
- クロムが Latte（明るい地 `#eff1f5`・文字 `#4c4f69`・ボタン `#ccd0da`・選択 `#1e66f5`）で一貫・文字 □ なし
- **プロット面は黒のまま**・曲線/カーソル線/アクティブ枠が黒背景で視認可（据え置きトークンの動作確認）
- readout チップがライト面＋濃文字で可読
- debug 版でクロムトークンが相異値に塗り分く（LIGHT 役割写像）
判定に迷う色は BLOCKED（トークン特定まで）。

- [ ] **Step 3: 両テーマのカタログ＋エクスポート**

```bash
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_dark --theme dark --catalog
uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog_light --theme light --catalog
uv run python scripts/export_design_tokens.py --theme dark
uv run python scripts/export_design_tokens.py --theme light
```
Expected: `design_export/dark/`＋`design_export/light/` に各17ファイル。light 実行後も dark subtree が残ること（purge スコープの実地確認）。

- [ ] **Step 4: 所見を report へ**（コミット無し — 成果物は gitignore）

---

### Task 8: docs 更新＋realgui 全数＋ゲート＋PR

**Files:**
- Modify: `docs/design.md`（「ダーク単一」→三態・運用コマンドに `--theme`・テーマ選択の説明）

- [ ] **Step 1: docs/design.md 更新**

原則5 を差し替え:
```markdown
5. **テーマ三態（ライト/ダーク/オート）** — 値セットは DARK（Mocha 系）と LIGHT（Latte 系）。
   View>テーマ で選択（QSettings 永続・既定オート=OS 追従）。**反映は再起動時**（オートの
   OS 追従も次回起動）。プロット面とその上の描画トークンはテーマ非依存（黒キャンバス据え置き）。
```
運用ループ手順4 のコマンド例を `--theme dark` / `--theme light` の2組に更新し、同期対象が `design_export/{dark,light}/` である旨を追記。

- [ ] **Step 2: realgui 全数＋ゲート4種**

```bash
uv run pytest --realgui tests/realgui/ -q   # 起動経路変更 (apply_startup_theme) の全数無回帰
uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add docs/design.md
git commit -m "docs: design.md をテーマ三態へ更新 (r4 Task 8)"
```

- [ ] **Step 3: PR 作成（コントローラ）** — 証拠: dark 完全一致ログ・LIGHT スクショ・realgui 全数・レビュー履歴。

---

### Task 9: 再同期・merge 後 docs（コントローラ実施）

- [ ] **Step 1**: DesignSync — `list_files` 突合。**旧非テーマパス（`tokens.css`・`cards/...` 等 root 直下）はローカルに無い残骸** → `finalize_plan` の deletes に列挙して削除・writes は `dark/**`＋`light/**`。`write_files` で両テーマ 34 ファイル push。
- [ ] **Step 2**: ユーザーに claude.ai/design 閲覧確認（Dark/Light グループが並ぶ）。
- [ ] **Step 3**: merge 後、CLAUDE.md Phase 行更新の docs PR。

---

## Self-Review メモ（プラン作成時に実施済み）

- spec §11 全項目に対応タスクあり: 11.2（ThemeMode/resolve/LIGHT=T1・settings/apply/conftest=T2・app/capture=T3・メニュー=T4）・11.3（forced 経路=T2/T3）・11.4（Latte 表＋据え置き=T1）・11.5（サブツリー/グループ/ラッパー/design.md=T5/T8）・11.6（テスト全項目=T1-T6・dark 完全一致=T7）・11.7 非スコープ遵守。
- 現物確認済み: `_ORG/_APP="ValiSync"`（main_window.py:60-61）・View メニュー挿入位置（:174-181）・conftest 隔離パターン（tests/gui/conftest.py 全文）・既存 export/capture の構造（増分2/3 で作成）。
- 既知の実装時注意: T4 の monkeypatch 先は「main_window が参照する側」（module import 形の推奨実装をテスト前提に明記）・T6 の realgui プリミティブ名は既存メニュー系テストの import に現物合わせ（式パターン明記済み）。
