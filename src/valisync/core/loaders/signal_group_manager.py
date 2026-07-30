from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from types import MappingProxyType

from valisync.core.loaders.column_names import (
    ColumnRecord,
    leaf_count,
    leaf_names,
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


class SignalGroupManager:
    """Manages loaded Signal_Groups under unique per-load keys.

    Each added group receives a key such as ``mf4_1`` / ``csv_2``, derived from
    its file format plus a per-format counter. The key namespaces every signal
    name (``mf4_1::speed``) so signals from different files — including re-loads
    of the same path — never collide. The counter never decrements, so a key is
    never reused after removal. Recovering the display name (original signal
    name and source file) is left to the GUI layer.
    """

    def __init__(self) -> None:
        self._groups: dict[str, SignalGroup] = {}
        self._counters: dict[str, int] = {}
        self._namespaced_list: list[Signal] | None = None
        self._namespaced_map: dict[str, Signal] | None = None
        self._namespaced_by_key: dict[str, list[Signal]] = {}
        # 鋳造した列 Signal (E-1)。**_invalidate_namespaced() に相乗りさせない** —
        # 相乗りすると 2 ファイル目のロードごとに全プロット列がフルチャンネル再読み
        # (実測 0.73-1.18 s/列) になる純粋な回帰。remove(key) でだけ切り離す。
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
        columns = tuple(self._resolved_by_key.pop(key, {}).values())
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
        # フルチャンネル再読み (実測 0.73-1.18 s/列) が走る。切り離しは remove(key) のみ。

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
        """
        self._ensure_namespaced()
        assert self._namespaced_map is not None
        hit = self._namespaced_map.get(key)
        if hit is not None:
            return hit
        group_key = key.split(KEY_SEPARATOR, 1)[0]
        if group_key not in self._groups:
            return None
        table = self._resolved_by_key.setdefault(group_key, {})
        cached = table.get(key)
        if cached is not None:
            return cached
        minted = self._mint_column(group_key, key)
        if minted is None:
            return None
        table[key] = minted
        self.mint_count += 1
        return minted

    def resolved_keys(self, group_key: str) -> frozenset[str]:
        """鋳造済み列キーの集合 (鋳造を誘発しない introspection)."""
        return frozenset(self._resolved_by_key.get(group_key, {}))

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
        ``_resolved_by_key`` へ**恒久的に**登録される (LRU は E-3 では入れない = C-g)
        ため、表示のためだけに列 Signal が寿命いっぱい滞留する。

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

        鋳造した Signal は列キーの**正典**であり (resolve は同じキーに同じオブジェクトを
        返す)、namespaced ラッパーと違って別の元 Signal を持たない --
        ``_sorted_view_delegate`` は付けない。
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
                    selector=(raw_leaf,),
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
