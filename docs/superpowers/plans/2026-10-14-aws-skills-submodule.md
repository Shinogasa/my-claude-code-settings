# AWSスキルのsubmodule取り込み 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 上流 `aws/agent-toolkit-for-aws` をsubmoduleで取り込み、選んだ12個のAWSスキルを `skills/` のsymlinkとmanifestで、Claude CodeとCodexの両方へ配布する。

**Architecture:** submoduleをリポジトリ直下の `agent-toolkit-for-aws/` に置く。`skills/<名前>` には、submodule内を指すgit管理の相対symlinkを置き、manifestの `shared` に名前を足す。`setup.sh` の事前検査は、submoduleが未初期化でもsymlinkの先が宣言済みのsubmoduleの中なら通す。

**Tech Stack:** bash（`setup.sh`）、Python 3 unittest（`tests/`）、git submodule

**Spec:** `docs/superpowers/specs/2026-10-14-aws-skills-submodule-design.md`

## Global Constraints

- 配布する12個: aws-billing-and-cost-management, aws-compute, aws-containers, aws-database, aws-iam, aws-networking, aws-observability, aws-security, aws-serverless, aws-storage, aws-well-architected-review, signing-in-to-aws
- submoduleのパス: `agent-toolkit-for-aws`、URL: `https://github.com/aws/agent-toolkit-for-aws.git`
- symlinkの形: `skills/<名前>` → `../agent-toolkit-for-aws/skills/core-skills/<名前>`（相対パス）
- manifestの形式（schemaVersion 1、キーは `schemaVersion` `shared` `claude` `codex` のみ）は変えない。`shared` は昇順に並べる
- AWS MCPの設定、find-skills、Gemini CLI・Kiro・OpenCodeは対象外
- 作業はworktree（`.claude/worktrees/aws-skills-submodule`、ブランチ `feat/aws-skills-submodule`）で行う。`setup.sh` の実行（Task 7）だけ、マージ後に本体で行う
- TDDの段階ごとにコミットする（REDで1回、GREENで1回）。コミットメッセージに段階と、失敗したテスト・通ったテストを書く
- コード・文書・コミットメッセージは日本語。コミットの末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` を付ける

## Review Focus

1. 新しい端末で、submoduleを初期化する前の事前検査 → 止まらずに進むこと（Task 2のテストで固定）
2. `skills/` のsymlinkが、リポジトリの外や宣言していないパスを指す → 事前検査は今と同じく `source が存在しません` で止まること（Task 2のテストで固定）
3. 上流でスキルの名前やディレクトリが変わり、symlinkの先が無くなる → テストが失敗して気づけること（Task 4のテストで固定）
4. `aws agent-toolkit update-skill` を誤って実行する → (a) submoduleの中身が書き換わるなら `git status`、(b) 配布先のsymlinkが実ディレクトリに置き換わるなら `setup.sh --dry-run` の `conflict` で検出できること（Task 1で挙動を確かめ、Task 5でREADMEに書き分ける）
5. 既存の外部スキル（yomiyasu、best-practice）の配布が壊れない → 既存のテストがすべて通ること（各TaskのGREENで全件実行）

---

### Task 1: `aws agent-toolkit update-skill` の書き込み先を確かめる（P03a）

コードは書かない。結果をspecに記録する。

このTaskはTask 2〜4と独立していて、結果はTask 5のREADMEにしか使わない。AWSの認証が切れている・SSOの再ログインが要るなどで止まったら、(c)「未確認」として理由を記録し、Task 2へ進む。Task 5の前に、もう一度だけ試す（P09a）。

**Files:**
- Modify: `docs/superpowers/specs/2026-10-14-aws-skills-submodule-design.md`（「運用」節）

- [ ] **Step 1: 隔離した環境を作る**

```bash
T=$(mktemp -d); mkdir -p "$T/home/.claude/skills" "$T/fake-submodule"
cp -R ~/.claude/skills/aws-iam "$T/fake-submodule/aws-iam"
printf '\n<!-- probe -->\n' >> "$T/fake-submodule/aws-iam/SKILL.md"
ln -s "$T/fake-submodule/aws-iam" "$T/home/.claude/skills/aws-iam"
shasum -a 256 "$T/fake-submodule/aws-iam/SKILL.md"
```

- [ ] **Step 2: `update-skill` を隔離したHOMEで実行する**

```bash
HOME="$T/home" AWS_CONFIG_FILE=~/.aws/config AWS_SHARED_CREDENTIALS_FILE=~/.aws/credentials \
  aws agent-toolkit update-skill --skill-name aws-iam --agent claude-code --region us-east-1; echo "exit=$?"
```

- [ ] **Step 3: 結果を3つに分類する**

```bash
ls -la "$T/home/.claude/skills/"; shasum -a 256 "$T/fake-submodule/aws-iam/SKILL.md"; grep -c 'probe' "$T/fake-submodule/aws-iam/SKILL.md"
```

- (a) symlinkが残り、`fake-submodule` の中身が変わった → symlinkを経由して書き換える
- (b) symlinkが実ディレクトリに置き換わった → submoduleは無事。配布先とsetup.shの管理が競合する
- (c) 何も変わらない（「最新」と判定されたなど） → 判定できない。specには「未確認」と書く

- [ ] **Step 4: specの「運用」節の1つ目の小項目を、結果に置き換える**

例（(a)の場合）: `- 2026-10-14に一時的なHOMEで確かめた結果、update-skillはsymlinkを経由してリンク先の中身を書き換えた`。(c)の場合は「未確認」と、判定できなかった理由（コマンドの出力）を書く。

- [ ] **Step 5: 後片付けとコミット**

```bash
rm -rf "$T"
git add docs/superpowers/specs/2026-10-14-aws-skills-submodule-design.md
git commit -m "docs: update-skillがsymlinkの先を書き換えるかを確かめた結果を書く"
```

---

### Task 2: `setup.sh` の事前検査で、submodule内を指すsymlinkを許す

**Files:**
- Modify: `setup.sh:179-184`（`is_declared_submodule_source`）
- Test: `tests/test_setup_cli.py`（`SetupDryRunTests` にテストを足す）

**Interfaces:**
- Produces: `is_declared_submodule_source <source>` — sourceがsymlinkなら、リンク先（リポジトリ内の相対パスへ正規化したもの）が `.gitmodules` で宣言されたpathか、その配下なら0を返す。symlinkでなければ今と同じ判定

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_setup_cli.py` の `SetupDryRunTests` に足す。

```python
    def add_external_skill_link(self, name: str, target: str, declare: bool = True):
        """宣言済みsubmoduleの中を指す、未初期化（先が無い）のskill symlinkを置く。"""
        if declare:
            with (self.repository / ".gitmodules").open("a", encoding="utf-8") as gitmodules:
                gitmodules.write(
                    '[submodule "ext-toolkit"]\n'
                    "\tpath = ext-toolkit\n"
                    "\turl = https://example.invalid/ext-toolkit.git\n"
                )
        (self.repository / "skills" / name).symlink_to(target)
        manifest_path = self.repository / "manifests" / "skills.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["shared"] = sorted(manifest["shared"] + [name])
        manifest_path.write_text(json.dumps(manifest, indent=4) + "\n", encoding="utf-8")

    def test_skill_link_into_uninitialized_declared_submodule_passes_preflight(self):
        self.add_external_skill_link("ext-skill", "../ext-toolkit/skills/ext-skill")
        result = self.dry_run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("source が存在しません", result.stderr)

    def test_skill_link_into_undeclared_path_is_rejected(self):
        self.add_external_skill_link("ext-skill", "../not-declared/skills/ext-skill")
        result = self.dry_run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source が存在しません", result.stderr)

    def test_absolute_skill_link_is_rejected_even_into_declared_submodule(self):
        target = self.repository / "ext-toolkit" / "skills" / "ext-skill"
        self.add_external_skill_link("ext-skill", str(target))
        result = self.dry_run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source が存在しません", result.stderr)

    def test_skill_link_escaping_repository_is_rejected(self):
        self.add_external_skill_link("ext-skill", "../../ext-toolkit/skills/ext-skill")
        result = self.dry_run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("source が存在しません", result.stderr)
```

- [ ] **Step 2: REDを確かめる**

Run: `python3 -m pytest tests/test_setup_cli.py -k "skill_link" -v`
Expected: `test_skill_link_into_uninitialized_declared_submodule_passes_preflight` だけがFAIL（stderrに `source が存在しません: .../skills/ext-skill`）。ほかの3つはPASS（今の実装でも拒否するため）

- [ ] **Step 3: REDでコミット**

```bash
git add tests/test_setup_cli.py
git commit -m "test(RED): submodule内を指す未初期化のskill symlinkで事前検査が止まる

test_skill_link_into_uninitialized_declared_submodule_passes_preflight が
「source が存在しません」で失敗することを確かめた。"
```

- [ ] **Step 4: 最小の実装**

`setup.sh` の `is_declared_submodule_source` を置き換える。

```bash
is_declared_submodule_source() {
  local source="$1" relative target declared
  relative="${source#"$SCRIPT_DIR"/}"
  [ -f "$SCRIPT_DIR/.gitmodules" ] || return 1
  if [ ! -L "$source" ]; then
    grep -F "path = $relative" "$SCRIPT_DIR/.gitmodules" >/dev/null 2>&1
    return
  fi
  # symlinkは、リンク先がリポジトリ内の宣言済みsubmoduleの配下にあるときだけ許す
  target="$(readlink "$source")" || return 1
  case "$target" in /*) return 1 ;; esac
  relative="$(python3 -c 'import os, sys; print(os.path.normpath(os.path.join(os.path.dirname(sys.argv[1]), sys.argv[2])))' \
    "$relative" "$target")" || return 1
  case "$relative" in ..|../*) return 1 ;; esac
  while IFS= read -r declared; do
    [ -n "$declared" ] || continue
    case "$relative" in "$declared"|"$declared"/*) return 0 ;; esac
  done < <(sed -n 's/^[[:space:]]*path[[:space:]]*=[[:space:]]*//p' "$SCRIPT_DIR/.gitmodules")
  return 1
}
```

- [ ] **Step 5: GREENを確かめる**

Run: `python3 -m pytest tests/test_setup_cli.py -k "skill_link" -v`
Expected: 4つともPASS

Run: `bash tests/run.sh`
Expected: すべてPASS

- [ ] **Step 6: GREENでコミット**

```bash
git add setup.sh
git commit -m "fix(GREEN): 宣言済みsubmodule内を指すskill symlinkを事前検査で許す

tests/test_setup_cli.py の skill_link の4テストと、tests/run.sh がすべて通った。"
```

---

### Task 3: manifestのテストで、未初期化のsymlinkもスキルとして数える

**Files:**
- Modify: `tests/test_skill_manifest.py:17-23`（`managed_skill_directories`）
- Test: `tests/test_skill_manifest.py`（`TestSkillManifest` にテストを足す）

**Interfaces:**
- Produces: `managed_skill_directories(root) -> set[str]` — `synced` を除き、ディレクトリと、symlink（先が無くてもよい）の名前を返す

- [ ] **Step 1: 失敗するテストを書く**

`TestSkillManifest` に足す。

```python
    def test_dangling_skill_symlink_is_counted(self):
        """submoduleが未初期化でも、symlinkのskillを分類の対象に含める。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "learning-mode").mkdir()
            (root / "ext-skill").symlink_to("../missing-submodule/ext-skill")
            self.assertEqual(managed_skill_directories(root), {"learning-mode", "ext-skill"})
```

- [ ] **Step 2: REDを確かめる**

Run: `python3 -m pytest tests/test_skill_manifest.py -k dangling -v`
Expected: FAIL（`{'learning-mode'} != {'learning-mode', 'ext-skill'}`）

- [ ] **Step 3: REDでコミット**

```bash
git add tests/test_skill_manifest.py
git commit -m "test(RED): 先が無いskill symlinkをmanifestの分類から落とす

test_dangling_skill_symlink_is_counted が ext-skill を数えずに失敗することを確かめた。"
```

- [ ] **Step 4: 最小の実装**

```python
def managed_skill_directories(root):
    """リポジトリが配布するskill directoryを収集する。"""
    # syncedは外部同期が所有するコンテナであり、manifestの配布単位ではない。
    # submodule内を指すsymlinkは、未初期化で先が無くても配布単位として数える。
    return {
        path.name for path in root.iterdir()
        if (path.is_dir() or path.is_symlink()) and path.name != "synced"
    }
```

- [ ] **Step 5: GREENを確かめる**

Run: `python3 -m pytest tests/test_skill_manifest.py -v`
Expected: すべてPASS

- [ ] **Step 6: GREENでコミット**

```bash
git add tests/test_skill_manifest.py
git commit -m "fix(GREEN): 先が無いskill symlinkもmanifestの分類対象に数える

tests/test_skill_manifest.py がすべて通った。"
```

---

### Task 4: submodule・12個のsymlink・manifestを追加する

**Files:**
- Modify: `.gitmodules`、`manifests/skills.json`
- Create: `agent-toolkit-for-aws`（submodule）、`skills/<12個>`（symlink）
- Test: `tests/test_skill_manifest.py`（新しいクラス `TestAwsSkillSubmodule`）

**Interfaces:**
- Consumes: Task 2の `is_declared_submodule_source`、Task 3の `managed_skill_directories`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_skill_manifest.py` の `TestExternalSkillSubmodule` の後に足す。

```python
AWS_SUBMODULE = "agent-toolkit-for-aws"
AWS_SKILLS = (
    "aws-billing-and-cost-management", "aws-compute", "aws-containers", "aws-database",
    "aws-iam", "aws-networking", "aws-observability", "aws-security", "aws-serverless",
    "aws-storage", "aws-well-architected-review", "signing-in-to-aws",
)


def declared_submodule_paths():
    text = (REPO_ROOT / ".gitmodules").read_text(encoding="utf-8")
    return re.findall(r"^\s*path\s*=\s*(\S+)\s*$", text, flags=re.MULTILINE)


class TestAwsSkillSubmodule(unittest.TestCase):
    """AWSスキルを上流submodule内へのsymlinkとして共有配布しているか。"""

    def test_submodule_is_declared(self):
        gitmodules = (REPO_ROOT / ".gitmodules").read_text(encoding="utf-8")
        self.assertIn(f"path = {AWS_SUBMODULE}", gitmodules)
        self.assertIn("url = https://github.com/aws/agent-toolkit-for-aws.git", gitmodules)

    def test_selected_skills_are_relative_links_listed_as_shared(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for name in AWS_SKILLS:
            with self.subTest(name=name):
                link = SKILLS_DIR / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(
                    os.readlink(link), f"../{AWS_SUBMODULE}/skills/core-skills/{name}"
                )
                self.assertIn(name, manifest["shared"])

    def test_every_skill_symlink_points_into_declared_submodule(self):
        declared = declared_submodule_paths()
        for link in SKILLS_DIR.iterdir():
            if not link.is_symlink():
                continue
            with self.subTest(link=link.name):
                target = os.readlink(link)
                self.assertFalse(os.path.isabs(target))
                relative = os.path.normpath(os.path.join("skills", target))
                self.assertTrue(
                    any(relative == path or relative.startswith(path + "/") for path in declared),
                    relative,
                )

    def test_links_resolve_to_skills_when_submodule_is_initialized(self):
        """上流で名前やパスが変わったら、ここで気づく。"""
        if not (REPO_ROOT / AWS_SUBMODULE / ".git").exists():
            self.skipTest("submoduleが未初期化")
        for name in AWS_SKILLS:
            with self.subTest(name=name):
                self.assertTrue((SKILLS_DIR / name / "SKILL.md").is_file())
```

ファイル冒頭の `import` に `import os` を足す。

- [ ] **Step 2: REDを確かめる**

Run: `python3 -m pytest tests/test_skill_manifest.py -k AwsSkillSubmodule -v`
Expected: `test_submodule_is_declared` と `test_selected_skills_are_relative_links_listed_as_shared` がFAIL。`test_links_resolve...` はskip

- [ ] **Step 3: REDでコミット**

```bash
git add tests/test_skill_manifest.py
git commit -m "test(RED): AWSスキルのsubmoduleとsymlinkが無い

TestAwsSkillSubmodule の宣言とsymlinkの2テストが失敗することを確かめた。"
```

- [ ] **Step 4: submodule・symlink・manifestを追加する**

```bash
git submodule add https://github.com/aws/agent-toolkit-for-aws.git agent-toolkit-for-aws
for name in aws-billing-and-cost-management aws-compute aws-containers aws-database aws-iam \
  aws-networking aws-observability aws-security aws-serverless aws-storage \
  aws-well-architected-review signing-in-to-aws; do
  ln -s "../agent-toolkit-for-aws/skills/core-skills/$name" "skills/$name"
done
python3 - <<'PY'
import json
from pathlib import Path
path = Path("manifests/skills.json")
manifest = json.loads(path.read_text(encoding="utf-8"))
aws = ["aws-billing-and-cost-management", "aws-compute", "aws-containers", "aws-database",
       "aws-iam", "aws-networking", "aws-observability", "aws-security", "aws-serverless",
       "aws-storage", "aws-well-architected-review", "signing-in-to-aws"]
manifest["shared"] = sorted(set(manifest["shared"]) | set(aws))
path.write_text(json.dumps(manifest, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
PY
git diff manifests/skills.json
```

`git diff` で、`shared` 以外とインデントが変わっていないことを確かめる。

- [ ] **Step 5: GREENを確かめる**

Run: `python3 -m pytest tests/test_skill_manifest.py -v`
Expected: すべてPASS（`test_links_resolve...` もskipされずにPASS）

Run: `bash tests/run.sh`
Expected: すべてPASS。`tests/test_setup_cli.py` などの `copy_repository` は `agent-toolkit-for-aws/` を複製しないので、Task 2の修正が実際のsymlinkでも効いていることをここで確かめられる

- [ ] **Step 6: GREENでコミット**

```bash
git add .gitmodules agent-toolkit-for-aws skills manifests/skills.json
git commit -m "feat(GREEN): AWSスキル12個をsubmodule内へのsymlinkで共有配布する

TestAwsSkillSubmodule の4テストと tests/run.sh がすべて通った。"
```

---

### Task 5: ADR 0035とREADMEを書く

**Files:**
- Create: `docs/adr/0035-aws-skills-via-upstream-submodule.md`
- Modify: `docs/adr/README.md`（一覧の末尾に1行）、`README.md`（ディレクトリ構成と新しい節）

- [ ] **Step 1: ADRを書く**

`docs/adr/0031-config-repo-worktree-scope.md` と同じ形式（frontmatterに `adr: 35`、`date: 2026-10-14`、`status: accepted`。節は「背景」「決定」「却下した案」「影響」）で書く。中身はspecの「背景」「構成」「採った案の弱点」「却下した案」から取る。「決定」には、2026-10-14にユーザーが会話の中で、プラグイン・コピー・CLI導入・submoduleの4案からsubmoduleを選んだこと、選んだ理由（スキルの選別とMCPの権限の絞り込みを保つ、両ホストへ届く、差分を読んでから更新できる）を書く。「却下した案」には3案とその理由を必ず書く。プラグインについては「他のスキルも使う時期が来たら、プラグインへの移行を改めて検討する」というユーザーの判断も書く。

- [ ] **Step 2: ADRの一覧に行を足す**

`docs/adr/README.md` の表の末尾に足す。

```markdown
| [0035](0035-aws-skills-via-upstream-submodule.md) | AWSスキルを上流submoduleへのsymlinkとmanifestで配布する | 2026-10-14 | accepted |
```

- [ ] **Step 3: READMEのディレクトリ構成を更新する**

`README.md` の「ディレクトリ構成」で、`codex-cli-best-practice/` の行の後に足す。

```
├── agent-toolkit-for-aws/       # AWS公式のスキル集（git submodule。skills/ のsymlinkから一部だけ配布）
```

`skills/` の一覧で、`backend-patterns/` の前に足す。

```
│   ├── aws-*/, signing-in-to-aws/  # AWSスキル（agent-toolkit-for-aws内へのsymlink）
```

- [ ] **Step 4: READMEに運用の節を足す**

「codex-cli-best-practice（submodule）」節の後、「CLAUDE.md と rules/ の使い分け」の前に足す。最後の段落（誤って実行した場合の検出と戻し方）は、Task 1の結果に合わせて次のどれかにする（P03a）。

- (a) symlinkの先を書き換えた: 下の例のとおり、`git status` で検出し `git -C agent-toolkit-for-aws checkout .` で戻す
- (b) symlinkを実ディレクトリに置き換えた: 次の `bash setup.sh --all --dry-run` に `conflict` として出る。`bash setup.sh --all --replace-conflicts` でsymlinkに戻す
- (c) 確かめられなかった: (a)と(b)の両方の検出方法と戻し方を書き、どちらが起きるかは未確認だと明記する

````markdown
## agent-toolkit-for-aws（submodule）

[aws/agent-toolkit-for-aws](https://github.com/aws/agent-toolkit-for-aws) をgit submoduleとして内包している。
配布するのは、`skills/` にsymlinkを置き、`manifests/skills.json` に載せたスキルだけ（経緯はADR 0035）。

スキルを増やす・減らす:

```bash
ln -s ../agent-toolkit-for-aws/skills/core-skills/<名前> skills/<名前>   # 増やす
# manifests/skills.json の shared に <名前> を足して、bash setup.sh --all を実行する
```

減らすときは、symlinkとmanifestの行を消してから `setup.sh` を実行する。

上流の更新を取り込む:

```bash
git submodule update --remote agent-toolkit-for-aws
git -C agent-toolkit-for-aws diff HEAD@{1} -- $(cd skills && for l in aws-* signing-in-to-aws; do printf 'skills/core-skills/%s ' "$l"; done)
```

配布しているスキルの差分を読んでからコミットする。上流でスキルの名前やパスが変わると、`tests/test_skill_manifest.py` が失敗する。

**`aws agent-toolkit add-skill` と `update-skill` は使わない。** 配布先はsymlinkなので、symlinkの先にあるsubmoduleの中身が書き換わるおそれがある。
誤って実行した場合は、`git status` にsubmoduleの未コミットの変更（`modified: agent-toolkit-for-aws (modified content)`）として出る。
`git -C agent-toolkit-for-aws checkout .` で戻す。
````

- [ ] **Step 5: コミット**

```bash
git add docs/adr/0035-aws-skills-via-upstream-submodule.md docs/adr/README.md README.md
git commit -m "docs: AWSスキルの取り込み方をADR 0035とREADMEに書く"
```

原則レビューや日本語文書レビューのフックで止まったら、フックの指示どおりにレビュワーを起動し、返ってきた問いや変更点をユーザーへ伝えてから、コミットし直す。

---

### Task 6: 全件テスト・PRの更新

- [ ] **Step 1: 全件テスト**

Run: `bash tests/run.sh --all`
Expected: すべてPASS。PR前の記録が残る

- [ ] **Step 2: 新しい端末を想定した事前検査**

```bash
T=$(mktemp -d); git clone -q "$(pwd)" "$T/repo" && git -C "$T/repo" checkout -q feat/aws-skills-submodule
mkdir -p "$T/home/.claude" "$T/home/.codex"
HOME="$T/home" bash "$T/repo/setup.sh" --all --dry-run; echo "exit=$?"
rm -rf "$T"
```

Expected: `exit=0`、かつ `skills/aws-iam` を含む `missing:` の行が出る（clone直後で、submoduleは未初期化）。
合格の根拠は「`missing:` にAWSスキルが出ること」とする。「`source が存在しません` が出ないこと」は、検査が走らなかった場合も同じ出力になるので根拠にしない（P07a）。
終了コードが0でなければ不合格として扱う。一時的なHOMEでpluginの照会などが先に失敗した場合は、照会に頼らずに事前検査まで進める方法を探してから判定し直し、探した結果を報告する

- [ ] **Step 3: pushしてPRの本文を更新する**

```bash
git push
gh pr edit 92 --body-file <進捗のチェックを更新した本文>
gh pr ready 92
```

本文の「進捗」で、終わった項目にチェックを付ける。draftを外す前に、ユーザーに確認する。

---

### Task 7: マージ後の移行（本体・ユーザーの了承が要る）

worktreeでは行わない。PRがマージされた後、本体で行う。どのステップも `~/.claude/` などを書き換えるので、実行する前にユーザーの了承を得る。

- [ ] **Step 1: 本体を最新にする**

```bash
cd <本体の作業ツリー> && git switch main && git pull && git submodule update --init --recursive
```

- [ ] **Step 2: 直接入っている12個を退避してから消す（P07a）**

```bash
SKILLS="aws-billing-and-cost-management aws-compute aws-containers aws-database aws-iam \
  aws-networking aws-observability aws-security aws-serverless aws-storage \
  aws-well-architected-review signing-in-to-aws"
B=<scratchpad>/aws-skills-backup; mkdir -p "$B/claude" "$B/agents"
for s in $SKILLS; do cp -R ~/.claude/skills/$s "$B/claude/" && cp -R ~/.agents/skills/$s "$B/agents/"; done
ls "$B/claude" "$B/agents" | grep -c -E '^(aws|signing)'   # 24 であること
for s in $SKILLS; do
  for a in claude-code universal; do aws agent-toolkit remove-skill --skill-name "$s" --agent "$a"; echo "$s/$a exit=$?"; done
done
ls -la ~/.claude/skills ~/.agents/skills | grep -E 'aws|signing'
```

Expected: 退避が24個。`remove-skill` は24回とも `exit=0`。最後の `ls` で何も出ない。
`exit` が0でない行があれば、Step 3へ進まずに止まり、ユーザーに報告する。

- [ ] **Step 2b: 戻す手順（Step 3が失敗したときだけ）**

`setup.sh` が途中で失敗し、スキルが使えない状態になったら、退避した分を書き戻す。

```bash
for s in $SKILLS; do
  rm -f ~/.claude/skills/$s ~/.agents/skills/$s   # setup.shが張ったsymlinkだけを消す（-rは付けない）
  cp -R "$B/claude/$s" ~/.claude/skills/ && cp -R "$B/agents/$s" ~/.agents/skills/
done
```

戻した後に、失敗の理由をユーザーへ報告する。退避は、Step 4の確認が済むまで消さない。

- [ ] **Step 3: setupを実行する**

```bash
bash setup.sh --all --dry-run   # 12個 × 2ホストが missing と出ることを確かめる
bash setup.sh --all
ls -la ~/.claude/skills/aws-iam ~/.agents/skills/aws-iam
```

Expected: どちらも `.../my-claude-code-settings/skills/aws-iam` へのsymlink

- [ ] **Step 4: 両方のホストで読み込めるか確かめる（P17a）**

- Claude Code: 新しいセッションを始め、スキル一覧に `aws-iam` が出ることをユーザーに確かめてもらう
- Codex: `codex exec "aws-iam スキルの description を1行で答えて"` を実行し、SKILL.mdの内容に沿った答えが返ることを確かめる

- [ ] **Step 5: worktreeを片付ける**

```bash
git worktree remove .claude/worktrees/aws-skills-submodule && git branch -d feat/aws-skills-submodule
```
