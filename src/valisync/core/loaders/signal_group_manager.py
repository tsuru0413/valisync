from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from types import MappingProxyType

from valisync.core.loaders.column_names import (
    ColumnPath,
    ColumnRecord,
    leaf_count,
    leaf_names,
    leaf_paths,
    parse_leaf,
)
from valisync.core.models import Signal, SignalGroup
from valisync.core.models.sample_source import LazyMdfValues

_FORMAT_KEY_PREFIX: dict[str, str] = {"MDF4": "mf4", "CSV": "csv"}
KEY_SEPARATOR = "::"

# 表を持たないグループ (CSV/Derived・未知 key) が返す共有の空ビュー。
_NO_COLUMN_RECORDS: Mapping[str, ColumnRecord] = MappingProxyType({})

# 鋳造列が親から**継承してはならない** metadata (LD-07)。value2text と変換情報は
# スカラー enum の概念で、配列成分/構造化フィールドへ写すと「その列の値ラベル」と
# いう偽の意味を与える。eager ローダーも展開時は raw_conversion=None で継承を
# 止めている (mdf_loader._load_group) ので、鋳造側をそれに一致させる。
_UNINHERITED_METADATA = frozenset({"conversion_info", "value_labels"})

# 鋳造列 LRU の既定容量 (**列数**)。1 列 ~96 KB (float64 実体化後) なので ~48 MB 相当。
# バイトでなく本数で持つのは、鋳造直後の列がまだ未展開 (nbytes 0) で、バイト予算だと
# 「まだ読んでいない列は無料」に見えて上限が一切効かないため。
_DEFAULT_RESOLVED_CAPACITY = 512

# pin が容量を食い尽くしても非 pin 用に必ず残す枠 (spec §5.5 の「LRU の最低容量を
# 無条件確保」)。0 にすると pin 過多のとき、鋳造した列が evict 走査の中で **自分自身を**
# 落としてしまい、ブラウザのプレビュー 1 本ごとにフルチャンネル再読みが復活する。
_MIN_EVICTABLE_COLUMNS = 1

# 高水位 (容量) を超えたら低水位まで一気に空けるヒステリシスの分母。予算ちょうどへ
# 削ると鋳造 1 本ごとに O(現存列) の走査が要り、E-4b の全列エクスポート (264k 鋳造)
# がそこで律速する。1/8 ずつ空ければ走査は鋳造 8 本に 1 度で済む。
_RESOLVED_EVICT_DIVISOR = 8


class SignalGroupManager:
    """Manages loaded Signal_Groups under unique per-load keys.

    Each added group receives a key such as ``mf4_1`` / ``csv_2``, derived from
    its file format plus a per-format counter. The key namespaces every signal
    name (``mf4_1::speed``) so signals from different files — including re-loads
    of the same path — never collide. The counter never decrements, so a key is
    never reused after removal. Recovering the display name (original signal
    name and source file) is left to the GUI layer.
    """

    def __init__(self, resolved_capacity: int = _DEFAULT_RESOLVED_CAPACITY) -> None:
        self._groups: dict[str, SignalGroup] = {}
        self._counters: dict[str, int] = {}
        self._namespaced_list: list[Signal] | None = None
        self._namespaced_map: dict[str, Signal] | None = None
        self._namespaced_by_key: dict[str, list[Signal]] = {}
        # 鋳造した列 Signal (E-1)。**_invalidate_namespaced() に相乗りさせない** —
        # 相乗りすると 2 ファイル目のロードごとに全プロット列がフルチャンネル再読み
        # (実測 0.73-1.18 s/列) になる純粋な回帰。切り離しは remove(key) と
        # E-4a の LRU evict のみ (どちらもグループ寿命/予算という明示の理由を持つ)。
        self._resolved_by_key: dict[str, dict[str, Signal]] = {}
        # 列鋳造の材料 (E-3)。_resolved_by_key と同じく **_invalidate_namespaced() に
        # 相乗りさせない** — グループの寿命 (add/remove) にだけ従う。相乗りさせると
        # 2 ファイル目のロードで表が消え、鋳造がファイル全体の再走査に落ちる。
        self._column_records: dict[str, dict[str, ColumnRecord]] = {}
        # {group_key: {physical_channel 表示名: 代表 Signal}} — 鋳造の継承元索引。
        # _column_records と同じ寿命 (add/remove のみ・_invalidate_namespaced では
        # 触らない)。索引にするのは、線形走査だと鋳造 1 本あたり O(n_channels)
        # (prod 4,324) を払うから。
        self._physical_by_name: dict[str, dict[str, Signal]] = {}
        self.mint_count = 0
        # ─── 鋳造列 LRU (E-4a・D4) ────────────────────────────────────────────
        self._resolved_capacity = max(1, resolved_capacity)
        # 名前空間つき列キーの recency 順 (dict の挿入順 = 古い順)。値は使わない。
        self._resolved_order: dict[str, None] = {}
        # GUI が push した「今プロットされている列」(spec §5.5)。evict 対象外。
        self._pinned: frozenset[str] = frozenset()
        self.resolved_evictions = 0
        # LRU の帳簿 (順序表・pin 集合) は GUI スレッドと E-4b のエクスポートワーカー
        # が同時に触りうる。MdfHandle._close_lock と同型の**小さい専用 lock** で守る —
        # 読み直列化用の handle.lock とは別物で、この下では I/O を一切しないので
        # 入れ子にならない (spec §5.8)。
        self._resolved_lock = threading.Lock()

    def add(
        self,
        group: SignalGroup,
        column_records: Mapping[str, ColumnRecord] | None = None,
    ) -> str:
        """Register a Signal_Group and return its assigned key.

        Duplicate source paths are allowed; each load receives a distinct key.
        ``column_records`` はローダーが 1 レコードプローブから作った
        {表示名: ColumnRecord} (MDF のみ)。CSV/Derived は列構造を持たないので None。
        """
        prefix = _FORMAT_KEY_PREFIX.get(group.file_format)
        if prefix is None:
            raise ValueError(f"unsupported file_format: {group.file_format!r}")
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        key = f"{prefix}_{self._counters[prefix]}"
        self._groups[key] = group
        self._physical_by_name[key] = self._index_physical(group)
        if column_records:
            # 呼び出し側の dict と縁を切る (ローダーの一時表が後から変わっても
            # 登録済みグループの列構造は動かない)。物理チャンネル数ぶんなので安い。
            self._column_records[key] = dict(column_records)
        self._invalidate_namespaced()
        return key

    def remove(self, key: str) -> tuple[SignalGroup, tuple[Signal, ...]]:
        """グループと、そのグループで鋳造済みの列 Signal を取り出して返す。

        列 Signal は SignalGroup.signals の外に居るため、ここで返さないと
        TeardownService の会計・解放から漏れる。

        Dependency checking against Derived_Signals (Req 4.5) is the Session's
        responsibility; this method removes unconditionally.
        """
        try:
            group = self._groups.pop(key)
        except KeyError:
            raise KeyError(f"no Signal_Group registered under key: {key!r}") from None
        with self._resolved_lock:
            table = self._resolved_by_key.pop(key, {})
            # recency 表からも外す。残すとアンロード済みキーが LRU の枠を食い続け、
            # 生きている列が理由なく落ちる (帳簿の静かなリーク)。
            for column_key in table:
                self._resolved_order.pop(column_key, None)
            columns = tuple(table.values())
        self._column_records.pop(key, None)
        self._physical_by_name.pop(key, None)
        self._invalidate_namespaced()
        return group, columns

    @property
    def keys(self) -> list[str]:
        """Keys of all registered groups, in insertion order."""
        return list(self._groups)

    def group(self, key: str) -> SignalGroup:
        """Return the Signal_Group registered under ``key`` (original signal names)."""
        return self._groups[key]

    def source_name(self, key: str) -> str:
        """Original source filename (basename) for the group under ``key``.

        Public recovery point for the GUI display name (the class otherwise
        leaves display-name recovery to the GUI layer). Raises KeyError if the
        key is unknown.
        """
        return self._groups[key].source_path.name

    @staticmethod
    def _namespaced(key: str, group: SignalGroup) -> list[Signal]:
        """Rewrite a group's signal names to ``{key}{KEY_SEPARATOR}{name}``.

        The returned Signals share the stored timestamp/value arrays.
        """
        result: list[Signal] = []
        for sig in group.signals:
            ns_sig = Signal(
                name=f"{key}{KEY_SEPARATOR}{sig.name}",
                timestamps=sig.timestamps,
                values_source=sig._values_source,
                file_format=sig.file_format,
                bus_type=sig.bus_type,
                source_file=sig.source_file,
                metadata=sig.metadata,
            )
            # namespaced ラッパーは FU-08 でキャッシュされ、add()/remove() の
            # 無効化までは再生成されない。無効化のたびにラッパーは作り直されるため、
            # sorted_view/finite_view の単調・非有限スキャン結果は長寿命の元 Signal に
            # 委譲して共有する — スキャンはラッパーが何度作り直されても元 Signal で
            # 1回だけ走る(render/カーソルのホットパス対策)。委譲は timestamps/values
            # の配列オブジェクトが元 Signal と同一であることが前提
            # (offset 適用後の別配列 Signal には絶対に付けないこと)。
            object.__setattr__(ns_sig, "_sorted_view_delegate", sig)
            result.append(ns_sig)
        return result

    def _invalidate_namespaced(self) -> None:
        """Drop the namespaced caches; rebuilt lazily on next access."""
        self._namespaced_list = None
        self._namespaced_map = None
        self._namespaced_by_key = {}
        # NOTE: _resolved_by_key はここで**捨てない** (Critical 1)。捨てると 2 ファイル目の
        # ロードごとに全プロット列が新オブジェクト (空キャッシュ) となり、次の render で
        # フルチャンネル再読み (実測 0.73-1.18 s/列) が走る。切り離しは remove(key) と
        # E-4a の LRU evict のみ。

    def _ensure_namespaced(self) -> None:
        """Build and cache the namespaced signal list/map once (idempotent).

        The expensive work — creating one namespaced Signal wrapper per signal
        across all groups — happens here a single time per load/unload, not on
        every ``signals()``/``signal_map()`` call (FU-08). The list preserves
        every signal (duplicate namespaced names included); the map is keyed by
        name with last-wins dedupe, matching the historical ``signals()``-to-dict
        behaviour its callers relied on.
        """
        if self._namespaced_list is not None:
            return
        result: list[Signal] = []
        for key, group in self._groups.items():
            result.extend(self._namespaced(key, group))
        self._namespaced_list = result
        self._namespaced_map = {sig.name: sig for sig in result}

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

    def signals(self) -> list[Signal]:
        """Return every signal across all groups, name-spaced by its group key."""
        self._ensure_namespaced()
        assert self._namespaced_list is not None
        return list(self._namespaced_list)

    def signal_map(self) -> Mapping[str, Signal]:
        """読み取り専用 ``{namespaced_name: Signal}`` ビュー (FU-08 でキャッシュ)。

        重複した名前空間つき名は last-wins (``signals()`` から dict を作るのと同じ)。
        読み取り専用なので呼び出し側は共有キャッシュを壊せない。

        **非対称 Mapping** (E-1・意図的逸脱): ``[]``/``get``/``in`` は列キーを解決器
        経由で鋳造しうるが、``__iter__``/``len`` は既存 (物理) キーのみを返す。全論理
        キーの列挙は 330k 列を鋳造して ~390 MB を再導入するため提供しない —
        ``dict(signal_map())`` は使ってはならない。
        """
        self._ensure_namespaced()
        assert self._namespaced_map is not None
        return _ResolvingMap(self._namespaced_map, self.resolve)

    def resolve(self, key: str) -> Signal | None:
        """名前空間つきキーを Signal へ解決する (無ければ列として鋳造を試みる)。

        グループ未ロードなら None (正当な不在)。ローダーが列を展開している間は
        全キーが既存 map で解決でき、鋳造経路はテストからのみ exercise される。

        **同一キー → 同一オブジェクトは pin 中のみ保証** (E-4a D4 の意図的
        supersede)。pin されていない列は :meth:`set_pinned_columns` が設定する
        予算に応じて古い順に落ちるので、再解決で**別オブジェクト**が返りうる。
        値・名前・時刻軸は同じで、読みも T2 のチャンネルキャッシュに当たるため
        安い。列 Signal を ``is`` で追跡するコードを書いてはならない。
        """
        self._ensure_namespaced()
        assert self._namespaced_map is not None
        hit = self._namespaced_map.get(key)
        if hit is not None:
            return hit
        group_key = key.split(KEY_SEPARATOR, 1)[0]
        if group_key not in self._groups:
            return None
        with self._resolved_lock:
            table = self._resolved_by_key.setdefault(group_key, {})
            cached = table.get(key)
            if cached is not None:
                # ヒットは recency を更新する。プロット中の列は render のたびに
                # ここを通る (GraphPanelVM が sig_map.get を引き直す) ので、
                # pin 済みの列は放っておいても MRU 側へ寄る。
                self._touch(key)
                return cached
            minted = self._mint_column(group_key, key)
            if minted is None:
                return None
            table[key] = minted
            self._resolved_order[key] = None
            self.mint_count += 1
            self._evict_resolved()
            return minted

    def resolved_keys(self, group_key: str) -> frozenset[str]:
        """鋳造済み列キーの集合 (鋳造を誘発しない introspection)."""
        with self._resolved_lock:
            return frozenset(self._resolved_by_key.get(group_key, {}))

    # ─── 鋳造列 LRU と pin (E-4a spec §5.5 / D4) ──────────────────────────────

    def set_pinned_columns(self, keys: Iterable[str]) -> None:
        """今 pin すべき列キー集合を差し替える (GUI が push する)。

        weakref では何も pin されない (VM は ``signal_key: str`` しか持たない)
        ため、GUI 側が明示的に押し込む。集合は**置き換え**であって追加ではない —
        差分更新にすると、パネル削除やクロスパネル軸移動のように「どの経路から
        通知が来るか」が変わる操作で漏れが出る。

        アンロード済みグループのキーが残っていても無害 (グループ key の連番は
        減らないので、外れたキーが後から別の列に当たることはない)。
        """
        pinned = frozenset(keys)
        with self._resolved_lock:
            self._pinned = pinned
            self._evict_resolved()

    def pinned_columns(self) -> frozenset[str]:
        """現在 pin されている列キー集合 (introspection・鋳造しない)."""
        return self._pinned

    def pinned_column_bytes(self) -> int:
        """pin 済みの鋳造列が **今** 保持している値バイトの合計 (spec §5.5)。

        ``Session.set_pinned_columns`` がこれを ``ChannelSampleCache.set_reserved``
        へ渡す (spec §5.2「予算の裁定者は 1 人」)。pin した列は所有権不変条件
        (spec §5.4) により自前の独立配列を抱えるので、チャンネル 2-D と**同じ**
        U3 256 MB を食う — 渡さないと 2 つの帳簿が互いの解放を当てにして両方が
        上限を超える。

        **未展開の列は 0**: 鋳造しただけの列は 1 バイトも保持していない
        (``nbytes_if_materialized`` は展開を誘発しない)。「鋳造したから食っている」
        と数えると、ブラウザで覗いただけの列がチャンネルキャッシュの容量を削り、
        最低容量まで痩せて再描画ごとのフルチャンネル再読みが復活する。

        pin 集合には物理チャンネルのキーも混ざる (プロットしたのがスカラー信号なら
        鋳造列ではない) が、ここには載らない — 走査するのは ``_resolved_by_key``
        (鋳造列の表) だけで、物理チャンネルの実体はグループ側の会計に属するから。

        **タイミング (仕様として受け入れる)**: この値は次の pin 変化まで更新され
        ないので、pin の後に実体化した列は次の push まで申告に現れない。過小申告は
        LRU の容量を広めに見せるだけで、実際の超過は ``put`` 側の evict が吸収する
        (``bytes_held`` は常に真の値)。

        lock 下で数え切るのは、表のコピーを外へ持ち出すと反復中に別スレッドの
        鋳造で ``dict changed size`` になるから。``nbytes_if_materialized`` は int の
        読みだけで I/O も ``handle.lock`` も触らないので、ロック順の危険は無い。
        """
        with self._resolved_lock:
            return sum(
                int(signal._values_source.nbytes_if_materialized)
                for table in self._resolved_by_key.values()
                for column_key, signal in table.items()
                if column_key in self._pinned
            )

    @property
    def resolved_capacity(self) -> int:
        """鋳造列 LRU の容量 (列数)."""
        return self._resolved_capacity

    @property
    def pinned_overflow(self) -> int:
        """予算を超えて pin されている鋳造列の数 (0 なら予算内)。

        pin は**拒否しない** (拒否するとプロット中の列が落ち、再描画ごとに
        316 ms 停止が復活する) ので、超過は落とすのではなくここで観測する。
        """
        with self._resolved_lock:
            pinned_live = sum(1 for k in self._resolved_order if k in self._pinned)
        return max(0, pinned_live - self._resolved_capacity)

    def resolved_lru_keys(self) -> tuple[str, ...]:
        """鋳造列の recency 順 (**古い順**) — 鋳造を誘発しない introspection."""
        with self._resolved_lock:
            return tuple(self._resolved_order)

    def _touch(self, key: str) -> None:
        """*key* を MRU 側へ移す (呼び出し側が ``_resolved_lock`` を保持していること)."""
        self._resolved_order.pop(key, None)
        self._resolved_order[key] = None

    def _evict_resolved(self) -> None:
        """非 pin の鋳造列を古い順に落として容量へ収める (D4)。

        **pin は決して落とさない**。pin が予算を超えても拒否せず、超過は
        :attr:`pinned_overflow` で観測する (spec §5.5)。pin だけで予算が埋まった
        場合でも非 pin 用に ``_MIN_EVICTABLE_COLUMNS`` 本は確保するので、鋳造した
        列がその場で自分を落とす形にはならない。

        高水位/低水位のヒステリシスは走査回数の償却のため (定数のコメント参照)。
        pin が予算を超えている極端な状態では毎回 O(pin 数) の走査になるが、
        これは「プロット中の列を落とさない」ことの代価として受け入れる。

        呼び出し側が ``_resolved_lock`` を保持していること。
        """
        if len(self._resolved_order) <= self._resolved_capacity:
            return  # 予算内 — pin の数え直しすらしない (鋳造ホットパスの O(n) 回避)
        pinned_live = sum(1 for k in self._resolved_order if k in self._pinned)
        room = max(self._resolved_capacity - pinned_live, _MIN_EVICTABLE_COLUMNS)
        slack = max(1, room // _RESOLVED_EVICT_DIVISOR)
        keep = max(room - slack, _MIN_EVICTABLE_COLUMNS)
        unpinned = [k for k in self._resolved_order if k not in self._pinned]
        excess = len(unpinned) - keep
        if excess <= 0:
            return
        for column_key in unpinned[:excess]:  # dict は挿入順 = 古い順
            del self._resolved_order[column_key]
            table = self._resolved_by_key.get(column_key.split(KEY_SEPARATOR, 1)[0])
            if table is not None:
                table.pop(column_key, None)
            self.resolved_evictions += 1

    def column_records(self, group_key: str) -> Mapping[str, ColumnRecord]:
        """{LD-08 dedup 済み表示名: ColumnRecord} の読み取り専用ビュー (E-3)。

        キー空間は Signal の ``metadata['physical_channel']`` と同一 — ブラウザや
        エクスポートの「物理チャンネル行」から列を引くのはこの表。未知 key と
        CSV/Derived は空を返す (``resolved_keys`` と同じ introspection 契約で、
        鋳造も KeyError も起こさない)。
        """
        table = self._column_records.get(group_key)
        return _NO_COLUMN_RECORDS if table is None else MappingProxyType(table)

    def column_names_of(self, group_key: str, display_name: str) -> tuple[str, ...]:
        """物理チャンネル 1 本の数値リーフ列名を _flatten と同じ順序で返す。

        base に**表示名**を渡すのが要点 (二重名の契約): 列キーは dedup 済み名から
        作り (``sig[1][0]``)、selector は生名から作る。ここで生名を base にすると
        UI/永続キーが黙って別物になる。
        表に無い物理チャンネル (CSV/Derived・未知 key) は 1 信号 1 列なので
        ``(display_name,)`` を返す。
        """
        record = self._column_records.get(group_key, {}).get(display_name)
        if record is None:
            return (display_name,)
        return tuple(leaf_names(display_name, record.spec))

    def total_column_count(self, group_key: str) -> int:
        """グループの数値列総数 (未知 key は ``group()`` と同じく KeyError)。

        ``source_info.n_channels`` とブラウザヘッダの母数 (U2: 単位は列数のまま)。
        名前を 1 本も生成せず、鋳造も誘発せずに数える。数えるのは**数値リーフのみ**
        — 非数値リーフでは Signal を作らないので、dtype-blind に数えると
        表示件数が実在しない列を含んでしまう。
        """
        group = self._groups[group_key]
        records = self._column_records.get(group_key)
        if not records:
            return len(group.signals)  # CSV/Derived: 1 信号 1 列
        return sum(leaf_count(record.spec) for record in records.values())

    def has_column(self, group_key: str, display_name: str) -> bool:
        """*display_name* がこのグループの **列** として実在するか (鋳造しない)。

        「あるか」しか要らない呼び出し側 (T5 の行フィルタ・T7 の表示名衝突判定) の
        ための存在判定。``resolve_signal`` で代用すると、ヒットした列が
        ``_resolved_by_key`` へ登録される。E-4a で LRU が入ったので恒久滞留はしなく
        なったが、**非 pin の枠を食ってプロット中でない列を押し出す** (spec §5.5)
        ため、表示や存在判定のためだけに列 Signal を鋳造してはならない。

        物理チャンネル名そのものが渡された場合は ``spec`` の形だけで決まる
        (列名を 1 本も生成しない — 広幅チャンネルで 1,000 本の f-string を作らない)。
        列キー (``Mat[1]`` / ``Pos.xb``) は表示名の最長一致で親を探し、その親の
        数値リーフ名に含まれるかを見る。``leaf_names`` は数値リーフしか生まないので、
        非数値リーフ (``Q.tag``) は自動的に False になる。
        未知 key / 未知名は False (``column_records`` と同じ introspection 契約)。
        """
        records = self._column_records.get(group_key)
        if not records:
            # 表を持たないグループ (CSV/Derived・未知 key) は 1 信号 1 列。
            group = self._groups.get(group_key)
            return group is not None and any(
                sig.name == display_name for sig in group.signals
            )
        record = records.get(display_name)
        if record is not None:
            # 物理チャンネル名そのもの。列でもあるのは「数値スカラー」= 1 本の
            # リーフが自分自身と同名になるときだけで、容器 (配列/構造体の親) は
            # 列ではない (親を列扱いすると 2-D 値がプロット/出力へ流れる)。
            return record.spec.kind == "leaf" and leaf_count(record.spec) == 1
        for i in range(len(display_name) - 1, 0, -1):
            parent = records.get(display_name[:i])
            if parent is None:
                continue
            names = leaf_names(display_name[:i], parent.spec)
            if any(name == display_name for name in names):
                return True
            # ここで打ち切らない: Mat[0] (1-D 実チャンネル) と Mat (3-D) のように
            # 長い方が別チャンネルとして実在しても、短い方が正しい親でありうる。
        return False

    def _mint_column(self, group_key: str, key: str) -> Signal | None:
        """列キーから Signal を鋳造する (解決できなければ None)。

        鋳造した Signal は **pin 中に限り**その列キーの正典 (resolve が同じ
        オブジェクトを返す) であり、namespaced ラッパーと違って別の元 Signal を
        持たない -- ``_sorted_view_delegate`` は付けない。pin されていない列は
        E-4a の LRU で落ちうるので、再解決で別オブジェクトが返る (D4 supersede)。
        """
        _prefix, sep, display_key = key.partition(KEY_SEPARATOR)
        if not sep:
            return None  # 名前空間の無いキーは列キーではない
        group = self._groups[group_key]
        handle = group.handle
        if handle is None:
            return None  # CSV/Derived は LD-14 の列文法を持たない
        records = self.column_records(group_key)
        # 親は **表示名** (LD-08 dedup 済み) の最長一致で確定する。表示名は物理
        # チャンネルごとに一意なので、parse_leaf 単体では避けられない生名衝突
        # (同名 2 チャンネルが同じ spec キーを共有する・column_names.parse_leaf の
        # precondition) をここで断てる。
        for i in range(len(display_key), 0, -1):
            record = records.get(display_key[:i])
            if record is None:
                continue
            rest = display_key[i:]
            if not rest:
                # 表示名そのもの = 物理チャンネル (容器またはスカラー) であって列
                # ではない。ここで **打ち切る** のが要点 (T7 の第 2 の防波堤):
                # `continue` にすると、実チャンネル `A[0]` が配列 `A` の列 0 と
                # 字面衝突したとき、より短い親 `A` がヒットして **別チャンネルの
                # 値を例外なしで返す**。今日この経路が踏まれないのは resolve() が
                # _namespaced_map を先に見るからで、その前提は「レコードのキー集合
                # == 発行された Signal 名」という 1:1 不変条件 — 述語ではない。
                # 1:1 が崩れた瞬間に誤データの入口になるので、鋳造器自身でも断つ。
                return None
            # 二重名の契約: 表示名は dedup 済み名から、selector は **生チャンネル名**
            # から導く。両者は同じ suffix を共有する (ローダーの out_leaves と
            # sel_leaves は同一構造を同順に走査する)。dedup 済み表示名で parse_leaf を
            # 引くと "W[1][2]" の "[1]" を W 自身の配列インデックスとして消費し、
            # 解決不能になるか別チャンネルの列を返す。
            raw_leaf = f"{record.raw_base_name}{rest}"
            if parse_leaf(raw_leaf, {record.raw_base_name: record.spec}) is None:
                continue  # 消費しきれない / 非数値リーフ = この親では解決不能
            path = _leaf_path(record, rest)
            if path is None:
                continue  # 名前は通ったが位置が引けない = この親では解決不能
            parent = self._physical_signal(group_key, display_key[:i])
            if parent is None:
                return None
            return Signal(
                name=key,
                # master は親と**同一オブジェクト**を渡す (source_info の
                # id(s.timestamps) dedup が同一性に依存する)。ローダーが read-only
                # 化済みなので Signal.__init__ はコピーしない。
                timestamps=parent.timestamps,
                values_source=LazyMdfValues(
                    handle,
                    record.raw_base_name,
                    record.group_index,
                    record.channel_index,
                    length=len(parent.timestamps),
                    # 名前は永続キー・位置は読み経路。両方渡すのが列の契約。
                    selector=(raw_leaf,),
                    path=path,
                ),
                file_format=parent.file_format,
                bus_type=parent.bus_type,
                source_file=parent.source_file,
                metadata={
                    k: v
                    for k, v in parent.metadata.items()
                    if k not in _UNINHERITED_METADATA
                },
            )
        return None

    @staticmethod
    def _index_physical(group: SignalGroup) -> dict[str, Signal]:
        """``{metadata['physical_channel']: 代表 Signal}`` を add() で 1 度だけ作る。

        反転後は「物理チャンネル 1 本 = Signal 1 個」なので、この索引は表示名の
        全単射そのものになる。``physical_channel`` を持たない Signal (CSV/Derived)
        は載らない — 旧実装の走査もそれらには一致しなかった (``.get`` が None を
        返し、display_name は必ず str)。

        **キーの重複はローダー側で構造的に潰れている**: 表示名が別チャンネルと
        衝突したら ``MdfLoader`` が error 診断つきでそのチャンネルを拒否する
        (1:1 不変条件の loud-fail)。手組みの SignalGroup (テスト) が重複を作った
        場合は旧走査と同じ「最初の 1 本」を採る。
        """
        index: dict[str, Signal] = {}
        for sig in group.signals:
            phys = sig.metadata.get("physical_channel")
            if isinstance(phys, str) and phys not in index:
                index[phys] = sig
        return index

    def _physical_signal(self, group_key: str, display_name: str) -> Signal | None:
        """物理チャンネル ``display_name`` を代表する Signal (継承元・O(1))。

        鋳造列は master・file_format・bus_type・source_file・unit 等をここから
        引き継ぐ (いずれもチャンネル単位で不変)。旧実装は ``group.signals`` の
        線形走査で **最初に一致した** Signal を返していた: 鋳造 1 本あたり
        O(n_channels) を払い、かつ同じ表示名の Signal が 2 本あると「どちらか」を
        黙って選ぶ曖昧さがあった。索引化で走査は消え、曖昧さの方はローダーの
        1:1 loud-fail が入口で断つ。
        """
        return self._physical_by_name.get(group_key, {}).get(display_name)


def _leaf_path(record: ColumnRecord, suffix: str) -> ColumnPath | None:
    """リーフ名サフィックスから **位置** を引く (E-4a・解決不能なら None)。

    サフィックス (``[2]`` / ``.xa``) は 2 つのキー空間 (LD-08 dedup 済み表示名 /
    生チャンネル名) が共有する唯一の部分なので、位置は dedup のずれを受けない —
    生名側でしか引けない ``parse_leaf`` (docstring の precondition) と対照的に、
    ここは表示名側の残余をそのまま使える。``leaf_paths`` は ``_flatten`` と同順で
    **全**リーフを返す (非数値も含む) ので、数値ゲートは呼び出し側の
    ``parse_leaf`` に残す — ここで数値判定を兼ねると混在構造 ``Q`` の
    ``Q.tag`` が裏口から列になる。

    **索引は ``leaf_paths`` が返すサフィックスで引く** (T1 レビューの前方ハザード)。
    ``zip(leaf_names(...), leaf_paths(...))`` で位置合わせしてはならない: 2 つは
    **別の列挙空間**で (``leaf_names`` は数値リーフのみ・``leaf_paths`` は全リーフ)、
    混在構造では長さが違う。フィールド順が ``(tag: S2, x: f8)`` の構造体では zip が
    キー ``R.x`` に ``.tag`` の経路を**例外なしで**結びつける = 本増分が潰そうと
    している「別の列を黙って返す」そのもの (S3-S5 の失敗モードが 1 層上がった形)。

    **索引は ``record`` 側に 1 度だけ作る** (I-2): 引くたびに ``leaf_paths`` を頭から
    回すと 1 鋳造が O(全リーフ) になり、幅 1,100 のチャンネルを全列鋳造すると
    1.2M ステップ = **O(n^2)** になる。E-4b の「すべて選択 -> エクスポート」は
    E-4a 完了に依存する (spec §4) ので、そこで律速するのはここ。初回の 1 回だけ
    全リーフを歩く (= 従来の**最悪 1 回分**と同じコスト) ので、単発の鋳造は遅く
    ならない。索引を持つのは実際に列を鋳造したチャンネルだけで、閲覧しかしない
    チャンネルには 1 バイトも作らない。

    **書き込みは dict 同士の merge (GIL 下で 1 ステップ)** — ``leaf_paths`` は
    **ジェネレータ**なので、``index.update(leaf_paths(record.spec))`` のように
    直接渡すと ``update`` はジェネレータを 1 件ずつ消費しながら ``index`` へ
    書き込む。この「1 発の代入」ではなく「複数回の代入」である間、他スレッドは
    ``record.path_index`` 越しに**部分的にしか埋まっていない索引**を観測できる
    (レビュー実測: 2000 件中 6 件だけ入った状態が見えた)。結果は「間違った値」
    ではなく「まだ入っていないキーが ``None`` を返す」(= このチャンネルは
    解決不能扱いになる) なので実害はサイレント破損ではないが、走査の途中経過を
    見せてよい理由にはならない。**``dict(leaf_paths(record.spec))`` で先に
    ジェネレータを完全に消費してから** ``index.update(その dict)`` する —
    dict 同士の merge は C 実装のみで進み Python コールバックへ戻らないため、
    途中経過を他スレッドへ見せない。二重に走っても同じ内容を作り直すだけなので
    競合そのものは無害だが、この関数を呼ぶのに専用 lock は要らない、という
    今日の安全性は「呼び出し元 (``resolve``) が ``_resolved_lock`` 下でしか
    ``_mint_column`` を呼ばない」という**呼び出し側の事実**に依っているだけで、
    この関数自身がアトミックだからではない — 将来ここが lock なしの経路
    (T3 以降の並行読み等) から呼ばれても崩れないよう、書き込みそのものを
    1 ステップにしておく。
    """
    index = record.path_index
    if not index:
        # 0 リーフのチャンネル (幅 0 軸) は毎回空走査になるが、その走査自体が
        # O(1) (leaf_paths が 1 件も yield しない) なので償却の意味がない。
        index.update(dict(leaf_paths(record.spec)))
    return index.get(suffix)


class _ResolvingMap(Mapping[str, Signal]):
    """既存マップ + 未知キーの解決器フォールバック (列挙は既存キーのみ)。

    ``Mapping`` の契約からの**意図的逸脱**: ``key in m`` が True でも ``iter(m)`` が
    その key を返さないことがある。全論理キーを列挙可能にすると 330k 列を鋳造して
    ~390 MB を再導入する — それが E-1 で取り除いているコストそのもの。読み取り専用
    (``__setitem__`` 無し) なので base の共有キャッシュは外から壊せない。
    """

    __slots__ = ("_base", "_resolve")

    def __init__(
        self, base: dict[str, Signal], resolve: Callable[[str], Signal | None]
    ) -> None:
        self._base = base
        self._resolve = resolve

    def __getitem__(self, key: str) -> Signal:
        hit = self._base.get(key)
        if hit is not None:
            return hit
        got = self._resolve(key)
        if got is None:
            raise KeyError(key)
        return got

    def get(self, key: str, default: Signal | None = None) -> Signal | None:  # type: ignore[override]
        # Mapping 既定の get は __getitem__ の KeyError を捕まえるので挙動は同じだが、
        # 呼出側 (約20箇所の sig_map.get) のホットパスから例外の送出/捕捉を外す。
        hit = self._base.get(key)
        if hit is not None:
            return hit
        got = self._resolve(key)
        return default if got is None else got

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        # 既存キーは解決器を通さない (鋳造を誘発しない)。
        return key in self._base or self._resolve(key) is not None

    def __iter__(self) -> Iterator[str]:
        return iter(self._base)  # 物理キーのみ — 鋳造しない (クラス docstring 参照)

    def __len__(self) -> int:
        return len(self._base)  # 物理キー数のみ — 鋳造しない
