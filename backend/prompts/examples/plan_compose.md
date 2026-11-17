# 示例：两日行程编排

## 输入

```json
{
  "需求": {"city":"杭州","days":2,"start_date":"2026-11-14","travelers":2,"interests":"老街区、茶文化","pace":"适中","budget":"两人 2000 以内","must_visit":"灵隐寺","transport":"transit"},
  "候选地点": [
    {"id":"B0FFH1","name":"灵隐寺","address":"西湖区灵隐路法云弄1号","location":"120.102,30.240"},
    {"id":"B0FFH2","name":"中国茶叶博物馆","address":"西湖区龙井路88号","location":"120.117,30.226"},
    {"id":"B0FFH3","name":"西湖风景名胜区","address":"西湖区龙井路1号","location":"120.144,30.245"},
    {"id":"B0FFH4","name":"河坊街","address":"上城区河坊街","location":"120.169,30.239"},
    {"id":"B0FFH5","name":"南宋御街","address":"上城区中山中路","location":"120.170,30.241"},
    {"id":"B0FFH6","name":"龙井村","address":"西湖区龙井村","location":"120.108,30.221"}
  ],
  "当前行程": null,
  "用户修改要求": "",
  "高德交通核验": []
}
```

## 输出

```json
{
  "days": [
    {"stops": [
      {"id":"B0FFH1","duration":150,"reason":"上午体力好，主殿和飞来峰一起走"},
      {"id":"B0FFH6","duration":90,"reason":"下山顺路，喝茶歇脚再走"},
      {"id":"B0FFH2","duration":90,"reason":"室内展馆，午后避晒补茶文化"}
    ]},
    {"stops": [
      {"id":"B0FFH3","duration":180,"reason":"留足湖边步行，不赶下一个点"},
      {"id":"B0FFH4","duration":120,"reason":"傍晚转到老城，边逛边吃"},
      {"id":"B0FFH5","duration":90,"reason":"与河坊街相接，夜景顺路收尾"}
    ]}
  ],
  "summary": "西线、老城分两天，灵隐寺放在首日上午，每天只在一个片区走。"
}
```

## 说明

- 第 1 天三个点都在西湖西侧（直线跨度约 3 公里），第 2 天三个点都在老城与湖东（约 3 公里），没有跨区往返。
- 灵隐寺是 must_visit，安排在第一天上午。
- 西湖风景名胜区只出现一次，没有再把它的子景点拆成独立站点。
- 没有写交通耗时、门票、营业时间；理由只写安排逻辑。
