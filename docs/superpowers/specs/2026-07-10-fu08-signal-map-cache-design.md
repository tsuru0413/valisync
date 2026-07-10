# FU-08 — 信号マップ・キャッシュ化による大容量オートフィット高速化 設計

## 目的

大容量ファイル（prod: 264,004 信号）ロード状態で、**信号を1本プロットするたび約8秒フリーズ**する問題を解消する。信号追加・Y軸オートフィットを大容量でも ~数ms にする。

## 根因（実測確定・2026-07-10）

`GraphPanelVM._signal_map()`（`gui/viewmodels/graph_panel_vm.py:1220`）は呼ばれるたびに `session.signals()` の全信号をループして `{name: Signal}` 辞書を再構築する。その `session.signals()` は `SignalGroupManager.signals()`（`core/loaders/signal_group_manager.py:99`）へ委譲し、これが **`_namespaced()`（L67）で全信号ぶんの namespaced `Signal` ラッパーを毎回新規生成**している（264k オブジェクト生成＋辞書構築）。

prod 実測:
- 信号1本プロット（`add_signal`→`_auto_fit_ranges`）: **~8,000ms**
- `reset_y()`（100信号オートフィット）: **~5,400ms**
- 対して `finite_view()`（キャッシュ済）＋min/max のみ: **2.07ms**（＝約2600倍の無駄）

`_signal_map()` の呼び出し元は9箇所（`reset_y`/`reset_axis_y`/`reset_x`/`_auto_fit_ranges`＝信号追加のたび・他）。`render_data`(L787) も呼ぶがレンダキャッシュ経由で通常 paint は無影響。加えて `graph_panel_vm.py:489` の reconcile も `{s.name for s in session.signals()}` で同じ264k走査を踏む。

当初カタログ仮説（`vs[np.isfinite(vs)]` の min/max が重い）は**誤り**（それは2ms）。真犯人は `session.signals()`／`_namespaced` のフルセッション再構築。

## アプローチ（採用：A＝ソース根治）

再構築の発生源である `SignalGroupManager` に namespaced 信号マップをキャッシュし、`add()`/`remove()`（＝ファイル load/unload）でのみ無効化する。`session.signals()` を含む全経路が一挙に高速化し、264k ラッパーの毎回再生成も消える。

不採用: B（パネル局所キャッシュ＝パネルごと264kマップ保持・reconcile 等は速くならない・session 変更通知の新規配線が要る）／C（`_signal_map` を per-key 参照へ＝9箇所改修・結局 source 基盤が要りAに収束）。

## 設計

### コンポーネント① `SignalGroupManager`（`core/loaders/signal_group_manager.py`）

**状態追加**: `_namespaced_map: dict[str, Signal] | None`（初期 `None`）。

**遅延構築＋キャッシュ**: 内部ヘルパ `_ensure_namespaced_map()` が `None` のとき全グループを走査して namespaced `{name: Signal}` 辞書を構築・保持する（現行 `signals()` のロジックを1回だけ実行）。`_namespaced()` によるラッパー生成もここで1回だけ。順序は `_groups` の挿入順×各グループ内順（現行 `signals()` と同一）。

**公開 API**:
- `signals() -> list[Signal]`: `list(self._ensure_namespaced_map().values())` を返す（現行契約＝毎回新規リストを維持・順序保存）。
- 新 `signal_map() -> Mapping[str, Signal]`: `MappingProxyType(self._ensure_namespaced_map())` を返す（**読取専用ビュー**でキャッシュを外部変異から保護）。

**無効化**: `add()`（L34 の後）と `remove()`（L44 の前後）で `self._namespaced_map = None`。この2つが `_groups` の唯一の変異点（確認済み）。

**据え置き**: `group_signals(key)`（L92）はホットパスでないため現状維持（別グループ観点で新規ラッパーを返す。挙動は sorted_view 委譲経由で `signals()` と機能等価）。

### コンポーネント② `Session`（`core/session.py`）

- 新 `signal_map(self) -> Mapping[str, Signal]`: `return self._groups.signal_map()`。
- `signals()`（L188）は現行のまま（委譲先がキャッシュ化されるだけ）。

### コンポーネント③ `GraphPanelVM._signal_map()`（`gui/viewmodels/graph_panel_vm.py:1220`）

```
base = self._session.signal_map()          # キャッシュ・O(1)（MappingProxy）
if not self._file_offsets and not self._signal_offsets:
    return base                            # 常態＝ゼロコピー返し
result = dict(base)                         # 稀（オフセット有り）: 浅コピー O(N)
#  該当信号のみ apply_offset で上書き:
#   - signal offset: 当該 namespaced name
#   - file offset:   当該グループ prefix の信号（session.group_signals で列挙）
#  apply_offset の入力は base ラッパー。生成される offset 済み Signal には
#  _sorted_view_delegate を付けない（別配列のため・signal_group_manager L87 の不変条件）
return result
```

戻り値は「読取専用マッピング」（常態は `MappingProxy`、オフセット時は素の `dict`）。呼び出し元はいずれも `.get(key)` の読取のみで、双方が対応。**実装時に `_signal_map()` の全9呼び出し元が読取専用（`MappingProxyType` を破壊的操作せず `.get()`/反復のみ）であることを確認する** — 破壊的に使う箇所があれば当該箇所で `dict(...)` 化するか設計を見直す。

## データフロー

1. ファイル load（GUI スレッドの `register_loaded`）→ `SignalGroupManager.add()` → キャッシュ無効化。
2. 次の `signals()`/`signal_map()` 呼出で1回だけ namespaced マップを構築・キャッシュ。
3. 以降の `add_signal`/`reset_y`/`reset_axis_y`/`reset_x`/reconcile はキャッシュを O(1) 参照（オフセット無し時）。
4. ファイル unload → `remove()` → キャッシュ無効化 → 次回再構築。

## 正しさ・整合

- **不変性**: `Signal` は frozen（配列も writeable=False）。namespaced ラッパーもキャッシュ後は不変に扱う。`_groups` の変異は `add`/`remove` のみ＝無効化はこの2点で必要十分。
- **スレッド**: ファイル解析はオフスレッドだが、`_groups` への `add`/`remove` と GUI からの参照は GUI スレッド上で直列（`register_loaded` は GUI スレッド）＝競合なし。
- **オフセット委譲の禁則**: `apply_offset` は元と別の配列を持つ Signal を返すため、`_sorted_view_delegate` を付けない（元の単調性キャッシュを別配列に誤共有しない）。既存 `_namespaced` の不変条件（L87）を踏襲。
- **メモリ**: namespaced ラッパー約264k個を永続保持（参照＋name 文字列で ~26MB 規模）。1.36GB ロード時に無視可。従来は毎回生成・破棄していたぶんの churn が消える。
- **空セッション**: マップは空辞書。`signals()` は空リスト。

## テスト戦略（GUI 入力経路の変更なし＝Layer A のみ・realgui 不要）

**コア単体（`tests/` core）**:
- `signal_map()`/`signals()` の内容・名前空間・順序が現行と一致（複数グループ）。
- 無効化: `add` 後に新グループ信号が現れる／`remove` 後に消える（stale なし）。
- キャッシュ同一性: 連続 `signal_map()`（および `signals()`）が**同一ラッパーオブジェクト**（`is`）を返す＝再構築されない perf ロック。
- `MappingProxyType` が読取専用（代入で `TypeError`）。

**VM 単体（`tests/gui` viewmodel・offscreen）**:
- オフセット無しで `_signal_map()` が `session.signal_map()` と同一内容（ラッパー同一性）。
- オフセット有りで対象信号のみ時間シフトが適用され、非対象は base ラッパーのまま。file offset がグループ全体に及ぶこと。
- `reset_y`/`reset_axis_y`/`add_signal` のレンジ結果が現行と不変（挙動保存・回帰防止）。
- 呼出回数スパイ（`_namespaced` or `SignalGroupManager.signals` 実構築）で「複数回 `add_signal`/`reset_y` してもマップ構築は1回」を固定。

**perf 回帰ガード**:
- prod はCIに載せられないため、合成の多グループ（例: 5万 name）を組み、`reset_y`/連続 `add_signal` が閾値内（例 <100ms）で完了することを assert（O(N) 再構築が復活したら落ちる）。

## スコープ外

- `group_signals(key)` の最適化（ホットパス外）。
- FU-02/03/04 等その他フォローアップ（別タスク）。
- ダウンサンプラ・レンダ経路（RN-04 で対応済み・本件と独立）。

## 成功基準

- prod（264k 信号）ロード状態で、信号1本 `add_signal` と `reset_y`（100信号）が **~数十ms 以内**（現行 8000ms / 5400ms から2桁以上改善）。
- 既存のオートフィット挙動（レンジ結果）が不変。
- 品質ゲート（pytest / ruff / mypy）全通過。
