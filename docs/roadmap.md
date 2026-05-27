# ValiSync Roadmap

プロジェクト全体の開発フェーズと各 spec の関係を俯瞰するドキュメント。

関連:
- `.kiro/specs/` — 各 spec の一次情報源（requirements / design / tasks）
- `CLAUDE.md` — Phase 状況テーブル（進捗管理）
- `.kiro/steering/product.md` — プロダクト原則

---

## Phase 概要

```mermaid
gantt
    title ValiSync Development Phases
    dateFormat YYYY-MM
    axisFormat %Y-%m

    section Phase 1
    valisync-core           :p1, 2026-05, 2026-07

    section Phase 2
    valisync-gui            :p2, after p1, 2026-10

    section Phase 3
    valisync-persistence    :p3a, after p2, 2026-11
    valisync-theme          :p3b, after p2, 2026-11

    section Phase 4
    valisync-i18n           :p4a, after p3a, 2026-12
    valisync-packaging      :p4b, after p3a, 2026-12
```

---

## Phase 1: データ処理基盤（valisync-core）

**目標**: GUI に依存しない純粋なデータ処理ライブラリを完成させる。

| Spec | 状態 | 概要 |
|------|------|------|
| `valisync-core` | requirements + design + tasks 完備 | Signal データモデル、MDF4/CSV ローダー、時刻同期、Formula エンジン、補間、統計、ダウンサンプラー、Calcbar、CSV エクスポート、Session |

### スコープ

- 不変データモデル（Signal, Signal_Group, FormatDefinition）
- MDF4 統合ローダー（CAN/XCP/Ethernet を asammdf で一括処理）
- CSV ローダー（FormatDefinition ベース）
- TimeSynchronizer（オフセット適用 + Unified_Timeline）
- Formula エンジン（再帰下降パーサー、入れ子 100 階層）
- Interpolator（線形補間・前値保持・最近傍）
- RangeStatistics（平均・最大・最小・標準偏差・サンプル数）
- Downsampler（min-max アルゴリズム）
- Calcbar 演算（移動平均・線形回帰・微分・積分）
- CSV エクスポート（原子性保証）
- Session オーケストレーション層

### 完了条件

- 全ユニットテスト + プロパティベーステスト通過
- 品質ゲート（pytest / ruff / mypy）クリア
- GUI 層なしで全コア機能が Session 経由で利用可能

---

## Phase 2: GUI 実装（valisync-gui）

**目標**: PyQt6/PySide6 + PyQtGraph による高速波形可視化デスクトップアプリケーションを完成させる。

| Spec | 状態 | 概要 |
|------|------|------|
| `valisync-gui` | requirements 完備、design + tasks 未作成 | ドッキング UI、波形/テーブル/棒グラフ/コンター表示、カーソル、D&D、Formula エディタ、Script Console、LOD レンダリング |

### スコープ

- ドッキングウィンドウシステム（QDockWidget）
- Graph_Area タブ管理 + Graph_Panel 分割表示
- Waveform_View（Y-T モード / X-Y プロットモード）
- 複数 Y 軸（独立スケール・高さ比率・配置変更）
- テーブル表示 / 棒グラフ / コンタープロット
- X 軸・Y 軸ズーム・パン（内側/外側ゾーン方式）
- Global_Cursor + Delta_Cursor + 範囲統計表示
- ドラッグ＆ドロップ（ファイル読み込み・信号追加・時間オフセット）
- Channel_Browser + Data_Explorer
- Formula エディタ（構文ハイライト・補完）
- Script Console（Python スクリプティング統合）
- Calcbar UI
- LOD レンダリング（動的ダウンサンプリング）
- コンテキストメニュー
- MVVM アーキテクチャ（Session 経由のみ）

### 完了条件

- 全 GUI 要件の受け入れ基準を満たす
- 100 万サンプル以上で 60fps レンダリング
- Session 経由以外のコアアクセスがないことを確認

### 前提

- Phase 1（valisync-core）完了

---

## Phase 3: UX 強化（persistence + theme）

**目標**: GUI 完成後に日常利用の快適性を高める機能を追加する。

| Spec | 状態 | 概要 |
|------|------|------|
| `valisync-persistence` | 未作成 | セッション永続化（プロジェクトファイル保存/復元） |
| `valisync-theme` | 未作成 | GUI テーマ切替（ライト/ダークモード） |

### valisync-persistence スコープ（想定）

- 解析セッション全体の保存/復元（プロジェクトファイル `.vsproj` 等）
- 保存対象: 読み込みファイルパス、オフセット設定、Formula 定義、Derived_Signal 再現情報、Layout_Template、表示設定
- JSON ベースのプロジェクトファイルフォーマット
- 最近使ったプロジェクトの一覧
- 自動保存（クラッシュリカバリ）
- **Formula 定義の外部ファイル化**
  - Formula 定義を独立した JSON ファイルとして保存・管理
  - Formula ライブラリ（複数の Formula 定義をまとめたコレクション）のインポート/エクスポート
  - チーム間での Formula 定義共有（ファイルコピーまたはネットワークドライブ経由）
  - FormatDefinition と同様の CRUD パターン（`data/formulas/` ディレクトリ）
  - GUI の Formula エディタからの保存/読み込み連携

### valisync-theme スコープ（想定）

- ライトモード / ダークモードの切替
- OS のシステム設定に追従するオプション
- グラフ背景色・グリッド色・波形デフォルト色のテーマ連動
- ユーザー設定の永続化

### 前提

- Phase 2（valisync-gui）完了

---

## Phase 4: リリース準備（i18n + packaging）

**目標**: エンドユーザーへの配布と多言語対応を実現する。

| Spec | 状態 | 概要 |
|------|------|------|
| `valisync-i18n` | 未作成 | 国際化（日本語/英語 UI 切替） |
| `valisync-packaging` | 未作成 | .exe 化（デスクトップアプリ配布） |

### valisync-i18n スコープ（想定）

- Qt の翻訳機構（QTranslator / .ts / .qm）を使用
- 日本語（デフォルト）+ 英語の 2 言語対応
- UI ラベル・メニュー・ダイアログ・エラーメッセージの翻訳
- 言語切替時の即時反映（アプリ再起動不要が理想）
- 翻訳ファイルの管理方針

### valisync-packaging スコープ（想定）

- PyInstaller による単一 .exe 生成
- Windows 向けインストーラー（NSIS or Inno Setup）
- アプリアイコン・スプラッシュスクリーン
- バージョニング戦略
- CI での自動ビルド（GitHub Actions で .exe アーティファクト生成）
- コード署名（将来検討）

### 前提

- Phase 3（persistence + theme）完了
- i18n は GUI の全テキストが確定した後に着手するのが効率的
- packaging は全機能統合後に配布形態を固める

---

## Spec 一覧と依存関係

```mermaid
graph LR
    CORE[valisync-core<br/>Phase 1] --> GUI[valisync-gui<br/>Phase 2]
    GUI --> PERSIST[valisync-persistence<br/>Phase 3]
    GUI --> THEME[valisync-theme<br/>Phase 3]
    PERSIST --> I18N[valisync-i18n<br/>Phase 4]
    THEME --> PKG[valisync-packaging<br/>Phase 4]
    I18N --> PKG
```

---

## 将来検討（スコープ外）

以下は現時点では roadmap に含めないが、将来的に検討する可能性がある領域:

| 領域 | 概要 | 検討タイミング |
|------|------|--------------|
| シナリオバリデーション | 期待値比較・検証ハイライト・Pass/Fail 判定 | Phase 4 完了後 |
| プラグインアーキテクチャ | カスタムローダー・カスタム Formula 関数の外部追加 | ユーザーフィードバック後 |
| クラウド連携 | リモートデータソース・チーム共有 | 組織利用の需要発生時 |
| AD スコープ拡張 | 完全自動運転向けの追加プロトコル対応 | ADAS → AD 移行時 |
