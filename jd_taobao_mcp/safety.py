from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse


_ALLOWED_ROOT_DOMAINS = (
    "jd.com",
    "360buy.com",
    "taobao.com",
    "tmall.com",
)

_BLOCKED_SCHEMES = {"file", "ftp", "data", "javascript", "chrome", "edge"}

# MCP 的模型参数不能替代真实用户确认，因此默认直接阻止可能产生账户或交易状态变化的动作。
_STATE_CHANGING_PATTERNS = (
    r"立即购买",
    r"购买",
    r"加入购物车",
    r"购物车",
    r"提交订单",
    r"确认订单",
    r"去结算",
    r"结算",
    r"支付",
    r"付款",
    r"确认收货",
    r"申请退款",
    r"退款",
    r"退货",
    r"充值",
    r"转账",
    r"开通白条",
    r"借款",
    r"收藏",
    r"关注店铺",
    r"关注",
    r"取消关注",
    r"删除",
    r"注销",
    r"退出登录",
    r"修改密码",
    r"新增地址",
    r"修改地址",
    r"保存地址",
    r"提交评价",
    r"发布评价",
    r"领券",
    r"领取优惠券",
)
_STATE_CHANGING_RE = re.compile("|".join(_STATE_CHANGING_PATTERNS), re.I)

_SENSITIVE_INPUT_RE = re.compile(
    r"密码|验证码|短信码|动态码|安全码|支付密码|银行卡|身份证|CVV|CVC|OTP",
    re.I,
)

_VERIFICATION_RE = re.compile(
    "\u6ed1\u5757|\u5b89\u5168\u9a8c\u8bc1|\u5f02\u5e38\u8bbf\u95ee|\u8bbf\u95ee\u8fc7\u4e8e\u9891\u7e41|\u8bf7\u5b8c\u6210\u9a8c\u8bc1|\u8bf7\u5148\u9a8c\u8bc1|\u8f93\u5165\u9a8c\u8bc1\u7801|\u83b7\u53d6\u9a8c\u8bc1\u7801|\u9a8c\u8bc1\u7801\u9519\u8bef|captcha|\u4eba\u673a\u9a8c\u8bc1|\u62d6\u52a8.*\u9a8c\u8bc1|\u62d6\u52a8\u4e0b\u65b9\u6ed1\u5757|\u62d6\u52a8\u5230\u6700\u53f3\u8fb9|\u9a8c\u8bc1\u5931\u8d25|\u70b9\u51fb\u6846\u4f53\u91cd\u8bd5|drag.*verify|verification failed|\u8acb\u5b8c\u6210\u9a57\u8b49|\u5b89\u5168\u9a57\u8b49|\u9a57\u8b49\u5931\u6557",
    re.I,
)


class SafetyError(RuntimeError):
    """Raised when an action violates the MCP server safety boundary."""


@dataclass(frozen=True, slots=True)
class ElementSafetyMetadata:
    text: str = ""
    aria_label: str = ""
    title: str = ""
    value: str = ""
    href: str = ""
    input_type: str = ""
    placeholder: str = ""
    name: str = ""
    form_action: str = ""

    def combined_text(self) -> str:
        return " ".join(
            part
            for part in (
                self.text,
                self.aria_label,
                self.title,
                self.value,
                self.href,
                self.placeholder,
                self.name,
            )
            if part
        )


def _host_matches(host: str, root: str) -> bool:
    host = host.lower().rstrip(".")
    return host == root or host.endswith("." + root)


def is_allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() in _BLOCKED_SCHEMES:
        return False
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return any(_host_matches(host, root) for root in _ALLOWED_ROOT_DOMAINS)


def ensure_allowed_url(url: str) -> str:
    if not is_allowed_url(url):
        raise SafetyError(
            "仅允许访问京东、淘宝和天猫域名；不允许 file://、本地地址或任意第三方网站。"
        )
    return url


def is_taobao_url(url: str) -> bool:
    """Use the same hostname normalization as the domain allowlist."""
    host = urlparse(url).hostname or ""
    return any(_host_matches(host, root) for root in ("taobao.com", "tmall.com"))


def ensure_click_allowed(
    metadata: ElementSafetyMetadata,
    *,
    allow_state_changing_actions: bool,
) -> None:
    if allow_state_changing_actions:
        return
    combined = metadata.combined_text()
    if _STATE_CHANGING_RE.search(combined):
        raise SafetyError(
            "该元素可能引发购买、结算、支付、购物车、关注、删除或其他账户状态变化，"
            "当前服务器按只读模式阻止了此次点击。"
        )


def ensure_typing_allowed(metadata: ElementSafetyMetadata) -> None:
    if metadata.input_type.lower() == "password":
        raise SafetyError("禁止通过 MCP 向密码框输入内容，请在浏览器窗口中手动完成登录。")
    if _SENSITIVE_INPUT_RE.search(metadata.combined_text()):
        raise SafetyError(
            "禁止通过 MCP 输入密码、验证码、银行卡、身份证或其他敏感认证信息；"
            "请在浏览器窗口中手动输入。"
        )


def page_requires_user_verification(text: str, url: str = "") -> bool:
    parsed = urlparse(url)
    jd_login = (
        (parsed.hostname or "").lower().rstrip(".") == "passport.jd.com"
        and parsed.path.lower().startswith(("/new/login", "/uc/login", "/login"))
    )
    return jd_login or bool(_VERIFICATION_RE.search(f"{url}\n{text[:5000]}"))
