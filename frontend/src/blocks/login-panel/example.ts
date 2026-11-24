import { defineBlockDemo } from "@/lib/blocks";

import { LoginPanel } from "./LoginPanel";

const start = () => Promise.resolve({ masked: "138****5678", message: "验证码发到 138****5678 了，5 分钟内有效", ttl_min: 5 });
const qr = "/api/channels/login/qr/Ldemo/fake.svg";

export default defineBlockDemo({
  block: "login-panel",
  title: "登录框（按设备给方式：微信里 / 电脑扫码 / 手机号）",
  order: 65,
  component: LoginPanel,
  examples: [
    { name: "电脑：扫码 + 手机号", props: { methods: ["qr", "sms"], lead: "登录以后，这单记在你的账号下。", qr: { image: qr, status: "pending" },
      onSmsStart: start, onSmsVerify: () => Promise.resolve() } },
    { name: "电脑：二维码过期", props: { methods: ["qr", "sms"], qr: { image: qr, status: "expired" }, onSmsStart: start, onSmsVerify: () => Promise.resolve() } },
    { name: "微信里", props: { methods: ["wx", "sms"], onSmsStart: start, onSmsVerify: () => Promise.resolve() } },
    { name: "手机浏览器", props: { methods: ["sms"], onSmsStart: start, onSmsVerify: () => Promise.resolve() } },
    { name: "微信授权没成", props: { methods: ["wx", "sms"], error: "没拿到微信的授权，再试一次，或者换手机号登录。", onSmsStart: start,
      onSmsVerify: () => Promise.resolve() } },
  ],
});
