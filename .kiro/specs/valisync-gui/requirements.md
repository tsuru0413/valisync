# Requirements Document

## Introduction

ValiSync GUI は ADAS ソフトウェア開発向けの時系列信号データ解析デスクトップアプリケーションの GUI 層である。valisync-core が提供するデータモデル・読み込み・同期・Formula・エクスポート機能の上に、高速波形可視化・直感的なインタラクション・解析ツールを提供する。AVL CONCERTO に着想を得た操作体系で、テストエンジニア・テスト設計者・制御エンジニアが複数フォーマットの信号データを統一時間軸上で効率的に分析できる環境を実現する。

本 spec はデータ可視化・インタラクション・解析ツールに焦点を当て、**シナリオバリデーション（検証ハイライト・期待値比較）はスコープ外**とする。GUI 層は MVVM パターンを意識し、UI ロジックとコアのデータ処理を完全に分離する。全ての計算処理を valisync-core の Session クラスに委譲する。

## Glossary

- **GUI_Application**: ValiSync のデスクトップ GUI アプリケーション全体。PyQt6/PySide6 で実装される
- **Workspace**: ドッキングウィンドウシステムによる画面全体のレイアウト構成
- **Dock_Widget**: QDockWidget ベースの自由配置・分割・フローティング可能なパネル単位。Channel_Browser および Graph_Area が該当する
- **Layout_Template**: ウィンドウ配置・グラフ設定を JSON 形式で保存・復元可能なテンプレート
- **Graph_Area**: タブ切り替え可能な複数のグラフ表示領域。各タブは独立したレイアウトを持つ
- **Graph_Panel**: Graph_Area 内の個別のグラフ描画領域。分割表示により複数パネルを同時表示可能
- **Waveform_View**: 時系列折れ線グラフ（波形表示）。PyQtGraph で高速レンダリングされる
- **Table_View**: 信号の数値データを表形式で表示するビュー
- **Bar_Chart_View**: 信号データを棒グラフとして表示するビュー
- **Contour_View**: 2D カラーマップ表示。X 軸は時間に限定されない
- **Cursor**: グラフ上の特定時刻を指す垂直線。値の読み取りに使用する
- **Global_Cursor**: 全グラフパネルに連動する垂直カーソル。クリックで全グラフに同時表示される
- **Delta_Cursor**: 2 点間の時間差（Δt）と値差（Δy）を計測するカーソルペア
- **Data_Explorer**: データソース（ローカルフォルダ・ネットワークドライブ）を登録し、解析対象ファイルを管理する独立ウィンドウ。ツールバーのボタンから呼び出される
- **Channel_Browser**: 選択ファイル内の信号を階層表示（ネットワーク＞ノード＞シグナル）するパネル
- **Signal_List_Panel**: 全利用可能信号の一覧と表示/非表示トグルを提供するパネル
- **Formula_Editor**: Formula 式の作成・編集用 GUI エディタ。ツールバーのボタンから呼び出される独立ウィンドウ
- **Script_Console**: Python スクリプトを記述・実行し、グラフや信号データを操作する統合環境。ツールバーのボタンから呼び出される独立ウィンドウ
- **Calcbar**: 選択波形に対して回帰線・移動平均等のマクロ処理を適用する UI
- **Drag_Offset**: 波形をドラッグして時間オフセットを決定する操作
- **LOD_Renderer**: Level of Detail。広域表示時に動的ダウンサンプリングを行い描画性能を維持する仕組み
- **Session**: valisync-core のオーケストレーション層。GUI から全てのコア機能にアクセスする唯一の窓口
- **Signal**: valisync-core で定義された不変の時系列データモデル
- **Signal_Group**: valisync-core で定義されたファイル単位の Signal 集合
- **Time_Synchronizer**: valisync-core の時刻同期モジュール
- **Formula_Engine**: valisync-core の数式エンジン
- **Interpolator**: 任意の時刻における信号値を補間計算するモジュール（コア拡張が必要）
- **Range_Statistics**: 指定時間範囲内の統計値（平均・最大・最小等）を計算するモジュール（コア拡張が必要）
- **Downsampler**: 描画用に大容量データを動的に間引くモジュール（コア拡張が必要）
- **Y_Axis**: Graph_Panel 内の個別の縦軸。独立した表示範囲・スケール・高さ比率・水平幅・配置位置を持ち、1つ以上の Signal に関連付けられる。複数 Signal を割り当てた場合は共通軸として表示範囲を同期する
- **Y-T_Mode**: Graph_Panel のデフォルト表示モード。横軸を時間、縦軸を信号値とする
- **XY_Plot_Mode**: Graph_Panel の表示モード。横軸に任意の Signal を割り当て、2 信号間の関係をプロットする

## Requirements

### Requirement 1: ドッキングウィンドウシステム

**User Story:** テストエンジニアとして、解析作業に合わせて画面構成を自由にカスタマイズしたい。これにより作業効率を最大化できる。

#### Acceptance Criteria

1. THE GUI_Application SHALL QDockWidget ベースのドッキングウィンドウシステムを採用し、Channel_Browser および Graph_Area を独立した Dock_Widget として提供する
2. THE Dock_Widget SHALL ドラッグ操作によりメインウィンドウ内の任意の位置にドッキング（上下左右・タブ化）可能とする
3. THE Dock_Widget SHALL メインウィンドウから切り離してフローティングウィンドウとして表示可能とする
4. THE Dock_Widget SHALL 分割表示（水平・垂直）により複数パネルを同時に表示可能とする
5. WHEN ユーザーがパネルを閉じた場合、THE GUI_Application SHALL メニューまたはショートカットから再表示可能とする
6. THE GUI_Application SHALL Data_Explorer、Formula_Editor、Script_Console をツールバーのボタンから呼び出される独立したウィンドウ（QDialog または QMainWindow）として提供する

### Requirement 2: レイアウトテンプレートの保存・復元

**User Story:** テスト設計者として、構築したウィンドウ配置やグラフ設定を保存し、特定のテスト環境を即座に復元したい。これにより繰り返し作業の準備時間を削減できる。

#### Acceptance Criteria

1. THE GUI_Application SHALL 現在の Workspace 構成（Dock_Widget の配置・サイズ・表示状態、Graph_Area のタブ構成・表示信号・各信号の表示色・Y軸割り当て、各 Graph_Panel の X 軸・Y 軸表示範囲、読み込み済みファイルパス一覧）を Layout_Template として保存する機能を提供する
2. THE GUI_Application SHALL Layout_Template を JSON ファイルとして永続化する
3. WHEN ユーザーが Layout_Template の読み込みを指示した場合、THE GUI_Application SHALL 保存されたファイルパスから Session 経由でファイルを再読み込みし、Workspace 構成（ウィンドウ配置・グラフ表示・表示範囲）を復元する
4. IF Layout_Template に記録されたファイルパスが存在しない場合、THEN THE GUI_Application SHALL 該当ファイルの読み込みをスキップし、読み込み失敗したファイル名をユーザーに通知する
5. THE GUI_Application SHALL Layout_Template の一覧表示・選択・削除機能を提供する
6. WHEN Layout_Template が正常に保存された場合、THE GUI_Application SHALL 再読み込み時に元の構成と同一のレイアウトを復元する（ラウンドトリップ特性）

### Requirement 3: データエクスプローラー

**User Story:** テストエンジニアとして、ローカルフォルダやネットワークドライブをデータソースとして登録し、解析対象ファイルを効率的に管理したい。これにより散在するログファイルを一元的に把握できる。

#### Acceptance Criteria

1. WHEN ユーザーがローカルフォルダパスをデータソースとして登録した場合、THE Data_Explorer SHALL 登録完了と同時にツリービューにフォルダ構造を表示する
2. THE Data_Explorer SHALL 登録済みデータソース内のファイルをフォーマット種別（CAN, XCP, Ethernet, CSV）のアイコンで識別可能に表示する
3. WHEN ユーザーがデータソース内のファイルをダブルクリックした場合、THE Data_Explorer SHALL Session 経由でファイルを読み込み、Channel_Browser に信号一覧を表示する
4. THE Data_Explorer SHALL ダブルクリック、コンテキストメニュー、およびキーボードショートカット（Enter キー）によるファイル読み込みを受け付ける
5. THE Data_Explorer SHALL データソースの追加・削除機能を提供する
6. THE Data_Explorer SHALL 登録済みデータソースを次回起動時にも保持する（永続化）
7. THE Data_Explorer SHALL OS のファイルマネージャからのドラッグ＆ドロップによるファイル読み込みを受け付ける

### Requirement 4: チャネルブラウザ

**User Story:** テストエンジニアとして、読み込んだファイル内の信号を階層的に閲覧し、目的の信号を素早く見つけたい。これにより数千の信号から必要なデータを効率的に選択できる。

#### Acceptance Criteria

1. THE Channel_Browser SHALL 読み込み済みファイルの信号を階層ツリー（ソースファイル＞信号名）で表示する
2. THE Channel_Browser SHALL 各信号にデータ型・サンプル数・時間範囲のメタ情報を表示する
3. WHEN ユーザーが信号をダブルクリックした場合、THE Channel_Browser SHALL 簡易波形プレビューをポップアップ表示する
4. THE Channel_Browser SHALL インクリメンタルサーチ（テキスト入力に応じたリアルタイム絞り込み）機能を提供する
5. THE Channel_Browser SHALL 信号をドラッグして Graph_Panel にドロップすることで波形表示を追加する操作を提供する
6. THE Channel_Browser SHALL 複数信号の同時選択（Ctrl+クリック、Shift+クリック）とまとめてのドラッグ＆ドロップを提供する
7. THE Channel_Browser SHALL 各信号に対して表示/非表示のトグルスイッチを提供する

### Requirement 5: グラフ表示領域のタブ管理

**User Story:** テストエンジニアとして、複数のグラフ表示領域をタブで切り替えたい。これにより異なる解析ビューを素早く切り替えて比較分析できる。

#### Acceptance Criteria

1. THE GUI_Application SHALL タブ切り替え可能な複数の Graph_Area を提供する
2. WHEN ユーザーがタブ追加操作を行った場合、THE GUI_Application SHALL 新しい空の Graph_Area タブを作成し、アクティブタブとして表示する
3. WHEN ユーザーがタブ削除操作を行った場合、THE GUI_Application SHALL 対象タブとその内部の全 Graph_Panel を削除する
4. THE GUI_Application SHALL 各タブにユーザーが編集可能な名前（1〜32 文字）を表示する
5. WHEN ユーザーがタブを切り替えた場合、THE GUI_Application SHALL 切り替え先タブの Graph_Area を 100ms 以内に表示する
6. WHEN ユーザーが最後の 1 つのタブに対して削除操作を行った場合、THE GUI_Application SHALL 削除を拒否し、ユーザーに通知する

### Requirement 6: グラフパネルの分割表示

**User Story:** テストエンジニアとして、1 つの Graph_Area 内に複数のグラフパネルを並べて表示したい。これにより関連する信号を同時に視認しながら比較分析できる。

#### Acceptance Criteria

1. THE Graph_Area SHALL 垂直方向の分割により複数の Graph_Panel を同時表示する
2. WHEN ユーザーがパネル追加操作を行った場合、THE Graph_Area SHALL 新しい Graph_Panel を既存パネルの下に追加する
3. WHEN ユーザーがパネル削除操作を行った場合、THE Graph_Area SHALL 対象パネルを削除し、残りのパネルが利用可能な領域を均等に再分配する
4. THE Graph_Area SHALL パネル間の境界をドラッグすることで各パネルの高さ比率を変更可能とする
5. THE Graph_Area SHALL 1 つの Graph_Area 内に最大 8 個の Graph_Panel を配置可能とする
6. WHEN Graph_Area 内のパネル数が 1 の場合、THE Graph_Area SHALL パネル削除操作を拒否する

### Requirement 7: 時間軸同期（Synchronized X-Axis）

**User Story:** テストエンジニアとして、複数のグラフパネルの X 軸（時間軸）を連動させたい。これにより異なるパネルに表示した信号の同一時刻の状態を正確に比較できる。

#### Acceptance Criteria

1. WHILE 同一 Graph_Area 内に複数の Graph_Panel が存在する間、THE Graph_Area SHALL 全パネルの X 軸表示範囲を同期する
2. WHEN いずれかの Graph_Panel で X 軸のズーム・パン操作が行われた場合、THE Graph_Area SHALL 同一 Graph_Area 内の全 Graph_Panel の X 軸表示範囲を同一に更新する
3. THE Graph_Area SHALL X 軸同期の有効/無効をユーザーが切り替え可能とする
4. WHEN X 軸同期が無効化された場合、THE Graph_Panel SHALL 各パネルが独立した X 軸表示範囲を持つ

### Requirement 8: 波形グラフ表示

**User Story:** テストエンジニアとして、信号データを時系列の折れ線グラフ（波形）として表示したい。これにより信号の時間変化を視覚的に把握できる。

#### Acceptance Criteria

1. WHEN ユーザーが Signal を Graph_Panel に追加した場合、THE Waveform_View SHALL デフォルトで横軸を時間（秒）、縦軸を信号値とする折れ線グラフ（Y-T モード）を描画する
2. THE Waveform_View SHALL 1 つの Graph_Panel 上に複数の Signal を重ね合わせて描画する（オーバーレイ表示）
3. THE Waveform_View SHALL 各 Signal を視覚的に区別可能な異なる色で描画する
4. THE Waveform_View SHALL 各 Signal の凡例（信号名と対応する色）を Graph_Panel 内に表示する
5. WHEN Signal のデータが空（サンプル数 0）の場合、THE Waveform_View SHALL 空のグラフ領域を表示し、凡例に信号名を表示する
6. THE Graph_Panel SHALL 複数の独立した Y 軸を動的に追加可能とし、各 Y 軸は個別の表示範囲・スケールを持つ
7. THE Graph_Panel SHALL 1 つの Y 軸に複数の Signal を割り当て可能とする（共通軸）。共通軸に割り当てられた全 Signal は同一の表示範囲・スケールを共有し、いずれかの Signal に対するズーム・パン操作が共通軸上の全 Signal に反映される
8. WHEN ユーザーが新しい Y 軸の追加を指示した場合、THE Graph_Panel SHALL 新しい Y 軸を作成し、指定された Signal をその Y 軸に関連付ける。Y 軸が 1 つの場合はグラフ描画領域の全高で表示し、複数の Y 軸が存在する場合は各 Y 軸を個別の軸として作成する
9. WHEN ユーザーが Signal を既存の Y 軸にドラッグ＆ドロップした場合、THE Graph_Panel SHALL その Signal を既存 Y 軸の共通軸として追加割り当てする
10. THE Graph_Panel SHALL 各 Y 軸の高さ比率を個別に変更可能とする。ユーザーは Y 軸間の境界をドラッグすることで各 Y 軸が占めるグラフ描画領域内の垂直方向の比率（例: 1/2, 1/3, 1/6）を調整できる
11. THE Graph_Panel SHALL 各 Y 軸に紐づく Signal の波形描画領域を、その Y 軸が占める垂直方向の比率と位置に追従させる。Y 軸がグラフ描画領域の下半分に配置された場合、波形のクリッピング領域もグラフ描画領域の下半分となる
12. THE Graph_Panel SHALL 各 Y 軸の水平方向の幅（ラベル・目盛り表示領域）をドラッグ操作で変更可能とする
13. THE Graph_Panel SHALL Y 軸を Graph_Area 内で自由に配置変更可能とする。Y 軸はドラッグ操作により、所属する Graph_Panel の左側・右側、および同一 Graph_Area 内の他の Graph_Panel の横にも配置可能とする
14. WHEN Y 軸の垂直位置が変更された場合、THE Graph_Panel SHALL Y 軸に紐づく波形の描画位置をリアルタイムで追従させる
15. THE Graph_Panel SHALL Y-T モード（デフォルト: 横軸=時間）と X-Y プロットモード（横軸=任意の Signal）の 2 つの表示モードを提供する
16. WHEN ユーザーが新しい Graph_Panel を作成した場合、THE GUI_Application SHALL Y-T モードと X-Y プロットモードの選択をユーザーに確認する
17. WHEN X-Y プロットモードが選択された場合、THE GUI_Application SHALL X 軸に割り当てる Signal の指定をユーザーに求め、指定された Signal を横軸として描画する
18. WHILE Graph_Panel が X-Y プロットモードである間、THE Waveform_View SHALL X 軸の Signal と Y 軸の各 Signal を対応するインデックスでプロットする

### Requirement 9: テーブル表示

**User Story:** テストエンジニアとして、信号の数値データを表形式で確認したい。これにより特定時刻の正確な値を読み取れる。

#### Acceptance Criteria

1. WHEN ユーザーがテーブル表示モードを選択した場合、THE Table_View SHALL 選択された Signal のタイムスタンプと値を行ごとに表示する
2. THE Table_View SHALL 複数の Signal を列方向に並べて同時表示する
3. THE Table_View SHALL タイムスタンプ列を第 1 列として固定し、水平スクロール時も常に表示する
4. THE Table_View SHALL 垂直スクロールにより全サンプルを閲覧可能とする
5. WHEN Global_Cursor が設定されている場合、THE Table_View SHALL Cursor 位置に最も近いサンプル行をハイライト表示する
6. IF 表示対象の Signal のサンプル数が 1000 を超える場合、THEN THE Table_View SHALL 先頭 1000 ポイントのみ表示するか全データを表示するかの確認ダイアログをユーザーに表示し、選択に従って表示する

### Requirement 10: 棒グラフ表示

**User Story:** テストエンジニアとして、信号データを棒グラフとして表示したい。これにより離散的なデータの比較や分布の把握に利用できる。

#### Acceptance Criteria

1. WHEN ユーザーが棒グラフ表示モードを選択した場合、THE Bar_Chart_View SHALL 選択された Signal のデータを棒グラフとして描画する
2. THE Bar_Chart_View SHALL 複数の Signal を並列棒グラフとして同一グラフ上に表示する
3. THE Bar_Chart_View SHALL 各 Signal を視覚的に区別可能な異なる色で描画する
4. THE Bar_Chart_View SHALL 横軸ラベルと縦軸ラベルを表示する

### Requirement 11: コンタープロット表示

**User Story:** テストエンジニアとして、2 次元のカラーマップ（コンタープロット）で信号間の関係を可視化したい。これにより時間軸に限定されない 2 変数間の相関を視覚的に分析できる。

#### Acceptance Criteria

1. WHEN ユーザーがコンタープロット表示モードを選択した場合、THE Contour_View SHALL X 軸・Y 軸・色値（Z 軸）にそれぞれ Signal を割り当てた 2D カラーマップを描画する
2. THE Contour_View SHALL X 軸に時間以外の Signal を割り当て可能とする
3. THE Contour_View SHALL カラーバー（色と値の対応表）を表示する
4. THE Contour_View SHALL カラーマップの色スケール範囲をユーザーが手動で設定可能とする
5. IF X 軸・Y 軸・Z 軸に割り当てられた Signal のサンプル数が異なる場合、THEN THE Contour_View SHALL 最も短い Signal のサンプル数に合わせてデータを切り詰め、切り詰めが発生した旨をユーザーに通知する

### Requirement 12: X 軸ズーム・パン操作

**User Story:** テストエンジニアとして、グラフの X 軸（時間軸）をドラッグ操作でズーム・パンしたい。これにより注目したい時間範囲を直感的に拡大・移動できる。

#### Acceptance Criteria

1. THE Graph_Panel SHALL X 軸領域を内側ゾーン（グラフ描画領域に近い側）と外側ゾーン（ウィンドウ端に近い側）に分割する
2. WHEN ユーザーが X 軸の内側ゾーンで水平方向にドラッグした場合、THE Graph_Panel SHALL ドラッグ開始地点と終了地点の X 軸上の値を新しい表示範囲の左端・右端として設定する（範囲選択方式のズーム）
3. WHEN ユーザーが X 軸の外側ゾーンで水平方向にドラッグした場合、THE Graph_Panel SHALL ドラッグ方向と距離に応じて X 軸の表示範囲をパン（平行移動）する
4. WHEN ユーザーが X 軸領域上でマウスホイールを操作した場合、THE Graph_Panel SHALL ホイール方向に応じて X 軸の表示範囲をズームイン・ズームアウトする
5. THE Graph_Panel SHALL ズーム操作時にマウスカーソル位置を中心としてズームする
6. THE Graph_Panel SHALL ズーム・パン操作を 16ms 以内（60fps 相当）に画面に反映する
7. WHEN ユーザーがダブルクリックを X 軸領域上で行った場合、THE Graph_Panel SHALL X 軸の表示範囲を全データ範囲にリセットする
8. WHEN マウスカーソルが X 軸の内側ゾーンと外側ゾーンの境界を越えた場合、THE Graph_Panel SHALL ドラッグ操作開始前のホバー状態でカーソル形状を変更し、現在のゾーンに対応する操作（ズームまたはパン）を視覚的に示す

### Requirement 13: Y 軸ズーム・パン操作

**User Story:** テストエンジニアとして、グラフの Y 軸（値軸）をドラッグ操作でズーム・パンしたい。これにより注目したい値範囲を直感的に拡大・移動できる。

#### Acceptance Criteria

1. THE Graph_Panel SHALL Y 軸領域を内側ゾーン（グラフ描画領域に近い側）と外側ゾーン（ウィンドウ端に近い側）に分割する
2. WHEN ユーザーが Y 軸の内側ゾーンで垂直方向にドラッグした場合、THE Graph_Panel SHALL ドラッグ開始地点と終了地点の Y 軸上の値を新しい表示範囲の上限・下限として設定する（範囲選択方式のズーム）
3. WHEN ユーザーが Y 軸の外側ゾーンで垂直方向にドラッグした場合、THE Graph_Panel SHALL ドラッグ方向と距離に応じて Y 軸の表示範囲をパン（平行移動）する
4. WHEN ユーザーが Y 軸領域上でマウスホイールを操作した場合、THE Graph_Panel SHALL ホイール方向に応じて Y 軸の表示範囲をズームイン・ズームアウトする
5. THE Graph_Panel SHALL ズーム操作時にマウスカーソル位置を中心としてズームする
6. THE Graph_Panel SHALL ズーム・パン操作を 16ms 以内（60fps 相当）に画面に反映する
7. WHEN ユーザーがダブルクリックを Y 軸領域上で行った場合、THE Graph_Panel SHALL Y 軸の表示範囲を表示中の全 Signal の値範囲にリセットする
8. WHEN マウスカーソルが内側ゾーンと外側ゾーンの境界を越えた場合、THE Graph_Panel SHALL ドラッグ操作開始前のホバー状態でカーソル形状を変更し、現在のゾーンに対応する操作（ズームまたはパン）を視覚的に示す

### Requirement 14: ドラッグ＆ドロップによる時間オフセット設定

**User Story:** テスト設計者として、波形をドラッグして時間オフセットを直感的に設定したい。これにより視覚的なフィードバックを得ながら信号の時間位置を調整できる。

#### Acceptance Criteria

1. WHEN ユーザーが Waveform_View 上の波形を水平方向にドラッグした場合、THE GUI_Application SHALL ドラッグ距離を時間オフセット値（秒単位）に変換し、ドラッグ操作中の各フレームにおいて波形の表示位置をオフセット後の位置に移動してプレビュー表示する
2. WHEN ユーザーがドラッグを完了（ドロップ）した場合、THE GUI_Application SHALL オフセット適用対象の選択ダイアログを表示する
3. THE GUI_Application SHALL オフセット適用対象として以下の選択肢を提供する: (a) ドラッグした Signal のみ、(b) ドラッグした Signal と同一 Signal_Group 内の全 Signal
4. WHEN ユーザーが適用対象を選択した場合、THE GUI_Application SHALL Session 経由で Time_Synchronizer.apply_offset() を呼び出し、選択された Signal にオフセットを適用する
5. WHEN オフセット適用が完了した場合、THE GUI_Application SHALL 影響を受けた全 Signal の波形表示を更新する
6. WHILE ユーザーがドラッグ操作中である間、THE GUI_Application SHALL 現在のオフセット量（秒単位、小数点以下 3 桁）をツールチップとして表示する
7. IF ユーザーがドラッグ中に Escape キーを押下した場合、THEN THE GUI_Application SHALL ドラッグ操作をキャンセルし、波形の表示位置をドラッグ開始前の状態に復元する
8. IF ユーザーが適用対象の選択ダイアログをキャンセルした場合、THEN THE GUI_Application SHALL オフセットを適用せず、波形の表示位置をドラッグ開始前の状態に復元する

### Requirement 15: グローバルカーソルによる値読み取り

**User Story:** テストエンジニアとして、全グラフパネルに連動するカーソルで特定時刻の全信号値を一覧確認したい。これにより特定イベント発生時の各信号の状態を横断的に把握できる。

#### Acceptance Criteria

1. WHEN ユーザーがグラフ描画領域をクリックした場合、THE GUI_Application SHALL クリック位置の時刻に Global_Cursor（垂直線）を全 Graph_Panel に同時表示する
2. THE Graph_Panel SHALL Global_Cursor 位置における各 Signal の補間値を凡例エリアに表示する
3. THE GUI_Application SHALL Global_Cursor 位置の補間値計算を Session 経由で Interpolator に委譲する
4. THE GUI_Application SHALL 補間方式（線形補間・前値保持・最近傍）をユーザーが切り替え可能とし、選択された方式で Interpolator を呼び出す
4. WHEN ユーザーが Global_Cursor をドラッグした場合、THE GUI_Application SHALL 全 Graph_Panel の Cursor 位置をリアルタイムで同期更新し、補間値を再計算して表示する
5. IF Global_Cursor 位置が Signal のタイムスタンプ範囲外にある場合、THEN THE Graph_Panel SHALL 該当 Signal の値を「範囲外」として表示し、補間計算を行わない

### Requirement 16: デルタカーソルによる差分計測

**User Story:** テストエンジニアとして、2 点間の時間差と値差を計測したい。これにより応答時間や変化量を正確に定量化できる。

#### Acceptance Criteria

1. WHEN ユーザーがデルタカーソルモードを有効にした場合、THE Graph_Panel SHALL 2 本の垂直カーソル線を表示する
2. THE Graph_Panel SHALL 2 本の Delta_Cursor 間の時間差（Δt）を表示する
3. THE Graph_Panel SHALL 2 本の Delta_Cursor 位置における各 Signal の値差（Δy）を表示する
4. THE Graph_Panel SHALL 各 Delta_Cursor を独立してドラッグ移動可能とする
5. WHEN Delta_Cursor 位置が変更された場合、THE Graph_Panel SHALL Δt および Δy をリアルタイムで再計算して表示する
6. THE GUI_Application SHALL 最大 5 組（10 本）の Delta_Cursor ペアを同時に表示可能とする

### Requirement 17: 範囲統計表示

**User Story:** テストエンジニアとして、選択した時間範囲内の信号の統計値（平均・最大・最小等）を確認したい。これにより特定区間の信号特性を定量的に把握できる。

#### Acceptance Criteria

1. WHEN ユーザーが Delta_Cursor で時間範囲を指定した場合、THE GUI_Application SHALL 指定範囲内の各 Signal に対して統計値を計算し表示する
2. THE GUI_Application SHALL 以下の統計値を表示する: 平均値（mean）、最大値（max）、最小値（min）、標準偏差（std）、サンプル数（count）
3. THE GUI_Application SHALL 統計値の計算を Session 経由で Range_Statistics に委譲する
4. WHEN Delta_Cursor 位置が変更された場合、THE GUI_Application SHALL 統計値を再計算して表示を更新する
5. IF 指定範囲内にサンプルが存在しない Signal がある場合、THEN THE GUI_Application SHALL 該当 Signal の統計値を「データなし」として表示する

### Requirement 18: 計算バー（Calcbar）

**User Story:** テスト設計者として、選択した波形に対して回帰線や移動平均などのマクロ処理を数クリックで適用したい。これにより高度な解析を手軽に実行できる。

#### Acceptance Criteria

1. THE Calcbar SHALL 選択中の Signal に対して適用可能な処理の一覧をツールバー形式で表示する
2. THE Calcbar SHALL 以下の処理を提供する: 移動平均（ウィンドウサイズ指定）、線形回帰、微分（1 次）、積分
3. WHEN ユーザーが Calcbar の処理を選択した場合、THE Calcbar SHALL Session 経由で処理を実行し、結果を Derived_Signal として生成する
4. WHEN データ更新イベントまたはプリセット設定の適用が発生した場合、THE Calcbar SHALL 自動的に関連する処理を再実行し、Derived_Signal を更新する
5. THE Calcbar SHALL 処理結果の Derived_Signal を元の Signal と同一 Graph_Panel 上にオーバーレイ表示する
6. THE Calcbar SHALL 処理パラメータ（移動平均のウィンドウサイズ等）をダイアログで入力可能とする

### Requirement 19: Formula エディタ

**User Story:** テスト設計者として、GUI 上で Formula 式を作成・編集したい。これにより派生信号の定義を直感的に行える。

#### Acceptance Criteria

1. THE Formula_Editor SHALL Formula 式の入力用テキストエリアを提供する
2. THE Formula_Editor SHALL 入力中にリアルタイムで構文検証を行い、エラー箇所をハイライト表示する
3. THE Formula_Editor SHALL 利用可能な関数名（sin, cos, log 等）の補完候補を表示する
4. THE Formula_Editor SHALL 利用可能な Signal 名の補完候補を表示する
5. WHEN ユーザーが Formula の実行を指示した場合、IF 構文検証でエラーが検出されている状態であれば、THEN THE Formula_Editor SHALL 実行をブロックし、エラー修正を促すメッセージを表示する。IF エラーが検出されていない場合、THEN THE Formula_Editor SHALL Session 経由で Formula_Engine.evaluate() を呼び出し、Derived_Signal を生成する
6. IF Formula の評価でエラーが発生した場合、THEN THE Formula_Editor SHALL エラーメッセージをエディタ下部に表示し、エラー箇所を示す
7. THE Formula_Editor SHALL 作成済みの Formula の一覧を表示し、編集・削除操作を提供する
8. THE Formula_Editor SHALL 仮想チャネル作成（既存 Signal 間の四則・論理演算）を Formula 式として記述・実行可能とする

### Requirement 20: Python スクリプティング統合

**User Story:** テスト設計者として、GUI 内で Python スクリプトを記述・実行し、グラフや信号データをプログラム的に操作したい。これにより GUI 操作では困難な高度な解析や自動化を実現できる。

#### Acceptance Criteria

1. THE Script_Console SHALL Python コードの入力・実行が可能なエディタ領域とコンソール出力領域を提供する
2. THE Script_Console SHALL Session オブジェクトおよび読み込み済み Signal データへのプログラム的アクセス API を提供する
3. THE Script_Console SHALL スクリプトから Graph_Panel への信号追加・削除操作を可能とする
4. WHEN ユーザーがスクリプトを実行した場合、THE Script_Console SHALL 実行結果（戻り値・print 出力・エラー）をコンソール出力領域に表示する
5. IF スクリプト実行中にエラーが発生した場合、THEN THE Script_Console SHALL トレースバック情報を表示し、GUI アプリケーションの動作を継続する
6. THE Script_Console SHALL スクリプトファイル（.py）の保存・読み込み機能を提供する

### Requirement 21: 描画パフォーマンスとダウンサンプリング（LOD）

**User Story:** テストエンジニアとして、数百万ポイントの大容量時系列データでも滑らかに操作したい。これにより大規模データの解析時にも快適な操作性を維持できる。

#### Acceptance Criteria

1. THE LOD_Renderer SHALL 表示ピクセル幅に応じて動的にダウンサンプリングを行い、描画ポイント数を最適化する
2. THE LOD_Renderer SHALL 100 万サンプル以上の Signal データを 60fps 以上のフレームレートでスムーズにレンダリングする
3. THE LOD_Renderer SHALL ダウンサンプリング時に各ピクセル区間の最大値・最小値を保持し、波形の包絡線を正確に表現する（min-max ダウンサンプリング）
4. WHEN ユーザーがズームインした場合、THE LOD_Renderer SHALL 表示範囲に応じてダウンサンプリング率を動的に調整し、詳細データを表示する
5. THE GUI_Application SHALL ダウンサンプリングを Session 経由で Downsampler に委譲する
6. THE LOD_Renderer SHALL ダウンサンプリングの適用有無をユーザーに視覚的に示す（ステータスバー等）

### Requirement 22: ドラッグ＆ドロップワークフロー

**User Story:** テストエンジニアとして、マウスのみで直感的にファイル読み込みから波形表示までを完結させたい。これにより操作の学習コストを最小限に抑えられる。

#### Acceptance Criteria

1. THE GUI_Application SHALL OS のファイルマネージャから Data_Explorer または Graph_Area へのファイルドラッグ＆ドロップによる読み込みを受け付ける
2. THE Channel_Browser SHALL 信号を Graph_Panel へドラッグ＆ドロップすることで波形表示を追加する操作を提供する
3. THE Channel_Browser SHALL 複数信号を同時選択してまとめてドラッグ＆ドロップ可能とする
4. WHEN 信号が Graph_Panel にドロップされた場合、THE Waveform_View SHALL ドロップされた信号を即座に波形として描画する
5. THE GUI_Application SHALL ドラッグ中にドロップ可能な領域を視覚的にハイライト表示する

### Requirement 23: コア拡張要件 — 補間計算（Interpolator）

**User Story:** 開発者として、任意の時刻における信号値を補間計算する機能をコアに追加したい。これにより GUI のカーソル値読み取り機能を実現できる。

#### Acceptance Criteria

1. WHEN 任意の時刻 t、サンプル数 2 以上の Signal、および補間方式が指定された場合、THE Interpolator SHALL 指定された補間方式に従い値を計算する
2. THE Interpolator SHALL 以下の補間方式を提供する: 線形補間（linear）、前値保持（zero-order hold / previous）、最近傍（nearest）
3. WHEN 線形補間が指定された場合、THE Interpolator SHALL Signal のタイムスタンプ列から t を挟む隣接 2 点（t[i] ≤ t < t[i+1]）を特定し、線形補間により値を計算する
4. WHEN 前値保持が指定された場合、THE Interpolator SHALL t 以下で最大のタイムスタンプに対応するサンプル値をそのまま返す
5. WHEN 最近傍が指定された場合、THE Interpolator SHALL t に最も近いタイムスタンプに対応するサンプル値を返す
6. THE Interpolator SHALL 補間結果を float64 精度で返す
7. IF 指定時刻 t が Signal のタイムスタンプ範囲（最小値〜最大値）外にある場合、THEN THE Interpolator SHALL 補間値ではなく範囲外であることを呼び出し元が判別可能な結果（正常値と型レベルで区別できる表現）を返し、外挿計算を行わない
8. IF 指定時刻 t が Signal のタイムスタンプと完全に一致する場合、THEN THE Interpolator SHALL 補間計算を行わず、該当サンプルの値をそのまま返す
9. THE Interpolator SHALL 元の Signal を変更せず、計算結果のみを返す（入力データの不変性を維持）
10. IF Signal のサンプル数が 2 未満（0 または 1）である場合、THEN THE Interpolator SHALL 補間不可であることを呼び出し元が判別可能な結果を返し、補間計算を行わない
11. IF 補間対象の隣接 2 点のいずれかの値が NaN である場合、THEN THE Interpolator SHALL 補間結果として NaN を返す

### Requirement 24: コア拡張要件 — 範囲統計計算（Range_Statistics）

**User Story:** 開発者として、指定時間範囲内の信号統計値を計算する機能をコアに追加したい。これにより GUI の範囲統計表示機能を実現できる。

#### Acceptance Criteria

1. WHEN 時間範囲（開始時刻 t_start、終了時刻 t_end）と Signal が指定された場合、THE Range_Statistics SHALL 範囲内のサンプルに対して統計値を計算する
2. THE Range_Statistics SHALL 以下の統計値を計算する: 平均値（mean）、最大値（max）、最小値（min）、標準偏差（std、母集団標準偏差 ddof=0）、サンプル数（count）
3. THE Range_Statistics SHALL t_start ≤ timestamp ≤ t_end を満たすサンプルを計算対象とする
4. IF 指定範囲内にサンプルが 0 個の場合、THEN THE Range_Statistics SHALL サンプル数 0 と各統計値（mean, max, min, std）を NaN として返す
5. IF t_start > t_end が指定された場合、THEN THE Range_Statistics SHALL バリデーションエラーを返す
6. IF t_start または t_end に NaN または無限大が指定された場合、THEN THE Range_Statistics SHALL バリデーションエラーを返す
7. THE Range_Statistics SHALL 元の Signal を変更せず、計算結果のみを返す（入力データの不変性を維持）
8. THE Range_Statistics SHALL 統計値を float64 精度で計算する（numpy の対応関数と同等の精度）

### Requirement 25: コア拡張要件 — ダウンサンプリング（Downsampler）

**User Story:** 開発者として、描画用に大容量データを動的に間引く機能をコアに追加したい。これにより GUI の LOD レンダリング機能を実現できる。

#### Acceptance Criteria

1. WHEN Signal と目標ポイント数 n（2 以上の整数）が指定された場合、THE Downsampler SHALL Signal のサンプルを n ポイント以下に間引いた新しい Signal オブジェクトを返す
2. THE Downsampler SHALL min-max ダウンサンプリングアルゴリズムを使用し、Signal を均等な区間に分割して各区間の最小値と最大値のサンプルをタイムスタンプとともに保持する。出力ポイント数は各区間につき最大2ポイント（min, max）であり、合計は n 以下とする
3. THE Downsampler SHALL ダウンサンプリング結果のタイムスタンプが元の Signal のタイムスタンプ範囲内に収まることを保証する
4. IF Signal のサンプル数が目標ポイント数 n 以下の場合、THEN THE Downsampler SHALL 元の Signal をそのまま返す（間引きを行わない）
5. THE Downsampler SHALL 元の Signal を変更せず、Signal データモデル（タイムスタンプ列と値列のペア）に準拠した新しい Signal オブジェクトを返す（入力データの不変性を維持）
6. THE Downsampler SHALL 結果のタイムスタンプが厳密に単調増加（t[i] < t[i+1]）であることを保証する
7. IF 目標ポイント数 n が 2 未満の整数、非整数、NaN、または無限大である場合、THEN THE Downsampler SHALL バリデーションエラーを返し、ダウンサンプリングを実行しない

### Requirement 26: コア拡張要件 — Calcbar 演算（移動平均・回帰・微分・積分）

**User Story:** 開発者として、移動平均・線形回帰・微分・積分の演算機能をコアに追加したい。これにより GUI の Calcbar 機能を実現できる。

#### Acceptance Criteria

1. WHEN Signal とウィンドウサイズ w（1 以上かつ Signal の要素数以下の整数）が指定された場合、THE Session SHALL 単純移動平均（SMA: 直近 w サンプルの算術平均）を計算し、結果を Derived_Signal として返す。先頭の w-1 サンプルについては利用可能なサンプル数での算術平均を値とする（縮小ウィンドウ方式）
2. WHEN Signal が指定された場合、THE Session SHALL 線形回帰（最小二乗法）を計算し、入力 Signal と同一のタイムスタンプ列に対する回帰直線上の予測値を値列とする Derived_Signal を返す
3. WHEN Signal が指定された場合、THE Session SHALL 数値微分を計算し、結果を Derived_Signal として返す。各サンプル i における微分値は (value[i+1] - value[i-1]) / (timestamp[i+1] - timestamp[i-1]) とする（中心差分）。先頭および末尾のサンプルは前方差分・後方差分をそれぞれ適用し、出力の要素数を入力と一致させる
4. WHEN Signal が指定された場合、THE Session SHALL 累積数値積分（台形則）を計算し、結果を Derived_Signal として返す。先頭サンプルの積分値は 0.0 とし、以降のサンプル i の値は先頭から i 番目までの台形則による累積和とする
5. THE Session SHALL 各演算結果の Derived_Signal が Signal の不変条件（タイムスタンプの単調増加、タイムスタンプ列と値列の要素数が入力 Signal と一致）を満たすことを保証する
6. THE Session SHALL 元の Signal を変更せず、新しい Derived_Signal を返す（入力データの不変性を維持）
7. IF 演算対象の Signal の要素数が 2 未満である場合、THEN THE Session SHALL 演算種別と必要最小要素数を含むエラーを返し、Derived_Signal を生成しない
8. IF 移動平均のウィンドウサイズ w が 1 未満または Signal の要素数を超える場合、THEN THE Session SHALL 指定値と許容範囲を含むバリデーションエラーを返し、Derived_Signal を生成しない

### Requirement 27: GUI とコアの分離（MVVM アーキテクチャ）

**User Story:** 開発者として、GUI 層がコアロジックに直接依存せず Session 経由でのみアクセスすることを保証したい。これによりコアの変更が GUI に波及しにくい疎結合アーキテクチャを維持し、将来的なヘッドレス化やテスト自動化を容易にする。

#### Acceptance Criteria

1. THE GUI_Application SHALL MVVM パターンに基づき、View（UI コンポーネント）と ViewModel（UI ロジック）と Model（Session/コアデータ）を分離する
2. THE GUI_Application SHALL 全てのデータ操作（読み込み・同期・Formula 評価・エクスポート・補間・統計計算・ダウンサンプリング）を Session クラス経由で実行する。描画パフォーマンス最適化目的のダウンサンプリングも例外なく Session 経由とする
3. THE GUI_Application SHALL Signal および Signal_Group のデータモデルを読み取り専用で参照する（変更操作を行わない）
4. THE GUI_Application SHALL コアモジュール（loaders, sync, formula, export）を直接インポートしない
5. WHEN Session からエラーが返された場合、THE GUI_Application SHALL エラー内容をユーザーに表示し、アプリケーションの動作を継続する
6. THE GUI_Application SHALL コアの処理結果を受け取り、表示の更新のみを担当する

### Requirement 28: アプリケーション起動と初期状態

**User Story:** テストエンジニアとして、アプリケーションを起動して即座に作業を開始したい。これにより起動時の待ち時間を最小限に抑えられる。

#### Acceptance Criteria

1. WHEN アプリケーションが起動された場合、THE GUI_Application SHALL メインウィンドウを表示し、デフォルトの Workspace レイアウト（Channel_Browser、空の Graph_Area）を初期状態として提供する
2. THE GUI_Application SHALL 起動時に前回終了時の Layout_Template を自動復元する。IF 前回のレイアウトが存在しない場合、またはレイアウトファイルが破損・現バージョンと非互換である場合、THEN THE GUI_Application SHALL デフォルトレイアウトを使用する
3. WHEN アプリケーションが起動された場合、THE GUI_Application SHALL 3 秒以内にユーザー操作可能な状態となる
4. THE GUI_Application SHALL ウィンドウサイズ・位置を次回起動時に復元する

### Requirement 29: コンテキストメニュー（右クリックメニュー）

**User Story:** テストエンジニアとして、各 GUI オブジェクトを右クリックして状況に応じた操作メニューにアクセスしたい。これにより頻繁に使う操作をメニューバーを経由せず素早く実行できる。

#### Acceptance Criteria

1. WHEN ユーザーが Waveform_View 上の波形を右クリックした場合、THE GUI_Application SHALL 以下の項目を含むコンテキストメニューを表示する: 信号の削除、表示色の変更、Y 軸割り当て変更、Calcbar 処理の適用、信号プロパティ表示
2. WHEN ユーザーが Y_Axis 上を右クリックした場合、THE GUI_Application SHALL 以下の項目を含むコンテキストメニューを表示する: 表示範囲リセット、軸の削除、Signal の追加/削除、スケール設定（リニア/ログ切替）
3. WHEN ユーザーが Graph_Panel の空白領域（波形・軸以外）を右クリックした場合、THE GUI_Application SHALL 以下の項目を含むコンテキストメニューを表示する: パネル追加、パネル削除、表示モード切替（Y-T / X-Y）、全軸表示範囲リセット
4. WHEN ユーザーが Channel_Browser 内の信号項目を右クリックした場合、THE GUI_Application SHALL 以下の項目を含むコンテキストメニューを表示する: アクティブ Graph_Panel に追加、新しい Y 軸で追加、波形プレビュー表示、信号プロパティ表示
5. WHEN ユーザーが Data_Explorer 内のファイル項目を右クリックした場合、THE GUI_Application SHALL 以下の項目を含むコンテキストメニューを表示する: ファイル読み込み、ファイルパスのコピー、データソースから除外
6. WHEN ユーザーが Graph_Area のタブを右クリックした場合、THE GUI_Application SHALL 以下の項目を含むコンテキストメニューを表示する: タブ名変更、タブ複製、タブ削除
7. THE GUI_Application SHALL コンテキストメニューの各項目について、現在の状態で実行不可能な項目をグレーアウト（無効化）表示する
