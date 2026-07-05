# 設計 spec: rendering-correctness（RN-01/RN-02 — 描画の正しさ）

波形描画のビューポート処理が、疎な信号のズーム時消失（RN-01）と別時間域の追加信号の無表示無告知（RN-02）で黙ってデータを見えなくする2件を解消する。いずれも「表示されるべきデータが気づかれず消える」サイレント欠陥。③ 正しさクラスタ（analysis-correctness に続く描画側）。

- **作成**: 2026-07-05
- **ステータス**: 設計（brainstorming 承認済み・writing-plans へ）
- **関連**: [audit-findings-catalog](../../audit-findings-catalog.md) SS-RENDER（RN-01/RN-02）／描画の正しさは analysis-correctness（AN-01/02/03）と同じ「サイレントなデータ欠落を断つ」方針の延長
- **前提コード**: `src/valisync/gui/viewmodels/graph_panel_vm.py` の `build_render()` 系（X 窓スライス）・`_auto_fit_ranges()`・`set_x_range()`・`reset_x()`・`x_range` フィールド

---

## 1. スコープと確定判断（brainstorming・ユーザー決定）

| ID | 現状の欠陥 | 決定 |
|---|---|---|
| RN-01 | X 窓スライスが `ts[lo_idx:hi_idx]`（窓内厳密・`searchsorted` left/right）で、窓を横切る線分の端点（窓外の隣接サンプル）を落とす。疎信号をズームすると窓内にサンプルが無く**丸ごと消える** | **窓外の隣接サンプルを左右1点ずつ取り込む**（`lo_idx-1`／`hi_idx+1` へ拡張・両端クランプ）。窓を横切る線分が描かれる |
| RN-02 | `_auto_fit_ranges` が `x_range is None` のときだけフィット。最初の自動フィットで非 None になると以後「手動扱い」となり、別時間域の2本目信号が**窓外で無表示・無告知** | **`_x_range_is_auto` フラグ**を導入。自動フィット中は追加時に全プロット信号の時間**和集合へ拡張**。手動ズーム後（`set_x_range` 済み）は尊重して触らない（Reset X が受け皿） |
| RN-02 手動時 | 手動ズーム中に範囲外信号を追加したケース | **何もしない**（ズーム尊重・既存 `reset_x()` で全体表示・ユーザー決定）。通知チャネルの新設はしない（YAGNI） |

## 2. 現状分析（根因の確定事実）

**RN-01（`graph_panel_vm.py` の窓スライス）**:
```python
lo_idx = int(np.searchsorted(ts, x_lo, side="left"))
hi_idx = int(np.searchsorted(ts, x_hi, side="right"))
ts_slice = ts[lo_idx:hi_idx]   # 窓 [x_lo, x_hi] 内のサンプルのみ
```
疎信号（例 t=0,100,200）を窓 [40,60] にズーム → `lo_idx=1, hi_idx=1` → `ts[1:1]` = 空 → 空スライス分岐で RenderCurve が空 → **プロットに何も描かれない**。実際は t=0 と t=100 を結ぶ線分が [40,60] を横切っており、その端点さえあれば描画できる。

**RN-02（`_auto_fit_ranges`）**:
```python
if self.x_range is None:
    ... # 全プロット信号の和集合で x_range をフィット
```
`x_range` は「最初の自動フィット」でも非 None になる。以後 add_signal → `_auto_fit_ranges` は「None でない＝手動」とみなして**何もしない**。別録画/別時間域の2本目信号（例 [500,600]）を先行信号 [0,100] の上に追加すると、窓 [0,100] の外にいて RN-01 のスライスで空になり、**凡例には出るがプロットは空**（サイレント失敗）。`reset_x()`（union フィット）で救えるがユーザーは気づけない。

**既存の関連機構**: `reset_x()`（line 504）は明示的に全信号の和集合へフィット（ユーザー操作）。`set_x_range()`（line 485）は手動ズーム/パンで範囲を設定。`x_range` は `__init__`（line 129）で `None` 初期化。

## 3. 設計

### 3.1 RN-01: 窓スライスに境界サンプルを取り込む

窓スライスを窓外の隣接サンプル1点ずつまで拡張する（該当スライス箇所すべてに適用）:

```python
lo_idx = int(np.searchsorted(ts, x_lo, side="left"))
hi_idx = int(np.searchsorted(ts, x_hi, side="right"))
lo_ext = max(0, lo_idx - 1)          # 窓に入る手前の1点
hi_ext = min(len(ts), hi_idx + 1)    # 窓を出た直後の1点
ts_slice = ts[lo_ext:hi_ext]
vs_slice = vs[lo_ext:hi_ext]
```

- **効果**: 窓内にサンプルが0点でも、窓を横切る線分の両端点が含まれ pyqtgraph が線を描く。疎信号のズーム消失が直る。
- **ダウンサンプリングとの整合**: 拡張後スライスがそのまま `Session.downsample` の入力になり、境界点が保存される（可視域の線分アンカー）。
- **信号終端より後の窓**（例 [300,400]・信号は t≤200）: 拡張で t=200 の1点を含むが、その点は可視 x 域の外でビューにクリップされ**外挿線は描かれない**（正しい・信号は存在しない区間を捏造しない）。
- **全体表示（`x_range is None`）時**: 元々全域スライスなので拡張は無影響（回帰なし）。
- **空信号（len(ts)==0）**: 従来どおり空 RenderCurve（凡例のみ）。

### 3.2 RN-02: 自動フィット状態を追跡し和集合へ拡張

**`_x_range_is_auto: bool`** を導入（`__init__` で `True`）:

- `set_x_range(lo, hi)`: 手動操作なので `_x_range_is_auto = False`。
- `reset_x()`: ユーザーが明示的に全体表示 → `_x_range_is_auto = True`（以後の追加でまた和集合拡張に戻る）。
- `_auto_fit_ranges()`: 条件を `x_range is None` から **`self._x_range_is_auto`** に変更。auto のとき、全プロット信号の時間和集合を計算して `x_range` に設定（現状の union 計算ロジックをそのまま流用）。フィット可能な信号が0本なら `x_range = None` のまま（据え置き）。
  - auto かつ現状 `x_range is None` の初回も同じ経路でフィット（挙動維持）。
- **手動ズーム後の範囲外追加**: `_x_range_is_auto is False` なので `_auto_fit_ranges` は何もしない＝ズーム尊重（ユーザー決定）。追加信号は `reset_x()` で見える。

> `reset_x()` は既に union フィットしているので、`_x_range_is_auto = True` を立てる1行を足すだけ。`_auto_fit_ranges` の union 計算は `reset_x()` と同一なので、必要なら小さなヘルパ `_union_time_extent()` に切り出して両者で共有（DRY・任意）。

### 3.3 対象ファイル・非ゴール

- 対象: `src/valisync/gui/viewmodels/graph_panel_vm.py` のみ（窓スライス箇所・`__init__` の `_x_range_is_auto`・`set_x_range`・`reset_x`・`_auto_fit_ranges`）。View 層・他 VM は不変更。
- 非ゴール: 手動ズーム中の範囲外追加の通知チャネル新設（YAGNI）／RN-03（リサイズ毎 LOD 再計算）・RN-04（X 同期のスレッド化）・RN-05（定数信号の零幅 Y 軸）＝性能/別課題で別増分／Y 軸オートフィット（既存の finite フィルタ済み・AN と別）／描画の NaN ギャップ表示（現状維持）。

## 4. 検証（Layer A・VM 単体）

GUI レンダ経由の false-green（memory `gui_offset_render_test_xrange_pitfall`＝auto-fit が窓外でビューポート誤リセットしキャッシュキー変化で見かけ上通る罠）を避けるため、テストは **x_range を広く明示固定**し RenderCurve の中身（timestamps 配列）を直接検証する。

- **RN-01**:
  - 疎信号（ts=[0,100,200]）を x_range=[40,60] にして `build_render` → 対象 RenderCurve の timestamps に境界2点（0 と 100）が含まれる（窓内0点でも線が引ける）。
  - 信号終端後の窓（x_range=[300,400]・ts≤200）→ 可視化される端点は終端の1点のみ（外挿の捏造なし）。
  - 全体表示（x_range=None）→ 全サンプルが出る（回帰）。
  - ダウンサンプリング発動時（len>n_target）でも境界点が保存される。
- **RN-02**:
  - 信号A[0,100]追加 → x_range=[0,100]・`_x_range_is_auto is True`。
  - 続けて信号B[500,600]追加 → x_range=[0,600]（和集合へ拡張）。
  - `set_x_range(40,60)`（手動）→ `_x_range_is_auto is False`。その後 信号C 追加 → x_range 不変（[40,60] 尊重）。
  - `reset_x()` → x_range=union・`_x_range_is_auto is True`（auto へ復帰）。
  - フィット可能信号0本 → x_range=None のまま。
- **回帰**: 既存の graph_panel_vm レンダ/レンジ系テスト（`tests/gui/test_graph_panel_*`）が全て緑。

## 5. エッジケース・留意点

- **RN-01 の境界拡張と重複タイムスタンプ**: `sorted_view()`（keep-last 済み・厳密単調）上でスライスするので `searchsorted` は安定。拡張は index ±1 のクランプのみで単調性に依存しない。
- **RN-02 の和集合と空信号**: 長さ0の信号は union 計算でスキップ（既存 `_auto_fit_ranges`/`reset_x` と同じガード）。
- **手動判定の粒度と X 同期**（確認済み）: パン/ズームは `set_x_range` 経由で手動扱い。X 同期は `graph_area_vm.py:248` で兄弟パネルへ `panel.set_x_range()` を通して伝播するため、同期パネルも `set_x_range` 経由で `_x_range_is_auto = False` になりドライバのレンジに追従する——これは**望ましい**（同期中は独立オートフィットせずドライバに従う）。オートフィットの union 拡張による range 変更も同期経由で兄弟へ伝播するが、graph_area_vm の既存の再入ガードでループしない。経路を分ける必要はない。
- **y_range は対象外**: 本増分は x 軸のみ。Y オートフィットは既存挙動（finite フィルタ済み）を維持。

## 6. 非ゴール

RN-03/04/05（性能・Y 軸退化）／通知チャネル新設／描画エンジンの変更／X 同期の再設計。

## 7. トレーサビリティ

catalog: **RN-01/RN-02 を ✅解消**（SS-RENDER のうち描画正しさ2件・残り RN-03/04/05 は性能/別課題）。実装プラン: `docs/superpowers/plans/2026-07-05-rendering-correctness.md`（writing-plans で作成）。
