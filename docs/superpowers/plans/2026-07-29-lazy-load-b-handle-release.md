# 増分B（決定的なハンドル解放＋teardown ペーシング）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **改訂履歴（2026-07-29・敵対的レビュー反映）**: 初版に対しアドバーサリアルレビュー
> （9 レンズ・独立実測つき）を実施し **判定 NEEDS-CHANGES（Critical 2 / Important 9 / Minor 3）**。
> **全件を本改訂で反映済み**。骨格（close を `Session.remove_group` に置く／多軸ペーシング／
> 会計の identity dedup／繰越 Minor）は spec と固定ユーザー決定に忠実で不変。主な修正は
> ①**ガードの置き場所**（`main_window.py` に unload 入口は存在しない → `AppViewModel.unload_file`
> のチョークポイントへ移し Task 1 と同一コミットで出荷）②**dedup 受け入れテストの反転是正**
> （fixture の master が writeable で共有が成立せず、正しい実装ほど RED・誤実装でだけ緑だった）
> ③**テストの正直さ**（ubuntu CI での確定 RED / 恒真 / demo-gate による 100% skip / 原理的に
> falsify 不能なテストを全て実効化）④**ペーシングの第 3 軸**（実時間デッドライン）。
>
> **本改訂で確定したユーザー判断 3 件**:
> 1. **ペーシングの第 3 軸を採用** — `_TICK_DEADLINE_S = 0.008`（半フレーム）を byte / signal と
>    並ぶ第 3 の停止条件にする。**`_SIGNAL_BUDGET = 8,000` は固定ユーザー決定どおりハード上限の
>    まま据え置き（下げない）**。WHY: 1.97µs/信号 は**未展開シェル**での実測値で、実際に展開済み
>    配列を解放するティックは実測 **24-38ms**＝count 軸が守ろうとしたフレーム予算をそのまま破る。
>    デッドラインは両方の形状に対して保証を成立させる。
> 2. **多重 unload は「冪等」にしない** — `remove_group` の 2 回目は今日 `KeyError`（実行確認済み）
>    で、GUI からは 1 回目でキーがリストから消えるため到達不能。**production の挙動は変えず、
>    spec の受け入れ基準の文言を実挙動へ訂正**する（本プランにも同旨を記載・Task 1 で実挙動を pin）。
> 3. **拒否の通知チャネルは「メニュー項目の disabled＋tooltip」＋「ステータス＋モーダルの
>    バックストップ」の二層**（モーダル単独の確認ダイアログは追加しない）。併せて**既存の無音の
>    拒否（`dependent_signals` による removal 拒否）も同じチャネルへ載せる** — 破壊的操作の
>    クリックが何も起こさないのは同じ欠陥だから。

**Goal:** 開いた mf4 のロックを unload で**決定的に**解放し、遅延ロード後の teardown が UI を固めないようにする。

**Architecture:** `MdfHandle.close()` を `Session.remove_group` から呼ぶ（core が handle 寿命を持ち、unload と `_discard` の両方を構造的にカバー）。teardown のバイト会計を正直化すると未展開グループが 1 ティックで解放され **実測 649ms のフリーズ**になるため、**バイト予算・信号数上限（8,000/tick）・実時間デッドライン（8ms）の三軸**にする。エクスポート実行中の unload は `AppViewModel.unload_file` のチョークポイントで拒否し、入口（コンテキストメニュー項目）も disabled にする。

**Tech Stack:** Python 3.13 / PySide6 / asammdf 8.8.22 / pytest。

**設計 spec:** [2026-07-24-lazy-load-signal-samples-design.md](../specs/2026-07-24-lazy-load-signal-samples-design.md) の「増分B」節（2026-07-29 再定義版）が一次情報源。

## Global Constraints

- 品質ゲート全通過: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- **ユーザー決定（変更不可）**:
  1. close は **`Session.remove_group`** に置く（`AppViewModel.unload_file` ではない）。
     ※ これは **close の置き場所**を縛る決定であり、**拒否ガードの置き場所は縛らない**。
  2. エクスポート中の unload は**許容するが、明示ガードで到達不能を確実にする**（`BusyOverlay` の偶然に依存しない）。
  3. ドレインの 1 ティック上限は **8,000 信号**（ハード上限・**下げない**）。バイト予算 64 MiB との二軸に、
     **本改訂で実時間デッドライン 8ms を第 3 軸として追加**（改訂履歴の判断 1）。先に達したもので中断。
  4. **MDF3 が開けない defect は本増分に含めない**（follow-up 起票）。
- **`MdfHandle._closed` のフラグは lock の外で立てる設計を維持する**（lock 内に移すと、待機中の reader が `is_closed` を False と読んで閉じる直前の handle に select を投げるため厳密に悪化する）。アトミック化はするが、位置は変えない。WHY をコメントに残す。
- **`os.replace` / `os.remove` をオラクルにするテストには必ず `pytest.mark.skipif(sys.platform != "win32")` を付ける。** POSIX の `rename(2)` は open 中のファイルでも成功するため、CI（`ubuntu-latest`・`.github/workflows/ci.yml:27,61`）では「毎回確定 RED」か「close の有無に関わらず恒真 PASS」のどちらかにしかならない。**CI 可視の主オラクルは `MdfHandle.is_closed` と close 呼出回数**。実 OS のロック解放の一次証拠は Task 8 の realgui（Windows・ローカル）に置く。
- **本増分で追加するテストは `demo_data/` に依存しないこと。** `demo_data/` は `.gitignore` 済みで CI に生成ステップが無く、`pytestmark = skipif(not DEMO.exists())` を持つファイル（`tests/core/loaders/test_lazy_mdf_values.py` 他 5 本）はモジュールごと skip される。フェイク／`tests/lazy_stubs.py`／`tests/mdf4_helpers.write_mdf4` + `tmp_path` を使う。
- **`RemovalResult.removed_columns` は「配線のみ」E-3 へ defer する** — 鋳造そのもの（`_mint_column` が `None` を返す限り常に `()`）は E-3 まで end-to-end 検証できないが、**受け渡し配線は `_resolved_by_key` の seed で検証可能**。ペーシング契約の穴を無音にしないため、本増分で **tripwire（loud-fail）** を置いて E-3 へ引き継ぐ（Task 6 Step 5）。規模は数十〜数千列＝数 ms であり 649ms フリーズの転移ではない。
- **多重 unload は冪等にしない**（判断 2）。2 回目の `remove_group` は `KeyError`（`signal_group_manager.py:57-60`）。production 挙動は変更せず、実挙動を Task 1 のテストで pin し、spec の受け入れ基準の文言を訂正する。
- GUI 変更は Layer A/B（CI）必須・Layer C（`--realgui`）で ①gate。
- コメントは WHY を書く。DRY / YAGNI / TDD。
- 実装はブランチ `feature/lazy-load-samples` 上。main 直接編集禁止。

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `src/valisync/core/session.py` | `remove_group` で handle close・`load` の登録失敗で close | 変更 |
| `src/valisync/core/loaders/mdf_handle.py` | `_closed` の check-and-set をアトミック化（位置は維持） | 変更 |
| `src/valisync/core/models/sample_source.py` | closed 先行 bail・double-checked read・`array_if_materialized`（会計の id-dedup 用） | 変更 |
| `src/valisync/gui/workers/teardown_service.py` | 三軸ペーシング（バイト＋信号数＋デッドライン）・identity dedup・`last_tick_bytes` | 変更 |
| `src/valisync/gui/workers/export_worker.py` | 実行中判定の公開（`is_busy`） | 変更 |
| `src/valisync/gui/viewmodels/app_viewmodel.py` | `set_busy_predicate` / `unload_file` の拒否ガード / 拒否理由の公開 / E-3 tripwire | 変更 |
| `src/valisync/gui/viewmodels/file_browser_vm.py` | `is_unload_blocked()`（メニュー affordance の述語） | 変更 |
| `src/valisync/gui/views/file_browser_view.py` | 「ファイルを閉じる」の disabled＋tooltip | 変更 |
| `src/valisync/gui/views/main_window.py` | 述語注入・拒否の通知（status＋モーダル DI）・`_discard` を teardown 経路へ・excepthook 診断の dedup とラベル | 変更 |
| `src/valisync/gui/strings.py` | 拒否文言 2 種 | 変更 |

---

## Task 1: `Session.remove_group` で handle を閉じる ＋ エクスポート中 unload を VM で拒否

> **なぜ 1 タスク・1 コミットか**: close だけを先に出荷すると、その後のコミットの間ずっと
> 「エクスポート中に unload すると GUI が実測 ~1.5s 同期ブロックし、以降の列読みが
> `SampleReadError` で壊れる」窓が開く。squash merge で main には残らないが、
> 分けて出す理由も無い（レビュー C1）。

**Files:**
- Modify: `src/valisync/core/session.py`（`remove_group`・~291）
- Modify: `src/valisync/gui/workers/export_worker.py`（`is_busy`）
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py`（`set_busy_predicate` / `unload_file` の先頭ガード / `last_unload_refusal`）
- Modify: `src/valisync/gui/views/main_window.py`（述語注入・`_on_app_change` の `"unload_blocked"` 分岐・通知モーダルの DI）
- Modify: `src/valisync/gui/strings.py`（`UNLOAD_BLOCKED_BY_EXPORT`）
- Test: `tests/core/test_handle_release.py`（新規）・`tests/gui/test_unload_export_guard.py`（新規）

**Interfaces:**
- Produces: `remove_group` が成功時に `SignalGroup.handle`（あれば）を close する。CSV グループは `handle is None` なので no-op。
- Produces: `ExportController.is_busy() -> bool`。
- Produces: `AppViewModel.set_busy_predicate(fn: Callable[[], bool] | None)`（`set_teardown` と同型の duck-typed 注入）・`AppViewModel.last_unload_refusal`・通知タグ `"unload_blocked"`。

- [ ] **Step 1: 失敗テストを書く（core 側 — ロック解放）**

`tests/core/test_handle_release.py`（新規）:

```python
"""unload でファイルロックが決定的に解放されることを固定する (増分B)。

今日でも最終的には解放されるが、それは asammdf の MDF.__del__ 経由で
「そのグループの最後の Signal 参照が死んだ時」= TeardownService のドレイン後
であり非決定的。明示 close で決定化する。

**CI 可視の主オラクルは `MdfHandle.is_closed` と mdf.close() の呼出回数**
(test_handle_is_closed_after_remove / test_remove_group_calls_close_exactly_once)。
os.replace を使う 2 本は Windows 限定 gate を付けてある — POSIX の rename(2) は
open 中のファイルでも成功するので、ubuntu CI では「確定 RED」か「恒真 PASS」に
しかならない (Global Constraints)。実 OS のロック解放の一次証拠は Task 8 の realgui。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.core.session import Session

windows_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="open-file rename lock は Windows のファイル共有セマンティクス "
    "(POSIX の rename(2) は open 中でも成功する)",
)


def _load_one(tmp_path: Path) -> tuple[Session, str, Path]:
    path = tmp_path / "lock.mf4"
    write_mdf4(
        path,
        [
            {
                "name": "Spd",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [1.0, 2.0],
            }
        ],
    )
    session = Session()
    outcome = session.load(path, confirm_expansion=None)
    return session, outcome.key, path


@windows_only
def test_file_is_locked_while_loaded(tmp_path: Path) -> None:
    session, _key, path = _load_one(tmp_path)
    victim = tmp_path / "moved.mf4"
    with pytest.raises(OSError):
        os.replace(path, victim)  # 開いている間は移動できない
    del session  # 明示: ここまで session を生存させる (早期解放でロックが落ちない)


@windows_only
def test_remove_group_releases_the_lock_without_gc(tmp_path: Path) -> None:
    # gc.collect() を呼ばずに解放されることが「決定的」の意味
    session, key, path = _load_one(tmp_path)
    session.remove_group(key)
    victim = tmp_path / "moved.mf4"
    os.replace(path, victim)  # 例外が出なければ成功
    assert victim.exists()


def test_handle_is_closed_after_remove(tmp_path: Path) -> None:
    """CI 可視の主オラクル (platform 非依存)。"""
    session, key, _path = _load_one(tmp_path)
    handle = session._groups.group(key).handle  # remove 前に掴んでおく
    assert handle is not None and handle.is_closed is False
    session.remove_group(key)
    assert handle.is_closed is True


def test_remove_group_calls_close_exactly_once(tmp_path: Path) -> None:
    """close 回数の platform 非依存オラクル (冪等 close なので 0 回も 2 回も不可)。"""

    class _CloseSpy:
        """handle.mdf を包んで close 回数を数える。

        MdfHandle.__slots__ に "mdf" があるのでインスタンス差し替えができる。
        """

        def __init__(self, real: object) -> None:
            self.real = real
            self.calls = 0

        def close(self) -> None:
            self.calls += 1
            self.real.close()

    session, key, _path = _load_one(tmp_path)
    handle = session._groups.group(key).handle
    assert handle is not None
    spy = _CloseSpy(handle.mdf)
    handle.mdf = spy
    session.remove_group(key)
    assert spy.calls == 1, f"mdf.close() が {spy.calls} 回 (冪等 close なので 1 回が正)"


def test_csv_group_removal_does_not_touch_a_handle(tmp_path: Path) -> None:
    """CSV は handle=None。close 経路が None で落ちないこと。

    (旧名 test_remove_group_is_idempotent_for_csv_groups — 本文は冪等性を一切
    exercise していなかったのでリネームした。冪等性の実挙動は
    test_remove_group_twice_raises が pin する。)
    """
    from valisync.core.models import Delimiter, FormatDefinition

    csv = tmp_path / "d.csv"
    csv.write_text("t,v\n0,1\n1,2\n", encoding="utf-8")
    session = Session()
    fmt = FormatDefinition(
        name="t1",
        delimiter=Delimiter.COMMA,
        timestamp_column=0,
        timestamp_unit="sec",
        signal_start_column=1,
        signal_end_column=1,
        has_header=True,
    )
    key = session.load(csv, fmt).key
    result = session.remove_group(key)
    assert result.removed is True


def test_remove_group_twice_raises(tmp_path: Path) -> None:
    """spec の「多重 unload 冪等」は今日のコードに対して偽 — 実挙動を pin する。

    2 回目は SignalGroupManager.remove が KeyError (signal_group_manager.py:57-60)。
    GUI からは 1 回目でキーがリストから消えるため到達不能なので、冪等化ではなく
    spec 文言の訂正を選んだ (改訂履歴の判断 2)。
    """
    session, key, _path = _load_one(tmp_path)
    session.remove_group(key)
    with pytest.raises(KeyError):
        session.remove_group(key)
```

- [ ] **Step 2: 失敗テストを書く（GUI 側 — 拒否ガード）**

`tests/gui/test_unload_export_guard.py`（新規）:

```python
"""エクスポート中の unload を **VM のチョークポイント**で拒否する (増分B・C1)。

実ユーザー経路は FileBrowserView._show_context_menu → build_context_menu →
_confirm_and_unload → FileBrowserVM.unload → **AppViewModel.unload_file** →
Session.remove_group。FileBrowserView も FileBrowserVM も ExportController に
到達できない (MainWindow が両者を別々に所有している) ため、ガードは
AppViewModel の 1 チョークポイントに置き、述語は MainWindow から duck-typed で
注入する (set_teardown と同型)。ここで assert しないと「MainWindow に unload
メソッドを新設してそれを assert」で実経路が無防備のまま緑になる。

拒否の機序 (WHY): close() は handle.lock を取るので、export ワーカーが select 中
だと GUI スレッドがその読み終了まで**同期ブロック**する (実測 cold 1.18s /
warm 0.73-0.83s)。in-flight の select は lock により完走し、SampleReadError に
なるのは _closed を見る「次の列」。BusyOverlay は MainWindow の子で cover() が
parent.rect() なので、フロートしたドック (トップレベル窓) は覆えない
= 「偶然の遮断」は今日も成立していない。
"""

from __future__ import annotations

import datetime
import threading
from pathlib import Path

import pytest

from tests.mdf4_helpers import CAN, write_mdf4
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel


def _loaded(tmp_path: Path) -> tuple[AppViewModel, str, object]:
    path = tmp_path / "guard.mf4"
    write_mdf4(
        path,
        [
            {
                "name": "Spd",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [1.0, 2.0],
            }
        ],
    )
    session = Session()
    key = session.load(path, confirm_expansion=None).key
    app_vm = AppViewModel(session=session)
    app_vm.register_loaded(key)
    handle = session._groups.group(key).handle
    assert handle is not None
    return app_vm, key, handle


def test_export_controller_is_busy_during_a_real_submit(qtbot) -> None:  # type: ignore[no-untyped-def]
    """実 submit で busy になり、完了で戻ること (内部集合を直接いじらない)。"""
    from valisync.gui.workers.export_worker import ExportController

    ctrl = ExportController()
    assert ctrl.is_busy() is False
    release = threading.Event()
    done: list[str] = []
    ctrl.submit(lambda: release.wait(5.0), on_success=lambda: done.append("ok"))
    assert ctrl.is_busy() is True  # submit 直後から busy (pool 開始を待たない)
    release.set()
    qtbot.waitUntil(lambda: done == ["ok"], timeout=5000)
    assert ctrl.is_busy() is False


def test_unload_is_refused_while_the_busy_predicate_is_true(tmp_path: Path) -> None:
    app_vm, key, handle = _loaded(tmp_path)
    tags: list[str] = []
    app_vm.subscribe(tags.append)
    app_vm.set_busy_predicate(lambda: True)

    app_vm.unload_file(key)

    assert key in app_vm.loaded_file_keys, "拒否されたのにリストから消えた"
    assert app_vm.session.group_signals(key), "拒否されたのに session から消えた"
    assert handle.is_closed is False, "拒否されたのに handle が閉じられた"
    assert tags == ["unload_blocked"], f"通知が {tags}"
    assert app_vm.last_unload_refusal == ("export_busy", ())


def test_unload_proceeds_when_the_predicate_is_false(tmp_path: Path) -> None:
    """positive control — 「そもそも経路に到達していない」との区別。"""
    app_vm, key, handle = _loaded(tmp_path)
    app_vm.set_busy_predicate(lambda: False)

    app_vm.unload_file(key)

    assert key not in app_vm.loaded_file_keys
    assert handle.is_closed is True
    with pytest.raises(KeyError):
        app_vm.session.group_signals(key)


def test_main_window_wires_the_export_controller_into_the_vm(qtbot) -> None:  # type: ignore[no-untyped-def]
    """実配線を通す: 実 submit で busy → 実 VM 経路の unload が拒否される。

    述語の同一性 (is) ではなく **効果** を見る — 述語を差し替えても
    「エクスポート中は閉じられない」が保たれることだけが契約。
    """
    from valisync.gui.views.main_window import MainWindow

    app_vm, key, handle = _loaded(tmp_path=Path(qtbot.__class__.__module__ and "."))  # ← 実装者へ: tmp_path fixture を使うこと
    win = MainWindow(app_vm)
    qtbot.addWidget(win)
    modals: list[str] = []
    win._notify_blocked = modals.append  # DI (既存 _default_confirm と同規約)

    release = threading.Event()
    win._export_controller.submit(lambda: release.wait(5.0))
    try:
        win.file_browser_vm.unload(0)  # 実 VM 経路 (View の確認モーダルの先)
        assert key in app_vm.loaded_file_keys
        assert handle.is_closed is False
        assert modals == ["エクスポート中はファイルを閉じられません"]
        assert win.status_message() == "エクスポート中はファイルを閉じられません"
    finally:
        release.set()
    qtbot.waitUntil(lambda: win._export_controller.is_busy() is False, timeout=5000)
```

> **実装者へ（必須の書き換え）**: `test_main_window_wires_the_export_controller_into_the_vm`
> の `_loaded(...)` 呼び出しはプレースホルダ。**`tmp_path: Path` を関数引数に取り
> `_loaded(tmp_path)` を呼ぶ**こと。文言は `S.UNLOAD_BLOCKED_BY_EXPORT` を参照せず
> **実文言を直書き**する（定数同士の比較は恒真化して独立オラクルにならない）。
> `MainWindow` の実 import 元・`qtbot.addWidget` の要否は既存 `tests/gui/` の
> MainWindow 系テストに合わせること。

- [ ] **Step 3: 失敗を確認**

Run: `uv run pytest tests/core/test_handle_release.py tests/gui/test_unload_export_guard.py -q -rs`

Expected（platform 明示）:
- Windows: `test_handle_is_closed_after_remove` / `test_remove_group_calls_close_exactly_once` /
  `test_remove_group_releases_the_lock_without_gc` が FAIL（close されないため）。
  ガード 4 本は `AttributeError: 'AppViewModel' object has no attribute 'set_busy_predicate'` で FAIL。
- Linux: `@windows_only` の 2 本が **skip** されることを `-rs` の出力で確認する
  （skip と pass を混同しない）。残りは Windows と同じく FAIL。

- [ ] **Step 4: `remove_group` で close する**

`session.py` の `remove_group`、`group, columns = self._groups.remove(key)` の直後に:

```python
        # 増分B: handle 寿命は core が持つ。ここで閉じることで unload と
        # MainWindow._discard (キャンセル完走のロールバック) の両方が構造的に
        # カバーされる — GUI 側 (unload_file) に置くと _discard が漏れる。
        # CSV/Derived グループは handle=None なので no-op。
        #
        # WHY (機序・誤解しやすい): close() は handle.lock を取る
        # (mdf_handle.py:30-31) ので、export ワーカーが select 中なら **GUI スレッドが
        # その読みの終了まで同期ブロック**する (実測 cold 1.18s / warm 0.73-0.83s)。
        # in-flight の select は lock により完走し、SampleReadError になるのは
        # _closed を見る「次の列」。lock は mdf.close() と in-flight mmap read の
        # 競合 (native アクセス違反) を防いでおり外せない。だから「エクスポート中の
        # unload」は close をやめるのではなく **UI 側で拒否**する
        # (AppViewModel.unload_file の述語ガード)。
        if group.handle is not None:
            group.handle.close()
```

（`SignalGroup.handle` は実在のフィールドなので `getattr` は使わない — 名前がドリフトしたら
`AttributeError` で loud-fail させる。)

- [ ] **Step 5: `is_busy` / 述語注入 / ガードを実装**

`export_worker.py`（`ExportController` に追加）:

```python
    def is_busy(self) -> bool:
        """エクスポートが実行中か (増分B: unload 拒否ガードの判定に使う)。

        submit で _active に入り _finish/_fail (GUI スレッドの queued スロット) で
        抜けるので、pool でワーカーが走り始める前から True になる — ガードとしては
        それが正しい (submit 直後の unload も拒否したい)。
        """
        return bool(self._active)
```

`app_viewmodel.py` の `__init__`（`self._teardown` の隣）に:

```python
        # 増分B: 「重い処理が実行中か」の duck-typed 述語 (GUI が ExportController を
        # 注入する)。VM は Qt も ExportController も知らないままガードできる。
        self._busy_predicate: Callable[[], bool] | None = None
        self._last_unload_refusal: tuple[str, tuple[str, ...]] | None = None
```

同ファイルに（`set_teardown` の直後）:

```python
    def set_busy_predicate(self, predicate: Callable[[], bool] | None) -> None:
        """Inject a duck-typed "a blocking job is running" predicate (増分B).

        Same shape as :meth:`set_teardown`. The real unload path
        (FileBrowserView → FileBrowserVM → :meth:`unload_file`) cannot reach the
        GUI-owned ExportController, so guarding at this single chokepoint is what
        makes the refusal cover the actual user path instead of a synthetic
        MainWindow entry point.
        """
        self._busy_predicate = predicate

    def is_busy(self) -> bool:
        """True when the injected predicate says a blocking job is running.

        The affordance (context-menu item) and the backstop (:meth:`unload_file`)
        read this same predicate, so they cannot disagree.
        """
        return self._busy_predicate is not None and self._busy_predicate()

    @property
    def last_unload_refusal(self) -> tuple[str, tuple[str, ...]] | None:
        """(reason code, detail names) of the most recently refused unload.

        Reason codes are VM-level, not user text: the View maps them to strings
        (``gui/strings.py``) so the ViewModel stays free of presentation.
        """
        return self._last_unload_refusal
```

`unload_file` の**先頭**（`self._session.remove_group(key)` より前）に:

```python
        if self.is_busy():
            # 増分B: close() は handle.lock を取るので、export ワーカーが select 中
            # だと GUI スレッドがその読み終了まで同期ブロックする (実測 0.73-1.18s)。
            # かつ _closed 以降の列読みは SampleReadError になりエクスポートが壊れる。
            # BusyOverlay は MainWindow の子で cover() が parent.rect() なので、
            # フロートしたドックは覆えない = 「偶然の遮断」は今日も成立していない。
            self._last_unload_refusal = ("export_busy", ())
            self._notify("unload_blocked")
            return
```

`main_window.py` の `self._export_controller = ExportController(parent=self)`（現 :198）の**直後**
（構築順は動かさない）に:

```python
        # 増分B: unload の拒否ガード。実経路 (FileBrowserView → FileBrowserVM →
        # AppViewModel.unload_file) は ExportController に到達できないので、述語を
        # VM のチョークポイントへ注入する (set_teardown と同型の duck-typed 注入)。
        self.app_vm.set_busy_predicate(self._export_controller.is_busy)
        # 拒否モーダルは DI (テストから差し替え可能 — _default_confirm と同規約)。
        self._notify_blocked: Callable[[str], None] = self._default_blocked_modal
```

同ファイルに:

```python
    def _default_blocked_modal(self, message: str) -> None:
        QMessageBox.warning(self, S.ACTION_REMOVE_FILE, message)

    def _on_unload_blocked(self) -> None:
        """VM が拒否した unload を通知する (FB-01: never silent — status + modal)。

        ステータス単独では不十分: event() が全ての QStatusTipEvent を横取りして
        set_status_message へ流すため (event() の docstring 参照)、メニューを
        hover しただけで空 tip が来てラベルが消える。timeout_ms は他の読み捨て
        メッセージと同じ 8000 (永続する stale ラベルを作らない)。
        """
        self.set_status_message(S.UNLOAD_BLOCKED_BY_EXPORT, timeout_ms=8000)
        self._notify_blocked(S.UNLOAD_BLOCKED_BY_EXPORT)
```

`_on_app_change`（現 :708）に分岐を追加:

```python
        if change == "unload_blocked":
            self._on_unload_blocked()
```

`strings.py` に:

```python
UNLOAD_BLOCKED_BY_EXPORT: Final = "エクスポート中はファイルを閉じられません"
```

- [ ] **Step 6: 通ることを確認 + 既存テスト全通過**

Run: `uv run pytest tests/core/ tests/test_session.py tests/gui/ -q`
Expected: PASS。close 後に遅延読みしようとするテストがあれば、それは
**`SampleReadError` になるのが正しい**（増分A で実装済み）。落ちたら中身を確認する。

- [ ] **Step 7: sabotage で honest-RED を確認（必須・結果を報告に記す）**

3 種を順に実施し、それぞれ確認したら戻す:

1. `remove_group` の `handle.close()` を一時的に外す →
   `test_handle_is_closed_after_remove` と `test_remove_group_calls_close_exactly_once` が
   **RED**。**`@windows_only` が skip されるプラットフォームでも RED になること**を確認する
   （＝ CI で執行力があることの証明）。
2. `unload_file` の述語ガード 4 行を外す → `test_unload_is_refused_while_the_busy_predicate_is_true`
   と `test_main_window_wires_the_export_controller_into_the_vm` が **RED**。
3. `main_window.py` の `set_busy_predicate(...)` の 1 行だけを外す →
   `test_main_window_wires_...` のみ **RED**（VM 単体テストは緑のまま＝配線と実装が独立に
   被覆されている証明）。

- [ ] **Step 8: ゲート＋コミット**

```bash
git add src/valisync/core/session.py src/valisync/gui/workers/export_worker.py \
        src/valisync/gui/viewmodels/app_viewmodel.py src/valisync/gui/views/main_window.py \
        src/valisync/gui/strings.py tests/core/test_handle_release.py \
        tests/gui/test_unload_export_guard.py
git commit -m "feat(core): remove_group で MDF ハンドルを閉じる＋エクスポート中の unload を VM で拒否"
```

---

## Task 2: 拒否の affordance ゲート（入口を塞ぐ）＋ 無音拒否の解消

> 改訂履歴の判断 3。Task 1 のバックストップで**フリーズ窓は既に閉じている**ので、
> 本タスクは UX の一次対策（実行不能な操作に確認モーダルを答えさせない）と、
> **既存の唯一の無音拒否**（`dependent_signals`）の同チャネル化。

**Files:**
- Modify: `src/valisync/gui/viewmodels/file_browser_vm.py`（`is_unload_blocked`）
- Modify: `src/valisync/gui/views/file_browser_view.py`（`build_context_menu`）
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py`（`dependent_signals` 拒否を同チャネルへ）
- Modify: `src/valisync/gui/views/main_window.py`（拒否理由 → 文言の写像）
- Modify: `src/valisync/gui/strings.py`
- Test: `tests/gui/test_unload_export_guard.py` に追記

**Interfaces:**
- Consumes: Task 1 の `AppViewModel.is_busy()` / `last_unload_refusal` / `"unload_blocked"`。
- Produces: `FileBrowserVM.is_unload_blocked() -> bool`。

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_unload_export_guard.py` に追記:

```python
def test_remove_action_is_disabled_and_explained_while_exporting(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """入口を塞ぐ: 実行不能な操作は確認モーダルを答えさせる前に disabled にする。"""
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
    from valisync.gui.views.file_browser_view import FileBrowserView

    app_vm, _key, _handle = _loaded(tmp_path)
    app_vm.set_busy_predicate(lambda: True)
    view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(view)

    menu = view.build_context_menu(0)
    remove = next(a for a in menu.actions() if a.text() == "ファイルを閉じる")
    assert remove.isEnabled() is False
    assert remove.toolTip() == "エクスポート中はファイルを閉じられません"
    # Qt はメニュー項目の tooltip を既定で抑制する — 有効化しないと説明が出ない。
    assert menu.toolTipsVisible() is True


def test_remove_action_is_enabled_when_not_exporting(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from valisync.gui.viewmodels.file_browser_vm import FileBrowserVM
    from valisync.gui.views.file_browser_view import FileBrowserView

    app_vm, _key, _handle = _loaded(tmp_path)
    app_vm.set_busy_predicate(lambda: False)
    view = FileBrowserView(FileBrowserVM(app_vm))
    qtbot.addWidget(view)

    menu = view.build_context_menu(0)
    remove = next(a for a in menu.actions() if a.text() == "ファイルを閉じる")
    assert remove.isEnabled() is True


def test_dependent_signal_refusal_is_announced_not_silent(tmp_path) -> None:
    """既存の唯一の無音拒否 (dependent_signals) を同じチャネルに載せる。

    確認モーダルに「はい」と答えた破壊的操作が何も起こさないのは、
    エクスポート中の拒否と同じ欠陥 (dependent_signals の GUI 消費者は grep でゼロ)。
    """
    app_vm, key, handle = _loaded(tmp_path)
    src = app_vm.session.signals()[0]
    derived = app_vm.session.evaluate_formula(f"{src.name} * 2", {src.name: src})
    tags: list[str] = []
    app_vm.subscribe(tags.append)

    app_vm.unload_file(key)

    assert key in app_vm.loaded_file_keys
    assert handle.is_closed is False
    assert tags == ["unload_blocked"]
    reason, names = app_vm.last_unload_refusal
    assert reason == "dependents"
    assert derived.name in names
```

> **実装者へ**: `evaluate_formula` の式は `tests/test_session.py:167-183` と同型に
> **namespaced 名をそのまま式に埋める**こと（`f"{src.name} * 2"`）。式パーサが
> `::` を含む識別子を扱えることは既存テストが実証済み。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_unload_export_guard.py -q`
Expected: FAIL（`remove.isEnabled()` が True・`toolTipsVisible()` が False・
`last_unload_refusal` が None）

- [ ] **Step 3: affordance ゲートを実装**

`file_browser_vm.py`:

```python
    def is_unload_blocked(self) -> bool:
        """True when unload would be refused right now (エクスポート実行中・増分B).

        Reads the SAME predicate as the backstop in ``AppViewModel.unload_file``,
        so the menu affordance and the refusal can never disagree.
        """
        return self._app_vm.is_busy()
```

`file_browser_view.py` の `build_context_menu` 冒頭を:

```python
        menu = QMenu(self)
        # Qt はメニュー項目の tooltip を既定で抑制する (src/ の前例は main_window.py と
        # graph_panel_view.py の 2 箇所のみ)。disabled の理由を出すには必須。
        menu.setToolTipsVisible(True)
        blocked = self._vm.is_unload_blocked()
        remove_action = menu.addAction(S.ACTION_REMOVE_FILE)
        remove_action.setEnabled(not blocked)
        if blocked:
            # 実行不能な操作は入口で塞ぐ — 確認モーダルに「はい」と答えさせてから
            # 拒否するのは二度手間 (直下の set_ref_action.setEnabled と同型)。
            remove_action.setToolTip(S.UNLOAD_BLOCKED_BY_EXPORT)
        remove_action.triggered.connect(lambda *_: self._confirm_and_unload(row))
```

（`FileBrowserView` に新しいコンストラクタ引数は足さない — VM 経由にすることで
`_export_controller` の構築順〔:191 の View より後の :198〕に振り回されず、
MainWindow を close over する参照循環も作らない。）

- [ ] **Step 4: 無音拒否を同チャネルへ**

`app_viewmodel.py` の `unload_file`、`if not result.removed:` を:

```python
        if not result.removed:
            # 増分B: 破壊的操作が無音で何も起きない状態をやめる (FB-01: never silent)。
            # dependent_signals は GUI の消費者がゼロだったので、確認モーダルに
            # 「はい」と答えたユーザーには「何も起きない」ようにしか見えなかった。
            self._last_unload_refusal = ("dependents", result.dependent_signals)
            self._notify("unload_blocked")
            return
```

`main_window.py` の `_on_unload_blocked` を理由ベースへ:

```python
    def _unload_refusal_message(self) -> str:
        reason, names = self.app_vm.last_unload_refusal or ("export_busy", ())
        if reason == "dependents":
            return S.UNLOAD_BLOCKED_BY_DEPENDENTS_TMPL.format(names="、".join(names))
        return S.UNLOAD_BLOCKED_BY_EXPORT

    def _on_unload_blocked(self) -> None:
        """(docstring は Task 1 のまま)"""
        message = self._unload_refusal_message()
        self.set_status_message(message, timeout_ms=8000)
        self._notify_blocked(message)
```

`strings.py` に:

```python
UNLOAD_BLOCKED_BY_DEPENDENTS_TMPL: Final = "派生信号 {names} が参照しているため閉じられません"
```

- [ ] **Step 5: 通ることを確認**

Run: `uv run pytest tests/gui/ -q`
Expected: PASS

- [ ] **Step 6: sabotage で honest-RED を確認（必須・結果を報告に記す）**

1. `remove_action.setEnabled(not blocked)` を外す → affordance テストのみ RED
   （バックストップのテストは緑 ＝ 2 チャネルが独立に被覆されている証明）。
2. `menu.setToolTipsVisible(True)` を外す → `toolTipsVisible()` の assert のみ RED。
3. `_notify_blocked(message)` を外す → モーダル assert のみ RED
   （ステータス assert は緑のまま）。
4. `dependents` 分岐の `_notify` を外す → `test_dependent_signal_refusal_is_announced_not_silent`
   が RED。

- [ ] **Step 7: ゲート＋コミット**

```bash
git add src/valisync/gui/viewmodels/file_browser_vm.py src/valisync/gui/views/file_browser_view.py \
        src/valisync/gui/viewmodels/app_viewmodel.py src/valisync/gui/views/main_window.py \
        src/valisync/gui/strings.py tests/gui/test_unload_export_guard.py
git commit -m "fix(gui): 閉じられない時はメニュー項目を disabled 化・無音だった派生信号拒否も通知"
```

---

## Task 3: `Session.load` の登録失敗で handle を閉じる

**Files:**
- Modify: `src/valisync/core/session.py`（`load` の `add()` 周辺・~169）
- Test: `tests/core/test_handle_release.py`

**Interfaces:**
- Consumes: Task 1 の close 規約

- [ ] **Step 1: 失敗テストを書く**

`tests/core/test_handle_release.py` に追記。**主テストは platform 非依存**にする
（`os.replace` 版は Linux で close の有無に関わらず PASS＝mutation 耐性ゼロ）。
スタブは group を捕捉し**強参照を保持したまま** assert する — そうしないと
「close したから」と「最後の参照が死んだから」を区別できない:

```python
def test_registration_failure_closes_the_handle(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """add() が raise しても handle はリークしない (CI 可視の主オラクル)。

    GUI では _on_load_error がモーダルを出す間トレースバックが handle を pin する
    ため、閉じないとダイアログ表示中ずっとファイルがロックされる。
    """
    path = tmp_path / "reg_fail.mf4"
    write_mdf4(
        path,
        [
            {
                "name": "Spd",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [1.0, 2.0],
            }
        ],
    )
    session = Session()
    captured: list[object] = []

    def _boom(group):  # type: ignore[no-untyped-def]
        captured.append(group)  # 強参照を保持 -> GC ではなく close だけを測る
        raise ValueError("unsupported file_format: 'MDF3'")

    monkeypatch.setattr(session._groups, "add", _boom)
    with pytest.raises(ValueError):
        session.load(path, confirm_expansion=None)

    handle = captured[0].handle
    assert handle is not None and handle.is_closed is True


@windows_only
def test_registration_failure_does_not_leave_the_file_locked(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """実 OS のロック解放版 (Windows のみ — POSIX の rename は open 中でも成功する)。"""
    path = tmp_path / "reg_fail2.mf4"
    write_mdf4(
        path,
        [
            {
                "name": "Spd",
                "bus_type": CAN,
                "timestamps": [0.0, 1.0],
                "values": [1.0, 2.0],
            }
        ],
    )
    session = Session()

    def _boom(_group):  # type: ignore[no-untyped-def]
        raise ValueError("unsupported file_format: 'MDF3'")

    monkeypatch.setattr(session._groups, "add", _boom)
    with pytest.raises(ValueError):
        session.load(path, confirm_expansion=None)

    victim = tmp_path / "moved2.mf4"
    os.replace(path, victim)  # 例外が出なければリークしていない
    assert victim.exists()
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/test_handle_release.py -q -rs`
Expected: `test_registration_failure_closes_the_handle` が FAIL（`is_closed is False`）。
Linux では `..._does_not_leave_the_file_locked` が skip されることを `-rs` で確認。

- [ ] **Step 3: `load` の登録を try/except で囲む**

`session.py` の `key = self._groups.add(result.signal_group)` を:

```python
        try:
            key = self._groups.add(result.signal_group)
        except Exception:
            # 登録に失敗したグループは誰も所有しない。handle を閉じないと
            # トレースバックが生かし続け、GUI のエラーダイアログ表示中ずっと
            # ファイルがロックされる。
            handle = result.signal_group.handle
            if handle is not None:
                handle.close()
            raise
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/core/ tests/test_session.py -q`
Expected: PASS

- [ ] **Step 5: sabotage で honest-RED を確認（必須・結果を報告に記す）**

`except Exception:` ブロックの `handle.close()` を一時的に外し、
`test_registration_failure_closes_the_handle` が **skip されるプラットフォームでも RED**
になることを確認してから戻す。

- [ ] **Step 6: ゲート＋コミット**

```bash
git add src/valisync/core/session.py tests/core/test_handle_release.py
git commit -m "fix(core): 登録失敗時に MDF ハンドルを閉じる (エラーダイアログ中のロック残留を解消)"
```

---

## Task 4: teardown の三軸ペーシング（バイト＋信号数＋実時間デッドライン）

**Files:**
- Modify: `src/valisync/gui/workers/teardown_service.py`
- Test: `tests/gui/test_teardown_pacing.py`（新規）

**Interfaces:**
- Produces: `TeardownService(..., byte_budget=..., signal_budget=8000, tick_deadline_s=0.008, now=time.perf_counter)`。
  `_drain` は**バイト予算・信号数予算・実時間デッドラインのいずれかに達したら中断**する。
  `now` は**注入可能**（テスト honesty の要 — 実時間で assert しないため）。

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_teardown_pacing.py`:

```python
"""ドレインは 1 ティックで予算を超えない (増分B・FU-16 の再来防止)。

バイト会計を正直にすると未展開の遅延グループは実質 0 バイトになり、330,004
シェルが 1 ティックで解放されて実測 649ms のフリーズになる。信号数の上限は
オプションではなく必須。**時間ではなく信号数で assert する** (マシン依存回避) —
デッドライン軸だけは注入した偽クロックで assert する (実時間は使わない)。
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np

from valisync.core.models import Signal, SignalGroup
from valisync.core.models.sample_source import EagerValues
from valisync.gui.workers.teardown_service import TeardownService


class _ZeroByteSource:
    """未展開の遅延ソース相当: 会計上 0 バイト."""

    is_materialized = False
    nbytes_if_materialized = 0

    def __init__(self, n: int) -> None:
        self.length = n

    def array(self) -> np.ndarray:  # pragma: no cover - 呼ばれてはいけない
        raise AssertionError("teardown must not materialize")

    def array_if_materialized(self) -> np.ndarray | None:
        # Task 5 で SampleSource に追加されるメンバ (会計の id-dedup 用)。
        # 会計は getattr フォールバックを使わず直接呼ぶので、ここに無いと
        # AttributeError で loud-fail する。
        return None


def _group_of(sigs: tuple[Signal, ...]) -> SignalGroup:
    return SignalGroup(
        signals=sigs,
        source_path=Path("/x.mf4").resolve(),
        file_format="MDF4",
        loaded_at=datetime.datetime.now(),
    )


def _lazy_group(n_signals: int, *, freeze_master: bool = True) -> SignalGroup:
    ts = np.arange(4, dtype=np.float64)
    if freeze_master:
        # 本番は Signal 構築前に master を凍結する (mdf_loader.py:487)。凍結しないと
        # Signal.__init__ (signal.py:77) が writeable な配列を信号ごとに copy するため
        # グループは master を共有せず、Task 5 の dedup テストが原理的に通らない。
        ts.flags.writeable = False
    sigs = tuple(
        Signal(
            name=f"s{i}",
            timestamps=ts,
            values_source=_ZeroByteSource(4),  # type: ignore[arg-type]
            file_format="MDF4",
            bus_type="",
            source_file="/x.mf4",
        )
        for i in range(n_signals)
    )
    return _group_of(sigs)


def _eager_group(n_signals: int, length: int) -> SignalGroup:
    """展開済み値を持つグループ (1 信号あたりの解放コストが約 3 倍の regime)。"""
    ts = np.arange(length, dtype=np.float64)
    ts.flags.writeable = False
    sigs = tuple(
        Signal(
            name=f"s{i}",
            timestamps=ts,
            values_source=EagerValues(np.arange(length, dtype=np.float64)),
            file_format="MDF4",
            bus_type="",
            source_file="/x.mf4",
        )
        for i in range(n_signals)
    )
    return _group_of(sigs)


def test_one_tick_never_frees_more_than_the_signal_budget(qtbot) -> None:  # type: ignore[no-untyped-def]
    # now を固定してデッドライン軸を無効化し、信号数軸だけを測る
    svc = TeardownService(signal_budget=100, now=lambda: 0.0)
    svc.enqueue("k", _lazy_group(1000))
    before = svc.pending_signals()
    svc._drain()  # 1 ティックぶんだけ回す
    freed = before - svc.pending_signals()
    assert freed == 100, f"1 ティックで {freed} 信号を解放した (上限 100)"


def test_drain_completes_across_ticks(qtbot) -> None:  # type: ignore[no-untyped-def]
    finished: list[str] = []
    svc = TeardownService(on_finished=finished.append, signal_budget=100)
    svc.enqueue("k", _lazy_group(1000))
    qtbot.waitUntil(lambda: finished == ["k"], timeout=5000)
    assert svc.pending_signals() == 0


def test_default_signal_budget_is_8000(qtbot) -> None:  # type: ignore[no-untyped-def]
    """count 軸の既定値 (ユーザー決定 3・ハード上限)。

    now を固定するのは必須 — 既定のまま実クロックで走らせるとデッドライン軸
    (8ms) が先に効いて 8,000 に届かず、count 軸を測れない。
    """
    svc = TeardownService(now=lambda: 0.0)
    svc.enqueue("k", _lazy_group(20000))
    before = svc.pending_signals()
    svc._drain()
    assert before - svc.pending_signals() == 8000


def test_tick_stops_at_the_deadline_with_a_fake_clock(qtbot) -> None:  # type: ignore[no-untyped-def]
    """デッドライン軸は偽クロックで assert する (実時間で assert しない)。

    spec の「時間で assert しない」制約はテストのオラクルについての制約であり、
    production 機構を時間軸にすることは禁じていない。
    """
    ticks = iter(range(10_000))
    svc = TeardownService(
        byte_budget=1 << 62,  # バイト軸を実質無効化
        signal_budget=10_000,  # 信号軸も 1 ティックで足りる大きさ
        tick_deadline_s=0.008,
        now=lambda: next(ticks) * 0.001,  # 呼ばれるたび +1ms
    )
    svc.enqueue("k", _lazy_group(10_000))
    before = svc.pending_signals()
    svc._drain()
    freed = before - svc.pending_signals()
    # 256 信号ごとに 1 回だけクロックを見るので、8 回目 (=2,048 信号) で 8ms に到達する。
    assert 0 < freed < 10_000, f"デッドラインで止まっていない (freed={freed})"


def test_one_tick_stops_over_materialized_signals_too(qtbot) -> None:  # type: ignore[no-untyped-def]
    """展開済み値 + sorted/finite/range_stat_index を持つ信号でも上限で止まる。

    シェルだけを流す他のテストは 1.6us regime しか通らない (実測: 展開済みは
    3.0us、+range_stat_index で 3.9-4.8us — 同じ予算でティックは 24-38ms になる)。
    """
    svc = TeardownService(signal_budget=100, byte_budget=1 << 62, now=lambda: 0.0)
    group = _eager_group(300, length=64)
    for sig in group.signals:
        sig.sorted_view()
        sig.finite_view()
        sig.range_stat_index()
    svc.enqueue("k", group)
    before = svc.pending_signals()
    svc._drain()
    assert before - svc.pending_signals() == 100
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_teardown_pacing.py -q`
Expected: FAIL（`signal_budget` / `tick_deadline_s` / `now` 引数が無い・
1 ティックで全部解放される）

- [ ] **Step 3: 三軸ペーシングを実装**

`teardown_service.py`（モジュール先頭に `import time`）:

```python
_BYTE_BUDGET = 64 * 1024 * 1024  # 64 MiB per tick
# 未展開の遅延シェルはバイト会計上ほぼ 0 なので、バイト予算だけでは 330k シェルが
# 1 ティックで解放され実測 649ms 固まる (FU-16 の再来)。解放コストは個数にも比例
# するため、信号数の上限を第 2 の軸として持つ。
_SIGNAL_BUDGET = 8_000  # ユーザー決定 3 (変更不可・ハード上限)
# WHY (第 3 軸): 予算はどちらもコストの proxy でしかない。1 信号の解放コストは状態で
# 1.6us (未展開シェル) → 4.8us (展開値 + sorted/finite + range_stat_index) と約 3 倍
# 動き、バイト軸は RangeStatIndex のブロック配列を数えないので補償できない。実測:
# 8,000 シェル = 13-17ms だが 8,000 展開信号 (240 サンプル) = 24ms・+RSI = 28ms、
# 1,200 サンプルでは 6,990 信号 / 64MiB で 36ms (両予算とも充足したまま)。
# frame budget と単調な唯一の軸は経過時間なので、それを実効の一次軸にする。
_TICK_DEADLINE_S = 0.008  # 半フレーム (60fps = 16.7ms)
```

`__init__` に `signal_budget: int = _SIGNAL_BUDGET` / `tick_deadline_s: float = _TICK_DEADLINE_S` /
`now: Callable[[], float] = time.perf_counter` を足し、`self._signal_budget` /
`self._deadline` / `self._now` に保持する（`now` の注入はテスト honesty の要 —
実時間で assert しないため）。

`_drain` を三軸へ:

```python
    def _drain(self) -> None:
        t0 = self._now()
        freed_bytes = 0
        freed_signals = 0
        deadline_hit = False
        while (
            self._groups
            and freed_bytes < self._budget
            and freed_signals < self._signal_budget
            and not deadline_hit
        ):
            key, sigs = self._groups[0]
            while (
                sigs
                and freed_bytes < self._budget
                and freed_signals < self._signal_budget
            ):
                sig = sigs.pop()
                self._pending_signals -= 1
                freed_signals += 1
                freed_bytes += sig.timestamps.nbytes + _materialized_value_bytes(sig)
                del sig  # 最後の強参照を落とす -> ここで配列が解放される
                # クロックは 256 信号ごとにだけ見る: 未展開シェル 1 本の解放は
                # ~1.6us なので、毎回 perf_counter を呼ぶとその自体が無視できない。
                if freed_signals & 0xFF == 0 and self._now() - t0 >= self._deadline:
                    deadline_hit = True
                    break
            if not sigs:
                self._groups.popleft()
                if self._on_finished is not None:
                    self._on_finished(key)
        if not self._groups:
            self._timer.stop()
```

（会計行 `sig.timestamps.nbytes + _materialized_value_bytes(sig)` は Task 5 で
`_retained_bytes(sig, seen)` に畳む。カウンタの更新を `pop` の直後に置くのは、
会計が raise してもキューと `pending_signals()` が乖離しないための安価な保険。)

- [ ] **Step 4: 通ることを確認 + 既存 teardown テスト全通過**

Run: `uv run pytest tests/gui/ -q`
Expected: PASS

- [ ] **Step 5: sabotage で honest-RED を確認（必須・結果を報告に記す）**

1. `freed_signals < self._signal_budget` の条件を `_drain` から一時的に外す →
   `test_one_tick_never_frees_more_than_the_signal_budget` が **FAIL**
   （1 ティックで 1000 信号すべて解放される）。
2. デッドライン条件（`deadline_hit` 周り）を一時的に外す →
   `test_tick_stops_at_the_deadline_with_a_fake_clock` が **FAIL**（freed == 10,000）。

両方を確認してから戻す。

- [ ] **Step 6: ゲート＋コミット**

```bash
git add src/valisync/gui/workers/teardown_service.py tests/gui/test_teardown_pacing.py
git commit -m "fix(gui): teardown を三軸ペーシング化 (8,000 信号/tick + 8ms デッドラインで 649ms フリーズを防ぐ)"
```

---

## Task 5: 会計の identity dedup（master の 5 万倍過大計上を是正）

**Files:**
- Modify: `src/valisync/core/models/sample_source.py`（`array_if_materialized` 追加）
- Modify: `src/valisync/gui/workers/teardown_service.py`（`_retained_bytes` / `last_tick_bytes`）
- Modify: 既存ダブル 5 個（下記 Step 3 の一覧）
- Test: `tests/gui/test_teardown_pacing.py`・`tests/gui/test_teardown_service.py`

**Interfaces:**
- Produces: `SampleSource.array_if_materialized() -> np.ndarray | None`（**展開を誘発しない**・
  未展開なら `None`）。会計はこれで id-dedup する。
- Produces: `TeardownService.last_tick_bytes`（直近ティックの accumulator・バイト軸の唯一の観測点）。

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_teardown_pacing.py` に追記。**片側しきい値は使わない** — 緩い不等式は
「正しい実装ほど永久 RED・timestamps 項を落とした誤実装でだけ緑」という反転を招く:

```python
def test_shared_master_is_counted_once_per_group(qtbot) -> None:  # type: ignore[no-untyped-def]
    """master はグループ内で identity 共有。信号ごとに数えると 5 万倍過大になる。"""
    svc = TeardownService()
    group = _lazy_group(100)
    assert len({id(s.timestamps) for s in group.signals}) == 1, (
        "fixture premise broken: master が凍結されておらず共有されていない"
    )
    m = group.signals[0].timestamps.nbytes
    svc.enqueue("k", group)
    assert svc.pending_bytes() == m  # 0 も 100*m も不合格


def test_distinct_masters_are_each_counted(qtbot) -> None:  # type: ignore[no-untyped-def]
    """CSV 形状 (writeable master => 信号ごとにコピー) では dedup が効かないこと。

    csv_loader は master を凍結せず writeable な配列を全 Signal に渡す
    (csv_loader.py:234/281) ので、Signal.__init__ が信号ごとにコピーする。
    CSV の会計は今日すでに正直 — 「CSV も dedup されていない」と後から
    直してはならない。
    """
    svc = TeardownService()
    group = _lazy_group(10, freeze_master=False)
    assert len({id(s.timestamps) for s in group.signals}) == 10, "前提が壊れている"
    m = group.signals[0].timestamps.nbytes
    svc.enqueue("k", group)
    assert svc.pending_bytes() == 10 * m


def test_materialized_value_is_added_to_the_master(qtbot) -> None:  # type: ignore[no-untyped-def]
    """共有 master + 展開済み値 1 本の合算を pin (timestamps 項の脱落を落とす)。"""
    ts = np.arange(1024, dtype=np.float64)
    ts.flags.writeable = False
    src = EagerValues(np.zeros(1024, dtype=np.float64))
    sig = Signal(
        name="s",
        timestamps=ts,
        values_source=src,
        file_format="MDF4",
        bus_type="",
        source_file="/x.mf4",
    )
    svc = TeardownService()
    svc.enqueue("k", _group_of((sig,)))
    assert svc.pending_bytes() == ts.nbytes + src.nbytes_if_materialized


def test_shared_value_array_is_counted_once(qtbot) -> None:  # type: ignore[no-untyped-def]
    """同一 EagerValues を共有する 2 信号の値配列は 1 回だけ計上される。

    array_if_materialized() を getattr フォールバックで書くと実ソースで dedup が
    無言で消えるが、master dedup テストは sig.timestamps しか見ないので検知できない。
    このテストがその穴を塞ぐ。
    """
    src = EagerValues(np.zeros(4096, dtype=np.float64))
    ts = np.arange(4096, dtype=np.float64)
    ts.flags.writeable = False
    sigs = tuple(
        Signal(
            name=f"s{i}",
            timestamps=ts,
            values_source=src,
            file_format="MDF4",
            bus_type="",
            source_file="/x.mf4",
        )
        for i in range(2)
    )
    svc = TeardownService()
    svc.enqueue("k", _group_of(sigs))
    assert svc.pending_bytes() == ts.nbytes + src.nbytes_if_materialized


def test_master_is_charged_every_tick_not_once_per_service(qtbot) -> None:  # type: ignore[no-untyped-def]
    """`seen` はティック単位 — サービス寿命にすると 2 ティック目が 0 バイトになる。

    id は生存中のオブジェクト間でのみ一意なので、記録した配列より長生きする set は
    以後の全確保をエイリアスする (実測 100% 再利用・memory
    gui_id_reuse_flake_object_recreation)。この assert は id 再利用に依存せず
    決定的に RED になる。
    """
    svc = TeardownService(signal_budget=10, byte_budget=1 << 62, now=lambda: 0.0)
    group = _lazy_group(35)  # 4 ティック必要
    m = group.signals[0].timestamps.nbytes
    svc.enqueue("k", group)
    charged: list[int] = []
    while svc.pending_signals() > 0:
        svc._drain()
        charged.append(svc.last_tick_bytes)
    assert len(charged) >= 3
    assert all(b >= m for b in charged), f"{charged} — master を計上しないティックがある"


def test_a_later_group_is_charged_in_full(qtbot) -> None:  # type: ignore[no-untyped-def]
    """A を完走ドレイン後に確保した B が 0 バイト計上にならない (id 再利用ガード)。"""
    svc = TeardownService(signal_budget=10_000, byte_budget=1 << 62, now=lambda: 0.0)
    svc.enqueue("a", _lazy_group(200))
    svc._drain()
    assert svc.pending_signals() == 0
    group_b = _lazy_group(5)
    expected = group_b.signals[0].timestamps.nbytes  # 共有 master 1 本ぶん
    svc.enqueue("b", group_b)
    svc._drain()
    assert svc.last_tick_bytes == expected
```

`tests/gui/test_teardown_service.py::test_drains_in_byte_budget_slices` のスパイに 1 行追加
（非共有ケースでは accumulator と実解放バイトが一致すべき）:

```python
    def _spy() -> None:
        before = svc.pending_bytes()
        orig()
        after = svc.pending_bytes()
        slice_bytes.append(before - after)
        assert svc.last_tick_bytes == before - after
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_teardown_pacing.py -q`

Expected: `test_shared_master_is_counted_once_per_group` が **FAIL with total == 3200
(= 100 * 32 B)**。**3200 以外、特に premise assert（`len({id(...)}) == 1`）での失敗は
fixture の凍結漏れであり、実装ではなくテスト（Task 4 の `_lazy_group`）を直すこと。**
実装後は `total == 32`。`last_tick_bytes` 系は `AttributeError` で FAIL。

- [ ] **Step 3: `array_if_materialized` を足して会計を dedup 化**

`sample_source.py` の `SampleSource` プロトコルと両実装に:

```python
    def array_if_materialized(self) -> np.ndarray | None:
        """展開済みなら値配列、未展開なら None (**展開は誘発しない**).

        nbytes_if_materialized は数値しか返さないので id-dedup ができない。
        teardown 会計が共有配列を二重計上しないために同一性が要る。
        """
```

`EagerValues` は常に `self._array`、`LazyMdfValues` は `self._cache`（未展開なら `None`）。

**`array_if_materialized` は `SampleSource` の構造的メンバ**（`isinstance(..., SampleSource)`
の使用箇所はゼロ）なので、**既存ダブルにも同じメンバを足す**。会計は**直接呼ぶ**こと —
`getattr(src, "array_if_materialized", None)` の**フォールバックは禁止**（名前がドリフト
しても実ソースで無言に dedup が消え、master dedup テストは `sig.timestamps` しか見ない
ため検知できない。`AttributeError` で loud-fail するのが正しい）:

| ダブル | 追加内容 |
|---|---|
| `tests/lazy_stubs.py:14` `CountingLazy` | `return self._cache` |
| `tests/gui/test_teardown_service.py:113` `_CountingSource` | `return None`（nbytes スパイの意味論を保つ） |
| `tests/gui/test_sample_read_error_degrade.py:31` `_FailingSource` | `return None` |
| `tests/gui/test_sample_read_error_hook.py:44` `_FailingSource` | `return None` |
| `tests/realgui/test_sample_read_error_realgui.py:49` `_FailingSource` | `return None` |
| Task 4 Step 1 の `_ZeroByteSource` | `return None`（**本 Task が自分で壊すので忘れずに** — 上のスニペットには既に入れてある） |

`teardown_service.py` の会計を、**グループ内で id を跨いで dedup** する形へ
（`_materialized_value_bytes` はここへ畳んで削除）:

```python
def _retained_bytes(sig: Signal, seen: set[int]) -> int:
    """この Signal が保持しているバイト数 (既に数えた配列は id で除外).

    master はグループ内で identity 共有されるので、信号ごとに数えると prod_demo で
    実体 0.2 MiB に対し 10,316 MiB (約 5 万倍) を計上してしまう。
    未展開信号の sig.values は絶対に読まない (読むと遅延ロードを再誘発する) —
    値は array_if_materialized() で「展開済みのときだけ」取る。
    """
    total = 0
    ts = sig.timestamps
    if id(ts) not in seen:
        seen.add(id(ts))
        total += int(ts.nbytes)
    val = sig._values_source.array_if_materialized()
    if val is not None and id(val) not in seen:
        seen.add(id(val))
        total += int(val.nbytes)
    for pair in (
        getattr(sig, "_sorted_view_cache", None),
        getattr(sig, "_finite_view_cache", None),
    ):
        if pair is None:
            continue
        for arr in pair:  # (timestamps, values) タプル
            if id(arr) not in seen:
                seen.add(id(arr))
                total += int(arr.nbytes)
    return total
```

**`seen` の寿命規約（必読・実装の自由度をここで潰す）**:
`seen` は **1 ティック単位**で作る（`_drain` の先頭で `freed_bytes`/`freed_signals` と
同じ寿命・`pending_bytes` も呼び出しごとに新規）。**`self._seen` 等でインスタンスに
持たせてはならない。** WHY: id は生存中のオブジェクト間でのみ一意で、記録した配列より
長生きする set は以後の全確保をエイリアスする（実測 100% 再利用・memory
`gui_id_reuse_flake_object_recreation`）。ティックを跨ぐと、後から enqueue された
グループの配列が直前に解放したアドレスに乗って 0 バイト計上され、**64 MiB 軸が黙って
死ぬ**（残るのは信号数軸とデッドライン軸のみ）。ティック内は安全: 会計対象の配列は全て
live な Signal が保持して自分のアドレスを占有しており、`_drain` 内で ndarray を新規確保
する経路も無い。副作用として共有 master は**ティックごとに 1 回**計上される（グループ
通算 1 回ではない）が、prod_demo で 0.2 MiB/tick＝64 MiB 予算の 0.3% に過ぎず、
**過大計上は direction-safe**（本増分が既に依拠している論法）。

**不採用案（再提案防止）**: master 分を `enqueue` 時に一括計上する案は**不採用** —
`enqueue` の O(1) 不変（`teardown_service.py:10-16` — 264k で全信号 nbytes 走査が
~320ms のフリーズだった実測）を破る。

`_drain` の会計行を `freed_bytes += _retained_bytes(sig, seen)` にし、
`t0 = self._now()` の隣で `seen: set[int] = set()` を作る。末尾（`if not self._groups:` の前）に:

```python
        # バイト軸を直接 assert できる唯一の観測点。pending_bytes は生存集合から
        # 都度再計算するため、共有配列があると _drain の会計と乖離しても差分に現れない。
        self._last_tick_bytes = freed_bytes
```

`__init__` で `self._last_tick_bytes = 0` を初期化し、`last_tick_bytes` プロパティで公開する。
`pending_bytes` も `seen` を使う形へ:

```python
    def pending_bytes(self) -> int:
        seen: set[int] = set()  # 呼び出しごとに新規 (寿命規約は _drain と同じ)
        return sum(
            _retained_bytes(s, seen) for _key, sigs in self._groups for s in sigs
        )
```

**`_range_stat_index_cache` の扱い（明記必須）**: `Signal.__slots__` にある
`_range_stat_index_cache`（`RangeStatIndex` はブロック配列 5 本）は**計上しない**。
WHY: ブロック配列は √n スケールで小さく、元の ts/vs は `finite_view` と共有されるため
二重計上になる。**ただしこれは時間問題の解決ではない** — 実測で RSI を持たせても
バイト計上は変わらないままティックが 24→36ms に増える（だから第 3 軸の
デッドラインが要る）。この 2 文をコードコメントに残すこと。

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/gui/ -q`

Expected: **上記 6 ダブルを更新する前**は `tests/gui/test_teardown_lazy.py`（2 件）・
`test_teardown_service.py::test_enqueue_is_o1_defers_byte_access_to_drain`・Task 4 の
`test_teardown_pacing.py` が `AttributeError` で FAIL する
（`test_enqueue_is_o1...` だけが `pending_signals()==0` を待つため 3s タイムアウト、
他は即 FAIL。ドレイン自体は 1 ティック 1 信号で完走し `on_finished` も発火するので
幽霊行は残らない）。**更新後に PASS**。

- [ ] **Step 5: sabotage で honest-RED を確認（必須・Task 4 Step 5 と同格・結果を報告に記す）**

1. `_retained_bytes` の id-dedup（`if id(...) not in seen`）を外す →
   `test_shared_master_is_counted_once_per_group` が **3,200 B で RED**・
   `test_shared_value_array_is_counted_once` も RED。
2. timestamps 項（`total += int(ts.nbytes)`）を落とす →
   `test_shared_master_is_counted_once_per_group` と
   `test_materialized_value_is_added_to_the_master` が RED。
   **今日のスイート（改訂前）はこの sabotage で全緑のままだったことも報告に記す。**
3. `seen` をサービス寿命（`__init__` で 1 個）に変える →
   `test_master_is_charged_every_tick_not_once_per_service` が RED。

全て確認してから戻す。

- [ ] **Step 6: ゲート＋コミット**

```bash
git add src/valisync/core/models/sample_source.py src/valisync/gui/workers/teardown_service.py \
        tests/lazy_stubs.py tests/gui/test_teardown_pacing.py tests/gui/test_teardown_service.py \
        tests/gui/test_sample_read_error_degrade.py tests/gui/test_sample_read_error_hook.py \
        tests/realgui/test_sample_read_error_realgui.py
git commit -m "fix(gui): teardown 会計を identity dedup 化 (共有 master の 5 万倍過大計上を是正)"
```

---

## Task 6: `_discard` を teardown 経路へ ＋ E-3 tripwire

> Task 1 でエクスポートガードは出荷済み。本タスクは `_discard`（キャンセル完走の
> ロールバック）の遅延解放配線のみ。

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（`_discard`・~609）
- Modify: `src/valisync/gui/viewmodels/app_viewmodel.py`（E-3 tripwire）
- Test: `tests/gui/test_discard_teardown.py`（新規）

**Interfaces:**
- Consumes: Task 1 の close 規約・`TeardownService.enqueue`

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_discard_teardown.py`（新規）:

```python
"""_discard (手遅れ完走のロールバック) の遅延解放を固定する (増分B)。

330,004 シェルの同期解放は GUI スレッドで実測 649ms。Task 1 で close は
remove_group が担うようになったが、遅延解放の配線は別途要る。
"""

from __future__ import annotations

# (実装者へ: MainWindow の組み立て・実 mf4 の用意は tests/gui/ の既存
#  MainWindow 系テストと tests/mdf4_helpers.write_mdf4 に合わせること。
#  demo_data/ は使わない — Global Constraints。)


def test_discard_hands_the_group_to_the_teardown_service(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """本命: 遅延解放が実際に起きたことを pending_signals で観測する。"""
    win, outcome, n_signals = _loaded_but_discarded_setup(qtbot, tmp_path)
    win.teardown_service._timer.stop()  # ドレインを止めて手渡しだけを見る

    win._discard_for_test(outcome)  # ← 実装者へ: 実 _discard クロージャを掴む方法は Step 3 の注記参照

    assert win.teardown_service.pending_signals() == n_signals


def test_discard_closes_the_handle(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """spec の Layer A 項目「_discard 経路でも close される」(Task 1 の close 規約が
    _discard も構造的にカバーしていることのガード)。"""
    win, outcome, _n = _loaded_but_discarded_setup(qtbot, tmp_path)
    handle = win.app_vm.session._groups.group(outcome.key).handle
    assert handle is not None and handle.is_closed is False

    win._discard_for_test(outcome)

    assert handle.is_closed is True


def test_discard_never_shows_a_releasing_row(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """UI churn が無いこと (幽霊行懸念の正直形)。

    `len(vm.files) == 1` は現行コードでも通る恒真 assert なので使わない。
    "releasing" 通知が 1 度も飛ばないことを見る — mark_released の既定値 pop が
    将来外れた場合に RED になる。
    """
    win, outcome, _n = _loaded_but_discarded_setup(qtbot, tmp_path)
    tags: list[str] = []
    win.app_vm.subscribe(tags.append)

    win._discard_for_test(outcome)
    qtbot.waitUntil(lambda: win.teardown_service.pending_signals() == 0, timeout=5000)

    assert "releasing" not in tags


def test_minted_columns_trip_the_e3_wire(tmp_path) -> None:
    """E-3 の未配線を無音にしない (m2)。

    鋳造列は enqueue(key, group)=group.signals を通らないため GUI スレッドで
    同期解放される (プロット済み列は実体化済みでバイトが重い)。配線は E-3 だが、
    鋳造が生きた瞬間に無音でペーシングを迂回しないよう loud-fail を置く。
    """
    import pytest

    app_vm, key, _handle = _loaded(tmp_path)  # tests/gui/test_unload_export_guard.py と同型
    app_vm.set_teardown(_DummyTeardown())
    column = _minted_column(f"{key}::Spd[7]")
    app_vm.session._groups._resolved_by_key.setdefault(key, {})[column.name] = column

    with pytest.raises(AssertionError, match="E-3"):
        app_vm.unload_file(key)
```

> **実装者へ**: `_discard` は `_load_file` 内のクロージャで外から掴めない。
> **プロダクションコードにテスト専用の入口を足さないこと** — 代わりに
> `win._load_file(path)` を実行して `LoadController.submit` に渡された
> `on_discard` を捕捉する（`_load_controller.submit` を monkeypatch して
> kwargs から `on_discard` を取り出すのが最小・`tests/gui/` の既存 LoadController
> 系テストに同型の捕捉があればそれを流用する）。上のスニペットの
> `_discard_for_test` はその捕捉した callable を指すプレースホルダ。
> `_minted_column` は `tests/test_session.py:236-251` の `_derived(...)` と同型。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_discard_teardown.py -q`
Expected: `test_discard_hands_the_group_to_the_teardown_service` が
`pending_signals() == 0` で FAIL（現行は戻り値を捨てている）。
`test_minted_columns_trip_the_e3_wire` は `DID NOT RAISE` で FAIL。
`test_discard_closes_the_handle` は Task 1 で既に PASS（regression lock）。

- [ ] **Step 3: `_discard` を直接 enqueue へ**

`announce` 引数案は**採らない**。WHY を残して再発明を防ぐ:
`TeardownService` は releasing 状態を一切持たない（スピナーは
`AppViewModel.unload_file` が `_releasing[key]` を書くことで出る）ため、
`enqueue` に `announce` を足しても **no-op の死んだ public API 追加**になる。

`main_window.py:609-612` の `_discard` を:

```python
        def _discard(outcome: LoadOutcome) -> None:
            # 増分B: 手遅れ完走のロールバック。Task 1 で handle は remove_group が
            # 閉じるが、シェルの解放を放置すると GUI スレッドで同期実行される
            # (330k シェルで実測 649ms)。AppViewModel は経由しない — このファイルは
            # loaded_keys に載っていないので releasing スピナー行を出してはいけない。
            # _discard は LoadController._finish (queued 接続スロット) から呼ばれる
            # = GUI スレッドなので、QTimer を持つ enqueue をここで呼んでよい。
            # なお本経路はエクスポートガードの対象外: このグループは register_loaded を
            # 通らず、エクスポートツリーの唯一のソース (app_vm.loaded_file_keys ->
            # export_csv_dialog.py:114) に載らないためエクスポート中になり得ない。
            result = session.remove_group(outcome.key, force=True)
            if result.removed_group is not None:
                self.teardown_service.enqueue(outcome.key, result.removed_group)
```

- [ ] **Step 4: E-3 tripwire を置く**

`app_viewmodel.py` の `unload_file`、`self._teardown.enqueue(...)` の直前に
（`assert` は `-O` で消えるので使わない）:

```python
            if result.removed_columns:
                # E-3: 鋳造列は enqueue(key, group)=group.signals を通らないため
                # GUI スレッドで同期解放される (プロット済み列は実体化済みでバイトが
                # 重い)。配線は E-3 の完了定義だが、鋳造が生きた瞬間に無音で
                # ペーシングを迂回しないよう loud-fail する。MainWindow._discard の
                # remove_group(force=True) も同じ配線が要る (E-3 の 2 サイト目)。
                raise AssertionError(
                    "E-3: 鋳造列は TeardownService へ渡すこと "
                    "(未配線のまま鋳造を有効化するとペーシングを迂回する)"
                )
```

- [ ] **Step 5: 通ることを確認**

Run: `uv run pytest tests/gui/ -q`
Expected: PASS

- [ ] **Step 6: sabotage で honest-RED を確認（必須・Task 4 Step 5 と同格・結果を報告に記す）**

1. `_discard` を現行の「戻り値を捨てる」形に戻す →
   `test_discard_hands_the_group_to_the_teardown_service` が
   `pending_signals() == 0` で **RED**。
2. tripwire の `raise` を外す → `test_minted_columns_trip_the_e3_wire` が **RED**
   （＝恒真でないことの実証）。

- [ ] **Step 7: ゲート＋コミット**

```bash
git add src/valisync/gui/views/main_window.py src/valisync/gui/viewmodels/app_viewmodel.py \
        tests/gui/test_discard_teardown.py
git commit -m "fix(gui): _discard を teardown 経路へ (649ms の同期解放を遅延化)・E-3 tripwire"
```

---

## Task 7: 繰越 Minor 3 件（excepthook dedup・`_closed` アトミック化・double-checked read）＋並行契約

**Files:**
- Modify: `src/valisync/gui/views/main_window.py`（excepthook）
- Modify: `src/valisync/core/loaders/mdf_handle.py`（`_closed`）
- Modify: `src/valisync/core/models/sample_source.py`（`array()`）
- Test（項目別に分割・**demo 非依存**）:
  - 項目 1（excepthook dedup）: `tests/gui/test_sample_read_error_hook.py`（既存・demo 非依存）
  - 項目 2/3 ＋ 並行契約: `tests/core/loaders/test_mdf_handle_concurrency.py`（**新規・demo 非依存**）

> **WHY 新規ファイル**: 自然な宛先に見える `tests/core/loaders/test_lazy_mdf_values.py` は
> :13-14 に module-level の demo skipif（`demo_data/quick_demo.mf4`）を持ち、`demo_data/` は
> `.gitignore` 済み・CI に生成ステップが無いため**丸ごと skip される**（同じ gate を持つ
> ファイルは 5 本）。固定ユーザー決定（`_closed` は lock の外で立て続ける）を守る唯一の
> 機構がそこに着地すると CI 執行力ゼロで main に乗る。`tests/lazy_stubs.py:1-7` が同じ罠への
> 既存対処。

- [ ] **Step 1: 失敗テストを書く**

**項目 1（excepthook dedup）** — `tests/gui/test_sample_read_error_hook.py` に追記:
同じ `signal_key` で `SampleReadError` を 2 回起こしても診断は 1 件。ラベルが固定文字列
でなく**実ファイル basename** になる（render 境界＝`graph_panel_vm.py:1656-1684` と同じ規約）。

**項目 2（`_closed` アトミック化）** — `tests/core/loaders/test_mdf_handle_concurrency.py`:

> **素朴な `threading.Barrier` 版は使わないこと。** 実 `MdfHandle` に対する barrier 同期
> 2 スレッド競合は **0/17,000 試行**（2/8 スレッド × `sys.setswitchinterval`
> 5ms/1e-5/1e-6/1e-9 × GIL 負荷 spinner 有無）で二重 close を再現できなかった
> （Windows の GIL 引き渡しはタイマー付き condvar 待ちで粒度が粗く、~4 バイトコードの
> check-and-set 窓に落ちない）。**決定的インターリーブ注入**へ差し替える。

```python
class _InterleavedHandle(MdfHandle):
    """基底 __slots__ の記述子を property で shadow し、`_closed` の
    「読み」と「書き」の間に決定的な引き渡し点を作る。

    罠 (a): yield は基底スロットを **読んだ後** に置く。先頭で yield すると
            現行の壊れたコードでも calls == 1 になり false-green (実測確認済み)。
    罠 (b): 引き渡しは **有界待ち** にする。素の join() だと修正後の実装が
            デッドロックしてテストがハングする。
    """

    def __init__(self, mdf, gate, resumed) -> None:  # type: ignore[no-untyped-def]
        super().__init__(mdf)
        self._gate = gate
        self._resumed = resumed
        self._yielded = False

    @property
    def _closed(self) -> bool:  # type: ignore[override]
        value = MdfHandle._closed.__get__(self)  # ← 先に読む
        if not self._yielded:
            self._yielded = True
            self._gate.set()
            self._resumed.wait(0.5)
        return value

    @_closed.setter
    def _closed(self, value: bool) -> None:
        MdfHandle._closed.__set__(self, value)


def test_concurrent_close_calls_mdf_close_once() -> None:
    """production では二重 close は無害 (asammdf 8.8.22 の MDF4.close() 自身が
    `if self._closed: return` を持ち、MdfHandle.close() は self.lock 下で呼ぶ)。
    **これは固定ユーザー決定が要求する内部契約の pin であってバグ回帰テストではない** —
    将来「無害だから」と削除しないこと。
    """
    spy = _CloseSpy()
    gate, resumed = threading.Event(), threading.Event()
    handle = _InterleavedHandle(spy, gate, resumed)

    a = threading.Thread(target=handle.close)
    a.start()
    assert gate.wait(1.0), "A が _closed を読む前に止まった (setup 失敗)"
    b = threading.Thread(target=handle.close)
    b.start()
    time.sleep(0.05)  # 壊れた実装なら B がここで mdf.close() まで走り抜ける
    resumed.set()
    a.join(timeout=0.5)
    b.join(timeout=0.5)

    assert not a.is_alive() and not b.is_alive(), (
        "デッドラック — check-and-set を handle.lock 下に入れていないか "
        "(専用の小さい lock を使うこと)"
    )
    assert spy.calls == 1, f"mdf.close() が {spy.calls} 回"
```

**項目 3（double-checked read）** — 同ファイルに 2 本:

```python
def test_concurrent_first_reads_select_once() -> None:
    """2 スレッドが同時に初回 array() へ到達しても select はちょうど 1 回。

    lock 内の再チェック (double-checked の "second check") を消すと 2 回になる。
    既存 `assert src.array() is got` は単一スレッドなので再チェックを消しても通り、
    `test_lazy_reads_are_serialized_by_handle_lock` は 8 個の別インスタンスなので
    同一インスタンスの二重初期化に盲目 (しかも同ファイルは CI で skip)。
    """
    ...  # フェイク handle/mdf + threading.Barrier(2)。select 回数 == 1 かつ
         # 2 スレッドの戻り値が `is` 同一であること。


def test_cache_hit_takes_no_lock() -> None:
    """キャッシュヒットは handle.lock を取らない (タイミング assert は使わない)。

    MdfHandle.__slots__ に "lock" があるので、取得回数を数えるラッパへ差し替えられる。
    """
    ...  # 初回 array() で acquires == 1 → カウンタを 0 に戻す → 2 回目で acquires == 0
```

**並行契約（spec のテスト方針「並行」項目・今日通るので lock）** — 同ファイルに 1 本:

```python
def test_close_during_in_flight_reads_never_crashes(tmp_path) -> None:
    """close() は mdf.close() を handle.lock 下で呼ぶので in-flight select を中断しない。

    待機中の reader は is_closed を lock 内で見て SampleReadError。Task 7 が array() の
    lock 前にキャッシュ読みと closed 先行 bail を足すため、**lock 内の is_closed 判定まで
    一緒に外へ出す TOCTOU** をこのテストが塞ぐ。実 mf4 (write_mdf4 + tmp_path・
    demo_data は使わない) の 40 チャンネルに対し 40 スレッドで未キャッシュ read を
    走らせつつ close → 完了 or SampleReadError のみ / プロセス生存 /
    close 後の新規 read は SampleReadError。
    """
```

> sabotage 注記（Step 5 で実施）: `is_closed` チェックを `with self._handle.lock:` の
> **上だけ**に動かす（＝lock 内の判定を消す）、または `mdf.close()` を lock の外へ出すと
> このテストが RED になることを確認し**結果を報告に記す**。RED にできないなら
> 装飾的なのでその旨を報告する。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_mdf_handle_concurrency.py tests/gui/test_sample_read_error_hook.py -q`
Expected: 新規 4 件のうち excepthook dedup / `_closed` / double-checked の 3 件が FAIL、
並行契約 1 件は **今日から PASS**（regression lock として置く）。

- [ ] **Step 3: 実装**

1. **excepthook**: `GraphPanelVM._read_error_reported` と同型の dedup セット＋
   `Path(source_file).name` をラベルに。
2. **`MdfHandle._closed`**: `threading.Lock` 下の check-and-set にする**が、フラグを立てる
   位置は lock の外のまま**（Global Constraints の理由）。
   ※ ここで使うのは **close 専用の小さい lock**で、読み直列化用の `handle.lock` とは別物。
   同じ lock を使うと in-flight read を待って GUI が固まる（かつ上のテストがデッドロックで
   落ちる）。
3. **`LazyMdfValues.array()`** を**省略記号のない完全形**へ（**順序厳守**）:

```python
        cached = self._cache
        if cached is not None:
            return cached  # ヒットは lock 不要 (代入は 1 回だけ・GIL 下で atomic)
        if self._handle.is_closed:
            # 先行 bail: close() の GUI 最悪待ちを「残り全列のループ」から
            # 「in-flight select 1 本」に縮める (belt-and-braces)。
            raise SampleReadError(
                f"信号 '{self._name}' のファイルは既に閉じられています"
            )
        with self._handle.lock:
            if self._cache is not None:  # ← 削除禁止 (double-checked の "second check")
                return self._cache
            if self._handle.is_closed:  # ← lock 内判定も **維持** (外へ出すと TOCTOU)
                raise SampleReadError(
                    f"信号 '{self._name}' のファイルは既に閉じられています"
                )
            ...  # 以降は現行のまま (select → LD-14 selector → _freeze → キャッシュ)
```

- [ ] **Step 4: 通ることを確認**

Run: `uv run pytest tests/core/loaders/test_mdf_handle_concurrency.py tests/gui/test_sample_read_error_hook.py -q`
→ その後 `uv run pytest tests/core/ tests/gui/ -q`
Expected: PASS

- [ ] **Step 5: sabotage で honest-RED を確認（必須・結果を報告に記す）**

1. check-and-set を close 専用 lock の外へ戻す → `test_concurrent_close_calls_mdf_close_once` が RED。
2. lock 内の再チェック（`if self._cache is not None`）を削る →
   `test_concurrent_first_reads_select_once` が select 2 回で RED。
3. lock 内の `is_closed` 判定を削る（先行 bail だけ残す）→
   `test_close_during_in_flight_reads_never_crashes` が RED。

- [ ] **Step 6: ゲート＋コミット**

```bash
git add src/valisync/gui/views/main_window.py src/valisync/core/loaders/mdf_handle.py \
        src/valisync/core/models/sample_source.py tests/
git commit -m "fix: 繰越 Minor 3 件 (excepthook dedup・_closed アトミック化・キャッシュヒットの lock 回避)＋並行契約 lock"
```

---

## Task 8: ①gate realgui ＋ 実測（受け入れ）

**Files:**
- Create: `tests/realgui/test_unload_releases_file_realclick.py`
- Modify: `scripts/measure_lazy_footprint.py`

- [ ] **Step 1: realgui テストを書く（5 段のレシピ・対照 assert 必須）**

> **各 assert は「ロードが実は失敗していた」「クリックが no-op だった」のどちらでも
> RED になること** — 対照 assert 無しの単発 `os.remove` は恒真。
> `FileBrowserVM.unload(index)` は範囲外 index を**無言の no-op** にし、実経路は確認モーダルを
> 挟むので、ロード未完了／メニュー項目が無い／ダイアログのボタンを取りこぼした、の
> いずれでもクリックは無音で通り、ファイルはロックされていないので `os.remove` が成功して
> PASS してしまう。

0. **必ずコピーで操作する**: `shutil.copy2(_PROD_MF4, tmp_path / "lock_target.mf4")`
   （または `tests/mdf4_helpers` で生成）。**`demo_data/prod_demo.mf4` 本体を削除してはならない**
   （gitignore された 1.36GB のデモ資産で `tests/realgui/test_lazy_load_realclick.py:46` 等が依存）。
1. **クリック前の対照 assert**:
   `qtbot.waitUntil(lambda: bool(window.app_vm.loaded_file_keys), timeout=_LOAD_TIMEOUT_MS)` と
   FileBrowser に行がある assert（`tests/realgui/test_lazy_load_realclick.py:191-199` と同型）
   ＝クリックが no-op でないことの保証。加えて
   `with pytest.raises(PermissionError): os.remove(path)` で「今ハンドルが開いている」ことを実測。
2. **`MDF.__del__` との弁別**: unload クリック**前**に teardown タイマーを止める
   （`window.teardown_service._timer.stop()` — `tests/realgui/test_close_release_spinner.py:94` の
   既存パターン）、クリック後に `pending_signals() > 0` を assert。ドレインを止めた状態では
   ロック解放の経路は `Session.remove_group` からの明示 close しか無いので、**Task 1 の close を
   消すとファイルサイズに依らず RED になる**。これを honest-RED/sabotage として報告に記す。
3. **経路全体を実クリックで通す**: 行の右クリック → 「ファイルを閉じる」 →
   確認ダイアログの「はい」を実クリック。**ダイアログが実際に出たことを assert**
   （出ないなら setup 失敗として FAIL — 取りこぼしクリックも無言 no-op）。
4. **事後 assert**: `os.remove(path)` が成功し、`app_vm.loaded_file_keys` からキーが消えている。
   最後にタイマーを再開しドレイン完了まで待つ。
5. **エクスポートガードの脚は File ドックを実クリックでフロートさせてから行う。**
   `threading.Event` でブロックする export callable を submit して in-flight を維持し
   （setup 前提として `ctrl.is_busy() is True` と `overlay.isHidden() is False` を assert）、
   フロート窓上の行へ実右クリック → メニューが**出ること**を確認 →
   「ファイルを閉じる」が **disabled** であることを確認（Task 2 の affordance）→
   さらにプログラム経路で `file_browser_vm.unload(0)` を叩き
   (a) 拒否メッセージが表示される・(b) `handle.is_closed is False` を assert。
   最後に Event を解放し、エクスポート完了後に**同じ実クリックで unload が成功する**ことまで
   確認する（「常に拒否するだけ」の退化実装を落とす）。

   **WHY（この構成でなければ恒真になる）**: `BusyOverlay(self)` は MainWindow の子で
   `cover()` が `parent.rect()`・`show()` が `raise_()`・`WA_TransparentForMouseEvents` は
   src/ のどこでも未設定・`submit` がエクスポート全期間 `busy.show()`。よって**ドッキング
   状態の行への実右クリックは全画面オーバーレイに当たり** `customContextMenuRequested` が
   発火しない（`tests/realgui/test_fu19_overlay_zorder.py:123-134` が「overlay が最前面
   ヒットターゲット」を実機で実証済み）。しかも MainWindow は `contextMenuEvent` を override
   せず `createPopupMenu` も既定なので、右クリックは QMainWindow の**ドック切替メニュー**を
   開く — 「メニューが出ない」を assert すると逆向きに誤誘導される。ガードのコードが 1 行も
   無くても「メニューが出ない／グループが残る」は成立するため、**フロートしたドックだけが
   ガードを原因と特定できる唯一の実入力構成**（実クリックでのフロート化は
   `tests/realgui/test_hit_targets.py:216-226` /
   `test_collapsible_docks_realclick.py:572-584` に前例あり）。
   `(c) グループが残っている` 単独では使わない（オーバーレイ遮断でも成立するため）。

   実 quick_demo のエクスポートはミリ秒で終わるため、**ブロックする export callable を
   注入しないと `is_busy()` が既に False で「拒否」assert が空虚に通る**。

共有 `tests/realgui/_realgui_input` を使い、**実マウスドラッグは使わない**。

- [ ] **Step 2: 実行して実機 pass を確認**

Run: `uv run pytest --realgui tests/realgui/test_unload_releases_file_realclick.py -q`
Expected: PASS

- [ ] **Step 3: ドレインのフリーズを実測（**2 入力必須**）**

`scripts/measure_lazy_footprint.py` に「ロード → unload → ドレイン完了までの**最大ティック
時間**」を出す段を足し、**次の 2 入力の両方**で実行する:

- **(a) prod_demo をロード → そのまま unload → 最大ティック**
- **(b) prod_demo をロード → 8,000 リーフ以上を実際に展開**（エクスポート、またはプロット＋
  範囲統計で `range_stat_index` まで作る）→ **unload → 最大ティック**

**WHY 2 入力必須**: ロード時に値は展開されない（増分A の遅延契約）ので (a) の入力は
全信号が未展開シェル＝1.6µs regime のみ。実測 13-17ms で「~16ms 前後」を満たすため、
**単一入力だと予算が『正しい』ことを構造的に証明してしまう**（展開済み信号は両予算を
充足したまま 24-38ms）。

**受け入れ**: 両入力とも最大ティックが **`_TICK_DEADLINE_S` + 1 信号ぶんの粒度**
（実質 ~8-12ms）に収まること。数値を**両方とも**報告と PR 本文に記録する。

> **【実測により supersede — 2026-07-29】** この帯の定義（`デッドライン + 粒度`）は
> 「1 信号の解放は安い」という前提に立っていたが、実測がそれを反証した。粒度 1 で
> 全数計測すると prod_demo 264,004 本のうち**1 本だけ 5.8ms** かかる解放があり
> （残り全て ≤0.6ms・p99 10µs・gc=0 のヒープ返却ストール・入力 (a) には非存在）、
> ペーシングは解放と解放の**あいだ**でしか止まれないため、
> **最大ティック = デッドライン + 最大単発解放 ≈ 14ms** が粒度非依存の構造的な床になる。
> 正しい帯の定義は **`デッドライン + 最大単発解放`**。
>
> **確定した実測値**（Task 9・`_CLOCK_CHECK_EVERY = 32`・各 5 回）:
> - (a) ロードのみ **8.1-8.2ms**（旧 8.7-8.9ms）— 帯内
> - (b) 8,004 リーフ展開 **10.3-14.2ms**（旧 11.2-16.8ms）— 旧帯は 4/5 で充足・新帯（≈14ms）で充足
>
> **1 フレーム（16.7ms）超えのティックは 0 件**（旧ベースラインは 16.8ms で到達）。
> 元の 649ms フリーズから約 46 倍。**バイト予算を絞ってもこの床は下がらない**
> （バイト軸はティックをデッドラインより早く終わらせることしかできない）。
> `_TICK_DEADLINE_S` を下げれば帯には入るが、ストールは消えず**無効になった旧定義に
> 数字を合わせるだけ**なので採らない。緩和は別機構（大配列の個別 `del` で巨大 decommit
> を分割）で、増分B のスコープ外＝follow-up。
>
> **CI の限界**: この床は prod_demo に対する手動スクリプトでしか観測できない。
> テストが pin するのは**定数**であって**その効果**ではない。

- [ ] **Step 4: フルゲート＋コミット**

Run: `uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/`

```bash
git add tests/realgui/test_unload_releases_file_realclick.py scripts/measure_lazy_footprint.py
git commit -m "test(gui): 増分B の ①gate realgui ＋ドレインのティック時間実測 (未展開/展開済みの 2 入力)"
```

---

## Self-Review（プラン著者チェック）

- **Spec のテスト方針 5 系統への写像**（機能項目だけでなく**テスト方針項目**へ写す —
  改訂前は機能側だけを写していたため「並行」「多重 unload」「`_discard` の close」の
  3 項目が無言で消えていた）:

  | spec テスト方針 | 本プランでの担い手 |
  |---|---|
  | **Layer A**（ロック解放 gc 無し／多重 unload／`_discard` でも close／登録失敗のリーク） | Task 1 Step 1（`@windows_only` の rename 2 本＋platform 非依存の `is_closed`/close 回数／`test_remove_group_twice_raises` で**実挙動を pin**＝spec 文言は「冪等」から訂正）・Task 6 Step 1（`test_discard_closes_the_handle`）・Task 3 |
  | **ペーシング**（1 ティックが 8,000 信号を超えない・信号数で assert） | Task 4 Step 1（5 本・sabotage 2 種）。デッドライン軸は**偽クロック**で assert（実時間は使わない） |
  | **会計**（master の identity dedup） | Task 5 Step 1（両側の厳密 pin 3 本＋実ソース dedup 1 本＋per-tick バイト 2 本・sabotage 3 種） |
  | **並行**（close と in-flight read で native クラッシュせず `SampleReadError`／キャッシュヒットは lock 非取得） | Task 7 Step 1（`test_close_during_in_flight_reads_never_crashes`・`test_cache_hit_takes_no_lock`・`test_concurrent_first_reads_select_once`） |
  | **①gate realgui** | Task 8 Step 1（5 段のレシピ・対照 assert・`MDF.__del__` との弁別・フロートドック） |

- **機能項目の写像**: close の `remove_group` 配置＝Task 1／エクスポートガード（VM チョーク
  ポイント＋affordance）＝Task 1/2／登録失敗のリーク＝Task 3／三軸ペーシング＝Task 4／
  会計の identity dedup＝Task 5／`_discard` と E-3 tripwire＝Task 6／繰越 Minor 3 件＝Task 7／
  ①gate と実測＝Task 8。
- **意図的にプラン外**: `RemovalResult.removed_columns` の**配線**（E-3 の完了定義。ただし
  ペーシング契約の穴は Task 6 の tripwire で無音化を防ぐ）・`MainWindow.closeEvent` での
  一括 close（Session 列挙 API が要る・YAGNI）・MDF3 が開けない defect（ユーザー決定 4 で
  follow-up）・`_range_stat_index_cache` のバイト計上（Task 5 Step 3 に WHY を明記した上で
  非計上）。
- **CI 執行力の点検**: `os.replace`/`os.remove` オラクルは全て `@windows_only`。
  Task 1/3/7 は**それぞれ platform 非依存の主オラクル**を持つ（`is_closed`・close 回数・
  決定的インターリーブ）。新規テストは `demo_data/` に一切依存しない。
- **`_discard` の被覆に関する注意**: **Task 8 Step 3 の実測は unload 経路のみで `_discard` を
  通らない** — Task 6 の遅延化は `test_discard_hands_the_group_to_the_teardown_service`
  （＋その sabotage）が唯一の被覆。
- **型整合**: `MdfHandle.close()/is_closed`・`SampleSource.array_if_materialized()`・
  `TeardownService(signal_budget=, tick_deadline_s=, now=)`・`TeardownService.last_tick_bytes`・
  `ExportController.is_busy()`・`AppViewModel.set_busy_predicate()/is_busy()/last_unload_refusal`・
  `FileBrowserVM.is_unload_blocked()` は全 Task で一貫。
- **Placeholder**: Task 6 Step 1 の `_discard` 捕捉（クロージャゆえ実 API を読んでから書く・
  **production にテスト専用入口を足さないこと**）と Task 7 Step 1 の項目 3 の 2 本のみ。
  それ以外は実 API 検証済みの具体コードつき。

> **実装上の注意**: sabotage ステップは **Task 1（3 種）・Task 2（4 種）・Task 3（1 種）・
> Task 4（2 種）・Task 5（3 種）・Task 6（2 種）・Task 7（3 種）・Task 8（close 削除）** の
> 全てが**必須**であり、結果を報告に記す。この増分は「実装が効いていることを証明できない
> テスト」を 6 回踏んだブランチの続きなので、**証明できないなら実装が効いていない**と扱う。
