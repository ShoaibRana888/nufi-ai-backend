"""The incremental context refresh respects `shared_with_chat`.

`update_context_activity` used to merge whatever it was handed into
`chat_contexts` blind. Logging against a row the user hid wrote the hidden
value straight back, reversing the rebuild `PATCH /sharing/{user_id}` does.
`api/water.py` guarded its own call by reading the flag off the *pre-write*
row; the other trackers did not guard at all.

Neither place could have answered on the create path. A row can be born
hidden: `users.chat_sharing_defaults` is applied by a BEFORE INSERT trigger
(`trg_share_default`) on every tracker table, so the pre-write row does not
exist and the write payload never carries the flag. The only thing that knows
is the row the store returns after the write.

So the decision lives in `update_context_activity` (one place, not seven),
and its contract is: `data` is the stored row. The write endpoints hand over
what `create_*` / `update_*` returned. These tests drive the real
`ChatContextManager` over a fake Supabase client, so the guard is exercised
for real behind each endpoint rather than stubbed at the seam -- stubbing
the method under a composition proves the composition, not the system.
"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

import api.exercise as exercise_endpoints
import api.sleep as sleep_endpoints
import api.steps as steps_endpoints
import api.supplements as supplements_endpoints
import api.water as water_endpoints
import api.weight as weight_endpoints
import main
from services.chat_context_manager import ChatContextManager

USER = 'u1'
DAY = date(2026, 9, 6)


# --- a fake Supabase client that records chat_contexts writes --------------


def _empty_context():
    return {
        'user_profile': {},
        'today_progress': {
            'date': str(DAY), 'meals': [], 'meals_logged': 0,
            'exercises': [], 'exercises_done': 0, 'exercise_minutes': 0,
            'water_glasses': 0, 'steps': 0, 'weight': None,
            'sleep_hours': None, 'supplements_taken': [],
            'totals': {'calories': 0, 'protein': 0, 'carbs': 0, 'fat': 0,
                       'fiber': 0},
        },
        'context_metadata': {},
    }


class _Response:
    def __init__(self, data):
        self.data = data


class _Query:
    """Records the fluent chain; answers select on chat_contexts with a row."""

    def __init__(self, client, table):
        self.client, self.table_name = client, table
        self.op, self.payload = None, None

    def select(self, *_):
        self.op = 'select'
        return self

    def update(self, payload):
        self.op, self.payload = 'update', payload
        return self

    def upsert(self, payload):
        self.op, self.payload = 'upsert', payload
        return self

    def eq(self, *_):
        return self

    def execute(self):
        if self.table_name != 'chat_contexts':
            raise AssertionError(f'unexpected table read: {self.table_name}')
        if self.op == 'select':
            return _Response([{
                'context_data': _empty_context(), 'version': 1,
                'last_updated': '2026-09-06T00:00:00',
            }])
        self.client.writes.append((self.op, self.payload))
        return _Response([{'ok': True}])


class FakeClient:
    def __init__(self):
        self.writes = []

    def table(self, name):
        return _Query(self, name)


def real_context_manager(client):
    manager = ChatContextManager.__new__(ChatContextManager)
    manager.supabase_service = type('S', (), {'client': client})()
    return manager


def written_progress(client):
    assert len(client.writes) == 1
    return client.writes[0][1]['context_data']['today_progress']


# --- the guard itself -------------------------------------------------------


def test_a_hidden_row_is_not_merged():
    client = FakeClient()
    result = asyncio.run(real_context_manager(client).update_context_activity(
        USER, 'steps', {'steps': 8200, 'shared_with_chat': False}, DAY))

    assert client.writes == [], 'a hidden row must not touch chat_contexts'
    assert result == {'success': True, 'skipped': 'hidden_from_chat'}


def test_a_shared_row_is_merged():
    client = FakeClient()
    asyncio.run(real_context_manager(client).update_context_activity(
        USER, 'steps', {'steps': 8200, 'shared_with_chat': True}, DAY))

    assert written_progress(client)['steps'] == 8200


def test_a_payload_with_no_flag_is_treated_as_shared():
    """Only an explicit False hides. The delete paths pass a reset with no
    flag, and a reset is the shared view's value regardless."""
    client = FakeClient()
    asyncio.run(real_context_manager(client).update_context_activity(
        USER, 'steps', {'steps': 0}, DAY))

    assert written_progress(client)['steps'] == 0


# --- every write endpoint hands over the stored row ------------------------
#
# The fake store's create/update returns a row with the flag the trigger
# would have set. If an endpoint passed its write payload instead, the flag
# would be missing and the guard would let the hidden value through.


class FakeStore:
    def __init__(self, existing, shared):
        self.existing, self.shared = existing, shared

    def _stored(self, data, entry_id=None):
        row = dict(data)
        if entry_id is not None:
            row['id'] = entry_id
        row.setdefault('id', 'new-row')
        row['shared_with_chat'] = self.shared
        return row

    # water
    async def get_water_by_date(self, *_):
        return self.existing

    async def create_water_entry(self, data):
        return self._stored(data)

    async def update_water_entry(self, entry_id, data):
        return self._stored(data, entry_id)

    # steps
    async def get_steps_by_date(self, *_):
        return self.existing

    async def create_step_entry(self, data):
        return self._stored(data)

    async def update_step_entry(self, entry_id, data):
        return self._stored(data, entry_id)

    # sleep
    async def get_sleep_by_date(self, *_):
        return self.existing

    async def create_sleep_entry(self, data):
        return self._stored(data)

    async def update_sleep_entry(self, entry_id, data):
        return self._stored(data, entry_id)

    # supplements
    async def get_supplement_log_by_date(self, *_):
        return self.existing

    async def create_supplement_log(self, data):
        return self._stored(data)

    async def update_supplement_log(self, log_id, data):
        return self._stored(data, log_id)

    # weight (always creates)
    async def create_weight_entry(self, data):
        return self._stored(data)

    async def initialize_starting_weight_for_user(self, *_):
        return None

    # exercise (always creates)
    async def create_exercise_log(self, data):
        return self._stored(data)


ENDPOINTS = {
    'water': (water_endpoints, '/api/health/water', {
        'user_id': USER, 'date': str(DAY), 'glasses_consumed': 3,
        'total_ml': 750.0, 'target_ml': 2000.0, 'notes': None,
    }, 'water_glasses', 3),
    'steps': (steps_endpoints, '/api/health/steps', {
        'userId': USER, 'date': str(DAY), 'steps': 8200,
    }, 'steps', 8200),
    'sleep': (sleep_endpoints, '/api/health/sleep/entries', {
        'user_id': USER, 'date': str(DAY), 'total_hours': 7.5,
    }, 'sleep_hours', 7.5),
    'supplements': (supplements_endpoints, '/api/health/supplements/log', {
        'user_id': USER, 'supplement_name': 'Vitamin D', 'date': str(DAY),
        'taken': True,
    }, 'supplements_taken', ['Vitamin D']),
    'weight': (weight_endpoints, '/api/health/weight', {
        'user_id': USER, 'date': str(DAY), 'weight': 70.5,
    }, 'weight', 70.5),
    'exercise': (exercise_endpoints, '/api/health/exercise/log', {
        'user_id': USER, 'exercise_name': 'Squat', 'exercise_type': 'strength',
        'sets': 3, 'reps': 10, 'exercise_date': str(DAY),
    }, 'exercises_done', 1),
}

# (tracker, existing row) -- the create path for all six, and the update
# path for the four that upsert by date.
PATHS = [
    ('water', None), ('water', {'id': 'wa1', 'glasses_consumed': 1}),
    ('steps', None), ('steps', {'id': 's1', 'steps': 100}),
    ('sleep', None), ('sleep', {'id': 'sl1', 'total_hours': 6.0}),
    ('supplements', None), ('supplements', {'id': 'sp1', 'taken': False}),
    ('weight', None),
    ('exercise', None),
]


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def wire(monkeypatch):
    def build(tracker, existing, shared):
        module = ENDPOINTS[tracker][0]
        fake_db = FakeClient()
        monkeypatch.setattr(module, 'get_supabase_service',
                            lambda: FakeStore(existing, shared))
        monkeypatch.setattr(module, 'get_context_manager',
                            lambda: real_context_manager(fake_db))
        return fake_db
    return build


@pytest.mark.parametrize('tracker,existing', PATHS)
def test_a_row_stored_hidden_never_reaches_the_context(client, wire, tracker, existing):
    """Hidden by the trigger at insert, or by PATCH /sharing before this
    write -- either way the stored row says False and nothing is merged."""
    module, path, body, _, _ = ENDPOINTS[tracker]
    fake_db = wire(tracker, existing, shared=False)

    response = client.post(path, json=body)

    assert response.status_code == 200, response.text
    assert fake_db.writes == [], (
        f'{tracker}: a hidden row was merged into chat_contexts -- the '
        f'endpoint is passing its write payload instead of the stored row'
    )


@pytest.mark.parametrize('tracker,existing', PATHS)
def test_a_row_stored_shared_still_refreshes(client, wire, tracker, existing):
    """The guard skips only hidden rows; the refresh itself still works."""
    module, path, body, key, expected = ENDPOINTS[tracker]
    fake_db = wire(tracker, existing, shared=True)

    response = client.post(path, json=body)

    assert response.status_code == 200, response.text
    assert written_progress(fake_db)[key] == expected


def test_the_water_response_still_carries_the_stored_row(client, wire):
    """Handing the stored row to the refresh must not change the response."""
    wire('water', {'id': 'wa1', 'glasses_consumed': 1}, shared=False)

    body = client.post('/api/health/water', json=ENDPOINTS['water'][2]).json()

    assert body['success'] is True
    assert body['id'] == 'wa1'
    assert body['entry']['glasses_consumed'] == 3
