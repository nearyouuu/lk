from __future__ import annotations
from typing import Dict, Any, Tuple
from datetime import datetime, timedelta
import hmac, hashlib

from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.core.config import Settings
from app.models.testing import Test, Question, QuestionType, TestAttempt, AttemptStatus

settings = Settings()


def make_attempt_token(attempt_id: int, student_id: int, test_id: int) -> str:
    msg = f"{attempt_id}:{student_id}:{test_id}".encode("utf-8")
    key = settings.JWT_SECRET.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_attempt_token(token: str, attempt_id: int, student_id: int, test_id: int) -> bool:
    return hmac.compare_digest(token, make_attempt_token(attempt_id, student_id, test_id))


def can_start_attempt(db: Session, test: Test, student_id: int) -> Tuple[bool, str | None, int]:
    now = datetime.utcnow()
    if not test.is_active:
        return False, "Тест отключён", 0
    if test.deadline and now > test.deadline:
        return False, "Дедлайн истёк", 0

    cnt = db.scalar(
        select(func.count()).select_from(TestAttempt)
        .where(TestAttempt.test_id == test.id, TestAttempt.student_id == student_id)
    ) or 0
    if cnt >= (test.max_attempts or 1):
        return False, "Превышено число попыток", cnt
    return True, None, cnt


def calc_must_finish_at(started_at: datetime, duration_minutes: int | None) -> datetime | None:
    if duration_minutes and duration_minutes > 0:
        return started_at + timedelta(minutes=duration_minutes)
    return None

def normalize_str(val):
    if val is None:
        return ""
    return str(val).strip().lower()

def evaluate_auto_detailed(questions: list[Question], answers: Dict[str, Any]) -> dict[str, int]:
    per_question = {}
    for q in questions:
        ans = answers.get(str(q.id))
        if ans is None:
            per_question[str(q.id)] = 0
            continue

        q_score = 0

        if q.type in (QuestionType.choice, QuestionType.multi_choice):
            correct = set(map(normalize_str, q.correct_answers or []))
            if not correct:
                per_question[str(q.id)] = 0
                continue
            if isinstance(ans, str):
                if normalize_str(ans) in correct:
                    q_score = q.points
            elif isinstance(ans, list):
                if set(map(normalize_str, ans)) == correct:
                    q_score = q.points

        elif q.type == QuestionType.input:
            if normalize_str(ans) in set(map(normalize_str, q.correct_answers or [])):
                q_score = q.points

        elif q.type == QuestionType.match:
            if isinstance(ans, dict) and isinstance(q.correct_answers, dict):
                matched = sum(
                    1
                    for k, v in q.correct_answers.items()
                    if normalize_str(ans.get(k)) == normalize_str(v)
                )
                total = len(q.correct_answers)
                if total > 0:
                    q_score = round(q.points * (matched / total))

        per_question[str(q.id)] = q_score

    return per_question


def evaluate_auto(questions: list[Question], answers: Dict[str, Any]) -> int:
    score = 0

    for q in questions:
        ans = answers.get(str(q.id))
        if ans is None:
            continue

        if q.type in (QuestionType.choice, QuestionType.multi_choice):
            correct = set(normalize_str(x) for x in (q.correct_answers or []))
            if not correct:
                continue

            if isinstance(ans, str):
                if normalize_str(ans) in correct:
                    score += q.points
            elif isinstance(ans, list):
                norm_ans = set(normalize_str(a) for a in ans)
                if norm_ans == correct:
                    score += q.points

        elif q.type == QuestionType.input:
            correct_variants = set(normalize_str(v) for v in (q.correct_answers or []))
            if normalize_str(ans) in correct_variants:
                score += q.points

        elif q.type == QuestionType.match:
            if not isinstance(ans, dict):
                continue
            correct_map = q.correct_answers or {}
            if not isinstance(correct_map, dict):
                continue

            matched = sum(
                1
                for left, right in correct_map.items()
                if normalize_str(ans.get(left)) == normalize_str(right)
            )
            total = len(correct_map)
            if total > 0:
                score += round(q.points * (matched / total))

        elif q.type == QuestionType.long_input:
            continue

    return score

def get_max_score_for_test(test: Test) -> int:
    if not test.questions:
        return 0
    return sum(q.points for q in test.questions)


def get_points_per_question(test: Test) -> dict[int, int]:
    return {q.id: q.points for q in test.questions}
