"""支付的纯函数：签名、验签、解密（微信 APIv3、支付宝 RSA2、假网关 HMAC）、读密钥文件、二维码。

不联网、不读 .env、不 import 节点；节点文件和网关客户端 import 这里。只用已装的 cryptography（wechatpy[cryptography] 带进来的）。
"""
