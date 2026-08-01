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
