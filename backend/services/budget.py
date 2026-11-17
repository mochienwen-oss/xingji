import json
from pydantic import BaseModel, Field, ValidationError
from .errors import ServiceError
from .llm import model_json


class EstimateItem(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    low: float = Field(ge=0, le=10000000, allow_inf_nan=False)
    high: float = Field(ge=0, le=10000000, allow_inf_nan=False)
    assumption: str = Field(min_length=1, max_length=200)


async def estimate(request: dict, days: list[dict]) -> list[dict]:
    prompt = ('你是旅行预算助手。根据用户的城市、出行天数、人数和行程，按整个旅行团估计费用范围。'
              '不得声称实时价格、真实票价或已核实的报价；无法合理估算时返回空数组。'
              '返回JSON：{"items":[{"category":"费用类别","low":最低金额,"high":最高金额,'
              '"assumption":"适用人数和关键假设"}]}，金额单位人民币元，最多5项。')
    context = {'需求': request, '行程': [[s['place']['name'] for s in day['stops']] for day in days]}
    raw = await model_json([{'role': 'system', 'content': prompt},
                            {'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}], 1500)
    try:
        items = raw['items']
        if not isinstance(items, list) or len(items) > 5:
            raise ValueError('items')
        result = [EstimateItem.model_validate(item) for item in items]
        if any(item.low > item.high for item in result):
            raise ValueError('range')
        return [item.model_dump() for item in result]
    except (KeyError, ValueError, TypeError, ValidationError) as exc:
        raise ServiceError('AI 费用估算结果不符合要求，请重试。') from exc
