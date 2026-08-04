from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    import numpy as np

from valisync.core.loaders.column_names import (
    ColumnPath,
    ColumnRecord,
    leaf_count,
    leaf_names,
    leaf_paths,
    owning_candidates,
)
from valisync.core.models import Signal, SignalGroup, retained_bytes
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

# 鋳造列 LRU の既定容量。単位は **列数だけ** で、この LRU はバイトを一切強制しない。
# バイトでなく本数で持つのは、鋳造直後の列がまだ未展開 (0 バイト) で、バイト予算だと
# 「まだ読んでいない列は無料」に見えて上限が一切効かないため。
# 512 という数は「prod の広幅 1 列 ~96 KB (float64 実体化後) x 512 = ~48 MB」という
# **最悪ケースの見積り**から採ったが、それは目安であって上限ではない: 512 本すべてが
# もっと長いチャンネルなら実体はいくらでも大きくなりうるし、逆に未展開なら 0 に
# なりうる。実体バイトを見て動くのは pin 側 (pinned_column_bytes ->
# ChannelSampleCache.set_reserved) だけで、ここを「48 MB の予算」と読んではならない。
_DEFAULT_RESOLVED_CAPACITY = 512

# pin が容量を食い尽くしても非 pin 用に必ず残す枠 (spec §5.5 の「LRU の最低容量を
# 無条件確保」)。0 にすると pin 過多のとき、鋳造した列が evict 走査の中で **自分自身を**
# 落としてしまい、ブラウザのプレビュー 1 本ごとにフルチャンネル再読みが復活する。
_MIN_EVICTABLE_COLUMNS = 1

# 高水位 (容量) を超えたら低水位まで一気に空けるヒステリシスの分母。予算ちょうどへ
# 削ると鋳造 1 本ごとに O(現存列) の走査が要り、E-4b の全列エクスポート (264k 鋳造)
# がそこで律速する。1/8 ずつ空ければ走査は鋳造 8 本に 1 度で済む。
_RESOLVED_EVICT_DIVISOR = 8


class _ChannelHit(NamedTuple):
    """列キーを所有する物理チャンネルの探索結果 (``_owning_channel`` の返り値)。

    ``rest`` が空文字 = 渡されたキーが **表示名そのもの** (物理チャンネルであって
    列ではない)。そのときだけ ``path`` は None になる — 鋳造器はここで打ち切り、
    チャンネル解決器 (``channel_key_of``) は「自分自身が所有者」として答える、
    という**唯一の非対称**がこのフィールドに集約されている。
    """

    display: str
    rest: str
    record: ColumnRecord
    path: ColumnPath | None


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
        # 名前空間キャッシュの世代 (E-4b)。lost-update (古いスナップショットの
        # 焼き付け) を閉じるための唯一の観測点で、_invalidate_namespaced が増やし
        # _ensure_namespaced / group_signals が commit 前に照合する。
        self._namespaced_gen = 0
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
        # export 専用 resolve の鋳造回数 (MG-1)。**mint_count とは別勘定**にする —
        # mint_count は「帳簿に載った鋳造」の数で、既存テストがその意味で pin して
        # いる。transient を混ぜると全列エクスポートで 330k 増えて意味が壊れる。
        self.transient_mint_count = 0
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
        # E-4b (spec §5.7-2): 連番の read-modify-write と表の更新を **_resolved_lock 下**
        # で不可分にする。今日ロック外なので、2 ファイル同時ドロップで同じキーが
        # 2 グループへ割り当たり後勝ちで 1 つ消える (消えたグループは _groups から
        # 辿れず、その handle は remove -> close へ到達できない = ファイルが開いたまま)。
        # ロード経路 (LoadWorker -> session.load -> add) にこの lock の再入は無い。
        with self._resolved_lock:
            self._counters[prefix] = self._counters.get(prefix, 0) + 1
            key = f"{prefix}_{self._counters[prefix]}"
            self._physical_by_name[key] = self._index_physical(group)
            if column_records:
                # 呼び出し側の dict と縁を切る (ローダーの一時表が後から変わっても
                # 登録済みグループの列構造は動かない)。物理チャンネル数ぶんなので安い。
                self._column_records[key] = dict(column_records)
            # 書き順は「内部表 -> _groups[key] -> _invalidate_namespaced」(I7b)。
            # 「最後に書く」の字義どおり (invalidate -> _groups) にすると、invalidate 後の
            # 間隙で走った再構築が **新グループを含まない** map を焼き付け、次の
            # invalidate までそのファイルの信号が引けない。
            self._groups[key] = group
            self._invalidate_namespaced()
        return key

    def remove(self, key: str) -> tuple[SignalGroup, tuple[Signal, ...]]:
        """グループと、そのグループで鋳造済みの列 Signal を取り出して返す。

        列 Signal は SignalGroup.signals の外に居るため、ここで返さないと
        TeardownService の会計・解放から漏れる。

        Dependency checking against Derived_Signals (Req 4.5) is the Session's
        responsibility; this method removes unconditionally.
        """
        with self._resolved_lock:
            # 在籍表からの pop も **lock の中** (resolve 側の在籍判定と対で意味を持つ)。
            # 外に出すと、resolve が lock 下で「在籍あり」を確認して鋳造している最中に
            # ここが _groups を抜き、_mint_column の self._groups[group_key] が
            # KeyError になる — resolve() の契約 (アンロード済みは None) が破れる。
            try:
                group = self._groups.pop(key)
            except KeyError:
                raise KeyError(
                    f"no Signal_Group registered under key: {key!r}"
                ) from None
            table = self._resolved_by_key.pop(key, {})
            # recency 表からも外す。残すとアンロード済みキーが LRU の枠を食い続け、
            # 生きている列が理由なく落ちる (帳簿の静かなリーク)。
            for column_key in table:
                self._resolved_order.pop(column_key, None)
            columns = tuple(table.values())
            # E-4b: 副表の掃除と無効化も **lock の中** (add() と対称にする)。
            # _mint_column はロック下でこの 2 表を読むので、外に置くと「読みながら
            # 消える」窓が残る。無効化を外に出すと、_groups から消えてから世代が
            # 上がるまでの間隙で走った再構築が「消えたグループを含む map」を
            # 焼き付ける (= 閉じたのに信号が引ける)。
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
        """Drop the namespaced caches; rebuilt lazily on next access.

        **呼び出し側が ``_resolved_lock`` を保持していること** (E-4b)。世代の +1 が
        非アトミックなうえ、これと ``_groups`` の書きが別トランザクションだと
        lost-update の窓が残る。
        """
        self._namespaced_list = None
        self._namespaced_map = None
        self._namespaced_by_key = {}
        self._namespaced_gen += 1
        # NOTE: _resolved_by_key はここで**捨てない** (Critical 1)。捨てると 2 ファイル目の
        # ロードごとに全プロット列が新オブジェクト (空キャッシュ) となり、次の render で
        # フルチャンネル再読み (実測 0.73-1.18 s/列) が走る。切り離しは remove(key) と
        # E-4a の LRU evict のみ。

    def _ensure_namespaced(self) -> tuple[list[Signal], dict[str, Signal]]:
        """Build and cache the namespaced signal list/map once (idempotent).

        The expensive work — creating one namespaced Signal wrapper per signal
        across all groups — happens here a single time per load/unload, not on
        every ``signals()``/``signal_map()`` call (FU-08). The list preserves
        every signal (duplicate namespaced names included); the map is keyed by
        name with last-wins dedupe, matching the historical ``signals()``-to-dict
        behaviour its callers relied on.

        **先頭 2 行 (lock なし高速路) はペアの世代整合を保証しない** (Minor 3):
        ``self._namespaced_list`` と ``self._namespaced_map`` を別々に読むので、
        その間に別スレッドの invalidate → 再構築 → commit が挟まると、古い世代の
        list と新しい世代の map を組にして返しうる。今日の呼び出し側 (``signals()``
        / ``signal_map()``) はどちらか一方しか消費しないので実害は無いが、将来
        両方を**同時に**消費する呼び出し側を足すなら、下のロック付き経路
        (list/map を同じ ``with`` の中で読む) を通すこと — ペアの整合が要るなら
        高速路を素通りしてはならない。

        E-4b (spec §5.7-3): 反復は **スナップショット** に対して行い、書き戻しは
        **世代照合つき** で行う。旧実装は無ロックで ``self._groups.items()`` を直に
        回しており、export worker の resolve が ~18 分走る本増分では
        ``dictionary changed size during iteration`` が窓ではなく常態になる。

        ビルドを lock の中でやらないのは、O(全信号) のラッパ構築が export worker の
        取る lock を占有し、正しさの修正が待ちの回帰に化けるため。ただしスナップ
        ショットだけでは **lost-update** (古いスナップショットを構築後に焼き付け、
        新グループが次の invalidate まで見えない) が残るので、commit 時の世代照合で
        閉じる。**この 2 段構えが「ロックにしない」ことの対価**であり、片方だけでは
        不完全。

        **無ロック経路は 2 回まで、3 回目は lock 下で作り切る** (I1・実測):
        「ロックにしない」対価には裏があり、add churn がビルド時間より速いと
        無ロック経路は commit のたびに世代がずれて**無限に負け続ける** — 修正前は
        進行の保証が無く、``resolve()`` (GUI の render パスと 18 分走る export
        worker の両方が通る最もホットな経路) がスレッドを握ったまま戻らない。
        実測 (prod 形 4,324 チャンネル・ロック外ビルド 1 回 76 ms・add 間隔 0.5 ms の
        連続 churn): 修正前は resolve() が 2 秒に 1 回しか完了せず最大待ち
        3,113 ms、``attempt >= 3`` の前進保証を入れた後は 7,852 完了・最大待ち
        163 ms。3 回目に限り lock を手放さずスナップショット取得から commit まで
        終わらせる (下の実装参照) — ``add()``/``remove()`` も同じ lock を取るので
        その中では churn が起こりえず必ず前進する。「O(全信号) の構築を lock 下で
        やらない」という上の意図は *毎回* ではなく *通常経路 (attempt 1-2)* の話
        として保たれる: 3 回目に限り、正しさ (有界な前進) を lock 保持時間より
        優先する。

        **値を返すのが契約** (brief の ``-> None`` からの意図的逸脱・報告済み):
        呼び出し側が ``self._namespaced_map`` を**もう一度**読む形にすると、その
        1 バイトコードの隙に別スレッドの add/remove が invalidate して None になり、
        ``resolve()`` (E-4b で最もホットな経路) が AttributeError で落ちる。返り値
        経由なら呼び出し側は自分が見たスナップショットを握り続けられる。
        """
        cached_list = self._namespaced_list
        cached_map = self._namespaced_map
        if cached_list is not None and cached_map is not None:
            return cached_list, cached_map
        attempt = 0
        while True:
            attempt += 1
            with self._resolved_lock:
                cached_list = self._namespaced_list
                cached_map = self._namespaced_map
                if cached_list is not None and cached_map is not None:
                    return cached_list, cached_map
                gen = self._namespaced_gen
                # lock 下なので安全 (C の原子性には依存しない — この行を with の
                # 外へ出さないこと。Minor 2)。
                snapshot = list(self._groups.items())
                if attempt >= 3:
                    # 前進保証 (I1): ここへ来るのは無ロック経路が 2 回とも churn に
                    # 負けた後だけ。lock を握ったまま作り切る — add()/remove() も
                    # この lock を取るので、この中では二度と負けない。_namespaced()
                    # は Signal ラッパの構築のみで I/O を行わないので lock 下で
                    # 呼んでよい (docstring の測定値・上のコメント参照)。
                    built = [s for k, g in snapshot for s in self._namespaced(k, g)]
                    built_map = {sig.name: sig for sig in built}
                    self._namespaced_list = built
                    self._namespaced_map = built_map
                    return built, built_map
            result: list[Signal] = []
            for group_key, group in snapshot:
                result.extend(self._namespaced(group_key, group))
            mapping = {sig.name: sig for sig in result}
            with self._resolved_lock:
                if self._namespaced_gen != gen:
                    continue  # 途中で add/remove が入った — 作り直す (lost-update 閉鎖)
                cached_list = self._namespaced_list
                cached_map = self._namespaced_map
                if cached_list is not None and cached_map is not None:
                    # 同世代で別スレッドが先に commit 済み — 正典を返す
                    # (同じ入力から作った等価物なので、どちらでも値は同じ)。
                    return cached_list, cached_map
                self._namespaced_list = result
                self._namespaced_map = mapping
                return result, mapping

    def group_signals(self, key: str) -> list[Signal]:
        """Namespaced signals for a single group (KeyError if key is unknown).

        Lets callers fetch one file's signals without scanning every group.
        Cached per key on the same invalidation lifecycle as the whole-session
        caches (FU-08); rebuilt only after add()/remove(). Prevents the
        per-call rebuild of every namespaced wrapper (FU-11).

        E-4b: per-key キャッシュにも ``_ensure_namespaced`` と同じ lost-update が
        あるので、書き戻しは世代照合つきで行う (下のコメント参照)。
        """
        with self._resolved_lock:
            group = self._groups[key]  # 未知 key は従来どおり KeyError
            cached = self._namespaced_by_key.get(key)
            gen = self._namespaced_gen
        if cached is None:
            cached = self._namespaced(key, group)
            with self._resolved_lock:
                # remove 済みキーの復活を防ぐ (復活すると「閉じたのに信号が引ける」
                # 状態が次の invalidate まで残る)。防御的 — 今日は世代照合だけで
                # 足りる (全 `_groups` 変異が同一 lock 下で invalidate を呼ぶため、
                # 世代不変 ⇒ 在籍不変)。在籍再確認は将来 invalidate を伴わない変異が
                # 入った場合の保険。
                if self._namespaced_gen == gen and key in self._groups:
                    self._namespaced_by_key[key] = cached
        return list(cached)  # 防御コピー(signals() と同契約) — Signal は共有

    def signals(self) -> list[Signal]:
        """Return every signal across all groups, name-spaced by its group key."""
        namespaced, _mapping = self._ensure_namespaced()
        return list(namespaced)

    def signal_map(self) -> Mapping[str, Signal]:
        """読み取り専用 ``{namespaced_name: Signal}`` ビュー (FU-08 でキャッシュ)。

        重複した名前空間つき名は last-wins (``signals()`` から dict を作るのと同じ)。
        読み取り専用なので呼び出し側は共有キャッシュを壊せない。

        **非対称 Mapping** (E-1・意図的逸脱): ``[]``/``get``/``in`` は列キーを解決器
        経由で鋳造しうるが、``__iter__``/``len`` は既存 (物理) キーのみを返す。全論理
        キーの列挙は 330k 列を鋳造して ~390 MB を再導入するため提供しない —
        ``dict(signal_map())`` は使ってはならない。
        """
        _namespaced, mapping = self._ensure_namespaced()
        return _ResolvingMap(mapping, self.resolve)

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
        _namespaced, mapping = self._ensure_namespaced()
        hit = mapping.get(key)
        if hit is not None:
            return hit
        group_key = key.split(KEY_SEPARATOR, 1)[0]
        # with の手前で束縛する (channel_cache.put と同型)。with 内の最終文である
        # ことに依存すると、将来 with 内の末尾に分岐が増えたときに束縛未到達の
        # 経路が生まれ UnboundLocalError になる (レビュー M2)。
        evicted: list[Signal] = []
        with self._resolved_lock:
            # グループ在籍の判定は **lock の中** で行う (E-4a T3 レビュー M3)。外で
            # 判定すると、判定を通ったスレッドが lock 待ちで止まっている間に別の
            # スレッドの remove() が完走し、_mint_column の self._groups[group_key] が
            # KeyError を上げて resolve() の外へ漏れる — 呼び出し側は「アンロード
            # 済み = None」しか想定していない。setdefault が remove() の掃除済み
            # エントリを蘇らせるのも同じバグの後半 (帳簿に幽霊グループが残る)。
            # 今日ここへ並行して入る呼び出し元は無いが、E-4b はエクスポート
            # ワーカーをこの経路へ載せる。
            if group_key not in self._groups:
                return None
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
            evicted = self._evict_resolved()
        # 最後の参照は lock の**外**で死ぬ (理由は _evict_resolved の docstring)。
        # ここは GUI の render と E-4b のエクスポートワーカーが**両方**踏む最も
        # ホットな経路で、lock 下で dealloc すると互いに待つ。
        del evicted
        return minted

    def resolve_transient(self, key: str) -> Signal | None:
        """エクスポート専用の列解決 (**帳簿に載せない** — E-4b MG-1)。

        ``resolve()`` との違いはただ 1 点、鋳造した列を ``_resolved_by_key`` /
        ``_resolved_order`` へ**登録しない**こと。生存はブロックローカルの参照だけ
        になり、参照を落とせばその場で消える。

        **なぜ LRU に任せられないか**: 全列エクスポート (330,004 列) を ``resolve()``
        で回すと、容量 512 の LRU の定常が 512 本 = G2 の上限を常時超える。しかも
        選択列が 512 未満の範囲エクスポートでは **1 本も evict されず**、現状の
        114.5 MiB 残留がそのまま残る (spec §5.3)。「LRU に任せる」は機構レス。

        **既に帳簿に在る列は作り直さず、そのまま返す** (二重実体化を避ける) が、
        recency は**動かさない**。動かすと全列エクスポートが LRU の順序表を総なめ
        して、GUI が次に読む列の追い出し順序が壊れる。

        pin・evict・``mint_count`` のいずれにも触れないので、D4 の identity 契約
        (pin 中は同一オブジェクト) は不変。
        """
        # 10a (spec §5.7-3・PR 1d51f85) supersede: `self._ensure_namespaced()` を
        # discard-return で呼び `assert self._namespaced_map is not None` する形は
        # コンパイルもテストも通るが、assert 直後の 1 バイトコードの隙に別スレッドの
        # add/remove が invalidate すると再び None に戻り `.get` が NoneType.get で
        # 落ちる窓を再導入する。返り値経由の形を崩さないこと。
        _namespaced, mapping = self._ensure_namespaced()
        hit = mapping.get(key)
        if hit is not None:
            return hit  # 物理チャンネルは既存オブジェクト (鋳造経路に入らない)
        group_key = key.split(KEY_SEPARATOR, 1)[0]
        with self._resolved_lock:
            # 在籍判定を lock の中で行う理由は resolve() と同一 (E-4a T3 レビュー M3)。
            # E-4b では export ワーカーがこの経路を ~18 分走らせるので、窓が常態化する。
            if group_key not in self._groups:
                return None
            # ``setdefault`` ではなく ``get`` (帳簿に空エントリすら作らない)。
            cached = self._resolved_by_key.get(group_key, {}).get(key)
            if cached is not None:
                return cached  # _touch しない (上記の WHY)
            minted = self._mint_column(group_key, key)
            if minted is not None:
                self.transient_mint_count += 1
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
        # with の手前で束縛する (resolve() と同型・レビュー M2 — 理由は resolve()
        # のコメント参照)。
        evicted: list[Signal] = []
        with self._resolved_lock:
            self._pinned = pinned
            evicted = self._evict_resolved()
        # channel_cache の put / set_reserved と同じ理由で lock の外まで持ち越す。
        del evicted

    def pinned_columns(self) -> frozenset[str]:
        """現在 pin されている列キー集合 (introspection・鋳造しない)."""
        return self._pinned

    def pinned_column_bytes(self) -> int:
        """pin 済みの鋳造列が **今** 保持している配列バイトの合計 (spec §5.5)。

        ``Session.set_pinned_columns`` がこれを ``ChannelSampleCache.set_reserved``
        へ渡す (spec §5.2「予算の裁定者は 1 人」)。pin した列は所有権不変条件
        (spec §5.4) により自前の独立配列を抱えるので、チャンネル 2-D と**同じ**
        U3 256 MB を食う — 渡さないと 2 つの帳簿が互いの解放を当てにして両方が
        上限を超える。

        **数え方は teardown と共有する** (``models.retained_bytes``)。値配列だけを
        数えてはならない: プロット中の列は ``sorted_view()`` が ``astype(float64)``
        で作った**別の実体**も抱えており、非 float64 チャンネルではそちらの方が
        大きい (幅広 uint8 で 8 倍)。過小申告は LRU に「まだ空きがある」と信じさせ、
        pin + キャッシュの合計が予算を超える — ``set_reserved`` が防ぐはずの失敗を
        会計そのものが招く形になる。

        **master は数えない**: 鋳造列は親物理チャンネルの master を**同一
        オブジェクトのまま**共有する (``_mint_column``) ので、ここへ載せると
        グループ側の帳簿と二重計上になる。``seen`` を pin 列すべてで共有するのは、
        同一チャンネルの兄弟列が master を共有する分も 1 回に畳むため。

        **未展開の列は 0**: 鋳造しただけの列は 1 バイトも保持していない
        (``retained_bytes`` は展開を誘発しない)。「鋳造したから食っている」と数えると、
        ブラウザで覗いただけの列がチャンネルキャッシュの容量を削り、最低容量まで
        痩せて再描画ごとのフルチャンネル再読みが復活する。

        pin 集合には物理チャンネルのキーも混ざる (プロットしたのがスカラー信号なら
        鋳造列ではない) が、ここには載らない — 走査するのは ``_resolved_by_key``
        (鋳造列の表) だけで、物理チャンネルの実体はグループ側の会計に属するから。

        **タイミング (仕様として受け入れる)**: この値は次の pin 変化まで更新され
        ないので、pin の後に実体化した列は次の push まで申告に現れない。過小申告は
        LRU の容量を広めに見せるだけで、実際の超過は ``put`` 側の evict が吸収する
        (``bytes_held`` は常に真の値)。

        lock 下で数え切るのは、表のコピーを外へ持ち出すと反復中に別スレッドの
        鋳造で ``dict changed size`` になるから。``retained_bytes`` は展開済み配列の
        nbytes を読むだけで I/O も ``handle.lock`` も触らないので、ロック順の危険は
        無い。
        """
        with self._resolved_lock:
            seen: set[int] = set()
            total = 0
            for table in self._resolved_by_key.values():
                for column_key, signal in table.items():
                    if column_key not in self._pinned:
                        continue
                    seen.add(id(signal.timestamps))  # master はグループ側の帳簿
                    total += retained_bytes(signal, seen)
            return total

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

    def _evict_resolved(self) -> list[Signal]:
        """非 pin の鋳造列を古い順に落として容量へ収め、**外した Signal を返す** (D4)。

        **返り値を捨ててはならない** — 呼び出し側は ``_resolved_lock`` の外まで
        参照を持ち越し、そこで初めて手放すこと (``resolve`` / ``set_pinned_columns``
        の ``del evicted``)。ここで参照を落とすと、鋳造列が抱える実体 (値配列 +
        ``sorted_view`` が作る float64 ビュー・prod 実測 ~108 KB/列) の dealloc が
        この lock の保持下で走る。E-4b でエクスポートワーカーが同じ lock の取り手に
        なった (``resolve_transient`` 経由で ~18 分にわたり繰り返し取得する。
        E-4b spec F6 = defer 根拠の失効) ので、GUI の ``resolve()`` がその dealloc
        を待つ。ロック順は保たれるのでデッドロックには
        ならず、**症状は待ち時間だけで数字にも出ない** — ``channel_cache.
        _evict_oldest`` が同じ理由で同じ形をしている。test-lock は
        ``test_resolved_column_lru.py::test_evicted_columns_are_freed_outside_the_lock``
        (2 経路とも回す)。

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
            return []  # 予算内 — pin の数え直しすらしない (鋳造ホットパスの O(n) 回避)
        pinned_live = sum(1 for k in self._resolved_order if k in self._pinned)
        room = max(self._resolved_capacity - pinned_live, _MIN_EVICTABLE_COLUMNS)
        slack = max(1, room // _RESOLVED_EVICT_DIVISOR)
        keep = max(room - slack, _MIN_EVICTABLE_COLUMNS)
        unpinned = [k for k in self._resolved_order if k not in self._pinned]
        excess = len(unpinned) - keep
        if excess <= 0:
            return []
        evicted: list[Signal] = []
        for column_key in unpinned[:excess]:  # dict は挿入順 = 古い順
            del self._resolved_order[column_key]
            table = self._resolved_by_key.get(column_key.split(KEY_SEPARATOR, 1)[0])
            if table is not None:
                dropped = table.pop(column_key, None)
                if dropped is not None:
                    evicted.append(dropped)
            self.resolved_evictions += 1
        return evicted

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

    def channel_master(self, group_key: str, display_name: str) -> np.ndarray | None:
        """物理チャンネルの master 配列 (**鋳造しない・値を読まない**)。

        見積 (E-4b T-UX) が union と空セル率を出すための唯一の入口。``resolve`` で
        代用すると列を鋳造して LRU の枠を食う (``has_column`` の docstring と同じ理由)。
        鋳造列は親の master を **同一オブジェクトのまま** 共有するので、ここで返す
        配列は列がどれであっても identity dedup の同じ 1 本になる (spec §5.4)。

        **ColumnRecord を持たないグループ (CSV/Derived) だけ**、信号名の線形走査へ
        落ちる。それらは ``physical_channel`` metadata を載せないので物理索引が空で、
        かつ 1 信号 = 1 列なので信号名がそのままチャンネル名になる (``scan_masters``
        の ``metadata.get("physical_channel", sig.name)`` フォールバックと同型)。
        **表を持つグループ (MDF) では走査しない**のが load-bearing: prod の
        330,004 列が全部解決不能な形 (アンロード直後など) になったとき、1 キューに
        つき 4,324 信号を走査すると 1.4e9 回の比較 = 見積が固まる。

        **残る限界 (既知・繰越)**: 表を持たないグループでは 1 チャンネル = 1 列
        なので、全列を見積もると走査は「列数 x 信号数」= O(N^2) になる。本機実測
        (見積全体・`estimate_export`): 500 列 5.9 ms / 2,000 列 74.8 ms /
        5,000 列 458 ms。**`estimate_export(channel_columns=...)` の表を渡しても
        消えない** (表が消すのは列 -> チャンネル解決の方で、走査はチャンネルごとに
        残る — 同条件で 5.3 / 67.5 / 442 ms)。実 ADAS CSV の列幅 (数十〜数百) では
        無視できるが、数千列の CSV が現れたら `_physical_by_name` と同型の索引が要る。
        """
        sig = self._physical_by_name.get(group_key, {}).get(display_name)
        if sig is None and not self._column_records.get(group_key):
            group = self._groups.get(group_key)
            if group is not None:
                sig = next((s for s in group.signals if s.name == display_name), None)
        return None if sig is None else sig.timestamps

    def is_lazy_group(self, group_key: str) -> bool:
        """このグループの samples が **まだファイル側に在る** か (handle を持つか)。

        見積の読みコスト項の母数。CSV/Derived は EagerValues で既に実体化済みなので
        0 秒 — ここを一様に cold 扱いすると、CSV だけの小さな出力でも確認ダイアログが
        「5 秒かかります」と嘘をつく。
        """
        group = self._groups.get(group_key)
        return group is not None and group.handle is not None

    def channel_leaf_count(self, group_key: str, display_name: str) -> int:
        """物理チャンネル 1 本の数値リーフ本数 (**鋳造しない・名前を生成しない**)。

        Task 11 レビュー C1 是正: 見積の読み単価はチャンネル**クラス**
        (scalar=1 リーフ / wide=2+ リーフ) で 480 倍差がある (spike §9-4:
        prod scalar 0.67ms 対 prod wide 338.2ms) ので、単一単価を全チャンネルへ
        掛けると scalar 側が桁で過大になる。この索引は ``total_column_count``
        (グループ全体の総リーフ数) と同じ ``leaf_count(record.spec)`` を**チャンネル
        1 本単位**で返す — 名前列挙 (``column_names_of``) と違い leaf_count は
        構造の深さだけを辿るので (再帰は軸長の掛け算・struct のフィールド和)、幅
        1,100 のチャンネルでも 1,100 本の文字列を作らない。
        表を持たないグループ (CSV/Derived・未知チャンネル) は 1 信号 = 1 列なので
        常に 1。
        """
        record = self._column_records.get(group_key, {}).get(display_name)
        return 1 if record is None else leaf_count(record.spec)

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

    def _owning_channel(self, group_key: str, display_key: str) -> _ChannelHit | None:
        """*display_key* を所有する物理チャンネルを最長一致で確定する。

        探索そのものは ``column_names.owning_candidates`` に**単一実装**として
        置いてある (E-4c G5) — 衝突検出 (``mdf_loader._shadow_diagnostics``) が
        同じ walk を通るので、「この列が消えた」と診断が言う列と鋳造器が実際に
        返す列が構造的にずれない。ここに残るのは**位置**の解決だけで、
        ``ColumnRecord.path_index`` を触るためマネージャの責務である。

        **``has_column`` の走査は畳まないこと** (意図的): あちらは
        ``raw_base_name`` を一切参照しない独立オラクルで、
        ``test_column_roundtrip.py`` の「生 selector 空間が表示空間へ漏れる」変異
        クラスを resolve とは別の観測点から殺している。共有化するとその歯が抜ける。

        ``_mint_column`` の探索ループ**そのもの**を切り出したもの — 鋳造器と
        チャンネル解決器 (``channel_key_of``) はここだけを共有する。**2 実装に
        してはならない**: 見積 (E-4b T-UX) が数えるチャンネルとブロック割当が
        使うチャンネルがずれ、見積の読み項が桁で嘘をつく。

        **鋳造しない・値を読まない**ので見積・計測器から呼べる。返り値が
        ``rest == ""`` のときは「表示名そのもの = チャンネルであって列ではない」で、
        打ち切り条件も ``_mint_column`` と同一 — ``continue`` にすると実チャンネル
        ``A[0]`` が配列 ``A`` の列 0 と字面衝突したとき短い親へ滑り、**別チャンネルの
        値を例外なしで返す**。
        """
        records = self._column_records.get(group_key)
        if not records:
            return None
        for candidate in owning_candidates(display_key, records):
            if not candidate.rest:
                return _ChannelHit(candidate.display, "", candidate.record, None)
            path = _leaf_path(candidate.record, candidate.rest)
            if path is None:
                continue  # 名前は通ったが位置が引けない = この親では解決不能
            return _ChannelHit(
                candidate.display, candidate.rest, candidate.record, path
            )
        return None

    def channel_key_of(self, group_key: str, column_key: str) -> str | None:
        """``"{group_key}::{物理チャンネル表示名}"`` (解決不能なら None・**鋳造しない**)。

        幅 k のチャンネルの列は k 本とも同じ 1 キーへ落ちる — 見積がチャンネル単位で
        読み時間を数えられる根拠そのもの (列ごとに別キーを返すと幅 1,100 の
        チャンネルで読み項が 1,100 倍に見える)。
        """
        _prefix, sep, display_key = column_key.partition(KEY_SEPARATOR)
        if not sep:
            return None  # 名前空間の無いキーは列キーではない (_mint_column と同じ)
        hit = self._owning_channel(group_key, display_key)
        return None if hit is None else f"{group_key}{KEY_SEPARATOR}{hit.display}"

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
        # 親は **表示名** (LD-08 dedup 済み) の最長一致で確定する。表示名は物理
        # チャンネルごとに一意なので、parse_leaf 単体では避けられない生名衝突
        # (同名 2 チャンネルが同じ spec キーを共有する・column_names.parse_leaf の
        # precondition) をここで断てる。探索は `_owning_channel` に 1 実装だけ置く
        # (見積・計測器と共有する — 2 実装にすると数えるチャンネルがずれる)。
        hit = self._owning_channel(group_key, display_key)
        if hit is None or hit.path is None:
            # path is None = 表示名そのもの = 物理チャンネル (容器またはスカラー)
            # であって列ではない。ここで **打ち切る** のが要点 (T7 の第 2 の防波堤):
            # 探索を続けると、実チャンネル `A[0]` が配列 `A` の列 0 と字面衝突した
            # とき、より短い親 `A` がヒットして **別チャンネルの値を例外なしで
            # 返す**。今日この経路が踏まれないのは resolve() が _namespaced_map を
            # 先に見るからで、その前提は「レコードのキー集合 == 発行された Signal
            # 名」という 1:1 不変条件 — 述語ではない。1:1 が崩れた瞬間に誤データの
            # 入口になるので、鋳造器自身でも断つ。
            return None
        parent = self._physical_signal(group_key, hit.display)
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
                hit.record.raw_base_name,
                hit.record.group_index,
                hit.record.channel_index,
                length=len(parent.timestamps),
                # 名前は永続キー・位置は読み経路。両方渡すのが列の契約。
                selector=(f"{hit.record.raw_base_name}{hit.rest}",),
                path=hit.path,
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
