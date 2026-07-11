# FU-16 remove_group 遅延分割解放 — gui-test-plan 分析（②十分な E2E 受け入れ設計）

> `/gui-test-plan` の出力。writing-plans がタスクへ織り込む。設計 spec: `2026-07-12-fu16-remove-group-deferred-teardown-design.md`。

## 全体ジャーニーと横断制約

- **ジャーニー**: 「閉じる」区間（開く→…→**閉じる**）。ユーザーは close「Yes」→ 即クローズ＋File Browser 行にスピナー→ UI 固まらず→ 数秒後スピナー行が消える、を体験する。
- **横断的な決定的ゲート = perf E2E（prod 330k・実ロード経路）**。過去、内部 `request_load`／小データ／`ExpansionConfirmer` 未 patch で **6s を 950ms と誤測**した（[[gui_perf_e2e_repro_must_drive_real_load_path]]）。本計画の perf E2E は必ず:
  1. 実アプリ経路（`MainWindow._load_file` オフスレッド）でロード。
  2. `ExpansionConfirmer` を全展開に patch → **`len(session.signals()) == 330_004` を検証**（~10 GB 到達の実証）。
  3. 実 close（`_confirm_and_unload`）→ graveyard→byte-budget drain を回す。
  4. **20 ms QTimer heartbeat で drain 中の最大 gap を実測**。
- **合格閾値（本計画で確定）**: 同期 close **< 200 ms**／drain 中 heartbeat **最大 gap < 150 ms**。byte-budget 既定 64 MB はこれを満たすよう調整（測定超過なら縮小）。honest-RED=現行同期 remove_group（~7 s 単発 gap）。

---

## Task A: core — `RemovalResult.removed_group`（グループ手渡し）
- **変更種別**: VM/純ロジック（core・可視挙動不変）
- **触れるユーザージャーニー**: 無し（配管。効果は close 経路の perf E2E で exercise）
- **E2E 受け入れ**: 直接の可視効果なし → **Layer A のみ**。
- **必要レイヤー**: A=必須 / B=不要 / 入力経路 E2E(C)=不要 / perf E2E=不要（効果は Task B/C）/ 描画=不要
- **受け入れ要件**:
  - **Red**: `test_remove_group_hands_off_group_and_defers_dealloc` — removed=True 時 `result.removed_group` が pop グループ／**weakref で「呼び出し元が参照を保持する限り core 内で同期解放されない」**／依存拒否時 `removed_group is None`。
  - **Green**: `RemovalResult` に `removed_group: SignalGroup | None`／`remove_group` で `group = self._groups.remove(key)` を捕捉して載せる。
  - **Verify**: CI（Layer A）。
- **②実質性チェック**: 自動アサート可（weakref 生存・フィールド値）。naive でない（同期解放の有無を weakref で実証）。
- **honest layering note**: core 単体では close の体感は変わらない。UI ブロック解消は Task B/C の perf E2E が証明する。

## Task B: `TeardownService` — graveyard + byte-budget QTimer drain
- **変更種別**: perf（GUI 機構・不可視）
- **触れるユーザージャーニー**: 閉じる（背景解放中の UI 応答）
- **E2E 受け入れ**（効果ごと）:
  - **~10 GB 背景解放中も UI が固まらない**: E2E=**perf E2E** / observable=**drain 中 heartbeat 最大 gap < 150 ms**＋同期 close < 200 ms / prod=**要（330k・実ロード経路・~10 GB 到達検証）** / 実経路=実 close→graveyard→drain を回し heartbeat 計測
  - **巨大配列でも 1 tick が短い（byte-budget が効く）**: Layer A で決定的（1 tick 解放バイト ≤ 予算＋最大1配列・巨大配列 1 本が単独 tick）
- **必要レイヤー**: A=必須 / B=不要（入力イベント無し）/ 入力経路 E2E(C)=不要（機構は不可視・可視効果は Task E）/ **perf E2E=必須（prod スケール実測）** / 描画=不要
- **入力経路の再現性**: N/A（機構）
- **受け入れ要件**:
  - **Red (Layer A)**: `test_teardown_drains_in_byte_budget_slices` — 小さい予算で大配列群を enqueue→1 tick 解放バイトが予算を大きく超えない／巨大配列 1 本が単独 tick／全解放で `on_finished`／空で timer stop／複数キー FIFO／**weakref で実解放を実証**。
  - **Red (perf E2E・honest-RED)**: 現行同期 remove_group=prod 330k 実 close で **~7 s 単発 heartbeat gap**。
  - **Green**: `TeardownService`（graveyard・`QTimer(0)`・byte-budget drain・`on_started`/`on_finished` 注入コールバック）。
  - **Verify (/verify)**: 起動=perf ハーネス（prod・実 `_load_file`＋ExpansionConfirmer 全展開・`len(signals)==330004` 検証）。観測=**同期 close < 200 ms・drain 中 heartbeat 最大 gap < 150 ms**（嘘プロキシ不可＝小データ/内部 API では無効）。
- **②実質性チェック**: 自動アサート可（Layer A=予算スライス境界・weakref 解放・FIFO／perf E2E=実測 max-gap vs 150 ms・同期 close vs 200 ms）。**naive 回避必須**: 小データ perf・内部 `request_load`・`set_active_file`/ExpansionConfirmer スキップは無効。
- **①証拠ゲート**: `- [ ] perf 実測（before ~7s 単発 / after 同期<200ms・drain max-gap<150ms）を PR 添付`
- **honest layering note**: perf E2E は **`len(session.signals())==330_004` を検証してから計測**（内部 API・小データは 6s を隠す＝950ms 誤測の再発防止）。

## Task C: `unload_file` 配線
- **変更種別**: VM/純ロジック（＋perf 効果）
- **触れるユーザージャーニー**: 閉じる（同期クローズの即時性）
- **E2E 受け入れ**: **close が即返る（~38 ms）** → perf E2E（Task B の同期 close 計測に相乗り・prod 要）
- **必要レイヤー**: A=必須（unload_file が `removed_group` を service へ渡す・配列に触れない・論理クローズ=prune/active_file/offsets は同期）/ B=不要 / C=不要 / perf E2E=Task B と共有 / 描画=不要
- **受け入れ要件**:
  - **Red (Layer A)**: `test_unload_file_defers_dealloc_to_service` — `service.enqueue` に `removed_group` を渡す（spy）・core を同期解放しない（weakref）・prune/active_file/offsets の既存後始末は同期発火。
  - **Green**: `if result.removed_group: self._teardown.enqueue(key, result.removed_group)`。
  - **Verify**: Task B の perf E2E に統合。
- **②実質性チェック**: 自動アサート可（enqueue spy・weakref・既存 notify）。

## Task D: File Browser releasing 状態（VM: `loaded ∪ releasing`）
- **変更種別**: ウィジェット構成・状態（VM）
- **触れるユーザージャーニー**: 閉じる（解放中の行が残る→消える）
- **E2E 受け入れ**: **解放中の行が残り完了で消える** → Layer A/B（VM 合成・releasing_keys lifecycle）
- **必要レイヤー**: A=必須（AppViewModel が `releasing_keys` 所有・`on_started`/`on_finished` で add/remove・`_notify`／FileBrowserVM が `loaded ∪ releasing` 合成）/ B=要（releasing 行の非操作性を実 Qt イベントで＝下記 Task E と一体）/ C=可視は Task E / perf=不要 / 描画=不要
- **受け入れ要件**:
  - **Red (Layer A)**: `test_releasing_file_stays_in_browser_until_finished` — `on_started(key)`→リストに releasing 行／`on_finished(key)`→消える／loaded と併存／複数同時。
  - **Green**: `AppViewModel.releasing_keys`＋通知／`FileBrowserVM` 合成。
  - **Verify**: CI。
- **②実質性チェック**: 自動アサート可（リスト内容・releasing フラグ）。

## Task E: File Browser view — スピナー描画（アニメ・淡色・非操作）
- **変更種別**: ウィジェット構成・状態（＋視覚）
- **触れるユーザージャーニー**: 閉じる（スピナー可視・UI 応答・完了で消える）
- **E2E 受け入れ**（効果ごと）:
  - **対象行にスピナーが回る（テキスト無し・淡色）**: E2E=**描画/入力経路 realgui** / observable=**スクショ目視（スピナー可視・淡色・テキスト無し）** / prod=**要**（prod close は解放が数秒続きスピナーが観測時間可視。小データは一瞬で消え可視化不能）/ 実経路=実 prod close→realgui スクショ
  - **解放中の行は非操作**: Layer B（releasing 行へ実 Qt クリック→選択/close されない）＋realgui 実クリック無効
  - **完了でスピナー行が消え UI は固まらない**: realgui（スクショ＋応答）＋perf E2E の heartbeat（定量）
- **必要レイヤー**: A=必須（releasing 行に spinner 表示状態・`ItemIsEnabled/Selectable` off・淡色）/ B=必須（releasing 行への実クリックが no-op）/ **入力経路 E2E(C)=必須（スピナー可視・淡色・完了で消滅・UI 応答をスクショ/実観測）** / perf=Task B と共有 / 描画 E2E=realgui スクショに包含
- **入力経路の再現性**: スピナー可視＝描画 realgui（スクショ）。非操作＝Layer B（`sendEvent` クリック）再現可＋realgui 実クリック。
- **受け入れ要件**:
  - **Red (Layer A/B)**: releasing 行が非選択・spinner 表示状態・実 Qt クリック no-op。
  - **Green**: releasing 行に `QMovie`/QTimer スピナー・`ItemIsEnabled/Selectable` off・淡色。
  - **Verify (/verify・realgui)**: 起動=`uv run valisync`（prod_demo.mf4）。手順=prod ロード→close。観測=**対象行にスピナー（テキスト無し・淡色）・UI 固まらない・数秒後スピナー行消滅**（スクショ添付）。
- **②実質性チェック**: 自動アサート可（非操作フラグ・spinner 表示状態）＋視覚（スピナー回転・淡色・消滅＝スクショ／UI 応答＝perf E2E heartbeat）。naive 回避: 小データはスピナーが一瞬で消え可視化不能→**prod 必須**。
- **①証拠ゲート**: `- [ ] uv run pytest --realgui tests/realgui/test_close_release_spinner.py + スクショ添付`
- **realgui 掴み点監査**: N/A（GraphPanel ゾーン幾何 frame/grip/軸幅は不変・File Browser 行装飾のみ）
- **honest layering note**: スピナーが「回る」ことは Layer A では証明不能（描画 realgui スクショが唯一）。UI 応答は perf E2E の heartbeat が定量ゲート。

---

## ①証拠ゲート集約（merge 前 `/gui-verify`）
- [ ] perf E2E（prod 330k・実ロード経路・`len==330004` 検証）: before ~7 s 単発 gap → after **同期 close < 200 ms・drain max heartbeat gap < 150 ms** の実測を PR 添付。
- [ ] `uv run pytest --realgui tests/realgui/test_close_release_spinner.py`: スピナー可視・淡色・非操作・完了で消滅・UI 応答のスクショ添付。
