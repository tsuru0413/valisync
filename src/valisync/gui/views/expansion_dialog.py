"""展開列数が上限を超えるチャンネルの展開/スキップを選ぶモーダル (LD-14).

per-channel でチェックし、OK で「展開する」インデックス集合を返す。初期状態は
全未チェック (=全スキップ) — ガードの主旨が慎重側のため。GUI スレッドで呼ぶ
前提の純 UI で、ワーカースレッドからの起動は ExpansionConfirmer が担う。
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from valisync.core.loaders.mdf_loader import EXPANSION_COLUMN_LIMIT, ExpansionRequest
from valisync.gui import strings as S

# FU-01: 画面内クランプ時にタイトルバー/タスクバーぶん残す余白 (px)。
# WM はモーダルの過大な高さをクランプしない (実測: 全高1940px > 画面816px で
# OK/Cancel が画面外) ため、ダイアログ側で availableGeometry 基準に収める。
_SCREEN_MARGIN = 80


def _clamped_size(hint: QSize, cap: int, vsb_w: int) -> QSize | None:
    """hint が cap に収まるなら None (resize 不要)、超えるならクランプ後サイズ。

    通常のデスクトップ画面では QScrollArea.sizeHint() が ~36x24 文字セルで
    bound されるためこの分岐は発火しない (スクロール化だけで画面内に収まる)。
    bound はフォント/スケール依存のため、大フォント・低解像度環境で
    bound > 画面高になったときの防御層として残す (Task 2 実測で判明)。
    幅は縦スクロールバーぶん広げ、ラベルの水平クリップを防ぐ。
    cap は正値を前提とする (負値でも QSize は返るが、呼び出し側の resize が
    Qt のレイアウト最小サイズでクランプされ優雅に劣化する — 実測確認済み)。
    """
    if hint.height() <= cap:
        return None
    return QSize(hint.width() + vsb_w, cap)


class ExpansionDialog(QDialog):
    def __init__(
        self, request: ExpansionRequest, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("大きな信号の展開確認")
        self.result_indices: set[int] = set()
        self._request = request

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(S.EXPANSION_OVER_LIMIT_TMPL.format(limit=EXPANSION_COLUMN_LIMIT))
        )

        self._checks: list[QCheckBox] = []
        checks_host = QWidget()
        checks_lay = QVBoxLayout(checks_host)
        checks_lay.setContentsMargins(0, 0, 0, 0)
        for ch in request.channels:
            cb = QCheckBox(f"{ch.name} — {ch.column_count} 列")
            cb.toggled.connect(self._update_total)
            checks_lay.addWidget(cb)
            self._checks.append(cb)
        checks_lay.addStretch(1)  # viewport が余るときチェック行を上詰めに保つ
        # FU-01: チェック列だけをスクロール領域へ。ヘッダ/合計/一括ボタン/OK は
        # スクロール外の常時可視。AdjustToContents で sizeHint が内容に追従する
        # (Qt は ~36x24 文字セルで bound するため大量チャンネルでも有界)。
        # 少数チャンネルでは従来同等のコンパクト表示になる。
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents
        )
        self._scroll.setWidget(checks_host)
        layout.addWidget(self._scroll, 1)

        self._total = QLabel()
        layout.addWidget(self._total)

        btn_row = QHBoxLayout()
        all_btn = QPushButton("すべて展開")
        none_btn = QPushButton("すべてスキップ")
        all_btn.clicked.connect(self._select_all)
        none_btn.clicked.connect(self._select_none)
        btn_row.addWidget(all_btn)
        btn_row.addWidget(none_btn)
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_total()

        # FU-01: 内容ヒントが画面に収まらない場合のみ高さを画面内へクランプ
        # (防御層 — 発火条件は _clamped_size の docstring 参照)。
        cap = self.screen().availableGeometry().height() - _SCREEN_MARGIN
        clamped = _clamped_size(
            self.sizeHint(), cap, self._scroll.verticalScrollBar().sizeHint().width()
        )
        if clamped is not None:
            self.resize(clamped)

    def _update_total(self) -> None:
        total = sum(
            self._request.channels[i].column_count
            for i, cb in enumerate(self._checks)
            if cb.isChecked()
        )
        self._total.setText(f"展開後の追加列数: {total}")

    def _select_all(self) -> None:
        for cb in self._checks:
            cb.setChecked(True)

    def _select_none(self) -> None:
        for cb in self._checks:
            cb.setChecked(False)

    def _on_accept(self) -> None:
        self.result_indices = {i for i, cb in enumerate(self._checks) if cb.isChecked()}
        self.accept()

    @staticmethod
    def ask(request: ExpansionRequest, parent: QWidget | None = None) -> set[int]:
        """モーダル表示し「展開する」インデックス集合を返す (Cancel は空集合)."""
        dlg = ExpansionDialog(request, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.result_indices
        return set()
