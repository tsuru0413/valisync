# E-4c: 衝突診断＋AST 構造ガード 設計 spec

- **日付**: 2026-08-04
- **親 spec**: [2026-07-30-e4-channel-cache-design.md](2026-07-30-e4-channel-cache-design.md) §7（E-4c の一次定義）・§12-1/§12-2（繰越）
- **関連**: [2026-08-01-e4b-export-write-path-design.md](2026-08-01-e4b-export-write-path-design.md) §5.7-1（CacheKey serial 化＝繰越の一部は消化済み）・F6（`_evict_resolved` の defer 根拠失効）
- **ブランチ**: `feature/e4c-collision-diag-ast-guard`（main `9fdc418` 起点）

## 1. 背景と目的

遅延ロードシリーズ（増分A/B・E-0〜E-3・E-4a/E-4b）の最終増分。残る 3 つの「サイレント破壊の穴」を閉じ、docs の stale 記述 1 点を正す。

1. **衝突の不可視性**: 2-D チャンネル `Mat` と実在 1-D チャンネル `Mat[0]` が共存すると、最長一致規則（E-3・test-lock 済みの意図的仕様）により実チャンネルが勝ち、**配列 `Mat` の第 0 列リーフは列キーで参照不能**になる。データは正しく読めるが、当該列が消えたことをユーザーが知る手段が**ゼロ**（診断なし・到達不能性を assert するテストも皆無）。
2. **列挙契約の構造的無防備**: `signal_map()` の非対称 Mapping 契約（ルックアップは鋳造・列挙は物理キーのみ）への防御は挙動テストのみで、将来 `src/` に `dict(session.signal_map())` が書かれてもコンパイルは通り、**容器のみの map が「全列」の顔をして黙って得られる**（330k 列の見かけ上の消失）。
3. **`_evict_resolved` の lock 内解放**（親 spec §12-2）: 鋳造列 LRU の evict が `_resolved_lock` 保持下で参照を手放す。E-4b spec F6 が「export worker が `_resolved_lock` の取り手になったら defer 根拠失効・E-4c で実施」と明記し、**その条件は E-4b 出荷で成立済み**。
4. **docs 正誤**: CLAUDE.md／roadmap の「`CacheKey` `id(handle)` は E-4c へ継続」は stale — E-4b spec §5.7-1 で serial 化済み（`grep -rn "id(handle)" src/` = 0 hits・`test_handle_serial.py` が production 経路で pin）。

## 2. スコープ / 非スコープ

**スコープ**: 上記 1–4。GUI の見た目・挙動は不変（診断ドックに info 行が増えるのは衝突ファイルをロードした場合のみ）。

**非スコープ（defer 記録・親 spec §12 と整合）**:
- **§12-1 鋳造列 LRU のバイト裁定** — 上限は構造的に有界（512 本 × prod 実測 ~108 KB/列 ≈ 55 MB）。本数縛りは「未展開列は 0 バイトでバイト予算が効かない」ための意図的設計（`signal_group_manager.py:34-41` に明記）。pin 側の実体バイトは `pinned_column_bytes` → `set_reserved` で予算計上済み。
- **`put()` evict の非ペーシング同期解放**（1 回 27–34 ms になりうる）— 最悪 2 フレーム未満・解放は lock 外が test-lock 済み・`ChannelSampleCache` は TeardownService への参照を持たない設計で配線追加はコストに見合わない。
- mmap フロア・MDF3・GUI 未帰属メモリ（親 spec §10 のまま）。
- **interior-node 一致の診断 gap**（whole-branch review T1-M1 defer）— `shadowed_leaf` は §3.2 どおりリーフ名一致のみを検出する。実チャンネル名が配列の**中間ノード**（途中の親）に一致する配置は未検出のまま部分木ごと到達不能になりうる。LD-14 の真性多段親でのみ理論上到達可能で、asammdf がサブ配列を読み戻し時に潰す（既知挙動）ため実ファイル経由では現状再現不可 — 実害の窓は極小と判断し defer。

## 3. 衝突診断（load 時静的検出）

### 3.1 採用案と不採用案

- **案 A（採用）: ロード完了時に record 表から静的検出**。決定的・1 回だけ・既存 plumbing（`LoadResult.diagnostics` → `LoadOutcome` → `diagnostics_vm.add`）にそのまま乗る。ヘッドレス（core 単体）でも診断が得られる。
- 案 B（不採用）: lookup 時検出 — core→GUI の診断口が load 経路にしかなく sink 新設＋重複抑止が必要。ユーザーが知るのが「触ったとき」まで遅延する。
- 案 C（不採用）: error 格上げ — 実チャンネル優先は E-3 の test-lock 済み意図的仕様。データは正しく読め、配列側 1 リーフが列キーで指せないだけなので **info** が適正（LD-12 の `n_info` 側に計上され、アラームにならない）。

### 3.2 検出規則

`_load_group` の `column_records` 確定後（= 1:1 loud-fail 検査群の後）、グループ内の全実チャンネル表示名について:

> 表示名が**別の配列チャンネルのリーフ名としても解釈できる**（最長一致で実チャンネルが勝つ配置）なら、その配列チャンネルとリーフ位置を特定し、ペアごとに info 診断 1 件。

- **判定は既存の最長一致実装と共有する**。`_owning_channel`（`signal_group_manager.py:775-794`）／`parse_leaf`（`column_names.py:245-251`）と同じ規則の**二重実装を作らない** — 規則だけを問う小さな判定関数（例: `shadowed_leaf(display_name, records) -> ShadowHit | None`）を `column_names.py` へ抽出し、検出側と（可能な範囲で）解決側が同一実装を参照する形にする。実装時に `_owning_channel` 側の直接再利用が自然ならそれでもよいが、**規則を 2 箇所に書くことだけは禁止**。
- 範囲チェック: 実チャンネル名 `Mat[0]` が配列 `Mat` のリーフとして**実在する位置**（`leaf_count(spec)` の範囲内）を指す場合のみ衝突。範囲外（例: 2 列の配列に対する `Mat[7]`）は到達不能列が存在しないので診断しない。
- 多段（`W[0][1]` 形・ndim≥3 の LD-14 名）も同一規則で扱う — 判定関数が `parse_leaf` と同じ walk を使う限り自動的に整合する。

### 3.3 文言と診断フィールド

core 慣例（インライン日本語 f-string・`mdf_loader.py:105-107` の展開 info と同型・全角括弧行に `# noqa: RUF001`）:

```python
Diagnostic(
    level="info",
    message=(
        f"信号 '{name}': 同名の実チャンネルが優先されるため、"
        f"配列 '{parent}' の列 {position} は列キーでは参照できません"
    ),
    signal_name=name,
)
```

- `signal_name` は勝った側（実チャンネル名）。診断ドックの「対象」列・ダブルクリックジャンプの既存挙動に整合する。
- `position` は walk のサフィックス文字列（**プラン執筆時の実コード検証で修正**: 当初案の整数 `[{idx}]` は §3.2 が要求する多段名 `.g[3]` を表現できない。単段の正準ケース `Mat`/`Mat[0]` では `列 [0]` と同一表示）。struct 親（`Nest.g[3]` → 親 `Nest`）も同じ規則で衝突しうるが、文言テンプレートは共通とする。
- 文言は表記規約 R-01..13（docs/design.md）に従う。`::` 内部キーは露出しない（E-0 契約）。本文言に全角括弧はなく `# noqa: RUF001` は不要（ruff 実測確認済み）。

### 3.4 発行地点

`mdf_loader.py` の **`load()` 末尾**（全グループ処理後・`column_records` と `diagnostics` の両方が完全な唯一の地点）。**プラン執筆時の実コード検証で当初案「`_load_group` 末尾」から修正**: `column_records` はファイル全体のアキュムレータで `load()` が `_load_group` に渡し込む形（`mdf_loader.py:285, :299-310`）のため、各グループ末尾では**それまでに処理したグループの分しか**入っておらず、`mdf.append([sig])`＝1 チャンネル 1 グループの配置では衝突ペアは通常**別グループ**にいる — グループ末尾走査は append 順に依存して無言で取りこぼす。CSV ローダーは対象外 — CSV に配列展開列は存在しない（`column_records` が空／spec なし）ため衝突が構造的に起きない。Derived も同様。

## 4. AST 構造ガード（二層防御の上段）

### 4.1 採用案と不採用案

- **案 A（採用）**: `tests/gui/test_theme_guard.py` 同型の専用 AST テストを新設（配置は `tests/core/test_signal_map_guard.py` — 対象が `src/valisync/` 全域の core 契約のため）。ratchet allowlist（`(相対path, 行内一致パターン, 理由)` タプル・行内容マッチ）＋**陳腐化 assert**（どこにも一致しない allowlist エントリで RED）を必ず持つ。
- 案 B（不採用）: mypy plugin — 過剰。
- 案 C（不採用）: `_ResolvingMap` の `keys()/items()/values()` を raise 化 — 「列挙 = 物理キーのみ」は E-1 の**意図的非対称仕様**であり、`list(m) == physical` を挙動テストが pin する正当な使用。仕様破壊になる。

### 4.2 検出形

`src/valisync/` 配下の全 `.py` を `ast.parse` → `ast.walk` し、以下を違反として収集:

1. **直結形**: `signal_map()` 呼び出し式（`Attribute.attr == "signal_map"` の `Call`）を直接の引数に取る `dict(…)` / `list(…)` / `set(…)` / `sorted(…)` / `tuple(…)` / `iter(…)`
2. **イテレーション形**: `for … in <x>.signal_map()` / 内包表記の `comprehension.iter` が同 `Call`
3. **ビュー形**: `<x>.signal_map().keys()` / `.items()` / `.values()`
4. **浅い変数追跡**: `signal_map` を名前に含む変数（`Name.id` に部分一致）への 1–3 と同形の適用

- 4 は意図的にヒューリスティック（データフロー解析はしない）。**false positive は allowlist で吸収**し、false negative は下段の既存挙動テスト（`test_signal_map_enumeration_does_not_mint` ほか `test_resolver.py:269-353` 群・`test_session_signal_map.py`）が実測で防ぐ — 上段「src/ に書いた瞬間 CI が落ちる」・下段「仕様が壊れたら落ちる」の二層。
- 違反メッセージは修正先を指す（theme_guard `:128-132` の先例）: 「全列列挙は禁止（列挙は物理キーのみ返る）。列数は `total_column_count()`／列名は `column_names_of()`／存在確認は `has_column()` を使う」。
- 初期 allowlist は空を目標とする。`src/` に正当な列挙（物理キー列挙として意図的に使う箇所）が実在した場合のみ、行内容つきで登録し理由を書く。

## 5. `_evict_resolved` の lock 外解放（§12-2）

`signal_group_manager.py:590-619` の evict ループを `_evict_oldest`（`channel_cache.py:338-355`）と同型に変える:

- lock 内では `self._resolved_order` / `_resolved_by_key` から**参照を외し、evicted リストへ退避するだけ**。
- `_resolved_lock` を出た後に評価リストを手放す（`del evicted` — 最後の参照の死＝実体解放が lock の外で走る）。
- 呼び出し元 2 箇所（`resolve()` 後・`set_pinned_columns()`）のどちらも同じ経路を通るため、`_evict_resolved` 自身が「lock 内で外し・戻り値で持ち出す」形にし、**呼び出し側が lock を出てから捨てる**設計にする（`_evict_oldest` の「返り値を捨ててはならない」docstring 契約と同文の WHY を書く）。

## 6. docs 正誤

CLAUDE.md 遅延ロード行と `docs/roadmap.md` E-4b 段落の「E-4a からの `CacheKey` `id(handle)`・鋳造列 LRU 本数縛りは E-4c へ継続」を訂正:

- `CacheKey` → **E-4b で serial 化済み**（spec §5.7-1・`test_handle_serial.py`）と記載。
- 鋳造列 LRU 本数縛り → E-4c で **defer 裁定**（§2 の理由つき）へ更新。

## 7. テスト戦略

親 spec §8 の教訓（sabotage 必須・到達範囲は主張でなく実測）と、E-4b で収斂した盲目生成源 4 型（フェイク過剰忠実・サイズ盲目・ランタイム偶然・中間リンク未固定）を各テストで点検する。

### 7.1 衝突診断

- 衝突 fixture: 既存オラクル（`test_column_roundtrip.py:293-336` — `{**expanded, **physical}` で shadow を符号化済み）と同じ `Mat`/`Mat[0]` 共存 mf4 を生成（`mdf_authoring_2d_and_value2text_traps` の作法: 2-D は uint8 byte-array・検証は `Session.load` 経由）。
- 正 assert: info 診断ちょうど 1 件・`level == "info"`・`signal_name == "Mat[0]"`・message に親名と列位置。
- 負 assert（**現状どのテストも持たない到達不能性そのもの**を同時に閉じる）: 配列側リーフが列キーで引けないこと＝`resolve` が実チャンネルを返すこと・`total_column_count` との整合。
- 0 件 assert: 非衝突ファイル（通常 fixture）で本診断が 1 件も出ない。範囲外リーフ名（`Mat[7]` が 2 列配列と共存）でも 0 件。
- 多段: `W[0][1]` 形の衝突でも検出（LD-14 名との整合）。
- **sabotage**: 判定関数を恒偽化（常に None）→ 正 assert が RED。恒真化 → 0 件 assert が RED。predicted vs measured を記録。

### 7.2 AST ガード

- sabotage は layer_c contract の N4 手法と同型: 一時違反ファイルを `src/valisync/` に置き、**offenders のファイル名特定つき RED** → 削除・クリーン確認。検出形 1–4 それぞれで 1 回ずつ（`dict(直結)`・`for in`・`.items()`・変数経由）。
- allowlist 陳腐化 assert 常設（theme_guard `:133-134` 同型）。
- 下段（既存挙動テスト）は無改変 — 二層が独立オラクルであることを保つ。

### 7.3 §12-2

- 既存 `test_dropped_arrays_are_freed_outside_the_lock`（`test_channel_cache.py:462-481`）の観測手法（解放時に lock 保持状態を記録する ndarray/オブジェクト）を `_resolved_lock` へ移植。evict される鋳造列 Signal の実体配列に観測子を仕込み、`observed == [False]` を assert。
- **sabotage**: lock 内解放へ戻す → RED。`resolve()` 経路と `set_pinned_columns()` 経路の両方で検証（片方だけの被覆は E-4a の同テストが踏んだ轍 `:473-477`）。

### 7.4 ゲート

フルスイート＋4 ゲート（serial）。realgui は不要見込み（GUI 挙動不変 — 診断ドックへの info 追加は既存 plumbing の既検証経路）。凍結カタログはピクセル不変が期待値（衝突 fixture はカタログ状態に含まれない）— merge 前の①点検は `/gui-verify` の判断に従う。

## 8. 受け入れ基準

| # | 項目 | 基準 |
|---|---|---|
| G1 | 衝突診断 | `Mat`/`Mat[0]` 共存ロードで info ちょうど 1 件・非衝突/範囲外で 0 件・多段名でも検出 |
| G2 | 到達不能性の負 assert | shadow されたリーフが列キーで引けないことを直接 assert するテストが常設される |
| G3 | AST ガード | 検出形 1–4 の一時違反ファイルが offenders 特定つき RED・クリーン tree で GREEN・allowlist 陳腐化 assert 常設 |
| G4 | §12-2 | `_evict_resolved` の解放が `_resolved_lock` 外（観測子 assert）・両呼び出し経路・sabotage RED |
| G5 | 規則の単一実装 | 最長一致規則の実装が 1 箇所（**検出と解決**が同一実装を参照）— grep で二重実装なし。**`has_column`（`signal_group_manager.py:747-756`）は対象外**: `test_column_roundtrip.py:611-616` が「2 つは別実装で連動しない」独立オラクルとして明文で保護しており、畳むとテストの歯が抜ける |
| G6 | docs 正誤 | CLAUDE.md/roadmap の CacheKey 行が「E-4b で serial 化済み」に是正 |
| G7 | 無回帰 | フルスイート・4 ゲート clean・既存挙動テスト（下段）無改変 |

## 9. 実装アンカー（棚卸し確定・2026-08-04 時点）

- 衝突 2 レジーム: loud-fail = `mdf_loader.py:447-474`／最長一致 = `column_names.py:245-251`・`signal_group_manager.py:775-794`（`_owning_channel`）・`:829-839`（`_mint_column`）・resolve の物理キー先行 = `:410-412`
- 既存 test-lock: `test_loader_inversion.py:228-273`（loud-fail）・`test_column_roundtrip.py:489-501`（実チャンネル優先）・`test_column_names.py:131-138`・`test_reference_overlay.py:455-459`
- 診断 plumbing: `load_result.py:16-43` → `session.py:234` → `main_window.py:696-713`（`n_info` 分岐）→ `diagnostics_vm.py:36-52`
- AST 前例: `tests/gui/test_theme_guard.py`（ratchet・陳腐化 assert `:133-134`）・`tests/gui/test_realgui_layer_c_contract.py`（ImportFrom 出所 `:70-81`・一時違反ファイル sabotage）
- 挙動テスト下段: `test_resolver.py:269-353`・`test_session_signal_map.py`
- 非鋳造 introspection（違反メッセージの誘導先）: `total_column_count`（`signal_group_manager.py:704-716`）・`column_names_of`・`has_column`・`channel_leaf_count`
- §12-2 対象: `signal_group_manager.py:590-619`（`_evict_resolved`）・呼び出し元 `:434-441`／`:504-507`・同型修正の手本 `channel_cache.py:338-355`（`_evict_oldest`）・観測手法 `test_channel_cache.py:462-481`
