"""A hot lane session goes read-only when ``/new`` or a policy reset moves its route on (ki66).

The cold-mount half (#140183 F2) marks a history mount superseded. A session that was the lane's
live conversation when the reset happened stayed writable: the routing entry rotated without the
authority noticing, and the successor publishes only on the lane's next inbound. A Desktop submit
to the old id was admitted and ran on the shared route, i.e. in the newer conversation.
"""
import pytest

from tests.gateway.test_authority_cold_route_recovery import _cold, _home, _ref, _source  # noqa: F401


def _writer():
    from gateway.session_contract import Principal
    caps = frozenset({'session:read', 'session:submit', 'session:control'})
    return Principal('viewer', 'fixture', caps, 'socket')


async def _reset_lane(tmp_path, *, publish_successor):
    cold = await _cold(tmp_path)
    old = cold.authority.register(_source())
    successor = cold.store.get_or_create_session(_source(), force_new=True)
    if publish_successor:
        assert cold.authority.register(_source()).session_id == successor.session_id
    return cold, old


@pytest.mark.asyncio
@pytest.mark.parametrize('publish_successor', [False, True])
async def test_a_hot_session_its_lane_reset_refuses_writes(tmp_path, publish_successor):
    from hermes_state_runtime import RuntimeStoreError
    from gateway.session_contract import Submission
    cold, old = await _reset_lane(tmp_path, publish_successor=publish_successor)
    cold.authority.authorize(_writer(), old, 'session:read')
    for capability in ('session:submit', 'session:control'):
        with pytest.raises(RuntimeStoreError, match='session_superseded'):
            cold.authority.authorize(_writer(), old, capability)
    with pytest.raises(RuntimeStoreError, match='session_superseded'):
        await cold.authority.submit(_writer(), Submission('r1', old, {'text': 'hi'}, 'queue'))
    with cold.authority.db._read_ctx() as conn:
        assert conn.execute('SELECT COUNT(*) FROM session_admissions').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_a_hot_session_its_lane_reset_never_resolves_the_successor_agent(tmp_path):
    cold, old = await _reset_lane(tmp_path, publish_successor=False)
    route = cold.authority.sessions[old.session_id].route
    successor_agent = object()
    cold.authority.runner._running_agents = {route: successor_agent}
    cold.authority.runner._cached_agent_for = lambda key: cold.authority.runner._running_agents.get(key)
    assert cold.authority.agent(old) is None
    assert cold.authority._runs_own_agent(old) is False


@pytest.mark.asyncio
async def test_a_hot_session_its_lane_reset_still_reads_its_own_controls(tmp_path):
    from gateway.session_ancillary import read
    from types import SimpleNamespace
    cold, old = await _reset_lane(tmp_path, publish_successor=False)
    connection = SimpleNamespace(authority=cold.authority, actor=_writer(), subscriptions={old.session_id})
    params = {'session_id': old.session_id}
    control = await read(connection, old, params, kind='control')
    assert control['control']['revision'] == ''
    assert await read(connection, old, params, kind='processes') == {'processes': []}
    assert await read(connection, old, params, kind='subagents') == {'subagents': [], 'delegations': []}


@pytest.mark.asyncio
async def test_closing_a_hot_session_its_lane_reset_leaves_the_successor_route_alone(tmp_path, monkeypatch):
    import tools.async_delegation as delegation
    from gateway.session_mutations import retire_live_sessions
    from gateway.session_viewer_close import close_viewer_session
    cold, old = await _reset_lane(tmp_path, publish_successor=False)
    touched = []
    monkeypatch.setattr(delegation, 'interrupt_for_session', lambda **kw: touched.append(('interrupt', kw)))
    monkeypatch.setattr(delegation, 'refuse_for_session', lambda *a, **kw: touched.append(('refuse', kw)))
    cold.authority.runner._evict_cached_agent = lambda key, **kw: touched.append(('evict', key))
    await close_viewer_session(cold.authority, old.session_id, 'tui_close')
    retire_live_sessions(cold.authority, [old.session_id])
    assert touched == []


@pytest.mark.asyncio
async def test_a_live_lane_session_stays_writable(tmp_path):
    cold = await _cold(tmp_path)
    live = cold.authority.register(_source())
    cold.authority.authorize(_writer(), live, 'session:submit')
    assert cold.authority.route_moved_past(live.session_id) is False


@pytest.mark.asyncio
async def test_the_lane_naming_the_session_again_makes_it_writable(tmp_path):
    cold, old = await _reset_lane(tmp_path, publish_successor=True)
    assert cold.authority.route_moved_past(old.session_id) is True
    live = cold.authority.sessions[old.session_id]
    cold.authority._publish_route(live.source, old.session_id, live.route)
    assert live.superseded is False
