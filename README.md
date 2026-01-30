# my-claude-code-settings

Claude Codeの個人設定・スキル・設定ファイルを管理するリポジトリ

参考: https://github.com/affaan-m/everything-claude-code

## セットアップ

このリポジトリをクローン後、以下のコマンドでClaude Codeの設定と同期します：

```bash
# skillsディレクトリをシンボリックリンクで同期
rm -rf ~/.claude/skills
ln -s $(pwd)/skills ~/.claude/skills
```

これにより、このリポジトリの`skills/`ディレクトリがClaude Codeから直接利用されるようになります。

## ディレクトリ構成

- `skills/` - Claude Codeカスタムスキル
  - `backend-patterns/` - バックエンドアーキテクチャのベストプラクティス
  - `coding-standards/` - コーディング規約・標準パターン
