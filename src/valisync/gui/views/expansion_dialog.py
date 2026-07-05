"""展開列数が上限を超えるチャンネルの展開/スキップを選ぶモーダル (LD-14).

per-channel でチェックし、OK で「展開する」インデックス集合を返す。初期状態は
全未チェック (=全スキップ) — ガードの主旨が慎重側のため。GUI スレッドで呼ぶ
前提の純 UI で、ワーカースレッドからの起動は ExpansionConfirmer が担う。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from valisync.core.loaders.mdf_loader import EXPANSION_COLUMN_LIMIT, ExpansionRequest


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
            QLabel(
                "以下の信号は展開すると列数が上限"
                f"（{EXPANSION_COLUMN_LIMIT}）を超えます。\n"  # noqa: RUF001
                "展開するものを選択してください（未選択はスキップ）。"  # noqa: RUF001
            )
        )

        self._checks: list[QCheckBox] = []
        for ch in request.channels:
            cb = QCheckBox(f"{ch.name} — {ch.column_count} 列")
            cb.toggled.connect(self._update_total)
            layout.addWidget(cb)
            self._checks.append(cb)

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
