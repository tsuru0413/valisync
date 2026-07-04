# 設計 spec: HILS デモ mf4 ジェネレータ（本番相当の実機確認データ）

ユーザーの実機確認データを本番（ADAS ECU の HILS 評価・CANape 計測）寄りにするための mf4 生成スクリプト。機能確認用の軽量データと、**ロード時間・メモリ挙動まで本番相当**の約2GB データの両方を、再現可能に生成する。

- **作成**: 2026-07-04
- **ステータス**: 実装完了（プラン b4dcba4／実装 dde7c00..83cc1f6・全5タスク＋各タスク3レンズレビュー消化・最終パネル ship）
- **種別**: 開発ツール（`scripts/`・製品コードは不変更）
- **関連**: LD-10（大容量 OOM リスク・第3弾）— 本ツールの hils プロファイルがそのままテストデータになる／LD-07（enum ラベル）／FB-04（キャンセル）— 2GB ロードで実用性を確認

---

## 1. 本番データ像（ユーザー提供・要件の一次情報）

ADAS ECU の HILS 評価ログ。**CANape で計測**された MDF 4.1 ファイルに3ソースが統合されている:

| ソース | 内容 | 性質 |
|---|---|---|
| XCP on Ethernet | カメラ/レーダーの物標情報・ADAS 制御値 | ECU 内部計測（DAQ ラスタ周期）。物標はオブジェクトリスト（配列/構造化） |
| CAN（DBC デコード済み） | 車速・トルクなど外部 ECU との送受信値 | メッセージ周期のイベント駆動 |
| Ethernet（ARXML デコード済み） | メーターへの周辺車両表示情報 | 表示更新周期 |

- スカラーと配列/構造化信号が混在。配列の MDF 表現は **(a) 要素ごとの個別チャンネル展開**と **(b) 1チャンネルに多次元格納**の**両パターンがあり得る**（ユーザー確認済み）。
- ファイルサイズは **約2GB 前後**（ロード時間等を本番相当にしたい・ユーザー指定）。

## 2. 成果物とスコープ

- **Create** `scripts/generate_demo_mf4.py` — asammdf ベースの生成 CLI（シード固定で再現可能）。
- **Create** `demo_data/`（gitignore 追加）— 生成ファイルの既定出力先。**生成ファイルはコミットしない**。
- **Modify** `docs/development.md` に使い方1節（生成コマンド・プロファイル・実機確認手順への導線）。
- **Modify** `docs/audit-findings-catalog.md` — SS-LOADERS に追補1行: 「多次元/構造化チャンネル（本番 (b) パターン）が表示不能（2D skip）」を新 ID（LD-12）として記録（対応は第3弾ブレストで LD-07 と統合判断）。
- **CI**: smoke プロファイルの生成→ロード検証テスト1本のみ（秒級）。

**非ゴール**: LD-10（大容量最適化）や多次元チャンネル表示対応の実装／実 DBC/ARXML ファイルの取り込み（信号定義・値はスクリプト内で生成）／MDF 3.x や他フォーマット。

## 3. 確定済みの設計判断（brainstorming・ユーザー決定）

1. **物標配列は (a) 展開を主表現＋(b) 2D チャンネルを数本併録** — (a) で全機能の実機確認が可能、(b) で「本番で起きる skip 診断」を忠実に再現し将来対応のテストデータとする。
2. **CANape 計測スタイル** — チャンネルグループ＝DAQ リスト/CAN メッセージ単位・バスソースメタ付与・CAN は DBC 流の整数 raw＋線形変換で格納。
3. **約2GB（hils プロファイル）** — 計測60分・XCP 1ms 高速ラスタが主要因。現行 valisync のロードが重い（LD-10 未対応）ことは**織り込み済みの測定対象**（FB-04 キャンセルの実用性確認・LD-10 の優先度判断材料）。

## 4. 生成データ設計

### 4.1 プロファイル

| プロファイル | 目的 | 計測時間 | 概算サイズ |
|---|---|---|---|
| `hils`（既定） | 本番相当のロード体感・LD-10 測定 | 60 分 | **約 2 GB** |
| `quick` | 機能の実機確認（軽量） | 5 分 | 約 180 MB |
| `smoke` | CI・開発 | 10 秒 | 数 MB |

サイズ試算（hils）: `XCP_1ms` = レコード 488 B（time 8B＋60ch×8B）× 3.6M サンプル ≈ **1.76 GB** ＋ `XCP_10ms` 系 ≈ 0.44 GB ＋ CAN/ETH ≈ 0.02 GB ＝ **約 2.2 GB**。実装時に実測して ±20% 程度に収める（`--duration`/ch 数で微調整）。

### 4.2 チャンネルグループ構成（CANape 風）

| グループ | レート | 内容 |
|---|---|---|
| `XCP_1ms` | 1ms 周期 | ADAS 制御内部値（高速）: `ACC.TargetAccel`・`AEB.TTC`・`LKA.SteerTrqCmd`・制御状態機械ほか **~60ch**（サイズの主要因 — §4.1 の試算と連動。物標の一部属性も含めてよい） |
| `XCP_10ms` | 10ms 周期 | 物標リスト展開 (a): `Radar.Obj[0..7].{dx,dy,vx,vy,ExistProb}`（40ch）・`Cam.Obj[0..7].{dx,dy,vx,TypeClass}`（32ch）・`Cam.Lane.{C0,C1,Curvature,Quality}`・ACC/AEB 状態系 ~100ch |
| `XCP_10ms_Struct` | 10ms | **(b) 2D チャンネル 2本**: `Radar.ObjMatrix`・`Cam.ObjMatrix`（各 (N,8) uint8・8物標の dx を列に量子化。実装は非構造化 byte-array 2D＝structured-dtype は Mdf4Loader で ndim==1 に見え skip されず偽データ化するため不採用）— 現行 valisync では「2D samples, skipped」警告になる（意図どおり・LD-12）→ **第3弾で展開表示に変更**（`Radar.ObjMatrix[0..7]`/`Cam.ObjMatrix[0..7]` として列展開され info 診断のみ・skip 警告 0件。本行の「skipped」記述は歴史 — 詳細は `docs/superpowers/plans/2026-07-05-core-loaders-hardening-r3.md` Task 3） |
| `VehDyn_10ms` | 10ms＋ジッタ | CAN: `VehSpd`・`YawRate`・`StrAngle`・`WhlSpd_FL/FR/RL/RR`（整数 raw＋線形変換・unit 付き） |
| `PwrTrq_20ms` | 20ms＋ジッタ | CAN: `EngTrq`・`MotTrq`・`AccelPdl`・`BrkPress` |
| `BodyInfo_100ms` | 100ms＋ジッタ | CAN: `TurnSig`（enum 生値＋value2text (TABX) conversion 埋込〔第3弾 LD-13/LD-07 で復活・§4.4〕・ラベルは `metadata['value_labels']` 構造化保持＋channel comment 併記）・`GearPos`・`DoorState` |
| `Cluster_100ms` | 100ms | ETH: `Cluster.SurrVeh[0..5].{RelX,RelY,Type}`・`Cluster.{ACCIcon,LaneStat,WarnMsg}` |

- source メタ: CAN グループ= bus_type CAN・bus 名 `CAN1`、ETH グループ= bus_type ETHERNET・`ETH1`、XCP はデバイス名 `XCP:HILS_ECU`。
- MDF バージョン 4.10 で書き出し。タイムスタンプは 0 起点。

### 4.3 シナリオ（値の意味づけ・300 秒周期で反復）

乱数ノイズではなく一貫した ACC 追従シナリオを 300 秒1サイクルとして生成し、hils では 12 サイクル反復（各サイクルにシード派生の揺らぎ）:

1. **0-60s 定常追従**: 先行車 80km/h・車間一定・物標スロット0=先行車
2. **60-120s 先行車減速**: TTC 低下 → `AEB.WarnLevel` 1→2 遷移・`ACC.TargetAccel` 負値・`BrkPress` 上昇
3. **120-180s カットイン**: 隣車線から割込み → 物標スロット入替（Obj[1]→Obj[0]）・`Cluster.SurrVeh` 表示遷移
4. **180-240s カメラロスト区間**: `Cam.Obj[*]` が NaN（欠測の本番表現）
5. **240-300s 復帰加速**: 定常へ戻る

各ソースの同一イベントが相関して動く（例: 減速イベントで XCP の TTC・CAN の BrkPress・ETH の WarnMsg が連動）— カーソル計測・範囲統計・オフセット比較が本番の確認作業と同型になる。

### 4.4 本番風の「汚れ」（`--dirty` オプション・既定 OFF）

- CAN グループ1つに重複タイムスタンプ数十点＋非単調数点 → LD-03/04 診断がドックに出る
- 値の NaN は `--dirty` に依らずシナリオ（カメラロスト）で常時含む
- enum 系は生値で生存し、`TurnSig` は value2text (TABX) conversion 埋込を第3弾（LD-13 解消）で復活 — ラベルは `metadata['value_labels']` に構造化保持（LD-07）＋ channel comment にも維持（人間可読の冗長化）

### 4.5 生成の技術要件

- **チャンク生成**: 一括生成は RAM 数 GB になるため、初回 `MDF.append` でグループ作成 → 以降 `MDF.extend(group_index, ...)` で5分チャンクずつ追記し、ピークメモリを数百 MB に抑える。
- 進捗表示（チャンクごとに1行）。hils の生成は分オーダーの見込み。
- CLI: `--out PATH`（既定 `demo_data/hils_demo.mf4`）・`--profile {hils,quick,smoke}`・`--duration SEC`（プロファイル既定の上書き）・`--seed INT`・`--dirty`。
- 依存は既存の asammdf/numpy のみ（dev 依存追加なし）。

## 5. 検証

- **CI（Layer A・秒級）**: smoke プロファイルを tmp に生成 → `Session.load` → (i) 期待 ch 数・グループ由来の代表信号名（`VehSpd` 等）が存在、(ii) (b) 2D チャンネルの skip 警告が diagnostics に含まれる、(iii) `--dirty` 時に非単調 warning が出る、を assert。
- **実機確認手順（docs に記載・/run /verify 観測）**:
  1. `uv run python scripts/generate_demo_mf4.py --profile quick` → `uv run valisync` で D&D → 物標・車速・メーター系のプロット/カーソル/統計を確認（Diagnostics に 2D skip 警告が出ること）
  2. `--profile hils`（2GB）→ ロード時間・メモリ・**キャンセルボタン（FB-04）の実用性**を確認 — **重い/OOM は現行仕様（LD-10 未対応）であり、この測定値が第3弾の優先度判断材料**（結果は roadmap/catalog の LD-10 行に追記）
- 生成スクリプト自体の単体テスト最小限（シナリオ値の妥当性: 定常区間の VehSpd ≈ 80、TTC が減速区間で単調減少、等の代表 assert）。

## 6. エッジケース・留意点

- 2GB 超の FAT32 等への書き出しはユーザー環境依存（ドキュメントに注記のみ）。
- asammdf の `extend` は appended group の index に依存 — グループ作成順を固定し index をスクリプト内定数で管理。
- 乱数はグループ間で独立ストリーム（`np.random.default_rng(seed + group_id)`）— チャンク境界で連続性を保つため、シナリオ値は「時刻の関数」として決定的に計算し、ノイズのみ rng（チャンク分割に依存しない再現性）。
- Windows パス・日本語パスで動作（Path ベース）。

## 7. トレーサビリティ

本 spec は開発ツール（実機確認データ）であり catalog の課題解消ではないが、次に接続する: **LD-10**（hils プロファイルが公式テストデータ・実測値を優先度判断へ）／**LD-07**（enum conversion 埋込データ）／**新 LD-12 追補**（多次元チャンネル表示不能 — 本 spec §2 で catalog に記録）／**FB-04**（2GB ロードでのキャンセル実用性確認）。実装プランは `docs/superpowers/plans/2026-07-04-hils-demo-mf4-generator.md` に作成予定。
