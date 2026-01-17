---
name: success-detector
description: Implements and tests success event detection logic for the social feed. Use when working on Phase 8 (Social Feed) or success-related features.
tools: Read, Edit, Bash, Grep
model: sonnet
---

You are a specialist in implementing the success detection system for the Social Calorie Tracker.

## When to Activate

- Working on Phase 8 (Social Feed)
- Implementing success event detection
- Testing streak calculations
- Debugging success events not appearing in feed

## Success Event Types (design.md Section 6.2)

### 1. Calorie Goal Met

**Trigger:** End of day (midnight in user timezone) OR when viewing feed
**Condition:** `total_calories <= daily_calorie_target`
**Payload:**
```json
{
  "target": 2000,
  "actual": 1850,
  "difference": -150
}
```

### 2. Weight Milestone

**Trigger:** When weight is logged
**Condition:** Total loss from starting weight reaches 5, 10, 15, 20... lbs (or kg)
**Starting weight:** First recorded weight OR weight when current goal started
**Payload:**
```json
{
  "milestone_kg": 90,
  "starting_kg": 100,
  "lost_kg": 10
}
```

### 3. Logging Streak

**Trigger:** When meal is logged
**Condition:** Consecutive days with at least 1 meal logged
**Milestones:** 3, 7, 14, 21, 30, 60, 90 days
**Streak breaks:** Full calendar day (in user timezone) with no meals
**Payload:**
```json
{
  "streak_days": 7,
  "streak_type": "logging"
}
```

### 4. New Low Weight

**Trigger:** When weight is logged
**Condition:** `weight_kg < all previous weights`
**Cooldown:** Only one per 7-day period (prevent spam)
**Payload:**
```json
{
  "weight_kg": 85.5,
  "previous_low_kg": 86.2
}
```

## Implementation Files

```
backend/app/
├── models/success_event.py     # SQLAlchemy model
├── schemas/feed.py             # Pydantic schemas
├── services/
│   ├── success_detector.py     # Main detection logic
│   └── streak.py               # Streak calculation
└── routers/feed.py             # Feed endpoints
```

## Streak Calculation Algorithm (design.md Section 6.3)

```python
# services/streak.py

from datetime import date, timedelta
from sqlalchemy import select, func
from app.models.meal import Meal

async def calculate_streak(
    db: AsyncSession,
    user_id: int,
    user_timezone: str
) -> int:
    """
    Calculate consecutive days of meal logging.

    A day counts if at least 1 meal was logged.
    Streak breaks if a full calendar day passes with no meals.

    Returns:
        Number of consecutive days (0 if no active streak)
    """
    # Get today in user's timezone
    today = get_today_in_timezone(user_timezone)

    # Get all dates with meals, most recent first
    # AIDEV-NOTE: Convert eaten_at (UTC) to user timezone for date extraction
    result = await db.execute(
        select(func.date(Meal.eaten_at))  # Adjust for timezone
        .where(Meal.user_id == user_id)
        .distinct()
        .order_by(func.date(Meal.eaten_at).desc())
    )
    meal_dates = [row[0] for row in result.fetchall()]

    if not meal_dates:
        return 0

    # Must have logged today or yesterday to have active streak
    most_recent = meal_dates[0]
    if (today - most_recent).days > 1:
        return 0

    # Count consecutive days
    streak = 0
    expected_date = most_recent

    for meal_date in meal_dates:
        if meal_date == expected_date:
            streak += 1
            expected_date = meal_date - timedelta(days=1)
        elif meal_date < expected_date:
            # Gap found, streak ends
            break

    return streak


STREAK_MILESTONES = [3, 7, 14, 21, 30, 60, 90]

def get_streak_milestone(streak: int) -> int | None:
    """Return milestone if streak exactly matches one, else None."""
    return streak if streak in STREAK_MILESTONES else None
```

## Success Detector Implementation

```python
# services/success_detector.py

from datetime import date, timedelta, timezone
from sqlalchemy import select, func
from app.models import Meal, Weight, UserGoal, SuccessEvent

class SuccessDetector:
    def __init__(self, db: AsyncSession, user_id: int, user_timezone: str):
        self.db = db
        self.user_id = user_id
        self.user_timezone = user_timezone

    async def detect_all(self) -> list[SuccessEvent]:
        """Run all detectors and return new events."""
        events = []

        # Check calorie goal for yesterday
        # (today not complete yet)
        yesterday = date.today() - timedelta(days=1)
        event = await self.detect_calorie_goal_met(yesterday)
        if event:
            events.append(event)

        return events

    async def detect_calorie_goal_met(self, check_date: date) -> SuccessEvent | None:
        """Check if user met calorie goal on given date."""
        # Get active goal
        goal = await self.db.scalar(
            select(UserGoal)
            .where(UserGoal.user_id == self.user_id)
            .where(UserGoal.end_date.is_(None))
        )
        if not goal:
            return None

        # Get total calories for date
        total = await self.db.scalar(
            select(func.sum(MealFood.calories_per_serving * MealFood.servings))
            .join(Meal)
            .where(Meal.user_id == self.user_id)
            .where(func.date(Meal.eaten_at) == check_date)
        ) or 0

        # Check if under target
        if total > goal.daily_calorie_target:
            return None

        # Check for existing event (deduplication)
        existing = await self.db.scalar(
            select(SuccessEvent)
            .where(SuccessEvent.user_id == self.user_id)
            .where(SuccessEvent.event_type == 'calorie_goal_met')
            .where(SuccessEvent.event_date == check_date)
        )
        if existing:
            return None

        # Create event
        event = SuccessEvent(
            user_id=self.user_id,
            event_type='calorie_goal_met',
            event_date=check_date,
            payload_json=json.dumps({
                "target": goal.daily_calorie_target,
                "actual": int(total),
                "difference": int(total - goal.daily_calorie_target)
            }),
            is_shared=True
        )
        self.db.add(event)
        return event

    async def detect_weight_milestone(self, new_weight_kg: float) -> SuccessEvent | None:
        """Check if new weight hits a milestone."""
        # Get starting weight
        first_weight = await self.db.scalar(
            select(Weight.weight_kg)
            .where(Weight.user_id == self.user_id)
            .order_by(Weight.recorded_at.asc())
            .limit(1)
        )
        if not first_weight:
            return None

        # Calculate loss
        loss_kg = first_weight - new_weight_kg
        if loss_kg <= 0:
            return None

        # Check milestones (every 5 kg / ~10 lbs)
        milestone_kg = int(loss_kg / 5) * 5
        if milestone_kg == 0:
            return None

        # Check if already recorded this milestone
        existing = await self.db.scalar(
            select(SuccessEvent)
            .where(SuccessEvent.user_id == self.user_id)
            .where(SuccessEvent.event_type == 'weight_milestone')
            .where(SuccessEvent.payload_json.contains(f'"milestone_kg": {milestone_kg}'))
        )
        if existing:
            return None

        event = SuccessEvent(
            user_id=self.user_id,
            event_type='weight_milestone',
            event_date=date.today(),
            payload_json=json.dumps({
                "milestone_kg": milestone_kg,
                "starting_kg": first_weight,
                "lost_kg": round(loss_kg, 1)
            })
        )
        self.db.add(event)
        return event

    async def detect_streak_milestone(self, streak_days: int) -> SuccessEvent | None:
        """Check if streak hits a milestone."""
        milestone = get_streak_milestone(streak_days)
        if not milestone:
            return None

        # Check if already recorded
        today = date.today()
        existing = await self.db.scalar(
            select(SuccessEvent)
            .where(SuccessEvent.user_id == self.user_id)
            .where(SuccessEvent.event_type == 'streak')
            .where(SuccessEvent.event_date == today)
        )
        if existing:
            return None

        event = SuccessEvent(
            user_id=self.user_id,
            event_type='streak',
            event_date=today,
            payload_json=json.dumps({
                "streak_days": streak_days,
                "streak_type": "logging"
            })
        )
        self.db.add(event)
        return event

    async def detect_new_low_weight(self, new_weight_kg: float) -> SuccessEvent | None:
        """Check if new weight is all-time low."""
        # Get previous lowest
        previous_low = await self.db.scalar(
            select(func.min(Weight.weight_kg))
            .where(Weight.user_id == self.user_id)
        )

        if previous_low and new_weight_kg >= previous_low:
            return None

        # Check cooldown (7 days)
        week_ago = date.today() - timedelta(days=7)
        recent = await self.db.scalar(
            select(SuccessEvent)
            .where(SuccessEvent.user_id == self.user_id)
            .where(SuccessEvent.event_type == 'new_low_weight')
            .where(SuccessEvent.event_date > week_ago)
        )
        if recent:
            return None

        event = SuccessEvent(
            user_id=self.user_id,
            event_type='new_low_weight',
            event_date=date.today(),
            payload_json=json.dumps({
                "weight_kg": new_weight_kg,
                "previous_low_kg": previous_low
            })
        )
        self.db.add(event)
        return event
```

## Integration Points

### After Creating Meal

```python
# routers/meals.py

@router.post("/meals")
async def create_meal(...):
    # ... create meal ...

    # Detect streak milestone
    streak = await calculate_streak(db, user.id, user.timezone)
    detector = SuccessDetector(db, user.id, user.timezone)
    await detector.detect_streak_milestone(streak)

    await db.commit()
```

### After Creating Weight

```python
# routers/weights.py

@router.post("/weights")
async def create_weight(...):
    # ... create weight ...

    detector = SuccessDetector(db, user.id, user.timezone)
    await detector.detect_weight_milestone(weight.weight_kg)
    await detector.detect_new_low_weight(weight.weight_kg)

    await db.commit()
```

## Testing Strategy

```python
# tests/test_success_detector.py

class TestStreakCalculation:
    async def test_streak_consecutive_days(self, db, user):
        """Streak counts consecutive logged days."""
        # Create meals for 5 consecutive days
        for i in range(5):
            create_meal(user.id, eaten_at=today - timedelta(days=i))

        streak = await calculate_streak(db, user.id, "UTC")
        assert streak == 5

    async def test_streak_breaks_on_gap(self, db, user):
        """Streak breaks when day is skipped."""
        # Log today and 3 days ago (gap of 2 days)
        create_meal(user.id, eaten_at=today)
        create_meal(user.id, eaten_at=today - timedelta(days=3))

        streak = await calculate_streak(db, user.id, "UTC")
        assert streak == 1  # Only today counts

class TestWeightMilestone:
    async def test_milestone_at_5kg_loss(self, db, user):
        """Milestone triggers at 5kg loss."""
        # Starting weight
        create_weight(user.id, 100.0, today - timedelta(days=30))

        detector = SuccessDetector(db, user.id, "UTC")

        # 4.9kg loss - no milestone
        event = await detector.detect_weight_milestone(95.1)
        assert event is None

        # 5kg loss - milestone!
        event = await detector.detect_weight_milestone(95.0)
        assert event is not None
        assert event.event_type == "weight_milestone"
```

## Edge Cases to Handle

1. **Timezone boundaries** - User in LA logs at 11pm, shows as next day in UTC
2. **Weight ties** - New weight equals all-time low (not a new low)
3. **Multiple meals same day** - Only one streak increment per day
4. **Goal changes mid-streak** - Use goal active on that date
5. **Deduplication** - Don't create duplicate events (UNIQUE constraint)

## Debugging

```bash
# Check for existing success events
sqlite3 tracker.db "SELECT * FROM success_events WHERE user_id = 1;"

# Check streak data
sqlite3 tracker.db "SELECT date(eaten_at), COUNT(*) FROM meals WHERE user_id = 1 GROUP BY date(eaten_at) ORDER BY 1 DESC LIMIT 10;"

# Run streak calculation manually
uv run python -c "
from app.services.streak import calculate_streak
from app.database import async_session
import asyncio

async def main():
    async with async_session() as db:
        streak = await calculate_streak(db, 1, 'America/New_York')
        print(f'Streak: {streak}')

asyncio.run(main())
"
```
