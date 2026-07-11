# FU-11 ChannelBrowser フィルタ perf 実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** prod（330k ch）で 1 打鍵 ~17 秒フリーズするフィルタを、`group_signals` のグループ別キャッシュ＋VM の precompute/メモで数十 ms まで削る。

**Architecture:** 二層。(1) core `SignalGroupManager.group_signals` を FU-08 と同じ無効化ライフサイクルでグループ別キャッシュ化。(2) `ChannelBrowserVM` が active_key ごとに `(orig, lower, unit, key)` タプルを 1 度だけ precompute し、`signals` を `(active_key, filter)` でメモ化。既存公開 API のシグネチャ・返り値の意味は不変。

**Tech Stack:** Python 3.11+ / dataclass / numpy（既存）/ pytest。GUI ライブラリ非依存の VM・core ロジック。

## Global Constraints

- 設計 spec: `docs/superpowers/specs/2026-07-11-fu11-channelbrowser-filter-perf-design.md`。逸脱時はユーザーに確認。
- **既存公開 API 不変**: `SignalGroupManager.group_signals`／`Session.group_signals`／`ChannelBrowserVM.signals`／`header_text`／`empty_state`／`_group_total`／`tooltip_for` のシグネチャ・例外・返り値の意味を変えない（速くするのみ）。
- **`group_signals` の返り値は防御コピー**（`list(cached)`）＝`signals()` の `list(self._namespaced_list)` と同じ契約。キャッシュ本体を漏らさない。
- **キャッシュ無効化はキー変更イベントに紐付ける**: core は `add()`/`remove()` の既存 `_invalidate_namespaced()`、VM は `active_file` 変更（prep+memo クリア）と `set_filter`（memo キー不一致で自然再計算）。
- **VM キャッシュは遅延ビルド厳守**: `set_active_file` では作らず、最初の `signals`/`header_text`/`empty_state` アクセス時に構築。かつ `session.group_signals`/`source_name` は毎回**動的参照**（bound reference を保持しない）。既存テストの「patch → `set_active_file` → access」パターン互換のため。
- **テストレイヤー**: 本変更は GUI 入力経路の新設なし＝**Layer A のみ・realgui 不要**。速度は wall-clock でなく **rebuild/fetch 回数の構造アサート**（既存 `test_active_file_switch_fetches_only_active_group_no_full_scan` の spy パターンが雛形）で証明する。
- **品質ゲート（各コミット前）**: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。`| tail` に通さない（exit code を隠す）。
- **コミット footer**（各コミット必須）:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0185WwLfeTaikM3BFQ3u63vL
  ```

## File Structure

| ファイル | 責務 | Task |
|---|---|---|
| `src/valisync/core/loaders/signal_group_manager.py` | Part A: `group_signals` のグループ別キャッシュ | 1 |
| `tests/test_session.py` | Part A: キャッシュ同一性＋無効化の core テスト | 1 |
| `src/valisync/gui/viewmodels/channel_browser_vm.py` | Part B+C: precompute タプル＋`signals` メモ | 2 |
| `tests/gui/test_channel_browser_vm.py` | Part B+C: fetch 回数の構造アサート＋stale 防止 | 2 |

---

### Task 1: Part A — `SignalGroupManager.group_signals` のグループ別キャッシュ（core）

**Files:**
- Modify: `src/valisync/core/loaders/signal_group_manager.py`（`__init__` / `_invalidate_namespaced` / `group_signals`）
- Test: `tests/test_session.py`（新規テスト 1 本を追記）

**Interfaces:**
- Consumes: 既存 `SignalGroup`・`_namespaced(key, group)`（静的メソッド・不変）・`self._groups`。
- Produces: `group_signals(key: str) -> list[Signal]`（シグネチャ不変）。同一 key への連続呼び出しは**同一 `Signal` オブジェクト**を含むリストを返す（キャッシュ hit＝再構築なし）。`add()`/`remove()` 後は再構築。未知 key は従来どおり `KeyError`。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_session.py` の `test_group_signals_returns_namespaced_signals_for_one_group`（既存・91 行付近）の直後に追記。ファイル冒頭の既存 import（`Session`・`pytest`・`_write_csv`・`_FMT`）を再利用する。

```python
def test_group_signals_caches_wrappers_until_invalidated(tmp_path):
    """FU-11: group_signals はキャッシュ済ラッパーを返し、呼び出し毎に 330k 個の
    Signal を再生成しない。オブジェクト同一性（連続呼び出しで同じ Signal）と、
    add() 無効化後の再構築で証明する。"""
    a = tmp_path / "a.csv"
    _write_csv(a, "t,speed", ["0.0,1.0"])
    session = Session()
    ka = session.load(a, format_def=_FMT).key

    first = session.group_signals(ka)
    second = session.group_signals(ka)
    # 防御コピー: リストオブジェクトは別物…
    assert first is not second
    # …だが中身の Signal ラッパーは同一（再構築されていない）。
    assert len(first) == len(second) == 1
    assert first[0] is second[0]

    # 別ファイルのロード（add）はキャッシュを無効化 → ラッパー再構築。
    b = tmp_path / "b.csv"
    _write_csv(b, "t,rpm", ["0.0,2.0"])
    session.load(b, format_def=_FMT)
    after = session.group_signals(ka)
    assert after[0] is not first[0]  # 無効化後は作り直される
    assert [s.name for s in after] == [f"{ka}::speed"]  # 内容は不変
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/test_session.py::test_group_signals_caches_wrappers_until_invalidated -v`
Expected: FAIL — 現行 `group_signals` は毎回 `_namespaced` を新規実行するため `first[0] is second[0]` が False。

- [ ] **Step 3: 最小実装**

`src/valisync/core/loaders/signal_group_manager.py` を 3 箇所編集。

`__init__`（既存の `self._namespaced_map` 行の直後）に 1 行追加:

```python
        self._namespaced_by_key: dict[str, list[Signal]] = {}
```

`_invalidate_namespaced` に 1 行追加:

```python
    def _invalidate_namespaced(self) -> None:
        """Drop the namespaced caches; rebuilt lazily on next access."""
        self._namespaced_list = None
        self._namespaced_map = None
        self._namespaced_by_key = {}
```

`group_signals` をキャッシュ経由に置換:

```python
    def group_signals(self, key: str) -> list[Signal]:
        """Namespaced signals for a single group (KeyError if key is unknown).

        Lets callers fetch one file's signals without scanning every group.
        Cached per key on the same invalidation lifecycle as the whole-session
        caches (FU-08); rebuilt only after add()/remove(). Prevents the
        per-call rebuild of every namespaced wrapper (FU-11).
        """
        group = self._groups[key]  # 未知 key は従来どおり KeyError
        cached = self._namespaced_by_key.get(key)
        if cached is None:
            cached = self._namespaced(key, group)
            self._namespaced_by_key[key] = cached
        return list(cached)  # 防御コピー(signals() と同契約) — Signal は共有
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/test_session.py -v`
Expected: PASS（新規テスト＋既存 `test_group_signals_returns_namespaced_signals_for_one_group` 等が緑）。

- [ ] **Step 5: 品質ゲート**

Run: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`
Expected: 全て pass（`| tail` に通さない）。

- [ ] **Step 6: コミット**

```bash
git add src/valisync/core/loaders/signal_group_manager.py tests/test_session.py
git commit -m "$(cat <<'EOF'
perf(core): FU-11 Part A — group_signals をグループ別キャッシュ化（330k ラッパー再生成を除去）

group_signals が FU-08 のキャッシュ層をバイパスし呼び出し毎に namespaced Signal
を再生成していた（prod 3.3s/回）。add/remove の既存無効化に相乗りするグループ別
キャッシュを追加。同一性テストで再構築ゼロ＋無効化後の再構築を保証。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0185WwLfeTaikM3BFQ3u63vL
EOF
)"
```

---

### Task 2: Part B+C — `ChannelBrowserVM` の precompute＋メモ（VM）

**Files:**
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py`（`__init__` / `signals` / `_group_total` / `_on_app_change` ＋新規 `_ensure_prep`・`_filtered`）
- Test: `tests/gui/test_channel_browser_vm.py`（新規テスト 2 本を追記）

**Interfaces:**
- Consumes: Task 1 の `session.group_signals(active_key)`（キャッシュ済・高速）・`session.source_name(active_key)`・`self._app_vm.active_file_key`・`_SEP`・`SignalItem`。
- Produces: `signals`（property・返り値型不変 `list[SignalItem]`）は 1 打鍵内の複数アクセスで `group_signals` を **≤1 回**しか呼ばず、同一 active_key の 2 打鍵目は **0 回**。`header_text`/`empty_state`/`tooltip_for` の返り値契約は不変。

- [ ] **Step 1: 失敗するテストを書く**

`tests/gui/test_channel_browser_vm.py` の末尾に 2 本追記。冒頭の既存 import（`AppViewModel`・`ChannelBrowserVM`・`Signal`・`Path`）と既存ヘルパ `_setup_vm`・`_csv_format` を再利用する。

```python
def test_one_keystroke_fetches_group_at_most_once(tmp_path: Path) -> None:
    """FU-11: 1 打鍵(model reset + header_text + empty_state)で group_signals は
    高々 1 回(prep 構築時のみ)。同一 active_file の 2 打鍵目は 0 回。per-access
    再取得への回帰を防ぐ構造アサート(既存 no-full-scan spy パターンの延長)。"""
    vm, app_vm, key = _setup_vm(tmp_path)
    session = app_vm.session
    real_group_signals = session.group_signals
    calls: list[str] = []

    def spy(k: str) -> list[Signal]:
        calls.append(k)
        return real_group_signals(k)

    session.group_signals = spy  # type: ignore[method-assign]
    app_vm.set_active_file(key)  # 遅延ビルド: ここでは fetch しない

    calls.clear()
    # 1 打鍵目: View/Model 相当の 3 消費
    vm.set_filter("s")
    _ = list(vm.signals)  # SignalTableModel._on_vm_change
    vm.header_text()  # _refresh_state 1
    vm.empty_state()  # _refresh_state 2
    assert len(calls) == 1  # prep を 1 度だけ構築し全消費で共有

    calls.clear()
    # 2 打鍵目: 同一 active_file → prep/memo で完全充足
    vm.set_filter("si")
    _ = list(vm.signals)
    vm.header_text()
    vm.empty_state()
    assert calls == []


def test_active_file_switch_invalidates_prep_no_leak(tmp_path: Path) -> None:
    """FU-11: active file 切替で precompute を作り直す。前ファイルの信号が stale
    キャッシュ経由で漏れないことを保証。"""
    app_vm = AppViewModel()
    fa = tmp_path / "a.csv"
    fa.write_text("t,alpha,gamma\n0,1,2\n1,3,4\n", encoding="utf-8")
    fb = tmp_path / "b.csv"
    fb.write_text("t,beta,delta\n0,1,2\n1,3,4\n", encoding="utf-8")
    ka = app_vm.request_load(fa, _csv_format())
    kb = app_vm.request_load(fb, _csv_format())
    vm = ChannelBrowserVM(app_vm)

    app_vm.set_active_file(ka)
    assert {s.name for s in vm.signals} == {"alpha", "gamma"}

    app_vm.set_active_file(kb)
    assert {s.name for s in vm.signals} == {"beta", "delta"}  # alpha/gamma を漏らさない
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py::test_one_keystroke_fetches_group_at_most_once tests/gui/test_channel_browser_vm.py::test_active_file_switch_invalidates_prep_no_leak -v`
Expected: FAIL — 現行は各 `self.signals`/`_group_total` が毎回 `group_signals` を呼ぶため `len(calls) == 1` が False（5 前後になる）。

- [ ] **Step 3: 最小実装**

`src/valisync/gui/viewmodels/channel_browser_vm.py` を編集。

`__init__` の末尾（既存 `self._unsubscribe = ...` の直後）にキャッシュフィールドを追加:

```python
        # FU-11: active_key ごと 1 度だけ作る (orig, lower, unit, key) タプル列と、
        # (active_key, filter) でメモした結果。生存キーは counter 非減で不変信号集合に
        # 対応するため stale 化しない。無効化は _on_app_change("active_file") で行う。
        self._prep_key: str | None = None
        self._prep: list[tuple[str, str, str, str]] = []
        self._memo_key: tuple[str, str] | None = None
        self._memo_result: list[SignalItem] = []
```

`signals` property を置換（既存の本体を丸ごと差し替え）:

```python
    @property
    def signals(self) -> list[SignalItem]:
        """Return the flat list of signals for the active file, filtered.

        Memoised by (active_key, filter) so the three per-keystroke consumers
        (model reset + header_text + empty_state) share a single filter pass.
        """
        active_key = self._app_vm.active_file_key
        if not active_key:
            return []
        sig_key = (active_key, self._filter_text)
        if self._memo_key != sig_key:
            try:
                self._memo_result = self._filtered()
            except KeyError:
                self._memo_result = []
            self._memo_key = sig_key
        return self._memo_result
```

`signals` の直後に `_ensure_prep`・`_filtered` を新規追加:

```python
    def _ensure_prep(self) -> None:
        """Build the filter-independent (orig, lower, unit, key) tuples once per
        active file (FU-11). Reads session.group_signals dynamically so a
        monkeypatched session (tests) is honoured on the first lazy access."""
        active_key = self._app_vm.active_file_key
        if self._prep_key == active_key:
            return
        group_sigs = self._app_vm.session.group_signals(active_key)  # Part A: cached
        prep: list[tuple[str, str, str, str]] = []
        for sig in group_sigs:
            orig = sig.name.split(_SEP, 1)[1] if _SEP in sig.name else sig.name
            unit = str(sig.metadata.get("unit", "")) if sig.metadata else ""
            prep.append((orig, orig.lower(), unit, sig.name))
        self._prep = prep
        self._prep_key = active_key

    def _filtered(self) -> list[SignalItem]:
        """Apply the current substring filter over the precomputed tuples,
        building a SignalItem only for matches (FU-11)."""
        self._ensure_prep()
        fl = self._filter_text.lower()
        if not fl:
            return [SignalItem(name=n, unit=u, key=k) for n, _lo, u, k in self._prep]
        return [
            SignalItem(name=n, unit=u, key=k)
            for n, lo, u, k in self._prep
            if fl in lo
        ]
```

`_group_total` を prep 再利用に置換（別 `group_signals` 呼び出しを消す）:

```python
    def _group_total(self) -> tuple[str, int] | None:
        """Return (basename, total channel count) for the active file, or None."""
        active_key = self._app_vm.active_file_key
        if not active_key:
            return None
        try:
            self._ensure_prep()  # prep hit なら追加 fetch なし
            name = self._app_vm.session.source_name(active_key)
        except KeyError:
            return None
        return name, len(self._prep)
```

`_on_app_change` にキャッシュ無効化を追加:

```python
    def _on_app_change(self, change: str) -> None:
        """Handle notifications from AppViewModel."""
        if change == "active_file":
            self._prep_key = None  # FU-11: 別ファイルの prep/memo を捨てる
            self._memo_key = None
            self._notify("signals")
```

- [ ] **Step 4: テストが通ることを確認**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py -v`
Expected: PASS（新規 2 本＋既存 `test_filter_narrows_flat_list`・`test_header_counts_and_has_rows`・`test_no_match_state_and_query`・`test_no_channels_state`・`test_signal_item_contains_unit`・`test_active_file_switch_fetches_only_active_group_no_full_scan`・tooltip 系が全て緑）。

- [ ] **Step 5: 品質ゲート**

Run: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`
Expected: 全て pass。

- [ ] **Step 6: コミット**

```bash
git add src/valisync/gui/viewmodels/channel_browser_vm.py tests/gui/test_channel_browser_vm.py
git commit -m "$(cat <<'EOF'
perf(gui): FU-11 Part B+C — ChannelBrowserVM の precompute＋メモで打鍵を数十msに

active_key ごと (orig, lower, unit, key) を 1 度だけ precompute し、signals を
(active_key, filter) でメモ化。_group_total も prep を再利用。1 打鍵の
group_signals 実効呼び出しを prep 構築時の 1 回のみ(2 打鍵目 0 回)に削減。
active_file 切替で prep/memo を無効化(stale 漏れ防止)。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0185WwLfeTaikM3BFQ3u63vL
EOF
)"
```

---

## 手動パフォーマンス確認（任意・非 CI）

CI で回すのは Task 1/2 の構造アサートのみ。実機体感の確認は scratchpad の `fu11_filter_profile.py` を prod_demo.mf4 に対して手動実行し、1 打鍵が数十 ms 台になることを確認する（demo_data は gitignore・スクリプトはコミットしない）。

## Self-Review

- **Spec coverage**: Part A → Task 1、Part B → Task 2 の memo、Part C → Task 2 の precompute。tooltip の波及は Part A で自動解消（spec §2.3・追加作業なし）。非目標（debounce 等）はタスク化しない。全 spec 節にタスク対応あり。
- **Placeholder scan**: TBD/TODO・「適切なエラー処理」等の曖昧句なし。全コードブロックは実コード。
- **Type consistency**: `_prep` は `list[tuple[str, str, str, str]]`、`_memo_key` は `tuple[str, str] | None`、`_memo_result` は `list[SignalItem]`。`_filtered`/`signals` の返り値は `list[SignalItem]`、`_group_total` は `tuple[str, int] | None`。全て Task 内で一貫。`group_signals` 返り値 `list[Signal]`（Task 1）を Task 2 が消費。
