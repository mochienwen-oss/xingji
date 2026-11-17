import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..db import Expense, TripBudget, User
from ..schemas import BudgetUpdate, ExpenseInput
from ..services import budget, trip_places
from .dependencies import current_user, db_session, get_trip, get_trip_member

router = APIRouter()
log = logging.getLogger(__name__)


def expense_json(item: Expense) -> dict:
    return {key: getattr(item, key) for key in ('id', 'amount_cents', 'category', 'expense_date', 'place_id', 'note')}


@router.get('/api/trips/{trip_id}/budget')
def get_budget(trip_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    get_trip_member(trip_id, user, db)
    record = db.get(TripBudget, trip_id)
    expenses = db.scalars(select(Expense).where(Expense.trip_id == trip_id).order_by(Expense.expense_date.desc(), Expense.id.desc())).all()
    return {'amount_cents': record.amount_cents if record else None, 'expenses': [expense_json(item) for item in expenses]}


@router.put('/api/trips/{trip_id}/budget')
def set_budget(trip_id: int, body: BudgetUpdate, user: User = Depends(current_user), db: Session = Depends(db_session)):
    """总预算只由 owner 设置；协作者可查看预算，并记录、修改、删除任意一笔支出（支出现在不记提交人）。"""
    get_trip(trip_id, user, db)
    record = db.get(TripBudget, trip_id)
    if record is None:
        record = TripBudget(trip_id=trip_id)
        db.add(record)
    record.amount_cents = body.amount_cents
    db.commit()
    return {'amount_cents': record.amount_cents}


@router.post('/api/trips/{trip_id}/expenses', status_code=201)
def add_expense(trip_id: int, body: ExpenseInput, user: User = Depends(current_user), db: Session = Depends(db_session)):
    get_trip_member(trip_id, user, db)
    item = Expense(trip_id=trip_id, **body.model_dump(mode='json'))
    db.add(item)
    db.commit()
    db.refresh(item)
    return expense_json(item)


def expense_in_trip(db: Session, trip_id: int, expense_id: int) -> Expense:
    item = db.scalar(select(Expense).where(Expense.id == expense_id, Expense.trip_id == trip_id))
    if item is None:
        raise HTTPException(404, '没有找到这笔支出。')
    return item


@router.put('/api/trips/{trip_id}/expenses/{expense_id}')
def edit_expense(trip_id: int, expense_id: int, body: ExpenseInput, user: User = Depends(current_user), db: Session = Depends(db_session)):
    get_trip_member(trip_id, user, db)
    item = expense_in_trip(db, trip_id, expense_id)
    for key, value in body.model_dump(mode='json').items():
        setattr(item, key, value)
    db.commit()
    return expense_json(item)


@router.delete('/api/trips/{trip_id}/expenses/{expense_id}')
def delete_expense(trip_id: int, expense_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    get_trip_member(trip_id, user, db)
    db.delete(expense_in_trip(db, trip_id, expense_id))
    db.commit()
    return {'ok': True}


@router.post('/api/trips/{trip_id}/budget/estimate')
async def estimate_budget(trip_id: int, user: User = Depends(current_user), db: Session = Depends(db_session)):
    row = get_trip_member(trip_id, user, db)
    try:
        saved = json.loads(row.data or '{}')
        data = await trip_places.refresh(saved)
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        # 历史数据损坏/字段缺失时返回可读 503，而不是把 500 抛给预算面板。
        log.warning('budget estimate skipped: corrupt trip data trip_id=%s error=%s', trip_id, exc)
        raise HTTPException(503, '行程数据暂时无法读取，请稍后再试。') from exc
    request = data.get('request')
    days = data.get('days')
    if not isinstance(request, dict) or not isinstance(days, list):
        log.warning('budget estimate skipped: incomplete trip data trip_id=%s', trip_id)
        raise HTTPException(503, '行程数据暂时无法读取，请稍后再试。')
    if data.get('place_notice'):
        raise HTTPException(503, data['place_notice'])
    return {'items': await budget.estimate(request, days)}
