# FU-11: ChannelBrowser フィルタ検索速度の改善（prod 330k ch）— 設計 spec

- **課題 ID**: FU-11（`docs/audit-findings-catalog.md`）
- **優先度**: 解決順①（最優先・実機フリーズ）
- **対象ブランチ**: `worktree-fu11-filter-perf`
- **日付**: 2026-07-11

## 1. 問題（ユーザー実機フィードバック）

> channelbrowser のフィルターの検索スピードを向上させたい。prod（330k チャンネル）読み込み時にフィルタをかけようとすると、**1 文字入力するたびに処理のためにフリーズ**するのをなんとかしたい。フィルタ適用までにディレイをいれる等も思いついたのですが、**可能な限りリアルタイム**で更新されるようにしたい。

ユーザーは「ディレイ（debounce）」も案として挙げたが、明示的に「可能な限りリアルタイム」を希望。したがって **debounce による症状緩和ではなく、1 打鍵あたりの計算量そのものを削る根本解決**を採る。

## 2. 真因（prod_demo.mf4 = 330,004 ch で実測）

`scripts`（scratchpad の `fu11_filter_profile.py`）で prod プロファイル（1.3GB / 330,004 ch）を全展開ロードし、1 打鍵の実効経路を分解計測した。

| 計測項目 | 実測 |
|---|---|
| `session.group_signals(key)` 1 回（cold） | **3,200 ms** |
| `session.group_signals(key)` 2 回目以降 | **3,300 ms**（毎回同じ＝キャッシュされていない） |
| `session.signals()`（FU-08 でキャッシュ済） | **6 ms** |
| 1 打鍵 `'Ra'` の実効コスト | **17,076 ms** → 1 row |
| cProfile: `group_signals` 呼び出し回数 / keystroke | **5 回** |
| cProfile: `Signal.__post_init__` 呼び出し | 1,650,020 回 / 18.45 s cumulative |

### 2.1 根本原因

`SignalGroupManager.group_signals(key)`（`signal_group_manager.py:125-130`）は、FU-08 でキャッシュ化された `_ensure_namespaced()` の経路を**バイパス**し、呼ばれるたびに `_namespaced(key, group)` を再実行する。`_namespaced` は当該グループの全信号（prod では 330k）に対し namespaced な `Signal` ラッパーを**都度新規生成**する（`Signal.__post_init__` の numpy 検証込みで 1 グループあたり 3.3 秒）。

`signals()`／`signal_map()` は `_ensure_namespaced()` 経由で全グループ分を 1 度だけ構築しキャッシュする（FU-08）が、**単一グループ取得の `group_signals(key)` にはそのキャッシュ層が無い**。

### 2.2 なぜ 1 打鍵で 5 回も呼ばれるか

1 打鍵（`search_box.textChanged` → `vm.set_filter` → `_notify("filter")`）で、以下の消費側が同期的に走る:

| 消費側 | 経路 | `group_signals` 回数 |
|---|---|---|
| `SignalTableModel._on_vm_change`（`qt_signal_models.py:110`） | `list(self._vm.signals)` | 1 |
| `ChannelBrowserView._refresh_state` → `header_text()`（`channel_browser_vm.py:114`） | `_group_total()`（len 用）＋ `len(self.signals)` | 2 |
| `ChannelBrowserView._refresh_state` → `empty_state()`（`channel_browser_vm.py:123`） | `_group_total()`＋ `self.signals` | 2 |
| **合計** | | **5** |

5 回 × 3.3 秒 ≈ 17 秒。これが 1 打鍵ごとのフリーズの実体。debounce では「入力停止後に 17 秒」に変わるだけで根本は残る。

### 2.3 波及（tooltip も同根）

`tooltip_for` → `_signal_by_key`（`channel_browser_vm.py:162`）も `group_signals(active_key)` を都度実行するため、prod では**ホバー 1 回ごとに 3.3 秒フリーズ**する。本設計の Part A（後述）で `group_signals` がキャッシュされると、tooltip の 3.3 秒フリーズも同時に解消される（linear scan は O(n) だが数 ms で許容 — 追加最適化は本 spec の対象外）。

## 3. 設計（A + B + C の三層）

3 層すべてを入れて初めて「可能な限りリアルタイム」に到達する。単層では下表のとおり不足する。

| 層 | 何を削るか | 単独効果（見積） |
|---|---|---|
| A: core キャッシュ | `group_signals` の 3.3 秒再構築 → 数 ms | 17 秒 → ~1 秒 |
| B: VM メモ | 1 打鍵内の 3 重フィルタ走査 → 1 回 | ~1 秒 → ~300 ms |
| C: VM precompute | 330k の再 `.lower()`／SignalItem 全生成を回避 | ~300 ms → 数十 ms |

**目標**: 1 打鍵 17,000 ms → 数十 ms（体感リアルタイム）。

### 3.1 Part A — `SignalGroupManager.group_signals` のグループ別キャッシュ（core）

`_namespaced_list`／`_namespaced_map`（全グループ）と同じ無効化ライフサイクルに乗せ、**グループ別 namespaced リストのキャッシュ**を追加する。

```python
# __init__
self._namespaced_by_key: dict[str, list[Signal]] = {}

# _invalidate_namespaced に 1 行追加
def _invalidate_namespaced(self) -> None:
    self._namespaced_list = None
    self._namespaced_map = None
    self._namespaced_by_key = {}          # ← 追加

# group_signals をキャッシュ経由に
def group_signals(self, key: str) -> list[Signal]:
    group = self._groups[key]             # 未知 key は従来どおり KeyError
    cached = self._namespaced_by_key.get(key)
    if cached is None:
        cached = self._namespaced(key, group)
        self._namespaced_by_key[key] = cached
    return list(cached)                   # signals() と同じく防御コピー
```

- **無効化**: `add()`／`remove()` が既に呼ぶ `_invalidate_namespaced()` に相乗り。キーは counter が減らないため再利用されず、生存キーは不変な信号集合に対応する（キャッシュが stale 化しない前提が構造的に保証される）。
- **返り値**: `list(cached)`（`Signal` オブジェクトは共有、リストのみ防御コピー）。`signals()` の `list(self._namespaced_list)` と同じ契約。O(n) ポインタコピーは 330k でも数 ms。
- **FU-08 との整合**: `_namespaced` が設定する `_sorted_view_delegate`（長寿命な元 Signal への委譲）はキャッシュ 1 回構築で確定し、無効化まで不変。FU-08 の「無効化のたびにラッパー作り直し」モデルをグループ別経路へ延伸したもの。
- **既存 API 不変**: シグネチャ・例外・返り値の意味は変わらない（速くなるだけ）。

### 3.2 Part C — VM の precompute タプル列（`ChannelBrowserVM`）

active_key ごとに 1 度だけ、フィルタ非依存の前処理済みタプル列を構築する。

- タプル: `(orig_name: str, lower_name: str, unit: str, key: str)`
  - `orig_name` = `sig.name` の `::` プレフィックス除去後
  - `lower_name` = `orig_name.lower()`（**1 度だけ小文字化**）
  - `unit` = `sig.metadata.get("unit", "")`
  - `key` = `sig.name`（namespaced フルキー）
- 構築は `group_signals(active_key)`（Part A で高速化済）を 1 回呼んで全 330k を走査。**active_key ごとに 1 回だけ**（生存キーは不変信号集合なので stale 化しない）。
- キャッシュは単一スロット（`_prep_key: str | None` ＋ `_prep: list[tuple[...]]`）。active_key が変わったら作り直す（無制限成長を避ける）。

キーストローク時のフィルタは precompute 済 `lower_name` への部分一致のみ。SignalItem は**マッチした行だけ**生成する:

```python
def _filtered(self) -> list[SignalItem]:
    self._ensure_prep()
    fl = self._filter_text.lower()
    if not fl:
        return [SignalItem(name=n, unit=u, key=k) for (n, _lo, u, k) in self._prep]
    return [SignalItem(name=n, unit=u, key=k)
            for (n, lo, u, k) in self._prep if fl in lo]
```

### 3.3 Part B — VM の結果メモ（`ChannelBrowserVM`）

1 打鍵内の 3 アクセス（model reset / header_text / empty_state）が同一フィルタ結果を共有するよう、`signals` の返り値を `(active_key, filter_text)` でメモ化する。単一スロット。

```python
@property
def signals(self) -> list[SignalItem]:
    active_key = self._app_vm.active_file_key
    if not active_key:
        return []
    sig_key = (active_key, self._filter_text)
    if self._memo_key != sig_key:
        try:
            self._memo_result = self._filtered()
        except KeyError:
            self._memo_result = []
        self._memo_key = sig_key
    return self._memo_result
```

加えて `_group_total()`（`header_text`／`empty_state` が各 1 回、計 2 回呼ぶ）はフィルタ非依存（総数＋ファイル名）なので active_key で単一スロットメモ化する。

これにより 1 打鍵の `group_signals` 実効呼び出しは **prep 構築時の 1 回のみ**（同一 active_key で 2 打鍵目以降は 0 回）。

**無効化規則**（stale 防止の要）:
- `_on_app_change("active_file")`: active file が変わった → `_prep_key`／`_memo_key`／`_group_total` メモを全クリア。
- `set_filter(text)`: filter が変わった → `_memo_key` は自然に不一致になり再計算（prep は同一 active_key なので保持）。
- **遅延ビルド厳守**: prep も memo も `set_active_file` では作らず、最初の `signals`／`empty_state`／`header_text` アクセス時に構築する。かつ `session.group_signals` は毎回**動的参照**する（bound reference を保持しない）。→ 既存テストの「`session.group_signals = lambda...` で patch してから `set_active_file` → アクセス」パターン（`test_channel_browser_vm.py` の `_cb_vm_with_signal` 他）が patched lambda を読むことを保証する。

## 4. データフロー（before / after）

**Before（1 打鍵）**: `set_filter` → 5 × `group_signals`（各 3.3 s、都度 330k ラッパー再生成）＋ 各アクセスで 330k を再 `.lower()`＋全 SignalItem 生成 = ~17 s。

**After（1 打鍵、同一 active_key で 2 打鍵目以降）**:
- `group_signals` 実効 0 回（prep は前打鍵で構築済・core も key キャッシュ済）
- `signals` は `(active_key, filter)` メモミス → `_filtered()` が precompute 済 `lower_name` を 330k 部分一致（C 実装の Python ループだが文字列比較のみ）＋マッチ分だけ SignalItem 生成
- header/empty は同一メモ＋`_group_total` メモを共有
- 実測見積: 数十 ms

## 5. エラーハンドリング

- Part A: 未知 key は `self._groups[key]` が従来どおり `KeyError`（キャッシュ導入で挙動不変）。
- Part B/C: `_filtered()` 内の `group_signals` が `KeyError` を投げたら `signals` は `[]` を返す（現行 `signals` の `except KeyError: return []` を踏襲）。`_group_total` も現行どおり `KeyError` で `None`。

## 6. テスト戦略（Layer 判定）

本変更は **GUI 入力経路の新設ではなく、既存フィルタ経路の高速化（VM ロジック＋core キャッシュ）**。新しい入力イベントハンドラ・ウィジェット幾何・D&D は無い。したがって:

- **Layer A（必須・headless）**: 挙動保存＋パフォーマンス代理（call-count / rebuild-count）アサート。
- **Layer B**: 不要（新しい実イベント経路が無い）。
- **Layer C（realgui）**: **不要**。既存の realgui（ChannelBrowser 系）に無回帰であればよく、本 spec は入力経路の挙動を変えない。速度は wall-clock でなく **rebuild 回数の構造アサート**で証明する（ハードウェア非依存・既存 `test_active_file_switch_fetches_only_active_group_no_full_scan` の spy パターンが雛形）。

### 6.1 受け入れ要件（Red/Green）

**Part A（core）**:
- `group_signals(key)` を 2 回呼んでも `_namespaced` の実構築は 1 回（`_namespaced` を spy して呼び出し回数 == 1、または 2 回の返り値内の `Signal` が同一オブジェクト）。
- `add()`／`remove()` 後は `group_signals(key)` が再構築される（無効化の検証）。
- 既存 `test_session.py::test_group_signals_returns_namespaced_signals_for_one_group` が無回帰（名前・namespacing 不変）。

**Part B/C（VM）**:
- 1 打鍵相当（`set_filter` → `list(vm.signals)` → `header_text()` → `empty_state()`）で `group_signals` 実効呼び出しが **≤ 1 回**（spy カウント）。同一 active_key の 2 打鍵目は **0 回**。
- フィルタ挙動が保存される: `test_filter_narrows_flat_list`／`test_no_match_state_and_query`／`test_header_counts_and_has_rows`／`test_no_channels_state`／`test_signal_item_contains_unit`／tooltip 系が全て無回帰。
- **stale 防止の明示テスト**: active_file を A→B に切替後、`vm.signals` が B の信号を返す（prep/memo が A のまま残らない）。
- **遅延ビルド保証テスト**: `session.group_signals` を patch → `set_active_file` → `vm.signals` が patched データを返す（`_cb_vm_with_signal` パターンの無回帰で担保）。

### 6.2 パフォーマンス回帰の番人（任意・非 CI）

prod 実測の再現手段として scratchpad の `fu11_filter_profile.py` を temp に残す（CI 非依存・手動）。CI で回すのは 6.1 の構造アサートのみ。

## 7. 非目標（YAGNI）

- **debounce / 遅延適用**: ユーザーが「可能な限りリアルタイム」を希望したため採らない。
- **tooltip の linear scan 最適化**: Part A で 3.3 s フリーズは解消。数 ms の O(n) scan はスコープ外。
- **仮想化リスト（QAbstractItemModel の遅延 fetch）**: 現行 reset モデルのままで数十 ms 目標に到達するため不要。
- **フィルタの正規表現／複数語対応**: 現行の単純部分一致を維持（挙動不変）。
- **core `signals()`／`signal_map()` の変更**: 既にキャッシュ済。触らない。

## 8. 影響ファイル

- `src/valisync/core/loaders/signal_group_manager.py`（Part A）
- `src/valisync/gui/viewmodels/channel_browser_vm.py`（Part B/C）
- テスト: `tests/test_session.py`（or 新規 core テスト）・`tests/gui/test_channel_browser_vm.py`

既存の公開 API（`group_signals`／`signals`／`header_text`／`empty_state`／`tooltip_for`）のシグネチャ・返り値の意味は不変。
