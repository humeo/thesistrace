"""SW2021 L1 identities; daily membership remains owned by Data Generation.

Source: https://tushare.pro/document/2?doc_id=181 (2021 classification table).
The six-digit index code is the identity stored in sw2021_l1, not industry_code.
"""

from types import MappingProxyType

SW2021_L1 = MappingProxyType(
    {
        "801010": "农林牧渔",
        "801030": "基础化工",
        "801040": "钢铁",
        "801050": "有色金属",
        "801080": "电子",
        "801110": "家用电器",
        "801120": "食品饮料",
        "801130": "纺织服饰",
        "801140": "轻工制造",
        "801150": "医药生物",
        "801160": "公用事业",
        "801170": "交通运输",
        "801180": "房地产",
        "801200": "商贸零售",
        "801210": "社会服务",
        "801230": "综合",
        "801710": "建筑材料",
        "801720": "建筑装饰",
        "801730": "电力设备",
        "801740": "国防军工",
        "801750": "计算机",
        "801760": "传媒",
        "801770": "通信",
        "801780": "银行",
        "801790": "非银金融",
        "801880": "汽车",
        "801890": "机械设备",
        "801950": "煤炭",
        "801960": "石油石化",
        "801970": "环保",
        "801980": "美容护理",
    }
)


def validate_sw2021_l1(value: object) -> str:
    if type(value) is not int or str(value) not in SW2021_L1:
        raise ValueError("Industry must be a literal SW2021 L1 code from the catalog")
    return str(value)
