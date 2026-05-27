# Requirements Document

## Introduction

ValiSync は ADAS ソフトウェア開発におけるデータ解析用スタンドアロン・デスクトップ GUI アプリケーションである。CAN・XCP・Ethernet・CSV の各フォーマットから取得した時系列信号データを統合・同期し、高速可視化による直感的な解析を提供する。テストエンジニア、テスト設計者、制御エンジニアが主要ユーザーであり、ADAS ECU 周辺の複雑なネットワーク信号を統一時間軸上で分析することを目的とする。

## Glossary

- **ValiSync**: 本アプリケーションの名称。ADAS ECU 周辺の信号データを統合・同期・可視化するデスクトップ GUI ツール
- **Signal_Loader**: 各フォーマット（MDF4, CSV）のログファイルを読み込み、内部データモデルに変換するモジュール
- **MDF4**: Measurement Data Format version 4（.mf4 ファイル）。ASAM 標準の計測データフォーマット。CAN・XCP・Ethernet 等の複数プロトコルの信号データを単一ファイルに格納する
- **asammdf**: MDF4 ファイルの読み書きに使用する Python ライブラリ。チャンネルグループのメタデータからプロトコル種別を判定可能
- **Time_Synchronizer**: 異なるフォーマット・周期のタイムスタンプを統一時間軸上に同期するモジュール
- **Unified_Timeline**: 全フォーマットの信号を同一の時間基準で表現する統一時間軸
- **Signal**: 時系列のサンプル値（タイムスタンプと値のペアの列）を持つデータ単位。読み込み後は不変（immutable）である
- **Signal_Group**: 同一ファイルから読み込まれた Signal の集合。ファイル単位で管理される
- **Format_Definition**: CSV ファイルの列構成・区切り文字・タイムスタンプ形式等を定義するユーザー設定
- **Formula**: Signal に対して適用する数式または関数処理。入力として 1 つ以上の Signal を受け取り、新しい派生 Signal を生成する
- **Derived_Signal**: Formula の適用により生成された Signal。元の Signal と同じデータモデルに従う
- **CAN**: Controller Area Network。車載ネットワークプロトコル。MDF4 ファイル内のチャンネルグループとして格納される
- **XCP**: Universal Measurement and Calibration Protocol。ECU 内部変数の計測プロトコル。MDF4 ファイル内のチャンネルグループとして格納される
- **Ethernet**: 車載 Ethernet 通信プロトコル。MDF4 ファイル内のチャンネルグループとして格納される
- **CSV**: Comma-Separated Values。汎用的な時系列データ交換フォーマット
- **Interpolator**: 任意の時刻における信号値を補間計算するモジュール。線形補間・前値保持・最近傍の 3 方式を提供する
- **Range_Statistics**: 指定時間範囲内の統計値（平均・最大・最小・標準偏差・サンプル数）を計算するモジュール
- **Downsampler**: 描画用に大容量データを動的に間引くモジュール。min-max ダウンサンプリングにより波形の包絡線を保持する

## Requirements

### Requirement 1: MDF4 信号データの読み込み

**User Story:** テストエンジニアとして、MDF4 ログファイルを読み込みたい。これにより CAN・XCP・Ethernet の全プロトコルの信号データを一括で解析対象として利用できる。

#### Acceptance Criteria

1. WHEN MDF4 ファイル（.mf4）が指定された場合、THE Signal_Loader SHALL asammdf ライブラリを使用してファイルを解析し、全チャンネルグループから Signal オブジェクトのリストを一括生成する
2. THE Signal_Loader SHALL asammdf の読み込み時に元データの改ざんを防ぐため、time_from_zero=False 等のオプションを使用し、タイムスタンプおよび信号値を元ファイルに記録された生の値のまま読み込む。また、メモリ消費量削減およびプロット時の数値処理を優先するため ignore_value2text_conversions=True を使用し、値を数値型（float64）として取得する（テキスト変換テーブルはメタデータとして別途保持する）
3. THE Signal_Loader SHALL 各 Signal に対してタイムスタンプ（秒単位に統一、float64 精度）、信号名（最大256文字）、数値（float64）を numpy 配列として保持する。IF 元データのタイムスタンプがミリ秒単位である場合、THEN THE Signal_Loader SHALL 読み込み時に 1/1000 を乗じて秒単位に変換する
4. THE Signal_Loader SHALL MDF4 ファイル内の各チャンネルグループのメタデータからプロトコル種別（CAN, XCP, Ethernet）を判定し、各 Signal の source_format フィールドに記録する
5. THE Signal_Loader SHALL asammdf から取得可能な信号プロパティ（単位、コメント、サンプリングレート、チャンネルグループ名、ソースバス種別、物理値/RAW値の変換情報等）を Signal のメタデータとして保持し、GUI から参照可能とする
6. IF MDF4 ファイルのフォーマットが不正である場合、THEN THE Signal_Loader SHALL 読み込みを拒否し、エラー内容を含む診断メッセージを返す
7. WHEN MDF4 ファイルが正常に読み込まれた場合、THE Signal_Loader SHALL 内部表現から元のファイルと意味的に等価なデータを再構成可能とする（ラウンドトリップ特性：全タイムスタンプと信号値が元データと一致すること）
8. IF 指定された MDF4 ファイルが存在しないまたは読み取り不可である場合、THEN THE Signal_Loader SHALL ファイルパスと原因を含むエラーを返す
9. WHEN MDF4 ファイルが有効なフォーマットだが信号データを含まない場合、THE Signal_Loader SHALL エラーメッセージを伴わず空の Signal リスト（要素数 0）を返す
10. IF 同一ファイル内に同名の信号が複数存在する場合、THEN THE Signal_Loader SHALL 各出現を独立した Signal として保持し、出現順のインデックスを付与して一意に識別可能とする

### Requirement 2: CSV 時系列データの読み込み

**User Story:** テストエンジニアとして、汎用 CSV フォーマットの時系列データを読み込みたい。これにより外部ツールで生成されたデータや手動作成のテストデータも解析対象として利用できる。

#### Acceptance Criteria

1. WHEN CSV ファイルと Format_Definition が指定された場合、THE Signal_Loader SHALL Format_Definition に従いファイルを解析し Signal オブジェクトのリストを生成する
2. THE Signal_Loader SHALL Format_Definition で指定されたタイムスタンプ列と信号チャンネル列に基づきデータを解釈する
3. IF Format_Definition でヘッダー行ありと指定されている場合、THEN THE Signal_Loader SHALL ヘッダー行の値を信号名として使用する
4. IF Format_Definition でヘッダー行なしと指定されている場合、THEN THE Signal_Loader SHALL 列番号に基づく連番名（"ch_1", "ch_2", ...）を信号名として割り当てる
5. IF CSV ファイルのフォーマットが Format_Definition と一致しない場合、THEN THE Signal_Loader SHALL 不正箇所の行番号とエラー内容を含む診断メッセージを返し、読み込み処理を中断する
6. IF CSV の数値フィールドに非数値データが含まれる場合、THEN THE Signal_Loader SHALL 該当セルの行番号・列番号を含むエラーを返し、読み込み処理を中断する
7. WHEN CSV ファイルが正常に読み込まれた場合、THE Signal_Loader SHALL 浮動小数点値を IEEE 754 倍精度で保持し、再出力時に元ファイルの数値と有効桁15桁以内で一致する内部表現を生成する（ラウンドトリップ特性）
8. WHEN データ行が0行の CSV ファイルが指定された場合、THE Signal_Loader SHALL 各信号チャンネルに対して要素数0の空 Signal オブジェクトを生成する

### Requirement 3: CSV フォーマット定義の管理

**User Story:** テスト設計者として、様々なツールから出力される CSV フォーマットに対応するため、フォーマット定義を GUI 上で設定・保存したい。これにより新しいツールのデータも追加設定のみで読み込み可能となる。

#### Acceptance Criteria

1. THE ValiSync SHALL Format_Definition の作成・編集・削除機能を GUI 上で提供する
2. THE Format_Definition SHALL 以下の設定項目を含む: 定義名（1〜64 文字の一意な識別名）、区切り文字（カンマ・タブ・セミコロン・スペースのいずれか）、タイムスタンプ列の位置（0 始まりの列インデックス、0〜255）、タイムスタンプの単位（sec または msec。タイムスタンプ列は数値型として直接パースする）、信号データ列の範囲（開始列インデックスと終了列インデックスの連続範囲、各 0〜255）、ヘッダー行の有無（真偽値）、単位行の有無（真偽値、ヘッダー行の直後に各列の単位を記載した行が存在するか）。IF タイムスタンプの単位が msec と指定されている場合、THEN THE Signal_Loader SHALL 読み込み時に 1/1000 を乗じて秒単位に変換する。IF 単位行ありと指定されている場合、THEN THE Signal_Loader SHALL 単位行の値を各 Signal の metadata に unit として格納する
3. WHEN ユーザーが Format_Definition を保存した場合、THE ValiSync SHALL data/ ディレクトリ内に JSON ファイルとして永続化し、次回起動時にも利用可能とする
4. THE ValiSync SHALL 保存済みの Format_Definition の一覧を定義名で表示し、CSV 読み込み時に選択可能とする
5. WHEN Format_Definition が正常に保存された場合、THE ValiSync SHALL 保存内容を再読み込みし元の設定と全フィールドが一致することを保証する（ラウンドトリップ特性）
6. IF Format_Definition の設定値が不正である場合（定義名が空・重複、列インデックスが範囲外、タイムスタンプ列が信号データ列の範囲と重複）、THEN THE ValiSync SHALL バリデーションエラーを返し保存を拒否する
7. IF 既に同名の Format_Definition が存在する状態で新規保存が試行された場合、THEN THE ValiSync SHALL 名前の重複を示すエラーを返し保存を拒否する

### Requirement 4: ファイル単位の Signal 管理

**User Story:** テストエンジニアとして、同一の測定環境で計測した複数のファイルを読み込む際に、Signal をファイル単位で管理したい。これによりファイルごとのデータの出所を明確に追跡できる。

#### Acceptance Criteria

1. THE Signal_Loader SHALL 読み込んだ Signal をファイル単位の Signal_Group として管理する
2. THE Signal_Loader SHALL 各 Signal_Group にソースファイルの絶対パス、フォーマット種別（CAN, XCP, Ethernet, CSV のいずれか）、読み込み日時（秒精度）を関連付けて保持する
3. WHEN 同一フォーマットの複数ファイルが読み込まれた場合、THE Signal_Loader SHALL 各ファイルを独立した Signal_Group として管理する
4. THE ValiSync SHALL Signal_Group 単位でのファイル追加・削除操作を提供する
5. IF Signal_Group の削除対象に含まれる Signal が Derived_Signal の入力として参照されている場合、THEN THE ValiSync SHALL 依存関係を示す警告をユーザーに提示し、削除の確認を求める。IF いずれの Derived_Signal からも参照されていない場合、THEN THE ValiSync SHALL 確認なしで即座に削除を実行する
6. THE ValiSync SHALL 読み込んだファイルごとにフォーマット種別の略称とフォーマット別連番を組み合わせた一意なキー（例: `mf4_1`, `csv_2`）を割り当て、各 Signal 名にキーを区切り文字 `::` とともに接頭辞として付与し（例: `mf4_1::speed`）、ファイル間で同名の信号が存在しても一意に識別可能とする。キーの連番はファイル削除後も再利用しない
7. WHEN 既に読み込み済みのファイルと同一パスのファイルが再度指定された場合、THE ValiSync SHALL 重複読み込みを許可し、各読み込みに一意なキーを割り当てて独立した Signal_Group として管理する

### Requirement 5: 複数フォーマットの統合表示

**User Story:** テストエンジニアとして、CAN・XCP・Ethernet・CSV の異なるフォーマットのファイルを同時に読み込み、同一グラフ上で統合的に表示したい。これにより異なる計測ツールで取得したデータを一元的に分析できる。

#### Acceptance Criteria

1. WHEN 異なるフォーマットの複数ファイルが読み込まれた場合、THE Signal_Loader SHALL 全ファイルの Signal を同一の Signal データモデル（タイムスタンプ配列と値配列のペア）に変換し、フォーマット間でデータ構造の差異がない状態で出力する
2. THE ValiSync SHALL フォーマットの違いに関わらず全 Signal を単一の Signal コレクションとして保持し、フォーマット種別による区別なく一覧取得・フィルタリング・可視化対象選択を可能とする
3. THE Signal_Loader SHALL 各 Signal のメタデータとしてソースフォーマット種別（CAN, XCP, Ethernet, CSV のいずれか）およびソースファイルパスを保持する
4. IF 複数ファイルの一括読み込み中に一部のファイルで読み込みエラーが発生した場合、THEN THE Signal_Loader SHALL 正常に読み込めたファイルの Signal を利用可能とし、失敗したファイルごとにエラー内容を報告する

### Requirement 6: 入力データの不変性保証

**User Story:** テストエンジニアとして、読み込んだ元データが一切改ざんされないことを保証したい。これにより解析結果の信頼性とトレーサビリティを確保できる。

#### Acceptance Criteria

1. THE Signal_Loader SHALL 読み込み元のファイルを読み取り専用モードで開き、書き込み操作を一切行わない
2. THE Signal SHALL 生成後にタイムスタンプ列およびデータ値列の変更を許容しない（immutable）
3. IF Signal のタイムスタンプ列またはデータ値列に対して変更操作が試行された場合、THEN THE Signal SHALL 例外を発生させ変更を拒否する
4. WHEN 同期処理が実行された場合、THE Time_Synchronizer SHALL 元の Signal を変更せず、新しい Signal オブジェクトを生成する
5. WHILE 解析セッションが継続している間、THE ValiSync SHALL 入力ファイルの内容を変更する機能を提供しない
6. IF 外部プロセスにより入力ファイルが変更された場合、THEN THE ValiSync SHALL 変更を検出次第即座にユーザーに通知し再読み込みの選択肢を提示する（連続する変更に対してもデバウンスせず個別に通知する）

### Requirement 7: CSV エクスポート

**User Story:** テストエンジニアとして、解析対象の Signal データを CSV ファイルとしてエクスポートしたい。これにより他のツールでの二次解析やレポート作成に利用できる。

#### Acceptance Criteria

1. WHEN ユーザーがエクスポート対象の Signal を1つ以上選択した場合、THE ValiSync SHALL 選択された全 Signal を単一の CSV ファイルとして出力する
2. THE ValiSync SHALL エクスポート時にタイムスタンプ列を第1列、各信号値を後続列として出力し、区切り文字はカンマとする
3. THE ValiSync SHALL エクスポート時にヘッダー行として第1列にタイムスタンプ列名、後続列に各信号名を出力する
4. WHEN 同期済みの Unified_Timeline 上のタイムスタンプでエクスポートが選択された場合、THE ValiSync SHALL 全 Signal を Unified_Timeline のタイムスタンプに揃えて出力し、該当タイムスタンプにサンプル値が存在しない Signal のセルは空文字とする
5. THE ValiSync SHALL Derived_Signal も元の Signal と同様にエクスポート可能とする
6. WHEN エクスポートされた CSV ファイルを再度読み込んだ場合、THE Signal_Loader SHALL 元の Signal と等価なデータを復元する（ラウンドトリップ特性）。等価とは、タイムスタンプおよび値の各要素が IEEE 754 倍精度浮動小数点の有効桁数（17桁）以内で一致することを指す
7. IF エクスポート先のファイル書き込みに失敗した場合、THEN THE ValiSync SHALL エラー原因を含む診断メッセージをユーザーに提示し、不完全なファイルを残さない

### Requirement 8: マルチフォーマット時刻同期

**User Story:** テストエンジニアとして、異なる周期・フォーマットの信号を統一時間軸上で正確に同期させたい。これにより複数フォーマットにまたがる信号の因果関係を正しく分析できる。

#### Acceptance Criteria

1. WHEN 2つ以上の異なるフォーマットを含む Signal_Group が入力された場合、THE Time_Synchronizer SHALL 全 Signal を Unified_Timeline 上に配置する
2. THE Time_Synchronizer SHALL 各 Signal の元のタイムスタンプ値を浮動小数点演算の丸め誤差（1 ULP）以内の差で統一時間軸上に変換する
3. THE Time_Synchronizer SHALL 異なるサンプリング周期の Signal 間において、同期前に時間的に先行していたサンプルが同期後も先行する関係を保存する（Signal 間の相対順序保存）
4. WHEN 同期処理が完了した場合、THE Time_Synchronizer SHALL 同期前後で各 Signal のサンプル数を変更しない
5. ~~時間ジャンプ検出~~ （スコープ外として削除）
6. THE Time_Synchronizer SHALL 同期後の各 Signal 内のタイムスタンプ列が同期前と同一の単調増加順序を維持することを保証する（単調性の保存）

### Requirement 9: 時間オフセットの設定

**User Story:** テスト設計者として、ファイル単位または信号単位で任意の時間オフセットを設定したい。これにより異なる計測セッションのデータを共通の基準で比較したり、既知の遅延を補正できる。

#### Acceptance Criteria

1. WHEN ユーザーがファイル単位の時間オフセットを秒単位の浮動小数点数で指定した場合、THE Time_Synchronizer SHALL 該当ファイルから読み込まれた全 Signal のタイムスタンプにオフセットを加算する。WHEN ファイル単位のオフセットが指定されていない場合、THE Time_Synchronizer SHALL タイムスタンプを変更しない
2. WHEN ユーザーが信号単位の時間オフセットを秒単位の浮動小数点数で指定した場合、THE Time_Synchronizer SHALL 該当 Signal のタイムスタンプにオフセットを加算する。WHEN 信号単位のオフセットが指定されていない場合、THE Time_Synchronizer SHALL タイムスタンプを変更しない
3. THE Time_Synchronizer SHALL 正および負のオフセット値（秒単位、IEEE 754 倍精度浮動小数点の有限値）を許容する
4. THE Time_Synchronizer SHALL オフセット適用後も各 Signal 内の連続するサンプル間の時間差を元の Signal と同一に保存する（間隔保存特性）
5. WHEN ファイル単位と信号単位の両方のオフセットが指定された場合、THE Time_Synchronizer SHALL 両オフセットを合算して適用する。WHEN いずれか一方のみが指定された場合、THE Time_Synchronizer SHALL 指定された単一のオフセットを適用する
6. IF オフセット適用後にタイムスタンプが負の値となる場合、THEN THE Time_Synchronizer SHALL 負のタイムスタンプを有効な値として許容する
7. THE Time_Synchronizer SHALL オフセットを Unified_Timeline への同期処理の前に適用する
8. IF オフセット値として NaN または無限大が指定された場合、THEN THE Time_Synchronizer SHALL バリデーションエラーを返し、オフセットを適用しない

### Requirement 10: Formula（計算式）の適用

**User Story:** テスト設計者として、読み込んだ信号に対して数式や関数処理を適用し、派生信号を生成したい。これにより物理量の変換や複数信号の演算結果を解析対象に追加できる。

#### Acceptance Criteria

1. WHEN ユーザーが Formula と対象 Signal を指定した場合、THE ValiSync SHALL まず Formula の構文を検証し、構文が有効な場合にのみ Formula を適用して Derived_Signal を生成する
2. THE Formula SHALL 四則演算（加算・減算・乗算・除算）、三角関数（sin, cos, tan, asin, acos, atan）、対数（log, log10）、絶対値（abs）、平方根（sqrt）、累乗（pow）を提供する
3. WHEN 複数の Signal を入力とする Formula が指定された場合、THE ValiSync SHALL 全入力 Signal のタイムスタンプ列の共通区間（全 Signal にサンプルが存在する時間範囲の積集合）を演算対象とし、各 Signal の元のサンプル時刻における値を用いて演算する
4. WHEN Formula の入力として Derived_Signal が指定された場合、THE ValiSync SHALL 最大 100 階層までの入れ子処理を実行する
5. THE Derived_Signal SHALL 元の Signal と同一のデータモデル（タイムスタンプ列と値列のペア）に従う
6. THE Derived_Signal SHALL 元の Signal と同様に ValiSync の可視化機能で描画可能なデータ構造に従う
7. IF Formula の演算でゼロ除算、負数の対数、負数の平方根、または定義域外の逆三角関数入力が発生した場合、THEN THE ValiSync SHALL 該当サンプルを NaN として記録し、NaN が発生したサンプル数と演算種別を含む警告を報告する
8. THE Formula SHALL 元の入力 Signal を変更せず、新しい Derived_Signal を生成する（入力データの不変性を維持）
9. IF Formula の式が構文エラーまたは未定義の関数名を含む場合、THEN THE ValiSync SHALL Derived_Signal を生成せず、エラー箇所を示すエラーメッセージを返す
10. IF Formula の入れ子が 100 階層を超えた場合、THEN THE ValiSync SHALL 処理を中止し、入れ子の深さ上限超過を示すエラーメッセージを返す

### Requirement 11: Signal データモデルの整合性

**User Story:** 開発者として、Signal データモデルが常に整合性を保つことを保証したい。これによりデータ処理パイプライン全体の信頼性を確保できる。

#### Acceptance Criteria

1. THE Signal SHALL タイムスタンプ列の全要素が有限値（NaN および Inf を含まない）であり、かつ厳密に単調増加（t[i] < t[i+1]）であることを保証する
2. THE Signal SHALL タイムスタンプ列とデータ値列の要素数が常に一致することを保証する
3. THE Signal SHALL タイムスタンプ列とデータ値列の両方が要素数 0 である場合を有効な空状態として許容する（一方のみが空で他方が非空の場合は要素数不一致エラーとする）
4. IF タイムスタンプが単調増加でないデータが入力された場合、THEN THE Signal_Loader SHALL 最初に違反が検出されたインデックス位置を含むバリデーションエラーを返す
5. IF タイムスタンプ列とデータ値列の要素数が一致しないデータで Signal が生成された場合、THEN THE Signal SHALL 両配列の要素数を含むバリデーションエラーを送出する
6. IF タイムスタンプ列に NaN または Inf が含まれるデータが入力された場合、THEN THE Signal_Loader SHALL 該当インデックス位置を含むバリデーションエラーを返す

### Requirement 12: 補間計算（Interpolator）

**User Story:** 開発者として、任意の時刻における信号値を補間計算する機能を提供したい。これにより GUI のカーソル値読み取り機能を実現できる。

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

### Requirement 13: 範囲統計計算（Range_Statistics）

**User Story:** 開発者として、指定時間範囲内の信号統計値を計算する機能を提供したい。これにより GUI の範囲統計表示機能を実現できる。

#### Acceptance Criteria

1. WHEN 時間範囲（開始時刻 t_start、終了時刻 t_end）と Signal が指定された場合、THE Range_Statistics SHALL 範囲内のサンプルに対して統計値を計算する
2. THE Range_Statistics SHALL 以下の統計値を計算する: 平均値（mean）、最大値（max）、最小値（min）、標準偏差（std、母集団標準偏差 ddof=0）、サンプル数（count）
3. THE Range_Statistics SHALL t_start ≤ timestamp ≤ t_end を満たすサンプルを計算対象とする
4. IF 指定範囲内にサンプルが 0 個の場合、THEN THE Range_Statistics SHALL サンプル数 0 と各統計値（mean, max, min, std）を NaN として返す
5. IF t_start > t_end が指定された場合、THEN THE Range_Statistics SHALL バリデーションエラーを返す
6. IF t_start または t_end に NaN または無限大が指定された場合、THEN THE Range_Statistics SHALL バリデーションエラーを返す
7. THE Range_Statistics SHALL 元の Signal を変更せず、計算結果のみを返す（入力データの不変性を維持）
8. THE Range_Statistics SHALL 統計値を float64 精度で計算する（numpy の対応関数と同等の精度）

### Requirement 14: ダウンサンプリング（Downsampler）

**User Story:** 開発者として、描画用に大容量データを動的に間引く機能を提供したい。これにより GUI の LOD レンダリング機能を実現できる。

#### Acceptance Criteria

1. WHEN Signal と目標ポイント数 n（2 以上の整数）が指定された場合、THE Downsampler SHALL Signal のサンプルを n ポイント以下に間引いた新しい Signal オブジェクトを返す
2. THE Downsampler SHALL min-max ダウンサンプリングアルゴリズムを使用し、Signal を均等な区間に分割して各区間の最小値と最大値のサンプルをタイムスタンプとともに保持する。出力ポイント数は各区間につき最大2ポイント（min, max）であり、合計は n 以下とする
3. THE Downsampler SHALL ダウンサンプリング結果のタイムスタンプが元の Signal のタイムスタンプ範囲内に収まることを保証する
4. IF Signal のサンプル数が目標ポイント数 n 以下の場合、THEN THE Downsampler SHALL 元の Signal をそのまま返す（間引きを行わない）
5. THE Downsampler SHALL 元の Signal を変更せず、Signal データモデル（タイムスタンプ列と値列のペア）に準拠した新しい Signal オブジェクトを返す（入力データの不変性を維持）
6. THE Downsampler SHALL 結果のタイムスタンプが厳密に単調増加（t[i] < t[i+1]）であることを保証する
7. IF 目標ポイント数 n が 2 未満の整数、非整数、NaN、または無限大である場合、THEN THE Downsampler SHALL バリデーションエラーを返し、ダウンサンプリングを実行しない

### Requirement 15: Calcbar 演算（移動平均・回帰・微分・積分）

**User Story:** 開発者として、移動平均・線形回帰・微分・積分の演算機能を提供したい。これにより GUI の Calcbar 機能を実現できる。

#### Acceptance Criteria

1. WHEN Signal とウィンドウサイズ w（1 以上かつ Signal の要素数以下の整数）が指定された場合、THE Session SHALL 単純移動平均（SMA: 直近 w サンプルの算術平均）を計算し、結果を Derived_Signal として返す。先頭の w-1 サンプルについては利用可能なサンプル数での算術平均を値とする（縮小ウィンドウ方式）
2. WHEN Signal が指定された場合、THE Session SHALL 線形回帰（最小二乗法）を計算し、入力 Signal と同一のタイムスタンプ列に対する回帰直線上の予測値を値列とする Derived_Signal を返す
3. WHEN Signal が指定された場合、THE Session SHALL 数値微分を計算し、結果を Derived_Signal として返す。各サンプル i における微分値は (value[i+1] - value[i-1]) / (timestamp[i+1] - timestamp[i-1]) とする（中心差分）。先頭および末尾のサンプルは前方差分・後方差分をそれぞれ適用し、出力の要素数を入力と一致させる
4. WHEN Signal が指定された場合、THE Session SHALL 累積数値積分（台形則）を計算し、結果を Derived_Signal として返す。先頭サンプルの積分値は 0.0 とし、以降のサンプル i の値は先頭から i 番目までの台形則による累積和とする
5. THE Session SHALL 各演算結果の Derived_Signal が Signal の不変条件（タイムスタンプの単調増加、タイムスタンプ列と値列の要素数が入力 Signal と一致）を満たすことを保証する
6. THE Session SHALL 元の Signal を変更せず、新しい Derived_Signal を返す（入力データの不変性を維持）
7. IF 演算対象の Signal の要素数が 2 未満である場合、THEN THE Session SHALL 演算種別と必要最小要素数を含むエラーを返し、Derived_Signal を生成しない
8. IF 移動平均のウィンドウサイズ w が 1 未満または Signal の要素数を超える場合、THEN THE Session SHALL 指定値と許容範囲を含むバリデーションエラーを返し、Derived_Signal を生成しない
