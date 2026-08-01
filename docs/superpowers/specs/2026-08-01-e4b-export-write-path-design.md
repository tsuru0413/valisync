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
- **prod 全列の見積（訂正済み）**: 出力 **~10.1 GB・純 Python 処理 ~18.4 分**（初期見積 29.65 GB/37 分は uint8 量子化の repr 長 4.57 文字を 18.63 と誤っており反証済み）。
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
   - **supersede（E-4b plan Task 7 の裁定・2026-08-01）— 「別持ちを廃止」は `ExportRequest` 経路に限って達成と読み替える**: `CsvExportOptions.header_names` は**撤去しない**。Task 7 が `CsvExporter.export` の legacy overload（`export(signals, output_path, use_unified_timeline, options)`・直呼び 36 サイト）を同じパイプラインへ落として存続させるため、`header_names` はその**唯一のヘッダ搬送路**として残る。撤去すると (i) `test_csv_export_options.py:158-171` の期待が動き（「既存テストの期待内容は編集しない」原則違反）、(ii) golden driver が GUI 形ヘッダを `header_names` へ詰めている 10 本（g01/g03-g11）が raw 名へ退行する。新境界（`ExportRequest`）では `header_resolver` が唯一の真実で `header_names` は読まれないので、C1/M7 の構造的根治（ヘッダと値を同じ keys から導出）は達成されている。完全撤去は **legacy overload 退役時の別増分**。

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
- **ヘッダと値は同じ keys から導出**する。これが C1（M7: `signals` ↔ `header_names` の対応を守るテストがゼロ・`signals.reverse()` で全緑）の構造的な根治 — 対応が by construction になる。ゴールデン fixture（§7.1）が二重の防波堤。
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
  - **係数は quick_demo 由来のまま出荷しない** — T-M で prod 1 点実測して検定してから確定（合成由来の単価は桁で外れる — 本シリーズで 3 回実証）。
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
2. prod_demo での実エクスポート未実施 — 「~10 GB・~18.4 分」は quick_demo 係数の外挿。**T-M で実測するまで受け入れ帯にしない**。空セルスキップの短縮幅（推定 30-45%）・oversize 再デコードの実分数も同様に T-M 実測待ち（受け入れ帯に使わない）。
3. 下流ツール（CANape/Excel(ja)/pandas・**および valisync 自身の `CsvLoader`** [I3]）の受理挙動 — `CsvLoader` は本増分で対応（§5.1-1）。外部ツールは実害が出たら `na_rep`/`bom` のオプション化を検討（YAGNI）。
4. `MDF.select(record_offset/record_count)` の実挙動（仮想グループ・LD-14 展開・`copy_master=False` との相互作用）— B3 spike の対象。
5. 多段マージの temp 増幅の実係数 — 「2.3 ×」は設計値（§5.3）。T-M で検証。
6. `metadata["unit"]` が `None` のときの `_header_rows` の挙動 — **production の mdf_loader は truthy ガード（`:159-161`）で None を載せない**（レビューで確認・§13-2）が、手組み metadata では TypeError になりうるので T-G の fixture に None unit を含めて確定させる。
7. 変異 M1/M2/M3/M4/M6/M8 の「全緑」は静的分析ベース — T-G の sabotage で再実行して確認。
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

## 13. 敵対的レビュー裁定記録（REFUTED — 同じ議論を繰り返さないため）

§11 実測記録・§12 繰越は将来使うための欠番。

1. **「searchsorted の対象軸が未規定」→ 部分 REFUTED** — §5.3 のパイプライン図が `resolve → sorted_view → searchsorted` と規定済み。副次 2 点（sides・len 0）のみ Minor で反映。
2. **「mdf_loader は unit を無検査代入・None 混入は実データ依存」→ REFUTED** — `if asammdf_sig.unit:` の truthy ガード（`mdf_loader.py:159-161`）で None/空文字は metadata に載らない。§9-6 の TypeError は手組み metadata（テスト）でのみ発生。
3. **「NaN タイムスタンプ行が空時刻になる」→ REFUTED** — `Signal.__init__`（`signal.py:80-82`）が全構築経路で非有限時刻を拒否するため構造的に到達不能。
4. **「`Mat[0]` 型衝突で重複列 2 本」→ REFUTED** — dedup 名と実チャンネル名の衝突は E-3 確定契約でローダーが loud-fail 拒否（`_index_physical`）し両行は共存できない。
5. **「keys tuple ~55 MB」→ 数値 REFUTED** — 実測 25.1 MB（330,004 × ~76 B）。「export 全期間生存・帳簿不在」の方向は CONFIRMED（§1 に反映）。
6. **「`file_browser_vm._human_size`」→ 名称誤り** — 実体は `_fmt_size`（`file_browser_vm.py:20-27`）。中身（B/KB/MB/GB・小数 1 桁）は主張どおり（§5.5 で参照）。
7. **「ExpansionConfirmer を参照すべき/している」→ 枠組み訂正** — ExpansionConfirmer は src から退役済み（grep 0 件）。ダイアログ型の指定が無かったのが実態で、`QMessageBox`＋DI 型の指定として §5.5 に反映。
