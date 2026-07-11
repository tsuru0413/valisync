# FU-16 prod クローズ prune perf 根治 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** prod（330k ch）でファイルを閉じた後のフリーズを、`prune_missing_signals` の session 全走査（＝namespaced 全再構築）を排除して解消する。

**Architecture:** `prune_missing_signals` を「`session.signals()` の全信号名集合との突合」から「**生存 group_key 集合とのメンバシップ判定**」へ置換する。`signal_key = {group_key}::{name}` なので entry から group_key を切り出し、`Session.group_keys()`（新規・`SignalGroupManager.keys` への委譲）で得た生存キー集合に含まれるかで prune する。session 全走査も namespaced 再構築も発火しないため、コストは O(#files)＋O(プロット中 entry 数) で 330k のチャンネル数に非依存。

**Tech Stack:** Python 3 / PySide6 / pyqtgraph / pytest / uv。

## Global Constraints

- 抽出は VM 側 `signal_key.split(KEY_SEPARATOR, 1)[0]`（既存 `graph_panel_vm.py:535` と同一パターン）。`KEY_SEPARATOR` は `graph_panel_vm.py:20` で import 済み。SGM に新ヘルパは追加しない。
- call-count 構造テストは **`app_vm.unload_file(key)` の unloaded 実ブロードキャスト → 全タブ全パネル配送**を通す（単一 prune 直叩きは N×P の乗数を exercise せず false-green）。
- perf 実測は **prod スケール必須**（`prod_demo.mf4` 330k）。小データ perf は FU-16 を隠す（naive）。
- スコープは A案 — 副次「`_invalidate_namespaced` 削除キーのみ drop」は**含めない**（prod 実測で残コストを見てから別増分）。
- 品質ゲート（コミット前に全通過）: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- prod デモデータ生成: `uv run python scripts/generate_demo_mf4.py --profile prod`（≈1.36GB・生成物は `demo_data/`・gitignore）。

---

### Task 1: `Session.group_keys()` 追加

**Files:**
- Modify: `src/valisync/core/session.py`（`signal_map` 付近＝`:192-198` の直後）
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `SignalGroupManager.keys`（`signal_group_manager.py:57-60`・`property -> list[str]`・挿入順）
- Produces: `Session.group_keys() -> list[str]`（Task 3 が `set(session.group_keys())` で消費）

- [ ] **Step 1: Write the failing test**

`tests/test_session.py` に追加（既存の load ヘルパ／fixture 命名は同ファイルの他テストに合わせる。CSV を2つロードしてキー順を検証）:

```python
def test_group_keys_returns_loaded_group_keys_in_insertion_order(
    tmp_path: Path,
) -> None:
    """Session.group_keys() delegates to SignalGroupManager.keys: the keys of
    all loaded groups in insertion order. Used by prune to test signal
    membership by file without walking every signal (FU-16)."""
    session = Session()
    k1 = session.load(_write_min_csv(tmp_path / "a.csv"), _csv_format())
    k2 = session.load(_write_min_csv(tmp_path / "b.csv"), _csv_format())
    assert session.group_keys() == [k1, k2]
    session.unload(k1)
    assert session.group_keys() == [k2]
```

`_write_min_csv` / `_csv_format` / `Session.load` / `Session.unload` は `tests/test_session.py` の既存ヘルパ・API を使う（無い場合は同ファイルの近接テストが使う最小 CSV 生成・format 生成をそのまま流用）。

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session.py::test_group_keys_returns_loaded_group_keys_in_insertion_order -v`
Expected: FAIL — `AttributeError: 'Session' object has no attribute 'group_keys'`

- [ ] **Step 3: Write minimal implementation**

`src/valisync/core/session.py` の `signal_map`（`:192-198`）の直後に追加:

```python
    def group_keys(self) -> list[str]:
        """Keys of all loaded groups, in insertion order.

        Delegates to SignalGroupManager.keys. Lets callers test whether a
        namespaced signal_key's group is still loaded without walking every
        signal (FU-16: prune reconciliation avoids forcing a namespaced
        rebuild at prod scale).
        """
        return self._groups.keys
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_session.py::test_group_keys_returns_loaded_group_keys_in_insertion_order -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/valisync/core/session.py tests/test_session.py
git commit -m "feat(fu16): Session.group_keys() — 生存グループキー一覧（SGM.keys 委譲）"
```

---

### Task 2: prod perf 計測ハーネス＋honest-RED ベースライン（旧 prune の遅さを実測）

**Files:**
- Create: `scripts/fu16_prune_bench.py`
- （前提）`demo_data/prod_demo.mf4` を生成済みにする

**Interfaces:**
- Consumes: `Session.load` / `AppViewModel` / `GraphAreaVM`（複数タブ・パネル構成）/ `GraphPanelVM.add_signal` / `AppViewModel.unload_file`
- Produces: 標準出力に `prune wall-clock (ms)` と `session.signals() call-count`（before 値を記録）

このタスクは perf E2E の honest-RED。**実装前（現行の全走査 prune）で prod 実測**し、遅さと呼出回数を確定する（gui-test-plan 手順6=真因の実測確定）。CI では走らせない（重い・ローカル実測）。

- [ ] **Step 1: prod デモデータを生成**

Run: `uv run python scripts/generate_demo_mf4.py --profile prod`
Expected: `demo_data/prod_demo.mf4`（≈1.36GB・330,004 ch）。既存なら skip 可。

- [ ] **Step 2: 計測ハーネスを書く**

`scripts/fu16_prune_bench.py`（GUI クリック不要＝ヘッドレスプロファイル。複数タブ×パネルで N×P の乗数経路を exercise。プロット中信号は少数＝prune コストが「プロット数」でなく「session 全走査」に支配される真因を露出させる）:

```python
"""FU-16 prune perf bench: prod スケールで unloaded→全パネル prune を実測.

before(全走査 prune): session の全 330k 信号を N×P 回走査＋remove 後初回の
namespaced 全再構築で長時間。after(group_key フィルタ): O(#files)×entry 数。
体感は実 GUI close(/verify)が最終ゲートだが、本ベンチで decisive な数値を取る。
"""

from __future__ import annotations

import time
from pathlib import Path

from valisync.core.formats import mdf_format  # 既存の MDF FormatDefinition 供給元に合わせる
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM

PROD = Path("demo_data/prod_demo.mf4")
TABS, PANELS_PER_TAB, SIGNALS_PER_PANEL = 3, 3, 5


def main() -> None:
    app_vm = AppViewModel()
    key = app_vm.request_load(PROD, mdf_format())
    # プロットする実在の signal_key を先頭から少数採取(プロット数は真因に無関係)
    names = [s.name for s in app_vm.session.signals()][:SIGNALS_PER_PANEL]

    vm = GraphAreaVM(app_vm)
    for _ in range(TABS - 1):
        vm.add_tab()
    for tab in range(TABS):
        vm.set_active_tab(tab)
        while len(vm.panels(tab)) < PANELS_PER_TAB:
            vm.add_panel(tab)
        for panel in vm.panels(tab):
            for name in names:
                panel.add_signal(name)

    calls = 0
    real_signals = app_vm.session.signals

    def spy():
        nonlocal calls
        calls += 1
        return real_signals()

    app_vm.session.signals = spy  # type: ignore[method-assign]

    t0 = time.perf_counter()
    app_vm.unload_file(key)  # unloaded broadcast → 全タブ全パネル prune
    dt_ms = (time.perf_counter() - t0) * 1000

    print(f"tabs={TABS} panels/tab={PANELS_PER_TAB} -> panels={TABS * PANELS_PER_TAB}")
    print(f"prune wall-clock: {dt_ms:.1f} ms")
    print(f"session.signals() call-count during prune: {calls}")


if __name__ == "__main__":
    main()
```

`mdf_format()` / `AppViewModel.request_load` / `GraphAreaVM.add_tab` / `set_active_tab` / `panels(tab)` / `add_panel(tab)` の正確な名前は、実装時に `tests/gui/test_graph_area_vm.py`（`vm.add_panel(0)` / `vm.panels(0)` / `app_vm.request_load` / `app_vm.unload_file` の既存使用）で確認して合わせる。タブ追加 API が別名なら `vm.inspect()["tabs"]` で確認。

- [ ] **Step 3: honest-RED を実測（現行の全走査 prune で）**

Run: `uv run python scripts/fu16_prune_bench.py`
Expected（現行実装）: `call-count = TABS*PANELS_PER_TAB = 9`（各パネルが `session.signals()` を1回呼ぶ＝乗数）、`prune wall-clock` は数百ms〜秒オーダー（remove 直後初回の namespaced 全再構築＋各パネル O(残存 330k) スキャン）。**この before 数値をコミットメッセージ/PR に転記**。

- [ ] **Step 4: Commit**

```bash
git add scripts/fu16_prune_bench.py
git commit -m "test(fu16): prod prune perf 計測ハーネス＋honest-RED ベースライン（call-count=9・wall-clock=<実測>ms を記録）"
```

---

### Task 3: `prune_missing_signals` を生存 group_key フィルタへ（call-count 構造テスト＋正当性）

**Files:**
- Modify: `src/valisync/gui/viewmodels/graph_panel_vm.py:482-497`
- Test: `tests/gui/test_graph_area_vm.py`

**Interfaces:**
- Consumes: `Session.group_keys()`（Task 1）/ `KEY_SEPARATOR`（`graph_panel_vm.py:20` で import 済み）
- Produces: 挙動不変の `prune_missing_signals`（`session.signals()` 非呼出）

- [ ] **Step 1: call-count 構造テストを書く（RED 予定）**

`tests/gui/test_graph_area_vm.py` に追加（既存 `test_graph_area_prunes_panels_when_file_unloaded`（`:524`）と同じ `_write_csv`/`_csv_format`/`AppViewModel`/`GraphAreaVM` パターン、spy は `test_channel_browser_vm.py:267-277` の no-full-scan パターンを踏襲）:

```python
def test_unload_prunes_every_panel_without_scanning_all_session_signals(
    tmp_path: Path,
) -> None:
    """FU-16: unloading a file must prune plotted signals in every panel via
    group-key membership, NEVER calling session.signals() (which forces a
    namespaced rebuild of all remaining signals at prod scale). Multiple
    panels must not multiply the scan. Sabotage-RED: reverting prune to
    `{s.name for s in session.signals()}` makes call-count == panel-count > 0.
    """
    app_vm = AppViewModel()
    key = app_vm.request_load(_write_csv(tmp_path / "a.csv"), _csv_format())
    key2 = app_vm.request_load(_write_csv(tmp_path / "b.csv"), _csv_format())
    vm = GraphAreaVM(app_vm)
    vm.add_panel(0)  # tab 0 に 2 panel（N×P の乗数を exercise）
    for panel in vm.panels(0):
        panel.add_signal(f"{key}::speed")
        panel.add_signal(f"{key2}::speed")

    calls = 0
    real_signals = app_vm.session.signals

    def spy_signals() -> list[Signal]:
        nonlocal calls
        calls += 1
        return real_signals()

    app_vm.session.signals = spy_signals  # type: ignore[method-assign]

    app_vm.unload_file(key)  # unloaded broadcast → every panel prunes

    assert calls == 0, f"prune walked all session signals {calls} times"
    # 正当性: 消えたファイルの信号だけ落ち、生存ファイルの信号は残る
    for panel in vm.panels(0):
        keys = [p["signal_key"] for p in panel.inspect()["plotted_signals"]]
        assert keys == [f"{key2}::speed"]
```

`Signal` の import が無ければ先頭に `from valisync.core.models import Signal` を追加。

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest "tests/gui/test_graph_area_vm.py::test_unload_prunes_every_panel_without_scanning_all_session_signals" -v`
Expected: FAIL — `calls == 2`（2パネル×1回 `session.signals()`。現行 prune が全走査）。

- [ ] **Step 3: prune を group_key フィルタへ実装**

`src/valisync/gui/viewmodels/graph_panel_vm.py:482-497` の `prune_missing_signals` を置換（docstring も更新）:

```python
    def prune_missing_signals(self) -> None:
        """Drop plotted signals whose source group is no longer loaded.

        Filters by *group key* membership (O(#files)) instead of walking every
        Session signal — the latter forced a namespaced rebuild of all
        remaining signals on the first call after unload and re-scanned O(n)
        per panel, freezing the app on close at prod scale (FU-16). A
        signal_key ``{group_key}::{name}`` survives iff its group_key is still
        loaded; whole groups load/unload together so per-signal matching is
        unnecessary. Survivors keep heights/positions; removed bands stay blank.
        """
        live = set(self._session.group_keys())
        kept = [
            e
            for e in self._plotted
            if e.signal_key.split(KEY_SEPARATOR, 1)[0] in live
        ]
        if len(kept) == len(self._plotted):
            return
        self._plotted = kept
        self._compact_axes()
        self._invalidate_cache()
        self._notify("signals")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest "tests/gui/test_graph_area_vm.py::test_unload_prunes_every_panel_without_scanning_all_session_signals" -v`
Expected: PASS（`calls == 0`・生存ファイル信号のみ残る）。

- [ ] **Step 5: 既存 prune 挙動の無回帰を確認**

Run: `uv run pytest "tests/gui/test_graph_area_vm.py::test_graph_area_prunes_panels_when_file_unloaded" tests/gui/test_app_viewmodel.py -v`
Expected: PASS（unload で該当信号が全パネルから消える既存契約を保存）。

- [ ] **Step 6: サボタージュ検証（honest-RED の証明）**

一時的に prune を旧実装（`present = {s.name for s in self._session.signals()}` / `kept = [e for e in self._plotted if e.signal_key in present]`）へ戻し、Step 4 のテストが `calls == 2` で FAIL することを確認 → 新実装へ戻す。（コミットはしない・確認のみ。）

- [ ] **Step 7: 品質ゲート＋Commit**

```bash
uv run ruff check && uv run ruff format --check && uv run mypy src/ && uv run pytest tests/gui/test_graph_area_vm.py -q
git add src/valisync/gui/viewmodels/graph_panel_vm.py tests/gui/test_graph_area_vm.py
git commit -m "perf(fu16): prune_missing_signals を生存 group_key フィルタへ（session 全走査＝namespaced 全再構築を排除・call-count N×P→0）"
```

---

### Task 4: prod perf 修正後実測＋FU-03 相乗り試行

**Files:**
- （実測のみ・コード変更なし。結果は Task 5 の catalog へ）

- [ ] **Step 1: after 実測（同ハーネス）**

Run: `uv run python scripts/fu16_prune_bench.py`
Expected（修正後）: `call-count == 0`、`prune wall-clock` が before から桁で短縮（O(#files)×entry 数）。before/after を並記して記録。

- [ ] **Step 2: 実 GUI で close の体感を確認（perf E2E の最終ゲート・/verify）**

Run: `uv run valisync`（`demo_data/prod_demo.mf4` を開く）
手順: prod をロード → 複数タブ・複数パネルに信号をプロット → ファイルを close（確認ダイアログ→OK）
観測: **クローズ後にフリーズしない**（体感）＋確認ダイアログ表示までが即時。スクショ or 体感記録を残す（嘘プロキシ不可＝実 close を実行）。

- [ ] **Step 3: FU-03 相乗り試行（同 prod セットアップ）**

同じ `uv run valisync`＋prod ロード・複数信号プロット状態で、**File/Channel/Diagnostics ドックの開閉**を実施し体感/レイテンシを観測。
- **再現（体感フリーズ）した場合**: FU-03 を🔴へ昇格し、条件（プロット信号数/パネル・軸数/ズーム状態）を記録して別途対応（本プランでは修正しない）。
- **再現しない場合**: クローズ判断（catalog: cProfile で ~44ms・RN-04 のベクトル化で緩和済みの公算）。
結果を Task 5 で catalog に転記。

- [ ] **Step 4: ①証拠ゲート（gui-verify で点検）**

- [ ] `scripts/fu16_prune_bench.py` の before/after（call-count・wall-clock）を PR に添付
- [ ] 実 GUI（prod）close→フリーズ無しの体感/スクショを添付
- [ ] FU-03 試行結果（再現有無・条件）を記録

---

### Task 5: catalog 更新（FU-16 解消・FU-03 結果転記）

**Files:**
- Modify: `docs/audit-findings-catalog.md`（FU-16 行・SS-FOLLOWUP 見出しの解決順注記・FU-03 行）

- [ ] **Step 1: FU-16 行を✅解消へ更新**

`docs/audit-findings-catalog.md` の FU-16 行（`:176`）の重要度を `✅` にし、根因フィックス（生存 group_key フィルタ＋`Session.group_keys()`）・**prod 実測 before/after（call-count N×P→0・wall-clock <before>→<after>）**・スコープA（副次増分 invalidate は非実施＝実測で残コスト無しを確認 or 別増分へ）を追記。

- [ ] **Step 2: FU-03 行を試行結果で更新**

FU-03 行（`:163`）に、同 prod セットアップでの実 GUI ドック開閉試行の結果（再現有無・条件・昇格 or クローズ判断）を転記。

- [ ] **Step 3: SS-FOLLOWUP 見出しの進捗注記を更新**

`:157` の解決順注記に「②FU-16 ✅解消（PR #XX）・FU-03 相乗り結果」を反映。

- [ ] **Step 4: Commit**

```bash
git add docs/audit-findings-catalog.md
git commit -m "docs(fu16): FU-16 ✅解消を catalog 反映（prod実測 <before>→<after>）＋FU-03 相乗り試行結果を転記"
```

---

## Self-Review

**1. Spec coverage:**
- 根因フィックス（prune を group_key フィルタ／`session.signals()` 非呼出）→ Task 3 ✅
- `Session.group_keys()` 追加 → Task 1 ✅
- 抽出は VM 側 split（既存パターン）→ Task 3 Step 3 ✅
- スコープ外（副次増分 invalidate 非実施）→ Global Constraints＋Task 5 で明記 ✅
- Layer A/B 構造アサート（call-count・unloaded 実経路・サボタージュRED）→ Task 3 ✅
- prod 実測 honest-RED＋after → Task 2（before）・Task 4（after）✅
- 実 GUI close 体感（最終ゲート）→ Task 4 Step 2 ✅
- FU-03 相乗り → Task 4 Step 3・Task 5 Step 2 ✅
- catalog 反映 → Task 5 ✅
- 受け入れ基準①〜⑥ → 全 Task に分配 ✅

**2. Placeholder scan:** 実装/テストコードは全て具体。`<before>/<after>` は実測後に埋める実値プレースホルダ（意図的）。API 名の実装時確認（add_tab 等）は「既存テストで確認」と具体化済み。

**3. Type consistency:** `group_keys() -> list[str]`（Task 1 定義）を Task 3 が `set(self._session.group_keys())` で消費・一致。`KEY_SEPARATOR`（既存 import）・`signal_key`（`_PlottedEntry.signal_key`）整合。spy パターンは `test_channel_browser_vm.py` と同一シグネチャ。
