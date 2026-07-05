# 設計 spec: LD-14 — ndim≥3 多段フラット展開＋per-channel 列数ガード

MDF4 ローダーの要素展開（LD-12）を **任意 ndim の多段フラット展開**（`Name[i][j]…`）へ一般化し、同時に **チャンネル単位の列数上限（1024）ガード**を導入する。上限超のチャンネルは、展開実行前にユーザーへポップアップで提示し、**チャンネルごとに展開/スキップを選択**できるようにする。

- **作成**: 2026-07-05
- **ステータス**: 設計（brainstorming 承認済み・writing-plans へ）
- **関連**: [core-loaders-hardening 第3弾 spec](2026-07-05-core-loaders-hardening-r3-design.md)（LD-12 の要素展開を土台に拡張）／[audit-findings-catalog](../../audit-findings-catalog.md) SS-LOADERS
- **前提コード**: `_explode_samples`（現行は 2D＋構造化 1 段のみ・3D 超は skip 警告）、`MDF4Loader.load`→`_load_group`→`mdf.select` のグループ一括読み、`Session.load(cancel=...)` の協調コールバック委譲、`LoadWorker(QRunnable)` on `QThreadPool`（ロードは GUI スレッド外）

---

## 1. スコープと確定判断（brainstorming・ユーザー決定）

| # | 決定 |
|---|---|
| 展開スキーム | 任意 ndim を再帰フラット展開 `Name[i][j]…`。構造化 dtype はフィールド展開 `Name.field` を各リーフで組合せ（案1＝多段フラット、ユーザー決定） |
| 上限の粒度 | **per-channel**。各チャンネルを完全展開したときの**リーフ列数**が **> 1024** のものを「超過チャンネル」とする（ユーザー決定「個別に 1024 を超える要素を持つ変数のみ…」） |
| 確認単位 | 1 ロードにつき**ポップアップ 1 回**（全超過チャンネルを集約提示） |
| 選択の粒度 | 超過チャンネルを一覧提示し、**チャンネルごとにチェックで展開/スキップを選択**（ユーザー決定「超過チャンネルごとに判断」） |
| 既定チェック状態 | **未チェック（＝スキップ）** を初期値。ガードの主旨が慎重側のため（ユーザー了承） |
| コールバック不在時（ヘッドレス/プログラム的ロード） | 超過チャンネルは**スキップ＋警告診断**。1024 以下は常に展開（新機能・安全側・従来 3D スキップと後方互換） |
| 1024 以下のチャンネル | ポップアップなしで自動展開（LD-12 の UX を維持） |

**LD-12 との関係（改訂）**: 第3弾 spec §1 の「LD-12: 列数上限は設けない」を **本増分で改訂**する。per-channel 1024 ガードを追加し、上限超は確認必須にする。1024 以下の 2D/構造化展開は従来どおり自動（無確認）で、LD-12 の通常挙動は不変。

## 2. 現状分析

`src/valisync/core/loaders/mdf4_loader.py`:

1. `_explode_samples(base_name, samples, diagnostics)` は **2D（列展開 `Name[i]`）** と **構造化 dtype（`Name.field`・サブ配列フィールドは 1 段だけ `Name.field[i]`）** のみ対応。**3D 以上は skip＋warning**（`samples.ndim` を含む文言）。多段のネストは扱えない。
2. `_load_group` は `mdf.select(entries)` でグループ全チャンネルを一括読み → チャンネルごとに `exploded = samples.ndim != 1 or bool(samples.dtype.names)` を判定し、`_explode_samples` または単一ペアを astype/Signal 構築ループへ流す。展開は**インライン**（読みながら即展開）。
3. 列数の事前把握や確認機構はない（LD-12 は上限なし前提）。

**課題**: (a) 本番の物標行列が 3D 以上のとき現状は丸ごと消える。(b) 深い展開は列数が組合せ的に膨張し得る（例 3D 32×32 = 1024 列/1 チャンネル）→ UI/モデルの実害。ユーザーが**どの重いチャンネルを展開するか制御**したい。

## 3. 設計

### 3.1 多段フラット展開（`_explode_samples` の再帰化）

`_explode_samples` を、任意 ndim・構造化を再帰で畳む純関数 `_flatten` に委譲する形へ書き換える。**サンプル軸は常に axis 0**。

```python
def _flatten(name: str, arr: np.ndarray) -> list[tuple[str, np.ndarray]]:
    """samples (axis 0 = サンプル) を 1D 列へ再帰フラット展開。"""
    if arr.dtype.names:  # 構造化 dtype: フィールドごとに Name.field を再帰
        out: list[tuple[str, np.ndarray]] = []
        for field in arr.dtype.names:
            out.extend(_flatten(f"{name}.{field}", arr[field]))
        return out
    if arr.ndim <= 1:  # リーフ: 連続化して 1D 列を確定
        return [(name, np.ascontiguousarray(arr))]
    # ndim >= 2: 先頭の非サンプル軸を Name[i] で 1 段剥がして再帰
    return [
        pair
        for i in range(arr.shape[1])
        for pair in _flatten(f"{name}[{i}]", arr[:, i])
    ]
```

- `_explode_samples(base, samples, diagnostics)` は `_flatten(base, samples)` を呼び、非空なら **info 診断 1 件**（`Signal 'base': {shape} を N 本に展開`。`shape` は `samples.shape[1:]` を `x` 連結、構造化混在時は列数のみ）を emit して返す。
- 現行の「2D 専用分岐・構造化サブ配列 1 段分岐・3D skip 分岐」は**すべて再帰に一本化**され消える。3D 超も skip ではなく展開されるようになる（挙動変更）。
- `np.ascontiguousarray` は**リーフでのみ**適用（中間スライスでコピーを作らない）。
- 展開後の各列は元チャンネルの**共有マスタを参照**（LD-10 のゼロコピー経路を維持・追加メモリは値のみ）。
- 展開名は**曖昧化済みベース名から派生**（重複名 `name[idx]` 方式との相互作用は現行どおり）。

### 3.2 per-channel 列数の事前算出（純関数）

完全展開後のリーフ列数を、**実サンプルを全量読まずに**求める。`_flatten` と同じ規則の純関数で、1 レコード分の samples（形状だけが本物）から計算する。

```python
def _leaf_column_count(arr: np.ndarray) -> int:
    """arr を _flatten したときのリーフ列数。arr は 1 レコード以上の samples。"""
    if arr.dtype.names:
        return sum(_leaf_column_count(arr[f]) for f in arr.dtype.names)
    if arr.ndim <= 1:
        return 1
    return int(np.prod(arr.shape[1:]))  # 非サンプル軸の積（構造化なしの一般 ndim）
```

> **不変条件（テストで固定）**: 任意の samples `s` について `len(_flatten("x", s)) == _leaf_column_count(s)`。この一致が崩れると誤判定になるため、直接ユニットテストで両者の整合を assert する。

### 3.3 展開前スキャン（ワンショット確認のための必須パス）

「全超過チャンネルを集約して 1 回だけ確認」するには、**select による本読みの前に**全チャンネルの列数を知る必要がある。グループを読みながらインライン確認すると、超過チャンネルを含むグループごとにポップアップが多発するため不可。

**採用案: 1 レコードプローブによる形状スキャン**（`load()` 冒頭・select 本読みの前）。呼び出し回数を抑えるため、**グループ単位で 1 レコードだけ select** する:

```
oversized: list[_OversizedChannel] = []
for gi in mdf.virtual_groups:
    entries = _group_entries(mdf, gi)
    probes = mdf.select(entries, record_count=1, raw=True,
                        ignore_value2text_conversions=True)   # グループ全ch × 1 レコード
    for (name, phys_gi, ci), probe in zip(entries, probes, strict=True):
        cols = _leaf_column_count(probe.samples)
        if cols > EXPANSION_COLUMN_LIMIT:                      # 1024
            oversized.append(_OversizedChannel(gi=phys_gi, ci=ci, name=name, column_count=cols))
```

- **なぜ dtype_fmt ではなく 1 レコードプローブか**: `Channel.dtype_fmt` は CA ブロック（channel array）由来の 2D を取りこぼす（デモの uint8 byte-array がまさにこれ — 既知の罠 [[mdf_authoring_2d_and_value2text_traps]]）。1 レコードプローブは**本読みと同じ経路で実サンプル形状を得る**ため、`shape[1:]` が本読みと必ず一致し、`_leaf_column_count` が正確になる。
- **なぜグループ単位 select か**: チャンネル単位 `get` を全ch分（HILS 171 回）呼ぶとシークが積み上がる。グループ単位 `select(record_count=1)` なら呼び出しは仮想グループ数（〜10 回）で済み、各回 1 レコードのみ。`raw=True` で変換コストも省く（形状は変換に依存しない）。
- **実装時確認事項**（第3弾と同じ流儀で asammdf 実ソース確認・report 記録）: `mdf.select(entries, record_count=1, raw=True)` が (i) 各チャンネルを 1 レコードで返し、(ii) `samples.shape[1:]` が全量読みと一致することを確認。`select` が `record_count` 非対応なら per-channel `mdf.get(..., record_count=1)` へフォールバック。形状不一致の型があれば該当型のみ本読み形状で再判定。
- `EXPANSION_COLUMN_LIMIT = 1024` はモジュール定数。

### 3.4 確認コールバックと GUI スレッド外→モーダル連携

`Session.load` / `MDF4Loader.load` に `cancel` と同じ委譲パターンで追加:

```python
@dataclass(frozen=True)
class OversizedChannel:
    name: str          # 表示名（曖昧化前のベース名）
    column_count: int  # 完全展開時のリーフ列数

@dataclass(frozen=True)
class ExpansionRequest:
    channels: tuple[OversizedChannel, ...]  # 超過チャンネル一覧（1024 超のみ・順序固定）

# confirm_expansion(request) -> set[int]
#   request.channels のインデックスのうち「展開する」ものの集合を返す。
#   返らなかったインデックス → スキップ（診断に列挙）。空集合 → 全スキップ。
ConfirmExpansion = Callable[[ExpansionRequest], set[int]]
```

**ローダー側フロー**（`load()` 内・スキャン後）:
1. `oversized` が空 → コールバック呼ばない（通常ロード）。
2. `oversized` があり `confirm_expansion` あり → `ExpansionRequest` を組み立て呼び出し。戻り `set[int]` を `expand_keys: set[(gi,ci)]` に写像（残りは `skip_keys`）。
3. `oversized` があり `confirm_expansion` なし（ヘッドレス）→ 全超過を `skip_keys` に。
4. **本読みパス**（`_load_group`）: `entries` から `skip_keys` のチャンネルを**除外**してから `select` する（＝スキップ対象は本読みすらしない → メモリ/時間も節約）。除外した各チャンネルは warning 診断（`Signal 'name': 展開列数 N が上限 1024 を超えるためスキップ`）を emit。
5. 承認された超過チャンネルは `_explode_samples`（再帰）で完全展開。1024 以下は従来どおり自動展開。

**GUI 側（ワーカースレッド→GUI スレッドのブロッキング委譲）**: `confirm_expansion` はワーカースレッドから呼ばれるが、モーダルは GUI スレッドで出す必要がある。専用 QObject＋シグナル＋`threading.Event` で marshal:

```python
class ExpansionConfirmer(QObject):
    _requested = pyqtSignal(object)  # (request, holder: dict, event) を GUI スレッドへ

    def confirm(self, request):          # ワーカースレッドから呼ばれる
        holder: dict = {}
        ev = threading.Event()
        self._requested.emit((request, holder, ev))   # QueuedConnection で GUI へ
        ev.wait()                                       # 回答までワーカーをブロック
        return holder["result"]

    @pyqtSlot(object)
    def _on_requested(self, payload):    # GUI スレッドで実行
        request, holder, ev = payload
        holder["result"] = ExpansionDialog.ask(request)   # モーダル（下記）
        ev.set()
```

- `_requested` は `Qt.QueuedConnection`（confirmer が GUI スレッド所属・emit がワーカースレッド → 自動で queued）。
- **デッドロックしない根拠**: ロード中の GUI スレッドはブロックされていない（オフスレッドロードの主旨）ため、queued スロットが処理でき、モーダルの入れ子イベントループが回る。
- ワーカーは `ev.wait()` で回答を待ち、`set[int]` を受け取ってローダーへ返す。

### 3.5 ポップアップ UI（`ExpansionDialog`）

`QMessageBox` ではなく **`QDialog`＋チェックボックス一覧**（per-channel 選択のため）:

- ヘッダ文: 「以下の信号は展開すると列数が上限（1024）を超えます。展開するものを選択してください。」
- 各行: `[ ] {name} — {column_count} 列`（初期状態 **未チェック＝スキップ**）。
- 補助ボタン: 「すべて展開／すべてスキップ」。選択中の**合計列数**を動的表示（当初の「総列数」要望はここに反映）。
- `OK` → チェック済みインデックスの `set[int]` を返す。`Cancel`／閉じる → 空集合（全スキップ）。
- 静的 `ExpansionDialog.ask(request) -> set[int]`（テスト容易性・GUI スレッドで呼ぶ前提）。

### 3.6 型と配置

- `OversizedChannel` / `ExpansionRequest` / `ConfirmExpansion` は `mdf4_loader.py`（または loaders 共有型モジュール）に定義し、`Session.load` の引数型に再エクスポート。
- `Session.load(..., confirm_expansion: ConfirmExpansion | None = None)` を追加し MDF4 ローダーへ委譲（CSV ローダーは対象外・引数無視）。
- `ExpansionDialog` / `ExpansionConfirmer` は `src/valisync/gui/`（views / workers）配下。`LoadController`/`LoadWorker` が confirmer を組み立て `Session.load` に渡す。

## 4. 検証

- **ユニット（Layer A・CI）**:
  - `_flatten`: 合成 ndarray で 3D（`A[i][j]`）・4D・構造化＋サブ配列混在・1D 素通しの名前と値を assert（**3D は asammdf public write で round-trip 不可のため合成 ndarray 直接テスト**）。
  - 不変条件 `len(_flatten(x, s)) == _leaf_column_count(s)` を複数形状で assert。
  - `_leaf_column_count`: 2D/3D/構造化/スカラーの列数。
- **統合（Layer A・CI）**: 上限ガードの end-to-end は **2D の広い uint8 byte-array チャンネル（列数 > 1024）** を書ける（3D と違い public write 可）。`tests/mdf4_helpers.py` に「幅 k>1024 の 2D uint8 チャンネル」ヘルパを追加し:
  - `confirm_expansion` スタブが `{該当 index}` を返す → その列が `Name[i]` で信号に出現、他の超過は不在＋warning 診断。
  - スタブが空集合 → 全超過スキップ＋warning。スキップ対象は select に渡らない（本読みされない）ことを確認（entries 除外の副作用テスト）。
  - コールバック不在（ヘッドレス既定）→ 全超過スキップ＋warning。
  - 1024 以下の 2D → ポップアップ経路を通らず自動展開（既存 LD-12 テストの回帰）。
- **GUI（Layer A/B・計画時 `/gui-test-plan` で②設計）**:
  - `ExpansionDialog.ask`: request からチェックボックス生成・トグル・OK/Cancel が正しい `set[int]` を返す（Layer A）。
  - `ExpansionConfirmer`: 別スレッドから `confirm()` を呼び、GUI スレッドのスロットが発火し `Event` 解放で戻り値が伝播する（Layer B・qtbot）。
  - 実 OS 入力依存の新規経路の要否（realgui ①ゲート）は writing-plans 時に `/gui-verify` 方針含め判定。
- **docs**: catalog に **LD-14 を追加（✅解消）** し LD-12 行に「per-channel 1024 ガードを LD-14 で追加（列数上限なしを改訂）」注記。roadmap・第3弾 spec §1 の LD-12 記述・CLAUDE.md を更新。

## 5. エッジケース・留意点

- **超過だが承認されたチャンネル**: 完全展開（列数どおり Signal 生成）。UI 負荷はユーザー承認済み。
- **プローブと本読みの形状差**: 原理上一致（同一レコード構造）。実装時に asammdf ソースで確認し、万一差が出る型があれば該当型のみ本読み形状で再判定するフォールバックを検討。
- **構造化 dtype の列数**: `_leaf_column_count` がフィールドを再帰合算するため、構造化×サブ配列の深いネストも 1024 判定に正しく反映。
- **重複名との相互作用**: スキャン・確認・本読みは同一の `_group_entries` 順に依拠。`skip_keys` は (gi,ci) キーで一意（名前衝突に非依存）。
- **キャンセルとの順序**: プローブスキャンの前後・グループ本読み前後で既存 `cancel` チェックを維持（スキャン自体もキャンセル可能にする）。
- **CSV ローダー対象外**（多次元展開は MDF4 固有）。
- **プローブのコスト回帰**: HILS 実測でスキャン追加分のロード時間悪化がないこと（目標: 現行比 +数百 ms 以内）をローカルで確認し catalog に記録。

## 6. 非ゴール

遅延ロード/メモリマップ（LD-10 次段）／上限値のユーザー設定 UI（定数 1024 固定・必要なら将来 follow-up）／Y 軸目盛のラベル化／LD-01/02（開く経路・第2弾）／CSV 側の変更／プローブのグループ一括最適化（correctness-first・必要時に後付け）。

## 7. トレーサビリティ

catalog: **LD-14 を新規追加（ndim≥3 多段展開＋per-channel 1024 ガード）→ ✅解消**。LD-12 の「列数上限なし」判断を本増分で改訂（1024 以下は自動展開のまま・超過は確認必須）。実装プラン: `docs/superpowers/plans/2026-07-05-ld14-ndim-flatten.md`（writing-plans で作成）。検証データ: 幅広 2D uint8 チャンネル（合成）＋ HILS デモ mf4（プローブコスト回帰）。
