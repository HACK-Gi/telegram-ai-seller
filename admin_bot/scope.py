"""វិសាលភាពរបស់ admin ម្នាក់ៗ — គត់ទិន្នន័យដែល derive ពីគណនីរបស់ខ្លួន។

គោលការណ៍សុវត្ថិភាព៖ **default ជាបិទ**។ Owner ឃើញទាំងអស់ (`account_ids is None`)
រីឯ staff ឃើញតែ `account_ids` របស់ខ្លួន ហើយ `()` = មិនឃើញអ្វីសោះ។ កូដដែលភ្លេច
បញ្ជូន scope ទៅ crud នឹងបានទិន្នន័យទាំងអស់ ដូច្នេះ read-path ក្នុង Panel ត្រូវ
ហៅតាម `scope.owner_id` / `scope.account_ids` ជានិច្ច កុំទុក default ដាច់ខាត។
"""
from __future__ import annotations

from dataclasses import dataclass

from config import settings


@dataclass(frozen=True)
class Scope:
    admin_id: int
    is_owner: bool
    account_ids: tuple[int, ...] | None

    @property
    def owner_id(self) -> int | None:
        """តម្លៃដែល crud ត្រូវការសម្រាប់ Owner != តែ owner ឃើញទាំងអស់។"""
        return None if self.is_owner else self.admin_id

    @property
    def ids(self) -> tuple[int, ...] | None:
        """ID គណនីដែល crud ចម្រោះតាម — None = គ្មានវិសាលភាព (owner)។"""
        return None if self.is_owner else (self.account_ids or ())

    @property
    def has_accounts(self) -> bool:
        return self.is_owner or bool(self.account_ids)

    def label(self) -> str:
        return "👑 Owner" if self.is_owner else f"🧑‍💼 Staff #{self.admin_id}"


def owner_scope() -> Scope:
    return Scope(admin_id=settings.owner_id, is_owner=True, account_ids=None)
