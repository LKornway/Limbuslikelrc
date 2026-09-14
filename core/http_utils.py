"""
统一的 HTTP 请求工具模块。

程序内所有网络请求默认走**直连线路**：不读取系统代理设置，也不使用
环境变量中的 HTTP_PROXY / HTTPS_PROXY，避免用户开启 VPN / 代理软件时
歌词与封面接口被代理接管而失败（例如 SSL EOF、连接超时）。

如需走代理（例如所在网络环境下直连不可用），可在设置中填写代理地址，
由本模块统一生效。

对外接口：
    http_get        —— GET 二进制内容（urllib，直连）
    http_get_json   —— GET 并解析 JSON
    new_session     —— 创建禁用环境代理的 requests.Session（网易云平台使用）
    set_proxy       —— 设置自定义代理（空字符串 = 直连）
"""

import json
import urllib.request

DEFAULT_TIMEOUT = 8

# 自定义代理地址；空字符串表示直连（默认）
_proxy_url = ""

# 共享 requests 会话（代理变更时重建）
_shared_session = None


def set_proxy(url):
    """
    设置网络代理。

    Args:
        url: 代理地址（如 http://127.0.0.1:7897）；空字符串表示直连。
    """

    global _proxy_url, _shared_session
    _proxy_url = (url or "").strip()
    # 重建共享会话，使新代理立即生效
    _shared_session = None


def get_proxy():
    """返回当前代理地址（空字符串表示直连）。"""

    return _proxy_url


def _build_opener():
    """
    构建 urllib opener：直连时使用空代理表，彻底忽略系统与环境代理。

    Returns:
        urllib.request.OpenerDirector: 用于发起请求的 opener。
    """

    if _proxy_url:
        handler = urllib.request.ProxyHandler(
            {"http": _proxy_url, "https": _proxy_url}
        )
    else:
        # 空字典 = 明确不使用任何代理（直连）
        handler = urllib.request.ProxyHandler({})
    return urllib.request.build_opener(handler)


def http_get(url, headers=None, timeout=DEFAULT_TIMEOUT):
    """
    GET 请求并返回原始字节。

    Args:
        url: 请求地址。
        headers: 请求头字典。
        timeout: 超时秒数。

    Returns:
        bytes: 响应内容。
    """

    request = urllib.request.Request(url, headers=headers or {})
    with _build_opener().open(request, timeout=timeout) as response:
        return response.read()


def http_get_json(url, headers=None, timeout=DEFAULT_TIMEOUT):
    """
    GET 请求并解析 JSON。

    Args:
        url: 请求地址。
        headers: 请求头字典。
        timeout: 超时秒数。

    Returns:
        dict | list: 解析后的 JSON 数据。
    """

    return json.loads(http_get(url, headers, timeout).decode("utf-8", "ignore"))


def new_session(timeout=DEFAULT_TIMEOUT):
    """
    创建 requests 会话：默认忽略环境变量代理（直连），可选用自定义代理。

    Args:
        timeout: 默认超时秒数（写入 session.timeout 供调用方参考）。

    Returns:
        requests.Session: 已配置好的会话对象。
    """

    import requests

    session = requests.Session()
    # 不读取 HTTP_PROXY / HTTPS_PROXY 等环境变量
    session.trust_env = False
    session.proxies = (
        {"http": _proxy_url, "https": _proxy_url} if _proxy_url else {}
    )
    session.timeout = timeout
    return session


def shared_session(timeout=DEFAULT_TIMEOUT):
    """
    返回进程内共享的 requests 会话（复用以保持连接池）。

    Args:
        timeout: 首次创建时的默认超时秒数。

    Returns:
        requests.Session: 共享会话对象。
    """

    global _shared_session
    if _shared_session is None:
        _shared_session = new_session(timeout)
    return _shared_session
