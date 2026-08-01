# E-4b: CSV エクスポート書き経路の再構築 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 「すべて選択 → エクスポート」が prod 規模（330,004 列）で OOM せず、範囲指定エクスポートが常駐を残さず、出力のバイト表現がゴールデンで凍結された状態にする。

**Architecture:** ゴールデン先行（出力仕様 4 点是正 → byte-identical 凍結）→ 境界 API の keys 化（移行橋つき）→ 列ブロック × 行ストリーム × 多段マージ（export 専用 resolve・fan-in 512）→ 見積/確認/進捗/協調キャンセル。並行性 3 点（serial キー・add 対称化・_ensure_namespaced 閉鎖）は独立レーン。

**Tech Stack:** Python 3.13 / PySide6 / asammdf 8.8.22 / numpy / uv。設計の一次情報源は [E-4b spec](../specs/2026-08-01-e4b-export-write-path-design.md)（敵対的レビュー 9 エージェント反映済み）。

## Global Constraints

- **品質ゲート**: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/` 全部 clean。**serial 実行・パイプ禁止**（`| tail` は exit code を隠す — memory 記録済み）。
- **既存テストの期待内容（値・文字列・assert 式）は 1 本も編集しない**。唯一の例外は次の 3 クラスで、いずれも機械的追随＋supersede コメント必須（他に契約が動くなら**停止して報告**）:
  - BOM 化に伴う読み口の付け替え — **影響テストは 26 本**（spec §5.1-2 のファイル別内訳）だが、**編集する物理読み口は 10 サイト・9 行**（Task 1 Step 7 の表が一次情報源。「26 本」は本数カウントであって行数ではない）。
  - realgui の内部状態読み（`test_export_flow.py:187` 等・Task 3/11 が列挙）。
  - **D1 呼び出し形の機械的追随**（Task 4 Step 1 の移行表が全数列挙）— `Session.export_csv` の第 1 引数が Signal リストから列キーへ変わるサイトで、**期待値・文言・数は 1 つも変えず**呼び出し形と assert 式の左辺だけを付け替える。
- **出力列順 = `ExportRequest.keys` の順 = ツリー表示順**（チェック順ではない・ファイル間含む）。ヘッダと値は同じ keys から導出（spec §10）。
- **会計・見積は値を読まない**（`.values`/`.array()`/`sorted_view()` 禁止）。G2/G5 の生存観測は **weakref の独立オラクル**（`resolved_keys()`/`bytes_held` は構造的に盲目のため禁止 — spec §10）。
- **union は完全一致セマンティクス**（tolerance 禁止）・dedup は identity（`is`）のみ。
- **ロック契約**: `handle.lock` 保持中に `resolve()` を呼ばない／`_resolved_lock` 下で I/O しない／唯一のネストは `handle.lock → cache._lock`。
- **temp は出力先と同一ディレクトリ**・失敗/キャンセルでファイルが存在しない（temp 含む）。
- **ゴールデンの再生成は禁止**（変更は supersede 記録つきの手動更新のみ・spec G1）。
- **sabotage 必須**: 追加した load-bearing assert は破壊実証（予測 RED vs 実測 RED を報告・不発は発見として報告し予測を書き換えない）。
- **単価を記録するときは主語（何が bytes を作ったか）を必ず併記**（合成 fixture の単価は実データと桁で外れる — 本シリーズで 3 回実証）。
- コメント/docstring は日本語で WHY。UI 文言は `gui/strings.py` 集約・表記規約 R-01..13。
- コミット: 日本語 subject・conventional prefix・`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`＋Claude-Session トレーラ。
- 共有インターフェース契約（ExportRequest・resolve_transient・CsvExporter.export・ExportEstimate・ExportCancelled・block_cols 式・`_MERGE_FAN_IN = 512`）は各タスクの Interfaces 節に逐語で再掲されている — 型・署名の食い違いはバグ。

## タスク依存グラフ

```
Task 1 (是正 4 点) → Task 2 (ゴールデン) → Task 3 (_selected 圧縮) → Task 4 (keys 化＋橋)
                                                                          ↓
                                       Task 5 (union 純関数) → Task 6 (ブロック書き) → Task 7 (多段マージ・橋撤去)
                                                                          ↓
                                                    Task 8 (見積＋確認)   ※ Task 8 の依存は Task 6 まで
                                                                          ↓    (Task 7 とは並列可)
                                                    Task 9 (Overlay＋キャンセル)

Task 10a (serial キー・add 対称化・_ensure_namespaced) — 独立・いつでも着手可
Task 10b (ExportSourceLost・export_resolver・decay 契約・lock 順 probe)
        — **Task 6 後かつ Task 9 より前**（Task 9 の G6/G7 が export_resolver を呼ぶ）
Task 11 (T-M 実測＋realgui＋spike) — 全タスク後
```

---
### Task 1: 出力仕様 4 点是正（NaN/±inf 空セル・BOM・最小クォート・単位 None）

ゴールデン（Task 2）を作る**前**に、直す意思のある出力仕様を全部入れる。ゴールデンは一度作ると変更が全面差分になるため、ここで入れ損ねた是正は「supersede 記録つきの手動更新」でしか入らなくなる（spec §5.1・B1）。

**変更は 4 点＋前提 1 点**:

| # | 変更 | 現状 | 是正後 | 根拠 |
|---|---|---|---|---|
| 1 | 値セルの NaN | `nan` | 空セル | spec §5.1-1・`Signal.finite_view()` と整合 |
| 1' | 値セルの ±inf | `inf` / `-inf` | 空セル | spec §5.1-1 [I-5/I-6]（`'inf'` を残す非対称を凍結しない） |
| 1'' | precision 指定時の NaN | `nan`（`f"{nan:.3f}"` の漏れ） | 空セル | spec §5.1-1 [I13/plan-6] |
| 2 | ファイル先頭 | BOM なし | UTF-8 BOM | spec §5.1-2（Excel(ja) の cp932 誤認） |
| 3 | セル | 無条件に素通し | RFC 4180 最小クォート（ヘッダ行・単位行にも適用） | spec §5.1-3 [M-2] |
| 前提 | `metadata["unit"] is None` | `TypeError`（`join` が None を拒否） | 空セル | spec §9-6（T-G の fixture で確定させる、と spec が defer した点） |

**据え置き（意図的・spec §5.1 末尾）**: 行末 LF・enum の float 化・shortest round-trip repr・末尾改行あり・失敗時にファイルが存在しない契約。

**対の修正（本タスクのスコープ・spec §5.1-1）**: `CsvLoader` が空セルを `ValueError` → ロード全体失敗にするため、**自製品の出力を自製品が読めない**。空セル = NaN 受理へ直す。

**Files:**
- Modify: `src/valisync/core/export/csv_exporter.py`（`_fmt_value`/`_quote`/`_join` 新設・`_header_rows`/`_rows_unified_timeline`/`_rows_shared_timeline`/`_atomic_write`）
- Modify: `src/valisync/core/loaders/csv_loader.py`（データ行ループの値セル分岐・現行 212-227 行）
- Create: `tests/core/test_export_output_spec.py`（本タスクが追加する唯一のテストファイル）
- Modify（**読み口のみ**・supersede コメント必須・期待内容は 1 文字も変えない）: `tests/test_export.py` / `tests/test_csv_export_options.py` / `tests/core/test_export_container_guard.py` / `tests/test_session.py` / `tests/realgui/test_export_range_realclick.py`

**Interfaces:**
- Consumes: なし（Task 1 は依存グラフの起点。`math` / `numpy` / 既存 `CsvExportOptions` のみ）
- Produces（Task 2 以降がこれに対して書かれる・シグネチャ厳守）:
  - `_fmt_value(value: float, options: CsvExportOptions) -> str` — 値セル専用。非有限は `""`。**時刻セルには使わない**（`_fmt` のまま）
  - `_quote(cell: str, delimiter: str) -> str` — RFC 4180 最小クォート
  - `_join(cells: list[str], opts: CsvExportOptions) -> str` — クォート＋連結。**join の唯一の出口**（4 サイトすべてがこれを通る）
  - `_atomic_write` の書き encoding = `"utf-8-sig"`（BOM はストリーム先頭 1 回のみ）
  - `CsvLoader`: 信号列の空セル（`strip()` が空）= `float("nan")`・**診断なし**。タイムスタンプ列は対象外（エラーのまま）
- 後続タスクへの契約（本タスクが docstring で固定する）:
  - **`_fmt` は時刻セルと値セルの共用のまま**（`:163`/`:194` が使う）。非有限分岐を `_fmt` に入れてはならない — 時刻は `Signal.__init__`（`signal.py:80-82`）が非有限を構造的に拒否しており、分岐は永久に死んだ枝になる
  - **クォート判定は `opts.delimiter`**。`","` を直書きすると `delimiter=";" / decimal=","` の出力（`0,5;1,5`）を誤ってクォートする（既存 `test_comma_decimal_with_semicolon_delimiter` が pin）
  - Task 6/7 のブロック書きでも**セル文字列化とクォートは `_fmt_value`/`_join` を通す**。ブロックごとに独自の `join` を書くと、ヘッダ/単位行だけ最小クォートで値行だけ素通し、という非対称が入る

---

- [ ] **Step 1: ベースラインを記録する**

Step 8/10 の「N 本増えた・既存は 1 本も減っていない」を主張でなく実測で示すため、先に数を控える。

```
uv run pytest -q
```
→ 末尾に出る `N passed, M skipped` の **N と M を控える**（realgui は `--realgui` 無しなら skip 側）。

続けて、BOM 変更が触る読み口の**全数**を実測で確定させる（spec §5.1-2 の「26 本」はテスト本数のカウントで、編集すべき**物理行**とは別物 — 下の Step 7 の表と突き合わせる）:

```
git grep -n 'read_text(encoding="utf-8")' -- tests/test_export.py tests/test_csv_export_options.py tests/core/test_export_container_guard.py tests/test_session.py tests/realgui/test_export_range_realclick.py
```
→ **ちょうど 10 行**出ることを確認する（Step 7 の表と 1 対 1）。増減していたら**停止して報告**する（誰かが新しい読み口を足した／消した）。

念のため広い方も見る:

```
git grep -n 'read_text(encoding="utf-8")' -- tests/
```
→ 18 行出る。差分の 8 行（`tests/gui/test_data_sources.py` 1・`tests/gui/test_realgui_layer_c_contract.py` 2・`tests/gui/test_theme_export.py` 2・`tests/gui/test_theme_guard.py` 1・`tests/gui/test_theme_icons.py` 2）は **CSV エクスポート出力を読んでいない**（JSON / .py ソース / HTML / LICENSES.md）ので**触らない**。

---

- [ ] **Step 2: 失敗テストを書く**

`tests/core/test_export_output_spec.py` を新規作成:

```python
"""出力仕様 4 点是正の契約 (E-4b Task 1・spec §5.1・ユーザー決定 B1)。

ゴールデン (Task 2) はこの是正**後**のバイトを凍結する。ゴールデンは
「今こう出ている」を丸ごと固めるだけで**意図を語らない**ので、
「なぜ空セルなのか」「なぜ最小クォートなのか」を語る執行点がここに要る。
ゴールデンだけにすると、将来 nan を復活させた誰かが「ゴールデンを
supersede すればよい」で通せてしまう。

`CsvLoader` 側 (空セル受理) を同じファイルに置くのは、**対で 1 つの契約**
だから — エクスポータが空セルを書き、ローダーが空セルを読む。片方だけ直すと
自製品の出力を自製品が読めない状態が残る (spec §5.1-1)。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from valisync.core.export.csv_exporter import CsvExporter, CsvExportOptions
from valisync.core.loaders.csv_loader import CsvLoader
from valisync.core.models import Delimiter, FormatDefinition, Signal

_BOM = b"\xef\xbb\xbf"


def _sig(
    name: str,
    ts: list[float],
    vs: list[float],
    metadata: dict[str, object] | None = None,
) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata=dict(metadata) if metadata is not None else {},
    )


def _text(path: Path) -> str:
    """出力を**BOM を剥がして**読む (本増分以降の正しい読み口)。"""
    return path.read_text(encoding="utf-8-sig")


# ─── 1. 非有限値は空セル (B1・spec §5.1-1) ────────────────────────────────────


def test_nan_value_becomes_empty_cell_shared_timeline(tmp_path: Path) -> None:
    """裸の ``nan`` は Excel で文字列・pandas で NaN・CANape で不明の三者三様。

    欠測 (統合タイムラインでサンプルが無い) と**同じ**空セル表現へ揃える。
    """
    s = _sig("x", [0.0, 1.0], [1.5, float("nan")])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out).splitlines() == ["timestamp,x", "0.0,1.5", "1.0,"]


def test_positive_and_negative_inf_become_empty_cells(tmp_path: Path) -> None:
    """±inf も NaN と同じ扱い (spec §5.1-1 [I-5/I-6])。

    ``finite_view`` は NaN と inf を等価に「非有限」と扱う。片方だけ空セルに
    すると、その非対称を**ゴールデンが恒久化**してしまう。
    """
    s = _sig("x", [0.0, 1.0, 2.0], [float("inf"), float("-inf"), 3.0])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out).splitlines() == ["timestamp,x", "0.0,", "1.0,", "2.0,3.0"]


def test_nan_is_empty_in_the_precision_branch_too(tmp_path: Path) -> None:
    """precision 指定時の ``f"{nan:.3f}"`` -> ``"nan"`` 漏れ (spec §5.1-1 [I13])。

    repr 側だけ直すと、GUI で「小数点以下の桁数」を指定した瞬間に nan が復活する。
    """
    s = _sig("x", [0.0, 1.0], [1.5, float("nan")])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(precision=3))
    assert _text(out).splitlines() == ["timestamp,x", "0.000,1.500", "1.000,"]


def test_nonfinite_is_indistinguishable_from_a_missing_sample(tmp_path: Path) -> None:
    """統合タイムラインで「欠測」と「NaN」が**同一バイト**になること。

    これが B1 の決定そのもの。区別できる形 (例: ``nan`` を残す/``NA`` を書く) に
    戻すと、この assert が両者を見分けてしまい RED になる。
    """
    a = _sig("a", [0.0, 1.0], [10.0, float("nan")])  # t=1.0 は「値はあるが NaN」
    b = _sig("b", [0.0], [20.0])  # t=1.0 は「サンプルが無い」
    out = tmp_path / "d.csv"
    CsvExporter().export([a, b], out, use_unified_timeline=True)
    rows = _text(out).splitlines()
    assert rows == ["timestamp,a,b", "0.0,10.0,20.0", "1.0,,"]


# ─── 2. UTF-8 BOM (spec §5.1-2) ───────────────────────────────────────────────


def test_output_starts_with_a_single_utf8_bom(tmp_path: Path) -> None:
    """BOM は**先頭 1 回だけ**。

    ``_atomic_write`` は ``write`` を 2 回呼ぶ (本文 + 末尾改行)。utf-8-sig の
    IncrementalEncoder が first フラグを持つので 1 回で済むが、行ごとに
    ``open`` し直す実装へ変えると各行頭に BOM が入る — ``count`` で塞ぐ。
    """
    s = _sig("x", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    raw = out.read_bytes()
    assert raw.startswith(_BOM)
    assert raw.count(_BOM) == 1
    assert raw == _BOM + b"timestamp,x\n0.0,1.5\n"


def test_japanese_header_survives_as_utf8_after_the_bom(tmp_path: Path) -> None:
    """BOM を入れる理由そのもの: ヘッダは日本語/ファイルキー併記を含みうる。"""
    s = _sig("mf4_1::車速", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(header_names=("車速",)))
    raw = out.read_bytes()
    assert raw == _BOM + "timestamp,車速\n0.0,1.5\n".encode()


# ─── 3. RFC 4180 最小クォート (spec §5.1-3 [M-2]) ─────────────────────────────


def test_delimiter_in_header_name_is_quoted(tmp_path: Path) -> None:
    """信号名こそ区切り文字混入の主経路 — ヘッダ行にも適用する [M-2]。"""
    s = _sig("a,b", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out).splitlines() == ['timestamp,"a,b"', "0.0,1.5"]


def test_double_quote_in_name_is_doubled_inside_quotes(tmp_path: Path) -> None:
    s = _sig('say "hi"', [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out).splitlines()[0] == 'timestamp,"say ""hi"""'


def test_newline_in_name_is_quoted_and_stays_a_single_logical_row(
    tmp_path: Path,
) -> None:
    """改行入りの名前は囲まないと**列構造が壊れる** (行が 2 行に割れる)。"""
    s = _sig("line\nbreak", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out) == 'timestamp,"line\nbreak"\n0.0,1.5\n'


def test_delimiter_in_unit_is_quoted_in_the_unit_row(tmp_path: Path) -> None:
    """単位行にも適用する [M-2] — ``m,s`` のような単位は実在する。"""
    s = _sig("x", [0.0], [1.5], metadata={"unit": "m,s"})
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(unit_row=True))
    assert _text(out).splitlines() == ["timestamp,x", 's,"m,s"', "0.0,1.5"]


def test_quoting_is_minimal_not_unconditional(tmp_path: Path) -> None:
    """**最小**であることが load-bearing。

    常時クォートに変えると全セルが変わり、Task 2 のゴールデン 11 本が全滅する。
    「クォートを入れた」だけでは足りず「入れていないセルはバイト不変」まで縛る。
    """
    s = _sig("x", [0.0], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out)
    assert _text(out) == "timestamp,x\n0.0,1.5\n"  # 引用符ゼロ


def test_quote_decision_uses_the_configured_delimiter_not_a_literal_comma(
    tmp_path: Path,
) -> None:
    """``delimiter=";"`` + ``decimal=","`` のセル ``0,5`` はクォートしない。

    ``","`` を直書きした実装だと ``"0,5";"1,5"`` になり、既存の
    ``test_comma_decimal_with_semicolon_delimiter`` が RED になる。ここは
    その既存 pin を**新設側からも**明示するミラー。
    """
    s = _sig("speed", [0.5], [1.5])
    out = tmp_path / "d.csv"
    CsvExporter().export(
        [s], out, options=CsvExportOptions(delimiter=";", decimal=",")
    )
    assert _text(out).splitlines() == ["timestamp;speed", "0,5;1,5"]


def test_empty_cell_is_not_quoted(tmp_path: Path) -> None:
    """空セルは区切り/引用符/改行のいずれも含まないのでクォート対象外。

    ここが崩れると欠測セルが全部 ``""`` になり、prod では出力の 66% が膨らむ。
    """
    a = _sig("a", [0.0, 1.0], [10.0, 11.0])
    b = _sig("b", [0.0], [20.0])
    out = tmp_path / "d.csv"
    CsvExporter().export([a, b], out, use_unified_timeline=True)
    assert _text(out).splitlines()[-1] == "1.0,11.0,"


# ─── 前提: unit=None (spec §9-6) ──────────────────────────────────────────────


def test_unit_none_is_written_as_an_empty_cell(tmp_path: Path) -> None:
    """production の mdf_loader は truthy ガードで None を載せない
    (mdf_loader.py:159-161・spec §13-2) が、手組み metadata (Derived・テスト・
    将来のローダー) は None を持ちうる。現状は ``join`` が TypeError を投げる。

    Task 2 のゴールデンが unit=None を軸に持つ (spec §9-6 が T-G へ defer した点)
    ので、ここで「空セルへ畳む」と決める。
    """
    s = _sig("x", [0.0], [1.5], metadata={"unit": None})
    out = tmp_path / "d.csv"
    CsvExporter().export([s], out, options=CsvExportOptions(unit_row=True))
    assert _text(out).splitlines() == ["timestamp,x", "s,", "0.0,1.5"]


# ─── 対の修正: CsvLoader が空セルを NaN として受理する (spec §5.1-1) ───────────


def _fmt_def(n_signals: int) -> FormatDefinition:
    return FormatDefinition(
        name="rt",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=n_signals,
        has_header=True,
    )


def test_loader_accepts_empty_signal_cell_as_nan(tmp_path: Path) -> None:
    """空セルは**欠測**であってエラーではない。

    現状は ``float("")`` の ValueError で LoadResult ごと失敗し、
    「自製品の統合タイムライン出力 (prod ではセルの 66% が空) を自製品が
    読めない」状態になっている。
    """
    src = tmp_path / "in.csv"
    src.write_text("t,a,b\n0.0,1.0,\n1.0,,2.0\n", encoding="utf-8")
    result = CsvLoader().load(src, _fmt_def(2))
    assert result.signal_group is not None, [d.message for d in result.diagnostics]
    a, b = result.signal_group.signals
    assert a.values[0] == 1.0 and math.isnan(float(a.values[1]))
    assert math.isnan(float(b.values[0])) and b.values[1] == 2.0


def test_loader_accepts_whitespace_only_cell_as_nan(tmp_path: Path) -> None:
    """他ツール由来の ``, ,`` も同じ意図 (欠測) なので同じ扱いにする。"""
    src = tmp_path / "in.csv"
    src.write_text("t,a\n0.0, \n", encoding="utf-8")
    result = CsvLoader().load(src, _fmt_def(1))
    assert result.signal_group is not None
    assert math.isnan(float(result.signal_group.signals[0].values[0]))


def test_loader_emits_no_diagnostic_for_empty_cells(tmp_path: Path) -> None:
    """空セルに警告を出さない。

    空セルは valisync 自身の出力における欠測の**正規表現**であり、prod の
    再取込では全信号に 1 件ずつ warning が出てノイズになる。値の破損を
    表明する ``'nan'``/``'inf'`` の**文字列**は LD-06 の警告を維持する
    (次のテストが反 vacuous 側)。
    """
    src = tmp_path / "in.csv"
    src.write_text("t,a\n0.0,\n1.0,\n", encoding="utf-8")
    result = CsvLoader().load(src, _fmt_def(1))
    assert result.signal_group is not None
    assert not [d for d in result.diagnostics if "非有限値" in d.message]


def test_loader_still_warns_for_literal_nan_and_inf_strings(tmp_path: Path) -> None:
    """反 vacuous: 空セルを黙らせても LD-06 の警告経路は生きている。"""
    src = tmp_path / "in.csv"
    src.write_text("t,a\n0.0,nan\n1.0,inf\n", encoding="utf-8")
    result = CsvLoader().load(src, _fmt_def(1))
    assert result.signal_group is not None
    assert any("非有限値 2 個" in d.message for d in result.diagnostics)


def test_loader_still_rejects_an_empty_timestamp(tmp_path: Path) -> None:
    """時刻列は対象外 — 時刻の欠測は時間軸そのものの破損。

    値セルの受理を ``row`` 全体へ広げると、時刻が空の行が t=NaN で通り
    ``Signal.__init__`` の非有限時刻拒否 (signal.py:80-82) まで潜る。
    """
    src = tmp_path / "in.csv"
    src.write_text("t,a\n,1.0\n", encoding="utf-8")
    result = CsvLoader().load(src, _fmt_def(1))
    assert result.signal_group is None
    assert any("タイムスタンプ" in d.message for d in result.diagnostics)


def test_export_then_reload_roundtrips_missing_cells_as_nan(tmp_path: Path) -> None:
    """自製品の出力を自製品が読み戻せる (spec §9-3 に valisync 自身を加えた根拠)。

    BOM (エクスポータ) と utf-8-sig 読み (csv_loader.py:46) の噛み合わせも
    ここで同時に効いている — BOM を剥がし損ねるとヘッダ名 ``timestamp`` が
    ``\\ufefftimestamp`` になり列検出がずれる。
    """
    a = _sig("a", [0.0, 1.0], [10.0, float("nan")])
    b = _sig("b", [0.0], [20.0])
    out = tmp_path / "out.csv"
    CsvExporter().export([a, b], out, use_unified_timeline=True)

    result = CsvLoader().load(out, _fmt_def(2))
    assert result.signal_group is not None, [d.message for d in result.diagnostics]
    la, lb = result.signal_group.signals
    assert la.name == "a" and lb.name == "b"
    np.testing.assert_array_equal(la.timestamps, np.array([0.0, 1.0]))
    assert la.values[0] == 10.0 and math.isnan(float(la.values[1]))
    assert lb.values[0] == 20.0 and math.isnan(float(lb.values[1]))
```

実行して RED を確認する:

```
uv run pytest tests/core/test_export_output_spec.py -q
```

**予測 RED（新規 20 本中 15 本 fail・5 本 pass）**:

| テスト | 予測される失敗理由 |
|---|---|
| `test_nan_value_becomes_empty_cell_shared_timeline` | `["timestamp,x","0.0,1.5","1.0,nan"] != [...,"1.0,"]` |
| `test_positive_and_negative_inf_become_empty_cells` | `"0.0,inf"` / `"1.0,-inf"` |
| `test_nan_is_empty_in_the_precision_branch_too` | `"1.000,nan"`（`f"{nan:.3f}"` の漏れ） |
| `test_nonfinite_is_indistinguishable_from_a_missing_sample` | `"1.0,nan,"`（欠測と非有限が区別できてしまう） |
| `test_output_starts_with_a_single_utf8_bom` | `raw.startswith(_BOM)` が False |
| `test_japanese_header_survives_as_utf8_after_the_bom` | 同上（BOM 無しの bytes） |
| `test_delimiter_in_header_name_is_quoted` | `"timestamp,a,b"`（クォート無し） |
| `test_double_quote_in_name_is_doubled_inside_quotes` | `'timestamp,say "hi"'` |
| `test_newline_in_name_is_quoted_and_stays_a_single_logical_row` | 生の改行で 3 行になる |
| `test_delimiter_in_unit_is_quoted_in_the_unit_row` | `"s,m,s"`（列が 3 つに割れる） |
| `test_unit_none_is_written_as_an_empty_cell` | `TypeError: sequence item 1: expected str instance, NoneType found` |
| `test_loader_accepts_empty_signal_cell_as_nan` | `signal_group is None`（診断 `信号列に非数値の値 ''`） |
| `test_loader_accepts_whitespace_only_cell_as_nan` | 同上（`' '`） |
| `test_loader_emits_no_diagnostic_for_empty_cells` | `signal_group is None` |
| `test_export_then_reload_roundtrips_missing_cells_as_nan` | `signal_group is None`（空セルで失敗） |
| `test_quoting_is_minimal_not_unconditional` | **pass**（現状すでにクォート無し — 是正後も不変であることの pin） |
| `test_quote_decision_uses_the_configured_delimiter_not_a_literal_comma` | **pass**（現状の挙動そのもの） |
| `test_empty_cell_is_not_quoted` | **pass** |
| `test_loader_still_warns_for_literal_nan_and_inf_strings` | **pass**（既存挙動） |
| `test_loader_still_rejects_an_empty_timestamp` | **pass**（既存挙動） |

（pass 5 本は「是正で壊れない」側の pin。合計 20 本・fail 15 本。実測が予測とずれたら**予測を書き換えず**発見として報告する。）

---

- [ ] **Step 3: `csv_exporter.py` を是正する（BOM 以外の 3 点＋unit=None）**

BOM を**この Step に含めない**のが要点。BOM は既存テスト 9 サイトを一斉に RED にするので、他の是正と混ぜると「どの変更がどのテストを落としたか」が読めなくなる（Step 6 で単独で入れる）。

`src/valisync/core/export/csv_exporter.py` の冒頭 import に `math` を足す:

```python
from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
```

`_fmt`（`:78-86`）の**直後**に 3 つのヘルパを追加する:

```python
def _fmt_value(value: float, options: CsvExportOptions) -> str:
    """値セルを書式化する。非有限 (NaN/±inf) は**空セル**にする (B1・spec §5.1-1)。

    欠測 (統合タイムラインでサンプルが無い) と同じ表現へ揃えるのが目的。裸の
    ``nan`` は Excel で文字列・pandas で NaN・CANape で不明の三者三様になり、
    analysis-correctness が ``Signal.finite_view()`` で確定させた「非有限は値と
    して扱わない」判断とエクスポートだけが逆を向いていた。

    ``_fmt`` を分岐させず**手前で**返すのは、``_fmt`` が時刻セル (:163/:194) と
    共用だから — 時刻は ``Signal.__init__`` (signal.py:80-82) が全構築経路で
    非有限を拒否しており、``_fmt`` 側の分岐は永久に到達しない死んだ枝になる。
    precision 指定時の ``f"{nan:.3f}"`` -> ``"nan"`` 漏れもここで同時に塞がる。
    """
    v = float(value)
    if not math.isfinite(v):
        return ""
    return _fmt(v, options)


def _quote(cell: str, delimiter: str) -> str:
    """RFC 4180 の**最小**クォート: 区切り/二重引用符/改行を含むときだけ囲む。

    「最小」であることが load-bearing — 常時クォートに変えると全セルのバイトが
    変わり、Task 2 のゴールデン全本が差分になる。それ以外のセルはバイト不変。

    判定に使うのは ``delimiter`` であって ``","`` ではない。``delimiter=";"`` +
    ``decimal=","`` の出力 (``0,5;1,5``) は**クォートしてはならない**
    (test_comma_decimal_with_semicolon_delimiter が pin)。
    """
    if delimiter in cell or '"' in cell or "\n" in cell or "\r" in cell:
        return '"' + cell.replace('"', '""') + '"'
    return cell


def _join(cells: list[str], opts: CsvExportOptions) -> str:
    """セル列を最小クォートしてから区切りで連結する — **join の唯一の出口**。

    ヘッダ行・単位行・データ行 (統合/共有) の 4 サイトすべてがここを通る。
    サイトごとに ``delimiter.join`` を直書きすると、信号名/単位だけクォートが
    抜ける非対称が入る (信号名と単位こそ区切り文字混入の主経路・spec §5.1-3
    [M-2])。
    """
    d = opts.delimiter
    return d.join(_quote(c, d) for c in cells)
```

`_header_rows`（`:137-148`）を差し替える:

```python
    def _header_rows(self, signals: list[Signal], opts: CsvExportOptions) -> list[str]:
        """ヘッダ行(+ unit_row 指定時は単位行)を返す。"""
        names = (
            list(opts.header_names)
            if opts.header_names is not None
            else [s.name for s in signals]
        )
        lines = [_join([_TIMESTAMP_HEADER, *names], opts)]
        if opts.unit_row:
            # None / キー欠落 / 空文字はすべて空セルへ畳む。production の
            # mdf_loader は truthy ガード (mdf_loader.py:159-161) で None を
            # 載せないが、手組み metadata (Derived・テスト) は None を持ちうる。
            # 畳まないと _quote の `delimiter in None` が TypeError になる
            # (spec §9-6 が T-G へ defer した点をここで確定させる)。
            units = [s.metadata.get("unit") or "" for s in signals]
            lines.append(_join([_TIMESTAMP_UNIT, *units], opts))
        return lines
```

`_rows_unified_timeline` の行組み立て（`:163-165`）を差し替える:

```python
            cells = [_fmt(ts, opts)]
            cells.extend(_fmt_value(lk[ts], opts) if ts in lk else "" for lk in lookups)
            lines.append(_join(cells, opts))
```

`_rows_shared_timeline` の行組み立て（`:194-196`）を差し替える:

```python
            cells = [_fmt(timestamps[i], opts)]
            cells.extend(_fmt_value(vs[i], opts) for vs in sorted_values)
            lines.append(_join(cells, opts))
```

**時刻セルは `_fmt` のまま**（両サイトの 1 行目）— 触らない。

確認:

```
uv run pytest tests/core/test_export_output_spec.py -q
```
→ BOM 2 本と CsvLoader 5 本のうち fail 側だけが残る（**予測: 6 failed, 14 passed**。fail = BOM 2 本＋loader 4 本〔`accepts_empty` / `accepts_whitespace` / `emits_no_diagnostic` / `roundtrips`〕）。

既存テストが無傷なことも確認する:

```
uv run pytest tests/test_export.py tests/test_csv_export_options.py tests/core/test_export_container_guard.py tests/test_pbt_csv.py -q
```
→ **全 pass**（BOM をまだ入れていないので読み口は無傷。クォートは既存 fixture のどの名前/単位にも区切り文字が無いのでバイト不変。PBT の名前は a-z のみ・値は finite のみなので非有限分岐にも触れない）。

---

- [ ] **Step 4: `csv_loader.py` を是正する（空セル = NaN 受理）**

`src/valisync/core/loaders/csv_loader.py` の値セルループ（現行 `:209-231`）を差し替える:

```python
            for sig_idx, col in enumerate(
                range(format_def.signal_start_column, format_def.signal_end_column + 1)
            ):
                val_str = row[col]
                if not val_str.strip():
                    # 空セル = 欠測として受理する (E-4b B1・spec §5.1-1 の対の修正)。
                    # エクスポータが欠測と非有限を空セルで書くようになったので、
                    # ここを ValueError にしたままだと**自製品の出力を自製品が
                    # 読めない** (prod の統合タイムライン出力はセルの 66% が空)。
                    #
                    # 診断は出さない: 空セルは valisync 自身の出力における欠測の
                    # 正規表現であり、再取込のたびに全信号へ warning が出る。
                    # 値の破損を表明する 'nan'/'inf' の**文字列**は下の
                    # nonfinite_counts で従来どおり警告する (LD-06)。
                    #
                    # タイムスタンプ列は対象外 (上の分岐のまま) — 時刻の欠測は
                    # 時間軸そのものの破損で、行として意味を成さない。
                    values_lists[sig_idx].append(float("nan"))
                    continue
                try:
                    val = float(val_str)
                except ValueError:
                    return LoadResult(
                        signal_group=None,
                        diagnostics=(
                            *diagnostics,
                            Diagnostic(
                                level="error",
                                message=f"信号列に非数値の値 {val_str!r}",
                                line_number=line_number,
                                column_number=col,
                            ),
                        ),
                    )
                # LD-06: nan/inf は欠測として正当なので受け入れ、件数だけ集計する
                if not math.isfinite(val):
                    nonfinite_counts[sig_idx] = nonfinite_counts.get(sig_idx, 0) + 1
                values_lists[sig_idx].append(val)
```

確認:

```
uv run pytest tests/core/test_export_output_spec.py -q
```
→ **予測: 2 failed, 18 passed**（残る fail は BOM 2 本のみ）

```
uv run pytest tests/test_loaders.py tests/test_pbt_csv.py -q
```
→ **全 pass**（PBT の `finite_floats` は空セルを生まない・`test_csv_nan_inf_values_accepted_with_count_warning` はリテラル文字列なので無傷）

---

- [ ] **Step 5: 品質ゲートを通して中間コミットする**

BOM を入れる**前**に区切るのは、BOM は既存テストの読み口 9 行を触る唯一の変更で、レビューの粒度として分けたほうが「期待内容は 1 文字も変えていない」を確認しやすいから。

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```
→ すべて exit 0。pytest は Step 1 の `N` に対して **`N + 20 passed`**（新規 20 本）。**パイプを通さない**（`| tail` は exit code を隠す）。

コミット:

```
git add -A
git commit -F - <<'EOF'
fix(core): CSV 出力の非有限値を空セル化し RFC 4180 最小クォートを導入 (E-4b B1)

NaN/±inf を欠測と同じ空セルへ統一 (precision 分岐の漏れ含む)。ヘッダ行・
単位行を含む join 4 サイトを _join へ集約して区切り/引用符/改行を含むセルの
みを最小クォート。metadata["unit"] is None は空セルへ畳む (spec §9-6)。
対で CsvLoader が空セルを NaN として受理するようにし、自製品の統合タイム
ライン出力を自製品が読み戻せるようにした (spec §5.1-1)。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
```

---

- [ ] **Step 6: BOM を入れて RED の全数を実測する**

`src/valisync/core/export/csv_exporter.py` の `_atomic_write`（`:206`）:

```python
            # UTF-8 BOM つきで書く (E-4b B1・spec §5.1-2)。ヘッダは
            # csv_header_names のファイルキー併記や日本語信号名を含みうるため、
            # BOM が無いと Excel(ja) が cp932 と誤認して化ける。pandas は
            # utf-8-sig 相当で自動除去し、自製品の CsvLoader は既に utf-8-sig
            # 読み (csv_loader.py:46) なので往復は無修正で生存する。
            # BOM はストリーム先頭の 1 回だけ (utf-8-sig の IncrementalEncoder が
            # first フラグを持つ) なので、write を 2 回に分けても二重に付かない。
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
```

RED の全数を**実測**する（spec §5.1-2 の「26 本」を主張でなく数える）:

```
uv run pytest tests/ -q -p no:randomly
```
→ 失敗本数と失敗ファイルを控える。**予測**: `tests/test_export.py` 4・`tests/test_csv_export_options.py` の `_read` 経由で 20 前後・`tests/core/test_export_container_guard.py` 2・`tests/test_session.py` 1 の**計 26 前後**が RED（realgui は `--realgui` 無しで skip なので、`_read_timestamps` の 1 本はこの走行では現れない）。失敗理由はすべて先頭列の `﻿timestamp`。

**実測が 26 と一致しなくても是正しない** — spec の 26 は本数カウントで、編集すべき物理行は Step 7 の表（9 行）が一次情報源。差があれば報告に書く。

---

- [ ] **Step 7: 読み口 9 行を機械的に `utf-8-sig` 化する（唯一の既存テスト編集）**

**期待内容（値・文字列・assert 式）は 1 文字も変えない。** 変えるのは `encoding="utf-8"` → `encoding="utf-8-sig"` だけで、各サイトの**直上に 1 行**の supersede コメントを置く。

```python
# supersede(E-4b §5.1-2): 出力に UTF-8 BOM が付いたため読み口のみ utf-8-sig 化 (期待値不変)
```

**全数表**（`git grep` で確定済み・行番号は編集前の値）:

| # | ファイル:行 | 現在の行 | 直前の識別コンテキスト | 措置 |
|---|---|---|---|---|
| 1 | `tests/test_export.py:30` | `    lines = out.read_text(encoding="utf-8").splitlines()` | 直前が `    CsvExporter().export([sig], out)` | utf-8-sig 化 |
| 2 | `tests/test_export.py:46` | 同上 | 直前が `    CsvExporter().export([a, b], out)` | utf-8-sig 化 |
| 3 | `tests/test_export.py:60` | 同上 | 直前が `    CsvExporter().export([a, b], out, use_unified_timeline=True)` | utf-8-sig 化 |
| 4 | `tests/test_export.py:81` | `    assert out.read_text(encoding="utf-8") == "ORIGINAL"` | `test_export_atomic_failure_preserves_existing_file` | **変更しない**（読む対象は `write_text` で置いた既存ファイルで、エクスポータは 1 バイトも書いていない。ここを触ると「失敗時は元ファイル無傷」の観測が BOM 許容へ緩む） |
| 5 | `tests/test_export.py:91` | `    lines = out.read_text(encoding="utf-8").strip().splitlines()` | `.strip()` 付きで一意 | utf-8-sig 化 |
| 6 | `tests/test_csv_export_options.py:25` | `    return p.read_text(encoding="utf-8").splitlines()` | ヘルパ `_read` — このファイルの読み口は**ここ 1 箇所のみ**（22 本のテストが経由） | utf-8-sig 化 |
| 7 | `tests/core/test_export_container_guard.py:161` | `    lines = out.read_text(encoding="utf-8").splitlines()` | `test_session_exports_expanded_column` | utf-8-sig 化 |
| 8 | `tests/core/test_export_container_guard.py:172` | `    assert out.read_text(encoding="utf-8").splitlines()[0] == "timestamp,Plain"` | `test_session_export_allows_signal_without_loaded_group` | utf-8-sig 化 |
| 9 | `tests/test_session.py:451` | `    assert out.read_text(encoding="utf-8").splitlines()[0] == "timestamp,speed"` | `test_export_csv_delegates_to_core` | utf-8-sig 化 |
| 10 | `tests/realgui/test_export_range_realclick.py:78` | `    lines = path.read_text(encoding="utf-8").splitlines()` | ヘルパ `_read_timestamps` | utf-8-sig 化 |

→ **編集する物理行は 9**（#4 を除く）。#1/#2/#3 は文字列が同一なので、`Edit` は**直前の `export(...)` 行を含めた 2 行**を `old_string` にして一意化する（`replace_all` は使わない — #5 や別ファイルへ波及する）。

編集後の確認:

```
uv run pytest -q
```
→ Step 1 の `N` に対して **`N + 20 passed`**・failed 0。

realgui 側（実ディスプレイが要る・①ゲートは Task 11 だが、読み口編集の妥当性はここで確かめる）:

```
uv run pytest tests/realgui/test_export_range_realclick.py --realgui -q
```
→ pass。実ディスプレイが無い環境なら skip されることを確認し、**skip だったことを報告に明記**する（pass と skip を混同しない）。

---

- [ ] **Step 8: 品質ゲートを通してコミットする**

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```
→ すべて exit 0。

```
git add -A
git commit -F - <<'EOF'
fix(core): CSV 出力へ UTF-8 BOM を付与し既存テストの読み口を utf-8-sig 化 (E-4b B1)

Excel(ja) が BOM 無し UTF-8 を cp932 と誤認してヘッダの日本語/ファイルキー
併記が化けるため、_atomic_write の書き encoding を utf-8-sig にした。
CsvLoader は既に utf-8-sig 読みなので往復は無修正で生存する。既存テストは
**期待内容を一切変えず**読み口 9 行のみ utf-8-sig 化し、各サイトへ supersede
コメントを残した (spec §7.1 の「既存テストは編集しない」原則の唯一の例外)。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
```

---

- [ ] **Step 9: sabotage で load-bearing を実証する**

**`git checkout -- src/...` で戻さない**（過去に実装者が自分の未コミット作業を消した）。各変異は手で入れて手で戻し、毎回 `git diff --stat` が空になったことを確認する。

| ID | 変異（src を書き換える） | 予測 RED |
|---|---|---|
| S1 | `_fmt_value` の非有限分岐を削除（`return _fmt(v, options)` だけにする） | 新規 4 本（`nan_value` / `inf` / `precision` / `indistinguishable`）＋`roundtrip` |
| S2 | `_quote` を `return cell` に（クォート撤去） | 新規 4 本（`delimiter_in_header` / `double_quote` / `newline` / `unit`）。**他は全 GREEN**（= 最小クォートが既存出力を 1 バイトも変えていない証拠） |
| S3 | `_quote` を無条件クォート（判定を `if True`） | 新規 3 本（`minimal_not_unconditional` / `configured_delimiter` / `empty_cell_not_quoted`）＋既存 `test_csv_export_options.py` の大半 |
| S4 | `_quote` の判定を `if "," in cell or ...`（`delimiter` を `","` 直書きに） | **既存** `test_comma_decimal_with_semicolon_delimiter` ＋新規 `configured_delimiter` |
| S5 | `_header_rows` の `_join` を素の `opts.delimiter.join` へ戻す（ヘッダ/単位行のクォート撤去 = spec [M-2] の変異） | 新規 `delimiter_in_header` / `double_quote` / `newline` / `unit_row` の 4 本。**データ行のテストは全 GREEN**（= ヘッダ/単位行への適用が独立に効いている証拠） |
| S6 | `_atomic_write` の encoding を `"utf-8"` に戻す | 新規 BOM 2 本のみ。**Step 7 で編集した 9 サイトは全 GREEN**（utf-8-sig は BOM 無しも読めるため）— 読み口編集が「BOM の有無どちらでも安全」であることの実証 |
| S7 | `csv_loader.py` の空セル分岐を削除 | 新規 loader 4 本（`accepts_empty` / `accepts_whitespace` / `emits_no_diagnostic` / `roundtrip`） |
| S8 | `_header_rows` の `or ""` を外す（`s.metadata.get("unit", "")` へ戻す） | 新規 `unit_none` 1 本（`TypeError`） |

各変異について **予測 RED と実測 RED を突き合わせて報告する**。不発（予測 RED なのに GREEN）は**予測を書き換えず発見として報告**する — テストが空虚である証拠なので、テストを強化するか、その旨を残す。

最後に残骸ゼロを確認:

```
git status --short
```
→ 出力が空であること。

---

- [ ] **Step 10: 最終ゲートと報告**

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```
→ すべて exit 0・`N + 20 passed`。

報告に含める:
- Step 1 のベースライン `N` / 最終値 `N + 20`
- Step 6 で実測した RED 本数（spec の「26 本」との差と、その解釈）
- Step 7 の編集行数（9）と、`#4` を意図的に除外した理由
- Step 9 の予測 RED vs 実測 RED（8 変異ぶん）
- realgui が pass だったか skip だったか

---

### Task 2: byte-identical ゴールデン（11 本・生成スクリプトは上書きを拒否）

Task 1 の是正後のバイトを凍結する。ゴールデンは「今こう出ている」を丸ごと固める強力なオラクルだが、**単独では意図を語らない**ので、Task 1 の契約テストと二枚で運用する（片方だけだと、将来の誰かがゴールデンを supersede して仕様を戻せてしまう）。

**この Task が閉じる spec の穴**:
- **M7**（spec §1）: `signals` ↔ `header_names` の対応を守るテストがゼロで `signals.reverse()` が全緑 → ゴールデン 11 本中 10 本が RED になる（Step 6 で実証）
- **MG-7**（spec §5.1-4）: `Session.export_csv` 直呼びのヘッダが raw namespaced 名 → 表示名導出形へ変わる。**主系のゴールデンは GUI 形（`csv_header_names` 由来）で駆動**して凍結し、passthrough 形も 1 本置く。これで Task 4 の `header_resolver`（既定 = passthrough）と GUI 注入版の**両方**がバイトで縛られる
- **M-4**（spec §5.4）: len 0 信号で searchsorted 素朴実装が IndexError → 現行の出力を先に凍結しておけば Task 6/7 が RED で気付く
- **ULP 分裂**（spec §5.4・C-1）: 分裂の**行数まで**凍結する

**Files:**
- Create: `tests/golden_csv_cases.py`（ケース定義＋駆動 — 生成とテストの唯一の共有点）
- Create: `tests/test_golden_csv.py`（バイト照合・孤児検出・感度オラクル・block_cols 申し送りガード）
- Create: `scripts/generate_golden_csv.py`（**上書きを拒否する**生成器・`--force` は意図的に用意しない）
- Create: `tests/golden_csv/g01..g11.csv`（コミットするバイト・11 ファイル）

**Interfaces:**
- Consumes（Task 1 の Produces）: `CsvExporter.export(signals, output_path, use_unified_timeline, options)` の現行シグネチャ・`CsvExportOptions(delimiter, decimal, unit_row, precision, header_names, time_start, time_end)`・BOM/最小クォート/非有限空セル/unit=None 空セルの挙動
- Consumes（既存）: `valisync.gui.display_names.csv_header_names`（pure Python・Qt import なし）・`valisync.core.session.Session`（`load` / `resolve_signal` / `remove_group`）
- Produces（Task 7 が消費する）:
  - `tests/golden_csv_cases.py`: `GoldenCase` / `GoldenInput` / `GOLDEN_CASES: tuple[GoldenCase, ...]` / `GOLDEN_DIR: Path` / `export_case(case, work_dir) -> bytes` / `BLOCK_COLS_VARIANTS: tuple[int | None, ...]`
  - `scripts/generate_golden_csv.py`: `main(golden_dir: Path = GOLDEN_DIR, cases: Sequence[GoldenCase] = GOLDEN_CASES) -> int`
- **Task 7 への申し送り（spec G1 の未充足部分）**: T-G 時点で `block_cols` は存在しない。Task 7 が列ブロック化したら、**同じ 11 ケースを `block_cols` を小さく注入して（複数ブロック・境界跨ぎで）再駆動しバイト一致を確認する**こと。忘れても誰も落ちない（1 ブロックのままでもバイトは一致する）ので、`test_block_cols_handoff_is_not_forgotten` が signature の変化を検知して強制する

---

- [ ] **Step 1: ケース定義モジュールを書く**

`tests/golden_csv_cases.py` を新規作成:

```python
"""ゴールデン CSV の入力ケース定義と駆動 (E-4b Task 2 / spec §7.1)。

**唯一の駆動点**: 生成スクリプト (``scripts/generate_golden_csv.py``) と照合
テスト (``tests/test_golden_csv.py``) の両方が ``export_case()`` を呼ぶ。
片方だけが知っている経路を作らないことで「生成したときと違う条件で比較する」
事故を構造的に消す。

**共有ヘルパに依存しない**: mf4 fixture は ``tests/mdf4_helpers.py`` を使わず
本モジュール内で完結させる。共有ヘルパは他タスクが自由に書き換える対象で、
そこに依存するとゴールデンが**無関係な編集で赤くなる** = 凍結の意味が消える。

**セル値は f(j, i) の単射** (spec §7.1 [I11])。列定数 f(j) だと searchsorted の
オフバイワンや行シフトでバイトが変わらず、オラクルが構造的に盲目になる。

**asammdf 依存の明示**: g08/g11 は実ローダーを通す。asammdf のラウンドトリップ
挙動 (2-D uint8 の列展開・TABX の生値保持) が変わればこの 2 本が RED になる。
それは誤検知ではなく**実挙動の変化**なので、RED になったらまずファイルを
読み戻して値を直接確認してから判断すること (ゴールデンの再生成で黙らせない)。

**ヘッダの駆動形 (MG-7)**: 主系 10 本は GUI と同じ導出形
(``csv_header_names`` → ``options.header_names``・export_csv_dialog.py:792-793
と同一) で凍結する。ユーザーが実際に見る形とゴールデンを一致させるため。
g02 だけが passthrough (raw namespaced 名) で、``Session.export_csv`` 直呼びの
既定バイトを凍結する — Task 4 の ``header_resolver`` 既定 (passthrough) が
これを再現しなければならない。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from valisync.core.export.csv_exporter import CsvExporter, CsvExportOptions
from valisync.core.models import Signal
from valisync.core.session import Session
from valisync.gui.display_names import csv_header_names

#: コミット済みゴールデンの置き場 (このファイルからの相対で解決する)。
GOLDEN_DIR = Path(__file__).resolve().parent / "golden_csv"

#: Task 7 が block_cols を導入したら「複数ブロックでも同じバイト」を駆動する
#: ための変種。T-G 時点では 1 ブロック相当の (None,) のみ。
#: test_block_cols_handoff_is_not_forgotten がこの定数と export の signature の
#: 同期を強制する (spec G1)。
BLOCK_COLS_VARIANTS: tuple[int | None, ...] = (None,)


# ─── 値の生成規則 ─────────────────────────────────────────────────────────────


def cell(j: int, i: int) -> float:
    """列 j (出力の値列 0 始まり)・行 i で**一意**な値。

    ``(j+1)*1000 + i`` は j < 100・i < 1000 の範囲で単射。列を入れ替えても行を
    ずらしても必ずバイトが変わる (列定数だとどちらにも盲目)。
    """
    return (j + 1) * 1000.0 + i


def cell_frac(j: int, i: int) -> float:
    """``cell`` の 1/3 ずらし版 — shortest round-trip repr (17 桁) を凍結する。

    ``1000.3333333333333`` のような repr が固まるので、``repr`` を ``str`` や
    numpy のベクトル化書式へ替える変更 (spec C-4 が禁じている) が必ず露見する。
    """
    return (j + 1) * 1000.0 + i / 3.0


def _cumulative(start: float, step: float, n: int) -> np.ndarray:
    """``start`` から ``step`` を**逐次加算**した float64 時刻列。

    ULP 分裂 (spec §5.4) は逐次加算でしか出ない: ``5.0 + 3*0.1`` は 5.3 だが
    ``((5.0+0.1)+0.1)+0.1`` は 5.300000000000001 になる。実 CANape の 10ms/100ms
    ラスタが分裂するのはこの機序なので、fixture も逐次加算で作る。
    """
    out = [start]
    for _ in range(n - 1):
        out.append(out[-1] + step)
    return np.array(out, dtype=np.float64)


def _sig(
    key: str,
    ts: Sequence[float] | np.ndarray,
    vs: Sequence[float] | np.ndarray,
    unit: str | None = "",
    *,
    unit_present: bool = True,
) -> Signal:
    """名前空間つきキーを ``name`` に持つ Signal (production と同じ形)。

    ``unit_present=False`` は metadata にキー自体を置かない (欠落) ケース。
    ``unit=None`` は「キーはあるが値が None」= spec §9-6 のケース。
    """
    metadata: dict[str, object] = {}
    if unit_present:
        metadata["unit"] = unit
    return Signal(
        name=key,
        timestamps=np.asarray(ts, dtype=np.float64),
        values=np.asarray(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata=metadata,
    )


def _noop() -> None:
    return None


# ─── ケースの型 ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GoldenInput:
    """1 ケースの export 入力一式。"""

    signals: list[Signal]
    #: 出力列順 = この順。``signal.name`` と 1:1 で一致すること (ヘッダと値を
    #: 同じキーから導出する契約・spec §10)。
    keys: tuple[str, ...]
    use_unified_timeline: bool
    options: CsvExportOptions
    #: True = GUI と同じ csv_header_names 導出形 / False = passthrough (raw keys)。
    derive_headers: bool = True
    #: mf4 ハンドルを閉じるなど、export 後に必ず走らせる後始末。
    close: Callable[[], None] = field(default=_noop)


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    build: Callable[[Path], GoldenInput]
    #: このケースが**単独で**守っている軸 (照合失敗時に読む人が最初に見る行)。
    why: str


def build_options(inp: GoldenInput) -> CsvExportOptions:
    """GUI (export_csv_dialog.py:792-793) と**同一手順**で header_names を埋める。"""
    if not inp.derive_headers:
        return inp.options
    header_map = csv_header_names(inp.keys)
    return replace(inp.options, header_names=tuple(header_map[k] for k in inp.keys))


def export_case(case: GoldenCase, work_dir: Path) -> bytes:
    """1 ケースを現行 API で駆動して出力バイトを返す。

    生成器とテストが**この関数だけ**を共有する。ここに入力を組む処理と export
    呼び出しを閉じ込めることで、「生成時は unified・照合時は shared」のような
    ずれが起こりえなくなる。
    """
    inp = case.build(work_dir)
    try:
        out = work_dir / f"{case.case_id}.csv"
        CsvExporter().export(
            inp.signals, out, inp.use_unified_timeline, build_options(inp)
        )
        return out.read_bytes()
    finally:
        inp.close()


# ─── ケース定義 ───────────────────────────────────────────────────────────────


_BASIC_KEYS = ("mf4_1::VehSpd", "mf4_1::EngSpeed", "mf4_1::Brake")
_BASIC_TS = [0.0, 0.5, 1.0, 1.5, 2.0]


def _basic_signals() -> list[Signal]:
    return [
        _sig(k, _BASIC_TS, [cell_frac(j, i) for i in range(len(_BASIC_TS))])
        for j, k in enumerate(_BASIC_KEYS)
    ]


def _build_shared_basic(_work: Path) -> GoldenInput:
    return GoldenInput(
        signals=_basic_signals(),
        keys=_BASIC_KEYS,
        use_unified_timeline=False,
        options=CsvExportOptions(),
    )


def _build_shared_passthrough_headers(_work: Path) -> GoldenInput:
    return GoldenInput(
        signals=_basic_signals(),
        keys=_BASIC_KEYS,
        use_unified_timeline=False,
        options=CsvExportOptions(),
        derive_headers=False,
    )


_GAP_KEYS = ("mf4_1::A", "mf4_1::B", "mf4_1::C")


def _gap_signals() -> list[Signal]:
    # 3 本のラスタをずらして union に穴を作り、そこへ NaN/±inf を重ねる。
    # t=1.0 の行は「A=正常値・B=NaN・C=-inf」= 欠測と非有限が同一バイトになる
    # ことをファイル上で示す唯一の行。
    return [
        _sig(_GAP_KEYS[0], [0.0, 1.0, 2.0], [cell(0, 0), cell(0, 1), cell(0, 2)]),
        _sig(_GAP_KEYS[1], [0.5, 1.0, 1.5], [cell(1, 0), float("nan"), float("inf")]),
        _sig(_GAP_KEYS[2], [1.0, 2.0], [float("-inf"), cell(2, 1)]),
    ]


def _build_unified_gaps_nonfinite(_work: Path) -> GoldenInput:
    return GoldenInput(
        signals=_gap_signals(),
        keys=_GAP_KEYS,
        use_unified_timeline=True,
        options=CsvExportOptions(),
    )


def _build_unified_range_closed(_work: Path) -> GoldenInput:
    # g03 と同じ信号を [0.5, 1.5] で閉区間フィルタ。両端がちょうどサンプル上に
    # 乗るので、`>=`->`>` / `<=`->`<` の変異と ±1 サンプルのずれが必ず出る。
    return GoldenInput(
        signals=_gap_signals(),
        keys=_GAP_KEYS,
        use_unified_timeline=True,
        options=CsvExportOptions(time_start=0.5, time_end=1.5),
    )


_QUOTE_KEYS = (
    "mf4_1::a,b",
    'mf4_1::say "hi"',
    "mf4_1::line\nbreak",
    "mf4_1::車速",
    "mf4_1::plain",
)


def _build_quoting_japanese_units(_work: Path) -> GoldenInput:
    ts = [0.0, 1.0]
    units: list[tuple[str | None, bool]] = [
        ("m,s", True),  # 単位に区切り文字 (単位行のクォート)
        ('in"ch', True),  # 単位に二重引用符
        (None, True),  # spec §9-6: キーはあるが None
        ("km/h", True),
        (None, False),  # キー欠落 (従来の既定 "")
    ]
    signals = [
        _sig(
            key,
            ts,
            [cell(j, i) for i in range(len(ts))],
            unit=u,
            unit_present=present,
        )
        for j, (key, (u, present)) in enumerate(zip(_QUOTE_KEYS, units, strict=True))
    ]
    return GoldenInput(
        signals=signals,
        keys=_QUOTE_KEYS,
        use_unified_timeline=False,
        options=CsvExportOptions(unit_row=True),
    )


_OPT_KEYS = ("mf4_1::spd", "mf4_1::rpm")


def _build_semicolon_precision_units(_work: Path) -> GoldenInput:
    ts = [0.0, 1.0]
    signals = [
        _sig(_OPT_KEYS[0], ts, [cell_frac(0, 0), float("nan")], unit="km/h"),
        _sig(_OPT_KEYS[1], ts, [cell_frac(1, 0), cell_frac(1, 1)], unit="1/min"),
    ]
    # decimal="," のセル (1000,333) が **クォートされない** ことと、precision 分岐の
    # NaN が空セルになることを 1 本で凍結する。
    return GoldenInput(
        signals=signals,
        keys=_OPT_KEYS,
        use_unified_timeline=True,
        options=CsvExportOptions(
            delimiter=";", decimal=",", precision=3, unit_row=True
        ),
    )


_ULP_KEYS = ("mf4_1::fast", "mf4_1::slow")


def _build_unified_ulp_split(_work: Path) -> GoldenInput:
    # 10ms x 51 点 と 100ms x 6 点。数学的には slow ⊂ fast だが、逐次加算の
    # 丸めで一致するのは t=5.0 だけ → union は 51 + 5 = 56 行に分裂する
    # (spec §5.4 の「今日すでに分裂している」の最小再現)。
    fast_ts = _cumulative(5.0, 0.01, 51)
    slow_ts = _cumulative(5.0, 0.1, 6)
    signals = [
        _sig(_ULP_KEYS[0], fast_ts, [cell(0, i) for i in range(len(fast_ts))]),
        _sig(_ULP_KEYS[1], slow_ts, [cell(1, i) for i in range(len(slow_ts))]),
    ]
    return GoldenInput(
        signals=signals,
        keys=_ULP_KEYS,
        use_unified_timeline=True,
        options=CsvExportOptions(),
    )


#: g07 の union 行数 (= データ行数)。実測値 (Step 3 で生成時に確認)。
#: 「分裂の行数まで凍結する」(spec §7.1) を、バイト差分を読まずに一目で
#: 分かる形にしておくための独立オラクル。
ULP_EXPECTED_ROWS = 56


def _write_golden_mdf4_dedup_enum(path: Path) -> Path:
    """同名 2-D uint8 x2 (dedup) + enum + 通常 の mf4。

    ローダー実測 (asammdf 8.8.22):
      mf4_1::W[0][0] = [0,2,4,6] / mf4_1::W[0][1] = [1,3,5,7]
      mf4_1::W[1][0] = [100,102,104,106] / mf4_1::W[1][1] = [101,103,105,107]
      mf4_1::Enum = [0.0,1.0,2.0,3.0] / mf4_1::Clean = [1.5,2.5,3.5,4.5]

    2-D は **uint8 でなければ往復しない** (float64 の 2-D は (N,w) -> (N,) へ
    潰れる — mdf4_helpers.py の同旨の注記)。値が 0-255 に制限されるので
    ``cell()`` は使えず、``base + 2*i + j`` の単射規則を使う。
    enum の samples を [0,1,2,3] にしてあるのは、[0,1,2,1] だと列内に重複が
    出て行シフトに鈍感になるため。
    """
    from asammdf import MDF
    from asammdf import Signal as ASignal
    from asammdf.blocks.conversion_utils import from_dict

    ts = np.array([0.0, 0.1, 0.2, 0.3], dtype=np.float64)
    mdf = MDF()
    try:
        for base in (0, 100):
            samples = np.array(
                [[base + 2 * i + j for j in range(2)] for i in range(4)],
                dtype=np.uint8,
            )
            mdf.append([ASignal(samples=samples, timestamps=ts, name="W", unit="m")])
        conv = from_dict(
            {
                "val_0": 0,
                "text_0": "S0",
                "val_1": 1,
                "text_1": "S1",
                "val_2": 2,
                "text_2": "S2",
                "val_3": 3,
                "text_3": "S3",
            }
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([0, 1, 2, 3], dtype=np.int16),
                    timestamps=ts,
                    name="Enum",
                    conversion=conv,
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.5, 2.5, 3.5, 4.5]),
                    timestamps=ts,
                    name="Clean",
                    unit="km/h",
                )
            ]
        )
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


_DEDUP_LEAVES = ("W[0][0]", "W[0][1]", "W[1][0]", "W[1][1]", "Enum", "Clean")


def _build_mdf_dedup_enum_columns(work: Path) -> GoldenInput:
    path = _write_golden_mdf4_dedup_enum(work / "golden_dedup_enum.mf4")
    session = Session()
    group_key = session.load(path).key
    assert group_key == "mf4_1", f"グループキーが想定外: {group_key}"
    keys = tuple(f"{group_key}::{leaf}" for leaf in _DEDUP_LEAVES)
    signals: list[Signal] = []
    for k in keys:
        sig = session.resolve_signal(k)
        assert sig is not None, f"列キーが解決できない: {k}"
        signals.append(sig)
    return GoldenInput(
        signals=signals,
        keys=keys,
        use_unified_timeline=False,
        options=CsvExportOptions(unit_row=True),
        # 遅延読み (LazyMdfValues) なので export が終わるまでハンドルを開けておく。
        # force=True は「Derived の依存が無いか」の判定を飛ばすため (この Session
        # は本ケース専用で Derived を持たない)。閉じないと tmp_path の後始末が
        # Windows で失敗する。
        close=lambda: session.remove_group(group_key, force=True),
    )


_EDGE_KEYS = ("mf4_1::empty", "mf4_1::messy", "mf4_1::clean")


def _build_unified_len0_nonmonotonic(_work: Path) -> GoldenInput:
    signals = [
        # LD-09 のヘッダのみ CSV 相当。素朴な searchsorted 実装は IndexError に
        # なる (spec §5.4 [M-4]) ので、現行の出力を先に凍結しておく。
        _sig(_EDGE_KEYS[0], [], []),
        # 非単調 + 重複。sorted_view は同時刻で **最後に記録された値** を残す
        # (CAN の last received wins) — t=1.0 の値が cell(1,3) になる。
        _sig(
            _EDGE_KEYS[1],
            [0.0, 2.0, 1.0, 1.0],
            [cell(1, 0), cell(1, 1), cell(1, 2), cell(1, 3)],
        ),
        _sig(_EDGE_KEYS[2], [0.0, 1.0, 2.0], [cell(2, i) for i in range(3)]),
    ]
    return GoldenInput(
        signals=signals,
        keys=_EDGE_KEYS,
        use_unified_timeline=True,
        options=CsvExportOptions(),
    )


_SOLO_KEYS = ("mf4_1::solo",)


def _build_shared_single_column_range(_work: Path) -> GoldenInput:
    ts = [0.0, 1.0, 2.0, 3.0]
    return GoldenInput(
        signals=[_sig(_SOLO_KEYS[0], ts, [cell(0, i) for i in range(len(ts))])],
        keys=_SOLO_KEYS,
        use_unified_timeline=False,
        options=CsvExportOptions(time_start=1.0, time_end=2.0),
    )


def _write_golden_mdf4_plain(path: Path, channels: list[tuple[str, list[float], list[float], str]]) -> Path:
    """1 チャンネル 1 グループの素の mf4 (g11 用・float64 のみ)。"""
    from asammdf import MDF
    from asammdf import Signal as ASignal

    mdf = MDF()
    try:
        for name, ts, vs, unit in channels:
            mdf.append(
                [
                    ASignal(
                        samples=np.asarray(vs, dtype=np.float64),
                        timestamps=np.asarray(ts, dtype=np.float64),
                        name=name,
                        unit=unit,
                    )
                ]
            )
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def _build_unified_cross_file_collision(work: Path) -> GoldenInput:
    """2 ファイルに同名 ``Spd`` + 片方に文字どおり ``timestamp`` という名の信号。

    ``csv_header_names`` の 2 つの分岐を同時に踏む唯一のケース:
      - 別グループが同じ bare 名を持つ -> ``Spd(mf4_1)`` / ``Spd(mf4_2)``
      - 母集合に常設注入された "timestamp" と衝突 -> ``timestamp(mf4_1)``
    ファイルキー併記のヘッダは BOM を入れた動機そのもの (spec §5.1-2)。
    """
    ta = [0.0, 1.0, 2.0]
    tb = [0.5, 1.0, 1.5]
    p1 = _write_golden_mdf4_plain(
        work / "golden_cross_a.mf4",
        [
            ("Spd", ta, [cell(0, i) for i in range(3)], "km/h"),
            ("timestamp", ta, [cell(1, i) for i in range(3)], "s"),
        ],
    )
    p2 = _write_golden_mdf4_plain(
        work / "golden_cross_b.mf4",
        [("Spd", tb, [cell(2, i) for i in range(3)], "km/h")],
    )
    session = Session()
    k1 = session.load(p1).key
    k2 = session.load(p2).key
    assert (k1, k2) == ("mf4_1", "mf4_2"), f"グループキーが想定外: {k1}/{k2}"
    keys = (f"{k1}::Spd", f"{k1}::timestamp", f"{k2}::Spd")
    signals: list[Signal] = []
    for k in keys:
        sig = session.resolve_signal(k)
        assert sig is not None, f"列キーが解決できない: {k}"
        signals.append(sig)

    def _close() -> None:
        session.remove_group(k1, force=True)
        session.remove_group(k2, force=True)

    return GoldenInput(
        signals=signals,
        keys=keys,
        use_unified_timeline=True,
        options=CsvExportOptions(unit_row=True),
        close=_close,
    )


GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        "g01_shared_basic",
        _build_shared_basic,
        "単一タイムライン・範囲なし・GUI 形ヘッダ・3 列。列順/ヘッダ対応/LF/BOM/"
        "最小クォート非適用/shortest repr の基準線",
    ),
    GoldenCase(
        "g02_shared_passthrough_headers",
        _build_shared_passthrough_headers,
        "header_names=None (passthrough) の raw namespaced ヘッダ。Task 4 の "
        "header_resolver 既定が再現すべきバイト (MG-7)",
    ),
    GoldenCase(
        "g03_unified_gaps_nonfinite",
        _build_unified_gaps_nonfinite,
        "統合タイムライン・欠測・NaN・±inf。欠測と非有限が同一バイトになる契約",
    ),
    GoldenCase(
        "g04_unified_range_closed",
        _build_unified_range_closed,
        "統合タイムライン + 閉区間 [0.5, 1.5]。両端がサンプル上に乗る境界",
    ),
    GoldenCase(
        "g05_quoting_japanese_units",
        _build_quoting_japanese_units,
        "要クォート名 3 種 (区切り/引用符/改行)・日本語・単位行・unit=None/欠落",
    ),
    GoldenCase(
        "g06_semicolon_precision_units",
        _build_semicolon_precision_units,
        "delimiter=';' + decimal=',' + precision=3 + 単位行 + precision 分岐の NaN",
    ),
    GoldenCase(
        "g07_unified_ulp_split",
        _build_unified_ulp_split,
        "ULP 分裂 (10ms x 51 と 100ms x 6 が 56 行へ分裂) — 行数まで凍結",
    ),
    GoldenCase(
        "g08_mdf_dedup_enum_columns",
        _build_mdf_dedup_enum_columns,
        "実 mf4 ロード経路: 重複名 dedup (W[0]/W[1]) + 2-D 列展開 + enum + 単位行",
    ),
    GoldenCase(
        "g09_unified_len0_nonmonotonic",
        _build_unified_len0_nonmonotonic,
        "len 0 信号 (M-4 の IndexError 予防) + 非単調/重複 ts の last-wins",
    ),
    GoldenCase(
        "g10_shared_single_column_range",
        _build_shared_single_column_range,
        "1 列のみ + 単一タイムライン + 範囲 [1.0, 2.0]。末尾余分区切りの検出",
    ),
    GoldenCase(
        "g11_unified_cross_file_collision",
        _build_unified_cross_file_collision,
        "2 ファイル同名 Spd と信号名 'timestamp' -> csv_header_names の衝突 2 分岐",
    ),
)
```

---

- [ ] **Step 2: 照合テストを書く（この時点で RED）**

`tests/test_golden_csv.py` を新規作成:

```python
"""出力バイトのゴールデン照合 (E-4b Task 2 / spec §7.1・G1)。

``read_bytes()`` の全文一致。ゴールデンは **BOM・行末 LF・クォート・区切り・
列順・ヘッダ導出形・repr・空セル** を一度に縛る唯一のオラクルで、Task 4-7 の
書き経路の全面再構築 (keys 化 -> 列ブロック -> 多段マージ) がバイトを 1 個も
変えていないことの受け入れ条件になる。

**再生成で黙らせない (spec G1)**: ``scripts/generate_golden_csv.py`` は既存
ファイルがあると何も書かずに終了する。意図的な変更は対象を ``git rm`` して
理由を docs/design.md 決定履歴へ記録してからの手動 supersede のみ。

**ゴールデンだけでは足りない部分**: ゴールデンは「今こう出ている」を固める
だけで、**オラクル自身が入力の何に反応するか**は語らない。列順を反転しても
バイトが変わらない実装 (spec §1 の M7 = 現状「全緑」) を捕まえるには、
入力を変えてバイトが**変わる**ことを直接見る必要がある — それが本ファイル
後半の感度オラクル群。
"""

from __future__ import annotations

import difflib
import inspect
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from tests.golden_csv_cases import (
    BLOCK_COLS_VARIANTS,
    GOLDEN_CASES,
    GOLDEN_DIR,
    ULP_EXPECTED_ROWS,
    GoldenCase,
    GoldenInput,
    build_options,
    export_case,
)
from valisync.core.export.csv_exporter import CsvExporter

_CASES_BY_ID = {c.case_id: c for c in GOLDEN_CASES}


def _golden_path(case_id: str) -> Path:
    return GOLDEN_DIR / f"{case_id}.csv"


def _diff_message(case: GoldenCase, expected: bytes, actual: bytes) -> str:
    """バイト差分を人が読める形に落とす。

    BOM/CRLF/末尾改行の差は decode 後の diff に**現れない**ので、先頭バイトと
    行末の種類を別途明記する (「diff が空なのに落ちる」を防ぐ)。
    """
    head = [
        f"case={case.case_id} ({case.why})",
        f"expected {len(expected)} bytes / actual {len(actual)} bytes",
        f"expected BOM={expected[:3]!r} / actual BOM={actual[:3]!r}",
        f"expected CRLF={expected.count(b'\r\n')} / actual CRLF={actual.count(b'\r\n')}",
    ]
    diff = difflib.unified_diff(
        expected.decode("utf-8-sig").splitlines(keepends=True),
        actual.decode("utf-8-sig").splitlines(keepends=True),
        fromfile="golden",
        tofile="actual",
        n=2,
    )
    return "\n".join([*head, "", *list(diff)[:60]])


# ─── 本体: バイト一致 ────────────────────────────────────────────────────────


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.case_id)
def test_golden_bytes_match(case: GoldenCase, tmp_path: Path) -> None:
    expected = _golden_path(case.case_id).read_bytes()
    actual = export_case(case, tmp_path)
    assert actual == expected, _diff_message(case, expected, actual)


def test_every_case_has_exactly_one_golden_file() -> None:
    """孤児と欠落の双方向検出。

    片方向 (ケース -> ファイル) だけだと、ケースを消したときに古いゴールデンが
    残り続け、次に同じ case_id を足した人が**別の意図のバイト**と照合される。
    """
    on_disk = {p.stem for p in GOLDEN_DIR.glob("*.csv")}
    declared = {c.case_id for c in GOLDEN_CASES}
    assert on_disk == declared, (
        f"孤児={sorted(on_disk - declared)} / 欠落={sorted(declared - on_disk)}"
    )


def test_all_goldens_start_with_a_bom_and_use_lf_line_endings() -> None:
    """凍結した 3 つの大域性質を、ケースを跨いで 1 本で言い切る。

    個々のバイト比較でも捕まるが、失敗メッセージが「56 行のどこかが違う」に
    なって読めない。ここが先に落ちれば原因が 1 行で分かる。
    """
    for case in GOLDEN_CASES:
        raw = _golden_path(case.case_id).read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), case.case_id
        assert raw.count(b"\xef\xbb\xbf") == 1, case.case_id
        assert b"\r" not in raw, case.case_id  # 行末 LF (据え置き決定)
        assert raw.endswith(b"\n"), case.case_id  # 末尾改行あり (据え置き決定)


def test_ulp_split_row_count_is_frozen() -> None:
    """分裂の**行数まで**凍結する (spec §7.1)。

    バイト比較でも当然捕まるが、行数を独立に言うことで「union の畳み方を
    tolerance 化した (spec C-1 が禁止)」という**意味**の退行が一目で分かる。
    反 vacuous: 分裂していなければ 51 行 (fast の点数) のはずで、56 > 51 が
    「実際に分裂している」ことの証拠。
    """
    raw = _golden_path("g07_unified_ulp_split").read_bytes()
    data_rows = raw.decode("utf-8-sig").splitlines()[1:]
    assert len(data_rows) == ULP_EXPECTED_ROWS
    assert ULP_EXPECTED_ROWS > 51, "分裂していない fixture では軸を守れない"


# ─── 感度オラクル: 入力を変えたらバイトが変わること ──────────────────────────


def _export_with(
    mutate: Callable[[GoldenInput], GoldenInput], case_id: str, tmp_path: Path
) -> bytes:
    """ケースの入力を変異させて export する (src は一切触らない)。"""
    case = _CASES_BY_ID[case_id]
    inp = case.build(tmp_path)
    try:
        mutated = mutate(inp)
        out = tmp_path / "mutated.csv"
        CsvExporter().export(
            mutated.signals,
            out,
            mutated.use_unified_timeline,
            build_options(mutated),
        )
        return out.read_bytes()
    finally:
        inp.close()


def test_reversed_column_order_changes_the_bytes(tmp_path: Path) -> None:
    """列順はゴールデンが縛る対象そのもの (spec §10)。"""
    actual = _export_with(
        lambda inp: replace(
            inp, signals=list(reversed(inp.signals)), keys=tuple(reversed(inp.keys))
        ),
        "g01_shared_basic",
        tmp_path,
    )
    golden = _golden_path("g01_shared_basic").read_bytes()
    assert actual != golden
    header = actual.decode("utf-8-sig").splitlines()[0]
    assert header == "timestamp,Brake,EngSpeed,VehSpd"


def test_signals_reversed_without_headers_changes_the_bytes(tmp_path: Path) -> None:
    """spec §1 の M7 (``signals.reverse()`` で全緑) を閉じる。

    keys はそのまま = ヘッダ不変で**値の列だけ**入れ替わる形。ヘッダと値を
    別々に運ぶ実装が黙って対応を崩したときの唯一の検出点。
    """
    actual = _export_with(
        lambda inp: replace(inp, signals=list(reversed(inp.signals))),
        "g01_shared_basic",
        tmp_path,
    )
    golden = _golden_path("g01_shared_basic").read_bytes()
    assert actual != golden
    lines = actual.decode("utf-8-sig").splitlines()
    assert lines[0] == "timestamp,VehSpd,EngSpeed,Brake"  # ヘッダは不変
    assert lines[1] != golden.decode("utf-8-sig").splitlines()[1]  # 値は入れ替わる


def test_dropping_columns_changes_the_bytes(tmp_path: Path) -> None:
    """列の部分集合がゴールデンと一致しないこと (= ゴールデンは列集合に敏感)。"""
    actual = _export_with(
        lambda inp: replace(inp, signals=inp.signals[:1], keys=inp.keys[:1]),
        "g01_shared_basic",
        tmp_path,
    )
    assert actual != _golden_path("g01_shared_basic").read_bytes()
    assert actual.decode("utf-8-sig").splitlines()[0] == "timestamp,VehSpd"


def test_changing_the_delimiter_changes_the_bytes(tmp_path: Path) -> None:
    actual = _export_with(
        lambda inp: replace(inp, options=replace(inp.options, delimiter=";")),
        "g01_shared_basic",
        tmp_path,
    )
    assert actual != _golden_path("g01_shared_basic").read_bytes()


def test_changing_the_precision_changes_the_bytes(tmp_path: Path) -> None:
    actual = _export_with(
        lambda inp: replace(inp, options=replace(inp.options, precision=6)),
        "g01_shared_basic",
        tmp_path,
    )
    assert actual != _golden_path("g01_shared_basic").read_bytes()


@pytest.mark.parametrize(
    ("start", "end"),
    [(0.0, 1.5), (0.5, 2.0)],
    ids=["start_minus_one_sample", "end_plus_one_sample"],
)
def test_range_boundary_off_by_one_sample_changes_the_bytes(
    start: float, end: float, tmp_path: Path
) -> None:
    """境界を 1 サンプル動かすと必ずバイトが変わること。

    ``_in_range`` の ``>=`` / ``<=`` を片側だけ壊す変異は、ゴールデンの中身が
    境界サンプルを含んでいなければ素通りする — g04 の両端がサンプル上に
    乗っていることがこのテストの前提。
    """
    actual = _export_with(
        lambda inp: replace(
            inp, options=replace(inp.options, time_start=start, time_end=end)
        ),
        "g04_unified_range_closed",
        tmp_path,
    )
    assert actual != _golden_path("g04_unified_range_closed").read_bytes()


def test_empty_selection_fails_loudly_and_writes_no_file(tmp_path: Path) -> None:
    """空選択の**現行**契約を凍結する: 例外・ファイル無し。

    今日は ``_rows_shared_timeline`` が ``views[0]`` で IndexError、
    ``_rows_unified_timeline`` が ``np.concatenate([])`` で ValueError になる。
    GUI は ``_on_accept`` の ``if not keys: return`` で到達させないが、
    ``Session.export_csv`` 直呼びは到達する。**沈黙して空ファイルを書く**
    (ヘッダだけの CSV を「成功」として渡す) 形へ degrade させないことが要点で、
    Task 6/7 の再構築後も何らかの loud-fail が残ることをここで縛る。
    """
    out = tmp_path / "empty.csv"
    for unified in (False, True):
        with pytest.raises((IndexError, ValueError)):
            CsvExporter().export([], out, unified)
        assert not out.exists()


# ─── Task 7 への申し送りガード ───────────────────────────────────────────────


def test_block_cols_handoff_is_not_forgotten() -> None:
    """spec G1「ゴールデンは複数ブロック (境界跨ぎ) で駆動」を強制する。

    T-G 時点で ``block_cols`` は存在しない。Task 7 が列ブロック化したとき、
    ゴールデンを 1 ブロックのまま走らせても**バイトは一致する** — つまり
    「境界跨ぎで駆動する」という受け入れ条件は、忘れても誰も落ちない。
    ``block_cols`` が現れた瞬間にここが RED になり、``BLOCK_COLS_VARIANTS`` の
    拡張と driver の追随を強制する。

    **見るのは ``__init__``**: Task 6/7 は ``block_cols`` を **コンストラクタの
    注入口** に置く (``export()`` の署名は共有インターフェース契約で凍結されて
    いるため)。``export`` の署名を見ると block_cols は永久に現れず、この
    ガードは恒久的に空虚になる (G1「複数ブロック駆動」の強制が消える)。
    """
    params = inspect.signature(CsvExporter.__init__).parameters
    has_block_cols = "block_cols" in params
    assert has_block_cols == (len(BLOCK_COLS_VARIANTS) > 1), (
        "block_cols の導入とゴールデンの複数ブロック駆動は同時に行うこと "
        f"(signature={list(params)}, variants={BLOCK_COLS_VARIANTS})"
    )
```

実行して RED を確認する:

```
uv run pytest tests/test_golden_csv.py -q
```

**予測 RED**: `tests/golden_csv/` がまだ無いので
- `test_golden_bytes_match[g01..g11]` の 11 本が `FileNotFoundError`
- `test_every_case_has_exactly_one_golden_file` が「欠落=11」で fail
- `test_all_goldens_start_with_a_bom_and_use_lf_line_endings` が `FileNotFoundError`
- `test_ulp_split_row_count_is_frozen` が `FileNotFoundError`
- 感度オラクル 7 本（`reversed` / `signals_reversed` / `dropping` / `delimiter` / `precision` / `boundary` x2）も golden 読みで `FileNotFoundError`
- `test_empty_selection_fails_loudly_and_writes_no_file` は **pass**
- `test_block_cols_handoff_is_not_forgotten` は **pass**

→ **予測: 21 failed, 2 passed**（`FileNotFoundError` が支配的）

---

- [ ] **Step 3: 生成スクリプトを書いてゴールデンを 1 回だけ作る**

`scripts/generate_golden_csv.py` を新規作成:

```python
"""ゴールデン CSV を生成する (E-4b Task 2)。**再生成は禁止**。

    uv run python scripts/generate_golden_csv.py

**既存のゴールデンを 1 つでも見つけたら何も書かずに終了する** (exit 1)。
ゴールデンは出力バイトの凍結そのものなので、「壊してから再生成して差分を見る」
運用にすると凍結が凍結でなくなる — 実装を壊した本人が再生成すれば常に緑になる
(spec G1)。

意図的な変更は **supersede**: 対象ファイルを ``git rm`` で明示的に落とし、
理由を docs/design.md 決定履歴へ記録してから本スクリプトを走らせる。
``--force`` は**意図的に用意しない** (用意した瞬間に上の抑止が効かなくなる)。
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    # `python scripts/x.py` では sys.path[0] が scripts/ になり tests/ が見えない。
    sys.path.insert(0, str(_REPO_ROOT))

from tests.golden_csv_cases import (  # noqa: E402  (sys.path 調整の後でしか import できない)
    GOLDEN_CASES,
    GOLDEN_DIR,
    GoldenCase,
    export_case,
)


def main(
    golden_dir: Path = GOLDEN_DIR,
    cases: Sequence[GoldenCase] = GOLDEN_CASES,
) -> int:
    golden_dir.mkdir(parents=True, exist_ok=True)
    existing = [c.case_id for c in cases if (golden_dir / f"{c.case_id}.csv").exists()]
    if existing:
        print("既存のゴールデンがあるため**何も書かずに**中止しました (spec G1):")
        for case_id in existing:
            print(f"  {golden_dir / (case_id + '.csv')}")
        print(
            "意図的に更新する場合は、対象を `git rm` して理由を "
            "docs/design.md 決定履歴へ記録してから再実行してください。"
        )
        return 1
    # **全ケースを組み立ててから書く** (二相)。途中のケースが例外を投げたときに
    # 部分的なゴールデンが残ると、次の実行は「既存あり」で拒否され、直すには
    # 半端なファイルを git rm する必要が出る = 拒否の仕組み自体が罠になる。
    produced: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for case in cases:
            produced[case.case_id] = export_case(case, work)
    for case_id, data in produced.items():
        (golden_dir / f"{case_id}.csv").write_bytes(data)
        n_lines = data.count(b"\n")
        print(f"wrote {case_id}.csv  ({len(data)} bytes, {n_lines} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

生成する:

```
uv run python scripts/generate_golden_csv.py
```
→ 11 行の `wrote ...` が出て exit 0。**`g07_unified_ulp_split.csv` の lines が 57**（ヘッダ 1 + データ 56）であることを確認する。57 でなければ `ULP_EXPECTED_ROWS` の値が実測と違う＝**停止して報告**（fixture か numpy の丸めが想定と違う）。

生成物を目視する（凍結する前に**人が一度読む** — これが仕様レビューの唯一の機会）:

```
uv run python -c "import pathlib
for p in sorted(pathlib.Path('tests/golden_csv').glob('*.csv')):
    print('=' * 8, p.name); print(p.read_text(encoding='utf-8-sig'))"
```
（リスト内包の中に `;` は置けない — `[print(a);print(b) for p in ...]` は SyntaxError。**ループ形で書く**。）

**期待する主要バイト**（一致しなければ停止して報告）:

| ファイル | 期待 |
|---|---|
| g01 | `timestamp,VehSpd,EngSpeed,Brake` / `0.0,1000.0,2000.0,3000.0` / `0.5,1000.3333333333333,2000.3333333333333,3000.3333333333333` … 計 5 データ行 |
| g02 | `timestamp,mf4_1::VehSpd,mf4_1::EngSpeed,mf4_1::Brake`（データ行は g01 と同一） |
| g03 | `timestamp,A,B,C` / `0.0,1000.0,,` / `0.5,,2000.0,` / `1.0,1001.0,,` / `1.5,,,` / `2.0,1002.0,,3001.0` |
| g04 | `timestamp,A,B,C` ＋ g03 の t=0.5/1.0/1.5 の 3 行のみ |
| g05 | `timestamp,"a,b","say ""hi""","line`＋改行＋`break",車速,plain` / 単位行 `s,"m,s","in""ch",,km/h,` |
| g06 | `timestamp;spd;rpm` / `s;km/h;1/min` / `0,000;1000,000;2000,000` / `1,000;;2000,333` |
| g07 | ヘッダ ＋ **56 データ行**・先頭 `5.0,1000.0,2000.0` |
| g08 | `timestamp,W[0][0],W[0][1],W[1][0],W[1][1],Enum,Clean` / `s,m,m,m,m,,km/h` / `0.0,0.0,1.0,100.0,101.0,0.0,1.5` … 4 データ行 |
| g09 | `timestamp,empty,messy,clean` / `0.0,,2000.0,3000.0` / `1.0,,2003.0,3001.0` / `2.0,,2001.0,3002.0` |
| g10 | `timestamp,solo` / `1.0,1001.0` / `2.0,1002.0` |
| g11 | `timestamp,Spd(mf4_1),timestamp(mf4_1),Spd(mf4_2)` / 単位行 `s,km/h,s,km/h` / 5 データ行（union = 0.0/0.5/1.0/1.5/2.0） |

照合テストを実行:

```
uv run pytest tests/test_golden_csv.py -q
```
→ **予測: 23 passed**（21 本の RED がすべて解消・感度オラクルも通る）

---

- [ ] **Step 4: 上書き拒否を恒久テストで縛る**

`tests/test_golden_csv.py` の末尾に追記:

```python
# ─── 生成器の上書き拒否 (spec G1) ────────────────────────────────────────────


def test_generator_refuses_to_overwrite_existing_goldens(tmp_path: Path) -> None:
    """2 回目の生成は**何も書かずに** exit 1 を返す。

    ここが緩むと「壊してから再生成」でゴールデンを黙らせられるようになる。
    1 ケースだけで駆動するのは、11 本を毎回作り直すコストを避けるため
    (拒否の判定はケース数に依存しない)。

    さらに 1 回目の生成物がコミット済みバイトと一致することも見る — 生成器と
    照合テストが同じ export_case を通っていることの独立確認 (別経路で作られた
    ゴールデンをうっかりコミットする事故の検出)。
    """
    from scripts.generate_golden_csv import main

    case = _CASES_BY_ID["g01_shared_basic"]
    assert main(golden_dir=tmp_path, cases=[case]) == 0
    produced = (tmp_path / f"{case.case_id}.csv").read_bytes()
    assert produced == _golden_path(case.case_id).read_bytes()

    before = produced
    assert main(golden_dir=tmp_path, cases=[case]) == 1
    assert (tmp_path / f"{case.case_id}.csv").read_bytes() == before


def test_generator_has_no_force_switch() -> None:
    """``--force`` 相当を持たないことを構造で縛る (spec G1)。

    「拒否する」実装は簡単に「拒否をスキップできる」実装へ育つ。main の
    キーワードに force/overwrite の類が現れたら RED。
    """
    from scripts.generate_golden_csv import main

    params = set(inspect.signature(main).parameters)
    assert params == {"golden_dir", "cases"}, params
```

`scripts` を import できるようにする必要があるか確認する（`tests/test_golden_csv.py` から `from scripts.generate_golden_csv import main`）:

```
uv run pytest tests/test_golden_csv.py -q
```
→ `ModuleNotFoundError: No module named 'scripts'` が出たら、pytest の rootdir が `sys.path` に入っていない。**その場合は `tests/test_golden_csv.py` 冒頭に以下を置く**（`tests.golden_csv_cases` が解決できている以上 rootdir は通っているはずなので、まず走らせて確認してから対処する）:

```python
import sys

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
```

→ **予測: 25 passed**

---

- [ ] **Step 5: 決定性を実プロセス跨ぎで確認する**

同一プロセス内で 2 回作っても、辞書のハッシュ順に依存する経路は露見しない。**プロセスを分けてハッシュシードを変える**:

```
PYTHONHASHSEED=0 uv run pytest tests/test_golden_csv.py -q
PYTHONHASHSEED=123456 uv run pytest tests/test_golden_csv.py -q
```
（**Bash ツールで実行する** — PowerShell には inline の env var 前置が無い。PowerShell なら `$env:PYTHONHASHSEED='0'; uv run pytest tests/test_golden_csv.py -q` の 2 文に分ける。）

→ 両方 **25 passed**。差が出たら、出力のどこかが `set`/`dict` の反復順に依存している（`csv_header_names` の `groups_by_bare` が最有力）ので**停止して報告**する。

---

- [ ] **Step 6: sabotage — 予測 RED と実測 RED を突き合わせる**

spec §9-7 は「変異 M1/M2/M3/M4/M6/M8 の『全緑』は静的分析ベース — T-G の sabotage で再実行して確認」とするが、**探索の M1..M8 の定義は spec にも repo にも残っていない**（`git grep` で 0 件）。よって **T-G が自分の変異表を一次情報源として定義し直す**。spec が名指しで内容を語っている 2 件（**M5** = export のインライン化／**M7** = `signals.reverse()`）は同じ番号で引き継ぐ。

**`git checkout -- src/...` で戻さない**。各変異は手で入れて手で戻し、毎回 `git status --short` が空になったことを確認する。

| ID | 変異 | 予測 RED |
|---|---|---|
| M1 | `_atomic_write` の `"\n".join(lines)` → `"\r\n".join(lines)`（行末 CRLF 化） | ゴールデン 11/11 ＋ `test_all_goldens_start_with_a_bom_and_use_lf_line_endings` |
| M2 | `_atomic_write` の encoding を `"utf-8"` へ（BOM 除去） | ゴールデン 11/11 ＋ BOM 大域テスト。**Task 1 の読み口 9 サイトは GREEN のまま**（utf-8-sig は BOM 無しも読める） |
| M3 | `_quote` を `return cell`（クォート除去） | **g05 / g06 のみ**（他 9 本は GREEN = 最小クォートが他ケースのバイトを 1 個も変えていない証拠） |
| M4 | `_header_rows` の `_join` を素の `opts.delimiter.join` へ（ヘッダ/単位行のクォート撤去 = spec [M-2]） | **g05 / g06 のみ**（データ行のクォートは生きているので、ヘッダ側への適用が独立に効いていることが分かる） |
| M5 | `_fmt_value` の非有限分岐を削除 | **g03 / g06**（g06 は precision 分岐の NaN） |
| M6 | `_in_range` の `t >= opts.time_start` → `t > opts.time_start` | **g04 / g10**（両ケースの下端がサンプル上に乗っている） |
| M7 | `CsvExporter.export` 冒頭に `signals = list(reversed(signals))` | **g01-g09/g11 の 10 本**（g10 は 1 列なので GREEN — これがゴールデンの粒度の限界であり、`test_signals_reversed_without_headers_changes_the_bytes` が別軸で補っている） |
| M8 | `_rows_unified_timeline` の欠測分岐 `else ""` → `else "0.0"` | **g03 / g04 / g07 / g09 / g11**（統合 5 本すべて。共有 6 本は欠測が無いので GREEN） |
| M9 | `build_options` を使わず `header_names=None` 固定（GUI 形の導出を殺す = MG-7 の退行） | **g01 と g03-g11 の 10 本**（g02 は元から passthrough なので GREEN — passthrough ゴールデンが「導出形と別物である」ことの証拠） |
| M10 | `_fmt` の `repr(float(value))` → `str(round(float(value), 6))`（spec C-4 が禁じた書式変更） | ゴールデン 11/11（`cell_frac` の 17 桁 repr が全滅） |

**入力側の変異はすでに恒久テスト化してある**（src を触らずに済む）:「列順反転」→ `test_reversed_column_order_changes_the_bytes` / 「ヘッダ入れ替え」→ `test_signals_reversed_without_headers_changes_the_bytes` / 「delimiter 変更」→ `test_changing_the_delimiter_changes_the_bytes` / 「precision 変更」→ `test_changing_the_precision_changes_the_bytes` / 「範囲境界 ±1 サンプル」→ `test_range_boundary_off_by_one_sample_changes_the_bytes` / 「1 列のみ」→ `test_dropping_columns_changes_the_bytes` / 「空選択」→ `test_empty_selection_fails_loudly_and_writes_no_file`。**これらは一度きりの sabotage ではなく常設のオラクル**であり、Task 4-7 の再構築でも同じ感度を要求し続ける。

各変異で:

```
uv run pytest tests/test_golden_csv.py -q
```
を走らせ、**RED になったケース ID の集合**を記録する。予測と実測がずれたら**予測を書き換えず**発見として報告する（特に「予測 RED なのに GREEN」= ゴールデンがその軸に盲目、という発見は必ず残す）。

最後に残骸ゼロを確認:

```
git status --short
```
→ 出力が空であること（未追跡のゴールデン 11 本は Step 7 で add するので、この時点では `??` が出る。`src/` に `M` が 1 つも無いことを見る）。

---

- [ ] **Step 7: 被覆の justification を書き残す**

`tests/golden_csv_cases.py` の `GOLDEN_CASES` 定義の**直前**に、被覆表をコメントとして置く（`why` フィールドはケース単体の理由で、**軸 × ケース**の全体像は別に要る）:

```python
# ─── 被覆 (spec §7.1 の軸 x ケース。全組み合わせではなく被覆集合) ─────────────
#
# 全直積は 2(TL) x 2(範囲) x 13(その他の軸) = 実用的でない。各軸を最低 1 本、
# 相互作用が疑われる組 (範囲 x TL 種別・非有限 x precision・クォート x 単位行)
# だけを重ねて 11 本に畳んである。
#
# | 軸                                   | 被覆ケース                        |
# |--------------------------------------|-----------------------------------|
# | 単一 (shared) タイムライン            | g01 g02 g05 g06(注) g08 g10       |
# | 統合 (unified) タイムライン           | g03 g04 g06 g07 g09 g11           |
# | 範囲なし                              | g01 g02 g03 g05 g06 g07 g08 g09 g11 |
# | 範囲あり (閉区間・両端がサンプル上)    | g04 (統合) / g10 (単一)            |
# | 欠測 (union の穴)                     | g03 g04 g07 g09 g11               |
# | NaN                                   | g03 g06                           |
# | ±inf                                  | g03                               |
# | 要クォート名 (区切り/引用符/改行)      | g05                               |
# | 日本語ヘッダ                          | g05                               |
# | 重複名 dedup (W[0] 形)                | g08                               |
# | enum                                  | g08                               |
# | unit=None / キー欠落                  | g05                               |
# | 単位行                                | g05 g06 g08 g11                   |
# | len 0 信号                            | g09                               |
# | 非単調/重複 ts (last-wins)            | g09                               |
# | ULP 分裂 (行数まで凍結)               | g07                               |
# | ヘッダ passthrough (raw namespaced)   | g02                               |
# | ヘッダ GUI 形・衝突なし (bare)         | g01 g03 g04 g05 g06 g07 g08 g09 g10 |
# | ヘッダ GUI 形・衝突あり (bare(group))  | g11                               |
# | ヘッダ GUI 形・"timestamp" 母集合注入  | g11                               |
# | 非既定 delimiter/decimal/precision     | g06                               |
# | 1 列のみ                              | g10                               |
# | 実ローダー経路 (遅延値・LazyMdfValues) | g08 g11                           |
#
# (注) g06 は統合。単一 x 非既定オプションは g05 (単位行つき) が担う。
#
# **軸を持たない意図的な穴**:
# - 空選択: 現行は例外 (共有=IndexError / 統合=ValueError) なのでゴールデンに
#   できない。test_empty_selection_fails_loudly_and_writes_no_file が凍結する。
# - 複数ブロック (境界跨ぎ): T-G に block_cols が存在しない。
#   test_block_cols_handoff_is_not_forgotten が Task 7 へ強制する (spec G1)。
# - prod 規模 (330,004 列): ゴールデンの目的はバイト表現の凍結であって規模の
#   検証ではない。規模は G3/G4 (Task 11 の T-M) が担う。
```

---

- [ ] **Step 8: 品質ゲートを通してコミットする**

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```
→ すべて exit 0。pytest は Task 1 完了時点（`N + 20`）に対して **`N + 45 passed`**（本タスクの新規 25 本）。

`ruff format` が `tests/golden_csv_cases.py` / `tests/test_golden_csv.py` / `scripts/generate_golden_csv.py` を整形した場合、**ゴールデンのバイトは変わらない**（整形はコードの見た目だけ）ことを再確認する:

```
uv run pytest tests/test_golden_csv.py -q
```
→ 25 passed（整形後も一致）。

コミット（**ゴールデン 11 本のバイトを含める**）:

```
git add -A
git commit -F - <<'EOF'
test(export): CSV 出力の byte-identical ゴールデン 11 本を凍結 (E-4b T-G)

是正 4 点 (非有限空セル・BOM・最小クォート・unit=None) 後の出力バイトを
tests/golden_csv/ へ凍結。単一/統合タイムライン x 範囲有無 x 欠測/NaN/±inf/
要クォート名/日本語/重複名 dedup/enum/unit=None/len 0/非単調 ts/ULP 分裂を
11 本で被覆し、セル値は f(列, 行) の単射にして行シフトに盲目にならないように
した。主系は GUI と同じ csv_header_names 導出形で駆動し (MG-7)、passthrough
形も 1 本置いて Session.export_csv 直呼びの既定バイトを縛る。

生成器は既存ファイルがあると何も書かず exit 1 (--force は用意しない)。
再生成での黙殺を構造的に禁じ、変更は git rm + 決定履歴記録の手動 supersede
のみとする (spec G1)。列順反転・ヘッダ対応崩し・区切り/精度変更・範囲境界
±1・1 列のみ・空選択は常設の感度オラクルとして残した。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
```

---

- [ ] **Step 9: 報告**

報告に含める:
- ゴールデン 11 本のファイル名・バイト数・行数（生成器の出力そのまま）
- `g07` の実測データ行数（`ULP_EXPECTED_ROWS` = 56 と一致したか）
- Step 3 の目視で「期待する主要バイト」表と食い違った箇所があればその全数
- Step 5 の `PYTHONHASHSEED` 2 値での結果
- Step 6 の変異 M1-M10 について **予測 RED 集合 vs 実測 RED 集合**（ケース ID 単位）。特に予測 GREEN が実測 RED（またはその逆）だった変異
- **spec の M1/M2/M3/M4/M6/M8 の定義が復元不能だったため T-G が M1-M10 を定義し直した**こと（spec §9-7 の該当項目を「T-G の変異表で置換した」と記録する必要がある）
- Task 7 への申し送り: `test_block_cols_handoff_is_not_forgotten` が signature 変更を検知して強制する仕組みになっていること
### Task 3: `_selected` の圧縮（ColumnSelection・順序・オフセットガード）

**Files:**
- Modify: `src/valisync/gui/views/export_csv_dialog.py`（`_ChannelRow`・`_selected`/`_selected_per_row`/`_offset_keys`・`_add_selection`/`_drop_selection`/`_toggle_row`/`_select_all`/`_select_none`/`_refresh_row_state`/`_materialize`/`_sync_row_children`/`_checked_keys`/`_offset_active_for_checked`/`__init__` の DI）
- Modify: `src/valisync/gui/views/main_window.py`（`export_csv` に `offset_keys=` を追加注入・**1 行**）
- Test (add): `tests/gui/test_export_selection_order.py`（**新規** — 順序の強化テスト。既存 `test_export_csv_dialog.py` は 1 行も編集しない）
- Test (add): `tests/gui/test_export_selection_footprint.py`（**新規** — 圧縮の構造テスト＋実測比）
- Test (add): `tests/gui/test_export_offset_guard_reversal.py`（**新規** — 反転したオフセットガードの fast path＋legacy 同値）
- Test (mechanical follow): `tests/realgui/test_export_flow.py:179/187/188/190/198/199/201/224/225`（`dlg._selected` の内部状態読み → `dlg.selected_count()`。supersede コメント必須）

**Interfaces:**

- **Consumes**
  - Task 1/2 の成果物には**依存しない**（本タスクは GUI ダイアログ内部の表現だけを変える。出力バイトには一切触れない）。Task 2 のゴールデンが**緑のまま**であることが本タスクの無回帰条件。
  - 既存 API（変更しない）: `Session.column_names_of(group_key, display_name) -> tuple[str, ...]`／`Session.has_column`／`Session.group_signals`／`Session.source_name`／`AppViewModel.loaded_file_keys`／`AppViewModel.signal_offsets: dict[str, float]`／`AppViewModel.file_offsets: dict[str, float]`／`GraphPanelVM.offset_for(signal_key) -> float`。
  - `KEY_SEPARATOR`（`valisync.core.loaders.signal_group_manager`・値は `"::"`）。
- **Produces**（Task 4 以降がこれに対して書かれる・シグネチャ厳守）
  ```python
  # src/valisync/gui/views/export_csv_dialog.py
  @dataclass(frozen=True, slots=True)
  class ColumnSelection:
      is_all: bool
      indices: frozenset[int] = frozenset()
      def contains(self, col_index: int) -> bool: ...
      def count(self, total: int) -> int: ...

  _ALL: ColumnSelection            # モジュール唯一の ALL インスタンス（全行で共有）

  class ExportCsvDialog(QDialog):
      _selected: dict[str, ColumnSelection]   # キー = 名前空間つき **物理チャンネル** キー
      def selected_count(self) -> int: ...    # 総選択 **列** 数（O(1)・realgui/テストの introspection 口）
      def _checked_keys(self) -> list[str]: ...  # 出力列順 = ツリー表示順（Task 4 が tuple 化して keys へ）
      def __init__(self, app_vm, initial_selected, parent=None, *,
                   x_range=None, cursor_a=None, cursor_b=None,
                   offset_for: Callable[[str], float] | None = None,
                   offset_keys: Callable[[], Iterable[str]] | None = None) -> None: ...
  ```
  - **`selected_count()` は「列本数」**（`len(_selected)` は圧縮後は**行数**になる — 単位が変わるので直接読ませない）。
  - `_checked_keys()` の**順序契約は不変**: ファイル順 → ローダー順 → 列順（= ツリー表示順）。**チェック順ではない**。Task 4 の `ExportRequest.keys` はこの列を tuple 化したもので、spec §10 の「出力列順」契約そのもの。
  - `offset_keys` の意味: **今 0 でないオフセットを持つキーの列挙**（名前空間つき信号キー ＋ ファイルオフセットのグループキーが混在してよい）。`None` = 未注入 = legacy 経路（後述）。

---

- [ ] **Step 1: ベースラインを記録し、順序テストを *先に* 強化する（追加のみ）**

まずベースラインを控える（Step 8 の「挙動不変」を主張でなく実測で示すため）:

```
uv run pytest -q
```
→ 出た「N passed, M skipped」を控える。

**なぜ先に強化するのか**: 現行の出力列順は `_checked_keys()` の `(row, col)` sort（`export_csv_dialog.py:570`）だけが担っている。ところが既存テストで**順序**を全等号で見ているのは `test_checked_keys_follow_tree_order_not_hash_order`（`:886-901`）**1 本だけ**で、しかも**単一ファイル**（`mf4_1` のみ）。ファイル跨ぎの順序は `:136` / `:205` / `:571` の `set(...) ==` 比較しか無く、**「チェック順 ≠ ツリー順」を突く経路は 1 本も無い**。この状態で `(row, col)` 運搬を捨てると、順序がチェック順（= dict 挿入順）に退化しても**全部緑のまま**通る（spec §5.6 [I4]）。

**既存テストの期待は 1 行も編集しない**（Global Constraints）。強化は**新規ファイルへの追加**だけで行う。

`tests/gui/test_export_selection_order.py` を新規作成:

```python
"""出力列順の全等号 pin（E-4b Task 3・spec §5.6 [I4] / §10）。

既存 `test_export_csv_dialog.py` の順序被覆は
`test_checked_keys_follow_tree_order_not_hash_order`（単一ファイル）1 本だけで、
ファイル跨ぎの順序は `set(...) ==` 比較しか無い。`_selected` を
`dict[key, (row, col)]` から `dict[phys_key, ColumnSelection]` へ圧縮すると
**順序の運搬者そのもの**（`(row, col)` sort）が消えるので、退化形
（チェック順 = dict 挿入順で出す実装）を捕まえる網をここで先に張る。

このファイルは Task 3 の**実装前に緑**でなければならない（現行実装の挙動を
pin する）。緑にならないなら、それは現行実装が既に順序を守っていないという
発見なので、実装を進める前に報告する。
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Signal
from valisync.gui.views.export_csv_dialog import ExportCsvDialog


class _Session:
    """3 ファイル / 混在幅（1 列・3 列・2 列）の最小 Session。

    `test_export_csv_dialog._FakeSession` を import しない — あちらは
    「既存テストの契約」であり、こちらが弄れば向こうが動く二重の真実になる。
    列構造の契約（未登録 = `(display_name,)`）だけを写す。
    """

    def __init__(self) -> None:
        self._groups: dict[str, list[Signal]] = {
            "csv_1": [_sig("csv_1::alpha", "alpha")],
            "mf4_1": [_sig("mf4_1::Mat", "Mat"), _sig("mf4_1::zeta", "zeta")],
            "csv_2": [_sig("csv_2::beta", "beta")],
        }
        self._columns: dict[tuple[str, str], tuple[str, ...]] = {
            ("mf4_1", "Mat"): ("Mat[0]", "Mat[1]", "Mat[2]"),
        }

    def source_name(self, key: str) -> str:
        return f"{key}.file"

    def group_signals(self, key: str) -> list[Signal]:
        return self._groups[key]

    def column_names_of(self, key: str, display_name: str) -> tuple[str, ...]:
        return self._columns.get((key, display_name), (display_name,))

    def has_column(self, key: str, display_name: str) -> bool:
        return self.column_names_of(key, display_name) == (display_name,)

    def resolve_signal(self, key: str) -> Signal | None:
        return _sig(key, key.split("::", 1)[1])


class _AppVM:
    def __init__(self) -> None:
        self.session = _Session()
        # ツリーのファイル順はこのリスト順 — アルファベット順とは**わざと違える**
        # （sorted() 実装が偶然緑になるのを防ぐ）。
        self.loaded_file_keys = ["csv_1", "mf4_1", "csv_2"]


def _sig(name: str, phys: str) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="CSV",
        bus_type="",
        source_file="",
        metadata={"physical_channel": phys},
    )


#: ツリー表示順の全列（ファイル順 -> ローダー順 -> 列順）。
_TREE_ORDER = [
    "csv_1::alpha",
    "mf4_1::Mat[0]",
    "mf4_1::Mat[1]",
    "mf4_1::Mat[2]",
    "mf4_1::zeta",
    "csv_2::beta",
]


def _leaves(dlg: ExportCsvDialog) -> dict[str, object]:
    """列キー -> チェック可能な葉アイテム（全コンテナを展開してから引く）。"""
    for row in dlg._iter_rows():
        dlg._tree.expandItem(row)
    return {
        c.data(0, Qt.ItemDataRole.UserRole): c
        for c in dlg._iter_children()
        if c.data(0, Qt.ItemDataRole.UserRole) is not None
    }


def test_select_all_orders_columns_across_files_by_tree_position(
    qtbot: QtBot,
) -> None:
    """ファイル跨ぎの全等号 pin（既存は set 比較しか無い）。

    ファイルキーの辞書順は csv_1 < csv_2 < mf4_1、列名の辞書順は
    alpha < beta < Mat[0]... なので、`sorted()` 退化・ハッシュ順退化・
    ファイル順無視のいずれも**この 1 本の等号**で落ちる。
    """
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set())
    qtbot.addWidget(dlg)

    dlg._select_all()

    assert dlg._checked_keys() == _TREE_ORDER


def test_check_order_does_not_leak_into_output_order(qtbot: QtBot) -> None:
    """**チェック順 ≠ ツリー順**（spec §5.6 [I4] の必須ケース）。

    ツリーの逆順にチェックしていく。順序を dict 挿入順（= チェック順）で
    運ぶ実装はここで `_TREE_ORDER[::-1]` を返して RED になる。
    `(row, col)` sort も ColumnSelection + ツリー walk も、どちらも緑。
    """
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set())
    qtbot.addWidget(dlg)
    leaves = _leaves(dlg)

    for key in reversed(_TREE_ORDER):
        leaves[key].setCheckState(0, Qt.CheckState.Checked)

    assert dlg._checked_keys() == _TREE_ORDER


def test_partial_selection_keeps_tree_order_within_and_across_rows(
    qtbot: QtBot,
) -> None:
    """部分選択でも順序はツリー順（行内の列順まで）。

    列 index を降順にチェックしても `Mat[0], Mat[2]` の順で出る = 行内の順序が
    `frozenset` の反復順（= 小さい int から、ただし CPython 実装依存）でなく
    **明示 sort / ツリー walk** から来ていることの pin。
    """
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set())
    qtbot.addWidget(dlg)
    leaves = _leaves(dlg)

    for key in ("csv_2::beta", "mf4_1::Mat[2]", "mf4_1::Mat[0]"):
        leaves[key].setCheckState(0, Qt.CheckState.Checked)

    assert dlg._checked_keys() == ["mf4_1::Mat[0]", "mf4_1::Mat[2]", "csv_2::beta"]


def test_deselect_then_reselect_does_not_move_a_column_to_the_end(
    qtbot: QtBot,
) -> None:
    """外して入れ直しても位置は動かない（挿入順運搬の最も出やすい症状）。"""
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set())
    qtbot.addWidget(dlg)
    dlg._select_all()
    leaves = _leaves(dlg)

    leaves["csv_1::alpha"].setCheckState(0, Qt.CheckState.Unchecked)
    leaves["csv_1::alpha"].setCheckState(0, Qt.CheckState.Checked)

    assert dlg._checked_keys() == _TREE_ORDER


@pytest.mark.parametrize("bulk", ["file_row", "select_all"])
def test_bulk_paths_produce_the_same_order_as_individual_checks(
    qtbot: QtBot, bulk: str
) -> None:
    """一括経路（ファイル行 / すべて選択）と個別チェックが**同じ列**を出す。

    圧縮後は一括経路が O(1) の ALL に化けるので、個別経路とのズレ（例: ALL が
    行の列数を取り違えて 1 列落とす）はここでしか出ない。
    """
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set())
    qtbot.addWidget(dlg)

    if bulk == "select_all":
        dlg._select_all()
    else:
        for i in range(dlg._tree.topLevelItemCount()):
            dlg._tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked)

    assert dlg._checked_keys() == _TREE_ORDER
```

**このファイルは現行実装（未改造）に対して緑になること**を先に確認する:

```
uv run pytest tests/gui/test_export_selection_order.py -q
```
Expected: **6 passed**（parametrize 込み）。

- [ ] **Step 2: 強化テストの honest-RED を *現行実装に対して* 実証する**

Step 1 のテストは「現行の挙動を pin する」ので緑で当たり前 — **空虚でないこと**をここで証明する。pristine copy を取ってから壊す（`git checkout -- src/...` で戻さない）:

```
cp src/valisync/gui/views/export_csv_dialog.py "$SCRATCH/export_csv_dialog.py.orig"
```
（`$SCRATCH` = `C:/Users/trtrm/AppData/Local/Temp/claude/D--Programming-projects-valisync/<session>/scratchpad`）

| # | 壊す箇所（正確な編集） | 予測 RED |
|---|---|---|
| P1 | `_checked_keys` の `return sorted(self._selected, key=lambda k: self._selected[k])` を `return list(self._selected)`（挿入順 = チェック順）へ | 新規 `test_check_order_does_not_leak_into_output_order` / `test_deselect_then_reselect_does_not_move_a_column_to_the_end` / `test_partial_selection_keeps_tree_order_within_and_across_rows`（beta → Mat[2] → Mat[0] の順にチェックするので挿入順では逆順で出る）の **計 3 件**。`test_select_all_orders_columns_across_files_by_tree_position` は `_select_all` が既にツリー順で挿入するので**緑のまま** — この非対称まで含めて実測と一致させる |
| P2 | 同じ行を `return sorted(self._selected)`（キーの辞書順）へ | 新規 4 件（`test_select_all_...` / `test_check_order_...` / `test_partial_selection_...` / `test_deselect_...`）＋ `bulk` parametrize 2 件 ＋ **既存** `test_checked_keys_follow_tree_order_not_hash_order` |

各 sabotage 後は `cp "$SCRATCH/export_csv_dialog.py.orig" src/valisync/gui/views/export_csv_dialog.py` で復元し、
`uv run pytest tests/gui/test_export_selection_order.py -q` が 6 passed に戻ることを確認してから次へ進む。

予測と実測の failed 一覧が一致しなければ**そのまま進めず**原因を特定して報告に書く（P1 の「1 本は緑のまま」は到達範囲の主張の検定そのもの）。

- [ ] **Step 3: `ColumnSelection` を実装して `_selected` を圧縮する**

`src/valisync/gui/views/export_csv_dialog.py` を編集。

**(a) `_ChannelRow` に選択キーを持たせる**（`f"{file_key}::{phys}"` を毎回組まないため。この文字列は `_selected` の dict キーと**同一オブジェクト**なので、行あたりの追加常駐は参照 1 個ぶんだけ）:

```python
@dataclass(slots=True)
class _ChannelRow:
    file_key: str
    phys: str
    count: int
    single_key: str | None
    #: `_selected` / `_row_by_sel_key` の共有キー（名前空間つき物理チャンネルキー）。
    #: 行ごとに 1 本だけ作り、以降は組み直さない（打鍵ごと・行ごとの f-string を
    #: 作らないための唯一の措置 — prod は 4,324 行）。
    sel_key: str = ""
    matched: str | None = None
    hit: bool = False
```

`_build_tree` の生成箇所（現 `:331`）を差し替える:

```python
                sel_key = prefix + phys
                self._rows.append(
                    _ChannelRow(file_key, phys, len(names), single, sel_key)
                )
                self._row_by_sel_key[sel_key] = row_index
```

**(b) `ColumnSelection` をモジュールに追加**（`_ChannelRow` の直前）:

```python
@dataclass(frozen=True, slots=True)
class ColumnSelection:
    """1 物理チャンネル行の選択状態（E-4b spec §5.6）。

    三態は **ALL / PARTIAL / NONE**。NONE は「``_selected`` にエントリが無い」で
    表し、空の PARTIAL は決して作らない — さもないと「なし」が行数ぶんの
    エントリを持ち、圧縮の目的（すべて選択 = 行数ぶんの ~0.5 MB）が消える。

    ALL に列 index を持たせないのが核心: prod は 4,324 行 / 330,004 列で、
    「すべて選択」を列ごとに持つと実測 54-57 MB（spec §1）。ALL は
    :data:`_ALL` 1 個を全行で共有するので、行あたりのコストは dict のスロットと
    キー文字列の参照だけになる。

    **順序は持たない** — 出力列順はツリー walk（``_checked_keys``）が導出する
    契約で、選択の表現に順序を持たせない（spec §10・順序はチェック順ではない）。
    """

    is_all: bool
    indices: frozenset[int] = frozenset()

    def contains(self, col_index: int) -> bool:
        return self.is_all or col_index in self.indices

    def count(self, total: int) -> int:
        """この行の選択列数（*total* = 行の全列数）。"""
        return total if self.is_all else len(self.indices)


#: ALL の唯一のインスタンス。frozen + slots なので全行で共有して安全。
_ALL = ColumnSelection(is_all=True)
```

**(c) `__init__` の状態を差し替える**（現 `:154-163`）:

```python
        # 選択の真実は **ダイアログ側**（U1）。未展開の列は QTreeWidgetItem を
        # 持たないので「木を数えて選択集合を作る」実装は原理的に成立しない。
        # 表現は **物理チャンネル 1 行 = 1 エントリ**（E-4b spec §5.6）— 列ごとに
        # (行, 列) を持つ旧形は prod で 54-57 MB だった。出力列順は
        # `_checked_keys()` のツリー walk が導出する（この表は順序を持たない）。
        self._selected: dict[str, ColumnSelection] = {}
        # 総選択列数（O(1)）。`len(self._selected)` は **行数** であって列数では
        # ないので、フッター/`_validate` はこちらを見る。
        self._total = 0
        # ファイルごとの選択列数。ファイルオフセット（グループキー）が選択集合に
        # 触れているかを O(1) で答えるためだけの覚え書き（`_set_row` が唯一の
        # 更新者）。走査で答えると、ファイル行 1 クリック（行ごとに `_validate()`
        # を通る）が prod で 行数 x 行数 回の走査になる。
        self._total_per_file: dict[str, int] = {}
        # 選択キー -> 行番号。列キーから所属行を最長一致で引く唯一の索引
        # （`_row_of_key`）。行数ぶん（prod 4,324）しか無い。
        self._row_by_sel_key: dict[str, int] = {}
        self._offset_for = offset_for
        self._offset_keys = offset_keys
        # legacy 経路: `offset_keys` を注入しない呼び出し側（F-0 の DI 形のまま
        # 構築する撮影ツール・既存テスト）向けに、旧来の「キーが入る瞬間に 1 度
        # 問い合わせて覚える」方式を残す。prod（main_window）は `offset_keys` を
        # 注入するので O(1) 経路を通る。両者の同値は
        # tests/gui/test_export_offset_guard_reversal.py が固定する。
        self._legacy_offset = offset_keys is None and offset_for is not None
        self._legacy_offset_hits: set[str] = set()
        self._rows: list[_ChannelRow] = []
```

（`self._selected_per_row` と `self._offset_keys: set[str]` は**削除**。`_offset_keys` という名前は DI の callable に付け替わるので、旧 set の残骸が残っていると型が黙って壊れる — grep で 0 件になるまで潰すこと。）

**(d) 単一の書き口 `_set_row` と派生アクセサ**（`_add_selection` の直前に置く）:

```python
    def _row_count(self, row_index: int) -> int:
        """この行の選択列数（0 = 未選択）。"""
        row = self._rows[row_index]
        sel = self._selected.get(row.sel_key)
        return 0 if sel is None else sel.count(row.count)

    def _set_row(self, row_index: int, sel: ColumnSelection | None) -> None:
        """行の選択状態を差し替える（``_selected`` への **唯一** の書き口）。

        総数カウンタ（`_total` / `_total_per_file`）をここでしか動かさないので、
        「経路を 1 つ足したらカウンタだけ更新し忘れる」形の破綻が構造的に起きない。
        *sel* が None、または空の PARTIAL ならエントリを消す（NONE = 不在）。
        """
        row = self._rows[row_index]
        before = self._row_count(row_index)
        if sel is None or (not sel.is_all and not sel.indices):
            self._selected.pop(row.sel_key, None)
            after = 0
        else:
            self._selected[row.sel_key] = sel
            after = sel.count(row.count)
        delta = after - before
        if delta:
            self._total += delta
            self._total_per_file[row.file_key] = (
                self._total_per_file.get(row.file_key, 0) + delta
            )

    def selected_count(self) -> int:
        """総選択 **列** 数（O(1)）。

        `len(self._selected)` は圧縮後 **行数** を返すので、テスト/realgui は
        必ずこちらを読む（E-4b spec §5.6 の単位変更点）。
        """
        return self._total
```

**(e) 追加/削除を ColumnSelection 上で行う**（現 `:458-471` を置換）:

```python
    def _add_selection(self, row_index: int, col_index: int, key: str) -> None:
        row = self._rows[row_index]
        sel = self._selected.get(row.sel_key)
        if sel is not None and sel.contains(col_index):
            return
        if sel is None:
            merged = frozenset({col_index})
        else:
            merged = sel.indices | {col_index}
        # 全列そろったら ALL へ畳む — 畳まないと「列を 1 本ずつ全部チェック」が
        # 旧形と同じ列数ぶんの int を抱える（圧縮が効くのは一括経路だけになる）。
        self._set_row(
            row_index,
            _ALL if len(merged) >= row.count else ColumnSelection(False, merged),
        )
        self._note_legacy_offset(key)

    def _drop_selection(self, row_index: int, col_index: int, key: str) -> None:
        row = self._rows[row_index]
        sel = self._selected.get(row.sel_key)
        if sel is None or not sel.contains(col_index):
            return
        base = frozenset(range(row.count)) if sel.is_all else sel.indices
        self._set_row(row_index, ColumnSelection(False, base - {col_index}))
        self._legacy_offset_hits.discard(key)

    def _select_row_all(self, row_index: int) -> None:
        """行を丸ごと選択する（**O(1)** — 列名を 1 本も作らない）。"""
        self._set_row(row_index, _ALL)
        if self._legacy_offset:
            # legacy 経路だけが列名を要する（旧挙動の完全保存）。prod は
            # `offset_keys` 注入側なのでここには入らない。
            for key in self._column_keys(row_index):
                self._note_legacy_offset(key)

    def _clear_row(self, row_index: int) -> None:
        was_selected = self._row_count(row_index) > 0
        self._set_row(row_index, None)
        if self._legacy_offset and was_selected:
            for key in self._column_keys(row_index):
                self._legacy_offset_hits.discard(key)

    def _note_legacy_offset(self, key: str) -> None:
        if self._legacy_offset and self._offset_for is not None:
            if self._offset_for(key) != 0.0:
                self._legacy_offset_hits.add(key)
```

**(f) 呼び出し側を追随させる**:

| 現行 | 置換後 |
|---|---|
| `:338` `if single is None and self._selected_per_row.get(row_index):` | `if single is None and self._row_count(row_index):` |
| `:405` `if key in self._selected` | `if sel is not None and sel.contains(col_index)`（`_materialize` の先頭で `sel = self._selected.get(row.sel_key)` を 1 度だけ引く） |
| `:484` `n = self._selected_per_row.get(row_index, 0)` | `n = self._row_count(row_index)` |
| `:504` `if key in self._selected` | `child.data(0, _COL_ROLE)` を使い `sel is not None and sel.contains(col_index)` |
| `:535-539` `_toggle_row` の 2 分岐ループ | `self._select_row_all(row_index)` / `self._clear_row(row_index)` |
| `:557` `self._drop_selection(key)` | `self._drop_selection(item.data(0, _ROW_ROLE), item.data(0, _COL_ROLE), key)` |
| `:579-581` `_select_all` の二重ループ | `for row_index in range(len(self._rows)): self._select_row_all(row_index)` |
| `:586-588` `_select_none` | `self._selected.clear()` ＋ `self._total = 0` ＋ `self._total_per_file.clear()` ＋ `self._legacy_offset_hits.clear()` |
| `:741` `n = len(self._selected)` | `n = self._total` |

**(g) `_checked_keys()` をツリー walk へ**（現 `:564-570` を置換）:

```python
    def _checked_keys(self) -> list[str]:
        """出力集合（フィルタ非依存・**ツリー表示順**）。

        `self._rows` はファイル順 -> ローダー順に積まれているので、その添字順に
        走査するだけでツリー表示順になる。行内は列 index の昇順（ALL は
        `_column_keys` の並びそのまま・PARTIAL は明示 sort）。

        **チェック順ではない**（spec §10）。旧形は `_selected` の値 `(row, col)`
        を sort して同じ順を作っていたが、その運搬者は E-4b で消えた — 順序は
        「選択の表現」ではなく「木」から導出する、が本増分の設計判断
        （spec §5.6 [I4]）。列キーの生成はここが唯一の一括点で、prod では
        330,004 本 ≈ 25.1 MB の一過性 tuple になる（spec §1 の帳簿）。
        """
        out: list[str] = []
        for row_index, row in enumerate(self._rows):
            sel = self._selected.get(row.sel_key)
            if sel is None:
                continue
            keys = self._column_keys(row_index)
            if sel.is_all:
                out.extend(keys)
            else:
                out.extend(keys[i] for i in sorted(sel.indices))
        return out
```

この時点で:

```
uv run pytest tests/gui/test_export_csv_dialog.py tests/gui/test_export_selection_order.py -q
```
Expected: **既存 + 新規すべて passed**（既存の 1 本も編集していないこと＝ `git diff --stat tests/gui/test_export_csv_dialog.py` が **0 行**であること）。

- [ ] **Step 4: オフセットガードを方向反転する**

現行は `_add_selection` の per-key probe（`:463-464`）で「選択列にオフセットあり → 表示由来ラジオ disabled」（F-0 出荷済み契約）を実現している。O(1) トグル化でこの probe 点が消えるので、**オフセット辞書側（少数）を走査して選択集合と交差判定**へ反転する（spec §5.6 [I5]）。

`_offset_active_for_checked`（現 `:692-708`）を置換し、索引ヘルパを足す:

```python
    def _row_of_key(self, key: str) -> int | None:
        """列キーの所属行を **最長一致** で引く（列名を 1 本も生成しない）。

        物理チャンネル表示名は列キーの接頭辞（``Mat`` -> ``Mat[0]`` /
        ``Pos`` -> ``Pos.x``）。`SignalGroupManager._mint_column` と同じ最長一致
        規則で、走査は行索引（prod 4,324 エントリ）への dict 参照だけ。
        ファイル接頭辞より短い所では打ち切る — 別ファイルの選択キーへ字面で
        滑り込むのを構造的に断つ。
        """
        group_key, sep, _bare = key.partition(KEY_SEPARATOR)
        if not sep:
            return None
        floor = len(group_key) + len(KEY_SEPARATOR)
        for i in range(len(key), floor, -1):
            row_index = self._row_by_sel_key.get(key[:i])
            if row_index is not None:
                return row_index
        return None

    def _selection_touches(self, key: str) -> bool:
        """*key*（列キー **または** グループキー）が現在の選択集合に触れているか。"""
        group_key, sep, _bare = key.partition(KEY_SEPARATOR)
        if not sep:
            # ファイルオフセットのキー = グループキー。そのファイルの列が 1 本でも
            # 選ばれていれば触れている（O(1)）。
            return self._total_per_file.get(key, 0) > 0
        row_index = self._row_of_key(key)
        if row_index is None:
            return False
        sel = self._selected.get(self._rows[row_index].sel_key)
        if sel is None:
            return False
        if sel.is_all:
            return True  # 列名を 1 本も作らずに決着（「すべて選択」の支配的経路）
        names = self._column_names(row_index)  # PARTIAL のときだけ 1 行ぶん生成
        bare = key[len(group_key) + len(KEY_SEPARATOR) :]
        try:
            col_index = names.index(bare)
        except ValueError:
            return False
        return col_index in sel.indices

    def _offset_active_for_checked(self) -> bool:
        """True iff *現在チェック中* の信号のどれかが 0 でないオフセットを持つ。

        **方向が反転している**（E-4b spec §5.6 [I5]）: 旧実装は「選択へ入る瞬間に
        キーごとに `offset_for` を問い合わせて覚える」だったが、`_select_all` /
        ファイル行チェックが O(1) になった今、キーが個別に通る瞬間はもう無い。
        代わりに **オフセット辞書側（少数 — 実運用で高々数十）** を走査し、
        選択集合と交差するかを見る。リアクティブ性（選択集合の変化に追随）は
        `_validate()` 経由の毎回評価で保たれる。

        `offset_keys` 未注入（F-0 の DI 形のまま構築する呼び出し側）は legacy 経路。
        `offset_for is None` は「オフセットは存在しない」（後方互換の既定）。

        既知の非対称（安全側）: ファイルオフセット（グループキー）は、そのファイル
        内に「ファイル +1 / 信号 -1」で相殺された信号があっても触れていると答える
        （= 過保護に disabled）。旧実装はキーごとに合成値を見ていたのでここだけ
        厳密だった。エクスポート可否ではなく **範囲ラジオの enabled** の話なので、
        過保護側へ倒すことを設計判断として受容する。
        """
        if self._offset_keys is None:
            return bool(self._legacy_offset_hits)
        for key in self._offset_keys():
            if self._offset_for is not None and self._offset_for(key) == 0.0:
                continue  # 合成して 0（相殺）はオフセット無しと同じ
            if self._selection_touches(key):
                return True
        return False
```

`__init__` の署名へ `offset_keys` を追加（`ask` にも同じキーワードを通す・両方とも**末尾**に足して既定 None = 完全後方互換）:

```python
        offset_for: Callable[[str], float] | None = None,
        offset_keys: Callable[[], Iterable[str]] | None = None,
```

`Iterable` を `from collections.abc import Callable, Iterable, Iterator` へ追加する。

`main_window.export_csv`（`:958-966`）に **1 行**足す:

```python
            offset_for=panel.offset_for,
            # E-4b spec §5.6 [I5]: ガードは「オフセット辞書側 -> 選択集合」へ
            # 反転した。列ごとの probe は `_select_all` の O(1) 化で消えるので、
            # 少数側（今 0 でないオフセットを持つキー）を列挙する口を渡す。
            # signal 側は名前空間つき列キー・file 側はグループキーで、
            # ダイアログはどちらの形も解釈する。
            offset_keys=lambda: (*self.app_vm.signal_offsets, *self.app_vm.file_offsets),
```

`tests/gui/test_export_offset_guard_reversal.py` を新規作成:

```python
"""反転したオフセットガード（E-4b Task 3・spec §5.6 [I5]）。

既存 `test_export_csv_dialog.py` の I2 系 6 本は **legacy 経路**（`offset_for`
のみ注入）を固定している。本ファイルは prod 経路（`offset_keys` 注入）を固定し、
さらに「同じシナリオで両経路が同じ答えを出す」ことを直接突き合わせる —
二経路になった時点で、片方だけ壊れて緑、が最も出やすい壊れ方になる。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from tests.gui.test_export_selection_order import _AppVM
from valisync.gui.views.export_csv_dialog import ExportCsvDialog


def _dlg(qtbot: QtBot, offsets: dict[str, float], *, fast: bool) -> ExportCsvDialog:
    kwargs: dict[str, object] = {
        "x_range": (2.0, 9.0),
        "cursor_a": 3.0,
        "cursor_b": 6.0,
        "offset_for": lambda k: offsets.get(k, 0.0),
    }
    if fast:
        kwargs["offset_keys"] = lambda: list(offsets)
    dlg = ExportCsvDialog(_AppVM(), initial_selected=set(), **kwargs)  # type: ignore[arg-type]
    qtbot.addWidget(dlg)
    return dlg


@pytest.mark.parametrize("fast", [True, False], ids=["fast", "legacy"])
def test_select_all_trips_the_guard_for_a_container_column(
    qtbot: QtBot, fast: bool
) -> None:
    """コンテナ行の **未展開の列** にオフセットがあっても一括選択で作動する。

    fast 経路では `_row_of_key("mf4_1::Mat[1]")` の最長一致が `mf4_1::Mat` 行へ
    落ちて ALL で即 True になる（列名を作らない）。
    """
    dlg = _dlg(qtbot, {"mf4_1::Mat[1]": 1.0}, fast=fast)
    assert dlg._range_visible.isEnabled() is True

    dlg._select_all()

    assert dlg._range_visible.isEnabled() is False
    assert dlg._range_cursor.isEnabled() is False


@pytest.mark.parametrize("fast", [True, False], ids=["fast", "legacy"])
def test_guard_releases_on_deselect_all(qtbot: QtBot, fast: bool) -> None:
    dlg = _dlg(qtbot, {"mf4_1::Mat[1]": 1.0}, fast=fast)
    dlg._select_all()
    # in-test positive control: ガードが**一度も作動していない**実装でも
    # 「解除したら有効」は自明に緑になる。作動状態を先に観測してから解除する。
    assert dlg._range_visible.isEnabled() is False

    dlg._select_none()

    assert dlg._range_visible.isEnabled() is True
    assert dlg._range_cursor.isEnabled() is True


@pytest.mark.parametrize("fast", [True, False], ids=["fast", "legacy"])
def test_guard_is_not_overprotective_for_unselected_offsets(
    qtbot: QtBot, fast: bool
) -> None:
    """オフセット信号を **選ばなければ** ラジオは有効のまま（Option B ではない）。"""
    dlg = _dlg(qtbot, {"mf4_1::Mat[1]": 1.0}, fast=fast)
    for row in dlg._iter_rows():
        dlg._tree.expandItem(row)
    leaf = next(
        c
        for c in dlg._iter_children()
        if c.data(0, Qt.ItemDataRole.UserRole) == "csv_1::alpha"
    )

    leaf.setCheckState(0, Qt.CheckState.Checked)

    assert dlg._range_visible.isEnabled() is True


@pytest.mark.parametrize("fast", [True, False], ids=["fast", "legacy"])
def test_partial_row_distinguishes_the_offset_column_from_its_siblings(
    qtbot: QtBot, fast: bool
) -> None:
    """PARTIAL の行では **その列** を選んだときだけ作動する（行単位に丸めない）。

    fast 経路の `_selection_touches` が ALL 早期 return だけで済ませ、PARTIAL の
    列 index 照合を落とすと Mat[0] を選んだだけで作動して RED。
    """
    dlg = _dlg(qtbot, {"mf4_1::Mat[1]": 1.0}, fast=fast)
    for row in dlg._iter_rows():
        dlg._tree.expandItem(row)
    leaves = {
        c.data(0, Qt.ItemDataRole.UserRole): c
        for c in dlg._iter_children()
        if c.data(0, Qt.ItemDataRole.UserRole) is not None
    }

    leaves["mf4_1::Mat[0]"].setCheckState(0, Qt.CheckState.Checked)
    assert dlg._range_visible.isEnabled() is True

    leaves["mf4_1::Mat[1]"].setCheckState(0, Qt.CheckState.Checked)
    assert dlg._range_visible.isEnabled() is False


def test_file_offset_group_key_trips_the_guard(qtbot: QtBot) -> None:
    """ファイルオフセット（グループキー）も交差判定の対象（fast 経路のみの形）。

    legacy 経路は `offset_for(列キー)` が合成値を返すので同じ答えになるが、
    fast 経路はグループキーを受け取るので、`_selection_touches` が
    「セパレータ無し = そのファイルの選択有無」を扱えないと素通しになる。
    """
    dlg = _dlg(qtbot, {"mf4_1": 1.0}, fast=True)
    assert dlg._range_visible.isEnabled() is True

    dlg._select_all()

    assert dlg._range_visible.isEnabled() is False


def test_zero_net_offset_is_not_an_offset(qtbot: QtBot) -> None:
    """相殺して 0 のキーはガードを作動させない（`offset_for` が値オラクル）。"""
    dlg = _dlg(qtbot, {"mf4_1::Mat[1]": 0.0}, fast=True)

    dlg._select_all()

    assert dlg._range_visible.isEnabled() is True
```

```
uv run pytest tests/gui/test_export_offset_guard_reversal.py tests/gui/test_export_csv_dialog.py -q
```
Expected: 新規 **12 passed**（parametrize 込み）＋既存すべて passed。

- [ ] **Step 5: realgui の内部状態読みを追随させる（機械的追随・supersede 記録つき）**

**方針の明示（このタスクの唯一の既存テスト編集）**: `tests/realgui/test_export_flow.py` の `dlg._selected` 読みは
**「出力に対する期待」ではなく「内部状態の構造読み」**である。本増分は `_selected` の**単位**を
「列 1 本 = 1 エントリ」から「物理チャンネル 1 行 = 1 エントリ」へ変える（spec §5.6）ので、
`len(dlg._selected)` はテストが意図した量（選択列数）を**もはや指さない**。
これは Global Constraints の「既存テストの期待内容は 1 本も編集しない」の**例外クラス**であり、
spec §5.1-2 の **BOM 読み口 26 本**と同じ扱い — すなわち
**「期待値（数・文言）は変えず、読み口だけを機械的に付け替え、各サイトに supersede コメントを残す」**。
`n_columns` との等号も、失敗メッセージ文言も、`mgr.mint_count == 0` も**一切変えない**。

編集は 3 種の機械的置換のみ:

| 現行 | 置換後 |
|---|---|
| `dlg._selected == {}` | `dlg.selected_count() == 0` |
| `len(dlg._selected) == n_columns` | `dlg.selected_count() == n_columns` |
| `len(dlg._selected)`（f-string 内） | `dlg.selected_count()` |
| `sorted(dlg._selected)[:5]`（`:225`） | `dlg._checked_keys()[:5]` |

`:179` の直前に supersede コメントを 1 度だけ置く（各行に繰り返さない）:

```python
    # E-4b Task 3 supersede: `_selected` は「列 1 本 = 1 エントリ」から
    # 「物理チャンネル 1 行 = 1 エントリ」へ圧縮された（spec §5.6・prod 54-57 MB
    # -> ~0.5 MB）ので `len(dlg._selected)` はもう選択列数ではない。**期待値
    # （n_columns との等号・文言）は 1 つも変えず**、読み口だけを列数を返す
    # `selected_count()` へ機械的に付け替える（BOM 読み口 26 本と同じ扱い）。
```

Layer C なので実ディスプレイでのみ実行できる:

```
uv run pytest tests/realgui/test_export_flow.py --realgui -q
```
Expected: **2 passed**（実ディスプレイが無い環境では skip — その場合は Step 8 の報告に「未実行（real display 不在）」と明記し、Task 11 の ①ゲートへ引き継ぐ）。

- [ ] **Step 6: 圧縮の効果を実測する（構造 ＋ バイト比）**

`tests/gui/test_export_selection_footprint.py` を新規作成:

```python
"""`_selected` の圧縮（E-4b spec §5.6）を構造とバイトの両方で固定する。

構造テスト（エントリ数 = **行数**）は scale-free な本命で、バイト比テストは
「畳み込みを外す」形の退行（ALL を PARTIAL(range(count)) で持つ）を捕まえる。
どちらか片方だけでは不十分: 構造だけだと PARTIAL 退行が緑、バイトだけだと
Python のバージョン差でしきい値が揺れる。

prod（4,324 行 / 330,004 列 / 実測 54-57 MB）はここでは再現しない — 合成でも
比は線形に効くので、CI では 100 行 / 50,000 列で十分に決定的。prod 1 点の実測は
Step 6b（demo_data がある環境でのみ）で行う（spec §9-1）。
"""

from __future__ import annotations

import sys

import numpy as np
from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.models import Signal
from valisync.gui.views.export_csv_dialog import ExportCsvDialog

_ROWS = 100
_COLS_PER_ROW = 500  # 100 x 500 = 50,000 列


def _deep_size(obj: object, seen: set[int] | None = None) -> int:
    """dict/tuple/frozenset/set/str/int を再帰した実バイト（共有は 1 度だけ数える）。

    共有を id で畳むのが要点: ALL の共有インスタンスや、`_rows` と `_selected` が
    共有する選択キー文字列を二重計上すると、圧縮の効果が見かけ上消える。
    """
    seen = set() if seen is None else seen
    if id(obj) in seen:
        return 0
    seen.add(id(obj))
    size = sys.getsizeof(obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            size += _deep_size(k, seen) + _deep_size(v, seen)
    elif isinstance(obj, (tuple, list, set, frozenset)):
        for item in obj:
            size += _deep_size(item, seen)
    elif hasattr(obj, "__slots__"):
        for name in obj.__slots__:  # type: ignore[attr-defined]
            size += _deep_size(getattr(obj, name), seen)
    return size


class _WideSession:
    def __init__(self) -> None:
        self._phys = [f"Ch{i:04d}" for i in range(_ROWS)]
        self._names = {
            p: tuple(f"{p}[{j}]" for j in range(_COLS_PER_ROW)) for p in self._phys
        }

    def source_name(self, key: str) -> str:
        return "wide.mf4"

    def group_signals(self, key: str) -> list[Signal]:
        return [
            Signal(
                name=f"mf4_1::{p}",
                timestamps=np.array([0.0]),
                values=np.array([1.0]),
                file_format="MDF4",
                bus_type="",
                source_file="",
                metadata={"physical_channel": p},
            )
            for p in self._phys
        ]

    def column_names_of(self, key: str, display_name: str) -> tuple[str, ...]:
        return self._names.get(display_name, (display_name,))

    def has_column(self, key: str, display_name: str) -> bool:
        return display_name not in self._names

    def resolve_signal(self, key: str) -> Signal | None:
        return None


class _WideAppVM:
    def __init__(self) -> None:
        self.session = _WideSession()
        self.loaded_file_keys = ["mf4_1"]


def test_select_all_keeps_one_entry_per_channel_row_not_per_column(
    qtbot: QtBot,
) -> None:
    """本命（scale-free）: 「すべて選択」のエントリ数は **行数**。

    旧形は列数ぶん（50,000）持っていた。列数に比例する実装はこの 1 本で落ちる。
    """
    dlg = ExportCsvDialog(_WideAppVM(), initial_selected=set())
    qtbot.addWidget(dlg)

    dlg._select_all()

    assert len(dlg._selected) == _ROWS
    assert dlg.selected_count() == _ROWS * _COLS_PER_ROW
    assert len(dlg._checked_keys()) == _ROWS * _COLS_PER_ROW


def test_select_all_footprint_is_orders_below_the_per_column_dict(
    qtbot: QtBot,
) -> None:
    """バイト比: 旧形（列ごとの `dict[str, tuple[int, int]]`）と実測で比べる。

    旧形を実際に組んで比べるのは、「比が桁で効く」ことを主張でなく実測で示す
    ため（推定値で書くと Python のバージョン差で意味が変わる）。
    """
    dlg = ExportCsvDialog(_WideAppVM(), initial_selected=set())
    qtbot.addWidget(dlg)
    dlg._select_all()

    new_bytes = _deep_size(dlg._selected)
    legacy = {
        key: (r, c)
        for r in range(_ROWS)
        for c, key in enumerate(dlg._column_keys(r))
    }
    legacy_bytes = _deep_size(legacy)

    print(f"[footprint] legacy={legacy_bytes:,} B  compressed={new_bytes:,} B")
    assert legacy_bytes // max(new_bytes, 1) >= 50, (
        f"圧縮比が想定を下回る: legacy={legacy_bytes} compressed={new_bytes}"
    )
    assert new_bytes < 1_000_000, f"50,000 列で {new_bytes} B は圧縮が効いていない"


def test_all_rows_share_one_selection_object(qtbot: QtBot) -> None:
    """ALL は行ごとに作らず共有する（`_ALL` シングルトン）。

    行ごとに `ColumnSelection(is_all=True)` を作る実装は上のバイト比を通って
    しまう（オブジェクトは小さい）ので、同一性で直接 pin する。
    """
    dlg = ExportCsvDialog(_WideAppVM(), initial_selected=set())
    qtbot.addWidget(dlg)
    dlg._select_all()

    values = list(dlg._selected.values())
    assert len({id(v) for v in values}) == 1


def test_unchecking_one_column_does_not_inflate_the_other_rows(
    qtbot: QtBot,
) -> None:
    """1 列外しても PARTIAL になるのは **その行だけ**（全行 PARTIAL 化の退行検出）。"""
    dlg = ExportCsvDialog(_WideAppVM(), initial_selected=set())
    qtbot.addWidget(dlg)
    dlg._select_all()

    dlg._drop_selection(0, 3, dlg._column_keys(0)[3])

    partial = [k for k, v in dlg._selected.items() if not v.is_all]
    assert len(partial) == 1
    assert dlg.selected_count() == _ROWS * _COLS_PER_ROW - 1
```

```
uv run pytest tests/gui/test_export_selection_footprint.py -q -s
```
Expected: **4 passed**。`[footprint]` 行の実測値（legacy / compressed）を報告に転記する。

- [ ] **Step 6b: prod 1 点の実測（spec §9-1・demo_data がある環境でのみ）**

spec §9-1 が「`_selected` 54-57 MB は合成再現・T-API 実装時に実ダイアログで 1 点測る」を残している。
`demo_data/` は gitignore でコミットしない — **スクラッチパッドの使い捨てスクリプト**で測る:

```
ls demo_data/*.mf4
```
が空なら「未実施（demo_data 不在）」と報告に書いて Step 7 へ進む。あるなら:

```python
# $SCRATCH/measure_selected.py
import sys
from PySide6.QtWidgets import QApplication
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.views.export_csv_dialog import ExportCsvDialog
from tests.gui.test_export_selection_footprint import _deep_size

app = QApplication([])
vm = AppViewModel()
vm.session.load(sys.argv[1])
vm.register_loaded(vm.session.group_keys()[0])
dlg = ExportCsvDialog(vm, initial_selected=set())
dlg._select_all()
print(f"rows={len(dlg._rows)} cols={dlg.selected_count()} "
      f"_selected={_deep_size(dlg._selected):,} B")
```

```
uv run python "$SCRATCH/measure_selected.py" demo_data/prod_demo.mf4
```
`rows` / `cols` / `_selected` の 3 数を報告に記録する（**主語つきで**: 「`_selected` が保持するバイト」であって
プロセス USS ではない）。spec §1 の 54-57 MB と突き合わせ、`< 1 MB` に落ちていることを確認する。

- [ ] **Step 6c: `_row_matches` への波及を調査して *記録だけ* する（spec §5.6 末尾）**

コードは変えない。次を実行して結果を報告に書く:

```
uv run python -c "import inspect, valisync.gui.views.export_csv_dialog as m; print(inspect.getsource(m.ExportCsvDialog._row_matches))"
```

確認すべき事実は 1 つ: **`_row_matches` は `_selected` を一切読まない**（読むのは `row.matched`/`row.hit` のメモと
`session.column_names_of`）。したがって本増分は打鍵ごとの列名再生成コストを**増やしも減らしもしない**。
フィルタ perf は本増分の目的ではないので（spec §8）、この事実を記録して終わり — 変更提案は書かない。

- [ ] **Step 7: sabotage で honest-RED を確認（必須）**

pristine copy は Step 2 のものを使う（無ければ取り直す）。各 sabotage 後に復元し、
復元直後に全 4 ファイルが緑に戻ることを確認してから次へ進む。

対象コマンド:
```
uv run pytest tests/gui/test_export_csv_dialog.py tests/gui/test_export_selection_order.py tests/gui/test_export_selection_footprint.py tests/gui/test_export_offset_guard_reversal.py -q -rf
```

| # | 壊す箇所（正確な編集） | 予測 RED |
|---|---|---|
| S1 | `_checked_keys` の `for row_index, row in enumerate(self._rows)` を `for row_index, row in sorted(enumerate(self._rows), key=lambda p: p[1].sel_key)` へ（行キー辞書順） | 新規 `test_select_all_orders_columns_across_files_by_tree_position` / `test_check_order_...` / `test_partial_selection_...` / `test_deselect_...` / `bulk` 2 件 ＋ **既存** `test_checked_keys_follow_tree_order_not_hash_order` / `test_file_row_check_cannot_fake_container_selection` / `test_file_row_checkbox_toggles_both_ways_through_the_delegate` / `test_file_row_check_from_partial_selects_everything` / `test_real_mdf_array_channel_is_one_row_with_lazy_columns` |
| S2 | `_add_selection` の ALL 畳み込み（`_ALL if len(merged) >= row.count else ...`）を常に `ColumnSelection(False, merged)` へ | `test_select_all_keeps_one_entry_per_channel_row_not_per_column` は **緑のまま**（`_select_all` は `_select_row_all` 経由で `_ALL` を直に置くので畳み込みを通らない）。RED は `test_all_rows_share_one_selection_object` **のみ**…にはならない点に注意 — 予測を「S2 は現行テストに RED を出さない可能性がある」とし、実測が RED 0 件なら**それを発見として報告**して、畳み込みを個別チェック経路で突くテスト（500 列を 1 本ずつチェックしてエントリが ALL に畳まれること）を新規 1 本足す |
| S3 | `_selection_touches` の `if sel.is_all: return True` を削除 | `test_select_all_trips_the_guard_for_a_container_column[fast]` / `test_file_offset_group_key_trips_the_guard` ではなく、**`[fast]` 側 1 件のみ**（group key 経路は `sep` 無し分岐で早期 return するので無関係）。`[legacy]` は別経路なので緑 |
| S4 | `_set_row` の `self._total += delta` を削除 | `test_selection_footer_updates_on_select_all_and_none`（既存）/ `test_selection_footer_shows_initial_count`（既存）/ `test_selection_footer_is_filter_independent`（既存）/ `test_file_row_check_cannot_fake_container_selection`（既存・フッター assert）/ `test_select_all_keeps_one_entry_per_channel_row_not_per_column` / `test_unchecking_one_column_does_not_inflate_the_other_rows` |
| S5 | `_row_of_key` の最長一致ループを `return self._row_by_sel_key.get(key)`（完全一致のみ）へ | `test_select_all_trips_the_guard_for_a_container_column[fast]` / `test_partial_row_distinguishes_the_offset_column_from_its_siblings[fast]` の **2 件**。1 列行（`csv_1::alpha`）は phys == 列名なので完全一致でも当たり、`[legacy]` は別経路 — この非対称まで一致させる |
| S6 | `_set_row` の `self._total_per_file` 更新を削除 | `test_file_offset_group_key_trips_the_guard` の **1 件のみ** |

**「既存テストを 1 行も編集していない」の実測**（例外は Step 5 の realgui のみ）:

```
git diff --stat tests/gui/test_export_csv_dialog.py tests/gui/test_main_window_export.py tests/gui/test_integration.py
```
Expected: **0 files changed**。

- [ ] **Step 8: ゲート＋コミット**

sabotage をすべて復元した状態で（**serial・パイプ禁止**）:

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

`uv run pytest` の passed 数が **Step 1 のベースライン + 22**（order 6 ＋ footprint 4 ＋ offset 12）になっていること。
skip 数も突き合わせる（増減があれば挙動不変が破れている）。

凍結カタログへの影響が無いことも確認する（`06_export_dialog_error` は本ダイアログの撮影状態）:

```
uv run python scripts/capture_ui_screenshots.py --catalog --theme dark --out "$SCRATCH/shots_dark"
uv run python scripts/compare_screenshots.py screenshots_catalog_dark "$SCRATCH/shots_dark"
```
Expected: **全状態一致**（本タスクはウィジェットを 1 つも足していないので 06 を含め差分ゼロ）。

```
git add src/valisync/gui/views/export_csv_dialog.py \
        src/valisync/gui/views/main_window.py \
        tests/gui/test_export_selection_order.py \
        tests/gui/test_export_selection_footprint.py \
        tests/gui/test_export_offset_guard_reversal.py \
        tests/realgui/test_export_flow.py
git commit -m "$(cat <<'EOF'
perf(gui): エクスポート選択を物理チャンネル単位の区間表現へ圧縮 (E-4b Task 3)

`_selected` を dict[列キー, (行, 列)] (prod 330,004 エントリ・実測 54-57 MB) から
dict[物理チャンネルキー, ColumnSelection] (~4,324 エントリ) へ置換する。
ALL は _ALL 1 個を全行で共有し、PARTIAL だけが明示 index を持つ。「すべて選択」
は行あたり O(1) になり、列名の f-string 生成も一括点 (_checked_keys) 1 箇所へ集約
される。

**順序の運搬者が消えるのが本変更の最も危ない点**。旧形は値 (行, 列) の sort が
出力列順を担っていたが、ColumnSelection は順序を持たない。順序は「選択の表現」
ではなく **木** から導出する (spec §5.6 [I4]) — `_rows` はファイル順 -> ローダー順
に積まれているので添字順の walk がそのままツリー表示順になる。この退化
(順序がチェック順へ落ちる) は既存の順序テストが単一ファイル 1 本しか無く
ファイル跨ぎは set 比較だけだったため **全部緑のまま通る** ので、圧縮の前に
test_export_selection_order.py (チェック順 = ツリー逆順のケースを含む) を足し、
現行実装に対する sabotage 2 種で網が空虚でないことを実証してから圧縮した。

オフセットガード (F-0 の「選択列にオフセットあり -> 表示由来ラジオ disabled」) は
方向を反転した (spec §5.6 [I5])。列ごとの probe 点が O(1) 化で消えるので、
オフセット辞書側 (少数) を走査して選択集合と交差判定する。列キーの所属行は
_mint_column と同じ最長一致で引き、ALL の行は列名を 1 本も作らずに決着する。
offset_keys 未注入の呼び出し側 (撮影ツール・既存テスト) は旧方式を legacy 経路
として保存し、両経路の同値を parametrize で直接突き合わせている。

既存テストの期待内容は 1 本も編集していない。唯一の追随は realgui の
`len(dlg._selected)` (内部状態の構造読み — 圧縮で単位が「列」から「行」へ変わる)
で、期待値と文言はそのままに読み口だけ selected_count() へ機械的に付け替えた
(BOM 読み口 26 本と同じ supersede 扱い)。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 4: `ExportRequest` keys 化＋`header_resolver`＋escape hatch＋移行橋

**Files:**
- Modify: `src/valisync/core/export/csv_exporter.py`（`ExportRequest` 新設・`CsvExportOptions.use_unified_timeline` 追加・`passthrough_header_names`・エラー定数 2 本。**`CsvExporter.export` の署名は変えない**）
- Create: `src/valisync/core/export/legacy_bridge.py`（**移行橋** — Task 7 が**ファイルごと削除**する）
- Modify: `src/valisync/core/export/__init__.py`（`ExportRequest` を公開）
- Modify: `src/valisync/core/session.py`（`export_csv` の keys 化・`_reject_container_channels` の keys 化）
- Modify: `src/valisync/gui/views/export_csv_dialog.py`（`ExportRequest` を core から再輸出・`csv_header_resolver`・`_on_accept` の keys 化・`_current_options` に unified）
- Modify: `src/valisync/gui/views/main_window.py`（`export_csv` の submit 引数・`:644` の stale 行番号コメント）
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py:141`（stale docstring "keys (paths)"）
- Test (add): `tests/core/test_export_request_bridge.py`（**新規** — 境界 API と橋）
- Test (add): `tests/core/test_export_bridge_golden.py`（**新規** — Task 2 のゴールデンを新境界で byte 一致）
- Test (add): `tests/gui/test_export_worker_compat.py`（**新規** — `submit` の後方互換 pin）
- Test (mechanical follow・移行表 Step 1 で全数確定): `tests/core/test_export_container_guard.py`（3 サイト）・`tests/test_csv_export_options.py`（1）・`tests/test_session.py`（1）・`tests/gui/test_main_window_export.py`（1 構築 ＋ 1 assert 群）・`tests/gui/test_export_csv_dialog.py`（2 `req.signals` 読み）・`tests/realgui/test_export_range_realclick.py`（2）

**Interfaces:**

- **Consumes**
  - Task 3: `ExportCsvDialog._checked_keys() -> list[str]`（ツリー表示順）・`selected_count()`。
  - Task 1/2: 是正 4 点込みのゴールデン成果物（`.csv` 実ファイル）。**本タスクはゴールデンを再生成しない** — 既存の `.csv` を `read_bytes()` で読み、新境界の出力と突き合わせるだけ（spec G1）。
  - 既存: `Session.resolve_signal(key) -> Signal | None`（Task 6 で `resolve_transient` へ差し替わる注入点）・`Session.column_names_of`・`Session.group_keys`・`gui.display_names.csv_header_names` / `display_names`。
- **Produces**（Task 5-11 がこれに対して書かれる・**共有インターフェース契約の逐語**）
  ```python
  # src/valisync/core/export/csv_exporter.py
  @dataclass(frozen=True)
  class ExportRequest:
      keys: tuple[str, ...]                     # 出力列順 = この順（ツリー表示順）
      output_path: Path
      options: CsvExportOptions                 # use_unified_timeline/delimiter/precision/
                                                # time_start/time_end/unit_row は options 経由
      header_resolver: Callable[[Sequence[str]], list[str]]
      extra_signals: tuple[Signal, ...] = ()    # Derived escape hatch (spec §5.2)

  def passthrough_header_names(keys: Sequence[str]) -> list[str]: ...   # 既定 resolver

  # src/valisync/core/session.py
  Session.export_csv(
      keys: Sequence[str], output_path: Path, options: CsvExportOptions | None = None, *,
      header_resolver: Callable[[Sequence[str]], list[str]] | None = None,
      extra_signals: Sequence[Signal] = (),
  ) -> None
  # header_resolver 既定 = passthrough (list(keys)) — 直呼び（テスト/ヘッドレス）の
  # 現行ヘッダバイトを保存する

  # src/valisync/core/export/legacy_bridge.py  ← Task 7 が **ファイルごと削除**
  def export_via_legacy_path(
      request: ExportRequest, resolve: Callable[[str], Signal | None]
  ) -> None: ...

  # src/valisync/gui/views/export_csv_dialog.py
  from valisync.core.export.csv_exporter import ExportRequest   # 再輸出（既存 import 経路を保存）
  def csv_header_resolver(keys: Sequence[str]) -> list[str]: ...  # モジュール **関数**（クロージャ禁止）
  ```
  - **`CsvExporter.export(signals, output_path, use_unified_timeline=False, options=None)` の署名は Task 4 では変えない**。Task 7 が `export(request, resolve, *, progress, cancel)` へ置き換え、そのとき本橋が消える。
  - **`CsvExportOptions.header_names` は Task 4 では残す**（`test_csv_export_options.py:161` が pin）。橋が `header_resolver` の結果をここへ詰めて旧実装へ渡すのが、ヘッダバイトを保存する仕組み。Task 7 の撤去時は supersede 記録が要る（下の「Task 7 への引き継ぎ」）。
  - `ExportController.submit` の署名は **変えない**（下の「解決した曖昧さ」参照）。

---

- [ ] **Step 1: 移行表を確定する（着手前に全数を実測で列挙する）**

推測でなく grep で数える:

```
grep -rn "\.export_csv(" tests/ src/ scripts/
grep -rn "CsvExporter()\.export(" tests/ src/ scripts/
grep -rn "ExportRequest" tests/ src/ scripts/
grep -rn "req\.signals\|req\.use_unified_timeline\|_result\.signals" tests/ src/ scripts/
```

**方針の 2 クラス**（各サイトに必ずどちらかを割り当てる）:

- **bridge-transparent（編集ゼロ）** — 橋が旧一括実装へ落とすので、期待値も呼び出し形も変わらない。
- **mechanical follow（supersede コメント必須）** — 呼び出し形（境界の**引数の意味**）が D1 で変わるサイト。
  **期待内容（値・文字列・数）は 1 つも変えない**。Global Constraints の例外クラスであり、
  spec §5.1-2 の BOM 読み口 26 本と同じ扱い。

| # | サイト | クラス | 内容 |
|---|---|---|---|
| 1 | `src/valisync/gui/views/main_window.py:971` | src 書き換え | `session.export_csv(req.keys, req.output_path, req.options, header_resolver=..., extra_signals=...)` |
| 2 | `src/valisync/gui/views/export_csv_dialog.py:794` | src 書き換え | `ExportRequest(keys=..., output_path=..., options=..., header_resolver=csv_header_resolver)` |
| 3 | `tests/core/test_export_container_guard.py:144` | mechanical | `session.export_csv([parent], ...)` → `([parent.name], ...)`。`pytest.raises(ValueError, match=r"Mat\[0\]")` は不変 |
| 4 | `tests/core/test_export_container_guard.py:159` | mechanical | `session.export_csv([col], out)` → `([col.name], out)`。ヘッダ期待 `f"timestamp,{key}::Mat[0]"` は passthrough resolver で**バイト不変** |
| 5 | `tests/core/test_export_container_guard.py:171` | mechanical | Derived（グループ非所属）→ `session.export_csv([], out, extra_signals=[_scalar_signal()])`。期待 `"timestamp,Plain"` 不変 |
| 6 | `tests/test_csv_export_options.py:78` | mechanical | 同上（`extra_signals=`）。期待 `"timestamp;v"` 不変 |
| 7 | `tests/test_session.py:450` | mechanical | 同上。期待 `"timestamp,speed"` 不変 |
| 8 | `tests/realgui/test_export_range_realclick.py:181-186` | mechanical | 4 位置引数 → `req.keys, req.output_path, req.options, header_resolver=req.header_resolver` |
| 9 | `tests/realgui/test_export_range_realclick.py:214-219` | mechanical | 同上 |
| 10 | `tests/gui/test_main_window_export.py:39-44` | mechanical | `ExportRequest(signals=..., use_unified_timeline=...)` → `keys=("csv_1::a",), options=..., header_resolver=csv_header_resolver`。`sig`/`Signal`/`np` が未使用になるので削除（ruff F841/F401） |
| 11 | `tests/gui/test_main_window_export.py:56-59` | mechanical | 転送 assert を `args[0] == ("csv_1::a",)` / `args[2] is req.options` / `kwargs["header_resolver"] is req.header_resolver` へ。**「4 引数が転送される」という契約の意図は保存**する |
| 12 | `tests/gui/test_export_csv_dialog.py:162` | mechanical | `{s.name for s in req.signals} == {...}` → `set(req.keys) == {...}`（右辺は不変） |
| 13 | `tests/gui/test_export_csv_dialog.py:858` | mechanical | `[s.name for s in req.signals] == ["mf4_1::Mat[1]"]` → `list(req.keys) == [...]`（右辺不変） |
| 14 | `tests/gui/test_export_csv_dialog.py:161/416/857` `isinstance(req, ExportRequest)` | **transparent** | GUI モジュールが core の `ExportRequest` を再輸出するので import も isinstance も生存 |
| 15 | `tests/gui/test_export_csv_dialog.py:859` `resolve_calls == 1` | **transparent** | accept 時の解決可能性検証（spec §5.2）が同じ回数 `resolve_signal` を呼ぶ |
| 16 | `tests/gui/test_export_csv_dialog.py:862-883`（missing 検出） | **transparent** | 保存先を訊く前に落とす UX 契約を保存 |
| 17 | `tests/test_export.py` 5 サイト（Derived） | **transparent** | `CsvExporter.export` の旧署名を Task 4 では変えない |
| 18 | `tests/test_csv_export_options.py` 24 サイト（`CsvExporter().export`） | **transparent** | 同上（`header_names` フィールドも残す） |
| 19 | `tests/core/test_export_container_guard.py` 6 サイト（`CsvExporter().export`） | **transparent** | 同上 |
| 20 | `tests/test_pbt_csv.py:192` | **transparent** | 同上 |
| 21 | `tests/gui/test_integration.py:175` | **transparent** | `ask` が None を返すのでエクスポートまで到達しない |
| 22 | `tests/realgui/test_export_flow.py:62` | **transparent** | `MainWindow.export_csv` 自体を monkeypatch |
| 23 | `tests/realgui/test_comparison_model_realclick.py:441` | **transparent** | ツリーのテキストしか読まない |
| 24 | `tests/gui/test_export_worker.py` 5 サイト | **transparent** | `submit` の署名を変えない |
| 25 | `tests/gui/test_unload_export_guard.py:63/118` | **transparent** | 同上 |
| 26 | `scripts/capture_ui_screenshots.py:245` | **transparent** | ダイアログを構築して撮るだけ |
| 27 | `tests/golden_csv_cases.py`（`export_case` の `CsvExporter().export(` 1 サイト）／`tests/test_golden_csv.py`（`_export_with` の 1 サイト ＋ `test_block_cols_handoff_is_not_forgotten` の signature introspection） | **transparent** | **Task 2 の成果物**。legacy 署名は Task 4 では変えないので無編集 |

grep の実測件数（`CsvExporter().export(` 36 ＋ `.export_csv(` 8 ＋ `ExportRequest` 構築 2 ＋ `req.signals` 読み 4 ＝ **50 サイト / 11 ファイル**）を報告に書き、
spec §5.2 の「48 サイト / 7 ファイル」との差分（**+2 / +4**）を差分の内訳つきで記録する（spec の数は概算・実測が正）。
**mechanical follow は 12 サイト・transparent は 38 サイト**。

> **この表の 50/11 は Task 2 の成果物を含まない時点の実測**。Task 2 が `tests/golden_csv_cases.py` と `tests/test_golden_csv.py` を足しているので、Task 4 の実行時 grep は **50/11 を再現しない**（`CsvExporter().export(` が +2 前後・ファイルが +2）。照合するときは **#27 の Task 2 追加分を内訳として控除**してから 50/11 と突き合わせ、控除後も一致しなければ**停止して報告**する（誰かが別の呼び出しを足している）。

- [ ] **Step 2: 失敗テストを書く**

`tests/core/test_export_request_bridge.py` を新規作成:

```python
"""境界 API の keys 化と移行橋（E-4b Task 4・spec §5.2）。

橋は「keys を全解決して旧一括実装へ渡す」薄いアダプタで、Task 7 が撤去する。
本ファイルが固定するのは **境界の契約** であって橋の実装ではないので、
Task 7 で橋が消えてもそのまま生き残る設計にしてある（本ファイルの test 関数は
1 本も ``export_via_legacy_path`` / ``legacy_bridge`` を参照しない — すべて
``Session.export_csv`` 経由。橋の削除で import エラーになるテストは存在しない）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.csv_exporter import (
    CsvExportOptions,
    ExportRequest,
    passthrough_header_names,
)
from valisync.core.models import Signal
from valisync.core.session import Session

from tests.mdf4_helpers import write_mdf4_2d


def _derived(name: str, ts: list[float], vs: list[float]) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="Derived",
        bus_type="",
        source_file="",
        metadata={},
    )


def _read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8-sig").splitlines()


# ─── keys 経路（passthrough 既定） ────────────────────────────────────────────


def test_export_csv_writes_columns_in_key_order(tmp_path: Path) -> None:
    """出力列順 = keys の順（spec §10）。**逆順を渡すと逆順で出る**。

    「ヘッダと値は同じ keys から導出」の by-construction 性の直接検証でもある。
    旧 API は signals と header_names を別々に運んでいて、header_names 指定時
    （GUI 経路）の対応崩しを守るテストが無かった（C1/M7）。header_names=None の
    既存テスト 6 本は `signals.reverse()` を捕まえるが、header_names 指定時は
    無検出だった。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    out = tmp_path / "rev.csv"

    session.export_csv([f"{key}::Mat[2]", f"{key}::Mat[0]"], out)

    assert _read(out)[0] == f"timestamp,{key}::Mat[2],{key}::Mat[0]"


def test_passthrough_header_resolver_is_the_default(tmp_path: Path) -> None:
    """既定 resolver は list(keys) — 直呼びの現行ヘッダバイトを保存する。"""
    assert passthrough_header_names(["a::b", "c::d"]) == ["a::b", "c::d"]


def test_injected_header_resolver_drives_the_header_row(tmp_path: Path) -> None:
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    out = tmp_path / "h.csv"

    session.export_csv(
        [f"{key}::Mat[0]"],
        out,
        header_resolver=lambda ks: [k.split("::", 1)[1] for k in ks],
    )

    assert _read(out)[0] == "timestamp,Mat[0]"


def test_header_resolver_length_mismatch_fails_loudly(tmp_path: Path) -> None:
    """resolver が keys と違う本数を返したら書かずに落ちる。

    ここを通すと「ヘッダと値がずれた CSV」が黙って出る — E-4b が構造的に
    根治しようとしている失敗そのものなので、橋の段でも検査する。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    out = tmp_path / "bad.csv"

    with pytest.raises(ValueError, match="ヘッダ"):
        session.export_csv(
            [f"{key}::Mat[0]", f"{key}::Mat[1]"], out, header_resolver=lambda ks: ["x"]
        )
    assert not out.exists()


def test_unresolvable_key_fails_loudly_without_writing(tmp_path: Path) -> None:
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    out = tmp_path / "missing.csv"

    with pytest.raises(ValueError, match="解決"):
        session.export_csv([f"{key}::NoSuchColumn"], out)
    assert not out.exists()


def test_empty_request_fails_loudly(tmp_path: Path) -> None:
    """keys も extra_signals も空なら書かずに落ちる（素の IndexError にしない）。"""
    out = tmp_path / "empty.csv"
    with pytest.raises(ValueError, match="1 つも"):
        Session().export_csv([], out)
    assert not out.exists()


# ─── Derived escape hatch（spec §5.2 [I-3]） ─────────────────────────────────


def test_extra_signals_carry_derived_signals_that_no_key_can_resolve(
    tmp_path: Path,
) -> None:
    """Derived は SignalGroupManager に登録されず keys で解決できない。

    ヘッダは Signal 自身の名前（keys 側の resolver は通さない）— 名前空間を
    持たないので resolver に渡す意味が無い。
    """
    out = tmp_path / "derived.csv"

    Session().export_csv([], out, extra_signals=[_derived("Plain", [0.0], [1.5])])

    assert _read(out)[0] == "timestamp,Plain"
    assert _read(out)[1] == "0.0,1.5"


def test_extra_signals_come_after_keys_in_column_order(tmp_path: Path) -> None:
    """列順は keys -> extra_signals（混ぜない）。

    GUI のツリーは `loaded_file_keys` しか列挙しないので Derived は今日
    選択に入らない。順序契約を先に固定しておかないと、後で Derived を
    載せた瞬間に列順が実装依存で決まる。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    out = tmp_path / "mixed.csv"

    session.export_csv(
        [f"{key}::Mat[0]"],
        out,
        extra_signals=[_derived("Extra", [0.0, 1.0, 2.0, 3.0], [9.0, 9.0, 9.0, 9.0])],
    )

    assert _read(out)[0] == f"timestamp,{key}::Mat[0],Extra"


def test_extra_signals_are_still_container_checked(tmp_path: Path) -> None:
    """escape hatch はコンテナ拒否の抜け道にはならない。

    名前空間つき Signal を extra_signals へ入れて guard を迂回できると、
    「GUI を通らない直呼びを守る唯一の層」（E-3 C-d）が穴になる。
    """
    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    parent = next(s for s in session.group_signals(key) if s.name == f"{key}::Mat")

    with pytest.raises(ValueError, match=r"Mat\[0\]"):
        session.export_csv([], tmp_path / "out.csv", extra_signals=[parent])


# ─── options.use_unified_timeline（M-1） ─────────────────────────────────────


def test_use_unified_timeline_travels_through_options(tmp_path: Path) -> None:
    """統合タイムラインは options 経由（共有インターフェース契約 M-1）。"""
    a = _derived("a", [0.0, 2.0], [10.0, 12.0])
    b = _derived("b", [1.0, 2.0], [21.0, 22.0])
    out = tmp_path / "u.csv"

    Session().export_csv(
        [],
        out,
        options=CsvExportOptions(use_unified_timeline=True),
        extra_signals=[a, b],
    )

    assert _read(out) == ["timestamp,a,b", "0.0,10.0,", "1.0,,21.0", "2.0,12.0,22.0"]


def test_positional_bool_as_options_is_refused(tmp_path: Path) -> None:
    """移行し損ねた呼び出し（第 3 引数に bool）を黙って options 扱いしない。

    `export_csv(keys, path, True)` は旧署名の use_unified_timeline のつもりで、
    新署名では options。dataclass でない bool が素通しされると
    `opts.delimiter` で AttributeError が出るだけで原因が分からない。
    """
    with pytest.raises(TypeError, match="use_unified_timeline"):
        Session().export_csv([], tmp_path / "x.csv", True)  # type: ignore[arg-type]


# ─── ExportRequest 自体 ──────────────────────────────────────────────────────


def test_export_request_is_frozen_and_defaults_extra_signals_empty() -> None:
    req = ExportRequest(
        keys=("a::b",),
        output_path=Path("x.csv"),
        options=CsvExportOptions(),
        header_resolver=passthrough_header_names,
    )
    assert req.extra_signals == ()
    with pytest.raises(Exception):
        req.keys = ()  # type: ignore[misc]
```

`tests/core/test_export_bridge_golden.py`（**Task 2 のゴールデンを新境界で byte 一致させる**）:

```python
"""Task 2 のゴールデンを **新しい境界 API 経由** でも byte 一致させる（spec G1/MG-7）。

期待バイトはこのファイルに書き写さない — Task 2 が凍結した `.csv` を
`read_bytes()` で読む（二重の真実を作らない・ゴールデンの再生成は禁止）。
橋を通しても 1 バイトも動かないことが「MG-7 のヘッダ導出形の凍結」の実証。

Task 2 の成果物 (実名・確定済み) を import して再利用し、**ケースの定義を
ここへ複製しない**:

    from tests.golden_csv_cases import GOLDEN_CASES, GOLDEN_DIR, build_options
"""
```
→ 実装時に Task 2 の公開口（ケース一覧 or fixture ディレクトリ）へ束ねる。
最低限、次の 2 本を成立させること:

1. `test_golden_bytes_survive_the_keys_boundary` — Task 2 の各ケースを
   `Session.export_csv(keys=..., header_resolver=<そのケースの resolver>)` で再実行し、
   `out.read_bytes() == golden_path.read_bytes()`。
2. `test_passthrough_golden_bytes_survive_the_keys_boundary` — resolver 未指定（passthrough）の
   ゴールデンについて同じことをする。

`tests/gui/test_export_worker_compat.py`:

```python
"""`ExportController.submit` の後方互換 pin（E-4b Task 4）。

spec §5.2 は「submit の署名は後方互換に拡張」と書くが、**T-API では拡張が
要らない**（境界の変更は callable の中身にしか現れない）。進捗/キャンセルを
足すのは T-UX (Task 8/9) なので、ここでは「足すときに壊してはいけない形」を
固定するだけにする — 既存 5 本と合わせてこれが Task 8/9 の受け入れ条件になる。
"""

from __future__ import annotations

import inspect

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.workers.export_worker import ExportController


def test_submit_takes_a_zero_arg_callable_positionally() -> None:
    """第 1 引数は位置で渡せる zero-arg callable のまま（既存 5 本の前提）。"""
    sig = inspect.signature(ExportController.submit)
    params = list(sig.parameters.values())
    assert params[1].name == "export_callable"
    assert params[1].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    # busy/on_success/on_error/label はすべて既定つきキーワード専用
    for name in ("busy", "on_success", "on_error", "label"):
        p = sig.parameters[name]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY
        assert p.default is None


def test_worker_is_retained_until_the_callback_fires(qtbot: QtBot) -> None:
    """QRunnable + 別 signals QObject の寿命保持（memory: queued signal 消失）。

    Task 8/9 が submit へ progress/cancel を足すときに最も落としやすい不変条件。
    `_active` を直接見るのは、これが「参照を保持している」ことの唯一の観測点だから。
    """
    import threading

    ctl = ExportController()
    release = threading.Event()
    done: list[int] = []
    ctl.submit(lambda: release.wait(5.0), on_success=lambda: done.append(1))
    assert len(ctl._active) == 1
    release.set()
    qtbot.waitUntil(lambda: done == [1], timeout=5000)
    assert ctl._active == set()
```

この時点で:
```
uv run pytest tests/core/test_export_request_bridge.py tests/gui/test_export_worker_compat.py -q
```
Expected: `test_export_worker_compat.py` の **2 passed**、`test_export_request_bridge.py` は
**collection error 1 件**（冒頭の `from valisync.core.export.csv_exporter import ExportRequest` が
ImportError — 12 本の test 関数は 1 本も実行されない。「13 failed」ではない）。
compat 側が先に緑なのが正しい（既存挙動の pin なので）。

- [ ] **Step 3: core を実装する（ExportRequest / options / Session / 橋）**

**(a) `src/valisync/core/export/csv_exporter.py`**

import に `from collections.abc import Callable, Sequence` を追加。

`CsvExportOptions` に**末尾**フィールドを 1 本足す（位置構築の後方互換のため必ず末尾）:

```python
    #: 統合タイムライン（各信号のタイムスタンプの和集合へ整列）で書き出すか。
    #: E-4b spec §5.2 [M-1]: 新境界 (`ExportRequest`) では use_unified_timeline を
    #: 独立引数で運ばず options に載せる（`Session.export_csv` の第 3 位置引数が
    #: bool から options へ変わるため、bool を別に運ぶと 2 つの真実になる）。
    #: **旧 `CsvExporter.export(..., use_unified_timeline=...)` は Task 4 では
    #: 据え置き**（直呼び 36 サイトの契約）で、橋が options -> 旧引数へ写す。
    #: Task 7 で旧引数が消え、このフィールドが唯一の真実になる。
    use_unified_timeline: bool = False
```

エラー定数を 2 本追加（core に置く理由は既存 2 本と同じ — GUI を通らない直呼びを守る唯一の層）:

```python
EXPORT_EMPTY_REQUEST_ERROR = (
    "書き出す列が 1 つも指定されていません。信号を選択してください。"
)
EXPORT_HEADER_LENGTH_ERROR_TMPL = (
    "ヘッダ名の本数 ({got}) が列数 ({want}) と一致しません。"
)
EXPORT_UNRESOLVED_KEYS_ERROR_TMPL = (
    "{n} 件の列を解決できませんでした (例: '{name}')。ファイルが閉じられた可能性があります。"
)
```

`ExportRequest` と既定 resolver（`CsvExporter` クラスの**前**に置く）:

```python
def passthrough_header_names(keys: Sequence[str]) -> list[str]:
    """既定のヘッダ解決器 — キーをそのままヘッダ名にする。

    `Session.export_csv` を直呼びする経路（テスト・scripted・realgui）の
    **現行ヘッダバイトを保存する**ための既定 (spec §5.2 / MG-7)。旧実装は
    `header_names is None` のとき `signal.name` を書いており、列キーは
    名前空間つき Signal 名と 1:1 なので `list(keys)` と同じバイトになる。
    GUI は `gui.display_names.csv_header_names` を束ねた resolver を注入する
    （core は gui を import しない契約 — C-5）。
    """
    return list(keys)


@dataclass(frozen=True)
class ExportRequest:
    """CSV 書き出しの確定要求（E-4b spec §5.2 の境界 API）。

    **Signal のリストを受けない**のが D1 の核心: prod 330,004 列を Signal で
    運ぶと出口に立つ前に ~390 MB を確定させてしまう。列は *キー* で運び、
    実体化は書き手（Task 6/7 の列ブロック）がブロック単位で行う。

    ``header_resolver`` を持たせるのは、ヘッダと値を**同じ keys から導出**する
    ため（別持ちの ``CsvExportOptions.header_names`` は「対応を守るテストが
    ゼロ」という穴を構造的に持っていた — C1/M7）。core は gui を import しない
    ので、表示名の計算は callable として注入する (C-5)。

    ``extra_signals`` は Derived 信号の escape hatch (spec §5.2 [I-3])。Derived は
    ``SignalGroupManager`` に登録されず keys では解決できないので、Signal 直渡しを
    維持する。出力列順は **keys -> extra_signals**（混ぜない）。
    """

    keys: tuple[str, ...]
    output_path: Path
    options: CsvExportOptions
    header_resolver: Callable[[Sequence[str]], list[str]]
    extra_signals: tuple[Signal, ...] = ()
```

**(b) `src/valisync/core/export/legacy_bridge.py`（新規・Task 7 が削除）**

```python
"""T-API の移行橋（E-4b spec §5.2 [plan-4] — **Task 7 がこのファイルごと削除する**）。

境界 API を keys 化する Task 4 と、列ブロック × 行ストリームで実際に書く
Task 6/7 の間を埋める薄いアダプタ。keys を **全部** 解決してから旧一括実装
(`CsvExporter.export(signals, ...)`) へ渡すので、メモリ挙動は Task 4 の時点では
**現状のまま**（改善しない）— 改善は Task 6/7 の仕事で、Task 4 の仕事は
「境界が動いても出力バイトが 1 バイトも動かない」ことを橋で証明することにある。

独立ファイルにしてあるのは、撤去が **ファイルの削除** という構造的に検証可能な
操作になるから（`grep -rn legacy_bridge src/` が 0 件になれば撤去完了）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from valisync.core.export.csv_exporter import (
    EXPORT_EMPTY_REQUEST_ERROR,
    EXPORT_HEADER_LENGTH_ERROR_TMPL,
    EXPORT_UNRESOLVED_KEYS_ERROR_TMPL,
    CsvExporter,
    ExportRequest,
)
from valisync.core.models import Signal


def export_via_legacy_path(
    request: ExportRequest, resolve: Callable[[str], Signal | None]
) -> None:
    """*request* の keys を全解決し、旧一括実装で書き出す。

    ヘッダは `request.header_resolver(request.keys)` から、値は同じ keys から
    解決した Signal から作る — **同じ列から両方を導出する**のが保存すべき契約
    (spec §10)。extra_signals は末尾に連結し、ヘッダは Signal 自身の名前を使う
    （名前空間を持たないので resolver に渡す意味が無い）。
    """
    resolved: list[Signal] = []
    missing: list[str] = []
    for key in request.keys:
        sig = resolve(key)
        if sig is None:
            missing.append(key)
        else:
            resolved.append(sig)
    if missing:
        raise ValueError(
            EXPORT_UNRESOLVED_KEYS_ERROR_TMPL.format(n=len(missing), name=missing[0])
        )

    header = list(request.header_resolver(request.keys))
    if len(header) != len(request.keys):
        raise ValueError(
            EXPORT_HEADER_LENGTH_ERROR_TMPL.format(
                got=len(header), want=len(request.keys)
            )
        )

    signals = [*resolved, *request.extra_signals]
    if not signals:
        raise ValueError(EXPORT_EMPTY_REQUEST_ERROR)
    names = (*header, *(s.name for s in request.extra_signals))

    # header_names は Task 4 時点の旧 CsvExporter への **唯一の** ヘッダ搬送路。
    # Task 7 で `CsvExporter.export(request, resolve, ...)` へ移ると、この
    # replace ごと消える（フィールド自体の撤去可否は Task 7 が判断する）。
    opts = replace(request.options, header_names=names)
    CsvExporter().export(
        signals, request.output_path, request.options.use_unified_timeline, opts
    )
```

**(c) `src/valisync/core/export/__init__.py`**

```python
from valisync.core.export.csv_exporter import (
    CsvExporter,
    CsvExportOptions,
    ExportRequest,
    passthrough_header_names,
)

__all__ = ["CsvExportOptions", "CsvExporter", "ExportRequest", "passthrough_header_names"]
```

**(d) `src/valisync/core/session.py`**

```python
    def export_csv(
        self,
        keys: Sequence[str],
        output_path: Path,
        options: CsvExportOptions | None = None,
        *,
        header_resolver: Callable[[Sequence[str]], list[str]] | None = None,
        extra_signals: Sequence[Signal] = (),
    ) -> None:
        """名前空間つき列キーで CSV を書き出す (E-4b spec §5.2・D1)。

        **Signal のリストは受けない** — prod 330,004 列を Signal で運ぶと出口に
        立つ前に ~390 MB を確定させる。解決は書き手が行う（Task 4 の時点では
        移行橋が全解決するので、メモリ挙動はまだ現状のまま）。

        *header_resolver* 既定は passthrough（`list(keys)`）で、直呼び経路の
        現行ヘッダバイトを保存する。GUI は `csv_header_names` を束ねた resolver を
        注入する（core は gui を import しない — C-5）。
        *extra_signals* は Derived の escape hatch（spec §5.2 [I-3]）。
        """
        if isinstance(options, bool):
            # 旧署名 (signals, path, use_unified_timeline, options) から移行し
            # 損ねた呼び出し。黙って options 扱いすると `opts.delimiter` の
            # AttributeError になるだけで原因が読めない。
            raise TypeError(
                "export_csv の第 3 引数は CsvExportOptions です "
                "(use_unified_timeline は options.use_unified_timeline へ移動 — "
                "E-4b spec §5.2)"
            )
        keys = tuple(keys)
        extras = tuple(extra_signals)
        self._reject_container_channels((*keys, *(s.name for s in extras)))
        request = ExportRequest(
            keys=keys,
            output_path=output_path,
            options=options if options is not None else CsvExportOptions(),
            header_resolver=(
                header_resolver
                if header_resolver is not None
                else passthrough_header_names
            ),
            extra_signals=extras,
        )
        export_via_legacy_path(request, self.resolve_signal)

    def _reject_container_channels(self, keys: Sequence[str]) -> None:
        """配列/構造体チャンネルの親を、値を読む前に拒否する (E-3 C-d)。

        GUI のダイアログは親行をチェック不可にしている (C-a) が、scripted /
        realgui は ``session.export_csv`` を直呼びするため、ここが実効的な唯一の
        防波堤になる。所属グループが引けないキー (Derived・アンロード済み) は
        列構造を知りようがないので通す — 判定不能を拒否に倒すと Derived_Signal の
        エクスポートが全滅する (最後の砦は CsvExporter 側の 1 時刻 1 値検査)。

        E-4b: 判定材料が Signal から **キー** へ変わっただけで、述語も文言も不変。
        値を読まない (ColumnRecord 由来) ので 0.1 ms fail-fast も維持される。
        extra_signals の名前もここへ流す — escape hatch を guard の抜け道に
        しないため。
        """
        loaded = set(self.group_keys())
        for key in keys:
            group_key, sep, bare = key.partition(KEY_SEPARATOR)
            if not sep or group_key not in loaded:
                continue
            columns = self.column_names_of(group_key, bare)
            if columns == (bare,):
                continue
            raise ValueError(
                EXPORT_CONTAINER_CHANNEL_ERROR_TMPL.format(
                    name=bare, example=columns[0] if columns else bare
                )
            )
```

`self._exporter` は橋が自前で `CsvExporter()` を作るので未使用になる。**削除しない**
（Task 7 が `CsvExporter.export(request, resolve, ...)` へ戻すときの受け皿。ruff は
インスタンス属性の未使用を報告しない）。橋へ `self._exporter` を渡さないのは、
Task 7 の差し替え点を `Session` 側 1 行（`export_via_legacy_path(...)` →
`self._exporter.export(request, self.resolve_signal_transient, ...)`）に閉じ込めるため。

import を追加: `from collections.abc import Callable, Iterable, Sequence`／
`from valisync.core.export.csv_exporter import ExportRequest, passthrough_header_names`／
`from valisync.core.export.legacy_bridge import export_via_legacy_path`。

```
uv run pytest tests/core/test_export_request_bridge.py -q
```
Expected: **12 passed**（`def test_` の実数）。

- [ ] **Step 4: GUI を実装する（dialog / main_window / stale docstring）**

**(a) `export_csv_dialog.py`**

- GUI ローカルの `ExportRequest` dataclass（`:105-112`）を**削除**し、core から**再輸出**する:

```python
from valisync.core.export.csv_exporter import (
    CsvExportOptions,
    ExportRequest,  # 再輸出: `from ...export_csv_dialog import ExportRequest` を
                    # 使う既存テスト/realgui の import 経路を保存する（型は core の
                    # ものが唯一の真実・E-4b spec §5.2）
)
```

- モジュール関数として resolver を定義する（**クロージャにしない**）:

```python
def csv_header_resolver(keys: Sequence[str]) -> list[str]:
    """GUI 側のヘッダ解決器 — 選択集合内で衝突するときだけ qualified にする (E-0)。

    **モジュール関数**であってダイアログのメソッドやクロージャではない。
    この callable は `ExportRequest` に載って worker スレッドへ渡り、書き出しが
    終わるまで生き続けるので、`self` を捕まえるとダイアログ（と、その先の
    QTreeWidget 全部）が export の全期間 GC されなくなる。
    """
    names = csv_header_names(keys)
    return [names[k] for k in keys]
```

- `_current_options` に統合タイムラインを載せる（`replace` の import は不要になるので削除）:

```python
            return CsvExportOptions(
                delimiter=self._delim.currentData(),
                decimal=self._decimal.currentData(),
                unit_row=self._unit_row.isChecked(),
                precision=precision,
                time_start=time_start,
                time_end=time_end,
                use_unified_timeline=self._unified.isChecked(),
            )
```

- `_on_accept` を keys 化する（`:760-800` を置換）:

```python
    def _on_accept(self) -> None:
        opts = self._current_options()
        keys = tuple(self._checked_keys())
        if opts is None or not keys:
            return
        # 解決可能性の検証は **保存先を訊く前**（spec §5.2・既存 UX 契約）。
        # E-4b: 結果の Signal は **保持しない** — 旧実装はここで作った
        # list[Signal] をそのまま要求に載せていて、prod 330,004 列で ~390 MB を
        # 出口の手前で確定させていた。鋳造は E-4a の LRU（容量 512）に載るので
        # 同時生存は 512 本で頭打ちになり、参照を落とせば残らない。
        # （Task 6 でここは `resolve_transient` へ差し替わり、帳簿にも載らなくなる。）
        session = self._app_vm.session
        missing = [k for k in keys if session.resolve_signal(k) is None]
        if missing:
            # 旧実装はここが素の KeyError でダイアログごとクラッシュしていた。
            # 無言で落とすと「選んだのに出ていない CSV」になるので、出力せずに
            # 理由を出す。
            self._error.setText(
                S.EXPORT_UNRESOLVED_ERROR_TMPL.format(
                    n=len(missing), name=display_names(missing)[missing[0]]
                )
            )
            return
        path = self._save_path_provider()
        if not path:
            return  # 保存ダイアログをキャンセル
        self._result = ExportRequest(
            keys=keys,
            output_path=Path(path),
            options=opts,
            header_resolver=csv_header_resolver,
        )
        self.accept()
```

`Signal` の import は `_physical_channels` がまだ使うので残す。`replace` は未使用になるので削除。
`Sequence` を `collections.abc` の import へ追加。

**(b) `main_window.export_csv`（`:970-973`）**

```python
        self._export_controller.submit(
            lambda: session.export_csv(
                req.keys,
                req.output_path,
                req.options,
                header_resolver=req.header_resolver,
                extra_signals=req.extra_signals,
            ),
```

**(c) stale な記述の是正（本増分の rider）**

- `app_viewmodel.py:141`: `"""List of keys (paths) for all currently loaded files."""` →
  ```python
        """読み込み済み全ファイルの **グループキー** (KEY_SEPARATOR の左側)。

        E-4b: 旧 docstring の "keys (paths)" は誤り。ここが返すのは
        `Session.load` が採番したグループキー ("mf4_1" 等) で、ファイルパスでは
        ない。エクスポートツリーのファイル行はこの順で並び、その順が出力列順の
        第 1 キーになる (spec §10) ので、パスと読み違えると列順の議論がずれる。
        """
  ```
- `main_window.py:644` の `export_csv_dialog.py:114` という行番号参照を
  `ExportCsvDialog._build_tree` という記号参照へ差し替える（行番号は本増分で動く）。

**(d) 移行表の mechanical follow を実行する（Step 1 の表 #3-#13）**

各サイトに 1 行の supersede コメントを置く。文例（`test_export_container_guard.py:144`）:

```python
    # E-4b Task 4 supersede: Session.export_csv の第 1 引数は **列キー** になった
    # (D1・spec §5.2 — Signal のリストは受けない)。期待 (ValueError と match の
    # "Mat[0]") は 1 文字も変えず、渡し方だけを機械的に付け替える。
```

Derived の 3 サイト（#5/#6/#7）は `extra_signals=` へ回す。文例:

```python
    # E-4b Task 4 supersede: Derived は SignalGroupManager に登録されず keys で
    # 解決できないので escape hatch (extra_signals) 経由になる (spec §5.2 [I-3])。
    # 出力バイトの期待は不変（ヘッダは Signal 自身の名前）。
```

```
uv run pytest tests/gui/test_export_csv_dialog.py tests/gui/test_main_window_export.py tests/core/test_export_container_guard.py tests/test_csv_export_options.py tests/test_session.py tests/test_export.py -q
```
Expected: **全部 passed**（`test_export.py` の Derived 5 本は **1 文字も編集せず** 緑）。

- [ ] **Step 5: ゴールデンを橋経由で byte 一致させる（MG-7 の実証）**

Task 2 の成果物は `tests/golden_csv_cases.py`（`GOLDEN_CASES` / `GOLDEN_DIR` / `build_options` / `export_case`）と `tests/golden_csv/g01..g11.csv` で確定済み。

`tests/core/test_export_bridge_golden.py` を Step 2 のスケルトンから完成させ:

```
uv run pytest tests/core/test_export_bridge_golden.py -q
```
Expected: Task 2 のケース数と同数 passed。**1 バイトでも違えば止める** — 差分が出たら
`cmp -l <golden> <out> | head` で最初の相違オフセットを出し、
「ヘッダ導出形 / passthrough / unit 行 / 範囲」のどれが動いたかを特定してから直す。
**ゴールデンの側は絶対に書き換えない**（spec G1）。

- [ ] **Step 6: sabotage で honest-RED を確認（必須）**

pristine copy:
```
cp src/valisync/core/session.py "$SCRATCH/session.py.orig"
cp src/valisync/core/export/legacy_bridge.py "$SCRATCH/legacy_bridge.py.orig"
cp src/valisync/gui/views/export_csv_dialog.py "$SCRATCH/export_csv_dialog.py.orig2"
```

対象コマンド:
```
uv run pytest tests/core/test_export_request_bridge.py tests/core/test_export_bridge_golden.py tests/gui/test_export_csv_dialog.py tests/gui/test_main_window_export.py tests/core/test_export_container_guard.py tests/test_export.py -q -rf
```

| # | 壊す箇所（正確な編集） | 予測 RED |
|---|---|---|
| S1 | `legacy_bridge` の `header = list(request.header_resolver(request.keys))` を `header = list(request.keys)` へ（resolver を無視） | `test_injected_header_resolver_drives_the_header_row` ＋ **ゴールデンの GUI 形ケース全部**。passthrough ゴールデンと `test_export_csv_writes_columns_in_key_order` は**緑のまま**（passthrough と同値）— この非対称が「resolver が実際に効いている」の証拠 |
| S2 | `Session._reject_container_channels` の本体を `return` 1 行へ | `test_session_rejects_container_channel_without_reading_values`（既存）/ `test_extra_signals_are_still_container_checked` の **2 件**。`CsvExporter` 直呼びの 6 本は最後の砦（`_require_single_value_columns`）で拾うので**緑のまま** |
| S3 | `legacy_bridge` の `signals = [*resolved, *request.extra_signals]` から `*request.extra_signals` を落とす | `test_extra_signals_carry_derived_signals_...` / `test_extra_signals_come_after_keys_in_column_order` / `test_use_unified_timeline_travels_through_options` / `test_empty_request_fails_loudly` は**緑のまま**（元から空）— 予測 RED は **3 件**、＋ mechanical follow した Derived 3 サイト（#5/#6/#7）も RED |
| S4 | `_on_accept` の `missing = [...]` ブロックを丸ごと削除 | `test_unresolvable_column_reports_instead_of_raising`（既存 `:862-883`）/ `test_accept_resolves_only_the_selected_columns`（既存 `:844-859`・`resolve_calls == 1` が 0 になる）の **2 件** |
| S5 | `legacy_bridge` の `request.options.use_unified_timeline` を `False` 固定へ | `test_use_unified_timeline_travels_through_options` ＋ **ゴールデンの統合タイムライン系ケース**。共有タイムラインのケースは**緑のまま** |
| S6 | `legacy_bridge` の header 長不一致ガード（3 行）を削除 | `test_header_resolver_length_mismatch_fails_loudly` の **1 件のみ** |
| S7 | `Session.export_csv` の `isinstance(options, bool)` ガードを削除 | `test_positional_bool_as_options_is_refused` の **1 件のみ** |
| S8 | `csv_header_resolver` をメソッド化して `self` を捕まえる形へ（`self._result = ExportRequest(..., header_resolver=lambda ks: ...)`） | **RED は 0 件になるはず** — これはテストで捕まえない設計判断（寿命の話は観測点が無い）。予測が「0 件」であることを実測で確認し、**予測を書き換えない**。0 件でなかったら発見として報告する |

**「橋の撤去が構造的に検証可能」の実測**（Task 7 への受け渡し）:
```
grep -rn "legacy_bridge\|export_via_legacy_path" src/
```
Expected: **`legacy_bridge.py` 自身 ＋ `session.py` の 2 箇所のみ**（import と呼び出し）。
3 箇所以上に散っていたら、Task 7 の撤去が「削除 1 ファイル ＋ 1 行差し替え」でなくなるので直す。

- [ ] **Step 7: ゲート＋コミット**

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

passed 数が **Task 3 完了時 + 12 + 2 + (ゴールデンのケース数)** になっていること。
凍結カタログの再確認（本タスクもウィジェットを足していない）:

```
uv run python scripts/capture_ui_screenshots.py --catalog --theme dark --out "$SCRATCH/shots_dark2"
uv run python scripts/compare_screenshots.py screenshots_catalog_dark "$SCRATCH/shots_dark2"
```
Expected: 全状態一致。

```
git add src/valisync/core/export/csv_exporter.py \
        src/valisync/core/export/legacy_bridge.py \
        src/valisync/core/export/__init__.py \
        src/valisync/core/session.py \
        src/valisync/gui/views/export_csv_dialog.py \
        src/valisync/gui/views/main_window.py \
        src/valisync/gui/viewmodels/app_viewmodel.py \
        tests/core/test_export_request_bridge.py \
        tests/core/test_export_bridge_golden.py \
        tests/gui/test_export_worker_compat.py \
        tests/core/test_export_container_guard.py \
        tests/test_csv_export_options.py \
        tests/test_session.py \
        tests/gui/test_main_window_export.py \
        tests/gui/test_export_csv_dialog.py \
        tests/realgui/test_export_range_realclick.py
git commit -m "$(cat <<'EOF'
refactor(core): エクスポート境界を列キー＋ヘッダ解決器へ (E-4b Task 4・移行橋つき)

`ExportRequest` を core (csv_exporter) に新設し、`Session.export_csv` の第 1 引数を
Signal のリストから **名前空間つき列キー** へ替える (D1・spec §5.2)。prod
330,004 列を Signal で運ぶと出口に立つ前に ~390 MB を確定させてしまうため、
列はキーで運び実体化は書き手へ委ねる。

ヘッダは `header_resolver` (callable) で **同じ keys から** 導出する。旧形は
signals と `CsvExportOptions.header_names` を別々に運んでおり、header_names
指定時 (GUI 経路) の対応崩しを守るテストが 1 本も無かった (C1/M7 —
header_names=None の既存テスト 6 本は `signals.reverse()` を捕まえるが
header_names 指定時は無検出だった)。by construction に変えることが構造的な
根治になる。既定は passthrough
(`list(keys)`) で、直呼び経路 (テスト/scripted/realgui) の現行ヘッダバイトを
そのまま保存する。GUI は csv_header_names を束ねたモジュール関数を注入する
(core は gui を import しない・C-5)。resolver をクロージャでなくモジュール関数に
してあるのは、これが worker スレッドへ渡って export 全期間生きるため —
self を捕まえるとダイアログとツリー全部が道連れで残る。

Derived は SignalGroupManager に登録されず keys で解決できないので
`extra_signals` を escape hatch として設けた (spec §5.2 [I-3])。test_export.py の
Derived 5 本は 1 文字も編集せず緑のまま。escape hatch がコンテナ拒否の抜け道に
ならないよう、extra_signals の名前も `_reject_container_channels` へ流している。

`legacy_bridge.py` は **Task 7 が削除する移行橋**。keys を全解決して旧一括実装へ
渡すだけなので、この時点でメモリ挙動は改善しない — Task 4 の仕事は「境界が
動いても出力バイトが 1 バイトも動かない」ことを Task 2 のゴールデンで実証する
ことにある (MG-7)。独立ファイルにしたのは撤去が「ファイル削除 + 1 行差し替え」
という構造的に検証可能な操作になるから。

移行は実測 50 サイト / 11 ファイル (spec §5.2 の「48/7」は概算)。うち 38 は
bridge-transparent (編集ゼロ)、12 が mechanical follow — 後者は **期待値と文言を
1 つも変えず** 呼び出し形だけを付け替え、各サイトに supersede コメントを残した
(BOM 読み口 26 本と同じ扱い)。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 3/4 から後続タスクへの引き継ぎ（明示）

| 宛先 | 内容 |
|---|---|
| Task 6 | `_on_accept` の解決可能性検証は今 `session.resolve_signal` を呼ぶ（E-4a LRU に載る）。`resolve_transient` が入ったらここを差し替える — 帳簿に載せない検証にできる。差し替え点は `export_csv_dialog._on_accept` の 1 行と `session.export_csv` の `export_via_legacy_path(request, self.resolve_signal)` の 1 行 |
| Task 7 | (1) `legacy_bridge.py` を**ファイルごと削除**し `session.export_csv` の 1 行を `self._exporter.export(request, self.resolve_signal_transient, ...)` へ。(2) `CsvExporter.export` の旧署名撤去は `CsvExporter().export(signals, ...)` 直呼び **36 サイト**（`test_csv_export_options.py` 24 / `test_export_container_guard.py` 6 / `test_export.py` 5 / `test_pbt_csv.py` 1）を動かす — 移行方針（`Session.export_csv` 経由へ寄せるか、`extra_signals` で包むか）を Task 7 の plan で確定し supersede 記録を残すこと。(3) `CsvExportOptions.header_names` の撤去は `test_csv_export_options.py:161` を動かす — 同上 |
| Task 8/9 | `ExportController.submit` は Task 4 で**変えていない**。progress/cancel の追加時は `tests/gui/test_export_worker_compat.py` の 2 本（第 1 引数の位置・worker 保持）が受け入れ条件 |
| Task 11 | `tests/realgui/test_export_flow.py` の Layer C 実行が本作業中に real display 不在で skip された場合、①ゲートで必ず実走させる |

### 解決した曖昧さ（spec / 共有契約と実コードの突き合わせで判断した点）

1. **`ExportController.submit` の「後方互換に拡張」（spec §5.2）** — T-API では**拡張が要らない**。境界の変更は `submit` に渡す callable の中身にしか現れず、`Callable[[], None]` のままで新経路が通る。実際に必要になるのは進捗/ETA/協調キャンセル（spec §5.5 = T-UX / Task 8/9）。**投機的な引数を先に足さない**代わりに、後方互換の**pin テスト**（`test_export_worker_compat.py`）を Task 4 で置き、Task 8/9 の受け入れ条件にした。
2. **`CsvExportOptions.header_names` の扱い（MG-7 は「別持ちを廃止」と書く）** — Task 4 で削除すると `test_csv_export_options.py:161` の期待が動く＝Global Constraints 違反。Task 4 では**残し**、橋が resolver の結果を詰める搬送路として使う（ヘッダバイトはこれで保存される）。撤去は Task 7 へ引き継ぎ（supersede 記録つき）。
3. **`use_unified_timeline` の二重化** — 共有契約は「options 経由」を明示するので `CsvExportOptions` に末尾フィールドを追加。ただし旧 `CsvExporter.export(..., use_unified_timeline=...)` は 36 サイトが直呼びしているので Task 4 では据え置き、橋が options → 旧引数へ写す。二重の真実になる窓は Task 4〜6 の間だけで、Task 7 の署名差し替えで閉じる。第 3 位置引数の意味が bool → options に変わるため、`isinstance(options, bool)` の loud-fail ガードを足した。
4. **`_selected` のキー空間（spec §5.6 [M-6] は「namespaced 物理チャンネルキー」）** — `row_index`（int）の方がさらに小さいが、spec/brief の指定どおり**名前空間つきキー**を採用した。代わりにキー文字列を `_ChannelRow.sel_key` に 1 度だけ作って dict キーと共有し（毎アクセスの f-string 生成をゼロにし）、同じ文字列で `_row_by_sel_key`（列キー → 行の最長一致索引）を張ってオフセットガードの反転にも再利用している。
5. **オフセットガード反転の DI（`offset_for` は値しか答えない）** — 反転には「今オフセットを持つキーの列挙」が要るので `offset_keys: Callable[[], Iterable[str]] | None` を**追加**（既存 `offset_for` は値オラクルとして残し、相殺して 0 のキーを弾く役に立つ）。`offset_keys` 未注入の呼び出し側（撮影ツール・既存 I2 テスト 6 本）は旧方式を legacy 経路として保存し、両経路の同値を parametrize で直接突き合わせた。**既存 6 本を編集せずに反転を入れる唯一の形**。
6. **accept 時の解決可能性検証（spec §5.2 は必須と書くが、330k 列で全 resolve は C-b と衝突する）** — `resolve_signal` の結果を**保持しない**形（`missing` の bool 判定のみ）にした。E-4a の LRU（容量 512）で同時生存が頭打ちになるので、旧実装の「list[Signal] を要求に載せる ~390 MB」は消え、時間コストだけが現状どおり残る。この時間は Task 8 の見積/確認ダイアログが前面化し、Task 6 で `resolve_transient` に差し替わる。
7. **`extra_signals` の列位置** — 共有契約は順序を規定していない。**keys → extra_signals の末尾連結**に固定した（GUI ツリーは `loaded_file_keys` しか列挙しないので今日 Derived は選択に入らず、後で載せたときに実装依存で決まるのを防ぐ）。テストで pin 済み。
8. **`ExportRequest` の同名衝突（GUI に既存の同名 dataclass がある）** — GUI 側を削除し core のものを**再輸出**する。`from ...export_csv_dialog import ExportRequest` と `isinstance(req, ExportRequest)` を使う既存 3 サイトが**無編集で生存**する（mechanical follow を 3 サイト減らせる）。
9. **spec §5.2 の「48 サイト / 7 ファイル」** — grep 実測は **50 サイト / 11 ファイル**。spec の数は概算として扱い、移行表は実測で作る（Step 1 に差分の記録を義務づけた）。
### Task 5: union モジュール（純関数）＋ `csv_loader` の master read-only 化

**Files:**
- Create: `src/valisync/core/export/timeline.py`（新規・純 numpy・`Signal` も `Session` も import しない）
- Modify: `src/valisync/core/loaders/csv_loader.py:234`（`timestamps` を read-only 化する 1 行を追加。`mdf_loader.py:432` の `master.flags.writeable = False` と同型）
- Test: `tests/core/export/test_timeline.py`（新規）
- Test: `tests/core/loaders/test_csv_master_sharing.py`（新規）
- **触らない**: `csv_exporter.py`（本タスクは exporter を 1 バイトも変えない＝挙動不変。配線は Task 6/7）

**Interfaces:**
- Consumes: なし（`numpy` のみ）。既存の `Signal.sorted_view()` / `Signal.__init__`（`models/signal.py:80-84`）は**テストのオラクルとして**参照するだけで、production 依存は作らない。
- Produces（Task 6/7/8 がこれに対して書く・シグネチャ厳守）:
  - `union_timeline(masters: Sequence[np.ndarray]) -> np.ndarray` — identity dedup ＋ `np.unique(np.concatenate(...))`。昇順・重複なし・**read-only**。空入力は長さ 0 の float64。
  - `canonical_master(master: np.ndarray) -> np.ndarray` — `Signal.sorted_view()[0]` と同一内容の時刻軸を**値を読まずに**得る。単調なら**同一オブジェクトを返す**（union の identity dedup が効き続ける前提条件）。
  - `column_on_union(sig_ts, sig_vals, union_ts) -> tuple[np.ndarray, np.ndarray]` — `(値, 存在フラグ)`。完全一致セマンティクス（tolerance 禁止）。len 0 信号で IndexError にならない。
  - `row_range(union_ts, time_start: float | None, time_end: float | None) -> tuple[int, int]` — 閉区間 `[time_start, time_end]` を覆う `[lo, hi)`。lo=`side='left'` / hi=`side='right'`（M-3）。
  - `hit_mask(sig_ts: np.ndarray, union_ts: np.ndarray) -> np.ndarray` — bool・長さ `len(union_ts)`・**完全一致**（tolerance 禁止）・**値を読まない**（`sig_vals` を受け取らない）。**存在判定の実装は 1 本だけ**（`hit_mask` と `column_on_union` の存在フラグが private `_align` を共有する — 2 つ持つと見積の空セル率と出力の空セルがずれる）。`sig_ts` は **`canonical_master` 済み**を渡す契約（生 master を渡すと `side='left'` が重複ランの先頭に当たり keep-last が崩れる）。
- 本タスクが固定する契約（docstring に書く）:
  - dedup は **`id()` のみ**。`np.array_equal` で畳むと ULP 差の行が黙って畳まれる（C3）。
  - union に NaN が入らないのは `Signal.__init__`（`signal.py:80-82`）の非有限時刻拒否**への依存**。依存が外れたら union が壊れる。
  - `column_on_union` の `sig_ts` は **`sorted_view()[0]`（昇順・重複なし）**であること。生 master（重複つき）を渡すと `side='left'` が先頭に当たり keep-last が崩れる。

**この 2 つの変更が対である理由（`csv_loader` を Task 5 に同梱する根拠）**: `csv_loader` は writeable な `timestamps` を渡すため `Signal.__init__`（`signal.py:83`）が**信号ごとにコピー**する。つまり CSV グループでは master オブジェクトが列数ぶん存在し、`union_timeline` の identity dedup が**構造的に 1 件も効かない**（spec §5.4 [I-9]）。union の正しさは変わらないが、dedup の受け入れテストを CSV で書くと恒真になる。read-only 化してはじめて「CSV でも 1 グループ = master 1 個」になる。

---

- [ ] **Step 1: 失敗テストを書く**

まず**ベースラインを記録する**（Step 6 の「挙動不変」を主張でなく実測で示すため）:

```
uv run pytest -q
```
→ 出た `N passed, M skipped` を控える。Step 6 で `N + 26 passed` になることを確認する。

`tests/core/export/test_timeline.py` を新規作成:

```python
"""union 合成と列引き当ての純関数 (E-4b Task 5・spec §5.4)。

**demo_data に依存しない**: 判定はすべて合成 ndarray と手組み Signal で踏める。
本モジュールの時点で production 配線は 0 件 (Task 6/7 が配線する) なので、
ここが唯一の執行点であり、緑であることが「実装が効いている」の唯一の根拠になる。
"""

from __future__ import annotations

import numpy as np

from valisync.core.export.csv_exporter import CsvExportOptions, _in_range
from valisync.core.export.timeline import (
    canonical_master,
    column_on_union,
    hit_mask,
    row_range,
    union_timeline,
)
from valisync.core.models import Signal


def _sig(name: str, ts: list[float], vs: list[float]) -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="test",
        bus_type="",
        source_file="",
    )


# ─── union: identity dedup (spec §5.4) ────────────────────────────────────────


def test_union_dedups_the_same_master_object(monkeypatch) -> None:
    """prod 形: 1 つの master オブジェクトを全列が共有する (loader が同一物を渡す)。

    **下界オラクル** [I11]: 結果だけを見ると dedup 有無で同じ配列になるので、
    dedup を消しても値ベースの assert は緑のまま通る。concat の**入力要素数**を
    直接観測して「畳んだこと」を性能側で pin する。
    """
    master = np.arange(1000, dtype=np.float64)
    concat_sizes: list[int] = []
    real = np.concatenate

    def spy(arrays, *args, **kwargs):  # type: ignore[no-untyped-def]
        concat_sizes.append(sum(len(a) for a in arrays))
        return real(arrays, *args, **kwargs)

    monkeypatch.setattr(np, "concatenate", spy)

    out = union_timeline([master] * 64)

    assert concat_sizes == [1000], "dedup が効いていない (64 本ぶん concat した)"
    assert np.array_equal(out, master)


def test_union_of_distinct_objects_with_equal_values_is_correct_but_not_deduped(
    monkeypatch,
) -> None:
    """安全側の逸脱: identity dedup は「別オブジェクト・同値」を畳まない。

    畳まれないのは**コストだけ**で、結果は正しい。ここを値比較 (array_equal) に
    「改善」すると ULP 差の行が黙って畳まれ、時刻がずれる (C3)。
    """
    a = np.arange(1000, dtype=np.float64)
    b = np.arange(1000, dtype=np.float64)  # 同値・別オブジェクト
    assert a is not b
    concat_sizes: list[int] = []
    real = np.concatenate

    def spy(arrays, *args, **kwargs):  # type: ignore[no-untyped-def]
        concat_sizes.append(sum(len(x) for x in arrays))
        return real(arrays, *args, **kwargs)

    monkeypatch.setattr(np, "concatenate", spy)

    out = union_timeline([a, b])

    assert concat_sizes == [2000]  # 畳まれない (identity が違う)
    assert np.array_equal(out, a)  # 正しさは保たれる


def test_union_is_sorted_unique_across_multi_rate_masters() -> None:
    slow = np.array([0.0, 2.0, 4.0])
    fast = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    out = union_timeline([slow, fast])
    assert out.tolist() == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_union_of_no_masters_is_empty_not_valueerror() -> None:
    """空選択 (列 0 本)。np.concatenate([]) は ValueError なので先に返す。"""
    out = union_timeline([])
    assert out.shape == (0,)
    assert out.dtype == np.float64


def test_union_result_is_read_only() -> None:
    out = union_timeline([np.arange(3, dtype=np.float64)])
    assert out.flags.writeable is False


def test_union_from_raw_masters_equals_union_from_sorted_views() -> None:
    """**Task 7 の等価性の要**: union を生 master から作ってよい根拠。

    旧実装は ``sorted_view()`` の時刻軸から union を作っていた (= 全列の値を
    実体化してから union を出す)。生 master から作れないと、見積 (T-UX) の
    「値を読まない」契約も、ブロック開始前の union 確定も成り立たない。
    非単調・重複 ts を含む形で**同値であること**をここで pin する。
    """
    a = _sig("a", [0.0, 2.0, 1.0], [10.0, 30.0, 20.0])  # 非単調
    b = _sig("b", [1.0, 1.0, 3.0], [1.0, 2.0, 3.0])  # 重複 ts
    from_raw = union_timeline([a.timestamps, b.timestamps])
    from_views = np.unique(np.concatenate([a.sorted_view()[0], b.sorted_view()[0]]))
    assert np.array_equal(from_raw, from_views)


# ─── canonical_master ─────────────────────────────────────────────────────────


def test_canonical_master_returns_the_same_object_when_monotonic() -> None:
    """同一オブジェクトを返すこと自体が契約 (identity dedup の前提条件)。"""
    m = np.arange(5, dtype=np.float64)
    assert canonical_master(m) is m


def test_canonical_master_matches_sorted_view_ts_for_non_monotonic_and_dups() -> None:
    s = _sig("x", [0.0, 2.0, 1.0, 1.0], [10.0, 30.0, 20.0, 21.0])
    assert np.array_equal(canonical_master(s.timestamps), s.sorted_view()[0])


# ─── column_on_union: 完全一致セマンティクス ──────────────────────────────────


def test_column_on_union_matches_only_exact_timestamps() -> None:
    """既存 test-lock ``"1.0,,21.0"`` (test_csv_export_options.py:284) と同じ形。"""
    union = np.array([0.0, 1.0, 2.0, 3.0])
    a_ts, a_vs = np.array([0.0, 2.0]), np.array([10.0, 12.0])
    b_ts, b_vs = np.array([1.0, 3.0]), np.array([21.0, 23.0])

    a_vals, a_present = column_on_union(a_ts, a_vs, union)
    b_vals, b_present = column_on_union(b_ts, b_vs, union)

    assert a_present.tolist() == [True, False, True, False]
    assert b_present.tolist() == [False, True, False, True]
    assert a_vals[0] == 10.0 and a_vals[2] == 12.0
    assert b_vals[1] == 21.0 and b_vals[3] == 23.0


def test_column_on_union_tail_overrun_is_absent_not_indexerror() -> None:
    """union の末尾が信号の末尾より後 (既存 test-lock "2.0,3.0," の形)。

    素朴な ``sig_ts[idx]`` は ``idx == len(sig_ts)`` で IndexError。
    """
    union = np.array([0.0, 1.0, 2.0])
    vals, present = column_on_union(np.array([0.0, 1.0]), np.array([4.0, 5.0]), union)
    assert present.tolist() == [True, True, False]
    assert vals[0] == 4.0 and vals[1] == 5.0


def test_column_on_union_head_underrun_is_absent() -> None:
    """union の先頭が信号の先頭より前 (clip の下側・idx == 0 の腕)。"""
    union = np.array([0.0, 5.0])
    _vals, present = column_on_union(np.array([5.0]), np.array([1.0]), union)
    assert present.tolist() == [False, True]


def test_column_on_union_of_zero_length_signal_is_all_absent() -> None:
    """LD-09 (ヘッダのみ CSV = データ行 0)。素朴実装は IndexError [M-4]。"""
    union = np.array([0.0, 1.0, 2.0])
    vals, present = column_on_union(
        np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64), union
    )
    assert present.tolist() == [False, False, False]
    assert len(vals) == 3  # 行数は union に揃う (下流の索引が壊れない)


def test_column_on_union_of_empty_union_is_empty() -> None:
    vals, present = column_on_union(np.array([0.0]), np.array([1.0]), np.empty(0))
    assert len(vals) == 0 and len(present) == 0


def test_column_on_union_outputs_are_read_only() -> None:
    vals, present = column_on_union(
        np.array([0.0]), np.array([1.0]), np.array([0.0, 1.0])
    )
    assert vals.flags.writeable is False
    assert present.flags.writeable is False


def test_column_on_union_ulp_split_rows(  # noqa: RUF001
) -> None:
    """ULP 分裂 (spec §1・C-1 で既知の不完全性として受容)。

    100 ms 刻みと 10 ms 刻みは「同じ 0.3 秒」を別のビット列で作る:
    ``3*0.1 == 0.30000000000000004`` / ``30*0.01 == 0.3``。tolerance を入れない
    限り union は分裂する。**分裂の行数まで凍結する** — 「union が 120 行に
    なった」ら誰かが tolerance を入れたということ。
    """
    slow_ts = np.array([i * 0.1 for i in range(12)], dtype=np.float64)
    fast_ts = np.array([i * 0.01 for i in range(120)], dtype=np.float64)
    union = union_timeline([slow_ts, fast_ts])

    assert len(union) == 122  # 120 ではない (2 点が ULP で分裂している)

    _sv, slow_present = column_on_union(slow_ts, slow_ts.copy(), union)
    _fv, fast_present = column_on_union(fast_ts, fast_ts.copy(), union)
    assert int(slow_present.sum()) == 12
    assert int(fast_present.sum()) == 120
    assert int((slow_present & fast_present).sum()) == 10  # 一致するのは 10 点だけ
    assert int((~slow_present & ~fast_present).sum()) == 0  # 全空の行は無い
    split = [t for t, p in zip(union.tolist(), fast_present.tolist()) if not p]
    assert split == [0.30000000000000004, 0.6000000000000001]


# ─── hit_mask: 見積と出力が同じ存在判定を共有する ─────────────────────────────


def test_hit_mask_agrees_with_column_on_union_presence() -> None:
    """**T-UX (見積) と書き手が同じ答えを出す**ことの pin。

    ずれると B2 が提示する空セル率が「正確値」でなくなる (見積は 2 割空だと
    言い、出力は 6 割空、という形の嘘)。存在判定の実装が 2 つに割れたときの
    唯一の検出点なので、境界 (先頭 underrun・末尾 overrun・len 0) を全部通す。
    """
    union = np.array([0.0, 1.0, 2.0, 3.0])
    for sig_ts in (
        np.array([0.0, 2.0]),
        np.array([1.0, 3.0]),
        np.array([5.0]),  # 全部範囲外
        np.empty(0, dtype=np.float64),  # len 0 (LD-09)
    ):
        vals = np.arange(len(sig_ts), dtype=np.float64)
        _v, present = column_on_union(sig_ts, vals, union)
        assert hit_mask(sig_ts, union).tolist() == present.tolist(), sig_ts


def test_hit_mask_is_read_only_and_matches_union_length() -> None:
    mask = hit_mask(np.array([0.0]), np.array([0.0, 1.0, 2.0]))
    assert mask.tolist() == [True, False, False]
    assert mask.flags.writeable is False


# ─── row_range: 閉区間の保存 (M-3) ────────────────────────────────────────────


def test_row_range_includes_both_endpoints() -> None:
    union = np.array([0.0, 1.0, 2.0, 3.0])
    assert row_range(union, 1.0, 2.0) == (1, 3)


def test_row_range_unbounded_sides() -> None:
    union = np.array([0.0, 1.0, 2.0])
    assert row_range(union, None, None) == (0, 3)
    assert row_range(union, 1.0, None) == (1, 3)
    assert row_range(union, None, 1.0) == (0, 2)


def test_row_range_outside_the_data_is_empty() -> None:
    union = np.array([0.0, 1.0])
    lo, hi = row_range(union, 5.0, 6.0)
    assert lo == hi  # 行 0 本 (ヘッダのみのファイルになる)


def test_row_range_agrees_with_in_range_row_by_row() -> None:
    """``_in_range`` (行ごとの比較) と**同じ行集合**であることの独立オラクル。

    sides を取り違えると両端が 1 行ずつ欠ける — 値ベースの assert では
    「境界にサンプルが無い」fixture で緑のまま通るので、境界に必ずサンプルが
    在る格子で全パターンを突き合わせる。
    """
    union = np.arange(0.0, 10.0, 1.0)
    for start in (None, 0.0, 2.0, 9.0, 9.5):
        for end in (None, 0.0, 2.0, 9.0, 9.5):
            if start is not None and end is not None and start > end:
                continue
            opts = CsvExportOptions(time_start=start, time_end=end)
            expected = [i for i, t in enumerate(union.tolist()) if _in_range(t, opts)]
            lo, hi = row_range(union, start, end)
            assert list(range(lo, hi)) == expected, (start, end)
```

`tests/core/loaders/test_csv_master_sharing.py` を新規作成:

```python
"""CSV グループの master が列間で共有されること (E-4b Task 5・spec §5.4 [I-9])。

``csv_loader`` が writeable な timestamps を渡していた間、``Signal.__init__``
(signal.py:83) は信号ごとに master をコピーしていた。結果、CSV では
``union_timeline`` の identity dedup が**構造的に 1 件も効かない** (畳めるはずの
n_signals 本がそのまま concat される)。read-only 化が dedup の前提条件。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from valisync.core.export.timeline import union_timeline
from valisync.core.loaders.csv_loader import CsvLoader
from valisync.core.models import Delimiter, FormatDefinition


def _fmt(**overrides: object) -> FormatDefinition:
    base: dict[str, object] = {
        "name": "test",
        "delimiter": Delimiter.COMMA,
        "timestamp_column": 0,
        "timestamp_unit": "sec",
        "signal_start_column": 1,
        "signal_end_column": 3,
        "has_header": True,
        "has_unit_row": False,
    }
    base.update(overrides)
    return FormatDefinition(**base)  # type: ignore[arg-type]


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "data.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_csv_group_signals_share_one_master_object(tmp_path: Path) -> None:
    path = _write(tmp_path, "t,a,b,c\n0.0,1,2,3\n1.0,4,5,6\n")
    group = CsvLoader().load(path, _fmt()).signal_group
    assert group is not None
    masters = [s.timestamps for s in group.signals]
    assert len(masters) == 3
    assert all(m is masters[0] for m in masters), "列ごとに master がコピーされている"


def test_csv_master_is_read_only(tmp_path: Path) -> None:
    """共有の実装手段そのものを pin する (writeable なら __init__ がコピーする)。"""
    path = _write(tmp_path, "t,a,b,c\n0.0,1,2,3\n")
    group = CsvLoader().load(path, _fmt()).signal_group
    assert group is not None
    assert group.signals[0].timestamps.flags.writeable is False


def test_csv_master_sharing_makes_union_dedup_effective(
    tmp_path: Path, monkeypatch
) -> None:
    """loader の 1 行と union の dedup を繋ぐ紐 (どちらが欠けても RED)。"""
    path = _write(tmp_path, "t,a,b,c\n0.0,1,2,3\n1.0,4,5,6\n2.0,7,8,9\n")
    group = CsvLoader().load(path, _fmt()).signal_group
    assert group is not None

    sizes: list[int] = []
    real = np.concatenate

    def spy(arrays, *args, **kwargs):  # type: ignore[no-untyped-def]
        sizes.append(sum(len(a) for a in arrays))
        return real(arrays, *args, **kwargs)

    monkeypatch.setattr(np, "concatenate", spy)
    union_timeline([s.timestamps for s in group.signals])
    assert sizes == [3], "3 列ぶん (9 要素) concat している = master が共有されていない"


def test_csv_header_only_file_still_loads_with_read_only_master(
    tmp_path: Path,
) -> None:
    """LD-09 (データ行 0)。長さ 0 配列でも flags 操作が通ることの pin。"""
    path = _write(tmp_path, "t,a,b,c\n")
    result = CsvLoader().load(path, _fmt())
    assert result.signal_group is not None
    assert len(result.signal_group.signals[0].timestamps) == 0
    assert result.signal_group.signals[0].timestamps.flags.writeable is False
```

- [ ] **Step 2: 失敗を確認**

```
uv run pytest tests/core/export/test_timeline.py tests/core/loaders/test_csv_master_sharing.py -q
```
Expected: **両ファイルとも `valisync.core.export.timeline` が存在しないので collection error**（`test_csv_master_sharing.py` も冒頭で `from valisync.core.export.timeline import union_timeline` するため、個々のテストは 1 本も実行されない）。

`timeline.py` だけを先に入れて `csv_loader` の read-only 化がまだの状態（＝ import は通る）で走らせた場合は、`test_csv_master_sharing.py` の **4 本すべてが RED**（`share_one_master` / `read_only` / `dedup_effective` に加え、`header_only` も `writeable is False` の行で落ちる）。**「4 本中 3 本」ではない**。

- [ ] **Step 3: 実装**

`src/valisync/core/export/timeline.py` を新規作成:

```python
"""統合タイムライン (union) の合成と列の引き当て (E-4b spec §5.4)。

**純関数のみ**: ``Signal`` も ``Session`` も import しない。ここが触るのは numpy
配列だけで、値の実体化 (``sorted_view()`` / ``.values``) を誘発する経路を 1 本も
持たない — 見積 (T-UX) が「値を読まない」契約を守れるのは、行数と空セル率が
このモジュールだけで出るからである。

**union に NaN が入らないのは ``Signal.__init__`` (models/signal.py:80-82) の
非有限時刻拒否への依存**。あの拒否が緩むと ``np.unique`` は NaN を畳めず
(NaN != NaN)、末尾に NaN 行が並んで「ほぼ全列が空」の行が黙って増える。
依存を切るときは、tolerance ではない明示的な非有限除去をここへ入れること。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def union_timeline(masters: Sequence[np.ndarray]) -> np.ndarray:
    """*masters* の和集合 (昇順・重複なし・read-only)。

    **dedup は ``id()`` (identity) であって値比較ではない** (spec §5.4)。
    ``np.array_equal`` で畳むと ULP 差 (``3*0.1 == 0.30000000000000004`` と
    ``30*0.01 == 0.3``) の行が黙って畳まれ、時刻が静かにずれる (C3)。identity だけ
    だと「別オブジェクト・同値」の master で dedup が効かないが、**効かないのは
    コストだけで正しさは保たれる** — 安全側に倒す。

    prod で効くのは、ローダーが仮想グループごとに master を 1 本読んで全 Signal へ
    **同一オブジェクトのまま**渡すから (``mdf_loader``・``_mint_column`` は
    ``parent.timestamps`` をそのまま渡す)。330,004 列に対し master オブジェクトは
    5 個で、1.352e9 要素の concat が 25,680 要素 (205 KB) になる。
    **5 個は生成デモの人工事実** — 実 CANape の独立ラスタでは O(10^2-10^3) になり
    うる (spec §9-9)。

    入力は生の ``Signal.timestamps`` でよい (``sorted_view()[0]`` を要求しない):
    ``np.unique`` が昇順・一意へ畳むので、非単調/重複 ts があっても結果は
    ``sorted_view`` 由来の union と一致する (test-lock:
    ``test_union_from_raw_masters_equals_union_from_sorted_views``)。
    """
    seen: set[int] = set()
    uniques: list[np.ndarray] = []
    for master in masters:
        if id(master) in seen:
            continue
        seen.add(id(master))
        uniques.append(master)
    if not uniques:
        # 空選択 (列 0 本)。np.concatenate([]) は ValueError なのでここで返す。
        empty = np.empty(0, dtype=np.float64)
        empty.flags.writeable = False
        return empty
    union = np.unique(np.concatenate(uniques))
    # 下流 (ブロック writer・マージ器) は行範囲のスライスを共有するだけで、
    # 誰も書き換えてよくない。凍結すると in-place 変形が loud-fail になる。
    union.flags.writeable = False
    return union


def canonical_master(master: np.ndarray) -> np.ndarray:
    """``Signal.sorted_view()[0]`` と同一内容の時刻軸を **値を読まずに** 返す。

    ``sorted_view`` は安定ソート + 同値 ts の keep-last で「昇順・重複なし」を
    作る。**時刻軸だけを見れば** 結果は ``np.unique`` と一致する (どちらも昇順・
    一意)。共有タイムライン前提の検証 (spec §5.2 MG-6・master のみで判定し値を
    読まない) はこれで足りる。

    単調な master は ``sorted_view`` が元配列をそのまま返すので、ここも
    **同一オブジェクト**を返す — ``union_timeline`` の identity dedup が
    canonical 化の後でも効き続けるための前提条件。
    """
    if len(master) < 2 or bool(np.all(np.diff(master) > 0)):
        return master
    return np.unique(master)


def _align(sig_ts: np.ndarray, union_ts: np.ndarray) -> tuple[np.ndarray | None, np.ndarray]:
    """``(索引, 存在フラグ)`` — **存在判定の唯一の実装**。

    ``hit_mask`` (見積が使う) と ``column_on_union`` (書き手が使う) がここを共有する。
    2 つ持つと「見積が数えた非空セル数」と「出力に実際に出る値」がずれ、B2 が
    提示する空セル率が嘘になる。索引が ``None`` = len 0 の信号 (全行 absent)。
    """
    n_rows = len(union_ts)
    if len(sig_ts) == 0:
        # len 0 の信号 (LD-09 のヘッダのみ CSV)。素朴な sig_ts[idx] は idx == 0 でも
        # IndexError になる (空配列には 0 番目も無い) ので、構造的に断つ [M-4]。
        return None, np.zeros(n_rows, dtype=bool)
    idx = np.searchsorted(sig_ts, union_ts, side="left")
    # 末尾越え (union の最後が信号の最後より後) は idx == len(sig_ts) になり、
    # そのままでは IndexError。clip してから **値の一致で** 判定する: clip 先の
    # 要素は union_ts と一致しないので present は False に落ちる (先頭側の
    # underrun も同じ理屈で False)。
    np.clip(idx, 0, len(sig_ts) - 1, out=idx)
    return idx, sig_ts[idx] == union_ts


def hit_mask(sig_ts: np.ndarray, union_ts: np.ndarray) -> np.ndarray:
    """*union_ts* の各行に *sig_ts* のサンプルが**在るか** (bool・長さ len(union_ts))。

    **値を読まない** — 引数に値配列を取らないのが契約そのもの。見積 (T-UX) が
    空セル率を「推定」でなく「正確値」として出せるのは、この関数が master だけで
    答えるから。**完全一致セマンティクス** (tolerance 禁止・spec §5.4)。

    *sig_ts* は ``canonical_master`` 済み (昇順・重複なし) を渡すこと。重複を含む
    生 master を渡すと ``side='left'`` が重複ランの**先頭**に当たり、``sorted_view``
    の keep-last (CAN の「最後に受けた値が勝つ」) と食い違う。
    """
    _idx, present = _align(sig_ts, union_ts)
    present.flags.writeable = False
    return present


def column_on_union(
    sig_ts: np.ndarray, sig_vals: np.ndarray, union_ts: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """*union_ts* の各行に対する ``(値, 存在フラグ)`` を searchsorted で引き当てる。

    **完全一致セマンティクス** (親 spec §6 確定・tolerance 禁止): 値が出るのは
    ``sig_ts`` にその時刻が**ビット一致**で在る行だけで、無ければ空セル。旧実装の
    ``dict(zip(ts.tolist(), vs.tolist()))`` と判定は同じ (Python float の
    ハッシュ一致 == float64 の ``==``) で、実測 97 B/サンプル -> 8 B/サンプルになる。

    前提: *sig_ts* は ``Signal.sorted_view()[0]`` (昇順・重複なし)・*union_ts* は
    昇順。重複を含む生 master を渡すと ``side='left'`` が重複ランの**先頭**に当たり、
    ``sorted_view`` の keep-last (CAN の「最後に受けた値が勝つ」) が崩れる。

    返す値は行数が必ず ``len(union_ts)`` に揃う (存在しない行の値は未定義・
    呼び出し側はフラグを見てから読むこと)。

    存在フラグは ``hit_mask`` と**同一の内部実装** (``_align``) から来る。
    ``hit_mask`` を呼び直さないのは、prod (union 12,012 行 x 330,004 列) で
    searchsorted が二重に走るのを避けるため — 共有しているのは実装であって
    呼び出しではない、という点だけが逸脱で、「存在判定は 1 実装」の契約は保たれる。
    """
    idx, present = _align(sig_ts, union_ts)
    vals = np.zeros(len(union_ts), dtype=np.float64) if idx is None else sig_vals[idx]
    vals.flags.writeable = False
    present.flags.writeable = False
    return vals, present


def row_range(
    union_ts: np.ndarray, time_start: float | None, time_end: float | None
) -> tuple[int, int]:
    """閉区間 ``[time_start, time_end]`` を覆う行範囲 ``[lo, hi)`` (None は無制限)。

    行ごとの ``_in_range`` 比較と**同じ行集合**を searchsorted 1 回で出す。sides は
    閉区間の保存則そのもの (spec M-3): lo は ``side='left'`` で time_start に一致
    する行を**含み**、hi は ``side='right'`` で time_end に一致する行を**含む**。
    取り違えると両端が 1 行ずつ欠ける (境界にサンプルが無い fixture では緑のまま)。
    """
    lo = (
        0
        if time_start is None
        else int(np.searchsorted(union_ts, time_start, side="left"))
    )
    hi = (
        len(union_ts)
        if time_end is None
        else int(np.searchsorted(union_ts, time_end, side="right"))
    )
    # CsvExportOptions.__post_init__ が start > end を拒否するので通常は起きないが、
    # 直接呼びで空範囲になっても負の長さを返さない。
    return lo, max(lo, hi)
```

`src/valisync/core/loaders/csv_loader.py:234` の直後へ 1 行 + WHY コメントを追加:

```python
        timestamps = np.array(timestamps_list, dtype=np.float64)
        # read-only にすると Signal.__init__ (signal.py:83) がコピーせず**共有**する
        # ため、CSV グループでも「1 グループ = master 1 個」になる。writeable のままだと
        # 列ごとにコピーが生まれ、E-4b の union identity dedup が構造的に 1 件も効かない
        # (spec §5.4 [I-9])。mdf_loader.py:432 の master 凍結と同型。
        timestamps.flags.writeable = False
```

- [ ] **Step 4: 通ることを確認**

```
uv run pytest tests/core/export/test_timeline.py tests/core/loaders/test_csv_master_sharing.py -q
```
Expected: `26 passed`（timeline 22 ＋ csv master 4）

CSV の read-only 化が**既存テストを 1 本も壊していない**ことを確認する（`timestamps` を書き換えるテストが在れば ValueError になる）:

```
uv run pytest tests/test_loaders.py tests/test_pbt_csv.py tests/test_csv_format_detector.py -q
grep -rn "timestamps\[" tests/ --include=*.py
```
Expected: 前者は無回帰で pass、後者は**代入形（`... timestamps[i] = ...`）が 0 件**。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

**まず pristine copy を取る。`git checkout -- src/...` で戻してはならない**（過去に実装者が自分の未コミット作業を消している）:

```
cp src/valisync/core/export/timeline.py "$SCRATCH/timeline.py.orig"
cp src/valisync/core/loaders/csv_loader.py "$SCRATCH/csv_loader.py.orig"
```
（`$SCRATCH` = `C:/Users/trtrm/AppData/Local/Temp/claude/D--Programming-projects-valisync/<session>/scratchpad`）
各 sabotage 後は `.orig` から復元し、復元直後に `26 passed` へ戻ることを確認してから次へ進む。

**到達範囲は主張でなく実測で確かめる**: 各 sabotage で「予測 RED 集合」を先に書き、`-rf` の実際の failed 一覧と突き合わせる。一致しなければ**予測かテストのどちらかが誤り**なので、そのまま進めず原因を報告に書く。

| # | 壊す箇所（正確な編集） | 予測 RED |
|---|---|---|
| S1 | `union_timeline` の identity dedup を外す（`seen` 判定を削除し全 master を `uniques` へ）| `test_union_dedups_the_same_master_object`（concat 64,000）と `test_csv_master_sharing_makes_union_dedup_effective`（concat 9）の **2 件**。値ベースの assert は**全て緑のまま** — これが下界オラクルを置いた理由そのもの |
| S2 | dedup を `id()` から値比較へ（`any(np.array_equal(u, m) for u in uniques)`）| `test_union_of_distinct_objects_with_equal_values_is_correct_but_not_deduped` の **1 件のみ**（concat が 1000 になる）。**ULP テストは緑のまま** — 値比較でも `0.3 != 0.30000000000000004` は畳まれないため。「値比較でも安全」に見える罠なので、S2 の RED が 1 件だけであることまで含めて実測と一致させる |
| S3 | `column_on_union` の `np.clip` を削除 | `test_column_on_union_tail_overrun_is_absent_not_indexerror` / `test_column_on_union_ulp_split_rows` の **2 件**（IndexError）。`matches_only_exact_timestamps` は union 末尾が両信号の範囲内なので**緑のまま** |
| S4 | `column_on_union` の len 0 早期 return を削除 | `test_column_on_union_of_zero_length_signal_is_all_absent` の **1 件**（`len(sig_ts) - 1 == -1` で clip が壊れ IndexError） |
| S5 | `row_range` の hi を `side='left'` へ | `test_row_range_includes_both_endpoints` / `test_row_range_agrees_with_in_range_row_by_row` の **2 件**（終端の 1 行が欠ける） |
| S6 | `canonical_master` を常に `np.unique(master)` にする（単調でも新配列）| `test_canonical_master_returns_the_same_object_when_monotonic` の **1 件のみ**。値は全て一致するので他は緑 — identity を assert していなければ dedup 崩壊が無症状で通る形 |
| S7 | `csv_loader` の `flags.writeable = False` を削除 | `test_csv_group_signals_share_one_master_object` / `test_csv_master_is_read_only` / `test_csv_master_sharing_makes_union_dedup_effective` / `test_csv_header_only_file_still_loads_with_read_only_master` の **4 件** |

**「production 未配線」の実測**（本タスクが挙動不変であることの構造的証明・主張で済ませない）:

```
grep -rn "export.timeline\|union_timeline\|column_on_union\|canonical_master\|row_range" src/ scripts/ | grep -v "^src/valisync/core/export/timeline.py"
```
Expected: **0 件**。加えて S1 を当てた状態で `uv run pytest -q` を回し、failed が新規 2 ファイル内だけであることを確認する（`csv_loader` の 1 行だけは配線なので、S7 では既存テストの緑も確認する）。

- [ ] **Step 6: ゲート＋コミット**

sabotage をすべて復元した状態で:

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```
`uv run pytest -q` の passed 数が **Step 1 のベースライン + 26**（skip 数は不変）であること。

```
git add src/valisync/core/export/timeline.py src/valisync/core/loaders/csv_loader.py tests/core/export/test_timeline.py tests/core/loaders/test_csv_master_sharing.py
git commit -m "$(cat <<'EOF'
feat(core): union の identity dedup と searchsorted 引き当てを純関数で新設 (未配線)

E-4b §5.4 の土台。統合タイムラインの合成 (union_timeline)・sorted_view と同値の
時刻軸 (canonical_master)・列の引き当て (column_on_union)・閉区間の行範囲
(row_range) を numpy だけの純関数として先に作る (この時点では誰も import しない
ので挙動は完全に不変)。

dedup は id() のみ。np.array_equal で畳むと ULP 差 (3*0.1 と 30*0.01) の行が
黙って畳まれて時刻がずれる (C3)。identity だけだと「別オブジェクト・同値」で
効かないが、効かないのはコストだけで正しさは保たれる = 安全側。

引き当ては searchsorted + 完全一致マスク。旧 dict(zip(...tolist())) の実測
97 B/サンプルが 8 B/サンプルになる。末尾越え (clip) と len 0 信号 (LD-09) の
両方で IndexError にならないことを test-lock。row_range の sides は閉区間の
保存則そのもの (lo=left / hi=right) で、_in_range との行集合一致を独立オラクル
として固定した。

対で csv_loader の master を read-only 化する 1 行を入れる (mdf_loader.py:432 と
同型)。writeable のままだと Signal.__init__ が信号ごとに master をコピーし、
CSV グループでは identity dedup が構造的に 1 件も効かない ([I-9])。

テスト 26 本 (Qt 非依存・demo_data 非依存)。sabotage 実測: dedup 除去=2 RED
(値ベースの assert は全て緑のまま = 下界オラクルの存在理由)・値比較 dedup=1 RED・
clip 除去=2 RED・len0 腕除去=1 RED・hi の side 取り違え=2 RED・canonical の
identity 喪失=1 RED・csv 凍結除去=4 RED。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 6: export 専用 resolve ＋ 列ブロックパイプライン（temp 書きまで）

**Files:**
- Modify: `src/valisync/core/models/signal.py:27`（`__slots__` へ `"__weakref__"` を追加 — G2/G5 の weakref オラクルの前提条件。理由は下記）
- Modify: `src/valisync/core/loaders/signal_group_manager.py:308`（`resolved_keys` の直前へ `resolve_transient` を挿入）＋ `:82`（`transient_mint_count` の初期化）＋ `:540-568`（`_mint_column` の最長一致ループを共有ヘルパ `_owning_channel` へ抽出し、`channel_key_of(group_key, column_key)` として公開）
- Modify: `src/valisync/core/loaders/channel_cache.py:281`（`reserved` プロパティの直後へ `available_bytes` を追加）
- Modify: `src/valisync/core/session.py:299`（`resolve_signal` の直後へ `resolve_signal_transient` を追加）＋ `channel_key_of` の委譲
- Modify: `src/valisync/core/export/csv_exporter.py`（`ExportCancelled` / `MasterScan` / `scan_masters` / `block_columns` / `plan_blocks` / `CsvExporter.__init__` / `_write_time_temp` / `_write_block_temp` / `_require_single_value_column` を追加。**`export()` は 1 行も変えない**＝この時点でも Task 4 の橋がそのまま走る）。**実績注記（Task 6 完了・commit `b0e7278`）**: `CsvExporter.__init__` は本タスクで**入れていない**（意図的な繰越）— 入れると Task 2 の ratchet（`test_block_cols_handoff_is_not_forgotten`、下記 `BLOCK_COLS_VARIANTS` 拡幅の項）が「`export()` が 1 行も変わらない = block_cols を読まない」状態のまま満たされてしまい、空虚な緑になって以後の強制力を失う（実測記録あり）。`__init__` 追加と `BLOCK_COLS_VARIANTS` 拡幅は**同一コミット**で行うこと
- Test: `tests/core/loaders/test_resolver_transient.py`（新規）
- Test: `tests/core/export/test_block_writer.py`（新規）
- **触らない**: `tests/core/loaders/test_resolver.py`（D4 identity 契約の既存 test-lock。**無編集で緑**であることが本タスクの受け入れ条件）

**Interfaces:**
- Consumes:
  - Task 5: `union_timeline` / `canonical_master` / `column_on_union` / `row_range`（`core.export.timeline`）
  - Task 4: `ExportRequest`（`keys` / `output_path` / `options` / `header_resolver` / `extra_signals`）・`CsvExportOptions.use_unified_timeline`（M-1 で options 経由へ移動）
  - T-G（Task 1/2）: `_fmt_value(value, options) -> str`（値セル書式化・非有限 -> 空セル）と `_join(cells, opts) -> str`（RFC 4180 最小クォート＋連結）。**Task 1 Produces の実名をそのまま使う**（別名を挟まない — 挟むと書式化が二重定義になり、片方だけ直る回帰が入る）
  - 既存: `SignalGroupManager._mint_column` / `_resolved_lock` / `_resolved_by_key`・`ChannelSampleCache.reserved`
- Produces（Task 7/8/9 がこれに対して書く・シグネチャ厳守）:
  - `SignalGroupManager.resolve_transient(key: str) -> Signal | None` — 帳簿 (`_resolved_by_key` / `_resolved_order`) に**載せない**・pin/LRU 非干渉
  - `SignalGroupManager.transient_mint_count: int` — transient 鋳造の回数（`mint_count` とは別勘定）
  - `Session.resolve_signal_transient(key: str) -> Signal | None` — 委譲
  - `SignalGroupManager.channel_key_of(group_key: str, column_key: str) -> str | None` ／ `Session.channel_key_of(column_key: str) -> str | None` — 列キー → `"{group_key}::{物理チャンネル表示名}"`。`_mint_column` の**最長一致ループを共有ヘルパへ抽出して委譲**する（**鋳造しない・値を読まない**）。**列 → チャンネルの解決器はこの 1 実装のみ**（Task 8 の見積も Task 11 の計測器もこれを呼ぶ）— 2 つ持つと「見積が数えたチャンネル」と「ブロック割当が使うチャンネル」がずれ、見積の読み項が桁で嘘をつく。`scan_masters` が `metadata["physical_channel"]` の変化点で採る区切りと**同一チャンネルへ落ちる**ことをテストで固定する
  - `ChannelSampleCache.available_bytes -> int` — `max(0, budget - reserved)`。ブロックサイズの動的決定 (D3「予算 − 現在の pin 済み」) の唯一の入口
  - `ExportCancelled(Exception)`（`core/export/csv_exporter.py`）
  - `MasterScan`（frozen dataclass: `masters: tuple[np.ndarray, ...]` / `runs: tuple[int, ...]` / `max_master_len: int`）
  - `scan_masters(columns: Sequence[tuple[str, Signal | None]], resolve: Callable[[str], Signal | None]) -> MasterScan`
  - `block_columns(n_rows: int, max_master_len: int, budget_bytes: int) -> int`
  - `plan_blocks(runs: Sequence[int], block_cols: int) -> tuple[tuple[int, int], ...]`
  - `CsvExporter(*, block_cols: int | None = None, budget_fn: Callable[[], int] | None = None, merge_fan_in: int | None = None)` — **Task 7 へ意図的に繰越**（`__init__` は Task 6 で入れていない。本タスクで入れると T2 ratchet が空虚に緑になる〔commit `b0e7278` に実測記録〕。`BLOCK_COLS_VARIANTS` 拡幅と同一コミットで入れること）
  - `CsvExporter._write_time_temp(...)` / `CsvExporter._write_block_temp(...) -> list[str]`（単位行の側帯を返す）

**実装前に必ず確定させること（別タスクが名前を持っている箇所）:**

```
grep -n "class ExportCancelled\|def _fmt\|def _join\|def _quote\|utf-8-sig\|use_unified_timeline" src/valisync/core/export/csv_exporter.py
grep -n "class ExportRequest" -A 12 src/valisync/core/export/csv_exporter.py
```
- `ExportCancelled` が既に在れば**再定義しない**。
- 値セル書式化 / 行 join は **`_fmt_value` / `_join`（Task 1 Produces の実名）をそのまま呼ぶ**。**新しい書式化関数を定義してはならない**し、別名のラッパも挟まない — どちらもゴールデンの書式が二重定義になり、片方だけ直る回帰が入る。上の grep で実名が違っていたら**停止して報告**する（Task 1 の契約が動いている）。
- `use_unified_timeline` が `CsvExportOptions` へ移っていること（M-1）を確認する。移っていなければ**停止して報告**（契約が動いている）。

**`Signal.__slots__` に `"__weakref__"` を足す理由（実測に基づく設計判断）:**
`Signal` は `__slots__` を持ち `__weakref__` を含まないため、**現状 `weakref.ref(sig)` は `TypeError: cannot create weak reference` になる**（実測）。spec §6 G2/G5 が要求する「weakref による独立カウント」はそのままでは書けない。`resolved_keys()` は export 専用 resolve に構造的に盲目・`bytes_held` は pin されない列に無関係（spec §10 で使用禁止）なので、**帳簿以外の観測手段はこれしかない**。コストは 1 インスタンスあたりポインタ 1 本（prod の常駐 Signal は E-3 反転後 4,324 個 = 約 35 KB）で、E-3/FU-20 が守っている帯（550 MB）に対して無視できる。

---

- [ ] **Step 1: 失敗テストを書く**

ベースラインを記録（`uv run pytest -q` の passed/skipped）。Step 6 で **+33** になることを確認する。

`tests/core/loaders/test_resolver_transient.py` を新規作成:

```python
"""export 専用 resolve が帳簿・pin・LRU を汚さないこと (E-4b Task 6・MG-1)。

全列エクスポートは 330,004 列を解決する。それを ``resolve()`` (帳簿つき) で
やると: 容量 512 の LRU に載って定常が 512 本 ≫ G2 上限になり、かつ選択列が
512 未満の範囲エクスポートでは **1 本も evict されず現状の 114.5 MiB 残留が
そのまま残る** (spec §5.3)。したがって「LRU に任せる」は機構レスであり、
専用経路が要る。

既存の D4 identity 契約 (tests/core/loaders/test_resolver.py) は**無編集で緑**の
ままでなければならない — transient resolve はその契約に触れない。
"""

from __future__ import annotations

import datetime
import weakref
from pathlib import Path

import numpy as np

from tests.mdf4_helpers import write_mdf4_2d
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup


def _sig(name: str) -> Signal:
    return Signal(
        name=name,
        timestamps=np.arange(3, dtype=np.float64),
        values=np.zeros(3),
        file_format="MDF4",
        bus_type="",
        source_file="/x.mf4",
    )


def _group(*names: str) -> SignalGroup:
    return SignalGroup(
        signals=tuple(_sig(n) for n in names),
        source_path=Path("/x.mf4").resolve(),
        file_format="MDF4",
        loaded_at=datetime.datetime.now(),
    )


def _add_real(mgr: SignalGroupManager, tmp_path: Path) -> str:
    result = MdfLoader().load(write_mdf4_2d(tmp_path))
    sg = result.signal_group
    assert sg is not None
    return mgr.add(sg, column_records=result.column_records)


def _close(mgr: SignalGroupManager, key: str) -> None:
    group, _columns = mgr.remove(key)
    if group.handle is not None:
        group.handle.close()


def test_signal_supports_weakref() -> None:
    """G2/G5 の独立オラクルの前提条件 (__slots__ に __weakref__ が要る)。

    無いと ``weakref.ref(sig)`` が TypeError になり、帳簿以外の観測手段が
    1 つも無くなる (resolved_keys は transient に盲目・bytes_held は pin 前提)。
    """
    ref = weakref.ref(_sig("x"))
    assert ref() is not None or ref() is None  # 生成できること自体が契約


def test_transient_resolve_mints_without_touching_the_ledger(tmp_path: Path) -> None:
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    try:
        col_key = f"{key}::Mat[2]"
        got = mgr.resolve_transient(col_key)
        assert got is not None
        assert got.name == col_key
        # 帳簿は 1 バイトも動かない
        assert mgr.resolved_keys(key) == frozenset()
        assert mgr.resolved_lru_keys() == ()
        assert mgr.mint_count == 0
        assert mgr.transient_mint_count == 1
    finally:
        _close(mgr, key)


def test_transient_resolve_values_match_the_ledger_resolve(tmp_path: Path) -> None:
    """「帳簿に載せない」は「別物を返す」ではない (誤データの排除)。"""
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    try:
        col_key = f"{key}::Mat[1]"
        transient = mgr.resolve_transient(col_key)
        ledger = mgr.resolve(col_key)
        assert transient is not None and ledger is not None
        assert np.array_equal(np.asarray(transient.values), np.asarray(ledger.values))
        assert transient.timestamps is ledger.timestamps  # master は同一オブジェクト
    finally:
        _close(mgr, key)


def test_transient_resolve_reuses_an_already_resolved_column(tmp_path: Path) -> None:
    """既に帳簿に在る列は**作り直さない** (二重実体化を避ける)。

    ただし recency は動かさない — 動かすと全列エクスポートが LRU の順序表を
    総なめし、GUI が次に読む列の追い出し順序が壊れる。
    """
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    try:
        col_key = f"{key}::Mat[1]"
        other = f"{key}::Mat[2]"
        first = mgr.resolve(col_key)
        mgr.resolve(other)  # MRU は other
        order_before = mgr.resolved_lru_keys()

        again = mgr.resolve_transient(col_key)

        assert again is first
        assert mgr.transient_mint_count == 0  # 鋳造していない
        assert mgr.resolved_lru_keys() == order_before  # recency も動かさない
    finally:
        _close(mgr, key)


def test_transient_resolve_returns_existing_physical_signal(tmp_path: Path) -> None:
    """物理チャンネルキーは既存 map をそのまま返す (鋳造経路に入らない)。"""
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    try:
        got = mgr.resolve_transient(f"{key}::Clean")
        assert got is not None
        assert mgr.transient_mint_count == 0
    finally:
        _close(mgr, key)


def test_transient_resolve_returns_none_for_unloaded_group() -> None:
    mgr = SignalGroupManager()
    assert mgr.resolve_transient("mf4_9::Nope") is None


def test_transient_resolve_returns_none_for_unresolvable_column() -> None:
    mgr = SignalGroupManager()
    key = mgr.add(_group("Mat[0]"))  # 表もハンドルも無い合成グループ
    assert mgr.resolve_transient(f"{key}::Mat[7]") is None
    assert mgr.transient_mint_count == 0


def test_transient_resolve_never_evicts_pinned_or_unpinned_columns(
    tmp_path: Path,
) -> None:
    """**MG-1 の核心**: 容量 1 の LRU へ transient を 100 回流しても帳簿が動かない。

    ``resolve()`` でやると 1 回目で pin 外が落ち、以後 evict が回り続ける。
    """
    mgr = SignalGroupManager(resolved_capacity=1)
    key = _add_real(mgr, tmp_path)
    try:
        pinned_key = f"{key}::Mat[0]"
        assert mgr.resolve(pinned_key) is not None
        mgr.set_pinned_columns({pinned_key})
        evictions_before = mgr.resolved_evictions

        for _ in range(100):
            for col in ("Mat[1]", "Mat[2]"):
                assert mgr.resolve_transient(f"{key}::{col}") is not None

        assert mgr.resolved_evictions == evictions_before
        assert mgr.resolved_keys(key) == frozenset({pinned_key})
        assert mgr.resolved_lru_keys() == (pinned_key,)
        assert mgr.transient_mint_count == 200
    finally:
        _close(mgr, key)


def test_transient_columns_die_when_dropped(tmp_path: Path) -> None:
    """G5 の土台: 参照を落とせば**その場で**消える (帳簿が掴んでいない証明)。"""
    mgr = SignalGroupManager()
    key = _add_real(mgr, tmp_path)
    try:
        col = mgr.resolve_transient(f"{key}::Mat[2]")
        assert col is not None
        ref = weakref.ref(col)
        assert ref() is not None  # 反 vacuous: 生きている状態を先に観測する
        del col
        assert ref() is None, "帳簿かキャッシュが transient 列を掴んでいる"
    finally:
        _close(mgr, key)


def test_session_delegates_resolve_signal_transient(tmp_path: Path) -> None:
    from valisync.core.session import Session

    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    got = session.resolve_signal_transient(f"{key}::Mat[1]")
    assert got is not None
    assert session.resolved_column_keys(key) == frozenset()


def test_channel_key_of_maps_every_column_of_a_channel_to_one_key(
    tmp_path: Path,
) -> None:
    """列 -> チャンネルの解決器 (**鋳造しない**)。幅 k の列は全部 1 チャンネルへ。

    見積 (T-UX) の読み項がチャンネル単位で数えられる根拠そのもの。ここが列ごとに
    別キーを返すと、幅 1,100 のチャンネルで読み時間が 1,100 倍に見える。
    """
    from valisync.core.session import Session

    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    before = session._groups.transient_mint_count

    channels = {session.channel_key_of(f"{key}::Mat[{i}]") for i in range(3)}

    assert channels == {f"{key}::Mat"}
    assert session.channel_key_of(f"{key}::Clean") == f"{key}::Clean"
    assert session.channel_key_of(f"{key}::NoSuch") is None
    assert session.channel_key_of("bare_key_without_separator") is None
    assert session._groups.transient_mint_count == before, "解決器が列を鋳造した"


def test_channel_key_of_agrees_with_scan_masters_channel_runs(tmp_path: Path) -> None:
    """**2 つの真実を作らない**ことの pin (C-1)。

    ``scan_masters`` は ``(id(master), metadata["physical_channel"])`` の変化点で
    区切りを採り、見積は ``channel_key_of`` で数える。両者が同じチャンネルへ
    落ちなければ、見積の読み項とブロック割当が別のものを数えていることになる。
    """
    from valisync.core.export.csv_exporter import scan_masters
    from valisync.core.session import Session

    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    keys = [f"{key}::Mat[{i}]" for i in range(3)] + [f"{key}::Clean"]

    scan = scan_masters([(k, None) for k in keys], session.resolve_signal_transient)

    # scan の runs が示す区切りを、channel_key_of の答えから独立に再構成する。
    resolved = [session.channel_key_of(k) for k in keys]
    runs: list[int] = []
    for channel in resolved:
        if runs and channel == resolved[sum(runs) - 1]:
            runs[-1] += 1
        else:
            runs.append(1)
    assert tuple(runs) == scan.runs, (runs, scan.runs, resolved)
```

> `Session.resolved_column_keys` が存在しない場合は `session._groups.resolved_keys(key)` を使う（`grep -n "def resolved_column_keys" src/valisync/core/session.py` で確認する）。

`tests/core/export/test_block_writer.py` を新規作成:

```python
"""列ブロックの計画と block-temp 書き (E-4b Task 6・spec §5.3)。

この時点で ``CsvExporter.export`` はまだ Task 4 の橋を通る。ブロック writer は
**独立に**駆動して観測する — 中間観測物は「block-temp のバイト内容」であり、
最終ファイルではない。
"""

from __future__ import annotations

import gc
import threading
import weakref
from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.csv_exporter import (
    CsvExporter,
    CsvExportOptions,
    ExportCancelled,
    block_columns,
    plan_blocks,
    scan_masters,
)
from valisync.core.export.timeline import union_timeline
from valisync.core.models import Signal

_MIB = 1024 * 1024


def _sig(
    name: str, ts: list[float], vs: list[float], *, unit: str = "", phys: str = ""
) -> Signal:
    metadata: dict[str, object] = {}
    if unit:
        metadata["unit"] = unit
    if phys:
        metadata["physical_channel"] = phys
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="test",
        bus_type="",
        source_file="",
        metadata=metadata,
    )


def _columns(*signals: Signal) -> list[tuple[str, Signal | None]]:
    """(key, 直渡し Signal) の列リスト。直渡しは resolve を経由しない形の pin。"""
    return [(s.name, None) for s in signals]


def _resolver(*signals: Signal):  # type: ignore[no-untyped-def]
    table = {s.name: s for s in signals}
    return lambda key: table.get(key)


# ─── block_columns (D3 の動的決定) ────────────────────────────────────────────


def test_block_columns_is_clamped_to_the_maximum_when_the_budget_is_large() -> None:
    assert block_columns(n_rows=100, max_master_len=100, budget_bytes=256 * _MIB) == 512


def test_block_columns_is_clamped_to_the_minimum_when_the_budget_is_tiny() -> None:
    """**下限 16 は「予算を守れない」ではなく「進める」ための床** (spec D3)。"""
    assert block_columns(n_rows=10_000_000, max_master_len=10_000_000, budget_bytes=1) == 16


def test_block_columns_scales_with_the_remaining_budget() -> None:
    # per_col = 1000*9 + 1000*16 = 25,000 B -> 2,500,000 // 25,000 = 100
    assert block_columns(n_rows=1000, max_master_len=1000, budget_bytes=2_500_000) == 100


def test_block_columns_of_an_empty_range_does_not_divide_by_zero() -> None:
    assert block_columns(n_rows=0, max_master_len=0, budget_bytes=1024) == 512


# ─── plan_blocks (チャンネル局所の割り当て) ───────────────────────────────────


def test_plan_blocks_keeps_a_channel_whole() -> None:
    """1 チャンネルの全列は同一ブロックへ (spec §5.3: evict 連鎖の頭打ち)。"""
    assert plan_blocks([3, 3, 3], block_cols=4) == ((0, 3), (3, 6), (6, 9))


def test_plan_blocks_packs_channels_up_to_the_limit() -> None:
    assert plan_blocks([2, 2], block_cols=4) == ((0, 4),)


def test_plan_blocks_splits_a_channel_that_alone_exceeds_the_limit() -> None:
    """幅 1,100 の単独チャンネルは分割する。

    分割してよいのは E-4a のチャンネルキャッシュが 2-D を保持しており、
    2 ブロック目の切り出しが select ではなくヒットになるから。
    「絶対に割らない」にすると 1 ブロックが上限の 2 倍を実体化する。
    """
    assert plan_blocks([10], block_cols=4) == ((0, 4), (4, 8), (8, 10))


def test_plan_blocks_of_no_columns_is_empty() -> None:
    assert plan_blocks([], block_cols=4) == ()


# ─── scan_masters (値を読まない前走査) ────────────────────────────────────────


def test_scan_masters_dedups_by_identity_and_counts_channel_runs() -> None:
    master = np.array([0.0, 1.0, 2.0])
    a = Signal(
        name="mf4_1::W[0]",
        timestamps=master,
        values=np.zeros(3),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={"physical_channel": "W"},
    )
    b = Signal(
        name="mf4_1::W[1]",
        timestamps=a.timestamps,
        values=np.zeros(3),
        file_format="MDF4",
        bus_type="",
        source_file="",
        metadata={"physical_channel": "W"},
    )
    c = _sig("mf4_1::Other", [0.0, 0.5, 1.0], [1.0, 2.0, 3.0], phys="Other")

    scan = scan_masters(_columns(a, b, c), _resolver(a, b, c))

    assert len(scan.masters) == 2  # W の 2 列は master を共有
    assert scan.runs == (2, 1)
    assert scan.max_master_len == 3


def test_scan_masters_never_materialises_values(tmp_path: Path) -> None:
    """見積 (T-UX) が「値を読まない」でいられる根拠を writer 側でも pin する。"""
    from tests.mdf4_helpers import write_mdf4_2d
    from valisync.core.session import Session

    session = Session()
    key = session.load(write_mdf4_2d(tmp_path)).key
    keys = [f"{key}::Mat[{i}]" for i in range(3)]
    resolve = session.resolve_signal_transient

    scan = scan_masters([(k, None) for k in keys], resolve)

    assert scan.runs == (3,)  # 3 列は同一物理チャンネル = 1 run
    parent = next(s for s in session.group_signals(key) if s.name == f"{key}::Mat")
    assert parent._values_source.is_materialized is False


def test_scan_masters_raises_for_an_unresolvable_key() -> None:
    with pytest.raises(ValueError, match="解決できません"):
        scan_masters([("mf4_1::Nope", None)], lambda _k: None)


# ─── block-temp の中身 ────────────────────────────────────────────────────────


def _write_block(
    tmp_path: Path, signals: list[Signal], opts: CsvExportOptions | None = None
) -> tuple[list[str], list[str]]:
    """1 ブロックを書いて (行, 単位側帯) を返す。"""
    opts = opts or CsvExportOptions()
    union = union_timeline([s.timestamps for s in signals])
    temp = tmp_path / "block.tmp"
    units = CsvExporter()._write_block_temp(
        _columns(*signals),
        resolve=_resolver(*signals),
        union_view=union,
        opts=opts,
        temp_path=temp,
        cancel=None,
    )
    return temp.read_text(encoding="utf-8").splitlines(), units


def test_block_temp_holds_one_joined_fragment_per_row(tmp_path: Path) -> None:
    a = _sig("a", [0.0, 2.0], [10.0, 12.0])
    b = _sig("b", [1.0, 2.0], [21.0, 22.0])
    rows, _units = _write_block(tmp_path, [a, b])
    assert rows == ["10.0,", ",21.0", "12.0,22.0"]  # union = {0,1,2}


def test_block_temp_row_count_equals_the_union_view_length(tmp_path: Path) -> None:
    a = _sig("a", [0.0, 2.0], [10.0, 12.0])
    rows, _units = _write_block(tmp_path, [a])
    assert len(rows) == 2


def test_block_temp_of_zero_rows_is_an_empty_file(tmp_path: Path) -> None:
    """範囲外エクスポート (ヘッダのみのファイル) の中間形。"""
    a = _sig("a", [], [])
    rows, _units = _write_block(tmp_path, [a])
    assert rows == []
    assert (tmp_path / "block.tmp").read_bytes() == b""


def test_block_temp_collects_units_in_column_order(tmp_path: Path) -> None:
    a = _sig("a", [0.0], [1.0], unit="km/h")
    b = _sig("b", [0.0], [2.0])
    _rows, units = _write_block(tmp_path, [a, b])
    assert units == ["km/h", ""]


def test_block_temp_unit_of_none_becomes_an_empty_cell(tmp_path: Path) -> None:
    """手組み metadata の ``unit=None`` (spec §9-6)。join で TypeError にしない。"""
    a = Signal(
        name="a",
        timestamps=np.array([0.0]),
        values=np.array([1.0]),
        file_format="t",
        bus_type="",
        source_file="",
        metadata={"unit": None},
    )
    _rows, units = _write_block(tmp_path, [a])
    assert units == [""]


def test_block_temp_honours_delimiter_and_decimal(tmp_path: Path) -> None:
    a = _sig("a", [0.0], [1.5])
    b = _sig("b", [0.0], [2.5])
    rows, _units = _write_block(
        tmp_path, [a, b], CsvExportOptions(delimiter=";", decimal=",")
    )
    assert rows == ["1,5;2,5"]


def test_block_temp_rejects_a_container_column_before_reading_rows(
    tmp_path: Path,
) -> None:
    """1 時刻 1 値でない列は行組み立ての**前**に拒否する (E-3 C-d の位置)。"""
    parent = Signal(
        name="Mat",
        timestamps=np.arange(4.0),
        values=np.arange(12, dtype=np.uint8).reshape(4, 3),
        file_format="MDF4",
        bus_type="",
        source_file="",
    )
    with pytest.raises(ValueError, match="配列チャンネル"):
        _write_block(tmp_path, [parent])
    assert (tmp_path / "block.tmp").exists() is False


# ─── キャンセル (I8: 3 つのチェック点) ────────────────────────────────────────


def test_cancel_before_a_column_read_stops_within_that_block(tmp_path: Path) -> None:
    """ブロック境界だけでは cold ~316 ms/列 x block_cols の間 Event を見ない。"""
    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    b = _sig("b", [0.0, 1.0], [3.0, 4.0])
    cancel = threading.Event()
    seen: list[str] = []

    def resolve(key: str) -> Signal | None:
        seen.append(key)
        cancel.set()  # 1 列目を渡した直後にキャンセル要求が立つ
        return {"a": a, "b": b}.get(key)

    with pytest.raises(ExportCancelled):
        CsvExporter()._write_block_temp(
            _columns(a, b),
            resolve=resolve,
            union_view=union_timeline([a.timestamps]),
            opts=CsvExportOptions(),
            temp_path=tmp_path / "block.tmp",
            cancel=cancel,
        )
    assert seen == ["a"], "2 列目を読み始めている (チェック点が列の前に無い)"


def test_cancel_inside_a_long_row_loop_stops_before_the_end(tmp_path: Path) -> None:
    n = 50_000
    a = _sig("a", np.arange(n).tolist(), np.arange(n).tolist())
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ExportCancelled):
        CsvExporter()._write_block_temp(
            _columns(a),
            resolve=_resolver(a),
            union_view=union_timeline([a.timestamps]),
            opts=CsvExportOptions(),
            temp_path=tmp_path / "block.tmp",
            cancel=cancel,
        )


# ─── G2/G5 の weakref オラクル ────────────────────────────────────────────────


def test_transient_columns_do_not_accumulate_across_blocks(tmp_path: Path) -> None:
    """**G2/G5 の形** (spec §6): 生存数はブロック内に閉じる。

    ``resolved_keys()`` / ``bytes_held`` は使わない — 前者は export 専用 resolve に
    構造的に盲目・後者は pin されない列に無関係 (spec §10)。
    """
    n_cols, block_cols = 12, 3
    master = np.arange(50, dtype=np.float64)
    master.flags.writeable = False
    refs: list[weakref.ref[Signal]] = []
    # **ブロック内**の生存数を採る (ブロック終端で採ると常に 0 になり、上界の
    # assert が恒真化する)。resolve が呼ばれた直後 = その列がまだ生きている瞬間。
    live_marks: list[int] = []

    def resolve(key: str) -> Signal | None:
        sig = Signal(
            name=key,
            timestamps=master,
            values=np.arange(50, dtype=np.float64),
            file_format="t",
            bus_type="",
            source_file="",
            metadata={"physical_channel": key},
        )
        refs.append(weakref.ref(sig))
        gc.collect()
        live_marks.append(sum(1 for r in refs if r() is not None))
        return sig

    exporter = CsvExporter()
    union = union_timeline([master])
    keys = [f"c{i}" for i in range(n_cols)]
    tails: list[int] = []
    for lo, hi in plan_blocks([1] * n_cols, block_cols):
        exporter._write_block_temp(
            [(k, None) for k in keys[lo:hi]],
            resolve=resolve,
            union_view=union,
            opts=CsvExportOptions(),
            temp_path=tmp_path / f"b{lo}.tmp",
            cancel=None,
        )
        gc.collect()
        tails.append(sum(1 for r in refs if r() is not None))

    assert len(refs) == n_cols  # 反 vacuous: 実際に 12 本鋳造している
    assert max(live_marks) >= 1, "1 本も生存を観測していない (上界 0 の空虚形)"
    assert max(live_marks) <= block_cols, live_marks  # G2: 同時生存 <= block_cols
    assert tails == [0] * len(tails), f"ブロック終端で参照が残った: {tails}"  # G5
```

- [ ] **Step 2: 失敗を確認**

```
uv run pytest tests/core/loaders/test_resolver_transient.py tests/core/export/test_block_writer.py -q
```
Expected: 両ファイルとも **collection error / AttributeError**（`resolve_transient` も `scan_masters` も存在しない）。`test_signal_supports_weakref` は **TypeError: cannot create weak reference to 'Signal' object** で落ちる（＝ `__weakref__` を足す前の honest-RED）。

- [ ] **Step 3: 実装**

**(a) `src/valisync/core/models/signal.py:27`** — `__slots__` の先頭へ追加（RUF023 のソート順で `"__weakref__"` が先頭になる）:

```python
    __slots__ = (
        # G2/G5 (E-4b spec §6) の生存オラクルが weakref を要求する。__slots__ に
        # __weakref__ が無いと weakref.ref(sig) が TypeError になり、**帳簿以外の
        # 観測手段が 1 つも無くなる** (resolved_keys は export 専用 resolve に
        # 構造的に盲目・bytes_held は pin されない列に無関係 = spec §10 で使用禁止)。
        # コストはインスタンスあたりポインタ 1 本 (prod の常駐 4,324 個で ~35 KB)。
        "__weakref__",
        "_finite_view_cache",
        "_monotonic",
        "_range_stat_index_cache",
        "_sorted_view_cache",
        "_sorted_view_delegate",
        "_values_source",
        "bus_type",
        "file_format",
        "metadata",
        "name",
        "source_file",
        "timestamps",
    )
```

**(b) `src/valisync/core/loaders/signal_group_manager.py`** — `__init__` の `self.mint_count = 0` の直後へ:

```python
        # export 専用 resolve の鋳造回数 (MG-1)。**mint_count とは別勘定**にする —
        # mint_count は「帳簿に載った鋳造」の数で、既存テストがその意味で pin して
        # いる。transient を混ぜると全列エクスポートで 330k 増えて意味が壊れる。
        self.transient_mint_count = 0
```

`resolved_keys` の直前へ:

```python
    def resolve_transient(self, key: str) -> Signal | None:
        """エクスポート専用の列解決 (**帳簿に載せない** — E-4b MG-1)。

        ``resolve()`` との違いはただ 1 点、鋳造した列を ``_resolved_by_key`` /
        ``_resolved_order`` へ**登録しない**こと。生存はブロックローカルの参照だけ
        になり、参照を落とせばその場で消える。

        **なぜ LRU に任せられないか**: 全列エクスポート (330,004 列) を ``resolve()``
        で回すと、容量 512 の LRU の定常が 512 本 = G2 の上限を常時超える。しかも
        選択列が 512 未満の範囲エクスポートでは **1 本も evict されず**、現状の
        114.5 MiB 残留がそのまま残る (spec §5.3)。「LRU に任せる」は機構レス。

        **既に帳簿に在る列は作り直さず、そのまま返す** (二重実体化を避ける) が、
        recency は**動かさない**。動かすと全列エクスポートが LRU の順序表を総なめ
        して、GUI が次に読む列の追い出し順序が壊れる。

        pin・evict・``mint_count`` のいずれにも触れないので、D4 の identity 契約
        (pin 中は同一オブジェクト) は不変。
        """
        # 10a (spec §5.7-3・PR 1d51f85) supersede: `self._ensure_namespaced()` を
        # discard-return で呼び `assert self._namespaced_map is not None` する形は
        # コンパイルもテストも通るが、assert 直後の 1 バイトコードの隙に別スレッドの
        # add/remove が invalidate すると再び None に戻り `.get` が NoneType.get で
        # 落ちる窓を再導入する。以下の返り値経由の形をそのまま写すこと。
        _namespaced, mapping = self._ensure_namespaced()
        hit = mapping.get(key)
        if hit is not None:
            return hit  # 物理チャンネルは既存オブジェクト (鋳造経路に入らない)
        group_key = key.split(KEY_SEPARATOR, 1)[0]
        with self._resolved_lock:
            # 在籍判定を lock の中で行う理由は resolve() と同一 (E-4a T3 レビュー M3)。
            # E-4b では export ワーカーがこの経路を ~18 分走らせるので、窓が常態化する。
            if group_key not in self._groups:
                return None
            cached = self._resolved_by_key.get(group_key, {}).get(key)
            if cached is not None:
                return cached  # _touch しない (上記の WHY)
            minted = self._mint_column(group_key, key)
            if minted is not None:
                self.transient_mint_count += 1
            return minted
```

同ファイルへ **列 → 物理チャンネルの解決器**を 1 本だけ置く（`_mint_column` の最長一致ループを抽出して両者が委譲する — 2 実装にすると見積とブロック割当がずれる）:

```python
    def _owning_channel(self, group_key: str, column_key: str) -> str | None:
        """列キーを所有する物理チャンネルの**表示名**（`_mint_column` と同じ最長一致）。

        ``_mint_column`` の探索ループから「どの record が親か」の判定だけを取り出した
        もの。**鋳造しない・値を読まない**ので見積 (E-4b T-UX) から呼べる。
        打ち切り条件も ``_mint_column`` と同一 — ``rest`` が空（表示名そのもの＝
        チャンネルであって列ではない）なら **そこで終了**する。`continue` にすると
        実チャンネル `A[0]` が配列 `A` の列 0 と字面衝突したとき短い親へ滑る。
        """
        records = self._column_records.get(group_key)
        if not records:
            return None
        display_key = column_key.split(KEY_SEPARATOR, 1)[-1]
        for i in range(len(display_key), 0, -1):
            record = records.get(display_key[:i])
            if record is None:
                continue
            rest = display_key[i:]
            if not rest:
                return display_key[:i]  # 表示名そのもの = そのチャンネル
            raw_leaf = f"{record.raw_base_name}{rest}"
            if parse_leaf(raw_leaf, {record.raw_base_name: record.spec}) is None:
                continue
            if _leaf_path(record, rest) is None:
                continue
            return display_key[:i]
        return None

    def channel_key_of(self, group_key: str, column_key: str) -> str | None:
        """``"{group_key}::{物理チャンネル表示名}"``（解決不能なら None）。"""
        display = self._owning_channel(group_key, column_key)
        return None if display is None else f"{group_key}{KEY_SEPARATOR}{display}"
```

`_mint_column` の最長一致ループは `_owning_channel` を呼ぶ形へ書き換える（**探索は 1 実装**）。書き換え後に既存の `tests/core/loaders/test_resolver.py`（D4 identity 契約）が**無編集で緑**であることを確認する — 緑にならないなら抽出が挙動を変えている。

**(c) `src/valisync/core/loaders/channel_cache.py`** — `reserved` プロパティの直後へ:

```python
    @property
    def available_bytes(self) -> int:
        """LRU が今使ってよいバイト数 (``budget - reserved``・下限 0)。

        E-4b のブロックサイズ決定 (D3「予算 − 現在の pin 済み」) の唯一の入口。
        2 回に分けて ``budget`` と ``reserved`` を読ませないのは、pin の push が
        間に挟まると両者が別時点の値になり、**予算を超えるブロック幅が計算できて
        しまう**から。``_capacity_for(0)`` と同じ式で、最低容量の床は掛けない
        (床は「1 エントリを載せ切る」ためのもので、ブロック幅の根拠ではない)。
        """
        return max(0, self._budget - self._reserved)
```

**(d) `src/valisync/core/session.py`** — `resolve_signal` の直後へ:

```python
    def channel_key_of(self, column_key: str) -> str | None:
        """列キー -> ``"{group_key}::{物理チャンネル表示名}"`` (**鋳造しない**)。

        E-4b の「列 -> チャンネル」解決の**唯一の入口**。見積 (T-UX) のチャンネル
        単価計算・ブロック割当・計測器がすべてここを通る。2 実装持つと「見積が
        数えたチャンネル」と「実際に読むチャンネル」がずれ、読み項が桁で外れる。
        """
        group_key, sep, _bare = column_key.partition(KEY_SEPARATOR)
        if not sep:
            return None
        return self._groups.channel_key_of(group_key, column_key)

    def resolve_signal_transient(self, key: str) -> Signal | None:
        """列キーを **帳簿に載せずに** Signal へ解決する (エクスポート専用・E-4b)。

        ``CsvExporter`` の列ブロックが 1 列ずつ呼び、ブロック終端で参照を落とす。
        ``resolve_signal`` を使うと鋳造列が LRU に載り、全列エクスポートで定常が
        容量ぶん (512 本) 常駐する / 範囲エクスポートでは 1 本も落ちない
        (spec §5.3 MG-1)。GUI の表示・プロットからは**呼んではならない**
        (pin の対象にならないため、次の render で必ず作り直しになる)。
        """
        return self._groups.resolve_transient(key)
```

**(e) `src/valisync/core/export/csv_exporter.py`** — 追加分（`export()` は無変更）:

```python
# ブロック幅の下限/上限 (spec D3)。下限 16 は「予算を守れない」ではなく **進める**
# ための床で、union が極端に長い (= 1 列が予算を超える) ときでも 16 列ずつ進む。
# 上限 512 は E-4a の鋳造列 LRU 容量と同じ数で、1 ブロックの同時生存が
# 「プロット中の全列」を超えないための目安。
_MIN_BLOCK_COLS = 16
_MAX_BLOCK_COLS = 512
# Session を経由しない直呼び (テスト・スクリプト) のための既定予算。
# ChannelSampleCache の既定と同じ 256 MB (D3「予算の裁定者は 1 人」)。
_DEFAULT_EXPORT_BUDGET_BYTES = 256 * 1024 * 1024
# 行ループ内でキャンセル要求を見る間隔 [I8]。``Event.is_set()`` は ~50 ns なので
# 毎行でも払えるが、1,024 行ごとにすると最も広いブロック (512 列 ~150 us/行) でも
# 応答は ~0.15 s に収まり、狭いブロックでは分岐そのものが消える。
_CANCEL_ROW_INTERVAL = 1024
# 何行ぶん溜めてから write するか。1 行ずつ write すると prod (12,012 行 x 8,253
# ブロック = 99M 回) で write のオーバーヘッドだけが積み上がる。1,024 行 x 512 列で
# バッファは ~2.4 MB に収まる。
_FLUSH_ROWS = 1024

EXPORT_UNRESOLVABLE_KEY_ERROR_TMPL = (
    "列 '{key}' を解決できません（ファイルがアンロードされた可能性があります）。"
)


class ExportCancelled(Exception):
    """協調キャンセルで中断した (temp は全削除済み・出力ファイルは存在しない)。"""


@dataclass(frozen=True)
class MasterScan:
    """列を **値を読まずに** 前走査した結果 (union と割り当ての材料)。

    ``masters`` は identity dedup 済み (spec §5.4)・``runs`` は物理チャンネル
    ごとの列数 (keys の並び順)・``max_master_len`` はブロック幅の見積に使う
    「1 列が実体化しうる最大サンプル数」。
    """

    masters: tuple[np.ndarray, ...]
    runs: tuple[int, ...]
    max_master_len: int


def scan_masters(
    columns: Sequence[tuple[str, Signal | None]],
    resolve: Callable[[str], Signal | None],
) -> MasterScan:
    """列を 1 周して master と物理チャンネルの区切りを集める (**値を読まない**)。

    ここで解決した Signal は**その場で捨てる** — 保持すると 330,004 本が同時生存
    して E-4b が消そうとしているメモリがそのまま戻る。鋳造自体は I/O を伴わない
    (``LazyMdfValues`` は遅延) ので、この前走査は master と metadata しか触らない。

    区切りは ``(id(master), physical_channel)`` の変化点で採る。キー文字列を
    parse しないのは、``Mat[0]`` のような列名が実チャンネル名と字面衝突しうる
    から (E-3 の 1:1 契約が守るのは衝突の**拒否**であって、字面の一意性ではない)。
    """
    seen_masters: set[int] = set()
    masters: list[np.ndarray] = []
    runs: list[int] = []
    max_len = 0
    current: tuple[int, object] | None = None
    for key, direct in columns:
        sig = direct if direct is not None else resolve(key)
        if sig is None:
            raise ValueError(EXPORT_UNRESOLVABLE_KEY_ERROR_TMPL.format(key=key))
        master = sig.timestamps
        if id(master) not in seen_masters:
            seen_masters.add(id(master))
            masters.append(master)
            max_len = max(max_len, len(master))
        channel = (id(master), sig.metadata.get("physical_channel", sig.name))
        if channel == current:
            runs[-1] += 1
        else:
            runs.append(1)
            current = channel
        del sig  # 前走査は 1 本ずつ捨てる (同時生存 1 本)
    return MasterScan(tuple(masters), tuple(runs), max_len)


def block_columns(n_rows: int, max_master_len: int, budget_bytes: int) -> int:
    """1 ブロックに載せる列数 (D3 の動的決定)。

    1 列が同時に抱える実体は「union 行に整列した float64 値 (8 B/行) + 存在
    フラグ (1 B/行)」で、これは**ブロックの終わりまで**生きる (行ループが全列を
    横断するため)。加えて 1 列ぶんの ``sorted_view`` (時刻 + 値 = 16 B/サンプル)
    が整列の間だけ生きる。合計を予算で割ったものが上限。

    **値を ``tolist()`` してはならない**: Python float は 32 B/セルで、この式の
    3.5 倍を食う (512 列 x 12,012 行 = 200 MB)。numpy 配列のまま持ち、セル書式化は
    書き出しの瞬間に 1 セルずつ行う。
    """
    per_col = n_rows * 9 + max_master_len * 16
    if per_col <= 0:
        return _MAX_BLOCK_COLS  # 行 0 本 (範囲外エクスポート) — 幅は制約にならない
    return max(_MIN_BLOCK_COLS, min(_MAX_BLOCK_COLS, budget_bytes // per_col))


def plan_blocks(runs: Sequence[int], block_cols: int) -> tuple[tuple[int, int], ...]:
    """物理チャンネルの区切り ``runs`` を ``[start, stop)`` のブロックへ詰める。

    **1 チャンネルの列は同じブロックへ**入れる (spec §5.3): チャンネルを跨いで
    混ぜると、ブロックごとに別チャンネルの 2-D を読み直して evict 連鎖が
    チャンネル数ぶんでなく列数ぶんになる。

    ただし**単独で上限を超える run は分割する**。割ってよいのは E-4a の
    チャンネルキャッシュが 2-D を保持しており、2 ブロック目の切り出しが select
    ではなくヒットになるから — 「絶対に割らない」にすると幅 1,100 のチャンネルで
    1 ブロックが上限の 2 倍を実体化する。
    """
    blocks: list[tuple[int, int]] = []
    start = cur = 0
    for run in runs:
        if cur > start and cur - start + run > block_cols:
            blocks.append((start, cur))
            start = cur
        cur += run
        while cur - start > block_cols:
            blocks.append((start, start + block_cols))
            start += block_cols
    if cur > start:
        blocks.append((start, cur))
    return tuple(blocks)


def _check_cancel(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise ExportCancelled("エクスポートはキャンセルされました")
```

`CsvExporter` へ `__init__` と 2 つの writer を追加:

```python
    def __init__(
        self,
        *,
        block_cols: int | None = None,
        budget_fn: Callable[[], int] | None = None,
        merge_fan_in: int | None = None,
    ) -> None:
        """*block_cols* / *budget_fn* / *merge_fan_in* は**注入口**（既定は自動）。

        ``export()`` の署名は共有契約で凍結されているので、テストと ①gate が
        「小さいブロックで駆動する」ための口はコンストラクタに置く (E-4a の
        ``Session(cache_budget_bytes=...)`` と同型)。*budget_fn* は
        ``Session`` が ``channel_cache.available_bytes`` を束ねて渡す — 呼び出し
        時に読むので、pin の増減が次のエクスポートに反映される。
        """
        self._block_cols_override = block_cols
        self._budget_fn = budget_fn
        self._merge_fan_in = merge_fan_in

    @staticmethod
    def _require_single_value_column(sig: Signal) -> None:
        """1 時刻 1 値でない列 (配列/構造化の親) を拒否する (E-3 C-d)。

        判定を ``sorted_view()`` ではなく ``values`` で行う理由は
        ``_require_single_value_columns`` の docstring と同一 (構造化の親では
        ``astype(np.float64)`` が先に生 TypeError を出す)。
        """
        values = sig.values
        if values.ndim != 1 or values.dtype.names is not None:
            raise ValueError(
                EXPORT_MULTI_COLUMN_VALUES_ERROR_TMPL.format(name=sig.name)
            )

    def _write_time_temp(
        self,
        union_view: np.ndarray,
        opts: CsvExportOptions,
        temp_path: Path,
        cancel: threading.Event | None,
    ) -> None:
        """時刻列を **幅 1 のブロック** として書く (マージ器に特別扱いを作らない)。"""
        with open(temp_path, "w", encoding="utf-8", newline="") as f:
            buf: list[str] = []
            for i, ts in enumerate(union_view.tolist()):
                if i % _CANCEL_ROW_INTERVAL == 0:
                    _check_cancel(cancel)
                buf.append(_join([_fmt(ts, opts)], opts))
                if len(buf) >= _FLUSH_ROWS:
                    f.write("\n".join(buf) + "\n")
                    buf.clear()
            if buf:
                f.write("\n".join(buf) + "\n")

    def _write_block_temp(
        self,
        columns: Sequence[tuple[str, Signal | None]],
        *,
        resolve: Callable[[str], Signal | None],
        union_view: np.ndarray,
        opts: CsvExportOptions,
        temp_path: Path,
        cancel: threading.Event | None,
    ) -> list[str]:
        """1 ブロックぶんのセル断片を *temp_path* へ書き、単位の側帯を返す。

        1 行 = このブロックの列だけを区切りで繋いだ断片 (時刻も他ブロックも
        含まない)。行数は必ず ``len(union_view)`` になる — マージ器の行数一致
        assert (MG-6) が意味を持つのはこの不変条件があるから。

        列の参照はこの関数を出る時点で 1 本も残らない (``aligned`` は numpy 配列
        だけを持つ)。これが G2/G5 の「同時生存 <= block_cols」の実装上の根拠。
        """
        aligned: list[tuple[np.ndarray, np.ndarray]] = []
        units: list[str] = []
        for key, direct in columns:
            # ブロック境界だけでなく **各列の読みの前** で見る [I8]: cold な列は
            # ~316 ms/列かかるので、境界だけだと block_cols x 316 ms の間 Event を
            # 見ないことになる。
            _check_cancel(cancel)
            sig = direct if direct is not None else resolve(key)
            if sig is None:
                raise ValueError(EXPORT_UNRESOLVABLE_KEY_ERROR_TMPL.format(key=key))
            self._require_single_value_column(sig)
            ts, vs = sig.sorted_view()
            aligned.append(column_on_union(ts, vs, union_view))
            unit = sig.metadata.get("unit", "")
            # production の mdf_loader は truthy ガードで None を載せないが
            # (spec §13-2)、手組み metadata では None がありうる (§9-6)。
            units.append(unit if isinstance(unit, str) else "")
            del sig, ts, vs  # 明示解放 (次の列を読む前に落とす)
        with open(temp_path, "w", encoding="utf-8", newline="") as f:
            buf: list[str] = []
            for i in range(len(union_view)):
                if i % _CANCEL_ROW_INTERVAL == 0:
                    _check_cancel(cancel)
                buf.append(
                    _join(
                        [
                            _fmt_value(vals[i], opts) if present[i] else ""
                            for vals, present in aligned
                        ],
                        opts,
                    )
                )
                if len(buf) >= _FLUSH_ROWS:
                    f.write("\n".join(buf) + "\n")
                    buf.clear()
            if buf:
                f.write("\n".join(buf) + "\n")
        return units
```

必要な import（ファイル冒頭へ追加）: `threading`・`from collections.abc import Callable, Sequence`・`from valisync.core.export.timeline import column_on_union`。

- [ ] **Step 4: 通ることを確認**

```
uv run pytest tests/core/loaders/test_resolver_transient.py tests/core/export/test_block_writer.py -q
uv run pytest tests/core/loaders/test_resolver.py tests/core/test_export_container_guard.py tests/test_export.py tests/test_csv_export_options.py -q
```
Expected: 前者 `33 passed`、後者は**無編集で全数 pass**（`export()` を触っていないので橋の挙動は完全に不変。D4 identity 契約も不変）。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

pristine copy（`signal.py` / `signal_group_manager.py` / `channel_cache.py` / `session.py` / `csv_exporter.py`）を `$SCRATCH` へ取ってから:

| # | 壊す箇所（正確な編集） | 予測 RED |
|---|---|---|
| S1 | `resolve_transient` の本体を `return self.resolve(key)` にする（帳簿つき resolve へ委譲）| `test_transient_resolve_mints_without_touching_the_ledger` / `test_transient_resolve_never_evicts_pinned_or_unpinned_columns` / `test_transient_columns_die_when_dropped` / `test_session_delegates_resolve_signal_transient` の **4 件**。`values_match` と `reuses_an_already_resolved_column` は**緑のまま**（値も再利用も同じ）— これが「帳簿を汚す実装」が値ベースでは検出できないことの実証 |
| S2 | `resolve_transient` の cached ヒットで `self._touch(key)` を呼ぶ | `test_transient_resolve_reuses_an_already_resolved_column` の **1 件のみ**（`resolved_lru_keys()` の順序が入れ替わる） |
| S3 | `Signal.__slots__` から `"__weakref__"` を削除 | `test_signal_supports_weakref` / `test_transient_columns_die_when_dropped` / `test_transient_columns_do_not_accumulate_across_blocks` の **3 件**（すべて `TypeError: cannot create weak reference`）。**RED の形が TypeError であること**まで確認する（値の不一致ではない = オラクル自体が消える形） |
| S4 | `_write_block_temp` の `del sig, ts, vs` を削除し `aligned` の隣に `sig` を保持するリストを足す | `test_transient_columns_do_not_accumulate_across_blocks` の **1 件のみ**。他は出力が同じなので緑 — G2/G5 が「出力テスト」では絶対に代替できないことの実証 |
| S5 | `_write_block_temp` の列ループ先頭の `_check_cancel` を削除（ブロック境界だけにする）| `test_cancel_before_a_column_read_stops_within_that_block` の **1 件**（`seen == ["a", "b"]` になる） |
| S6 | 行ループの `_check_cancel` を削除 | `test_cancel_inside_a_long_row_loop_stops_before_the_end` の **1 件** |
| S7 | `plan_blocks` の run 境界判定を消し単純に `block_cols` で切る | `test_plan_blocks_keeps_a_channel_whole` の **1 件のみ**（`((0,4),(4,8),(8,9))` になる） |
| S8 | `block_columns` の `max(_MIN_BLOCK_COLS, ...)` を外す | `test_block_columns_is_clamped_to_the_minimum_when_the_budget_is_tiny` の **1 件**（0 になり、後段が無限ループ化しうる形）|
| S9 | `scan_masters` の identity dedup を外す | `test_scan_masters_dedups_by_identity_and_counts_channel_runs` の **1 件**（`len(masters) == 3`）|
| S10 | `_require_single_value_column` の呼び出しを `_write_block_temp` の**行ループ直前**へ移す | `test_block_temp_rejects_a_container_column_before_reading_rows` は**緑のまま**（例外は出るので）。RED になるのは既存 `tests/core/test_export_container_guard.py::test_exporter_writes_nothing_when_rejected` **のみ**（`seen` に sorted_view が乗る）— この 1 件が「ガードの位置」の唯一の番人であることを実測で確かめる |

**予測が外れたら止めて報告する**（このリポジトリでは「到達範囲の主張が誤っていた sabotage」を過去 3 件摘出している）。

**未配線の実測**（`export()` を触っていないことの構造的証明）:

```
git diff --stat src/valisync/core/export/csv_exporter.py
grep -n "def export" -A 15 src/valisync/core/export/csv_exporter.py
```
Expected: `export()` の本体が Task 4 時点と 1 行も違わないこと（差分は追加行のみ）。

- [ ] **Step 6: ゲート＋コミット**

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```
passed 数が **Step 1 のベースライン + 33**。

**共有インターフェース契約を同時に更新する**（`.superpowers/sdd/e4b-shared-interfaces.md`・「逐語・変更禁止」なので**実装が確定した時点で契約側を追随させる**のが唯一の整合手段）:
- `SignalGroupManager.channel_key_of` / `Session.channel_key_of` を「export 専用 resolve」節へ追記（Task 8 が逐語で消費する）。
- `block_cols` 式（L51）を実装式 `clamp(残余予算 // (union長 * 9 + master長 * 16), 16, 512)` へ。
- チャンネル局所の割り当て（L52）へ「**単独で上限を超える run は分割する**」の逸脱を明記。
差分を報告に転記する（契約が動いたことは後続の著者にとって最重要の情報）。

```
git add src/valisync/core/models/signal.py src/valisync/core/loaders/signal_group_manager.py src/valisync/core/loaders/channel_cache.py src/valisync/core/session.py src/valisync/core/export/csv_exporter.py tests/core/loaders/test_resolver_transient.py tests/core/export/test_block_writer.py
git commit -m "$(cat <<'EOF'
feat(core): export 専用 resolve と列ブロック writer を新設 (export() は未配線)

E-4b §5.3 の本体の前半。エクスポートの列解決を _resolved_by_key/_resolved_order へ
**載せない**専用経路 (resolve_transient) にし、鋳造列の生存をブロックローカルの
参照だけにする (MG-1)。E-4a の LRU に載せると、全列エクスポートは定常 512 本
(G2 上限超) になり、選択列 < 512 の範囲エクスポートでは 1 本も evict されず現状の
114.5 MiB 残留がそのまま残る — 「LRU に任せる」は機構レスだった。

ブロック writer は 1 行 = そのブロックの列だけのセル断片を block-temp へ流す。
行数は必ず union 行数に一致する (マージ器の行数一致 assert が意味を持つ前提)。
値は numpy 配列のまま持ち tolist しない (Python float 32 B/セルは見積の 3.5 倍で、
512 列 x 12,012 行 = 200 MB になる)。ブロック幅は D3 の動的決定
(clamp(残余予算 // (union長 x 9 + master長 x 16), 16, 512)) で、残余予算は
ChannelSampleCache.available_bytes (budget - reserved) から取る = 裁定者は 1 人。

列の割り当てはチャンネル局所 (1 チャンネルの全列を同一ブロックへ)。ただし単独で
上限を超える run は分割する — E-4a のチャンネルキャッシュが 2-D を保持している
ので 2 ブロック目はヒットになり、割らない方が 1 ブロックの実体化を倍にする。

キャンセルは 3 点で見る (ブロック境界・各列読みの前・行 1,024 行ごと) [I8]。
境界だけだと cold ~316 ms/列 x block_cols の間 Event を見ない。

Signal.__slots__ へ __weakref__ を追加。無いと weakref.ref(sig) が TypeError で、
G2/G5 の独立オラクルが書けない (resolved_keys は transient に構造的に盲目・
bytes_held は pin されない列に無関係 = spec §10 で使用禁止)。コストはポインタ
1 本 x 常駐 4,324 個 = ~35 KB。

export() は 1 行も変えていない (Task 4 の橋がそのまま走る) ので挙動は不変。
テスト 33 本。sabotage 実測: 帳簿つき resolve へ委譲=4 RED (値ベースの 2 本は
緑のまま)・touch 追加=1 RED・__weakref__ 除去=3 RED (TypeError)・参照保持=1 RED
(出力テストは全て緑 = G2/G5 が代替不能であることの実証)・キャンセル点除去=各 1 RED・
チャンネル局所除去=1 RED・下限クランプ除去=1 RED・master dedup 除去=1 RED・
ガード位置の後退=既存 container guard の 1 件のみ RED。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 7: 多段マージ＋橋の撤去＋ゴールデン再駆動

**Files:**
- Modify: `src/valisync/core/export/csv_exporter.py`（`_MERGE_FAN_IN` / `merge_stage_count` / `estimate_output_bytes` / `_require_disk_space` / `_merge_one_stage` / `_export_request` を追加し、`export()` を最終形へ。**`_rows_unified_timeline` / `_rows_shared_timeline` / `_atomic_write` / `_require_single_value_columns` / Task 4 の橋を削除**）
- Modify: `src/valisync/core/session.py:502`（`export_csv` を keys ＋ `resolve_signal_transient` 配線へ）＋ `:163`（`CsvExporter(budget_fn=...)` の配線）
- Test: `tests/core/export/test_merge_pipeline.py`（新規）
- Test: `tests/core/export/test_block_equivalence.py`（新規・ブロック幅を変えても出力バイトが不変）
- Test: `tests/core/export/test_export_scale_invariance.py`（新規・G3）
- Modify: `tests/golden_csv_cases.py`（`BLOCK_COLS_VARIANTS = (None, 1, 2)` へ拡張・`export_case(case, work_dir, block_cols: int | None = None) -> bytes` へ引数を足し内部を `CsvExporter(block_cols=block_cols).export(...)` に。**ケース定義と期待バイトは 1 文字も変えない**）
- Modify: `tests/test_golden_csv.py`（`test_golden_bytes_match` を `block_cols` 2 軸 parametrize へ・**期待バイトは共通**〔`_golden_path(case_id).read_bytes()` のまま〕・`test_block_cols_handoff_is_not_forgotten` が緑になることを確認し supersede コメントを残す）
- **触らない**: `tests/test_export.py` / `tests/test_csv_export_options.py` / `tests/core/test_export_container_guard.py`（**無編集で全数緑**が本タスクの主受け入れ条件）

**`CsvExportOptions.header_names` の裁定（Task 4 の引き継ぎ (3) への回答）**: **撤去しない**。legacy overload（`export(signals, path, use_unified_timeline, options)`）の**唯一のヘッダ搬送路**として残置する — 撤去すると `test_csv_export_options.py:158-171` の期待が動き（Global Constraints 違反）、かつゴールデン g01/g03-g11 の 10 本が GUI 形ヘッダから raw 名へ退行する（Task 2 の変異 M9 がこの依存を実証済み）。spec §5.1-4 [MG-7] の「別持ちを廃止」は **`ExportRequest` 経路に限って達成**と読み替える（新境界では `header_resolver` が唯一の真実で `header_names` は読まれない）。**この supersede を spec §5.1-4 と docs/design.md 決定履歴へ記録する**（Step 6 のコミット時）。完全撤去は legacy overload 退役時の別増分。

**Interfaces:**
- Consumes: Task 5（`union_timeline` / `canonical_master` / `row_range`）・Task 6（`scan_masters` / `block_columns` / `plan_blocks` / `_write_time_temp` / `_write_block_temp` / `ExportCancelled` / `Session.resolve_signal_transient` / `ChannelSampleCache.available_bytes`）・Task 4（`ExportRequest` / `Session.export_csv` の keys 署名 / 橋）・T-G（`_fmt_value` / `_join` / BOM 付き書き出し）
- Produces（Task 8-11 がこれに対して書く）:
  - `_MERGE_FAN_IN = 512`（module 定数）
  - `merge_stage_count(n_inputs: int, fan_in: int) -> int`
  - `estimate_output_bytes(n_rows: int, n_columns: int) -> int`（T-UX の見積が係数を差し替える起点）
  - `CsvExporter.export(request: ExportRequest, resolve: Callable[[str], Signal | None], *, progress: Callable[[int, int], None] | None = None, cancel: threading.Event | None = None) -> None`（共有契約の最終形）＋ legacy 形 `export(signals: list[Signal], output_path: Path, use_unified_timeline: bool = False, options: CsvExportOptions | None = None)` の overload
  - `progress` の単位: `total = 1 (時刻 temp) + ブロック数 + マージ段数`

**実装前に必ず確定させること:**

```
ls tests/core/export/
grep -rln "golden" tests/ --include=*.py
grep -n "def export" -A 30 src/valisync/core/export/csv_exporter.py     # T-API の dispatch 形
grep -n "def export_csv" -A 20 src/valisync/core/session.py
```
T-API がどの形で「legacy list 形」と「ExportRequest 形」を分岐しているかを読み、**本タスクは中身の置換だけ**にする（形が違えば以下のコードを T-API の形へ合わせる。分岐そのものが無い＝既存 40 サイトが編集されている場合は**停止して報告**）。

**橋の撤去で最も壊しやすい点**: legacy 形（`export([sig], path)`）を旧実装に残したまま request 形だけをブロック化すると、`_rows_unified_timeline` の `dict(zip(...tolist()))`（実測 97 B/サンプル・20 列で Win32 working set 2.14 GiB）が**生き残ったまま緑**になる。legacy 形も同じ内部関数へ落とすこと。落とせば `tests/test_csv_export_options.py` の 19 本 ＋ `tests/test_export.py` の 5 本 ＋ container guard 8 本が**そのままブロックパイプラインの回帰網**になる。

**設計の裏取り（プロトタイプ実測・2026-08-01）**: 「生 master から union → `row_range` → `column_on_union` → 1 セルずつ書式化」が現行実装と **byte-identical** であることを 12 fixture（union / union+範囲 / 共有 / 非単調 / 重複 ts / 非有限 / ULP 分裂 / len 0 混在 / unit 行 / precision+decimal 変更）で実測済み（mismatches: 0）。Task 7 はこの等価性を test-lock する作業であり、探索ではない。

---

- [ ] **Step 1: 失敗テストを書く**

ベースラインを記録。Step 6 で **+26** になることを確認する。

`tests/core/export/test_merge_pipeline.py` を新規作成:

```python
"""多段マージと export() の最終形 (E-4b Task 7・spec §5.3)。

**FD 天井は本環境実測 8,189 本** (CPython 3.13.7 / Win11)。prod 3 ファイル比較の
全列エクスポートは block 数 ~8,253 で、単段の横マージは**確実に**天井を超える
(MG-2) — だから多段。
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.csv_exporter import (
    _MERGE_FAN_IN,
    CsvExporter,
    CsvExportOptions,
    ExportCancelled,
    ExportRequest,
    merge_stage_count,
)
from valisync.core.models import Signal


def _sig(name: str, ts: list[float], vs: list[float], unit: str = "") -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="test",
        bus_type="",
        source_file="",
        metadata={"unit": unit} if unit else {},
    )


def _request(signals: list[Signal], out: Path, **opts: object) -> ExportRequest:
    return ExportRequest(
        keys=tuple(s.name for s in signals),
        output_path=out,
        options=CsvExportOptions(**opts),  # type: ignore[arg-type]
        header_resolver=list,
    )


def _resolve(signals: list[Signal]):  # type: ignore[no-untyped-def]
    table = {s.name: s for s in signals}
    return lambda key: table.get(key)


def _read(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8-sig").splitlines()


# ─── 段数の算術 ───────────────────────────────────────────────────────────────


def test_merge_stage_count_matches_the_prod_shape() -> None:
    """prod 3 ファイル全列 = block ~8,253 + 時刻 1 -> F=512 で 2 段 (MG-2)。"""
    assert merge_stage_count(8254, _MERGE_FAN_IN) == 2
    assert merge_stage_count(_MERGE_FAN_IN, _MERGE_FAN_IN) == 1
    assert merge_stage_count(_MERGE_FAN_IN + 1, _MERGE_FAN_IN) == 2
    assert merge_stage_count(2, _MERGE_FAN_IN) == 1


def test_merge_stage_count_is_at_least_one() -> None:
    """入力 1 本でも 1 段走る (ヘッダ/単位行を書くのが最終段の役目)。"""
    assert merge_stage_count(1, _MERGE_FAN_IN) == 1


def test_merge_never_opens_more_than_fan_in_plus_one(tmp_path: Path) -> None:
    """同時 open の上界 = F + 1 (実測天井 8,189 に対し 1 桁の余裕)。"""
    n = 40
    signals = [_sig(f"s{i}", [0.0, 1.0], [float(i), float(i) + 0.5]) for i in range(n)]
    out = tmp_path / "o.csv"
    opened: list[int] = []
    live = 0

    import builtins

    original = builtins.open

    def counting_open(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal live
        handle = original(*args, **kwargs)
        live += 1
        opened.append(live)
        close = handle.close

        def wrapped_close() -> None:
            nonlocal live
            live -= 1
            close()

        handle.close = wrapped_close  # type: ignore[method-assign]
        return handle

    builtins.open = counting_open  # type: ignore[assignment]
    try:
        CsvExporter(block_cols=1, merge_fan_in=4).export(
            _request(signals, out), _resolve(signals)
        )
    finally:
        builtins.open = original  # type: ignore[assignment]
    assert max(opened) <= 4 + 1
    assert len(_read(out)) == 3  # header + 2 rows


# ─── 行数一致 assert (MG-6) ───────────────────────────────────────────────────


def test_merge_loud_fails_when_an_input_has_fewer_rows(tmp_path: Path) -> None:
    """ブロック writer のバグ (行数のずれ) を黙って横に繋がない。

    ずれたまま繋ぐと、ある列から先が **1 行ずれた別の時刻の値**になる —
    例外も長さ検証も出ないサイレント誤データ。
    """
    exporter = CsvExporter()
    a = tmp_path / "a.tmp"
    b = tmp_path / "b.tmp"
    a.write_text("1\n2\n3\n", encoding="utf-8")
    b.write_text("4\n5\n", encoding="utf-8")  # 1 行少ない
    with pytest.raises(ValueError, match="行数が一致しません"):
        exporter._merge_one_stage(
            [a, b], out_dir=tmp_path, token="t", stage=0, prefix_lines=(), opts=CsvExportOptions(), cancel=None
        )


def test_merge_loud_fails_when_an_input_has_more_rows(tmp_path: Path) -> None:
    exporter = CsvExporter()
    a = tmp_path / "a.tmp"
    b = tmp_path / "b.tmp"
    a.write_text("1\n2\n", encoding="utf-8")
    b.write_text("4\n5\n6\n", encoding="utf-8")
    with pytest.raises(ValueError, match="行数が一致しません"):
        exporter._merge_one_stage(
            [a, b], out_dir=tmp_path, token="t", stage=0, prefix_lines=(), opts=CsvExportOptions(), cancel=None
        )


# ─── 出力の形 ─────────────────────────────────────────────────────────────────


def test_multi_stage_merge_produces_the_same_file_as_single_stage(
    tmp_path: Path,
) -> None:
    signals = [_sig(f"s{i}", [0.0, 1.0, 2.0], [float(i), float(i), float(i)]) for i in range(9)]
    wide = tmp_path / "wide.csv"
    deep = tmp_path / "deep.csv"
    CsvExporter(block_cols=9, merge_fan_in=512).export(
        _request(signals, wide), _resolve(signals)
    )
    CsvExporter(block_cols=1, merge_fan_in=2).export(
        _request(signals, deep), _resolve(signals)
    )
    assert wide.read_bytes() == deep.read_bytes()


def test_unit_row_comes_from_the_sideband_not_a_second_resolve(
    tmp_path: Path,
) -> None:
    """マージ段での再 resolve は禁止 (330k 再解決 = ~390 MB の一撃・MG-4)。"""
    a = _sig("a", [0.0], [1.0], unit="km/h")
    b = _sig("b", [0.0], [2.0], unit="rpm")
    out = tmp_path / "o.csv"
    calls: list[str] = []
    table = {"a": a, "b": b}

    def resolve(key: str) -> Signal | None:
        calls.append(key)
        return table.get(key)

    CsvExporter(block_cols=1).export(
        _request([a, b], out, unit_row=True), resolve
    )
    assert _read(out) == ["timestamp,a,b", "s,km/h,rpm", "0.0,1.0,2.0"]
    # 前走査 (scan_masters) 1 回 + ブロック 1 回 = 列あたり 2 回。マージ段で
    # 3 回目が出たら再 resolve が入っている。
    assert calls.count("a") == 2 and calls.count("b") == 2


def test_export_leaves_no_temp_files_on_success(tmp_path: Path) -> None:
    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    out = tmp_path / "o.csv"
    CsvExporter(block_cols=1, merge_fan_in=2).export(_request([a], out), _resolve([a]))
    assert [p.name for p in tmp_path.iterdir()] == ["o.csv"]


def test_cancel_removes_every_temp_and_leaves_no_output(tmp_path: Path) -> None:
    """G6: 「temp が一度は存在した」ことを観測してから消滅を assert する。"""
    signals = [
        _sig(f"s{i}", np.arange(50.0).tolist(), np.arange(50.0).tolist())
        for i in range(8)
    ]
    out = tmp_path / "o.csv"
    cancel = threading.Event()
    saw_temp: list[int] = []

    def progress(done: int, total: int) -> None:
        saw_temp.append(len([p for p in tmp_path.iterdir() if p.name != "o.csv"]))
        if done >= 2:
            cancel.set()

    with pytest.raises(ExportCancelled):
        CsvExporter(block_cols=1).export(
            _request(signals, out), _resolve(signals), progress=progress, cancel=cancel
        )
    assert max(saw_temp) > 0, "temp が一度も存在していない (上界 0 の空虚形)"
    assert list(tmp_path.iterdir()) == []


def test_disk_space_shortage_is_rejected_before_writing(
    tmp_path: Path, monkeypatch
) -> None:
    """D5: 2.3 x 推定出力を満たさないなら開始しない。"""
    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    out = tmp_path / "o.csv"
    monkeypatch.setattr(
        shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(0, 0, 0)
    )
    with pytest.raises(ValueError, match="空き容量"):
        CsvExporter().export(_request([a], out), _resolve([a]))
    assert list(tmp_path.iterdir()) == []


# ─── progress ─────────────────────────────────────────────────────────────────


def test_progress_units_are_blocks_plus_merge_stages(tmp_path: Path) -> None:
    signals = [_sig(f"s{i}", [0.0, 1.0], [1.0, 2.0]) for i in range(4)]
    out = tmp_path / "o.csv"
    seen: list[tuple[int, int]] = []
    CsvExporter(block_cols=1, merge_fan_in=2).export(
        _request(signals, out), _resolve(signals), progress=seen.append
    )
    total = seen[0][1]
    # 時刻 temp 1 + ブロック 4 = 5 本 -> F=2 なら 3 段
    assert total == 1 + 4 + 3
    assert [d for d, _t in seen] == list(range(1, total + 1))


# ─── オフスレッド性 (G7 の core 側の半分) ─────────────────────────────────────


def test_export_runs_entirely_on_the_calling_thread(tmp_path: Path) -> None:
    """core は自分でスレッドを起こさない (worker 側の責務・部分並列化の検出)。"""
    a = _sig("a", [0.0, 1.0], [1.0, 2.0])
    out = tmp_path / "o.csv"
    threads: set[int] = set()

    def resolve(key: str) -> Signal | None:
        threads.add(threading.get_ident())
        return a if key == "a" else None

    CsvExporter().export(_request([a], out), resolve)
    assert threads == {threading.get_ident()}
```

`tests/core/export/test_block_equivalence.py` を新規作成:

```python
"""ブロック幅・fan-in を変えても出力バイトが変わらないこと (E-4b Task 7)。

**ゴールデンの補完**: ゴールデン (T-G) が「正しいバイト」を固定するのに対し、
ここは「どう分割しても同じバイト」を固定する。ブロック境界のオフバイワン・
マージ順の入れ替え・断片の取りこぼしはここで RED になる。

fixture 軸は spec §7.1 と同一 (単一/統合 x 範囲 x 欠測 x 非有限 x 非単調 x
重複 ts x len 0 x ULP 分裂 x unit x delimiter/decimal/precision)。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.csv_exporter import (
    CsvExporter,
    CsvExportOptions,
    ExportRequest,
)
from valisync.core.models import Signal


def _sig(name: str, ts: list[float], vs: list[float], unit: str = "") -> Signal:
    return Signal(
        name=name,
        timestamps=np.array(ts, dtype=np.float64),
        values=np.array(vs, dtype=np.float64),
        file_format="test",
        bus_type="",
        source_file="",
        metadata={"unit": unit} if unit else {},
    )


def _case_union() -> tuple[list[Signal], dict[str, object]]:
    return [_sig("a", [0.0, 2.0], [10.0, 12.0]), _sig("b", [1.0, 3.0], [21.0, 23.0])], {}


def _case_range() -> tuple[list[Signal], dict[str, object]]:
    sigs, _ = _case_union()
    return sigs, {"time_start": 1.0, "time_end": 2.0}


def _case_shared() -> tuple[list[Signal], dict[str, object]]:
    return [
        _sig("c", [0.0, 1.0], [1.0, 2.0]),
        _sig("d", [0.0, 1.0], [3.0, 4.0]),
    ], {"use_unified_timeline": False}


def _case_non_monotonic() -> tuple[list[Signal], dict[str, object]]:
    return [_sig("x", [0.0, 2.0, 1.0], [10.0, 30.0, 20.0])], {}


def _case_duplicate_ts() -> tuple[list[Signal], dict[str, object]]:
    return [_sig("dup", [0.0, 1.0, 1.0, 2.0], [1.0, 2.0, 3.0, 4.0])], {}


def _case_non_finite() -> tuple[list[Signal], dict[str, object]]:
    return [_sig("e", [0.0, 1.0, 2.0], [np.nan, np.inf, -np.inf])], {}


def _case_len_zero() -> tuple[list[Signal], dict[str, object]]:
    return [_sig("a", [0.0, 1.0], [1.0, 2.0]), _sig("z", [], [])], {}


def _case_ulp() -> tuple[list[Signal], dict[str, object]]:
    slow = [i * 0.1 for i in range(12)]
    fast = [i * 0.01 for i in range(120)]
    return [
        _sig("slow", slow, [float(i) for i in range(12)]),
        _sig("fast", fast, [float(i) for i in range(120)]),
    ], {}


def _case_units() -> tuple[list[Signal], dict[str, object]]:
    return [
        _sig("a", [0.0, 1.0], [1.0, 2.0], unit="km/h"),
        _sig("b", [0.0, 1.0], [3.0, 4.0]),
    ], {"unit_row": True}


def _case_formats() -> tuple[list[Signal], dict[str, object]]:
    sigs, _ = _case_union()
    return sigs, {"delimiter": ";", "decimal": ",", "precision": 3}


def _case_many_columns() -> tuple[list[Signal], dict[str, object]]:
    return [
        _sig(f"s{i}", [0.0, 1.0, 2.0], [float(i), float(i) * 2, float(i) * 3])
        for i in range(17)
    ], {}


_CASES = {
    "union": _case_union,
    "range": _case_range,
    "shared": _case_shared,
    "non_monotonic": _case_non_monotonic,
    "duplicate_ts": _case_duplicate_ts,
    "non_finite": _case_non_finite,
    "len_zero": _case_len_zero,
    "ulp": _case_ulp,
    "units": _case_units,
    "formats": _case_formats,
    "many_columns": _case_many_columns,
}


def _export(
    tmp_path: Path, name: str, block_cols: int | None, fan_in: int | None
) -> bytes:
    signals, overrides = _CASES[name]()
    out = tmp_path / f"{name}_{block_cols}_{fan_in}.csv"
    table = {s.name: s for s in signals}
    CsvExporter(block_cols=block_cols, merge_fan_in=fan_in).export(
        ExportRequest(
            keys=tuple(s.name for s in signals),
            output_path=out,
            options=CsvExportOptions(**overrides),  # type: ignore[arg-type]
            header_resolver=list,
        ),
        table.get,
    )
    return out.read_bytes()


@pytest.mark.parametrize("name", sorted(_CASES))
@pytest.mark.parametrize(("block_cols", "fan_in"), [(1, 2), (2, 3), (16, 512), (512, 512)])
def test_output_bytes_are_independent_of_block_width_and_fan_in(
    tmp_path: Path, name: str, block_cols: int, fan_in: int
) -> None:
    reference = _export(tmp_path, name, None, None)
    assert _export(tmp_path, name, block_cols, fan_in) == reference


def test_reference_output_is_not_trivially_empty(tmp_path: Path) -> None:
    """反 vacuous: 参照側が空バイトなら上の全 parametrize が恒真になる。"""
    for name in _CASES:
        assert len(_export(tmp_path, name, None, None)) > 0
```

`tests/core/export/test_export_scale_invariance.py` を新規作成:

```python
"""G3: ブロック k と k+1 の増分が「ブロック 1 個分」に対して +/-20% (spec §6)。

**計測は tracemalloc** (numpy のデータ確保も追跡される — 実測で 16 MB の
ndarray が get_traced_memory に出ることを確認済み)。psutil は本番/dev いずれの
依存にも無いので、USS 版は VALISYNC_MEMTEST + importorskip の opt-in に留める
(tests/core/loaders/test_mdf_loader_master_retention.py と同型)。

2 ブロックでは傾き検定にならないので **ブロック数 >= 8** で測る。
"""

from __future__ import annotations

import os
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

from valisync.core.export.csv_exporter import (
    CsvExporter,
    CsvExportOptions,
    ExportRequest,
)
from valisync.core.models import Signal

_N_COLUMNS = 16
_BLOCK_COLS = 2
_N_ROWS = 20_000
_N_BLOCKS = _N_COLUMNS // _BLOCK_COLS
# 1 ブロックが同時に抱える実体 (block_columns の式と同じ 9 B/セル)
_PER_BLOCK_BYTES = _BLOCK_COLS * _N_ROWS * 9


def _run(tmp_path: Path) -> list[int]:
    master = np.arange(_N_ROWS, dtype=np.float64)
    master.flags.writeable = False
    values = np.arange(_N_ROWS, dtype=np.float64)

    def resolve(key: str) -> Signal | None:
        return Signal(
            name=key,
            timestamps=master,
            values=values.copy(),
            file_format="t",
            bus_type="",
            source_file="",
            metadata={"physical_channel": key},
        )

    samples: list[int] = []

    def progress(done: int, total: int) -> None:
        del total
        samples.append(tracemalloc.get_traced_memory()[0])

    request = ExportRequest(
        keys=tuple(f"c{i}" for i in range(_N_COLUMNS)),
        output_path=tmp_path / "big.csv",
        options=CsvExportOptions(),
        header_resolver=list,
    )
    tracemalloc.start()
    try:
        CsvExporter(block_cols=_BLOCK_COLS).export(request, resolve, progress=progress)
    finally:
        tracemalloc.stop()
    # 先頭 1 件は時刻 temp、その後の _N_BLOCKS 件がブロック境界。
    return samples[1 : 1 + _N_BLOCKS]


def test_memory_per_block_does_not_grow_with_the_block_index(tmp_path: Path) -> None:
    marks = _run(tmp_path)
    assert len(marks) == _N_BLOCKS >= 8
    slope = (marks[-1] - marks[0]) / (len(marks) - 1)
    assert abs(slope) <= 0.2 * _PER_BLOCK_BYTES, (
        f"ブロックあたり {slope:,} B 積み上がっている "
        f"(許容 {0.2 * _PER_BLOCK_BYTES:,.0f} B): {marks}"
    )


def test_the_harness_actually_observes_a_block_sized_footprint(
    tmp_path: Path,
) -> None:
    """反 vacuous: 計測が全部 0 なら傾き検定は恒真になる。"""
    marks = _run(tmp_path)
    assert max(marks) >= _PER_BLOCK_BYTES * 0.5, marks


@pytest.mark.skipif(
    not os.environ.get("VALISYNC_MEMTEST"), reason="opt-in (USS 実測・psutil 要)"
)
def test_uss_per_block_does_not_grow(tmp_path: Path) -> None:
    """spec G3 の字義どおりの USS 版 (opt-in)。CI では tracemalloc 版が門番。"""
    psutil = pytest.importorskip("psutil")
    proc = psutil.Process()
    marks: list[int] = []
    master = np.arange(_N_ROWS, dtype=np.float64)
    master.flags.writeable = False

    def resolve(key: str) -> Signal | None:
        return Signal(
            name=key,
            timestamps=master,
            values=np.arange(_N_ROWS, dtype=np.float64),
            file_format="t",
            bus_type="",
            source_file="",
            metadata={"physical_channel": key},
        )

    def progress(done: int, total: int) -> None:
        del total
        marks.append(proc.memory_full_info().uss)

    CsvExporter(block_cols=_BLOCK_COLS).export(
        ExportRequest(
            keys=tuple(f"c{i}" for i in range(_N_COLUMNS)),
            output_path=tmp_path / "big.csv",
            options=CsvExportOptions(),
            header_resolver=list,
        ),
        resolve,
        progress=progress,
    )
    block_marks = marks[1 : 1 + _N_BLOCKS]
    slope = (block_marks[-1] - block_marks[0]) / (len(block_marks) - 1)
    assert abs(slope) <= 0.2 * _PER_BLOCK_BYTES, block_marks
```

**T-G のゴールデン駆動テストへ `block_cols` の parametrize を足す**（期待バイトは 1 バイトも変えない）。T-G の実名は `tests/golden_csv_cases.py::export_case` / `BLOCK_COLS_VARIANTS` と `tests/test_golden_csv.py::test_golden_bytes_match`（Task 2 Produces で確定済み）。

`tests/golden_csv_cases.py`:

```python
#: Task 7 が列ブロック化したので、ゴールデンは **複数ブロック（境界跨ぎ）でも
#: 駆動する**（spec G1）。None = 自動決定（= 1 ブロック相当）。
BLOCK_COLS_VARIANTS: tuple[int | None, ...] = (None, 1, 2)


def export_case(case: GoldenCase, work_dir: Path, block_cols: int | None = None) -> bytes:
    inp = case.build(work_dir)
    try:
        out = work_dir / f"{case.case_id}.csv"
        CsvExporter(block_cols=block_cols).export(
            inp.signals, out, inp.use_unified_timeline, build_options(inp)
        )
        return out.read_bytes()
    finally:
        inp.close()
```

`tests/test_golden_csv.py`（**期待バイトは共通** — parametrize されるのは駆動側だけ）:

```python
# E-4b Task 7 supersede: block_cols を注入する 2 軸目を足した (spec G1
# 「ゴールデンは複数ブロック・境界跨ぎで駆動」)。**期待バイトは 1 バイトも
# 変えていない** — 全変種が同じ golden ファイルと突き合わされる。
@pytest.mark.parametrize("block_cols", BLOCK_COLS_VARIANTS, ids=lambda b: f"bc{b}")
@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.case_id)
def test_golden_bytes_match(
    case: GoldenCase, block_cols: int | None, tmp_path: Path
) -> None:
    expected = _golden_path(case.case_id).read_bytes()
    actual = export_case(case, tmp_path, block_cols=block_cols)
    assert actual == expected, _diff_message(case, expected, actual)
```

`BLOCK_COLS_VARIANTS` を `(None, 1, 2)` へ広げた瞬間に `test_block_cols_handoff_is_not_forgotten`（`CsvExporter.__init__` の署名に `block_cols` が現れたか）が**同時に緑へ倒れる**ことを確認する — 片方だけだとこのガードが RED になる（それが「忘れたら落ちる」の実効性の証明）。

**ゴールデンの再生成は禁止**（G1）。`block_cols=1` で 8 ブロック以上になる case が最低 1 本あることを確認する（`g05` は 5 列・`g08` は 6 列なので、無ければ列 8 本以上の case を**新規に 1 本足す**＝既存ゴールデンは触らない）。

- [ ] **Step 2: 失敗を確認**

```
uv run pytest tests/core/export/ -q
```
Expected: `test_merge_pipeline.py` は `merge_stage_count` / `_merge_one_stage` が無く collection error。`test_block_equivalence.py` / `test_export_scale_invariance.py` は `CsvExporter(block_cols=...)` を受けても `export()` が橋のままなので、**ブロック幅を変えても同じ**＝一部は緑になりうる。**緑になる項目を先に記録する**（Step 4 で「実際に効いた」ことを言うため。`progress` を受け取らない橋では `test_progress_units_*` と scale invariance が RED になるので、そこが本タスクの honest-RED）。

- [ ] **Step 3: 実装**

`src/valisync/core/export/csv_exporter.py`:

```python
# 同時 open = F + 1 本。**本環境実測の FD 天井は 8,189 本** (OSError errno 24・
# CPython 3.13.7 / Win11) で、prod 3 ファイル比較の全列エクスポートは block 数
# ~8,253 = 単段では確実に超える (MG-2)。512 なら 8,254 本が 2 段で畳める。
_MERGE_FAN_IN = 512
# 中間 temp を含むディスクピークの見積係数 (spec §5.3: 出力 x (1 + 1/F の等比和 +
# 安全率))。**設計値であって実測値ではない** — T-M で検証する (§9-5)。
#
# **この 1 つが唯一の実体**（`_DISK_HEADROOM` という private 名は作らない）:
# GUI 側の門番 (`estimate.disk_shortfall`) が同じ係数を別に持つと、Task 11 の検定で
# 片方だけ更新されたときに「GUI の D5 を通過 -> 確認 Yes -> core で ValueError」
# という UX 破綻窓が開く。`estimate.py` はこれを import して再輸出する。
TEMP_AMPLIFICATION = 2.3
# 1 セルあたりの推定バイト (区切り込み)。spec §1 の訂正済み見積 (uint8 量子化の
# repr 長 4.57 文字・float64 は ~17 文字) の中間を採った**開始前の粗い門番**。
# **Task 11 が単価 3 定数 (estimate.py の チャンネル単価/セル単価/平均セル長) と
# 同時にこれも prod 1 点で検定する** — core の門番 (ここ) が GUI の門番より
# 緩いと、GUI が通した要求を core が弾く順序逆転が起きる (Task 8 Step 4 の
# 上界包含がその構造的な防止策)。
_EST_BYTES_PER_CELL = 12


def merge_stage_count(n_inputs: int, fan_in: int) -> int:
    """*n_inputs* 本を fan-in *fan_in* で畳むのに要する段数 (最低 1 段)。

    最低 1 段なのは、**ヘッダ行と単位行を書くのが最終段の役目**だから。入力が
    1 本でも 1 段走らせて先頭に付ける (最終段の後に別パスを足すと出力全体を
    もう 1 回コピーすることになり、prod の 10 GB では丸ごと 1 往復になる)。
    """
    stages = 0
    remaining = n_inputs
    while remaining > 1:
        remaining = -(-remaining // fan_in)  # ceil
        stages += 1
    return max(1, stages)


def estimate_output_bytes(n_rows: int, n_columns: int) -> int:
    """出力サイズの粗い推定 (時刻列を含む)。T-UX が係数を実測で差し替える起点。"""
    return n_rows * (n_columns + 1) * _EST_BYTES_PER_CELL
```

`CsvExporter` の `export()` を最終形へ（**T-API の dispatch の形に合わせる**）:

```python
    def export(  # type: ignore[override]
        self,
        request: ExportRequest | list[Signal],
        resolve: Callable[[str], Signal | None] | Path | None = None,
        use_unified_timeline: bool = False,
        options: CsvExportOptions | None = None,
        *,
        progress: Callable[[int, int], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        """CSV を書き出す。

        正準形は ``export(request, resolve, progress=..., cancel=...)``。
        legacy 形 ``export(signals, output_path, use_unified_timeline, options)``
        は**同じパイプラインへ落とす** — 旧一括実装を残すと
        ``dict(zip(...tolist()))`` (実測 97 B/サンプル・20 列で working set
        2.14 GiB) が legacy 経路にだけ生き残り、既存テストが全部緑のままそこを
        通り続ける。
        """
        if isinstance(request, ExportRequest):
            assert not isinstance(resolve, Path) and resolve is not None
            self._export_request(request, resolve, progress, cancel)
            return
        # legacy 形: 名前の重複 (同名 Signal 2 本) が dict で潰れないよう、位置を
        # そのままキーにする。ヘッダは元の name を返す resolver で復元する。
        signals = list(request)
        assert isinstance(resolve, Path)
        keys = tuple(f"#{i}" for i in range(len(signals)))
        table = {k: s for k, s in zip(keys, signals, strict=True)}
        opts = options if options is not None else CsvExportOptions()
        # **`options.header_names` を読む**のがここの要点 (旧 `_header_rows` の
        # 「header_names があればそれ・無ければ signal.name」を逐語で保存する)。
        # 読まないと golden driver が GUI 形ヘッダを header_names へ詰めている
        # 10 本 (g01/g03-g11) が raw 名へ退行し、既存
        # test_csv_export_options.py:158-171 も RED になる。header_names は
        # legacy overload の唯一のヘッダ搬送路として**残置する** (上の裁定)。
        if opts.header_names is not None:
            fixed = list(opts.header_names)
            resolver: Callable[[Sequence[str]], list[str]] = lambda _ks: list(fixed)
        else:
            resolver = lambda ks: [table[k].name for k in ks]
        self._export_request(
            ExportRequest(
                keys=keys,
                output_path=Path(resolve),
                options=replace(opts, use_unified_timeline=use_unified_timeline),
                header_resolver=resolver,
            ),
            table.get,
            progress,
            cancel,
        )

    def _export_request(
        self,
        request: ExportRequest,
        resolve: Callable[[str], Signal | None],
        progress: Callable[[int, int], None] | None,
        cancel: threading.Event | None,
    ) -> None:
        opts = request.options
        # **空リクエストの loud-fail はここが本体**（橋の撤去で消える検査の移設）。
        # 無いと `union_timeline([])` が長さ 0 を返し → ブロック 0 本 → 「ヘッダ
        # だけのファイルを成功として書く」へ degrade する。Task 2 の
        # test_empty_selection_fails_loudly_and_writes_no_file と Task 4 の
        # test_empty_request_fails_loudly が縛っているのはまさにこの分岐。
        # 注: 「列 >= 1 本だが範囲外 = ヘッダのみのファイル」は**別契約**で、
        # 現行どおり成功として書く（空**列**とは区別する）。
        if not request.keys and not request.extra_signals:
            raise ValueError(EXPORT_EMPTY_REQUEST_ERROR)
        output_path = Path(request.output_path)
        out_dir = output_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        columns: list[tuple[str, Signal | None]] = [(k, None) for k in request.keys]
        columns.extend((s.name, s) for s in request.extra_signals)

        # --- 前走査 -> union -> 前提検証 -> 行範囲 (すべて値を読まない) --------
        scan = scan_masters(columns, resolve)
        # **ヘッダ長の検査は temp を 1 バイトも書く前**（橋の撤去で消える検査の
        # 移設）。resolver 呼び出しを最終段まで遅らせると、ヘッダ長不一致が
        # 「全ブロックを書き切ってから落ちる」形になり、Task 4 の
        # test_header_resolver_length_mismatch_fails_loudly が縛っている
        # 「書かずに落ちる」が ~18 分の無駄と temp 生成を伴う形へ degrade する。
        names = list(request.header_resolver(request.keys))
        if len(names) != len(request.keys):
            raise ValueError(
                EXPORT_HEADER_LENGTH_ERROR_TMPL.format(
                    got=len(names), want=len(request.keys)
                )
            )
        union = union_timeline(scan.masters)
        if not opts.use_unified_timeline:
            self._require_shared_timeline(scan.masters)
        lo, hi = row_range(union, opts.time_start, opts.time_end)
        union_view = union[lo:hi]

        budget = (
            self._budget_fn() if self._budget_fn is not None
            else _DEFAULT_EXPORT_BUDGET_BYTES
        )
        block_cols = self._block_cols_override or block_columns(
            len(union_view), scan.max_master_len, budget
        )
        fan_in = self._merge_fan_in or _MERGE_FAN_IN
        blocks = plan_blocks(scan.runs, block_cols)
        _require_disk_space(out_dir, len(union_view), len(columns))

        n_units = 1 + len(blocks) + merge_stage_count(1 + len(blocks), fan_in)
        done = 0

        def tick() -> None:
            nonlocal done
            done += 1
            if progress is not None:
                progress(done, n_units)

        token = uuid.uuid4().hex[:12]
        temps: list[Path] = []
        try:
            # --- 時刻列 (幅 1 のブロック・マージ器に特別扱いを作らない) --------
            time_temp = out_dir / f".tmp_export_{token}_time.csv"
            temps.append(time_temp)
            self._write_time_temp(union_view, opts, time_temp, cancel)
            tick()

            # --- 列ブロック -----------------------------------------------------
            units: list[str] = []
            for i, (start, stop) in enumerate(blocks):
                _check_cancel(cancel)  # ブロック境界
                temp = out_dir / f".tmp_export_{token}_b{i:05d}.csv"
                temps.append(temp)
                units.extend(
                    self._write_block_temp(
                        columns[start:stop],
                        resolve=resolve,
                        union_view=union_view,
                        opts=opts,
                        temp_path=temp,
                        cancel=cancel,
                    )
                )
                tick()

            # --- ヘッダ/単位行 (keys から導出・単位は側帯から) -----------------
            # `names` は temp を書く**前**に解決済み（長さ検査も済み）。ここで
            # resolver を呼び直さない — 2 回呼ぶと副作用つき resolver で
            # ヘッダと検査対象がずれる。
            names.extend(s.name for s in request.extra_signals)
            prefix = [_join([_TIMESTAMP_HEADER, *names], opts)]
            if opts.unit_row:
                prefix.append(_join([_TIMESTAMP_UNIT, *units], opts))

            # --- 多段マージ -----------------------------------------------------
            stages = merge_stage_count(len(temps), fan_in)
            current = list(temps)
            for stage in range(stages):
                is_last = stage == stages - 1
                outputs: list[Path] = []
                for chunk_start in range(0, len(current), fan_in):
                    chunk = current[chunk_start : chunk_start + fan_in]
                    merged = self._merge_one_stage(
                        chunk,
                        out_dir=out_dir,
                        token=token,
                        stage=stage,
                        prefix_lines=tuple(prefix) if is_last else (),
                        opts=opts,
                        cancel=cancel,
                    )
                    temps.append(merged)
                    outputs.append(merged)
                    for spent in chunk:
                        spent.unlink(missing_ok=True)
                        temps.remove(spent)
                current = outputs
                tick()
            final_temp = current[0]
            os.replace(final_temp, output_path)
            temps.remove(final_temp)
        finally:
            # B6「何も残さない」: 成功でも失敗でもキャンセルでも temp は残さない。
            for leftover in temps:
                try:
                    leftover.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _require_shared_timeline(masters: Sequence[np.ndarray]) -> None:
        """全 master が同一時間軸であることを **値を読まずに** 検証する (MG-6)。

        比較は ``canonical_master`` 同士 — 旧実装は ``sorted_view()[0]`` を比べて
        いたので、生 master のまま比べると「非単調だが整列すれば同じ」信号を
        誤って拒否する。
        """
        if not masters:
            return
        base = canonical_master(masters[0])
        for master in masters[1:]:
            other = canonical_master(master)
            if other.shape != base.shape or not np.array_equal(other, base):
                raise ValueError(
                    "選択した信号が同一の時間軸を共有していません。"
                    "共有タイムラインで書き出すには統合タイムラインを有効にしてください。"
                )

    def _merge_one_stage(
        self,
        inputs: Sequence[Path],
        *,
        out_dir: Path,
        token: str,
        stage: int,
        prefix_lines: Sequence[str],
        opts: CsvExportOptions,
        cancel: threading.Event | None,
    ) -> Path:
        """*inputs* を横に繋いだ 1 本の temp を作る (同時 open = len(inputs) + 1)。

        **全入力の行数一致を assert する** (MG-6): ずれたまま繋ぐと、ある列から
        先が 1 行ずれた別時刻の値になる — 例外も長さ検証も出ないサイレント誤データ
        なので、ここで loud-fail させて B6 (全 temp 削除) へ倒す。

        断片に改行は入りえない (値セルは数値であり、クォートが要る文字を含むのは
        ヘッダ/単位行だけで、それは最終段でここへ prefix として渡される) ので、
        行単位の読み出しで正しい。
        """
        merged = out_dir / f".tmp_export_{token}_s{stage}_{uuid.uuid4().hex[:8]}.csv"
        # utf-8-sig は**最終段のみ**が付ける BOM。中間 temp は素の utf-8。
        encoding = "utf-8-sig" if prefix_lines else "utf-8"
        handles = []
        try:
            for path in inputs:
                handles.append(open(path, encoding="utf-8", newline=""))
            with open(merged, "w", encoding=encoding, newline="") as out:
                for line in prefix_lines:
                    out.write(line + "\n")
                buf: list[str] = []
                row = 0
                while True:
                    if row % _CANCEL_ROW_INTERVAL == 0:
                        _check_cancel(cancel)
                    fragments = [h.readline() for h in handles]
                    if all(f == "" for f in fragments):
                        break
                    if any(f == "" for f in fragments):
                        raise ValueError(
                            "内部エラー: 列ブロックの行数が一致しません "
                            f"(段 {stage}・行 {row})"
                        )
                    buf.append(opts.delimiter.join(f.rstrip("\n") for f in fragments))
                    if len(buf) >= _FLUSH_ROWS:
                        out.write("\n".join(buf) + "\n")
                        buf.clear()
                    row += 1
                if buf:
                    out.write("\n".join(buf) + "\n")
        finally:
            for handle in handles:
                handle.close()
        return merged


def _require_disk_space(out_dir: Path, n_rows: int, n_columns: int) -> None:
    """D5: 中間 temp を含むピーク (`TEMP_AMPLIFICATION` x 推定出力) が入らないなら開始しない。"""
    need = int(estimate_output_bytes(n_rows, n_columns) * TEMP_AMPLIFICATION)
    free = shutil.disk_usage(out_dir).free
    if free < need:
        raise ValueError(
            f"出力先の空き容量が不足しています（推定 {need:,} バイト必要・"
            f"空き {free:,} バイト）。範囲を狭めるか列を減らしてください。"
        )
```

必要な import（ファイル冒頭へ追加）: `shutil`・`uuid`・`from dataclasses import dataclass, replace`・`from valisync.core.export.timeline import canonical_master, row_range, union_timeline`。`tempfile` は `_atomic_write` の削除で不要になるので**外す**（残すと ruff F401）。

**削除する**（橋の撤去）: `_rows_unified_timeline` / `_rows_shared_timeline` / `_atomic_write` / `_require_single_value_columns`（複数形）／Task 4 が入れた「keys → 全解決 → 旧実装」のアダプタ。

`src/valisync/core/session.py`:

```python
        # budget_fn は**呼び出し時に読む** — pin の増減 (プロット操作) を次の
        # エクスポートのブロック幅へ反映させるため (D3「予算 − 現在の pin 済み」)。
        self._exporter = CsvExporter(
            budget_fn=lambda: self._channel_cache.available_bytes
        )
```
`export_csv` は keys を受け、`resolve=self.resolve_signal_transient` を渡す（Task 4 が敷いた署名のまま中身を差し替える）。

> **Task 10b への引き継ぎ（対で記録・spec §5.7 [I7c]）**: ここで渡す resolver は本タスクでは `self.resolve_signal_transient` のまま。**Task 10b が `self.export_resolver()` へ差し替える**（1 行）— そうしないと `ExportSourceLost` が production から到達不能なまま（欠落キーは `scan_masters` の `ValueError` になり decay 経路へ落ちない）で、spec §5.7 [I7c] の「診断 1 件」も誰も出さない。差し替え点は `Session.export_csv` と（Task 9 が作る）`Session.export_csv_request` の **2 箇所**。

- [ ] **Step 4: 通ることを確認**

```
uv run pytest tests/core/export/ -q
uv run pytest tests/test_export.py tests/test_csv_export_options.py tests/core/test_export_container_guard.py tests/test_session.py -q
uv run pytest -q
```
Expected:
- `tests/core/export/` = 新規 26 本 ＋ Task 5/6 ぶんが全数 pass
- **既存 40 サイト（`test_export.py` 5・`test_csv_export_options.py` 19・container guard 8・`test_session.py` ほか）が無編集で全数 pass** ← 本タスクの主受け入れ条件
- ゴールデンが `block_cols=None/1/2` の 3 通りとも byte-identical（G1）

橋が消えたことの構造的確認:

```
grep -n "dict(zip\|_rows_unified_timeline\|_rows_shared_timeline\|_atomic_write" src/valisync/core/export/csv_exporter.py
```
Expected: **0 件**。

- [ ] **Step 5: sabotage で honest-RED を確認（必須）**

| # | 壊す箇所（正確な編集） | 予測 RED |
|---|---|---|
| S1 | `_merge_one_stage` の行数一致 assert（`if any(f == "" ...)`）を削除 | `test_merge_loud_fails_when_an_input_has_fewer_rows` / `..._has_more_rows` の **2 件**。**ブロック等価テストは全数緑のまま**（健全な経路では行数が揃う）— assert が「壊れたときにだけ意味を持つ」種類のものである実測 |
| S2 | マージのチャンク順をシャッフル（`chunk = list(reversed(...))`）| `test_multi_stage_merge_produces_the_same_file_as_single_stage` ＋ `test_block_equivalence` の **多列 case 全数** ＋ ゴールデン全数。列順が契約であること（spec §10）の実証 |
| S3 | `_MERGE_FAN_IN` を 2 にする（定数を書き換え） | **RED は 0 件**（段数が増えるだけで出力は同じ）。代わりに `test_progress_units_are_blocks_plus_merge_stages` が **fan_in 注入を使っているので緑のまま**であることを確認し、`merge_stage_count(8254, 2) == 13` を手で確かめて「段数が増えても出力不変」を実測メモに残す |
| S4 | `row_range` の呼び出しを外して `union_view = union` にする | `test_block_equivalence[range-*]` ＋ 既存 `test_time_range_*`（`test_csv_export_options.py` の 12 本前後）が RED |
| S5 | `_require_shared_timeline` の呼び出しを削除 | 既存 `test_shared_timeline_rejects_mismatched_length_signals` / `..._same_length_different_timestamps` / `test_time_range_shared_timeline_mismatch_loud_fail_preserved` の **3 件**（`:92`/`:101` の test-lock がそのまま門番になっている実測） |
| S6 | `_require_shared_timeline` の比較を `canonical_master` から生 master へ | 既存 `test_export_shared_timeline_non_monotonic_sorted_rows` は**単一信号なので緑のまま**。RED になるのは新規に足す `test_shared_timeline_accepts_identically_non_monotonic_masters`（**この sabotage のために 1 本足すこと** — 足さないと canonical 化の必要性が誰にも守られていない） |
| S7 | `finally` の temp 掃除を削除 | 既存 `test_export_atomic_failure_preserves_existing_file`（`tmp_path.iterdir() == ["out.csv"]`）＋ `test_cancel_removes_every_temp_and_leaves_no_output` ＋ `test_export_leaves_no_temp_files_on_success` の **3 件** |
| S8 | ブロックの `aligned` をブロック跨ぎで保持（`self._keep.append(aligned)`）| `test_memory_per_block_does_not_grow_with_the_block_index` の **1 件のみ**。出力テストは全数緑 — G3 が出力では代替不能であることの実証 |
| S9 | `_require_disk_space` の呼び出しを削除 | `test_disk_space_shortage_is_rejected_before_writing` の **1 件** |
| S10 | legacy 形を旧実装（保存しておいた `_rows_*`）へ戻す | **RED は 0 件になりうる**（出力は同じ）。したがって橋の撤去は grep（`dict(zip` が 0 件）で確認する — テストでは検出できないことを明記して報告する |
| S11 | `_export_request` の**空リクエスト検査**（`if not request.keys and not request.extra_signals: raise`）を削除 | 既存 `tests/test_golden_csv.py::test_empty_selection_fails_loudly_and_writes_no_file`（Task 2）＋ `tests/core/test_export_request_bridge.py::test_empty_request_fails_loudly`（Task 4）の **2 件**。どちらも「ヘッダだけのファイルが成功として書かれる」形で落ちる（例外が出ない）— **橋にしか無かった検査を本体へ移した**ことの実証 |
| S12 | `_export_request` の**ヘッダ長検査**（`if len(names) != len(request.keys): raise`）を削除 | 既存 `tests/core/test_export_request_bridge.py::test_header_resolver_length_mismatch_fails_loudly` の **1 件**。同 sabotage で `assert not out.exists()` も落ちる（`raise` が無いのでファイルが書かれる）ことまで確認する |
| S13 | ヘッダ解決（`names = list(request.header_resolver(...))` と長さ検査）を **temp 書きの後**（元の位置）へ戻す | **RED は 1 件**（S12 と同じテストの `assert not out.exists()` — 全ブロックを書いてから落ちるので出力ファイルは残らないが temp 生成は走る）。RED が出ない場合は**発見として報告**し、「検査の位置」を守る番人が居ないことを記録する（位置は perf/B6 の契約であって出力の契約ではない） |

- [ ] **Step 6: ゲート＋コミット**

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```
passed 数が **Step 1 のベースライン + 26**（ゴールデンの parametrize 追加ぶんは別途加算）。

**共有インターフェース契約と spec を同時に更新する**:
- 契約 L33 の `units` を「**1（時刻 temp）＋ ブロック数 ＋ マージ段数**」へ（実装は時刻列を幅 1 のブロックとして 1 単位数える）。
- 契約 L28-32 へ **legacy overload**（`export(signals, output_path, use_unified_timeline, options)`）が存続することを追記（`CsvExporter.export` は 2 形の dispatch であって request 形だけではない）。
- spec §5.1-4 [MG-7] へ `header_names` 残置の supersede を記録（上の裁定）＋ docs/design.md 決定履歴に 1 行。

```
git add src/valisync/core/export/csv_exporter.py src/valisync/core/session.py tests/core/export/
git commit -m "$(cat <<'EOF'
perf(core)!: CSV エクスポートを列ブロック x 行ストリーム x 多段マージへ (橋を撤去)

E-4b §5.3 の本体。旧一括実装 (_rows_unified_timeline / _rows_shared_timeline /
_atomic_write) と T-API の移行橋を削除し、legacy 形の呼び出しも同じパイプラインへ
落とした。旧実装を legacy にだけ残すと dict(zip(...tolist())) (実測 97 B/サンプル・
20 列で Win32 working set 2.14 GiB) が既存テスト 40 サイトの下で生き残る。

パイプライン: 前走査 (値を読まない) -> union (identity dedup) -> 共有タイムライン
前提検証 (canonical_master 同士・値を読まない) -> 行範囲 1 回 -> 列ブロックを
block-temp へ -> 多段マージ -> os.replace。

多段マージの fan-in は 512。本環境の FD 天井は実測 8,189 本 (OSError errno 24) で、
prod 3 ファイル比較の全列 (~8,254 本) は単段では確実に超える (MG-2)。同時 open は
F+1 本のみ。段ごとに全入力の**行数一致を assert** する — ずれたまま繋ぐと、ある列
から先が 1 行ずれた別時刻の値になる (例外も長さ検証も出ないサイレント誤データ)。

時刻列は幅 1 のブロックとして扱い、マージ器に特別扱いを作らない。ヘッダは keys から
header_resolver で・単位行はブロックパス中の側帯から、最終段の先頭に書く (マージ段
での再 resolve は禁止 = 330k 再解決 ~390 MB の一撃・MG-4)。

開始前に shutil.disk_usage で 2.3 x 推定出力を検査する (D5)。失敗・キャンセル・
成功のいずれでも temp を残さない (B6)。progress の単位は 1 (時刻) + ブロック数 +
マージ段数。

受け入れの主力は新規テストではなく **既存 40 サイトが無編集で緑**であること
(legacy 形が同じパイプラインへ落ちるため)。加えてゴールデンを block_cols=None/1/2
の 3 通りで再駆動して byte-identical (G1)・ブロック幅と fan-in を変えても出力
バイトが不変であることを 11 fixture x 4 構成で固定・ブロックあたりの
tracemalloc 増分が +/-20% 以内 (G3)。

sabotage 実測: 行数 assert 除去=2 RED (等価テストは全数緑)・マージ順反転=多列
case 全数 + ゴールデン全数 RED・行範囲除去=既存 time_range 12 本 RED・共有前提
検証除去=既存 test-lock 3 本 RED・temp 掃除除去=3 RED・ブロック跨ぎ保持=G3 の
1 件のみ RED (出力テストは全数緑)・ディスク検査除去=1 RED。橋の撤去そのものは
テストで検出不能なので grep (dict(zip が 0 件) で確認した。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```
### Task 8: 見積＋確認ダイアログ（B2 / D5・spec §5.5 前半）

**Files:**
- Create: `src/valisync/core/export/estimate.py`（`ExportEstimate` / `estimate_export` / `disk_shortfall` / 係数定数）
- Create: `src/valisync/gui/formatting.py`（`format_duration` — Task 9 の ETA と共有する pure 関数）
- Create: `src/valisync/gui/views/export_confirm.py`（`confirm_body` / `needs_confirmation` — Qt 非依存の pure 層）
- Modify: `src/valisync/core/loaders/signal_group_manager.py`（`channel_master` / `is_lazy_group` を追加。**鋳造しない・値を読まない** introspection）
- Modify: `src/valisync/core/session.py`（`channel_master` / `is_lazy_channel` の委譲）
- Modify: `src/valisync/gui/strings.py`（確認ダイアログ／ディスク不足の文言）
- Modify: `src/valisync/gui/views/main_window.py`（`export_csv` の accept 流路へ 見積 → D5 検査 → 確認 を挿す・`_confirm_export_fn` の DI 口を追加）
- Test: `tests/test_export_estimate.py`（新規・Qt 非依存）
- Test: `tests/gui/test_export_confirm.py`（新規）

**Interfaces:**

- **Consumes**（**Task 4/5/6 まで** — 本タスクは Task 7 を待たない。見積は書き経路に触れないので Task 7 と並列に進めてよい）:
  - `valisync.core.export.csv_exporter.ExportRequest`（Task 4・`keys` / `output_path` / `options` / `header_resolver` / `extra_signals`）
  - `valisync.core.export.timeline.union_timeline(masters: Sequence[np.ndarray]) -> np.ndarray`（Task 5・identity dedup ＋ `np.unique`）
  - `valisync.core.export.timeline.hit_mask(sig_ts: np.ndarray, union_ts: np.ndarray) -> np.ndarray`（Task 5・`bool` 配列・長さ = `len(union_ts)`・値を読まない）
  - `valisync.core.export.timeline.row_range(union_ts, time_start, time_end) -> tuple[int, int]`（Task 5・閉区間 `[lo, hi)`・lo=`left` / hi=`right`）
  - `valisync.core.export.timeline.canonical_master(master) -> np.ndarray`（Task 5・`hit_mask` へ渡す前の正規化。単調なら同一オブジェクト）
  - `valisync.core.session.Session.channel_key_of(column_key: str) -> str | None`（Task 6・列キー → `"{group_key}::{物理チャンネル表示名}"`。**列 → チャンネル解決の唯一の実装**で、ブロック割当も同じものを使う）
  - `valisync.core.session.Session.resolve_signal_transient`（Task 6・本タスクでは**呼ばない**が、呼んでいないことをテストで固定する）
- **Produces**（Task 9/10/11 と Task 11 の検証対象）:
  - `ExportEstimate`（共有契約の逐語形）／`estimate_export(session, keys, options) -> ExportEstimate`
  - `disk_shortfall(output_path: Path, est_bytes: int) -> int`（D5・不足バイト数・足りていれば 0）
  - `CONFIRM_THRESHOLD_S: float = 5.0` / `TEMP_AMPLIFICATION: float = 2.3` / 単価 3 定数（Task 11 が prod 1 点で検定して置き換える対象）
  - `needs_confirmation(est: ExportEstimate) -> bool`（**時間ベース** — spec I10）
  - `confirm_body(est: ExportEstimate) -> str`（pure・Task 11 の realgui が実ダイアログ本文として観測する）
  - `gui.formatting.format_duration(seconds: float) -> str`（Task 9 の ETA が使う）
  - `MainWindow._confirm_export_fn: Callable[[ExportEstimate], bool]`（DI 口・realgui とテストが差し替える）
  - `SignalGroupManager.channel_master` / `is_lazy_group`、`Session.channel_master` / `is_lazy_channel`

- **Step 0: 依存契約の実物確認（実装前に必ず）**

```
uv run python -c "from valisync.core.export.timeline import union_timeline, hit_mask, row_range, canonical_master; print(union_timeline, hit_mask, row_range, canonical_master)"
uv run python -c "from valisync.core.session import Session; print(Session.channel_key_of)"
uv run python -c "from valisync.core.export.csv_exporter import ExportRequest; import dataclasses; print([f.name for f in dataclasses.fields(ExportRequest)])"
```
Expected: 3 行とも成功し、最後は `['keys', 'output_path', 'options', 'header_resolver', 'extra_signals']`。

**名前が違ったら import 行だけを実物へ合わせ、「違っていた」という事実を報告に書く**（黙って合わせると、共有契約 `.superpowers/sdd/e4b-shared-interfaces.md` が実装と乖離したまま次の著者へ渡る）。**関数が存在しない場合は停止して報告**する — 見積を自前の union 実装で書くと「見積が使う union」と「出力が使う union」が 2 つの真実になり、行数の見積が出力と食い違う（B2 が提示する「正確値」が正確でなくなる）。

- [ ] **Step 1: 失敗テストを書く**

まずベースラインを記録する（Step 6 の「挙動不変」を主張でなく実測で示すため）。**パイプを通さない**（`| tail` は exit code を隠す — Global Constraints）:

```
uv run pytest -q
```
→ 出た `N passed, M skipped` を控える。Step 6 で `N + 16 passed` になることを確認する。

`tests/test_export_estimate.py` を新規作成:

```python
# ruff: noqa: RUF002, RUF003
"""事前見積 (E-4b T-UX・spec §5.5 / B2) の正確値・推定値・D5 検査。

**demo_data に依存しない**: 合成 mf4 (tests.mdf4_helpers) で「複数レート」「幅広
2-D チャンネル」「CSV グループ」の 3 形すべてを踏める。demo_data/ は gitignore 済みで
CI に生成ステップが無く、そこへ置くと丸ごと skip される (E-4a T0 と同じ判断)。

このファイルの中心的な主張は 2 つ:
1. 見積は **値を 1 バイトも読まない** (spec §6 全タスク共通制約)。読むと「見積のために
   10 GB 読む」形になり、B2 が減らそうとしている待ちを見積自身が作る。
2. 読み項は **物理チャンネル単位** で数える。列単位で数えると幅 1,100 の
   チャンネルで 1,100 倍に膨れ、prod 全列の推定が 29 時間 (実測外挿 18.4 分の ~95 倍)
   になる = 見積が桁で嘘をつく。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.mdf4_helpers import CAN, write_mdf4, write_mdf4_wide_2d
from valisync.core.export.csv_exporter import CsvExportOptions
from valisync.core.export.estimate import (
    CONFIRM_THRESHOLD_S,
    TEMP_AMPLIFICATION,
    ExportEstimate,
    disk_shortfall,
    estimate_export,
)
from valisync.core.session import Session


def _two_rate_session(tmp_path: Path) -> tuple[Session, list[str]]:
    """10 ms と 100 ms の 2 チャンネル (master 2 本・union は 12 行)。

    fast: t = 0.00, 0.01, ... 0.09 (10 点) / slow: t = 0.00, 0.05 (2 点だが
    0.00 は fast と一致するので union は 11 行)。**値ではなく時刻の重なりだけ**で
    空セル率が決まることを、手計算できる小ささで固定する。
    """
    path = tmp_path / "two_rate.mf4"
    write_mdf4(
        path,
        [
            {
                "name": "Fast",
                "bus_type": CAN,
                "timestamps": [round(i * 0.01, 4) for i in range(10)],
                "values": [float(i) for i in range(10)],
            },
            {
                "name": "Slow",
                "bus_type": CAN,
                "timestamps": [0.0, 0.05],
                "values": [100.0, 200.0],
            },
        ],
    )
    session = Session()
    key = session.load(path).key
    return session, [f"{key}::Fast", f"{key}::Slow"]


def test_rows_and_columns_are_exact(tmp_path: Path) -> None:
    """列数 = keys 長・行数 = union 長 (どちらも B2 の「正確値」)。"""
    session, keys = _two_rate_session(tmp_path)
    est = estimate_export(session, keys, CsvExportOptions())
    assert est.columns == 2
    # union = fast の 10 点 ∪ {0.05}。0.05 は fast の 0.05 と **同一 float** なので
    # 畳まれる (完全一致セマンティクス・tolerance 無し) -> 10 行。
    assert est.rows == 10


def test_empty_ratio_is_exact_from_searchsorted_hits(tmp_path: Path) -> None:
    """空セル率は推定でなく **正確値** (master の union への引き当てヒット数)。

    fast は 10 行すべてにヒット・slow は 0.00 と 0.05 の 2 行だけ。
    非空セル = 10 + 2 = 12 / 全セル = 10 行 x 2 列 = 20 -> 空セル率 0.4。
    """
    session, keys = _two_rate_session(tmp_path)
    est = estimate_export(session, keys, CsvExportOptions())
    assert est.empty_ratio == pytest.approx(0.4)


def test_estimate_reads_no_values_and_mints_no_columns(tmp_path: Path) -> None:
    """値を読まない・鋳造もしない (spec §6 共通制約 / MG-1 の帳簿汚染回避)。

    ``LazyMdfValues.array`` を「呼ばれたら即失敗」に差し替えるので、見積のどこかが
    値へ触れた瞬間に AssertionError で落ちる (返り値を偽装しないのは、偽装すると
    「読んだが正しい答えが出た」で緑になるため)。
    """
    from valisync.core.models import sample_source as ss

    session, keys = _two_rate_session(tmp_path)
    mgr = session._groups
    before_mint = mgr.mint_count
    # **transient は別勘定** (Task 6 の MG-1)。`mint_count` だけを見ていると、
    # 見積が `resolve_signal_transient` で全列鋳造しても全緑で通る — Step 0 で
    # 「呼んでいないことをテストで固定する」と宣言した対象はこちら側。
    before_transient = mgr.transient_mint_count
    before_resolved = mgr.resolved_keys(keys[0].split("::", 1)[0])

    original = ss.LazyMdfValues.array

    def boom(self: object) -> np.ndarray:
        raise AssertionError("見積が値を読んだ (spec §6 の禁止事項)")

    ss.LazyMdfValues.array = boom  # type: ignore[method-assign]
    try:
        est = estimate_export(session, keys, CsvExportOptions())
    finally:
        ss.LazyMdfValues.array = original  # type: ignore[method-assign]

    assert est.rows == 10
    assert mgr.mint_count == before_mint, "見積が列を鋳造した (LRU の枠を食う)"
    assert mgr.transient_mint_count == before_transient, (
        "見積が resolve_signal_transient 経由で列を鋳造した "
        "(帳簿は汚れないが 330k 本の一過性 Signal を作る)"
    )
    assert mgr.resolved_keys(keys[0].split("::", 1)[0]) == before_resolved


def test_read_term_counts_physical_channels_not_columns(tmp_path: Path) -> None:
    """読み項は **チャンネル単位**。幅 k の 2-D を全列選んでも 1 チャンネル分。

    E-4a 以降の読みは 1 select + k スライスなので、列単位で数えると k 倍の嘘になる。
    """
    # 実シグネチャは `write_mdf4_wide_2d(tmp_path, cols=1025)` — **第 1 引数は
    # ディレクトリ**でファイルパスではなく、`name` / `rows` / `width` という
    # キーワードは存在しない (行数は 3 行固定・チャンネル名は "Wide")。
    path = write_mdf4_wide_2d(tmp_path, cols=16)
    session = Session()
    key = session.load(path).key
    cols = session.column_names_of(key, "Wide")
    assert len(cols) == 16, "fixture 前提: 幅 16 の 2-D チャンネル"
    keys = [f"{key}::{c}" for c in cols]

    est_all = estimate_export(session, keys, CsvExportOptions())
    est_one = estimate_export(session, keys[:1], CsvExportOptions())

    # 16 列でも 1 列でも「読むチャンネル」は 1 本 -> 読み項は同じ。
    assert est_all.est_read_s == pytest.approx(est_one.est_read_s)
    assert est_all.est_read_s > 0.0
    # 書き項は列数に比例する (読み項と書き項が別勘定であることの positive control)。
    assert est_all.est_write_s > est_one.est_write_s


def test_eager_csv_group_contributes_no_read_time(tmp_path: Path) -> None:
    """CSV グループは既に実体化済み (EagerValues) — cold read は 0。

    ここを 0 にしないと、CSV だけを選んだ小さなエクスポートでも確認ダイアログが
    出て「5 秒かかります」と嘘をつく。
    """
    from valisync.core.models import Delimiter, FormatDefinition

    csv = tmp_path / "eager.csv"
    csv.write_text("t,A\n0.0,1.0\n1.0,2.0\n", encoding="utf-8")
    fmt = FormatDefinition(
        name="f",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    session = Session()
    key = session.load(csv, fmt).key
    est = estimate_export(session, [f"{key}::A"], CsvExportOptions())
    assert est.est_read_s == 0.0
    assert est.rows == 2


def test_time_range_narrows_rows_on_a_closed_interval(tmp_path: Path) -> None:
    """範囲は閉区間 (lo=left / hi=right — M-3)。境界サンプルは残る。"""
    session, keys = _two_rate_session(tmp_path)
    opts = CsvExportOptions(time_start=0.02, time_end=0.05)
    est = estimate_export(session, keys, opts)
    # 0.02 / 0.03 / 0.04 / 0.05 の 4 行 (両端を含む)。
    assert est.rows == 4


def test_empty_selection_is_all_zero_without_dividing_by_zero(tmp_path: Path) -> None:
    """0 列 / 0 行でも例外を出さない (確認ダイアログの手前で落ちない)。"""
    session, _keys = _two_rate_session(tmp_path)
    est = estimate_export(session, [], CsvExportOptions())
    assert est == ExportEstimate(
        columns=0, rows=0, empty_ratio=0.0, est_bytes=0, est_read_s=0.0, est_write_s=0.0
    )


def test_disk_shortfall_requires_the_temp_amplification(tmp_path: Path) -> None:
    """D5 は **2.3 x 推定出力** を要求する (多段マージの中間 temp を含む・spec §5.3)。

    1.0 x で判定すると、出力ちょうどの空きしかないボリュームで最終 replace の直前に
    ENOSPC になり、B6 の「何も残さない」が「途中まで書かれた temp が残る」に degrade する。
    """
    import valisync.core.export.estimate as est_mod

    free_bytes = 1_000
    est_mod.shutil.disk_usage = lambda _p: type(  # type: ignore[assignment]
        "U", (), {"total": free_bytes, "used": 0, "free": free_bytes}
    )()
    try:
        # 2.3 x 500 = 1150 > 1000 -> 150 不足
        assert disk_shortfall(tmp_path / "out.csv", 500) == 150
        # 2.3 x 400 = 920 <= 1000 -> 足りている
        assert disk_shortfall(tmp_path / "out.csv", 400) == 0
    finally:
        import shutil as real_shutil

        est_mod.shutil = real_shutil  # type: ignore[assignment]
    assert TEMP_AMPLIFICATION == 2.3


def test_confirm_threshold_is_time_based_not_size_based() -> None:
    """閾値は推定時間 (spec I10)。サイズで判定すると読み支配ケースが素通りする。

    「カーソル A-B x 全列」は出力 2,057 B・読み 6.5 s (spec §1 実測) — サイズ基準の
    どんな閾値でも下回るので、確認もキャンセル導線も出ないまま 6.5 秒フリーズする。
    """
    from valisync.gui.views.export_confirm import needs_confirmation

    tiny_but_slow = ExportEstimate(
        columns=330_004,
        rows=1,
        empty_ratio=0.66,
        est_bytes=2_057,
        est_read_s=6.5,
        est_write_s=0.2,
    )
    big_but_fast = ExportEstimate(
        columns=2,
        rows=10,
        empty_ratio=0.0,
        est_bytes=10_000_000_000,
        est_read_s=0.1,
        est_write_s=0.1,
    )
    assert needs_confirmation(tiny_but_slow) is True
    assert needs_confirmation(big_but_fast) is False
    assert CONFIRM_THRESHOLD_S == 5.0
```

`tests/gui/test_export_confirm.py` を新規作成:

```python
# ruff: noqa: RUF002, RUF003
"""確認ダイアログの本文・閾値・D5 拒否の配線 (E-4b T-UX・B2/D5)。

本文は pure 関数 (``export_confirm.confirm_body``) が作り、QMessageBox は
``MainWindow._confirm_export_fn`` の既定実装が包むだけ — file_browser_view の
``_confirm_fn`` DI と同型 (spec §5.5 [I15/ux-A])。テストは DI 口を差し替えて
「訊いたか」「答えに従ったか」を効果で見る (モーダルは開かない)。
"""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.core.export.estimate import ExportEstimate
from valisync.gui.views.export_confirm import confirm_body, needs_confirmation

_EST = ExportEstimate(
    columns=1234,
    rows=5678,
    empty_ratio=0.6612,
    est_bytes=10_100_000_000,
    est_read_s=600.0,
    est_write_s=504.0,
)


def test_body_labels_the_estimated_values_as_estimates() -> None:
    """B2: 正確値 (列/行/空セル率) と推定値 (サイズ/時間) を読者が区別できること。"""
    body = confirm_body(_EST)
    assert "推定サイズ" in body
    assert "推定時間" in body
    assert "1234" in body and "5678" in body


def test_body_uses_no_digit_grouping() -> None:
    """桁区切りは付けない (既存決定・strings.py:261 のチャンネル件数と同規約)。"""
    body = confirm_body(_EST)
    assert "1,234" not in body
    assert "5,678" not in body


def test_body_explains_why_cells_are_empty() -> None:
    """空セル率だけ出しても読者は原因を推測できない (spec §5.5 の文言例)。"""
    body = confirm_body(_EST)
    assert "66" in body  # 0.6612 -> 66 %
    assert "記録周期" in body


def test_confirmation_is_skipped_below_the_threshold(qtbot: QtBot) -> None:
    fast = ExportEstimate(2, 10, 0.0, 100, 0.1, 0.1)
    assert needs_confirmation(fast) is False


def test_main_window_asks_and_aborts_when_refused(qtbot: QtBot, tmp_path: Path) -> None:
    """拒否したら submit しない (「訊いたが無視して書き出す」を閉じる)。"""
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    asked: list[ExportEstimate] = []
    submitted: list[object] = []
    window._confirm_export_fn = lambda est: (asked.append(est), False)[1]
    window._export_controller.submit = lambda *a, **k: submitted.append(a)  # type: ignore[method-assign]

    window._run_export(_request(tmp_path), _EST)

    assert len(asked) == 1
    assert submitted == []


def test_main_window_submits_when_confirmed(qtbot: QtBot, tmp_path: Path) -> None:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    submitted: list[object] = []
    window._confirm_export_fn = lambda est: True
    window._export_controller.submit = lambda *a, **k: submitted.append(a)  # type: ignore[method-assign]

    window._run_export(_request(tmp_path), _EST)

    assert len(submitted) == 1


def test_disk_shortfall_refuses_before_asking_anything(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """D5 は **唯一の拒否**。不足なら確認も submit もせずに理由を出す。"""
    import valisync.gui.views.main_window as mw
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    asked: list[object] = []
    submitted: list[object] = []
    blocked: list[str] = []
    window._confirm_export_fn = lambda est: asked.append(est) or True
    window._export_controller.submit = lambda *a, **k: submitted.append(a)  # type: ignore[method-assign]
    window._notify_blocked = blocked.append
    mw.disk_shortfall = lambda _p, _b: 4_096  # type: ignore[assignment]

    window._run_export(_request(tmp_path), _EST)

    assert submitted == []
    assert asked == [], "ディスク不足なのに続行可否を訊いた (答えても書けない)"
    assert blocked and "空き容量" in blocked[0]


def _request(tmp_path: Path):  # type: ignore[no-untyped-def]
    from valisync.core.export.csv_exporter import CsvExportOptions, ExportRequest

    return ExportRequest(
        keys=("mf4_1::A",),
        output_path=tmp_path / "out.csv",
        options=CsvExportOptions(),
        header_resolver=list,
    )
```

**この時点で走らせて RED を確認する**（Step 5 の「通った」を主張でなく差分で示すため）:

```
uv run pytest tests/test_export_estimate.py tests/gui/test_export_confirm.py -q
```

**予測 RED**: **両ファイルとも collection error 2 件**（`valisync.core.export.estimate` と `valisync.gui.views.export_confirm` がまだ存在しない — 個々のテストは 1 本も実行されない）。個別の failed 一覧は出ない。**AssertionError や値の不一致が出たら予測が外れている**（誰かが同名モジュールを先に作っている）ので、進めずに報告する。

- [ ] **Step 2: `estimate.py` を実装**

`src/valisync/core/export/estimate.py`:

```python
"""エクスポートの事前見積 (E-4b T-UX・spec §5.5 / ユーザー決定 B2)。

**この module は値を読まない** — ``Signal.values`` / ``.array()`` / ``sorted_view()``
をどの経路からも呼ばない (spec §6 の全タスク共通制約)。見積が値を読むと「見積のために
10 GB 読む」形になり、B2 が減らそうとしている待ちを見積自身が作る。触ってよいのは
master (``Signal.timestamps`` — ロード時点で既にメモリに在る) と列構造 (ColumnRecord)
だけ。列の**鋳造**もしない: 鋳造は E-4a の LRU 枠を食い、プロット中でない列を押し出す。

**係数は Task 11 (T-M) が prod_demo 1 点で検定するまで暫定**である (spec §5.5
「係数は quick_demo 由来のまま出荷しない」)。合成由来の単価はこのシリーズで 3 回
桁を外している (channel_cache.py の evict 単価コメント参照) ので、検定前の値を
受け入れ帯に使ってはならない。出典と算術を定数の隣に残すのは、検定のときに
「何を測り直せばよいか」が数字だけからは復元できないため。
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np

from valisync.core.export.csv_exporter import TEMP_AMPLIFICATION
from valisync.core.export.timeline import (
    canonical_master,
    hit_mask,
    row_range,
    union_timeline,
)

if TYPE_CHECKING:
    from valisync.core.export.csv_exporter import CsvExportOptions
    from valisync.core.session import Session

# 読み: E-4a T5 実測の cold 1 列 316 ms。E-4a 以降の読みは **物理チャンネル単位**
# (1 select + k スライス) なので、これは「列単価」ではなく **チャンネル単価** として
# 使う。spec §5.5 の字面 (cold 列数 x 列単価) をそのまま実装すると、幅 1,100 の
# チャンネルを 1,100 回読む前提になり prod 全列で ~29 時間 (§1 の外挿 18.4 分の
# ~95 倍) を提示する = 見積が桁で嘘をつく。逸脱を spec §5.5 へ追記するのは Task 11。
_READ_S_PER_COLD_CHANNEL: Final = 0.316

# 書き: spec §1 の prod 全列外挿 (出力 ~10.1 GB・純 Python ~18.4 分) と平均セル長
# 4.57 文字から 1,104 s / (10.1e9 B / 5.57 B) ~= 6.1e-7 s/セル。per-cell repr の
# 単価 (0.3-1 us) とも桁が合う。
_WRITE_S_PER_CELL: Final = 6.1e-7

# 値セルの平均文字数。spec §1 で「uint8 量子化の repr 長 4.57 文字」を実測済み
# (初版の 18.63 は反証された)。
_AVG_VALUE_CHARS: Final = 4.57

# 時刻セルは float64 の shortest round-trip repr で最長 17 文字 + 余裕 1。1 列しか
# 無いので過大評価の寄与は小さく、est_bytes は D5 の検査に使うため **安全側 (過大)**
# に倒す。
_AVG_TIME_CHARS: Final = 18.0

# ヘッダ 1 セルの平均文字数 (表示名 + 区切り)。単位行が有効ならもう 1 行ぶん。
_AVG_HEADER_CHARS: Final = 24.0

# 多段マージの中間 temp を含むディスクピーク係数 (spec §5.3・実係数は Task 11 検証)。
# **定数の実体は `csv_exporter.py` に 1 つだけ置く**（上の import で持ってきている
# ものをそのまま再輸出する）。GUI 側 (disk_shortfall) と core 側 (_require_disk_space)
# が別々に 2.3 を持つと、片方だけ Task 11 の検定で更新されたときに
# 「GUI の D5 を通過 -> 確認 Yes -> core で ValueError」という UX 破綻窓が開く。
# ここへ再輸出するのは共有インターフェース契約が `estimate.TEMP_AMPLIFICATION` を
# 名指ししているため (テストも `from ...estimate import TEMP_AMPLIFICATION` で読む)。
# **Task 7 より先に本タスクが着地する場合**は、本タスクが `csv_exporter.py` へ
# この定数 (と WHY コメント) を置き、Task 7 は `_DISK_HEADROOM` を新設せず
# これを使う — どちらが先でも **定数は 1 つ**。

# 確認ダイアログを出す閾値。**時間ベース** (spec I10) — サイズ基準にすると
# 「カーソル A-B x 全列」(出力 2,057 B・読み 6.523 s の実測ケース) が素通りする。
CONFIRM_THRESHOLD_S: Final = 5.0


@dataclass(frozen=True)
class ExportEstimate:
    """B2 が人に提示する 5 点 + 内訳 (共有契約の逐語形)。"""

    columns: int  # 正確
    rows: int  # 正確 (union 長・master のみで計算)
    empty_ratio: float  # 正確 (searchsorted ヒット数から)
    est_bytes: int  # 推定
    est_read_s: float  # 推定 (cold チャンネル数 x チャンネル単価)
    est_write_s: float  # 推定 (セル数 x セル単価)


def estimate_export(
    session: Session, keys: Sequence[str], options: CsvExportOptions
) -> ExportEstimate:
    """列キー集合から出力の規模を見積もる (**値を読まない・鋳造しない**)。"""
    key_tuple = tuple(keys)
    columns = len(key_tuple)
    if columns == 0:
        return ExportEstimate(0, 0, 0.0, 0, 0.0, 0.0)

    # 1) 列 -> 物理チャンネル。channel_key_of は ColumnRecord の最長一致だけを見る
    #    (Task 6 のブロック割当と **同じ解決器** — 2 つ持つと見積と出力がずれる)。
    cols_per_channel: dict[str, int] = {}
    for key in key_tuple:
        channel = session.channel_key_of(key)
        if channel is None:
            continue  # Derived / 解決不能: master を持たない (extra_signals 経路)
        cols_per_channel[channel] = cols_per_channel.get(channel, 0) + 1

    # 2) チャンネル -> master。identity dedup は union と同じ規則 (spec §5.4)。
    masters: dict[int, np.ndarray] = {}
    cols_per_master: dict[int, int] = {}
    cold_channels = 0
    for channel, n_cols in cols_per_channel.items():
        master = session.channel_master(channel)
        if master is None:
            continue
        mid = id(master)
        masters.setdefault(mid, master)
        cols_per_master[mid] = cols_per_master.get(mid, 0) + n_cols
        if session.is_lazy_channel(channel):
            # 実体化済み (CSV/Derived) のチャンネルは読み直さないので 0 秒。
            cold_channels += 1

    union = union_timeline(list(masters.values()))
    # 行範囲は **Task 5 の `row_range` をそのまま消費する**（自前で searchsorted
    # を書き直さない — 見積と出力で行の切り方が 2 つになると、B2 が「正確値」と
    # 名乗る行数が出力とずれる）。sides は Task 5 のテストが pin 済み。
    lo, hi = row_range(union, options.time_start, options.time_end)
    rows_ts = union[lo:hi]
    rows = int(rows_ts.size)

    # 3) 空セル率は「各 master が union 窓の何行にヒットするか」の厳密和。
    filled = 0
    for mid, master in masters.items():
        # **canonical_master を通す**: `hit_mask` の契約は「昇順・重複なしの
        # sig_ts」で、生 master をそのまま渡すと非単調/重複 ts のグループで
        # `side='left'` が重複ランの先頭に当たり、書き手 (sorted_view の keep-last)
        # と違う行を「在る」と数える。単調な master は同一オブジェクトが返るので
        # 支配的経路のコストはゼロ。
        filled += (
            int(np.count_nonzero(hit_mask(canonical_master(master), rows_ts)))
            * cols_per_master[mid]
        )
    total_cells = rows * columns
    empty_ratio = 0.0 if total_cells == 0 else 1.0 - filled / total_cells
    # master を持たない列 (Derived) は filled に寄与しないので、僅かに過大へ倒れうる。
    # 率なので [0, 1] へ丸める (負の空セル率を人に見せない)。
    empty_ratio = min(1.0, max(0.0, empty_ratio))

    delimiter_len = len(options.delimiter)
    non_empty = 1.0 - empty_ratio
    per_row = (
        _AVG_TIME_CHARS
        + columns * (delimiter_len + _AVG_VALUE_CHARS * non_empty)
        + 1  # 行末 LF (据え置き・spec §5.1)
    )
    header_lines = 1 + (1 if options.unit_row else 0)
    header_bytes = 3 + header_lines * (  # 3 = UTF-8 BOM (spec §5.1-2)
        columns * (_AVG_HEADER_CHARS + delimiter_len) + 16
    )

    return ExportEstimate(
        columns=columns,
        rows=rows,
        empty_ratio=empty_ratio,
        est_bytes=int(header_bytes + per_row * rows),
        est_read_s=cold_channels * _READ_S_PER_COLD_CHANNEL,
        est_write_s=total_cells * _WRITE_S_PER_CELL,
    )


def disk_shortfall(output_path: Path, est_bytes: int) -> int:
    """D5: 必要量 (``TEMP_AMPLIFICATION`` x 推定出力) に対する不足バイト数。

    足りていれば 0。**これがエクスポートの唯一の拒否**なので、検査できない状況
    (存在しないボリューム・権限) では 0 を返して通す — 誤拒否を作ると「書けるのに
    書けないアプリ」になり、B2 の「情報提示して人が決める」という方針に反する。
    """
    required = int(est_bytes * TEMP_AMPLIFICATION)
    probe = output_path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free = int(shutil.disk_usage(str(probe)).free)
    except OSError:
        return 0
    return max(0, required - free)
```

`src/valisync/core/export/__init__.py` は**触らない**（`csv_exporter` と同じく完全パス import。キュレートされた `__all__` を膨らませない）。

- [ ] **Step 3: 鋳造しない master 参照 API を core へ足す**

`src/valisync/core/loaders/signal_group_manager.py`（`column_names_of` の直後へ）:

```python
    def channel_master(self, group_key: str, display_name: str) -> np.ndarray | None:
        """物理チャンネルの master 配列 (**鋳造しない・値を読まない**)。

        見積 (E-4b T-UX) が union と空セル率を出すための唯一の入口。``resolve`` で
        代用すると列を鋳造して LRU の枠を食う (``has_column`` の docstring と同じ理由)。
        鋳造列は親の master を **同一オブジェクトのまま** 共有するので、ここで返す
        配列は列がどれであっても identity dedup の同じ 1 本になる (spec §5.4)。
        """
        sig = self._physical_by_name.get(group_key, {}).get(display_name)
        return None if sig is None else sig.timestamps

    def is_lazy_group(self, group_key: str) -> bool:
        """このグループの samples が **まだファイル側に在る** か (handle を持つか)。

        見積の読みコスト項の母数。CSV/Derived は EagerValues で既に実体化済みなので
        0 秒 — ここを一様に cold 扱いすると、CSV だけの小さな出力でも確認ダイアログが
        「5 秒かかります」と嘘をつく。
        """
        group = self._groups.get(group_key)
        return group is not None and group.handle is not None
```

`numpy` の import が未追加なら `import numpy as np` をモジュール先頭へ足す（型注釈のみなので `from __future__ import annotations` 下では実行時 import 不要 — `TYPE_CHECKING` ブロックへ入れる）。

`src/valisync/core/session.py`（`column_names_of` の委譲群の隣へ）:

```python
    def channel_master(self, channel_key: str) -> np.ndarray | None:
        """``"{group_key}::{物理チャンネル表示名}"`` の master (鋳造しない)。"""
        group_key, sep, display = channel_key.partition(KEY_SEPARATOR)
        if not sep:
            return None
        return self._groups.channel_master(group_key, display)

    def is_lazy_channel(self, channel_key: str) -> bool:
        """そのチャンネルの読みが **まだ発生していない** か (見積の読み項の母数)。"""
        group_key, sep, _display = channel_key.partition(KEY_SEPARATOR)
        return bool(sep) and self._groups.is_lazy_group(group_key)
```

- [ ] **Step 4: 文言・pure 層・accept 流路を配線**

`src/valisync/gui/formatting.py`（新規・Qt 非依存）:

```python
"""表示用フォーマッタ (pure Python・Qt 非依存)。

``file_browser_vm._fmt_size`` と同じ位置づけだが、こちらは **View と VM の双方**
(確認ダイアログ本文と BusyOverlay の ETA) が使うため中立な置き場に置く。
文言そのものは strings.py が持ち、ここは数値 -> 文字列の変換だけを担う。
"""

from __future__ import annotations


def format_duration(seconds: float) -> str:
    """人が読む所要時間。桁区切りは付けない (既存決定)。

    粒度を段階的に落とすのは、~18 分のエクスポートで「1104 秒」と出しても
    読者が待てるかどうかを判断できないため。負値・NaN は 0 として扱う
    (ETA は経過時間から外挿するので、時計の逆行で負にならない保証が無い)。
    """
    if not (seconds > 0):  # NaN もここへ落ちる
        return "0 秒"
    total = int(seconds + 0.5)
    if total < 60:
        return f"{total} 秒"
    if total < 3600:
        minutes, sec = divmod(total, 60)
        return f"{minutes} 分 {sec} 秒" if sec else f"{minutes} 分"
    hours, rest = divmod(total, 3600)
    minutes = rest // 60
    return f"{hours} 時間 {minutes} 分" if minutes else f"{hours} 時間"
```

`src/valisync/gui/views/export_confirm.py`（新規・Qt 非依存）:

```python
"""エクスポート確認ダイアログの本文と閾値判定 (pure・E-4b B2)。

QMessageBox の組み立ては ``MainWindow._default_confirm_export`` が行い、ここは
「何を見せるか」だけを持つ — file_browser_view の ``_default_confirm`` /
``_confirm_fn`` と同じ分離 (spec §5.5 [I15/ux-A])。pure なので Qt 無しでテストできる。
"""

from __future__ import annotations

from valisync.core.export.estimate import CONFIRM_THRESHOLD_S, ExportEstimate
from valisync.gui import strings as S
from valisync.gui.formatting import format_duration
from valisync.gui.viewmodels.file_browser_vm import _fmt_size


def needs_confirmation(est: ExportEstimate) -> bool:
    """確認を出すか。**推定時間ベース** (spec I10)。

    サイズ基準にすると「カーソル A-B x 全列」(出力 2 KB・読み 6.5 s) が素通りし、
    進捗もキャンセルも無いまま固まる。読み項と書き項を足すのは、どちらか一方でも
    支配しうるため (読み支配 = 範囲指定 x 全列 / 書き支配 = 全期間 x 全列)。
    """
    return (est.est_read_s + est.est_write_s) >= CONFIRM_THRESHOLD_S


def confirm_body(est: ExportEstimate) -> str:
    """B2 の 5 点。正確値と推定値を文言で区別する (「推定」の 2 文字が唯一の目印)。"""
    return S.EXPORT_CONFIRM_BODY_TMPL.format(
        columns=est.columns,
        rows=est.rows,
        size=_fmt_size(est.est_bytes),
        duration=format_duration(est.est_read_s + est.est_write_s),
        empty=round(est.empty_ratio * 100),
    )
```

`src/valisync/gui/strings.py`（`EXPORT_*` 群の末尾へ）:

```python
# ── エクスポート確認 (E-4b・B2 / spec §5.5) ──────────────────────────────────
# 桁区切りは付けない (既存決定・CHANNEL_HEADER_COUNT_TMPL と同規約)。列数/行数/
# 空セル率は **正確値**、サイズと時間は **推定値** — 読者がその区別を付けられるよう
# 推定側にだけ「推定」を冠する (B2)。空セル率は理由まで書かないと「壊れている」と
# 読まれる (spec §5.5 の文言例をそのまま採用)。
EXPORT_CONFIRM_TITLE: Final = "エクスポートの確認"
EXPORT_CONFIRM_BODY_TMPL: Final = (
    "{columns} 列 × {rows} 行を書き出します。\n"
    "推定サイズ: 約 {size}／推定時間: 約 {duration}\n"
    "出力の約 {empty} % は空セルです（信号ごとに記録周期が異なるため）。"
)
EXPORT_CONFIRM_YES: Final = "書き出す"  # 本文動詞と一致 (CONFIRM_CLOSE_YES と同規約)
EXPORT_CONFIRM_NO: Final = "キャンセル"
EXPORT_DISK_SHORT_TMPL: Final = (
    "保存先の空き容量が足りません（あと約 {shortfall} 必要です）。"
    "出力範囲を狭めるか列を減らしてください。"
)
```

`src/valisync/gui/views/main_window.py`:

1. import へ `from valisync.core.export.csv_exporter import estimate_output_bytes`（core 門番と同じ式・I-3 の上界包含用）と `from valisync.core.export.estimate import disk_shortfall, estimate_export`、`from valisync.gui.views.export_confirm import confirm_body, needs_confirmation` を追加（`disk_shortfall` はモジュール属性として参照するため、テストが `mw.disk_shortfall` を差し替えられる形で束縛する）。
2. `__init__` の `self._notify_blocked = self._default_blocked_modal` の直後へ:

```python
        # B2: 続行可否は人が決める。ダイアログ型は QMessageBox + DI (file_browser_view
        # の _confirm_fn と同規約) — realgui は実ボタンを押し、Layer B は差し替える。
        self._confirm_export_fn: Callable[[ExportEstimate], bool] = (
            self._default_confirm_export
        )
```

3. `export_csv` の末尾（`req is None` の後）を差し替え:

```python
        if req is None:
            return
        est = estimate_export(self.app_vm.session, req.keys, req.options)
        self._run_export(req, est)

    def _run_export(self, req: ExportRequest, est: ExportEstimate) -> None:
        """D5 検査 -> 確認 -> 投入。**拒否は D5 のディスク不足のみ** (B2)。

        見積を引数で受けるのは、キャンセル時に **開始前の値** を再掲する (B6) ため
        — 後から計算し直すと、unload 済みのファイルでは値が変わる/出せなくなる。
        """
        # **GUI 門番は core 門番を上界包含する**（順序逆転の構造排除・I-3）。
        # core (`csv_exporter._require_disk_space`) は粗い `_EST_BYTES_PER_CELL = 12`
        # で判定するので、GUI の推定 (実測校正済みの ~5.6 B/セル) だけを見ると
        # 「GUI の D5 を通過 -> 確認 Yes -> core で ValueError」という窓が開く。
        # 両者の大きい方で判定すれば、GUI を通ったものは必ず core も通る。
        need_bytes = max(
            est.est_bytes, estimate_output_bytes(est.rows, est.columns)
        )
        shortfall = disk_shortfall(req.output_path, need_bytes)
        if shortfall > 0:
            # 唯一の拒否。訊く前に落とす — 「はい」と答えても書けないので。
            self._notify_blocked(
                S.EXPORT_DISK_SHORT_TMPL.format(shortfall=_fmt_size(shortfall))
            )
            return
        if needs_confirmation(est) and not self._confirm_export_fn(est):
            return
        session = self.app_vm.session
        run = self._export_controller.prepare()  # Task 9 が中身を作る
        self._export_controller.submit(
            lambda: session.export_csv_request(
                req, progress=run.progress, cancel=run.cancel
            ),
            run=run,
            busy=self.busy_overlay,
            label=req.output_path.name,
            on_success=lambda: self.set_status_message(
                f"エクスポートしました: {req.output_path.name}"
            ),
            on_error=self._on_export_error,
            on_cancelled=lambda exc: self._on_export_cancelled(exc, est),
        )

    def _default_confirm_export(self, est: ExportEstimate) -> bool:
        # 標準ボタンのラベルを本文の動詞へ合わせるため、question() でなく
        # QMessageBox を明示構築する (file_browser_view._default_confirm と同型)。
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(S.EXPORT_CONFIRM_TITLE)
        box.setText(confirm_body(est))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        yes_button = box.button(QMessageBox.StandardButton.Yes)
        no_button = box.button(QMessageBox.StandardButton.No)
        assert yes_button is not None
        assert no_button is not None
        yes_button.setText(S.EXPORT_CONFIRM_YES)
        no_button.setText(S.EXPORT_CONFIRM_NO)
        return box.exec() == QMessageBox.StandardButton.Yes
```

> `_run_export` の `run=` / `on_cancelled=` / `session.export_csv_request` は **3 つとも Task 9 が作る**（`export_csv_request` は Task 4 の Produces にも `Session` の署名にも無い — Task 4 が作るのは `export_csv(keys, ...)` だけで、progress/cancel を運ぶ口は持たない）。Task 8 を単独で緑にするために、Task 9 未着手の時点では `run`/`on_cancelled` を渡さず `session.export_csv(req.keys, req.output_path, req.options, header_resolver=req.header_resolver, extra_signals=req.extra_signals)` を呼ぶ形（現行 `submit` シグネチャ）で書き、Task 9 が同じ関数を `export_csv_request` 版へ差し替えて 2 引数を足す。**どちらの形でも `_run_export` が「D5 → 確認 → submit」の順序を持つこと**が Task 8 の受け入れであり、Step 1 のテストはその順序だけを見る（`submit` を差し替えるので引数の形には依存しない）。

- [ ] **Step 5: 通ることを確認**

```
uv run pytest tests/test_export_estimate.py tests/gui/test_export_confirm.py -q
```
Expected: `16 passed`

- [ ] **Step 6: sabotage で honest-RED を確認（必須）**

pristine copy を先に取る。**`git checkout -- src/...` で戻さない**（過去に実装者が自分の未コミット作業を消している）:

```
cp src/valisync/core/export/estimate.py "$SCRATCH/estimate.py.orig"
cp src/valisync/gui/views/export_confirm.py "$SCRATCH/export_confirm.py.orig"
```
各 sabotage 後は該当ファイルを `cp` で復元し、復元直後に `uv run pytest tests/test_export_estimate.py tests/gui/test_export_confirm.py -q` が `16 passed` へ戻ることを確認してから次へ進む。

**到達範囲は主張でなく実測で確かめる**: 各 sabotage で予測 RED 集合を先に書き、`-q -rf` の実 failed 一覧と突き合わせる。一致しなければ予測かテストのどちらかが誤りなので、進めずに原因を報告へ書く。

| # | 壊す箇所（正確な編集） | 予測 RED |
|---|---|---|
| S1 | `est_read_s` を `columns * _READ_S_PER_COLD_CHANNEL` へ（列単価化 = spec 字面どおりの実装） | `test_read_term_counts_physical_channels_not_columns` の **1 件のみ**（他の fixture は 1 チャンネル 1 列なので列数=チャンネル数で見分けが付かない — この 1 本だけが識別力を持つことまで含めて実測と一致させる） |
| S2 | `needs_confirmation` を `est.est_bytes > 10_000_000` へ | `test_confirm_threshold_is_time_based_not_size_based` の **1 件のみ**（`_EST` 系の本文テストは閾値を見ていない） |
| S3 | `hit_mask(master, rows_ts)` を `np.ones(rows_ts.size, dtype=bool)` へ（全ヒット扱い） | `test_empty_ratio_is_exact_from_searchsorted_hits` の **1 件**（`test_rows_and_columns_are_exact` は union 長しか見ないので緑のまま） |
| S4 | `disk_shortfall` の `TEMP_AMPLIFICATION` を `1.0` へ（`csv_exporter.py` 側の実体を書き換える） | `test_disk_shortfall_requires_the_temp_amplification` の **1 件**。**同じ 1 箇所の編集が core 側 `_require_disk_space` も動かす**ことを `test_disk_space_shortage_is_rejected_before_writing`（Task 7）が緑のままであることで確認する（＝ 定数が 1 つであることの実証） |
| S6 | `estimate_export` の master 取得を `session.resolve_signal(key).timestamps` へ（値は読まないが**鋳造する**） | `test_estimate_reads_no_values_and_mints_no_columns` の **1 件**（`mint_count` が増える。`boom` は `array()` にしか仕掛けていないので「読んだ」側の assert は発火せず、**鋳造だけ**を捕まえていることを実測で確認する） |
| S6b | `estimate_export` の master 取得を `session.resolve_signal_transient(key).timestamps` へ（transient 経由で全列鋳造する） | `test_estimate_reads_no_values_and_mints_no_columns` の **1 件**（`transient_mint_count` が増える）。**S6 とは別勘定**なので、`transient_mint_count` の assert が無いとこの変異は**全緑で通る** — 行 6804 の「`resolve_signal_transient` を呼んでいないことをテストで固定する」という宣言が空手形でないことの実証 |

（旧 S5「`_row_window` の hi を `side="left"` へ」は**削除**した — `_row_window` は Task 5 の `row_range` へ統合され対象が消滅した。sides の変異検定は Task 5 の `test_row_range_includes_both_endpoints` / `test_row_range_agrees_with_in_range_row_by_row` が担う。）

**D5 が「唯一の拒否」であることの構造確認**（主張で済ませない）:

```
grep -n "return$\|return None" src/valisync/gui/views/main_window.py | sed -n '1,200p'
```
`_run_export` 内の早期 return が **2 つだけ**（D5 不足・確認拒否）であることを目視で確認する。3 つ目が増えていたら B2 の「拒否は D5 のみ」が破れている。

- [ ] **Step 7: ゲート＋コミット**

sabotage をすべて復元した状態で（**serial 実行・パイプ禁止** — `| tail` は exit code を隠す）:

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```
`uv run pytest -q` の passed 数が Step 1 のベースライン + 16 であること（skip 数も突き合わせる）。

**共有インターフェース契約を同時に更新する**: L43 の `est_read_s` の説明「cold **列**数 × **列**単価」を「cold **チャンネル**数 × **チャンネル**単価」へ（本タスクが宣言済みの意図的逸脱・spec §5.5 への追記は Task 11 が担当）。

```
git add src/valisync/core/export/estimate.py src/valisync/gui/formatting.py \
        src/valisync/gui/views/export_confirm.py src/valisync/gui/strings.py \
        src/valisync/gui/views/main_window.py src/valisync/core/session.py \
        src/valisync/core/loaders/signal_group_manager.py \
        tests/test_export_estimate.py tests/gui/test_export_confirm.py
git commit -m "$(cat <<'EOF'
feat(export): エクスポートの事前見積と確認ダイアログ (E-4b T-UX・B2/D5)

開始前に「列数・行数・空セル率 (正確値)」と「推定サイズ・推定時間 (推定値)」を
提示し、続行可否を人に決めさせる。拒否は D5 のディスク不足だけ (B2: 他は情報提示)。

見積は **値を 1 バイトも読まない**: 触るのは master (ロード時点でメモリに在る) と
ColumnRecord だけで、列の鋳造もしない (鋳造すると E-4a の LRU 枠を食い、プロット中で
ない列を押し出す)。union と searchsorted は Task 5 の timeline を、列 -> チャンネルの
解決は Task 6 の channel_key_of を共有する — 2 つ持つと見積の行数が出力とずれる。

読み項は **チャンネル単位** で数える (spec §5.5 の字面「cold 列数 x 列単価」からの
意図的逸脱): E-4a 以降の読みは 1 select + k スライスなので、列単位だと幅 1,100 の
チャンネルで 1,100 倍になり prod 全列の推定が ~29 時間 (§1 外挿 18.4 分の ~95 倍)
という桁の嘘になる。CSV/Derived は実体化済みなので読み項 0。

確認スキップ閾値は **推定時間 5 s** (spec I10)。サイズ基準だと「カーソル A-B x 全列」
(出力 2,057 B・読み 6.523 s の実測ケース) が素通りして無言で固まる。

係数 3 つ (チャンネル単価 0.316 s / セル単価 6.1e-7 s / 平均セル長 4.57 文字) は
quick_demo 由来の **暫定値**で、Task 11 が prod_demo 1 点で検定するまで受け入れ帯に
使わない (合成由来の単価はこのシリーズで 3 回桁を外している)。D5 の必要量は多段
マージの中間 temp を含む 2.3 x 推定出力 (実係数も Task 11 検証)。

sabotage 実測: 列単価化=1 RED / サイズ閾値化=1 RED / 全ヒット扱い=1 RED /
2.3 -> 1.0=1 RED / 閉区間の右端=1 RED / resolve 経由の master 取得 (鋳造) =1 RED。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 9: BusyOverlay 3 衝突の解消＋協調キャンセル配線（spec §5.5 後半）

**Files:**
- Modify: `src/valisync/gui/views/busy_overlay.py`（所有権 `acquire`/`release`・determinate 進捗・ETA ラベル・キャンセルボタンの有効/無効）
- Modify: `src/valisync/gui/workers/load_worker.py`（`LoadController` の `busy.show()/hide()` を所有権 API へ）
- Modify: `src/valisync/gui/workers/export_worker.py`（`ExportRun`／`prepare()`／`cancel_active()`／進捗の queued 配送／`ExportCancelled` の routing）
- Modify: `src/valisync/core/session.py`（`export_csv_request` を追加 — progress/cancel をパイプラインへ届ける唯一の口）
- Modify: `src/valisync/gui/views/main_window.py`（`:209` の恒久配線をルータへ・`_on_export_cancelled`・`_run_export` の submit を `export_csv_request` 版へ）
- Modify: `src/valisync/gui/strings.py`（ETA・中止中・中止後メッセージ・decay 診断）
- Test: `tests/gui/test_busy_ownership_progress.py`（新規）
- Test: `tests/gui/test_export_cancel_routing.py`（新規・G6/G7 を含む）

**Interfaces:**

- **Consumes**:
  - Task 7 の `CsvExporter.export(request, resolve, *, progress, cancel)` と `ExportCancelled`（共有契約の逐語形）
  - Task 4 の `Session.export_csv` / `ExportRequest`（`_run_export` が呼ぶ形）
  - Task 8 の `ExportEstimate`（B6 のキャンセルメッセージで再掲）／`gui.formatting.format_duration`（ETA）
  - **Task 10b の `Session.export_resolver()` と `ExportSourceLost`** — G6/G7 のテスト（`test_cancelling_export_leaves_no_file_and_no_temp` / `test_export_runs_off_the_gui_thread_at_resolve_and_at_write`）が `session.export_resolver()` を直接呼び、`_on_export_cancelled` が `isinstance(exc, ExportSourceLost)` で診断を出し分ける。**番号順（8 → 9 → 10）で実行すると AttributeError で停止する** — 依存グラフのとおり Task 10b を先に入れること
  - 既存: `LoadController.cancel_active`（挙動そのものは変えない — 隠す手段だけ所有権 API へ移す）
- **Produces**（Task 11 の realgui ①ゲートが実 OS 入力で駆動する面）:
  - `Session.export_csv_request(request: ExportRequest, *, progress: Callable[[int, int], None] | None = None, cancel: threading.Event | None = None) -> None` — `self._exporter.export(request, <resolver>, progress=progress, cancel=cancel)` への薄い委譲（`<resolver>` は Task 10b 適用後 `self.export_resolver()`・それ以前は `self.resolve_signal_transient`）。**GUI 経路から progress/cancel がパイプラインへ届く唯一の口**で、これが無いと Task 8 が書いた `_run_export` の `run.progress` / `run.cancel` が行き先を失う
  - `BusyOverlay.acquire(owner, *, message) / release(owner) / owner_count() / set_progress(owner, done, total) / eta_text() / set_cancel_enabled(enabled)`
  - `BusyOverlay(parent=None, *, clock=time.monotonic)`（ETA を決定的にテストするための注入口）
  - `ExportController.prepare() -> ExportRun`（`.progress(done, total)` / `.cancel: threading.Event`）
  - `ExportController.cancel_active()`
  - `MainWindow._cancel_busy_operations()`（`cancel_requested` の宛先）
  - `MainWindow._on_export_cancelled(exc, est)`（B6）

**この増分で最も壊しやすい点**

`main_window.py:209` の

```python
self.busy_overlay.cancel_requested.connect(self._load_controller.cancel_active)
```

は**エクスポート中のキャンセルボタンを今日死なせている**。単に宛先を差し替えるだけでは不十分で、`LoadController._refresh_busy` / `cancel_active` が `busy.hide()` を**直接**呼ぶ限り、ロードの完了がエクスポートの overlay を消す（衝突 2）。所有権を入れずに宛先だけ直すと、キャンセルは効くのに overlay が先に消えて「終わったように見えるが temp を消している最中」という B6 契約の観測窓が壊れる。

- [ ] **Step 1: 失敗テストを書く**

まずベースラインを記録する（**パイプ禁止**）:

```
uv run pytest -q
```
→ `N passed, M skipped` を控える。Step 7 で **`N + 14 passed`**（本タスクの新規 14 本 = ownership 7 ＋ cancel routing 7）になることを確認する。

`tests/gui/test_busy_ownership_progress.py`:

```python
# ruff: noqa: RUF002, RUF003
"""BusyOverlay の所有権 (参照カウント) と determinate 進捗 / ETA (E-4b・spec §5.5)。

今日の 3 衝突のうち 2 つ (所有権・不確定バー) をここで閉じる。3 つ目 (cancel の
恒久配線) は test_export_cancel_routing.py。

ETA は注入した時計で駆動する — wall-clock に依存させると「遅いマシンで落ちる」
テストになり、値を緩めた瞬間に何も検証しなくなる。
"""

from __future__ import annotations

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]

from valisync.gui.views.busy_overlay import BusyOverlay


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_overlay_stays_up_until_every_owner_releases(qtbot: QtBot) -> None:
    """衝突 2: 1 インスタンス共有でも、片方の完了が他方の overlay を消さない。"""
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    load, export = object(), object()

    overlay.acquire(load, message="a.mf4 を読み込み中…")
    overlay.acquire(export, message="out.csv をエクスポート中…")
    assert overlay.owner_count() == 2
    assert not overlay.isHidden()

    overlay.release(export)
    assert not overlay.isHidden(), "export の完了が load の overlay を消した"
    assert overlay.message() == "a.mf4 を読み込み中…", "残った所有者の文言へ戻らない"

    overlay.release(load)
    assert overlay.isHidden()
    assert overlay.owner_count() == 0


def test_release_of_a_non_owner_is_a_no_op(qtbot: QtBot) -> None:
    """遅れて届いた解放が、無関係な所有者の overlay を落とさない。

    LoadController は cancel 済みワーカーの完了で _refresh_busy を呼ばないが、
    非 cancel の別ワーカーが後から 0 件で refresh する経路がある (load_worker._pop)。
    """
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    owner = object()
    overlay.acquire(owner, message="x")
    overlay.release(object())
    assert not overlay.isHidden()
    assert overlay.owner_count() == 1


def test_progress_makes_the_bar_determinate_and_release_restores_it(
    qtbot: QtBot,
) -> None:
    """衝突 3: ブロック進捗を出す。解放したら不確定へ戻す (次のロードが壊れない)。"""
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    owner = object()
    assert overlay.is_indeterminate()  # 構築直後は従来どおり不確定

    overlay.acquire(owner, message="エクスポート中…")
    overlay.set_progress(owner, 3, 12)

    assert not overlay.is_indeterminate()
    assert overlay.progress_bar.maximum() == 12
    assert overlay.progress_bar.value() == 3

    overlay.release(owner)
    assert overlay.is_indeterminate(), "解放後も determinate のままだと次のロードで固着"


def test_eta_says_measuring_until_the_first_unit_completes(qtbot: QtBot) -> None:
    """done=0 は 0 除算そのもの。外挿できないことを人に見せる (spec §5.5)。"""
    clock = _Clock()
    overlay = BusyOverlay(clock=clock)
    qtbot.addWidget(overlay)
    owner = object()
    overlay.acquire(owner, message="エクスポート中…")

    clock.now = 4.0
    overlay.set_progress(owner, 0, 10)

    assert "計測中" in overlay.eta_text()


def test_eta_extrapolates_from_elapsed_over_completed(qtbot: QtBot) -> None:
    """経過 x 残り/完了。2/10 を 4 秒で終えたなら残り 8 単位 = 16 秒。"""
    clock = _Clock()
    overlay = BusyOverlay(clock=clock)
    qtbot.addWidget(overlay)
    owner = object()
    overlay.acquire(owner, message="エクスポート中…")
    overlay.set_progress(owner, 0, 10)  # 起点を記録

    clock.now = 4.0
    overlay.set_progress(owner, 2, 10)

    assert "16 秒" in overlay.eta_text(), overlay.eta_text()


def test_zero_total_does_not_divide_by_zero(qtbot: QtBot) -> None:
    """総単位 0 (空選択の縁) でも例外を出さない。"""
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    owner = object()
    overlay.acquire(owner, message="x")
    overlay.set_progress(owner, 0, 0)
    assert overlay.is_indeterminate()


def test_progress_from_a_released_owner_is_ignored(qtbot: QtBot) -> None:
    """queued 配送で遅れて届いた進捗が、解放済みの overlay を再表示しない。"""
    overlay = BusyOverlay()
    qtbot.addWidget(overlay)
    owner = object()
    overlay.acquire(owner, message="x")
    overlay.release(owner)
    overlay.set_progress(owner, 5, 10)
    assert overlay.isHidden()
    assert overlay.is_indeterminate()
```

`tests/gui/test_export_cancel_routing.py`:

```python
# ruff: noqa: RUF002, RUF003
"""キャンセルの配線・オフスレッド性・temp の後始末 (E-4b・G6/G7・spec §5.5-1)。

今日の欠陥: busy_overlay.cancel_requested は _load_controller.cancel_active へ
**恒久配線**されており、エクスポート中のキャンセルボタンは押しても何も起きない。
ここではボタンの下流 (MainWindow のルータ) を効果で固定する。

G6/G7 は実 CsvExporter を実ファイルへ走らせる (スタブでは temp も別スレッドも
存在しないので、どちらの契約も検証できない)。
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from pytestqt.qtbot import QtBot  # type: ignore[import-untyped]


def test_cancel_button_routes_to_every_active_controller(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """load / export の **両方** が走っていれば両方が中止される。

    「今アクティブなのはどれか」を別に持たない設計の受け入れ: ルータに状態を作ると
    2 つ目の真実になり必ず腐る (旧実装が load へ恒久配線されていたのがまさにそれ)。
    """
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    load_cancel = threading.Event()
    export_release = threading.Event()

    window._load_controller.submit(
        lambda: load_cancel.wait(5.0) or _outcome(tmp_path),
        busy=window.busy_overlay,
        cancel_event=load_cancel,
        label="a.mf4",
    )
    run = window._export_controller.prepare()
    window._export_controller.submit(
        lambda: export_release.wait(5.0),
        run=run,
        busy=window.busy_overlay,
        label="out.csv",
    )

    window.busy_overlay.cancel_requested.emit()

    assert load_cancel.is_set(), "load へ届いていない"
    assert run.cancel.is_set(), "export へ届いていない (今日の欠陥そのもの)"
    export_release.set()
    qtbot.waitUntil(lambda: not window._export_controller.is_busy(), timeout=5000)


def test_cancelling_export_leaves_no_file_and_no_temp(qtbot: QtBot, tmp_path: Path) -> None:
    """G6: temp が **一度は存在した** ことを観測してから、消滅とファイル不在を assert。

    上界 0 だけ (temp が無い) を見ると、そもそも temp を作らない実装や 0 行で
    即終了した実装でも緑になる (空虚形)。
    """
    from valisync.core.export.csv_exporter import CsvExporter, ExportCancelled

    session, request = _big_request(tmp_path)
    out = request.output_path
    system_temp_before = set(Path(tempfile.gettempdir()).glob(".tmp_*"))
    seen: list[str] = []
    cancel = threading.Event()

    def progress(done: int, total: int) -> None:
        seen.extend(p.name for p in out.parent.glob(".tmp_*"))
        if done >= 1:
            cancel.set()

    exporter = CsvExporter()
    raised = False
    try:
        exporter.export(
            request,
            session.export_resolver(),
            progress=progress,
            cancel=cancel,
        )
    except ExportCancelled:
        raised = True

    assert raised, "cancel を立てたのに完走した (協調キャンセルが効いていない)"
    assert seen, "temp が一度も観測されなかった — 消滅 assert が空虚形になっている"
    assert list(out.parent.glob(".tmp_*")) == [], "temp が残った (B6 違反)"
    assert not out.exists(), "キャンセルしたのに出力ファイルが存在する"
    # temp は **出力先と同一ディレクトリ** (os.replace の原子性と D5 の
    # ボリューム検査が同じボリュームであることの前提・spec §10)。
    assert set(Path(tempfile.gettempdir()).glob(".tmp_*")) == system_temp_before


def test_export_runs_off_the_gui_thread_at_resolve_and_at_write(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """G7: 捕捉点 2 箇所 (解決時・書き時)。部分インライン化を検出する。

    1 点だけだと「解決は GUI スレッドで先にやって書きだけ逃がす」実装が緑になり、
    E-4b が消そうとしている「保存を押した瞬間に固まる」体感が残る。
    """
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    session, request = _big_request(tmp_path)
    main_ident = threading.get_ident()
    at_resolve: list[int] = []
    at_write: list[int] = []
    base_resolver = session.export_resolver()

    def resolve(key: str):  # type: ignore[no-untyped-def]
        at_resolve.append(threading.get_ident())
        return base_resolver(key)

    done: list[bool] = []
    run = window._export_controller.prepare()

    def do_export() -> None:
        from valisync.core.export.csv_exporter import CsvExporter

        CsvExporter().export(
            request,
            resolve,
            progress=lambda d, t: at_write.append(threading.get_ident()),
            cancel=run.cancel,
        )

    window._export_controller.submit(
        do_export, run=run, busy=window.busy_overlay,
        on_success=lambda: done.append(True),
    )
    qtbot.waitUntil(lambda: done == [True], timeout=20000)

    assert at_resolve and at_write
    assert main_ident not in at_resolve, "列解決が GUI スレッドで走っている"
    assert main_ident not in at_write, "書き出しが GUI スレッドで走っている"
    assert set(at_resolve) == set(at_write), "解決と書きが別スレッドに分かれている"


def test_cancelled_export_reports_the_pre_start_estimate(qtbot: QtBot, tmp_path: Path) -> None:
    """B6: キャンセル後は開始前の見積値を再掲し、削り方を促す。"""
    from valisync.core.export.estimate import ExportEstimate
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    est = ExportEstimate(1234, 5678, 0.66, 10_100_000_000, 600.0, 504.0)
    from valisync.core.export.csv_exporter import ExportCancelled

    window._on_export_cancelled(ExportCancelled("cancelled"), est)

    msg = window.status_message()
    assert "1234" in msg and "5678" in msg
    assert "1,234" not in msg  # 桁区切りは付けない
    assert "狭め" in msg or "減らし" in msg


def test_cancel_callback_is_actually_wired_to_the_controller(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """上のテストは `_on_export_cancelled` を**直呼び**するので、`_run_export` の
    `on_cancelled=` 配線が消えても緑のまま (M-12)。submit 経由で
    ``ExportCancelled`` を投げさせ、配線そのものを効果で見る。
    """
    from valisync.core.export.csv_exporter import ExportCancelled
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    seen: list[Exception] = []
    window._on_export_cancelled = lambda exc, est: seen.append(exc)  # type: ignore[assignment]
    window._confirm_export_fn = lambda _e: True

    est = _tiny_estimate()
    run = window._export_controller.prepare()

    def boom() -> None:
        raise ExportCancelled("cancelled")

    window._export_controller.submit(
        boom,
        run=run,
        busy=window.busy_overlay,
        on_cancelled=lambda exc: window._on_export_cancelled(exc, est),
    )
    qtbot.waitUntil(lambda: len(seen) == 1, timeout=5000)
    assert isinstance(seen[0], ExportCancelled)
    # 反 vacuous: エラー面へは流れていない (ExportCancelled は正常系)。
    assert window.busy_overlay.isHidden()


def test_source_lost_adds_one_diagnostic_but_a_user_cancel_does_not(
    qtbot: QtBot,
) -> None:
    """spec §5.7 [I7c] の「診断 1 件」。**出し分け**が本体。

    ユーザーが押した中止まで診断を出すと診断ドックが中止のたびに汚れ、
    逆に出さないと「元ファイルが消えた」が数秒で流れるステータスにしか
    残らず、後から辿れない。
    """
    from valisync.core.export.csv_exporter import ExportCancelled, ExportSourceLost
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    est = _tiny_estimate()
    before = len(window.app_vm.diagnostics)

    window._on_export_cancelled(ExportCancelled("user"), est)
    assert len(window.app_vm.diagnostics) == before, "ユーザー中止で診断が増えた"

    window._on_export_cancelled(ExportSourceLost("mf4_1::A が読めません"), est)
    assert len(window.app_vm.diagnostics) == before + 1
    added = window.app_vm.diagnostics[-1]
    assert added.level == "error"
    assert "mf4_1::A" in added.message


def _tiny_estimate():  # type: ignore[no-untyped-def]
    from valisync.core.export.estimate import ExportEstimate

    return ExportEstimate(1, 1, 0.0, 10, 0.0, 0.0)


def test_cancel_keeps_the_overlay_up_until_the_worker_stops(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """export の cancel は load と **非対称** (即時 UI 解放をしない)。

    temp を消し切る前に「中止した」と見せると、ユーザーは残骸が消える前に次の
    エクスポートを始められ、「失敗ならファイルが存在しない」の観測窓が壊れる。
    """
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    release = threading.Event()
    run = window._export_controller.prepare()
    window._export_controller.submit(
        lambda: release.wait(5.0), run=run, busy=window.busy_overlay, label="out.csv"
    )
    assert not window.busy_overlay.isHidden()

    window._cancel_busy_operations()

    assert run.cancel.is_set()
    assert not window.busy_overlay.isHidden(), "worker 停止前に overlay を下ろした"
    assert window.busy_overlay.cancel_button.isEnabled() is False
    assert "中止" in window.busy_overlay.message()

    release.set()
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=5000)
```

`_outcome` / `_big_request` はファイル末尾のヘルパ（実 mf4 を 1 本書き、Task 4 の `ExportRequest` を組む）:

```python
def _outcome(tmp_path: Path):  # type: ignore[no-untyped-def]
    from tests.mdf4_helpers import CAN, write_mdf4
    from valisync.core.session import Session

    path = tmp_path / f"late_{threading.get_ident()}.mf4"
    write_mdf4(
        path,
        [{"name": "S", "bus_type": CAN, "timestamps": [0.0], "values": [1.0]}],
    )
    return Session().load(path)


def _big_request(tmp_path: Path):  # type: ignore[no-untyped-def]
    """進捗が 2 回以上出る規模 (ブロック境界を跨ぐ) の実セッションと ExportRequest。

    ブロック数 1 だと progress が 1 回しか呼ばれず、G6 の「done >= 1 で cancel」が
    「最後の 1 単位の直後」= 実質完走になる。**複数ブロック**が G6/G7 の前提。
    """
    from tests.mdf4_helpers import CAN, write_mdf4
    from valisync.core.export.csv_exporter import CsvExportOptions, ExportRequest
    from valisync.core.session import Session

    path = tmp_path / "big.mf4"
    ts = [round(i * 0.001, 6) for i in range(4000)]
    write_mdf4(
        path,
        [
            {
                "name": f"Ch{i:03d}",
                "bus_type": CAN,
                "timestamps": ts,
                "values": [float(i * 1000 + j) for j in range(len(ts))],
            }
            for i in range(48)
        ],
    )
    session = Session()
    key = session.load(path).key
    keys = tuple(f"{key}::Ch{i:03d}" for i in range(48))
    request = ExportRequest(
        keys=keys,
        output_path=tmp_path / "out.csv",
        options=CsvExportOptions(),
        header_resolver=list,
    )
    return session, request
```

**この時点で走らせて RED を確認する**:

```
uv run pytest tests/gui/test_busy_ownership_progress.py tests/gui/test_export_cancel_routing.py -q
```

**予測 RED**: `test_busy_ownership_progress.py` は **7 本すべてが AttributeError**（`BusyOverlay.acquire` / `release` / `owner_count` / `set_progress` / `eta_text` が不在・`BusyOverlay(clock=...)` は `TypeError`）。`test_export_cancel_routing.py` は **7 本すべてが AttributeError**（`ExportController.prepare` / `MainWindow._cancel_busy_operations` / `MainWindow._on_export_cancelled` / `Session.export_csv_request` が不在）。**collection error にはならない**（import はモジュール単位で、不在なのは属性だから）。`ImportError` が出たら Task 10b が未着手（`ExportSourceLost`）なので、進めずに依存グラフへ戻る。

> `block_cols` は Task 6 が動的に決めるため、48 列 x 4,000 行で複数ブロックになるとは限らない。**`_big_request` の直後に `assert` でブロック数を固定しない**代わりに、G6/G7 のテスト側で `progress` の呼び出し回数が 2 以上であることを確認する（1 回しか来なければ fixture の規模不足として loud-fail する）。Task 6 の `block_cols` 決定関数が公開されていれば、それを注入して 8 列固定にするのが望ましい（Step 2 で実物を確認して、注入できるなら注入する）。

- [ ] **Step 2: `BusyOverlay` に所有権と determinate 進捗を入れる**

`src/valisync/gui/views/busy_overlay.py`（差分の要点。既存の `set_message` / `message` / `is_indeterminate` / `cover` / `show` / `eventFilter` は**そのまま残す** — `test_load_worker.py` の 5 本と realgui 4 本が掴んでいる）:

```python
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # 既存 3 ウィジェット (_label / progress_bar / cancel_button) の構築は不変。
        # 足すのは ETA 用の 4 つ目のラベルと、所有権/時計の 4 フィールドだけ。
        super().__init__(parent)
        self._label = QLabel("読み込み中…", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)  # 既定は不確定 (既存 test-lock)
        self.progress_bar.setTextVisible(False)
        self.cancel_button = QPushButton("キャンセル", self)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self._eta = QLabel("", self)
        self._eta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._eta.setVisible(False)  # 不確定のあいだは行そのものを出さない

        layout = QVBoxLayout(self)
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._eta, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.hide()
        if parent is not None:
            parent.installEventFilter(self)  # FU-02 (既存コメントは維持)

        # 所有権 (spec §5.5-2)。1 インスタンスを LoadController (件数ベース) と
        # ExportController (旧: 無条件 hide) が共有しており、相互ガードが無かった。
        # dict は挿入順 = 取得順で、**最後に取った所有者の文言** を出す。
        self._owners: dict[int, tuple[object, str]] = {}
        self._clock = clock
        self._progress_owner: object | None = None
        self._progress_started = 0.0

    def acquire(self, owner: object, *, message: str) -> None:
        """*owner* の名義で overlay を出す (同じ owner の再取得は文言更新)。"""
        self._owners.pop(id(owner), None)  # 再取得は最新へ (文言の最終決定者)
        self._owners[id(owner)] = (owner, message)
        self._label.setText(message)
        self.cancel_button.setEnabled(True)
        self.show()

    def release(self, owner: object) -> None:
        """*owner* の名義を返す。**最後の 1 人が返したときだけ** 隠す。"""
        if self._owners.pop(id(owner), None) is None:
            return  # 非所有者の解放は no-op (遅れて届いた完了で他人を消さない)
        if self._progress_owner is owner:
            self._reset_progress()
        if self._owners:
            self._label.setText(next(reversed(self._owners.values()))[1])
            return
        self.hide()

    def owner_count(self) -> int:
        """現在この overlay を保持している所有者の数 (test-facing)."""
        return len(self._owners)

    def set_progress(self, owner: object, done: int, total: int) -> None:
        """ブロック単位の進捗を determinate バーと ETA へ反映する (spec §5.5-3)。

        解放済み owner からの進捗は捨てる — 進捗は queued 配送 (ワーカースレッド
        -> GUI スレッド) なので、完了/キャンセルの後に 1-2 発遅れて届く。
        """
        if id(owner) not in self._owners or total <= 0:
            return
        if self._progress_owner is not owner:
            self._progress_owner = owner
            self._progress_started = self._clock()
        self.progress_bar.setRange(0, int(total))
        self.progress_bar.setValue(int(done))
        self._eta.setText(self._eta_text_for(int(done), int(total)))
        self._eta.setVisible(True)

    def eta_text(self) -> str:
        """現在の ETA 表示 (test-facing)."""
        return self._eta.text()

    def set_cancel_enabled(self, enabled: bool) -> None:
        """キャンセル要求が受理された後、二重押しを防ぐために落とす。"""
        self.cancel_button.setEnabled(enabled)

    def _eta_text_for(self, done: int, total: int) -> str:
        if done <= 0:
            # **0 除算ガードそのもの**。最初のブロックが終わるまでは外挿できない
            # ことを人に見せる (「残り 0 秒」と嘘をつかない)。
            return S.BUSY_ETA_MEASURING
        elapsed = self._clock() - self._progress_started
        remaining = elapsed * (total - done) / done
        return S.BUSY_ETA_TMPL.format(eta=format_duration(remaining))

    def _reset_progress(self) -> None:
        """不確定へ戻す (次のロードが determinate のまま固着しないように)。"""
        self._progress_owner = None
        self.progress_bar.setRange(0, 0)
        self._eta.setText("")
        self._eta.setVisible(False)
        self.cancel_button.setEnabled(True)
```

import へ `time` / `Callable` / `from valisync.gui import strings as S` / `from valisync.gui.formatting import format_duration` を追加。

- [ ] **Step 3: 2 つの Controller を所有権 API へ移す**

`load_worker.py`（**挙動は不変**・隠す手段だけ差し替え）:

```python
    def cancel_active(self) -> None:
        """Cancel every active load: hard (events) + soft (immediate UI release)."""
        busies = set()
        for worker, (event, _label, busy, _discard) in self._active.items():
            if event is not None:
                event.set()
            self._cancelled.add(worker)
            if busy is not None:
                busies.add(busy)
        for busy in busies:
            # E-4b: hide() 直呼びをやめる。1 インスタンスを export と共有しており、
            # 直に隠すとエクスポート中の overlay まで消える (spec §5.5-2)。
            # 所有者が自分だけなら release がそのまま hide になるので、既存の
            # 「ソフト側は即時解放」契約 (test_load_worker.py) はバイト等価に保たれる。
            busy.release(self)
```

`_refresh_busy` も同型:

```python
        if not labels:
            busy.release(self)
            return
        if len(labels) == 1:
            busy.acquire(self, message=S.BUSY_LOADING_TMPL.format(label=labels[0] or "ファイル"))
        else:
            busy.acquire(self, message=S.BUSY_LOADING_MULTI_TMPL.format(n=len(labels)))
```

`export_worker.py`:

```python
class ExportRunSignals(QObject):
    progress = Signal(int, int)  # (done_units, total_units)


class ExportRun:
    """1 回のエクスポートに紐づく進捗シンクと協調キャンセル Event。

    ``ExportController.prepare()`` が **GUI スレッドで** 作る — QObject の affinity が
    GUI スレッドになり、ワーカースレッドからの emit が自動的に queued 配送になる
    (直接 UI を触ると Qt が落ちる)。呼び出し側はこれを export callable へ close over
    して ``CsvExporter.export(progress=, cancel=)`` へ渡す。callable の引数を
    controller が規定しない形にしてあるので、**ゼロ引数 submit の既存契約**
    (tests/gui/test_unload_export_guard.py が実行している) はそのまま生きる。
    """

    __slots__ = ("cancel", "signals")

    def __init__(self) -> None:
        self.signals = ExportRunSignals()
        self.cancel = threading.Event()

    def progress(self, done: int, total: int) -> None:
        """ワーカースレッドから呼ぶ (queued で GUI スレッドへ運ばれる)。"""
        self.signals.progress.emit(int(done), int(total))
```

`ExportController`:

```python
        # worker -> (run, busy)。run を保持するのは signals の生存だけでなく、
        # cancel_active が Event へ届くための唯一の経路でもある。
        self._active: dict[ExportWorker, tuple[ExportRun, BusyOverlay | None]] = {}

    def prepare(self) -> ExportRun:
        """submit の **前** に進捗/キャンセルのハンドルを渡す。

        callable は呼び出し側が組むので、submit の後では間に合わない (ワーカーが
        走り出してから progress を差し込む窓は無い)。
        """
        return ExportRun()

    def submit(
        self,
        export_callable: Callable[[], None],
        *,
        run: ExportRun | None = None,
        busy: BusyOverlay | None = None,
        on_success: Callable[[], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_cancelled: Callable[[Exception], None] | None = None,
        label: str | None = None,
    ) -> None:
        run = run if run is not None else ExportRun()
        worker = ExportWorker(export_callable)
        self._active[worker] = (run, busy)
        if busy is not None:
            busy.acquire(self, message=S.BUSY_EXPORTING_TMPL.format(label=label or "CSV"))
            run.signals.progress.connect(
                lambda done, total: busy.set_progress(self, done, total)
            )
        worker.signals.finished.connect(lambda: self._finish(worker, on_success))
        worker.signals.failed.connect(
            lambda exc: self._fail(worker, exc, on_error, on_cancelled)
        )
        self._pool.start(worker)

    def cancel_active(self) -> None:
        """実行中のエクスポートへ協調キャンセルを要求する。

        load 側 (soft-cancel = 即 UI 解放) と **意図的に非対称**: overlay は
        ExportCancelled が戻るまで下ろさない。temp を消し切る前に「中止した」と
        見せると、ユーザーは残骸が消える前に次のエクスポートを始められ、
        「失敗ならファイルが存在しない」(spec §10) の観測窓が壊れる。
        """
        for run, busy in self._active.values():
            run.cancel.set()
            if busy is not None:
                busy.set_message(S.BUSY_EXPORT_CANCELLING)
                busy.set_cancel_enabled(False)  # 二重押しで別の操作を巻き込まない

    def _finish(self, worker, on_success) -> None:  # type: ignore[no-untyped-def]
        _run, busy = self._active.pop(worker)
        if busy is not None:
            busy.release(self)
        if on_success is not None:
            on_success()

    def _fail(self, worker, exc, on_error, on_cancelled) -> None:  # type: ignore[no-untyped-def]
        from valisync.core.export.csv_exporter import ExportCancelled

        _run, busy = self._active.pop(worker)
        if busy is not None:
            busy.release(self)
        if isinstance(exc, ExportCancelled):
            # ユーザー起点 (と decay) の正常系 — エラー面へ流さない
            # (LoadCancelled が on_cancelled へ回るのと同型)。
            if on_cancelled is not None:
                on_cancelled(exc)
            return
        if on_error is not None:
            on_error(exc)
```

`is_busy()` は `bool(self._active)` のまま（dict 化しても真理値は同じ・既存テスト無編集）。

- [ ] **Step 4: `main_window.py:209` の恒久配線をルータへ**

```python
        # 旧: self.busy_overlay.cancel_requested.connect(self._load_controller.cancel_active)
        # -> エクスポート中のキャンセルボタンは押しても何も起きなかった (spec §5.5-1)。
        self.busy_overlay.cancel_requested.connect(self._cancel_busy_operations)
```

```python
    def _cancel_busy_operations(self) -> None:
        """BusyOverlay のキャンセルを **実行中の全操作** へ配る (spec §5.5-1)。

        「今アクティブなのはどれか」をルータ側に持たない: 各コントローラは自分の
        active 集合を既に持っており、アイドルなら cancel_active は no-op。ルータに
        状態を作ると 2 つ目の真実になり必ず腐る — 旧実装が load へ恒久配線されて
        いたのがまさにその腐り方だった。
        """
        self._load_controller.cancel_active()
        self._export_controller.cancel_active()

    def _on_export_cancelled(self, exc: Exception, est: ExportEstimate) -> None:
        """B6: 中止を告げ、**開始前の見積値** を再掲して削り方を促す。

        中止後に測り直さないのは、unload 済み/範囲変更後では値が変わってしまい、
        「なぜ止めたのか」の手がかりにならないため。

        **ユーザーが押した中止と「元ファイルが消えた」を出し分ける** (spec §5.7
        [I7c] の「診断 1 件」): `ExportSourceLost` は `ExportCancelled` の
        サブクラスなので temp 削除の経路は共有するが、原因はユーザー起点ではない
        — ステータス行は数秒で流れるので、**診断ドックへ 1 件残す**のが「なぜ
        出力が無いのか」を後から辿れる唯一の記録になる。
        """
        from valisync.core.export.csv_exporter import ExportSourceLost

        if isinstance(exc, ExportSourceLost):
            self.app_vm.add_diagnostic(
                level="error", message=S.EXPORT_SOURCE_LOST_DIAG_TMPL.format(reason=exc)
            )
        self.set_status_message(
            S.EXPORT_CANCELLED_TMPL.format(
                columns=est.columns, rows=est.rows, size=_fmt_size(est.est_bytes)
            )
        )
```

> `app_vm.add_diagnostic` と読み側 `app_vm.diagnostics` の実名は実装時に確認する（`grep -n "diagnostic" src/valisync/gui/viewmodels/app_viewmodel.py`）。既存の診断追加口・読み口と**同じ 1 本ずつ**を使う（新設しない）。名前が違えばテスト側の 2 サイトも同時に合わせ、違っていた事実を報告に書く。

`src/valisync/core/session.py`（C-2 の欠落配線）:

```python
    def export_csv_request(
        self,
        request: ExportRequest,
        *,
        progress: Callable[[int, int], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        """組み立て済みの *request* をそのまま書き出す（progress/cancel つき）。

        `export_csv(keys, ...)` との違いは 2 点だけ: **要求を組み直さない**
        （GUI が `header_resolver` まで決めた `ExportRequest` を持っているので、
        keys へ分解して組み直すと resolver が既定へ落ちてヘッダが変わる）と、
        **progress/cancel を通す**こと。GUI 経路がこの 2 つをパイプラインへ
        届ける唯一の口で、これが無いと `ExportRun` の進捗もキャンセルも
        `CsvExporter` に到達しない（キャンセルボタンが押せるのに効かない）。
        """
        self._reject_container_channels(
            (*request.keys, *(s.name for s in request.extra_signals))
        )
        self._exporter.export(
            request,
            self.export_resolver(),  # Task 10b。未着手なら resolve_signal_transient
            progress=progress,
            cancel=cancel,
        )
```

`strings.py`:

```python
# ── BusyOverlay の ETA / エクスポート中止 (E-4b・spec §5.5-3 / B6 / §5.7 I7c) ──
BUSY_ETA_MEASURING: Final = "残り時間: 計測中…"
BUSY_ETA_TMPL: Final = "残り時間: 約 {eta}"
BUSY_EXPORT_CANCELLING: Final = "エクスポートを中止しています…"
EXPORT_CANCELLED_TMPL: Final = (
    "エクスポートを中止しました（{columns} 列 × {rows} 行・推定 {size}）。"
    "出力範囲を狭めるか列を減らして再実行してください。"
)
EXPORT_SOURCE_LOST_DIAG_TMPL: Final = (
    "エクスポート中に元ファイルが読めなくなったため中止しました（{reason}）。"
    "ファイルを閉じずに再実行してください。"
)
```

- [ ] **Step 5: 通ることを確認**

```
uv run pytest tests/gui/test_busy_ownership_progress.py tests/gui/test_export_cancel_routing.py -q
uv run pytest tests/gui/test_load_worker.py tests/gui/test_busy_overlay.py tests/gui/test_unload_export_guard.py tests/gui/test_main_window.py -q
```
Expected: 1 行目 `14 passed`／2 行目は**既存本数のまま全 pass**（`test_cancel_requested_wired_to_controller` を含む — ルータが `_load_controller.cancel_active` を呼ぶので monkeypatch 版も緑のまま）。**ここが赤くなったら既存契約が動いている**ので、停止して報告する。

- [ ] **Step 6: sabotage で honest-RED を確認（必須）**

```
cp src/valisync/gui/views/busy_overlay.py "$SCRATCH/busy_overlay.py.orig"
cp src/valisync/gui/workers/export_worker.py "$SCRATCH/export_worker.py.orig"
cp src/valisync/gui/views/main_window.py "$SCRATCH/main_window.py.orig"
```

| # | 壊す箇所（正確な編集） | 予測 RED |
|---|---|---|
| S1 | `BusyOverlay.release` の本体を `self.hide()` のみへ（所有権を無視） | `test_overlay_stays_up_until_every_owner_releases` / `test_release_of_a_non_owner_is_a_no_op` の **2 件** |
| S2 | `_cancel_busy_operations` から `self._export_controller.cancel_active()` を削除（＝ 旧 `:209` の恒久配線と等価） | `test_cancel_button_routes_to_every_active_controller` / `test_cancel_keeps_the_overlay_up_until_the_worker_stops` の **2 件**。**これが「今日死んでいるキャンセル」の再現**であり、この 2 件が RED になることが本増分の存在理由の実証 |
| S3 | `set_progress` の `setRange(0, int(total))` を削除 | `test_progress_makes_the_bar_determinate_and_release_restores_it` の **1 件** |
| S4 | `_eta_text_for` の `if done <= 0:` を削除 | `test_eta_says_measuring_until_the_first_unit_completes` の **1 件**（ZeroDivisionError） |
| S5 | `ExportController.submit` の `self._pool.start(worker)` を `export_callable()` の直呼びへ（GUI スレッドでインライン実行） | `test_export_runs_off_the_gui_thread_at_resolve_and_at_write` の **1 件**（2 つの assert のうち先に当たる方で落ちる） |
| S6 | `CsvExporter` の temp 削除（`finally` / `except BaseException` の `unlink`）を削除 | `test_cancelling_export_leaves_no_file_and_no_temp` の **1 件**。**「一度は存在した」assert は緑のまま**であることまで確認する — それが「上界 0 の空虚形になっていない」ことの実証 |
| S7 | `release` の `if self._progress_owner is owner: self._reset_progress()` を削除 | `test_progress_makes_the_bar_determinate_and_release_restores_it` の後半 **1 件** |
| S8 | `_run_export` の `on_cancelled=` を渡さない形へ戻す（Task 8 の暫定形と同じ） | `test_cancel_callback_is_actually_wired_to_the_controller` の **1 件のみ**。`test_cancelled_export_reports_the_pre_start_estimate` は `_on_export_cancelled` を直呼びするので**緑のまま** — 直呼びテストが配線に盲目であることの実証 |
| S9 | `_on_export_cancelled` の `isinstance(exc, ExportSourceLost)` 分岐を削除 | `test_source_lost_adds_one_diagnostic_but_a_user_cancel_does_not` の **1 件**（診断が増えない）。逆に分岐を `isinstance(exc, ExportCancelled)` へ広げた場合も同テストの前半（ユーザー中止で増やさない）が RED になることまで確認する |

- [ ] **Step 7: ゲート＋コミット**

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

```
git add src/valisync/gui/views/busy_overlay.py src/valisync/gui/workers/load_worker.py \
        src/valisync/gui/workers/export_worker.py src/valisync/gui/views/main_window.py \
        src/valisync/gui/strings.py tests/gui/test_busy_ownership_progress.py \
        tests/gui/test_export_cancel_routing.py
git commit -m "$(cat <<'EOF'
fix(gui): BusyOverlay の 3 衝突を解消し協調キャンセルを実配線 (E-4b T-UX)

1. cancel_requested は _load_controller.cancel_active へ**恒久配線**されており、
   エクスポート中のキャンセルボタンは今日押しても何も起きなかった。MainWindow の
   ルータ (_cancel_busy_operations) が実行中の全コントローラへ配る形にする。
   「今アクティブなのはどれか」をルータに持たせないのは、各コントローラが既に
   自分の active 集合を持っており、状態を二重化すると必ず腐るから (旧配線が
   まさにその腐り方だった)。
2. 1 インスタンスを LoadController (件数ベース) と ExportController (無条件 hide) が
   相互ガード無しで共有していた。所有権 (acquire/release の参照カウント) を入れ、
   最後の 1 人が返したときだけ隠す。LoadController の hide() 直呼びを release へ
   置換 — 所有者が自分だけなら release がそのまま hide になるので、「ソフト側は
   即時解放」の既存契約はバイト等価に保たれる (test_load_worker.py 無編集で緑)。
3. 不確定バー setRange(0,0) のままではブロック進捗が出ない。determinate 化
   (block_done / block_total) と ETA (経過 x 残り/完了・最初のブロックまでは
   「計測中…」・done<=0 が 0 除算ガードそのもの) を足し、解放時に不確定へ戻す
   (戻さないと次のロードで determinate が固着する)。

エクスポートのキャンセルは load と**意図的に非対称**: overlay は ExportCancelled が
戻るまで下ろさず、文言を「中止しています…」へ、ボタンを disabled にする。temp を
消し切る前に「中止した」と見せると、ユーザーは残骸が消える前に次のエクスポートを
始められ、「失敗ならファイルが存在しない」(spec §10) の観測窓が壊れる。

進捗/キャンセルのハンドル (ExportRun) は submit の**前**に prepare() で渡す。
callable の引数を controller が規定しない形にしたので、ゼロ引数 submit の既存契約
(test_unload_export_guard.py が実行している) はそのまま生きる。

G6 (キャンセルで temp もファイルも残らない) は **temp が一度は存在したことを観測して
から** 消滅を assert する (上界 0 だけだと temp を作らない実装でも緑になる)。
G7 (オフスレッド性) は解決時と書き時の 2 点でスレッド ID を捕捉し、部分インライン化
(解決だけ GUI スレッド) を検出する。

sabotage 実測: release の hide 直呼び=2 RED / export ルート削除 (旧配線の再現) =2 RED /
setRange 削除=1 RED / 0 除算ガード削除=1 RED / pool.start の直呼び化=1 RED /
temp 削除の除去=1 RED (「一度は存在した」は緑のまま = 空虚形でない実証) /
release の進捗リセット削除=1 RED。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 10: 並行性 3 点＋ロック契約（T-CONC）

> **このタスクは 2 つに割れる**（spec §4 の依存表「T-CONC は独立」は Step 2–4 にだけ当てはまる）:
>
> - **Task 10a = Step 2–4**（`MdfHandle.serial` 化・`add()` のロック対称化と書き順・`_ensure_namespaced`/`group_signals` の世代ガード）— **本当に独立**で、Task 4–9 のどれも待たない。いつ着手してもよい。
> - **Task 10b = Step 5 全体**（`ExportSourceLost` の decay 契約・`Session.export_resolver()`・ロック順 probe）— **Task 6 後かつ Task 9 より前**。`ExportSourceLost` は Task 6 が作る `ExportCancelled` を継承し、`export_resolver` は Task 6 の `resolve_signal_transient` を呼ぶ。さらに **Task 9 の G6/G7 が `session.export_resolver()` を直接呼ぶ**ので、番号順（8 → 9 → 10）に流すと Task 9 が誤った理由の AttributeError で停止する。
>
> Task 10b では、Task 7 が `Session.export_csv` へ配線した `resolve=self.resolve_signal_transient` を **`self.export_resolver()` へ差し替える**（Task 9 が作る `export_csv_request` も同様）。差し替えないと `ExportSourceLost` は production から到達不能なまま（欠落キーは `scan_masters` の `ValueError` になる）で、spec §5.7 [I7c] の「診断 1 件」も誰も出さない。

**Files:**
- Modify: `src/valisync/core/loaders/mdf_handle.py`（`serial` を `__slots__` へ追加・`release_handle(id(self))` → `serial`）
- Modify: `src/valisync/core/models/sample_source.py`（`:188` の `id(self._handle)` → `self._handle.serial`）
- Modify: `src/valisync/core/session.py`（`:469` の `id(group.handle)` → `group.handle.serial`・`export_resolver()` を追加）
- Modify: `src/valisync/core/loaders/channel_cache.py`（`CacheKey` の型コメント／`get` の docstring `:108-112` の是正）
- Modify: `src/valisync/core/loaders/signal_group_manager.py`（`add()` のロック対称化・書き順・`_ensure_namespaced` / `group_signals` の世代ガード）
- Modify: `src/valisync/core/export/csv_exporter.py`（`ExportSourceLost` と文言定数）
- Modify: `scripts/measure_lazy_footprint.py`（`:853` docstring・`:934` の `hid = id(handle)`）
- Test: `tests/core/loaders/test_handle_serial.py`（新規）
- Test: `tests/core/loaders/test_group_manager_concurrency.py`（新規）
- Test: `tests/core/export/test_export_decay.py`（新規・`tests/core/export/` を新設）
- Test: `tests/core/loaders/test_lock_order_probe.py`（新規）

**Interfaces:**
- **Consumes**: 既存の `ChannelSampleCache` / `MdfHandle` / `SignalGroupManager`（E-4a）／Task 6 の `resolve_transient` と ブロック解決関数（Step 5 の probe が走らせる。未着手なら後で繋ぐ）
- **Produces**（Task 11 と Task 6/7 が依存する）:
  - `MdfHandle.serial: int`（プロセス単調・`__slots__` に追加）
  - `CacheKey = (handle.serial, group_index, channel_index)` の新しい意味
  - `SignalGroupManager.add()` の **ロック下＋書き順** 契約（counters/内部表 → `_groups[key]` → `_invalidate_namespaced()`）
  - `_ensure_namespaced` / `group_signals` の世代ガード（lost-update の閉鎖）
  - `csv_exporter.ExportSourceLost(ExportCancelled)` と `Session.export_resolver() -> Callable[[str], Signal]`
  - `tests/core/loaders/test_lock_order_probe.py::assert_no_resolve_under_handle_lock`（Task 6/7 の実装がロック契約を破ったら落ちる常設 probe）

- [ ] **Step 1: 失敗テストを書く**

`tests/core/loaders/test_handle_serial.py`:

```python
# ruff: noqa: RUF002, RUF003
"""キャッシュキーの第 1 成分を id(handle) から MdfHandle.serial へ (E-4b・spec §5.7-1)。

id() は **生存中のオブジェクト間でのみ** 一意で、閉じたハンドルのアドレスは次の
ロードが再利用する (実測 100% 再利用・memory gui_id_reuse_flake_object_recreation)。
今日は「close の前に drop_handle」という**手順**でしか守られておらず、手順を 1 箇所
忘れると別ファイルの 2-D を引き当てる (長さが合えば例外も出ない = サイレント誤データ)。
serial 化でこの窓が**構造的に**消えることを固定する。

demo_data に依存しない (ndarray と偽ハンドルだけで全経路を踏める)。
"""

from __future__ import annotations

import threading

import numpy as np

from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.loaders.mdf_handle import MdfHandle


class _FakeMdf:
    def close(self) -> None:
        pass


def test_serial_is_strictly_increasing_across_handles() -> None:
    a = MdfHandle(_FakeMdf())
    b = MdfHandle(_FakeMdf())
    assert b.serial > a.serial


def test_recycled_address_does_not_recycle_the_serial() -> None:
    """id 再利用を **強制再現** し、serial が follow しないことを見る。

    参照を落として同型のオブジェクトを作り直すと CPython はアドレスを再利用する。
    id ベースのキーではここで A のエントリを B が引く。

    **早期 return で核心 assert を素通しさせない** (spec §7.3「id 強制再現…で
    固定」): 1 回で再利用が起きないことはあるので、**同サイズを即時再確保**する
    形で N 回リトライし、**一度も再現しなければ fail** する。「再現しなかったので
    単調性だけ見た」を許すと、この test は id 再利用に対して恒久的に無力になる
    (memory `gui_id_reuse_flake_object_recreation` と同じ罠の裏返し)。
    """
    cache = ChannelSampleCache(budget_bytes=4096)
    reproduced = False
    for _ in range(50):
        a = MdfHandle(_FakeMdf(), cache=cache)
        a_id, a_serial = id(a), a.serial
        cache.put((a_serial, 0, 0), np.zeros(64, dtype=np.uint8))
        del a  # drop_handle を **わざと呼ばない** (手順に頼らないことの検証)

        b = MdfHandle(_FakeMdf(), cache=cache)  # 同サイズを即時再確保
        assert b.serial != a_serial  # 単調性は毎回見る
        if id(b) == a_id:
            reproduced = True
            assert cache.get((b.serial, 0, 0)) is None, "別ファイルの 2-D を引き当てた"
            break
        del b
    assert reproduced, (
        "50 回試して id 再利用が一度も起きなかった — 核心 assert "
        "(cache.get((b.serial, 0, 0)) is None) を一度も実行できていない"
    )


def test_serials_are_unique_under_concurrent_construction() -> None:
    """2 スレッド同時ロード (実際に踏める形) でも serial は衝突しない。"""
    handles: list[MdfHandle] = []
    lock = threading.Lock()

    def make() -> None:
        local = [MdfHandle(_FakeMdf()) for _ in range(200)]
        with lock:
            handles.extend(local)

    threads = [threading.Thread(target=make) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({h.serial for h in handles}) == 400


def test_close_releases_by_serial_not_by_address() -> None:
    """close() の backstop (release_handle) も serial で引く。"""
    cache = ChannelSampleCache(budget_bytes=4096)
    handle = MdfHandle(_FakeMdf(), cache=cache)
    cache.put((handle.serial, 1, 2), np.zeros(64, dtype=np.uint8))
    assert cache.bytes_held == 64
    handle.close()
    assert cache.bytes_held == 0
```

`tests/core/loaders/test_group_manager_concurrency.py`:

```python
# ruff: noqa: RUF002, RUF003
"""SignalGroupManager の並行性 (E-4b・spec §5.7-2/-3)。

E-4b は export worker の resolve を ~18 分走らせるので、親 spec §12-5 が「窓」と
記録した競合が **常態** になる。窓を自分で広げながら繰越にはできない (C-2/MG-5)。

demo_data 非依存 — 合成 SignalGroup で add/resolve/namespace 構築のすべてを踏める。
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from valisync.core.loaders.signal_group_manager import SignalGroupManager
from valisync.core.models import Signal, SignalGroup


def _group(name: str, n: int = 2) -> SignalGroup:
    return SignalGroup(
        signals=[
            Signal(
                name=f"{name}_{i}",
                timestamps=[0.0, 1.0],
                values=[float(i), float(i + 1)],
                file_format="CSV",
            )
            for i in range(n)
        ],
        source_path=Path(f"{name}.csv"),
        file_format="CSV",
    )


def test_concurrent_add_keeps_every_counter_and_key(qtbot=None) -> None:  # noqa: ARG001
    """2 スレッド同時 add で キー欠落ゼロ・連番の重複ゼロ (spec §5.7-2)。

    今日 add() はロック外で counters を read-modify-write しており、2 ファイル
    同時ドロップで **同じキーが 2 グループに割り当たる** (後勝ちで 1 つ消える)。

    **supersede 記録 (spec §7.3「全 handle が close 到達」)**: ここは handle を
    持たない合成グループで駆動するので close 到達数は数えない。spec の要求は
    「キー欠落ゼロ → 到達可能」という等価性で満たす — `remove(key)` は
    `self._groups[key]` からグループを取り出して返す唯一の経路なので、キーが
    1 つも失われていなければ **すべての handle は remove -> close へ到達できる**。
    逆に旧実装のキー衝突では、後勝ちで消えたグループが `_groups` から辿れず
    handle が close 不能になる（それがこの assert が守っている実害そのもの）。
    実 handle 込みの close 到達は Task 11 の G4/G5 走行で実測する。
    """
    mgr = SignalGroupManager()
    keys: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def add_many(tag: str) -> None:
        barrier.wait(timeout=5.0)
        local = [mgr.add(_group(f"{tag}{i}")) for i in range(50)]
        with lock:
            keys.extend(local)

    threads = [threading.Thread(target=add_many, args=(f"t{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert len(keys) == 200
    assert len(set(keys)) == 200, "同じキーが 2 グループへ割り当たった"
    assert sorted(mgr.keys) == sorted(keys), "登録済みグループとキーが食い違う"


def test_resolve_right_after_add_sees_the_new_group() -> None:
    """書き順: counters/内部表 -> _groups[key] -> _invalidate_namespaced (I7b)。

    「最後に書く」の字義どおり (invalidate -> _groups) だと、invalidate 後の間隙で
    走った resolve が **新グループを含まない** map を焼き付け、次の invalidate まで
    そのファイルの信号が引けなくなる。
    """
    mgr = SignalGroupManager()
    mgr.signal_map()  # 先にキャッシュを立てておく (invalidate の効果を可視化)
    key = mgr.add(_group("fresh"))
    assert mgr.signal_map().get(f"{key}::fresh_0") is not None


def test_namespace_build_survives_a_concurrent_add() -> None:
    """反復中の add で dict-changed-size を出さない (spec §5.7-3)。

    構築を人工的に遅らせて窓を確実に踏む (遅らせないと GIL の引き渡し粒度で
    ほぼ落ちない = sabotage しても緑になる)。
    """
    mgr = SignalGroupManager()
    for i in range(200):
        mgr.add(_group(f"pre{i}"))

    original = SignalGroupManager._namespaced
    started = threading.Event()

    def slow(key: str, group: SignalGroup):  # type: ignore[no-untyped-def]
        started.set()
        threading.Event().wait(0.001)
        return original(key, group)

    SignalGroupManager._namespaced = staticmethod(slow)  # type: ignore[method-assign]
    errors: list[BaseException] = []
    try:
        def build() -> None:
            try:
                mgr.signals()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        t = threading.Thread(target=build)
        t.start()
        started.wait(timeout=5.0)
        late_key = mgr.add(_group("late"))
        t.join(timeout=20.0)
    finally:
        SignalGroupManager._namespaced = original  # type: ignore[method-assign]

    assert errors == [], f"反復中の add で例外: {errors!r}"
    # lost-update の閉鎖: 構築が古いスナップショットを焼き付けていない。
    assert mgr.signal_map().get(f"{late_key}::late_0") is not None


def test_group_signals_cache_is_not_resurrected_after_removal() -> None:
    """per-key キャッシュの世代ガード (同じ lost-update が group_signals にもある)。

    **競合形でなければ空虚**: 単一スレッドの「add -> remove -> group_signals」は
    新実装の `self._groups[key]` が無条件 KeyError を投げるので、世代照合と
    `key in self._groups` の再確認 (`if self._namespaced_gen == gen and
    key in self._groups:`) を**丸ごと削除しても緑**になる。守るべきなのは
    「ビルド中に remove が入った」窓なので、`test_namespace_build_survives_a_
    concurrent_add` と同じ slow-`_namespaced` フックで競合を作る。
    """
    mgr = SignalGroupManager()
    key = mgr.add(_group("g"))

    original = SignalGroupManager._namespaced
    started = threading.Event()
    proceed = threading.Event()

    def slow(k: str, group: SignalGroup):  # type: ignore[no-untyped-def]
        started.set()
        proceed.wait(5.0)  # ビルド中に remove を差し込む窓
        return original(k, group)

    SignalGroupManager._namespaced = staticmethod(slow)  # type: ignore[method-assign]
    result: list[object] = []
    try:

        def build() -> None:
            try:
                result.append(mgr.group_signals(key))
            except KeyError:
                result.append(KeyError)

        t = threading.Thread(target=build)
        t.start()
        started.wait(timeout=5.0)
        mgr.remove(key)  # ビルド中に消える
        proceed.set()
        t.join(timeout=20.0)
    finally:
        SignalGroupManager._namespaced = original  # type: ignore[method-assign]

    # ビルド自身は完走してよい (スナップショットに対して作っている)。禁じるのは
    # **消えたキーのキャッシュを書き戻すこと** — 書き戻すと「閉じたのに信号が
    # 引ける」状態が次の invalidate まで残る。
    assert key not in mgr._namespaced_by_key, (
        "remove 済みキーの namespaced キャッシュが復活した (世代照合が効いていない)"
    )
    with pytest.raises(KeyError):
        mgr.group_signals(key)
```

`tests/core/export/test_export_decay.py`（`tests/core/export/__init__.py` は作らない — 既存のテストツリーは package でない）:

```python
# ruff: noqa: RUF002, RUF003
"""unload x export の競合は **クラッシュでなく decay** (E-4b・spec §5.7 [I7c])。

今日の防波堤は GUI の busy 述語 1 枚 (app_viewmodel.py:247-255)。E-4b 後もそれは
維持しつつ、core 側の振る舞いを定義する: worker の resolve が None / SampleReadError
を返したら B6 経路 (全 temp 削除・ファイル無し・診断 1 件) へ落ちる。

ExportSourceLost が ExportCancelled を継承するのは、temp 削除と「ファイルが存在しない」
契約の経路を **1 本に保つ** ため — 別系統の例外にすると finally の網から漏れる。
"""

from __future__ import annotations

import pytest

from valisync.core.export.csv_exporter import ExportCancelled, ExportSourceLost
from valisync.core.models.sample_source import SampleReadError


class _StubSession:
    """resolve_signal_transient だけを持つ最小スタブ (Session を丸ごと作らない)。"""

    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour

    def resolve_signal_transient(self, key: str):  # type: ignore[no-untyped-def]
        if self.behaviour == "none":
            return None
        raise SampleReadError("ファイルは既に閉じられています", signal_key=key)


def _resolver(behaviour: str):  # type: ignore[no-untyped-def]
    from valisync.core.session import Session

    return Session.export_resolver(_StubSession(behaviour))  # type: ignore[arg-type]


def test_unloaded_group_decays_to_export_source_lost() -> None:
    with pytest.raises(ExportSourceLost):
        _resolver("none")("mf4_1::A")


def test_sample_read_error_decays_to_export_source_lost() -> None:
    with pytest.raises(ExportSourceLost):
        _resolver("raise")("mf4_1::A")


def test_export_source_lost_is_an_export_cancelled() -> None:
    """継承が temp 削除経路の共有そのもの (別系統にすると finally から漏れる)。"""
    assert issubclass(ExportSourceLost, ExportCancelled)
```

`tests/core/loaders/test_lock_order_probe.py`:

```python
# ruff: noqa: RUF002, RUF003
"""ロック順 probe: handle.lock 保持中に resolve() を呼ばない (spec §10)。

列ブロックの **最も自然な書き方**

    with handle.lock:
        for k in block:
            resolve(k)

がこの契約を破る。破っても単一スレッドでは何も起きない (threading.Lock は非再帰
なので self-deadlock すら起きず、ただ他スレッドの読みを ~18 分止めるだけ) ため、
**テストでしか捕まえられない**。E-4a の _LockProbeArray と同じ「解放/呼び出しの
瞬間にロック状態を非ブロッキングで問い合わせる」手法を転用する。

非ブロッキング acquire が False を返す原因は「自スレッドが保持」と「他スレッドが
保持」の 2 つあるので、**このテストは単一スレッドで走らせる** (他に握る者が居ない
状態を作る)。
"""

from __future__ import annotations

import threading
from typing import Any


def assert_no_resolve_under_handle_lock(handle: Any, resolve: Any) -> Any:
    """*resolve* を包み、呼び出し時に *handle.lock* が保持されていたら即座に落とす。

    Task 6/7 のブロック処理へこのラッパを差し込んで使う (常設 probe)。
    """

    def probed(key: str):  # type: ignore[no-untyped-def]
        acquired = handle.lock.acquire(blocking=False)
        if not acquired:
            raise AssertionError(
                "handle.lock を保持したまま resolve() が呼ばれた (spec §10 違反)"
            )
        handle.lock.release()
        return resolve(key)

    return probed


def test_probe_detects_a_violation() -> None:
    """probe 自身が効くことの positive control (probe が壊れていたら全部緑になる)。"""

    class _H:
        lock = threading.Lock()

    handle = _H()
    probed = assert_no_resolve_under_handle_lock(handle, lambda k: k)
    assert probed("ok") == "ok"
    with handle.lock:
        try:
            probed("bad")
        except AssertionError:
            return
    raise AssertionError("probe が違反を見逃した")


def test_block_pipeline_never_resolves_under_the_handle_lock(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """**実在 API のブロック経路**を probe 越しに走らせ、違反ゼロを固定する。

    駆動するのは Task 6 の `scan_masters` + `CsvExporter._write_block_temp` —
    ブロック内で `resolve` を呼ぶのはこの 2 つだけで、`iter_blocks` のような
    「ブロックを列挙する公開関数」は存在しない (Task 6 の Produces は
    `plan_blocks(runs, block_cols)` という**純関数**で、session も keys も
    受け取らない)。probe を差し込む口は `resolve` 引数そのもの。

    Task 6 未着手の時点ではこのテストを xfail でも skip でもなく **停止して報告**
    する (「まだ無い」を skip で流すと、繋ぎ忘れが永久に緑のまま残る)。
    """
    from tests.mdf4_helpers import CAN, write_mdf4
    from valisync.core.export.csv_exporter import (
        CsvExporter,
        CsvExportOptions,
        ExportRequest,
        scan_masters,
    )
    from valisync.core.export.timeline import union_timeline
    from valisync.core.session import Session

    path = tmp_path / "probe.mf4"
    write_mdf4(
        path,
        [
            {
                "name": f"C{i}",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [float(i), float(i + 1)],
            }
            for i in range(6)
        ],
    )
    session = Session()
    key = session.load(path).key
    handle = session._groups.group(key).handle
    assert handle is not None
    keys = [f"{key}::C{i}" for i in range(6)]
    columns = [(k, None) for k in keys]
    probed = assert_no_resolve_under_handle_lock(handle, session.export_resolver())

    # 前走査 (値を読まない) とブロック書きの **両方** を probe 越しに通す。
    # 片方だけだと、もう片方が handle.lock 下で resolve していても緑になる。
    scan = scan_masters(columns, probed)
    union = union_timeline(scan.masters)
    CsvExporter(block_cols=2).export(
        ExportRequest(
            keys=tuple(keys),
            output_path=tmp_path / "probe_out.csv",
            options=CsvExportOptions(),
            header_resolver=list,
        ),
        probed,
    )
    assert len(union) == 2  # 反 vacuous: 実際に列を走査している
```

> **変えてはならないのは `resolve` 引数に `probed` を渡している 2 箇所**（`scan_masters` と `CsvExporter.export`）。Task 6/7 の実シグネチャが違っていたら、probe を差し込む口（= `resolve` を受け取る引数）を実物へ合わせ、**違っていた事実を報告に書く**（黙って合わせると共有契約が実装と乖離したまま次の著者へ渡る）。

**この時点で走らせて RED を確認する**（**パイプ禁止**）:

```
uv run pytest tests/core/loaders/test_handle_serial.py tests/core/loaders/test_group_manager_concurrency.py tests/core/export/test_export_decay.py tests/core/loaders/test_lock_order_probe.py -q
```

**予測 RED（種別が 3 通りに割れる — 一緒くたにしない）**:

| ファイル | 予測 |
|---|---|
| `test_handle_serial.py` | 4 本すべて `AttributeError: 'MdfHandle' object has no attribute 'serial'`（collection は通る） |
| `test_group_manager_concurrency.py` | `test_concurrent_add_keeps_every_counter_and_key` が**確率的に** RED（キー重複）・`test_group_signals_cache_is_not_resurrected_after_removal` が RED（世代ガード未実装で `_namespaced_by_key` にキャッシュが残る）。他 2 本は現行実装でも緑になりうる |
| `test_export_decay.py` | **collection error**（`from valisync.core.export.csv_exporter import ExportSourceLost` が ImportError） |
| `test_lock_order_probe.py` | `test_probe_detects_a_violation` は **pass**（probe 自身は自己完結）／`test_block_pipeline_never_resolves_under_the_handle_lock` は `Session.export_resolver` 不在の AttributeError |

- [ ] **Step 2: `serial` 化（src 3 サイト＋計測器 2 サイト）**

`mdf_handle.py`:

```python
import itertools

# プロセス単調な連番。**id() の再利用を構造的に消す** (spec §5.7-1): id は生存中の
# オブジェクト間でのみ一意で、閉じたハンドルのアドレスは次のロードが再利用する。
# itertools.count の __next__ は C 実装で GIL を離さないため、2 スレッド同時
# ロードでも重複しない (専用 lock は要らない)。
_HANDLE_SERIAL = itertools.count(1)


class MdfHandle:
    __slots__ = (
        "_close_lock", "_closed", "cache", "lock", "mdf", "serial", "source_path",
    )

    def __init__(self, mdf, source_path="", cache=None) -> None:  # type: ignore[no-untyped-def]
        # 既存 6 フィールドの初期化は 1 行も変えない。足すのは serial だけ。
        self.mdf = mdf
        self.lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._closed = False
        self.source_path = source_path
        self.cache = cache
        self.serial = next(_HANDLE_SERIAL)
```

`close()` の末尾:

```python
        # E-4b: キーは serial なので id 再利用による誤配は構造的に起きない。ここで
        # 落とす理由は **予算の返却** だけになった (回収されない close = ローダーの
        # エラー/キャンセル経路でエントリが恒久滞留するのを防ぐ)。
        if self.cache is not None:
            self.cache.release_handle(self.serial)
```

`sample_source.py:188`:

```python
        key = (self._handle.serial, self._gi, self._ci)
```

`session.py:469` 周辺（コメントも書き換える — 根拠が変わったので）:

```python
            # **close の前**に落とす (spec §5.7)。E-4b で serial 化したので「id 再利用で
            # 別ファイルの 2-D を引き当てる」経路は**構造的に消えた**が、この順序は
            # 維持する — 残る根拠は **解放のペーシング** である。close() は自ハンドルの
            # エントリを ChannelSampleCache から落として**その場で同期解放**するので、
            # 順序を逆にすると teardown へ渡す実体が消え、13.2 MB/本のチャンネル配列が
            # 三軸ペーシングを迂回して GUI スレッドで解放される (会計上は「配列は 1 本も
            # 無かった」ように見えるので、症状はフリーズだけで数字に出ない)。
            cached = cache.drop_handle(group.handle.serial)
```

`channel_cache.py` の `CacheKey` docstring:

```python
CacheKey = tuple[int, int, int]
"""キー = ``(handle.serial, group_index, channel_index)``。

**名前をキーにしない** (spec §5.3): 生名は LD-08 重複で一意でなく (mdf_loader の
``name_total[base_name] > 1`` — 既存 fixture ``Mat2`` がその形)、表示名はファイル間で
一意でない。``Session`` は 1 キャッシュを全ファイルで共有するので、ハンドルを含めないと
2 ファイル比較で同じ曲線が 2 本描かれる (長さが同じなら sample_source の長さ検証も
通り、例外も出ない = サイレント誤データ)。

**``id(handle)`` から ``handle.serial`` へ (E-4b・spec §5.7-1)**: id は生存中の
オブジェクト間でのみ一意で、閉じたハンドルのアドレスは次のロードが再利用する
(実測 100% 再利用・memory gui_id_reuse_flake_object_recreation)。旧キーの一意性は
「close の前に drop_handle を呼ぶ」という**手順**でしか守られておらず、手順を 1 箇所
忘れれば別ファイルの 2-D を無言で返した。serial (プロセス単調 int) はハンドルの
生死と無関係なので、この窓は構造的に存在しない。drop_handle を close の前に呼ぶ
契約自体は維持する — 根拠が「キーの一意性」から「解放のペーシング」へ変わった。
"""
```

`channel_cache.py` の `get()` docstring `:108-112` の是正（**実装に存在しない機構の記述**）:

```python
        不在は ``misses`` を 1 増やす。**正しい関係は等式でなく ``misses >= select``**。
        production が select を呼ぶ唯一の理由がここの None なので下限は必ず立つ。
        上振れ (miss > select) が起きるのは **同じ列 (同じ LazyMdfValues インスタンス)
        を 2 スレッドが同時に読んだとき**だけで、``handle.lock`` 下の
        ``if self._cache is not None`` 再チェックが 2 本目の select を畳む。

        **兄弟列は畳まれない (E-4b で是正)**: 旧記述は「同一チャンネルの別列の同時読みが
        select 1 回に畳まれる」と書いていたが、そんな機構は実装に無い —
        ``sample_source.py:203-206`` が明示的に逆を書いており (「lock 内で
        channel_cache を引き直さない … 代償は同一チャンネルの別列を同時に読み始めた
        稀なケースで select が 1 本余分に走ること」)、兄弟列の同時読みは
        **miss 2 / select 2** になる。E-4b の並列度をこの記述から決めると外すので
        是正した (本増分のブロック処理は spec §5.7-4 のとおり**直列**)。
```

`scripts/measure_lazy_footprint.py`:

```python
def _handle_of(session: Any, key: str) -> Any:
    """グループの MdfHandle (キャッシュキー ``(handle.serial, gi, ci)`` の第 1 成分)。"""
```
```python
    hid = handle.serial   # 旧: id(handle) — serial 化後は 1 件もヒットせず 0 を返す
```

**追随漏れの検出**（serial 化後に `id(handle)` が残ると、ヒットせず**サイレントに 0** を返す — 例外が出ないのが最悪の性質）:

```
grep -rn "id(handle)\|id(self._handle)\|id(group.handle)\|id(self))" src/ scripts/
```
Expected: **0 件**（`mdf_handle.py` の `id(self)` を含めて残っていないこと）。

- [ ] **Step 3: `add()` のロック対称化と書き順**

`signal_group_manager.py`:

```python
        # 名前空間キャッシュの世代。lost-update (古いスナップショットの焼き付け) を
        # 閉じるための唯一の観測点で、_invalidate_namespaced が増やし
        # _ensure_namespaced / group_signals が commit 前に照合する。
        self._namespaced_gen = 0
```

```python
    def add(self, group, column_records=None) -> str:  # type: ignore[no-untyped-def]
        prefix = _FORMAT_KEY_PREFIX.get(group.file_format)
        if prefix is None:
            raise ValueError(f"unsupported file_format: {group.file_format!r}")
        # E-4b (spec §5.7-2): 連番の read-modify-write と表の更新を **_resolved_lock 下**
        # で不可分にする。今日ロック外なので、2 ファイル同時ドロップで同じキーが
        # 2 グループへ割り当たり後勝ちで 1 つ消える (実際に踏める)。ロード経路
        # (LoadWorker -> session.load -> add) にこの lock の再入は無いことを確認済み。
        with self._resolved_lock:
            self._counters[prefix] = self._counters.get(prefix, 0) + 1
            key = f"{prefix}_{self._counters[prefix]}"
            self._physical_by_name[key] = self._index_physical(group)
            if column_records:
                # 呼び出し側の dict と縁を切る (物理チャンネル数ぶんなので安い)。
                self._column_records[key] = dict(column_records)
            # 書き順は「内部表 -> _groups[key] -> _invalidate_namespaced」(I7b)。
            # 「最後に書く」の字義どおり (invalidate -> _groups) にすると、invalidate 後の
            # 間隙で走った再構築が **新グループを含まない** map を焼き付け、次の
            # invalidate までそのファイルの信号が引けない。
            self._groups[key] = group
            self._invalidate_namespaced()
        return key
```

`remove()` は `_column_records.pop` / `_physical_by_name.pop` / `_invalidate_namespaced()` を **既存の `with` の中へ移す**（`_mint_column` はロック下でこれらを読むので、外に置くと読みながら消える）。

`_invalidate_namespaced` に 1 行追加（**呼び出し側が `_resolved_lock` を保持していること**を docstring に明記）:

```python
    def _invalidate_namespaced(self) -> None:
        """Drop the namespaced caches; rebuilt lazily on next access.

        **呼び出し側が ``_resolved_lock`` を保持していること** (E-4b)。世代の +1 が
        非アトミックなうえ、これと ``_groups`` の書きが別トランザクションだと
        lost-update の窓が残る。
        """
        self._namespaced_list = None
        self._namespaced_map = None
        self._namespaced_by_key = {}
        self._namespaced_gen += 1
        # NOTE: _resolved_by_key はここで**捨てない** (Critical 1)。… (既存コメント維持)
```

- [ ] **Step 4: `_ensure_namespaced` / `group_signals` の競合閉鎖**

**採用: スナップショット＋世代照合（ロック内でビルドしない）**。理由:

- 危険なのは `_groups` の**反復**だけで、`list(self._groups.items())` は C レベルで完結し Python コールバックへ戻らないため**原子的**。したがってスナップショットを取るだけで `dict changed size` は消える。
- ここを丸ごと `_resolved_lock` 下に入れると、O(全信号) のラッパ構築が **export worker が 330k 回取るのと同じ lock** の中に入る。正しさの修正が待ち時間の回帰へ化ける（E-4b はまさにその lock をホットにする増分）。
- ただしスナップショットだけでは **lost-update**（古いスナップショットを構築後に焼き付け、新グループが次の invalidate まで見えない）が残る。これを世代照合（commit 時に `_namespaced_gen` が動いていたらやり直す）で閉じる。**この 2 段構えが「ロックにしない」ことの対価**であり、片方だけでは不完全。

```python
    # 10a (spec §5.7-3・PR 1d51f85) supersede: 実装は `-> None` でなく
    # `-> tuple[list[Signal], dict[str, Signal]]` を返す (呼び出し側が
    # self._namespaced_map を**もう一度**読むと invalidate との競合窓が開くため)。
    # さらに無ロック再試行に attempt>=3 の前進保証を追加した — 詳細は src の実装参照。
    def _ensure_namespaced(self) -> tuple[list[Signal], dict[str, Signal]]:
        """Build and cache the namespaced signal list/map once (idempotent).

        E-4b (spec §5.7-3): 反復は **スナップショット** に対して行い、書き戻しは
        **世代照合つき** で行う。旧実装は無ロックで ``self._groups.items()`` を直に
        回しており、export worker の resolve が ~18 分走る本増分では
        ``dictionary changed size during iteration`` が窓ではなく常態になる。

        ビルドを lock の中でやらないのは、O(全信号) のラッパ構築が export worker の
        取る lock を占有し、正しさの修正が待ちの回帰に化けるため。
        """
        if self._namespaced_list is not None:
            return
        while True:
            with self._resolved_lock:
                if self._namespaced_list is not None:
                    return
                gen = self._namespaced_gen
                snapshot = list(self._groups.items())  # C レベルで完結 = 原子的
            result: list[Signal] = []
            for key, group in snapshot:
                result.extend(self._namespaced(key, group))
            mapping = {sig.name: sig for sig in result}
            with self._resolved_lock:
                if self._namespaced_gen != gen:
                    continue  # 途中で add/remove が入った — 作り直す (lost-update 閉鎖)
                if self._namespaced_list is None:
                    self._namespaced_list = result
                    self._namespaced_map = mapping
                return
```

`group_signals` も同型に:

```python
    def group_signals(self, key: str) -> list[Signal]:
        with self._resolved_lock:
            group = self._groups[key]  # 未知 key は従来どおり KeyError
            cached = self._namespaced_by_key.get(key)
            gen = self._namespaced_gen
        if cached is None:
            cached = self._namespaced(key, group)
            with self._resolved_lock:
                # remove 済みキーの復活を防ぐ (per-key キャッシュにも同じ
                # lost-update がある — 復活すると「閉じたのに信号が引ける」)。
                if self._namespaced_gen == gen and key in self._groups:
                    self._namespaced_by_key[key] = cached
        return list(cached)  # 防御コピー(signals() と同契約) — Signal は共有
```

- [ ] **Step 5: decay 契約とロック順 probe**

`csv_exporter.py`（`ExportCancelled` の直後）:

```python
EXPORT_SOURCE_LOST_TMPL = (
    "エクスポート中に元ファイルが閉じられたため中止しました（列: {key}）"
)


class ExportSourceLost(ExportCancelled):
    """エクスポート中に元ファイルが閉じられ、列が解決できなくなった (decay)。

    ``ExportCancelled`` を **継承する** のは、temp 削除と「失敗ならファイルが存在
    しない」契約 (spec §10) の経路を 1 本に保つため — 別系統の例外にすると
    ``finally`` の網から漏れて残骸が出る。GUI は isinstance で「ユーザーが押した」と
    「ファイルが消えた」を出し分ける (前者はステータスのみ・後者は診断 1 件)。
    """
```

`session.py`:

```python
    def export_resolver(self) -> Callable[[str], Signal]:
        """エクスポート専用の列解決器 (帳簿に載せない・decay を loud にする)。

        unload との競合契約 (spec §5.7 [I7c]): GUI 側の busy ガード
        (app_viewmodel.unload_file の述語) は維持したうえで、core 側の振る舞いを
        **クラッシュではなく decay** として定義する。None と SampleReadError の
        どちらも ExportSourceLost へ畳むのは、呼び出し側 (パイプライン) に
        「None なら何を書くか」という 2 つ目の分岐を作らせないため — 部分的に
        空セルで埋めた CSV が出るくらいなら、何も残さない方が正しい (B6)。
        """

        def resolve(key: str) -> Signal:
            try:
                sig = self.resolve_signal_transient(key)
            except SampleReadError as exc:
                raise ExportSourceLost(str(exc)) from exc
            if sig is None:
                raise ExportSourceLost(EXPORT_SOURCE_LOST_TMPL.format(key=key))
            return sig

        return resolve
```

**production への配線（これを忘れると `ExportSourceLost` は到達不能なまま）**:

`Session.export_csv`（Task 7 が敷いた）と `Session.export_csv_request`（Task 9 が敷く）の resolver 引数を、**それぞれ 1 行ずつ** `self.export_resolver()` へ差し替える:

```python
        # 旧: self._exporter.export(request, self.resolve_signal_transient, ...)
        self._exporter.export(request, self.export_resolver(), ...)
```

差し替えないと、欠落キーは `scan_masters` の `ValueError`（decay ではない）になり、`ExportSourceLost` は**テストの中でしか存在しない例外**になる — spec §5.7 [I7c] の「B6 経路（全 temp 削除・ファイル無し・**診断 1 件**）」のうち診断が誰からも出ない。差し替え後、`grep -n "resolve_signal_transient" src/valisync/core/session.py` の残りが `resolve_signal_transient` の**定義と `export_resolver` 内の呼び出しだけ**であることを確認する。

`assert_no_resolve_under_handle_lock` は Step 1 のテストファイルに置く（production コードではない）。Task 6/7 の実装者はブロック解決をこの probe 越しに走らせるテストを常設する。

- [ ] **Step 6: 通ることを確認**

```
uv run pytest tests/core/loaders/test_handle_serial.py tests/core/loaders/test_group_manager_concurrency.py tests/core/export/test_export_decay.py tests/core/loaders/test_lock_order_probe.py -q
uv run pytest tests/core/ tests/test_measure_lazy_footprint.py -q
```
Expected: 1 行目 `13 passed`／2 行目は**既存本数のまま全 pass**。

- [ ] **Step 7: sabotage で honest-RED を確認（必須）**

```
cp src/valisync/core/loaders/signal_group_manager.py "$SCRATCH/sgm.py.orig"
cp src/valisync/core/loaders/mdf_handle.py "$SCRATCH/mdf_handle.py.orig"
cp src/valisync/core/models/sample_source.py "$SCRATCH/sample_source.py.orig"
```

| # | 壊す箇所（正確な編集） | 予測 RED |
|---|---|---|
| S1 | `sample_source.py` の `key` を `(id(self._handle), self._gi, self._ci)` へ戻す＋`mdf_handle.close` を `release_handle(id(self))` へ戻す | `test_recycled_address_does_not_recycle_the_serial` / `test_close_releases_by_serial_not_by_address` の **2 件**。前者は 50 回リトライで id 再利用を強制再現するので、**「再利用が起きなかったので緑」は起きない**（起きたらリトライ数が足りないという発見なので、予測を書き換えず報告する） |
| S2 | `add()` の `with self._resolved_lock:` を外して本体を 1 段デデント | `test_concurrent_add_keeps_every_counter_and_key` の **1 件**（キー重複で `len(set(keys)) != 200`）。**確率的に緑になりうる**ので、RED になるまで最大 5 回回して「n 回中 m 回 RED」を報告に書く（決定化のため `Barrier` を入れてある） |
| S3 | `add()` の書き順を `self._invalidate_namespaced()` → `self._groups[key] = group` へ入れ替え | `test_resolve_right_after_add_sees_the_new_group` の **1 件** |
| S4 | `_ensure_namespaced` の `if self._namespaced_gen != gen: continue` を削除 | `test_namespace_build_survives_a_concurrent_add` の **後半 assert 1 件**（例外は出ないまま `late` が map に無い = lost-update そのもの） |
| S5 | `_ensure_namespaced` の `snapshot = list(...)` を `self._groups.items()` の直反復へ | 同テストの **前半 assert 1 件**（`RuntimeError: dictionary changed size during iteration` が `errors` に入る） |
| S5b | `group_signals` の書き戻しガード `if self._namespaced_gen == gen and key in self._groups:` を無条件書き戻しへ | `test_group_signals_cache_is_not_resurrected_after_removal` の **1 件**（`key not in mgr._namespaced_by_key` が落ちる）。**単一スレッド形（add -> remove -> group_signals）だけを見ていた旧テストではこの変異が全緑で通る**ことも確認する — 競合形へ書き換えた理由の実証 |
| S6 | `export_resolver` の `if sig is None: raise` を `return sig  # type: ignore` へ | `test_unloaded_group_decays_to_export_source_lost` の **1 件** |
| S7 | `ExportSourceLost` の基底を `Exception` へ | `test_export_source_lost_is_an_export_cancelled` の **1 件**（＋ Task 9 の `test_cancelling_export_leaves_no_file_and_no_temp` が decay 経路を踏む構成なら連鎖 — 実測して報告に書く） |
| S8 | `assert_no_resolve_under_handle_lock` の `if not acquired:` を `if False:` へ | `test_probe_detects_a_violation` の **1 件**（probe 自身の positive control が効いていることの実証） |

- [ ] **Step 8: ゲート＋コミット**

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
```

```
git add src/valisync/core/loaders/mdf_handle.py src/valisync/core/loaders/channel_cache.py \
        src/valisync/core/loaders/signal_group_manager.py src/valisync/core/models/sample_source.py \
        src/valisync/core/session.py src/valisync/core/export/csv_exporter.py \
        scripts/measure_lazy_footprint.py tests/core/loaders/test_handle_serial.py \
        tests/core/loaders/test_group_manager_concurrency.py tests/core/export/test_export_decay.py \
        tests/core/loaders/test_lock_order_probe.py
git commit -m "$(cat <<'EOF'
fix(core): 並行性 3 点とロック契約を閉じる (E-4b T-CONC・spec §5.7)

1. MdfHandle.serial (itertools.count のプロセス単調 int) を __slots__ へ追加し、
   ChannelSampleCache のキーを (id(handle), gi, ci) -> (handle.serial, gi, ci) へ。
   id は生存中のオブジェクト間でのみ一意で、閉じたハンドルのアドレスは次のロードが
   再利用する (実測 100% 再利用)。旧キーの一意性は「close の前に drop_handle」という
   **手順**でしか守られておらず、1 箇所忘れれば別ファイルの 2-D を無言で返した。
   置換は src 3 サイト (sample_source の id(self._handle) / session の id(group.handle) /
   mdf_handle の id(self)) と計測器 2 サイト — 追随漏れは例外でなく**サイレントに 0**
   を返すので grep で 0 件を実測して確認する。drop-before-close 契約は維持し、根拠を
   「キーの一意性」から「解放のペーシング」へ書き換えた。
2. SignalGroupManager.add() を _resolved_lock 下へ。書き順は「内部表 -> _groups[key]
   -> _invalidate_namespaced」(I7b) — 「最後に書く」の字義どおりだと invalidate 後の
   間隙で走った再構築が新グループを欠いた map を焼き付ける。
3. _ensure_namespaced / group_signals の無ロック反復を閉じる。**スナップショット
   (list(dict.items()) は C レベルで原子的) + 世代照合**を採用し、ロック下でビルド
   しない — O(全信号) の構築を export worker が 330k 回取る lock の中へ入れると、
   正しさの修正が待ちの回帰に化ける。スナップショットだけでは lost-update (古い
   スナップショットの焼き付け) が残るので、commit 時の世代照合で閉じる。

unload x export は **クラッシュでなく decay**: Session.export_resolver() が None /
SampleReadError を ExportSourceLost (ExportCancelled のサブクラス) へ畳み、B6 経路
(全 temp 削除・ファイル無し・診断 1 件) へ落とす。継承にするのは temp 削除の finally
網を 1 本に保つため。

channel_cache.get の docstring が主張していた「同一チャンネルの別列の同時読みを
select 1 回に畳む」機構は **実装に存在しない** (sample_source.py:203-206 が明示的に
逆を書く) ので是正した。上振れ (miss > select) が起きるのは同じ列を 2 スレッドが
同時に読んだときだけで、兄弟列は miss 2 / select 2 になる。

ロック順 probe (handle.lock 保持中の resolve 検出) を常設。列ブロックの最も自然な
書き方がこの契約を破り、破っても単一スレッドでは何も起きない (他スレッドの読みを
~18 分止めるだけ) ため、テストでしか捕まえられない。

sabotage 実測: serial -> id 復帰=最大 2 RED (アドレス再利用は環境依存) / add の lock
除去=1 RED (確率的・n 回中 m 回) / 書き順反転=1 RED / 世代照合削除=1 RED (lost-update) /
スナップショット削除=1 RED (dict changed size) / None 素通し=1 RED / 継承の除去=1 RED /
probe の無効化=1 RED。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```

---

### Task 11: T-M 実測＋realgui ①ゲート＋record range spike

> **実行者への注記（分割可）**: 本タスクは性質の違う 4 つ（prod 実測 ~18 分走行 × 複数回／realgui 2 本／spike／spec 追記）が混載しており、1 subagent の 2-4h 帯を超えうる。**次の 3 つへ分けて dispatch してよい**（プランの構造は変えない — Step 番号はそのまま）:
> - **11a**: Step 1-3（`--export` 段の実装・prod 2 走行・係数の差し替え。G4/G5）
> - **11b**: Step 4-5（realgui ①ゲートと その sabotage）
> - **11c**: Step 6-7（record range spike ＋ spec/契約の更新）
>
> 分けた場合も **Step 8 のゲートとコミットは最後に 1 回**（11c が担当）。11b は 11a の係数更新後に走らせること（fixture の閾値 assert が係数に依存する）。

**Files:**
- Modify: `scripts/measure_lazy_footprint.py`（`--export` 段: 係数検定・G4 全列完走・G5 常駐）
- Create: `scripts/e4b_record_range_spike.py`（B3 spike・`fu16_*_bench.py` と同じ位置づけの使い捨て計測器）
- Create: `tests/realgui/test_export_confirm_cancel_realclick.py`（G8 の (a)(b)）
- Modify: `tests/realgui/test_export_range_realclick.py`（`_read_timestamps` を全列読みへ強化・supersede コメント）
- Modify: `tests/test_measure_lazy_footprint.py`（`--export` 段の「ゼロ件で黙って合格」防止 test-lock）
- Modify: `docs/superpowers/specs/2026-08-01-e4b-export-write-path-design.md`（§11 実測記録を新設・§9-2/-4/-5 を実測へ差し替え）

**Interfaces:**
- **Consumes**: Task 4–10 の全成果物（`ExportRequest` / `resolve_transient` / `CsvExporter.export(progress, cancel)` / `estimate_export` / `ExportRun` / `MdfHandle.serial`）
- **Produces**: spec §11 の実測表（G4 の USS 上限・係数の実測値・多段マージ増幅の実係数）／realgui の ①ゲート証拠／record range の採否判断

- [ ] **Step 1: 計測器へ `--export` 段を足す（demo_data gate つき）**

`scripts/measure_lazy_footprint.py` へ 3 関数を追加し、`main()` の先頭で `--export` を分岐する（`--core` と同型の early return）:

```python
def export_estimate_check(session: Any, keys: list[str], out: Path) -> dict[str, float]:
    """B2 の係数を **読み項と書き項に分けて** 検定する (spec §7.4)。

    分けて測るのが要点 (I10): 合算だけ合っていても、読み支配ケース (カーソル A-B x
    全列) と書き支配ケース (全期間 x 全列) のどちらかが桁で外れていることがある。

    **単価を記録するときは主語 (何がそのバイト/秒を作ったか) を必ず併記する** —
    この系列は同じ罠を 3 度踏んでいる (T4 の未タッチページ 17-25 倍 / 増分B の
    3.0-4.8 us/signal 対 実 8-27 us / channel_cache の warm-allocator 2 倍)。
    """
    from valisync.core.export.csv_exporter import (
        CsvExporter,
        CsvExportOptions,
        ExportRequest,
    )
    from valisync.core.export.estimate import estimate_export

    options = CsvExportOptions()
    t0 = time.perf_counter()
    est = estimate_export(session, keys, options)
    estimate_wall = time.perf_counter() - t0

    request = ExportRequest(
        keys=tuple(keys), output_path=out, options=options, header_resolver=list
    )
    marks: list[tuple[int, float]] = []
    t1 = time.perf_counter()
    CsvExporter().export(
        request,
        session.export_resolver(),
        progress=lambda d, t: marks.append((d, time.perf_counter())),
    )
    wall = time.perf_counter() - t1
    actual_bytes = out.stat().st_size
    # 最初のブロックが終わるまでが「読み支配」区間の代理指標。
    first_block_s = (marks[0][1] - t1) if marks else wall
    return {
        "estimate_wall_s": estimate_wall,
        "est_rows": est.rows,
        "est_columns": est.columns,
        "est_empty_ratio": est.empty_ratio,
        "est_bytes": est.est_bytes,
        "actual_bytes": actual_bytes,
        "bytes_ratio": actual_bytes / max(1, est.est_bytes),
        "est_read_s": est.est_read_s,
        "est_write_s": est.est_write_s,
        "actual_wall_s": wall,
        "actual_first_block_s": first_block_s,
        "time_ratio": wall / max(1e-9, est.est_read_s + est.est_write_s),
    }


def export_full_run(session: Any, keys: list[str], out: Path, uss_limit_mb: float) -> None:
    """G4: prod 全列エクスポートが OOM せず完走し、**中身が正しい**ことまで見る。

    「完走した」だけでは空のファイルでも緑になる (spec §6 G4)。行数 = union 長・
    列数 = keys 長・ランダム 100 セルの独立オラクル照合を併置する。

    ``uss_limit_mb`` は **判定走行とは別の走行から供給する** (同一走行から閾値を得る
    循環の禁止・G4)。呼び出し側 (main) が --uss-limit で受け取り、既定値を持たない。
    """
    import random

    from valisync.core.export.csv_exporter import (
        CsvExporter,
        CsvExportOptions,
        ExportRequest,
    )
    from valisync.core.export.timeline import union_timeline

    # ゼロ件で「完走した」と刷る黙った合格を禁止する (E-3 T9 の穴と同型)。
    assert len(keys) >= 1000, f"測定対象が {len(keys)} 列しかない — 全列走行ではない"

    peak = [uss_mb()]

    def progress(done: int, total: int) -> None:
        peak[0] = max(peak[0], uss_mb())

    request = ExportRequest(
        keys=tuple(keys), output_path=out, options=CsvExportOptions(),
        header_resolver=list,
    )
    t0 = time.perf_counter()
    CsvExporter().export(request, session.export_resolver(), progress=progress)
    wall = time.perf_counter() - t0

    # --- 内容検証 (「完走した」だけでは空ファイルでも緑) ---------------------
    masters = _distinct_masters(session, keys)
    union = union_timeline(masters)
    n_union = int(union.size)
    rng = random.Random(20260801)  # 固定 seed: 落ちたセルを再現できるようにする
    samples = [(rng.randrange(n_union), rng.randrange(1, len(keys) + 1)) for _ in range(100)]
    header, n_rows, picked = _scan_output(out, {r for r, _c in samples})
    assert n_rows == n_union, (n_rows, n_union)
    assert len(header) == len(keys) + 1, (len(header), len(keys) + 1)

    for r, c in samples:
        got = picked[r][c]
        want = _oracle_cell(session, keys[c - 1], float(union[r]))
        assert got == want, f"row={r} col={c} key={keys[c - 1]} got={got!r} want={want!r}"

    print(
        f"G4 OK  columns={len(keys):,} rows={n_rows:,} "
        f"bytes={out.stat().st_size:,} wall={wall:.1f}s USS_peak={peak[0]:,.0f}MB "
        f"(limit {uss_limit_mb:,.0f}MB — 別走行から供給)",
        flush=True,
    )
    assert peak[0] <= uss_limit_mb, (peak[0], uss_limit_mb)
```

`_oracle_cell` は **パイプラインから独立** させる（`apply_path` もチャンネルキャッシュも
使わない — 同じ機構で照合すると、機構ごと間違っていても一致してしまう）:

```python
def _oracle_cell(session: Any, column_key: str, t: float) -> str:
    """列 *column_key* の時刻 *t* におけるセルを **名前引き経路** で独立に作る。

    E-3 以前の読み経路 (mdf.select + dict(_flatten(...))) をそのまま使うので、
    E-4a の位置パスにも E-4b のブロック機構にも依存しない。時刻が無い列は空セル
    (完全一致セマンティクス — tolerance を入れると照合が甘くなる)。

    **非有限値も空セル** (Task 1 の是正 1・1')。ここを ``repr(float(...))`` の
    ままにすると、demo データに NaN/±inf が 1 つでも乗った瞬間に
    ``'nan' != ''`` の**誤 RED** が出る (production が正しいのにゲートが落ちる)。
    """
    import math

    import numpy as np

    from valisync.core.loaders.column_names import _flatten

    channel = session.channel_key_of(column_key)
    assert channel is not None, column_key
    group_key, _sep, display = channel.partition("::")
    record = session._groups.column_records(group_key)[display]
    handle = session._groups.group(group_key).handle
    with handle.lock:
        asig = handle.mdf.select(
            [(record.raw_base_name, record.group_index, record.channel_index)],
            raw=False, ignore_value2text_conversions=True, copy_master=False,
        )[0]
    leaf = column_key.split("::", 1)[1][len(display):]
    columns = dict(_flatten(record.raw_base_name, asig.samples))
    values = columns[f"{record.raw_base_name}{leaf}"]
    ts = np.asarray(asig.timestamps)
    idx = int(np.searchsorted(ts, t, side="left"))
    if idx >= ts.size or ts[idx] != t:
        return ""  # このレートには当該時刻のサンプルが無い = 空セル
    value = float(values[idx])
    if not math.isfinite(value):
        return ""  # 非有限は欠測と同じ空セル (Task 1 の是正 1/1')
    return repr(value)
```

```python
def export_range_residency(session: Any, keys: list[str], out: Path) -> tuple[int, int]:
    """G5: カーソル A-B (1 行) エクスポート後の鋳造列常駐を **weakref で** 数える。

    ``resolved_keys()`` も ``bytes_held`` も使わない (spec §10): 前者は LRU の帳簿で
    export 専用 resolve に構造的に盲目、後者は pin されない列を数えない。実装自身の
    カウンタに頼らない独立オラクルが要る (E-4a の教訓)。
    """
    import gc
    import weakref

    from valisync.core.export.csv_exporter import (
        CsvExporter,
        CsvExportOptions,
        ExportRequest,
    )

    alive: weakref.WeakSet = weakref.WeakSet()
    base = session.export_resolver()

    def watched(key: str):  # type: ignore[no-untyped-def]
        sig = base(key)
        alive.add(sig)
        return sig

    # 1 行だけ出す範囲 (spec §1 の「カーソル A-B で 1 行 = 6.523 s / 114.5 MiB 常駐」
    # の再現形)。t0 を閉区間の両端に置くので出力は 1 行になる。
    masters = _distinct_masters(session, keys)
    t0 = float(masters[0][0])
    options = CsvExportOptions(time_start=t0, time_end=t0)
    CsvExporter().export(ExportRequest(tuple(keys), out, options, list), watched)
    minted = len(keys)
    gc.collect()
    # alive に残るのは「まだ誰かが参照している鋳造列」。block_cols + ε を超えたら
    # ブロック終端の参照解放が効いていない (G5 の判定は呼び出し側 main が行う)。
    return minted, len(alive)


def _distinct_masters(session: Any, keys: list[str]) -> list[Any]:
    """列キー集合が触る master を identity dedup で集める (**値を読まない**)。"""
    seen: dict[int, Any] = {}
    for key in keys:
        channel = session.channel_key_of(key)
        if channel is None:
            continue
        master = session.channel_master(channel)
        if master is not None:
            seen.setdefault(id(master), master)
    return list(seen.values())


def _scan_output(path: Path, wanted: set[int]) -> tuple[list[str], int, dict[int, list[str]]]:
    """~10 GB の CSV を **1 パスのストリームで** 走査し、ヘッダ・行数・指定行だけ返す。

    行を全部リストへ溜めると計測器自身が 10 GB を抱え、測ろうとしているピークを
    自分で作る (E-4a T5 の「対照が測定対象を汚す」と同型の罠)。保持するのは
    ``wanted`` の 100 行だけ。
    """
    picked: dict[int, list[str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        header = f.readline().rstrip("\n").split(",")
        count = 0
        for line in f:
            if not line.strip():
                continue
            if count in wanted:
                picked[count] = line.rstrip("\n").split(",")
            count += 1
    return header, count, picked
```

`tests/test_measure_lazy_footprint.py` へ 2 本追加（**ゼロ件で黙って合格しない**ことの test-lock — 既存の同ファイルの主張を `--export` 段へ拡張）:

```python
def test_export_full_run_refuses_a_zero_column_subject(mlf, tmp_path) -> None:
    """列 0 件で「完走した」と刷るのを禁止する (E-3 T9 の穴を --export 段でも塞ぐ)。"""
    with pytest.raises(AssertionError, match="測定対象"):
        mlf.export_full_run(_tiny_session(tmp_path), [], tmp_path / "o.csv", 1e9)


def test_export_full_run_requires_an_externally_supplied_limit(mlf) -> None:
    """USS 上限に既定値を持たせない (判定走行から閾値を得る循環の禁止・G4)。"""
    import inspect

    sig = inspect.signature(mlf.export_full_run)
    assert sig.parameters["uss_limit_mb"].default is inspect.Parameter.empty
```

- [ ] **Step 2: prod_demo で 2 走行（較正 → 判定）**

```
uv run --with psutil python scripts/measure_lazy_footprint.py --export --calibrate
```
出力から **USS ピーク** `P_A`（MB）と `bytes_ratio` / `time_ratio` を控える。次に閾値を**別走行から**与えて判定する:

```
uv run --with psutil python scripts/measure_lazy_footprint.py --export --uss-limit <ceil(P_A*1.25/100)*100>
```
Expected: `G4 OK` 行（完走・行数一致・列数一致・ランダム 100 セル一致）と `G5 residual columns = <n> (<= block_cols)` 行が出て exit 0。

**記録する数値（主語つきで spec §11 へ書く）**:

| 指標 | 主語（何がそれを作ったか） |
|---|---|
| 出力サイズ / 行数 / 列数 | prod_demo 1 ファイル・全列（`--export` の keys 集合） |
| 完走 wall / 最初のブロックまでの wall | 直列ブロック処理（並列ブロックは非スコープ） |
| USS ピーク | `psutil.memory_full_info().uss`（RSS ではない — 共有ページを含めない） |
| `bytes_ratio`（実バイト / 推定バイト） | 平均セル長 4.57 文字の仮定に対する実測 |
| `time_ratio`（実 wall / 推定 wall） | 読み項（チャンネル単価 0.316 s）と書き項（セル単価 6.1e-7 s）の合算 |
| 多段マージの temp 増幅実係数 | ブロック数 × fan-in 512 の実際の段数（設計値 2.3 の検証） |

- [ ] **Step 3: 係数を実測へ差し替える**

`bytes_ratio` / `time_ratio` が **1.0 ± 0.3 の外**なら `estimate.py` の該当定数を実測値へ更新し、定数コメントの「Task 11 が検定するまで暫定」の一文を**実測日・主語つきの確定文**へ書き換える。読み項と書き項は**別々に**判定する（合算だけを合わせると、片側が 2 倍・片側が 0.5 倍でも「合っている」ことになる）。

更新後に Task 8 のテストを回し直す:

```
uv run pytest tests/test_export_estimate.py tests/gui/test_export_confirm.py -q
```
Expected: `16 passed`（係数に依存する assert は `est_read_s > 0` などの**関係**でしか書いていないので、値の更新で落ちない設計になっている。落ちたらそのテストが係数へ過剰結合しているので、値でなく関係へ書き換える）。

- [ ] **Step 4: realgui ①ゲート（G8）**

`tests/realgui/test_export_confirm_cancel_realclick.py`（新規）:

```python
# ruff: noqa: RUF002, RUF003
"""Layer C (realgui・G8) — 確認 -> 完走 -> 実ファイル読み直し / 実キャンセル -> 何も残らない。

**fixture は確認閾値を確実に超える規模を明示指定する** (spec §6 G8 の空虚化防止):
閾値未満だと確認ダイアログが出ないまま (a) が「何も起きなかった」で緑になる。
超え方は **チャンネル数** で作る — 見積の読み項はチャンネル単価 0.316 s なので、
120 チャンネルで推定 ~38 s となり閾値 5 s を確実に超える一方、実際の書き出しは
数秒で終わる (推定は小さいチャンネルに対して過大に出る = 既知の性質)。
テストは「推定が本当に閾値を超えている」ことを assert してから進む — 係数が
Task 11 の検定で下がったらここが loud-fail し、黙ってダイアログを飛ばさない。

エビデンス: design_export/evidence_e4b/ へ保存。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from tests.realgui._realgui_input import LDOWN, LUP, at, skip_unless_real_display

pytestmark = pytest.mark.realgui

_EVIDENCE_DIR = Path(__file__).resolve().parents[2] / "design_export" / "evidence_e4b"
_CHANNELS = 120
_SAMPLES = 50_000


def _fixture_mf4(path: Path) -> None:
    from tests.mdf4_helpers import CAN, write_mdf4

    ts = [round(i * 0.001, 6) for i in range(_SAMPLES)]
    write_mdf4(
        path,
        [
            {
                "name": f"Ch{i:03d}",
                "bus_type": CAN,
                "timestamps": ts,
                "values": [float(i * 100 + (j % 97)) for j in range(_SAMPLES)],
            }
            for i in range(_CHANNELS)
        ],
    )


def _pump(dt: float = 0.03) -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    time.sleep(dt)


def _real_click(widget) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import QPoint

    center = QPoint(widget.width() // 2, widget.height() // 2)
    gp = widget.mapToGlobal(center)
    dpr = widget.devicePixelRatioF()
    x, y = round(gp.x() * dpr), round(gp.y() * dpr)
    at(x, y, LDOWN)
    _pump()
    at(x, y, LUP)
    for _ in range(4):
        _pump(0.02)


def test_confirm_then_export_completes_and_the_file_reads_back(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """(a) 実 OS クリックで [書き出す] -> 完走 -> 実ファイルを全列読み直し。"""
    skip_unless_real_display()
    from PySide6.QtWidgets import QMessageBox

    from valisync.core.export.csv_exporter import CsvExportOptions, ExportRequest
    from valisync.core.export.estimate import CONFIRM_THRESHOLD_S, estimate_export
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "confirm.mf4"
    _fixture_mf4(src)

    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    session = window.app_vm.session
    outcome = session.load(src)
    window._on_loaded(outcome)
    keys = tuple(f"{outcome.key}::Ch{i:03d}" for i in range(_CHANNELS))
    out = tmp_path / "confirm_out.csv"

    est = estimate_export(session, list(keys), CsvExportOptions())
    # 空虚化防止: ダイアログ経路を本当に通ることを、進む前に確定させる。
    assert est.est_read_s + est.est_write_s >= CONFIRM_THRESHOLD_S, (
        f"fixture が確認閾値に届かない (推定 {est.est_read_s + est.est_write_s:.2f} s "
        f"< {CONFIRM_THRESHOLD_S} s) — このままでは (a) がダイアログを通らず空振りする"
    )

    _show_top(window, qtbot)
    done: list[bool] = []
    boxes: list[QMessageBox] = []
    real_confirm = window._default_confirm_export

    def capture(est_arg):  # type: ignore[no-untyped-def]
        # 実 QMessageBox を出し、実 OS クリックで [書き出す] を押す。
        # exec() はモーダルなので、押下は別スレッドの実入力で行う。
        box_ready = threading.Event()

        def clicker() -> None:
            box_ready.wait(5.0)
            time.sleep(0.4)
            for w in __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication.topLevelWidgets():
                if isinstance(w, QMessageBox) and w.isVisible():
                    boxes.append(w)
                    btn = w.button(QMessageBox.StandardButton.Yes)
                    _real_click(btn)
                    return

        t = threading.Thread(target=clicker)
        t.start()
        box_ready.set()
        result = real_confirm(est_arg)
        t.join(timeout=10.0)
        return result

    window._confirm_export_fn = capture
    request = ExportRequest(keys, out, CsvExportOptions(), list)
    window._run_export(request, est)
    qtbot.waitUntil(lambda: out.exists(), timeout=180_000)
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=10_000)

    assert boxes, "確認ダイアログが実際には出ていない (空虚化)"
    rows = _read_rows(out)
    assert len(rows) == _SAMPLES, f"行数が想定外: {len(rows)}"
    assert len(rows[0]) == _CHANNELS + 1, f"列数が想定外: {len(rows[0])}"
    assert "エクスポートしました" in window.status_message()
    window.close()


def test_real_cancel_midway_leaves_no_file_and_no_temp(
    qtbot: QtBot, tmp_path: Path
) -> None:
    """(b) 実 OS クリックでキャンセル -> ファイル無し・temp 無し。"""
    skip_unless_real_display()
    from valisync.core.export.csv_exporter import CsvExportOptions, ExportRequest
    from valisync.core.export.estimate import estimate_export
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel
    from valisync.gui.views.main_window import MainWindow

    src = tmp_path / "cancel.mf4"
    _fixture_mf4(src)
    window = MainWindow(AppViewModel())
    qtbot.addWidget(window)
    session = window.app_vm.session
    outcome = session.load(src)
    window._on_loaded(outcome)
    keys = tuple(f"{outcome.key}::Ch{i:03d}" for i in range(_CHANNELS))
    out = tmp_path / "cancel_out.csv"
    est = estimate_export(session, list(keys), CsvExportOptions())

    _show_top(window, qtbot)
    window._confirm_export_fn = lambda _e: True  # (b) の対象は確認ではなくキャンセル
    seen_temp: list[str] = []
    window._run_export(ExportRequest(keys, out, CsvExportOptions(), list), est)

    qtbot.waitUntil(lambda: not window.busy_overlay.isHidden(), timeout=10_000)
    qtbot.waitUntil(
        lambda: seen_temp.extend(p.name for p in out.parent.glob(".tmp_*")) or bool(seen_temp),
        timeout=60_000,
    )
    shot = _EVIDENCE_DIR / "e4b_cancel_overlay.png"
    _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(shot))

    _real_click(window.busy_overlay.cancel_button)
    qtbot.waitUntil(lambda: window.busy_overlay.isHidden(), timeout=120_000)

    assert seen_temp, "temp が一度も観測されず、消滅 assert が空虚形になっている"
    assert not out.exists(), f"キャンセルしたのにファイルが存在する。証拠: {shot}"
    assert list(out.parent.glob(".tmp_*")) == [], "temp が残った (B6 違反)"
    assert "中止" in window.status_message()
    window.close()


def _show_top(window, qtbot) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    screen = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(
        screen.x() + 60, screen.y() + 60,
        min(1120, screen.width() - 120), min(760, screen.height() - 120),
    )
    window.show()
    window.raise_()
    window.activateWindow()
    qtbot.waitExposed(window)
    for _ in range(4):
        _pump(0.02)


def _read_rows(path: Path) -> list[list[str]]:
    text = path.read_text(encoding="utf-8-sig")
    return [line.split(",") for line in text.splitlines()[1:] if line]
```

`tests/realgui/test_export_range_realclick.py` の `_read_timestamps` を強化（**既存 assert 式は変えず**、全列読みを重ねる）:

```python
def _read_rows(path: Path) -> list[list[str]]:
    """全列を読む (G8 supersede)。

    **supersede 記録**: 旧 `_read_timestamps` は時刻列だけを読んでいたため、値列が
    全部空/全部ずれていても緑だった (spec §6 G8: 「時刻列しか読まない」を全列読みへ
    強化する)。時刻の assert は下の `_read_timestamps` がそのまま残す (既存の
    期待内容は 1 文字も変えない) — ここは列数と非空セルの存在を**足す**だけ。
    BOM 読み口は spec §5.1-2 の 26 サイトのうちの 1 つ (utf-8-sig)。
    """
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    assert lines and lines[0].startswith("timestamp,"), f"想定外のヘッダ: {lines[:1]}"
    header = lines[0].split(",")
    rows = [line.split(",") for line in lines[1:] if line]
    for row in rows:
        assert len(row) == len(header), f"列数がヘッダと不一致: {len(row)}"
    assert any(cell for row in rows for cell in row[1:]), "値列が全部空 (時刻だけの出力)"
    return rows


def _read_timestamps(path: Path) -> list[float]:
    return [float(row[0]) for row in _read_rows(path)]
```

実行:

```
uv run pytest --realgui tests/realgui/test_export_confirm_cancel_realclick.py -q
uv run pytest --realgui tests/realgui/test_export_range_realclick.py -q
```
Expected: 前者 `2 passed`／後者は**既存本数のまま pass**。

- [ ] **Step 5: realgui の sabotage（①ゲートが本当にゲートか）**

| # | 壊す箇所 | 予測 RED |
|---|---|---|
| R1 | `estimate.CONFIRM_THRESHOLD_S` を `1e9` へ（確認が絶対に出ない） | `test_confirm_then_export_completes_and_the_file_reads_back` の **1 件**（`boxes` が空 = 「確認ダイアログが実際には出ていない」）。**閾値 assert は緑のまま**（推定値そのものは変わらない）ことまで確認する |
| R2 | `_cancel_busy_operations` から export 側を削除 | `test_real_cancel_midway_leaves_no_file_and_no_temp` の **1 件**（overlay が下りず timeout） |
| R3 | `CsvExporter` の temp 削除を除去 | 同上の temp 残存 assert **1 件**（ファイル不在 assert は緑のまま） |
| R4 | `_read_rows` の列数 assert を削除した状態で、パイプラインの値列書き出しを空文字固定にする | 「値列が全部空」assert の **1 件**（＝ 旧 `_read_timestamps` では捕まらなかった穴の実証） |

- [ ] **Step 6: record range spike（B3・採否判断）**

`scripts/e4b_record_range_spike.py`（**production コードではない**。採用が決まった場合のみ Task 6/7 へ差し戻す）:

```python
"""B3 spike: MDF.select(record_offset/record_count) が読む量を実際に縮めるか。

**採否の条件** (spec §5.3):
- 仮想グループ (LD-14 展開の元になる 2-D チャンネル) で窓読みが成立するか
- copy_master=False との相互作用 (master も窓になるか・長さが samples と一致するか)
- 採る場合の必須条件 = **窓読みの結果を ChannelSampleCache に入れない**
  (キー空間に窓が無く、後続の全期間読みが切り詰められた配列を引く。_column_of の
  検証は長さ比較だけなので、同長の別窓は素通しする = サイレント誤データ)

quick_demo (170 MB) に対して 4 形を測る: 全期間 select / 窓 select (先頭 10%) /
2-D チャンネルの窓 select / copy_master=False x 窓。判断は「読む量 (wall と
process I/O) が窓の比率どおり縮むか」で行い、縮まないなら不採用にして理由を
spec §9-4 へ追記する。
"""
```

実行と判断:

```
uv run --with psutil python scripts/e4b_record_range_spike.py
```

- **縮む＋2-D で成立**した場合 → spec §10 へ「窓読みの結果を `ChannelSampleCache` に入れない」を**契約として確定**し、§5.3 の record range 項を「採用（Task 6 の読みへ適用）」へ改訂して follow-up チップを起票する（本増分では production へ入れない — 受け入れ条件ではない）。
- **縮まない／2-D で破綻**した場合 → spec §9-4 に**理由を実測つきで追記**して不採用を確定する（「未検証」のまま残さない — 次の増分で同じ spike をやり直すことになる）。

- [ ] **Step 7: spec と CLAUDE.md/roadmap の更新**

`docs/superpowers/specs/2026-08-01-e4b-export-write-path-design.md`:

- **§11「実測記録」を新設**（現在は欠番）: Step 2 の表をそのまま（**主語つき**で）貼る。G4 の USS 上限は「較正走行 P_A から供給・判定走行は別」と明記する。
- **§9-2** を「T-M で実測するまで受け入れ帯にしない」→ 実測値へ差し替え（`~10.1 GB・~18.4 分` の外挿を実測で置換）。
- **§9-4** に record range spike の結論（採用条件 or 不採用理由）を追記。
- **§9-5** の「2.3 × は設計値」を実測係数へ差し替え（外れていたら **`csv_exporter.TEMP_AMPLIFICATION`（実体は 1 つ）** を更新し、Task 8 のテストの `assert TEMP_AMPLIFICATION == 2.3` を新値へ更新する — **これは意図的 supersede なので理由をコメントで残す**）。
- **§5.5** に Task 8 の逸脱（読み項をチャンネル単価で計算する）を追記する。
- **§6 G3 の測定器 supersede**: spec は「**USS 増分**が ±20%」と書くが、実装は **tracemalloc を主**にし USS 版は `VALISYNC_MEMTEST` の opt-in に落とした（psutil が本番/dev いずれの依存にも無く、CI では丸ごと skip されるため — Task 7 `test_export_scale_invariance.py`）。**CI の門番は tracemalloc 版**である旨を §6 G3 へ追記する。
- **§5.3 / 共有契約 L52 の `plan_blocks` supersede**: 契約は「列の割り当てはチャンネル局所（**チャンネル跨ぎで混ぜない**）」と書くが、実装は **単独で上限を超える run を分割する**（幅 1,100 のチャンネルで 1 ブロックが上限の 2 倍を実体化するのを避けるため・E-4a のチャンネルキャッシュが 2-D を保持しているので 2 ブロック目はヒットになる）。この**意図的逸脱**を §5.3 へ明記する。
- **§5.1-4 [MG-7] の scope supersede**（Task 7 の裁定を spec へ反映）: 「`CsvExportOptions.header_names` の別持ちを廃止」は **`ExportRequest` 経路に限って達成**と読み替える。legacy overload の唯一のヘッダ搬送路として `header_names` は**残置**する（撤去は legacy overload 退役時の別増分）。docs/design.md 決定履歴にも 1 行残す。

`CLAUDE.md` / `docs/roadmap.md` の Phase 表 行の更新は **コントローラがユーザーと文言を詰める**。本タスクは「更新が必要である」ことと、書くべき内容（E-4b の出口数値・残る繰越＝並列ブロック処理／`_evict_resolved` の lock 外解放／レート別ファイル分割）を**報告に列挙するだけ**にする。

- [ ] **Step 8: ゲート＋コミット**

```
uv run pytest -q
uv run ruff check
uv run ruff format --check
uv run mypy src/
uv run pytest --realgui tests/realgui/ -q
```
realgui のフル一括実行では、既知の実行順依存フレーク（フォント計量 23px⇔24px・grip drag・expansion dialog wheel）が出うる。**出たら単体で回し直し、単体 pass を証拠として報告に書く**（既知フレークを本増分の失敗として扱わない／逆に本増分由来の失敗を既知フレークとして流さない — 単体で落ちるなら本増分の問題）。

```
git add scripts/measure_lazy_footprint.py scripts/e4b_record_range_spike.py \
        tests/realgui/test_export_confirm_cancel_realclick.py \
        tests/realgui/test_export_range_realclick.py tests/test_measure_lazy_footprint.py \
        src/valisync/core/export/estimate.py \
        docs/superpowers/specs/2026-08-01-e4b-export-write-path-design.md
git commit -m "$(cat <<'EOF'
test(export): prod 実測で係数を検定し realgui ①ゲートを張る (E-4b T-M)

計測器へ --export 段を追加。見積係数を **読み項と書き項に分けて** 検定する (合算だけ
合っていても、読み支配ケース (カーソル A-B x 全列) と書き支配ケース (全期間 x 全列) の
どちらかが桁で外れていることがある)。単価はすべて **主語つき** で記録した — この系列は
「何がそのバイト/秒を作ったか」を落として 3 度桁を外している。

G4 (全列完走) は「完走した」だけでは空ファイルでも緑になるので、行数 = union 長・
列数 = keys 長・ランダム 100 セルの独立オラクル照合を併置した。USS 上限は **較正走行から
供給し判定走行とは別** にする (同一走行から閾値を得る循環の禁止)。G5 (範囲エクスポート
後の常駐) は weakref の独立オラクルで数える — resolved_keys() は export 専用 resolve に
構造的に盲目で、bytes_held は pin されない列を数えない (spec §10)。

realgui ①ゲート (G8): (a) 実 OS クリックで確認ダイアログの [書き出す] を押して完走させ、
実ファイルを **全列** 読み直す。(b) 実キャンセルでファイルも temp も残らないことを、
**temp が一度は存在したことを観測してから** assert する。fixture は 120 チャンネルで
推定所要が確認閾値 5 s を確実に超えるようにし、超えていることをテスト自身が assert
する — 係数が検定で下がったらここが loud-fail し、黙ってダイアログを飛ばさない。

既存 realgui の _read_timestamps (時刻列しか読まない) を全列読みへ強化した
(supersede 記録つき)。値列が全部空でも緑だった穴を閉じる。

B3 の record range spike を実施し、採否と理由を spec §9-4 / §10 へ確定させた。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q6EW9U6n6snpfd5kDHpbox
EOF
)"
```
