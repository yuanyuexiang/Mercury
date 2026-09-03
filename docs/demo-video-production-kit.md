# Mercury 90 秒演示视频制作包

版本：v1.0  
用途：英文获客主视频，可投放 YouTube、X、LinkedIn、Telegram 私聊和落地页。  
核心观众：已经用 Telegram 承接咨询的海外 SaaS、API、开发者工具及 B2B 服务团队负责人。

## 一、视频只讲一个故事

一个半夜进入 Telegram 的潜在客户先获得有依据的产品回答，随后表达采购意向；Mercury 将其识别为高意向线索并交给真人。老板第二天打开后台时，已经知道客户是谁、为什么值得跟进、从哪个渠道而来。

视频不解释 RAG、向量数据库、Agent 或技术架构。全片只证明四件事：

1. 用企业资料回答 Telegram 咨询；
2. 资料不足或问题敏感时不擅自承诺；
3. 从自然对话中生成、评分销售线索；
4. 高意向转人工，并记录渠道来源。

## 二、最终成片规格

- 时长：75–90 秒，目标 84 秒；
- 画幅：主版 1920×1080，另裁 1080×1080；
- 帧率：30 fps；
- 语言：英文旁白 + 烧录英文字幕；
- 录屏：Telegram 使用手机竖屏，后台使用桌面横屏；
- 节奏：每 3–6 秒必须出现一次明显的画面变化；
- 鼠标：开启点击高亮，移动要慢，避免来回寻找；
- 隐私：只使用 `scripts/seed_demo.py` 生成的虚构人物与数据；不得出现真实 Token、邮箱、服务器地址或客户资料；
- CTA 链接：使用后台「推广获客」页生成的 `video_demo` 渠道深链。

## 三、逐秒分镜与旁白

### 0:00–0:06｜钩子

**画面**

- 黑底白字快速出现：`A buyer messages you on Telegram at 3:07 AM.`
- 切入 Telegram 对话，顶部保留 Mercury Bot 名称。

**旁白**

> A potential buyer messages your business on Telegram while your team is asleep.

**屏幕字幕**

`A buyer. 3:07 AM. No one online.`

### 0:06–0:23｜有依据地回答

**画面**

依次发送下面两条消息，每条停留到机器人回复完整出现：

```text
Can you deploy this for our own Telegram bot?
```

```text
How much is the pilot, and how soon can it go live?
```

回复出现后，用轻微放大突出价格和交付周期；不要把等待过程全部保留在成片中。

**旁白**

> Mercury answers from your approved product documents, including deployment, pricing and delivery details. If the answer is not in your materials, it does not invent one.

**屏幕标签**

- `Answers from approved docs`
- `No invented pricing or promises`

### 0:23–0:39｜自然识别购买意向

**画面**

发送：

```text
We're a 50-person SaaS company. We need HubSpot integration and want a demo next week. Budget is around $1,000. Contact me at alex@northstar.example.
```

机器人确认需求后，画面右侧依次浮现四个简洁标签：

- `50-person SaaS team`
- `HubSpot`
- `$1,000 budget`
- `Demo next week`

**旁白**

> As the conversation continues, it captures the company, requirement, budget and timeline naturally — without forcing the buyer through a long form.

### 0:39–0:49｜敏感问题转人工

**画面**

发送：

```text
Can you change the contract and sign our DPA?
```

保留机器人转人工提示，随后切到后台「会话」列表中醒目的待接管状态。

**旁白**

> Contract, privacy and other sensitive questions go straight to a person. Once a human takes over, the AI stays silent.

**屏幕标签**

`Human handoff — AI pauses`

### 0:49–1:08｜老板看到的结果

**画面**

按以下顺序录制后台，使用硬切，不在页面之间展示加载过程：

1. 「概览」：停留在漏斗和今日数字，2 秒；
2. 「会话」：点击待接管的 Julia 或其他虚构高意向会话，3 秒；
3. 会话详情：突出线索字段、分数和评分理由，5 秒；
4. 「线索」：展示高意向列表，3 秒；
5. 「推广获客」：展示不同渠道的会话、线索和高意向数，3 秒。

**旁白**

> Your team sees a prioritized lead, the reasons behind the score, the full conversation, and the channel that produced it. High-intent buyers stop getting buried in support chat.

**屏幕标签**

- `Explainable lead score`
- `Full conversation context`
- `Channel attribution`

### 1:08–1:20｜一句话收束

**画面**

Telegram 手机画面和后台桌面画面并排。中间出现：

`Telegram conversations → qualified sales leads`

**旁白**

> Mercury turns Telegram conversations into qualified sales leads — automatically, with a human always in control.

### 1:20–1:27｜CTA

**画面**

品牌页定格，显示 Telegram 二维码和短句：

```text
7-day Telegram Lead Pilot
Talk to the bot. The demo is the product.
```

底部小字：

```text
Limited paid pilot · Scope confirmed after a short review
```

**旁白**

> Talk to the bot and try the workflow yourself. Apply for a seven-day paid pilot.

不在视频中承诺固定价格、转化率、SLA 或无法控制的销售结果。价格放在机器人知识库和后续沟通中，以便调整验证。

## 四、录制顺序

不要按成片顺序录制。按下面顺序能减少重录：

1. 重建演示数据；
2. 单独录制所有后台镜头；
3. 用测试 Telegram 账号完整走一遍客户对话；
4. 单独录制 Telegram 镜头；
5. 录制 CTA 二维码静态画面；
6. 录旁白；
7. 按逐秒分镜剪辑；
8. 最后加入字幕、放大框和点击音效。

Telegram 对话建议预先复制到手机备忘录，逐条粘贴发送，避免录制时输入错误。后台镜头每段多录 3 秒头尾，方便剪辑。

## 五、录制前检查表

### 环境

- [ ] 使用专门的演示数据库，而不是生产客户数据库；
- [ ] 执行 `uv run python scripts/seed_demo.py`，后台能看到完整漏斗、会话、线索和渠道数据；
- [ ] Telegram Bot 名称、头像和欢迎语均为 Mercury；
- [ ] 已上传 `docs/knowledge/` 下的演示知识库并完成索引；
- [ ] 模型连接测试通过；
- [ ] 运营者 Telegram 能收到高意向或人工接管通知；
- [ ] 后台浏览器缩放设为 100%，没有开发者工具、书签栏和密码提示；
- [ ] 手机开启勿扰模式，隐藏通知预览和状态栏中的个人信息；
- [ ] 后台「推广获客」已生成 `video_demo` 深链和二维码。

### 功能彩排

- [ ] 两个资料内问题能得到正确回答；
- [ ] 回答中没有虚构价格、折扣或承诺；
- [ ] 50 人、HubSpot、预算、邮箱、下周 Demo 能进入线索字段；
- [ ] 线索达到高意向，评分理由可见；
- [ ] 合同/DPA 问题触发人工接管；
- [ ] `human_active` 状态下再发一条测试消息，AI 不回复；
- [ ] 会话来源显示为 `video_demo`；
- [ ] 全流程没有真实客户数据或密钥。

### 视觉

- [ ] 手机字体和后台文字在 1080p 下可读；
- [ ] 高意向分数、评分理由和渠道归因各有一次特写；
- [ ] 删除所有加载等待、页面抖动和误点击；
- [ ] 背景音乐不盖过旁白；
- [ ] 字幕与旁白逐句一致；
- [ ] CTA 至少停留 5 秒，二维码可实际扫码。

## 六、失败时的备选镜头

- 实时模型回复太慢：彩排时录好完整回复，成片删掉等待时间；不要伪造回复内容。
- Telegram 网络不稳定：使用之前录好的真实对话镜头，不用静态设计稿冒充运行效果。
- 线索提取未及时完成：先完成整段对话，等待后台任务结束后再单独录后台。
- Google Sheets 暂时不可用：本主视频只展示后台同步状态；恢复后另录 10 秒 Sheet 镜头作为销售通话补充材料。
- 演示环境临时故障：使用种子数据录老板视角，并明确保留一份完整、已成功运行的 Telegram 对话素材。

## 七、剪辑交付物

最终保留以下文件：

```text
demo-video/
├── mercury-demo-16x9.mp4
├── mercury-demo-square.mp4
├── mercury-demo-en.srt
├── mercury-demo-thumbnail.png
├── telegram-raw.mp4
├── admin-raw.mp4
├── voiceover.wav
└── recording-notes.md
```

建议缩略图文案：

```text
Turn Telegram Chats
Into Qualified Leads
```

发布说明首句统一使用：

> Mercury answers Telegram inquiries from your own documents, qualifies each buyer, and hands high-intent conversations to your team.

