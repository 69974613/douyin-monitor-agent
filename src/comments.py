from __future__ import annotations

from typing import List, Optional, Tuple

from src.models import Comment, CommentHit


def classify(text: str, strong_keywords: List[str],
             weak_keywords: List[str]) -> Tuple[Optional[str], str]:
    """强意图优先匹配：强关键词（BGM/求歌名/背景音乐…）→ 自动回复；
    弱关键词（歌/好听）→ 仅记录、转人工，避免"唱了一首歌"这类误伤打扰。"""
    low = text.lower()
    # 长关键词优先匹配：否则"这首歌叫什么歌"永远先命中"什么歌"，
    # 对照题目 10 个关键词演示时该关键词无法在"命中关键词"列出现
    for kw in sorted(strong_keywords, key=len, reverse=True):
        if kw.lower() in low:
            return kw, "strong"
    for kw in sorted(weak_keywords, key=len, reverse=True):
        if kw.lower() in low:
            return kw, "weak"
    return None, ""


def build_reply(template: str, song: str, singer: str) -> str:
    return template.format(song=song, singer=singer)


def scan_comments(
    comments: List[Comment],
    strong_keywords: List[str],
    weak_keywords: List[str],
    templates: List[str],
    song: str,
    singer: str,
) -> List[CommentHit]:
    """扫描评论区：强意图生成话术，弱意图标记'仅记录'。

    评论级去重由调用方（Monitor）经 SQLite replied_comments 表保证，
    本函数保持无状态，可安全重试。
    """
    hits: List[CommentHit] = []
    for i, c in enumerate(comments):
        kw, strength = classify(c.text, strong_keywords, weak_keywords)
        if not kw:
            continue
        if strength == "strong":
            tpl = templates[i % len(templates)]
            hits.append(CommentHit(
                comment_id=c.comment_id,
                account=c.account, aweme_id=c.aweme_id, title="",
                comment_text=c.text, matched_keyword=kw,
                reply_text=build_reply(tpl, song, singer), action="已自动回复"))
        else:
            hits.append(CommentHit(
                comment_id=c.comment_id,
                account=c.account, aweme_id=c.aweme_id, title="",
                comment_text=c.text, matched_keyword=kw,
                reply_text="", action="弱意图-仅记录(转人工)"))
    return hits
