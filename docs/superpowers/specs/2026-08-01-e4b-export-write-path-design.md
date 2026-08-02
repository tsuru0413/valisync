# E-4b: CSV エクスポート書き経路の再構築 設計

**目的**: 「すべて選択 → エクスポート」が prod 規模（330,004 列）で OOM せず、範囲指定エクスポートが常駐を残さず、出力のバイト表現が回帰テストで凍結された状態にする。

**親 spec**: [E-4 設計](2026-07-30-e4-channel-cache-design.md) §6 が概要を確定済み（本 spec はその詳細化）。E-4a（読み経路・PR #152）完了が前提。

**ブランチ**: `feature/e4b-export-write-path`

**改訂履歴**: 初版（2026-08-01）→ 敵対的レビュー 7 レンズ＋裁定＋統合（9 エージェント・Critical 7 / Important 15 / Minor 11 / REFUTED 7 — §13）を反映（裁定 ID: MG-x/I-x/F-x/compat-x/ux-x/plan-x）。

---

## 1. なぜ今やるのか（実測）

E-4a 探索 workflow（8 エージェント・quick_demo 実測＋実コード検証・2026-08-01）＋敵対的レビューの追加実測で確定した事実:

- **メモリ則**: `peak ≈ 3 × 出力サイズ + 14.7 MB` がバイト単位で成立（`lines: list[str]` 構築 → `"\n".join` → `f.write` の UTF-8 エンコードバッファの 3 コピー。`csv_exporter.py:199-213` の `_atomic_write`）。逐次 write なら書き段は +19,389 B。
- **エクスポートした列は解放されない**: export 後の残留が列数に厳密比例（2,400,000 B/列）。materialized のまま常駐。
- **範囲フィルタは読む量に一切効かない**: `_in_range` は行ループの内側のみ（`:161`/`:192`）。カーソル A–B で 1 行だけ出す実測 = 出力 2,057 B に **6.523 s・cold read 120,000,000 B・export 後も 114.5 MiB 常駐**。F-0 で出荷した主要導線がこの体感。
- **統合タイムライン経路は別格**: `dict(zip(ts.tolist(), vs.tolist()))`（`:156`）が実測 **97 B/サンプル**（`sorted_view` の 12 倍）。20 列で tracemalloc 612 MB・**Win32 working set 2.14 GiB**。
- **union は ULP 差で分裂している（今日すでに）**: `5.0 + 3*0.1 = 5.300000000000001` ≠ `5.0 + 30*0.01 = 5.3`。prod デモの `100ms ⊂ 10ms` は 1188/1200 で False。union = 12,012 行のうち 12 行が「ほぼ全列が空」。prod 全列では**セルの 66% が空**。
- **prod 全列の見積（本節時点の外挿・のちに反証）**: 出力 **~10.1 GB・純 Python 処理 ~18.4 分**（初期見積 29.65 GB/37 分は uint8 量子化の repr 長 4.57 文字を 18.63 と誤っており反証済み）。**この行自体も Task 11 (T-M) の prod_demo 実測で外挿として反証された** — 実測は出力 **10.75 GB・完走 46-48 分**（§9-2/§11 参照）。本行は「なぜ今やるのか」当時の見積として歴史的に残し、値としては §11 の実測を参照すること。
- **ガードの先読み**: `_require_single_value_columns`（`:105`）が行生成の前に全列の `.values` を読む。フック実測（6 列 × 300,000 行）: ガード完了 625 ms → **最初のバイトがディスクに届くのは 9,185 ms**。
- **`_selected` の実測**: 実体は **`dict[str, tuple[int, int]]`**（`export_csv_dialog.py:154` — キー = namespaced 列キー・値 = ツリー位置 `(row, col)`）で **54.1–56.6 MB**。出力の列順は `_checked_keys()` の `(row, col)` sort（`:570`）が担う（§5.6 の圧縮はこの**順序運搬**も置換する必要がある）。`app_viewmodel.py:141` の docstring "keys (paths)" は stale で誤読の原因 — 本増分で是正。
- **FD 同時 open 天井（本環境実測・MG-2）**: **8,189 本で `OSError errno 24`**（CPython 3.13.7 / Win11）。prod 3 ファイル比較の全列エクスポートは block 数 ~8,253 で、単段の横マージは**確実に**天井を超える → §5.3 は多段マージが必須。
- **`ExportRequest.keys` の tuple 自体が ~25.1 MB**（330,004 × ~76 B・実測）で export 全期間生存する。帳簿（どの数字にも出ない）として §6 G4 の実測に含める。
- **E-4a の恒久コスト**: `ColumnRecord.path_index` が 182 B/リーフ。エクスポートは全チャンネルに触るので prod で **~57 MB が `remove(key)` まで恒久**（列ブロック内で参照を落としても戻らない）。既知として記録・本増分では削らない。

## 2. ユーザー決定

| # | 決定 | 内容 |
|---|---|---|
| U4（親 spec） | ストリーム化する | 全列エクスポートを行ストリームで OOM 解消 |
| U5（親 spec） | 列方向もチャンクして上限なし | 列ブロック＋**多段**マージ |
| D1（親 spec） | 境界 API 変更 | `ExportRequest`/`Session.export_csv`/`CsvExporter.export` の入力を keys ＋解決器へ |
| D2（親 spec） | 協調キャンセルのみ | 真のハング（asammdf 内部でのブロック）は対象外と明記済み |
| D3（親 spec） | ブロックサイズは動的 | 「予算 − 現在の pin 済み」から動的に決める（§5.3 で採用 — 初版の固定 120 は記録なき supersede だった [perf-4]） |
| D5（親 spec） | ディスク検査 | 開始前に `shutil.disk_usage` で検査して不足なら拒否 |
| **B1**（2026-08-01） | **是正してから凍結** | NaN 表現・BOM・クォート規則＋**ヘッダ導出形**（§5.1 — 計 4 点）を是正してから byte-identical ゴールデンを作る。行末 LF・enum の float 化は据え置き |
| **B2**（2026-08-01） | **事前見積＋確認** | 開始前に列数・行数・空セル率（正確値）と推定サイズ・推定時間（推定値）を提示して続行可否を人に決めさせる。拒否は D5 のディスク不足のみ。完走できる水準（進捗＋ETA＋協調キャンセル）まで作る |
| **B3**（2026-08-01） | **常駐解消＋読み削減 spike** | 常駐 114 MB の解消は受け入れ条件。読む量の削減（record range）は spike して可能なら採るが受け入れ条件にしない |
| **B6**（2026-08-01） | **何も残さない** | キャンセル/失敗時は全 temp 削除。「失敗ならファイルが存在しない」契約（test-lock 済み）を維持。キャンセルメッセージで見積値を再掲し範囲/列の削減を促す |

## 3. コントローラ決定

| # | 決定 | 理由 |
|---|---|---|
| C-1 | 統合タイムラインの既定と出力の形は不変 | union の tolerance 化は親 spec §6「searchsorted 置換は完全一致セマンティクスを保つ」を破る。レートごとファイル分割は正当な要望だが出口の再設計＝**別増分として記録**。ULP 分裂は §5.4 で既知の不完全性として明記 |
| C-2 | 並行性は「今日踏める 2 点」＋**E-4b が常態化させる 1 点**を同梱 | `MdfHandle.serial` と `add()` のロック対称化は今日すでに「2 ファイル同時ドロップ」で踏める。**加えて `_ensure_namespaced()` の無ロック反復も同梱**（初版は繰越としたが、E-4b は export worker の resolve を ~18 分走らせ、親 spec §12-5 が「窓」と記録した競合を**常態**へ変える — 窓を自分で拡大しながら繰越にはできない [MG-5]）。`_evict_resolved` の lock 外解放は繰越のまま（§8） |
| C-3 | `≤380 ms` 帯のハード化は E-4b ではやらない | 残差は asammdf の decode 1 回＋I/O の分散（E-4a T5 実測: ~15% が帯超過・最悪 607 ms）で、エクスポート書き経路の増分では触れない層。E-4a 全体レビューの「E-4b がハード化を持つ」という繰越は**帰属誤り**として訂正し、「別の読み経路 perf 増分（要 spike: asammdf 側 read 最適化）」へ付け替える |
| C-4 | セルのフォーマットは per-cell `repr` を維持 | ゴールデンが shortest round-trip repr を固定する。numpy 系のベクトル化は repr 完全一致の保証が無く、ゴールデンを不安定にする。~18 分は B2 の見積提示で正当な待ちにする。時間短縮は測定結果として報告のみ（約束しない） |
| C-5 | ヘッダ解決は **DI（callable 注入）** | core は `gui.display_names` を import しない明文契約（`csv_exporter.py:39-44`）があり、core 移設は構造変更＝ユーザー承認事項かつ `_TIMESTAMP_POOL_GROUP` 注入の写し漏れリスクを負う。`ExportRequest` にヘッダ解決器（GUI 側で `csv_header_names` を束ねた callable）を持たせる（§5.2）[MG-4] |

## 4. 増分の分割

| 増分 | 内容 | 依存 |
|---|---|---|
| **T-G**（ゴールデン先行） | 出力仕様 4 点是正（§5.1）→ byte-identical ゴールデン作成（§7.1） | なし（現行コードに対して） |
| **T-API**（境界） | keys ＋解決器化（§5.2）・`_selected` 圧縮（§5.6）・**移行橋 = keys を受けて旧一括実装で処理する薄いアダプタ**（この時点でフル緑・§5.2 末尾）[plan-4] | T-G |
| **T-PIPE**（本体） | 列ブロック × 行ストリーム × 多段マージ（§5.3）・union dedup ＋ searchsorted（§5.4）・橋の撤去 | T-API |
| **T-UX** | 見積＋確認・進捗＋ETA・協調キャンセル（§5.5） | T-PIPE |
| **T-CONC** | 並行性 3 点＋ロック契約（§5.7） | 独立（早期に入れてよい） |
| **T-M** | prod 実測＋realgui ①ゲート（§6/§7.4） | 全部 |

E-4c（衝突診断＋AST 構造ガード）は親 spec §7 のまま独立・本 spec の対象外。

## 5. 設計

### 5.1 出力仕様の是正（凍結前・現行コードに対する最小変更）

ゴールデンは一度作ると変更が全面差分になるため、直す意思のあるものは凍結前に入れる。**変更は次の 4 点・他は現状バイト不変**:

1. **NaN → 空セル**。現状は裸の `nan`（Excel で文字列・pandas で NaN・CANape 不明の三者三様）。欠測（タイムライン上にサンプルが無い）と同じ空セル表現へ統一する。根拠: analysis-correctness が `Signal.finite_view()` で「非有限は値として扱わない」判断を確定済みで、エクスポートだけが逆を向いている。
   - **±inf も同時に確定する [I-5/I-6]**: `finite_view` は NaN と inf を等価に「非有限」と扱うので、出力も **inf → 空セル** に揃える（`'inf'` を残す非対称を凍結しない）。fixture 軸に ±inf を追加。
   - **対の `CsvLoader` 修正を本増分スコープに含める（根治）**: `csv_loader.py:212-227` は空セルを `ValueError` → ロード全体失敗にするため、**自製品の出力を自製品が読めなくなる**。空セル = NaN 受理へ修正し、§9-3 の「下流ツール」リストに valisync 自身を加える。
   - 注入点は**値セル 2 サイト**（`csv_exporter.py:164`/`:195`）— `_fmt` は時刻セルと共用（`:163`/`:194`）なので触らない。precision 分岐の `f"{nan:.3f}"` → `"nan"` 漏れも同時に対処 [I13/plan-6]。
2. **UTF-8 BOM あり**。`csv_header_names` はファイルキー併記で日本語を含みうる。BOM なしだと Excel(ja) が cp932 と誤認して化ける。pandas は `utf-8-sig` 相当で自動除去・**`CsvLoader` は既に utf-8-sig 読み**（`csv_loader.py:46`）なので roundtrip は無修正で生存する。
   - **既存テストへの影響（**影響テスト 26 本**・supersede 記録つきで読み口のみ編集を許す）[MG-3]**: `test_export.py` 3・`test_csv_export_options.py` 19・`test_export_container_guard.py` 2・`test_session.py:451`・realgui `_read_timestamps`。**「26 本」は影響を受けるテストの本数であって編集する行数ではない** — 実際に書き換える**物理読み口は 10 サイト・9 行**（`test_csv_export_options.py` は 22 本のテストがヘルパ `_read` 1 箇所を共有する等）で、全数表は E-4b plan Task 1 Step 7 が一次情報源。**期待内容（値・文字列）は 1 本も変えない** — 読み口を `encoding="utf-8-sig"` にするだけの機械的編集で、各サイトに supersede コメントを残す。§7.1 の「既存テストは編集しない」原則の唯一の例外として明記。
   - **supersede（レビュー是正・2026-08-01）— 本番の読み口は `CsvLoader` の 1 箇所ではなく 2 箇所**: `CsvFormatDetector`（`csv_format_detector.py:147`）も自製品の出力を読む本番経路（「開く」経路の CSV 自動検出・`main_window.py:675`）だが、上の「`CsvLoader` は既に utf-8-sig 読み」という記載はこれを見落としていた。原因は Task 1 Step 1 の読み口全数実測（`.superpowers/sdd/task-1-report.md` §3）が `tests/` 配下・`read_text(encoding="utf-8")` という綴りに絞った grep だったこと — 検出器は `src/` にあり `.open("r", encoding="utf-8", ...)` という別綴りで読むため、スコープ（対象ディレクトリ）と綴りの両方で網から漏れた。実害: `str.strip()` は U+FEFF を落とさない（空白ではなく書式制御文字 Cf）ため、BOM 付きヘッダで `_detect_timestamp_column`（`:184-185`）の名前ヒントが列 0 で外れ、時間らしい名前を持つ**信号**列が誤って時間軸に選ばれる（単調列フォールバックが名前ヒントを持たない信号では覆い隠すため、多くのケースでは表面化しない）。修正: 検出器も `utf-8-sig` 読みへ（`tests/core/test_export_output_spec.py::test_detector_finds_the_timestamp_column_in_our_own_bom_output` が pin）。
3. **RFC 4180 最小クォート**。セルが `delimiter`・`"`・改行を含む場合のみ `"..."` で囲み内部の `"` は `""` へ。それ以外のセルはバイト不変。**ヘッダ行・単位行にも適用**する（信号名/単位こそ区切り文字混入の主経路）[M-2]。注入点は **join 4 サイト**（`:144`/`:147`/`:165`/`:196`）への集約 [I13]。
4. **ヘッダ導出形 [MG-7]**。`CsvExportOptions.header_names` の別持ちを廃止し keys から導出（§5.2）するため、`Session.export_csv` 直呼び（header 未指定）の出力ヘッダが raw namespaced 名（`mf4_1::speed`）→ **表示名導出形**へ変わる。これは「第 4 のバイト変更」であり、**ゴールデンは導出形ヘッダで駆動して凍結する**（GUI 経由の実出力は既に導出形なので、ユーザーが見る形とゴールデンが一致する）。T-G 時点での駆動方法（導出を先行導入するか、golden driver が導出形と同一バイトを明示注入で固定するか）は plan で確定。
   - **supersede（E-4b plan Task 7 の裁定・2026-08-01）— 「別持ちを廃止」は `ExportRequest` 経路に限って達成と読み替える**: `CsvExportOptions.header_names` は**撤去しない**。Task 7 が `CsvExporter.export` の legacy overload（`export(signals, output_path, use_unified_timeline, options)`・直呼び 36 サイト）を同じパイプラインへ落として存続させるため、`header_names` はその**唯一のヘッダ搬送路**として残る。撤去すると (i) `test_csv_export_options.py:158-171` の期待が動き（「既存テストの期待内容は編集しない」原則違反）、(ii) golden driver が GUI 形ヘッダを `header_names` へ詰めている 10 本（g01/g03-g11）が raw 名へ退行する。新境界（`ExportRequest`）では `header_resolver` が唯一の真実で `header_names` は読まれないので、C1/M7 の構造的根治（ヘッダと値を同じ keys から導出）は達成されている。完全撤去は **legacy overload 退役時の別増分**。**landing 済み（Task 7・2026-08-01）**: `docs/design.md` 決定履歴に 1 行記録。実装上の位置は `CsvExporter.export` の legacy 分岐で、`header_names` から固定 resolver を作って `_export_request` へ渡す（`_export_request` は `options.header_names` を読まない）。副産物として **legacy 形にも C-5 のヘッダ長検査がかかる**ようになった（旧 `_header_rows` は長さ無検査で、`header_names` が短いとヘッダだけ列数の足りない CSV を黙って書いていた）— 既存 19 本はすべて長さ一致で呼んでおり無回帰。

**据え置き（意図的）**: 行末 LF（Excel/pandas とも読める）・enum の float 化（直すと dtype 依存分岐が入りゴールデンが不安定化）・数値の shortest round-trip repr・末尾改行あり・失敗時にファイルが存在しない契約。

### 5.2 境界 API のキー化（D1）

```python
@dataclass(frozen=True)
class ExportRequest:
    keys: tuple[str, ...]              # 列キー（表示空間・"file::Name[idx]" 形）。順序 = 出力列順
    output_path: Path
    options: CsvExportOptions          # use_unified_timeline は options 経由で存続 [M-1]
    header_resolver: Callable[[Sequence[str]], list[str]]
                                       # GUI 側で csv_header_names を束ねて注入 (C-5)。
                                       # core は gui.display_names を import しない契約を維持
```

- `Session.export_csv(keys, output_path, options, header_resolver)` — Signal のリストを受けない。解決はブロック内で export 専用 resolve（§5.3）。
- **ヘッダと値は同じ keys から導出**する。これが C1（M7: `signals` ↔ `header_names` の対応を守るテストがゼロ〔既存の header_names テストは全て 1 列 fixture〕。`signals.reverse()` そのものは header_names=None の既存テスト 6 本が捕まえるが、**header_names 指定時**（GUI 経路）の対応崩しは無検出だった）の構造的な根治 — 対応が by construction になる。ゴールデン fixture（§7.1）が二重の防波堤。
- **単位行は keys から導出できない**（各列の `metadata["unit"]` が要る）。**ブロックパス中に側帯収集**し、最終マージの先頭で書く。**マージ段での再 resolve は禁止**（330k 再 resolve は ~390 MB の一撃 — §10 契約）[MG-4]。
- **keys の解決可能性検証は accept 時（worker 投入前）**に行い、既存 UX 契約（保存先を訊く前に missing 検出 — `export_csv_dialog.py:768-785`・test `:862-883` が pin）を保存する。worker 内で発生した dtype 縁例のみ B6 経路（全 temp 削除・ファイル無し）[I-4]。
- **Derived 信号の扱い [I-3]**: 現行は `session.py:517-519` が素通しし `test_export.py` 5 本が固定するが、Derived は `SignalGroupManager` に登録されず keys で解決できない。**`ExportRequest.extra_signals: tuple[Signal, ...]`（escape hatch・既定空）を設け、Derived は Signal 直渡しを維持**する。keys 化の対象は解決可能な列のみ。プロット中の Derived が消えない（既存テスト 5 本が無編集で生存する）ことを T-API の受け入れに含める。
- `Session._reject_container_channels` は `column_names_of` ベースのまま keys で成立（値を読まない・0.1 ms fail-fast 維持）。
- **共有タイムライン前提検証（`csv_exporter.py:179-186` の loud-fail）は union 確定直後・ブロック書き開始前**に全 keys へ実施（master のみで判定・値を読まない）[MG-6]。
- 廃止に伴い `app_viewmodel.py:141` の stale docstring（"keys (paths)"）を是正。
- **T-API の移行橋 [plan-4/I12]**: keys 化した `ExportRequest` を受けて**旧一括実装で処理する薄いアダプタ**（keys → resolve 全列 → 旧 `CsvExporter.export`）を同時に入れ、T-API 単独でフル緑にする。`ExportController.submit` の署名は後方互換に拡張（`export_worker.py:72-80`）。影響 48 サイト / 7 ファイル＋`test_integration.py` の追随方針（橋経由なら期待値不変）を plan に明記。T-PIPE で橋を撤去。

### 5.3 書きパイプライン: 列ブロック × 行ストリーム × 多段マージ

```
[見積・確認・ディスク検査 (§5.5)]
  → union タイムライン確定 (§5.4・1 回だけ)
  → 共有タイムライン前提検証 (§5.2・master のみ・値を読まない)
  → for block in chunks(keys, block_cols):          # block_cols は D3 準拠の動的決定
        export 専用 resolve → sorted_view → searchsorted 引き当て
        → 行ストリームで block-temp へセル断片を書く   # "v1,v2,...,vN" 行
        → unit 側帯収集 → ブロック終端で参照を明示解放
  → 多段マージ: fan-in F (既定 512 目安・plan で確定) で block-temp を
    行単位 join → 中間 temp → … → final-temp    # 段数 = ceil(log_F(block 数))
  → os.replace(final-temp, output_path)
```

- **export 専用 resolve [MG-1]**: エクスポートの列解決は **`_resolved_by_key`/`_resolved_order` に登録しない**専用経路（`SignalGroupManager.resolve_transient(key)` — 命名は plan で確定）で行い、鋳造列の生存を**ブロックローカル参照のみ**にする。E-4a の LRU（容量 512）に載せると: 全列エクスポートの定常が ~512 本 ≫ G2 上限になり、選択列 < 512 の範囲エクスポートでは 1 本も evict されず**現状の 114.5 MiB 残留がそのまま残る** — 「LRU に任せる」は機構レスであり、親 spec §12-1 が自己警告した言い回しの再利用だった。代替案（各ブロック終端の明示 evict API）との選択は plan で確定するが、**受け入れは機構でなく観測（G2/G5 の weakref カウント）で判定**する。
- **ブロックサイズは D3 準拠の動的決定**: `block_cols = clamp(残余予算 // 列あたり実体化バイト見積, 最小 16, 最大 512)`。列あたり見積は `union 長 × 8 B（sorted_view float64）＋ native`。**E-4a キャッシュとの相互作用**: ブロックが読む物理チャンネルの samples は `ChannelSampleCache`（256 MB・予約は pin 分）に入るが、export の読みは**チャンネル単位で局所**（1 チャンネルの全列を同一ブロックに割り当てる — 列をチャンネル跨ぎで混ぜない）なので、キャッシュヒットはブロック内で完結し evict 連鎖はチャンネル数分で頭打ち。
  - **supersede（E-4b plan Task 6・2026-08-01）— 単独で上限を超える run は分割する**: 「チャンネル跨ぎで混ぜない」は字面どおりだと幅 1,100 のチャンネルで 1 ブロックが `block_cols` の 2 倍超を実体化する。分割してよい根拠は E-4a のチャンネルキャッシュが 2-D を保持していること（2 ブロック目の切り出しは `select` ではなくヒットになる）。よって `plan_blocks` の契約は「**1 チャンネルの列は可能なかぎり同一ブロックへ。ただし単独で `block_cols` を超える run は `block_cols` 単位で分割する**」。
  - 列あたり実体化バイトの実装式は `union 長 × 9 B（float64 値 8 B ＋ 存在フラグ 1 B）＋ master 長 × 16 B（整列中の sorted_view: 時刻 8 B ＋ 値 8 B）`（上の「× 8 ＋ native」の精密化）。
- **1 ブロックの同時生存**（帳簿・G4 の実測対象）: 鋳造列 Signal ≤ block_cols ＋ union 配列 ＋ searchsorted の idx/mask 配列（union 長 × 8 B ＋ union 長 × 1 B）＋ 書き出しバッファ ＋ keys tuple ~25.1 MB（全期間）。
- **多段マージ [MG-2]**: 同時 open は fan-in F 本＋書き 1 本のみ（実測天井 8,189 に対し余裕 1 桁）。**マージ器は全入力 temp の行数一致を assert**（不一致 = ブロック書きのバグ → loud-fail → B6 で全 temp 削除）[MG-6]。中間 temp を含むディスクピークは `出力 × (1 + 1/F の等比和 + 安全率)` ≈ **2.3 × 推定出力**を D5 検査値とする（実係数は T-M 検証・§9-5）。
- 時刻列は**専用 temp** が持つ（block-temp と対称な「幅 1 のブロック」として扱い、マージ器に特別扱いを作らない）。ヘッダ行は keys から `header_resolver` で・単位行は側帯収集から、最終マージの先頭で書く。
- **範囲指定（B3）**: union 確定後に `searchsorted` で行範囲 `[lo, hi)` を 1 回だけ求め（閉区間保存: lo は `side='left'`・hi は `side='right'` [M-3]）、全ブロックがその行範囲だけを書く。読み（`sorted_view` の実体化）は全期間のままだが、export 専用 resolve によりブロック終端で参照が落ち**常駐しない**（G5）。
- **record range spike（B3・採否は spike 結果で）**: `MDF.select(record_offset=, record_count=)` で読む量自体を縮める案。**採る場合の必須条件 — 窓読みの結果を `ChannelSampleCache` に入れない**（キー空間に窓が無く、後続の全期間読みが切り詰められた配列を引くサイレント誤データ。`_column_of` の検証は長さ比較のみで同長の別窓は素通し）。仮想グループ・LD-14 展開・`copy_master=False` との相互作用が未検証（§9-4）なので、spike で挙動確認 → 採否判断 → 採らない場合は理由を本 spec に追記。
- **統合タイムライン経路の `dict(zip(...tolist()))` は廃止**し、searchsorted 引き当てに統一（97 B/サンプル → 8 B/サンプル）。非統合（per-signal タイムライン）経路も同じブロック機構を通す。

### 5.4 union の identity dedup ＋ searchsorted

- master 配列を `id()` で dedup してから `np.unique(np.concatenate(uniques))`。prod: 330,004 列の master オブジェクトは **5 個**（loader が仮想グループごとに 1 本読んで全 Signal に同一オブジェクトを渡す — `mdf_loader.py:415`/`:561`・`_mint_column` は `parent.timestamps` をそのまま渡す）。1.352e9 要素のコピーが 25,680 要素（205 KB）になる。**注意: 5 個は生成デモの人工事実** — 実 CANape の独立ラスタでは master 本数 G = O(10²–10³) になりうる（§9 に外挿警告）。
- **dedup は `is`（identity）であって値比較ではない**。`np.array_equal` で畳むと ULP 差の行が畳まれ時刻が黙ってずれる（C3）。identity のみだと「別オブジェクト・同値」の master では dedup が効かないだけ（正しさは保たれ、コストだけ増える）— 安全側。
- **CSV グループでは dedup が構造的に効かない [I-9]**: `csv_loader` は writeable な timestamps を渡すため `Signal.__init__` が per-signal コピーする（`signal.py:83` は read-only 入力のみ共有）。**`csv_loader` の timestamps read-only 化 1 行（`mdf_loader.py:432` と同型）を本増分スコープに含める** — これで CSV グループも列間共有になり dedup が効く。
- 値引き当ては `np.searchsorted(ts, union_ts)` ＋完全一致検証（`ts[idx] == union_ts` のマスク）。**完全一致セマンティクスを保つ**（親 spec §6 確定・`"1.0,,21.0"` と末尾越えの test-lock が既に RED 網）。**len 0 信号（LD-09 のヘッダのみ CSV）で素朴実装は IndexError** — fixture 軸に追加 [M-4]。
- union に NaN が入らないのは `Signal.__init__` の非有限時刻拒否（`signal.py:80-82`）への依存 — その旨を明記し、依存が外れたら union が壊れることをコメントで繋ぐ。
- **ULP 分裂は既知の不完全性として受容**（C-1）。B2 の確認ダイアログに空セル率を出すことで、ユーザーが「行が異常に多い」ことに気付ける。tolerance 化・レート別ファイル分割は不採用/別増分。

### 5.5 見積＋確認・進捗＋ETA・協調キャンセル

- **見積**（値を読まずに計算）:
  - **正確値**: 列数（keys 長）・行数（union 長 — master は既にメモリに在るので読み無しで計算可能）・空セル率（各 master の union への searchsorted ヒット数から厳密に出る）。
  - **推定値**: サイズ ≈ 行数 × (平均セル長 × 非空率 + 区切り) の係数化・時間 = **読みコスト項（cold 列数 × 列単価）＋ セル書きコスト項（セル数 × 単価）** [I10 — 初版の「セル数 × 単価」だけでは「カーソル A–B × 全列」の読み支配ケースを 0 と見積もる]。
    - **Task 8 の逸脱（2026-08-02 追記）**: 読みコスト項は字面どおりの「cold **列**数 × 列単価」ではなく **cold チャンネル数 × チャンネル単価** で計算する。E-4a 以降の読みは 1 select + k スライスなので、列単位で数えると幅 1,100 のチャンネルを 1,100 回読む前提になり prod 全列で ~29 時間 (330,004 列 × 旧単価 0.316 s ≈ 104,281 s — **Task 11 実測 46-48 分の ~38 倍**。当初は未検証の 18.4 分外挿と比較して「~95 倍」としていたが、その外挿自体が §9-2/§11 の実測で反証されているため比較基準を実測値へ差し替えた) を提示する — 見積が桁で嘘をつく。実装は `estimate.py::estimate_export` の `lazy_scalar_channels * _READ_S_PER_COLD_SCALAR_CHANNEL + lazy_wide_channels * _READ_S_PER_COLD_WIDE_CHANNEL`。
  - **係数は quick_demo 由来のまま出荷しない** — T-M で prod 1 点実測して検定してから確定（合成由来の単価は桁で外れる — 本シリーズで 3 回実証）。**解消（T-M・2026-08-02、Task 11 レビュー C1 で再是正）**: prod_demo 実測 2 点 (空セル率 66%/0%) で検定。**初版は読みコスト単価を単一定数 (0.316 s/channel・「幅 1,100 の最広チャンネル 1 本」の cold select) として全チャンネルへ一律適用しており、scalar チャンネル (4,324 本中 4,004 本) で ~21 倍の過大見積になっていた**（旧「自己無矛盾性チェック」は read_a を仮定して VALUE を逆算し、その VALUE で read_a を再現するだけの恒等式で、読み単価そのものの独立検証にはなっていなかった）。レビュー是正で読み項を **scalar/wide のチャンネルクラス別単価** に分割（prod_demo 全数再測定: scalar 5.55 ms/channel・wide 161 ms/channel）し、書きコスト単価の 2x2 較正をこの是正後の読み項で解き直した結果、**BASE は 0 ではなく 4.815e-7 s/セル**（VALUE は 6.813e-7 s/セルへ更新）と判明した — 旧 BASE=0 は「読み項の過大推定が書き項の較正へ漏れた結果」であって実測ではなかった。詳細は §11・`estimate.py` の定数コメント。
- **確認ダイアログ**: 上記 5 点を提示。拒否（開始不能）は D5 のディスク不足のみ・他は情報提示して人が決める。**確認スキップ閾値は推定時間ベース**（推定 < 5 s 目安・plan で確定。サイズのみで判定しない — 読み支配ケースが素通りする [I10]）。**進捗とキャンセルは閾値と独立に常時提供**（見積が外れて 10 倍かかったときの脱出路）。
- **ダイアログの型と文言 [I15/ux-A]**: `QMessageBox` ＋ `_confirm_fn` DI 型（`file_browser_view.py:183-191` と同型）。全文言は `strings.py` 集約（増分 D-1 の文言 OS）・ボタンは本文動詞一致（`CONFIRM_CLOSE_YES` 型）・桁区切りは付けない（既存決定 `strings.py:261`）・サイズ表記は `_fmt_size` 同型（`file_browser_vm.py:20-27`・B/KB/MB/GB・小数 1 桁）。空セル率の文言例: 「出力の約 66% は空セルです（信号ごとに記録周期が異なるため）」。
- **進捗＋ETA [I14/ux-B,C]**: `BusyOverlay` は現状 3 点で衝突する — 全て本増分で解消する:
  1. **`cancel_requested` は `_load_controller.cancel_active` へ恒久配線**（`main_window.py:209`）＝ エクスポート中のキャンセルボタンは**今日死んでいる**。アクティブ操作（load/export）へのルーティングに改める。
  2. 1 インスタンス共有で LoadController（件数ベース）と ExportController（無条件 hide）が相互ガード無し — 所有権（参照カウント or 操作種別タグ）を設計。
  3. 不確定バー `setRange(0,0)` のままではブロック進捗が出ない — **determinate 化**（ブロック単位 `block_done / block_total`・マージ段も段数で進捗に計上）・ETA は「経過 × 残り/完了」で最初のブロック完了までは「計測中…」・完了 0 除算ガード。
- **協調キャンセル**: `threading.Event` を**ブロック境界＋ブロック内の各列読みの前＋行ループ N 行ごと**にチェック [I8 — ブロック境界だけでは cold ~316 ms/列 × block_cols の間 Event を見ない]。キャンセル時: 全 temp 削除 → 「範囲を狭める/列を減らす」を**開始前見積値**つきで提示（B6）。D2 どおり asammdf 内部でブロックする真のハングは対象外。

### 5.6 `_selected` の圧縮

- 現行 `dict[str, tuple[int, int]]`（330,004 キー・54-57 MB・値はツリー位置 = **出力順の運搬者**）→ 物理チャンネル単位の区間表現:

```python
@dataclass
class ColumnSelection:
    ALL / NONE / PARTIAL(indices: frozenset[int])   # チャンネルごと
_selected: dict[str, ColumnSelection]               # キーは namespaced 物理チャンネルキー（~4,324 個）[M-6]
```

- 「すべて選択」= 全チャンネル ALL で **~0.5 MB**。PARTIAL は明示 indices のみ保持。
- **出力順の導出を明示設計する [I4]**: 現行の順序は `_checked_keys()` の `(row, col)` sort が担っており、ColumnSelection には順序が無い。**ツリー表示順の walk で keys を再導出**する（チェックした順ではない）。§7 の C9 テストに「**チェック順 ≠ ツリー順**」ケースを必須で入れる（sort 廃止で順序がチェック順に退化する回帰を捕まえる）。
- **オフセットガードの再実装 [I5]**: 現行は per-key probe（`_add_selection`:463-464）で「選択列にオフセットあり → 表示由来ラジオ disabled」（F-0 出荷済み契約）を実現しており、O(1) トグル化で消える。**方向反転で再実装** — オフセット辞書側（少数）を走査して選択集合と交差判定。
- `ExportRequest.keys` への展開は accept 時にツリー walk で行い、tuple 化は必要（順序が契約・~25.1 MB は §1 帳簿）。
- 追随が要る既存テスト: `test_export_flow.py:187-188` の `len(dlg._selected)` を含め、移行対象を plan で全数列挙 [compat-9]。
- `_row_matches`（打鍵ごとに 330,004 本の f-string 再生成）への波及は本増分で調査し、非自明なら記録のみ（フィルタ perf は本増分の目的でない）。

### 5.7 並行性の 3 点＋ロック契約

1. **`MdfHandle.serial`**: `itertools.count()` によるプロセス単調 int を `__slots__` に追加し、`ChannelSampleCache` のキーを `(id(handle), gi, ci)` → `(handle.serial, gi, ci)` へ。id 再利用（実測 100% 再現の CPython アドレス再利用）で別ファイルの値を返す窓が**構造的に消滅**する。
   - **置換サイトは grep 実測で src 3 箇所**（`sample_source.py` の `id(self._handle)`・`session.py` の `id(group.handle)`・`mdf_handle.py` の `id(self)` — spec 字面の `id(handle)` では 1 つも hit しない綴り違い）**＋ `scripts/measure_lazy_footprint.py:934`/`:867-869`**（serial 化後にサイレント 0 を返す — 計測器も同時に追随）[I7a]。
   - §10 の drop-before-close 契約の**根拠が変わる**: serial 化で「id 再利用の誤配」は消え、残る根拠は「解放のペーシング（teardown 経由）」のみ — 契約自体は維持し根拠を書き換える。
2. **`add()` のロック対称化**: `SignalGroupManager.add()` を `_resolved_lock` 下に入れる。**書き順は「counters/内部表の更新 → `self._groups[key] = ...` → `_invalidate_namespaced()`」**（「最後に書く」の字義通り実装は invalidate 後の間隙で新グループ欠落キャッシュが固定される — 精密化 [I7b]）。ロード経路（`LoadWorker` → `session.load` → `add`）に `_resolved_lock` の再入は無いことを確認済み。
3. **`_ensure_namespaced()` の競合閉鎖 [MG-5]**: `resolve()` が lock 取得前に無ロックで `_groups.items()` を反復する現状は、export worker の resolve が ~18 分走る E-4b で dict-changed-size / None.get の**常態化**になる。読み書きを `_resolved_lock` 下（または immutable snapshot の原子的差し替え）に入れる。C-2 の初版判断（繰越）を supersede。

**unload との競合契約 [I7c]**: 今日の防波堤は GUI busy 述語（`app_viewmodel.py:247-255`）1 枚。E-4b 後も **GUI 側ガードは維持**しつつ、core 側の振る舞いを定義する — worker の resolve が `None` / `SampleReadError` を返したら **B6 経路（全 temp 削除・ファイル無し・診断 1 件）**。クラッシュではなく decay。

**保存するロック契約**（spec 明記＋テスト固定）:
- `handle.lock` を保持したまま `SignalGroupManager.resolve()` を呼ばない（列ブロックの最も自然な書き方 `with handle.lock: for k in block: resolve(k)` がこれを破る。**単一スレッドのテストでは検出不能**なので、lock-order を観測する probe（既存 `_LockProbeArray` 型）で固定）。
- `_resolved_lock` 下で I/O をしない（`pinned_column_bytes` が `array_if_materialized` に留まっていることが防波堤でもある）。
- 既存の唯一のネスト `handle.lock → cache._lock` は不変。

4. **docstring 是正**: `channel_cache.py:108-112` が主張する「同一チャンネルの別列の同時読みを select 1 回に畳む」機構は**実装に存在しない**（`sample_source.py:203-206` が明示的に逆を書く）。E-4b の並列度設計をこの記述から決めると外すため是正する。なお本増分のブロック処理は**直列**（並列ブロックは複雑さに対する利得が I/O 支配で薄い — 測定で覆れば別増分）。

## 6. 受け入れ基準

各基準に「緑のまま壊れている」経路を閉じる条件を併記する [I11]。

| # | 基準 | 測り方・空虚化の閉鎖 |
|---|---|---|
| G1 | **ゴールデン一致** | 是正 4 点込みの出力が byte-identical（§7.1・`read_bytes` 比較）。**block_cols を注入可能**にし、ゴールデンは複数ブロック（境界跨ぎ）で駆動。**ゴールデンの再生成は禁止**（変更は supersede 記録つきの手動更新のみ）。§9-7 の sabotage 再実行を T-G の完了条件に含める |
| G2 | **同時生存が閉じる** | 鋳造列 Signal の同時生存数 ≤ block_cols ＋ ε を **weakref ベースの独立カウント**で観測（`resolved_keys()` は LRU 帳簿＝export 専用 resolve に構造的に盲目なので**使わない**。`bytes_held` も使わない — エクスポート列は pin されない）[MG-1] |
| G3 | **スケール不変** | ブロック k と k+1 の増分（分母 = ブロック 1 個分の実体化バイト）が ±20%。ブロック数 ≥ 8 の fixture で測る（2 ブロックでは傾き検定にならない）。**supersede（E-4b plan Task 7・2026-08-01）: CI の門番は `tracemalloc` 版**（`psutil` が本番/dev いずれの依存にも無く、USS 版は CI で丸ごと skip されるため）。spec 字面どおりの **USS 版は `VALISYNC_MEMTEST` + `importorskip` の opt-in** として併置する（`tests/core/loaders/test_mdf_loader_master_retention.py` と同型） |
| G4 | **全列完走** | prod_demo 全列エクスポートが OOM せず完走。USS ピーク上限は **T-M の実測で確定し、判定走行とは別の走行から供給**（同一走行から閾値を得る循環の禁止）。完走後の**出力内容検証**（行数 = union 長・列数 = keys 長・ランダム 100 セルの独立オラクル照合）を併置 — 「完走した」だけでは空のファイルでも緑 |
| G5 | **範囲の常駐解消** | カーソル A–B（1 行）エクスポート後の鋳造列常駐 ≤ block_cols **本**（単位は列本数 — バイト解釈だと 288 MB 帯になり現状の 114.5 MiB が素通しする）。G2 と同じ weakref オラクル |
| G6 | **キャンセル** | 実キャンセルで全 temp が消えファイルが存在しない。**temp は出力先と同一ディレクトリ**（D5 のボリューム検査と同一ボリューム・`os.replace` の原子性前提）。**「temp が一度は存在した」ことを観測してから消滅を assert**（上界 0 の空虚形回避） |
| G7 | **オフスレッド性** | export 実行スレッド ID ≠ メインスレッド ID を assert。**捕捉点は 2 箇所**（resolve 時と write 時 — 部分インライン化の検出）（M5 の「インライン化しても全緑」を閉じる） |
| G8 | **realgui ①ゲート** | 実 OS 入力で（a）確認ダイアログ → 続行 → 完走 → 実ファイル読み直し（b）実キャンセル → ファイル無し。**fixture は確認閾値を確実に超える規模を明示指定**（閾値未満だとダイアログ経路が空振りして (a) が空虚化）。既存 `test_export_range_realclick.py` の `_read_timestamps`（時刻列しか読まない）を**全列読み**へ強化 |

## 7. テスト方針（探索＋敵対的レビューで実証された盲点を閉じる）

### 7.1 ゴールデン（T-G）

- fixture の値は **`f(j, i)` の単射**（列 j × 行 i で全セル一意 — 列定数 `f(j)` だけだと searchsorted のオフバイワン・行シフトに盲目 [I11]）。
- 被覆する軸: 単一/統合タイムライン × 範囲あり/なし × 欠測あり × NaN あり × **±inf** × 要クォート名 × 日本語ヘッダ × 重複名 dedup（`W[0]` 形）× enum × **unit=None** × **len 0 信号** × **非単調/重複 ts**。ULP 分裂 fixture（`100ms ⊂ 10ms` の再現）も 1 本 — 分裂の**行数まで**凍結。
- 比較は `read_bytes()` 全文一致。既存テストの**期待内容**は 1 本も編集しない（唯一の例外 = §5.1-2 の BOM 読み口 26 本・supersede 記録つき）。
- **sabotage 必須**: 列順反転・ヘッダ入れ替え・行末 CRLF 化・BOM 除去・クォート除去・**delimiter 変更・precision 変更・範囲境界 ±1 サンプル・空選択・1 列のみ**の各変異で RED を実証してから凍結。§9-7 の静的分析ベース変異（M1/M2 等）もここで再実行。

### 7.2 パイプライン（T-PIPE）

- union dedup は「同一 master 共有」（prod 形）と「別 master・同値」（dedup が効かず正しさだけ保たれる形）の**両 fixture**。**dedup の下界オラクル**（dedup を削除すると concat 要素数が跳ねることを観測 — 性能 RED）も置く [I11]。
- searchsorted は既存 test-lock（`"1.0,,21.0"`・末尾越え）＋ ULP 分裂ゴールデンが RED 網。既存 test-lock 2 本（`csv_exporter` の `:92`/`:101` 相当）は T-API の橋経由で期待値不変のまま移行 [MG-6]。
- container/dtype ガードの fail-fast 維持は `sorted_view` spy 方式（`test_export_container_guard.py` が既に確立）をブロック化後も維持。
- G2/G5 の生存数は **weakref による独立オラクル**（§6）。実装自身が書くカウンタだけに頼らない（E-4a の教訓: カウンタは自己バイパスに盲目）。
- 多段マージの行数不一致 loud-fail（§5.3）の RED を、行数をずらした block-temp 注入で実証。

### 7.3 並行性（T-CONC）

- serial キー: 「handle A を閉じ → 同 id で handle B が再利用 → B の読みが A のエントリを引かない」を id 強制再現（既存 memory の手法）で固定。
- add 対称化: 2 スレッド同時 `add()` で `_counters` の欠落ゼロ・全 handle が close 到達。書き順（§5.7-2）の間隙は「add 直後の resolve が新グループを見る」ことで観測。
- `_ensure_namespaced`: resolve 反復中の並行 add で dict-changed-size が出ないことをストレス（反復を人工的に長引かせる hook）で固定。
- lock 契約: `_LockProbeArray` 型 probe を「`handle.lock` 保持中の resolve 呼び出し」検出に転用。

### 7.4 実測（T-M）

- prod_demo 1 点実測で見積係数を検定（B2 の式・読み項と書き項を別々に）。
- 全列エクスポート実走（G4）— USS ピーク・完走時間・出力サイズを記録し spec §1 の見積と突き合わせ。
- **単価を記録するときは主語（何が bytes を作ったか）を必ず併記**（本シリーズで 3 回踏んだ罠）。

## 8. 非スコープ（明示）

- `≤380 ms` 帯のハード化（C-3・帰属を読み経路 perf 増分へ訂正）
- レートごとのファイル分割出力（C-1・別増分として記録）
- union の tolerance 化（C-1・不採用）
- セルフォーマットのベクトル化・空セルスキップ最適化（C-4・測定報告のみ）
- `_row_matches` のフィルタ perf（§5.6・調査と記録のみ）
- `path_index` の 57 MB 恒久コスト（§1・記録のみ）
- 並列ブロック処理（§5.7-4・直列で出荷）
- E-4c（衝突診断＋AST ガード・親 spec §7 のまま独立）
- `_evict_resolved` の lock 外解放（親 spec §12-2 の繰越のまま。**ただし E-4b で「競合する取り手が居ない」という defer 根拠は失効する**［export worker が `_resolved_lock` の取り手になる］— ホット化したら E-4c で実施 [F6]）
- 親 spec §12 の残り繰越

## 9. 未解決の不明点（plan / spike で解消）

1. GUI 経路（`ExportCsvDialog`/`ExportController`）の実測が無い — `_selected` 54-57 MB は合成再現。T-API 実装時に実ダイアログで 1 点測る。
2. **解消（T-M・2026-08-02）**: prod_demo 全列 (330,004 列) 実エクスポートを 2 回実施 (較正走行 + 判定走行・別プロセス)。実測 actual_wall = **2,903.7 s (48.4 分・較正走行) / 2,762.4 s (46.0 分・判定走行 G4)**・出力 **10,745,297,021 B (~10.75 GB)**。旧見積「~10.1 GB・~18.4 分」（quick_demo 係数の外挿）は外挿として的中率が低く（時間は ~2.6-2.9 倍過小）、実測値へ置換した。詳細は §11。空セルスキップの短縮幅・oversize 再デコードの実分数は本増分の受け入れ対象に含まれず未計測のまま（別増分）。
3. 下流ツール（CANape/Excel(ja)/pandas・**および valisync 自身の `CsvLoader`** [I3]）の受理挙動 — `CsvLoader` は本増分で対応（§5.1-1）。外部ツールは実害が出たら `na_rep`/`bom` のオプション化を検討（YAGNI）。
4. **解消（T-M・2026-08-02・B3 spike）— 不採用を確定**。`scripts/e4b_record_range_spike.py` で quick_demo (narrowest=scalar・widest=8-leaf 2-D) と prod_demo の実チャンネルを計測。**スカラーは窓読みで縮む**（quick_demo VehSpd 相当: 10% 窓で wall 比 0.237・quick_demo ACC.TargetAccel: 0.142）が、**prod 規模の広幅 2-D チャンネル (Prod10Wide_0000・1,100 leaves) は縮まない**（全期間 338.2 ms → 10% 窓 376.7 ms・比 1.114 = むしろ悪化。`copy_master=False` でも同様 339.1 ms）— MDF4 のデータブロックがチャンネル全体で 1 単位に圧縮されており、部分窓でも該当ブロックを丸ごと復号する構造と推定される。読み時間の支配項は広幅チャンネル（1 本 338 ms 対スカラー 1 本 0.7 ms・~480 倍）なので、**全体としての採用メリットは無い**。§5.3/§10 の「採る場合」の契約記述はそのまま残す（条件つきなので無効化不要）が、本増分では不採用・production へ入れない。follow-up: record range を採るなら「広幅チャンネルには効かない」ことを前提にスカラー限定の最適化として再設計すること。
   **M2 是正（Task 11 レビュー）**: 判断の決め手だった `Prod10Wide_0000` 実測は、当初 `scripts/e4b_record_range_spike.py` の `TARGET` が quick_demo 固定でファイルを直接編集しないと再現できなかった。`--target <path>` を追加し `--target demo_data/prod_demo.mf4` で同じ判断材料 (2-D が縮まない・scalar は縮む) を再現できることを確認した (再実行では 419.70 ms → 371.99 ms・比 0.886 — 単発計測のノイズで数値は上の実測と完全一致しないが、「窓の比率どおり (~0.100) には遠く及ばず縮まない」という結論は同じ)。
5. **解消（T-M・2026-08-02）**: 多段マージの temp 増幅の実係数を、複数ブロック・複数マージ段を強制する fixture (block_cols/merge_fan_in 注入・spec G1 と同じ口) で直接測定 (`shutil.disk_usage` はボリューム全体の空き容量を返すため他プロセスの I/O ノイズを拾う実測上の罠があり、**scratch ディレクトリの実ファイル合計サイズ**を高頻度サンプリングする方式へ訂正して測った)。2 構成 (12 ブロック/3 段構成・50 ブロック/2 段構成) でそれぞれ **1.956 × / 1.973 ×** — 設計値 2.3 × に対し実測は一貫して低く、**2.3 × は安全側 (十分な余裕を持った上限) と確認**。値の変更は不要。（**M1 是正・Task 11 レビュー**: 本行は当初 12 ブロック/3 段構成と 50 ブロック/2 段構成の対応が §11.5 と逆順で記載されていた。計測器自体は未コミット [M2] のため再実行では突合できないが、実測直後に書かれた報告書 [`.superpowers/sdd/task-11-report.md` §11] の記述「12ブロック/3段・50ブロック/2段で1.956×/1.973×」を一次情報として §11.5 側の順序に揃えた。）
6. `metadata["unit"]` が `None` のときの `_header_rows` の挙動 — **production の mdf_loader は truthy ガード（`:159-161`）で None を載せない**（レビューで確認・§13-2）が、手組み metadata では TypeError になりうるので T-G の fixture に None unit を含めて確定させる。
7. T-G の変異表（`.superpowers/sdd/task-2-report.md` §3・**TG-1..TG-11** と改称）で置換。探索の M1..M8 の定義は復元不能（`.superpowers/sdd/` を含む全数検索で 0 件）。spec G7 の M5（インライン化）は T-G の表とは無関係の別番号。
8. **oversize-skip 再デコード病 [I9]**: `channel_cache.py:144` の `size > budget` skip（D7）に該当する >256 MB の 2-D チャンネルが実在すると、ブロック内の列ごとに全 select が復活する（条件依存で 5-55 分/チャンネル）。prod_demo には無いが実データでの存在可能性を既知リスクとして記録。
9. **master 本数の外挿**: デモの仮想グループ 5 個は人工事実。実 CANape の独立ラスタでは G = O(10²–10³) になりえ、union のコストと空セル率が変わる。T-M ではデモ値、実データ入手時に再測。

## 10. 保存すべき契約（違反＝サイレント破壊）

- 出力列順 = `ExportRequest.keys` の順 = ツリー表示順（ファイル間含む・チェック順ではない）。
- ヘッダと値は**同じキーから導出**する（別持ちの復活はレビューで落とす）。単位行はブロックパス中の側帯収集から — **マージ段での再 resolve は禁止**。
- union は完全一致セマンティクス（tolerance 禁止）・dedup は identity のみ。
- 窓読み（record range）の結果を `ChannelSampleCache` に入れない（spike で採る場合）。
- `handle.lock` 保持中に `resolve()` を呼ばない／`_resolved_lock` 下で I/O をしない。
- export の列解決は `_resolved_by_key`/`_resolved_order` に載せない（export 専用 resolve）。
- 失敗/キャンセルならファイルが存在しない（temp 含む）。temp は出力先と同一ディレクトリ（`os.replace` 原子性・D5 検査と同一ボリューム）。
- エクスポートの受け入れを `bytes_held`・`resolved_keys()` で書かない（前者は pin されず、後者は export 専用 resolve に構造的に盲目）。
- drop-before-close は維持（serial 化後の根拠は「解放のペーシング」— §5.7-1）。

## 11. 実測記録（T-M・2026-08-02）

prod_demo.mf4（1.36 GB・330,004 列・4,324 物理チャンネル・rows(union)=12,012）で
2 走行（較正 → 判定・別プロセス）を実施。手順・生ログは
`.superpowers/sdd/task-11-report.md` 参照。

### 11.1 較正走行（`--export --calibrate`）— 係数検定 2 点

| 指標 | 点 (a) 全列 | 点 (b) 単一 master 部分集合 (Prod10Wide_0000) | 主語 |
|---|---|---|---|
| 列数 / 行数 | 330,004 / 12,012 | 1,100 / 12,000 | `estimate_export` の正確値 |
| 空セル率 | 65.89% | 0.0% | searchsorted ヒット数（正確値） |
| 出力バイト（実測） | 10,745,297,021 B (~10.75 GB) | 79,306,195 B | 実ファイルサイズ |
| `bytes_ratio`（実/推定） | 1.058 | 1.075 | 平均セル長 4.57 文字の仮定に対する実測（1.0±0.3 内・据え置き） |
| `actual_wall_s` | 2,903.69 s (48.4 分) | 15.51 s | 直列ブロック処理・単一プロセスの壁時計（read+write 合算） |
| `actual_first_block_s`（**Task 11 レビュー是正・未達 2 の解消**） | 7.66 s | 0.0837 s | `export_estimate_check` の `marks[0]` までの wall（brief Step 2 が指定していたが初版報告では記録漏れだった — §11.3 末尾で解釈を検討） |
| `time_ratio`（旧係数） | 1.176 | 2.21-2.32 | 旧 (read+write) 合算推定に対する実測比 — **合算では近く見えた点 (a) の裏で書き支配の点 (b) は 2 倍以上外れていた**（I10 の警告どおり） |
| USS ピーク (`P_A`) | 2,879 MB | — | `psutil.memory_full_info().uss`・**同一プロセスで点 (b) 実行後に点 (a) を実行**したための累積 (下記 11.3 参照) |

### 11.2 判定走行（`--export --uss-limit 3600`）— G4/G5（較正とは別プロセス）

- **G4 全列完走 + 内容照合**: `columns=330,004 rows=12,012 bytes=10,745,297,021 wall=2,762.4s(46.0分) USS_peak=439MB` — 閾値 3,600 MB (= P_A×1.25 の切り上げ) に対し **OK**（大幅な余裕）。行数=union 長・列数=keys 長・ランダム 100 セルの独立オラクル (`_oracle_cell`) 照合が全 100 件一致。出力バイトは較正走行の点 (a) と**完全一致**（10,745,297,021 B）— 書きパイプラインの決定性を実証。
- **G5 範囲常駐**: 修正後のオラクルで `residual columns = 0 (<= block_cols=512+eps8)` — **OK**（ブロック終端の参照解放は理論上限どころか実測ゼロ）。
- **USS_peak の較正走行との乖離 (2,879 → 439 MB)**: 較正走行は同一プロセス内で点 (b) → 点 (a) を連続実行しており、Python アロケータの断片化蓄積が P_A を押し上げたと推定（主語: 「2 回の全列級書き出しを経たプロセスの累積断片化」であって「1 回の全列エクスポートの定常ピーク」ではない）。判定走行は較正走行の P_A から得た閾値 (3,600 MB) を実測 439 MB で大きく下回っており、**同一走行から閾値を得る循環の禁止（spec §6 G4）という設計意図は達成**（較正走行の P_A は保守的な上限として機能した）。
  **M4 是正（Task 11 レビュー）**: 2,879 MB と 439 MB は**採取方式が異なる 2 つの計測**であることをここに明記する — 較正走行の P_A は `UssPeakSampler`（バックグラウンドスレッドが 2 秒周期で独立にサンプリングし続ける・書き込み処理と非同期）、判定走行 (G4) の USS ピークは `export_full_run` の `progress` コールバック（ブロック完了ごとにその場で 1 回サンプリング・書き込み処理と同期）から得ている。上記の「同一プロセスでの累積断片化」という推定はこの採取方式の違い（未統制変数）には触れていない — 報告 §14-1 が自認するとおり、直接の反証・確証はしていない。

### 11.3 係数較正（2 点連立）— **Task 11 レビュー是正版（C1）**

**初版（反証済み・以下は履歴として残す）**: 書き 2 項モデル
(`total_cells*BASE + nonempty_cells*VALUE = write_time`) は 1 点では 2 係数を
決められない（T8 レビュー）。読み時間を差し引いた `write_time` を 2 点（点
(a): 旧読み係数 0.316×4,324ch ≈ 1,366.4 s を減算／点 (b): 独立オラクル実測
414.5 ms を減算）から求め連立を解いたところ、両点とも BASE が僅かに負
(-3.5e-9 〜 -7.4e-9 s/セル) になり、BASE を 0 へクランプして VALUE のみ
1.1403e-6 → 丸めて 1.14e-6 を採用していた。**この BASE=0 は誤りだった**:
点 (a) の read_a を旧読み係数の一律適用 (1,366.4 s) で仮定していたが、この
仮定自体が ~21 倍過大 (下記 C1 是正)。read_a を過大に見積もると差し引いた
`write_time_a` が過小になり、それを埋め合わせるように BASE が偽の負値へ
落ちる — 「BASE は実測ノイズ内でゼロ」という結論は**読み項の誤った仮定が
言わせていた**のであって、書き時間の実測そのものではなかった (レビュー C1
指摘)。「自己無矛盾性チェック」(この VALUE で書き時間を計算し実測から
読み時間を逆算すると定数と 0.3% 差で一致) も、read_a の仮定から VALUE を
逆算し、その VALUE で read_a を再現するだけの恒等式であり、読み単価の
独立検証にはならない。

**是正版**: 読み項を C1 是正 (下記) の scalar/wide クラス別単価
(scalar 5.55 ms/channel・wide 161 ms/channel) で計算し直す:

- 点 (a) 読み時間 = 4,004 × 0.00555 s + 320 × 0.161 s ≈ **73.61 s**
  （旧仮定の 1,366.4 s から 1/18.6 に縮小）。
- 点 (b) 読み時間 = 1 × 0.161 s ≈ **0.161 s**（点 (b) は `Prod10Wide_0000`
  1 チャンネルのみ選択・wide クラス）。

差し引いた `write_time_a` = 2,903.69 − 73.61 ≈ 2,830.08 s・`write_time_b` =
15.51 − 0.161 ≈ 15.349 s。点 (b) は空セル率 0%（`total_cells_b = nonempty_b`
= 13,200,000）なので `BASE + VALUE = write_time_b / total_cells_b` ≈
1.1628e-6 が直接求まる。これを点 (a) の連立
(`total_cells_a*BASE + nonempty_a*(BASE+VALUE)` の形に整理) へ代入して解くと:

**BASE = 4.815e-7 s/セル・VALUE = 6.813e-7 s/セル**（負値なし・クランプ不要 —
是正前と違い物理的に妥当な解が最初から出る）。この係数は両点の
`actual_wall` を連立の定義上厳密に再現する（残差 0）。**削除済みだった独立
micro-bench**（空セル 333.6 ns・値セル増分 722.8 ns = 3.336e-7 / 7.228e-7
s/セル）と桁・比率が近く、独立した実測（channel_cache 増分の micro-bench）
と較正結果が整合する形になった — 是正前の「BASE=0 が独立 micro-bench と
矛盾する」という不整合が解消された。

**読みコスト単価自体の再測定**（C1 是正の核）: 旧 `_READ_S_PER_COLD_CHANNEL
= 0.316 s/channel` は「幅 1,100 の最広チャンネル 1 本」の cold select を
scalar/wide 問わず全チャンネルへ一律適用しており、scalar (4,324 本中 4,004
本) を ~21 倍過大に見積もっていた（レビュアー実測: prod_demo cold select
直叩き・`copy_master=False`・scalar 25/200 サンプル平均 5.74 ms 対 wide
25/200 サンプル平均 127.7 ms・~480 倍差 — spike §9-4 の
「prod scalar 0.67 ms 対 prod wide 338.2 ms」と同じ桁）。本タスクは
prod_demo の**全数**（サンプリング誤差ゼロ）で独立に再測定した:
scalar 4,004/4,004 本 平均 **5.5474 ms**・wide 320/320 本 平均 **160.61 ms**
（全数測定はレビュアーのサンプル平均よりやや高い — wide 側の分布が右に
裾を引く〔最大 575.8 ms〕ため）。丸めて `_READ_S_PER_COLD_SCALAR_CHANNEL =
0.00555`・`_READ_S_PER_COLD_WIDE_CHANNEL = 0.161` を採用。

**独立クロスチェック（`actual_first_block_s`）**: brief Step 2 は「最初の
ブロックまでの wall」を独立指標として記録するよう指定していた（初版報告は
未記録・§11.1 表へ追加）。値は 点 (a) 7.66 s・点 (b) 0.0837 s。**ただし本
レビュー是正でコード経路を辿った結果、この指標は読み支配区間の代理指標
ではないと判明した**: `CsvExporter.export` の最初の `tick()` は時刻列の
一時ファイル書き込み直後に発火し、そこに至るまでの `scan_masters` は
**値を 1 バイトも読まない**（`sig.timestamps` だけを見る前走査・
`resolve_signal_transient` 経由の鋳造は I/O を伴わない）。つまり
`actual_first_block_s` はチャンネル読みの物理コストではなく、**選択列数
（330,004 対 1,100）に比例する `scan_masters` の逐次解決コスト**を主に
測っている（列数比 300.0 に対し wall 比 91.5 — 固定費込みの線形当てはめ
`fixed + k*columns` で fixed≈58 ms・k≈23 µs/column と高精度に一致）。
**した がって `actual_first_block_s` は本 C1 是正 (scalar/wide 単価) の
独立検証としては使えない** — 別の未モデル化コスト（列単位の解決オーバー
ヘッド・全体の 0.3% 未満で無視できる規模）を露呈させた、という位置づけで
記録に留める。brief の記録義務（Step 2）は §11.1 表への追加で満たした。

新係数での time_ratio は両点とも 1.000（連立の定義上・残差 0）。**加えて
本増分の realgui fixture (120 scalar チャンネル・200,000/50,000 行) を
独立クロスバリデーションに使うと**、新係数の予測値は実測とよく一致する
(200,000 行: 予測 28.57 s 対 実測 28.99 s・-1.4% / 50,000 行: 予測 7.64 s
対 実測 ~7.3 s・+4.7%) — 較正に使っていない第 3・第 4 の独立点でも桁だけ
でなく数割の精度で一致する。既知の限界: 空セル率 0-66% の範囲でのみ検証
（受け入れ基準 G4/G5 はこの範囲外を要求しないため出荷は妨げない）。

### 11.4 record range spike（B3）— 不採用

quick_demo + prod_demo の実チャンネルで 4 形を計測（`scripts/e4b_record_range_spike.py`）。
prod 規模の広幅 2-D チャンネル (`Prod10Wide_0000`) は 10% 窓でも wall が**縮まない**
（338.2 ms → 376.7 ms・比 1.114 = 悪化）。詳細と判断根拠は §9-4。

### 11.5 disk peak amplification（`TEMP_AMPLIFICATION`）

複数ブロック・複数マージ段を強制する 2 fixture（12 ブロック/3 段・50 ブロック/2 段）
で scratch ディレクトリの実ファイル合計サイズ（`shutil.disk_usage` はボリューム
全体を返し他プロセス I/O ノイズを拾うため不採用）を高頻度サンプリングし、
実測 **1.956× / 1.973×**（設計値 2.3× に対し安全側）。値の変更なし。詳細は §9-5。

### 11.6 realgui ①ゲート（G8）

`tests/realgui/test_export_confirm_cancel_realclick.py`（新設 2 本）:
実 OS クリックで (a) 確認ダイアログの [書き出す] → 完走 → 実ファイル全列読み直し
／(b) 実キャンセル → temp 出現を観測してからファイル無し・temp 無しを確認。
sabotage 4 件（R1 確認閾値・R2 cancel 配線・R3 temp 削除・R4 値列読み口）全て
予測どおり loud-fail することを実証（詳細・predicted vs 実際の assert 差異は
`.superpowers/sdd/task-11-report.md`）。既存 `test_export_range_realclick.py`
の `_read_timestamps` を全列読み (`_read_rows`) へ強化・既存本数のまま pass。

**Task 11 レビュー是正（I2/I3/I4/M6/M7）**: レビュアーが指定コマンドを 3 回
実行し (b) が 1 回 flaky RED（実クリックが cancel ボタンへ届かなかった —
`busy_overlay.py:66-70` に記録済みの既往）を検出、かつ失敗メッセージが
「キャンセルしたのにファイルが存在する」= production バグと誤読させる形で
あることを指摘した（I2）。是正:

- (b) は cancel Event (`ExportRun.cancel` — production の協調キャンセル観測点)
  を独立に検証し、「クリックが届いていない」と「キャンセルが効いていない」を
  別メッセージへ分離。クリック自体もリポジトリ確立プロトコル（効いたことを
  確認してから進む・`press_grip_and_confirm` と同型）の再試行ループへ強化。
- (a) は確認ダイアログの実クリックを「0.4 秒待って 1 回だけ走査」から
  「デッドラインつき再試行ループ + GUI スレッド watchdog タイマ」へ書き換え、
  `QMessageBox.exec()`（timeout 無し）の無期限ハングを構造的に排除（I4）。
- (a) の「全列読み直し」主張へ非空セルの存在チェックを追加（I3・共有
  `read_export_rows`）。
- `_pump`/`_real_click`/`_read_rows` の重複を `tests/realgui/_realgui_input`
  （`pump`/`pump_n`/`real_click_widget`/`read_export_rows`）へ共有昇格（M6）。

**是正後の実証**: 指定コマンド（両ファイル）を**連続 4 回**実行し全数 pass
（3/3/3/3 test）。sabotage 3 件を追加実施し、いずれも予測どおり loud-fail:
(1) confirm を「ダイアログを出さず True を返す」に差し替え → `assert boxes`
が「確認ダイアログが実際には出ていない (空虚化)」で RED（I4 是正前は無期限
ハングでこの assert に到達すらできなかった — M7 是正）。(2) (b) のクリック
先を cancel ボタンでなく window 本体へ差し替え → 新設の
`run.cancel.is_set()` assert が「クリックが届いていない」で RED（旧
「キャンセルが効いていない」への誤読を構造的に回避できることを実証）。
いずれも production コード側の差分ゼロで revert 済み。

## 13. 敵対的レビュー裁定記録（REFUTED — 同じ議論を繰り返さないため）

§12 繰越は将来使うための欠番。

1. **「searchsorted の対象軸が未規定」→ 部分 REFUTED** — §5.3 のパイプライン図が `resolve → sorted_view → searchsorted` と規定済み。副次 2 点（sides・len 0）のみ Minor で反映。
2. **「mdf_loader は unit を無検査代入・None 混入は実データ依存」→ REFUTED** — `if asammdf_sig.unit:` の truthy ガード（`mdf_loader.py:159-161`）で None/空文字は metadata に載らない。§9-6 の TypeError は手組み metadata（テスト）でのみ発生。
3. **「NaN タイムスタンプ行が空時刻になる」→ REFUTED** — `Signal.__init__`（`signal.py:80-82`）が全構築経路で非有限時刻を拒否するため構造的に到達不能。
4. **「`Mat[0]` 型衝突で重複列 2 本」→ REFUTED** — dedup 名と実チャンネル名の衝突は E-3 確定契約でローダーが loud-fail 拒否（`_index_physical`）し両行は共存できない。
5. **「keys tuple ~55 MB」→ 数値 REFUTED** — 実測 25.1 MB（330,004 × ~76 B）。「export 全期間生存・帳簿不在」の方向は CONFIRMED（§1 に反映）。
6. **「`file_browser_vm._human_size`」→ 名称誤り** — 実体は `_fmt_size`（`file_browser_vm.py:20-27`）。中身（B/KB/MB/GB・小数 1 桁）は主張どおり（§5.5 で参照）。
7. **「ExpansionConfirmer を参照すべき/している」→ 枠組み訂正** — ExpansionConfirmer は src から退役済み（grep 0 件）。ダイアログ型の指定が無かったのが実態で、`QMessageBox`＋DI 型の指定として §5.5 に反映。
