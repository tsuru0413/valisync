# 雑メモ解消（ドック/メニュー UX）設計

> **出典**: ユーザー雑メモ（デスクトップ `valisync雑メモ.txt`）由来の実装可能 3 項目。
> UIUX 敵対的レビュー catalog（UX/UXG）とは別系統のユーザー直接要望。
> メモリ削減（雑メモ 07/12・native dtype で 10GB→1.36GB 解消済み・真の遅延ロードは将来課題）は本増分から除外。
> ブランチ `feature/memo-ux-cleanup`。

## Goal

ブラウザドック/メニューの 3 つの UX 改善:
- **#14**: チャンネルブラウザのヘッダーから選択中ファイル名表示を廃止し（件数のみ残す）、最小ドック幅を下げる。
- **#15**: チャンネルブラウザの右クリックメニューに「信号プロパティを表示」を追加（ダブルクリックと同じプレビュー窓）。
- **#17**: ドックをチェベロンで折りたたんだとき、折りたたみレールが「プロットと開いているドックの間」でなく**画面端**に来るようにする。

## ユーザー決定（確定）

1. #14: ファイル名廃止後は**件数のみ残す**（「{total} 信号中 {shown} 件を表示」）。どのファイルかは右上ファイルブラウザの選択で判別。
2. #17: 折りたたみレールを**開いているドックより外側（画面端側）**へ。プロット｜開いているドック｜レール〔画面端〕の順。
3. #17 の現状挙動をユーザー承認済み（再現スクショ提示・2026-07-23）— 片方折りたたみでレールが中央側に挟まる。

## §1 #14: ヘッダーのファイル名廃止＋最小ドック幅

### 現状
`ChannelBrowserVM.header_text()`（[channel_browser_vm.py:187-197](../../../src/valisync/gui/viewmodels/channel_browser_vm.py)）は
`"{name} — {total} 信号中 {shown} 件を表示"`（`name`=`session.source_name(active_key)`）。View 側
`ChannelBrowserView.header_label`（[channel_browser_view.py:109](../../../src/valisync/gui/views/channel_browser_view.py)・`QLabel`・**word-wrap 未設定**）が
`_refresh_state()`（[:165](../../../src/valisync/gui/views/channel_browser_view.py)）で表示。`channel_dock` に明示的 `setMinimumWidth` は無く、
**非折返しヘッダーラベルのテキスト全長**が最小ドック幅を規定している。

### 変更
- `header_text()` の通常/空テンプレから**ファイル名プレフィックス `"{name} — "` を除去**:
  - 通常: `"{total} 信号中 {shown} 件を表示"`（`S.CHANNEL_HEADER_COUNT_TMPL` を改訂・`strings.py:229`）。
  - 空: `"0 信号"` 等（`S.CHANNEL_HEADER_EMPTY_TMPL` からファイル名除去・`strings.py:228`）。
  - ファイル未選択時は現状の `"ファイル未選択"` 維持。
- `header_label` に **`setWordWrap(True)`** を追加（短文化しても長カウントで最小幅が張り付かないよう保険）。
- 文言変更は `strings.py` の該当定数を改訂（D-1 表記規約 R-01..13 に従う・**対訳表 G 番号の該当行を更新**）。
- **どのファイルかの判別**は右上ファイルブラウザの選択ハイライトに一本化（既存挙動）。ファイル名を別面へ出す配線は追加しない。

## §2 #15: 右クリックに「信号プロパティを表示」

### 現状
`ChannelBrowserView.build_context_menu()`（[channel_browser_view.py:286-294](../../../src/valisync/gui/views/channel_browser_view.py)）は
「アクティブパネルへ追加」（`S.ACTION_ADD_TO_ACTIVE_PANEL`）1 項目のみ。信号ダブルクリック→プレビュー窓は
`doubleClicked`→`_emit_preview`→`preview_requested.emit(key)`（[:141,278-282,61](../../../src/valisync/gui/views/channel_browser_view.py)）→
MainWindow の `preview_requested.connect(signal_preview_window.show_signal)`（[main_window.py:433-435](../../../src/valisync/gui/views/main_window.py)）で
単一インスタンス `SignalPreviewWindow`（プレビュー＋プロパティ）を開く。

### 変更
- `build_context_menu()` に **「信号プロパティを表示」**（`S.ACTION_SHOW_SIGNAL_PROPERTIES` 新設・`strings.py`）を追加。
- **単一選択の leaf のときのみ有効化**（`selected_signal_keys()`（[:251-264](../../../src/valisync/gui/views/channel_browser_view.py)）が 1 件かつ leaf）。複数選択/parent 選択時は disabled。
- `triggered` で選択 leaf キーに対し `self.preview_requested.emit(key)` を発火 → 既存の MainWindow 配線でダブルクリックと同一のプレビュー窓を開く（新規窓/経路は作らない）。
- 「アクティブパネルへ追加」は複数選択前提のまま維持（本項目のみ単一選択制約）。

## §3 #17: 折りたたみレールを画面端へ

### 現状（根本原因・再現で確定）
折りたたみは `_collapse_dock`（[main_window.py:983-1013](../../../src/valisync/gui/views/main_window.py)）が `dock.hide()`＋`rail.add_tab`。
レール `DockCollapseRail` は `CentralWithRails`（[central_with_rails.py:14-39](../../../src/valisync/gui/views/central_with_rails.py)）が
**中央ウィジェットの縁**（右ドックなら col2=中央の右端）に据える。QMainWindow の右ドック領域は中央ウィジェットの
**外側（画面端寄り）**にあるため、右ドック領域に**開いているドックが残っている**と、折りたたみレール（中央の右端）が
**プロットと開いているドックの間**に挟まる。両方折りたたむと右ドック領域が空になりレールが画面端に来る（09_collapsed が正）。
片方だけ折りたたむと中央側にレールが残るのが不整合（再現スクショで確定）。

### 望ましい挙動（確定）
- 折りたたみレールは**常に画面端側**（開いているドックより外側）に置く。順序: **プロット｜開いているドック｜レール〔画面端〕**。
- プロットは折りたたみで空いた分を吸収して広がる（現状の利点を維持）。
- 両方折りたたみ（09_collapsed）の見た目は不変に保つ（既にレールが画面端）。
- 上端/下端ドック（診断）・左右で同じ原則（各辺のレールはその辺の画面端側）。

### 機構（実装時スパイク必須）
中央ウィジェットの縁にレールを置く現行 `CentralWithRails` 構造では、レールが構造的に「ドック領域の内側」になる。
「開いているドックより外側」を実現する機構は Qt 上で自明でないため、**実装の最初にスパイクで機構を決める**
（過去増分の Fusion/QPalette・Lucide 選定と同型のスパイク前置き）。候補:
- **A: レールを最外ドック化** — 各辺の最外側に常駐する薄い「レールドック」（QDockWidget）を置き、折りたたみタブを
  そこへ集約。QMainWindow のドック順で最外側を保証（新規ドック追加時も最外を維持）。QMainWindow のドック体系内で完結。
- **B: レールを窓外縁オーバーレイ化** — レールを QMainWindow レベルの薄い縁ウィジェットとして絶対配置し、
  ドック領域の外側（窓の縁）に重ねる。z-order/ヒット判定の管理が要（[[gui_overlay_sibling_zorder_sinks_behind_later_children]] の教訓）。
- **C: `CentralWithRails` の被包範囲拡大** — 中央だけでなくドック領域も含めて包み、レールを真の窓縁へ。QMainWindow の
  ドック領域は内部管理のため実現可否をスパイクで確認。
- スパイクは**片方折りたたみで実 OS レールが開いているドックの外側（画面端）に来る**ことを実機ピクセルで確認して採否を決める。
  両方折りたたみ（09）と全展開が無回帰であることも同時確認。
- 折りたたみ状態の永続（`dockCollapsed` QSettings・[[gui_restorestate_resets_dock_corner_config]] と同型の復元順）は現行踏襲。

## §4 テスト（gui-test-plan 準拠）

### #14（Layer A/B）
- **T-A1**: `header_text()` がファイル名を含まない（通常/空/未選択の各分岐）。
- **T-B1**: `header_label.wordWrap()` True・ヘッダー表示がファイル名なし。最小幅が縮小方向へ（`channel_dock.minimumSizeHint().width()` がファイル名込み時より小・値の絶対 assert は環境依存回避で相対比較）。

### #15（Layer B）
- **T-B2**: 単一 leaf 選択で右クリック→「信号プロパティを表示」有効・複数/parent 選択で disabled。triggered で `preview_requested` が選択キーで発火（signal spy）。**sabotage**: 複数選択でも有効化する実装 → RED。

### #17（Layer C・realgui ①ゲート — 最重要）
- **T-C1 片方折りたたみのレール位置**: 実 OS で 2 ファイル or 2 ドック開状態 → チェベロンで片方折りたたみ →
  **折りたたみレールの x 位置が、開いているドックの x 位置より画面端側（外側）**であることを実測（レール矩形 vs 開ドック矩形の x 比較）。実ピクセルスクショ目視も添付。File 折りたたみ/Channel 折りたたみの両対称。
- **T-C2 無回帰**: 両方折りたたみ（09 相当）でレールが画面端・プロット全幅／全展開でレールゼロ幅、が不変。
- **honest-RED**: 現状（レールが中央側）でこの assert が RED になることを実証（機構変更前）。
- ゾーン境界を動かす変更ではないが、レール位置変更で既存 realgui の折りたたみ系（増分C の `dock.height()` 実測・
  visibleRegion）が無回帰か全数確認。

### ①証拠ゲート
`uv run pytest tests/realgui/ --realgui -q` フル＋T-C1/T-C2 のスクショ/矩形実測を merge 前に必須化。

## §5 凍結カタログ

- **#14**: チャンネルブラウザのヘッダーテキストが変わる。02_plotted 等**チャンネルブラウザが可視な状態**でヘッダー行が差分
  （プロット面 viewport は不変を `--crop-meta` で実証）。ベースライン更新。
- **#15**: 右クリックメニューは撮影対象外（見た目の静的差分なし）。
- **#17**: 09_collapsed は**両方折りたたみで不変**（レールは既に画面端）。片方折りたたみ状態はカタログに無いため、
  **新規カタログ状態（例 `10_collapse_one`）を追加**して片方折りたたみのレール画面端配置を凍結被覆するか、realgui T-C1 に
  一本化するかを実装時に判断（realgui を一次被覆とし新規状態は任意）。
- per-state 期待差分に限定を確認 → ベースライン昇格 → 再撮影 compare exit 0（両テーマ）＋決定性。

## §6 受け入れ基準

1. チャンネルブラウザのヘッダーにファイル名が出ない（件数のみ）・最小ドック幅が縮小方向。
2. 右クリックに「信号プロパティを表示」（単一 leaf のみ有効）・ダブルクリックと同じプレビュー窓が開く。
3. 片方折りたたみでレールが**開いているドックの外側（画面端）**に来る（実 OS ピクセルで実証）。
4. 両方折りたたみ（09）・全展開は無回帰。折りたたみ状態の永続も無回帰。
5. full suite green・realgui フル＋T-C1/T-C2・凍結 per-state 契約・決定性 exit 0。

## §7 敵対的レビューが攻撃すべき点（closure anchors）

- **#17 機構スパイクの実効**: 採用機構が「片方折りたたみでレールが開ドックの外側」を実 OS で本当に達成するか（honest-RED→GREEN）。
  両方折りたたみ・全展開・折りたたみ永続復元の無回帰。z-order/ヒット判定（B 案採用時）。
- **#17 の対称性**: File 折りたたみ/Channel 折りたたみ・上下端（診断）でも原則一貫か。
- **#14 の最小幅**: word-wrap＋ファイル名除去で最小幅が実際に下がるか（minimumSizeHint の相対比較・絶対 px 非依存）。
  ファイル名を失って「どのファイル」の判別性が実用上足りるか（ファイルブラウザ選択のみ）。
- **#15 の有効化条件**: 単一 leaf 制約が正しく効くか（複数/parent で disabled）・既存「追加」項目に無回帰か。
- **文言**: `strings.py` 集約・対訳表更新・恒真テストなし。
- **凍結カタログ**: #14 のヘッダー差分がチャンネルブラウザ可視状態に限定・プロット viewport 不変。
