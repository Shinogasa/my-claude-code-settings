# 旧形式の skills 親symlinkを自動移行する 設計書

- 日付: 2026-09-30
- 状態: 承認済み（ユーザー承認: 旧形式を見つけたら自動で移行する）
- 関連ADR: `docs/adr/0022-legacy-skills-parent-link-migration.md`（proposed）
- ブランチ: `fix/claude-skills-per-skill-links`

## 1. 背景

`bash setup.sh --all` が exit 2 で止まる。

```
link source and destination overlap after symlink resolution:
source=<repo>/skills/api-design destination=~/.claude/skills/api-design
```

| 確認済みの事実 | 根拠 |
|---|---|
| 旧 `setup.sh` は `~/.claude/skills` と `~/.agents/skills` を **repo の `skills/` へのディレクトリsymlink** として作っていた | `git show f207b3b^:setup.sh` の25行・81行 |
| `f207b3b`（2026-08-26）以降は `manifests/skills.json` に従い **skillごと** に `<host>/skills/<skill>` をリンクする | `setup.sh` の `build_targets`（139行〜） |
| 旧形式から新形式への移行処理は無い | `setup.sh` と `bin/setup-state.py` を確認 |
| 旧形式の親リンクが残ると、`validate_link_target_topology`（416行〜）が自己参照として拒否する。検査は正しい（通すと repo 内に自己参照リンクを作る） | 実行結果とコード |
| `test_codex_rejects_agent_skills_parent_symlink_to_repository`（`540b207`）が「親symlinkは `--replace-conflicts` でも拒否し、何も変えない」を固定している | `tests/test_setup_preflight.py` 520行付近 |
| `backup_conflict` は `os.rename` で宛先を退避する。親がsymlinkのまま動かすと **repo 内の実物** を動かす | `bin/setup-state.py:126` |
| この環境では `~/.claude/skills` が旧形式のまま、`~/.agents/skills` は実ディレクトリ（移行済み） | 実物を確認 |
| Claude Code は claude.ai の skill を `~/.claude/skills/synced/` へ同期する。`synced` は予約名で、利用者のskillとしては読み込まれない | code.claude.com/docs/en/skills |
| Claude Code は personal の `<skill-name>` がsymlinkでも target の `SKILL.md` を読む | 同上「Symlinked folders」 |
| ownership 状態は生成ファイルのsha256だけを記録し、リンクの所有は記録しない | `~/.claude/.my-claude-code-settings/ownership.json` |

旧形式の副作用として、claude.ai の同期が repo の作業ツリー内（`skills/synced/`）へ書き込んでいる。
git では追跡外だが、`git stash -u` に巻き込まれ、テストの skill 分類から除外する対処（`e30671f`）が必要になった。

## 2. 決定

旧形式と**確定できる**親symlinkだけを、フラグ無しで自動移行する。確定できないものは今までどおり拒否する。

### 2.1 旧形式の判定条件（すべて満たすときだけ移行する）

ホストごとに親パス `P`（Claude: `$CLAUDE_DIR/skills`、Codex: `$AGENTS_DIR/skills`）について判定する。
判定の対象は、そのホストが今回選ばれているとき（`selected_claude` / `selected_codex`）だけ。

1. `P` が symlink である
2. `P` の解決先が、**この repo の `skills/`** の解決先と一致する（`Path.resolve()` 同士の比較）
3. `P` の親ディレクトリ（`$CLAUDE_DIR` / `$AGENTS_DIR`）が、symlinkを解決しても repo の外にある

どれか1つでも満たさない場合は移行しない。特に次は**移行せず、今までどおり拒否する**。

| 状況 | 扱い | 理由 |
|---|---|---|
| `P` が別の場所（別clone、自作のskill置き場）へのsymlink | 拒否（今の `validate_link_target_topology` のまま。拒否メッセージに「repo 以外を指すため自動移行しない」を足す） | 形は同じでも由来が違う。外すと向こうのskillが黙って読まれなくなる |
| `P` が壊れたsymlink | 拒否 | 由来を確定できない |
| `P` が実ディレクトリ | 移行不要（既存の処理のまま） | — |

### 2.2 移行の手順

`preflight` の**前**に `migrate_legacy_skill_parents` を1回だけ呼ぶ（`validate_sources true` の直後、849行の `preflight` の前）。
移行後は既存の `preflight` → 再preflight → snapshot 検証 → apply がそのまま走る。

各対象ホストについて:

1. **退避対象の確定**: repo の `skills/` 直下のうち、git に**追跡されていない**項目を列挙する（今は `synced`）。
   - 判定は `git -C "$SCRIPT_DIR" ls-files -- "skills/<name>"` が空かどうか
   - 追跡されている項目は repo の実物なので**動かさない**
2. **一時ディレクトリの作成**: `P` と同じ親の下に `P.migrating.<timestamp>` を実ディレクトリで作る
3. **追跡外項目の移動**: 1 の各項目を、repo の `skills/<name>` から一時ディレクトリへ `os.rename` で移す（同一ファイルシステム内の移動）
   - `synced` 以外の追跡外項目があった場合も同じく移す（利用者が repo 内に直接置いたものを失わないため）
4. **親リンクの差し替え**: `P` のsymlinkを `unlink` し、一時ディレクトリを `P` へ `rename` する
5. 結果を1行ずつ報告する（`注意: ~/.claude/skills を旧形式のsymlinkから実ディレクトリへ移行しました。移した追跡外項目: synced`）

移行処理は Python で書き、`bin/setup-state.py` にサブコマンド `migrate-legacy-skills-parent` として足す（既存の退避・検証と同じ場所にまとめる）。
シェル側はそれを呼ぶだけにする。

### 2.3 失敗時の倒し方

移行は「親リンクがあるか、完成した実ディレクトリがあるか」のどちらかの状態にしか止まらないようにする。

| 失敗した段 | 状態 | 対処 |
|---|---|---|
| 1〜2 | 何も変わっていない | エラーで終了（exit 1） |
| 3 の途中 | 一部の追跡外項目が一時ディレクトリへ移っている。親リンクは残っている | 移した項目を repo の `skills/` へ戻してからエラー終了する。戻せなかった項目は、パスを列挙してエラー終了する |
| 4 の `unlink` の後、`rename` の前 | 親リンクが消え、一時ディレクトリだけがある | 直ちに `rename` を再試行し、失敗したら一時ディレクトリのパスと手で戻す手順（`mv P.migrating.<ts> P`）を表示してエラー終了する |

再実行したときに `P.migrating.*` が残っていたら、移行を始めず、そのパスを表示してエラー終了する（途中状態を上書きしない）。

### 2.4 既存テストとの関係

`test_codex_rejects_agent_skills_parent_symlink_to_repository` は、**repo の `skills/` を指す親symlinkを拒否する**ことを固定している。
今回の決定はこの契約を置き換える。テスト名と期待値を「移行する」へ変え、拒否の契約は「repo 以外を指す親symlink」に移す。
置き換えることは ADR 0022 に明記する。

## 3. 対象ファイル

| ファイル | 変更 |
|---|---|
| `bin/setup-state.py` | サブコマンド `migrate-legacy-skills-parent <parent> <repo_skills> <repo_root>` を追加 |
| `setup.sh` | `migrate_legacy_skill_parents` 関数を追加し、`validate_sources true` と `preflight` の間で呼ぶ。拒否メッセージに理由を足す |
| `tests/test_setup_preflight.py` | 既存の親symlink拒否テストを置き換え、下の 4 章のテストを追加 |
| `tests/test_skill_manifest.py` | `e30671f` で入れた `synced` 除外は**残す**（移行前の環境や、利用者が再び repo 内に置いた場合への防御） |
| `README.md` | 「旧形式からの移行」を1段落追記 |
| `docs/adr/0022-legacy-skills-parent-link-migration.md` | 新規（proposed。実装PRで accepted） |

## 4. テスト

すべて `tests/test_setup_preflight.py` の一時HOMEと repo 複製（`copy_repository`）の上で行う。
repo 複製は git リポジトリとして初期化し、`skills/` 配下を追跡させた状態にする（追跡外判定を実物で検査するため）。

1. **Claude の旧形式を移行する**: `~/.claude/skills` → repo `skills/`。`--claude` で exit 0。`~/.claude/skills` が実ディレクトリになり、manifest の各skillがsymlinkで、repo の `skills/<skill>/SKILL.md` が残っている
2. **Codex の旧形式を移行する**: `~/.agents/skills` で同じ。既存の拒否テストを置き換える
3. **追跡外項目を運ぶ**: repo の `skills/synced/x/SKILL.md`（追跡外）を置いて移行し、`~/.claude/skills/synced/x/SKILL.md` に移っていること、repo の `skills/synced` が無くなっていること
4. **追跡中の項目は動かさない**: 移行後も repo の `skills/api-design/SKILL.md` が同じ内容で残っていること
5. **別の場所を指す親symlinkは拒否する**: 別ディレクトリへのsymlinkなら exit≠0、リンクと参照先が無変更、backups が作られていない。stderr に「自動移行しない」理由が出る
6. **壊れたsymlinkは拒否する**: exit≠0、無変更
7. **途中状態が残っていたら始めない**: `~/.claude/skills.migrating.X` を置いて exit≠0、そのパスが stderr に出る、親リンクが無変更
8. **冪等**: 移行後にもう一度 `--claude` を実行して exit 0、状態が同じ
9. **選ばれていないホストは移行しない**: `--codex` だけのとき、Claude の旧形式リンクは無変更
10. **追跡外項目の移動に失敗したら元に戻す**: 一時ディレクトリへの移動が失敗する状況（移動先に同名の読み取り専用ディレクトリを置くなど、テストで再現できる方法を実装担当が選ぶ）で、親リンクと repo の追跡外項目が元のままであること

## 5. 対象外

- `~/.claude/skills/synced` の同期そのものの停止（`syncClaudeAiSkills`）
- ownership 状態にリンクの所有を記録する拡張
- 他の旧形式リンク（`commands`、`rules` など）。これらは今もディレクトリ単位のリンクで、形式は変わっていない

## 6. 受入条件

- 上の 4 章のテストが通り、全テストが通る
- この環境で `bash setup.sh --all` が exit 0 になり、`~/.claude/skills` が実ディレクトリになる。`/skills` に `learning-mode` が出る。`~/.claude/skills/synced/` に同期済みskillが残っている（実ホスト確認は親）
- repo の作業ツリーから `skills/synced/` が消える
