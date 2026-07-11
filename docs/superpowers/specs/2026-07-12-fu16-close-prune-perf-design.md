# FU-16: prod クローズの prune perf 根治 — 設計 spec

- **日付**: 2026-07-12
- **課題**: FU-16（`docs/audit-findings-catalog.md` SS-FOLLOWUP）
- **重要度**: 🟠 perf（真因確定・実測は着手時に prod で締める）
- **相乗り**: FU-03（大容量でドック開閉が体感フリーズ）の再現試行を同 prod セットアップで実施
- **スコープ方針**: A案（prune 根治のみ・副次の増分 invalidate は実測後判断）

## 1. 背景・症状

prod（330k ch・1.36GB）でファイルをクローズすると、**確認ポップアップ表示まで**と**確認後のクローズ処理**の両方が長時間フリーズする、というユーザー実機フィードバック。

## 2. 真因（確定・2026-07-12 実コード検証済み）

### 2.1 確認前（基本 light・例外1つ）

`_close_selected`（`file_browser_view.py`）は `files[row]` をキャッシュし QMessageBox を即時表示するため基本 light。**例外は右クリックで非選択行を閉じる時のみ**: `setCurrentIndex` が `selectionChanged` → `set_active_file`（`app_viewmodel.py:118-141`・同一キー dedup なし）→ `ChannelBrowserVM` prep 再構築 O(該当 ch) を誘発。本サブスペックの主対象ではないが、実測で確認する。

### 2.2 確認後（真のボトルネック）

- `unloaded` イベントで `GraphAreaVM._on_app_change`（`graph_area_vm.py:57-67`）が `_for_each_panel`（全タブ全パネル）に `prune_missing_signals()` を配送。
- `GraphPanelVM.prune_missing_signals`（`graph_panel_vm.py:482-497`）は毎回 `present = {s.name for s in self._session.signals()}` を実行。
- `session.signals()` → `SignalGroupManager.signals()` → `_ensure_namespaced()`。`remove()` の `_invalidate_namespaced()` 直後の**初回**で残存全信号の namespaced ラッパーを**全再構築**、以降のパネルも `list(...)` 防御コピー＋set 内包表記で **O(残存信号数)** スキャン。
- prod 330k では **(i) 一回の全再構築（残存データ比例）× (ii) パネル数の乗数**の両方が効き、クローズ後が長時間フリーズ。

**直交関係**: FU-11 の `group_signals` キャッシュは prune 非経由なので本件とは独立。

## 3. 設計方針（A案）

### 3.1 根因フィックス — prune を生存グループキー集合フィルタへ

`prune_missing_signals` を、`session.signals()` の全走査から **生存 group_key 集合とのメンバシップ判定**へ変更する。`signal_key` は `{group_key}{KEY_SEPARATOR}{name}`（`KEY_SEPARATOR = "::"`）なので、entry の signal_key から group_key を切り出し、生存 group_key 集合に含まれるかで判定できる。

```python
def prune_missing_signals(self) -> None:
    live = set(self._session.group_keys())          # O(#files)
    kept = [
        e for e in self._plotted
        if e.signal_key.split(KEY_SEPARATOR, 1)[0] in live
    ]
    if len(kept) == len(self._plotted):
        return                                       # 既存 no-op 契約を保存
    self._plotted = kept
    self._compact_axes()
    self._invalidate_cache()
    self._notify("signals")
```

- `session.signals()` を**呼ばない** → namespaced 全再構築を発火させない。
- コストは **O(#files) の集合構築 ＋ O(プロット中 entry 数) の split+membership**。パネル数 N 倍でも #files 比例（330k のチャンネル数に非依存）。
- prune が正しいのは、`signal_key` の group_key 部分が生存グループのキーであれば、そのグループの信号がロード済み＝存続を意味するため。個別信号名の突合は不要（グループ単位でロード/アンロードされる）。

### 3.2 API 変更 — `Session.group_keys()`

現状 Session は `signals`/`signal_map`/`source_name`/`group_signals`/`source_info` を公開するが、**グループキー一覧は未公開**。薄い委譲を1つ追加:

```python
def group_keys(self) -> list[str]:
    """Keys of all loaded groups (insertion order)."""
    return self._groups.keys
```

`SignalGroupManager.keys`（`signal_group_manager.py:57-60`）への委譲のみ。

### 3.3 抽出責務は VM 側 split（既存パターン踏襲）

signal_key → group_key の切り出しは **VM 側 `split(KEY_SEPARATOR, 1)[0]`** とする。SGM に新ヘルパは追加しない。理由: このパターンは既にコードベースに確立している。
- `graph_panel_vm.py:535`（`group_key = signal_key.split("::", 1)[0]`）
- `app_viewmodel.py:71,95`・`session.py:316`

`graph_panel_vm.py` は `KEY_SEPARATOR` を import 済み（`:20`）なので、新規コードは規約明示のため `KEY_SEPARATOR` を用いる（周辺の既存 `"::"` リテラルとの表記差は許容範囲・意味は同一）。

### 3.4 スコープ外（実測後に判断）

catalog は副次「`_invalidate_namespaced` を**削除キーのみ drop**（増分更新）」も挙げるが、本増分には**含めない**。prune を keys ベースにすれば prune 経路は `signals()` を呼ばなくなり、**全再構築の主要な発火源が消える**。`remove()` 後に残る全再構築は render 等の他経路での**1回のみ**（残存データ比例）。これが prod 実測で体感問題として残る場合に限り、別増分で SGM の増分 invalidate（`_namespaced_list`/`_map` から削除キー分のみ除外・`_namespaced_by_key` は該当キー pop）を設計する。YAGNI 準拠。

## 4. テスト戦略（`/gui-test-plan` で②を正式設計）

### 4.1 Layer A/B（CI・決定的）

- **構造アサート（本件の核）**: `prune_missing_signals` が `session.signals()` / `SignalGroupManager.signals()` を**呼ばない**（スパイ／呼び出しカウント）。N パネル × `unloaded` 配送で `signals()` 呼出 0（catalog「N×P 呼出 → fix後0」の恒久ガード）。サボタージュ RED（旧実装に戻すと呼出が復活）で honest 性を担保。
- **正当性契約の保存**: 生存 group_key の entry を残す／削除された group_key の entry を落とす／全存続時は no-op（`len` 不変で early return＝既存契約）／`_compact_axes`・`_invalidate_cache`・`_notify` の副作用が従来同値。
- **API**: `Session.group_keys()` が `SignalGroupManager.keys` と一致。

### 4.2 honest-RED ＋ prod 実測（着手時に締める）

- prod 330k をロード → 複数タブ/パネルに信号をプロット → ファイルを close。
- **修正前**（honest-RED）と**修正後**でクローズ処理時間を実測し、体感フリーズ解消を実証。具体の合格閾値は `/gui-test-plan` の②で確定。

### 4.3 FU-03 相乗り

同 prod 実測セットアップで**ドック開閉のフリーズ**を試行。**再現すれば🔴昇格**して別途対応、**再現しなければクローズ判断**（catalog: 現行コードで ~44ms・RN-04 のベクトル化で緩和済みの公算）。結果を catalog に転記。

## 5. 受け入れ基準

1. `prune_missing_signals` が session 全走査／namespaced 再構築を発火しない（構造テスト・サボタージュ RED 付き）。
2. prune の正当性契約（残す/落とす/no-op/副作用）が保存される。
3. `Session.group_keys()` が SGM.keys と一致。
4. prod 実測でクローズ処理の体感フリーズが解消（閾値は②で設定）。
5. FU-03 の再現試行結果を catalog に記録。
6. 既存テスト無回帰・品質ゲート（pytest / ruff check / ruff format / mypy）通過。

## 6. 影響ファイル（見込み）

- `src/valisync/core/session.py` — `group_keys()` 追加
- `src/valisync/gui/viewmodels/graph_panel_vm.py` — `prune_missing_signals` 差し替え
- `tests/` — 構造アサート＋正当性契約テスト（Layer A/B）、prune 呼出スパイ
- `docs/audit-findings-catalog.md` — FU-16 解消・FU-03 試行結果の転記
