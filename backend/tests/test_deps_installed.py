"""锁文件里该有的库都在（机器人假模型、企业微信加解密、图片处理）。"""


def test_key_libraries_importable():
    from PIL import Image  # noqa: F401
    from pydantic_ai.models.function import FunctionModel  # noqa: F401
    from pydantic_ai.models.test import TestModel  # noqa: F401
    from wechatpy.enterprise.crypto import WeChatCrypto  # noqa: F401
