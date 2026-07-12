# FU-16: remove_group の遅延分割解放（close の UI ブロック根治）— 設計 spec

- **日付**: 2026-07-12
- **課題**: FU-16（`docs/audit-findings-catalog.md` SS-FOLLOWUP）本体の根治
- **重要度**: 🟠 perf（真因 e2e 再現済み・PoC でアプローチ検証済み）
- **前提**: prune 改善（別 follow-up・PR #88 merged）は 6秒フリーズと無関係。本 spec が FU-16 の 6秒フリーズそのものを根治する。

## 1. 背景・症状

prod（展開後 330,004 ch・~10 GB のライブ配列）でファイルをクローズすると、確認ダイアログの「Yes」押下後、**ファイルが実際に閉じられるまで約6秒 UI がフリーズ**する（ユーザー実機フィードバック）。

## 2. 真因（e2e 再現で確定・2026-07-12）

実アプリ経路（`_load_file` オフスレッドロード＋`ExpansionConfirmer` 全展開 → 330,004 ch）で実 close を再現した結果、フリーズの **99.6%** は `Session.remove_group`（`src/valisync/core/session.py:260-276`）の次の1行:

```python
self._groups.remove(key)  # SGM.remove が返す SignalGroup を捨てる
```

`SignalGroupManager.remove` は pop した `SignalGroup` を返すが、`remove_group` はそれを**捨てる**。その戻り値が参照する **~10 GB の numpy 配列（各 Signal の timestamps/values）＋~330k の Signal オブジェクト**が、文末で**同期 refcount dealloc**され、UI スレッドを ~7 秒ブロックする。

- GC サイクルは **0 回**（純 refcount・`gc.freeze/disable` は無効）。
- スケール駆動因は信号数でなく**ライブデータ量**（264k/~1.4 GB=806 ms vs 330k/~10 GB=7314 ms）。
- namespaced ラッパーは配列を**ゼロコピー共有**（`_sorted_view_delegate`）なので解放は安価。~10 GB は**元グループの Signal 配列**にある。

（再現詳細: repro report・catalog FU-16 行・memory [[gui_perf_e2e_repro_must_drive_real_load_path]]）

## 3. PoC 検証結果（アプローチ確定・2026-07-12）

「chunked deferred teardown が本当に UI ブロックを解くか」を実装前に PoC で検証（`scratchpad/fu16_poc.py`・PoC report）:

- **同期クローズ 7322 ms → 38 ms**（~190×）＝クリック時フリーズ解消。
- GUI スレッドの `QTimer(interval 0)` graveyard 分割 drain で **~10.5 GB を背景解放**（working set 10986→466 MB・GC 0 回）。
- **naive offthread は無効**（monolithic tp_dealloc が GIL を保持＝GIL trap）。GUI スレッド QTimer で十分＝**worker thread 不要**。
- **件数分割（8000件/tick）は不十分**: 巨大配列が末尾 tick に集中し **576 ms スパイク**。→ **バイト予算分割**が必須（後述）。

## 4. 設計方針

### 4.1 アーキテクチャ（core / GUI 境界）

core は Qt 非依存の純ロジックを維持する。**core は「グループを捨てず手渡す」だけ**、保持（graveyard）とバイト予算分割解放・スピナー通知は GUI 層（Qt イベントループを持つ層）に置く。

```
[Yes] → core.remove_group(手渡し) → GUI TeardownService(graveyard, 即return)
        → QTimer(0) byte-budget drain → (完了)
                      │ releasing_started(key)          │ releasing_finished(key)
                      ▼                                 ▼
              File Browser: 行にスピナー          File Browser: 行を削除
```

### 4.2 core 変更 — `remove_group` が削除グループを返す

`RemovalResult` に `removed_group: SignalGroup | None` を追加し、削除成功時に pop したグループを載せる。呼び出し元（GUI）がそれを graveyard へ移すことで、**core は同期 dealloc しない**（グループへの唯一の強参照が graveyard に移る）。

```python
@dataclass(frozen=True)
class RemovalResult:
    removed: bool
    dependent_signals: tuple[str, ...] = ()
    removed_group: SignalGroup | None = None   # 追加: 削除に成功した時のみ非 None

def remove_group(self, key: str, force: bool = False) -> RemovalResult:
    ...
    if dependents and not force:
        return RemovalResult(removed=False, dependent_signals=dependents)
    group = self._groups.remove(key)           # 捨てず捕捉
    return RemovalResult(removed=True, dependent_signals=dependents, removed_group=group)
```

- `SignalGroupManager.remove` は既に group を返す（変更不要）。
- core は Qt を一切 import しない（純粋なまま）。
- `removed_group` を無視する既存の非 GUI 呼び出し元があっても、その場合は従来どおり戻り値スコープ終了で同期 dealloc される（挙動不変）。GUI だけが graveyard へ移して遅延解放する。

### 4.3 GUI — `TeardownService`（新規 `gui/workers/teardown_service.py`）

`QObject` 派生。graveyard（解放待ちの Signal 参照の平坦リスト）と `QTimer(interval 0)` を保持し、バイト予算で分割解放する。

- `enqueue(key: str, group: SignalGroup) -> None`: `group.signals` の各 Signal を graveyard へ push（`(key, signal)` 単位）。`releasing_started(key)` を emit。タイマー未稼働なら start。
- ドレイン（タイマー timeout ごと）: graveyard 末尾から、**積算バイト（`sig.timestamps.nbytes + sig.values.nbytes`）が予算（既定 `_BYTE_BUDGET = 64 MB`）に達するまで** pop して参照を落とす（del）。予算超過で return（次 tick へ）。
- あるキーの Signal が graveyard から全て消えたら「完了」を通知。graveyard が空になったらタイマー stop。
- **通知は注入コールバック**（`on_started(key)` / `on_finished(key)`）で外へ渡す。配線側（`AppViewModel`）が受けて `releasing_keys` を更新する。TeardownService は GUI スレッドの `QObject`（drain は `QTimer`＝同一スレッドなので、クロススレッド signal の生存問題 [[gui_qrunnable_signals_lifetime_retention]] は起きない）。

**バイト予算の根拠**: 件数でなくバイト量を上限にすることで、巨大配列 1 本でも 1 tick を短く保つ（PoC の 576 ms スパイク回避）。既定 64 MB はテストで heartbeat 最大 gap < ~100 ms を満たすよう調整するチューニング可能定数。

### 4.4 `AppViewModel.unload_file` の配線

```python
def unload_file(self, key: str) -> None:
    result = self._session.remove_group(key)
    if not result.removed:
        return
    # ...既存の loaded_keys/active_file/offsets 後始末（即時・軽量）...
    self._notify("unloaded")                      # prune 等は従来どおり即時
    if result.removed_group is not None:
        self._teardown.enqueue(key, result.removed_group)   # ~10GB を背景 drain へ
```

`unload_file` は即 return（~38 ms）。論理クローズ（prune・ChannelBrowser クリア・非アクティブ化）は従来どおり同期で完了する。

### 4.5 File Browser の「releasing」状態

- **`AppViewModel` が `releasing_keys` 集合を所有**（TeardownService の `on_started`/`on_finished` で add/remove し `_notify`）。`FileBrowserVM` は既存の app 購読（`_on_app_change`）でこれを読み、表示リストを **`loaded_keys ∪ releasing_keys`** に合成する。
- releasing の行は **スピナーのみ（テキスト無し）・淡色・非操作**（再選択/再クローズ不可）。完了で `releasing_keys` から除去 → 行が消える。
- スピナーは `QMovie` か QTimer 駆動の再描画（外部アセット無し）。

### 4.6 エッジケース

- **アプリ終了が drain 中**: drain を放棄してプロセス終了（OS が全メモリを即回収）。終了をブロックしない。
- **同一ファイルの再オープンが drain 中**: 別ロード＝別グループ/別キー（`csv_N+1` 等）なので独立。旧グループは graveyard で独立に drain・競合なし。
- **複数ファイルの連続クローズ**: graveyard は FIFO で全 Signal を混在保持し drain。各キーが個別に `releasing_started/finished` を受けるので、File Browser は行ごとに個別スピナー。

## 5. スコープ

- **含む**: `remove_group` のクローズ経路の遅延分割解放＋File Browser スピナー。
- **含まない**: FU-03（ドック開閉フリーズ・別タスク）／FU-18（`source_info` 330k tooltip freeze・未検証仮説・別タスク）／`gc.freeze()`（再現で GC=0＝無効）／worker thread（PoC で不要）。

## 6. テスト戦略（`/gui-test-plan` で②を正式設計）

### 6.1 Layer A/B（CI・決定的）
- **core**: `remove_group` が `removed_group` に pop したグループを載せる（removed=True 時）／依存拒否時は None。同期解放しない（呼び出し元が参照を保持すればグループは生存）。
- **TeardownService**: `enqueue` で `releasing_started` 発火／drain がバイト予算で分割（1 tick の解放バイトが予算を大きく超えない・巨大配列 1 本でも tick を跨ぐ）／全 Signal 解放で `releasing_finished`／空で timer stop／複数キー FIFO。参照が実際に落ちる（weakref で解放を検証）。
- **File Browser**: releasing_started で `loaded ∪ releasing` にその行が出る（スピナー・非操作）／releasing_finished で消える。
- **unload_file**: 即 return（配列に触れない）＋`removed_group` を TeardownService へ渡す。

### 6.2 perf E2E（prod 330k・本 spec の核）
- PoC ハーネス（`scratchpad/fu16_poc.py`）を製品テスト化: 実アプリ経路で prod 330k をロード → close。**同期クローズ時間が小（例 < 200 ms）** かつ **drain 中の heartbeat 最大 gap < 閾値（例 100–150 ms）** を実測（閾値は②で確定）。honest-RED は現行同期 remove_group（~7 s 単発 gap）。

### 6.3 realgui（Layer C）
- 実 prod close → **スピナーが対象行に出る・UI が固まらない・drain 完了で行が消える**をスクショ/実 OS 観測。

**ゾーン境界を動かす変更ではない**（File Browser の行装飾のみ）ため、掴み点の realgui 再監査は不要。

## 7. 受け入れ基準

1. `remove_group` が削除グループを `removed_group` で返し、core は同期解放しない（呼び出し元保持でグループ生存を実証）。
2. `TeardownService` がバイト予算で分割解放し、巨大配列 1 本でも 1 tick を跨ぐ（件数でなくバイト上限）。全解放で `releasing_finished`。
3. `unload_file` が即 return（配列に触れない）。論理クローズ（prune 等）は同期で完了。
4. File Browser が releasing 行をスピナーのみ・淡色・非操作で表示し、完了で削除。複数同時対応。
5. prod 330k で同期クローズが小＋drain 中 heartbeat 最大 gap < 閾値（②で設定・honest-RED 付き）。
6. アプリ終了/同一ファイル再オープンが drain 中でも破綻しない。
7. 既存テスト無回帰・品質ゲート（pytest / ruff check / ruff format / mypy）通過。

## 8. 影響ファイル（見込み）

- `src/valisync/core/session.py` — `RemovalResult.removed_group` 追加・`remove_group` で捕捉して返す
- `src/valisync/gui/workers/teardown_service.py` — 新規 `TeardownService`（graveyard＋byte-budget QTimer＋通知）
- `src/valisync/gui/viewmodels/app_viewmodel.py` — `unload_file` から TeardownService へ配線・releasing_keys 管理（または FileBrowserVM）
- `src/valisync/gui/viewmodels/file_browser_vm.py` — 表示リストを `loaded ∪ releasing` に・releasing 状態公開
- `src/valisync/gui/views/file_browser_view.py` — releasing 行のスピナー（アニメ）・淡色・非操作描画
- `src/valisync/gui/views/main_window.py`（等）— TeardownService の生成/配線
- `tests/` — Layer A/B（core・service・VM・view）＋perf E2E ハーネス（prod）
- `docs/audit-findings-catalog.md` — FU-16 ✅解消の転記
