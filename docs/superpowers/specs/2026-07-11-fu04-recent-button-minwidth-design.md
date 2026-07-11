# FU-04 修正設計 — Recent Files ボタンの最小幅有界化

**日付**: 2026-07-11
**課題**: FU-04（[docs/audit-findings-catalog.md](../../audit-findings-catalog.md) FU-04 行）
**種別**: バグ修正（GUI レイアウト・根本解決）

## 問題

大容量ファイル読込後、Diagnostics ドックを切り替えると File/Channel Browser ドックが**意図せず画面外へ押し出され操作不能・復帰困難**になる。

## 根本原因（実測で確定）

`src/valisync/gui/views/welcome_view.py:65` が Recent Files を **フルパス文字列をラベルにした `QPushButton(path)`** で生成している。QPushButton は文字列全体が収まるよう `minimumSizeHint().width()` をパス長に比例して要求する（省略なし・幅上限なし）。

この過大な最小幅が次の連鎖でウィンドウ全体を過剰制約する（`fu04_minwidth_decompose.py` の実測）:

1. Recent ボタンの最小幅がパス長に比例（smoke の110字パスで **813px**）。
2. `WelcomeView` の最小幅がそのボタンに支配される（**831px**）。
3. 中央 `QStackedWidget` の最小幅は **全ページの最大**（Qt 既定）なので、**グラフエリア表示中でも隠れた WelcomeView ページ経由**でウィンドウ最小幅を支配する。
4. ユーザー実データの長いパスでは最小幅が **2009px** に達し画面幅（1920）を超える。
5. この過剰制約下で Diagnostics 切替の再レイアウト＋ウィンドウ・リサイズ（Qt が画面幅にクランプ）が走り、収まらない右ドックが画面外へ押し出される。

計測値（`fu04_minwidth_decompose.py`・画面 1536×816）:

| 状態 | window 最小幅 | 駆動元 |
|---|---|---|
| FRESH（データなし） | 426 | Diagnostics ドック(426) |
| smoke ロード後 | **1024** | WelcomeView(831) ← Recent ボタン(813=フルパス) |

**結論**: この最小幅は「正当に必要な幅」ではなく**過大報告（バグ）**である。ウィンドウは本来もっと小さく描画できるのに、Recent ボタンのラベル幅が不要な下限を作っている。

## 設計方針

**Recent Files ボタンがパス長に比例した最小幅を要求しないよう、ボタン側で有界化する。** それ以外（ウィンドウ/画面幅のクランプ、QStackedWidget のページ最大の抑制）は**行わない**。

### なぜボタン側の有界化が正しい根本解決か

- 最小幅（`minimumSizeHint`）は「下限」であり、これを下げても**上限・推奨幅（`sizeHint`/最大化）には一切影響しない**。したがって**ユーザーが意図的にウィンドウを画面より大きく表示することは完全に維持される**（ユーザー要件）。
- 過大な下限が消えることでウィンドウは画面に収まれるようになり、**過剰制約が解消 → Diagnostics 切替でドックが意図せず画面外へ飛ぶ現象が根絶される**（症状の隠蔽でなく原因の除去）。
- 修正は WelcomeView 1ファイル・`refresh()` のボタン生成箇所に閉じる。

### 非目標（Non-Goals）

- ウィンドウ/ドック最小幅を画面幅へクランプしない（意図的な大画面表示を殺さないため）。
- `QStackedWidget` の「全ページ最大」挙動は変更しない（根本はボタン側であり、そこを直せば隠れページの寄与も無害になる）。
- プロット列のスクロール化・圧縮はしない（本課題の駆動元ではないと実測で判明）。

## 変更するユニット

### `WelcomeView.refresh()`（`src/valisync/gui/views/welcome_view.py:56-68`）

Recent ボタン生成を次のように変える:

- **ラベル**: フルパスをそのまま渡さず、**省略表示**にする。パスの中央省略（`QFontMetrics.elidedText(path, Qt.TextElideMode.ElideMiddle, MAX_W)`）でドライブ名とファイル名を残しつつ、ボタンが要求する最小幅を `MAX_W`（+マージン）に有界化する。`ElideMiddle` によりファイル名（末尾）が保持される。
- **ツールチップ**: フルパスを `btn.setToolTip(path)` で提供（省略で失われる情報を補完）。
- **クリック挙動は不変**: `open_requested.emit(path)`（フルパス）を発火する既存配線をそのまま維持する。省略はあくまで表示のみ。
- `MAX_W` は WelcomeView モジュールの定数（目安 ~360px。厳密値はプラン）。ボタンフォントの `QFontMetrics` で省略幅を算出する。

この結果、Recent ボタンの `minimumSizeHint().width()` はパス長に依存せず `MAX_W`+マージン以下に有界化され、WelcomeView → 中央 stack → ウィンドウの最小幅がパスで膨張しなくなる。

## テスト戦略（GUI テストレイヤー準拠）

### Layer A/B（決定的・CI）— 回帰の主ガード

1. **ボタン最小幅の有界性**: 極端に長いパス（例 300字）を Recent に登録して `WelcomeView` を `refresh()` した後、`welcome_view.minimumSizeHint().width()`（および各 Recent ボタンの `minimumSizeHint().width()`）が `MAX_W`+マージン以下に収まることを assert。修正前実装（`QPushButton(path)`）では ~2000px となり RED（サボタージュで実証）。
2. **ウィンドウ最小幅の非膨張**: 長いパスを Recent 登録した MainWindow（グラフエリア表示中）で `main_window.minimumSizeHint().width()` がパス長に依存せず有界であることを assert。
3. **表示は省略・保持は完全**: ボタンのラベルは省略済み（`btn.text() != full_path` かつ末尾のファイル名を含む）・`btn.toolTip() == full_path`・クリックで `open_requested` がフルパスを発火。

### Layer C（realgui・ローカル `--realgui`）— 実機の意図せぬ画面外を実証

長いパスを Recent 登録 → MainWindow を実表示（`QT_QPA_PLATFORM=windows`）→ Diagnostics ドックを実操作で切替 → File/Channel Browser ドックが**画面内に留まる**ことを、`isVisible()` ではなく **`visibleRegion` 非空＋画面内ジオメトリ**で確認（`isVisible()` は画面外でも True を返す罠のため）。修正前は同手順でドックが画面外へ出る（honest-RED）。

## 受け入れ基準

- 長いパスの Recent 登録があっても、ウィンドウ最小幅がパス長で膨張しない（Layer A/B で有界性を assert）。
- 長いパス Recent ＋ Diagnostics 切替でドックが画面外へ出ない（Layer C 実測）。
- 意図的な大画面表示（最大化・手動拡大）は従来どおり可能（回帰なし）。
- 品質ゲート（pytest / ruff / mypy）通過。

## 影響範囲

- 変更: `src/valisync/gui/views/welcome_view.py`（`refresh()` のボタン生成＋モジュール定数）。
- 新規テスト: WelcomeView 最小幅の Layer A/B、ドック非displacement の realgui。
- 他ファイル・他挙動への影響なし（クリック配線・MRU・D&D は不変）。
