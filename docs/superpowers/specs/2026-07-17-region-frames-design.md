# 領域境界フレーム（region frames）設計

日付: 2026-07-17 ／ ステータス: 承認済み（brainstorming・スパイク実機比較で変種確定）
関連: [design-token-pipeline spec](2026-07-15-design-token-pipeline-design.md)・[docs/design.md](../../design.md)（運用ループ — 本件はその最初の反復）

## 1. 背景・問題

File Browser / Channel Browser / Diagnostics / 中央（プロット）エリアの境界が視認できない。
根本原因は「線の欠如」に加えて面の同化 — DARK で `chrome_window` #1e1e2e と
`chrome_base` #181825 がほぼ同値（LIGHT も #eff1f5 vs #e6e9ef）で、Fusion の
separator も同系色のため 4 領域が一続きの面に見える。

## 2. 採用案（スパイク実機比較で確定）

4 変種（現状 / A separator 線のみ / B 1px 枠 / C 背景差＋枠）を実アプリに当てて
dark/light × 全体像＋境界拡大シートで比較し、ユーザーが **B** を選択。

**B = 現行配色は一切変えず、境界線だけを追加する**:
1. **separator 明色化** — `QMainWindow::separator` を境界線色・幅 4px で描画
2. **1px 枠** — 各領域のコンテンツを境界線色 1px の枠で囲む

C（`chrome_window` の暗色化による面の分離）は不採用 — 配色変更を伴わない控えめな
変化を優先。将来のデザイン反復で再検討可能（スパイク画像は比較済み資産）。

## 3. スコープ

- **対象領域（4）**: file_dock / channel_dock / diagnostics_dock の中身
  ＋ `central_stack`（QStackedWidget — Welcome 画面でも同じ枠が付き一貫）
- **対象外**: DataExplorer・SignalPreview（独立トップレベルウィンドウでドック領域では
  ない）。フローティング状態のドック（OS ネイティブ枠が付く）。
- **テーマ**: dark/light 両対応。適用は既存どおり起動時（ランタイム切替なし）。

## 4. トークン

`Colors` に **`chrome_frame`** を 1 フィールド追加（chrome 系 14 個目・役割 =「領域境界線」）。

| テーマ | 値 | 由来 |
|---|---|---|
| DARK | `#45475a` | Catppuccin Mocha surface1（スパイク目視承認値） |
| LIGHT | `#bcc0cc` | Catppuccin Latte surface1（同上） |

separator と 1px 枠は同一役割なので単一トークンを共有する。両値とも既存トークンと
非重複（同値別トークンの盲点 — memory gui_freeze_tokenization_verification_pattern —
は発生しない）。golden スナップショット（DARK/LIGHT 全域 test-lock）を更新する。
エクスポート（tokens.css/json・colors カード）はフィールド走査のため自動反映。

## 5. QSS（qss.py — pure・呼び出し時読み）

```python
def main_window_separator() -> str:
    """QMainWindow::separator { background: <chrome_frame>; width: 4px; height: 4px; }"""

def region_frame(object_name: str) -> str:
    """#<object_name> { border: 1px solid <chrome_frame>; }"""
```

- ID セレクタで子ウィジェットへの波及を遮断（PR #116 のドロップ枠と同じ流儀）。
- separator 幅 4px は Fusion 既定より僅かに狭い（スパイクで数 px の layout shift を
  実測・目視承認済み）。掴み幅としては十分。

## 6. 適用（apply.py — Qt 隔離層）

### 6.1 app レベル: separator

`apply_theme()` に `app.setStyleSheet(qss.main_window_separator())` を追加。
- 現在 app レベル stylesheet は未使用（grep 確認済み）— 衝突なし。
- 同一文字列の再設定なので冪等性は保たれる。
- app スタイルシート設定は全ウィジェットのスタイル解決を QStyleSheetStyle 経由に
  する — 副作用の有無はスパイクで実証済み（差分は separator＋shift のみで
  無関係な再描画なし）。§8 の前後差分解析が最終ゲート。

### 6.2 ウィジェット単位: 枠ヘルパ

```python
def frame_region(widget: QWidget, name: str) -> None:
    """領域コンテンツに 1px 境界枠を付ける（シェルが対象を選ぶ）。"""
    # 1. objectName 未設定なら name を付与（設定済みならそれを使う）
    # 2. WA_StyledBackground 付与（素の QWidget 子は QSS 枠を描かない — PR #116）
    # 3. layout の余白が全て 0 なら (1,1,1,1) へ — 枠が margins-0 の子に覆われる
    #    罠の対策。既定余白あり（Diagnostics 容器）は不変。layout 無しも不変。
    # 4. widget.setStyleSheet(qss.region_frame(widget.objectName()))
```

## 7. 配線（main_window.py）

dock 3 つの中身＋central_stack に `frame_region()` を 4 回呼ぶ:

| 対象 | name |
|---|---|
| `self.file_browser_view` | `region_file_browser` |
| `self.channel_browser_view` | `region_channel_browser` |
| `self.diagnostics_dock.widget()` | `region_diagnostics` |
| `self.central_stack` | `region_central` |

**view 側は無変更** — どの領域に枠を付けるかはシェル（MainWindow）の責務。同じ view を
別文脈（テスト・プレビュー）で使っても枠は付かない。

**既知の副作用**: 余白 0→1px 化で中身が 1px 内側へずれる（意図差分）。hit-test は
widget 相対座標で自己整合するため機能影響なしの見込みだが、ゾーン/グリップ/D&D 系
realgui 全数で無回帰を実証する（memory gui_panel_chrome_layout_row_shifts_hittest_origin
の教訓 — 座標系ずれは headless が構造的に見逃しうる）。

## 8. 検証

**Layer B（CI・headless）**:
- golden 更新（chrome_frame 追加）・qss 生成関数のトークン参照/ID セレクタテスト
- `frame_region` 単体: objectName 付与規則・WA 付与・余白 0→1 のみ昇格・QSS 適用
- honest ピクセルテスト（蛍光緑親パターン・PR #116 確立）: 枠が実際に描画されることを
  実証（WA を外すと RED の sabotage 構成）
- 配線テスト: `build_main_window` 後に 4 領域へ枠 QSS・`apply_theme` が app
  stylesheet に separator 規則を設定

**実機（意図差分の証明・r5 と同型）**:
- 前後撮影 → 差分解析で「変化が境界線＋1px シフトに限定」を実証（dark/light 両テーマ）
- `--debug-theme` で chrome_frame が境界にのみ着地することを目視
- realgui **全数**＋journey smoke（/gui-verify ①ゲート — 入力経路の追加はないため
  contract は無回帰中心）

## 9. 成果物

- 凍結ベースライン差し替え（意図差分後の新 5 状態）・カタログ再撮影（dark/light）・
  エクスポート再生成・valisync-design 再同期
- docs/design.md: トークン表に `chrome_frame` 追記＋**決定履歴に初エントリ**
  （運用フェーズ最初の反復として記録）
- merge 後に CLAUDE.md 更新の docs PR

## 10. 進め方

`feature/region-frames` ブランチ・subagent-driven development・ゲート 4 種
（pytest / ruff check / ruff format --check / mypy src/）。タスク 4〜5 個の小反復。
