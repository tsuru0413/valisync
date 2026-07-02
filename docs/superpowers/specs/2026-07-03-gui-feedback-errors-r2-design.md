# 設計 spec: gui-feedback-errors 第2弾（FB-04/05/07/08/09/10）

エラー・診断・状態フィードバック可視化の第2弾。第1弾（FB-01/02/03/06・PR #37）が作った器（ステータスバー・Diagnostics ドック・`LoadOutcome` 伝播）の上に、ロード中の可視化/中断と「いま何を見ているか」の常設表示を積む。

- **作成**: 2026-07-03
- **ステータス**: 設計承認済み（brainstorming でモックアップ承認・実装プラン未作成）
- **一次情報源の課題**: [docs/audit-findings-catalog.md](../../audit-findings-catalog.md) の **FB-04/05/07/08/09/10**
- **第1弾 spec**: [2026-07-02-gui-feedback-errors-design.md](2026-07-02-gui-feedback-errors-design.md)
- **完成イメージ**: brainstorming で提示・承認された2モック（第2弾サーフェス全体像／FileBrowser・ChannelBrowser 詳細＝ヘッダ行・空状態3分類・ツールチップ・BusyOverlay）

---

## 1. 目的とゴール

**成功の判定（受け入れの方向性）**
- 重いロード中に「何を読み込んでいるか」が見え、キャンセルで UI が即時に応答を取り戻す（FB-04）。
- Channel Browser が「どのファイルの信号を・何件中何件表示しているか」を常設表示し、空のときは理由（未選択／検索0件／0ch）が分かる（FB-05/09）。
- ウィンドウタイトルにアクティブファイル名が出る（FB-07）。
- 初回起動で両 Browser が「次に何をすべきか」を案内する（FB-08）。
- File Browser の行ホバーでファイルの素性（パス/サイズ/時間範囲/ch数/形式）が確認できる（FB-10）。

## 2. スコープ

| ID | 課題（catalog より） | 対応の要点 |
|---|---|---|
| FB-04 | BusyOverlay がラベル/進捗/キャンセル無しの全画面ブロック | ラベル＋キャンセルボタン＋ハイブリッドキャンセル（§4.1） |
| FB-05 | 検索0件/未選択でリストが無言に空・件数表示なし | ヘッダ行の件数＋空状態3分類（§4.2） |
| FB-07 | ウィンドウタイトルが固定「ValiSync」 | 「<アクティブファイル名> — ValiSync」（§4.3） |
| FB-08 | 空状態ガイド皆無（両 Browser にプレースホルダ無し） | Browser×2 のプレースホルダ（§4.2/§4.4） |
| FB-09 | 表示中ファイルがビューに示されない | ChannelBrowser ヘッダ行にファイル名（FB-05 と統合・§4.2） |
| FB-10 | File Browser が basename のみ | ホバーツールチップ＋`Session.source_info` 新設（§4.5） |

**非ゴール（境界注記）**
- **グラフエリアの空状態ガイド**: 将来「D&D 時に表示オブジェクト（plot / table 等）を選択して切り替える」構想（`valisync-gui-views` 系）があり、グラフエリアの空状態の意味論はそこで変わる。本弾では触れず views 側へ委譲する。File/Channel Browser は初期から常設表示のアンカーとして本弾でガイドを担う（ユーザー確認済み）。
- ロード進捗のパーセント表示（進捗率の算出はローダー API 拡張が必要・キャンセルと分離可能なため見送り。バーは不確定のまま）。
- ツールチップへの診断件数表示（DiagnosticsVM への配線が増えるため YAGNI。catalog 文言の範囲に留める）。

## 3. 確定済みの設計判断（brainstorming）

1. **FB-04 はハイブリッドキャンセル**: ソフト（ボタン押下で UI 即時解放・結果破棄）＋ハード（ローダーの協調的チェックポイントで実停止）。core 公開 API 変更（`cancel` パラメータ）を含む — **ユーザー承認済み**。
2. **FB-08 の範囲は Browser×2**（グラフエリアは非ゴール・上記境界注記）。
3. **実行形態**: 実装は直列（subagent-driven-development）、**レビュー/検証を Workflow 多レンズ並列**にする（§7）。

## 4. アーキテクチャとコンポーネント

MVVM を維持し、Session を唯一のゲートウェイとする。ViewModel は Qt-free。

### 4.1 FB-04 — ハイブリッドキャンセル

**core（公開 API 変更・要承認事項＝承認済み）**
- `LoadCancelled(Exception)` を `valisync.core.session` に新設。
- `Session.load(path, format_def=None, cancel: Callable[[], bool] | None = None) -> LoadOutcome`。`cancel` はローダーへ透過。
- `Mdf4Loader.load(path, cancel=None)`: 現行の `raw = list(mdf.iter_channels(...))`（mdf4_loader.py:88・支配的コスト）を逐次ループに変え、**1チャンネルごと**に `cancel()` を確認 → True なら `LoadCancelled` を raise（グループ未登録のまま脱出）。変換ループ（同 :112）にも同チェック。
- `CsvLoader.load(path, fmt, cancel=None)`: 行パースループで **N 行ごと**（N=1000）に確認。
- 中断できない盲点は `MDF()` 構造パース（mdf4_loader.py:73）のみ — ソフト側が UI を守る。

**gui**
- `BusyOverlay`: ラベル（単一ロード「読み込み中: <basename>」／複数「N ファイルを読み込み中」）＋「キャンセル」`QPushButton` を追加。`cancel_requested = Signal()`。
- `LoadController`:
  - `submit(..., cancel_event: threading.Event | None = None)` を追加。**Event は呼び出し側（`main_window._load_file`）が生成**し、`lambda: session.load(target, None, cancel=event.is_set)` と `cancel_event=event` の両方を submit へ渡す。controller は event を保持し `cancel_active()` でセットする（所有は呼び出し側・セット権は controller）。
  - **アクティブ数カウント**を導入し、オーバーレイは全ロード終了まで表示（現行の「最初の完了で消える」潜在バグを修正）。ラベルはアクティブ数に追従。
  - `cancel_active()`: 全アクティブ worker の Event をセットし、**即時に** busy を隠して各 worker を「キャンセル済み世代」に記録。以降その worker の finished/failed は破棄する。
  - **手遅れ完走の巻き戻し**: キャンセル済み worker が `finished(outcome)` を返した場合（全チェックポイント通過後にキャンセルが届いたケース）、`session.remove_group(outcome.key, force=True)` で登録を取り消し、真に破棄する。
  - `failed` が `LoadCancelled` の場合は **cancelled 経路**: `on_error` を呼ばず（モーダル無し・Diagnostics 追記無し）、`LoadTask` には新設の `cancelled` 状態をセット、`on_cancelled` コールバック（任意）を呼ぶ。
- `MainWindow`: `busy_overlay.cancel_requested → _load_controller.cancel_active()` を配線し、cancelled 経路でステータスバーに「キャンセルしました: <basename>」。

### 4.2 FB-05＋FB-09 — ChannelBrowser ヘッダ行と空状態3分類（統合実装）

- `ChannelBrowserVM`（Qt-free）に追加:
  - `header_text() -> str`: 「<アクティブファイル basename> — 全 M ch 中 N 件表示」（M=ファイル全ch数、N=フィルタ通過数）。未選択時は「ファイル未選択」。
  - `empty_state() -> str`: `"none_selected" | "no_match" | "no_channels" | "has_rows"` の4値（`no_match` は現在のクエリ文字列を `filter_query()` で併せて公開）。
  - 既存の `"signals"` 通知に載せて View が再描画（新規通知タグは増やさない）。
- `ChannelBrowserView`:
  - 検索ボックス上にヘッダ `QLabel` 1本。
  - ツリーを `QStackedWidget` で「ツリー ⇄ プレースホルダ QLabel」に切替（第1弾 DiagnosticsView の空プレースホルダと同一パターン）。メッセージ:
    - `none_selected`: 「File Browser でファイルを選択すると信号一覧を表示します」（FB-08 の ChannelBrowser 側を兼ねる）
    - `no_match`: 「『<query>』に一致する信号はありません」
    - `no_channels`: 「このファイルに信号がありません（Diagnostics に詳細）」
  - **既存の検索・信号 D&D・右クリックメニューの入力経路は無変更**（realgui 実証済み経路を壊さない）。

### 4.3 FB-07 — ウィンドウタイトル

- `MainWindow` が `"active_file"`（および `"unloaded"`）通知を購読し `setWindowTitle`。書式: アクティブ有り「<basename> — ValiSync」／無し「ValiSync」。

### 4.4 FB-08 — FileBrowser プレースホルダ

- `FileBrowserView`: リストを `QStackedWidget` で「リスト ⇄ プレースホルダ」に切替。空時「ファイルが読み込まれていません／ウィンドウへファイルをドロップして追加」。判定は既存 `"files"` 通知で `vm.files` の空/非空。
- ChannelBrowser 側の空状態は §4.2 の `none_selected` が兼ねる。

### 4.5 FB-10 — File Browser ツールチップ

- **core（読み取り専用の公開 API 追加）**: `Session.source_info(key) -> SourceInfo`。`SourceInfo`（frozen dataclass）= `full_path: Path` / `size_bytes: int | None`（stat 失敗時 None）/ `t_min: float | None` / `t_max: float | None`（0ch 時 None）/ `n_channels: int` / `file_format: str`。実装は `SignalGroupManager` の group から算出（timestamps は sorted 済みのため各信号 `[0]`/`[-1]` の min/max・O(ch数)）。
- `FileBrowserVM.file_info(index) -> SourceInfo | None`＋ツールチップ整形 `tooltip_text(index) -> str | None`（純 Python）: フルパス／「サイズ: 48.2 MB」／「時間範囲: 0.000 – 312.450 s（312.5 s）」／「チャンネル: 214 ch ・ 形式: MDF4」の4行。size 不明時はサイズ行を省略（graceful degradation）。
- `FileListModel.data()` に `Qt.ToolTipRole` を追加し `vm.tooltip_text(row)` を返す。リスト行の表示（basename）は不変。

## 5. データフロー（FB-04 キャンセル）

```
[キャンセルボタン] → BusyOverlay.cancel_requested → LoadController.cancel_active()
   ├─ 即時: Event.set() 全 worker ＋ busy.hide() ＋ 世代をキャンセル済みに（ソフト）
   ├─ ローダー: 次のチャンネル/行境界で cancel() → LoadCancelled raise（ハード・未登録で脱出）
   │     → worker.failed(LoadCancelled) → controller: cancelled 経路（モーダル/診断なし・status のみ）
   └─ 手遅れ完走: worker.finished(outcome) → キャンセル済み世代 → remove_group(key, force=True) で巻き戻し破棄
```

## 6. エラー処理・エッジケース

- キャンセル後の遅延シグナル（finished/failed とも）は世代判定で破棄。二重キャンセルは no-op。
- `LoadCancelled` は Diagnostics に記録しない（ユーザー起点の正常系）。`LoadTask.cancelled` は error と別状態。
- `source_info`: ファイル移動/削除で `stat` 失敗 → `size_bytes=None`・ツールチップはサイズ行のみ欠落。0ch グループ → `t_min/t_max=None`・「時間範囲: —」。
- ヘッダ行/タイトルは unload・アクティブ切替（`set_active_file(None)` 含む）で即追従。
- 検索クエリ表示（`no_match`）はエスケープ不要（QLabel の plain text 表示を使い、HTML 解釈させない）。

## 7. テスト戦略（docs/gui-testing-layers.md 準拠）＋実行形態

- **Core 単体（Layer A）**: `cancel` が k チャンネル後に True → `LoadCancelled`・グループ未登録。CSV の N 行チェック。`source_info` の各フィールド・stat 失敗・0ch。
- **Layer A（VM）**: `header_text`/`empty_state` の4状態遷移・`tooltip_text` 整形・graceful degradation。
- **Layer B（実イベント）**: キャンセルボタン `qtbot.mouseClick` → Event セット＋オーバーレイ即時非表示（実装済みコードへの追加カバレッジは sabotage-RED で「壊すと落ちる」を確認する第1弾の慣行に従う）。プレースホルダ⇄リスト切替・ヘッダ更新・タイトル更新・`ToolTipRole` の内容。cancelled 経路でモーダルが呼ばれないこと（QMessageBox monkeypatch）。
- **Layer C（realgui）**: 新規入力経路はキャンセルボタン（標準 QPushButton・単純クリック）のみ。着手時 `/gui-test-plan` で②実質的受け入れ要件と realgui 要否を判定し、merge 前 `/gui-verify` で①証拠ゲート。既存 realgui 経路（検索・D&D・メニュー）は無変更のため対応 realgui の再実行は回帰確認のみ。
- **実行形態（ユーザー選択）**: 実装は直列 subagent-driven-development。**タスクレビュー/最終レビューを Workflow 多レンズ並列**（spec 準拠・品質・回帰リスクの並列 verify、最終は判定パネル）にする。

## 8. FB 項目 → 設計の対応

| ID | 対応 |
|---|---|
| FB-04 | §4.1 ハイブリッドキャンセル＋ラベル＋複数ロード表示修正 |
| FB-05 | §4.2 ヘッダ件数＋空状態3分類（no_match/no_channels） |
| FB-07 | §4.3 タイトル書式＋購読 |
| FB-08 | §4.4 FileBrowser プレースホルダ＋§4.2 none_selected |
| FB-09 | §4.2 ヘッダのアクティブファイル名 |
| FB-10 | §4.5 source_info＋ToolTipRole |

## 9. トレーサビリティ

catalog の FB-04/05/07/08/09/10 を本 spec で満たす。第1弾（FB-01/02/03/06）は [2026-07-02-gui-feedback-errors-design.md](2026-07-02-gui-feedback-errors-design.md)・PR #37。実装プランは `docs/superpowers/plans/2026-07-03-gui-feedback-errors-r2.md` に writing-plans で作成予定。グラフエリア空状態は将来の表示オブジェクト切替構想（views 系）の設計時に本 spec の境界注記を参照すること。
