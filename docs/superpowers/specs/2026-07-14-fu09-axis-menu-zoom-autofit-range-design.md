# FU-09: 軸右クリックメニューに中心基準ズーム＋X軸メニュー整備 設計

## 背景 / 課題

- **FU-09**（UX 要望）: 右クリックメニュー（Y軸 `build_axis_menu` 等）に**ズームイン/ズームアウト（引き）**の離散操作を追加したい。現状ズームは inner ゾーンのドラッグのみ。中心基準で軸レンジを拡大/縮小するアクション。
- **追加のユーザー指示（2026-07-14）**: 倍率はイン/アウトとも **10%**。**X軸もスコープに含める**（X軸メニューに autofit/範囲指定も追加し、Y と対等にする）。

現状（`graph_panel_view.py`）:
- Y軸ズームは inner ゾーン（`AXZONE_ZOOM`）の**ドラッグ＝レンジセレクト**（`_finish_axis_drag`→`set_axis_range`。始点/終点のデータ値がそのまま新 y_range）。**中心基準の倍率ズームではない**。
- `build_axis_menu(axis_index)`（Y軸右クリック）: この軸をオートフィット（`vm.reset_axis_y`）／範囲を指定…（`_prompt_axis_range`→`vm.set_axis_range`）／軸を削除／曲線一覧チェック。
- `contextMenuEvent` ルーティング: カーソル線 → 曲線 → Y軸（`ZONE_Y_INNER/OUTER`）→ 空白（`build_context_menu`）。**X軸専用メニューは無い**（`ZONE_X_INNER/OUTER` は存在するがメニュー未配線）。
- VM: `set_axis_range(axis_index, lo, hi)`・`axes[i].y_range`・`reset_axis_y(axis_index)`・`set_x_range(lo, hi)`（X-sync fan-out に相乗り）・`reset_x()`（全信号の時間範囲 union）・`x_range: tuple | None`。

## ゴール

1. Y軸メニュー（`build_axis_menu`）に「ズームイン」「ズームアウト（引き）」を追加（中心基準・倍率）。
2. X軸右クリックメニュー（`build_x_axis_menu`・新規）を Y と対等に整備: **X軸をオートフィット／範囲を指定…／ズームイン／ズームアウト（引き）** の4項目。`contextMenuEvent` に ZONE_X ブランチを追加して表示。

ドラッグのレンジセレクトとは別種の、ワンクリックの中心基準ズームを提供する。

## 倍率（中心基準・10%・Y/X 共通）

- 現レンジ `(lo, hi)` から center=(lo+hi)/2、half=(hi-lo)/2。
- **ズームイン** = half×**0.9**（レンジ −10%＝拡大表示）。
- **ズームアウト（引き）** = half×**1.1**（レンジ +10%）。
- 新レンジ = (center - new_half, center + new_half)。

## アーキテクチャ / 変更点

### VM（`gui/viewmodels/graph_panel_vm.py`）

- **共有純関数 `_scaled_range(lo, hi, factor) -> tuple[float, float] | None`**（モジュールレベル）:
  - center=(lo+hi)/2、half=(hi-lo)/2×factor。new=(center-half, center+half)。
  - `half == 0`（degenerate）・入力/結果が非有限（`math.isfinite` 否定）なら **None**（呼び出し側 no-op）。
- **`zoom_axis(axis_index: int, factor: float) -> None`**:
  - `0 <= axis_index < len(axes)` かつ `axes[i].y_range is not None` を確認。`_scaled_range(lo, hi, factor)` が None でなければ `axes[i].set_range(new_lo, new_hi)` → `_notify("axes")`（`set_axis_range` と同経路）。None/範囲未設定は no-op。
- **`zoom_x(factor: float) -> None`**:
  - `x_range is not None` を確認。`_scaled_range(lo, hi, factor)` が None でなければ **`set_x_range(new_lo, new_hi)`** を呼ぶ（既存の `_x_range_is_auto=False`＋`_notify("range")`＝X-sync fan-out に相乗り）。None/範囲未設定は no-op。

（既存 `reset_x`・`reset_axis_y`・`set_x_range`・`set_axis_range` は不変で再利用。）

### View（`gui/views/graph_panel_view.py`）

- **`build_axis_menu(axis_index)` に追加**（「範囲を指定…」の後・「軸を削除」の前）:
  - 「ズームイン」→ `vm.zoom_axis(axis_index, 0.9)`
  - 「ズームアウト（引き）」→ `vm.zoom_axis(axis_index, 1.1)`
  - 両アクションは `axes[axis_index].y_range is None` のとき `setEnabled(False)`（グレーアウト。中心を持たない軸は倍率ズーム不能）。
- **新 `build_x_axis_menu() -> QMenu`**（Y と対等の4項目）:
  - 「X軸をオートフィット」→ `vm.reset_x()`
  - 「範囲を指定…」→ `_prompt_x_range()`
  - 「ズームイン」→ `vm.zoom_x(0.9)`（`x_range is None` で disabled）
  - 「ズームアウト（引き）」→ `vm.zoom_x(1.1)`（`x_range is None` で disabled）
- **`_prompt_x_range() -> None`**: `fn = self._range_dialog_fn or self._default_range_dialog`; `result = fn(-1, self.vm.x_range)`; result があれば `self.vm.set_x_range(lo, hi)`。**`axis_index = -1` を X軸（時間）のセンチネル**として単一 DI `_range_dialog_fn` を Y/X 両用で再利用。
- **`_default_range_dialog(axis_index, current)` にタイトル分岐**: `axis_index == -1` なら `"X軸（時間）の範囲を指定"`、それ以外は既存 `"Y軸の範囲を指定"`（ダイアログ本体・バリデーション・戻り値は不変）。
- **`contextMenuEvent` に ZONE_X ブランチ追加**（Y軸分岐の後・空白フォールバックの前）:
  ```
  if self._zone_at(pos) in (ZONE_X_INNER, ZONE_X_OUTER):
      self.build_x_axis_menu().exec(event.globalPos())
      return
  ```
  ルーティング: カーソル → 曲線 → Y軸 → **X軸（新）** → 空白。

## データフロー

- Y軸ズーム: 右クリック（Y軸ストリップ）→ `build_axis_menu` → 「ズームイン/アウト」→ `zoom_axis(i, factor)` → `_scaled_range` → `axes[i].set_range` → notify → 再描画。
- X軸ズーム: 右クリック（X軸ストリップ）→ ZONE_X 分岐 → `build_x_axis_menu` → 「ズームイン/アウト」→ `zoom_x(factor)` → `_scaled_range` → `set_x_range` → notify（X-sync ON なら fan-out で全パネル連動）→ 再描画。
- X軸オートフィット/範囲指定: `reset_x()` / `_prompt_x_range()`→`set_x_range`。

## エラーハンドリング

- `y_range`/`x_range` が None または degenerate（half=0）・非有限: `_scaled_range` が None を返し zoom は no-op（例外を投げない）。メニューでは zoom を disabled にして先回り（範囲未設定の可視 feedback）。
- 反復ズームアウトでの非有限化: `_scaled_range` の結果 `math.isfinite` チェックで弾く。
- 範囲指定ダイアログのバリデーション（非有限・lo>=hi で OK 無効）は既存 `_default_range_dialog` のまま。

## テスト設計（gui-test-plan）

- **Layer A（VM）**:
  - `_scaled_range`: center 不変・half×factor（in 0.9/out 1.1）・`half=0`/非有限入力/非有限結果で None。
  - `zoom_axis`: y_range を center 保持で拡縮・範囲外 index/`y_range=None`/degenerate で no-op（レンジ不変）。
  - `zoom_x`: `set_x_range` 経由で拡縮・`_x_range_is_auto=False`・`x_range=None` で no-op。fan-out 相乗り（`notify("range")` 発火）を構造で確認。
- **Layer B（View）**:
  - `build_axis_menu`: 「ズームイン」「ズームアウト（引き）」が存在し trigger で `zoom_axis` 経由レンジ変化・`y_range=None` で disabled。
  - `build_x_axis_menu`: 4項目（autofit/範囲指定/zoom in/zoom out）が存在・autofit で `reset_x`・zoom で `zoom_x`・`x_range=None` で zoom disabled。
  - `contextMenuEvent`: ZONE_X で `build_x_axis_menu` を出す（Y ゾーンは従来どおり `build_axis_menu`・無回帰）。
  - `_prompt_x_range`: stub `range_dialog_fn` 注入時に `set_x_range` を戻り値で呼ぶ・None で呼ばない。
- **gui-verify ①ゲート**（入力経路追加＝メニュー項目）: realgui で「実右クリック（Y軸ストリップ）→ズームイン実クリック→Y軸レンジ縮小」「実右クリック（X軸ストリップ）→ズームイン実クリック→X軸レンジ縮小」を実証（FU-05/06 の実メニュー項目クリックと同型・`QMenu.exec` ネストループ内で実項目クリック＋ESC watchdog）。既存 Y軸メニュー（オートフィット/範囲指定/削除）＋ journey smoke 無回帰。

## YAGNI（除外）

- 倍率設定 UI（10% 固定）・カーソル基準ズーム（中心基準のみ）は作らない。
- X軸メニューへの「軸を削除」「曲線一覧」（X は削除不能・entry は Y軸帰属）は追加しない。
- 新しいドラッグズームモードは追加しない（既存レンジセレクトは不変）。

## Global 制約

- 変更は `gui/viewmodels/`（VM ロジック）と `gui/views/`（メニュー/ルーティング）に閉じる。core は Qt 非依存維持。
- 品質ゲート: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全通過（unscoped・repo ルート）。
- Python コメント/文字列に全角約物 `()：+=` 禁止（RUF001/002/003）。ASCII を使う。例外: メニュー表示ラベル「ズームアウト（引き）」の全角括弧は UI 日本語ラベルゆえ `# noqa: RUF001` を付ける（既存 `menu.addAction("サブカーソル（Δ）")  # noqa: RUF001` と同じ前例に倣う）。
- 入力経路（メニュー項目追加＋ZONE_X ルーティング）変更ゆえ merge 前に gui-verify ①（realgui 実メニュー項目クリック＋ journey smoke）。
