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
| `AI_BACKEND` | `mock` \| `groq` \| `qoder_cli` \| `openai` \| `ollama` (ណែនាំ `openai` = Qoder Proxy, មើល ៤.១) |
| `SESSION_FERNET_KEY` | បង្កើត៖ `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` (ប្រើនៅជំហានទី ២) |
| `TG_API_ID` / `TG_API_HASH` | **ចាំបាច់** — App តែមួយសម្រាប់គ្រប់គណនី ហើយអានពី `.env` តែប៉ុណ្ណោះ (មិនដែលវាយតាម chat ទេ)។ ខ្វះ/ខុស → `/addsession` បដិសេធ ព្រមទាំងណែនាំជំហាន |

លើកដំបូង អាចដាក់ `BOT_TOKEN=MOCK` និង `USE_MOCK_BOT=true` បាន ព្រោះប្រព័ន្ធមាន
Mock Telegram session ក្នុង `admin_bot/mock.py` សម្រាប់តេស្ត។

## ២. ដំណើរការ

```bash
python main.py                      # Admin Bot + កិច្ចស្វ័យប្រវត្តិ
python scripts/smoke_test.py        # តេស្ត ១៩៥ ជំហានក្នុង Panel (គ្មាន token, គ្មានបណ្តាញ)
python scripts/smoke_test_ai.py     # តេស្ត ៣៧ checks — echo guard + fallback chain
python scripts/smoke_test_userbot.py    # តេស្ត ២០៣ checks — sticky + catalog + voice gate (គ្មានបណ្តាញ)
python scripts/smoke_test_migration.py  # តេស្ត ៤៨ checks — migration v4 + oversell (ច្បាប់ app.db, គ្មានប៉ះពិត)
./scripts/install_qoder.sh          # ដំឡើង/ផ្ទៀងផ្ទាត់ Qoder CLI (សម្រាប់ Qoder Proxy)
./scripts/run_qoder_proxy.sh --bg   # រត់ OpenAI-compatible Proxy នៅ port 3000
python scripts/test_qoder_proxy.py  # តេស្ត Proxy ពិតតាម HTTP (health + chat + 400)
python scripts/test_ai_engines.py   # តេស្តគ្រប់ backend + Fallback Chain (ត្រូវការបណ្តាញ)
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

`ai_engine/` មាន ៥ ក្បាល ជ្រើសរើសដោយ `AI_BACKEND`៖

* `mock` — ឆ្លើយតាម keyword សម្រាប់សាកល្បង (គ្មានបណ្តាញ)
* `groq` — Groq API (OpenAI-compatible, ឥតគិតថ្លៃ)។ **ចំណាំ:** `llama-3.1-70b-versatile`
  ត្រូវបាន decommissioned (Error 400) ហើយ `llama-3.3-70b-versatile` ក៏មិនមានលើ key
  គ្រប់គ្នាដែរ — ម៉ូដែលដែលតេស្តឆ្លងហើយ: `qwen/qwen3.8-27b`, `openai/gpt-oss-120b`,
  `allam-2-7b` (រកមើលរបស់ key អ្នក: `curl -s https://api.groq.com/openai/v1/models -H "Authorization: Bearer $KEY"`)
* `qoder_cli` — ហៅ CLI តាម `asyncio.create_subprocess_exec` (**មិនឆ្លងកាត់ shell** ដូច្នេះ
  អត្ថបទពីអតិថិជនមិនអាចចាក់បញ្ចូល command បានទេ)។ តម្លៃ `{prompt}` ក្នុង `QODER_CLI_ARGS`
  ត្រូវជំនួសដោយ transcript ទាំងមូល។ *កុំភ្លេច៖ ពិនិត្យ license/usage terms របស់ CLI មុនប្រើក្នុងបរិបទពាណិជ្ជកម្ម។*
* `openai` — endpoint ណាក៏បានដែលមាន `/chat/completions` (vLLM, LM Studio, OpenRouter…)
  រួមទាំង **Qoder Proxy** នៅក្នុង machine របស់អ្នក (មើល ៤.១)
* `ollama` — `/api/chat`

Prompt ដែលផ្ញើទៅ AI = System Prompt + Few-shot + **Catalog ផលិតផលពី DB**
(`ai_engine/prompting.py`) ដូច្នេះ AI ឃើញតម្លៃ និង stock ពិតប្រាកដ តែត្រូវបង្គាប់
ថាកុំបញ្ចេញ Code ដោយខ្លួនឯង។

`BackendChain` (`ai_engine/chain.py`) រក្សាស្ថិរភាព៖ ចម្លើយទទេ/ខ្លីពេក/ជា echo → retry ម្តង
រួចលោតទៅ fallback (groq បើ `GROQ_API_KEY` មាន, openai បើ `OPENAI_BASE_URL` មាន) ហើយបញ្ចប់
ដោយ `mock` ជាក្តាមសង្រ្គោះ ដើម្បីកុំឱ្យ Bot ស្ងាត់ទាំងស្រុង។ នៅពេលចម្លើយចេញពី mock ម្ចាស់ទទួល
សារជូនដំណឹង (១×/ម៉ោង/គណនី) ព្រោះ mock មិនបោះកំហុស។ បើគ្មាន fallback ឡើយ និងគ្រប់ backend
បរាជ័យ → ម្ចាស់ទទួល "⚠️ AI ទាំងអស់បរាជ័យ!" ហើយអតិថិជនទទួលសារសុវត្ថិភាព
«សូមរង់ចាំបន្តិច ខ្ញុំកំពុងពិនិត្យ។»។
Panel បង្ហាញ backend ពិត (`backend: qoder_cli · 12.3s`) ជាមួយ ⚠️ ពេលលោត fallback។

### ៤.១ AI Backend Setup (Qoder CLI + Proxy)

Qoder CLI មិនមែនជា HTTP server ទេ ដូច្នេះ `scripts/qoder_proxy.py` (FastAPI + uvicorn) បំប្លែង
`POST /v1/chat/completions` ទៅជាការហៅ `qodercli -p` ម្តង រួចឆ្លើយតបជាទម្រង់ OpenAI។ Bot រត់
`AI_BACKEND=openai` ចង្អុលមកវា ដូច្នេះមិនត្រូវការ API key ទេ។

```bash
# ១. ដំឡើង/ផ្ទៀងផ្ទាត់ CLI (write PATH ទៅ ~/.bashrc បើកូវខ្វះ)
./scripts/install_qoder.sh

# ២. រត់ Proxy នៅ port 3000 (--bg = background, log/PID ក្នុង logs/)
./scripts/run_qoder_proxy.sh          # foreground
./scripts/run_qoder_proxy.sh --bg     # background

# ៣. តេស្ត
.venv/bin/python scripts/test_qoder_proxy.py   # health + models + chat + 400 cases
.venv/bin/python scripts/test_ai_engines.py    # គ្រប់ backend + Fallback Chain
```

`.env`៖

```env
AI_BACKEND=openai
OPENAI_BASE_URL=http://127.0.0.1:3000/v1
OPENAI_API_KEY=sk-qoder-proxy-local
OPENAI_MODEL=qoder-cli
AI_TIMEOUT=90
```

ឈ្មោះ model មិនសំខាន់ទេ (Proxy មិនអើពើ លើកលែងតែកំណត់ `QODER_PROXY_MODEL`)។
ការកំណត់ Proxy បន្ថែម៖ `QODER_PROXY_HOST` · `QODER_PROXY_PORT` · `QODER_PROXY_TIMEOUT`
(ត្រូវតិចជាង `AI_TIMEOUT`) · `QODER_PROXY_CONCURRENCY` (ចំនួន CLI ដែលរត់ព្រមគ្នា, លំនាំដើម ២)។

សុវត្ថិភាពរបស់ Proxy៖ prompt ចូលតាម **stdin** (មិនឆ្លង shell, មិនចូល argv) + `--tools ""`
បិទ tool ទាំងអស់ + `--no-session-persistence` ដូច្នេះសារអតិថិជនមិនអាចឱ្យ CLI កែឯកសារ ឬ
រត់ command បានទេ។ Log បង្ហាញតែប្រវែងចម្លើយ មិន log prompt ពេញលេញទេ។

### ៤.២ 🖥️ Platform Support (Auto-Install ធ្វើតែលើ VPS)

`python main.py` ហៅ `services/qoder_setup.py` មុន `init_db()` — វាពិនិត្យ Platform រួច
Auto-Install Qoder CLI + Auto-Run Proxy **តែនៅពេលជា VPS** (មិនមែន Serverless)។
បើ Qoder បរាជ័យ Bot **នៅរត់ធម្មតា** ហើយ `ai_engine` ធ្លាក់ទៅ Groq រួច Mock ដោយស្វ័យប្រវត្តិ
(`openai → fallback: groq, mock`)។

| Platform | Bot | Userbot | Qoder AI | Session Web |
| :--- | :--- | :--- | :--- | :--- |
| **VPS / Cloud Shell** | ✅ | ✅ | ✅ Auto-Install | ✅ |
| **Render / Railway** | ✅ | ✅ | ✅ Auto-Install | ✅ |
| **Heroku** | ✅ | ✅ | ⚠️ ត្រូវ buildpack | ✅ |
| **Vercel / Netlify** | ❌ | ❌ | ❌ (រំលង) | ✅ |

សញ្ញាដែលរាប់ជា Serverless (រំលង Auto-Install ទាំង `install_qoder.sh` និង `main.py`)៖
`VERCEL` · `VERCEL_ENV` · `NETLIFY` · `AWS_LAMBDA_FUNCTION_NAME`។

```bash
./scripts/install_qoder.sh                 # VPS → ✅ Qoder CLI ready ឬដំឡើងថ្មី
VERCEL=1 ./scripts/install_qoder.sh        # ⏭️ Serverless — រំលង (exit 0 ជានិច្ច)
VERCEL=1 .venv/bin/python main.py          # Bot ចាប់ផ្តើមដោយគ្មាន Qoder (fallback Groq)
```

ចំណាំ៖
* **Cloud Shell** អាច reset ពេលបិទ >១២០ នាទី → CLI បាត់ ប៉ុន្តែ `main.py` ដំឡើងឡើងវិញជានិច្ចពេល Startup។
* **Vercel** គាំទ្រតែ `session_web/` (គ្មាន polling Telegram ជាប់ជានិច្ច ហើយគ្មាន filesystem) — កុំ Deploy ទាំង Bot ឡើង។
* **Bot គួររត់លើ VPS/Render/Railway** រីឯ Session Web ប៉ុណ្ណោះដែល Deploy ទៅ Vercel។

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
                        · qoder_setup.py (Platform Detection + Auto-Install CLI/Proxy តែ VPS)
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
  មាន warm-up ៧ ថ្ងៃ, និង **មិន log session string ឬ api credentials**។
* ការបន័ែមគណនីធ្វើ **តាម chat Admin Bot** ដោយ **Session String តែមួយគត់** (`/addsession`
  ឬចុច «🔐 បន័ែមគណនីតាម Session String»)។ OTP/2FA វាយក្នុង chat **ត្រូវបានលុបចោល**
  ព្រោះ chat របស់ Bot មិនមែនកន្លែងសុវត្ថិភាពទេ (aiogram រក្សា update, log, backup)។ សារ
  Session String ដែល admin វាយចូល **ត្រូវលុបភ្លាម** ពេលអានរួច (`_delete_secret`) ទើប
  គ្មានអ្វីសល់ក្នុង history របស់ Bot។ `api_id`/`api_hash` មិនដែលវាយតាម chat ទេ — អានពី
  `.env` ហើយ session រក្សាទុក Fernet ក្នុង DB តែប៉ុណ្ណោះ (Panel បង្ហាញតែ «✅ កំណត់ក្នុង .env រួច»)។
  (CLI login ត្រូវបានលុបចេញ — មានផ្លូវ chat តែមួយ)
* `.env` និង `data/` ស្ថិតក្នុង `.gitignore` — កុំពិនិត្យវាចូល repository ឡើយ។

### ៦.១ បើក Userbot (ជំហានទី ២.១)

1. ដាក់ `TG_API_ID` + `TG_API_HASH` (App របស់អ្នកពី **my.telegram.org → API development
   tools**) និង `SESSION_FERNET_KEY` (បង្កើត៖ `python scripts/generate_keys.py --write`) ក្នុង
   `.env` — គ្រប់គណនីប្រើ App តែមួយ ដូច្នេះគ្មានតម្លៃណាវាយតាម chat ទេ។
2. បង្កើត Session String តាមមួយក្នុងចំណោមពីរផ្លូវ (OTP/2FA វាយចូលកន្លែងដែល មិនមែន
   chat របស់ Bot)៖
   * **Terminal របស់អ្នក** — `.venv/bin/python scripts/get_session.py +855XXXXXXXX`
     (ផ្លូវដែលទំនងជាងគេ ព្រោះ Telegram មិនសូវសង្ស័យ IP របស់អ្នក)
   * **គេហទំព័រ Make Session** `<web-session>` — សម្រាប់ភ្ញៀវមិនរត់ Python (មើលផ្នែក
     «🌐 Deploy Session Web App» ខាងក្រោម)
3. ផ្ញើវាទៅ Bot តាម `/addsession` (ឬចុច ➕/ប៊ូតុង Session String ក្នុង menu Accounts) —
   Bot លុបសារភ្លាម រួច Validate → Encrypt → Save ក្នុង DB ហើយភ្ជាប់គណនី។ ខុសទ្រង់ទ្រាយ
   ឬផុតកំណត់ → បដិសេធ + ណែនាំបង្កើតថ្មី (គ្មាន row សល់) និង `/cancel` បោះបង់គ្រប់ពេល។
4. បើក `python main.py` — គណនីដែល `enabled` ភ្ជាប់ស្វ័យប្រវត្តិ; បន្ថែម/បិទគណនីថ្មី
   តាម panel ឃើញផលក្នុង ≤ ៦០ វិនាទី (hot-reload គ្មាន restart — addsession ហៅ `reconcile()` ភ្លាម)
5. បញ្ជាសង្គ្រោះបន្ទាន់ពី Telegram ផ្ទាល់ (send ទៅលេខគណនី userbot)៖
   `/pause <id>` · `/resume <id>` · `/pauseall` · `/resumeall` · `/stopbot` · `/startbot` · `/status`

ច្បាប់ sticky គឺ hard-rule៖ អតិថិជនសរសេរមក A → តែ A តប។ បើគេសរសេរមក B → B មិនតប
ទេ ហើយម្ចាស់ទទួលបានជូនដំណឹង (គ្មាន auto-switch/RR សម្រាប់ inbound — ការផ្ញើរាល់ចេញពី
គណនីទៅមនុស្សមិនស្គាល់គឺជាផ្លូវ ban)។ តេស្ត៖ `python scripts/smoke_test_userbot.py` (២០៣ checks គ្មានបណ្តាញ)។

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

## 🌐 Deploy Session Web App (`session_web/`)

គេហទំព័រ «Make Session» ឱ្យភ្ញៀវបង្កើត Session String ខ្លួនឯង (OTP → StringSession) រួចចម្លង
មកផ្ញើ `/addsession` — មិនត្រូវ install Python។ គ្មាន Database/File/Log របស់ api_hash, លេខ
ទូរស័ព្ទ, OTP ឬ session ទេ ហើយ pending state រវាង request ទី១–២ ជា **Fernet token stateless**
(single-use + TTL) ព្រោះ serverless isolate មិនចែក memory គ្នា។ ឯកសារពេញ: `session_web/README.md`។

```bash
# ១. រត់ក្នុង machine (សាកល្បងមុន deploy)
.venv/bin/python session_web/app.py                      # → http://127.0.0.1:5050

# ២. Deploy ទៅ Vercel (ឥតគិតថ្លៃ) — ត្រូវ log in រួច (`vercel whoami`)
cd session_web
vercel deploy --prod --yes --project bot-auto-sell-make-session --create-if-missing
#  គួរឃើញ: ▲ Aliased  https://bot-auto-sell-make-session.vercel.app

# ៣. Secret សម្រាប់ sign pending token (បើមិនដាក់ → key បណ្តោះអាសន្ន per isolate
#    ហើយភ្ញៀវត្រូវសុំ OTP ឡើងវិញពេល isolate ផ្លាស់ប្តូរ)
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" \
  | vercel env add SESSION_WEB_SECRET --environment production --project bot-auto-sell-make-session --non-interactive

# ៤. Redeploy ដើម្បី apply env var
vercel deploy --prod --yes --project bot-auto-sell-make-session
```

បន្ទាប់ពី deploy រួច ដាក់ URL ពិតក្នុង `.env` របស់ Bot រួច restart (តំណនេះបង្ហាញក្នុង
`/addsession` និង menu Accounts → របៀបប្រើ)៖

```
SESSION_WEB_URL=https://bot-auto-sell-make-session.vercel.app
```

> ⚠️ **Vercel = AWS IP** — Telegram តែងសង្ស័យ login ពី datacenter (អាចជួប
> `PhoneNumberAppForbidden` ឬ ត្រូវចុច link ដែល Telegram ផ្ញើទៅ app)។ បើបរាជ័យ →
> ប្រើ `scripts/get_session.py` លើ machine របស់ភ្ញៀវ, ផ្លាស់ទៅ Render/Railway (always-on),
> ឬ tool ฝั่ง client ដូចជា <https://gabrielmaialva33.github.io/ssg/> (session មិនឆ្លង server)។
> ⚠️ Server-side generator ឃើញ api_hash របស់ភ្ញៀវជានិច្ច (វាត្រូវប្រើវា) — កុំបើក request-body
> log នៅ layer ខាងមុខ ហើយកុំចែក `SESSION_WEB_SECRET`/`SESSION_FERNET_KEY` ទៅណាទេ។
> បើមិនទាន់ deploy → ដាក់ `SESSION_WEB_URL=off` ដើម្បីលាក់តំណពី Bot។

## 👥 Multi-User (Owner + Staff)

* `/addsession` **គ្មាន owner-only guard** — Owner និង Staff (`ADMIN_IDS` ឬ DB admin) បន្ថែម
  គណនីផ្ទាល់ខ្លួនបាន។ `StaffGate` បន្ថែម `scope` ទៅគ្រប់ handler ដោយស្វ័យប្រវត្តិ។
* គណនីដែលបន្ថែម ជាប់នឹង `owner_admin_id = scope.admin_id` (អ្នកដែលផ្ញើ session)។
* `/accounts` តាម scope៖ Owner ឃើញទាំងអស់ (`owner_id=None`) · Staff ឃើញតែគណនីខ្លួន ·
  គណនីដែល admin ផ្សេងកាន់កាប់ហើយ → បដិសេធ (IDOR guard) ហើយត្រូវ Owner ប្ដូរម្ចាស់
  (`acc:owner:`)។
* Web App គាំទ្រ multi-user ដោយធម្មជាតិ — pending token ជា stateless Fernet មិនមាន
  per-process session ទេ។

## 🧪 Testing

គ្រប់តេស្តរត់ **ក្នុង machine តែមួយ** — គ្មាន BOT_TOKEN ពិត គ្មានបណ្តាញ Telegram គ្មានប៉ះ
`data/app.db` (រាល់ suite បង្កើត DB សាកល្បងរបស់វាខ្លួនឯង)៖

```bash
.venv/bin/python scripts/smoke_test.py         # ១៩៥ ជំហាន — Panel ទាំងមូលឆ្លងកាត់ dispatcher + MockSession
.venv/bin/python scripts/smoke_test_ai.py      # ៣៧  checks — echo guard, fallback chain, mock មិនស្ងាត់
.venv/bin/python scripts/smoke_test_userbot.py # ២០៣ checks — sticky, catalog, rate cap, session crypto
.venv/bin/python scripts/smoke_test_migration.py # ៤៨ checks — migration idempotent + oversell (ច្បាប់ app.db)
.venv/bin/python scripts/smoke_test_session_web.py # ៤១ checks — Make Session web (Telethon fake, Flask test_client)
```

**ច្បាប់ដែលតេស្តការពារ (ចុះឈ្មោះគណនី)៖**

* **Session String ជាផ្លូវតែមួយ** — `/addaccount` មិនសួរលេខទូរស័ព្ទ/OTP ទេ វាបញ្ជូនទៅ
  `/addsession`។ គ្មាន `waiting_phone`/`waiting_code`/`waiting_password` ក្នុង FSM ទៀតទេ
  (OTP login ត្រូវបានលុបចោលពីកូដ — តេស្តវាស់ «លុបមែន» ដោយ `hasattr`)។
* **api_id/api_hash មិនដែលវាយតាម chat** — អានពី `.env` តែប៉ុណ្ណោះ ហើយ Panel បង្ហាញតែ
  ស្ថានភាពកំណត់ (✅/❌) មិនមែនតម្លៃពិត។
* **សារ Session String ត្រូវ Auto-delete** មុនការ validate បន្ទាប់ពីអាន — ទោះករណីបដិសេធ។
* **Session ចូល DB ជា Fernet ciphertext** — decrypt ត្រឡប់ដើម ហើយ plaintext មិនដែល
  ចេញជាសារ Bot ឬចូល log (វាស់ទាំង traceback នៃករណី exception)។
* **ទ្រង់ទ្រាយត្រូវរាំងមុនភ្ជាប់** — ខ្លីជាង ៥០ តួ ឬមិនចាប់ផ្តើមដោយលេខ → បដិសេធ ដោយមិន
  បង្កើត client និងមិនបន្សល់ row។
* **Session ខូច/ផុតកំណត់ → បដិសេធ + ណែនាំបង្កើតថ្មី** — មិនដែល orphan row; កំហុសបង្ហាញតែ
  ប្រភេទ exception មិនមែនទិន្នន័យ។
* **IDOR** — លេខដែលជាគណនីរបស់ admin ផ្សេង មិនអាច replace session បានទេ ហើយមិន
  trigger reconcile។ លេខដើម → upsert (រក្សា account id, គ្មាន row ស្ទួន)។
* Save ជោគជ័យ → `manager.reconcile()` ម្តង ហើយគណនីលេចមុខក្នុង `/accounts`។

បន្ទាប់ពីកែ `admin_bot/`, `userbot/` ឬ `ai_engine/` — ត្រូវរត់ទាំង ៤ suite ឱ្យឃើញ
«✅ គ្រប់ជំហានដំណើរការរលូន» / «N/N checks ឆ្លងកាត់» មុន commit។ ផ្លូវ network ពិត
(Telegram DC) ត្រូវតេស្តលើគណនីពិតដោយម្ចាស់ ព្រោះ suite ទាំងនេះក្លែង Telethon client។

## ៧. គម្រោង

* [x] **ជំហានទី ១** — Core scaffold: DB ទាំងអស់, Admin Panel ពេញលេញ, AI engine ៤ ក្បាល, backup/របាយការណ៍
* [x] **ជំហានទី ២.១** — Userbot multi-account (Telethon): sticky sessions, hot-reload, anti-ban
      (២០៣/២០៣ checks គ្មានបណ្តាញ — live test ត្រូវការ TG_API_ID/HASH + Fernet key)
* [x] **ជំហានទី ២.១b** — ហាងលក់ពេញលេញ៖ ៧ ប្រភេទ + product_code, stock reservation
      + oversell prevention, inline catalog (welcome→categories→product→🛒→QR),
      voice/video rejection, prompt ថ្មី categories-aware (Panel ១៩៥ · userbot ២០៣ ·
      migration ៤៨ · AI ៣៧ ឆ្លងកាត់ទាំងអស់)
* [ ] **ជំហានទី ២.២** — ភ្ជាប់ Panel ឱ្យបញ្ជា userbot ផ្ទាល់ (send-from-sticky-account, live status) + live test
* [ ] **ជំហានទី ៣** — SaaS $3/ខែ (តែលើ Bot API)៖ `/subscribe`, ស្លីប, admin បញ្ជាក់, ជូនដំណឹងមុនផុតកំណត់ ៣ ថ្ងៃ
