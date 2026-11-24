"""图库对外接口的返回结构。只有号和缩略图 / 预览图的网址，没有任何文件路径（check.py 第 6 条）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TypeRef(BaseModel):
    code: str
    name: str


class TypeCount(TypeRef):
    count: int


class TypeGroup(BaseModel):
    key: str
    title: str
    types: list[TypeCount]


class Chip(BaseModel):
    label: str
    query: str


class SiteOut(BaseModel):
    """每页都要的：页头链接、「要全部图库」弹层、图型下拉。"""

    service_url: str
    qr_url: str  # 客服二维码图片地址；空 = 还没放上来
    account_note: str  # 关注公众号那一行；空 = 不显示
    types: list[TypeRef]


class HomeOut(BaseModel):
    total: int
    journals: int
    groups: list[TypeGroup]
    popular: list[Chip]


class Card(BaseModel):
    id: int
    thumb_url: str
    title: str
    journal: str
    year: str
    tier: str
    type_code: str
    type_name: str


class Group(BaseModel):
    key: str
    title: str
    learn: str
    cards: list[Card]


class WordCount(BaseModel):
    word: str
    count: int  # 全库有几张图对上这个词


class SearchOut(BaseModel):
    search_id: int | None
    query: str
    words: list[WordCount]
    zero_words: list[str]
    guess: TypeRef | None  # 猜出来的图型；猜不出 null
    code: str  # 实际按哪个图型找的（「任意」= 不限）
    code_name: str
    overridden: bool
    groups: list[Group]
    total: int


class BrowseOut(BaseModel):
    code: str
    name: str
    group_title: str
    total: int
    cards: list[Card]


class Tag(BaseModel):
    label: str
    words: list[str]


class DetailOut(Card):
    preview_url: str
    paper_title: str
    authors: str
    doi: str
    link: str
    caption: str
    cite: str
    types: list[TypeRef]
    tags: list[Tag]
    credits: list[str] = []  # 「标签由 XX 改过」这类署名（审过的才有）


class CardsOut(BaseModel):
    cards: list[Card]


class Proposed(BaseModel):
    """「标签不对，我来改」：直接写改成什么（都可不填）。"""

    what: str = Field(default="", max_length=120)  # 这张图讲的是什么
    code: str = Field(default="", max_length=8)  # 图型


class FeedbackIn(BaseModel):
    reason: str = Field(max_length=32)
    note: str = Field(default="", max_length=500)
    query: str = Field(default="", max_length=300)
    search_id: int | None = None
    website: str = ""  # 蜜罐：人看不见，机器人会填
    proposed: Proposed | None = None
    credit: str = Field(default="", max_length=40)  # 署名


class TakedownIn(BaseModel):
    """版权方要求删除：哪几张（网址或号）、权利人、联系方式、理由。"""

    figures: str = Field(min_length=1, max_length=2000)
    holder: str = Field(default="", max_length=200)
    contact: str = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=2000)
    website: str = ""


class SiteFeedbackIn(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    contact: str = Field(default="", max_length=100)
    page: str = Field(default="", max_length=300)
    website: str = ""


class ClickIn(BaseModel):
    search_id: int
    figure_id: int
    position: int = Field(default=0, ge=0, le=1000)
    lane: str = Field(default="", max_length=64)


class Done(BaseModel):
    message: str
