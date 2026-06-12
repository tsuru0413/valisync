# Requirements Document: valisync-gui-mvp

## Introduction

本 spec は `valisync-gui`（29 要件）を **MVP 垂直スライス**方針で分解した 6 sub-spec の **1 つ目**であり、GUI の「歩く骨格（walking skeleton）」を定義する。最大リスクである **統合の成立性**（QDockWidget + PyQtGraph + MVVM 配線 + 実データ操作）を最初に検証することを目的とする。

成功条件（ユーザー観点）: 「ファイルを読み込み → 信号をツリーから探し → パネルへドラッグ → 波形が描画され → ズーム/パンででき、ドッキング・タブ・パネル分割・X 軸同期が機能し、数百万点でも実用精度で滑らかに操作できる」状態。

本 sub-spec は親 `valisync-gui` の要件 R1, R3, R4, R5, R6, R7, R8（基本 Y-T 部分）, R12, R13, R21, R22, R27, R28, R29（最小）を担う。以下は親要件への対応を併記する。

### スコープ外（後続 sub-spec / Phase へ委譲）

- 複数 Y 軸レイアウト・X-Y プロットモード（親 R8.6–8.18）→ `valisync-gui-axes`
- カーソル・範囲統計・Drag-offset（親 R14, R15, R16, R17）→ `valisync-gui-analysis`
- Calcbar UI・Formula エディタ（親 R18, R19）→ `valisync-gui-derived`
- Table / 棒グラフ / コンタービュー（親 R9, R10, R11）→ `valisync-gui-views`
- Python Script Console（親 R20）→ `valisync-gui-script`
- Layout_Template の保存/復元（親 R2）→ Phase3 `valisync-persistence`
- Channel_Browser のダブルクリック波形プレビューポップアップ（親 R4.3）→ 後続 sub-spec へ defer

### 前提（充足済み / 着手前作業）

- 親 R23–26（Interpolator / Range_Statistics / Downsampler / Calcbar 演算）は valisync-core で実装済み
- **着手前のコア作業**: ① Task 8.2（Session）完了 — `load` / Signal_Group 参照 / `downsample` を公開すること。② `Downsampler` を **O(N) ベクトル化**（後述の動的 LOD が 16ms 予算を満たすための根本対処）。振る舞い（min-max・厳密単調・不変条件）は不変、性能のみ改善

## Glossary

親 `valisync-gui` の Glossary を継承する。本 sub-spec で中心となる用語: GUI_Application, Dock_Widget, Graph_Area, Graph_Panel, Waveform_View, Data_Explorer, Channel_Browser, Global/Delta_Cursor（本 spec ではカーソルは未実装）, LOD_Renderer, Session, Signal, Signal_Group。

## Requirements

### Requirement 1: ドッキングウィンドウシステム（親 R1）

**User Story:** テストエンジニアとして、解析作業に合わせて画面構成を自由にカスタマイズしたい。

#### Acceptance Criteria

1. THE GUI_Application SHALL QDockWidget ベースのドッキングウィンドウシステムを採用し、Channel_Browser および Graph_Area を独立した Dock_Widget として提供する
2. THE Dock_Widget SHALL ドラッグ操作によりメインウィンドウ内の任意の位置にドッキング（上下左右・タブ化）可能とする
3. THE Dock_Widget SHALL メインウィンドウから切り離してフローティングウィンドウとして表示可能とする
4. WHEN ユーザーがパネルを閉じた場合、THE GUI_Application SHALL メニューまたはショートカットから再表示可能とする
5. THE GUI_Application SHALL Data_Explorer をツールバーのボタンから呼び出される独立したウィンドウ（QMainWindow）として提供する（Formula_Editor / Script_Console は本 sub-spec のスコープ外）

### Requirement 2: アプリケーション起動と初期状態（親 R28）

**User Story:** テストエンジニアとして、アプリを起動して即座に作業を開始したい。

#### Acceptance Criteria

1. WHEN アプリが起動された場合、THE GUI_Application SHALL メインウィンドウを表示し、デフォルトの Workspace（Channel_Browser + 空の Graph_Area）を初期状態として提供する
2. WHEN アプリが起動された場合、THE GUI_Application SHALL 3 秒以内にユーザー操作可能な状態となる
3. THE GUI_Application SHALL ウィンドウサイズ・位置を次回起動時に復元する（QSettings 等の最小復元。本格的な Layout_Template は Phase3）
4. WHEN ファイル読み込みが要求された場合、THE GUI_Application SHALL 読み込みをワーカースレッドで実行し、読み込み中は不確定（インディターミネート）ビジー表示を行い UI が応答停止していないことを視覚的に示す
5. THE GUI_Application SHALL 通常規模のファイル読み込みを概ね 15 秒以内に完了する（読み込み中のキャンセル・確定進捗バーは本 sub-spec のスコープ外）

### Requirement 3: データエクスプローラー（親 R3）

**User Story:** テストエンジニアとして、ローカルフォルダをデータソースとして登録し、解析対象ファイルを管理したい。

#### Acceptance Criteria

1. WHEN ユーザーがローカルフォルダをデータソース登録した場合、THE Data_Explorer SHALL ツリービューにフォルダ構造を表示する
2. THE Data_Explorer SHALL ファイルをフォーマット種別（CAN/XCP/Ethernet/CSV）が識別可能なアイコンで表示する（MVP では拡張子ベースの簡易判定で可）
3. WHEN ユーザーがファイルをダブルクリック / Enter / コンテキストメニューで読み込み指示した場合、THE Data_Explorer SHALL Session 経由でファイルを読み込み、Channel_Browser に信号一覧を表示する
4. THE Data_Explorer SHALL データソースの追加・削除機能を提供する
5. THE Data_Explorer SHALL 登録済みデータソースを次回起動時にも保持する（JSON ファイルで永続化）
6. THE Data_Explorer SHALL OS のファイルマネージャからのドラッグ＆ドロップによるファイル読み込みを受け付ける

### Requirement 4: チャネルブラウザ（親 R4、R4.3 を除く）

**User Story:** テストエンジニアとして、読み込んだファイル内の信号を階層的に閲覧し、目的の信号を素早く見つけたい。

#### Acceptance Criteria

1. THE Channel_Browser SHALL 読み込み済みファイルの信号を階層ツリー（ソースファイル > 信号名）で表示する
2. THE Channel_Browser SHALL 各信号にデータ型・サンプル数・時間範囲のメタ情報を表示する
3. THE Channel_Browser SHALL インクリメンタルサーチ（テキスト入力に応じたリアルタイム絞り込み）を提供する
4. THE Channel_Browser SHALL 信号をドラッグして Graph_Panel にドロップすることで波形表示を追加する操作を提供する
5. THE Channel_Browser SHALL 複数信号の同時選択（Ctrl+クリック、Shift+クリック）とまとめてのドラッグ＆ドロップを提供する
6. THE Channel_Browser SHALL 各信号に対して表示/非表示のトグルを提供する

### Requirement 5: グラフ表示領域のタブ管理（親 R5）

**User Story:** テストエンジニアとして、複数のグラフ表示領域をタブで切り替えたい。

#### Acceptance Criteria

1. THE GUI_Application SHALL タブ切り替え可能な複数の Graph_Area を提供する
2. WHEN ユーザーがタブ追加操作を行った場合、THE GUI_Application SHALL 新しい空の Graph_Area タブを作成し、アクティブタブとして表示する
3. WHEN ユーザーがタブ削除操作を行った場合、THE GUI_Application SHALL 対象タブとその内部の全 Graph_Panel を削除する
4. THE GUI_Application SHALL 各タブにユーザーが編集可能な名前（1〜32 文字）を表示する
5. WHEN ユーザーがタブを切り替えた場合、THE GUI_Application SHALL 切り替え先タブの Graph_Area を 100ms 以内に表示する
6. WHEN ユーザーが最後の 1 つのタブに対して削除操作を行った場合、THE GUI_Application SHALL 削除を拒否し、ユーザーに通知する

### Requirement 6: グラフパネルの分割表示（親 R6）

**User Story:** テストエンジニアとして、1 つの Graph_Area 内に複数のグラフパネルを並べて表示したい。

#### Acceptance Criteria

1. THE Graph_Area SHALL 垂直方向の分割により複数の Graph_Panel を同時表示する
2. WHEN ユーザーがパネル追加操作を行った場合、THE Graph_Area SHALL 新しい Graph_Panel を既存パネルの下に追加する
3. WHEN ユーザーがパネル削除操作を行った場合、THE Graph_Area SHALL 対象パネルを削除し、残りのパネルが領域を均等に再分配する
4. THE Graph_Area SHALL パネル間の境界をドラッグすることで各パネルの高さ比率を変更可能とする
5. THE Graph_Area SHALL 1 つの Graph_Area 内に最大 8 個の Graph_Panel を配置可能とする
6. WHEN Graph_Area 内のパネル数が 1 の場合、THE Graph_Area SHALL パネル削除操作を拒否する

### Requirement 7: 時間軸同期（親 R7）

**User Story:** テストエンジニアとして、複数のグラフパネルの X 軸を連動させたい。

#### Acceptance Criteria

1. WHILE 同一 Graph_Area 内に複数の Graph_Panel が存在する間、THE Graph_Area SHALL 全パネルの X 軸表示範囲を同期する
2. WHEN いずれかの Graph_Panel で X 軸のズーム・パン操作が行われた場合、THE Graph_Area SHALL 同一 Graph_Area 内の全 Graph_Panel の X 軸表示範囲を同一に更新する
3. THE Graph_Area SHALL X 軸同期の有効/無効をユーザーが切り替え可能とする
4. WHEN X 軸同期が無効化された場合、THE Graph_Panel SHALL 各パネルが独立した X 軸表示範囲を持つ

### Requirement 8: 波形グラフ表示（基本 Y-T、親 R8.1–8.5）

**User Story:** テストエンジニアとして、信号データを時系列の折れ線グラフとして表示したい。

#### Acceptance Criteria

1. WHEN ユーザーが Signal を Graph_Panel に追加した場合、THE Waveform_View SHALL 横軸を時間（秒）、縦軸を信号値とする折れ線グラフ（Y-T モード）を描画する
2. THE Waveform_View SHALL 1 つの Graph_Panel 上に複数の Signal を重ね合わせて描画する（オーバーレイ表示）
3. THE Waveform_View SHALL 各 Signal を視覚的に区別可能な異なる色で描画する
4. THE Waveform_View SHALL 各 Signal の凡例（信号名と対応する色）を Graph_Panel 内に表示する
5. WHEN Signal のデータが空（サンプル数 0）の場合、THE Waveform_View SHALL 空のグラフ領域を表示し、凡例に信号名を表示する

（複数 Y 軸・X-Y プロットモードは `valisync-gui-axes` で実装。本 sub-spec は単一の共通 Y 軸での Y-T 表示とする）

### Requirement 9: X 軸ズーム・パン操作（親 R12）

**User Story:** テストエンジニアとして、X 軸をドラッグ操作でズーム・パンしたい。

#### Acceptance Criteria

1. THE Graph_Panel SHALL X 軸領域を内側ゾーン（描画領域に近い側）と外側ゾーン（ウィンドウ端に近い側）に分割する
2. WHEN ユーザーが X 軸の内側ゾーンで水平ドラッグした場合、THE Graph_Panel SHALL ドラッグ開始・終了地点を新しい表示範囲の左端・右端として設定する（範囲選択ズーム）
3. WHEN ユーザーが X 軸の外側ゾーンで水平ドラッグした場合、THE Graph_Panel SHALL X 軸表示範囲をパンする
4. WHEN ユーザーが X 軸領域でマウスホイール操作した場合、THE Graph_Panel SHALL カーソル位置を中心にズームイン/アウトする
5. THE Graph_Panel SHALL ズーム・パン操作を 16ms 以内（60fps 相当）に画面へ反映する
6. WHEN ユーザーが X 軸領域でダブルクリックした場合、THE Graph_Panel SHALL X 軸表示範囲を全データ範囲にリセットする
7. WHEN マウスカーソルが内側/外側ゾーン境界を越えた場合、THE Graph_Panel SHALL ホバー時にカーソル形状を変更し、現在のゾーンの操作（ズーム/パン）を視覚的に示す

### Requirement 10: Y 軸ズーム・パン操作（親 R13）

**User Story:** テストエンジニアとして、Y 軸をドラッグ操作でズーム・パンしたい。

#### Acceptance Criteria

1. THE Graph_Panel SHALL Y 軸領域を内側ゾーンと外側ゾーンに分割する
2. WHEN ユーザーが Y 軸の内側ゾーンで垂直ドラッグした場合、THE Graph_Panel SHALL ドラッグ開始・終了地点を新しい表示範囲の上限・下限として設定する（範囲選択ズーム）
3. WHEN ユーザーが Y 軸の外側ゾーンで垂直ドラッグした場合、THE Graph_Panel SHALL Y 軸表示範囲をパンする
4. WHEN ユーザーが Y 軸領域でマウスホイール操作した場合、THE Graph_Panel SHALL カーソル位置を中心にズームイン/アウトする
5. THE Graph_Panel SHALL ズーム・パン操作を 16ms 以内に画面へ反映する
6. WHEN ユーザーが Y 軸領域でダブルクリックした場合、THE Graph_Panel SHALL Y 軸表示範囲を表示中の全 Signal の値範囲にリセットする
7. WHEN マウスカーソルが内側/外側ゾーン境界を越えた場合、THE Graph_Panel SHALL ホバー時にカーソル形状を変更し操作種別を視覚的に示す

### Requirement 11: 描画パフォーマンスと動的ダウンサンプリング（LOD、親 R21）

**User Story:** テストエンジニアとして、数百万ポイントの大容量データでも滑らかに操作したい。

#### Acceptance Criteria

1. THE LOD_Renderer SHALL 表示ピクセル幅と現在の X 表示範囲に応じて動的にダウンサンプリングを行い、描画ポイント数を最適化する
2. THE LOD_Renderer SHALL 100 万サンプル以上の Signal を 60fps 以上でスムーズにレンダリングする
3. THE LOD_Renderer SHALL ダウンサンプリング時に各ピクセル区間の最大値・最小値を保持し、波形の包絡線を正確に表現する（min-max）
4. WHEN ユーザーがズームインした場合、THE LOD_Renderer SHALL 表示範囲に応じてダウンサンプリング率を動的に調整し、詳細データを表示する
5. THE GUI_Application SHALL ダウンサンプリングを Session 経由で Downsampler に委譲する（描画最適化目的も例外なく Session 経由）
6. THE LOD_Renderer SHALL ダウンサンプリングの適用有無をユーザーに視覚的に示す（ステータスバー等）

### Requirement 12: ドラッグ＆ドロップワークフロー（親 R22、MVP 部分）

**User Story:** テストエンジニアとして、マウス操作でファイル読み込みから波形表示まで完結させたい。

#### Acceptance Criteria

1. THE GUI_Application SHALL OS のファイルマネージャから Data_Explorer または Graph_Area へのファイル D&D による読み込みを受け付ける
2. THE Channel_Browser SHALL 信号を Graph_Panel へ D&D することで波形表示を追加する操作を提供する
3. THE Channel_Browser SHALL 複数信号を同時選択してまとめて D&D 可能とする
4. WHEN 信号が Graph_Panel にドロップされた場合、THE Waveform_View SHALL ドロップされた信号を即座に波形描画する
5. THE GUI_Application SHALL ドラッグ中にドロップ可能領域を視覚的にハイライト表示する

### Requirement 13: GUI とコアの分離（MVVM、親 R27）

**User Story:** 開発者として、GUI 層が Session 経由でのみコアにアクセスする疎結合を保証し、将来のヘッドレス化・テスト自動化を容易にしたい。

#### Acceptance Criteria

1. THE GUI_Application SHALL MVVM パターンに基づき View（Qt/PyQtGraph）と ViewModel（純 Python・Qt 非依存）と Model（Session/コアデータ）を分離する
2. THE GUI_Application SHALL 全データ操作（読込・ダウンサンプリングを含む）を Session クラス経由で実行する
3. THE GUI_Application SHALL Signal および Signal_Group を読み取り専用で参照する（変更操作を行わない）
4. THE GUI_Application SHALL コアモジュール（loaders, sync, formula, export, downsampler 等）を直接インポートしない
5. WHEN Session からエラーが返された場合、THE GUI_Application SHALL エラー内容をユーザーに表示し、アプリの動作を継続する
6. THE ViewModel SHALL 現在の表示状態（パネルごとの表示信号・X/Y 範囲・適用 DS 後の点数・DS 適用フラグ等）を構造化データとして取得可能に公開し、Qt・ディスプレイ非依存で検査・駆動できるようにする（AI エージェントによる実機テスト容易性）

### Requirement 14: コンテキストメニュー（最小、親 R29 の一部）

**User Story:** テストエンジニアとして、頻用操作を右クリックから素早く実行したい。

#### Acceptance Criteria

1. WHEN ユーザーが Channel_Browser の信号項目を右クリックした場合、THE GUI_Application SHALL 「アクティブ Graph_Panel に追加」を含むコンテキストメニューを表示する
2. WHEN ユーザーが Data_Explorer のファイル項目を右クリックした場合、THE GUI_Application SHALL 「ファイル読み込み」「データソースから除外」を含むコンテキストメニューを表示する
3. WHEN ユーザーが Graph_Panel の空白領域を右クリックした場合、THE GUI_Application SHALL 「パネル追加」「パネル削除」「全軸表示範囲リセット」を含むコンテキストメニューを表示する
4. THE GUI_Application SHALL 現在の状態で実行不可能なメニュー項目をグレーアウト表示する

（Waveform 上・Y_Axis 上・タブ上の完全なコンテキストメニュー（親 R29.1, R29.2, R29.6 等）は、対応機能を持つ後続 sub-spec で順次充足する）
