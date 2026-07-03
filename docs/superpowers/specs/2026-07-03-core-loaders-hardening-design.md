# 設計 spec: core-loaders-hardening 第1弾（TS 堅牢化 — LD-03/04/05/06/08/09）

ローダー堅牢性の第1弾。実車ログ特有の異常データ（非単調/重複タイムスタンプ・nan/inf・重複名・空データ）を**「弾く」から「記録どおり受け入れて診断で透明化」へ転換**し、サイレントなデータ欠損を根治する。診断の受け皿は gui-feedback-errors で整備済みの Diagnostics ドック（PR #37/#38）。

- **作成**: 2026-07-03
- **ステータス**: 設計承認済み（実装プラン未作成）
- **一次情報源の課題**: [docs/audit-findings-catalog.md](../../audit-findings-catalog.md) の **LD-03/04/05/06/08/09**
- **関連**: FB 第1弾 spec（診断の器）[2026-07-02-gui-feedback-errors-design.md](2026-07-02-gui-feedback-errors-design.md)・FB 第2弾 spec [2026-07-03-gui-feedback-errors-r2-design.md](2026-07-03-gui-feedback-errors-r2-design.md)

---

## 1. 目的とゴール

現状、`Signal.__post_init__` が厳密単調（`diff > 0`）を強制し、MDF4 は非単調 ch を丸ごと skip・CSV は1列の乱れでファイル全体が失敗する。CAN/イベント駆動ログでは重複・逆転は日常的であり、主要ツール（asammdf・MATLAB・Vector CANape・ETAS MDA）はいずれも**ロード時に拒否せず「記録どおり読んで演算時に整列」**する（ASAM MDF 規格は単調を要求するが実ファイルの違反は普通 — asammdf Issue #1110 等）。現行 valisync はどのツールより厳しい外れ値になっている。

**成功の判定（受け入れの方向性）**
- 非単調/重複タイムスタンプを含む MDF4/CSV が、データ改変なしで開ける（ch 消滅・ファイル全滅が起きない）。
- 補間・統計・LOD・描画は従来どおり正しく動く（単調前提の演算は整列ビュー経由）。
- 受け入れた異常（非単調・重複・nan/inf・重複名・空データ・0ch）が Diagnostics ドックに件数付きで残る。
- 既に単調なファイル（大半のケース）ではメモリ・速度のオーバーヘッドが実質ゼロ（zero-copy fast path）。

## 2. スコープ

**第1弾（本 spec）**: LD-03 / LD-04 / LD-05 / LD-06 / LD-08 / LD-09。

| ID | 課題（catalog より） | 対応の要点 |
|---|---|---|
| LD-03 | MDF4 の非単調/重複 ch が丸ごと skip | 受け入れ＋異常検出 warning（§4.2） |
| LD-04 | CSV は1列の乱れでファイル全体が失敗 | 同上・MDF4 と対称化（§4.2） |
| LD-05 | 0ch MDF4 が無言で「成功」 | 「0 チャンネル」warning（§4.3） |
| LD-06 | CSV の 'nan'/'inf' が無言採用 | 値として受け入れ＋件数 warning（§4.3） |
| LD-08 | CSV 同名ヘッダで重複 `Signal.name` | MDF4 と同じ連番曖昧化＋warning（§4.3） |
| LD-09 | ヘッダのみ CSV が空信号を無言生成 | 成功＋「データ行 0」warning（§4.3） |

**後続（同サブスペックの別弾）**: 第2弾=開く経路（LD-01 CSV ピッカー〔SH-01 と連携〕・LD-02 拡張子 .mdf/.dat）、第3弾=LD-07（enum ラベル＝モデル拡張）・LD-10（OOM 最適化）・LD-11（重複ロード検出）。

**非ゴール**
- 統計/補間側の NaN/Inf 防御（`analysis-correctness` AN-01 の責務 — 本弾は「NaN/Inf が入ったことを診断で見せる」まで）。
- 記録順（非整列）での描画モード（生データは保持するため将来追加可能 — §3 決定2の余地）。
- CSV フォーマットピッカー等の GUI 変更（本弾は GUI 入力経路に一切触れない）。

## 3. 確定済みの設計判断（brainstorming・ユーザー決定）

1. **LD-03/04 は「記録どおり保持」**: 生データを改変せず `Signal` に保持し、整列は演算側の責務とする（業界標準準拠）。ロード時の自動修復（データ書き換え）はしない。
2. **演算も描画も「整列ビュー」を使う**: core が1箇所で提供する遅延整列ビュー（安定ソート＋重複 keep-last・キャッシュ）を、単調前提の全消費経路（補間・統計時間窓・LOD・描画・export 等）が使う。既存 LOD/レンダパイプラインは実質無改修。生データが残るため「記録順表示モード」は将来の拡張余地。
3. **重複タイムスタンプの解決は keep-last**: CAN の「後に受信した値が現在値」意味論に整合（安定ソート前提で「記録順で最後の値」と定義）。
4. **増分は ①TS堅牢化 → ②開く経路 → ③その他** の順（catalog 推奨の②先行から変更・ユーザー決定）。

## 4. アーキテクチャとコンポーネント

### 4.1 `Signal` — 検証緩和と整列ビュー（core）

- **検証緩和**: `__post_init__` から厳密単調検証（`np.all(np.diff(...) > 0)`）を**撤廃**。維持するのは (a) timestamps/values の長さ一致、(b) **タイムスタンプの有限性**（NaN/Inf の時刻はソート意味論が壊れるため不変条件として残す — 非有限 ts を含む ch はローダーで per-ch skip＋error 診断。§4.2）。値（values）側の NaN/Inf は許容（欠測として正当・LD-06）。
- **整列ビュー**: `Signal.sorted_view() -> tuple[np.ndarray, np.ndarray]` を新設。
  - 意味論: `timestamps` を**安定 argsort**し、同一タイムスタンプは**記録順で最後**の値だけ残す（keep-last）。返す配列は厳密単調。
  - **zero-copy fast path**: 既に厳密単調（重複なし）の場合は生配列**そのもの**を返す（コピー・追加メモリなし — LD-10 を悪化させない）。
  - 遅延評価＋キャッシュ: 初回呼び出しで計算し `object.__setattr__` で保持（frozen dataclass）。冪等計算のため競合しても安全（GIL 下で最後の書き込みが勝つだけ）。
  - 補助 API: `is_monotonic: bool`（fast path 判定の公開・テスト/診断向け）。
- **消費経路の切替**: 単調前提で `signal.timestamps`/`signal.values` を読む全計算・描画経路を `sorted_view()` に切替える。対象（実装プランで全列挙する）: Interpolator・統計の時間窓切出し・Downsampler/LOD・sync/offset・formula engine・CSV export・カーソル読み取り・レンダデータ供給。表示専用のメタ情報（ch 数・名前等）は無関係。

### 4.2 ローダー — 「弾く」から「検出して診断」へ（LD-03/04）

- **MDF4**（mdf4_loader.py）: 現行の「`Signal` 構築で ValueError → warning 降格で ch skip」経路を廃止。非単調・重複はそのまま `Signal` 化し、**異常を検出したら warning 診断**を発行: 「`<ch>`: 非単調 N 箇所・重複タイムスタンプ M 点（表示/演算は整列ビューで補正）」。**非有限タイムスタンプ**を含む ch のみ従来どおり per-ch skip（error 級診断・受け入れ不能の唯一の残存ケース）。
- **CSV**（csv_loader.py）: タイムスタンプ列の非単調/重複で**ファイル全体を失敗させる経路を廃止**し、MDF4 と対称に受け入れ＋warning。非数値タイムスタンプ行は従来どおりファイル失敗（構文エラーは別問題）。CSV は全列が同一時間軸のため、診断はファイル単位で1件（「タイムスタンプ列: 非単調 N 箇所・重複 M 点」）。
- 検出は O(n) の `np.diff` 1回（ソートはしない — ソートコストは sorted_view の遅延評価に委ねる）。

### 4.3 ローダー — 品質診断の追加（LD-05/06/08/09）

- **LD-05**: MDF4 で `len(signals) == 0` のとき warning「チャンネルが 0 本です（全チャンネルが読み取り不能）」を diagnostics に追加（成功扱いは維持 — GUI は R2 の `no_channels` プレースホルダ＋Diagnostics ドックが受け皿）。
- **LD-06**: CSV の値パースで NaN/Inf を**受け入れた上で**列ごとに件数を集計し、warning「`<col>`: 非有限値 K 個（'nan'/'inf' 文字列由来）」。float() の挙動は変えない（'nan'→NaN・'inf'→Inf は業界標準・NaN は欠測表現として正当）。
- **LD-08**: CSV の同名ヘッダを MDF4 と同じ**連番方式**で曖昧化解消（`name[0]`・`name[1]`…）＋warning「重複ヘッダ `<name>` を連番で改名」。`Signal.name` の一意性がグループ内で保証される。
- **LD-09**: データ行が 0 行の CSV（ヘッダのみ）はロード成功＋warning「データ行が 0 行です」（長さ 0 の Signal 群を生成 — `SourceInfo.t_min/t_max=None`・ツールチップ「時間範囲: —」と整合）。

### 4.4 診断の文言方針

- すべて `Diagnostic(level="warning", message=..., signal_name=<ch生名 or None>)` で発行（`signal_name` は R2 までの慣行どおり loader の生名。namespaced 照合の follow-up は既知の ledger 項目）。
- 件数を必ず含める（「何がどれだけ」— 監査可能性）。修復・変換をした場合（LD-08 の改名）は前後を明記。

## 5. データフロー

```
Loader: 生データを無改変で Signal 化 ＋ 異常検出（O(n) diff）→ Diagnostic warnings
  → Session.load → LoadOutcome(key, diagnostics) → Diagnostics ドック（FB の器・既設）
Signal: 生配列（記録どおり）を保持
  → sorted_view()（遅延・安定ソート＋keep-last・単調なら zero-copy）
  → 補間・統計・LOD・描画・export 等の全単調前提経路
```

## 6. エラー処理・エッジケース

- **非有限タイムスタンプ**: MDF4 は per-ch skip＋error 診断。CSV はタイムスタンプ列に 'nan'/'inf' が来た場合も同様に受け入れ不能（現行の非数値 ts と同じファイル失敗経路に「非有限」を追加 — 時刻軸が壊れているため）。
- **全点同一タイムスタンプ**: keep-last で1点に縮退（warning の重複点数で可視）。長さ1の Signal として有効。
- **長さ 0/1 の Signal**: sorted_view は自明（fast path）。既存の 0 長対応（SourceInfo 等）と整合。
- **sorted_view のキャッシュ**: Signal は frozen＝配列は読み取り専用（既存の `__post_init__` が writeable を落とす）なのでキャッシュ無効化は不要。
- **後方互換**: `Signal.timestamps`/`values` の生アクセスは従来どおり（既存テストの大半は単調データのため fast path で挙動不変）。厳密単調を**前提にしていた**消費側は本弾で全て sorted_view へ切替え、プラン作成時に `timestamps` の全参照を監査して漏れゼロを保証する。
- **Derived 信号**（formula engine 出力）: 入力が sorted_view 経由なら出力は単調 — 生成側は不変。

## 7. テスト戦略（docs/gui-testing-layers.md 準拠）

- **Core 単体（Layer A・本弾の主戦場）**:
  - `sorted_view`: 安定性（同値タイムスタンプで記録順最後が残る）・単調出力・fast path が**生配列と同一オブジェクト**（`is` 比較 — id() ではなく参照保持。memory: `gui_id_reuse_flake_object_recreation`）・長さ 0/1・全点同一。
  - **property-based**（既存 `tests/test_pbt_*` の流儀）: 任意の非単調配列で sorted_view が厳密単調・keep-last 意味論・生データ不変。
  - ローダー: 非単調/重複 MDF4・CSV が成功＋診断件数一致・データ無改変。LD-05/06/08/09 の各診断。非有限 ts の skip/失敗経路。
  - 消費経路: 非単調 Signal を入力に補間・統計・downsampler が整列ビュー経由で正しい値を返す（単調入力時と同値になるケースで検証）。
- **Layer B**: 非単調ファイルのロード → Diagnostics ドックに warning 行が出る（FB の器との接続確認・既存パターン）。プロットが整列済みで描画される（render 経路の x 単調性 assert）。
- **Layer C（realgui）**: **GUI 入力経路の変更なし → 新規 realgui 不要**。merge 前 `/gui-verify` は「GUI 入力経路の変更なし → ゲート対象外」判定の確認＋headless full のみ。
- render 経由の検証は x_range 固定の教訓に従う（memory: `gui_offset_render_test_xrange_pitfall`）。

## 8. LD 項目 → 設計の対応

| ID | 対応 |
|---|---|
| LD-03 | §4.1 検証緩和＋§4.2 MDF4 受け入れ＋warning・§4.1 sorted_view |
| LD-04 | §4.2 CSV 対称化（ファイル全滅廃止） |
| LD-05 | §4.3 0ch warning |
| LD-06 | §4.3 非有限値の件数 warning（受け入れは維持） |
| LD-08 | §4.3 連番曖昧化＋warning |
| LD-09 | §4.3 データ行 0 warning |

## 9. トレーサビリティ

catalog の LD-03/04/05/06/08/09 を本 spec で満たす。LD-01/02（第2弾）・LD-07/10/11（第3弾）は同サブスペックの後続弾として brainstorming/writing-plans から。実装プランは `docs/superpowers/plans/2026-07-03-core-loaders-hardening.md` に作成予定。診断表示の器は FB 第1弾/第2弾（PR #37/#38）。統計側の NaN/Inf 防御は `analysis-correctness`（AN-01）へ。
