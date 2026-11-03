"""A hot conversation detaches after a route reset and never controls its successor (ki66)."""
import pytest

from tests.gateway.test_authority_cold_route_recovery import _cold, _compressed_lane, _home, _ref, _source  # noqa: F401


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
async def test_a_hot_session_its_lane_reset_stays_on_its_own_route(tmp_path, publish_successor):
    from gateway.session import build_session_key
    cold, old = await _reset_lane(tmp_path, publish_successor=publish_successor)
    live = cold.authority.sessions[old.session_id]
    for capability in ('session:read', 'session:submit', 'session:control'):
        cold.authority.authorize(_writer(), old, capability)
    assert live.detached
    assert live.route == build_session_key(live.source)
    assert live.route != cold.store._generate_session_key(_source())
    assert cold.store.get_or_create_session(live.source).session_id == old.session_id
    assert cold.store.get_or_create_session(_source()).session_id != old.session_id


@pytest.mark.asyncio
async def test_a_hot_session_its_lane_reset_never_resolves_the_successor_agent(tmp_path):
    cold, old = await _reset_lane(tmp_path, publish_successor=False)
    route = cold.store._generate_session_key(_source())
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
async def test_a_compressed_detached_session_keeps_its_own_running_agent(tmp_path):
    from types import SimpleNamespace
    from gateway.session_ancillary import _require_current_route
    from gateway.session_detached import route_entry
    route = _compressed_lane(tmp_path)
    cold = await _cold(tmp_path)
    old = cold.authority.register(_source())
    assert old.session_id == 'lane-root'
    cold.store.get_or_create_session(_source(), force_new=True)
    successor = cold.authority.register(_source())
    assert successor.session_id != old.session_id
    live = cold.authority.sessions[old.session_id]
    assert live.detached and live.route != route
    own_agent = SimpleNamespace(session_id='lane-tip')
    cold.authority.runner._running_agents = {live.route: own_agent, route: object()}
    cold.authority.runner._cached_agent_for = lambda key: cold.authority.runner._running_agents.get(key)
    assert route_entry(cold.authority, live.route).session_id == 'lane-tip'
    _require_current_route(cold.authority, old)
    assert cold.authority.agent(old) is own_agent
    assert cold.authority._runs_own_agent(old) is True


@pytest.mark.asyncio
@pytest.mark.parametrize('foreign_detached', [False, True])
async def test_a_detached_session_cannot_project_the_successor_route(tmp_path, foreign_detached):
    from gateway.session_ancillary import _require_current_route
    from gateway.session_detached import detached_key
    from hermes_state_runtime import RuntimeStoreError
    cold, old = await _reset_lane(tmp_path, publish_successor=True)
    successor = cold.store.get_or_create_session(_source())
    route = cold.store._generate_session_key(_source())
    live = cold.authority.sessions[old.session_id]
    live.route = detached_key(route, successor.session_id) if foreign_detached else route
    with pytest.raises(RuntimeStoreError, match='stale_generation'):
        _require_current_route(cold.authority, old)


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
    successor_route = cold.store._generate_session_key(_source())
    for operation, target in touched:
        assert (target if operation == 'evict' else target.get('session_key')) != successor_route


@pytest.mark.asyncio
async def test_a_live_lane_session_stays_writable(tmp_path):
    cold = await _cold(tmp_path)
    live = cold.authority.register(_source())
    cold.authority.authorize(_writer(), live, 'session:submit')
    assert not cold.authority.sessions[live.session_id].detached


@pytest.mark.asyncio
async def test_the_lane_naming_the_session_again_makes_it_writable(tmp_path):
    cold, old = await _reset_lane(tmp_path, publish_successor=True)
    assert cold.authority.sessions[old.session_id].detached
    live = cold.authority.sessions[old.session_id]
    cold.authority.name_lane(cold.store._generate_session_key(_source()), old.session_id, _source())
    assert not live.detached
    cold.authority.authorize(_writer(), old, 'session:submit')
