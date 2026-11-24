"""平台适配器（模块 C：闲鱼、小红书、抖音）。11-18 模块 A 先建了这个包放红线词表（redline.py），适配器由模块 C 加。

依赖只许 core 和 intake（intake 里只许 adapters、platform_texts、pricing、runtime）；intake 不许 import 这里。
"""
