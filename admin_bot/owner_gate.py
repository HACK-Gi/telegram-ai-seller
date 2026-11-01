"""សិទ្ធិ Owner តែម្នាក់ឯង — សម្រាប់ផ្នែកដែលប៉ះទិន្នន័យ global ទាំងមូល។

គោលការណ៍៖ **default ជាបិទ**។ យើងមិនសរសេរ `if not scope.is_owner: return` ក្នុង
គ្រប់ handler ទេ (ងាយភ្លេច ហើយការស្ងាត់ធ្វើឱ្យ staff គិតថា Panel ខូច) — គិតជា
`OwnerOnly` filter ដែលបដិសេធដោយបង្ហាញហេតុផលច្បាស់លាស់។

**ហេតុអ្វីជា filter មិនមែន outer middleware លើ router**៖ aiogram ហោះ
`Router.propagate_event` តាម `observer.wrap_outer_middleware(...)` ដែល *wrapper*
នេះគ្របលើការបន្តទៅ sub-routers ផង មិនមែនតែ handler របស់ router នោះទេ។
middleware ដែល `return None` (បដិសេធ) ទើប dispatcher ចាត់ទុក update ជា «បាន
ដោះស្រាយ» ហើយ**ឈប់បន្ត**ទៅ router ក្រោយ — staff ត្រូវបានគេលួចបិទផ្លូវទៅ
orders/customers/accounts ទាំងមិនដឹងខ្លួន។ filter វិញ វាស់តែ handler ដែល
filters របស់វាឈ្នះ ទើប update ដែលមិនគ្របដណ្តប់ បន្តដំណើរធម្មតា។
"""
from __future__ import annotations

import logging

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from admin_bot.scope import Scope

log = logging.getLogger("admin.owner_gate")

REFUSAL = "🔒 ផ្នែកនេះមានតែ <b>ម្ចាស់ (Owner)</b> ប៉ុណ្ណោះ។\nប្រសិនបើត្រូវការប្ដូរ សូមទាក់ទងម្ចាស់។"


async def refuse(event: CallbackQuery | Message) -> None:
    """ប្រាប់ staff មូលហេតុជំនួសការស្ងាត់ (callback មិនត្រូវការ HTML)។"""
    if isinstance(event, CallbackQuery):
        await event.answer(REFUSAL.replace("<b>", "").replace("</b>", ""), show_alert=True)
    else:
        await event.answer(REFUSAL)


class OwnerOnly(BaseFilter):
    """ដាក់លើ handler នីមួយៗ — read ដែល staff ត្រូវឃើញ មិនដាក់ filter នេះទេ។

    ត្រូវការ `scope` ដែល StaffGate ចាក់ឱ្យរាល់ update ដូច្នេះ filter មិន DB hit ទេ។
    """

    async def __call__(self, event: CallbackQuery | Message, scope: Scope) -> bool:
        if scope.is_owner:
            return True
        log.info("បដិសេធ right-owner ពី user %s", scope.admin_id)
        await refuse(event)
        return False
