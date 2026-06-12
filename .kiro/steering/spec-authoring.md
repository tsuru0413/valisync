# Spec Authoring Rules

`.kiro/specs/<spec>/{requirements,design,tasks}.md` を生成・更新する際に従うべきプロジェクト固有ルール。

---

## 基本姿勢

本プロジェクトは **単一の Claude Code セッションで進める個人開発** である。spec の wave 構造・タスク粒度は **並列度の最大化ではなく、認知負荷の最小化** を優先する。

---

## tasks.md の Wave 設計ルール

`Task Dependency Graph` セクション (末尾の JSON) を生成する際、以下を必ず満たすこと。

### サイズ

- 1 wave は **3-5 タスク** を目安
- 1-2 タスクの wave も可 (フェーズ区切り・チェックポイント等)
- **6 タスク超は禁止** — 認知単位として大きすぎる

### グルーピング原則

- 1 wave 内のタスクは **同じサブシステム / モジュール / 責務** に閉じる
  - 例: `models/income.py` の変更タスクは同 wave、`models/expense.py` は別 wave
  - 例: backend と frontend のタスクは別 wave に分ける
- **同じファイルを編集する複数タスクを同 wave に置かない**
  - 順序依存があるなら wave を分けるか、Notes に明示
  - 並列実行不可なタスクを wave に並べてはならない
- **optional テスト (`*` マーク) のみで構成される wave は末尾にまとめる**
  - 必須実装の慣性を保つため

### フェーズ境界

責務が大きく違う領域 (backend / frontend、コア実装 / プロパティテスト等) を含む spec では、wave 群をフェーズ分割し、コメントでフェーズ境界を明示する。

例:
```
═══ Phase A: Backend ═══
Wave 0, Wave 1, ...
═══ Phase B: Frontend ═══
Wave N, Wave N+1, ...
```

### 実装順の明示

wave 内タスクの実装順が自明でない場合 (依存・前提条件あり) は、`tasks.md` の **Notes** セクションに順序を補記する。

---

## チェックリスト (spec 完成前)

新しい spec を生成 or 既存 spec を大幅追加するとき、以下を確認:

- [ ] 各 wave のタスク数は 3-5 に収まっているか (6 超を避けたか)
- [ ] 1 wave 内のタスクは同じサブシステム/責務に閉じているか
- [ ] 同じファイルを編集する複数タスクが同 wave に並んでいないか
- [ ] optional テストのみで構成される wave は末尾に配置されているか
- [ ] backend/frontend のように責務が大きく違う場合、フェーズ境界が明示されているか
- [ ] wave 内の実装順が自明でないなら Notes に補記されているか

---

## 既存 spec の扱い

既に進行中の spec は **wave 番号の振り直しは行わない** (進捗との整合性を保つため)。

ただし、進行中 spec に **新規 task を追加** する場合は、本ルールに従って新 wave を配置する。

---

## Follow-up memo 運用

実装中に **本 spec のスコープ外だが将来別 spec で対応すべき改善余地** が見つかった場合、`docs/<topic>-followup.md` として記録する。即 spec 化しない知見を体系的に蓄積するための仕組み。

### Follow-up memo の構造

```markdown
# <タイトル> 改善メモ

> 関連 spec (発見元) と発見の経緯を冒頭に明記

## 現象 (or 課題)

## Spec 上の評価
  - 本 spec で扱うべきか / 別 spec か / 単純な後追いか

## 原因の仮説 (or 背景)

## 改善案 (複数)
  - 案 A: 簡素実装
  - 案 B: より丁寧な実装

## 採用方針 (推奨)
  - 後日 spec 化する想定 → spec 名候補・実装規模・着手タイミング

## 関連リンク
  - 関連 requirement / 改修対象ファイル / 既存テストなど
```

### CLAUDE.md への反映

Follow-up memo を作成したら、`CLAUDE.md` の Phase 状況テーブルの該当 spec 行に link を併記する:

```
| <spec名> | ... | **完了** ...。<経緯>のため別 spec `<候補名>` で根本解決検討 — 詳細は [docs/<topic>-followup.md](docs/<topic>-followup.md) | ... |
```

これにより:

- Phase 状況テーブルが「未対応 backlog の可視化」を兼ねる
- 半年後に「あの memo どこだっけ?」とならない
- `git log -- docs/` で過去 follow-up を一覧できる

### Memo を spec 化するタイミング

以下のいずれかが起きたら spec 化を検討:

- ユーザーから「次は X をやろう」と指示された
- 別 spec の作業中に同じ問題に遭遇 (重要度上昇)
- 利用者から実際にフィードバックが届いた

spec 化されたら follow-up memo の内容は spec の requirements / design に取り込み、不要なら削除する (リンクは git log で追える)。

---

## 使用言語 (Language Policy)

- **ドキュメント (英語)**: 本プロジェクトで生成するドキュメント (`requirements.md`, `design.md`, `tasks.md` 等)、コードコメント、コミットメッセージは、技術的な正確性と一貫性を保つため **英語 (English)** で記述する。
- **コミュニケーション (日本語)**: ユーザー（人間）との対話や説明、質問等は **日本語 (Japanese)** で行う。
