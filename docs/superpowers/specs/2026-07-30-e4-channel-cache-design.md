# E-4: チャンネル単位サンプルキャッシュとリソース会計の整理 — 設計

> **位置づけ**: [列展開の遅延化設計（増分E）](2026-07-24-deferred-column-expansion-design.md) の最終増分。
> E-3（反転・PR #151）が**オブジェクト数**を根治した（264,004 → 4,324）のに対し、本増分は
> **列読みの対話コスト**と**リソース会計**を扱う。
>
> **改訂履歴（v2）**: 初版に敵対的レビュー（7 レンズ × 独立検証・83 エージェント）を実施し
> **判定 NEEDS-CHANGES**。**Critical 3・Important 9・Minor 12** を反映し、**REFUTED 16 件**を
> §12 に記録した。主な反転: ①位置スライスの**所有権不変条件**が抜けており view が焼き付いて
> 予算・会計・「pin 不要」の根拠が同時に崩れる ②キャッシュの**キー空間が未規定**で自然な
> 選択がいずれも別チャンネルを返す ③列ブロック化は**入口が `list[Signal]` のままではメモリを
> 上限化しない**（テストは全部緑で通る）④広幅チャンネルの dtype 見積が **7.3× 誤り**
> （float64 96 MB ではなく uint8 13.2 MB）⑤**3 つの独立増分へ分割**（読み → 書きの順は必須制約）。

## 1. なぜ今やるのか（E-3 出荷時の実測）

E-3 は目標を全て達成した（`prod_demo.mf4` 1,297 MB・実 GUI）:

| 指標 | eager | E-3 後 |
|---|---|---|
| Signal オブジェクト | 264,004 | **4,324** |
| ヘッドレス core 常駐 RSS | 590 MB | **297 MB** |
| USS（主指標） | +281 MiB | **+15 MB** |
| 実 GUI ロード | 13.1 s | **2.40 s** |
| GUI 定常 RSS | 868 MB | **550 MB** |

**しかし対話コストは 1 ミリ秒も動いていない。** `LazyMdfValues.array()` は列ごとに
「全チャンネル `select` ＋ 全リーフ `_flatten`」をやり直すままで、E-3 はオブジェクト数を
変えただけだからである。T9 の実測: **309–327 ms/列**（最悪 = 1,100 列の広幅チャンネル）・
**5 列で 1,584 ms** — 目標 448 ms の **3.5 倍**。この数値は E-3 spec が目標設定に使った
参照帯（333–386 ms/列）に収まる＝**目標設定の根拠が追認された**。

E-3 は**この経路の重要性を上げた**: 1024 ガード退役で広幅 60 チャンネルが初めて使えるように
なり、レーダー物体リストの兄弟列比較（`Radar.ObjList.dx[0..k]`）はまさにこの形である。

持ち越した会計上の負債が 2 つ: **`_selected` が 330,004 キーで +58 MB**、
**`_resolved_by_key` に上限が無い**（決定 C-g で E-4 へ送った）。

## 2. ユーザー決定

| # | 論点 | 決定 |
|---|---|---|
| U1 | 複数列をどう追加するか | **両方する** — まとめても、1 列ずつ探索もする |
| U2 | 持続キャッシュの形 | **バイト上限つき LRU**（時間に依らない方がテストが単純） |
| U3 | キャッシュ合計の追加メモリ予算 | **256 MB** |
| U4 | 「すべて選択 → エクスポート」の OOM | **ストリーム化する** |
| U5 | 列数の次元 | **列方向もチャンクして上限なし** |
| **D1** | エクスポートの境界 API 変更（`list[Signal]` → keys ＋ 解決器） | **変える**（src/ の構造変更として事前承認済み。これ無しでは U4/U5 を実現できない） |
| **D2** | キャンセルの意味論 | **協調キャンセルのみ**。実行中の `select` は中断できないので、既知の Minor「ハングしたエクスポートが全 unload をブロック」は**本増分では解消しない**（別 follow-up。§4.5 で明記） |

**U1 からの帰結（簡略化）**: バースト層は不要。上限つき LRU 1 つが両方を兼ねる。

## 3. コントローラ決定（レビューの未解決 D3-D7）

| # | 論点 | 決定と理由 |
|---|---|---|
| D3 | エクスポートの作業予算は U3 の 256 MB と同一か別枠か | **同一**。別枠にすると「作業列 ＋ 2-D キャッシュ ＋ in-flight デコード」が同時に立ちピークが予算の約 2 倍になる。同一なら LRU がエクスポート中にチャンネル配列を退避して席を空ける＝**§3.2 が選んだ「裁定者は 1 人」がそのまま効く**。ブロックサイズ N は「予算 − 現在の pin 済み」から動的に決める |
| D4 | `_resolved_by_key` の正典契約（同一キー → 同一オブジェクト） | **「pin 中のみ保証」へ supersede**。evict を入れる以上ほかに無い。`test_resolver.py` の test-lock 更新と docstring 7 サイトの更新を同一タスクに含め、**意図的 supersede として記録**する |
| D5 | ディスク増幅（多段マージで出力の 2〜3 倍） | **開始前に `shutil.disk_usage` で検査して拒否**。見積（列数 × 行数 × 平均セル長 × 3）が temp ボリュームの空きを超えたら開始しない。ENOSPC に任せると数十分後に失敗する |
| D6 | ①gate で予算超 evict をどう起こすか | **予算を注入して小さくする**。実データで広幅 20 本超に触るのは decode だけで 6.4 s かかり realgui のランタイムを圧迫する。注入は `TeardownService(byte_budget=…)` の先例と同型 |
| D7 | oversize エントリ（1 エントリ > 予算） | **キャッシュしない**（入れると他を全部落として自分も次で落ちるので無意味）。ただし静かに遅いままにするのは罠なので **introspection で観測可能にする**（`cache.skipped_oversize` カウンタ） |

## 4. 増分の分割（レビュー勧告・採用）

**6 本立てを 3 つに割る。読み経路 → 書き経路の順序は必須制約である。**

| | 内容 | 主な影響面 |
|---|---|---|
| **E-4a**（本 spec の主対象） | `ChannelSampleCache`（キー空間・所有権不変条件・スレッド契約）＋ pin/evict ＋ 位置ベース selector ＋ teardown 会計 | `core/models/sample_source.py`・`core/loaders/signal_group_manager.py`・`core/loaders/column_names.py` |
| **E-4b** | 境界 API 変更（D1）＋ 行ストリーム ＋ 列ブロック ＋ 多段マージ ＋ union/searchsorted ＋ 協調キャンセル ＋ `_selected` 圧縮 ＋ byte-identical ゴールデン | `core/export/csv_exporter.py`・`gui/views/export_csv_dialog.py`・`gui/workers/export_worker.py` |
| **E-4c** | 衝突診断 ＋ AST 構造ガード | 独立。どちらにも相乗り可 |

**順序が必須な理由**: E-4b を先に出すと、U4「ストリーム化で OOM を解消」が `_resolved_by_key` の
恒久滞留で**実際には解消しないまま出荷される**。逆に E-4a があれば `_checked_keys()` が
（行, 列）順＝物理チャンネル連続なので select は ~4,324 回で済む。

**E-4a を割ってはならない**: 「キャッシュ」と「pin/evict」を分けると `_resolved_by_key` が
無制限のまま残り、**1 つの予算に裁定者が 2 人**いる状態＝§5.2 が明示的に不採用にした形になる。

**b の受け入れ条件は a の完了に依存する**（b のブロック解放は a の evict が効いて初めて
バイトが返る）。これをプランに明記すること。

## 5. E-4a: 読み経路

### 5.1 3 つのキャッシュ、3 つの扱い

| | 中身 | prod 実測 | 扱い |
|---|---|---|---|
| **`ChannelSampleCache`**（新設） | デコード済み 2-D 配列 | 広幅 1 本 **13.2 MB**（12000×1100 **uint8**） | **バイト上限 LRU・自由に evict** |
| `_resolved_by_key` | 鋳造した列 Signal | 1 列 ~96 KB（float64 実体化後） | **参照中は pin・それ以外を evict** |
| `_selected`（エクスポート） | ユーザーの選択キー集合 | 330k キー = 58 MB | **キャッシュではない → 圧縮**（E-4b） |

> **dtype 訂正（レビュー I1・重要）**: 初版は広幅 1 本を「12000×1000 float64 = 96 MB」と
> 書いたが、prod の広幅配列は **uint8** で **13.2 MB**（7.3× の誤り）。
> **帰結**: 256 MB には広幅が **~19 本**入るので、①gate は実データでは evict を
> ほぼ発火させられない → D6（予算注入）が必要。予算配分の説明も書き直した。

### 5.2 なぜ扱いが分かれるか

**`_selected` は evict できない** — ユーザーの意図そのものであり、捨てれば選択が消える。
上限ではなく**表現**を変える（行レンジ集合）。

**`ChannelSampleCache` は pin 不要** — ただし**§5.4 の所有権不変条件が成り立つ場合に限る**。
列 Signal が鋳造された時点でその列の 1-D 配列は `LazyMdfValues._cache` が保持するので、
2-D 配列は次の列を作るためだけに要る。

**`_resolved_by_key` は pin 必須** — `GraphPanelVM.render_data` は再描画のたびに
`_signal_map()` を引き直す（レンダーキャッシュのキーに x 範囲・パネル幅・可視キーが入るので
ズーム/パンで必ずミスする）。プロット中の列が evict されると**再描画ごとに 316 ms 停止**する。

### 5.3 キー空間（レビュー C2）

**キーは `(handle, group_index, channel_index)`。名前はキーに使わない。**

- 生名は LD-08 重複で一意でない（`mdf_loader.py` の `deduplicated = name_total[base_name] > 1`）。
  既存 fixture `Mat2`（生名共有・幅 3 と 4・selector 文字列まで一致）がその形。
- 表示名はファイル間で一意でない。`Session` が 1 キャッシュを全ファイルで共有するので
  **handle をキーに含めないと 2 ファイル比較で同じ曲線が 2 本描かれる**（長さが同じなら
  `sample_source.py` の長さ検証も通り、例外は出ない）。

**テスト**: 「生名が同一で `(gi, ci)` が異なる 2 チャンネル」（既存 `Mat2`）と「同一
`(name, gi, ci)` を持つ値の異なる 2 ファイル」の両方で、片方を読んだ後にもう片方が
**別値**であることを assert。sabotage: キーから handle / gi / ci を外すと RED。

### 5.4 所有権の不変条件（レビュー C1・**この増分で最も壊しやすい点**）

**命中パスは必ず基底を持たない独立配列を返す。**

```python
out = np.ascontiguousarray(apply_path(cached, path))
if out.base is not None:
    out = out.copy()
```

**なぜ必要か**: `_freeze`（`sample_source.py`）は `frozen = array.copy() if array.flags.writeable
else array` で **read-only 入力を素通しする**（docstring が機能として明記）。現行の miss
パスが安全なのは `_flatten` の `np.ascontiguousarray(arr[:, i])` が非連続スライスを必ず
実コピーするからであって、`_freeze` が守っているからではない。

共有キャッシュを（リポジトリの凍結規約どおり）read-only で保持すると、命中パスの
`cached[..., pos]` は writeable=False の **view** になり `_freeze` を素通りして `_cache` に
焼き付く。すると:

1. LRU が evict しても列 Signal が `base` 経由で 2-D 全体を保持し、**RSS は 1 バイトも
   下がらない** — §5.2 の「evict のコストは将来の初回読みだけ」と §9 の RSS 天井が同時に偽になる
2. `nbytes_if_materialized` は view 自身の nbytes を返すので `_retained_bytes` が実体の
   1/1000 を計上し、**64 MiB のバイト軸が黙って死ぬ**（§5.6 が防ごうとした同期解放が復活）
3. §10 の「位置スライスと名前引きの**値一致**」テストは**view でも通る**ので両軸とも構造的に盲目

**テスト（必須）**: 鋳造列に対し `sig._values_source.array_if_materialized().base is None` と
`_retained_bytes(sig, set()) == values.nbytes + timestamps.nbytes` を test-lock し、
**copy を外すと両方 RED になることを実測で示す**。

### 5.5 pin の供給機構（レビュー I9）

**`weakref.WeakValueDictionary` は使えない** — VM は `signal_key: str` しか保持せず
Signal オブジェクトを持たないので、弱参照にすると何も pin されず毎回再鋳造＝フルチャンネル
再読みになる（既知の Critical の再発）。

したがって **pin 集合を明示的に供給する**。供給元は `GraphAreaVM`（全タブ × 全パネルの
plotted entries）で、`AppViewModel` 経由で `Session` へ「今 pin すべきキー集合」を渡す。
core が GUI の状態を直接見に行くのではなく、**GUI が push する**形にして依存の向きを保つ。

- **pin 対象**: 全タブ・全パネルの plotted entries（アクティブパネルだけでは不足 —
  2 タブ目の列が evict されるとタブを戻した最初の再描画で 316 ms/列 停止する）
- **evict 可**: ブラウザのプレビューで一度覗いた列・エクスポートで読んだ列
- **予算超過時**: pin は**拒否しない**（拒否すると再描画ごと 316 ms 停止が復活する）。
  LRU の最低容量（1 物理チャンネル分）を無条件に確保し、超過分は「予算外」として
  introspection に出す

### 5.6 位置ベース selector（レビュー I2）

**位置は整数序数では表現できない** — 構造化 × 配列の入れ子（`Name.field[i]` / `Name[i][j]`）が
あるため、**パス**（フィールド名と添字の列）で表す。

**列挙空間を明示する**: `leaf_names` は**数値リーフのみ**を返すが `_flatten` は全リーフを
返す。パスは **`_flatten` と同じ全リーフ空間**で定義し、数値判定は別に持つ
（混在構造 `Q`(x: f8, tag: S2) で両者がずれる）。

**名前は永続キーのまま保つ**（LD-14 リーフ名は永続キー）。位置はロードごとに導出し保存しない。
`SampleReadError` の文言と診断が**名前を失わない**こと。

### 5.7 teardown 会計（レビュー I3）

**`columns=` にそのまま相乗りできない** — `enqueue(key, group, columns=())` の `columns` は
`tuple[Signal, ...]` だが、キャッシュが持つのは**生 ndarray** である。

`RemovalResult` に **`cached_arrays: tuple[np.ndarray, ...]`** を足し、`TeardownService` が
`Signal` と ndarray の両方を受けられるようにする（`_retained_bytes` は既に id() dedup を
持つので、ndarray を直接数える分岐を足すだけで済む）。

**close との順序**: `MdfHandle.close()` でキャッシュを落とすと teardown へ渡す前に消える。
**close の前に `remove_group` が回収する**順序を明記する。

**LRU の evict は unload と違いペーシングを通らない**。1 エントリ 13.2 MB なので同期解放の
実測は 1 ms 未満と見込まれるが、**実測して spec の数値を確定する**（E-3 T9 が「最大単発解放
5.8 ms が構造的な床」を実測した先例に倣う）。（T4 実測: 最大 0.364 ms / 中央値 0.042 ms・
1 エントリ 13.2 MB・20 回）

### 5.8 スレッド契約（レビュー I6）

E-3 は「**キャッシュヒットは `handle.lock` を取らない**」を test-lock している。これを壊さない。

- `handle.lock` は**ファイル単位**だが、予算は**プロセス単位**である。予算の増減は
  キャッシュ自身の小さな lock で保護する（`MdfHandle._close_lock` と同型・読み直列化 lock とは別物）
- エクスポートは別スレッド（`QRunnable`）で走る。**エクスポートが予算を食い尽くして
  プロットのキャッシュを追い出さない**よう、pin 済み分は §5.5 の規則で守られる

## 6. E-4b: 書き経路（概要・詳細は E-4a 完了後に別 spec）

**メモリを食う箇所は 4 つある**（初版は 2 つと書いた・レビュー C3）:

1. 全信号の同時実体化（`views = [s.sorted_view() ...]`）
2. CSV テキストの `list[str]`（＋ `_atomic_write` の `"\n".join` 全文コピー）
3. **`_on_accept` の全列鋳造と `ExportRequest.signals` の強参照**
4. **`_require_single_value_columns` の全列 `.values` 読み**（行を 1 行も書く前に走る）

**③④があるため、列ブロック化だけではピークは列数に比例したまま**であり、
§10 のテスト（byte-identical・FD 上限・temp が残らない）は**全部緑で通る**。

したがって **D1（境界 API 変更）が前提**: `ExportRequest` / `Session.export_csv` /
`CsvExporter.export` の入力を `keys: tuple[str, ...]` ＋ 解決器へ変え、列ブロックの内側で
mint → 読み → **参照を落とす**。`Session._reject_container_channels` は既に
`column_names_of` ベースで値を読まないので keys のまま成立する。

その他 E-4b の確定事項:
- **union は identity dedup が要る**（`np.concatenate` は identity を見ない・レビュー I4）
- **`np.searchsorted` 置換は完全一致セマンティクスを保つ**（既存 test-lock が
  `"1.0,,21.0"` と末尾越えを固定済みで、ガード無し実装は即 RED）
- **byte-identical ゴールデンは現在存在しない**（レビュー I8）。既存テストは行末・末尾改行・
  列順に構造的に盲目なので、**先にゴールデンを作る**
- **受け入れは RSS でなく**「同時生存 Signal 数がブロックサイズに閉じている」（鋳造/読み
  カウンタ）と「ブロック k と k+120 の USS 差が ±20% 以内（スケール不変性）」で測る

## 7. E-4c: 衝突診断と構造ガード

**衝突診断**: `Mat[0]` 衝突（2-D `Mat` の第 0 列と実在する 1-D `Mat[0]`）は最長一致で実チャンネルが
勝つ規則が E-3 で入り T0 が test-lock しているが、**info 診断が出ていない**。配列側の当該列が
**到達不能になる**ことをユーザーが知る手段が無いので 1 件追加する。

**AST 構造ガード**: `dict(signal_map())` への防御は現在**挙動テスト**なので、将来 `src/` に
書かれてもコンパイルは通り**容器のみの map が黙って得られる**。`tests/gui/test_theme_guard.py`
（ratchet allowlist つき AST ガード）と同型のガードを足す。

## 8. E-4a のテスト方針

| 系統 | 何を押さえるか |
|---|---|
| **所有権（C1）** | 鋳造列の `array_if_materialized().base is None`／`_retained_bytes` が実体と一致。**copy を外すと両方 RED** |
| **キー空間（C2）** | 生名共有 2 チャンネル（`Mat2`）と 2 ファイル同一 `(name, gi, ci)` で**別値**。キーから handle/gi/ci を外すと RED |
| **LRU / pin** | pin 済みは残る・予算超で古い順に落ちる・pin 拒否は起きない・oversize は載らず `skipped_oversize` が増える |
| **位置 selector** | パスと名前引きの**値一致**（全リーフ空間・混在構造 `Q` を含む）／`SampleReadError` が名前を失わない |
| **会計** | 2-D 配列が teardown の三軸ペーシングを通る（`cached_arrays` 経由）／close 前に回収される順序 |
| **スレッド** | キャッシュヒットが `handle.lock` を取らない（E-3 の test-lock を壊さない）／予算の増減が競合しない |
| **①gate（realgui）** | まとめて 5 列追加 → **select 回数 == 1・`_flatten` 回数 == 1**／探索的に 1 列ずつ → 2 本目以降がヒット／**予算を注入して**古いチャンネルが落ちることを実測 |

**このリポジトリ系列の教訓を適用する**: 増分B〜E-3 で「実装が効いていることを証明できない
テスト」を実測で 8 件以上摘出した（構造的に空虚な sabotage・到達範囲の主張が誤っていた
sabotage 3 件・**プランの例示コードが自ら実装すると称した決定を一度も満たしていなかった
2 件**・別の例外が先に `pytest.raises` を満たして偶然緑だったテスト・反転で恒真化した
オラクル・「0 ms」を刷って合格する計測）。**各タスクの sabotage は必須**とし、到達範囲は
主張でなく実測で確かめる。

**observability を先に作る**: 「select 回数」を数える口は現在無い。E-3 が `mint_count` /
`resolved_keys()` を非鋳造 introspection として足した先例に倣い、`ChannelSampleCache` に
`hits` / `misses` / `evictions` / `skipped_oversize` / `bytes_held` を持たせる。

## 9. E-4a の出口（受け入れ）

| 項目 | 現在 | 目標 |
|---|---|---|
| 同一広幅チャンネルの隣接 5 列 | 1,584 ms | **≤ 380 ms** |
| 同上の `select` 呼び出し回数 | 5 | **1** |
| 同上の `_flatten` 呼び出し回数 | 5 | **1** |
| 鋳造列の `values.base` | （該当なし） | **`None`**（C1） |
| キャッシュ飽和後の USS | — | **ベース +256 MB 以内** |
| LRU evict 1 回の同期解放時間 | — | **実測 0.364 ms**（最大・20 回・1 エントリ 13.2 MB） |

`--core` モード（E-3 T9 新設）と実 GUI の両方で測る。**主指標は USS**。

`column_read_latency`（計測器）は**未鋳造の列を選ぶ実装**なので、キャッシュが入ると
「未鋳造 ≠ キャッシュが冷たい」の乖離が生まれる。**E-4a で計測器側も直す**（レビュー M5）。

## 10. 非スコープ

- **mmap フロアの削減**（~205 MiB）— 別 follow-up
- **MDF3 が開けない欠陥** — ユーザーが MDF3 ファイルを持たないため据え置き
- **PC-19 リッチツールチップの復活** — `has_column` 以上のものは作らない。なお
  「PC-19 復活で hover ごとに 316 ms」はレビューで **REFUTED**（`_mint_column` は Signal を
  作るだけでデコードせず、`tooltip_for` は metadata と `len(timestamps)` しか触らない）
- **真のハングしたエクスポートの中断**（D2 により本増分では解消しない）— 別 follow-up
- **GUI 側の未帰属メモリ**（E-3 T9 が GUI USS +87 MB のうち ~48 MB を未帰属と記録）

## 11. 保存すべき契約（違反＝サイレント破壊）

- **`handle.lock` はキャッシュヒットで取らない**（E-3 の test-lock）
- **`_closed` は読み直列化 lock の外で立てる**（固定ユーザー決定）
- **teardown の三軸ペーシング**（64 MiB / 8,000 信号 / 8 ms・クロックは 32 信号ごと）と
  identity dedup 会計
- **records↔signals の 1:1**（誤データ経路の唯一の防波堤）
- **LD-14 リーフ名は永続キー** — 変更は全保存の無言リネーム
- **`_resolved_by_key` の「同一キー → 同一オブジェクト」は D4 で「pin 中のみ」へ supersede**
  （意図的・test-lock 更新を伴う）

## 12. REFUTED になった指摘（記録・同じ議論を繰り返さないため）

敵対的レビューの検証段で落ちた主要なもの:

1. 「予算配分が U4 で破綻し LRU 容量 0 → 5.8 時間」— §5.2 が「エクスポートで読んだ列は
   evict 可」と明記済み。`_checked_keys()` は（行, 列）順＝物理チャンネル連続なので
   LRU 1 スロットでほぼ 100% ヒットする
2. 「prod は 263 ブロック > 200 で 1 パスにならない」— 2-D は float64 でなく uint8。
   貪欲パッキングで 43〜119 ブロック
3. 「pin 対象の列挙漏れ 4 件」— `SignalPreviewVM._signal` はメソッドで保持は `str` のみ、
   `reference_overlay` の candidate はループローカル、`RenderCurve` は ndarray のみ
   （docstring が「no Session or Signal objects cross this boundary」と明記）
4. 「`_resolved_by_key` を `WeakValueDictionary` に」— VM は `str` しか持たないので
   何も pin されず毎回再鋳造になる（→ §5.5）
5. 「searchsorted 置換で Req 7.4 違反」— 既存 test-lock が即 RED にする
6. 「`columns=` に生 ndarray を入れると `_drain` が AttributeError」— mypy が先に落とす。
   かつ `_pending_signals -= 1` は会計より前に置く設計で乖離しない
7. 「close 後のキャッシュ配列が mmap を alias して 0xC0000005」— asammdf の select は
   新規確保した bytes を base に持ち mmap を alias しない
8. 「hils の広幅チャンネルは 1 エントリ 3.96 GB」— hils の最広は `ObjMatrix`（2.88 MB）。
   1,100 列は prod にしか無い
9. 「位置化は `_flatten` と `column_names` の唯一の実行時整合チェックを削除する」—
   挙げられた乖離トリガは現行の名前引きに対しても免疫で、実 mf4 2 本の独立オラクルが既にある
10. 「容器 Signal の二重保持が単一裁定者を壊す」— 3 サイトが全て `is_container_channel` で
    塞いでおり production から到達不能
