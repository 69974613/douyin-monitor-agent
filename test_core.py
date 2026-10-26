from __future__ import annotations

"""核心逻辑单测（标准库 unittest，无需 pytest）：`python -m unittest test_core -v`

覆盖三块最不能坏的业务：
1. 题目2 申请单解析（正则层——LLM 兜底依赖网络，不进单测）
2. 财务对账（差额计算与预警文案）
3. 评论关键词分类（含"长词优先"与 BGM 大小写归一回归）
"""

import os
import unittest
from unittest import mock

from src.agent2.master_agent import reconcile
from src.agent2.sub_agent import parse_applications
from src.comments import classify

STRONG = ["BGM", "求歌名", "什么歌", "什么歌曲", "这首歌叫什么歌", "背景音乐"]
WEAK = ["好听", "歌"]


class TestParseApplications(unittest.TestCase):
    def test_advance_line(self):
        text = "申请为【达人：初秋】垫付 ¥950（歌曲《你是我的仰望》）"
        apps, unparsed, _stated = parse_applications("", text)
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0].amount, 950.0)
        self.assertEqual(apps[0].blogger, "初秋")
        self.assertEqual(apps[0].type, "垫付")
        self.assertEqual(apps[0].song, "你是我的仰望")
        self.assertEqual(unparsed, [])

    def test_doujia_line(self):
        text = ("抖加支付人：爆火音乐\n"
                "歌名：《你是我的仰望》- 博主名：初秋 - 金额：¥400")
        apps, unparsed, _stated = parse_applications(text, "")
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0].type, "抖加")
        self.assertEqual(apps[0].amount, 400.0)
        self.assertEqual(apps[0].payer, "爆火音乐")
        self.assertEqual(unparsed, [])

    def test_bad_line_goes_to_unparsed(self):
        text = "初秋 垫付 ¥950（没写歌曲名）"   # 含垫付+¥ 但不符合 ADVANCE_RE 固定句式
        # 屏蔽环境变量里的 DEEPSEEK_API_KEY，保证单测不发起真实 LLM 网络调用
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            apps, unparsed, _stated = parse_applications("", text, llm_cfg={"api_key": ""})
        self.assertEqual(apps, [])
        self.assertEqual(len(unparsed), 1)


class TestReconcile(unittest.TestCase):
    def test_mismatch_warns(self):
        warnings = reconcile({"垫付": 2595.0},
                             [{"type": "垫付", "amount": 2250.0}])
        self.assertTrue(len(warnings) > 0)
        self.assertIn("差额 ¥345", warnings[0])

    def test_match_no_warning(self):
        self.assertEqual(
            reconcile({"垫付": 2250.0}, [{"type": "垫付", "amount": 2250.0}]),
            [])

    def test_missing_stated_skipped(self):
        self.assertEqual(reconcile({}, [{"type": "垫付", "amount": 1.0}]), [])


class TestClassify(unittest.TestCase):
    def test_strong(self):
        kw, strength = classify("求歌名！太喜欢了", ["求歌名"], ["歌"])
        self.assertEqual((kw, strength), ("求歌名", "strong"))

    def test_long_keyword_first(self):
        # 回归：短词"什么歌"是长词子串，长词必须优先命中
        kw, _ = classify("这首歌叫什么歌？", STRONG, WEAK)
        self.assertEqual(kw, "这首歌叫什么歌")

    def test_bgm_case_insensitive(self):
        for text in ("求BGM", "Bgm是什么", "bgm"):
            kw, strength = classify(text, ["BGM"], [])
            self.assertEqual((kw, strength), ("BGM", "strong"))

    def test_weak(self):
        kw, strength = classify("唱了一首歌", STRONG, WEAK)
        self.assertEqual((kw, strength), ("歌", "weak"))

    def test_no_hit(self):
        self.assertEqual(classify("今天天气不错", STRONG, WEAK), (None, ""))


if __name__ == "__main__":
    unittest.main()
