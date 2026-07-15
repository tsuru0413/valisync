# valisync デザインシステム

一次情報源。**値の真実は `src/valisync/gui/theme/tokens.py`（DARK）**であり、本書は
原則・トークンの意味・運用手順を持つ（値は書かない — 乖離を作らないため）。
設計の経緯は [spec](superpowers/specs/2026-07-15-design-token-pipeline-design.md)。

## 原則

1. **意味名トークン** — 役割ベース（`surface_chip`・`accent_active`）で命名し、値名
   （`catppuccin_blue` 等）にしない。役割が違えば値が同じでも別トークン
   （例: `drop_highlight` と `signal_palette[0]`）。
2. **単一の真実・一方向フロー** — tokens.py → コード/エクスポート/カタログ。
   Claude Design 側での直接編集はしない。
3. **色の直書き禁止** — `tests/gui/test_theme_guard.py` が CI で検出する。QSS/リッチ
   テキスト断片は `theme/qss.py` の生成関数を追加して使う。
4. **呼び出し時読み** — `tokens.active()` を使用時に読む。module 定数・default 引数へ
   束縛しない（デバッグテーマ・将来のテーマ切替が効かなくなる）。
5. **ダーク単一（拡張可能構造）** — 値セットは DARK のみ。ライトは将来 ThemeTokens
   インスタンス追加で対応（切替 UI は未実装・YAGNI）。

## トークンの意味（カテゴリ概要）

| カテゴリ | 代表トークン | 使い分け |
|---|---|---|
| プロット面 | `plot_background` / `plot_foreground` | pyqtgraph 全体（背景・軸/文字） |
| 信号 | `signal_palette`（10色巡回） | 曲線の自動色。ユーザー指定色はトークン外 |
| カーソル | `cursor_a` / `cursor_b` | プロット線と readout マーカーで共有 |
| readout チップ | `surface_chip` / `border_chip` / `text_primary` / `text_secondary` / `close_hover` | フロート表の面・枠・文字階層 |
| アクティブ強調 | `accent_active` / `accent_active_dark` / `grip_fill` | アクティブ軸/パネルの amber 系 |
| インタラクション | `drop_highlight` / `axis_move_indicator` / `axis_move_fill` | D&D・軸移動の一時表示 |
| フィードバック | `error` / `busy_spinner` / `text_releasing` / `preview_curve` | 検証エラー・非同期状態 |
| 寸法 | `spacing.*` / `radii.*` / `typography.small_px` / `grid_alpha` | チップ余白・角丸・縮小ラベル・グリッド透過 |

## 運用ループ（1 反復 = 1 feature ブランチ）

1. **検討**: claude.ai/design のプロジェクト「valisync-design」でカードを見ながら議論。
   改善案は `design/proposals/` に案A/案B カードを作り push して比較
   （規約は `design/proposals/README.md`）。
2. **承認**: 採用案を決める。
3. **反映**: `tokens.py` の値変更＋`tests/gui/test_theme_tokens.py` の golden 更新＋本書
   に決定理由を追記。クロム系の初回だけ `apply.py` の構造作業を伴う（spec §8 増分3）。
4. **再生成**:
   ```bash
   uv run python scripts/capture_ui_screenshots.py --out design_export/screenshots_catalog --catalog
   uv run python scripts/export_design_tokens.py
   ```
   → DesignSync で増分同期（`list_files` でリモートと突合 → `finalize_plan` →
   `write_files`。常にコンポーネント単位・丸ごと置換しない・push 前に `get_project` で
   design-system 型を検証）。
5. **照合**: Ground Truth（新スクショ）と Components（意図したデザイン）を見比べ、
   「意図した変化のみか」を確認。採用済み Proposals はローカル・リモート両方から削除。

## 検証の道具

- **凍結比較**: `scripts/compare_screenshots.py BASELINE AFTER`（exit 0=完全一致）。
  リファクタ（値不変）の証明に使う。
- **デバッグテーマ**: `capture_ui_screenshots.py --debug-theme`（全トークン相異値）。
  役割写像（どのトークンがどこに着地するか）の目視検証。同値別トークンの誤配線は
  ピクセル比較で原理的に不可視 — 値分岐テーマのテストで補完する
  （memory: gui_freeze_tokenization_verification_pattern）。

## Do / Don't

- Do: 新しい色が必要になったら tokens.py に意味名で追加 → qss.py に生成関数 → golden 更新。
- Do: カードテンプレートの色は `var(--vs-*)` のみ（`tests/gui/test_theme_export.py` が検証）。
- Don't: view/VM に hex・`rgba(`・`QColor(リテラル)` を書く（ガードテストが落とす）。
- Don't: Claude Design 上でカードを直接編集する（次回 push で消える — 真実はリポジトリ）。
