# 増分D-1「文言 OS」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 日本語を一次言語化し、全ユーザー可視文言を `gui/strings.py`＋対訳表＋表記規約で統治する（UX-08/10/11/20/36/40/41/50/51/55 の解消）。

**Architecture:** pure Python の `src/valisync/gui/strings.py`（定数＋`mn()`/`strip_mnemonic()`）を単一の真実とし、views/VM/workers が参照。Qt 実装ダイアログは qtbase_ja QTranslator（install-once 冪等）で一括日本語化。core 診断は core 内リテラル日本語化。ニーモニクスはメニューバー面のみ（G-46 表が全数）で、実メニュー walk テストが重複と付与漏れを両方向検出する。

**Tech Stack:** PySide6（QTranslator/QLibraryInfo）・pytest（Layer A/B・fresh-process subprocess）・realgui（Layer C ①ゲート — Task 7 のみ）。

**Spec:** [docs/superpowers/specs/2026-07-22-incd-strings-os-design.md](../specs/2026-07-22-incd-strings-os-design.md)（§3 対訳表 G-01..46・§4 規約 R-01..13・§5 判断点 14 全確定・G-44/45 個別 8 訳・G-46 ニーモニクス割当表）。付録 [インベントリ](../specs/2026-07-22-incd-strings-inventory.md)は**所在特定のみ**（提案列は出典にしない）。

## Global Constraints

- **文言の唯一の出典は spec §3 対訳表＋§4 規約＋本プランの対応表**（本プランの対応表は §3/§4 から生成済み・「※spec確定」等の逐語値をそのまま使う）。付録インベントリの提案列から転記しない。
- **機械一括置換は禁止** — 対応表の旧文言 grep はサイト特定に使い、置換はサイト単位で文脈確認（短い旧文言「All」「テーマ」等は部分文字列衝突する）。
- **不変**: objectName・QSettings キー・VM キー（`visible_stat_cols` の mean/min/max/std/count）・csv_format_dialog の currentText データ値（sec/msec）・時刻表示 `{t:.3f} s`・readout precision。
- **意図的英語（変更禁止）**: 統計列見出し mean/min/max/std/count（G-29）・X 軸ラベル Time（G-30）・単位/記号/キー名/識別子/例外原文 {exc}（R-01）。
- `strings.py` は **pure Python・Qt import 禁止**・ファイル冒頭 `# ruff: noqa: RUF001, RUF002`。
- **ニーモニクス**: spec G-46 の表が全数かつ唯一の出典。コンテキストメニュー・共有 QAction（AnalysisActions）・ドックトグル・テーマ radio・Recent Files 動的項目には**付与しない**。2面共有文言は素形定数＋メニューバー側のみ `mn()` 合成。
- **QTranslator**: module-level singleton・install-once（2回呼んでも増えない）・QApplication 不在時はスキップし次回自己回復・ロード失敗は警告のみで起動継続。
- **負アサート**（`not any(... in ...)` 型）は新文言断片へ書き換えたうえで sabotage（旧挙動を一時再現）で RED を実証してから green 化。
- 各タスク末で品質ゲート: `uv run pytest`（scoped→タスク末 full）・`uv run ruff check`・`uv run ruff format`・`uv run mypy src/`。**realgui はタスク内では文言追随の書き換えのみ行い、実行は Task 7 の①ゲートに集約**（ただし書き換え時に旧文言 grep 残ゼロを確認）。
- 単一 feature ブランチ `feature/incd-strings-os`。撮影比較・ベースライン昇格・DesignSync は Task 7 の 1 回のみ。
- コミットメッセージ末尾: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

## Task 1: `strings.py` 基盤＋QTranslator（install-once）

**Files:**
- Create: `src/valisync/gui/strings.py`
- Modify: `src/valisync/gui/theme/apply.py`（`apply_startup_theme` 系列に translator 適用を追加）
- Modify: `pyproject.toml`（`[tool.ruff.lint.per-file-ignores]` の `tests/**` へ `RUF001` 追加）
- Test: `tests/gui/test_strings.py`（新規）・`tests/gui/test_theme_apply.py`（追記）

**Interfaces:**
- Produces: `strings.mn(text: str, key: str) -> str`（`f"{text}(&{key})"`）・`strings.strip_mnemonic(text: str) -> str`・以後のタスクが定数を**この module に追記**していく。`theme.apply._qt_translator`（module-level singleton・テストから状態確認可）。

- [ ] **Step 1: 失敗するテストを書く（helpers）** — `tests/gui/test_strings.py`:

```python
"""gui/strings.py — 文言 OS の基盤 (Layer A・Qt 非依存)。"""

from valisync.gui import strings


def test_mn_composes_mnemonic():
    assert strings.mn("補間方式", "I") == "補間方式(&I)"


def test_strip_mnemonic_ja_and_legacy_forms():
    assert strings.strip_mnemonic("ファイル(&F)") == "ファイル"
    assert strings.strip_mnemonic("開く(&O)…") == "開く…"
    assert strings.strip_mnemonic("&File") == "File"
    assert strings.strip_mnemonic("E&xit") == "Exit"
    # && はリテラル & (Qt 仕様) — 破壊しない
    assert strings.strip_mnemonic("A && B") == "A & B"


def test_strings_module_is_qt_free():
    import sys

    assert "PySide6" not in getattr(strings, "__qt_probe__", "")
    # import 済みモジュール群に strings 起因の PySide6 依存が無いことは
    # 「strings を単独 import した fresh プロセス」で検証する (test_theme_apply 側)。
    assert "valisync.gui.strings" in sys.modules
```

- [ ] **Step 2: RED 確認** — `uv run pytest tests/gui/test_strings.py -v` → `ModuleNotFoundError`（strings 未作成）。

- [ ] **Step 3: `src/valisync/gui/strings.py` を作成**:

```python
# ruff: noqa: RUF001, RUF002
"""GUI 文言の単一の真実 (増分D-1 文言 OS)。

- pure Python・Qt 非依存 (theme/tokens.py と同じ隔離方針)。
- 定数は日本語一次 (spec 2026-07-22-incd-strings-os-design.md §3 対訳表が出典)。
- ニーモニクスはメニューバー面のみ (G-46)。2面共有文言は素形定数＋mn() 合成。
"""

from __future__ import annotations

import re

_MNEMONIC_RE = re.compile(r"\(&[^)]\)")


def mn(text: str, key: str) -> str:
    """メニューバー掲載面のニーモニクス付与形を合成する (G-46 が割当の唯一の出典)。"""
    return f"{text}(&{key})"


def strip_mnemonic(text: str) -> str:
    """表示文言からニーモニクスを除いた素形 (テストの掴み点比較用)。"""
    text = _MNEMONIC_RE.sub("", text)
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")
```

（定数は Task 2 以降で各エリアが追記する — 本タスクは基盤のみ。）

- [ ] **Step 4: GREEN 確認** — `uv run pytest tests/gui/test_strings.py -v` → PASS。

- [ ] **Step 5: 失敗するテストを書く（QTranslator）** — `tests/gui/test_theme_apply.py` へ追記:

```python
def test_qtbase_ja_qm_exists():
    """PySide6 wheel に qtbase_ja.qm が同梱されていること (spec §2.2 の前提)。"""
    from pathlib import Path

    from PySide6.QtCore import QLibraryInfo

    tr_dir = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    assert (tr_dir / "qtbase_ja.qm").exists()


def test_translator_install_is_idempotent(qapp):
    """apply_startup_theme を2回呼んでも translator は1つ (install-once・spec §2.2)。"""
    from valisync.gui.theme import apply as theme_apply

    theme_apply.apply_startup_theme()
    first = theme_apply._qt_translator
    theme_apply.apply_startup_theme()
    assert theme_apply._qt_translator is first
    assert first is not None
```

- [ ] **Step 6: RED 確認** — `uv run pytest tests/gui/test_theme_apply.py -k translator -v` → FAIL（`_qt_translator` 属性なし）。

- [ ] **Step 7: `theme/apply.py` に translator 適用を実装** — 既存の `apply_startup_theme` の QApplication 取得後（Fusion 適用と同じ位置づけ）に呼ぶ:

```python
_qt_translator: QTranslator | None = None
_qt_translator_attempted = False


def _install_qt_translator() -> None:
    """qtbase_ja を install-once で適用する (spec §2.2)。

    QApplication 不在なら何もしない (次回呼び出しで自己回復)。ロード失敗は
    警告のみ — 自前文言 (strings.py) は translator 非依存のため起動は継続する。
    """
    global _qt_translator, _qt_translator_attempted
    app = QApplication.instance()
    if app is None or _qt_translator is not None or _qt_translator_attempted:
        return
    _qt_translator_attempted = True
    translator = QTranslator()
    tr_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_ja", tr_dir):
        app.installTranslator(translator)
        _qt_translator = translator
    else:
        logger.warning("qtbase_ja.qm のロードに失敗 — Qt 標準文言は英語のまま継続")
```

注意: `QTranslator`/`QLibraryInfo` の import は apply.py 冒頭（既に Qt を import 済みの module）。`logger` が無ければ `logging.getLogger(__name__)` を追加。

- [ ] **Step 8: fresh-process ガードテスト** — `tests/gui/test_theme_apply.py` へ追記（既存 subprocess パターン `test_theme_apply.py:345-364` と同型）:

```python
def test_dialog_buttonbox_japanese_fresh_process(tmp_path):
    """install 後に QDialogButtonBox 標準ボタンが日本語 (fresh-process — 共有 qapp の
    残留 translator と区別するため・spec §2.2/§6)。"""
    import subprocess
    import sys

    script = tmp_path / "probe.py"
    script.write_text(
        "import sys\n"
        "from PySide6.QtWidgets import QApplication, QDialogButtonBox\n"
        "app = QApplication(sys.argv)\n"
        "from valisync.gui.theme import apply as theme_apply\n"
        "theme_apply.apply_startup_theme()\n"
        "box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)\n"
        "text = box.button(QDialogButtonBox.StandardButton.Cancel).text()\n"
        "sys.exit(0 if 'キャンセル' in text else 1)\n",
        encoding="utf-8",
    )
    env_result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert env_result.returncode == 0, env_result.stderr.decode(errors="replace")
```

- [ ] **Step 9: GREEN 確認** — `uv run pytest tests/gui/test_theme_apply.py -v` → 全 PASS（既存の冪等テスト群も無回帰）。

- [ ] **Step 10: `pyproject.toml`** — `[tool.ruff.lint.per-file-ignores]` の `"tests/**"` エントリへ `"RUF001"` を追加（既存 B011 等に併記）。`uv run ruff check` green。

- [ ] **Step 11: ゲート＋コミット** — `uv run pytest tests/gui/test_strings.py tests/gui/test_theme_apply.py && uv run ruff check && uv run ruff format && uv run mypy src/` → `git commit -m "feat(gui): strings.py 基盤 (mn/strip_mnemonic)＋qtbase_ja QTranslator install-once (文言OS Task1)"`

---

## Task 2: シェル（メニューバー・ドック名 3面・ステータス・Welcome E-3・workers）＋メニュー walk テスト

**Files:**
- Modify: `src/valisync/gui/strings.py`（シェル定数追記）・`src/valisync/gui/views/main_window.py`・`src/valisync/gui/views/shell_actions.py`・`src/valisync/gui/views/welcome_view.py`・`src/valisync/gui/workers/load_worker.py`・`src/valisync/gui/workers/export_worker.py`
- Test: `tests/gui/test_menu_mnemonics.py`（新規・walk テスト）・既存テスト追随（下記リスト）

**Interfaces:**
- Consumes: `strings.mn`/`strip_mnemonic`（Task 1）。
- Produces: `strings.DOCK_FILE_BROWSER = "ファイルブラウザ"`・`DOCK_CHANNEL_BROWSER = "チャンネルブラウザ"`・`DOCK_DIAGNOSTICS = "診断"`・`REF_DIAGNOSTICS = "「診断」ドック"`（参照句 — Task 5 の channel_browser placeholder も同定数を合成）・`WELCOME_OPEN_LABEL = "計測ファイルを開く"`（E-3 — Task なし他所参照）。G-46 のメニュー定数群。

**対応表（このタスクの全サイト — 「変更なし」行は確認のみ）:**

| file:line | 現文言 | 新文言 |
|---|---|---|
| main_window.py:140 | File Browser | ファイルブラウザ |
| main_window.py:157 | Channel Browser | チャンネルブラウザ |
| main_window.py:227 | File Browser | ファイルブラウザ（L140 と同一定数） |
| main_window.py:228 | Channel Browser | チャンネルブラウザ（同上） |
| main_window.py:229 | Diagnostics | 診断 |
| main_window.py:262 | &File | ファイル(&F) |
| main_window.py:265 | Recent Files | 最近使ったファイル(&R) |
| main_window.py:268 | E&xit | 終了(&X) |
| main_window.py:275 | &View | 表示(&V) |
| main_window.py:282 | テーマ | テーマ(&T) |
| main_window.py:289 | オート (OS に合わせる) | オート（OS に合わせる） |
| main_window.py:300 | Reset Layout | レイアウトをリセット(&R) |
| main_window.py:305 | &Analyze | 解析(&A) |
| main_window.py:310 | 補間方式 | `mn(S.INTERP_METHOD, "I")`＝補間方式(&I)（素形定数はコンテキストメニュー側と共有 — Task 4） |
| main_window.py:320 | &Help | ヘルプ(&H) |
| main_window.py:321 | &About ValiSync | ValiSync について(&A) |
| main_window.py:325 | Main | メイン |
| main_window.py:332 | Data Explorer | データエクスプローラ（G-39 素形定数） |
| main_window.py:434 | ・ ⚠ {n} 件の診断（Diagnostics を参照） | ・ ⚠ 警告/エラー {n} 件（「診断」ドックを参照） |
| main_window.py:436 | ・ ℹ {n} 件の情報（Diagnostics を参照） | ・ ℹ 情報 {n} 件（「診断」ドックを参照） |
| main_window.py:647 | unknown | 表示分岐で「バージョン不明」（G-37 — `f"v{ver}"` 合成をやめ ver 不明時は文字列全体を差し替える） |
| main_window.py:651 | About ValiSync | ValiSync について（メニューと同一定数の素形） |
| main_window.py:853 | File Browser | ファイルブラウザ（DOCK_* 定数） |
| main_window.py:854 | Channel Browser | チャンネルブラウザ |
| main_window.py:855 | Diagnostics | 診断 |
| shell_actions.py:24-27 | 開く…（既存 ja） | 開く(&O)…（G-46） |
| shell_actions.py:31 | フォルダを開く… | データエクスプローラ(&D)（G-39 — mn 合成・三点リーダ除去） |
| shell_actions.py:34 | データソースフォルダを登録する | データエクスプローラを開く（statusTip — ツールバー側 L336 と同一定数） |
| shell_actions.py:38-41 | エクスポート…（既存 ja） | エクスポート(&E)…（G-46） |
| welcome_view.py:43 | 計測ファイルを開く  (Ctrl+O) | E-3: `set_open_action()` 後注入でラベル=`WELCOME_OPEN_LABEL`＋` ({shortcut})` を動的合成（二重スペース根治・`QAction.changed` でショートカット部のみ追随・`action.text()` は使わない） |
| workers/load_worker.py:160 | 読み込み中: {label or 'ファイル'} | {label or 'ファイル'} を読み込み中…（G-41 テンプレート定数） |
| workers/load_worker.py:162 | {n} ファイルを読み込み中 | {n} ファイルを読み込み中… |
| workers/export_worker.py:71 | エクスポート中: {label or 'CSV'} | {label or 'CSV'} をエクスポート中… |

QDialogButtonBox/QMessageBox 標準ボタン（main_window.py:462 OK 等）は **コード変更なし**（Task 1 の translator が供給）。

- [ ] **Step 1: 失敗する walk テストを書く** — `tests/gui/test_menu_mnemonics.py`（Layer B）:

```python
"""実メニュー walk によるニーモニクス検査 (spec §2.4 — タプル自己申告方式は不採用)。"""

import re

from valisync.gui.app import build_main_window
from valisync.gui.strings import strip_mnemonic

_MN = re.compile(r"&(?!&)(.)")

# G-46 の表 (spec §3) — メニュー名 → {付与項目の素形: キー}
G46 = {
    "ファイル": {"開く…": "o", "データエクスプローラ": "d", "最近使ったファイル": "r", "エクスポート…": "e", "終了": "x"},
    "表示": {"テーマ": "t", "レイアウトをリセット": "r"},
    "解析": {"補間方式": "i"},
    "ヘルプ": {"ValiSync について": "a"},
}
TOP_LEVEL = {"ファイル": "f", "表示": "v", "解析": "a", "ヘルプ": "h"}


def _mnemonics_of(menu):
    """QMenu 直下の {素形テキスト: ニーモニクス小文字 or None}。"""
    out = {}
    for act in menu.actions():
        if act.isSeparator():
            continue
        m = _MN.search(act.text())
        out[strip_mnemonic(act.text())] = m.group(1).lower() if m else None
    return out


def test_menubar_mnemonics_match_g46_and_unique(qtbot):
    win = build_main_window()
    qtbot.addWidget(win)
    menus = {}
    for act in win.menuBar().actions():
        menus[strip_mnemonic(act.text())] = act.menu()
        m = _MN.search(act.text())
        assert m and m.group(1).lower() == TOP_LEVEL[strip_mnemonic(act.text())]
    for name, expected in G46.items():
        got = _mnemonics_of(menus[name])
        assigned = {t: k for t, k in got.items() if k is not None}
        # 付与集合が G-46 と一致 (漏れ・過剰の双方向検出)
        assert assigned == expected, f"{name}: {assigned} != {expected}"
        # メニュー内で一意
        keys = [k for k in assigned.values()]
        assert len(keys) == len(set(keys))
```

- [ ] **Step 2: RED 確認** — `uv run pytest tests/gui/test_menu_mnemonics.py -v` → FAIL（現行は &File 等の英語）。

- [ ] **Step 3: strings.py にシェル定数を追記し、対応表どおり main_window/shell_actions/welcome/workers を置換** — 定数命名: `MENU_FILE`/`MENU_VIEW`/`MENU_ANALYZE`/`MENU_HELP`（ニーモニクス込み）・`DOCK_*`（素形）・`ACTION_OPEN`/`ACTION_DATA_EXPLORER`/`ACTION_EXPORT`/`ACTION_EXIT`/`ACTION_RESET_LAYOUT`/`MENU_RECENT`/`MENU_THEME`/`ABOUT_TITLE`・`STATUS_*_TMPL`・`BUSY_LOADING_TMPL = "{name} を読み込み中…"` 等。E-3 は `WelcomeView.set_open_action(action)` を新設し `MainWindow` が ShellActions 構築後に注入（`action.changed.connect` でショートカット部再合成）。G-37 は `_update_about` 系で `ver` 不明時にラベル全体を「バージョン不明」へ分岐。

- [ ] **Step 4: 既存テスト追随（named sites — strip_mnemonic ヘルパへ書換）**:
  - `tests/realgui/test_shell_chrome_flow.py:142` — `a.text().replace("&", "") == "View"` → `strip_mnemonic(a.text()) == "表示"`（:154 も同様）
  - `tests/realgui/test_theme_menu_realclick.py:62` — `"View" in a.text()` → `strip_mnemonic(a.text()) == "表示"`・`:68` — `a.text() == "テーマ"` → `== "テーマ(&T)"`（または strip 比較）
  - `tests/gui/test_main_window_menus.py:13,20-21` — replace イディオム → `strip_mnemonic`＋日本語期待値
  - `tests/gui/test_shell_chrome.py:42-44,82`・`tests/gui/test_main_window.py:205` — メニュータイトル期待値を日本語へ
  - `tests/realgui/test_analyze_menu_realclick.py:117` — `"Analyze" in a.text()` → `strip_mnemonic(a.text()) == "解析"`（:127/131 のカーソル項目は G-28 非付与で不変 — 確認のみ）
  - 加えて対応表の各旧文言で `uv run python -m pytest --collect-only -q` ではなく **grep**: `rg -l "File Browser|Channel Browser|Recent Files|Reset Layout|&File|&View|&Analyze|&Help|E&xit|About ValiSync|Diagnostics を参照|件の診断|フォルダを開く|データソースフォルダを登録|読み込み中:|エクスポート中:" tests/ src/` — src 残 0・tests はサイト単位で追随。

- [ ] **Step 5: GREEN＋ゲート** — `uv run pytest tests/gui/ -x -q`（realgui 除く full gui）→ PASS。`uv run pytest -q`（headless full）→ PASS。ruff/format/mypy green。

- [ ] **Step 6: コミット** — `git commit -m "feat(gui): シェル文言の日本語一次化＋G-46 ニーモニクス＋実メニュー walk テスト (文言OS Task2)"`

---

## Task 3: ダイアログ（export_csv・csv_format・expansion・signal_preview）

**Files:**
- Modify: `src/valisync/gui/strings.py`・`src/valisync/gui/views/export_csv_dialog.py`・`csv_format_dialog.py`・`expansion_dialog.py`・`signal_preview_window.py`
- Test: 既存 `tests/gui/test_export_csv_dialog.py`・`test_csv_format_dialog.py`・`test_expansion_dialog.py`・`test_signal_preview*.py` の文言追随

**Interfaces:**
- Consumes: `strings`（Task 1）。標準ボタンは translator（Task 1）供給 — コード変更なし。

**対応表:**

| file:line | 現文言 | 新文言 |
|---|---|---|
| export_csv_dialog.py:109 | 選択なし | すべて解除（G-19） |
| export_csv_dialog.py:134 | ラウンドトリップ(無指定) | ラウンドトリップ（桁数指定なし）＋setToolTip「元値を損なわない最大精度で出力します」（E-1/G-38） |
| export_csv_dialog.py:123 付近 | 統合タイムライン（既存 ja） | setToolTip「全信号を共通時間列に整列して 1 表で出力します」を追加（E-1） |
| export_csv_dialog.py:153 | Cancel（カスタムボタン） | キャンセル |
| export_csv_dialog.py:220 | 少なくとも1信号を選択してください | 少なくとも 1 つの信号を選択してください（R-07 — 数詞スペース） |
| expansion_dialog.py:60 | 上限（{n}）… | 「…上限 ({EXPANSION_COLUMN_LIMIT}) を超えます。」（R-02 半角括弧・2文目は不変） |
| signal_preview_window.py:40 | プレビューできません | この信号はプレビューできません |
| signal_preview_window.py:61 | 信号プレビュー - {key} | 信号プレビュー — {key}（R-05 em ダッシュ） |
| csv_format_dialog.py:89 ほか OK/Cancel | （標準ボタン） | 変更なし — translator 供給（テスト期待のみ「キャンセル」等へ） |
| csv_format_dialog.py:69 sec/msec | （データ値兼用） | 変更なし（R-11 意図的英語） |

- [ ] **Step 1:** strings.py へダイアログ定数を追記し対応表どおり置換（E-1 の 2 ツールチップ含む）。
- [ ] **Step 2:** 既存テスト追随 — `rg "選択なし|ラウンドトリップ\(無指定\)|少なくとも1信号|プレビューできません|信号プレビュー - " tests/ src/` → src 残 0・tests サイト単位追随。標準ボタン文言を assert しているテストが無いか `rg '"Cancel"|"OK"' tests/gui/` で確認し、あれば StandardButton enum 取得へ書換（文言比較を避ける）。
- [ ] **Step 3:** `uv run pytest tests/gui/ -q` → PASS。ゲート → `git commit -m "feat(gui): ダイアログ文言の統一 (G-19/G-38/E-1・R-02/R-05/R-07) (文言OS Task3)"`

---

## Task 4: グラフ系（コンテキストメニュー・タブ名・オフセット書式）＋コンテキストメニュー & 不在 walk

**Files:**
- Modify: `src/valisync/gui/strings.py`・`src/valisync/gui/views/graph_panel_view.py`・`graph_area_view.py`・`analysis_actions.py`（文言は既に ja — 定数参照化のみ）・`cursor_readout.py`（同）・`src/valisync/gui/viewmodels/graph_area_vm.py`
- Test: `tests/gui/test_menu_mnemonics.py`（拡張 — graph 系ビルダーの & 不在）・既存テスト追随

**Interfaces:**
- Consumes: `strings`。Produces: `strings.TAB_DEFAULT_TMPL = "タブ {n}"`（graph_area_vm が参照 — VM から strings import 可・pure）・`strings.INTERP_METHOD = "補間方式"`（素形 — Task 2 の menubar 側 `mn()` と共有）・`strings.OFFSET_TMPL = "{delta_t:+.3f} s"` 系。

**対応表:**

| file:line | 現文言 | 新文言 |
|---|---|---|
| viewmodels/graph_area_vm.py:56 | Tab 1 | タブ 1（G-40 — `TAB_DEFAULT_TMPL.format(n=1)`） |
| viewmodels/graph_area_vm.py:159 | Tab {n} | タブ {n} |
| graph_panel_view.py:815 | Time | **変更なし**（G-30 意図的英語） |
| graph_panel_view.py:1884 | Δt = {delta_t:+.3g} s | Δt = {delta_t:+.3f} s（E-4） |
| graph_panel_view.py:1962 | Δt = {delta_t:+.3g} s を適用します。対象を選択してください。 | Δt = {delta_t:+.3f} s を適用します。対象を選択してください。（E-4 — .3g→.3f のみ） |
| graph_panel_view.py:2350 | オフセット: {v:+.3f}s | オフセット: {v:+.3f} s（R-06 スペース） |
| graph_panel_view.py:2386 | 追加する Δt (秒): | 追加する Δt（秒）:（R-02 — 括り内容に日本語） |
| graph_panel_view.py:2507 | {which} カーソルの時刻 (秒): | {which} カーソルの時刻（秒）: |
| graph_panel_view.py:2538 | Add Panel | パネルを追加（G-18） |
| graph_panel_view.py:2541 | Remove Panel | パネルを削除（G-15） |
| graph_panel_view.py:2544 | Reset All Axes | すべての軸をオートフィット（G-20） |
| graph_panel_view.py:2602/2631 | ズームアウト（引き） | ズームアウト（G-21 — noqa 除去可） |
| cursor_readout.py:37/239 | mean/min/max/std/count・min（全区間） | **変更なし**（G-29 意図的英語） |
| analysis_actions.py:81/92/103 | カーソル A / カーソル B（Δ）/ カーソルを消す | **変更なし**（G-28 — strings 定数参照化のみ・ニーモニクス非付与） |

オフセット 4 画面（1884/1962/2385/2350）は `strings` の単一テンプレート群から合成し、散在 f-string を排除（R-06）。

- [ ] **Step 1: walk テスト拡張（RED）** — `tests/gui/test_menu_mnemonics.py` へ追記: graph 系ビルダー全数（`build_context_menu`〔X軸同期注入あり/なし両分岐〕・`build_curve_menu`・`build_axis_menu`・`build_x_axis_menu`・`build_cursor_menu`・`build_readout_menu`〔`build_column_menu` 含む再帰〕）を構築し、全 QAction/サブメニューtitle walk で `"&" not in text or "&&" in text` を assert（付与しない規約 — spec §2.4）。既存メニュー構築テスト（`tests/gui/test_context_menus.py`）の構築手順を流用。
- [ ] **Step 2:** 対応表どおり置換（Time/統計列は触らない）。ズームイン/ズームアウトの対称対を確認。
- [ ] **Step 3: 既存テスト追随** — named sites: `tests/gui/test_context_menus.py`（14 サイト — Add Panel/Remove Panel/Reset All Axes/ズームアウト（引き）等の等値・in 比較）・`tests/gui/test_graph_panel_view.py` の「ズームアウト（引き）」6 サイト・`tests/realgui/test_graph_panel_menu_realclick.py:83`・`tests/gui/test_graph_panel_cursor.py:662,708`・`tests/gui/test_cursor_readout.py:457,513`（不変確認）。オフセット表示 assert（`+.3g` 期待）を `rg '\.3g|\+X\.XXX|オフセット:' tests/` で全数列挙し `.3f`/スペース入りへ追随。
- [ ] **Step 4:** `uv run pytest tests/gui/ -q` → PASS。ゲート → `git commit -m "feat(gui): グラフ系文言統一＋タブ既定名 G-40＋オフセット書式 E-4＋context menu & 不在 walk (文言OS Task4)"`

---

## Task 5: ブラウザ・診断・VM・adapters（E-2・G-14・G-39 受け側・G-42/43）

**Files:**
- Modify: `src/valisync/gui/strings.py`・`src/valisync/gui/views/channel_browser_view.py`・`file_browser_view.py`・`data_explorer_view.py`・`diagnostics_view.py`・`src/valisync/gui/viewmodels/channel_browser_vm.py`・`file_browser_vm.py`・`signal_preview_vm.py`・`src/valisync/gui/adapters/signal_tree_model.py`
- Test: `tests/gui/test_diagnostics_view.py`（E-2）・walk テスト拡張（3 ブラウザのコンテキストメニュー）・既存追随

**対応表:**

| file:line | 現文言 | 新文言 |
|---|---|---|
| adapters/signal_tree_model.py:59 | Name / Unit | 名前／単位（G-43） |
| viewmodels/channel_browser_vm.py:186 | ファイル未選択 | 変更なし |
| viewmodels/channel_browser_vm.py:189 | {name} — 0 ch | {name} — 0 信号（G-42） |
| viewmodels/channel_browser_vm.py:190 | {name} — {total} ch 中 {m} 件表示 | {name} — {total} 信号中 {m} 件を表示（G-42/R-07） |
| viewmodels/file_browser_vm.py:93 | 時間範囲: {a:.3f} – {b:.3f} s（…） | 時間範囲: {a:.3f}–{b:.3f} s（…）（R-05 — en ダッシュスペースなし） |
| viewmodels/file_browser_vm.py:97 | チャンネル: {n} ch ・ 形式: {fmt} | 変更なし（G-02 技術メタ情報） |
| viewmodels/signal_preview_vm.py:56 | {lo:.4g} - {hi:.4g} s | {lo:.4g}–{hi:.4g} s（R-05） |
| channel_browser_view.py:48 | File Browser でファイルを選択すると… | ファイルブラウザでファイルを選択すると\n信号一覧を表示します（DOCK_FILE_BROWSER 定数から合成） |
| channel_browser_view.py:50 | このファイルに信号がありません（Diagnostics に詳細） | このファイルに信号がありません（詳細は「診断」ドックへ）（REF_DIAGNOSTICS 合成） |
| channel_browser_view.py:68 | Filter signals… | 信号名でフィルタ…（G-16 — export_csv_dialog.py:78 と同一定数化） |
| channel_browser_view.py:288 | Add to Active Panel | アクティブパネルへ追加（G-18・ニーモニクス非付与） |
| data_explorer_view.py:70 | Data Explorer | データエクスプローラ（G-39 素形定数） |
| data_explorer_view.py:96/97/99 | Sources / Add Source / Remove Source | データソース／データソースを追加／データソースを削除（G-09） |
| data_explorer_view.py:115 | Select Data Source Folder | データソースフォルダを選択 |
| data_explorer_view.py:228 | Load File | ファイルを開く（G-12） |
| data_explorer_view.py:231 | Remove from Data Sources | データソースから削除 |
| diagnostics_view.py:36 | ソース（列ヘッダ） | データソース（G-04・他列レベル/#/メッセージ/対象は不変） |
| diagnostics_view.py:47 | Diagnostics | 診断（DOCK_DIAGNOSTICS） |
| diagnostics_view.py:56-59 | All / Errors / Warnings / Clear | すべて／エラー／警告／クリア（G-27/G-22） |
| diagnostics_view.py:128 | str(e.seq)（0 始まり表示） | str(e.seq + 1)（E-2 — 表示のみ 1 始まり・内部 index 不変） |
| file_browser_view.py:106 | Remove File | ファイルを閉じる（G-14） |
| file_browser_view.py:115 | {filename} を閉じますか? … | {filename} を閉じますか？…（R-10 全角？） |
| file_browser_view.py:116 | Yes / No 標準ボタン | `button(Yes).setText("閉じる")`・`button(No).setText("キャンセル")`（G-14/§2.2 — 本文動詞と一致） |

- [ ] **Step 1: E-2 の RED** — `tests/gui/test_diagnostics_view.py:97-98` の seq 表示 assert（"0"/"1"）を 1 始まり期待（"1"/"2"）へ書き換え → RED 確認 → diagnostics_view.py:128 を `str(e.seq + 1)` へ → GREEN。
- [ ] **Step 2:** walk テスト拡張 — channel_browser/file_browser/data_explorer の 3 コンテキストメニュー構築経路で & 不在 assert（Task 4 と同型）。
- [ ] **Step 3:** 対応表どおり置換（G-16 は export_csv_dialog.py:78 と同一定数 `FILTER_PLACEHOLDER` へ集約）。
- [ ] **Step 4: 既存テスト追随** — named sites: `tests/realgui/test_data_explorer_realclick.py:88`（**リスト全体等値** `["Load File", "Remove from Data Sources"]` → `["ファイルを開く", "データソースから削除"]` — 項目順込み直書き）・`tests/realgui/test_channel_browser_realclick.py:105`（同型）・`tests/realgui/test_file_browser_realclick.py:99`・`tests/realgui/test_remove_file_preserves_proportions.py:230`・`tests/gui/test_file_browser_view.py:150,232`・`tests/gui/test_channel_browser_view.py:402`。grep: `rg "Filter signals|Add to Active Panel|Load File|Remove Source|Remove File|Sources|Errors|Warnings|\"All\"|\"Clear\"|Name.*Unit" tests/ src/`（短語はサイト確認必須）。
- [ ] **Step 5:** `uv run pytest tests/gui/ -q` → PASS。ゲート → `git commit -m "feat(gui): ブラウザ/診断/VM/adapters 文言統一 (G-04/09/12/14/16/27/39/42/43・E-2) (文言OS Task5)"`

---

## Task 6: core 診断・例外（G-03/33-38/44/45）＋同一性テスト＋負アサート棚卸し

**Files:**
- Modify: `src/valisync/core/loaders/mdf_loader.py`・`csv_loader.py`・`csv_format_detector.py`（確認のみ — 対応表対象行なし）・`src/valisync/core/session.py`・`src/valisync/core/models/format_def.py`・`signal.py`・`src/valisync/core/export/csv_exporter.py`
- Test: `tests/test_loaders.py`・`tests/test_demo_mf4.py`・`tests/test_session.py`・`tests/test_format_def*.py`・`tests/test_csv_exporter*.py` ほか文言依存テスト全数＋新規同一性テスト

**対応表（G-44/45 の 8 訳は spec §3 の個別表が逐語出典 — 下表はそれ以外含む全サイト）:**

| file:line | 現文言 | 新文言 |
|---|---|---|
| mdf_loader.py:108 | Signal '{base}': {shape}を {n} 本に展開 | 信号 '{base}': {shape}を {n} 本に展開（G-03） |
| mdf_loader.py:252 | File not found or not accessible: {p} | ファイルが見つからないか、アクセスできません: {p}（G-34） |
| mdf_loader.py:265 | Failed to parse MDF '{f}': {exc} | MDF '{f}' の解析に失敗しました: {exc}（R-08） |
| mdf_loader.py:295 | Signal '{n}': 展開列数 {n} が上限 {l} を超えるためスキップ | 信号 '{n}': …（G-03 のみ） |
| mdf_loader.py:335 | Failed to read channels from '{f}': {exc} | '{f}' のチャンネル読み取りに失敗しました: {exc}（R-08・G-02 チャンネル=MDF 文脈） |
| mdf_loader.py:440 | Signal '{n}': 非有限タイムスタンプを含むため skip（…） | 信号 '{n}': 非有限タイムスタンプを含むためスキップ（…）（G-03/G-33） |
| mdf_loader.py:477 | Signal '{n}' has non-numeric values, skipped: dtype {d} | 信号 '{n}': 非数値型のためスキップ（dtype {d}）（G-03/G-33） |
| mdf_loader.py:492 | Signal '{n}': 非単調 {n} 箇所・… | 信号 '{n}': …（G-03 のみ） |
| csv_loader.py:40 | File not found or not accessible: {p} | ファイルが見つからないか、アクセスできません: {p}（G-34 — mdf と**同一文字列**） |
| csv_loader.py:53 | Cannot read '{f}': {exc} | '{f}' の読み込みに失敗しました: {exc} |
| csv_loader.py:72 | Expected header row but file is empty | ヘッダ行が必要ですが、ファイルが空です |
| csv_loader.py:85 | Header has {n} columns, expected at least {m} | ヘッダの列数が {n} 列です（{m} 列以上が必要） |
| csv_loader.py:157 | Row has {n} columns, expected at least {m} | 行の列数が {n} 列です（{m} 列以上が必要） |
| csv_loader.py:174 | Non-numeric timestamp {ts!r} | 非数値のタイムスタンプ {ts!r}（R-01 repr 維持） |
| csv_loader.py:189 | （既存 ja） | 非有限タイムスタンプ {ts!r}（時刻軸が破損）（!r 維持のまま） |
| csv_loader.py:212 | Non-numeric value {v!r} in signal column | 信号列に非数値の値 {v!r} |
| csv_loader.py:260 | '{name}': 非有限値 {n} 個（…） | 信号 '{name}': 非有限値 {n} 個（…）（G-03） |
| models/signal.py:36 | timestamps contains non-finite value at index {i} | 時刻列の {i} 番目に非有限値が含まれています |
| session.py:52 | failed to load {p}: {msgs} | {p} の読み込みに失敗しました: {msgs} |
| session.py:153 | CSV files require a FormatDefinition | CSV の読み込みにはフォーマット定義が必要です（G-35） |
| session.py:160 | no loader supports file: {p} | 対応していないファイル形式です: {p}（G-36） |
| models/format_def.py:37/41/45/49/54 | （5 件） | **spec §3 G-44 個別表の逐語値**（時間列/信号列/名前 — {name!r} 維持） |
| export/csv_exporter.py:32/35/37 | （3 件） | **spec §3 G-45 個別表の逐語値** |
| format_def_manager.py | （例外 2 件） | **変更なし**（非到達 — spec §2.3 スコープ外） |

- [ ] **Step 1: 同一性テスト（RED→GREEN）** — `tests/test_loaders.py` へ:

```python
def test_file_not_found_message_identical_across_loaders():
    """G-34: 2 ローダーの同一原文は同一訳を恒久強制 (writer のコピー先揺れ防止)。"""
    import inspect

    from valisync.core.loaders import csv_loader, mdf_loader

    needle = "ファイルが見つからないか、アクセスできません:"
    assert needle in inspect.getsource(csv_loader)
    assert needle in inspect.getsource(mdf_loader)
```

- [ ] **Step 2: 負アサート棚卸し（プロトコル必須）** — `rg -n "not any|not in" tests/ | rg -i "message|msg|text"` で全数列挙。既知 3 件は必ず含む: `tests/test_loaders.py:476-479`（"non-numeric"）・`tests/test_loaders.py:591-593`（"skipped"）・`tests/test_demo_mf4.py:227-232`（"skipped"）。各件: (a) 新文言断片（「非数値型」「スキップ」）へ書換、(b) **sabotage** — loader の該当分岐を一時的に旧挙動へ戻し（例: 477 の skip 分岐を無効化して TurnSig をテキスト化）テストが RED になることを確認、(c) sabotage を戻し GREEN。英語トークン grep（`rg "skipped|non-numeric|not accessible|columns, expected" tests/`）で残存ゼロ確認。
- [ ] **Step 3:** 対応表＋G-44/45 個別表どおり置換。肯定形の文言依存テスト（`tests/test_loaders.py:757-759` 等）も同時追随。
- [ ] **Step 4:** `uv run pytest tests/ -q --ignore=tests/realgui` → PASS。ゲート → `git commit -m "feat(core): 診断・例外文言の日本語一次化 (G-03/33-38/44/45)＋同一性テスト＋負アサート sabotage-RED 棚卸し (文言OS Task6)"`

---

## Task 7: 凍結検証・①ゲート・同期・ドキュメント

**Files:**
- Modify: `scripts/compare_screenshots.py`（viewport crop 比較モード）・`scripts/capture_ui_screenshots.py`（プロット viewport 矩形のメタ JSON 出力）
- Modify: `docs/design.md`（表記規約節＋決定履歴）・`CLAUDE.md`（Phase 行）・`docs/uiux-adversarial-review-catalog.md`（解消マーク — UX-10/36/40/41/50/51/55 全・UX-08/11/20/55 全または部分・UX-11 の supersede 注記）
- 実行: realgui フル・撮影前後比較・ベースライン昇格・DesignSync 再同期

- [ ] **Step 1: viewport crop 比較モード（TDD）** — capture 側: 各状態保存時に `{state}.viewport.json`（プロット viewport の grab 画像内矩形 `{x,y,w,h}` — `GraphPanelView` の plot viewport geometry を window 座標へ mapTo して記録）。compare 側: `--crop-meta` 指定時、両画像の当該矩形 crop を比較し不一致なら exit 1。Layer A テスト: 合成 PNG＋メタ JSON で crop 一致/不一致の両方向を検証。
- [ ] **Step 2: 撮影前後比較** — main 由来の既存ローカルベースライン（無ければ `git stash` せず main を別 worktree で撮影）に対し、本ブランチで `uv run python scripts/capture_ui_screenshots.py --catalog --theme dark`／`--theme light` → `compare_screenshots.py --diff-out` で **18 枚の赤マスクを目視**（差分がテキスト＋テキスト起因のコントロール寸法変化に限られること）＋ **viewport crop 機械一致**。想定差分: E-1（ツールチップは非表示 — 差分なしのはず）・E-2（# 列）・E-3（CTA）・E-4（オフセット表示は撮影状態に含まれる場合のみ）・E-5（標準ボタン「キャンセル」等・Data Explorer 列ヘッダ）。
- [ ] **Step 3: ①ゲート（/gui-verify 準拠）** — `uv run pytest tests/realgui/ --realgui -q` フル pass＋証拠添付: (a) build_main_window 経由手順で QDialogButtonBox が「キャンセル」表示のスクショ、(b) Alt→F/V/A/H＋G-46 配下項目の実キー到達（実 OS 入力）、(c) 主要ジャーニー（開く→メニュー→右クリック→エクスポート→診断→Data Explorer〔QFileSystemModel ヘッダ日本語〕）スクショ目視。
- [ ] **Step 4: ベースライン昇格＋再撮影 compare exit 0＋DesignSync** — 新撮影をベースラインへ昇格 → 再撮影で完全一致（決定性）→ `uv run python scripts/export_design_tokens.py` 再生成 → DesignSync で Ground Truth 再同期（dark/light）。
- [ ] **Step 5: ドキュメント** — docs/design.md へ「表記規約」節（spec §4 R-01..13 を転記）＋決定履歴エントリ（判断点 14 の確定値・#1/#2/#7 のユーザー選定・UX-11 ドック名 supersede）。CLAUDE.md Phase 行更新。カタログ該当行へ解消マーク。
- [ ] **Step 6: 最終ゲート＋コミット** — full pytest・ruff・mypy → `git commit -m "docs+test(gui): 文言OS 凍結検証 (18枚+viewport crop)・①ゲート・DesignSync 再同期・表記規約 docs 化 (文言OS Task7)"`

---

## Self-Review 済み確認事項

- spec §1 の解消 10 行 → Task 対応: UX-10（T2-T6 全域）・UX-08（T6）・UX-11（T5 G-42/R-07・supersede は T7 docs）・UX-20（T2 G-39/T5 G-12,14,16）・UX-36（T3 E-1）・UX-40（T4 G-40）・UX-41（T2 walk）・UX-50（T3 G-19）・UX-51（T4 G-21）・UX-55（T2-T5 R-02/05/06/10・T5 E-2）。
- 非到達行（付録 note「非到達」・format_def_manager）は対応表から除外済み — 例外は G-44/45 の防御的 4 件（spec 確定で対象）。
- 型整合: `mn`/`strip_mnemonic` は Task 1 定義を T2/T4 で使用。`DOCK_*`/`REF_DIAGNOSTICS`/`INTERP_METHOD`/`TAB_DEFAULT_TMPL` の生成タスクと消費タスクの対応を Interfaces に明記済み。
