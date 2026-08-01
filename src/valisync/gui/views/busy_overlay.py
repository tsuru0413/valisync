"""BusyOverlay — busy indicator shown during loads and exports (Task 9.1 / E-4b).

A message label, a centred QProgressBar, an ETA line, and a cancel button
(``cancel_requested`` is emitted on click; routing the click to the operations
that are actually running is the caller's job — see
``MainWindow._cancel_busy_operations``). Starts hidden.

**所有権 (E-4b・spec §5.5-2)**: この 1 インスタンスを ``LoadController`` (件数
ベースで表示) と ``ExportController`` (旧: 無条件 hide) が共有しており、相互
ガードが無かった — ロードの完了がエクスポートの overlay を消していた。
``acquire``/``release`` の参照カウントを入れ、**最後の 1 人が返したときだけ**
隠す。バーは既定で不確定 (``setRange(0, 0)``) のままで、``set_progress`` が
呼ばれたブロック進捗のあいだだけ determinate になる。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, cast

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from valisync.gui import strings as S
from valisync.gui.formatting import format_duration


class BusyOverlay(QWidget):
    """Busy overlay with reference-counted ownership, hidden until acquired."""

    cancel_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._label = QLabel("読み込み中…", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progress_bar = QProgressBar(self)
        # range (0, 0) makes the bar indeterminate (no percentage).
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)

        # 残り時間の行。不確定のあいだは行そのものを出さない — 「残り時間: --」を
        # 常時置くと、ロード (進捗を出さない) でも空欄がちらついて意味を失う。
        self._eta = QLabel("", self)
        self._eta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._eta.setVisible(False)

        self.cancel_button = QPushButton("キャンセル", self)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._eta, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignCenter)

        self.hide()

        # FU-02: 表示中に親が resize されると cover() が stale になり、透過
        # overlay のラベル/キャンセルが旧矩形の中心へズレて届きにくくなる。
        # 親の Resize を購読して追従する (親側の変更なしで自己完結)。
        if parent is not None:
            parent.installEventFilter(self)

        # 所有権 (spec §5.5-2)。dict は挿入順 = 取得順で、**最後に取った所有者の
        # 文言** を出す。キーを id() にするのは、所有者 (controller) を hashable と
        # 仮定しないため。値側に所有者そのものを持つので、id の再利用は起きない
        # (生存参照を握っているあいだ id は再利用されない)。
        self._owners: dict[int, tuple[object, str]] = {}
        self._clock = clock
        self._progress_owner: object | None = None
        self._progress_started = 0.0
        # I2: 進捗の外挿は「最初に観測した done」を起点にする (0 でなく)。
        # prod の最初のティックは done=1 (csv_exporter の `tick()` は加算後に
        # 呼ぶため done=0 は一度も来ない) — 起点を 0 で固定すると
        # `completed = done - 0` が最初のティックから 1 以上になり、かつ
        # elapsed もほぼ 0 なので「残り時間: 約 0 秒」と嘘をつく。
        self._progress_base = 0
        # M6: cancel_active が「二重押しを止める」ために外から無効化した後、
        # 無関係な acquire (別の load/export の開始・進捗更新) が無条件に
        # 再有効化してしまうと二重押し防止が意味を失う。set_cancel_enabled の
        # 呼び出し履歴をここに憶えて acquire がそれを尊重する。
        self._cancel_locked = False

    # ── 所有権 ────────────────────────────────────────────────────────────────

    def acquire(self, owner: object, *, message: str) -> None:
        """*owner* の名義で overlay を出す (同じ owner の再取得は文言更新)。"""
        self._owners.pop(id(owner), None)  # 再取得は最新へ (文言の最終決定者)
        self._owners[id(owner)] = (owner, message)
        self._label.setText(message)
        # M6: 中止処理中 (set_cancel_enabled(False) 済み) に無関係な acquire
        # (例: 別の load が始まる・進捗が別 owner から再取得される) が来ても、
        # ボタンを無条件に生き返らせない。ロックの解除は _reset_progress
        # (= 操作が実際に終わった時) だけの役目。
        if not self._cancel_locked:
            self.cancel_button.setEnabled(True)
        self.show()

    def release(self, owner: object) -> None:
        """*owner* の名義を返す。**最後の 1 人が返したときだけ** 隠す。"""
        if self._owners.pop(id(owner), None) is None:
            return  # 非所有者の解放は no-op (遅れて届いた完了で他人を消さない)
        if self._progress_owner is owner:
            # 進捗の持ち主だけが抜けた場合も不確定へ戻す — 戻さないと残った
            # 所有者 (ロード) の overlay が他人の「12 分の 3」で固まる。
            self._reset_progress()
        if self._owners:
            self._label.setText(next(reversed(self._owners.values()))[1])
            return
        # 最後の 1 人。次の操作が前回の determinate / disabled を引き継がないよう
        # 完全に初期状態へ戻してから隠す。
        self._reset_progress()
        self.hide()

    def owner_count(self) -> int:
        """現在この overlay を保持している所有者の数 (test-facing)."""
        return len(self._owners)

    # ── 進捗 / ETA ────────────────────────────────────────────────────────────

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
            # I2: prod の最初のティックは done=1 (csv_exporter.tick は加算後に
            # 呼ぶ)。起点をここへ固定し、外挿は「この owner になってから進んだ
            # 分」だけを見る。
            self._progress_base = int(done)
        self.progress_bar.setRange(0, int(total))
        self.progress_bar.setValue(int(done))
        self._eta.setText(self._eta_text_for(int(done), int(total)))
        self._eta.setVisible(True)

    def eta_text(self) -> str:
        """現在の ETA 表示 (test-facing)."""
        return self._eta.text()

    def set_cancel_enabled(self, enabled: bool) -> None:
        """キャンセル要求が受理された後、二重押しを防ぐために落とす。"""
        # M6: False の間は `acquire` に無条件の再有効化をさせない。True に
        # 戻すのはここか _reset_progress (操作が実際に終わった時) だけ。
        self._cancel_locked = not enabled
        self.cancel_button.setEnabled(enabled)

    def _eta_text_for(self, done: int, total: int) -> str:
        # I2: 起点 (`_progress_base` = この owner で最初に観測した done) から
        # まだ 1 単位も進んでいなければ外挿できない。**0 除算ガードそのもの**
        # ("残り 0 秒" と嘘をつかない) — `done <= 0` だけを見ていた旧実装は、
        # prod の最初のティック (done=1) をすり抜けて elapsed=0 のまま外挿し
        # 「残り時間: 約 0 秒」を出していた。
        completed = done - self._progress_base
        if completed <= 0:
            return S.BUSY_ETA_MEASURING
        remaining = total - done
        # 進捗の単位は **等重でない** (csv_exporter の `n_units` コメント):
        # prod 形は「時刻 1 + ブロック 8,253 + マージ 2 = 8,256 単位」で、末尾の
        # マージ 2 単位は単位数では 0.024% しかないのに、その 2 単位で ~10 GB の
        # 全列を 2 回フル読み書きする。残りが全体の 1% を切ったら、その残りは
        # 構造的にマージ段でしかありえない = 単位あたり等重の仮定が崩れており、
        # 線形外挿は「残り 約 0 秒」と言いながら数分回る嘘になる。数字を引っ込め、
        # 段が何本あるか (呼び出し側は知らない) に依存しない表示にする。
        # 下限の 1 は「最終単位は必ずマージ段」(merge_stage_count >= 1) の構造。
        if remaining <= max(1, total // 100):
            return S.BUSY_ETA_FINISHING
        elapsed = self._clock() - self._progress_started
        return S.BUSY_ETA_TMPL.format(
            eta=format_duration(elapsed * remaining / completed)
        )

    def _reset_progress(self) -> None:
        """不確定へ戻す (次のロードが determinate のまま固着しないように)。"""
        self._progress_owner = None
        self._progress_base = 0
        self.progress_bar.setRange(0, 0)
        self._eta.setText("")
        self._eta.setVisible(False)
        self.cancel_button.setEnabled(True)
        self._cancel_locked = False  # M6: 操作が終わったのでロックも解除する

    # ── 既存の表示 API (直呼び経路・realgui が掴んでいる) ──────────────────────

    def set_message(self, text: str) -> None:
        """Show *text* as the load description (FB-04 label)."""
        self._label.setText(text)

    def message(self) -> str:
        """Current label text (test-facing)."""
        return self._label.text()

    def is_indeterminate(self) -> bool:
        """Return True when the progress bar shows an indeterminate animation."""
        return self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0

    def cover(self) -> None:
        """Resize to fill the parent (so it overlays the busy area)."""
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())

    def show(self) -> None:
        """Show the overlay, covering the parent and raising it above siblings."""
        self.cover()
        super().show()
        # FU-19: central_stack/ドックは overlay より後に生成され Qt 兄弟 z-order で
        # 上に積まれる。表示のたび最前面へ持ち上げないと不透明なプロット背景に隠れる。
        self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # 親の resize へ追従 (可視時のみ — 非表示時は show() が cover する)。
        # False を返しイベントは消費しない (親の通常の resize 処理を妨げない)。
        # filter は親にのみ install しているため watched は常に親。
        if event.type() == QEvent.Type.Resize and self.isVisible():
            self.cover()
        return False


# ── controller から overlay を掴む口 (所有権 API と旧 protocol の橋) ────────────
#
# production の `busy` は常に `BusyOverlay` だが、`LoadController.submit(busy=)` /
# `ExportController.submit(busy=)` は歴史的に「`set_message`/`show`/`hide` だけを
# 話す最小スタブ」も受け取れる契約で走ってきた (tests/gui/test_export_worker.py の
# duck-typed fake が今もその形)。controller から所有権 API を直接呼ぶと、その
# スタブでは AttributeError で submit ごと死ぬ。落とし所をここ 1 か所に閉じ込め、
# controller 側は所有権だけを語る。**実 overlay で所有権が本当に効いていること**
# は tests/gui/test_busy_ownership_progress.py が実 controller 2 本同時で固定して
# いるので、この分岐が実経路の所有権をすり抜けることはない。


def acquire_busy(busy: object, owner: object, message: str) -> None:
    """*owner* 名義で *busy* を出す (所有権を解さない相手なら旧 protocol へ)。"""
    # M7: production の `busy` は常に BusyOverlay — else 分岐は
    # tests/gui/test_export_worker.py の duck-typed fake **専用** (上のモジュール
    # コメント参照)。ここに `assert isinstance(busy, BusyOverlay)` は入れない:
    # それをやると else 分岐そのものが到達不能になり、あの fake を使うテストが
    # 「所有権を解さない相手も受ける」という本橋の存在理由ごと壊れる。以下 4 関数
    # 共通の契約。
    if isinstance(busy, BusyOverlay):
        busy.acquire(owner, message=message)
        return
    legacy = cast(Any, busy)
    legacy.set_message(message)
    legacy.show()


def release_busy(busy: object, owner: object) -> None:
    """*owner* 名義を返す (所有権を解さない相手なら旧 protocol へ)。"""
    if isinstance(busy, BusyOverlay):
        busy.release(owner)
        return
    cast(Any, busy).hide()


def set_busy_progress(busy: object, owner: object, done: int, total: int) -> None:
    """*owner* 名義の進捗を反映する (所有権を解さない相手では no-op)。"""
    if isinstance(busy, BusyOverlay):
        busy.set_progress(owner, done, total)


def set_busy_cancel_enabled(busy: object, enabled: bool) -> None:
    """キャンセルボタンの有効/無効 (所有権を解さない相手では no-op)。"""
    if isinstance(busy, BusyOverlay):
        busy.set_cancel_enabled(enabled)
