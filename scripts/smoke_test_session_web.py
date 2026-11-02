"""🧪 Smoke test — Session Web App (`session_web/`) គ្មានបណ្តាញ គ្មាន Telegram។

ប្រើ៖ python scripts/smoke_test_session_web.py

`app.py` រស់ដោយ Telethon ពិត ប៉ុន្តែការ test គ្រប់យ៉ាងត្រូវ test បានមុន deploy — ដូច្នេះ
សំណុំតេស្តនេះ patch `_request_code`/`_login` ដូចគ្រីប fake Telethon ក្នុង smoke_test.py ហើយ
រត់ Flask test_client តាម flow ពិត (send_otp → verify_otp → 2FA → session)។

ច្បាប់ ១២ ដែលការ test ការពារ៖

១.  ទំព័រ render + `Cache-Control: no-store` គ្រប់ response
២.  validation មិនប៉ះបណ្តាញ (api_id លេខ, api_hash hex ៣២, លេខទូរស័ព្ទ E.164)
៣.  លេខខ្មែររាងផ្សេងៗ → E.164 តែមួយ
៤.  pending state ជា Fernet token (មិន plaintext) + TTL + single-use
៥.  re-issue (OTP ខុស / 2FA) ត្រូវ jti ថ្មី ទើប read បាន
៦.  flow ពេញ → session string ចាប់ផ្តើមដោយ «1»
៧.  2FA → status `2fa_required` រួចចូលដោយពាក្យសម្ងាត់
៨.  session ទទេ/exception → error ដែលមិនបែក data ផ្ទៃក្នុង
៩.  គ្មាន API ID/Hash/លេខទូរស័ព្ទ/OTP/session ក្នុង log (សល់តែឈ្មោះ error)
១០. rate limit តាមលេខទូរស័ព្ទ រក្សាតែ hash
១១. token មិនអាចប្រើស្ទួន (replay)
១២. គ្មាន session string លេចក្នុង response របស់ `/send_otp`
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "session_web"))

from cryptography.fernet import Fernet  # noqa: E402

# key របស់តេស្តតែមួយ — មិនពឹង .env របស់ម្ចាស់, មិនពឹង Vercel secret
os.environ["SESSION_WEB_SECRET"] = Fernet.generate_key().decode()
os.environ.pop("SESSION_WEB_URL", None)  # តេស្ត same-origin តែប៉ុណ្ណោះ

import app as web  # noqa: E402

HASH32 = "0123456789abcdef0123456789abcdef"
API_ID = 12345
PHONE_LOCAL = "093251670"
PHONE_E164 = "+85593251670"

passed = 0
failed: list[str] = []


def check(label: str, cond: bool) -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ✅ {label}")
    else:
        failed.append(label)
        print(f"  ❌ {label}")


client = web.app.test_client()

print("— ទំព័រ + no-store —")
page = client.get("/")
html = page.get_data(as_text=True)
check("GET / → 200", page.status_code == 200)
check("ទំព័រមានប្រអប់ API ID/API Hash/លេខទូរស័ព្ទ + ប៊ូតុង ផ្ញើ OTP", all(k in html for k in ("API ID", "API Hash", "លេខទូរស័ព្ទ", "ផ្ញើ OTP")))
check("ទំព័រមានប៊ូតុង ផ្ទៀងផ្ទាត់ + ចម្លង", "ផ្ទៀងផ្ទាត់" in html and "ចម្លង" in html)
check("គ្មាន session string លេខសម្ងាត់ pre-render", "1SESSION" not in html)
check("Cache-Control: no-store គ្រប់ response", page.headers.get("Cache-Control") == "no-store")
health = client.get("/health").get_json()
check("/health ឆ្លើយ OK", health.get("ok") is True)

print("— validation (មិនប៉ះបណ្តាញ) —")
for label, body in (
    ("API ID មិនមែនលេខ", {"api_id": "abc", "api_hash": HASH32, "phone": PHONE_E164}),
    ("API Hash ខ្លី", {"api_id": str(API_ID), "api_hash": "abc", "phone": PHONE_E164}),
    ("API Hash មិន hex", {"api_id": str(API_ID), "api_hash": "z" * 32, "phone": PHONE_E164}),
    ("លេខទូរស័ព្ទខ្លី", {"api_id": str(API_ID), "api_hash": HASH32, "phone": "12"}),
):
    res = client.post("/send_otp", json=body)
    msg = res.get_json().get("message", "")
    check(f"{label} → 400 + ការណែនាំខ្មែរ", res.status_code == 400 and len(msg) > 5)
check("request_id ទទេ → verify 400", client.post("/verify_otp", json={"request_id": "", "otp": "12345"}).status_code == 400)
check("request_id ខូច → 400 (មិន 500)", client.post("/verify_otp", json={"request_id": "nope", "otp": "12345"}).status_code == 400)

print("— លេខខ្មែរ → E.164 —")
for raw, want in (
    ("093251670", PHONE_E164),
    ("093 251 670", PHONE_E164),
    ("+85593251670", PHONE_E164),
    ("0085593251670", PHONE_E164),
    ("93251670", PHONE_E164),
    ("12", None),
):
    check(f"{raw!r} → {want}", web.normalize_phone(raw) == want)

print("— pending token (Fernet, TTL, single-use) —")
token = web._issue({"jti": "t1", "api_id": API_ID, "api_hash": HASH32, "phone": PHONE_E164,
                    "hash": "h", "tries": 0, "stage": "code"})
check("token មិន plaintext (គ្មានលេខ/api_hash លាយ)", PHONE_E164 not in token and HASH32 not in token)
check("token read បាន + stage", web._read(token)["stage"] == "code")
web._consume(token)
check("token ប្រើហើយ → read None (anti-replay)", web._read(token) is None)
web._USED.clear()
original = {"jti": "t2", "api_id": API_ID, "api_hash": HASH32, "phone": PHONE_E164,
            "hash": "h", "tries": 1, "stage": "code"}
reissued = web._reissue(original)
check("re-issue មាន jti ថ្មី (read បាន)", web._read(reissued) is not None)
check("re-issue រក្សា tries/stage", web._read(reissued)["tries"] == 1)
check("re-issue មិន mutate payload ដើម", original["jti"] == "t2")
web._USED.clear()

print("— flow ពេញ (Telethon fake) —")
calls: list[tuple] = []


async def fake_request_code(phone, api_id, api_hash):
    calls.append(("send", phone, api_id, api_hash))
    return "PHONE_CODE_HASH"


async def fake_login(phone, api_id, api_hash, code, password, phone_code_hash):
    calls.append(("login", phone, code, password, phone_code_hash))
    if code == "00000":
        return "2fa", ""
    if code == "99999":
        raise RuntimeError("boom — មានទិន្នន័យមិនគួរបង្ហាញ")
    if password == "2FAPASS":
        return "ok", "1" + "S" * 300
    if code == "11111":
        return "ok", "1" + "A" * 300
    return "failed", ""


web._request_code = fake_request_code
web._login = fake_login
web.limiter.enabled = False  # flask-limiter វាស់ IP (test client ដូចគ្នា) — បិទសម្រាប់ flow


def send_otp(phone: str = PHONE_LOCAL) -> str:
    web._PHONE_HITS.clear()
    return client.post("/send_otp", json={"api_id": str(API_ID), "api_hash": HASH32, "phone": phone}).get_json()["request_id"]


data = client.post("/send_otp", json={"api_id": str(API_ID), "api_hash": HASH32, "phone": PHONE_LOCAL}).get_json()
check("/send_otp → code_sent + request_id វែង", data["status"] == "code_sent" and len(data["request_id"]) > 50)
check("Telethon បាន E.164 + API ID/Hash ពិត", calls[-1] == ("send", PHONE_E164, API_ID, HASH32))
check("គ្មាន session string ក្នុង /send_otp", "session" not in str(data))

token = data["request_id"]
done = client.post("/verify_otp", json={"request_id": token, "otp": "11111"}).get_json()
check("/verify_otp → ok + session ចាប់ផ្តើមដោយ «1»", done["status"] == "ok" and done["session_string"].startswith("1"))
check("token តែមួយ ប្រើស្ទួន → 400", client.post("/verify_otp", json={"request_id": token, "otp": "11111"}).status_code == 400)
check("login ដោយ phone_code_hash ដែល Telegram ផ្តល់", calls[-1][4] == "PHONE_CODE_HASH")

token = send_otp()
two = client.post("/verify_otp", json={"request_id": token, "otp": "00000"}).get_json()
check("គណនីមាន 2FA → status 2fa_required", two["status"] == "2fa_required")
check("2FA → request_id ថ្មី (token ចាស់បិទ)", two["request_id"] != token)
done = client.post("/verify_otp", json={"request_id": two["request_id"], "password": "2FAPASS"}).get_json()
check("2FA ពាក្យសម្ងាត់ត្រឹមត្រូវ → session", done["status"] == "ok" and done["session_string"].startswith("1"))

token = send_otp()
empty = client.post("/verify_otp", json={"request_id": token, "otp": "22222"})
check("session ទទេ → 502 error (មិន session ក្លែងក្លាយ)", empty.status_code == 502 and empty.get_json()["status"] == "error")

token = send_otp()
boom = client.post("/verify_otp", json={"request_id": token, "otp": "99999"})
check("exception ខាងក្នុង → 502 + សារទូទៅ គ្មាន data លេច",
      boom.status_code == 502 and "boom" not in boom.get_json()["message"])

print("— គ្មានទិន្នន័យសម្ងាត់ក្នុង log —")
records: list[str] = []


class Collect(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        records.append(record.getMessage())


handler = Collect()
web.log.addHandler(handler)
web.log.setLevel(logging.INFO)


async def flood(phone, api_id, api_hash):
    class FloodWaitError(Exception):
        pass

    raise FloodWaitError(f"429 too many requests for {phone} hash {api_hash}")


web._request_code = flood
for _ in range(4):
    client.post("/send_otp", json={"api_id": "999", "api_hash": "f" * 32, "phone": "091234567"})
dumped = "\n".join(records)
web.log.removeHandler(handler)
check("log គ្មានលេខទូរស័ព្ទ", "091234567" not in dumped and "+85591234567" not in dumped)
check("log គ្មាន api_hash", "f" * 32 not in dumped and HASH32 not in dumped)
check("log គ្មាន message ដើមរបស់ exception", "too many requests for" not in dumped)
check("log មានតែឈ្មោះ error class", "FloodWaitError" in dumped)

print("— rate limit តាមលេខទូរស័ព្ទ (រក្សាតែ hash) —")
web._USED.clear()
web._PHONE_HITS.clear()
web._request_code = fake_request_code
codes = [
    client.post("/send_otp", json={"api_id": str(API_ID), "api_hash": HASH32, "phone": "091111111"}).status_code
    for _ in range(5)
]
check(f"លេខតែមួយ → ៣ ដងដំបូង OK រួច 429 {codes}", codes == [200, 200, 200, 429, 429])
check("រក្សាទុកតែ hash — គ្មានលេខទូរស័ព្ទសុទ្ធក្នុង memory", all(len(k) == 16 and "091111111" not in k for k in web._PHONE_HITS))

print()
total = passed + len(failed)
if failed:
    print(f"❌ មានបរាជ័យ — {passed}/{total} checks ឆ្លងកាត់")
    for label in failed:
        print(f"   • {label}")
    sys.exit(1)
print(f"✅ ជោគជ័យ — {passed}/{total} checks ឆ្លងកាត់ (គ្មានបណ្តាញ)")
