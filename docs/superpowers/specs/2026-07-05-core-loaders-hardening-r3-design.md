# 設計 spec: core-loaders-hardening 第3弾（LD-07/10/12/13 — MDF4 読み取りパス刷新）

MDF4 ローダーの読み取りパスを `select()` ベースに刷新し、LD-13（enum チャンネル消滅）と LD-10（大容量メモリ膨張）を同一の変更で解消する。その上に LD-12（多次元チャンネルの要素展開）と LD-07（enum ラベルの保持と GUI 併記）を載せる。LD-11 は対応しない（ユーザー判断で現状許容）。

- **作成**: 2026-07-05
- **ステータス**: 実装完了（プラン c046e25／実装 0209eb8..fd78026・全7タスク＋各タスク3レンズレビュー消化・最終パネル判定済み。**LD-10 実測: hils 2.01GB が 7.8s/+7.3GB → 3.05s/+2.53GB**・realgui 40/40 無回帰）
- **関連**: [audit-findings-catalog](../../audit-findings-catalog.md) SS-LOADERS（LD-07/10/12/13 を解消・LD-11 は仕様判断を記録）／HILS デモ mf4（PR #40/#42・検証データ）／第2弾=開く経路（LD-01/02）は別増分のまま
- **テストデータ**: `scripts/generate_demo_mf4.py`（quick/hils・2D `ObjMatrix`・enum `TurnSig`）— 本増分で TurnSig の value2text 埋込を復活させ end-to-end 検証を閉じる

---

## 1. スコープと確定判断（brainstorming・ユーザー決定）

| ID | 決定 |
|---|---|
| LD-13 | 読み取りを `select()` 系へ切替え `ignore_value2text_conversions=True` を「効く場所」で使う — value2text 付きチャンネル（DBC デコード済み enum）が生値で生存 |
| LD-10 | **コピー排除まで**（遅延ロードはしない・将来課題として roadmap へ）。共有マスタ・不要 astype コピー撲滅・逐次変換で、2GB 級のピークメモリを実測 +7.3GB → データ実体1コピー分（約 +2.2〜2.5GB）へ |
| LD-12 | 2D/構造化チャンネルを**要素展開**して表示可能に。**列数上限は設けない**（ユーザー決定 — 生フレーム `DataBytes` 型が数十列展開され得る帰結は許容し、info 診断で透明化。実害が出たら将来閾値を後付け）。**→ LD-14 で改訂**: per-channel 1024 列ガードを追加（1024 以下は自動展開のまま・超過はユーザー確認で展開/スキップ）。設計は [ld14-design](2026-07-05-ld14-ndim-flatten-design.md) |
| LD-07 | 変換表を `Signal.metadata["value_labels"]` に構造化保持＋**カーソル readout / ChannelBrowser ツールチップに「生値 (ラベル)」併記**。プロット描画と Y 軸目盛は数値のまま（目盛ラベル化は views 系の将来課題） |
| LD-11 | **対応しない** — 同一パス二重読込は別グループとして増殖する現状挙動を許容（ユーザー決定）。catalog に判断を記録して close |

## 2. 現状分析（根因の確定事実）

`src/valisync/core/loaders/mdf4_loader.py` の現行読み取りパス:

1. `MDF(path, ignore_value2text_conversions=True, ...)` — **このオプションは `MDF()` には無効**（dead・LD-13）。有効なのは `select()`/`iter_groups()`/`to_dataframe()` 系のみで、`get()`/`iter_channels()` は引数自体を持たない（asammdf 8.8.11 実ソースで検証済み）
2. `iter_channels(skip_master=True, copy_master=True)` → `raw` リストに**全チャンネル実体化** — `copy_master=True` が**マスタ時刻軸をチャンネル数分複製**（60ch グループなら同一 3.6M 点×60）
3. 変換ループが `raw` を保持したまま `astype(np.float64)`（既に float64 でも無条件コピー）→ `Signal.__post_init__` が writeable 配列を再コピー — **変換中は二重在庫**
4. value2text 付きチャンネルは iter_channels がテキスト配列を返し「non-numeric, skipped」で**チャンネルごと消滅**（LD-13）
5. `samples.ndim != 1` は skip＋警告（LD-12）

**LD-10 実測（2026-07-04・catalog 記録済み）**: hils 2.01GB/171ch → ロード 7.8 秒・プロセスピーク **+7.3GB（約3.6倍）**。上記 2+3 の複製で全て説明がつく。

## 3. 設計

### 3.1 読み取りパス刷新（LD-13＋LD-10 の本体）

**案A（採用）: グループ単位の `select()` バッチ読み**（案B=iter_channels 維持は LD-13 が解決せず却下、案C=DataFrame 系は pandas 経由のオーバーヘッドと列名衝突の扱いで却下）:

```
MDF(path, time_from_zero=False) を開く
for gi, group in enumerate(mdf.groups):                    # グループ走査
    entries = [(ch.name, gi, ci) for ci, ch in enumerate(group.channels) if not master]
    sigs = mdf.select(entries, ignore_value2text_conversions=True,
                      copy_master=False, ...)              # グループ一括取得
    master = グループの時刻軸を float64 で1本だけ実体化し writeable=False
    for asig in sigs:                                      # 逐次変換（rawリスト全量保持をしない）
        キャンセルチェック → 診断（非有限/非単調/重複名[idx]/2D展開）→
        values = asig.samples.astype(np.float64, copy=False); values.flags.writeable = False
        Signal(timestamps=master(共有), values=values, ...)  # ゼロコピー経路
```

> **実装時逸脱（Task 2 レビュー critical で確定・上記スケッチより優先**）: グループ走査は `enumerate(mdf.groups)`（物理グループ）ではなく **`for gi in mdf.virtual_groups:`＋`mdf.included_channels(gi)`** で行う。物理グループ数で回すと (i) MDF v4.20+ の remote-master/column-storage ファイルで follower gi が KeyError → ファイル全体が読めない、(ii) 構造化チャンネルの成分エントリを重複取得する。included_channels は iter_channels の実体でマスタ・成分とも除外済み（回帰テスト: `test_remote_master_style_virtual_groups_do_not_kill_load`）。

- **共有マスタ**: 同一チャンネルグループの全 Signal が同じ read-only `timestamps` 配列オブジェクトを参照（Signal は immutable 前提なので安全・`sorted_view()` のキャッシュも信号ごとに独立で影響なし）
- **`astype(copy=False)`**: 既に float64 なら無コピー。int 系（DBC raw）は必然の1コピーのみ
- **writeable=False で Signal のゼロコピー経路**: `Signal.__post_init__` の防御コピーは writeable 配列にのみ発動する（LD 第1弾の実装）— 事前に read-only 化して直渡し
- **逐次変換**: asammdf Signal を変換後すぐ参照を手放し、「raw 全量＋変換済み全量」の二重在庫を解消
- **維持する既存契約**: 協調キャンセル（チャンネル単位のチェックポイント → FB-04）、非有限 ts の error skip、非単調/重複の warning（LD-03）、ファイル全体での重複名 `name[idx]` 曖昧化（**2パス**: まず全グループの名前を数えてから変換 — 名前カウントはメタデータ走査のみでメモリ影響なし）、0ch warning（LD-05）、`_extract_metadata`/`_detect_bus_type`
- **実装時確認事項**（HILS デモ Task 2 と同じ流儀で asammdf 実ソース確認・report に記録）: `select()` の引数形式（`(name, group, index)` タプル対応）と `copy_master=False` 時のマスタ共有実態、raster/validation 系デフォルト、マスタチャンネル自身の除外方法。期待と異なる場合は per-group `get()`＋raw=False の組合せ等の代替を検討し、**LD-13 が解決しない代替は不可**

**受け入れ基準（LD-10）**: (a) 同一グループの Signal 群が `np.shares_memory` でマスタ共有していること（CI・quick/smoke 級で assert）、(b) hils 2.01GB のローカル実測でピーク増分が **+3.0GB 以下**（設計目標 +2.2〜2.5GB・実装時に before/after を catalog LD-10 行へ記録）、(c) ロード時間が現行 7.8 秒から悪化しない

### 3.2 LD-12: 多次元/構造化チャンネルの要素展開

読み取りループ内で `samples.ndim != 1` または構造化 dtype のとき、skip ではなく**展開**する:

- **2D 配列（shape (N, k)）**: 列ごとに `Name[0]` … `Name[k-1]` の 1D Signal 群へ。dtype は数値なら astype(float64)、非数値列は従来どおり non-numeric skip
- **構造化 dtype（フィールド持ち）**: フィールドごとに `Name.field` へ展開（フィールド値がさらに (N, k) なら `Name.field[i]` まで1段展開。それ以上のネストは skip＋警告 — 本番想定は物標リスト1段）
- **3D 以上**: 従来どおり skip＋警告（形状情報を診断に含める）
- **列数上限なし**（§1 ユーザー決定）。展開時は info レベル診断「Signal 'Name': 2D (N×k) を k 本に展開」で透明化
- 展開された全信号は元チャンネルの**共有マスタを参照**（追加メモリは値のみ）
- 重複名 `name[idx]` 方式との相互作用: 重複カウントは従来どおり**ベース名の事前カウント**（メタデータ走査・サンプル読み前）で行い、展開名は曖昧化済みベース名から派生させる（例: 同名 `M` が2本なら `M[0][i]`/`M[1][i]`）。「展開名が別の実チャンネル名と偶然一致する」ケースは病的として許容（発生しても信号は両方残り、名前だけ同一 — 実運用で想定しない）
- HILS デモ mf4 の `Radar.ObjMatrix`/`Cam.ObjMatrix` がそのまま受け入れテストデータ（現行「skip 警告2件」→「展開 info 2件＋`Radar.ObjMatrix[0..7]` が信号リストに出現」へ挙動変更 — **デモ関連の既存テスト（skip 前提）を新契約に更新する**）

### 3.3 LD-07: value_labels の保持と GUI 併記

**ローダー側**: `select(ignore_value2text_conversions=True)` で生値を得つつ、チャンネルの conversion オブジェクトから value→text 対応表を抽出し `Signal.metadata["value_labels"]: dict[float, str]` に保持（既存の `conversion_info` 文字列は互換のため残す）。抽出は asammdf の conversion ブロック（TABX 系）の公開属性から行い、**API 形式は実装時にソース確認**。抽出失敗・部分テーブル・範囲テキスト（value range to text）は「labels なしで続行」（チャンネル自体は生値で生存 — LD-13 の成果を損なわない）。

**GUI 側（2箇所・プロット描画は不変更）**:
1. **カーソル readout**（`CursorReadout` 補間値フロート表）: 表示値 v が**整数に厳密一致**（`|v - round(v)| < 1e-9`）し、かつ `round(v)` が value_labels に存在するときのみ「`2 (ACTIVE)`」形式で併記。補間途中の 1.4 等には付けない（嘘ラベル防止）。ラベル解決は VM 層（テスト容易性）
2. **ChannelBrowser ツールチップ**（FB-10 の `tooltip_text` 拡張）: value_labels を持つ信号に「ラベル: 0=OFF, 1=LEFT, 2=RIGHT」行を追加（**先頭8件**まで・超過は「… (全 n 件)」）

### 3.4 デモ generator の輪を閉じる（LD-13 の end-to-end 検証）

`scripts/generate_demo_mf4.py` の `TurnSig` に value2text conversion 埋込を**復活**（第2弾 Task 2 で LD-13 回避のため見送った箇所）。ロード後に (a) `TurnSig` が生値 {0,1,2} で生存、(b) `metadata["value_labels"]` に OFF/LEFT/RIGHT が入ることを統合テストで assert。HILS デモ spec §4.4 の見送り注記も更新。

### 3.5 LD-11: 仕様判断の記録のみ

catalog の LD-11 行を「✅ 仕様と判断（2026-07-05 ユーザー決定）— 同一パス再読込は別グループとして許容。ファイル更新追従の明示的な再読込操作は将来必要になれば別途起票」に更新。コード変更なし。

## 4. 検証

- **ユニット/統合（Layer A・CI）**: `tests/mdf4_helpers.py` に TABX 付き・2D・構造化 dtype の書込ヘルパを追加し、(i) value2text チャンネル生存＋value_labels 抽出、(ii) 2D/構造化の展開（名前・値・共有マスタ `np.shares_memory`）、(iii) 3D skip・ネスト超過 skip、(iv) 非単調/非有限/重複名/0ch/キャンセルの**既存診断が刷新後も全て維持**（既存テスト群がそのまま回帰網）、(v) デモ smoke 統合テストの契約更新（ObjMatrix: skip→展開）
- **メモリ検証（CI-safe）**: quick 級生成ファイルで「同一グループのマスタ共有」「values の不要コピーなし（可能なら `np.shares_memory`/base 検査）」を assert。**hils 2GB の before/after 実測はローカルのみ**（ヘッドレス計測スクリプトは前回のものを再用・結果を catalog へ）
- **GUI（Layer A/B・計画時に /gui-test-plan で②設計）**: readout のラベル併記（整数一致時のみ・非一致時は生値のみ）・ツールチップのラベル行（8件切詰め）。実 OS 入力に依存する新規経路はない見込みだが、①ゲート要否は writing-plans 時に /gui-test-plan で判定
- **docs**: catalog（LD-07/10/12/13 ✅解消・LD-11 仕様判断・LD-10 行に after 実測）・roadmap・HILS デモ spec §4.4 注記・CLAUDE.md の第3弾記述

## 5. エッジケース・留意点

- **文字列/VLSD チャンネル**: value2text とは別物（データ自体が文字列）— 従来どおり non-numeric skip（挙動不変）
- **展開の暴走**（上限なし採用の帰結）: 生フレーム `DataBytes` 型（N×64 等）は 64 本に展開される — ユーザー許容済み。info 診断で件数が見えるため、実害が出たら閾値を後付け
- **conversion が線形（DBC factor/offset）のみのチャンネル**: value_labels なし（数値変換は select が適用済み）— 従来と同じ物理値
- **部分テーブル**（テーブル外の値）: 生値のみ表示（readout のラベル解決が miss するだけ）
- **共有マスタと既存機能の相互作用**: `sorted_view()`（LD 第1弾）は timestamps を読むだけで書き換えない・オフセット機能は新配列を作る — 共有で問題なし（プランで assert テストを置く）
- **キャンセルの粒度**: select() のグループ一括読みはグループ内でキャンセル不可（グループ間でチェック）。最大グループ（hils の XCP_1ms ≈ 1.7GB）の読みが数秒単位になる場合の応答性は実装時に計測し、粒度が粗すぎるならグループ内をチャンネル分割で select する
- **CSV ローダーは対象外**（LD-13/10/12/07 は全て MDF4 固有）

## 6. 非ゴール

遅延ロード・メモリマップ（LD-10 の次段・roadmap 記録）／LD-11 の再読込操作／Y 軸目盛のラベル化（views 系）／LD-01/02（第2弾=開く経路）／CSV 側の変更／asammdf のバージョン更新。

## 7. トレーサビリティ

catalog: **LD-07/LD-10/LD-12/LD-13 を ✅解消**（LD-10 は after 実測付き）・**LD-11 を仕様判断で close**。これにより SS-LOADERS は第2弾（LD-01/02・開く経路）を残すのみ。実装プラン: [2026-07-05-core-loaders-hardening-r3.md](../plans/2026-07-05-core-loaders-hardening-r3.md)（全7タスク消化済み）。検証データ: HILS デモ mf4（quick=機能・hils=LD-10 実測）。
