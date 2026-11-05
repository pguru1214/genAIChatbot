"""Structured, bounded day schedules rendered with server-calculated clock times."""
from datetime import date, timedelta
from typing import Literal, ClassVar
from urllib.parse import urlencode

from pydantic import BaseModel, Field, model_validator

from app.planning import clock_minutes
from app.tourism import DestinationNeedsClarification


class Activity(BaseModel):
    kind: Literal['visit', 'transfer', 'meal', 'break', 'check-in']
    title: str = Field(min_length=1, max_length=140)
    duration_minutes: int = Field(ge=5, le=1440)
    description: str = Field(min_length=1, max_length=400)
    source_ids: list[str] = Field(default_factory=list)


class DayPlan(BaseModel):
    day: int = Field(ge=1, le=7)
    base: str = Field(min_length=1, max_length=120)
    activities: list[Activity] = Field(default_factory=list, max_length=32)
    review_note: str | None = Field(default=None, max_length=800)


class TravelLeg(BaseModel):
    day: int = Field(ge=1, le=7)
    title: str = Field(min_length=1, max_length=140)
    duration_minutes: int = Field(ge=5, le=10080)
    timing_note: str = Field(min_length=1, max_length=800)


class TransportOption(BaseModel):
    mode: Literal['train', 'bus', 'car/taxi', 'flight', 'sea', 'local']
    route: str = Field(min_length=1, max_length=300)
    duration_estimate: str = Field(min_length=1, max_length=180)
    cost_estimate: str = Field(min_length=1, max_length=180)
    best_for: str = Field(min_length=1, max_length=250)


class BudgetItem(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    amount: int = Field(ge=0)


class DetailedItinerary(BaseModel):
    overview: str = Field(min_length=1, max_length=800)
    recommended_mode: str = Field(min_length=1, max_length=400)
    transport_options: list[TransportOption] = Field(min_length=1, max_length=4)
    days: list[DayPlan] = Field(min_length=1, max_length=7)
    budget_allocation: list[BudgetItem] = Field(min_length=1, max_length=8)
    packing_list: list[str] = Field(min_length=1, max_length=14)
    notes: list[str] = Field(default_factory=list, max_length=8)
    source_ids: list[str] = Field(default_factory=list)
    travel_legs: list[TravelLeg] = Field(default_factory=list, max_length=16)


def budget_limit(value):
    import re
    match = re.fullmatch(r'\s*(?:INR\s*|₹\s*)?(\d[\d,]*(?:\.\d+)?)\s*(k|K)?\s*(?:INR)?\s*', str(value))
    return float(match[1].replace(',', '')) * (1000 if match[2] else 1) if match else None


def schedule_schema(request, research):
    minutes = clock_minutes(request['day_end']) - clock_minutes(request['day_start'])
    known = {e['id'] for e in research.get('evidence', [])}
    limit = budget_limit(request.get('budget'))

    class CheckedItinerary(DetailedItinerary):
        allowed_source_ids: ClassVar[list[str]] = sorted(known)
        @model_validator(mode='after')
        def constraints(self):
            issues = []
            if [d.day for d in self.days] != list(range(1, request['days'] + 1)):
                issues.append('Include exactly the requested sequential days')
            if not set(self.source_ids).issubset(known):
                issues.append('Unknown itinerary source ID')
            for day in self.days:
                for activity in day.activities:
                    if not set(activity.source_ids).issubset(known):
                        issues.append(f'Day {day.day}: unknown activity source ID')
                if day.review_note:
                    continue  # Unscheduled candidates are explicitly shown for review, never clocked as a feasible day.
                duration = sum(a.duration_minutes for a in day.activities)
                if duration > minutes:
                    issues.append(f'Day {day.day}: activities exceed {minutes} minutes (total {duration}). Reduce visits, preserve transfers/meals.')
                if not day.activities:
                    issues.append(f'Day {day.day}: include activities or an explicit review note')
                if minutes >= 300 and not any(a.kind == 'meal' for a in day.activities):
                    issues.append(f'Day {day.day}: include a meal break')
                visits = [i for i, a in enumerate(day.activities) if a.kind == 'visit']
                for left, right in zip(visits, visits[1:]):
                    if not any(a.kind == 'transfer' for a in day.activities[left + 1:right]):
                        issues.append(f'Day {day.day}: include walking or transport time between attractions')
            if limit is not None and sum(i.amount for i in self.budget_allocation) > limit:
                issues.append('Suggested budget allocations exceed the supplied total budget')
            if issues:
                raise ValueError('; '.join(dict.fromkeys(issues)))
            return self

    return CheckedItinerary


def proposal_schema(research):
    """Ask AI for typed suggestions; scheduling arithmetic belongs to the backend."""
    known = sorted(e['id'] for e in research.get('evidence', []))
    class ItineraryProposal(DetailedItinerary):
        allowed_source_ids: ClassVar[list[str]] = known
    return ItineraryProposal


def prepare_schedule(payload, request, research):
    """Preserve useful AI output without presenting an impossible day as complete."""
    plan = DetailedItinerary.model_validate(payload).model_copy(deep=True)
    limit = clock_minutes(request['day_end']) - clock_minutes(request['day_start'])
    days = {d.day: d for d in plan.days}
    if len(days) != len(plan.days) or any(n > request['days'] for n in days):
        raise ValueError('Duplicate or unexpected itinerary days')
    plan.days = [days.get(n) or DayPlan(day=n, base=request['destination'], review_note='The AI did not supply this day. Refine the trip to complete it.')
                 for n in range(1, request['days'] + 1)]
    notes = []
    for day in plan.days:
        # A long train/bus journey is not a short sightseeing activity. Keep its
        # full estimate and flag the arrival/return day until timing is confirmed.
        long_legs = [a for a in day.activities if a.kind == 'transfer' and a.duration_minutes >= limit]
        if long_legs:
            for activity in long_legs:
                plan.travel_legs.append(TravelLeg(day=day.day, title=activity.title,
                    duration_minutes=activity.duration_minutes,
                    timing_note='Separate intercity travel estimate. An overnight journey or extra travel day may be required; departure and arrival are unverified.'))
            day.activities = [a for a in day.activities if a not in long_legs]
            day.review_note = 'Confirm arrival/return timing for the long journey below before scheduling these optional stops. No arrival before 10 AM is assumed.'
        if any(leg.day == day.day for leg in plan.travel_legs) and not day.review_note:
            day.review_note = 'Confirm the separate intercity journey and its arrival/return timing before scheduling these optional stops.'
        if day.review_note:
            continue
        activities, last_visit, transferred = [], None, True
        for activity in day.activities:
            if activity.kind == 'visit' and last_visit and not transferred:
                activities.append(Activity(kind='transfer', title=f'Transfer to {activity.title}'[:140], duration_minutes=30,
                    description='Provisional transfer allowance; verify the actual route.'))
                notes.append('Missing local transfers use provisional 30-minute allowances, not live road travel times.')
            activities.append(activity)
            if activity.kind == 'visit':
                last_visit, transferred = activity, False
            elif activity.kind == 'transfer':
                transferred = True
        if limit >= 300 and not any(a.kind == 'meal' for a in activities):
            activities.append(Activity(kind='meal', title='Meal break', duration_minutes=45,
                description='Suggested meal allowance; no restaurant reservation is assumed.'))
        deficit = max(0, sum(a.duration_minutes for a in activities) - limit)
        for activity in reversed(activities):
            if deficit and activity.kind == 'break':
                reduction = min(deficit, activity.duration_minutes)
                if 0 < activity.duration_minutes - reduction < 5:
                    reduction = activity.duration_minutes
                activity.duration_minutes -= reduction
                deficit = max(0, deficit - reduction)
        day.activities = [a for a in activities if a.duration_minutes]
        if deficit:
            day.review_note = (f'These suggestions need {sum(a.duration_minutes for a in day.activities)} minutes, '
                               f'but your daily window allows {limit}. Choose fewer stops or different travel arrangements. '
                               'Visit and journey durations have not been shortened to make them appear to fit.')
        elif not day.activities:
            day.review_note = 'Choose activities for this day; no researched schedule was supplied.'
    ceiling = budget_limit(request.get('budget'))
    total = sum(i.amount for i in plan.budget_allocation)
    if ceiling is not None and total > ceiling:
        # These are spending caps, never fare quotations. Rebalance targets only.
        for item in plan.budget_allocation:
            item.amount = int(item.amount * ceiling / total)
        notes.append('Suggested spending caps were rebalanced to your budget. Actual fares and costs remain unverified and may be higher.')
    for note in dict.fromkeys(notes):
        if len(plan.notes) < 8:
            plan.notes.append(note)
        else:
            plan.notes[-1] += ' ' + note
    return schedule_schema(request, research).model_validate(plan.model_dump())


def repair_transfer_allowances(payload, request, research):
    """Fill an omitted transfer from spare time/flexible rest; never shrink a visit.

    The allowance is explicitly provisional, not a calculated road travel time.
    Every other constraint is revalidated before the plan can be presented.
    """
    plan = DetailedItinerary.model_validate(payload)
    repaired = 0
    limit = clock_minutes(request['day_end']) - clock_minutes(request['day_start'])
    for day in plan.days:
        activities = []
        last_visit, transferred = None, True
        for activity in day.activities:
            if activity.kind == 'visit' and last_visit and not transferred:
                activities.append(Activity(kind='transfer', title=f'Transfer to {activity.title}'[:140], duration_minutes=30,
                    description='Provisional 30-minute transfer allowance. Check the actual route and allow more time if needed.'))
                repaired += 1
            activities.append(activity)
            if activity.kind == 'visit':
                last_visit, transferred = activity, False
            elif activity.kind == 'transfer':
                transferred = True
        deficit = max(0, sum(a.duration_minutes for a in activities) - limit)
        for activity in reversed(activities):
            if deficit and activity.kind == 'break':
                reduction = min(deficit, activity.duration_minutes)
                if 0 < activity.duration_minutes - reduction < 5:
                    reduction = activity.duration_minutes
                activity.duration_minutes -= reduction
                deficit = max(0, deficit - reduction)
        if deficit:
            raise ValueError('No spare time or flexible rest to add the missing transfer allowance')
        activities = [a for a in activities if a.duration_minutes]
        day.activities = activities
    if not repaired:
        raise ValueError('No missing transfers to repair')
    note = 'The planner reserved provisional 30-minute allowances for omitted transfers using spare time or flexible rest. Verify actual routes; visit durations and meals were not shortened.'
    if len(plan.notes) < 8:
        plan.notes.append(note)
    else:
        plan.notes[-1] += ' ' + note
    return schedule_schema(request, research).model_validate(plan.model_dump())


def connectivity_context(request, research):
    origin = (request.get('origin') or '').strip()
    if not origin:
        raise DestinationNeedsClarification('Where will you start your journey? Please provide your starting city.', field='origin')
    target = request['destination']
    bases = [e['data'].get('base') for e in research.get('evidence', []) if e.get('data', {}).get('base')]
    if bases:
        target = bases[0] + ', ' + research.get('location', {}).get('admin1', request['destination']) + ', India'
    island = any(s in request['destination'].casefold() for s in ['andaman', 'nicobar', 'lakshadweep'])
    modes = ['flight', 'sea'] if island else ['train', 'bus', 'car/taxi', 'flight']
    links = [{'label': 'Check route in Google Maps', 'url': 'https://www.google.com/maps/dir/?' + urlencode({
        'api': 1, 'origin': origin, 'destination': target})},
        {'label': 'Check Indian Railways services', 'url': 'https://www.irctc.co.in/'}]
    return {'origin': origin, 'destination_base': target, 'modes_to_consider': modes,
        'verification_links': links,
        'availability': 'No live routing, fares, traffic, flight, bus or rail timetables were queried.',
        'planning_rules': 'Compare relevant modes conditionally. Do not assert a direct service, invent train/flight numbers, '
            'departure times, station/airport names, ticket prices or booking availability without evidence. '
            'Road access to islands is not assumed. Explain where transfers or extra transit nights may be needed.'}


def format_clock(minutes):
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def render_schedule(plan, request, connectivity):
    data = plan.model_dump()
    start = date.fromisoformat(str(request['start_date']))
    lines = [plan.overview, '', 'Planning assumptions:',
        f"- Start: {request['origin']}. Destination: {request['destination']}.",
        f"- Trip dates: {start.isoformat()} to {(start + timedelta(days=request['days'] - 1)).isoformat()}.",
        f"- Daily window: {request['day_start']}–{request['day_end']} (destination local time).",
        f"- Total-trip budget: {request['currency']} {request['budget']}; allocations below are planning targets, not quotes."]
    needs_review = any(d.review_note for d in plan.days) or bool(plan.travel_legs)
    if needs_review:
        lines.insert(0, 'Draft itinerary — review the flagged travel/day arrangements before booking.\n')
    if request.get('defaulted_fields'):
        labels = {'start_date': 'departure date (today + 7 days)', 'budget': 'budget', 'currency': 'currency',
                  'day_start': 'daily start', 'day_end': 'daily finish', 'interests': 'interests', 'companions': 'traveller details'}
        lines.append('- Defaults used: ' + ', '.join(labels.get(f, f) for f in request['defaulted_fields']) + '. Change any in trip details.')
    if request.get('companions') == 'not specified':
        lines.append('- Cost planning uses a one-adult baseline; update traveller details for your group.')
    lines += ['', 'Getting there and return:', plan.recommended_mode,
              'Transport options are unverified suggestions; durations and costs are estimates. Check services before booking.']
    for option in plan.transport_options:
        lines.append(f'- {option.mode}: {option.route}. Duration: {option.duration_estimate}. Cost: {option.cost_estimate}. {option.best_for}')
    if plan.travel_legs:
        lines += ['', 'Intercity travel outside the sightseeing schedule:']
        lines.extend(f'- Day {leg.day}: {leg.title} — {leg.duration_minutes / 60:g} hours ({leg.duration_minutes} min, estimate). {leg.timing_note}' for leg in plan.travel_legs)
    schedule = []
    for day in plan.days:
        day_date = start + timedelta(days=day.day - 1)
        lines += ['', f'Day {day.day}: {day_date.isoformat()} — {day.base}']
        if day.review_note:
            lines.append('Needs review: ' + day.review_note)
            lines.extend(f'- Optional, unscheduled: {a.title} — {a.duration_minutes} min (estimate). {a.description}' for a in day.activities)
            schedule.append({'day': day.day, 'date': day_date.isoformat(), 'base': day.base,
                             'status': 'needs_review', 'review_note': day.review_note, 'activities': [],
                             'unscheduled_options': [a.model_dump() for a in day.activities]})
            continue
        cursor = clock_minutes(request['day_start'])
        slots = []
        for index, activity in enumerate(day.activities):
            end = cursor + activity.duration_minutes
            next_visit = next((a.title for a in day.activities[index + 1:] if a.kind == 'visit'), None)
            slot = {**activity.model_dump(), 'start': format_clock(cursor), 'end': format_clock(end),
                    'next_attraction': next_visit if activity.kind == 'visit' else None, 'timing_basis': 'planning estimate'}
            slots.append(slot)
            lines.append(f"- {slot['start']}–{slot['end']} | {activity.title} | {activity.duration_minutes} min (estimate). {activity.description}"
                         + (f' Next attraction: {next_visit}.' if slot['next_attraction'] else ''))
            cursor = end
        finish = clock_minutes(request['day_end'])
        if cursor < finish:
            lines.append(f'- {format_clock(cursor)}–{format_clock(finish)} | Flexible buffer / return to your base | {finish - cursor} min.')
        schedule.append({'day': day.day, 'date': day_date.isoformat(), 'base': day.base, 'status': 'scheduled', 'activities': slots})
    lines += ['', 'Suggested budget allocation:']
    lines.extend(f'- {i.category}: {request["currency"]} {i.amount}' for i in plan.budget_allocation)
    lines += ['', 'Packing checklist:', *['- ' + item for item in plan.packing_list], '', 'Before you travel:',
        '- Visit lengths and travel times are planning estimates, not verified opening hours or live routing results.',
        '- Confirm opening days, entry slots and services before following this schedule.', *['- ' + note for note in plan.notes]]
    all_sources = list(dict.fromkeys([*plan.source_ids, *(s for d in plan.days for a in d.activities for s in a.source_ids)]))
    return {'answer': '\n'.join(lines), 'source_ids': all_sources, 'schedule': schedule,
            'connectivity': connectivity, 'structured_plan': data, 'planning_status': 'needs_review' if needs_review else 'scheduled'}


def demo_schedule(request):
    window = clock_minutes(request['day_end']) - clock_minutes(request['day_start'])
    # Divide any supported window into illustrative activities without overlap.
    weights = [('visit', 'Sample attraction', 3), ('transfer', 'Sample local transfer', 1),
               ('meal', 'Lunch break', 1), ('visit', 'Sample second attraction', 2), ('break', 'Return and rest', 1)]
    durations = [window * weight // 8 for _, _, weight in weights]
    durations[-1] += window - sum(durations)
    return DetailedItinerary(overview='DEMO itinerary — illustrative scheduled activities; no live transport or attraction data.',
        recommended_mode='Check transport from your origin before travel. Demo mode does not verify services.',
        transport_options=[TransportOption(mode='local', route=f"{request['origin']} to {request['destination']}",
            duration_estimate='Not verified in demo mode', cost_estimate='Not verified', best_for='Illustration only')],
        days=[DayPlan(day=i, base=request['destination'], activities=[Activity(kind=k, title=t, duration_minutes=n,
            description='Illustrative activity only.', source_ids=['demo-1']) for (k,t,_), n in zip(weights,durations)])
            for i in range(1, request['days'] + 1)],
        budget_allocation=[BudgetItem(category='Trip budget placeholder', amount=int(budget_limit(request['budget']) or 0))],
        packing_list=['Comfortable shoes', 'Water bottle', 'Charger'], source_ids=['demo-1'])
