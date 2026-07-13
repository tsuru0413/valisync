# FU-22 (A) active-file 同一キーガード 設計 spec

## 背景と課題

アクティブファイルをセットすると ChannelBrowser の 264k 行モデルが同期リビルドされ GUI が ~5s フリーズする(FU-22)。FU-21 調査中に実測発見。real widget tree・prod スケール(prod_demo.mf4 264,004 信号)の実測で**2側面**に分解した:

- **(A) 無条件 same-key re-fire**(本 spec のスコープ): `AppViewModel.set_active_file(key)` が同一キーでも無条件に `_notify("active_file")` し、ChannelBrowser を丸ごと再リビルドする。ロード直後の file-list 行は視覚未選択(currentIndex 無効)ゆえ、**初回右クリックで `setCurrentIndex` が selectionChanged を発火 -> `select_file` -> `set_active_file(同一 key)`** となり ~5s の再リビルドが走る(同一行2回目は Qt が selectionChanged を抑制し 1ms)。
- **(B) 真の activate/切替の 264k 構築コスト自体**(別サブスペック): 別ファイル選択・ロード時 auto-active でも ~5s。

## 実測(systematic-debugging Phase 1・確定)

repro(build_main_window + `app_vm.request_load(prod_demo.mf4)`・offscreen・real widget tree):

| 計測 | 値 |
|---|---|
| (B) cold build (first set_active_file) | 5,097 ms |
| (A) same-key re-fire CURRENT | 5,230 ms |
| (A) same-key re-fire GUARDED (`set_active_file` 同一キー no-op) | 2.8 ms |
| (B) genuine switch (None->key) | 4,805 ms |

内訳(sync/deferred + proxy 分離)で **(B) の支配コストは VM の SignalItem 構築(484ms)ではなく**、QTreeView が 264k フル model reset に同期反応(~2,750ms)＋ QSortFilterProxyModel(PC-20 ソート)の 264k 再マップ(~1,550ms)であることも確定(deferred processEvents は 3ms＝delayed-layout 仮説は棄却)。よって (B) は view 仮想化の大スコープで**本 spec では扱わない**。

## スコープ(本 spec = (A) のみ)

**(A) 無条件 same-key re-fire を SOURCE ガードで根絶する。** (B) の view 仮想化は別サブスペック(別 brainstorming)へ分離する(ユーザー合意・2026-07-13)。(A) 単独では genuine な別ファイル選択の ~5s は残るが、(A) は純粋な重複バグで安価・低リスク・高 value。

## 設計

### 変更点(1箇所)

`AppViewModel.set_active_file`(`src/valisync/gui/viewmodels/app_viewmodel.py`)の先頭に同一キーガードを追加:

```python
def set_active_file(self, key: str | None) -> None:
    """Set the active file and notify subscribers ('active_file')."""
    if key == self._active_file_key:
        # FU-22: 同一キー再選択は state 不変。無条件 notify は ChannelBrowser の
        # 264k リビルドを重複起動する(prod 実測 ~5s)。同一キーは no-op で根絶。
        return
    self._active_file_key = key
    self._notify("active_file")
```

### なぜ SOURCE(set_active_file)か(handler 側 skip でなく)

- **副作用ゼロを実コードで確認**: `"active_file"` に反応する購読者は 2 つだけ - `ChannelBrowserVM._on_app_change`(264k リビルド＝まさに消したい対象)と `MainWindow._update_window_title`(同一キーでは同一文字列で冪等)。`file_browser_vm`/`data_explorer_view`/`graph_area_vm` は `"active_file"` を購読しておらず影響なし。
- **最小・最根本**: 元凶は `_on_app_change` が `_ensure_prep` の既存 early-return(`_prep_key == active_key`)を `_prep_key=None` で自ら壊す点。source で notify を止めれば handler 側の無効化も走らない。handler 側 skip は「無駄な notify を購読者へ投げ続ける」分散リスクが残る。
- **ロード経路は非依存**: ロードは別イベント `"loaded"` が `ChannelBrowserVM.refresh()` を呼ぶ経路で、同一キー activate に依存しない。
- **None ケースも安全**: unload は自前ガード済み。`select_file(-1) -> None` は既に None なら no-op で問題なし。

### テスト設計(gui-test-plan 分類: VM 純ロジック -> Layer A/B・realgui 不要)

ユーザー可視効果 = 「同一キー再選択で ChannelBrowser が丸ごとリビルドされない(5s フリーズが消える)」。これは model reset 回数で決定論的に観測でき、prod スケール不要(5,230ms->2.8ms は Phase 1 repro で実測済み・本 spec に記録)。

- **Layer A(AppViewModel)**:
  - `test_set_active_file_same_key_is_noop`: notifications を購読し `set_active_file(key)`(1発目 notify) -> クリア -> `set_active_file(同一 key)` で `"active_file"` notify が**出ない**。state(`active_file_key`)は不変。
  - `test_set_active_file_genuine_change_still_notifies`: None->key、key->別key で `"active_file"` が出る(ガードが genuine 変更を塞がない無回帰)。
- **Layer B(ChannelBrowserVM + SignalTableModel 統合)**:
  - `test_same_key_activation_does_not_rebuild_model`: 実 `SignalTableModel` の `beginResetModel` 呼び出し回数を記録。`set_active_file(key)`(1回 reset) -> `set_active_file(同一 key)` で **reset 回数が増えない**(honest observable＝ユーザーの 5s フリーズ源)。sabotage-RED: ガードを外すと reset が 2 回に増え RED。
  - `test_genuine_switch_rebuilds_model`: 別キーへ切替で reset される(無回帰)。

### catalog 反映

`docs/audit-findings-catalog.md` の FU-22 行を更新: (A) を✅解消(feature ブランチ名・実測値)、(B) は「QTreeView+proxy の 264k フル reset 反応が支配的(tree ~2,750ms + proxy ~1,550ms・VM SignalItem は 484ms のみ)＝view 仮想化の別サブスペックへ」と実測付きで記録。

## YAGNI で除外

- (B) の view 仮想化(fetchMore incremental / PC-20 proxy を VM 側ソートで撤去 / 264k を一度にビューへ入れない): 別サブスペック。
- `_on_app_change` の追加ガード: source ガードで無効化自体が走らないため不要。
