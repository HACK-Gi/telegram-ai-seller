"""វិសាលភាពរបស់ tenant ម្នាក់ៗ — គត់ទិន្នន័យដែល derive ពីគណនីរបស់ខ្លួន។

គោលការណ៍សុវត្ថិភាព៖ **default ជាបិទ**។ គ្មាននរណាម្នាក់ (រួមទាំង OWNER) ឃើញទិន្នន័យ
របស់ tenant ផ្សេងទេ — `owner_id` និង `ids` ត្រួតពិនិត្យតាមម្ចាស់ជានិច្ច ហើយ `()` =
មិនឃើញអ្វីសោះ។ កូដដែលភ្លេចបញ្ជូន scope ទៅ crud នឹងបានទិន្នន័យទាំងអស់ ដូច្នេះ
read-path ក្នុង Panel ត្រូវហៅតាម `scope.owner_id` / `scope.ids` ជានិច្ច កុំទុក default ទេ។

`is_owner` **មិនមែន** សិទ្ធិឃើញទិន្នន័យអ្នកផ្សេងទេ — វាគត់សិទ្ធិ global (ការកំណត់ទូទៅ,
Admins, backup/restore, System Prompt, បោះយុថ្កា pause-all, ផ្ទេរម្ចាស់គណនី)។
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    admin_id: int
    is_owner: bool
    account_ids: tuple[int, ...]

    @property
    def owner_id(self) -> int:
        """ID ដែល crud ត្រូវ filter តាម — ម្ចាស់ហាងគ្រប់រូប រួមទាំង OWNER។"""
        return self.admin_id

    @property
    def ids(self) -> tuple[int, ...]:
        """ID គណនីរបស់ tenant នេះ (= ទិន្នន័យលក់ទាំងអស់ដែលគេមើលឃើញ)។"""
        return self.account_ids or ()

    @property
    def has_accounts(self) -> bool:
        return bool(self.account_ids)

    def label(self) -> str:
        return "👑 Owner" if self.is_owner else f"🏪 Shop #{self.admin_id}"
