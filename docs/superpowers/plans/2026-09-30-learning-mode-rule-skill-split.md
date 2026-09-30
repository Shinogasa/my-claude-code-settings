# learning-mode rule／skill分割 実装計画

- 設計書（正本）: `docs/superpowers/specs/2026-09-30-learning-mode-rule-skill-split-design.md`
- ADR: `docs/adr/0021-learning-mode-rule-skill-split.md`
- ブランチ: `docs/learning-mode-rule-skill-split`（mainから作成済み）
- 設計書と本計画が矛盾したら設計書を優先する

各Taskは TDD（RED→GREEN）で進め、Taskごとにコミットする。
コミットメッセージは Conventional Commits・日本語。末尾に次を付ける。

```
Co-Authored-By: Codex <noreply@openai.com>
```

## Task 0: 受領と事前確認

- [x] handoffを validator で `validate` し、同じ `INPUT_DIGEST` で handoff・設計書・本計画を `read` で全行読む
- [x] `bin/detect-parallel-sessions` が空配列であることを確認する（空でなければ停止して親へ報告）
- [x] `git status --short` で、親所有の未コミット差分（handoffの「Git状態」に列挙）以外が無いことを確認する
- [x] 現行 `rules/learning-mode.md` の見出しと行番号を記録する（Task 5 の欠落照合に使う）
- [x] 全テストのベースラインを取る: `python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py'`

## Task 1: 分割後の契約テストを先に書く（RED）

- [x] `tests/test_learning_mode_contract.py` に `TestLearningModeSplit` を追加し、設計書 6.2 の1〜12を実装する
  - skill・references のパスは定数にする（`SKILL = ROOT / "skills" / "learning-mode" / "SKILL.md"` など）
  - ファイルが無い場合も `assertTrue(path.is_file())` で意味のある失敗にする
- [x] 設計書 6.1 の否定assertを skill と references にも適用する
- [x] 実行して、新規テストだけが失敗し、既存テストは通ることを確認する（RED）
- [x] commit: `test: learning-modeのrule/skill分割契約を追加`

## Task 2: skill と references を作る

- [x] `skills/learning-mode/SKILL.md` を設計書 3.2 の順序で作る。本文は現行ruleからの**移動**。書き換えるのは次だけ
  - 相互参照のリンク先（「→『定石の供給』」→「→ `references/delta-supplements.md`」など）
  - 予測フェーズの停止手段は「常時ruleの停止手段で問う」とし、ホスト名を書かない（設計書 6.2.1）
- [x] `skills/learning-mode/references/delta-supplements.md` を作る（現行「概念名の供給」「定石の供給」「次の問いの立て方」）
- [x] `skills/learning-mode/references/rationalizations.md` を作る（現行「合理化防止」の3表）
- [x] `manifests/skills.json` の `shared` に `learning-mode` を追加する（アルファベット順）
- [x] この時点ではruleを変更しない。skill関連テストが通り、ruleのサイズ・手順残存テストだけが失敗することを確認する
- [x] commit: `feat: learning-modeの手順と書式をskillへ切り出す`

## Task 3: 常時ruleを判定と開示順だけにする（GREEN）

- [x] `rules/learning-mode.md` を設計書 3.1 の見出し順に書き直す
  - `## 両学習モードの共通方針` は**1文字も変えない**
  - `## 設計Predict固有の発火規則` で削るのは例示の文と「L1を捨てるわけではない」段落の短縮だけ
  - `## 開示前の禁止事項` に現行の停止手段の表と上書き宣言2件をそのまま移す
  - `## 詳細手順の読み込み` を `rules/code-learning.md` の入口と同じ構造で書く
- [ ] 全テストを実行して GREEN を確認する
- [x] ruleの文字数を出力し、6,000文字以下であることを確認する
- [x] commit: `refactor: learning-modeの常時ruleを判定と開示順に絞る`

## Task 4: 参照元を更新する

- [x] `CLAUDE.md` の学習モード節と「学習アウトプット」行の参照先を設計書 4章どおりに更新する
  - `tests/test_instruction_graph.py` が固定している文字列（`rules/learning-mode.md` の列挙、`## 学習モード` 見出し、「セッション開始時に以下をすべて全文読む」）は変えない
- [x] `output-styles/review-and-design.md` の110行目に skill を併記する
  - `tests/test_learning_mode_contract.py` の `test_review_style_does_not_delegate_to_disabled_plugin`（`rules/learning-mode.md` を含む）を満たし続けること
- [x] `README.md` のディレクトリ構成を更新する
- [ ] 全テストを実行する
- [x] commit: `docs: learning-modeのskill分割に合わせて参照を更新`

## Task 5: 移動の欠落照合と最終検査

- [ ] 現行ruleの各 `###` 見出し配下の段落が、新rule・skill・referencesのいずれかに存在することをスクリプトで照合する
  - 例: 現行の各段落（空行区切り）の先頭40文字を、新3ファイルを連結した本文で検索し、見つからないものを列挙する
  - 見つからない段落は、意図的に削った例示か、移し忘れかを判別してledgerに記録する。移し忘れなら戻す
- [ ] 設計書 6.3 の検査を全部実行し、出力を保存する
- [ ] `docs/adr/0021-learning-mode-rule-skill-split.md` を `status: accepted` にし、「結果」に実測のrule文字数・skill文字数・行数を追記する
- [ ] commit: `docs: ADR 0021を採択し分割後のサイズを記録`

## 親が担当すること（実装担当は行わない）

- `bash setup.sh --all` による配布と、両ホストでの `/skills` 一覧・発火の実ホスト確認
- `/context` での Memory files の減少の実測
- push、PR作成、merge
