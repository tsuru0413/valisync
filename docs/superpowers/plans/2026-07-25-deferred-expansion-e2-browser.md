# 列展開遅延化 E-2（ブラウザ）実装プラン

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **改訂履歴（2026-07-25・実装着手前）**: 本プランは敵対的レビューで **NEEDS-CHANGES**（**Critical 3 / Important 7 / Minor 4**）。
> 全指摘を本改訂に反映済み — C1 単一列行の実 identity（`single_column`）／C2 `_group_total()` の列単位化／
> C3 フィルタの子合成への伝播と `column_count` の意味固定／I1 `physical_channel` は `signal_name`／
> I2 計測点をフィルタ後まで拡張／I3 名前キャッシュ→**0 MB フィルタメモ**へ差し替え／I4 既存被覆の追随と
> realgui のゲート実行／I5 realgui オラクルの 3 穴／I6 表記規約 R-07・対訳表 G-42 の改訂を成果物化／
> I7 テストコードを実ヘルパのシグネチャ・実 fixture へ再導出／m1 展開時の全走査排除／m2 親行 Unit は空／
> m3 キャッシュのライフサイクル／m4 凍結カタログ指示のトートロジー是正。
> 5 つのユーザー判断点はコントローラ決定済み（Global Constraints と各 Task に反映）。

**Goal:** チャンネルブラウザが「展開後の列」ではなく「物理チャンネル」を消費するようにし、per-列の VM/モデル残渣（実測 87 MB）を落とす。**ローダーはまだ列を展開する**ので、合成した列キーは必ず実 Signal に当たり、ブラウザ単独で検証できる。

**Architecture:** ローダーが各列 Signal に**物理チャンネル名**を metadata として付ける（加算的・挙動不変）。`ChannelBrowserVM` はそれで物理チャンネル単位に prep を作り、`tree_groups()` は葉のリストでなく `(physical_name, unit, base_key, column_count, single_column)` を返す。`SignalTreeModel` は子ノードを**要求時に合成**する。ツリーは**1 行＝1 物理チャンネル**へ平坦化し、件数は列を ch 単位で数え、フィルタは列名にマッチしつつ**フィルタ文字列をキーにした 0 MB のメモ**で 3 パスを 1 パスへ畳む。

**Tech Stack:** Python 3.13 / PySide6 / numpy / pytest。

**設計 spec:** [2026-07-24-deferred-column-expansion-design.md](../specs/2026-07-24-deferred-column-expansion-design.md)（E-2 の節が一次情報源）。前提: [E-0/E-1 プラン](2026-07-24-deferred-expansion-e0-e1.md) 完了済み。

## Global Constraints

- 品質ゲート全通過: `uv run pytest` / `uv run ruff check` / `uv run ruff format --check` / `uv run mypy src/`。
- **ローダーは列展開を続ける**（反転は E-3）。合成した列キーは既存 `signal_map()` で必ず解決できる。
- **文字列解析で物理チャンネルを推測してはならない**。`ACC.Speed`（ドット入りチャンネル名）と `P.x`（構造化フィールド）は文字列では区別できない（quick_demo は 173 中 156 がドット付き）。物理チャンネル名は**ローダー由来の metadata** を使う。

### 不変条件（違反＝サイレント破壊・全 Task で守る）

- **【葉キーの不変条件 / C1・C3・ユーザー判断点3 の共有ルール】**
  **葉ノードの `key` は常に実 Signal キー。`base_key` は親をグループ化するための合成ハンドルであり、決して `_Node.key` に到達しない。**
  行が**現在ちょうど 1 列を提示している**とき（実列数 1、**または**フィルタで一致列が 1 本に落ちた）その行は葉であり、
  **key も表示名もその 1 列の実 identity から採る**。それ以外は `key=None` の親。
  これは現行 `signal_tree_model.py:81-86`（`len(leaves) == 1` 分岐）と**等価挙動＝無回帰**である。
  実 mf4 で再現済みの反例: 形状 (N,1) の 2D → `Mono[0]` ／ 単一数値フィールド構造化 → `P.x` ／
  数値+文字列の混在構造化（非数値リーフは dtype ゲートで落ちる）→ `Q.x`。いずれも `column_count == 1` かつ
  `orig != physical_channel` で、合成 `g::Mono` / `g::P` / `g::Q` は Signal として実在しない。
- **【件数の単位の不変条件 / C2】** 常に `0 <= shown_count() <= _group_total()`。フィルタ無しでは等しい。
  `shown_count()` が列を数える以上 `_group_total()` も列で数える（単位混在で `shown > total` になる）。
- **【フィルタの単一の真実 / C3】** 「一致」の述語（`fl in orig.lower()`）は 1 経路のみ。
  `shown_count()`（一致列総数）・`tree_groups()`（一致列 ≥1 の行）・`column_names_for()`（一致列だけの子行）が
  同じ述語を共有し、件数と子行が乖離できない構造にする。
- **`column_count` はフィルタ非依存の実列数**（`_group_total()` の供給元）。フィルタ側の数は `shown_count()` だけが担い、
  子の行数は `column_names_for()`（絞り込み済み）が担う。**葉/親の判定に `column_count` を使わない**
  （使うとフィルタで 1 列に落ちた行がドラッグ不能な親のままになり、今日できる「絞って→ドラッグ」を壊す）。

### ユーザー決定（変更不可）

1. ツリーは 1 行＝1 物理チャンネルへ**平坦化**（モジュール階層は廃止）。
2. 件数は**列を ch 単位**で「`{total} ch 中 {shown} ch を表示`」。
3. フィルタは**列名にマッチ**する。
4. **列の個別選択は維持する**（展開した子行を単独でプロット/D&D できる）。

> **名前キャッシュは「ユーザー決定」ではない**（旧版の誤記）。spec:79-93 の**技術判断**側にあり、
> コントローラ決定により **E-2 では採らない**（下記）。上記 4 点はメモ案でも完全に保たれる。

### コントローラ決定（本改訂で確定・再質問しない）

1. **名前キャッシュ（E-2 で ≈33 MB／E-3 で 41.7 MB）は E-2 から外す。** 代わりに**フィルタ文字列をキーにした
   0 MB のメモ化**を実装し、入力停止ごとの 3 パスを 1 パスへ畳む（Task 4）。名前キャッシュは **E-3 の条件付き**
   （実測で必要と出たときのみ・E-3 申し送り参照）へ移す。
2. **CSV/Derived は `physical_channel` を持たない**ため 1 列＝1 物理チャンネルになり、CSV ヘッダー
   `Arr[0]`/`Arr[1]` は**もう親行にならない**。CSV に配列展開の概念が無い以上意味論的に正しいので**受容**するが、
   **ユーザー可視の挙動変更**として spec の意図的逸脱リスト（spec:247-255）と docs/design.md 決定履歴へ記録する（Task 4）。
   これで壊れる realgui（唯一の親子ドラッグ Layer C 被覆）は**実 2D mf4 へ移して被覆を保つ**（Task 3）。
3. **フィルタで一致列が 1 本になった行は今日どおり葉**（その列の実キーでドラッグ可能）。上記
   「葉キーの不変条件」で C1 と同じ 1 つのルールとして表現済み。
4. **件数に桁区切りは付けない**（現行 `CHANNEL_HEADER_COUNT_TMPL` の挙動を保存。spec:71 の「330,004」は
   散文表記でありフォーマット指定ではない）。本増分で数値フォーマットは変えない。
5. **親行（複数列）の Unit セルは空のまま**（UX-29 の設計根拠＝親は空・実体は子を維持。単位集約は増分5 の記録済み defer）。
   実装者が「親切心で」集約単位を出さないこと（混在単位の構造化チャンネル `P.x`=m / `P.t`=s で誤表示になる）。

### その他

- GUI 変更は Layer A/B（CI）必須・Layer C（`--realgui`）で ①ゲート。
- コメントは WHY を書く。DRY / YAGNI / TDD。
- 実装はブランチ `feature/lazy-load-samples` 上。main 直接編集禁止。

## E2E 受け入れ設計（/gui-test-plan）

| 効果 | E2E タイプ | 実 observable | prod スケール | 実経路 exercise |
|---|---|---|---|---|
| ツリーが 1 行＝1 物理チャンネルへ平坦化 | 描画＋入力経路(C) | 実ディスプレイでトップレベル行が**物理チャンネル**（`ACC.Speed`/`ACC.Accel` が別行・`"ACC"` は存在しない）・**配列チャンネルを実クリックで展開すると列が出る** | 不要（合成 fixture で構造が出る・quick_demo は補助） | 実 MainWindow＋実クリック |
| 件数表示が列を ch 単位で出る | 描画 | 実ヘッダー文字列（フィルタ前後） | 不要 | 実 VM→実ラベル |
| 列名フィルタが効く | 入力経路(C) | 実タイピング（**英数字のみ**）で親が絞り込まれ、**展開した子行が一致列だけ**になる | 不要 | 実キー入力 |
| **列の個別選択が生きている**（ユーザー決定 4） | 入力経路(C) | **配列チャンネルの子行**を実クリック→右クリック「アクティブパネルへ追加」→ `panel.signal_keys_drawn()` に含まれ `panel.curve_xy(entry_id)` が非空 | 不要 | 実 MainWindow＋実クリック |
| **VM/モデル残渣の削減** | perf | **psutil 実測**: (a) prep＋tree_groups 後に **−約 87 MB**（`_prep` 68 MB＋`_Node.leaves` 19 MB）／(b) **1 回のフィルタ適用を通した後**の増分が **≈0 MB**（メモ案の検証） | **必須（prod_demo）** | 実 GUI ロード経路 |

- **必要レイヤー**: A=必須／B=要（VM の prep・tree_groups・フィルタ・件数）／入力経路 E2E(C)=要（平坦化・フィルタ・列の個別選択は実ツリーでしか確認できない）／perf E2E=**要（prod スケール）**／描画 E2E=要。
- **①証拠ゲート**: `uv run pytest --realgui tests/realgui/test_channel_tree_flatten_realclick.py -q` ＋ **realgui フル** `uv run pytest --realgui tests/realgui/ -q` ＋証拠添付。
- **honest layering note**: 「行数が減った」だけでは残渣削減の証拠にならない（`is_materialized` と RSS の関係と同じ）。**psutil 実測**と**行数/構造の実機確認**の両方が要る。さらに**フィルタ前の RSS だけでは定常値を測ったことにならない**（旧版の測定点はメモ/キャッシュが存在し得ない唯一の瞬間だった）。
- **凍結カタログ（m4・トートロジー是正）**: 撮影 fixture は 2 列 CSV（`t,EngineSpeed,VehSpd`・`scripts/capture_ui_screenshots.py:29-33`）で**ドット付き名も配列チャンネルも含まない**ため、**ツリー行構造は新旧とも 2 行で不変**（単一列チャンネルは葉になるので展開アイコンも出ない）。期待差分は**チャンネルドックのヘッダー文言のみ**。`--crop-meta` は `_ChannelTree.sizeHint` が定数 `_TREE_SIZEHINT_WIDTH = 198`（`channel_browser_view.py:64-77`・行数非依存）で中央ジオメトリが動かないため**必ず一致する（トートロジー）** — これを「平坦化を検証した」と読み替えないこと。平坦化・要求時合成の一次証拠は Task 5 の realgui が担い、カタログの役割は「チャンネルドック外へ波及していないこと」の凍結のみ（**意図的ギャップ**）。

---

## Task 1: ローダーが物理チャンネル名を metadata に付ける（加算的・挙動不変）

**Files:**
- Modify: `src/valisync/core/loaders/mdf_loader.py`（Signal 構築部）
- Test: `tests/core/loaders/test_physical_channel_metadata.py`（新規）

**Interfaces:**
- Produces: 展開列の Signal は `metadata["physical_channel"]` に**曖昧化済み**物理チャンネル名（`signal_name`）を持つ。
  LD-08 dedup が無ければ `base_name` と同値、あれば `base_name[idx]`。非展開（1D）チャンネルも同じキーを持つ（値は自身の `signal_name`）。

> **なぜ `base_name` ではなく `signal_name` か（I1）**: `mdf_loader.py:481-484` は `name_total[base_name] > 1` のとき
> `signal_name = f"{base_name}[{idx}]"` を鋳造する。つまり**別の物理チャンネル（別 gi/ci・別 shape/unit）が同じ
> `base_name` を共有しうる**（`tests/test_loaders.py:306-320` が 2 本の `sig` → `{'sig[0]','sig[1]'}` を実証済み）。
> 生 `base_name` を刻むと Task 2 がこの 2 本を 1 行へ融合し、`base_key = "grp::sig"` はどの Signal にも当たらない
> ＝Task 1 が自称する「ローダー由来の真の同一性」を Task 1 自身が満たさない。さらに `idx` は dtype ゲート・
> 非有限 master 除外・skip_keys より**前**に採番されるため、片方が落ちると生き残り 1 本が `column_count == 1` の
> 葉になり合成キーが死ぬ。`out_leaves = _explode_samples(signal_name, samples)`（:497）なので `signal_name` は
> 全 `out_name` の厳密な接頭辞であり、1 列チャンネルでは**列キーそのもの**になる。
> selector 側の生名は `LazyMdfValues` が別に保持しているので影響しない。

- [ ] **Step 1: 失敗テストを書く**

`tests/core/loaders/test_physical_channel_metadata.py`:

```python
"""列 Signal は自分がどの物理チャンネル由来かを metadata で持つ。

ブラウザが「1 行＝1 物理チャンネル」を作るのに文字列解析を使えないため
(ドットはチャンネル名にもフィールド区切りにも現れる)、グループ化キーは
ローダー由来の真の同一性でなければならない。
"""

from __future__ import annotations

from pathlib import Path

from tests.mdf4_helpers import CAN, write_mdf4, write_mdf4_2d
from valisync.core.loaders.mdf_loader import MdfLoader


def test_expanded_columns_carry_physical_channel_name(tmp_path: Path) -> None:
    # write_mdf4_2d は引数 tmp_path のみ・固定 mat2d.mf4 に Mat(4x3 uint8) と
    # スカラー Clean を書く -> 展開後は Mat[0..2] + Clean = 4 列 / 2 物理チャンネル。
    path = write_mdf4_2d(tmp_path)
    sg = MdfLoader().load(path, confirm_expansion=None).signal_group
    assert sg is not None
    cols = [s for s in sg.signals if s.name.startswith("Mat[")]
    assert len(cols) == 3
    assert {s.metadata["physical_channel"] for s in cols} == {"Mat"}
    clean = next(s for s in sg.signals if s.name == "Clean")
    assert clean.metadata["physical_channel"] == "Clean"


def test_scalar_channel_carries_its_own_name(tmp_path: Path) -> None:
    path = write_mdf4(
        tmp_path / "scalar.mf4",
        [{"name": "Spd", "bus_type": CAN, "timestamps": [0.0, 1.0], "values": [1.0, 2.0]}],
    )
    sg = MdfLoader().load(path, confirm_expansion=None).signal_group
    assert sg is not None
    sig = next(s for s in sg.signals if s.name == "Spd")
    assert sig.metadata["physical_channel"] == "Spd"


def test_duplicate_raw_names_are_two_distinct_physical_channels(tmp_path: Path) -> None:
    """LD-08: 同名チャンネル 2 本は別の物理チャンネル。生 base_name を刻むと
    両方 'sig' になり Task 2 が 1 行へ融合して死にキーを作る (I1)。"""
    path = write_mdf4(
        tmp_path / "dup.mf4",
        [
            {"name": "sig", "bus_type": CAN, "timestamps": [0.0, 1.0], "values": [1.0, 2.0]},
            {"name": "sig", "bus_type": CAN, "timestamps": [0.0, 1.0], "values": [3.0, 4.0]},
        ],
    )
    sg = MdfLoader().load(path, confirm_expansion=None).signal_group
    assert sg is not None
    assert {s.metadata["physical_channel"] for s in sg.signals} == {"sig[0]", "sig[1]"}
```

> **実装者へ（I7）**: `tests/mdf4_helpers.py` の**シグネチャまで**確認すること。
> `write_mdf4_2d(tmp_path)` は**引数なし**で固定の `Mat`(4x3)＋`Clean` を書く／
> `write_mdf4(path, channels)` の `channels` は **dict のリスト**（キー: `name` / `timestamps` / `values` /
> `bus_type` / `source_name` / `unit` / `comment`）。**観測値に合わせて期待値を書き換えるのではなく、
> 期待値を fixture から導出すること**。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/core/loaders/test_physical_channel_metadata.py -q`
Expected: FAIL（`KeyError: 'physical_channel'`）

- [ ] **Step 3: ローダーで metadata を付ける**

`mdf_loader.py` の `out_metadata` 構築サイト（:550 近傍・`deduplicated` 分岐と同スコープ）に追加:

```python
                # ブラウザの「1 行=1 物理チャンネル」グループ化キー。文字列解析では
                # ACC.Speed (チャンネル名) と P.x (構造化フィールド) を区別できない。
                # 生 base_name ではなく signal_name を使う: LD-08 で name_total>1 のとき
                # base_name は別の物理チャンネル (別 gi/ci・別 shape/unit) と共有され
                # 同一性を失う。selector 側の生名は LazyMdfValues が別に保持している。
                out_metadata["physical_channel"] = signal_name
```

> **メモリ増分について（I2-5・実装者が無い give-back を探さないように）**: prod_demo の 264,004 Signal は
> metadata が key 数 3（264,000 件）/4（4 件）で全て `sizeof` 184 B。CPython の dict は 5 キーまで 184 B の
> ままなので `physical_channel` 追加でリサイズは起きず、値も既存 str の共有参照ゆえ**増分ゼロ**（実測）。
> 本増分の give-back は無い（名前キャッシュは採らない — コントローラ決定 1）。

- [ ] **Step 4: 通ることを確認 + 既存ローダーテスト全通過**

Run: `uv run pytest tests/core/loaders/ tests/test_loaders.py -q`
Expected: PASS（metadata の追加は加算的で既存の診断・命名・展開規約に影響しない）

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/core/loaders/mdf_loader.py tests/core/loaders/test_physical_channel_metadata.py
git commit -m "feat(core): 列 Signal に物理チャンネル名 metadata を付与 (ブラウザのグループ化キー)"
```

---

## Task 2: VM の prep を物理チャンネル単位にし、`tree_groups()` が仕様を返す

**Files:**
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py`
- Modify: `tests/mdf4_helpers.py`（新ヘルパ 2 本）
- Test: `tests/gui/test_channel_browser_vm.py`（既存を追随）＋`tests/gui/test_channel_browser_physical.py`（新規）

**Interfaces:**
- Consumes: `metadata["physical_channel"]`（Task 1）
- Produces:
  - `ChannelBrowserVM._prep: list[tuple[str, str, str, int, tuple[str, str], list[tuple[int, int]]]]`
    — `(physical_name, unit, base_key, column_count, first_column, spans)`。**フィルタ非依存**。
    - `first_column` = 最初に見た列の**実 identity** `(orig, ns_name)`（`_ensure_prep` は既に全 Signal を 1 回
      走査しているのでコスト増ゼロ）。
    - `spans` = `self._group_sigs` 上のこの物理チャンネルの列の位置区間リスト。走査で**構築した実測値**なので
      連続性の仮定を置かない（LD-08 や interleave で非隣接ブロックになりうる）。
    - **`lower`（小文字化した名前）は持たない** — これが 68 MB の本体。フィルタは Task 4 のメモが担う。
  - `tree_groups() -> list[tuple[str, str, str, int, tuple[str, str] | None]]`
    — `(physical_name, unit, base_key, column_count, single_column)`（**葉のリストは返さない**）。
    - `base_key` = `f"{active_key}{KEY_SEPARATOR}{physical_name}"`。**これは合成ハンドルであって Signal キーではない**。
    - `column_count` = **フィルタ非依存の実列数**。
    - `single_column` = その行が**現在ちょうど 1 列を提示している**ときのみ `(orig, ns_name)`、それ以外 None。
      （フィルタ空なら「実列数 1」、フィルタ時は「一致列が 1 本」— 葉キーの不変条件を 1 つの値で表現する）
    - フィルタで**一致列 0 の行は返さない**。
  - `column_names_for(base_key: str) -> list[tuple[str, str, str]]` — `(orig, unit, key)`。
    その物理チャンネルの列のうち**現在のフィルタに一致するものだけ**を返す（フィルタ空なら全列）。
    走査は**その行の span だけ**（`group_signals` 全走査は禁止 — prod 264,004 件で展開ごと ~100-130 ms）。
  - `shown_count() -> int` — **一致した列の総数**（件数表示が列基準のため）。
  - `_group_total() -> int | None` — **フィルタ非依存の総列数**（`sum(row[3] for row in self._prep)`）。
- **不変条件**: `0 <= shown_count() <= _group_total()`・フィルタ無しでは等しい。
  `tree_groups()` の各行の `single_column` が非 None なら、その `ns_name` は `session.signal_map()` で解決する。
  `column_names_for()` が返す全 `key` も同様。

> **なぜ `_materialize` から `column_names_for` を呼ぶのに `group_signals` 全走査を使わないか（m1）**:
> `group_signals()` は防御コピー `list(cached)` を返す（`signal_group_manager.py:151`・prod で ~2 ms・
> 2.1 MB/回）。展開のたびに呼ぶと `4,324 行 × 264,004 Signal` の O(n²) になり E-2 の目的と正面衝突する。
> リストは `_prep` 構築時に 1 回だけ掴み `_prep_valid` と同じ寿命で `self._group_sigs` に持つ
> （264k ポインタ＝2.1 MB・Signal 実体は共有なので新規メモリではない）。
> **`_rebuild` から `column_names_for()` を呼ぶ代替案は採らないこと**（同じ O(n²) になる）。

- [ ] **Step 1: 失敗テストを書く**

まず `tests/mdf4_helpers.py` にヘルパを 2 本足す（**合成 Signal では再現しないので実 asammdf ラウンドトリップ必須**）:

```python
def write_mdf4_single_column_shapes(tmp_path: Path) -> Path:
    """「展開したのに列が 1 本」になる 3 形状 + スカラー — C1 の RED fixture.

    ローダー実測: Mono[0] (形状 (N,1) の 2D) / P.x (単一数値フィールド構造化) /
    Q.x (数値+文字列の混在構造化 — 非数値リーフは dtype ゲートで落ちる) / Clean。
    いずれも column_count == 1 かつ orig != physical_channel なので、合成した
    base_key (g::Mono / g::P / g::Q) を葉キーにすると「見えるのに永久に
    描かれない行」になる (実 Signal として存在しない)。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        mdf.append(
            [
                ASignal(
                    samples=np.arange(4, dtype=np.uint8).reshape(4, 1),
                    timestamps=ts,
                    name="Mono",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [(1.0,), (2.0,), (3.0,), (4.0,)], dtype=[("x", "<f8")]
                    ),
                    timestamps=ts,
                    name="P",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array(
                        [(1.0, b"ab"), (2.0, b"cd"), (3.0, b"ef"), (4.0, b"gh")],
                        dtype=[("x", "<f8"), ("tag", "S2")],
                    ),
                    timestamps=ts,
                    name="Q",
                )
            ]
        )
        mdf.append(
            [
                ASignal(
                    samples=np.array([1.0, 2.0, 3.0, 4.0]), timestamps=ts, name="Clean"
                )
            ]
        )
        path = tmp_path / "single_cols.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path


def write_mdf4_interleaved_arrays(tmp_path: Path) -> Path:
    """配列 / スカラー / 配列 の順 — 列 span が連続性に依存しないことの pin.

    ローダー実測: A[0], A[1], S, B[0], B[1]。
    """
    ts = np.array([0.0, 0.1, 0.2, 0.3])
    mdf = MDF()
    try:
        for name, samples in (
            ("A", np.array([[0, 1], [2, 3], [4, 5], [6, 7]], dtype=np.uint8)),
            ("S", np.array([1.0, 2.0, 3.0, 4.0])),
            ("B", np.array([[8, 9], [10, 11], [12, 13], [14, 15]], dtype=np.uint8)),
        ):
            mdf.append([ASignal(samples=samples, timestamps=ts, name=name)])
        path = tmp_path / "interleaved.mf4"
        mdf.save(path, overwrite=True)
    finally:
        mdf.close()
    return path
```

`tests/gui/test_channel_browser_physical.py`（新規）:

```python
"""ブラウザは物理チャンネル単位で行を作る (1 行 = 1 物理チャンネル)。"""

from __future__ import annotations

from pathlib import Path

from tests.mdf4_helpers import (
    CAN,
    write_mdf4,
    write_mdf4_2d,
    write_mdf4_interleaved_arrays,
    write_mdf4_single_column_shapes,
)
from valisync.gui.viewmodels.app_viewmodel import AppViewModel
from valisync.gui.viewmodels.channel_browser_vm import ChannelBrowserVM


def _vm_for(path: Path) -> tuple[ChannelBrowserVM, AppViewModel]:
    app_vm = AppViewModel()
    key = app_vm.request_load(path)  # MDF4 は format_def 不要
    app_vm.set_active_file(key)
    return ChannelBrowserVM(app_vm), app_vm


def _vm(tmp_path: Path) -> ChannelBrowserVM:
    # write_mdf4_2d = Mat 3 列 + Clean 1 列 -> 2 行 / 4 列
    return _vm_for(write_mdf4_2d(tmp_path))[0]


def test_tree_groups_is_one_row_per_physical_channel(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    rows = vm.tree_groups()
    names = [name for name, _unit, _key, _n, _single in rows]
    assert names == ["Mat", "Clean"]
    assert not any(n.startswith("Mat[") for n in names)  # 列は行にならない
    mat = next(r for r in rows if r[0] == "Mat")
    assert mat[3] == 3  # column_count
    assert mat[4] is None  # 複数列 -> 親 (single_column なし)


def test_dotted_channel_name_is_not_split(tmp_path: Path) -> None:
    # ACC.Speed は「ACC の下の Speed」ではなく 1 本の物理チャンネル (平坦化)
    path = write_mdf4(
        tmp_path / "dot.mf4",
        [
            {"name": "ACC.Speed", "bus_type": CAN, "timestamps": [0.0, 1.0], "values": [1.0, 2.0]},
            {"name": "ACC.Accel", "bus_type": CAN, "timestamps": [0.0, 1.0], "values": [3.0, 4.0]},
        ],
    )
    vm, _app_vm = _vm_for(path)
    names = [name for name, _u, _k, _n, _s in vm.tree_groups()]
    assert names == ["ACC.Speed", "ACC.Accel"]  # "ACC" 1 行ではない


def test_column_names_for_returns_only_that_channels_columns(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    mat = next(r for r in vm.tree_groups() if r[0] == "Mat")
    cols = vm.column_names_for(mat[2])
    assert [c[0] for c in cols] == ["Mat[0]", "Mat[1]", "Mat[2]"]


def test_shown_count_counts_columns_not_rows(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    # Mat の 3 列 + Clean の 1 列 = 4 (行数 2 ではない)
    assert vm.shown_count() == 4


def test_single_column_rows_carry_the_real_column_identity(tmp_path: Path) -> None:
    """C1: 「展開したのに 1 列」の行は、合成 base_key ではなく実列の identity を持つ。

    sabotage: single_column の代わりに base_key/physical_name を返すと 3 本とも RED。
    """
    vm, app_vm = _vm_for(write_mdf4_single_column_shapes(tmp_path))
    rows = {name: (base_key, n, single) for name, _u, base_key, n, single in vm.tree_groups()}
    assert set(rows) == {"Mono", "P", "Q", "Clean"}
    sig_map = app_vm.session.signal_map()
    for phys, expected_orig in (
        ("Mono", "Mono[0]"),
        ("P", "P.x"),
        ("Q", "Q.x"),
        ("Clean", "Clean"),
    ):
        base_key, n, single = rows[phys]
        assert n == 1, f"{phys} should have exactly one column"
        assert single is not None, f"{phys}: single_column must carry the real column"
        orig, ns_name = single
        assert orig == expected_orig
        assert sig_map.get(ns_name) is not None, f"{ns_name} must resolve to a Signal"
        if phys != "Clean":
            # 合成ハンドルは実在しない — これを葉キーにするのが C1 のバグ
            assert sig_map.get(base_key) is None


def test_duplicate_raw_names_stay_two_rows(tmp_path: Path) -> None:
    """I1: LD-08 同名チャンネルは 2 行 (現行 _base_of の融合挙動の意図的 supersede)。"""
    path = write_mdf4(
        tmp_path / "dup.mf4",
        [
            {"name": "sig", "bus_type": CAN, "timestamps": [0.0, 1.0], "values": [1.0, 2.0]},
            {"name": "sig", "bus_type": CAN, "timestamps": [0.0, 1.0], "values": [3.0, 4.0]},
        ],
    )
    vm, app_vm = _vm_for(path)
    rows = vm.tree_groups()
    assert [name for name, *_rest in rows] == ["sig[0]", "sig[1]"]
    sig_map = app_vm.session.signal_map()
    for _name, _u, _bk, n, single in rows:
        assert n == 1 and single is not None
        assert sig_map.get(single[1]) is not None


def test_column_spans_do_not_assume_contiguity(tmp_path: Path) -> None:
    """m1: 配列 / スカラー / 配列 の順でも各行が自分の列だけを返す。"""
    vm, _app_vm = _vm_for(write_mdf4_interleaved_arrays(tmp_path))
    by_name = {name: base_key for name, _u, base_key, _n, _s in vm.tree_groups()}
    assert [c[0] for c in vm.column_names_for(by_name["A"])] == ["A[0]", "A[1]"]
    assert [c[0] for c in vm.column_names_for(by_name["B"])] == ["B[0]", "B[1]"]
    assert [c[0] for c in vm.column_names_for(by_name["S"])] == ["S"]


def test_every_exposed_key_resolves(tmp_path: Path) -> None:
    """恒久ガード: VM が外へ出す全キーが実 Signal に当たる (葉キーの不変条件)。"""
    vm, app_vm = _vm_for(write_mdf4_single_column_shapes(tmp_path))
    sig_map = app_vm.session.signal_map()
    for _name, _u, base_key, _n, single in vm.tree_groups():
        if single is not None:
            assert sig_map.get(single[1]) is not None
        for _orig, _unit, key in vm.column_names_for(base_key):
            assert sig_map.get(key) is not None
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_channel_browser_physical.py -q`
Expected: FAIL（`tree_groups()` が 2-tuple を返す・`column_names_for` 未定義）

- [ ] **Step 3: VM を書き換える**

`channel_browser_vm.py`:

1. `_base_of` と `_BASE_RE` を**削除**（文字列解析は使わない）。
2. `__init__` に `self._group_sigs: list[Signal] = []` と `self._row_by_base_key: dict[str, int] = {}` を足す
   （どちらも `_prep` と同じ寿命）。`self._prep` の型注釈を新形へ。
3. `_ensure_prep` を物理チャンネル単位に:

```python
    def _ensure_prep(self) -> None:
        """物理チャンネル単位の (name, unit, base_key, column_count, first_column,
        spans) を active file ごとに 1 度だけ作る。

        グループ化キーはローダー由来の metadata['physical_channel'] — 文字列解析では
        ACC.Speed (チャンネル名) と P.x (構造化フィールド) を区別できないため。
        E-2 時点ではローダーがまだ列を展開するので、ここで列を物理チャンネルへ畳む。
        小文字化した列名は **持たない** (旧 _prep の 68 MB の本体) — フィルタは
        _ensure_filter_memo が 1 パスで解決する。
        """
        active_key = self._app_vm.active_file_key
        if self._prep_valid and self._prep_key == active_key:
            return
        self._filter_memo = None  # prep が変われば絞り込み結果も無効
        if not active_key:
            self._prep = []
            self._group_sigs = []
            self._row_by_base_key = {}
            self._prep_key = active_key
            self._prep_valid = True
            return
        # 防御コピー list(cached) は prod で ~2 ms / 2.1 MB (264k ポインタ・Signal 実体は
        # 共有)。column_names_for が展開のたびに再取得しないよう _prep と同じ寿命で持つ。
        group_sigs = self._app_vm.session.group_signals(active_key)
        prep: list[tuple[str, str, str, int, tuple[str, str], list[tuple[int, int]]]] = []
        row_by_base_key: dict[str, int] = {}
        for i, sig in enumerate(group_sigs):
            ns_name = sig.name
            orig = (
                ns_name.split(KEY_SEPARATOR, 1)[1] if KEY_SEPARATOR in ns_name else ns_name
            )
            md = sig.metadata or {}
            # CSV/Derived は physical_channel を持たない = 1 列 1 物理チャンネル
            # (意図的逸脱・Global Constraints コントローラ決定 2)。
            phys = str(md.get("physical_channel") or orig)
            # base_key は「親をグループ化するための合成ハンドル」であって Signal キー
            # ではない (Mono / P / Q は実在しない)。葉の key には決して使わない。
            base_key = f"{active_key}{KEY_SEPARATOR}{phys}"
            row = row_by_base_key.get(base_key)
            if row is None:
                row_by_base_key[base_key] = len(prep)
                unit = str(md.get("unit", ""))
                prep.append((phys, unit, base_key, 1, (orig, ns_name), [(i, i + 1)]))
            else:
                name, unit, bk, n, first, spans = prep[row]
                last_start, last_stop = spans[-1]
                # 連続なら区間を伸ばし、そうでなければ新区間 (連続性は仮定でなく実測)
                if last_stop == i:
                    spans[-1] = (last_start, i + 1)
                else:
                    spans.append((i, i + 1))
                # unit は「最初に見た列」のもの。集約しない — 親行の Unit は空
                # (UX-29: 親は空・実体は子。混在単位の P.x=m / P.t=s で誤表示になる)。
                prep[row] = (name, unit, bk, n + 1, first, spans)
        self._prep = prep
        self._group_sigs = group_sigs
        self._row_by_base_key = row_by_base_key
        self._prep_key = active_key
        self._prep_valid = True
```

4. `tree_groups()` は葉を作らず上記 5-tuple のリストを返す（**フィルタ適用は Task 4 のメモ経由**。
   Task 2 の時点では「フィルタ空 = 全行・`single_column = first_column if column_count == 1 else None`」で足りる）。
   既存の `except KeyError: return []` ガードは**そのまま維持**する（FU-22 A/B の production 到達経路）。
5. `column_names_for(base_key)` を新設:

```python
    def column_names_for(self, base_key: str) -> list[tuple[str, str, str]]:
        """base_key の物理チャンネルの列を (orig, unit, key) で返す。

        走査はその行の span (最大でそのチャンネルの列数) だけ — group_signals 全走査
        (prod 264,004) を展開のたびに走らせない (O(n^2) 回避)。
        Task 4 で「現在のフィルタに一致する列だけ」へ絞る (述語は _ensure_filter_memo と
        共有 — 件数と子行が乖離できない構造にする)。
        """
        self._ensure_prep()
        row = self._row_by_base_key.get(base_key)
        if row is None:
            return []
        out: list[tuple[str, str, str]] = []
        for start, stop in self._prep[row][5]:
            for sig in self._group_sigs[start:stop]:
                ns_name = sig.name
                orig = (
                    ns_name.split(KEY_SEPARATOR, 1)[1]
                    if KEY_SEPARATOR in ns_name
                    else ns_name
                )
                md = sig.metadata or {}
                out.append((orig, str(md.get("unit", "")), ns_name))
        return out
```

6. `shown_count()` は**列数**を返す（Task 2 時点＝フィルタ無しなら `_group_total()` と同値）。
7. **`_group_total()` を「フィルタ非依存の総列数」へ変える（C2）**:

```python
        # shown_count() が列を数える以上 total も列で数える。行数のままだと
        # prod で「4,324 ch 中 264,004 ch を表示」= shown > total の自己矛盾になる
        # (ユーザー決定 4)。empty_state() の total == 0 分岐は変更不要 —
        # チャンネルは必ず 1 列以上持つので「列 0」と「チャンネル 0」は同値
        # (実装者が『ついでに直す』のを防ぐため明記)。
        return sum(row[3] for row in self._prep)
```

   None ガード（active_key 無し／`_ensure_prep()` の KeyError）は**現行のまま維持**。
8. `inspect()["signal_count"]` は `shown_count()` の実体なので意味が「列数」へ揃う
   （現状も 1 Signal = 1 列なので値は不変）。docstring を更新する。

- [ ] **Step 4: 通ることを確認 + 既存 VM テストを追随**

Run: `uv run pytest tests/gui/test_channel_browser_vm.py tests/gui/test_channel_browser_physical.py -q`
Expected: PASS。

**移送先を名指しで指示する（総論禁止・C3-4 / I4）**:
- `tests/gui/test_channel_browser_vm.py:433-467`（`test_tree_groups_buckets_arrays_under_base`）:
  合成 Signal の `_sig()` に `physical_channel` を持たせ（`_sig("g::Arr[0]", phys="Arr")` /
  `_sig("g::Struct.field", phys="Struct")`）、**実際に親が立つ形のまま**新契約へ書き換える。
  `phys` を付けないと fallback `md.get("physical_channel") or orig` で各列が自分自身の物理チャンネルになり
  **親が 1 つも生まれず assert が vacuous 化する**。
- `tests/gui/test_channel_browser_vm.py:469-517`（`test_tree_groups_honors_filter`）の
  **子レベル assert（:504-508・`set_filter("arr[1]")` → リーフは `["Arr[1]"]`）は削除せず**
  Task 4 で `test_column_names_for_honors_filter` として**等価移送**する
  （`column_names_for(arr_key)` が `["Arr[1]"]` のみを返す）。
  **「親が残ることだけ確認する」形へ弱めてはならない。**
- `tests/gui/test_channel_browser_vm.py:519-544`（`test_shown_count_matches_tree_groups_leaf_total`）:
  「`tree_groups()` の全リーフ数」という概念が消えるので、`sum(column_count)` ベース
  （＝`_group_total()`）と `shown_count()` の関係を検証する形へ移送する。
- **assert を弱めないこと** — 「どの信号が見えるか」を検証しているテストは必ず等価に保つ。

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/gui/viewmodels/channel_browser_vm.py tests/mdf4_helpers.py tests/gui/
git commit -m "feat(gui): チャンネルブラウザの prep を物理チャンネル単位へ (葉の事前生成を廃止)"
```

---

## Task 3: `SignalTreeModel` が子を要求時に合成する（平坦化）

**Files:**
- Modify: `src/valisync/gui/adapters/signal_tree_model.py`
- Modify: `src/valisync/gui/views/channel_browser_view.py`（`_sample_unit_values` の docstring 追随のみ）
- Test: `tests/gui/test_signal_tree_model.py`（既存を追随＋新規ケース）
- Test: `tests/gui/test_channel_browser_view.py`（合成フィクスチャの追随）
- Test: `tests/realgui/test_signal_dnd_realclick.py`（CSV 配列 fixture を実 2D mf4 へ移す）

**Interfaces:**
- Consumes: `tree_groups() -> [(name, unit, base_key, column_count, single_column)]`・`column_names_for(base_key)`（Task 2）

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_signal_tree_model.py` に追記（実 mf4 経由のヘルパを新設）:

```python
def _vm_from_mf4(path) -> ChannelBrowserVM:
    app_vm = AppViewModel()
    key = app_vm.request_load(path)
    app_vm.set_active_file(key)
    return ChannelBrowserVM(app_vm)


def _vm_with_array_channel(tmp_path) -> ChannelBrowserVM:  # type: ignore[no-untyped-def]
    from tests.mdf4_helpers import write_mdf4_2d

    return _vm_from_mf4(write_mdf4_2d(tmp_path))  # Mat 3 列 + Clean 1 列


def test_top_level_rows_are_physical_channels(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # 1 行 = 1 物理チャンネル。配列チャンネルは 1 行で、展開して初めて列が出る。
    vm = _vm_with_array_channel(tmp_path)
    model = SignalTreeModel(vm)
    tops = [model.index(r, 0).data() for r in range(model.rowCount())]
    assert tops == ["Mat", "Clean"]
    assert not any(str(t).startswith("Mat[") for t in tops)


def test_children_are_synthesized_on_demand(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_array_channel(tmp_path)
    model = SignalTreeModel(vm)
    row = next(r for r in range(model.rowCount()) if model.index(r, 0).data() == "Mat")
    parent = model.index(row, 0)
    node = parent.internalPointer()
    assert node.children is None                 # 要求されるまで作らない
    assert model.hasChildren(parent) is True     # 合成せずに親と判る
    assert model.rowCount(parent) == 3           # ここで初めて合成される
    assert model.index(0, 0, parent).data() == "Mat[0]"


def test_scalar_channel_has_no_children(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    vm = _vm_with_array_channel(tmp_path)
    model = SignalTreeModel(vm)
    row = next(r for r in range(model.rowCount()) if model.index(r, 0).data() == "Clean")
    assert model.hasChildren(model.index(row, 0)) is False


def test_parent_row_unit_cell_is_blank(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """m2: 親行の Unit は "" のまま (UX-29 — 親は空・実体は子)。"""
    vm = _vm_with_array_channel(tmp_path)
    model = SignalTreeModel(vm)
    row = next(r for r in range(model.rowCount()) if model.index(r, 0).data() == "Mat")
    assert model.index(row, 1).data() == ""


def test_single_column_channels_are_draggable_leaves(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """C1: (N,1) 2D / 単一フィールド構造化 / 混在構造化 は列 1 本の **葉**。

    表示名も key も実列のもの (Mono[0] / P.x / Q.x)。sabotage: key を base_key に
    戻す・表示名を physical_name に戻すと 3 本とも RED になる。
    """
    from tests.mdf4_helpers import write_mdf4_single_column_shapes

    vm = _vm_from_mf4(write_mdf4_single_column_shapes(tmp_path))
    model = SignalTreeModel(vm)
    tops = [model.index(r, 0).data() for r in range(model.rowCount())]
    assert tops == ["Mono[0]", "P.x", "Q.x", "Clean"]
    for r in range(model.rowCount()):
        idx = model.index(r, 0)
        assert model.hasChildren(idx) is False
        assert model.signal_key_at(idx) == f"mf4_1::{tops[r]}"
        assert model.flags(idx) & Qt.ItemFlag.ItemIsDragEnabled


def test_every_signal_key_in_the_tree_resolves(qtbot, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """恒久ガード (E-3 の鋳造書き換えでも生き残る): モデルが出す全キーが解決する。

    トップレベル全行と展開済み全子を歩き、signal_key_at が None でない全キーが
    session.signal_map() で解決することを assert する。
    """
    from tests.mdf4_helpers import write_mdf4_single_column_shapes

    app_vm = AppViewModel()
    key = app_vm.request_load(write_mdf4_single_column_shapes(tmp_path))
    app_vm.set_active_file(key)
    model = SignalTreeModel(ChannelBrowserVM(app_vm))
    sig_map = app_vm.session.signal_map()

    def walk(parent) -> None:  # type: ignore[no-untyped-def]
        for r in range(model.rowCount(parent)):
            idx = model.index(r, 0, parent)
            k = model.signal_key_at(idx)
            if k is not None:
                assert sig_map.get(k) is not None, f"dead key in tree: {k!r}"
            else:
                walk(idx)  # 親は必ず展開して子まで検査する

    walk(QModelIndex())
```

> **実装者へ**: `mf4_1` は `SignalGroupManager` が MDF4 の 1 本目に割り当てるキー。
> テスト内で固定値に頼りたくなければ `app_vm.active_file_key` から組み立てること。

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_signal_tree_model.py -q`
Expected: FAIL

- [ ] **Step 3: モデルを書き換える**

`signal_tree_model.py`:

1. `_Node` の `leaves`（事前生成した葉リスト）を廃し、代わりに `base_key: str | None` を持たせる。
   `__slots__ = ("base_key", "children", "key", "orig", "parent", "row", "unit")`。
   **`column_count` はノードに載せない**（YAGNI — `hasChildren` は `key is None` から導ける。
   「対称性のために」足さないこと）。
2. `_rebuild()` は `tree_groups()` の 5-tuple から**トップレベル行だけ**を作る:

```python
    def _rebuild(self) -> None:
        """Eager top-level only; children stay lazy (None)."""
        top: list[_Node] = []
        for row, (name, unit, base_key, _count, single) in enumerate(
            self._vm.tree_groups()
        ):
            if single is not None:
                # この行は今ちょうど 1 列を提示している (実列数 1、またはフィルタで
                # 一致列が 1 本に落ちた)。key も表示名もその列の **実 identity** から
                # 採る — 合成 base_key は Signal として実在しないことがあり
                # (Mono[0] の親 "Mono" / P.x の親 "P" / Q.x の親 "Q")、葉キーにすると
                # 「見えるのに永久に描かれない行」になる。現行 :81-86 の
                # len(leaves) == 1 分岐と等価挙動 = 無回帰。
                orig, key = single
                top.append(_Node(orig, unit, key, base_key, None, row))
            else:
                # 親行の Unit は "" (UX-29: 親は空・実体は子。集約は増分5 の defer)。
                top.append(_Node(name, "", None, base_key, None, row))
        self._top = top
        self._sort_top()
```

3. `_materialize(node)` は `self._vm.column_names_for(node.base_key)` を呼んで子ノードを作る
   （**呼ばれるまで作らない**）。子は常に葉なので `base_key=None`。
4. `hasChildren` は `node.key is None` で判定する:

```python
        # tree_groups() は一致列 0 の行を返さず、一致列 1 本の行は葉 (key 非 None) に
        # なるので、key is None <=> 提示列 >= 2。column_count で判定してはならない
        # (フィルタで 1 列に落ちた行がドラッグ不能な親のままになる)。合成を誘発せずに
        # 親と判るのがこの形の要点 (rowCount は materialize する)。
        return node.key is None
```

5. `channel_browser_view.py:255-271` の docstring を追随:
   「Group (array/LD-14) rows」→「Group（物理チャンネル）rows」。挙動は変えない。

- [ ] **Step 3.5: テストフィクスチャの追随（親を消して green にすることを禁止する）**

合成 Signal（`metadata={"unit": ...}` のみ）を使うテストは、fallback
`phys = md.get("physical_channel") or orig` により `g::Arr[0]` が自分自身の物理チャンネルになり、
**親ノードが 1 つも生まれない**。対象を行番号つきで列挙する:

| ファイル | 箇所 | 対応 |
|---|---|---|
| `tests/gui/test_signal_tree_model.py` | `_sig`/`_model`（:16-38）・`_sort_model`（:108-120） | `_sig(name, phys=...)` を足し `g::Arr[i]` → `phys="Arr"` |
| `tests/gui/test_channel_browser_view.py` | :112-124 / :143-178 / :643 / :749-765 | 同上（`Arr` 系は `phys="Arr"`・`Struct.field` は `phys="Struct"`） |
| `tests/gui/test_channel_browser_vm.py` | :440-466 / :476-492 / :527-538 | Task 2 Step 4 で移送済み — 未対応が残っていればここで揃える |

**green にする最短手（`parents and` を落とす）は禁止**: `all()` が空リストに対して恒真化し、
FU-22 B の eager materialization 凍結に対する唯一のガードが黙って死ぬ（D-1 で silent vacuous assert を
4 件実証した前科がある）。

Step 4 の完了条件（**親を持ったまま green** であること）:
`test_children_lazy_until_requested` / `test_sort_does_not_materialize_children` /
`test_sorting_enabled_does_not_materialize_children` / `test_children_sorted_on_materialize` /
`test_sampling_reflects_real_leaf_units_once_group_materialized`。
**sabotage**: `_rebuild` から `_materialize` を呼ぶと上記が RED になることを実証してから戻す。

**realgui の CSV 配列 fixture を実 2D mf4 へ移す（I4-3）**:
`tests/realgui/test_signal_dnd_realclick.py:493-533` の `_make_browser_and_panel_arrays` は
実 CSV（`t,Arr[0],Arr[1],Scalar`）で親を作っているが、CSV は `physical_channel` を持たないため
平坦化後は親が立たない（コントローラ決定 2 の受容した挙動変更）。metadata 追加では直せない（実ローダー経路）。
これは `tests/realgui` 全体で `tree.expand(` を含む**唯一**のテストであり、
`model.index(childRow, 0, parentIndex) → visualRect` の掴み点（memory
`gui_qsortfilterproxy_visualrect_source_index_empty_rect` が守る経路）の唯一の Layer C 被覆。

- fixture を `write_mdf4_2d(tmp_path)`（`Mat` 3 列＋`Clean`）へ差し替え、`app_vm.request_load(path)`
  （format_def 不要）にする。
- `::Arr[0]` 参照を `::Mat[0]` へ。
- :578-581 の「row 0 が親」前提は **`signal_key_at` が None の行を探す**形へ直す
  （行順に依存しない）。
- **「親＝key None」「展開→子行を実ドラッグ→カーブが出る」という assert の意味は保つ**（削除・弱化は禁止）。

- [ ] **Step 4: 通ることを確認 + 既存モデル/ビューテスト全通過**

```bash
uv run pytest tests/gui/ -q
# realgui は --realgui 時のみ実行される (tests/conftest.py:37-42)。
# 上の gui/ だけでは Step 3.5 で移した Layer C 被覆を 1 本も踏まない。
uv run pytest --realgui tests/realgui/test_signal_dnd_realclick.py -q
```
Expected: PASS。落ちたテストは新契約へ追随させる（**被覆を落とさない**）。

- [ ] **Step 5: ゲート＋コミット**

```bash
git add src/valisync/gui/adapters/signal_tree_model.py src/valisync/gui/views/channel_browser_view.py tests/
git commit -m "feat(gui): ツリーを物理チャンネル 1 行へ平坦化し子を要求時合成 (葉の事前保持を廃止)"
```

---

## Task 4: 件数表示（列を ch 単位）とフィルタ（列名マッチ＋0 MB メモ）＋規約の改訂記録

**Files:**
- Modify: `src/valisync/gui/strings.py`
- Modify: `src/valisync/gui/viewmodels/channel_browser_vm.py`（`shown_count()`・**`_group_total()`**・`tree_groups()`・`column_names_for()`・新規メモ）
- Modify: `docs/design.md`（表記規約 R-07 行＋決定履歴）
- Modify: `docs/superpowers/specs/2026-07-22-incd-strings-os-design.md`（R-07:210・G-42:172）
- Modify: `docs/superpowers/specs/2026-07-22-incd-strings-inventory.md`（G-42 現物:309-310）
- Modify: `docs/superpowers/specs/2026-07-24-deferred-column-expansion-design.md`（技術判断の訂正＋意図的逸脱の追記）
- Test: `tests/gui/test_channel_browser_physical.py`・`tests/gui/test_channel_browser_vm.py`・`tests/gui/test_channel_browser_view.py`

**Interfaces:**
- Produces: `CHANNEL_HEADER_COUNT_TMPL` が `"{total} ch 中 {shown} ch を表示"`
  （`CHANNEL_HEADER_EMPTY_TMPL` も `"0 ch"` へ揃える）。**桁区切りは付けない**（コントローラ決定 4）。
- Produces: `ChannelBrowserVM._filter_memo: tuple[str, list[...], int] | None`
  — `(フィルタ文字列, 生存行, 一致列総数)`。`_ensure_filter_memo()` が列名走査を**1 回だけ**実行し、
  `tree_groups()` は `memo[1]`、`shown_count()` は `memo[2]` を返す。
- **不変条件（C3-6）**: 述語 `fl in orig.lower()` は 1 経路のみ。`shown_count()`・`tree_groups()`・
  `column_names_for()` が同じ述語を共有する（件数と子行が乖離できない構造）。

> **なぜ名前キャッシュ（≈33 MB）でなくメモ（0 MB）か（I3・コントローラ決定 1）**:
> フィルタは **200 ms シングルショット debounce** の後に 1 回だけ走る
> （`channel_browser_view.py:38` `_FILTER_DEBOUNCE_MS = 200`・:107-110・:179・:220-222）。
> 走るのは**打鍵ごとではなく入力停止ごと**。その 1 回で 3 パスが走るが、3 つとも同じ `_prep` を
> 同じ `self._filter_text.lower()` で歩く: (a) `SignalTreeModel._on_vm_change` → `_rebuild()` →
> `tree_groups()`（signal_tree_model.py:72-81）、(b) `_refresh_state` → `header_text()` → `shown_count()`、
> (c) 同 `_refresh_state` → `empty_state()` → `shown_count()`（channel_browser_view.py:207-218）。
> 間に結果を変えるものは無いので、フィルタ文字列をキーにしたメモ 1 個で **3→1** に畳める。
> メモのペイロード（生存行タプル＋int）は prod でも 4,324 行＝数十 KB。
> **メモは列ごとの小文字名を保持しない**（それが 33 MB の本体）。子行は `column_names_for` が
> その行の span（最大 1,024 列）を展開時に再走査して賄うので、名前キャッシュは不要。

- [ ] **Step 1: 失敗テストを書く**

`tests/gui/test_channel_browser_physical.py` に追記:

```python
def test_header_counts_columns_in_ch_units(tmp_path: Path) -> None:
    vm = _vm(tmp_path)  # Mat 3 列 + Clean 1 列 = 2 行 / 4 列
    assert vm.header_text() == "4 ch 中 4 ch を表示"


def test_header_total_is_columns_not_rows(tmp_path: Path) -> None:
    """C2: total も shown も「列」。行数を total にすると shown > total になる。"""
    vm = _vm(tmp_path)
    rows = vm.tree_groups()
    total_cols = sum(r[3] for r in rows)  # r[3] = column_count
    assert total_cols > len(rows)  # fixture が配列を含むことの担保
    assert vm.header_text() == f"{total_cols} ch 中 {total_cols} ch を表示"
    for q in ("", "mat", "mat[1", "zzz"):
        vm.set_filter(q)
        assert 0 <= vm.shown_count() <= total_cols


def test_filter_matches_column_names_and_keeps_parent(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    vm.set_filter("mat")
    rows = vm.tree_groups()
    assert [r[0] for r in rows] == ["Mat"]  # Clean は落ちる
    assert vm.shown_count() == 3
    assert vm.header_text() == "4 ch 中 3 ch を表示"


def test_column_names_for_honors_filter(tmp_path: Path) -> None:
    """C3: 絞り込んだ親を展開しても **一致列だけ** が出る
    (test_channel_browser_vm.py:504-508 の子レベル assert の等価移送先)。"""
    vm = _vm(tmp_path)
    vm.set_filter("mat[1")
    mat = next(r for r in vm.tree_groups() if r[0] == "Mat")
    assert [c[0] for c in vm.column_names_for(mat[2])] == ["Mat[1]"]
    assert vm.shown_count() == 1  # ヘッダーと木が同じ基準
    assert vm.header_text() == "4 ch 中 1 ch を表示"


def test_row_filtered_down_to_one_column_becomes_a_real_leaf(tmp_path: Path) -> None:
    """コントローラ決定 3: 絞って 1 列に落ちた行は今日どおり葉 (実キーでドラッグ可)。

    column_count は実列数 (3) のまま = _group_total の単位が壊れない。
    """
    vm, app_vm = _vm_for(write_mdf4_2d(tmp_path))
    vm.set_filter("mat[1")
    mat = next(r for r in vm.tree_groups() if r[0] == "Mat")
    assert mat[3] == 3  # column_count はフィルタ非依存
    assert mat[4] is not None  # single_column = 提示している唯一の列
    orig, ns_name = mat[4]
    assert orig == "Mat[1]"
    assert app_vm.session.signal_map().get(ns_name) is not None


def test_filter_matching_nothing_yields_no_rows(tmp_path: Path) -> None:
    vm = _vm(tmp_path)
    vm.set_filter("zzz")
    assert vm.tree_groups() == []
    assert vm.shown_count() == 0
    assert vm.empty_state() == "no_match"


def test_one_filter_application_scans_columns_once(tmp_path: Path) -> None:
    """I3/I2-4: 入力停止 1 回で走る 3 パス (tree_groups / header_text / empty_state) が
    列名走査を 1 回に畳めていること。これが崩れると受け入れの perf 前提が壊れる。"""
    vm = _vm(tmp_path)
    vm.set_filter("mat")
    before = vm.inspect()["filter_scans"]
    vm.tree_groups()
    vm.header_text()
    vm.empty_state()
    assert vm.inspect()["filter_scans"] == before + 1
    vm.tree_groups()  # 同じフィルタの再問い合わせは 0 回
    assert vm.inspect()["filter_scans"] == before + 1
    vm.set_filter("mat[1")
    vm.tree_groups()
    assert vm.inspect()["filter_scans"] == before + 2


def test_filter_memo_does_not_hold_per_column_names(tmp_path: Path) -> None:
    """メモは行数ぶんしか持たない (名前キャッシュ 33 MB の再導入を構造で禁じる)。"""
    vm = _vm(tmp_path)
    vm.set_filter("mat")
    rows = vm.tree_groups()
    assert len(rows) == 1 and rows[0][3] == 3  # 1 行 / 実列数 3
    memo = vm._filter_memo
    assert memo is not None
    assert len(memo[1]) == len(rows)  # 保持は行単位 — 列単位ではない


def test_filter_memo_dropped_on_prep_lifecycle(tmp_path: Path) -> None:
    vm, app_vm = _vm_for(write_mdf4_2d(tmp_path))
    vm.set_filter("mat")
    vm.tree_groups()
    assert vm._filter_memo is not None
    vm.refresh()
    assert vm._filter_memo is None
```

- [ ] **Step 2: 失敗を確認**

Run: `uv run pytest tests/gui/test_channel_browser_physical.py -q`
Expected: FAIL

- [ ] **Step 3: 文言とフィルタメモを実装**

1. `strings.py`:
   ```python
   CHANNEL_HEADER_EMPTY_TMPL: Final = "0 ch"
   CHANNEL_HEADER_COUNT_TMPL: Final = "{total} ch 中 {shown} ch を表示"
   ```
   **桁区切りは付けない**（現行 `{total}` の挙動を保存。`{total:,}` にはしない — コントローラ決定 4）。
2. `channel_browser_vm.py` にフィルタメモを追加:

```python
    def _ensure_filter_memo(
        self,
    ) -> tuple[list[tuple[str, str, str, int, tuple[str, str] | None]], int]:
        """フィルタ 1 パス分の結果 (生存行・一致列総数) を文字列キーでメモする。

        _notify('filter') は 3 消費者へ fan-out するが全て同じ問いを聞く:
        SignalTreeModel._on_vm_change -> _rebuild -> tree_groups()
        (signal_tree_model.py:72-81) / _refresh_state -> header_text() -> shown_count() /
        同 -> empty_state() -> shown_count() (channel_browser_view.py:207-218)。
        走るのは打鍵ごとではなく **入力停止ごと** (200 ms debounce・
        channel_browser_view.py:38,105-110,179) で、その 1 回に同じ列名走査が 3 回走る。
        フィルタ文字列をキーにしたメモで 3->1 に畳む。

        追加メモリは実質ゼロ: 保持するのは生存行のタプル (prod 4,324) と int だけで、
        列ごとの小文字名は持たない (それが旧 _prep の 68 MB / 名前キャッシュ案の 33 MB)。
        子行は column_names_for が展開時にその行の span を再走査して賄う。
        """
        self._ensure_prep()
        fl = self._filter_text.lower()
        memo = self._filter_memo
        if memo is not None and memo[0] == fl:
            return memo[1], memo[2]
        rows: list[tuple[str, str, str, int, tuple[str, str] | None]] = []
        total = 0
        for name, unit, base_key, count, first, spans in self._prep:
            if not fl:
                matched, single = count, (first if count == 1 else None)
            else:
                matched, single = 0, None
                for start, stop in spans:
                    for sig in self._group_sigs[start:stop]:
                        ns_name = sig.name
                        orig = (
                            ns_name.split(KEY_SEPARATOR, 1)[1]
                            if KEY_SEPARATOR in ns_name
                            else ns_name
                        )
                        if _matches(orig, fl):  # 述語は単一の真実 (C3)
                            matched += 1
                            single = (orig, ns_name)
                if matched != 1:
                    single = None  # 提示列が 1 本のときだけ葉にする
            if matched:
                rows.append((name, unit, base_key, count, single))
                total += matched
        self._filter_memo = (fl, rows, total)
        self._filter_scans += 1  # inspect() から観測する (perf 前提の pin)
        return rows, total
```

   モジュール直下に述語を 1 つだけ置く（`column_names_for` と共有する — **これが単一の真実**）:
```python
def _matches(orig: str, filter_lower: str) -> bool:
    """フィルタ一致述語。件数 (shown_count)・行 (tree_groups)・子行
    (column_names_for) が同じ問いを共有するための単一の真実 — 分岐させると
    「N ch 中 1 ch を表示」と言いながら展開すると 3 列出る、が起きる。"""
    return not filter_lower or filter_lower in orig.lower()
```
3. `tree_groups()` は `self._ensure_filter_memo()[0]` を返す（既存の `except KeyError: return []` は維持）。
4. `shown_count()` は `self._ensure_filter_memo()[1]` を返す（既存の KeyError ガード配置は**変えない** —
   `header_text()` が先に `_group_total()` で守る現行構造を保存）。
5. `column_names_for(base_key)` に**同じ述語**を適用（フィルタ空なら全列）。
   `_matches(orig, self._filter_text.lower())` を使うこと。
6. `_ensure_prep()`・`set_filter()` で `self._filter_memo = None`。
   `__init__` に `self._filter_memo = None` と `self._filter_scans = 0`、`inspect()` に
   `"filter_scans": self._filter_scans` を足す。

   > **メモのライフサイクル（m3）**: メモは 0 MB・再構築が安いので `_prep` と同じライフサイクルで良い
   > （m3 が問題視した「33 MB を無関係なロードごとに捨て直す」構造ではない）。
   > **名前キャッシュを E-3 で採る場合は m3 のライフサイクル要件（group_key ごと・`refresh()` で捨てない・
   > LRU=2）を必ず適用すること** — E-3 申し送りに転記済み。

- [ ] **Step 4: 規約の改訂を記録する（I6・ゲートとコミットの前）**

新文言 `{total} ch 中 {shown} ch を表示` は現行の表記規約を 3 点で破る（単一パターン／「ch」は技術メタ情報限定／列は「列」）。
G-42 の現物はまさに**旧「{total} ch 中 …」を「信号」へ直した記録**なので、**無記録だと次の文言スイープで確実に戻される**。
設計 spec 自身（`2026-07-24-deferred-column-expansion-design.md:254-255`）が改訂を要求している成果物。

- [ ] `docs/design.md:63` の R-07 に例外を明記:
      「ただしチャンネルブラウザの件数表示のみ、展開列を『ch』単位で数える（`{total} ch 中 {shown} ch を表示`）—
      ユーザー決定 4・列展開遅延化 E-2。R-07 の単一パターン規定と『ch は技術メタ情報に限定』を当該箇所に限り supersede」。
- [ ] `docs/superpowers/specs/2026-07-22-incd-strings-os-design.md` の R-07（:210）と G-42（:172）に同じ supersede 注記。
- [ ] `docs/superpowers/specs/2026-07-22-incd-strings-inventory.md:309-310` の G-42 行にも注記
      （**この行には「ch は技術メタ情報限定ゆえ ch→信号」という逆向きの根拠が書かれている**ため、
      ここを直さないと逆転が無記録のまま残る）。
- [ ] `docs/design.md` 決定履歴に 2026-07-25 エントリ（トークン変更なし・文言のみ・理由＝件数の意味が
      「信号」から「展開列」へ変わった・PR 番号）。**併せてコントローラ決定 2（CSV/Derived の
      `Arr[0]`/`Arr[1]` が親行にならなくなるユーザー可視の挙動変更）も同エントリに記録する。**
- [ ] `docs/superpowers/specs/2026-07-24-deferred-column-expansion-design.md` を 2 点訂正:
      (a) 意図的逸脱リスト（:247-255）に「CSV/Derived は `physical_channel` を持たないため 1 列＝1 物理チャンネルとなり、
      CSV ヘッダー `Arr[0]`/`Arr[1]` は親行にならない」を追加。
      (b) 技術判断（:79-93）を訂正: **「1 打鍵で 3 パス」→「入力停止ごとに 3 パス（200 ms debounce・
      `channel_browser_view.py:38,105-110,179`）」**、および **E-2 は 0 MB のフィルタメモを採用し、
      名前キャッシュ（41.7 MB は 330,004 列＝1024 ガード退役後の値・E-2 スケール 264,004 列では比例で ≈33 MB）は
      E-3 の条件付きへ移す**（実測でメモ案が現行 170-213 ms を上回った場合のみ）。

- [ ] **Step 5: 通ることを確認 + 文言 assert の追随**

Run: `uv run pytest tests/gui/ -q`
Expected: PASS。

**追随先を名指しで指示する（I6-4）**:
- `tests/gui/test_channel_browser_view.py:303` の literal `"2 信号中 2 件を表示"` → 新文言へ。
  この fixture はスカラー CSV（1ch=1列）なので値は `"2 ch 中 2 ch を表示"`。
- 同 :343 の旧ベースライン文字列（幅比較の対照として**意図的に複製**している行）は
  **「ファイル名プレフィックス＋新文言」**へ書き換える。本文だけ差し替えると
  比較の差分が「ファイル名＋wrap の有無」以外を含んでしまい、幅比較が同一内容の対照でなくなる。
- `tests/gui/test_channel_browser_vm.py:346/358/371` は `S.CHANNEL_HEADER_*` を symbolic 参照する
  トートロジーなので**回帰ガードにならない**（文言追随のみ・値は自動追随する）。
  同様に :340-348 / :351-359 は**スカラー CSV（1ch=1列）なので `total == shown` となり
  どちらの定義でも通る＝C2 の証拠にはならない**。C2 の回帰ガードは
  `test_header_total_is_columns_not_rows`（配列 fixture）が担う。

- [ ] **Step 6: ゲート＋コミット**

```bash
git add src/valisync/gui/strings.py src/valisync/gui/viewmodels/channel_browser_vm.py tests/gui/ \
        docs/design.md \
        docs/superpowers/specs/2026-07-22-incd-strings-os-design.md \
        docs/superpowers/specs/2026-07-22-incd-strings-inventory.md \
        docs/superpowers/specs/2026-07-24-deferred-column-expansion-design.md
git commit -m "feat(gui): 件数を列の ch 単位表示へ・フィルタを列名マッチ＋0 MB メモ化 (R-07/G-42 改訂を同載)"
```

---

## Task 5: ①gate realgui ＋ 残渣削減の実測（受け入れ）

**Files:**
- Create: `tests/realgui/test_channel_tree_flatten_realclick.py`
- Modify: `tests/mdf4_helpers.py`（realgui fixture ヘルパ）
- Modify: `scripts/measure_lazy_footprint.py`（prep/tree_groups 後＋**フィルタ後**の RSS を出力）

- [ ] **Step 1: realgui テストを書く（実 OS 入力）**

まず fixture ヘルパを足す（**狙う mutation を殺せる形**にすることが要件・I5-1）:

```python
def write_mdf4_flatten_fixture(tmp_path: Path) -> Path:
    """平坦化 realgui の fixture — 5 物理チャンネル / 9 列.

    ローダー実測: ACC.Speed, ACC.Accel, Mat[0..2], Pos.xa, Pos.xb, Pos.yc, Scalar。

    狙う mutation は **_base_of によるドット分割グルーピングの復活**。
    接頭辞を共有する 2 本 (ACC.Speed / ACC.Accel) が無いと
    SignalTreeModel._rebuild の単一リーフ畳み込み (現行 signal_tree_model.py:81-86) で
    旧実装でも "ACC.Speed" がトップ行に見えてしまい、オラクルが mutation を殺せない。
    Pos は「英数字だけの実打鍵で一部の列だけを絞り込む」ための構造化チャンネル
    ('x' は他のチャンネル名に現れない — ord('[') == VK_LWIN 問題の回避策)。
    """
```
（本体は `write_mdf4_2d` と同型の `MDF()` → `append` × 5 → `save`。
`Pos` は `dtype=[("xa", "<f8"), ("xb", "<f8"), ("yc", "<f8")]`。）

`tests/realgui/test_channel_tree_flatten_realclick.py` は実ディスプレイの実 MainWindow で:

1. **平坦化**: トップレベル行が `["ACC.Speed", "ACC.Accel", "Mat", "Pos", "Scalar"]` で
   **`"ACC"` が存在しないこと**（＝ドット分割の復活を殺す）。
2. **要求時合成**: `Mat` 行を**実クリックで展開**すると `Mat[0..2]` が子として現れること。
3. **列名フィルタ**: 検索ボックスへ**実タイピング**（`key(ord(ch.upper()))` で `X` の 1 打鍵）→
   debounce（200 ms）を pump で待ち → 行が `["Pos"]` に絞られ、**実クリックで展開した子行が
   `["Pos.xa", "Pos.xb"]` だけ**であること（`Pos.yc` は出ない＝C3 の回帰を殺す）。
4. **列の個別選択が生きている**（ユーザー決定 4 の受け入れ・C1-6）: フィルタを消してから
   **配列チャンネル `Mat` の子行**を実クリックで選択 → 実右クリック →
   「アクティブパネルへ追加」（`S.ACTION_ADD_TO_ACTIVE_PANEL`）を実クリック →
   `panel.signal_keys_drawn()` に `...::Mat[0]` が含まれ `panel.curve_xy(panel.entry_id_for(key))` が非空。
   **対象行は必ず配列チャンネルの子行**にすること — トップレベルのスカラーでは
   `base_key == 実キー`になり C1 の回帰を素通しする。

**実打鍵の制約（I5-3・必ず守る）**:
`tests/realgui/_realgui_input.py` は `key(vk)` しか持たず、`VkKeyScan`/`SendInput`/`type_text` は存在しない。
唯一のタイピング前例は `key(ord(ch.upper()))`（`test_tab_ui_flow.py:142`・`test_menu_mnemonics_realclick.py:96,108`）で、
**A-Z / 0-9 の VK が ASCII と一致することにのみ依存**している。
**`ord('[') == 0x5B == VK_LWIN` なのでスタートメニューが開き、以後の実クリックが別ウィンドウへ流れる**
（共有マシン上の不透明なフレーク）。`VK_OEM_4`(0xDB) も JP 配列では `[` ではない。
→ **実打鍵は英数字のみ**（`X`）。`Mat[0]` のような記号入り列名マッチのロジックは
**Task 4 の Layer B（`vm.set_filter("mat[1")`）で被覆済み**なので Layer C は英数字打鍵で十分。
どうしても記号打鍵が要るなら、`_realgui_input` に `VkKeyScanW` ベースの `type_text(s)`
（下位バイト=VK・上位バイトのビットで Shift/Ctrl/Alt 合成）を新設し、そこを**唯一の記号打鍵経路**にすること。

**quick_demo は補助オラクルへ降格（I5-2）**:
`demo_data/quick_demo.mf4` があればトップ行数＝物理チャンネル数（実測 180・`_base_of` なら 25 グループ）も確認する。
**不在時に `pytest.skip` してはならない**（`demo_data/` は .gitignore:55 で非コミット。
`test_lazy_load_realclick.py:163-164` の skip 前例をそのまま真似ると、①ゲートの単一ファイル実行で
**skip がそのまま「pass」として報告されうる**）。→ 明示 fail か `xfail(strict=False)` にし、
**①ゲートの証拠報告に「合成 fixture で pass・quick_demo は present/absent」を必ず書く**。

- [ ] **Step 1b: 既存 realgui の着地点を棚卸しする（I4-7）**

```bash
grep -rn 'signal_key_at(' tests/realgui/
```
各サイトが意図した行種に着地し続けるかを**実行して**確認する
（`test_active_panel_flow.py:142` / `test_fu15_axis_deselect.py:120` / `test_journey_smoke.py:86` /
`test_lazy_load_realclick.py` はスカラー CSV で `is not None` のみなので無影響の見込みだが、確認は実行で行う）。

- [ ] **Step 2: 実行して実機 pass を確認（①ゲート）**

```bash
uv run pytest --realgui tests/realgui/test_channel_tree_flatten_realclick.py -q
uv run pytest --realgui tests/realgui/ -q     # realgui フル (I4-5)
```
Expected: PASS（スクショ目視/AI 判定つき）。報告様式は過去増分と同じ
**「realgui フル N/N pass（既知フレークは単体再実行で pass を示す）」**。
`uv run pytest -q` は realgui を全 skip する（`tests/conftest.py:37-42`）ので、
**フルゲートだけでは Layer C を 1 本も踏まない**ことに注意。

- [ ] **Step 3: 残渣削減を実測（フィルタ前・フィルタ後の両方）**

`scripts/measure_lazy_footprint.py` に**5 段**の RSS を出す段を足し、prod_demo で実行する:

1. ロード直後
2. `signal_map()` 後
3. `group_signals()` 後
4. **prep＋`tree_groups()` 後**（＝旧プランが唯一測っていた点）
5. **`set_filter("...")` 後に `tree_groups()` / `shown_count()` / `header_text()` を全て通した状態**
   （production の 3 パスと同じ経路）— さらに `set_filter("")` に戻した後も測る

各段で `gc.collect()` 後の RSS を印字し、**段 5 − 段 4 の差**を「フィルタ機構の実測コスト」として
明示ラベルで出す（この自己差分はマシン間ノイズに強く、記憶された 87 MB との A/B より頑健）。
**1 打鍵ぶんのフィルタ適用 wall time も同じ run で出す**。

Run: `uv run --with psutil python scripts/measure_lazy_footprint.py`

Expected（**両方必須**・PR 本文へ記録）:
- (a) 段 4 で E-2 前の実測残渣（`_prep` 68 MB＋`_Node.leaves` 19 MB ≒ **87 MB**）が消えていること。
- (b) 段 5 − 段 4 の増分が **≈0 MB**（メモ案の検証。列ごとの小文字名を保持していないことの実測側の裏付け）。
- (c) 1 回のフィルタ適用の wall time が**現行 170-213 ms を上回らない**こと。

> **判定基準（コントローラ決定 1）**: (b)(c) を満たせば E-2 は名前キャッシュ無しで着地する。
> **上回った場合に限り** E-3 で名前キャッシュを検討し、そのときは `column_names_for` も賄える形
> （`(orig, lower, unit, key)` per base）で設計して**実測し直す**
> （33/41.7 MB は小文字名のみの見積りでありこの形はカバーしない）。乖離したら spec:83-88 の表を実測値へ訂正する。

- [ ] **Step 4: assert を弱めていないことの機構的確認（I4-6）**

```bash
git diff <E-1 tip>..HEAD -- tests/ | grep '^-.*assert'
```
削除された assert を**移行先とともに列挙して報告する**（移行先が無いものは戻す）。

- [ ] **Step 5: 凍結カタログの差分確認（m4）**

撮影と比較を実行する。**主判定は「差分がチャンネルドックのヘッダー文言 1 行に限定されること」**。
`--crop-meta` の一致は**補助**でしかない（撮影 fixture は 2 列 CSV でツリー行構造が新旧とも 2 行で不変・
`_TREE_SIZEHINT_WIDTH` が定数なので中央ジオメトリは構造的に動かない＝トートロジー）。
ヘッダー文言以外の差分が出たら**波及として調査**してからベースラインを更新する。
両テーマ・再撮影で決定性（exit 0）まで確認する。

- [ ] **Step 6: フルゲート＋コミット**

```bash
uv run pytest -q && uv run ruff check && uv run ruff format --check && uv run mypy src/
git add tests/realgui/test_channel_tree_flatten_realclick.py tests/mdf4_helpers.py scripts/measure_lazy_footprint.py
git commit -m "test(gui): E-2 の ①gate realgui ＋残渣削減の実測 (フィルタ前後)"
```

---

## E-3 への申し送り（E-1/E-2 のレビューが残したもの）

- **`RemovalResult.removed_columns` を `TeardownService` へ配線する**（E-1 Task 5 で生成のみ・
  未消費）。配線せずに E-3 で鋳造が生きると、鋳造列が teardown 会計から漏れる。
- **`dict(signal_map())` の AST/ratchet ガードを入れる**（E-1 Task 6）。E-3 で鋳造が生きると
  390 MB 回帰の防波堤が docstring だけになる。`tests/gui/test_theme_guard.py` に同型の前例がある。
- **Critical 1 の寿命ガードを production 鋳造経路にも張る**（E-1 Task 5 は test double 依存）。
- `metadata["physical_channel"]`（本プラン Task 1）は E-3 で `ColumnSpec` に置き換わる可能性が
  あるが、**キーは維持する**（ブラウザの契約になるため）。
  併せて: **`physical_channel` の値は表示名空間**（`signal_name` 由来）であり、`ColumnSpec` の
  **生名キー空間**（selector 用）とは別物。E-3 で置き換える際もブラウザへ渡す識別子は表示名空間のまま維持する
  （`column_names.py:99-104` の前提条件＝生名キーの単純な Mapping は 2 チャンネルをサイレントに衝突させる）。
  生名が VM 層で要るなら `physical_channel_raw` を別キーとして足し、**このキーを多重定義しない**。
- **列 span は eager 展開前提の一時措置**（`_prep` の `spans` と `self._group_sigs`）。E-3 で
  `leaf_names(base, spec)` ベースへ置換し、境界フィールドを削除する。
- **名前キャッシュは E-2 で意図的に見送った**（0 MB メモで代替）。E-3 で必要と実測されたときだけ導入し、
  そのときは m3 のライフサイクル要件を必ず適用する: `_prep_valid` に相乗りさせない／`group_key` ごとの
  `dict` にする（`refresh()` は `main_window.py:708-710` の `change == "loaded"` **1 箇所だけ**が呼ぶので、
  相乗りすると 2 本目のファイルをロードするたびに 1 本目のキャッシュを捨てる＝増分E の比較ワークフローそのもの）／
  **常駐上限 LRU=2**（無制限だと 2 ファイル比較で ~66-83 MB 常駐し削減目標を相殺する）／
  破棄は `"unloaded"` 通知でその key のみ pop。生成回数カウンタ（`inspect()` 経由）で
  「無関係な 2 本目 load で再生成が走らない」「グループ削除でその key が消える」を pin し、
  sabotage（`refresh()` に `clear()` を足すと前者が RED）を実証すること。

## Self-Review（プラン著者チェック）

- **Spec coverage（E-2）**: 物理チャンネル単位の prep＝Task 2／ツリー平坦化と子の要求時合成＝Task 3／
  件数の ch 単位表示とフィルタ＝Task 4／①gate と残渣実測＝Task 5。**spec に無い Task 1 を追加**した
  理由: E-2 は「ローダーがまだ展開する」ため VM は文字列しか持たず、`ACC.Speed`（チャンネル名）と
  `P.x`（構造化フィールド）を区別できない。ローダー由来の metadata が無いと平坦化が構造化チャンネルを壊す。
  加算的・挙動不変で E-3 の前段にもなる。
- **型整合**: `tree_groups() -> [(name, unit, base_key, column_count, single_column)]`・
  `column_names_for(base_key) -> [(orig, unit, key)]`・`shown_count()`＝一致列数・
  `_group_total()`＝実列総数（`sum(row[3] for row in _prep)`）、で全 Task 一貫。
  `_prep` は `(physical_name, unit, base_key, column_count, first_column, spans)`。
- **葉キーの不変条件の一貫性**: C1（実列数 1）と C3-3／コントローラ決定 3（フィルタで 1 列に落ちた行）を
  `single_column` **1 つの値**で表現し、モデルの葉/親判定は `single_column is not None`（＝`node.key is None`）で行う。
  レビュー C3-2 の「`hasChildren` は `column_count > 1` のままでよい」は**この統合により意図的に採らない**
  （採るとフィルタで 1 列に落ちた行がドラッグ不能な親になり、今日の affordance を失う）。
  `column_count` はフィルタ非依存のまま `_group_total()` の供給元として残るので、C3-2 の本来の目的
  （件数の単位が壊れない）は保たれている。
- **テストコードの実在性（I7）**: 全コードブロックを実ヘルパのシグネチャに突き合わせ済み。
  `write_mdf4_2d(tmp_path)` は**引数なし**で `Mat`(4x3)＋`Clean`＝**2 行 / 4 列**。
  `write_mdf4(path, channels)` の `channels` は **dict のリスト**。期待値は全て fixture から導出してある
  （`shown_count() == 4` / `"4 ch 中 4 ch を表示"` / `"4 ch 中 1 ch を表示"` / スカラー行名は `"Clean"`）。
  新規ヘルパ 3 本（`write_mdf4_single_column_shapes` / `write_mdf4_interleaved_arrays` /
  `write_mdf4_flatten_fixture`）の**ローダー出力は実 asammdf ラウンドトリップで確認済み**
  （`Mono[0]` / `P.x` / `Q.x` / `Clean`、`A[0] A[1] S B[0] B[1]`、
  `ACC.Speed ACC.Accel Mat[0..2] Pos.xa Pos.xb Pos.yc Scalar`）。
- **Placeholder**: 無し。
- **意図的逸脱（記録が必要なもの）**: (1) CSV/Derived の `Arr[0]`/`Arr[1]` が親行にならない
  （Task 4 Step 4 で spec と design.md へ記録）。(2) LD-08 同名チャンネルの融合をやめ 2 行にする
  （現行 `_base_of` 挙動の supersede・Task 2 のテストで固定）。(3) 件数の単位が「ch＝展開列」へ
  （R-07/G-42 の supersede・Task 4 Step 4）。
- **弱くしていない受け入れ**: perf 受け入れは 2 項（フィルタ前 −87 MB **かつ** フィルタ後の増分 ≈0 MB）に
  **増やして**あり、緩めていない。realgui は fixture を mutation-killing に固定し、skip を pass に読み替える
  逃げ道を塞ぎ、フルスイート実行を必須にしてある。




