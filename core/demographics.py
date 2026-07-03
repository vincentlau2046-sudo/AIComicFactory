"""
core/demographics.py — 角色人口学推断（年龄/性别/年龄标签）

从角色描述文本推断性别、年龄段、年龄标签，供 S3/S5 prompt 构建使用。
修复：年龄关键词列表中的正则模式（如 "6[0-9]岁"）用 re.search 替代 in 判断。
"""

import re
from typing import Tuple


# 年龄推断规则：(标签, [关键词或正则], age_tag_for_danbooru)
AGE_RULES = [
    ("老年人", [
        r"老年", r"老头", r"退休", r"爷爷", r"年老", r"奶奶", r"白发", r"皱纹", r"老人",
        r"6[0-9]岁", r"7[0-9]岁", r"8[0-9]岁",
    ], "old, elderly"),
    ("中年人", [
        r"中年", r"师傅", r"工头", r"大姐", r"阿姨", r"大叔",
        r"4[0-9]岁", r"5[0-9]岁", r"鱼尾纹", r"灰白", r"发际线后退",
    ], "mature, middle-aged"),
    ("青年人", [
        r"年轻", r"小伙", r"青年", r"2[0-9]岁", r"新手", r"大学生", r"学生", r"清澈",
    ], "young"),
]

# 性别推断关键词
FEMALE_KEYWORDS = ["女", "女性", "女士", "小姐", "姐姐", "妹妹", "妈妈", "奶奶", "阿姨", "大姐", "少妇", "妇人", "女人", "女孩", "姑娘"]
MALE_KEYWORDS = ["男", "男性", "先生", "小伙", "老爹", "儿子", "哥哥", "弟弟", "爸爸", "爷爷", "大叔", "男人", "男孩", "小伙子"]


def infer_gender(text: str, gender_field: str = None) -> str:
    """
    推断角色性别。
    
    Args:
        text: 角色描述文本（description + visualHint 等）
        gender_field: 显式 gender 字段（"male"/"female"），优先级最高
    
    Returns:
        "male" | "female" | "unknown"
    """
    if gender_field:
        return gender_field
    
    # 只看前 200 字符，避免被长描述中的代词干扰
    t = text[:200] if text else ""
    
    female_score = sum(1 for kw in FEMALE_KEYWORDS if kw in t)
    male_score = sum(1 for kw in MALE_KEYWORDS if kw in t)
    
    if female_score > male_score:
        return "female"
    elif male_score > female_score:
        return "male"
    return "unknown"


def infer_age(text: str, visual_hint: str = "") -> Tuple[str, str]:
    """
    推断角色年龄段。
    
    Args:
        text: 角色描述文本
        visual_hint: visualHint 字段
    
    Returns:
        (label, danbooru_tag)
        label: "老年人" | "中年人" | "青年人" | "成年人"
        danbooru_tag: "old, elderly" | "mature, middle-aged" | "young" | ""
    """
    combined = f"{text or ''} {visual_hint or ''}"
    
    for label, patterns, tag in AGE_RULES:
        for pattern in patterns:
            if re.search(pattern, combined):
                return label, tag
    
    return "成年人", ""


def infer_gender_tag(text: str, gender_field: str = None, age_tag: str = "") -> str:
    """
    推断 Danbooru 性别+年龄标签。
    
    Returns:
        "1girl, old, elderly" | "1man, young" | "1girl" | "1man"
    """
    gender = infer_gender(text, gender_field)
    
    # 对于 unknown 性别，从文本前 80 字符猜测
    if gender == "unknown":
        t = text[:80] if text else ""
        gender = "female" if any(kw in t for kw in ["女", "女性"]) else "male"
    
    base = "1girl" if gender == "female" else "1man"
    if age_tag:
        return f"{base}, {age_tag}"
    return base


def infer_concept_gender(text: str, gender_field: str = None) -> str:
    """
    推断写实概念风格性别词。
    
    Returns:
        "woman" | "man"
    """
    gender = infer_gender(text, gender_field)
    if gender == "unknown":
        t = text[:80] if text else ""
        gender = "female" if any(kw in t for kw in ["女", "女性"]) else "male"
    return "woman" if gender == "female" else "man"
