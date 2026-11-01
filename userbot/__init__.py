"""Userbot (Telethon) = អ្នកលក់ AI លើគណនីពិត — ជំហានទី ២.១ ដំណើរការ។

ស្ថាបត្យកម្មក្នុងមួយគណនី៖
  manager.py   → AccountManager (ភ្ជាប់/បិទ/hot-reload, គ្មាន cross-account path)
  seller.py    → sticky bind + debounce + AI reply + off-hours + code delivery
  controls.py  → បញ្ជាម្ចាស់ (/pause /resume /pauseall /stopbot …)
  outbox.py    → single writer ក្នុងមួយគណនី (budget, FloodWait, typing, delay)
  limits.py    → កម្រិត 50/h · 200/ថ្ងៃ + warm-up tiers (derive ពី messages តារាង)
  session_store.py → Fernet encrypt session (គ្មាន session ណាលើ disk/log)
  safety.py    → រាំង secret ចូល log + រាំង AI មិនឱ្យប្រកាស Code
  text_delay.py / coalescer.py → ពន្យារពេលដូចមនុស្ស + debounce 3 វិនាទី
"""
