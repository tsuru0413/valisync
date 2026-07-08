# gui-shell-controls 設計 spec — シェル操作の可視化・入口/出口の完成

- **日付**: 2026-07-07
- **状態**: 設計（brainstorming 完了・ユーザー承認済み）→ writing-plans へ
- **一次情報源**: [docs/audit-findings-catalog.md](../../audit-findings-catalog.md) の SH-01..15、[docs/roadmap.md](../../roadmap.md)
- **ビジュアルモック**: https://claude.ai/code/artifact/1191d606-4857-453f-8565-35b7fab36083
- **設計探索の来歴**: 敵対的マルチエージェント探索（web リサーチ5並列 → 4案の多様な立案 → 案ごと2レンズの敵対的批評 → 統合）。18エージェント・0エラー。参照ツール: asammdf（同一 PySide6+pyqtgraph スタック・最近接）/ Vector CANape・vSignalyzer / ETAS MDA / NI DIAdem / Dewesoft X / VS Code・JetBrains（シェル idiom）。

---

## 1. 背景と目的

valisync は ADAS 計測（CAN/XCP/Ethernet/CSV を統一時間軸に統合）を可視化・解析するデスクトップ GUI（PySide6/Qt6・pyqtgraph・MVVM）。実ユーザージャーニー監査「開く → 見る → 解析する」で、シェル操作に **15 の UX 欠陥（SH-01..15）** が確定した。核心の失敗は **「初回のエンジニアが、データの開き方・解析結果の書き出し方に気づけない」** ことである。

重要な事実: **バックエンドは既に存在し、GUI に配線されていないだけ** — `Session.export_csv`、`GraphAreaVM`/`View` の `add_tab`/`remove_tab`/`rename_tab`/`add_panel`/`remove_panel`、`QSettings` による geometry/windowState 永続化。したがって本サブスペックは主に **「検証済みバックエンドの UI サーフェス化」** であり、真に新規なのは Welcome 空状態・オフスレッド Export ダイアログ・データソース一覧・Recent Files・CSV エクスポータのオプション拡張に限られる。

**目的**: 15 の欠陥を解消しつつ、既存の Qt6+pyqtgraph MVVM シェルに収まる **モダンで発見可能な UI/UX** を与える。特に (a) ディスカバラビリティ失敗（入口/出口）を最優先で埋め、(b) ネイティブ desktop として構築可能な範囲に留め、(c) 15 コントロールを乱雑さなく収容し、(d) 大容量 mf4・多信号・多パネル比較のパワーユーザー動線を尊重する。

---

## 2. 設計方向（採用と却下）

4 案（IDE パワーユーザー / ガイド重視 / 常時リボン / ワークスペース）はいずれも**同一のバックエンド検証済みコア**に収束し、各案が上に乗せた差別化上部構造は**全批評（kill レンズ＋ADAS 実用性レンズ）が致命的欠陥と判定**した。統合の結論は明快 — **「共有ベースラインを出荷し、差別化を捨てる」**。

### 採用: クラシック・ネイティブ QMainWindow シェル

- **ディスカバラビリティの背骨** = 従来メニューバー（File / View / Analyze / Help・File 先頭）＋薄いアイコン＋ラベル `QToolBar`（`QStyle.standardIcon`＝アセット不要・ツールチップにショートカット併記）。ツールバーは主要動詞（Open, Export, New Tab, Add Panel, Reset Layout）＋ユーザー明示要望のドックトグルボタン3つ（`dock.toggleViewAction()`）のみ。
- **アーキテクチャの背骨** = 中央 **QAction レジストリ**。各コマンドを1回定義（icon＋tooltip-with-shortcut＋statusTip＋shortcut）し、メニュー/ツールバー/コンテキストへ同一マウント。SH-05/06/14 を1判断に集約し、後日コマンドパレットを安価に graft できる余地を残す。
- **入口** = 中央 **Welcome 空状態**（`QStackedWidget` 切替）。支配的な「計測ファイルを開く（Ctrl+O）」CTA＋ドロップヒント＋Recent Files。
- **出口** = 一級市民の **Export CSV ダイアログ**（File>Export…・Ctrl+E・ツールバー）。データ無し時は無効化＋ツールチップで予告。
- **タブ/パネル** = ネイティブ `QTabWidget`（`setTabsClosable`＋コーナー＋＋ダブルクリック改名）。
- **レイアウト** = 現行の予測可能な固定ドック配置を維持＋Reset Layout。
- **データソース修正** = 既存 File Browser ドック内で `sources_file` 永続化・Open/Add・一覧・確認付き削除（ビュー再配置はしない）。

### 却下（各批評の致命的欠陥）

- **常時リボン（CommandDeck）**: Qt6 ネイティブウィジェットでない・約 80px 常時占有で波形圧迫・1366px bench 幅で溢れ・メニュー廃止でスケール行き止まり。valisync の約 20 コマンドには過剰。
- **アクティビティレール再配置（Studio）**: 右→左移動は利得ゼロで CANape 空間記憶と Layer-C dock-geometry テストを破壊。
- **コマンドパレット旗艦（Studio）**: CANape/MDA ペルソナにパレット操作記憶がない（Studio 自身のリスク節が認める）。**後続増分で QAction レジストリ上に graft** する。
- **ワークスペース subsystem（Workspaces）**: Phase3 delegated（roadmap）・File 降格・registry-blob 永続化債務・構造再配置で承認ゲート要。名前付き .vsproj は Phase3 valisync-persistence へ。

---

## 3. 承認済み設計判断

| # | 判断 | 決定 | 根拠 |
|---|---|---|---|
| DP1 | 主要ディスカバラビリティ・サーフェス | **メニューバー＋薄いツールバー** | リサーチ全会一致・asammdf 実証・最低リスク・波形非圧迫 |
| Recent | 最近使ったファイル | **追加**（当初「実装しない」を再考の上で覆す） | リサーチが日次価値最高のアクセラレータと強く推奨 |
| DP3 | オンボーディング深度 | **中央 Welcome 空状態のみ** | 最高レバレッジ・最低コスト・nag なし。コーチマーク等は却下 |
| DP6 | Export 実行とオプション | **オフスレッド＋フル CSV オプション（区切り/小数/単位行/精度）** | 大容量で同期は凍結（実証）。Excel/MATLAB 連携にフルオプション |
| DP2 | コマンドパレット | **後送り**（レジストリは今作る） | 現ペルソナに過剰・コマンド増後に安価 graft |
| DP4 | パネルコントロール | メニュー＋ツールバー＋コンテキストで可視化・**in-place chrome とアクティブパネルモデルは gui-plot-analysis-controls へ後送り** | 8パネル比較の画素課税回避・`main_window.py:280` の `panels[0]` hardcode は別モデル変更 |
| DP5 | レイアウト永続化 | 固定ゾーン＋Reset Layout のみ・**ワークスペースは Phase3 へ** | roadmap の Phase3 委譲を尊重・データ復元と JSON スキーマを一体設計 |

---

## 4. アーキテクチャ（コンポーネント境界）

MVVM・薄い MainWindow を維持。新規/変更コンポーネント:

### 4.1 ShellActions（QAction レジストリ）— 新規 `gui/views/shell_actions.py`
- **責務**: シェルコマンドを1回だけ定義（`QAction`: text・`QStyle.StandardPixmap` icon・shortcut・statusTip・shortcut 併記 tooltip）し、辞書 `actions: dict[str, QAction]` として保持。メニュー/ツールバー/コンテキストは本レジストリを参照して構築。
- **利用**: `MainWindow` が `ShellActions(self)` を構築し、`build_menubar()` / `build_toolbar()` がレジストリからマウント。各 `QAction.triggered` は MainWindow のスロット（`open_file` / `export_csv` / …）へ接続。
- **依存**: `MainWindow`（親・スロット）。VM 状態には触れない（純粋にコマンド定義）。
- **増分1 で定義**: `open`（Ctrl+O）・`open_folder`・`export`（Ctrl+E）。`reset_layout`・dock トグルは増分3 で追加（レジストリは増分横断で成長）。
- **拡張性**: 後日パレットはレジストリ上の read-only フィルタ（約150 LOC）として graft 可能。

### 4.2 WelcomeView（空状態）— 新規 `gui/views/welcome_view.py`
- **責務**: 「計測ファイルを開く（Ctrl+O）」CTA・ドロップヒント・Recent Files リストを描画。CTA/Recent クリックでシグナル emit（`open_requested(Path|None)`）。
- **配置**: `MainWindow` の中央を `QStackedWidget` 化し `[WelcomeView, GraphAreaView]`。**表示規則**: 初期状態は WelcomeView。最初の読み込み成功で GraphAreaView へ永続スワップ（`_workbench_started` ラッチ）。**最後の1件をアンロードしても Welcome へは戻さない**（GraphArea を維持し、GraphArea 側の空表示に委ねる）＝ stranding 回避。
- **依存**: `AppViewModel`（loaded state・Recent 供給）。ドロップは既存 `graph_area_view.file_dropped` 経路と重複しない（Welcome 上のドロップも `open_requested` に集約）。

### 4.3 ExportCsvDialog — 新規 `gui/views/export_csv_dialog.py`
- **責務**: モーダル `QDialog`。ファイル別グループの信号ツリー（チェックボックス・**初期選択＝現在プロット中**）・フィルタ・すべて/なし・統合タイムライン切替・CSV 形式（区切り/小数/単位行/精度）・出力先（`getSaveFileName`）。`ExportRequest`（選択 Signal 群・`CsvExportOptions`・`use_unified_timeline`・path）を返す静的 `ask(...)`（`CsvFormatDialog.ask` が前例）。
- **依存**: `Session`（信号列挙・グループ）、「現在プロット中」集合は `GraphAreaVM` のアクティブタブのパネル群からプロット済みキーを収集。
- **実行**: ダイアログは選択のみ。実 export は MainWindow が **オフスレッド**（`LoadController`/`BusyOverlay` 再利用）で `session.export_csv(...)` を呼ぶ。

### 4.4 CsvExporter オプション拡張 — **コア変更** `core/export/csv_exporter.py`
- **現状**（精読済み）: `export(signals, output_path, use_unified_timeline=False)`。`_fmt(v)=repr(float(v))` で **round-trip 保証**、区切りは `","` hardcode、ヘッダは `_TIMESTAMP_HEADER="timestamp"`、単位行なし。全行を `list[str]` としてメモリ構築 → `_atomic_write`（temp→rename）。**この全行メモリ構築が大容量オフスレッド必須の直接根拠**。
- **変更**: `CsvExportOptions`（`delimiter: str=","`・`decimal: str="."`・`unit_row: bool=False`・`precision: int|None=None`）を導入し `export(signals, output_path, use_unified_timeline=False, options=CsvExportOptions())` へ。`_fmt`・`_rows_unified_timeline`・`_rows_shared_timeline`・ヘッダ結合をオプション経由に。
  - **単位行**: `unit_row=True` でヘッダ直下に各信号の単位行を出力（timestamp 列は `s` 等）。
  - **精度**: `precision=None`（既定）は現行 `repr` の **round-trip を維持**（無回帰）。有限 N 指定時は `f"{v:.{N}g}"` で桁制限（可読性↔round-trip のトレードオフは plan で明記）。
  - **制約**: `decimal=","` と `delimiter=","` は衝突するため、ダイアログ側で相互排他バリデーション（例: 小数=カンマ選択時は区切りを `;` に強制/警告）。plan で検証規則を確定。
- **注記**: これは **core の構造変更**（memory `feedback_structural_change_approval`）。DP6 のフルオプション承認が本変更を含意する。`export` は後方互換（新引数は既定値付き）だが、署名変更として spec レビューで確認する。**呼び出しは必ずオフスレッド**。

### 4.5 選択部分集合の組み立て
- `unified_timeline_signals(...)` は**全**ロード信号を返す。Export のチェック部分集合へ絞る必要がある。増分1 の組み立て経路: 選択キー集合でフィルタし、`use_unified_timeline=True` のとき per-file/per-signal オフセットを再適用（増分1 ではオフセットは既定 0；オフセット連動は analysis 由来で後続）。

### 4.6 FileBrowserView 強化（SH-07/08/10/15）
- ドックヘッダに Open/Add-folder コントロール（`open_requested` emit）。ソース一覧を既存ドック内に追加（DataExplorer と `sources_file` を共有）。Remove File / Remove Source は選択対象明示＋確認ダイアログ。**ビュー再配置はしない**（承認ゲート・Layer-C 再検証を回避）。

### 4.7 MainWindow 変更
- 中央を `QStackedWidget`（Welcome / GraphArea）化。`ShellActions` 構築＋メニュー/ツールバー構築。`open_file`（`QFileDialog.getOpenFileName` → 既存 `_load_file`）・`export_csv`（ExportCsvDialog → オフスレッド export）スロット追加。Recent Files 更新は `_on_loaded` にフック。

---

## 5. 増分計画

| 増分 | テーマ | 含む SH | 主コンポーネント |
|---|---|---|---|
| **増分1** | **File I/O 導線（入口/出口）** | SH-01・SH-07・SH-03 | ShellActions・WelcomeView・ExportCsvDialog・csv_exporter 拡張・Recent Files・QStackedWidget 化 |
| 増分2 | タブ/パネル・データソース管理 | SH-02/04/13/06・SH-08/10/15 | QTabWidget affordance・Analyze メニュー・FileBrowser ソース一覧 |
| 増分3 | レイアウト/chrome | SH-05・SH-11・SH-12・SH-14 | ショートカット監査・Reset Layout・ドックトグルボタン・Help/About |
| Phase3 調整 | データソース/ワークスペース永続化 | SH-09（名前付き .vsproj） | valisync-persistence と統合 |

増分1 はやや大きいため、writing-plans で **1a（Open＋Recent＋Welcome＋ShellActions レジストリ）/ 1b（Export ダイアログ＋csv_exporter 拡張）** に細分してよい。

---

## 6. 増分1 詳細設計（File I/O 導線）

### 6.1 SH-01 Open 導線
- **経路**（3+1）: `File>Open…`（Ctrl+O）・ツールバー Open・Welcome CTA・File Browser ＋ボタン。すべて MainWindow `open_file()` に集約。
- **フロー**: `QFileDialog.getOpenFileName`（フィルタ: `Measurement files (*.mf4 *.mdf *.dat *.csv)`）→ 既存 `_load_file(path)`（CSV は `_csv_format_resolver` で LD-01 解決・オフスレッド・BusyOverlay・診断）。
- **Open Folder**: 既存 Data Explorer を開く（`open_data_explorer`）にマップ。
- **複数選択**: **v1 は単一ファイル**（`LoadController` が BusyOverlay を1つずつ駆動）。複数キューは後続。

### 6.2 SH-01 Recent Files（MRU）
- `QSettings` に最近パスのリスト（最大 10・重複除去・先頭挿入）。`File>Recent Files` サブメニュー（固定 QAction プール）＋Welcome リストに反映。各読み込み成功（`_on_loaded`）で更新。
- **存在検証**: 表示時に存在しないパスはグレーアウト/剪定。クリックで `open_file(path)`。

### 6.3 SH-07 File Browser Open
- FileBrowserView ヘッダに Open/Add ボタン → `open_requested` emit → MainWindow が接続。空リストから前進可能に。

### 6.4 SH-03 Export
- **到達**: `File>Export…`・Ctrl+E・ツールバー。データ無し時は QAction 無効化＋「先にデータを読み込んでください」ツールチップ（出口を予告）。
- **ダイアログ**: §4.3。初期選択＝現在プロット中信号。
- **実行**: オフスレッド（`LoadController`/`BusyOverlay` パターン再利用）。成功/失敗はステータスバー＋（失敗時）診断/モーダル（既存 FB-01 パターン踏襲）。
- **exporter**: §4.4 のオプション拡張。

### 6.5 Welcome 空状態
- §4.2。表示規則・unload-last 規則を実装。

### 6.6 データフロー / エラー処理
- Open は既存の堅牢なロードパイプライン（オフスレッド・CSV フォーマット解決・診断・FB-01 失敗可視化）を再利用。Export も同パターン（BusyOverlay・キャンセル・失敗時ステータス＋診断）。

### 6.7 エッジケース（open questions の解決）
- **複数ファイル**: v1 単一。
- **最後の1件アンロード**: workbench 維持＋インライン表示（Welcome へ戻さない）。
- **QSettings INI 移行**（memory `followup_settings_iniformat`）: **据え置き**（レジストリキー増を許容）。INI 移行は独立タスク（既存 geometry/windowState の移行パス必須）。
- **ショートカット衝突**: プロット/カーソル系キーは `Qt.WidgetWithChildrenShortcut` にスコープ。Qt に Export/New-Tab の StandardKey は無く手製（Ctrl+E/Ctrl+T）。pyqtgraph 束縛（現状 `graph_panel_view` は Escape のみ）との衝突監査を計画に含める。

---

## 7. テスト戦略（GUI テストレイヤー）

`docs/gui-testing-layers.md` に従い、**新入力経路ごとに Layer C 証拠**を計画へ scope（headless の false-green を実 OS 入力で検証）。

- **Layer A/B（headless・CI）**:
  - ShellActions: 各コマンドの QAction 生成（id/shortcut/enabled 状態）。
  - WelcomeView: 表示規則（初期→初回ロードでスワップ・unload-last で維持）・`open_requested` emit。
  - ExportCsvDialog: 初期選択＝プロット中・フィルタ・すべて/なし・返す `ExportRequest` の正しさ。
  - csv_exporter: 区切り/小数/単位行/精度オプションの出力（core ユニット）。
  - Recent Files: MRU ロジック（挿入/重複除去/上限/存在剪定）。
  - FileBrowser Open ボタン: `open_requested` emit。
  - Export 実行: オフスレッド委譲（LoadController パターン）・失敗時フィードバック。
- **Layer C（realgui・ローカル `--realgui`）**:
  - `File>Open` メニュークリック＋Ctrl+O で QFileDialog 起動経路。
  - Welcome CTA クリック → open。
  - File Browser ＋ボタン → open。
  - Export ダイアログの実操作（チェック・トグル・エクスポート）。
  - （増分3）ドックトグルボタン・Reset Layout。

計画時に `/gui-test-plan`（②受け入れ要件設計）、merge 前に `/gui-verify`（①realgui 証拠ゲート）を使う。

---

## 8. SH 対応表

| ID | 要素 | 増分 |
|---|---|---|
| SH-01 | File>Open・Ctrl+O・Welcome CTA・Recent | 増分1 |
| SH-07 | File Browser ＋ボタン | 増分1 |
| SH-03 | Export ダイアログ・Ctrl+E・オフスレッド・フルオプション | 増分1 |
| — | Welcome 空状態・QAction レジストリ | 増分1 |
| SH-02 | New Tab（＋・Ctrl+T） | 増分2 |
| SH-04 | タブを閉じる（✕） | 増分2 |
| SH-13 | タブ改名（ダブルクリック） | 増分2 |
| SH-06 | Add/Remove Panel 可視化（in-place chrome は別サブスペック） | 増分2 |
| SH-08 | ファイル削除の確認 | 増分2 |
| SH-10/15 | データソース一覧・Remove Source | 増分2 |
| SH-05 | キーボードショートカット（衝突監査込み） | 増分3 |
| SH-11 | Reset Layout | 増分3 |
| SH-12 | ドックトグルボタン | 増分3 |
| SH-14 | アイコン/ツールチップ・Help/About | 増分3 |
| SH-09 | データソース永続化（名前付き .vsproj は Phase3） | Phase3 調整 |

---

## 9. 未解決・後続への申し送り

- **csv_exporter のコア変更**（§4.4）は spec レビューで署名を確認（`feedback_structural_change_approval`）。
- **パレット / ワークスペース / パネル in-place chrome / アクティブパネルモデル** は後続増分・別サブスペック（gui-plot-analysis-controls）・Phase3。
- **INI 移行**（`followup_settings_iniformat`）は独立タスク。
- **Layer-C 検証予算**を各新入力経路について計画に明記（headless green から仮定しない）。
