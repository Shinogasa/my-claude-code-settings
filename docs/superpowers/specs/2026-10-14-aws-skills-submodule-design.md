# AWSスキルをsubmoduleで取り込み、manifestで配布する

日付: 2026-10-14
関連: ADR 0035（このspecと同時に書く）、ADR 0022、ADR 0031
決めた人: ユーザー（2026-10-14の会話で、取り込み方・配布するスキル・作業場所を決めた）

## 背景

`aws agent-toolkit`（aws-cli 2.37系のサブコマンド）が、AWSのスキル24個を `~/.claude/skills/` と `~/.agents/skills/` へ実ディレクトリとして直接入れた。ユーザーが内容を確認して12個に絞ったが、どれもこのリポジトリの管理外にある。そのため別の端末では、`setup.sh` を実行しても入らない。

スキルの上流は `aws/agent-toolkit-for-aws`（GitHub、Apache-2.0）の `skills/core-skills/<名前>/`。

## 目的

別の端末でも、`setup.sh` を実行すれば同じ12個がClaude CodeとCodexの両方に入る状態にする。配布するスキルは、ユーザーが選んだものに限る。上流の更新は、差分を読んでから取り込む。

## 対象外

- AWS MCPの設定（`~/.claude.json`、`~/.codex/config.toml`）。会社のAWSプロファイル名を含むので、公開リポジトリに載せない
- `find-skills` など、ほかの管理外スキル
- Gemini CLI・Kiro・OpenCodeへの配布

## 配布する12個

aws-billing-and-cost-management, aws-compute, aws-containers, aws-database, aws-iam, aws-networking, aws-observability, aws-security, aws-serverless, aws-storage, aws-well-architected-review, signing-in-to-aws

## 構成

- 上流をリポジトリ直下の `agent-toolkit-for-aws/` にsubmoduleとして置く
- `skills/<名前>` に、git管理の相対symlinkを置く（`../agent-toolkit-for-aws/skills/core-skills/<名前>`）
- `manifests/skills.json` の `shared` に12個の名前を足す。形式（schemaVersion 1）は変えない
- 配布の経路: submodule → `skills/<名前>`（symlink）→ `setup.sh` → `~/.claude/skills/<名前>` と `~/.agents/skills/<名前>`

`skills/` 配下がそのまま配布対象の一覧になる、という今の約束は変わらない。

## 変更点

### `setup.sh` の事前検査

新しい端末では、1回目の事前検査（`preflight`）がsubmoduleの初期化より先に走る。そのときsymlinkの先がまだ無いので、`source が存在しません` で止まる。

今の例外判定 `is_declared_submodule_source` は、sourceのパス自体が `.gitmodules` で宣言されているかしか見ない。これを広げ、sourceがsymlinkの場合も許す。条件は、そのリンク先（リポジトリ内の相対パスに正規化したもの）が宣言済みのsubmoduleの配下にあること。リンク先がリポジトリの外や、宣言されていないパスを指す場合は、今と同じくエラーにする。

### `tests/test_skill_manifest.py`

- `managed_skill_directories` は `is_dir()` で数えている。submoduleが未初期化だとsymlinkの先が無いので数えられず、分類の検査が失敗する。symlinkも数えるように直す
- 追加する検査
  - `skills/` 配下のsymlinkはすべて、宣言済みのsubmoduleの配下を指す
  - submoduleが初期化済みなら、symlinkはすべて `SKILL.md` を持つディレクトリへ解決できる。上流でスキルの名前やパスが変わったときに検出するため

### テストの進め方

`setup.sh` の修正とテストの修正は、TDDで進める（REDとGREENのたびにコミットする）。`setup.sh` の事前検査は、既存の `tests/test_setup_preflight.py` の形式に合わせ、「submoduleが未初期化で、symlinkの先が無い」状態を再現する。

## 移行（今の端末）

マージした後、本体で次の順に行う。

1. `aws agent-toolkit remove-skill --skill-name <名前> --agent claude-code` と `--agent universal` で、直接入っている12個を消す。消さずに `setup.sh` を実行すると、既存のディレクトリと競合して止まる
2. 本体で `bash setup.sh --all` を実行する。`~/.claude/` などを書き換えるので、ユーザーの了承を得てから行う

## 運用

- 更新: `git submodule update --remote agent-toolkit-for-aws` で上流を取り込み、12個のディレクトリの差分を読んでからコミットする
- 移行した後は `aws agent-toolkit add-skill` と `update-skill` を使わない。symlinkを経由して、submoduleの中身を書き換えるおそれがある
  - 2026-10-14に一時的な `HOME` で確かめた結果、`update-skill` はsymlinkを残したまま、リンク先の中身を書き換えた（`SKILL.md` が上流の版で上書きされ、`.aws-skill-metadata` が書かれた）。版が同じなら「already up to date」で何もしない。版の判定には `.aws-skill-metadata` を使う
  - そのため誤って実行すると、submoduleに未コミットの変更が出る。`git status` で検出できる。READMEには、この検出方法と、`git -C agent-toolkit-for-aws checkout .` と `git -C agent-toolkit-for-aws clean -fd` で戻す手順を書く
- スキルを増やすときは、symlinkを足してmanifestに追加する。減らすときは、その逆を行う
- 運用手順はREADMEに書く

## 作業場所

触るのは `.gitmodules`、`agent-toolkit-for-aws/`（新規）、`skills/` に新しく置くsymlink、`manifests/skills.json`、`setup.sh`、`tests/`、`docs/`、README。既存のスキルは書き換えない。新しいsymlinkは、本体で `setup.sh` を実行するまで動作中のエージェントに影響しないため、worktreeで作業する（ADR 0031）。

## 採った案の弱点

- 上流の未選択スキル（12個）や、プラグイン・ツール類もcloneされる（約12.8MB）。配布はしないが、ディスクとcloneの時間は増える
- symlinkが二段になる（`~/.claude/skills/<名前>` → `skills/<名前>` → submodule内）。各ホストがこの連鎖を解決できるかは、完了条件で確かめる
- submoduleを手で進めないと更新されない。上流の修正を取り込み忘れても、気づく仕組みは無い

## 却下した案

理由の詳細はADR 0035に書く。

- Claude Codeプラグイン `aws-core`: 有効・無効をプラグイン単位でしか切り替えられず、25個（core-skillsの24個に aws-secrets-manager を加えたもの）とMCP設定（`--skip-auth` 付き）が一式で入る（Codex向けのプラグインもあるが、同じく一式で入る）
- 12個をコピーしてコミットする: 上流との差分を追えなくなり、更新のたびに手作業でコピーし直すことになる
- `setup.sh` から `aws agent-toolkit add-skill` を呼ぶ: 中身がリポジトリに残らず、導入するたびに最新版が入る。各端末のaws-cliと、us-east-1でしか動かないtoolkitのAPIにも依存する

## 完了条件

- 新しい端末を想定し、submoduleを初期化していない状態から `setup.sh --all --dry-run` を実行しても、事前検査で止まらない
- テストがすべて通る
- 今の端末で移行した後、12個がsymlinkとして `~/.claude/skills/` と `~/.agents/skills/` に入っている
- 移行した後に新しく始めたClaude Codeのセッションで、スキル一覧に `aws-iam` が出る
- 移行した後に新しく始めたCodexのセッションで、`aws-iam` のスキルを読み込める
