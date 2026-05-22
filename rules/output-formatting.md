---
alwaysApply: true
---

# 出力フォーマット

## URL表示ルール

- URLを含むリストを表示する際、項目名とURLは改行せず1行にまとめる
- テーブル形式よりフラットリスト形式（`- 項目名 URL`）を優先する
- 理由: ユーザーがコピペしやすい形式にするため

良い例:
```
- BFFのdev1環境を作る https://app.asana.com/1/xxx/project/yyy/task/zzz
- コイン残高APIの実装 https://app.asana.com/1/xxx/project/yyy/task/zzz
```

悪い例:
```
| タスク | URL |
|---|---|
| BFFのdev1環境を作る | https://app.asana.com/1/xxx/project/yyy/task/zzz |
```
