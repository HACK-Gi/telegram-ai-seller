# 🌐 Bot Auto Sell — Make Session (web)

ទំព័រមួយដែល **ភ្ញៀវ** បង្កើត `Session String` របស់ខ្លួនឯងបាន ដោយមិនត្រូវ install Python —
រួចចម្លងវាទៅផ្ញើ Bot តាម `/addsession`។ វាជាជំនួសឱ្យ `scripts/get_session.py` (ដែលត្រូវរត់
លើកុំព្យូទ័រផ្ទាល់) សម្រាប់អ្នកដែលគ្មាន terminal។

## ១. រត់លើកុំព្យូទ័រផ្ទាល់

```bash
cd /home/mengly20132013/telegram-ai-seller
.venv/bin/pip install -r session_web/requirements.txt   # Flask, flask-cors, flask-limiter
.venv/bin/python session_web/app.py                     # → http://127.0.0.1:5050
```

បើក `http://127.0.0.1:5050` ក្នុង browser រួចធ្វើតាម ៣ ជំហានលើអេក្រង់។

## ២. Deploy ទៅ Vercel

```bash
cd session_web
vercel login            # លើកដំបូងតែប៉ុណ្ណោះ (ត្រូវការគណនី Vercel របស់អ្នក)
vercel --prod
```

`vercel.json` ប្រើ `@vercel/python` ហើយ route `/(.*)` ទៅ `app.py` (Flask ជា WSGI
object ឈ្មោះ `app` — Vercel រកឃើញស្វ័យប្រវត្តិ)។ URL ដែលទទួលបាន ប្រហែល
`https://bot-auto-sell-make-session.vercel.app`។

### Env variables ក្នុង Vercel Project Settings

| Key | ចាំបាច់? | សារៈ |
|---|---|---|
| `SESSION_WEB_SECRET` | ណែនាំខ្លាំង | Fernet key សម្រាប់ pending token — បង្កើតដោយ `.venv/bin/python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`។ បើមិនដាក់ → key បណ្តោះអាសន្ន per isolate (ភ្ញៀវត្រូវសុំ OTP ឡើងវិញ ពេល isolate ផ្លាស់ប្តូរ) |
| `SESSION_WEB_URL` | មិនចាំបាច់ | `https://<domain>` — ដាក់ CORS ឱ្យតែ origin របស់ app ខ្លួន |
| `SESSION_WEB_TTL` | ទេ | វិនាទី សម្រាប់ pending token (default `600`) |
| `SESSION_WEB_TIMEOUT` | ទេ | វិនាទី សម្រាប់ពេល Telegram ឆ្លើយ (default `30`) |

## ៣. របៀបប្រើ (សម្រាប់ភ្ញៀវ)

1. ទៅ <https://my.telegram.org/apps> log in ដោយលេខទូរស័ព្ទ → ចម្លង **API ID** + **API Hash**។
2. វាយ API ID, API Hash, លេខទូរស័ព្ទ (`093251670` ឬ `+85593251670`) → **ផ្ញើ OTP**។
3. វាយកូដពី Telegram → **ផ្ទៀងផ្ទាត់** (បើគណនីមាន 2FA ទំព័រនឹងសុំពាក្យសម្ងាត់បន្ថែមមួយក្បាល)។
4. ចុច **ចម្លង** → បើក Bot → `/addsession` → paste → Bot លុបសារ រួច encrypt ទុកក្នុង DB។

## ៤. សុវត្ថិភាព — ហេតុអ្វីបានជា app.py សរសេរបែបនេះ

* **គ្មាន database, គ្មាន file, គ្មាន log** នៃ api_id/api_hash/លេខទូរស័ព្ទ/OTP/2FA/session string។
  យើង log តែ *ឈ្មោះ* error class (`send_otp failed: FloodWaitError`) ប៉ុណ្ណោះ។
* ចន្លោះ `/send_otp` → `/verify_otp` ទិន្នន័យត្រូវ **encrypt ក្នុង token Fernet stateless**
  មិនមែន dict ក្នុង process ទេ — ព្រោះ Vercel isolate ទំនេរសម្រាប់ request ទី២ អាចស្ថិតនៅ
  ជា isolate ផ្សេងគ្នា។ token មាន TTL និង **ប្រើបានតែម្តង** (`jti` blocklist)។
* Rate limit ២ជ្រុង: flask-limiter តាម IP (`5/hour` សម្រាប់ `/send_otp`, `10/hour`
  សម្រាប់ `/verify_otp`) + តាមលេខទូរស័ព្ទ `3` ក្នុង ១០ នាទី (រក្សាតែ `sha256(phone)[:16]`)។
* គ្រប់ response មាន `Cache-Control: no-store`។

## ៥. ដែនកំណត់ដែលត្រូវដឹង (មិនមែន bug ទេ)

1. **Telegram តែងហាមឃាត់ login ពី IP datacenter** (Vercel = AWS) — ភ្ញៀវអាចជួប
   `PhoneNumberAppForbidden` ឬត្រូវចុច link ដែល Telegram ផ្ញើទៅ app ផ្ទាល់។ ដំណោះស្រាយ
   ដែលទំនងជាងគេនៅតែជា `scripts/get_session.py` លើកុំព្យូទ័ររបស់ភ្ញៀវ។
2. Server-side generator **ឃើញ** api_hash របស់ភ្ញៀវជានិច្ច (វាត្រូវប្រើវា) — នេះជា
   ការទទួលខុសត្រូវរបស់អ្នកដំណើរការ។ សរសេរ policy ឱ្យច្បាស់លើទំព័រ ហើយកុំបើក log
   request body ណាមួយនៅ layer ខាងមុខ (Vercel រក្សា log URL/query ដោយស្វ័យប្រវត្តិ
   ប៉ុន្តែ request body មិនត្រូវបាន capture ទេ)។
3. បើចង់ជៀសវាងទាំងស្រុង → ប្រើ tool ផ្នែក client (ឧ. <https://gabrielmaialva33.github.io/ssg/>)
   ដែល session string មិនដែលឆ្លងកាត់ server របស់យើងសោះ។

## ៦. ជួសជុល

`GET /health` → `{"ok":true,"ttl":600,"timeout":30,"secret_configured":true,"version":"..."}`។
បើ `/send_otp` ឱ្យ `502` ជាប្រចាំ = បណ្តាញទៅ Telegram ខូច ឬ IP ត្រូវហាមឃាត់ (មិនមែនកំហុស code ទេ)។

គ្រប់ error response មាន `detail` = កូដខ្លី ១ ពាក្យ (`ApiIdInvalidError`, `token_expired`,
`secret_missing`, `stage_failed`, …) ដែលបង្ហាញលើទំព័រក្នុង «〔…〕» — ភ្ញៀវរាយការណ៍តែកូដនោះ
គ្រប់គ្រាន់សម្រាប់ trace ដោយមិនចាំបាច់បង្ហាញទិន្នន័យផ្ទាល់ខ្លួន។

debug ពី production (log គ្មាន OTP/api_hash/លេខទូរសព្ទ/session — មានតែប្រវែង និងឈ្មោះ error):

```bash
cd session_web
vercel logs --since 30m --limit 50          # hobby រក្សា log តែ ៣០ នាទី
vercel logs --follow                         # មើលពេលភ្ញៀវកំពុងសាកល្បង
```

មុន deploy ត្រូវរត់ test គ្មានបណ្តាញឱ្យផាសុកភាពជាមុនសិន (វាចាប់កំហុសដូចជា NameErrorដូចជា NameError
ដែលធ្វើឱ្យ `/send_otp` ជា 500 និងភ្ញៀវឃើញតែ Error Code):

```bash
.venv/bin/python scripts/smoke_test_session_web.py
```
