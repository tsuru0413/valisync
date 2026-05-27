# Signal 名前空間（ファイル単位キー）

一次情報源: `.kiro/specs/valisync-core/design.md` — SignalGroupManager セクション

---

## 概要

ValiSync は読み込みファイルごとに一意なキーを割り当て、全 Signal 名を `{key}::{原信号名}` の名前空間に展開する。これにより異なるファイル間（同一パスの重複読み込みを含む）で信号名が衝突しない。

## キー形式

| file_format | キー例 |
|---|---|
| MDF4 | `mf4_1`, `mf4_2`, ... |
| CSV | `csv_1`, `csv_2`, ... |

- フォーマット別連番（1 始まり）
- ファイル削除後も連番を戻さない。キーは安定識別子として機能し再利用されない

## 区切り文字: `::`

`/`（除算演算子）・`.`（小数点）と Formula パーサーで衝突しないため `::` を採用。CAN/XCP 信号名に `::` が含まれることはまれであり、split("::", 1) によりキーと原信号名を確実に復元できる（キー自体に `::` を含まないため堅牢）。

## 重複ファイルの許可

同一パスを複数回読み込んだ場合も各読み込みに一意なキーを付与し、独立した Signal_Group として管理する（Req 4.7）。削除操作はパスではなくキー指定で行う（パスは重複しうるため曖昧）。

## GUI 層との責務分担

- **core 層**: `key::original_name` 形式の名前を正規名として扱う
- **GUI 層**: 表示名（原信号名・ソースファイルのベースネーム）の復元は GUI の責務。`name.split("::", 1)` と `SignalGroupManager.group(key).source_path.stem` で復元可能

## Session との責務分担

`SignalGroupManager` は add/remove のみを提供する純粋コレクション。依存チェック（Req 4.5）と一括読み込みの部分失敗処理（Req 5.4）は Session（`core/session.py`）が担う。

## Phase 2 への繰り延べ

`SignalGroupManager.signals()` は呼び出しごとに keyed Signal を再生成するため、大規模信号では Signal 不変条件の再検証（O(n)）が発生する。Phase 2 でキャッシュ等の最適化を検討する。
