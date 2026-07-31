"""pin の供給機構 —— GUI が push する (E-4a spec §5.5)。

``weakref.WeakValueDictionary`` は使えない: VM は ``signal_key: str`` しか持たず
Signal オブジェクトを持たないので、弱参照にすると **何も pin されず** 毎回再鋳造 =
フルチャンネル再読みになる (敵対的レビューで REFUTED 済み)。よって
GraphAreaVM -> AppViewModel -> Session -> SignalGroupManager の一方向 push で配る。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from tests.mdf4_helpers import write_mdf4_wide_2d
from valisync.core.session import Session
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.graph_area_vm import GraphAreaVM


def _session_with_wide(
    tmp_path: Path, capacity: int | None = None
) -> tuple[Session, str]:
    """幅 8 の 2-D チャンネル ``Wide`` を持つ実 mf4 をロードした Session と group key。

    *capacity* は鋳造列 LRU の容量注入 (D6「予算を注入して小さくする」と同型) —
    実データで evict を起こすには広幅を何十本も触る必要があり、テストの実行時間を
    圧迫するため。
    """
    session = Session() if capacity is None else Session(column_capacity=capacity)
    outcome = session.load(write_mdf4_wide_2d(tmp_path, cols=8))
    return session, outcome.key


def test_pins_span_all_tabs_and_panels(tmp_path: Path) -> None:
    """pin 対象は **全タブ・全パネル**。

    アクティブパネル/アクティブタブに絞ると 2 タブ目の列が evict され、タブを
    戻した最初の再描画で 316 ms/列 停止する (spec §5.5)。
    """
    session, key = _session_with_wide(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    area.active_panel().add_signal(f"{key}::Wide[0]")  # タブ 1 / パネル 1
    area.add_tab()
    area.active_panel().add_signal(f"{key}::Wide[1]")  # タブ 2 / パネル 1
    area.add_panel()
    area.active_panel().add_signal(f"{key}::Wide[2]")  # タブ 2 / パネル 2

    expected = frozenset({f"{key}::Wide[0]", f"{key}::Wide[1]", f"{key}::Wide[2]"})
    assert area.pinned_signal_keys() == expected
    assert session.pinned_columns() == expected


def test_adding_a_signal_pushes_the_pin_to_the_session(tmp_path: Path) -> None:
    session, key = _session_with_wide(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    assert session.pinned_columns() == frozenset()

    area.active_panel().add_signal(f"{key}::Wide[0]")
    assert session.pinned_columns() == frozenset({f"{key}::Wide[0]"})


def test_removing_a_signal_narrows_the_pushed_pin_set(tmp_path: Path) -> None:
    session, key = _session_with_wide(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    panel = area.active_panel()
    panel.add_signal(f"{key}::Wide[0]")
    panel.add_signal(f"{key}::Wide[1]")

    panel.remove_signal(f"{key}::Wide[0]")
    assert session.pinned_columns() == frozenset({f"{key}::Wide[1]"})


def test_removing_a_tab_drops_its_pins(tmp_path: Path) -> None:
    """タブ削除はどのパネルからも "signals" 通知が来ない = 専用の push が要る。"""
    session, key = _session_with_wide(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    area.active_panel().add_signal(f"{key}::Wide[0]")
    area.add_tab()
    area.active_panel().add_signal(f"{key}::Wide[1]")

    area.remove_tab(1)
    assert session.pinned_columns() == frozenset({f"{key}::Wide[0]"})


def test_removing_a_panel_drops_its_pins(tmp_path: Path) -> None:
    session, key = _session_with_wide(tmp_path)
    area = GraphAreaVM(AppViewModel(session))
    area.active_panel().add_signal(f"{key}::Wide[0]")
    area.add_panel()
    area.active_panel().add_signal(f"{key}::Wide[1]")

    area.remove_panel(0, 1)
    assert session.pinned_columns() == frozenset({f"{key}::Wide[0]"})


def test_app_viewmodel_forwards_pins_to_the_session(tmp_path: Path) -> None:
    session, key = _session_with_wide(tmp_path)
    app_vm = AppViewModel(session)
    app_vm.set_pinned_columns(frozenset({f"{key}::Wide[3]"}))
    assert session.pinned_columns() == frozenset({f"{key}::Wide[3]"})


def test_plotted_column_survives_browsing_pressure(tmp_path: Path) -> None:
    """プロット中の列は「他の列を覗く」圧力で evict されない (pin の存在理由)。

    非 pin の対照 (browsed) を同じ圧力に置くのが要点 —— これが無いと、圧力が
    そもそも掛かっていないだけの偽緑と区別できない。
    """
    session, key = _session_with_wide(tmp_path, capacity=2)
    area = GraphAreaVM(AppViewModel(session))
    plotted = f"{key}::Wide[0]"
    browsed = f"{key}::Wide[1]"
    area.active_panel().add_signal(plotted)

    pinned_sig = session.resolve_signal(plotted)
    browsed_sig = session.resolve_signal(browsed)
    assert pinned_sig is not None and browsed_sig is not None
    for i in range(2, 8):
        assert session.resolve_signal(f"{key}::Wide[{i}]") is not None

    assert session.resolve_signal(browsed) is not browsed_sig, (
        "非 pin が落ちていない — 圧力不足で pin の効果を検証できていない (setup 失敗)"
    )
    assert session.resolve_signal(plotted) is pinned_sig


def test_pins_reserve_their_bytes_in_the_channel_cache(tmp_path: Path) -> None:
    """pin した列の実体は **チャンネルキャッシュと同じ予算** から引かれる (spec §5.2)。

    「予算の裁定者は 1 人」の実配線そのもの。pin した列は所有権不変条件 (spec §5.4)
    により自前の独立配列を抱えるので、チャンネル 2-D と同じ U3 256 MB を食う。
    繋がないと ``ChannelSampleCache.set_reserved`` は誰も呼ばない dead API になり、
    「プロット中の列 + キャッシュ」の合計が静かに 256 MB を超える —
    **どちらの側も自分の帳簿では予算内に見える**ので、症状は数字に出ない。

    ``reserved`` を直接見るのは、効果 (LRU 容量の縮み) だけを観測しようとすると
    pin が予算に対して小さい構成では何も起きず、配線が外れても緑のまま通るため。

    **実体化は pin push の「前」に起きる** (実測・E-4a T3 で確認): ``add_signal`` は
    ``_notify("signals")`` を出す前に ``_auto_fit_ranges`` -> ``_visible_union_range``
    で ``sig.values`` を読むので、push の時点で列は既に実体を持っている。したがって
    申告値は「1 回分 stale」にはならない — 「鋳造しただけで未展開の列は 0」という
    もう一方の契約は manager 側の
    ``test_pinned_column_bytes_counts_only_what_is_materialized`` が固定する。
    """
    session, key = _session_with_wide(tmp_path)
    plotted = f"{key}::Wide[0]"
    area = GraphAreaVM(AppViewModel(session))
    assert session.channel_cache.reserved == 0, "pin ゼロの状態で予約がある"

    area.active_panel().add_signal(plotted)
    sig = session.resolve_signal(plotted)
    assert sig is not None
    one = np.asarray(sig.values).nbytes
    assert one == 3, one  # 反 vacuous: 0 と機械的に区別できる値 (3 サンプル x uint8)
    assert session.channel_cache.reserved == one, (
        "pin の実体バイトが予算の裁定者へ渡っていない (set_reserved が未配線)"
    )

    # 覗くだけの列 (非 pin) を実体化しても申告は増えない。定数を刷っているだけの
    # 実装や「鋳造列ぜんぶ」を数える実装をここで落とす。
    browsed = session.resolve_signal(f"{key}::Wide[2]")
    assert browsed is not None
    _ = browsed.values
    area.active_panel().add_signal(f"{key}::Wide[1]")  # 次の pin push を起こす

    assert session.channel_cache.reserved == one * 2, (
        "pin 集合の実体バイト合計になっていない (非 pin を数えた / 増えていない)"
    )
