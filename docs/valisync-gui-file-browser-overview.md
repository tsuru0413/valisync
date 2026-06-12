# valisync-gui-file-browser — 要件メモ

> Kiro spec 生成用の要件整理。`.kiro/specs/<spec-name>/{requirements,design,tasks}.md` をこのメモを起点に生成する想定。

## 1. 背景
現状の MVP では、読み込まれたファイルとそれに属する信号を 1つの `ChannelBrowser`（QTreeView）階層構造で表示している。しかし、複数ファイルを扱う際の一覧性・操作性向上のため、ファイル一覧（`FileBrowser`）と信号一覧（`ChannelBrowser`）をマスター・ディテール形式に分離し、それぞれ独立した UI コンポーネントとして再設計する。

## 2. 要件サマリー (確定済み項目)
| ID | 要件 | 内容 |
|---|---|---|
| R1 | Dock の分離 | `FileBrowser` と `ChannelBrowser` を完全に独立した `QDockWidget` として実装する。 |
| R2 | 初期レイアウト | 右側ドックエリアに、上が `FileBrowser`、下が `ChannelBrowser` となるように初期配置する。 |
| R3 | FileBrowser の責務 | 読み込み済みのファイルをリスト表示する。単一選択のみを許可する。 |
| R4 | ChannelBrowser の責務 | 階層ツリー表示を廃止し、フラットなリスト（テーブル）表示に変更する。 |
| R5 | 表示内容の連動 | `FileBrowser` で選択された単一ファイルに含まれる信号のみを `ChannelBrowser` に表示する。複数ファイル選択時は信号を表示しない（将来拡張用）。 |
| R6 | カラムの変更 | `ChannelBrowser` のカラムから「型」「サンプル数」「時間範囲」を削除し、「単位 (unit)」カラムのみを追加する（Name, Unit）。 |

## 3. 対象範囲 (In scope / Out of scope)
- **In scope**: `MainWindow` のドック構成の変更、新しい View (`FileBrowserView`) と ViewModel (`FileBrowserVM`) の作成、既存の `ChannelBrowser` 関連クラスの大幅なリファクタリング（ツリーからリストへの移行、カラム変更）。
- **Out scope**: `FileBrowser` での複数ファイル選択時の信号マージ表示（将来拡張）。

## 4. アーキテクチャ (現状 → 移行後)
* **現状**: `MainWindow` + Right Dock (`ChannelBrowser`: 階層ツリー)
* **移行後**: `MainWindow` + Right Dock Top (`FileBrowser`: リスト) + Right Dock Bottom (`ChannelBrowser`: フラットリスト、カラムは Name / Unit)
* **VM 間連携**: `AppViewModel` (または Session) が「現在選択中のファイル (active_file)」状態を持ち、それが変化した際に `ChannelBrowserVM` が自身のリストを更新する（Observer パターン経由）。

## 5. 採用しない選択肢と理由
- **案**: 1つの DockWidget 内で QSplitter を使って上下分割する。
- **理由**: ユーザーが FileBrowser と ChannelBrowser を別々のモニターや場所に自由にフローティング/ドッキングさせたい場合に対応できないため不採用。完全に独立した Dock とし、Qt のタブ/分割機能に委ねる。
