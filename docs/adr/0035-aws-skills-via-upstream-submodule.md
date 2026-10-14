---
adr: 35
date: 2026-10-14
status: accepted
---

# AWSスキルを上流submoduleへのsymlinkとmanifestで配布する

## 背景

解く問題: `aws agent-toolkit` が直接入れたAWSスキルを、このリポジトリで管理する。別の端末でも `setup.sh` を実行すれば、同じスキルがClaude CodeとCodexの両方に入る状態にする。

`aws agent-toolkit`（aws-cli 2.37系のサブコマンド）が、AWSのスキル24個を `~/.claude/skills/` と `~/.agents/skills/` へ実ディレクトリとして直接入れた。
ユーザーが内容を確認して12個に絞ったが、どれもこのリポジトリの管理外にある。そのため別の端末では入らない。

スキルの上流は `aws/agent-toolkit-for-aws`（GitHub、Apache-2.0）の `skills/core-skills/<名前>/`。
同じリポジトリが、Claude Codeプラグイン `aws-core` としても配布されている。プラグインにはAWS MCPの設定も含まれる。

## 決定

2026-10-14、ユーザーが会話の中で決めた。プラグイン・コピー・CLIでの導入・submoduleの4案を比べた。
ユーザーは最初、わかりやすさからプラグインを選んだ。比較の材料は、AIがまとめたものだった。
判断が変わったきっかけは、プラグインは丸ごとでしかオン・オフできず、MCPの設定まで一緒に入るという点だった。比較を見たうえで、submoduleを選んだ。
わかりやすさの懸念（symlinkが二段になる）は、READMEに運用の節を設けて補う。

- 上流をリポジトリ直下の `agent-toolkit-for-aws/` にsubmoduleとして置く
- `skills/<名前>` に、submodule内を指すgit管理の相対symlinkを置く（`../agent-toolkit-for-aws/skills/core-skills/<名前>`）
- `manifests/skills.json` の `shared` に名前を足す。配布は既存の `setup.sh` の経路に乗せる
- 配布するのは、ユーザーが選んだ12個（aws-billing-and-cost-management, aws-compute, aws-containers, aws-database, aws-iam, aws-networking, aws-observability, aws-security, aws-serverless, aws-storage, aws-well-architected-review, signing-in-to-aws）
- `setup.sh` の事前検査は、sourceのsymlinkが宣言済みのsubmoduleの配下を指すなら、submoduleが未初期化でも通す。リポジトリの外や、宣言していないパス、絶対パスを指すsymlinkは、今と同じく止める

選んだ理由:

- スキルを12個に絞った選別を保てる
- AWS MCPの設定を持ち込まない。MCPは会社のAWSプロファイル名と権限に関わるので、公開リポジトリに載せず、権限を絞った設定を各端末で持つ
- Claude CodeとCodexの両方へ届く
- 上流の更新を、差分を読んでから取り込める

## 却下した案

### Claude Codeプラグイン `aws-core`

有効・無効をプラグイン単位でしか切り替えられない。25個（core-skillsの24個に aws-secrets-manager を加えたもの）と、MCP設定（`--skip-auth` 付き）が一式で入る。
Codex向けのプラグインもある（`.codex-plugin/`）。比較した時点では「Codexには入らない」と誤認していたが、却下の理由は上の2点で変わらない（2026-10-14、実装中に確認した）。
ユーザーは、ほかのAWSスキルも使う時期が来たら、プラグインへの移行を改めて検討すると決めた。

### 12個をコピーしてコミットする

上流との差分を追えなくなる。更新のたびに手作業でコピーし直すことになる。

### `setup.sh` から `aws agent-toolkit add-skill` を呼ぶ

中身がリポジトリに残らず、導入するたびにその時点の最新版が入る。各端末のaws-cliと、us-east-1でしか動かないtoolkitのAPIにも依存する。

## 結果

- 別の端末でも、`setup.sh` で12個が両ホストに入る
- 新しい端末では、submoduleの初期化より先に事前検査が走る。symlinkの先がまだ無くても止まらない
- `aws agent-toolkit add-skill` と `update-skill` は使わない。2026-10-14に一時的な `HOME` で確かめたところ、`update-skill` はsymlinkを残したまま、リンク先の中身を上書きした。誤って実行すると、submoduleに未コミットの変更が出る

### 諦めたこと

- 上流の未選択スキルや、プラグイン・ツール類もcloneされる（約12.8MB）。配布はしないが、ディスクとcloneの時間は増える
- symlinkが二段になる（`~/.claude/skills/<名前>` → `skills/<名前>` → submodule内）

### 既知のリスク

- submoduleを手で進めないと更新されない。上流の修正を取り込み忘れても、気づく仕組みは無い。`update-skill` の誤実行を止める仕組みも置かない。どちらもユーザーが受け入れた（2026-10-14）。差分に気づいた時点で、遡って取り込めばよいという判断である
- 2026-10-14の時点で、toolkitのAPIが配っていた版（v3）と、GitHubの `main`（9f10c28）の中身が一致しなかった。移行すると、各スキルの中身はGitHubの版に変わる
  - 照合の方法: APIが配った12個の全176ファイルについて、同じ中身がGitHubの履歴（全ブランチ）にあるかをファイルのハッシュで調べた
  - 結果: 97件は `main` と同じだった。25件はGitHubの古いコミット（2026-08）と同じで、GitHubは2026-10に更新済みだった。残りの54件はGitHubのどこにも無く、うち12件は `SKILL.md` のfrontmatterをtoolkitが書き換えたことによる差だった
  - GitHubに無い内容の大半は、GitHubの方が新しい差だった。APIにしか無い内容は少数で、aws-iam の `references/common-pitfalls.md` にある `aws:TagKeys` の節、aws-containers の `beanstalk-cluster-mode.md` などがある。どちらもGitHubのコミット・PR・コード検索に無かった
  - ユーザーは、大半のファイルで新しいGitHubの版を使うと決めた（2026-10-14）。APIにしか無い内容が必要になったら、取り込み方を見直す

### 見直す条件

ほかのAWSスキルを使う時期が来たら、プラグインへの移行を検討する。
toolkitのAPIが配る版とGitHubの版の差が続き、GitHubの版に欠けている内容が要るようになったら、取り込み方を見直す。

## 根拠

- `docs/superpowers/specs/2026-10-14-aws-skills-submodule-design.md`
- `aws/agent-toolkit-for-aws` の `skills/core-skills/` と `plugins/aws-core/`（2026-10-14時点の `main`）
