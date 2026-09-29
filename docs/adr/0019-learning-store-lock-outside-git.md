---
adr: 19
date: 2026-09-29
status: accepted
---

# 学習storeの排他lockをGit metadataの外に置く

## 背景

ADR 0017の専用store実装では、同時保存と旧記録取込の排他に
`<store>/.git/agent-learning.lock`を使っていた。Codexの`workspace-write`で
一時storeを`--add-dir`へ指定した実機対話では、最初のoperation保存が
`WRITE_FAILED: 排他lockを開けません`となった。Codexは書込可能root内でも
`.git`を保護する。後続のresume turnでは保存できる場合があり、再開時だけの
成功を初回の保存能力と取り違えやすかった。

## 決定

排他lockをstore直下の`.learning-store.lock`へ移し、`init`が作る
`.gitignore`でGit管理から除外する。lockは通常file・単一link・実行user所有・
group/otherアクセスなしを確認して開く。保存とimportは同じlockを使う。
Codexではstoreをsessionの書込可能rootへ追加する。`init`と`bind`ではbinding先にも
書込権限を与える。
`status`のOS権限表示はsandbox内の書込保証と扱わず、`record`の結果を確認する。

## 検討した代替案

- **`.git`内のlockを維持して権限昇格する**: 通常のCodex sandboxで記録できず、
  利用者の学習作業ごとに権限境界を変えることになる。
- **排他lockを廃止する**: 同時保存・importと訂正履歴の競合検出が崩れる。
- **ユーザー共通の一時directoryにlockを置く**: storeごとの識別と残存file管理が増え、
  store本体とlockの権限・所有確認を別々に維持する必要がある。

## 結果

Codex sandbox内での初回operation保存を確認できる。store直下にはGit管理外の
lock fileが残る。既存storeにも次回保存時に同じfileを作れるが、旧storeの
`.gitignore`には除外規則が無いため、必要なら除外規則を追加する。
`--add-dir`やマシン固有の書込可能rootを省いたsessionの保存は引き続き失敗する。

## 根拠

- [Codexの承認・sandbox説明](https://learn.chatgpt.com/docs/agent-approvals-security)
- [Codex設定の書込可能root](https://learn.chatgpt.com/docs/config-file/config-reference)
- 2026-09-29の一時Git repoと隔離`XDG_CONFIG_HOME`によるCodex実機検証
- `tests/test_learning_store.py`のlock保護テスト
