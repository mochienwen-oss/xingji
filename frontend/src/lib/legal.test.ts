import { describe, expect, it } from 'vitest';
import { EMPTY_OPERATOR, normalizeOperator } from './legal';

describe('normalizeOperator', () => {
  it('未配置时回退为空对象', () => {
    expect(normalizeOperator(undefined)).toEqual(EMPTY_OPERATOR);
    expect(normalizeOperator(null)).toEqual(EMPTY_OPERATOR);
    expect(normalizeOperator('oops')).toEqual(EMPTY_OPERATOR);
  });

  it('去掉首尾空格并忽略非字符串字段', () => {
    expect(
      normalizeOperator({
        name: ' 杭州行迹科技有限公司 ',
        contact_email: ' legal@xingji.example ',
        jurisdiction: 123,
        icp_number: '浙ICP备2026000000号',
      }),
    ).toEqual({
      name: '杭州行迹科技有限公司',
      contact_email: 'legal@xingji.example',
      jurisdiction: '',
      icp_number: '浙ICP备2026000000号',
    });
  });
});
