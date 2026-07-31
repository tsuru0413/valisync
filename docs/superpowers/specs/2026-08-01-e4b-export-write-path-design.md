# E-4b: CSV エクスポート書き経路の再構築 設計

**目的**: 「すべて選択 → エクスポート」が prod 規模（330,004 列）で OOM せず、範囲指定エクスポートが常駐を残さず、出力のバイト表現が回帰テストで凍結された状態にする。

**親 spec**: [E-4 設計](2026-07-30-e4-channel-cache-design.md) §6 が概要を確定済み（本 spec はその詳細化）。E-4a（読み経路・PR #152）完了が前提。

**ブランチ**: `feature/e4b-export-write-path`

---

## 1. なぜ今やるのか（実測）

E-4a 探索 workflow（8 エージェント・quick_demo 実測＋実コード検証・2026-08-01）で確定した事実:

- **メモリ則**: `peak ≈ 3 × 出力サイズ + 14.7 MB` がバイト単位で成立（`lines: list[str]` 構築 → `"\n".join` → `f.write` の UTF-8 エンコードバッファの 3 コピー。`csv_exporter.py:199-213` の `_atomic_write`）。逐次 write なら書き段は +19,389 B。
- **エクスポートした列は解放されない**: export 後の残留が列数に厳密比例（2,400,000 B/列）。materialized のまま常駐。
- **範囲フィルタは読む量に一切効かない**: `_in_range` は行ループの内側のみ（`:161`/`:192`）。カーソル A–B で 1 行だけ出す実測 = 出力 2,057 B に **6.523 s・cold read 120,000,000 B・export 後も 114.5 MiB 常駐**。F-0 で出荷した主要導線がこの体感。
- **統合タイムライン経路は別格**: `dict(zip(ts.tolist(), vs.tolist()))`（`:156`）が実測 **97 B/サンプル**（`sorted_view` の 12 倍）。20 列で tracemalloc 612 MB・**Win32 working set 2.14 GiB**。
- **union は ULP 差で分裂している（今日すでに）**: `5.0 + 3*0.1 = 5.300000000000001` ≠ `5.0 + 30*0.01 = 5.3`。prod デモの `100ms ⊂ 10ms` は 1188/1200 で False。union = 12,012 行のうち 12 行が「ほぼ全列が空」。prod 全列では**セルの 66% が空**。
- **prod 全列の見積（訂正済み）**: 出力 **~10.1 GB・純 Python 処理 ~18.4 分**（初期見積 29.65 GB/37 分は uint8 量子化の repr 長 4.57 文字を 18.63 と誤っており反証済み）。
- **ガードの先読み**: `_require_single_value_columns`（`:105`）が行生成の前に全列の `.values` を読む。フック実測（6 列 × 300,000 行）: ガード完了 625 ms → **最初のバイトがディスクに届くのは 9,185 ms**。
- **`_selected` の実測**: `set[str]`・キーはグループキー形（`mf4_1::Prod10Wide_0000[527]`・~27 文字）で **54.1–56.6 MB**（+58 MB の当初測定と整合。`app_viewmodel.py:141` の docstring "keys (paths)" は stale で誤読の原因 — 本増分で是正）。
- **E-4a の恒久コスト**: `ColumnRecord.path_index` が 182 B/リーフ。エクスポートは全チャンネルに触るので prod で **~57 MB が `remove(key)` まで恒久**（列ブロック内で参照を落としても戻らない）。既知として記録・本増分では削らない。

## 2. ユーザー決定

| # | 決定 | 内容 |
|---|---|---|
| U4（親 spec） | ストリーム化する | 全列エクスポートを行ストリームで OOM 解消 |
| U5（親 spec） | 列方向もチャンクして上限なし | 列ブロック＋多段マージ |
| D1（親 spec） | 境界 API 変更 | `ExportRequest`/`Session.export_csv`/`CsvExporter.export` の入力を keys ＋解決器へ |
| D2（親 spec） | 協調キャンセルのみ | 真のハング（asammdf 内部でのブロック）は対象外と明記済み |
| D5（親 spec） | ディスク検査 | 開始前に `shutil.disk_usage` で検査して不足なら拒否 |
| **B1**（2026-08-01） | **3 点直してから凍結** | NaN 表現・BOM・クォート規則を是正してから byte-identical ゴールデンを作る。行末 LF・enum の float 化は据え置き |
| **B2**（2026-08-01） | **事前見積＋確認** | 開始前に列数・推定サイズ・行数・推定時間・空セル率を提示して続行可否を人に決めさせる。拒否は D5 のディスク不足のみ。完走できる水準（進捗＋ETA＋協調キャンセル）まで作る |
| **B3**（2026-08-01) | **常駐解消＋読み削減 spike** | 常駐 114 MB の解消は受け入れ条件（ストリーム化の副産物）。読む量の削減（record range）は spike して可能なら採るが受け入れ条件にしない |
| **B6**（2026-08-01） | **何も残さない** | キャンセル/失敗時は全 temp 削除。「失敗ならファイルが存在しない」契約（test-lock 済み）を維持。キャンセルメッセージで見積値を再掲し範囲/列の削減を促す |

## 3. コントローラ決定

| # | 決定 | 理由 |
|---|---|---|
| C-1 | 統合タイムラインの既定と出力の形は不変 | union の tolerance 化は親 spec §6「searchsorted 置換は完全一致セマンティクスを保つ」を破る。レートごとファイル分割は正当な要望だが出口の再設計＝**別増分として記録**。ULP 分裂は §5.4 で既知の不完全性として明記 |
| C-2 | 並行性は最小 2 点だけ同梱 | `MdfHandle.serial` と `add()` のロック対称化はどちらも**今日すでに「2 ファイル同時ドロップ」で踏める**数十行の修正で、E-4b（worker から resolve）が確実に窓を拡大する。`_ensure_namespaced` の一括公開・`_evict_resolved` の lock 外解放は親 spec §12 記録済みの繰越のまま |
| C-3 | `≤380 ms` 帯のハード化は E-4b ではやらない | 残差は asammdf の decode 1 回＋I/O の分散（E-4a T5 実測: ~15% が帯超過・最悪 607 ms）で、エクスポート書き経路の増分では触れない層。E-4a 全体レビューの「E-4b がハード化を持つ」という繰越は**帰属誤り**として訂正し、「別の読み経路 perf 増分（要 spike: asammdf 側 read 最適化）」へ付け替える |
| C-4 | セルのフォーマットは per-cell `repr` を維持 | ゴールデンが shortest round-trip repr を固定する。numpy 系のベクトル化は repr 完全一致の保証が無く、ゴールデンを不安定にする。~18 分は B2 の見積提示で正当な待ちにする。時間短縮は測定結果として報告のみ（約束しない） |

## 4. 増分の分割

| 増分 | 内容 | 依存 |
|---|---|---|
| **T-G**（ゴールデン先行） | 出力仕様 3 点是正（§5.1）→ byte-identical ゴールデン作成（§7.1） | なし（現行コードに対して） |
| **T-API**（境界） | keys ＋解決器化（§5.2）・`_selected` 圧縮（§5.6） | T-G |
| **T-PIPE**（本体） | 列ブロック × 行ストリーム × 横マージ（§5.3）・union dedup ＋ searchsorted（§5.4） | T-API |
| **T-UX** | 見積＋確認・進捗＋ETA・協調キャンセル（§5.5） | T-PIPE |
| **T-CONC** | 並行性 2 点＋ロック契約（§5.7） | 独立（早期に入れてよい） |
| **T-M** | prod 実測＋realgui ①ゲート（§6/§7.4） | 全部 |

E-4c（衝突診断＋AST 構造ガード）は親 spec §7 のまま独立・本 spec の対象外。

## 5. 設計

### 5.1 出力仕様の 3 点是正（凍結前・現行コードに対する最小変更）

ゴールデンは一度作ると変更が全面差分になるため、直す意思のあるものは凍結前に入れる。**変更は次の 3 点のみ・他は現状バイト不変**:

1. **NaN → 空セル**。現状は裸の `nan`（Excel で文字列・pandas で NaN・CANape 不明の三者三様）。欠測（タイムライン上にサンプルが無い）と同じ空セル表現へ統一する。根拠: analysis-correctness が `Signal.finite_view()` で「非有限は値として扱わない」判断を確定済みで、エクスポートだけが逆を向いている。**注意**: これは「その行にサンプルはあるが値が NaN」と「サンプルが無い」の区別を出力から消す。区別が要る下流が現れたら `na_rep` オプション化を別途検討（YAGNI で今は入れない）。
2. **UTF-8 BOM あり**。`csv_header_names` はファイルキー併記で日本語を含みうる。BOM なしだと Excel(ja) が cp932 と誤認して化ける。pandas/CANape は BOM を透過的に扱う（pandas は `utf-8-sig` 相当で自動除去）。
3. **RFC 4180 最小クォート**。セルが `delimiter`・`"`・改行を含む場合のみ `"..."` で囲み内部の `"` は `""` へ。それ以外のセルはバイト不変。現状はクォート皆無（`delimiter.join` のみ）で、信号名に区切り文字が入ると列がずれる実害経路がある（`delimiter` にセミコロン/タブを選べる）。

**据え置き（意図的）**: 行末 LF（Excel/pandas とも読める）・enum の float 化（直すと dtype 依存分岐が入りゴールデンが不安定化）・数値の shortest round-trip repr・末尾改行あり・失敗時にファイルが存在しない契約。

### 5.2 境界 API のキー化（D1）

```python
@dataclass(frozen=True)
class ExportRequest:
    keys: tuple[str, ...]          # 列キー（表示空間・"file::Name[idx]" 形）。順序 = 出力列順
    output_path: Path
    options: CsvExportOptions      # header_names は廃止 — ヘッダは keys から解決器で導出
```

- `Session.export_csv(keys, output_path, options)` — Signal のリストを受けない。解決はブロック内で `resolve_signal`。
- **ヘッダ名は keys から `display_names` 経由で導出**する（`header_names` の別持ちを廃止）。これが C1（`signals` ↔ `header_names` の対応を守るテストがゼロ・`signals.reverse()` で全緑）の**構造的な根治** — 対応が「同じキーから導く」ことで by construction になる。ゴールデン fixture（§7.1）が二重の防波堤。
- `Session._reject_container_channels` は `column_names_of` ベースのまま keys で成立（値を読まない・0.1 ms fail-fast 維持）。
- `_require_single_value_columns` の dtype 判定はブロック内へ移る（§5.3）。container 判定はキーで開始前に落ちるので、C8 の「N 列書いた後に落ちる」は**非数値 dtype の縁例に限られる**。落ちたら B6 どおり全 temp 削除でファイルは残らない。
- 廃止に伴い `app_viewmodel.py:141` の stale docstring（"keys (paths)"）を是正。

### 5.3 書きパイプライン: 列ブロック × 行ストリーム × 横マージ

```
[見積・確認・ディスク検査 (§5.5)]
  → union タイムライン確定 (§5.4・1 回だけ)
  → for block in chunks(keys, BLOCK_COLS):          # 既定 120 列
        resolve → sorted_view → searchsorted 引き当て
        → 行ストリームで block-temp へセル断片を書く   # "v1,v2,...,v120" 行
        → 参照を落とす (block ローカル変数のみ・キャッシュは E-4a の LRU に任せる)
  → 横マージ: 全 block-temp を行単位で並行に読み delimiter join → final-temp
  → os.replace(final-temp, output_path)
```

- **1 ブロックの同時生存**: 鋳造列 Signal ≤ BLOCK_COLS ＋ union 配列 ＋ 書き出しバッファ。行ストリームなので `lines: list[str]` と `"\n".join` の全文コピーは消える（A1 の 3 コピー → 0）。
- **横マージのディスクピーク ≈ 2 × 出力**（断片合計 ≒ 出力・最終 temp ＝ 出力）。D5 の `shutil.disk_usage` 検査は `2.2 × 推定出力` を要求する（安全率 0.2 は temp のヘッダ/時刻列分）。
- 時刻列は**専用 temp** が持つ（block-temp と対称な「幅 1 のブロック」として扱い、マージ器に特別扱いを作らない）。ヘッダ 1-2 行（名前行・単位行）は最終マージの先頭で keys から導出して書く。
- **範囲指定（B3）**: union 確定後に `searchsorted` で行範囲 `[lo, hi)` を 1 回だけ求め、全ブロックがその行範囲だけを書く。読み（`sorted_view` の実体化）は全期間のままだが、**ブロック終端で参照が落ちるので常駐しない**（受け入れ条件: 範囲エクスポート後の鋳造列常駐が BLOCK_COLS 相当以下）。
- **record range spike（B3・採否は spike 結果で）**: `MDF.select(record_offset=, record_count=)` で読む量自体を縮める案。**採る場合の必須条件 — 窓読みの結果を `ChannelSampleCache` に入れない**（キー空間 `(serial, gi, ci)` に窓が無く、後続の全期間読みが切り詰められた配列を引く C2 のサイレント誤データになる。`_column_of` の検証は長さ比較のみで同長の別窓は素通し）。仮想グループ・LD-14 展開・`copy_master=False` との相互作用が未検証（§9-4）なので、spike で挙動確認 → 採否判断 → 採らない場合は理由を本 spec に追記。
- **統合タイムライン経路の `dict(zip(...tolist()))` は廃止**し、searchsorted 引き当てに統一（97 B/サンプル → 8 B/サンプル）。非統合（per-signal タイムライン）経路も同じブロック機構を通す。

### 5.4 union の identity dedup ＋ searchsorted

- master 配列を `id()` で dedup してから `np.unique(np.concatenate(uniques))`。prod: 330,004 列の master オブジェクトは **5 個**（loader が仮想グループごとに 1 本読んで全 Signal に同一オブジェクトを渡す — `mdf_loader.py:415`/`:561`・`_mint_column` は `parent.timestamps` をそのまま渡す）。1.352e9 要素のコピーが 25,680 要素（205 KB）になる。
- **dedup は `is`（identity）であって値比較ではない**。`np.array_equal` で畳むと ULP 差の行が畳まれ時刻が黙ってずれる（C3）。逆に identity のみだと「別オブジェクト・同値」の master では dedup が効かないだけ（正しさは保たれ、コストだけ増える）— 安全側。
- 値引き当ては `np.searchsorted(ts, union_ts)` ＋完全一致検証（`ts[idx] == union_ts` のマスク）。**完全一致セマンティクスを保つ**（親 spec §6 確定・`"1.0,,21.0"` と末尾越えの test-lock が既に RED 網）。
- **ULP 分裂は既知の不完全性として受容**（C-1）。B2 の確認ダイアログに空セル率を出すことで、ユーザーが「行が異常に多い」ことに気付ける。tolerance 化・レート別ファイル分割は不採用/別増分。

### 5.5 見積＋確認・進捗＋ETA・協調キャンセル

- **見積**（値を読まずに計算）: 行数 = union 長（§5.4 は読む前に master だけで計算可能 — master は既にメモリに在る）・列数 = keys・サイズ ≈ 行数 × (平均セル長 × 非空率 + 区切り) を係数化・時間 ≈ セル数 × 単価。**係数は quick_demo 由来のまま出荷しない** — T-M で prod 1 点実測して検定してから確定（[[perf_pacing_floor_is_deadline_plus_largest_atomic_unit]] の教訓: 合成由来の単価は桁で外れる）。
- **確認ダイアログ**: 列数・推定サイズ・推定行数・推定時間・空セル率。拒否（開始不能）は D5 のディスク不足のみ・他は情報提示して人が決める。閾値以下（推定 < 10 MB かつ < 5 s 目安・値は plan で確定）は確認を出さない。
- **進捗**: ブロック単位（`block_done / block_total`）＋ ETA（経過 × 残り/完了）。既存の `BusyOverlay`/ステータスバー機構に乗せる（新 UI は作らない）。
- **協調キャンセル**: `threading.Event` をブロック境界＋行ループの N 行ごと（plan で確定・数千行目安）にチェック。キャンセル時: 全 temp 削除 → 「範囲を狭める/列を減らす」を見積値つきで提示（B6）。D2 どおり asammdf 内部でブロックする真のハングは対象外。

### 5.6 `_selected` の圧縮

- `set[str]`（330,004 キー・54-57 MB）→ 物理チャンネル単位の区間表現:

```python
@dataclass
class ColumnSelection:
    ALL / NONE / PARTIAL(indices: frozenset[int])   # チャンネルごと
_selected: dict[str, ColumnSelection]               # キーは物理チャンネルキー（~4,324 個）
```

- 「すべて選択」= 全チャンネル ALL で **~0.5 MB**。PARTIAL は明示 indices のみ保持。
- `ExportRequest.keys` への展開は accept 時に**ジェネレータで**行い、list を実体化するのはブロック分割の直前（tuple 化は必要 — 順序が契約）。
- **順序契約の先行強化（C9）**: 現在ファイル間順序は `set()` 比較で盲目（`test_export_csv_dialog.py:136/:205/:571`）。圧縮の**前に**順序比較テストへ強化し、圧縮後も「ツリー表示順 = 出力列順」を保存する。
- `_row_matches`（打鍵ごとに 330,004 本の f-string 再生成）への波及は本増分で調査し、非自明なら記録のみ（フィルタ perf は本増分の目的でない）。

### 5.7 並行性の最小 2 点＋ロック契約

1. **`MdfHandle.serial`**: `itertools.count()` によるプロセス単調 int を `__slots__` に追加し、`ChannelSampleCache` のキーを `(id(handle), gi, ci)` → `(handle.serial, gi, ci)` へ。id 再利用（実測 100% 再現の CPython アドレス再利用）で別ファイルの値を返す窓が**構造的に消滅**する。置換サイトは `drop_handle`/`release_handle` の呼び出し 2 箇所＋キー構築 1 箇所。
2. **`add()` のロック対称化**: `SignalGroupManager.add()` を `_resolved_lock` 下に入れ、`self._groups[key] = ...` を最後に書く（`remove()` は E-4a T3 で既にロック下 — 非対称が `_counters` の RMW 競合とグループ黙殺・`handle.close()` 不達を生む。`add()` はロードワーカースレッドで走り、`data_explorer_view.py:217-219` が URL ごとに submit するので **`add()` 同士も今日並行しうる**）。

**保存するロック契約**（spec 明記＋テスト固定）:
- `handle.lock` を保持したまま `SignalGroupManager.resolve()` を呼ばない（C7: 列ブロックの最も自然な書き方 `with handle.lock: for k in block: resolve(k)` がこれを破る。resolve → `_resolved_lock` → `_evict_resolved` の同期解放でサイクルの片側が揃う。**単一スレッドのテストでは検出不能**なので、lock-order を観測する probe（既存 `_LockProbeArray` 型）で固定）。
- `_resolved_lock` 下で I/O をしない（`pinned_column_bytes` が `array_if_materialized` に留まっていることが防波堤でもある）。
- 既存の唯一のネスト `handle.lock → cache._lock` は不変。
3. **docstring 是正（C10）**: `channel_cache.py:108-112` が主張する「同一チャンネルの別列の同時読みを select 1 回に畳む」機構は**実装に存在しない**（`sample_source.py:203-206` が明示的に逆を書く）。E-4b の並列度設計をこの記述から決めると外すため是正する。なお本増分のブロック処理は**直列**（並列ブロックは複雑さに対する利得が I/O 支配で薄い — 測定で覆れば別増分）。

## 6. 受け入れ基準

| # | 基準 | 測り方 |
|---|---|---|
| G1 | **ゴールデン一致** | 是正 3 点込みの出力が byte-identical（§7.1 の fixture 群・`read_bytes` 比較） |
| G2 | **同時生存が閉じる** | 鋳造列 Signal の同時生存数 ≤ BLOCK_COLS ＋ ε（鋳造/解放カウンタで観測。**`bytes_held` は使わない** — エクスポート列は pin されず構造的に盲目 = C5） |
| G3 | **スケール不変** | ブロック k と k+120 の USS 差 ±20%（親 spec §6 確定） |
| G4 | **全列完走** | prod_demo 全列エクスポートが OOM せず完走（USS ピーク上限は T-M の実測で確定・quick_demo 係数からの外挿を受け入れ帯にしない） |
| G5 | **範囲の常駐解消** | カーソル A–B（1 行）エクスポート後の鋳造列常駐 ≤ BLOCK_COLS 相当（現状 114.5 MiB → ブロック分のみ） |
| G6 | **キャンセル** | 実キャンセルで全 temp が消えファイルが存在しない・GUI が固まらない（オフスレッド assert = C6） |
| G7 | **オフスレッド性** | export 実行スレッド ID ≠ メインスレッド ID を assert する専用テスト（M5 の「インライン化しても全緑」を閉じる） |
| G8 | **realgui ①ゲート** | 実 OS 入力で（a）確認ダイアログ → 続行 → 完走 → 実ファイル読み直し（b）実キャンセル → ファイル無し。既存 `test_export_range_realclick.py` の `_read_timestamps`（時刻列しか読まない）を**全列読み**へ強化 |

## 7. テスト方針（探索で実証された盲点 C1-C10 を閉じる）

### 7.1 ゴールデン（T-G）

- fixture は **全列が相異なる定数値**（列 j の値 = f(j) で一意）を持つ mf4 ＋ CSV。「列 j のヘッダと列 j の値が同じ信号から来る」ことがバイト比較で落ちる（C1/M7: 現在 `signals.reverse()` しても全緑）。
- 被覆する軸: 単一/統合タイムライン × 範囲あり/なし × 欠測あり × NaN あり × 要クォート名 × 日本語ヘッダ × 重複名 dedup（`W[0]` 形）× enum。ULP 分裂 fixture（`100ms ⊂ 10ms` の再現）も 1 本 — 分裂の**行数まで**凍結し、将来 union 実装を触った者が黙って挙動を変えられないようにする。
- 比較は `read_bytes()` 全文一致。既存テストは 1 本も編集しない（ゴールデンは追加）。
- **sabotage 必須**: 列順反転・ヘッダ入れ替え・行末 CRLF 化・BOM 除去・クォート除去の各変異で RED を実証してから凍結。

### 7.2 パイプライン（T-PIPE）

- union dedup は「同一 master 共有」（prod 形）と「別 master・同値」（dedup が効かず正しさだけ保たれる形）の**両 fixture**（C3）。
- searchsorted は既存 test-lock（`"1.0,,21.0"`・末尾越え）＋ ULP 分裂ゴールデンが RED 網。
- container/dtype ガードの fail-fast 維持は `sorted_view` spy 方式（`test_export_container_guard.py` が既に確立）をブロック化後も維持（C8）。
- G2 の生存数カウンタは**外部から観測**（`resolved_keys()` のスナップショット）— 実装自身が書く数値だけに頼らない（E-4a の教訓: カウンタは自己バイパスに盲目 → 独立オラクル併置。[[test_blindness_reaim_existing_probe]]）。

### 7.3 並行性（T-CONC）

- serial キー: 「handle A を閉じ → 同 id で handle B が再利用 → B の読みが A のエントリを引かない」を id 強制再現（既存 memory の手法）で固定。
- add 対称化: 2 スレッド同時 `add()` で `_counters` の欠落ゼロ・全 handle が close 到達。
- lock 契約: `_LockProbeArray` 型 probe を「`handle.lock` 保持中の resolve 呼び出し」検出に転用。

### 7.4 実測（T-M）

- prod_demo 1 点実測で見積係数を検定（B2 の式）。
- 全列エクスポート実走（G4）— USS ピーク・完走時間・出力サイズを記録し spec §1 の見積と突き合わせ。
- **単価を記録するときは主語（何が bytes を作ったか）を必ず併記**（本シリーズで 3 回踏んだ罠）。

## 8. 非スコープ（明示）

- `≤380 ms` 帯のハード化（C-3・帰属を読み経路 perf 増分へ訂正）
- レートごとのファイル分割出力（C-1・別増分として記録）
- union の tolerance 化（C-1・不採用）
- セルフォーマットのベクトル化（C-4・測定報告のみ）
- `_row_matches` のフィルタ perf（§5.6・調査と記録のみ）
- `path_index` の 57 MB 恒久コスト（§1・記録のみ）
- 並列ブロック処理（§5.7-3・直列で出荷）
- E-4c（衝突診断＋AST ガード・親 spec §7 のまま独立）
- 親 spec §12 の残り繰越（`_ensure_namespaced` 一括公開・`_evict_resolved` lock 外解放）

## 9. 未解決の不明点（plan / spike で解消）

1. GUI 経路（`ExportCsvDialog`/`ExportController`）の実測が無い — `_selected` 54-57 MB は合成再現。T-API 実装時に実ダイアログで 1 点測る。
2. prod_demo での実エクスポート未実施 — 「~10 GB・~18.4 分」は quick_demo 係数の外挿。**T-M で実測するまで受け入れ帯にしない**。
3. 下流ツール（CANape/Excel(ja)/pandas）の受理挙動は B1 決定の前提として一般知識ベース — 実害が出たら `na_rep`/`bom` のオプション化を検討（YAGNI）。
4. `MDF.select(record_offset/record_count)` の実挙動（仮想グループ・LD-14 展開・`copy_master=False` との相互作用）— B3 spike の対象。
5. 多段マージの temp 増幅の実係数 — D5 の「2.2 ×」は設計値。T-M で検証。
6. `metadata["unit"]` が `None` のときの `_header_rows` の挙動（TypeError の可能性）— T-G の fixture に None unit を含めて確定させる。
7. 変異 M1/M2/M3/M4/M6/M8 の「全緑」は静的分析ベース — T-G の sabotage で再実行して確認。

## 10. 保存すべき契約（違反＝サイレント破壊）

- 出力列順 = `ExportRequest.keys` の順 = ツリー表示順（ファイル間含む）。
- ヘッダと値は**同じキーから導出**する（別持ちの復活はレビューで落とす）。
- union は完全一致セマンティクス（tolerance 禁止）・dedup は identity のみ。
- 窓読み（record range）の結果を `ChannelSampleCache` に入れない（spike で採る場合）。
- `handle.lock` 保持中に `resolve()` を呼ばない／`_resolved_lock` 下で I/O をしない。
- 失敗/キャンセルならファイルが存在しない（temp 含む）。
- エクスポートの受け入れを `bytes_held` で書かない（pin されず構造的に盲目）。
