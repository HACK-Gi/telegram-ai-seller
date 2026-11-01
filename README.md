# Telegram AI Auto-Seller (SaaS)

ប្រព័ន្ធលក់ឯកសារឌីជីថលលើ Telegram ជាភាសាខ្មែរ មាន ៣ ផ្នែក៖

| ផ្នែក | តួនាទី | ស្ថានភាព |
|---|---|---|
| **Userbot (Telethon)** | អ្នកលក់ AI — ឆ្លើយអតិថិជន ២៤/៧ ដោយប្រើលេខទូរស័ព្ទផ្ទាល់ខ្លួន | ជំហានទី ២ |
| **Admin Bot (Aiogram)** | ផ្ទាំងគ្រប់គ្រងសម្រាប់ម្ចាស់តែប៉ុណ្ណោះ — **មិនឆ្លើយអតិថិជន** | ✅ ជំហានទី ១ រួច |
| **SaaS $3/ខែ** | ការជាវ + បញ្ជាក់ស្លីប ដោយ admin | ជំហានទី ៣ |

គោលការណ៍សំខាន់ដែលប្រព័ន្ធដើរតាម៖ **AI មិនបញ្ចេញ Code ដោយខ្លួនឯងទេ** — ម្ចាស់ជាអ្នក
ចុច «ផ្ទៀងផ្ទាត់ + បញ្ចេញ Code» ក្នុង Panel។

---

## ១. តំឡើង

```bash
cd telegram-ai-seller
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # រួចកែតម្លៃក្នុង .env
```

តម្លៃចាំបាច់ក្នុង `.env`៖

| អថេរ | អត្ថន័យ |
|---|---|
| `BOT_TOKEN` | Token ពី `@BotFather`។ ដាក់ `MOCK` បើសាកល្បងដោយគ្មានបណ្តាញ |
| `OWNER_ID` | Telegram ID របស់ម្ចាស់ (រកពី `@userinfobot`) — គត់គេដែលចូល Settings/Admins បាន |
| `ADMIN_IDS` | ID ជំនួយ (ឆ្លាស់គ្នាដោយ `,`) អាចទទេ |
| `AI_BACKEND` | `mock` \| `qoder_cli` \| `openai` \| `ollama` |
| `SESSION_FERNET_KEY` | បង្កើត៖ `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` (ប្រើនៅជំហានទី ២) |
| `TG_API_ID` / `TG_API_HASH` | ពី `my.telegram.org/api/credentials` (ប្រើនៅជំហានទី ២) |

លើកដំបូង អាចដាក់ `BOT_TOKEN=MOCK` និង `USE_MOCK_BOT=true` បាន ព្រោះប្រព័ន្ធមាន
Mock Telegram session ក្នុង `admin_bot/mock.py` សម្រាប់តេស្ត។

## ២. ដំណើរការ

```bash
python main.py                      # Admin Bot + កិច្ចស្វ័យប្រវត្តិ
python scripts/smoke_test.py        # តេស្ត ១២១ ជំហានក្នុង Panel (គ្មាន token, គ្មានបណ្តាញ)
python scripts/smoke_test_ai.py     # តេស្ត ៣២ checks — echo guard + fallback chain
python scripts/smoke_test_userbot.py    # តេស្ត ១១៥ checks — sticky + catalog + voice gate (គ្មានបណ្តាញ)
python scripts/smoke_test_migration.py  # តេស្ត ៣២ checks — migration v4 + oversell (ច្បាប់ app.db, គ្មានប៉ះពិត)
```

`main.py` នឹង៖ បង្កើតតារាង + តម្លៃលំនាំដើម → ចាប់ផ្តើម APScheduler → poll Telegram។
បើគ្មាន `BOT_TOKEN` ពិត វានឹងបិទខ្លួនឯងដោយបង្ហាញការណែនាំ (មិនបាច់ភ័យ)។

កំណត់ហេតុទាំងអស់សរសេរទៅ `logs/app.log` (៥MB × ៥ កំណាត់)។

### ដំណើរការជាសេវា (ណែនាំ)

ប្រើ systemd ដើម្បីឱ្យវាស្វ័យប្រវត្តិ restart ពេលដួល៖

```ini
# /etc/systemd/system/ai-seller.service
[Unit]
Description=Telegram AI Auto-Seller
After=network-online.target

[Service]
WorkingDirectory=/path/to/telegram-ai-seller
ExecStart=/path/to/telegram-ai-seller/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## ៣. ម៉ឺនុយ និងពាក្យបញ្ជា

ចូល Bot រួចចុច `/start` ឬ `/menu` ដើម្បីមើលប៊ូតុងទាំងអស់។

| ប៊ូតុង | អ្វីដែលធ្វើ |
|---|---|
| 📦 ផលិតផល | បង្កើត/កែ/លុប, បញ្ចូល Stock (auto codes `{CODE}-S001` ឬ manual), រូបភាព, discount, ចម្រោះតាមប្រភេទ, ស្វែងរក |
| 📦 ប្រភេទអីវ៉ាន់ | ៧ ប្រភេទលំនាំដើម + «ទូទៅ» — បន័ែម/កែ/prefix/បិទ-បើក/លុប (រាំងបើមានផលិតផល) |
| 💳 QR Code | **Upload រូបភាព QR ពិតពី App ធនាគារតែប៉ុណ្ណោះ** (គ្មានបង្កើត PNG ស្វ័យប្រវត្តិ), កំណត់ Default, ភ្ជាប់នឹងផលិតផល |
| 🧠 System Prompt | កែ Persona, Few-shot, សាកល្បង AI ភ្លាម |
| 🛒 Orders | Tab ស្ថានភាព, មើលស្លីប, **ផ្ទៀងផ្ទាត់ + បញ្ចេញ Code**, បោះបង់, កំណត់ត្រា |
| 👥 អតិថិជន | CRM៖ Tag, កំណត់ត្រា, Pause AI ម្នាក់ៗ, Block, សម្អាត Context |
| 📱 គណនី Telegram | មើល/លុបគណនី, Set Primary, AI on/off (បន្ថែមគណនី = ជំហានទី ២) |
| 📊 Analytics | ចំណូល, Order, អតិថិជនថ្មី/ចាស់, ផលិតផលលក់ដាច់, របាយការណ៍ ៤ ចន្លោះពេល |
| ⚙️ ការកំណត់ | Working hours, សារក្រៅម៉ោង, Toggle AI/Userbot ទាំងអស់, threshold, ភាសា, Backup/Restore |
| 🔐 Admins | បន័ែម/លុប admin ជំនួយ (owner តែប៉ុណ្ណោះ) |

ពាក្យបញ្ជា៖ `/start` `/menu` `/help` `/id` `/cancel` `/orders` `/stats`
`/categories` `/addcategory` `/products` `/addproduct` `/addstock <code>` `/lowstock`
`/pause <telegram_id>` `/resume <telegram_id>` `/pauseall` `/resumeall`
`/addadmin <id> <ឈ្មោះ>` `/deladmin <id>`

## ៤. ម៉ាស៊ីន AI (pluggable)

`ai_engine/` មាន ៤ ក្បាល ជ្រើសរើសដោយ `AI_BACKEND`៖

* `mock` — ឆ្លើយតាម keyword សម្រាប់សាកល្បង (គ្មានបណ្តាញ)
* `qoder_cli` — ហៅ CLI តាម `asyncio.create_subprocess_exec` (**មិនឆ្លងកាត់ shell** ដូច្នេះ
  អត្ថបទពីអតិថិជនមិនអាចចាក់បញ្ចូល command បានទេ)។ តម្លៃ `{prompt}` ក្នុង `QODER_CLI_ARGS`
  ត្រូវជំនួសដោយ transcript ទាំងមូល។ *កុំភ្លេច៖ ពិនិត្យ license/usage terms របស់ CLI មុនប្រើក្នុងបរិបទពាណិជ្ជកម្ម។*
* `openai` — endpoint ណាក៏បានដែលមាន `/chat/completions` (vLLM, LM Studio, OpenRouter…)
* `ollama` — `/api/chat`

Prompt ដែលផ្ញើទៅ AI = System Prompt + Few-shot + **Catalog ផលិតផលពី DB**
(`ai_engine/prompting.py`) ដូច្នេះ AI ឃើញតម្លៃ និង stock ពិតប្រាកដ តែត្រូវបង្គាប់
ថាកុំបញ្ចេញ Code ដោយខ្លួនឯង។

`BackendChain` (`ai_engine/chain.py`) រក្សាស្ថិរភាព៖ ចម្លើយទទេ/ខ្លីពេក/ជា echo → retry ម្តង
រួចលោតទៅ fallback (openai បើ `OPENAI_BASE_URL` មាន)។ បើគ្រប់ backend បរាជ័យ → ម្ចាស់ទទួល
"⚠️ AI ទាំងអស់បរាជ័យ!" ហើយអតិថិជនទទួលសារសុវត្ថិភាព «សូមរង់ចាំបន្តិច ខ្ញុំកំពុងពិនិត្យ។»។
Panel បង្ហាញ backend ពិត (`backend: qoder_cli · 12.3s`) ជាមួយ ⚠️ ពេលលោត fallback។

## ៥. រចនាសម្ព័ន្ធ

```
main.py                 ចំណុចចូល
config.py helpers.py    ការកំណត់ + ជំនួយទូទៅ (UTC ក្នុង DB, បង្ហាញម៉ោងក្នុងស្រុក)
database/               models.py (៩តារាង) · session.py · crud.py (គ្រប់ការងារទិន្នន័យ)
admin_bot/              access.py (StaffGate) · bot.py · keyboards.py · render.py
  media.py mock.py        · handlers/ (products, qrcodes, prompt, orders, customers,
                           accounts, analytics, settings)
ai_engine/              base · mock · qoder_cli · openai_compat · ollama · prompting · chain
services/               backup.py · reports.py · scheduler.py (២១:០០ របាយការណ៍,
                        ចន្ទ ០៩:០០ សេចក្តីសង្ខេប, backup រាល់ ២៤ ម៉ោង, stock តិច)
userbot/                (ជំហានទី ២.១ — ដំណើរការ)៖ manager.py (multi-account +
                        hot-reload ៦០s) · seller.py (sticky bind + AI reply + off-hours
                        + voice gate + code delivery) · catalog.py (inline buttons
                        សម្ភារៈ → ទិញ → QR) · controls.py (/pause /resume /pauseall
                        /stopbot /startbot /status) · outbox.py (single writer ក្នុង
                        មួយគណនី) · limits.py · session_store.py · safety.py ·
                        coalescer.py · text_delay.py · chat_login.py (login តាម chat)
data/ media/ backups/ logs/   ទិន្នន័យម៉ាស៊ីន — gitignore ទាំងអស់
```

រូបភាព និង QR ត្រូវរក្សាទុក **២ កន្លែង**៖ `file_id` (សម្រាប់ Bot) និងឯកសារក្នុង `media/`
(សម្រាប់ Telethon ជំហានទី ២ — file_id របស់ Bot មិនអាចប្រើដោយ client ផ្សេងបានទេ)។

## ៦. សុវត្ថិភាព (អានមុនប្រើ)

* Panel ចម្លើយតែ **owner + admin** ប៉ុណ្ណោះ។ អ្នកប្រើផ្សេងទៀតត្រូវបដិសេធស្ងាត់ៗ។
* ជំហានទី ២ (Userbot) នឹង៖ ចម្លើយ **តែអតិថិជនដែលផ្ញើសារមកមុន (inbound only)**, ពន្យារ
  ៥–១៥ វិនាទីរវាងសារ, រៀប typing, កំណត់ ៥០ សារ/ម៉ោង និង ២០០ សារ/ថ្ងៃ ក្នុងមួយគណនី,
  មាន warm-up ៧ ថ្ងៃ, និង **មិន log session ឬ OTP**។
* ការបន័ែមគណនីធ្វើ **តាម chat Admin Bot** (`/addaccount` ឬចុច ➕ ក្នុង menu Accounts) ហើយ
  សារ OTP/2FA ដែល admin វាយចូល **ត្រូវលុបភ្លាម** ពេលអានរួច (`_delete_secret`) ទើប code
  មិនសល់ក្នុង history របស់ Bot។ OTP/2FA/session មិនដែលចូល log ឬ chat ឡើយ — session
  string រក្សាទុក Fernet ក្នុង DB តែប៉ុណ្ណោះ។ (CLI login ត្រូវបានលុបចេញ — មានផ្លូវ chat តែមួយ)
* `.env` និង `data/` ស្ថិតក្នុង `.gitignore` — កុំពិនិត្យវាចូល repository ឡើយ។

### ៦.១ បើក Userbot (ជំហានទី ២.១)

1. ដាក់ `TG_API_ID`, `TG_API_HASH`, `SESSION_FERNET_KEY` ក្នុង `.env`
2. ចុះឈ្មោះគណនីនីមួយៗ **តាម chat Admin Bot**៖ `/addaccount +855XXXXXXXX` (ឬ `+addaccount`
   តាមប៊ូតុង ➕) — Bot សួរលេខ → OTP → 2FA (បើមាន) → រក្សាទុក session។ សារ OTP/2FA ត្រូវ
   **លុបភ្លាម** បន្ទាប់ពីអាន, ខុស ៣ ដង ឬអត់ឆ្លើយ ៥ នាទី (OTP) / ៣ នាទី (2FA) → login បញ្ចប់ខ្លួនឯង,
   និង `/cancel` បោះបង់គ្រប់ពេល។ (ផ្លូវ CLI លុបចេញហើយ — មិនមាន OTP វាយក្នុង terminal ទេ)
3. បើក `python main.py` — គណនីដែល `enabled` ភ្ជាប់ស្វ័យប្រវត្តិ; បន្ថែម/បិទគណនីថ្មី
   តាម panel ឃើញផលក្នុង ≤ ៦០ វិនាទី (hot-reload គ្មាន restart — coordinator ហៅ `reconcile()` ភ្លាម)
4. បញ្ជាសង្គ្រោះបន្ទាន់ពី Telegram ផ្ទាល់ (send ទៅលេខគណនី userbot)៖
   `/pause <id>` · `/resume <id>` · `/pauseall` · `/resumeall` · `/stopbot` · `/startbot` · `/status`

ច្បាប់ sticky គឺ hard-rule៖ អតិថិជនសរសេរមក A → តែ A តប។ បើគេសរសេរមក B → B មិនតប
ទេ ហើយម្ចាស់ទទួលបានជូនដំណឹង (គ្មាន auto-switch/RR សម្រាប់ inbound — ការផ្ញើរាល់ចេញពី
គណនីទៅមនុស្សមិនស្គាល់គឺជាផ្លូវ ban)។ តេស្ត៖ `python scripts/smoke_test_userbot.py` (១៥៥ checks គ្មានបណ្តាញ)។

### ៦.២ ហាងលក់ពេញលេញលើ Userbot (inline catalog)

* សារដំបូងពីអតិថិជន → ស្វាគមន៍ + ប៊ូតុងប្រភេទ (ទំនាក់ទំនងដំបូងមិនហៅ AI ទេ)។
  វាយ «menu/មេនុ/catalog…» គ្រប់ពេល → មើលសម្ភារៈឡើងវិញ។
* លំហូរទិញ៖ ប្រភេទ → ផលិតផល → «🛒 ទិញឥឡូវ» → ស្តុកត្រូវ**កក់ (reserve)** + បង្កើត Order
  → ផ្ញើ QR + ជូនដំណឹងម្ចាស់ → អតិថិជនផ្ញើរូប slip → ម្ចាស់ផ្ទៀងផ្ទាត់ក្នុង Panel → Code
  (content ពិត ឧ. username|password) ចេញពីគណនី sticky តែមួយ។ គ្មាន order_id លើ QR ទេ
  ដើម្បីកុំឱ្យ mark_code_sent សម្រាប់សារដែលមិនមែនជា Code។
* **Oversell ត្រូវរាំង**៖ កក់បើសល់គ្រប់រឿងទេបោះបង់ order ស្វ័យប្រវត្តិ («🔴 ស្តុកអស់…»)។
  បោះបង់ order → Code ត្រឡប់ទៅ stock វិញ។
* **Voice/Video note ត្រូវបដិសេធ** ដោយសារខ្មែរ (text ✅ · រូបភាព/slip ✅ · voice ❌ ·
  video note ❌ · sticker ❌ មិនឆ្លើយ)។ សារ catalog/voice មិនចូល AI context ទេ (no_log)
  ប៉ុន្តែរាប់ budget ដូចគ្នា។
* ទំព័រ schema បច្ចុប្បន្ន **v4** (additive ជានិច្ច — មិនដែល DROP)៖ categories,
  product_code, stock reservation, default prompt refresh (ជំនួសតែលំនាំដើមចាស់ មិនប៉ះ
  កំណត់ហេតុម្ចាស់)។

## ៧. គម្រោង

* [x] **ជំហានទី ១** — Core scaffold: DB ទាំងអស់, Admin Panel ពេញលេញ, AI engine ៤ ក្បាល, backup/របាយការណ៍
* [x] **ជំហានទី ២.១** — Userbot multi-account (Telethon): sticky sessions, hot-reload, anti-ban
      (១១៥/១១៥ checks គ្មានបណ្តាញ — live test ត្រូវការ TG_API_ID/HASH + Fernet key)
* [x] **ជំហានទី ២.១b** — ហាងលក់ពេញលេញ៖ ៧ ប្រភេទ + product_code, stock reservation
      + oversell prevention, inline catalog (welcome→categories→product→🛒→QR),
      voice/video rejection, prompt ថ្មី categories-aware (Panel ១២១ · userbot ១១៥ ·
      migration ៣២ · AI ៣២ ឆ្លងកាត់ទាំងអស់)
* [ ] **ជំហានទី ២.២** — ភ្ជាប់ Panel ឱ្យបញ្ជា userbot ផ្ទាល់ (send-from-sticky-account, live status) + live test
* [ ] **ជំហានទី ៣** — SaaS $3/ខែ (តែលើ Bot API)៖ `/subscribe`, ស្លីប, admin បញ្ជាក់, ជូនដំណឹងមុនផុតកំណត់ ៣ ថ្ងៃ
