"""The coach's "today" is the user's day, not the server's.

Every tracker write is keyed by the user's day (`get_user_date` /
`tz_offset`), and so are the context endpoints and the daily reset. The chat
path was not: `generate_chat_response` rebuilt the context for
`datetime.now().date()` and `get_enhanced_context` read it back through the
dateless `get_or_create_context`, which resolved "today" the same way. The
server clock is UTC.

That was recorded as inert. It is not. 31 of the 79 user chat messages ever
sent landed between 19:00 and 24:00 UTC -- 00:00 to 05:00 for a UTC+5 user --
and each of those rebuilt and read the previous user-day's row: yesterday's
meals presented as today, and anything logged after local midnight invisible.

The fix threads the user's date through as a required argument, from the
endpoint's offset down to the rebuild, the cached read and the weekly window.
Required, not defaulted: the default is the bug.
"""
import asyncio
import inspect
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import api.chat as chat_endpoints
import main
import services.chat_context_manager as ccm
from services.chat_context_manager import ChatContextManager
from services.chat_service import HealthChatService

CHAT = '/api/health/chat'
USER = 'u1'

# 26 hours apart, so the two users' dates always differ regardless of when
# the suite runs -- a server-clock implementation hands both the same date.
AHEAD = {'X-Timezone-Offset': '840'}
BEHIND = {'X-Timezone-Offset': '-720'}
AHEAD_MINUTES, BEHIND_MINUTES = 840, -720


def user_today(offset_minutes):
    return (datetime.utcnow() + timedelta(minutes=offset_minutes)).date()


# --- the endpoint resolves the day from the request's offset ---------------


class FakeChatService:
    def __init__(self):
        self.calls = []

    async def generate_chat_response(self, user_id, message, today):
        self.calls.append(today)
        return 'ok'


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def test_the_chat_endpoint_hands_the_service_the_users_date(client, monkeypatch):
    service = FakeChatService()
    monkeypatch.setattr(chat_endpoints, 'get_chat_service', lambda: service)

    ahead = client.post(CHAT, json={'user_id': USER, 'message': 'hi'}, headers=AHEAD)
    behind = client.post(CHAT, json={'user_id': USER, 'message': 'hi'}, headers=BEHIND)

    assert ahead.json()['success'] and behind.json()['success']
    assert service.calls == [user_today(AHEAD_MINUTES), user_today(BEHIND_MINUTES)]
    assert service.calls[0] != service.calls[1]


# --- the service rebuilds and reads the same day it was given ---------------


class RecordingContextManager:
    def __init__(self):
        self.rebuilt, self.read = [], []

    async def rebuild_context(self, user_id, target_date):
        self.rebuilt.append(target_date)
        return {'context': {}}

    async def get_or_create_context(self, user_id, target_date):
        # Positional and required: a dateless call is a TypeError here, which
        # is the point -- there is no server-day fallback left to fall into.
        self.read.append(target_date)
        return {'context': {'user_profile': {}, 'today_progress': {'date': str(target_date)}}}


class RecordingWeeklyManager:
    def __init__(self):
        self.current, self.recent = [], []

    async def get_or_create_weekly_context(self, user_id, target_date, today=None):
        self.current.append(target_date)
        self.today_seen = today
        return {'summary': {}}

    async def get_recent_weeks_context(self, user_id, weeks_count=4, end_date=None):
        self.recent.append(end_date)
        return []


class FakeStore:
    async def save_chat_message(self, *_, **__):
        return None

    async def get_recent_chat_context(self, *_, **__):
        return []


class FakeOpenAI:
    """The one attribute chain generate_chat_response touches."""

    def __init__(self):
        outer = self

        class _Completions:
            async def create(self, **_):
                message = type('M', (), {'content': ' a reply '})()
                choice = type('C', (), {'message': message})()
                return type('R', (), {'choices': [choice]})()

        self.client = type('Client', (), {})()
        self.client.chat = type('Chat', (), {})()
        self.client.chat.completions = _Completions()


def real_chat_service(weekly):
    service = HealthChatService.__new__(HealthChatService)
    service.supabase_service = FakeStore()
    service.openai_service = FakeOpenAI()
    service.weekly_manager = weekly
    return service


@pytest.fixture
def wired(monkeypatch):
    context, weekly = RecordingContextManager(), RecordingWeeklyManager()
    monkeypatch.setattr(ccm, 'get_context_manager', lambda: context)
    return real_chat_service(weekly), context, weekly


def test_the_service_rebuilds_and_reads_the_day_it_is_given(wired):
    service, context, weekly = wired
    day = date(2026, 9, 13)

    reply = asyncio.run(service.generate_chat_response(USER, 'what should I eat for breakfast?', day))

    assert reply == 'a reply'
    assert context.rebuilt == [day], 'the rebuild must target the user\'s day'
    assert context.read == [day], 'the cached read must target the same day'
    assert weekly.current == [day] and weekly.recent == [day], (
        '"this week" is the week containing the user\'s today'
    )
    assert weekly.today_seen == day, (
        'the weekly manager must also be told whose today it is, because it '
        'judges "is this week still current" against it'
    )


def test_the_two_halves_cannot_disagree(wired):
    """Whatever day comes in, the rebuild and the read are for that day.

    Before this, the rebuild used `datetime.now().date()` and the read went
    through the dateless `get_or_create_context`: two spellings of the server
    day. Now there is one value and both halves receive it.
    """
    service, context, _ = wired
    for day in (date(2026, 1, 1), date(2026, 12, 31)):
        asyncio.run(service.generate_chat_response(USER, 'how is my progress?', day))

    assert context.rebuilt == context.read == [date(2026, 1, 1), date(2026, 12, 31)]


def test_the_fallback_context_is_for_the_same_day(wired):
    """If the cached read fails, the direct build reads the user's day too."""
    service, _, _ = wired
    read = []

    async def get_shared_activities_for_date(user_id, target_date):
        read.append(target_date)
        return {}

    async def get_user_by_id(user_id):
        return {'name': 'A'}

    service.supabase_service.get_shared_activities_for_date = get_shared_activities_for_date
    service.supabase_service.get_user_by_id = get_user_by_id
    day = date(2026, 9, 13)

    context = asyncio.run(service.get_user_context(USER, day))

    assert context['today_progress']['date'] == str(day)
    assert read == [day, day - timedelta(days=1)], 'today, and yesterday for sleep'


# --- the date is required, all the way down ---------------------------------


@pytest.mark.parametrize('func,param', [
    (HealthChatService.generate_chat_response, 'today'),
    (HealthChatService.get_comprehensive_context, 'today'),
    (HealthChatService.get_enhanced_context, 'today'),
    (HealthChatService.get_user_context, 'today'),
    (ChatContextManager.get_or_create_context, 'target_date'),
    (ChatContextManager.ensure_daily_context, 'today'),
])
def test_the_day_has_no_default(func, param):
    """A default is where the server day creeps back in."""
    parameter = inspect.signature(func).parameters[param]
    assert parameter.default is inspect.Parameter.empty, (
        f'{func.__qualname__}({param}=...) must not default; the caller knows '
        f'whose day it means'
    )


def test_nothing_on_the_chat_path_reads_the_server_clock():
    """No `datetime.now().date()` left in the functions that pick the day."""
    for func in (
        HealthChatService.generate_chat_response,
        HealthChatService.get_comprehensive_context,
        HealthChatService.get_enhanced_context,
        HealthChatService.get_user_context,
        HealthChatService._get_empty_context,
        ChatContextManager.get_or_create_context,
        ChatContextManager.ensure_daily_context,
    ):
        assert 'now().date()' not in inspect.getsource(func), func.__qualname__


# --- the weekly manager judges "current week" on the user's day ----------------


class _WeeklyRow:
    """A fake Supabase client holding one cached, non-empty weekly row."""

    def __init__(self):
        self.deleted = False

        outer = self

        class _Query:
            def __init__(self, table):
                self.table = table
                self.op = 'select'

            def __getattr__(self, name):
                if name == 'delete':
                    def _delete():
                        self.op = 'delete'
                        return self
                    return _delete
                return lambda *a, **k: self

            def execute(self):
                if self.op == 'delete':
                    outer.deleted = True
                    return type('R', (), {'data': []})()
                return type('R', (), {'data': [{
                    'context_data': {'week_info': {'days_logged': 5}},
                    'summary_data': {'cached': True},
                    'version': 1,
                    'updated_at': '2026-09-06T00:00:00',
                }]})()

        class _Client:
            def table(self, name):
                return _Query(name)

        self.client = _Client()


def _weekly_manager(client):
    from services.weekly_context_manager import WeeklyContextManager
    manager = WeeklyContextManager.__new__(WeeklyContextManager)
    manager.supabase_service = type('S', (), {'client': client.client})()
    manager.scheduled = []
    manager._schedule_current_week_refresh = lambda *a: manager.scheduled.append(a)
    return manager


def test_a_western_users_live_sunday_is_still_the_current_week():
    """UTC has reached Monday; the user is still on Sunday (UTC-8, evening).

    Judged on the server date, that Sunday's week is "completed" and the
    cached row is served without a refresh -- and keeps being served, since
    completed weeks are never revalidated. Everything the user logs for the
    rest of their Sunday is dropped from that week for good. Judged on the
    user's day, the week is current: the cache is served and a refresh is
    scheduled, as for any other current week.
    """
    users_sunday = date(2026, 9, 13)          # a Sunday
    client = _WeeklyRow()
    manager = _weekly_manager(client)

    result = asyncio.run(manager.get_or_create_weekly_context(
        USER, users_sunday, today=users_sunday))

    assert result['success'] is True
    assert result['week_end'] == str(users_sunday)
    assert manager.scheduled, (
        'a week that is still current for the user must go down the '
        'stale-while-revalidate path, not be frozen as completed'
    )
    assert not client.deleted


def test_a_genuinely_past_week_is_served_from_cache():
    last_sunday = date(2026, 9, 6)
    client = _WeeklyRow()
    manager = _weekly_manager(client)

    result = asyncio.run(manager.get_or_create_weekly_context(
        USER, last_sunday, today=date(2026, 9, 13)))

    assert result['summary'] == {'cached': True}
    assert manager.scheduled == []


def test_recent_weeks_judge_currency_on_the_same_day_they_count_back_from():
    seen = []

    async def fake(user_id, target_date, today=None):
        seen.append((target_date, today))
        return {'success': True}

    from services.weekly_context_manager import WeeklyContextManager
    manager = WeeklyContextManager.__new__(WeeklyContextManager)
    manager.get_or_create_weekly_context = fake
    users_today = date(2026, 9, 13)

    asyncio.run(manager.get_recent_weeks_context(USER, weeks_count=2, end_date=users_today))

    assert seen == [(users_today, users_today),
                    (users_today - timedelta(weeks=1), users_today)]
