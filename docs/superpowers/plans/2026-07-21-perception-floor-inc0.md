# 増分0「知覚の床」Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 知覚基盤の一斉是正（トークン 8 値・QSS 枠・当たり判定・アイコン・初期レイアウト/列幅）で UX-12/18/21応急/27/29/35/38/39/42/49＋UX-07応急 を解消する。

**Architecture:** tokens.py の値変更（LIGHT はプロット面/Typography/grid を参照共有で自動追従）＋qss/apply の app sheet 1 ルール追加＋view の寸法/列幅/初期レイアウト小改修。全変更に実測根拠（spec §1）。

**Tech Stack:** PySide6 / pyqtgraph / pytest(-qt)。Layer C は `--realgui`。

**Spec:** [2026-07-21-perception-floor-inc0-design.md](../specs/2026-07-21-perception-floor-inc0-design.md)（値・根拠・波及全数は spec が真実 — 本プランは手順）

## Global Constraints

- 新値（spec §1.1 表の 8 トークン）は**一字一句 spec のとおり**。LIGHT: error #c0392b 維持・Typography/palette/grid_alpha は参照共有のまま（独立定義禁止 — identity lock `test_theme_tokens.py:200`）。
- 値分岐テーマテスト 3 関係（spec §3）は必須。既存型: `tests/gui/test_theme_qss.py:138-151`。
- QLineEdit ルールに carve-out `QLineEdit#qt_spinbox_lineedit { border: none; }` 必須（spec §1.2）。
- 当たり判定は `setMinimumHeight`（fixedSize 禁止 — 幅縮小で視覚不変と矛盾）。
- Unit 列に `ResizeToContents` 禁止（prod O(n) 走査 — spec §1.5-13 のサンプリング幅方式）。
- 旧色 grep（spec §2-8 のパターン・期待残存リスト）を merge 前に実施。
- 品質ゲート: pytest / ruff check / ruff format / mypy を各コミット前。コメント WHY のみ日本語。

---

### Task 1: トークン値変更＋golden/構造 assert 追随

**Files:**
- Modify: `src/valisync/gui/theme/tokens.py`（DARK: §1.1 の 8 値）
- Modify: `tests/gui/test_theme_tokens.py`（値 golden :69-93 相当・`len(v) == 10`→8 :54・axis_move RGB 形式 :91-92・text_secondary :85）
- Modify: `tests/gui/test_theme_export.py`（:33-34 range(10)→8・:40 font-small 10px・:41 grid-alpha 150・:53 len 8・:54 palette[0] "#56b4e9"・:57 small_px 10・:58 grid_alpha 150）

**Interfaces:** Produces: 新トークン値（後続全タスクの前提）。

- [ ] **Step 1（RED）**: tokens.py を変更**せず** golden テストを spec §1.1 の新値へ先に書き換え、`uv run pytest tests/gui/test_theme_tokens.py tests/gui/test_theme_export.py -v` が旧値で FAIL することを確認
- [ ] **Step 2（GREEN）**: tokens.py の DARK を更新:

```python
        signal_palette=(
            Color.from_hex("#56B4E9"),
            Color.from_hex("#E69F00"),
            Color.from_hex("#00C08B"),
            Color.from_hex("#F0E442"),
            Color.from_hex("#FF6E4A"),
            Color.from_hex("#D98BC0"),
            Color.from_hex("#9A8CFF"),
            Color.from_hex("#C8C8C8"),
        ),
        cursor_b=Color.from_hex("#74c7ec"),
        text_secondary=Color.from_hex("#9399b2"),
        drop_highlight=Color.from_hex("#94e2d5"),
        axis_move_indicator=Color.from_hex("#f59e0b"),
        axis_move_fill=Color(245, 158, 11, 60),
        error=Color.from_hex("#f38ba8"),
    ...
    typography=Typography(small_px=10),
    grid_alpha=150,
```

（他トークン・LIGHT ブロックは不変。パレット由来のコメント「palette[0] と同値だが…」は drop_highlight の単独値化に合わせ「パレット外の teal — 一時表示がどの曲線とも紛れない (UX-35)」へ更新）
- [ ] **Step 3**: `uv run pytest tests/gui/test_theme_tokens.py tests/gui/test_theme_export.py tests/gui/test_theme_guard.py -v` → PASS
- [ ] **Step 4**: full gates → Commit `feat(theme): 知覚の床トークン一斉是正 (UX-12/18/27/35/39・spec §1.1)`

### Task 2: パレット循環テスト再設計＋値分岐 3 関係

**Files:**
- Modify: `tests/gui/test_graph_panel_vm.py:810-824`（`test_palette_cycles_beyond_ten_signals` → `test_palette_cycles_beyond_palette_length`: 9 信号構築・`colors[8] == colors[0]`・docstring に「10 色 tab10 前提の意図的 supersede（spec §2-3）」）
- Modify: `tests/gui/test_theme_qss.py`＋`tests/gui/test_cursor_readout.py`（値分岐 3 関係 — 既存 :138-151/:565 の型で追加）

**Interfaces:** Consumes: Task 1 の新値。

- [ ] **Step 1**: 循環テスト再設計（上記）→ `uv run pytest tests/gui/test_graph_panel_vm.py -k palette -v` PASS
- [ ] **Step 2（値分岐・各 sabotage RED 実証）**: 3 テストを追加 — 値分岐テーマ（`dataclasses.replace` で対象トークンだけ相異値化）で:
  - `error` vs `delta_negative`: error=Color(1,2,3) のテーマで `qss.error_label`/`rename_error_border` 出力に `1, 2, 3` が含まれ delta_negative 値を含まない＋readout Δ負値セルは delta_negative 側
  - `error` vs `close_hover`: 同型で readout ✕ hover → close_hover・エラー文言/枠 → error
  - `axis_move_indicator` vs `accent_active`: 軸移動フィードバック線の pen → axis_move_indicator・アクティブ枠/バッジ色 → accent_active
  各テストは実装の写像を一時的に取り違えるサボタージュ（ローカル patch）で RED になることを確認してから確定
- [ ] **Step 3**: full gates → Commit `test(theme): 同値別役割 3 関係の値分岐テスト＋循環テスト 8 色化 (spec §2-3/§3)`

### Task 3: QLineEdit 枠 QSS＋carve-out

**Files:**
- Modify: `src/valisync/gui/theme/qss.py`（生成関数追加）
- Modify: `src/valisync/gui/theme/apply.py:67-69`（app sheet 連結）
- Test: `tests/gui/test_theme_qss.py`・`tests/gui/test_theme_apply.py`（相当ファイル）

**Interfaces:** Produces: `qss.line_edit_frame(tt) -> str`。

- [ ] **Step 1（RED）**: 「app sheet に QLineEdit 枠・focus・carve-out の 3 ルールが含まれる」テスト → FAIL
- [ ] **Step 2（GREEN）**:

```python
def line_edit_frame(tt: tokens.ThemeTokens) -> str:
    """QLineEdit の常時枠 (UX-49) — Fusion 導出色は未フォーカス枠を描かず
    プレースホルダだけの行と区別できないため app QSS で明示する。
    QSpinBox 内部の qt_spinbox_lineedit は自枠の内側に二重枠を作るため除外
    (spec §1.2 carve-out)。"""
    c = tt.colors
    return (
        f"QLineEdit {{ border: 1px solid {c.chrome_frame.hex}; }}\n"
        f"QLineEdit:focus {{ border: 1px solid {c.chrome_highlight.hex}; }}\n"
        "QLineEdit#qt_spinbox_lineedit { border: none; }"
    )
```

apply.py: `new_sheet = qss.main_window_separator(tt) + "\n" + qss.line_edit_frame(tt)`
- [ ] **Step 3**: full gates → Commit `feat(gui): QLineEdit 常時枠+focus 強調 (UX-49・QSpinBox carve-out)`

### Task 4: 当たり判定（高さ 24px 保証）＋realgui 実クリック

**Files:**
- Modify: `src/valisync/gui/views/collapsible_dock_title_bar.py`（フロート/✕ text ボタンに `setMinimumHeight(24)`）
- Modify: `src/valisync/gui/views/graph_panel_view.py`（パネル +/× ボタン同処置 — 実装位置は `_panel_chrome`/add ボタン生成部を grep）
- Test: `tests/gui/`（minimumHeight assert）＋`tests/realgui/test_hit_targets.py`（新設）

**Interfaces:** Consumes: spec §1.3（chevron=既充足で変更なし・DockCollapseRail=対象外・fixedSize 禁止）。

- [ ] **Step 1（Layer A RED→GREEN）**: 対象ボタンの `minimumHeight() >= 24` assert → setMinimumHeight(24) で GREEN
- [ ] **Step 2（Layer C・新設 realgui）**: 実行時 geometry から「旧 rect 外 ∧ 新 rect 内」の点を導出して実 OS クリック
  （honest RED: 拡張ロジックを一時無効化した sabotage で同座標クリックが不発になることを 1 度実証 — spec §5 Task C。
  chevron は現状 24×23 の実測記録のみ）。掴み点監査: 隣接ボタン非誤爆＋panel chrome 直下以外の plot press 無回帰
  （scoped: `uv run pytest --realgui tests/realgui/test_hit_targets.py tests/realgui/test_dock_collapse*.py tests/realgui/test_curve_direct_ops.py`。
  collapse 系 realgui のファイル名は tests/realgui/ を ls して実名に合わせる）
- [ ] **Step 3**: full gates → Commit `feat(gui): 常用ボタンの当たり判定を高さ24pxへ (UX-38)`

### Task 5: export アイコン差し替え

**Files:**
- Create: `src/valisync/gui/theme/icons/lucide/download.svg`（unpkg lucide-static@1.24.0 から取得・無改変）
- Modify: `src/valisync/gui/theme/icons.py:25`（`"export": "lucide/download.svg"`）・`src/valisync/gui/theme/icons/LICENSES.md`（追記）
- Test: 既存 `tests/gui/test_theme_icons.py`（currentColor 規約・レジストリ解決が自動カバー — download.svg が対象に入ることを確認）

- [ ] **Step 1**: SVG 取得（`curl -o ... https://unpkg.com/lucide-static@1.24.0/icons/download.svg`）→ currentColor のみ確認
- [ ] **Step 2**: レジストリ差し替え＋LICENSES.md 追記 → `uv run pytest tests/gui/test_theme_icons.py -v` PASS
- [ ] **Step 3**: `uv run uv build --wheel` 相当の package-data 収載確認（増分5 の既存手順/テストに従う）→ full gates → Commit `feat(theme): export アイコンを Lucide download へ (UX-42・save は増分F 温存)`

### Task 6: 初期ドック比率 1:4（restore bool 化・show 後適用・Reset Layout 整合）

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（`_restore_state()` bool 返し :598-611・初回 show 後の `_apply_default_dock_ratio()` 新設・`_reset_layout()` 末尾で再適用）
- Test: `tests/gui/test_main_window*.py`

**Interfaces:** Produces: `_restore_state() -> bool`（restoreState の bool 伝搬）・`_apply_default_dock_ratio()`。

- [ ] **Step 1（RED）**: 「保存 state 無しの初回 show 後に `resizeDocks` が File:Channel=1:4 で呼ばれる」「保存 state ありなら呼ばれない」「`_reset_layout()` 後にも適用される」を呼出記録（monkeypatch/spy）で assert → FAIL
- [ ] **Step 2（GREEN）**:

```python
    def _apply_default_dock_ratio(self) -> None:
        """初期ドック比率 File:Channel≈1:4 (UX-21 応急・spec §1.5-12)。
        pre-show は dock extent 未確定で no-op になるため初回 show 後に呼ぶ
        (main_window.py の _apply_saved_collapse と同じ罠の回避)。"""
        self.resizeDocks(
            [self.file_dock, self.channel_dock], [1, 4], Qt.Orientation.Vertical
        )
```

`_restore_state` は `restoreState(...)` の bool を返す。`showEvent` 初回（フラグ）で
`if not self._state_restored: QTimer.singleShot(0, self._apply_default_dock_ratio)`。
`_reset_layout()` の restore 後にも `_apply_default_dock_ratio()`（初回起動と Reset Layout の比率一致 — spec §1.5-12c）。
offscreen での dock 実寸 assert は書かない（false-green — 効きは Task 9 のカタログ 01 実ディスプレイで確認）。
- [ ] **Step 3**: full gates → Commit `feat(gui): 初期ドック比率 File:Channel=1:4 (UX-21 応急・show後適用/Reset整合)`

### Task 7: 列幅既定（Name Stretch・Unit サンプリング幅・Diagnostics Stretch）＋perf 実測

**Files:**
- Modify: `src/valisync/gui/views/channel_browser_view.py`（Name=Stretch・Unit=Interactive＋reset 時 先頭 50 行サンプリング幅 `setColumnWidth`〔上限 120px 程度・フォントメトリクス〕）
- Modify: `src/valisync/gui/views/diagnostics_view.py`（メッセージ列 Stretch・他 ResizeToContents）
- Test: `tests/gui/test_channel_browser_view.py`・`tests/gui/test_diagnostics_view.py`

- [ ] **Step 1（RED→GREEN）**: ResizeMode/列幅の assert → 実装。**ResizeToContents を Unit に使わない**（Global Constraints）
- [ ] **Step 2（perf E2E）**: quick_demo（187ch）＋可能なら hils/prod 相当で「ファイル選択→ChannelBrowser 表示までの同期ブロック時間」を現行 main と同等（±10%）と実測（スクリプトは Stage A の perf_feel_check 型）
- [ ] **Step 3**: full gates → Commit `feat(gui): 列幅既定の是正 (UX-29/UX-07 応急・Unit はサンプリング幅で prod 安全)`

### Task 8: realgui 追随＋旧色 grep

**Files:**
- Modify: `tests/realgui/test_offscale_badge.py`（曲線色を `set_color` で #56B4E9/#00C08B に明示指定・:266 の色距離コメントを新値で書き直し — spec §2-5）
- 確認: `tests/realgui/test_fu12_boundary_data_visible.py`（palette[0] #56B4E9 の青ドミナンスで成立するか実行）

- [ ] **Step 1**: バッジテスト修正 → `uv run pytest --realgui tests/realgui/test_offscale_badge.py -v` PASS
- [ ] **Step 2**: `uv run pytest --realgui tests/realgui/ -v` **フル実行** → 全 PASS（色 assert の想定外 fallout はここで検出）
- [ ] **Step 3（旧色 grep）**: spec §2-8 のパターンで src/ tests/ 全域 grep → 期待残存リスト（LIGHT error・chrome_highlight・cursor_readout fixture・graph_panel_view.py docstring）との完全一致を確認
- [ ] **Step 4**: Commit `test(realgui): 新パレット追随 (バッジ色衝突回避・全数実行)`

### Task 9: 凍結撮影・per-state 突合・ベースライン/Ground Truth 更新・決定履歴

- [ ] **Step 1**: full gates（pytest/ruff×2/mypy）
- [ ] **Step 2**: dark/light の `--catalog` 撮影 → **spec §4 の per-state 期待差分表と 1 状態ずつ突合**（表外差分=回帰調査。特に 06/07 のスピンボックス二重枠なし・08 ほぼ不変）
- [ ] **Step 3**: ベースライン更新＋`export_design_tokens` 両テーマ＋DesignSync 再同期（docs/design.md 手順4-5）
- [ ] **Step 4**: docs/design.md 決定履歴へ記録（値一覧・パレット最終確定と増分E 色相ファミリー制約・カタログ UX 該当課題の解消マークは PR 内で）
- [ ] **Step 5**: Commit → PR（本文に per-state 差分表と実測根拠を引用）

## 実施順序と依存

Task 1 → 2（トークン確定）→ 3/5/6/7（独立・順不同）→ 4（realgui 環境）→ 8 → 9。
Task 4/8/9 はローカル実ディスプレイ必須。PR は 1 本（spec コミット済みブランチ）。
