# 設計 spec: core-loaders-hardening 第2弾（開く経路 — LD-01 / LD-02）

実ユーザージャーニーの入口「**ファイルを開く**」で、CSV が GUI から一切開けず（LD-01）、`.mdf`/`.dat` が拡張子で拒否される（LD-02）2つの「行き止まり」を解消する。FB-01/FB-02（PR #37）で失敗は無言でなくなったが、**開く手段そのものが無い**状態を作れるようにするのが本増分。

- **作成**: 2026-07-05
- **ステータス**: 設計（brainstorming 承認済み・writing-plans へ）
- **関連**: [audit-findings-catalog](../../audit-findings-catalog.md) SS-LOADERS（LD-01/LD-02）／UI 側の File>Open は SH-01（`gui-shell-controls`・別サブスペック）で本増分の非ゴール
- **前提コード**:
  - `core/session.py:148-157`（CSV は `format_def is None` で `ValueError`／未対応拡張子で `ValueError("no loader supports")`）
  - `core/loaders/csv_loader.py:25-26`（`supports`＝`.csv`・`load` は `FormatDefinition` 必須）
  - `core/loaders/mdf4_loader.py:201-202`（`supports`＝`.mf4` 限定）・`:237-259`（不正ファイルは try/except で診断化＝クラッシュなし）
  - `core/models/format_def.py`（`FormatDefinition`＝delimiter/timestamp_column/timestamp_unit/signal_start_column/signal_end_column/has_header/has_unit_row・`__post_init__` で不変条件検証）
  - `gui/views/main_window.py:139-164 _load_file`（D&D と Data Explorer 両経路の**単一集約点**・現状 `session.load(target, None, ...)` 固定）
  - `gui/views/data_explorer_view.py:268` 経由で `load_handler=self._load_file`

---

## 1. スコープと確定判断（brainstorming・ユーザー決定）

| 項目 | 決定 |
|---|---|
| LD-01 CSV フォーマット取得 | **自動検出＋確認ダイアログ**。core に純粋な検出器、GUI に確認/微調整モーダル。高確信度でも**常にダイアログを出す**（プリフィル済み）。 |
| 時間単位（sec/msec） | 自動判定は困難 → 検出器の既定は `"sec"`（低確信度）。**ダイアログで確認必須**。 |
| LD-02 .mdf/.dat 受け入れ | **拡張子ホワイトリスト拡張**（`.mf4/.mdf/.dat`）。版判定は asammdf の内容自動判別に委任。非MDF/破損は既存 try/except で診断化。 |
| LD-02 クラス/ファイル名 | **リネームして置き換え**（ユーザー決定）: `Mdf4Loader`→`MdfLoader`、`mdf4_loader.py`→`mdf_loader.py`、`Session._mdf4_loader`→`_mdf_loader`、診断文言「MDF4」→「MDF」。 |
| 非ゴール | File>Open メニュー（SH-01）／フォーマット定義の保存・再利用／内容スニッフィング／MDF3 固有変換の作り込み（asammdf 委任・検証のみ）。 |

## 2. LD-02: MDF ローダーの拡張子拡張＋リネーム

**2.1 supports の拡張**
```python
_SUPPORTED_SUFFIXES = frozenset({".mf4", ".mdf", ".dat"})

def supports(self, file_path: Path) -> bool:
    return file_path.suffix.lower() in self._SUPPORTED_SUFFIXES
```
- 版判定は `MDF(str(file_path), ...)` の内容自動判別に委任（asammdf は MDF 2/3/4 を版横断で同一 API＝`virtual_groups`/`select`/`included_channels` に正規化）。
- 非MDF の `.dat`・破損ファイルは既存の `try/except`（`load` 内 `MDF(...)` 構築）で `LoadResult(signal_group=None, diagnostics=[error])` に変換 → `Session.load` が `LoadError` 送出 → `_on_load_error` のエラーダイアログ（**クラッシュなし・現状で確認済み**）。

**2.2 リネーム（置き換え）**
- ファイル: `core/loaders/mdf4_loader.py` → `core/loaders/mdf_loader.py`（`git mv`）。
- クラス: `Mdf4Loader` → `MdfLoader`。docstring を「MDF 3.x / 4.x を読み込む」に更新。
- 参照更新: `core/session.py`（import・`self._mdf4_loader`→`self._mdf_loader`）、`core/loaders/__init__.py` などの再エクスポート、テスト内の import。`ConfirmExpansion`/`ExpansionRequest`/`OversizedChannel`/`EXPANSION_COLUMN_LIMIT` 等の公開シンボルはモジュールパス変更に追従（`session.py` の再エクスポートも更新）。
- 診断文言: `f"Failed to parse MDF4 '{...}'"` → `f"Failed to parse MDF '{...}'"`。
- 全参照は grep で洗い出し、`ruff`/`mypy`/`pytest` で取りこぼしゼロを保証。

## 3. LD-01: CSV 自動検出＋確認ダイアログ（3ユニット）

### 3.1 core: `CsvFormatDetector`（新規 `core/loaders/csv_format_detector.py`）
純粋・Qt-free・単体テスト可能。ファイル先頭のみ読み（省メモリ）、推定 `FormatDefinition` と注記を返す。

```python
@dataclass(frozen=True)
class DetectedFormat:
    """検出結果。format は妥当なら FormatDefinition、不能なら None。"""
    format: FormatDefinition | None      # 不変条件を満たさない/検出不能なら None
    delimiter: Delimiter                  # プリフィル用（format=None でも埋める）
    has_header: bool
    has_unit_row: bool
    timestamp_column: int
    timestamp_unit: str                   # 既定 "sec"
    signal_start_column: int
    signal_end_column: int
    preview_rows: tuple[tuple[str, ...], ...]  # 先頭 ~10 行を検出区切りで分割
    notes: tuple[str, ...]                # 低確信度/検出不能の説明（ダイアログ表示用）

class CsvFormatDetector:
    def detect(self, file_path: Path, *, max_rows: int = 50) -> DetectedFormat: ...
```

**検出ロジック**（順序）:
1. **区切り**: 候補 `, \t ; ␣` それぞれで先頭数行を分割し、「行間で列数が最も安定し、かつ列数が最多」の候補を選ぶ（`csv.Sniffer` を第一候補に使い、失敗時にこのヒューリスティックへフォールバック）。
2. **ヘッダ**: 先頭行の全セルが非数値なら `has_header=True`。
3. **単位行**: `has_header` かつ 2 行目の全セルが非数値なら `has_unit_row=True`。
4. **時間列**: データ先頭行で、ヘッダ名が `time/timestamp/t/時刻/sec/ms` 等に一致する列を優先。無ければ「単調増加の数値列」を優先。それも無ければ第0列。
5. **時間単位**: 自動判定せず既定 `"sec"`、`notes` に「単位は要確認」。
6. **信号列範囲**: 時間列を除く数値列のうち、連続する範囲を `signal_start_column..signal_end_column` とする。
7. **format 構築**: 上記から `FormatDefinition(...)` を try 構築。`__post_init__` の不変条件（時間列が信号列範囲外・列番号域内 等）を満たせば `format` に格納、`ValueError` なら `format=None`＋`notes` に理由。
8. **検出不能**（0列・空・全非数値でデータ行なし）: `format=None`、`notes` に説明、`preview_rows` は読めた範囲を格納。

### 3.2 GUI: `CsvFormatDialog`（新規 `gui/views/csv_format_dialog.py`）
検出値でプリフィルした確認/微調整モーダル。

- **プレビュー**: `preview_rows` を表形式表示。現在の時間列を1色、信号列範囲を別色でハイライト。
- **編集フィールド**: 区切り（`Delimiter` ドロップダウン）・ヘッダ有無（チェック）・単位行有無（チェック）・時間列（スピナー）・時間単位（sec/msec ラジオ）・信号列 start/end（スピナー）。すべて `DetectedFormat` でプリフィル。
- **ライブ更新**: 区切り変更で `preview_rows` を再分割し表を更新。列選択変更でハイライトを更新。
- **バリデーション**: フィールドから `FormatDefinition` を試作し、`__post_init__` の `ValueError` を捕捉して OK ボタンを無効化＋理由をラベル表示（不変条件をそのまま UI 制約に流用）。
- **API**: `ask(detected: DetectedFormat) -> FormatDefinition | None`（モーダル実行。OK→妥当な `FormatDefinition`、キャンセル/×→`None`）。`notes` があれば冒頭に警告バナー表示。

### 3.3 配線: `main_window._load_file` の CSV プリフライト
D&D と Data Explorer が通る単一集約点に CSV 分岐を追加。

```python
def _load_file(self, path: str | Path) -> None:
    target = Path(path)
    if self.app_vm.session.is_csv(target):     # is_csv は csv_loader.supports へ委譲
        fmt = self._csv_format_resolver(target)  # 検出＋ダイアログ（注入可能）
        if fmt is None:
            self._on_load_cancelled(target)      # キャンセル=中止（エラー無し）
            return
    else:
        fmt = None                               # MDF は従来どおり
    # 以降は既存の submit（session.load(target, fmt, cancel=..., confirm_expansion=...)）
```

- **`_csv_format_resolver`**: 既定は「`CsvFormatDetector().detect(path)` → `CsvFormatDialog(self).ask(detected)`」を行う callable。**コンストラクタ注入可能**（`format_resolver: Callable[[Path], FormatDefinition | None] | None = None`）にし、配線テストで実ダイアログを差し替える。
- **検出はファイル先頭のみ**読むので GUI スレッド同期実行で軽い（重い全体ロードは従来どおりオフスレッド）。
- **CSV 判定**: `session._csv_loader.supports(path)` を薄く公開する `Session.is_csv(path)` を追加（GUI が loader 内部へ触らない）。

## 4. データフロー

```
D&D / Data Explorer
      → main_window._load_file(path)
          ├─ [CSV] CsvFormatDetector.detect(path) → CsvFormatDialog.ask(detected)
          │        ├─ FormatDefinition → LoadController.submit(session.load(path, fmt, ...))
          │        └─ None(キャンセル) → _on_load_cancelled(path)    ← エラー出さない
          └─ [MDF] LoadController.submit(session.load(path, None, ...))
      → 既存 on_success(_on_loaded) / on_error(_on_load_error) / on_cancelled
```

## 5. エラー処理

| ケース | 挙動 |
|---|---|
| CSV 検出不能 | ダイアログは開く（`notes` 警告表示・既定値で編集可）。ユーザーが妥当な定義を組めば読める。組めなければキャンセル=中止。 |
| CSV ロード失敗 | 既存 `_on_load_error`（非単調/重複/`nan` 文字列等は LD-04/06 で受入済み）。 |
| ダイアログ キャンセル | ロード中止（`_on_load_cancelled` 相当・モーダル/診断なし）。 |
| 非MDF `.dat`・破損 MDF | 既存 try/except で診断化 → エラーダイアログ（クラッシュなし）。 |

## 6. テスト戦略（GUI テストレイヤー準拠）

- **core `CsvFormatDetector`**（単体・Layer 不問）: カンマ/タブ/セミコロン/スペース区切り・ヘッダ有無・単位行有無・時間列名検出/単調列フォールバック/第0列フォールバック・時間単位既定 `sec`・信号列範囲・`__post_init__` 違反で `format=None`・検出不能（空/全非数値）。
- **LD-02**（実 asammdf ラウンドトリップ・memory `mdf_authoring_2d_and_value2text_traps` に従い `Session.load` 経由）: asammdf で **MDF3（version="3.30"）実ファイル生成** → `Session.load` で信号が読める／`.dat` にリネームした MDF4 が開ける／**非MDF `.dat`** が `LoadError`（診断 error）になる／`supports()` が 3 拡張子を受理。
- **`CsvFormatDialog`**（Layer B・qtbot）: `ask()` が `DetectedFormat` をプリフィル／編集→期待 `FormatDefinition`／キャンセル→`None`／不変条件違反で OK 無効化。
- **配線**（`_load_file`・resolver 注入）: CSV は resolver 経由で得た `FormatDefinition` で `session.load` が呼ばれる／resolver が `None` を返すとロードされず `_on_load_cancelled`／MDF は resolver を通らず `format_def=None`。
- 実機ダイアログ操作の realgui 要否は `/gui-test-plan`（②受け入れ要件設計）で判断。merge 前は `/gui-verify`（①証拠ゲート）。

## 7. ファイル構成

- **新規**: `core/loaders/csv_format_detector.py`、`gui/views/csv_format_dialog.py`、`tests/core/test_csv_format_detector.py`、`tests/core/loaders/test_mdf_loader_formats.py`（MDF3/.dat）、`tests/gui/test_csv_format_dialog.py`、配線は既存 `tests/gui/test_main_window*` へ追加。
- **リネーム**: `core/loaders/mdf4_loader.py` → `core/loaders/mdf_loader.py`（`git mv`・既存テスト `tests/core/loaders/test_mdf4_loader*.py` の import 追従、必要ならファイル名も整合）。
- **変更**: `core/loaders/mdf_loader.py`（`MdfLoader`・supports・docstring・診断文言）、`core/session.py`（import・`_mdf_loader`・再エクスポート・`is_csv` 追加）、`gui/views/main_window.py`（`_load_file` CSV プリフライト＋`format_resolver` 注入）。

## 8. エッジケース・留意点

- **区切り検出の誤り**: ダイアログで手動修正できるため致命的でない。プレビューのライブ更新で即座に気づける。
- **時間単位の既定 sec**: msec データを sec と誤読すると時間軸が 1000 倍ずれる → ダイアログで明示確認させる（`notes` に注意喚起）。将来「単位ヒント（ヘッダの `[ms]` 等）から推定」は follow-up。
- **フォーマット再利用**: 同形式の CSV を連続で開くたびダイアログが出る煩わしさは follow-up（「前回の定義を既定にする」等）。本増分は毎回確認で単純化。
- **MDF3 固有差**: VLSD 文字列・変換の一部が MDF3 で異なり得る。asammdf 委任で大半は吸収されるが、テストで実際に読めることを担保。読めない特殊構造が出れば別途起票。
- **クラス名リネームの波及**: 公開シンボルのモジュールパスが変わるため、外部（テスト・`__init__`・`session` 再エクスポート）の全参照を grep で洗い出し、品質ゲートで取りこぼしゼロを保証。

## 9. トレーサビリティ

catalog: **LD-01/LD-02 を解消**（SS-LOADERS 第2弾）。実装プラン: `docs/superpowers/plans/2026-07-05-core-loaders-r2-open-path.md`（writing-plans で作成）。roadmap の `core-loaders-hardening` 行を「第2弾（開く経路）完了」へ更新予定。
