---
adr: 18
date: 2026-09-28
status: accepted
---

# Codexサブエージェントの基準ペアをGPT-6へ移す

## 背景

ADR 0010の基準ペアと8件のcustom agentはGPT-5.6に固定されていた。GPT-6の公開後も
既定値と生成済みTOMLが旧世代のままでは、新しいモデルを使う意図が通常の委譲に反映されない。
ユーザーはGPT-6を積極的に使い、将来の世代更新を簡単にする設計はTODOへ分けるよう指定した。

OpenAI公式の標準API単価（100万トークン、272K以下の入力）は、GPT-5.6 Terraが
入力$2・出力$12、GPT-6 Solが入力$2・出力$10。GPT-6 Solは複雑なcodingとagent作業、
Lunaは範囲の狭い反復作業、Astraは特に難しい作業向けと説明されている。
この単価はCodex契約上の実請求額や、タスク完了までの総コストを証明しない。

## 決定

- 通常の既定値は`gpt-6-luna` + `medium`とする。機械作業はLuna low、狭い難問は
  Luna highまたはmaxへ上げる。
- 広い探索は`gpt-6-sol` + `medium`、多層デバッグ・通常の意味的セキュリティレビュー・
  設計・最終統合はSol highを基準とする。特に難しい工程は、検証済みhandoff付きの
  明示ペアで`gpt-6-astra` + `high`を検討する。
- `code-architect`はSol high、`code-explorer`はSol mediumへ変更し、routing文書との
  既知の不一致を解消する。他のroleは役割とeffortを保ってGPT-6へ移す。
- handoff validatorにはGPT-6 Sol/Lunaの使用ペアを追加する。旧GPT-5.6ペアは既存handoffと
  復旧testのために残す。新しいGPT-6ペアの許可effortはCodexの利用可能な範囲で絞る。
- ADR 0010の親工程、provider固定、人間確認の境界は維持する。新規same-thread begin停止は
  ADR 0016に従う。

## 検討した代替案

### 全roleをAstraへ移す

採らない。Astraは高難度向けだが、通常の機械作業まで高い単価で処理する理由がない。
高難度工程での明示的な昇格先として残す。

### GPT-5.6 Terraを広い探索と必須レビューに残す

採らない。GPT-6 Solは公式の位置づけが対象作業に合い、公開単価では入力が同額、出力が
低い。品質・所要時間を含む総コストは未測定なので、代表タスクによる再評価をTODOに残す。

### 新旧モデル名を一括置換する

採らない。過去のADR、実測記録、旧pending復旧fixtureは当時のモデル名自体が証拠である。
validatorの旧ペアも即時削除すると既存handoffを受け取れなくなる。

### 今回すべてのモデル参照を共通定義へ集約する

採らない。世代移行と構造変更を同時に行うと、どちらが回帰原因か追いにくい。
更新点の集約と整合性検査は`tasks/backlog.md`のTODOとして別に設計する。

## 結果

生成元、生成済みagent、setup既定値、handoff validator、routing文書とsecurity policyが
GPT-6の基準ペアで揃う。旧handoffと過去の実測は保持する。

モデル名の設定と静的テストは、実際のsubagentのmodel・reasoning effort・sandboxが
選ばれた証拠ではない。runtime smoke testで確かめる。GPT-6 Solが旧Terraより
品質・所要時間を含む総コストで優れるかも未検証である。

## 根拠

- OpenAI Docs: https://developers.openai.com/api/docs/guides/latest-model
- OpenAI Docs: https://developers.openai.com/api/docs/models/gpt-6-sol
- OpenAI Docs: https://developers.openai.com/api/docs/models/gpt-5.6-terra
- Codex CLI 0.155.1（2026-09-28のローカル`codex --version`）
- `docs/adr/0010-codex-adaptive-model-routing.md`
- `docs/adr/0016-codex-parent-routing-pilot.md`
