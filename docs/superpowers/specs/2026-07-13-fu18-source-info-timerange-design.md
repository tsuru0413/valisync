# FU-18（source_info hover のフリーズ＋FU-20 float64 キャッシュ blowup）設計 spec

Tier 3 perf。ソース情報ツールチップの hover で `Session.source_info` が全信号に `sorted_view()` を呼び、初回 hover でフリーズ。FU-20 後は各 sorted_view が値を float64 upcast＋キャッシュするため、hover 一発で全信号の float64 キャッシュを materialize し **FU-20 のメモリ勝ちを打ち消す**。真因を実機で確定した。

## 真因（実機確定・2026-07-13）

`source_info`（`session.py:235-236`）は t_min/t_max のためだけに `group.signals`（最大 330k）全てへ `s.sorted_view()[0][0]`/`[0][-1]` を呼ぶ。だが必要なのは timestamps の **min/max のみ**で、sorted_view の①argsort ②値 float64 upcast ③per-Signal キャッシュ汚染 の**いずれも不要**。

hover 経路確定: `qt_signal_models.data(ToolTipRole)`（`:92`）→ `FileBrowserVM.tooltip_text`（`:82`）→ `file_info`（`:78`）→ `session.source_info`。素の QListView なので Qt 既定ツールチップが dwell で自動発火（クリック不要）。

`prod_demo.mf4`（264,004 信号・headless）実測:

| | 初回 hover | RSS 増分 | sorted_view キャッシュ |
|---|---|---|---|
| **現状（sorted_view）** | **7,689 ms** | **+4.69 GB** | 264k 全 populate |
| A（生 min/max・per-signal） | 2,047 ms | 0 GB | 0 |
| **A+B（master id dedup・分離マイクロ測定）** | **0 ms** | **0 GB** | **0** |
| **A+B（実装後の統合実測）** | **41 ms** | **+0.00 GB** | **0** |

**unique master timestamp 配列は 5 本のみ**（264k 信号が channel-group ごとの master を共有＝`mdf_loader.py:506 timestamps=master`＋`signal_group_manager.py:85` pass-through で id 同一）。id() dedup で 264k→5 reduction に潰れる。上表の「0ms」は dedup 済み 5 本の min/max のみを測った分離値で、**実装後の実コードは `{id(s.timestamps): s for s in group.signals}` の O(n) dict 内包（264k の id/len 走査）ぶんで 41ms**（フリーズ閾値を遥かに下回り体感ゼロ・2回目 44ms でキャッシュ非増加）。t_min/t_max は現状と一致（0.0/119.99）。**full 330k 展開なら float64 キャッシュ blowup は ~10.8GB で再 OOM**。

`sorted_view()[0][0]`=min timestamp・`[0][-1]`=max timestamp の等価性: sorted_view は ts 昇順ソート＋keep-last dedup だが **dedup は内部重複のみ除去し端点を保存**するので raw `timestamps.min()/.max()` と厳密に等価。timestamps は `Signal.__post_init__` の isfinite ガード（`signal.py:32`）で有限保証 → min/max が NaN 化する懸念なし。

## 修正: 生 timestamps min/max ＋ master dedup（A+B）

### A（必須・メモリ安全の核）
`source_info` の t_min/t_max 計算を `sorted_view()` から**生 timestamps の min/max**へ置換。sorted_view の argsort・float64 upcast・キャッシュ汚染を全撤去＝**+4.69GB blowup（FU-20 の勝ちを打ち消す再 OOM リスク）を除去**。

### B（初回速度）
group 内で timestamps を `id()` で dedup し、**unique master ごとに1回だけ** min/max（264k→5・2047ms→0ms）。

### ガードレールヘルパ `Signal.time_range()`
`Signal` に `time_range() -> tuple[float, float] | None` を追加（空なら None・raw timestamps の min/max・**sorted_view を誘発しない**）。source_info の dedup 済み代表信号に適用。将来 `sorted_view()[0][0]` で範囲を取る誤用（＝FU-18 の再発）を防ぐ discoverable な正道。core は Qt 非依存を維持。

### engine.py は変更しない（fork 助言の是正）
`engine.py:322-323` も `sorted_view()[0][0/-1]` の同型パターンだが、**line 328 `ts = signals[n].sorted_view()[0]` が結果グリッド構築に refs の sorted_view を本当に使う**ため、322-323 をヘルパ化しても refs の float64 キャッシュ materialize は 328 で起き**回避されない**（一次情報で確認）。よって engine.py 変更は blowup を先回りできずスコープクリープ＝**本 spec では触れない**。formula refs は少数で bounded なので緊急性もない。

### C（メモ化）棄却
A+B で実測 41ms（体感ゼロ・一度きりの O(n) 走査）のため YAGNI。仮に将来メモ化するなら不変フィールド（t_min/t_max/n_channels/format）のみ・`size_bytes`（`source_path.stat().st_size`）は揮発値なので毎回 re-stat。本 spec では非採用。

### 影響範囲（負の契約）
- **VM・GUI・hover 経路の配線は不変**（source_info の内部計算のみ変更・戻り値 `SourceInfo` の型/フィールドは不変）。
- `sorted_view()`/`finite_view()`/FU-20 の native dtype 保持は不変。
- `if len(s.timestamps)` の空信号ガードは維持（空信号は範囲に寄与しない）。
- `size_bytes` の毎回 stat は不変。

## テスト（gui-test-plan ②）

`_sorted_view_cache` が populate されたか（＝source_info が sorted_view を誘発したか）が **honest observable**。RSS 実測より CI で安定・決定的。

- **Layer A（core・ヘッドレス）**:
  - **キャッシュ非汚染（核）**: 共有 master を持つ多数信号の group をロード → `source_info(key)` → 全 `group.signals` の `getattr(sig, "_sorted_view_cache", None) is None` を assert。sabotage（旧 `sorted_view()[0][0]` 復帰）で cache populate → RED。
  - **値正しさ**: 非単調/重複 timestamps を含む信号を持つ group で `source_info().t_min/t_max` が真の min/max（raw timestamps 全体の最小/最大）と一致。sorted_view 経由でも同値だが、raw min/max が端点で厳密一致することを lock。
  - **空信号ガード**: 空 timestamps 信号が混在しても t_min/t_max は非空信号のみから算出（空 group は None）。
  - `Signal.time_range()` の単体: 通常/非単調/空（None）。
- **ローカル手動（realgui 同様のゲート）**: 実 `prod_demo.mf4` で `source_info` 初回時間 ~0ms・RSS 非増加を Win32 実測（本 spec の 7689ms/+4.69GB→0ms/0GB の実機再現）・証拠添付。CI では prod が重いためローカル限定。
- prod スケール必須（264k/共有 master の dedup 効果・float64 キャッシュ blowup はスケール依存）。

## ファイル構成（変更予定）
- `src/valisync/core/models/signal.py`: `Signal.time_range()` 追加。
- `src/valisync/core/session.py`: `source_info` の t_min/t_max を master dedup＋`time_range()` へ置換。
- テスト: `tests/test_session.py`（source_info キャッシュ非汚染・値正しさ・空ガード）・`tests/test_signal_sorted_view.py` または該当（`time_range()` 単体）・ローカル prod perf スクリプト（非コミット）。
- **不変**: engine.py・VM・GUI・hover 配線・SourceInfo 型・sorted_view/FU-20。
