# 旧形式 skills 親symlinkの自動移行 実装計画

- 設計書（正本）: `docs/superpowers/specs/2026-09-30-claude-skills-legacy-link-migration-design.md`
- ADR: `docs/adr/0022-legacy-skills-parent-link-migration.md`
- ブランチ: `fix/claude-skills-per-skill-links`（mainの `a6a4b63` から作成済み）
- 設計書と本計画が矛盾したら設計書を優先する

各Taskは TDD（RED→GREEN）で進め、Taskごとにコミットする。
コミットメッセージは Conventional Commits・日本語。

## Task 0: 受領と事前確認

- [x] handoff を validator で `validate` し、同じ `INPUT_DIGEST` で handoff・設計書・本計画を `read` で全行読む
- [x] `bin/detect-parallel-sessions` が空配列であることを確認する
- [x] `git status --short` を確認する。`skills/synced/`（追跡外）以外に差分が無いこと
- [x] 関連テストのベースラインを取る: `python3 -m unittest tests.test_setup_preflight tests.test_setup_cli tests.test_skill_manifest`

## Task 1: テストの土台を整える

- [x] `tests/test_setup_preflight.py` の `copy_repository` は git リポジトリを作らない（親が確認済み: `shutil.copytree` だけで `git init` が無い）。
  複製後に `git init`・`git add skills`・commit を行うヘルパーを追加する（追跡外判定を実物で検査するため）
  - git の設定はテスト内で閉じる（`-c user.name=t -c user.email=t@example.com -c commit.gpgSign=false -c core.hooksPath=/dev/null`。`tests/test_detect_parallel_sessions_hook.py` の `git()` と同じ形）
  - **`copy_repository` は開発者の作業ツリーの `skills/` をそのまま複製するため、`skills/synced/` が紛れ込む。** ヘルパーは追跡させる前に複製先の `skills/synced` を削除し、テスト3が置く追跡外項目だけが追跡外になるようにする
  - 既存テストの振る舞いを変えないこと。ヘルパーは新規テストからだけ呼ぶ
- [x] commit: `test: setup移行テスト用に追跡状態を持つrepo複製を追加`

## Task 2: 移行テストを先に書く（RED）

- [x] 設計書 4 章のテスト1〜10を追加する
- [x] 既存の `test_codex_rejects_agent_skills_parent_symlink_to_repository` を、設計書 2.4 どおりに「移行する」テストへ置き換える。拒否の契約はテスト5（別の場所を指すsymlink）へ移す
- [x] 実行して、新規テストが RED になることを確認する。既存の他のテストは通ること
- [x] commit: `test: 旧形式skills親symlinkの自動移行契約を追加`

## Task 3: 移行処理を実装する（GREEN）

- [x] `bin/setup-state.py` に `migrate-legacy-skills-parent` サブコマンドを追加する（設計書 2.1〜2.3）
  - 判定: symlink であること、解決先が repo の `skills/` と一致すること、親が repo の外にあること
  - 途中状態 `*.migrating.*` の検出
  - 追跡外項目の列挙は `git -C <repo_root> ls-files -- skills/<name>` を使う
  - 失敗時の巻き戻し（設計書 2.3 の表）
- [x] `setup.sh` に `migrate_legacy_skill_parents` を追加し、`validate_sources true` と `preflight` の間で呼ぶ
  - 選ばれているホストだけを対象にする
  - 移行したら `yellow` で1行報告する
- [x] `validate_link_target_topology` の拒否メッセージに、repo 以外を指すため自動移行しない旨を足す（別の場所へのsymlinkのとき）
- [x] 全テストを実行して GREEN を確認する
- [x] commit: `fix: 旧形式のskills親symlinkをsetup.shで自動移行する`

## Task 4: ドキュメント

- [x] `README.md` に「旧形式からの移行」を1段落追記する（何を旧形式とみなすか、何を運ぶか、途中状態が残ったときの戻し方）
- [x] `docs/adr/0022-legacy-skills-parent-link-migration.md` を `status: accepted` にする
- [x] commit: `docs: skills親symlinkの移行を記録しADR 0022を採択`

## Task 5: 最終検査

- [x] `python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v`
- [x] `bash -n setup.sh`
- [x] `git diff --check`
- [x] **実環境では `setup.sh` を実行しない**（親が行う）

## 親が担当すること（実装担当は行わない）

- この環境での `bash setup.sh --all` の実行と、`~/.claude/skills` が実ディレクトリになったことの確認
- `/skills` に `learning-mode` が出ること、`~/.claude/skills/synced/` に同期済みskillが残っていることの確認
- Codex で `learning-mode` が見えることの確認
- push、PR作成、merge
