"""Local (ki66) additions split out of the upstream-owned test_authority_active_list.py."""

import pytest

from tests.gateway.test_authority_active_list import owner  # noqa: F401  (shared fixture)


@pytest.mark.asyncio
async def test_a_live_entry_with_no_row_does_not_crash_the_list(owner):
    owner.authority.sessions['ghost'] = owner.authority.sessions['chat']
    listed = await owner.active(current_session_id='chat')
    assert 'chat' in listed and 'ghost' not in listed
