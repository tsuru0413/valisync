# 設計 spec: カーソル/軸 UX 増分②（ポインタ形状 — PC-22 / PC-13 / PC-14 ＋オフセット誤発火）

ユーザーが実機で発見したカーソル/軸のポインタ形状3課題を、**拡張可能なカーソルレジストリ**を土台に解消する。増分①（PC-21 readout 追従＋RN-06 perf）とは独立で、本ブランチは①（PR #49）にスタックしてコンフリクトを回避する。

- **作成**: 2026-07-05
- **ステータス**: 設計（brainstorming 承認済み・writing-plans へ）
- **関連**: [audit-findings-catalog](../../audit-findings-catalog.md) PC-22 / PC-13 / PC-14（ユーザー実機発見 2026-07-05）。増分① spec [cursor-readout-perf](2026-07-05-cursor-readout-perf-design.md)。
- **前提コード（精読・現行行）**:
  - `gui/views/graph_panel_view.py`: `cursor_for_zone:238-246`（X ゾーン→カーソル・inner/outer 双方 `SizeHorCursor`）・`_AlignedAxisItem.cursor_for_local:303-326`（Y ゾーン→カーソル・ZOOM=Cross/PAN=OpenHand）・`_AlignedAxisItem.hoverMoveEvent:339-357`（**アクティブ軸ゲート**＝非アクティブは `unsetCursor`）・`_make_cursor_line:1116-1128`（カーソル線生成・setCursor 無し）・`mousePressEvent:1602-1615`（ZONE_PLOT で `_curve_at` 命中→`_begin_offset_drag`）・`eventFilter:1617-1640`/`mouseMoveEvent:1642-1649`（ホバーカーソル更新）・`_curve_at:1419-1446`（`CURVE_HIT_TOL_PX=8.0` 以内の最近傍曲線キー）
  - 定数: `ZONE_X_INNER`(=zoom)/`ZONE_X_OUTER`(=pan)/`ZONE_PLOT`・`AXZONE_GRIP_TOP/BOTTOM`/`AXZONE_FRAME`/`AXZONE_ZOOM`/`AXZONE_PAN`

---

## 1. スコープと確定判断（brainstorming・ユーザー決定）

| 項目 | 決定 |
|---|---|
| スコープ | **ポインタ形状（PC-22/PC-13/PC-14）＋オフセット誤発火修正**。①（readout/perf）とは別 PR。 |
| カーソル生成 | **拡張可能なカーソルレジストリ**（`CursorKind` enum ＋ `cursor(kind)` 遅延キャッシュ）。ゾーン判定は純粋な kind 返却、QCursor 生成はレジストリ1点。 |
| PC-14（X） | inner=zoom → **カスタム水平ズーム bracket [\|→←\|]**（`QCursor(QPixmap)`・Qt 移植可）／outer=pan → `SizeHorCursor`（[←→]）。 |
| PC-13（Y ゲート） | 非アクティブ Y 軸ホバー → **`PointingHandCursor`（「クリックで活性化」）**／アクティブ軸 → ゾーン別形状。操作モデル（活性化必須）と一致し誤誘導なし。 |
| Y 形状統一 | Y zoom=Cross → **カスタム垂直ズーム bracket [\|↑↓\|]**／Y pan=OpenHand → **`SizeVerCursor`**（[↕]）。grip=SizeVer・frame=SizeAll は不変。X と流儀統一。 |
| PC-22（カーソル線） | `_make_cursor_line` 生成直後に **`line.setCursor(SizeHorCursor)`**（線は常に水平ドラッグ＝静的形状で十分）。 |
| オフセット誤発火 | プロット領域で曲線近傍にホバー時に **`SizeHorCursor`（オフセットドラッグ可のアフォーダンス）** を表示 → 「曲線近くの左ドラッグ＝オフセット」が不意打ちでなく予測可能に。挙動（トリガ条件）は不変。 |

## 2. カーソルレジストリ（`gui/views/cursor_shapes.py`・新規）

**目的**: (a) カスタム QCursor(QPixmap) を1箇所で生成・遅延キャッシュ、(b) ゾーン→カーソルのマッピングを純粋関数（QApplication 不要でテスト可能）に保つ、(c) 将来のカーソル追加を容易に。

- **`class CursorKind(Enum)`**: `ARROW / PAN_H / PAN_V / ZOOM_H / ZOOM_V / RESIZE_V / MOVE / ACTIVATE / DRAG_H`。
- **`cursor(kind: CursorKind) -> QCursor`**: モジュール辞書に遅延キャッシュ。標準 kind は `QCursor(Qt.CursorShape.*)`、`ZOOM_H`/`ZOOM_V` は `_build_zoom_cursor(horizontal)` でカスタム pixmap。初回呼び出し時（＝ホバー時・QApplication 存在下）に生成。
  - 標準対応: ARROW→Arrow・PAN_H→SizeHor・PAN_V→SizeVer・RESIZE_V→SizeVer・MOVE→SizeAll・ACTIVATE→PointingHand・DRAG_H→SizeHor。
- **`_build_zoom_cursor(horizontal: bool) -> QCursor`**: 32×32 透明 `QPixmap` に「両端バー＋内向き矢印」を描画（水平=[\|→←\|]／垂直=[\|↑↓\|]）。視認性のため白ハロー（太）＋黒線（細）の二重描画。ホットスポット中心 (16,16)。
- **拡張点**: 新カーソルは `CursorKind` に1つ追加し、標準辞書 or `_build_*` に対応を足すだけ。

## 3. PC-14（X 軸）— zoom/pan 区別

`cursor_for_zone(zone) -> CursorKind`（返り値型を `Qt.CursorShape` → `CursorKind` に変更・純粋）:
- `ZONE_X_INNER` → `CursorKind.ZOOM_H`
- `ZONE_X_OUTER` → `CursorKind.PAN_H`
- その他 → `CursorKind.ARROW`

呼び出し側（`eventFilter`/`mouseMoveEvent`）は `self.setCursor(cursor(self._hover_cursor(pos)))` に変更（§6 で `_hover_cursor` 定義）。

## 4. PC-13（Y 軸）— 形状統一＋活性化ゲート

`_AlignedAxisItem.cursor_for_local(...) -> CursorKind`（返り値型変更・純粋）:
- `AXZONE_GRIP_TOP/BOTTOM` → `CursorKind.RESIZE_V`
- `AXZONE_FRAME` → `CursorKind.MOVE`
- `AXZONE_ZOOM` → `CursorKind.ZOOM_V`（旧 Cross）
- `AXZONE_PAN` → `CursorKind.PAN_V`（旧 OpenHand）

`hoverMoveEvent`（活性化ゲート＝PC-13）:
- アクティブ軸（`_vm_axis_index == view._active_axis_index`）→ `self.setCursor(cursor(self.cursor_for_local(...)))`
- 非アクティブ軸 → `self.setCursor(cursor(CursorKind.ACTIVATE))`（旧 `unsetCursor`）。「クリックで活性化」を示し、操作モデルと一致。
- `hoverLeaveEvent` は `unsetCursor`（不変）。

## 5. PC-22（カーソル線）— ドラッグ可アフォーダンス

`_make_cursor_line` の生成直後に `line.setCursor(cursor(CursorKind.DRAG_H))`（=SizeHor）。A/B 両線に適用（`_make_cursor_line` は両方が通る）。色ハイライト（hoverPen）とは独立の静的形状で十分（線は常に水平ドラッグ）。

## 6. オフセット誤発火 — プロット領域の曲線アフォーダンス

**現状**: `mousePressEvent` の `ZONE_PLOT` 分岐が `_curve_at`（`CURVE_HIT_TOL_PX=8px` 以内）で曲線を拾うと即 `_begin_offset_drag`。ホバー時のカーソルは Arrow のままで、オフセット発火が不意打ち。

**修正（アフォーダンス）**: view に `_hover_cursor(pos: QPointF) -> CursorKind` を新設:
```
zone = self._zone_at(pos)
if zone == ZONE_PLOT and self._curve_at(pos) is not None:
    return CursorKind.DRAG_H   # オフセットドラッグ可のヒント
return cursor_for_zone(zone)
```
`eventFilter`/`mouseMoveEvent` は `self.setCursor(cursor(self._hover_cursor(pos)))` を使う。曲線から離れたプロット領域は Arrow のまま。**挙動（オフセット発火条件）は不変** — 曲線上の左ドラッグがオフセットであることを事前にカーソルで示し、不意打ちを解消する。

## 7. データフロー（不変）
ホバー移動 → `eventFilter`（viewport no-button move）／`mouseMoveEvent` → `_hover_cursor(pos)`（純粋 kind）→ `cursor(kind)`（レジストリ）→ `setCursor`。軸は `_AlignedAxisItem.hoverMoveEvent` → `cursor_for_local`（純粋 kind）→ `cursor(kind)`。カーソル線は生成時 `setCursor` 一度。

## 8. エラー処理・エッジ
- `cursor(kind)` は未知 kind に Arrow フォールバック（防御的）。
- QPixmap 生成は QApplication 必須 → 遅延（初回ホバー時）。ヘッドレステストは pytest-qt の QApplication 下で実行。
- 非アクティブ軸ホバー時も `set_hover_axis` は従来どおり呼ぶ（hover フレーム描画は不変）。

## 9. テスト戦略（GUI テストレイヤー準拠）
- **Layer A（純粋・レジストリ）**: `cursor_for_zone`/`cursor_for_local` が各ゾーンで期待 `CursorKind` を返す。`cursor(kind)` が標準 kind で期待 `.shape()`、`ZOOM_H/ZOOM_V` で `Qt.CursorShape.BitmapCursor`（カスタム pixmap）を返し、同一 kind は同一オブジェクトをキャッシュ（`is`）。
- **Layer B（qtbot）**: 非アクティブ Y 軸ホバー → `PointingHandCursor`／アクティブ軸ゾーン → 期待形状。カーソル線が `SizeHorCursor` を持つ。プロット領域で曲線上ホバー → `SizeHorCursor`、曲線外 → Arrow。X inner/outer ホバー → zoom(BitmapCursor)/pan(SizeHor)。
- **Layer C（realgui・ローカル `--realgui`）**: 実 OS ホバーで X inner=カスタムズーム／outer=SizeHor／Y 非アクティブ=PointingHand／カーソル線=SizeHor の実カーソル形状を確認（`QCursor` の実適用は合成イベントで false-green になり得るため実機ゲート）。
- **無回帰**: 既存 `test_graph_panel_zoom.py`（cursor_for_zone）・`test_axis_interaction.py`（cursor_for_local）・`test_x_hover_cursor.py` を新契約（`CursorKind`）へ更新。

## 10. ファイル構成
- **新規**: `gui/views/cursor_shapes.py`（`CursorKind`・`cursor()`・`_build_zoom_cursor`）、`tests/gui/test_cursor_shapes.py`（レジストリ Layer A）。
- **変更**: `gui/views/graph_panel_view.py`（`cursor_for_zone`/`cursor_for_local` を kind 返却化・`hoverMoveEvent` 活性化ゲート・`_make_cursor_line` setCursor・`_hover_cursor` 新設・`eventFilter`/`mouseMoveEvent` 配線）。
- **テスト更新**: `test_graph_panel_zoom.py`・`test_axis_interaction.py`・`test_x_hover_cursor.py`。realgui: `tests/realgui/test_axis_cursor_shapes.py`（新規・任意実行）。

## 11. 非ゴール
オフセット操作の**トリガ条件変更**（本増分はアフォーダンス提示のみ・発火条件は不変）／PC-03 オフセット起動導線の別解決／カーソル形状のテーマ連動配色／X 軸のグリップ/リサイズ（存在しない）。

## 12. トレーサビリティ
catalog: **PC-22 / PC-13 / PC-14 を解消**（増分②）。実装プラン: `docs/superpowers/plans/2026-07-05-cursor-axis-pointer-shapes.md`（writing-plans）。ブランチは①（PR #49）にスタック、①マージ後に PR base を main へ retarget。
