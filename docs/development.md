# Development Workflow

開発時のコマンド・品質ゲート・依存管理の運用ノート。

関連:
- `../CLAUDE.md` — エントリポイント
- `policies.md` — プロジェクト方針
- `workflow.md` — ブランチ/PR フロー・superpowers 計画フロー

---

## 技術スタック

- **言語/ランタイム**: Python 3.12+（`requires-python >= 3.12`）。コアは標準ライブラリ + numpy のみ、GUI は PySide6（LGPL）+ PyQtGraph。
- **パッケージ管理**: uv（`pyproject.toml` + `uv.lock`）。build backend は setuptools（`pip install -e .` 可）。
- **コア依存**: numpy（Signal のタイムスタンプ・値配列）。
- **テスト**: pytest >= 8.0 / Hypothesis >= 6.100 / pytest-cov >= 5.0。カバレッジ下限 80%（`fail_under = 80`）。
- **Lint/Format/型**: ruff（flake8/isort/black 代替）/ mypy。設定は `pyproject.toml`（`[tool.pytest.ini_options]` / `[tool.ruff]` / `[tool.mypy]`）。
- **Coding Standards**: 型ヒントを全関数に付与 / immutable データは frozen dataclass + numpy array / インターフェースは Protocol で定義し具象で実装 / 変換処理は新オブジェクトを返す（元データ不変）/ FormatDefinition の永続化は JSON（`data/`）。
- **GUI entry point**: `src/valisync/gui/app.py`。

## 品質ゲート

コミット前にこの順で全てを通す。1つでも失敗したら commit しない。

```bash
uv run pytest                # 1. 全テスト pass
uv run ruff check            # 2. lint 違反ゼロ
uv run ruff format --check   # 3. format 差分ゼロ
uv run mypy src/             # 4. 型エラーゼロ
```

## テスト

```bash
uv run pytest                          # 全テスト
uv run pytest -m property              # プロパティテストのみ
uv run pytest --cov                    # カバレッジ付き
uv run pytest -k "test_name"           # 名前一致で絞り込み
```

レイアウト:
- `tests/` — テストディレクトリ
- `--import-mode=importlib` (`pyproject.toml` 設定) により `__init__.py` 不要

新規モジュールを実装したら必ず対応する pytest テストを追加すること。

### プロパティベーステスト (Hypothesis)

- `pytestmark = pytest.mark.property` を付与し `uv run pytest -m property` で抽出できるようにする
- 検証するプロパティの一次情報源は `.kiro/specs/<spec>/design.md` の **Correctness Properties**。`test_pbt_*.py` の各テストはそこの Property 番号に対応させる（トレーサビリティ）
- 共有 strategy は `tests/conftest.py` に集約: `monotonic_timestamps`（厳密単調増加・有限 float64）、`valid_signals`（Signal 不変条件を満たす生成）。`settings` プロファイルは `default`(200 examples) / `ci`(500)
- 一時ファイルを使う往復テストは **function-scoped fixture を避け**、テスト内で `tempfile.TemporaryDirectory()` を使う（Hypothesis の `function_scoped_fixture` health check 回避 + example 間の分離）

### MDF4 / CSV テストデータ

静的なサンプルファイルはコミットせず、テスト内で**プログラム生成**する:

- **CSV**: `tmp_path` にテキストを書き出すだけ
- **MDF4**: `tests/mdf4_helpers.py` の `write_mdf4()` が asammdf 書き込み API で生成。`Source(bus_type=...)` で CAN/Ethernet、source 名に `xcp` を含めると XCP を合成できる

利点: git に binary blob を置かない / プロトコル・チャンネルグループ・同名信号をパラメトライズできる / 往復 Property（読込→書出→再読込）はそもそも書き込み能力を要求する。

### GUI / Qt (offscreen) テスト

GUI は `pytest-qt` + `QT_QPA_PLATFORM=offscreen`（`tests/gui/conftest.py` で設定）でヘッドレス実行する。MVVM 境界の一次情報源は `.kiro/specs/valisync-gui-mvp/design.md`。

**テストレイヤー（必須運用）**: 入力イベント系は「ヘッドレス状態検証（Layer A）」だけでなく「実イベント経路を `sendEvent` で通すヘッドレス検証（Layer B）」を必須とし、経路を新規/変更したときは実 OS 入力（Layer C, `--realgui`）でローカル実機確認する。詳細・早見表: `docs/gui-testing-layers.md`。

**原則: ピクセルでなく構造化状態を assert する**（VM の `inspect()` / View が公開する投影状態）。実装で確立したパターン:

- **コンテキストメニュー**: View は `build_context_menu()->QMenu` を返し、テストは `action.text()` / `isEnabled()`（グレーアウト）/ `trigger()` を検査（Layer A）。**加えて起動経路は実イベントで検証する（Layer B）**: アイテムビューでは `QListView` に `CustomContextMenu` ポリシーを設定し `customContextMenuRequested` で駆動する（`contextMenuEvent` をコンテナで override すると子ビューからイベントが伝播せず実 GUI で出ない — PR #11）。テストは `QApplication.sendEvent(viewport, QContextMenuEvent(...))` で起動を検査し、シグナルを直接 `emit` しない
- **ズーム/パン**: 「ゾーン判定・範囲演算」は純関数（`classify_zone`/`zoom_range`/`pan_range`）、「ジェスチャ適用」はデータ座標メソッド（`apply_zone_drag`/`apply_zone_wheel`/`reset_zone`）として検査。Qt イベント→ピクセル写像のグルーは offscreen 幾何が不安定なため **smoke（no-crash）のみ**
- **波形描画**: `curve_keys()`/`curve_xy()`/`pen_color()` で投影を検査 + `QWidget.grab()` のスモーク。カーソル状態は `cursor_line_visible()`/`readout_visible()` で検査

**落とし穴（実際に踏んだもの）**:

- **`QDropEvent` は `QMimeData` を借用する**。テストで一時オブジェクトを渡すと使用前に GC されアクセス違反（Windows fatal exception / segfault）。`QMimeData` は **ローカル変数で保持**してからイベントを渡す
- **View は長命 VM を unsubscribe する**。VM はウィジェットより長命なので、破棄後の `_notify` が削除済み C++ オブジェクトを叩き `RuntimeError`。`self.destroyed.connect(lambda *_: unsubscribe())`（**view を参照しない closure**）で対処。検証は `view.deleteLater()` → `qtbot.wait(50)` → `len(vm._callbacks) == 0`
- **offscreen はフォントが無く文字が □ で描画**される（`grab()` スクショ）。レイアウト・ドッキング・波形描画の確認には十分だが文字は読めない（cosmetic、バグではない）
- **クロスビュー操作は Qt シグナルで疎結合**（`add_to_panel_requested` / `file_dropped` / `add_panel_requested` 等）。各 View 単体テストは emit を検査し、接続は MainWindow（統合）で行う
- **`QStackedWidget` の最小幅は「全ページの最大」**（currentWidget ではない・Qt 既定）。隠れたページに無制限幅のウィジェット（フルパスをラベルにした `QPushButton` 等＝最小幅がコンテンツ長に比例）があると、**表示中ページと無関係に**ウィンドウ最小幅が膨張し、最小幅>画面幅の過剰制約で再レイアウト時にドックが画面外へ押し出される（FU-04・PR #80、実機 min 2009px > 画面 1920px）。修正はコンテンツ長比例の最小幅を**発生源で有界化**（`fm.elidedText(..., ElideMiddle, MAX_W)`＋フルテキストは tooltip）— ウィンドウ側クランプは意図的な大画面表示を殺すため不可。調査は central の全ページを `minimumSizeHint()` 分解して駆動元を特定する。テストの注意2点: ElideMiddle の末尾保持は**約半予算**なので `endswith(長いファイル名)` は高 DPI フォントで脆弱（短い5字サフィックスで assert）／有界性は絶対 px でなく**パス長不変性**（150字 vs 400字で最小幅差 ≤16px）で assert するとフォント/スタイル差に頑健
- **`QScrollArea.sizeHint()` は `AdjustToContents` でも約 36×24 × フォント高で bound される**（幅・高さともフォント高の倍数）。大量コンテンツでも sizeHint は有界＝スクロール化するだけでダイアログの過大化は通常止まる。逆に「内容ヒント超過時のみ」の分岐（画面内クランプ等）は通常画面で発火せず、統合テストが GREEN でも**未検証のデッドコード**になりがち — 環境依存の防御層は純関数へ抽出して直接テストする（FU-01・PR #81 の `_clamped_size`。bound はフォント/スケール依存のため大フォント・低解像度では発火し得る）

**スレッド（読込ワーカー）**: `LoadController`/`LoadWorker` は**スレッドセーフな `session.load` のみオフスレッド**実行（不変 Signal）、状態変更・通知は queued signal でメインスレッドへ。テストは `qtbot.waitSignal` / `waitUntil`。「読込中ビジー表示」はブロッキング callable（`threading.Event`）で停止させて決定論的に検証する。

## デモデータ（本番相当 mf4）

実機確認用の HILS 評価ログ（CANape 計測・XCP/CAN/Ethernet 統合）を模した mf4 を
`scripts/generate_demo_mf4.py` で生成できる。設計:
[2026-07-04-hils-demo-mf4-generator-design.md](superpowers/specs/2026-07-04-hils-demo-mf4-generator-design.md)、
実装プラン: [2026-07-04-hils-demo-mf4-generator.md](superpowers/plans/2026-07-04-hils-demo-mf4-generator.md)。

### 生成コマンド

```bash
uv run python scripts/generate_demo_mf4.py --profile smoke   # CI/開発用: 10秒分・実測約5.6MB
uv run python scripts/generate_demo_mf4.py --profile quick   # 機能確認用: 5分分(300s)・実測0.17GB
uv run python scripts/generate_demo_mf4.py --profile hils    # 本番相当: 60分分(3600s)・実測2.01GB
```

- `--out PATH`（既定 `demo_data/hils_demo.mf4`）・`--duration SEC`（プロファイル既定秒数の上書き）・
  `--seed INT`（既定42・同一シードで再現可能）・`--dirty`（`VehDyn_10ms` グループ (CAN) に
  重複/非単調タイムスタンプを注入し、LD-03 の warning 診断を発火させる）。
- 生成物は `demo_data/`（`.gitignore` 済み）配下に置く運用とし、コミットしない。
- **実測値（2026-07-04・Windows 11 / AMD64（Ryzen 系）・`uv run` 経由・キャリブレーション目標 1.6-2.4GB を確認）**:
  `hils` = 2,005,292,424 bytes（2.01 GB）・wall clock 約42秒（12チャンク×300s、`time` 計測）・
  python.exe 系プロセス合計ピーク WorkingSet 約394MB（チャンク書き出しのため全量を一度に展開しない設計どおり）。
  同一 seed で2回生成しバイト完全一致を確認済み（再現性）。目標範囲内のため `Ctrl.Internal[NN]`
  本数（48ch）の調整は不要だった。`quick` = 167,145,296 bytes（0.17 GB）・wall clock 約4.3秒。
  生成時間はディスク/CPU 依存の参考値（`time` はいずれも user/sys がほぼ0秒＝ネイティブ拡張内の
  処理が支配的で Python 側オーバーヘッドは小さい）。

### `prod` プロファイル（本番想定・大規模チャンネル / FU-07）

FU-01（1024列超の展開ダイアログがスクロール不能）・FU-03（多チャンネルのドック切替フリーズ）を実機再現するための大規模データ。

- 生成: `uv run python scripts/generate_demo_mf4.py --profile prod --out demo_data/prod_demo.mf4`
- 目標: 計測 **120秒** / 展開後 **~32万チャンネル** / **~1.5GB**（アレイ主体・広幅アレイ >1024列を数十本含む）。
- 実機確認: `uv run valisync` でロード → (i) 広幅アレイの LD-14 展開ダイアログがチェックボックス多数でスクロール不能（FU-01）・(ii) ロード後にドック表示切替がフリーズ気味（FU-03）を `/run`・`/verify` で観測。
- **実測値（2026-07-10・Windows 11 / AMD64・`uv run` 経由・seed 42）**: 生成 **25秒**（24チャンク）/ ロード **Session.load 8.0s＋materialize 2.2s ≈10秒** / 実サイズ **1.36 GB**（推定 1.359GB とほぼ一致＝差は mf4 メタデータ）/ 展開後 ch 数 **330,004**（うち広幅 60×1100=66,000 はヘッドレスで全スキップ→**264,004 ロード**・GUI では ExpansionDialog で選択）。いずれも目標 1.5GB/32万/120s の±20%内。
- 注: FU-08（Y軸オートフィットの重さ）は高サンプル数が要るため `hils`（1ms×3600s）が適役（`prod` は 120秒×10ms 上限で対象外）。

### 実機確認手順

1. **quick（機能確認）**: `uv run python scripts/generate_demo_mf4.py --profile quick` →
   `uv run valisync` で生成ファイルを D&D → 物標（Radar/Cam）・車速・メーター系のプロット/
   カーソル計測/範囲統計/時間オフセットを一通り操作して確認する。Diagnostics ドックに
   `Radar.ObjMatrix[0..7]`/`Cam.ObjMatrix[0..7]` への展開 info 診断（LD-12・第3弾で解消）が
   出ることも合わせて確認する。
2. **hils（本番相当・重い経路の確認）**: `uv run python scripts/generate_demo_mf4.py --profile hils` →
   ロード時間・メモリ使用量を体感/計測しつつ、**ロード中のキャンセルボタン（FB-04）が実用に耐えるか**
   （押下から実際に中断されるまでの応答性）を確認する観点も持つ。
   **LD-10 は第3弾（`select()` ベース刷新＋共有マスタ/ゼロコピー化）で解消済み** — 大容量 MDF4 の
   配列多重コピーは after 実測（下記）のとおり大幅に縮小した。結果は roadmap／
   catalog（`docs/audit-findings-catalog.md`）の LD-10 行に記録済み。
   **ロード実測 before（2026-07-04・ヘッドレス `Session.load`・Win11）**: hils 2.01GB → **7.8 秒・
   プロセスピーク +7.3GB（ファイルの約3.6倍に膨張）**、quick 0.17GB → 0.9 秒・+0.66GB
   （約4倍 — 小ファイルほど固定オーバーヘッドの寄与が増えるため概ね同程度）。
   **第3弾（`select()` ベース刷新＋共有マスタ/ゼロコピー化）で解消 — after（2026-07-05・同条件）**:
   hils 2.01GB → **3.05 秒・+2.53GB**、quick 0.17GB → 0.79 秒・+0.445GB。受け入れ基準
   （ピーク増分 ≤+3.0GB・ロード時間 ≤7.8 秒）を充足。詳細は catalog LD-10 行。
- `--dirty` を付けると `VehDyn_10ms`（CAN: `VehSpd` 等）に重複/非単調タイムスタンプが混入し、
  Diagnostics ドックに LD-03 の warning（「非単調 N 箇所・重複タイムスタンプ M 点」）が表示される。

## Lint / Format (Ruff)

`pyproject.toml` の `[tool.ruff]` で集中管理。

```bash
uv run ruff check              # 違反検出のみ
uv run ruff check --fix        # 自動修正
uv run ruff format             # フォーマッタ適用
```

推奨ルールセット: `E, W, F, I, B, UP, SIM, RUF`

<!-- TODO: プロジェクト固有の ignore ルールを記載 -->

## 型チェック (Mypy)

```bash
uv run mypy src/               # 標準実行
```

推奨 strictness (`pyproject.toml` の `[tool.mypy]`):
- `disallow_incomplete_defs = true`
- `check_untyped_defs = true`
- `no_implicit_optional = true`
- `warn_unused_ignores = true`

## 依存管理

```bash
uv sync --extra dev            # dev 依存をインストール (初回 / 依存変更後)
uv add --dev <package>         # 新規 dev 依存追加
uv lock --upgrade              # ロックファイル更新
```

## CI (GitHub Actions)

`.github/workflows/ci.yml` — push to `main` と全 PR で品質ゲートを自動実行。

設定の要点:
- **ランナー**: `ubuntu-latest`
- **Python matrix**: requires-python の下限と最新の両端
- **uv キャッシュ**: `astral-sh/setup-uv@v3` の `enable-cache: true`
- **同時実行制御**: `concurrency` + `cancel-in-progress: true`

## 開発環境の落とし穴

- **Windows**: `python` コマンドは Microsoft Store スタブになり得る → 常に `uv run python` を使う
- **Qt offscreen テストの落とし穴**（`QMimeData` 借用によるアクセス違反、View の unsubscribe 漏れ、□ フォント描画など）は上の「[GUI / Qt (offscreen) テスト](#gui--qt-offscreen-テスト)」を参照
- **CRLF 警告**: Windows では新規ファイルコミット時に `LF will be replaced by CRLF` 警告が出るが無害（`.gitattributes` 未設定のため）
