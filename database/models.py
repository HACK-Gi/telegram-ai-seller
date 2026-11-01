"""Database models — រចនាសម្ព័ន្ធទិន្នន័យទាំងអស់សម្រាប់ប្រព័ន្ធ។

ចំណាំសំខាន់អំពី media៖ Telegram Bot `file_id` អាចប្រើបានតែដោយ bot ដែលបាន
Upload វាប៉ុណ្ណោះ។ ដូច្នេះរូបភាព/QR ត្រូវរក្សាទុកជា 2 កន្លែង៖
  * `*_file_id(s)`  — សម្រាប់ Admin Bot ផ្ញើឡើងវិញក្នុង Panel
  * `*_path(s)`     — ឯកសារក្នុងថត media/ សម្រាប់ Userbot (Telethon) ផ្ញើទៅអតិថិជន
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from helpers import utcnow


class Base(DeclarativeBase):
    pass


class OrderStatus:
    PENDING_PAYMENT = "pending_payment"   # បានប្រាប់ថាចង់ទិញ, រង់ចាំបង់តាម QR
    AWAITING_VERIFY = "awaiting_verify"   # បានទទួល Slip, រង់ចាំម្ចាស់ផ្ទៀងផ្ទាត់
    DELIVERED = "delivered"               # បញ្ចេញ Code រួច
    CANCELLED = "cancelled"

    ALL = (PENDING_PAYMENT, AWAITING_VERIFY, DELIVERED, CANCELLED)
    LABELS = {
        PENDING_PAYMENT: "⏳ រង់ចាំបង់ប្រាក់",
        AWAITING_VERIFY: "🔎 រង់ចាំផ្ទៀងផ្ទាត់ Slip",
        DELIVERED: "✅ បានប្រគល់",
        CANCELLED: "❌ បោះបង់",
    }


class AccountStatus:
    ACTIVE = "active"      # ភ្ជាប់រួច អាចឆ្លើយតបបាន
    OFFLINE = "offline"    # មិនបានភ្ជាប់ (enabled=False ឬបរាជ័យ connect)
    PAUSED = "paused"      # ភ្ជាប់ ប៉ុន្តែ pause_until > ពេលបច្ចុប្បន្ន (flood ឬដល់កម្រិត)
    BANNED = "banned"      # Telegram បានដក session

    ALL = (ACTIVE, OFFLINE, PAUSED, BANNED)
    LABELS = {ACTIVE: "🟢 Active", OFFLINE: "⚪ Offline", PAUSED: "🟡 Paused", BANNED: "🔴 Banned"}


# ---------- Settings ----------
class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")

    def __init__(self, key: str = "", value: str = "") -> None:
        self.key = key
        self.value = value


# ---------- Products + Stock ----------
class Category(Base):
    """ប្រភេទអីវ៉ាន់ (Game Accounts, AI Pro, Clothing…) — ប៊ូតុង menu សម្រាប់អតិថិជន។"""
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # game_acc
    prefix: Mapped[str] = mapped_column(String(8), default="")  # GAME (ទំនេរ = derive ពី code)
    name_kh: Mapped[str] = mapped_column(String(100))
    name_en: Mapped[str] = mapped_column(String(100), default="")
    icon: Mapped[str] = mapped_column(String(8), default="📦")
    description: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def product_prefix(self) -> str:
        """Prefix សម្រាប់ product_code — ឧ. GAME-001, AIPRO-001។"""
        return (self.prefix or self.code.upper().replace("_", ""))[:5]


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[float] = mapped_column(Float, default=0.0)
    category: Mapped[str] = mapped_column(String(100), default="ទូទៅ", index=True)
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    image_file_ids: Mapped[list] = mapped_column(JSON, default=list)
    image_paths: Mapped[list] = mapped_column(JSON, default=list)
    # ជំហានទី ៣ — ប្រភេទ + កូដផលិតផល (additive; `category` string នៅតែជា name_kh mirror សម្រាប់ backward-compat)
    product_code: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True, index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name_en: Mapped[str] = mapped_column(String(200), default="")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False)
    # RBAC — អ្នកបង្កើតជាម្ចាស់ (Telegram user id)។ NULL ក្រោយ migration = owner
    owner_admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    stock: Mapped[list["StockCode"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", lazy="selectin"
    )
    qrcodes: Mapped[list["QRCode"]] = relationship(back_populates="product", lazy="selectin")
    category_rel: Mapped["Category | None"] = relationship(lazy="selectin")

    @property
    def final_price(self) -> float:
        return round(self.price * (100 - (self.discount_percent or 0)) / 100, 2)

    @property
    def remaining(self) -> int:
        return sum(1 for code in self.stock if not code.is_sold)

    @property
    def available(self) -> int:
        return sum(1 for code in self.stock if code.status == StockCodeStatus.AVAILABLE)

    @property
    def reserved(self) -> int:
        return sum(1 for code in self.stock if code.status == StockCodeStatus.RESERVED)


class StockCodeStatus:
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"


class StockCode(Base):
    __tablename__ = "stock_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(Text)
    is_sold: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"), nullable=True)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # ជំហានទី ៣ — ខ្លឹមសារពិត (login|pass) + ស្ថានភាពកក់ ដើម្បីការពារ oversell
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default=StockCodeStatus.AVAILABLE, index=True)
    reserved_for_customer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    product: Mapped[Product] = relationship(back_populates="stock")


# ---------- QR / Payment ----------
class QRCode(Base):
    __tablename__ = "qrcodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(50), default="ABA")
    account_info: Mapped[str] = mapped_column(Text, default="")
    image_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    # QR ជាលុយពិត៖ ភ្ជាប់នឹងគណនីដែលលក់ ដើម្បីឱ្យប្រាក់ចូលគណនីដែលត្រូវគ្នា។
    # NULL = QR ទូទៅរបស់ម្ចាស់ ប៉ុន្តែវាមិនដែលជំនួស QR ដែលភ្ជាប់គណនីផ្សេងទេ។
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    product: Mapped[Product | None] = relationship(back_populates="qrcodes")

    # RBAC — QR របស់ម្ចាស់ណា ប្រាក់ចូលតែគណនីរបស់ម្ចាស់នោះ (D3: មិនដែល fallback ឆ្លងម្ចាស់)
    owner_admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)


# ---------- Orders ----------
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    customer_name: Mapped[str] = mapped_column(String(200), default="")
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    product_name: Mapped[str] = mapped_column(String(200), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.PENDING_PAYMENT, index=True)
    slip_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    slip_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    delivered_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Snapshot គណនីនៅពេលបង្កើត order (កុំ derive ពី customer ព្រោះការប្តូរ binding នឹងសរសេរប្រវត្តិឡើងវិញ)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # NULL = ម្ចាស់បាន confirm ប៉ុន្តែ userbot មិនទាន់ផ្ញើ code ទៅអតិថិជន
    code_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------- Messages (AI context) ----------
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | owner
    content: Mapped[str] = mapped_column(Text)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ---------- Customers (CRM) ----------
class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    username: Mapped[str] = mapped_column(String(100), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    total_spent: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # គណនី «sticky» ដែលអតិថិជនបានសរសេរមក កំណត់តែម្តងគត់ (ទិន្នន័យសម្រាប់ attribution ប៉ុណ្ណោះ)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Telethon StringSession មិនរក្សា entity cache ទេ ដូច្នេះត្រូវការ access_hash ដើម្បីផ្ញើក្រោយ restart
    access_hash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


# ---------- Telegram Accounts (Userbot sessions) ----------
class Account(Base):
    __tablename__ = "telegram_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")            # ស្លាកឯកជនរបស់ម្ចាស់
    session_encrypted: Mapped[str] = mapped_column(Text, default="")      # Fernet ciphertext ប៉ុណ្ណោះ
    status: Mapped[str] = mapped_column(String(16), default=AccountStatus.OFFLINE, index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # ជំហានទី ២ — intent របស់ម្ចាស់ ចែកពី status ដែល manager សរសេរតាមពិត
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(100), default="")
    display_name: Mapped[str] = mapped_column(String(200), default="")
    working_hours: Mapped[str | None] = mapped_column(String(16), nullable=True)  # NULL = ប្រើតួនាទី global
    warmup_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    warmup_days: Mapped[int] = mapped_column(Integer, default=7, server_default="7")
    pause_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    # RBAC — admin ដែលបន្ថែម/គ្រប់គ្រងគណនីនេះ (owner = OWNER_ID ដោយ backfill)
    owner_admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    # fingerprint ថេរ ដើម្បីឱ្យ device ពេល login == ពេល manager ភ្ជាប់រាល់ពេល reconnect
    device_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # App credentials ដែលម្ចាស់គណនីបង្កើតនៅ my.telegram.org — Fernet ciphertext ប៉ុណ្ណោះ។
    # NULL = មិនទាន់កំណត់ → fallback ទៅ TG_API_ID/TG_API_HASH ក្នុង .env (គណនីចាស់)
    tg_api_id_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tg_api_hash_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)


class AccountProduct(Base):
    """វិសាលភាពផលិតផលក្នុងមួយគណនី។ **គ្មាន row = លក់គ្រប់ផលិតផល active**។"""
    __tablename__ = "account_products"
    __table_args__ = (UniqueConstraint("account_id", "product_id", name="uq_account_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("telegram_accounts.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------- SaaS Subscribers (ជំហានទី ៣) ----------
class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    plan: Mapped[str] = mapped_column(String(32), default="basic")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_slip: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


# ---------- Admins ----------
class Admin(Base):
    __tablename__ = "admins"
    __table_args__ = (UniqueConstraint("telegram_id", name="uq_admin_telegram_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(16), default="admin")  # owner | admin
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
