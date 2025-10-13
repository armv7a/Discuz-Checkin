import os
import re
import sys
import time
import cloudscraper
import yaml
import requests
from datetime import datetime
from urllib.parse import urlencode

LOG_FILE = "logs.txt"
LOG_LEVELS = ["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"]

def log(msg, level="INFO"):
    if level not in LOG_LEVELS:
        level = "INFO"
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{timestamp} [{level}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def mask_sensitive_data(data, visible_chars=4):
    if not data:
        return "***"
    if len(data) <= visible_chars * 2:
        return "*" * len(data)
    return data[:visible_chars] + "*" * (len(data) - visible_chars * 2) + data[-visible_chars:]

def send_notification(title, msg, copy_to_clipboard=False):
    print("\n" + "="*60)
    print(f"📢 {title}")
    print("="*60)
    print(msg)
    print("="*60)
    
    if "❌" in title or "错误" in title:
        if sys.platform != "win32":
            print("\033[91m" + "⚠️  请检查配置或网络连接" + "\033[0m")
        else:
            print("⚠️  请检查配置或网络连接")
    
    log(f"{title}: {msg}", level="INFO")

def pushplus_send_message(pushplus_config, title, content):
    if not pushplus_config.get("enabled", False):
        log("PushPlus 推送未启用", level="INFO")
        return False
    
    token = pushplus_config.get("token", "").strip()
    if not token:
        log("PushPlus token 未配置", level="WARN")
        return False
    
    params = {
        "token": token,
        "title": title,
        "content": content,
        "template": "txt",  # 使用纯文本模板
        "channel": "wechat"  # 默认微信渠道
    }
    
    # 可选参数
    if pushplus_config.get("topic"):
        params["topic"] = pushplus_config["topic"]
    if pushplus_config.get("webhook"):
        params["webhook"] = pushplus_config["webhook"]
    if pushplus_config.get("callbackUrl"):
        params["callbackUrl"] = pushplus_config["callbackUrl"]
    
    api_url = "https://www.pushplus.plus/send"
    
    try:
        log(f"发送 PushPlus 通知: {title}", level="INFO")
        response = requests.get(api_url, params=params, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 200:
                msg_id = result.get("data", "未知ID")
                log(f"PushPlus 消息发送成功，消息ID: {mask_sensitive_data(msg_id)}", level="INFO")
                return True
            else:
                log(f"PushPlus 消息发送失败: {result.get('msg', '未知错误')}", level="ERROR")
                return False
        else:
            log(f"PushPlus API 请求失败，状态码: {response.status_code}", level="ERROR")
            return False
            
    except Exception as e:
        log(f"PushPlus 推送异常: {e}", level="ERROR")
        return False

def format_push_content(all_results):
    content = "多站点论坛签到报告\n"
    content += "=" * 50 + "\n"
    
    total_sites = len(all_results)
    total_accounts = 0
    total_success = 0
    
    for site_name, site_data in all_results.items():
        results = site_data["results"]
        total_accounts += len(results)
        site_success = sum(1 for r in results if "成功" in r or "已签" in r)
        total_success += site_success
        
        content += f"\n🏠 站点: {site_name}\n"
        content += f"   处理账号: {len(results)} 个\n"
        content += f"   成功: {site_success} 个\n"
        content += f"   失败: {len(results) - site_success} 个\n"
        content += f"   成功率: {site_success/len(results)*100:.1f}%\n"
        
        for idx, result in enumerate(results, 1):
            content += f"   {idx}. {result}\n"
    
    content += "\n" + "=" * 50 + "\n"
    content += f"📊 全局统计: {total_sites} 个站点, {total_accounts} 个账号\n"
    content += f"✅ 总成功: {total_success}/{total_accounts}\n"
    content += f"❌ 总失败: {total_accounts - total_success}/{total_accounts}\n"
    content += f"📈 总成功率: {total_success/total_accounts*100:.1f}%\n"
    content += "=" * 50 + "\n"
    
    return content, total_success, total_accounts

def load_config(config_path):
    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(
                "# 多站点配置示例\n"
                "sites:\n"
                "  - name: \"站点1名称\"\n"
                "    url: \"https://example1.com\"\n"
                "    auth:\n"
                "      accounts:\n"
                "        - cookies: \"xxx=yyy;mmm=nnn\"\n"
                "          # formhash: \"abc123\"  # 可选：自定义 formhash，如果自动获取失败可手动设置\n"
                "        - cookies: \"aaa=bbb;ccc=ddd\"\n"
                "          formhash: \"def456\"  # 为特定账号设置固定 formhash\n"
                "    options:\n"
                "      rotate_accounts: true\n"
                "      timeout: 15\n\n"
                "  - name: \"站点2名称\"\n"
                "    url: \"https://example2.com\"\n"
                "    auth:\n"
                "      accounts:\n"
                "        - cookies: \"eee=fff;ggg=hhh\"\n"
                "    options:\n"
                "      rotate_accounts: true\n"
                "      timeout: 15\n\n"
                "# PushPlus 推送配置\n"
                "pushplus:\n"
                "  enabled: false  # 是否启用推送\n"
                "  token: \"\"  # 在 pushplus.plus 官网获取令牌\n"
                "  # channel 默认为 wechat（微信）\n"
                "  # template 默认为 txt（纯文本）\n"
            )
        log("未找到 config.yaml，已创建多站点模板，请填写后重试。", level="FATAL")
        raise FileNotFoundError("未找到 config.yaml，已创建多站点模板，请填写后重试。")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    sites_config = []
    if "sites" in config:
        sites_config = config.get("sites", [])
    else:
        # 兼容旧版配置格式
        base_url = config.get("site", {}).get("url", "").rstrip("/")
        cookie_list = config.get("auth", {}).get("cookies", [])
        options = config.get("options", {})
        if base_url and cookie_list:
            # 将旧格式转换为新格式
            accounts = [{"cookies": cookie} for cookie in cookie_list]
            sites_config = [{
                "name": "默认站点",
                "url": base_url,
                "auth": {"accounts": accounts},
                "options": options
            }]

    if not sites_config:
        log("未找到有效的站点配置", level="FATAL")
        raise ValueError("config.yaml 中未配置任何站点，请检查配置。")

    pushplus_config = config.get("pushplus", {})

    # 验证每个站点的配置
    validated_sites = []
    for site in sites_config:
        base_url = site.get("url", "").rstrip("/")
        auth_config = site.get("auth", {})
        
        # 支持两种格式：accounts 列表或 cookies 列表（兼容旧版）
        if "accounts" in auth_config:
            accounts = auth_config["accounts"]
        elif "cookies" in auth_config:
            # 兼容旧版：将 cookies 列表转换为 accounts 列表
            accounts = [{"cookies": cookie} for cookie in auth_config["cookies"]]
        else:
            accounts = []
            
        options = site.get("options", {})
        site_name = site.get("name", "未命名站点")
        
        if not base_url:
            log(f"站点 '{site_name}' 的 url 为空，已跳过", level="ERROR")
            continue
        if not accounts:
            log(f"站点 '{site_name}' 的 accounts 为空，已跳过", level="ERROR")
            continue
        
        validated_accounts = []
        for account in accounts:
            cookies = account.get("cookies", "")
            formhash = account.get("formhash", "")  # 获取自定义 formhash
            if not cookies:
                log(f"站点 '{site_name}' 中发现空的 cookies，已跳过该账号", level="WARN")
                continue
            validated_accounts.append({
                "cookies": cookies,
                "formhash": formhash
            })
        
        if not validated_accounts:
            log(f"站点 '{site_name}' 没有有效的账号配置，已跳过", level="ERROR")
            continue
            
        validated_sites.append({
            "name": site_name,
            "url": base_url,
            "accounts": validated_accounts,
            "options": options
        })
        log(f"站点配置加载成功: {site_name} - {len(validated_accounts)} 个账号", level="INFO")

    if not validated_sites:
        log("没有有效的站点配置", level="FATAL")
        raise ValueError("config.yaml 中没有有效的站点配置。")

    # 检查 PushPlus 配置
    if pushplus_config.get("enabled", False):
        if pushplus_config.get("token"):
            log(f"PushPlus 推送已启用，渠道: {pushplus_config.get('channel', 'wechat')}", level="INFO")
        else:
            log("PushPlus 已启用但 token 未配置，推送功能将不可用", level="WARN")
    
    return validated_sites, pushplus_config

def parse_cookie(cookie_str):
    cookies = {}
    for item in cookie_str.split(";"):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            cookies[k.strip()] = v.strip()
    # 隐藏 cookie 值，只显示键
    masked_keys = list(cookies.keys())
    log(f"解析 cookie: 共 {len(masked_keys)} 个键", level="TRACE")
    return cookies

def fetch_formhash(base_url, cookies, headers, timeout):
    scraper = cloudscraper.create_scraper()
    log(f"访问论坛首页获取 formhash: {base_url}", level="INFO")
    try:
        resp = scraper.get(base_url, headers=headers, cookies=cookies, timeout=timeout)
        log(f"访问论坛首页成功，响应长度: {len(resp.text)}", level="DEBUG")
    except Exception as e:
        log(f"访问论坛首页失败: {e}", level="ERROR")
        raise RuntimeError(f"无法访问论坛首页：{e}")

    html = resp.text
    patterns = [
        r"formhash=([a-zA-Z0-9]+)",
        r'name="formhash"\s+value="([a-zA-Z0-9]+)"'
    ]
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            formhash = m.group(1)
            log(f"formhash 获取成功: {mask_sensitive_data(formhash)}", level="INFO")
            return formhash
    log("未找到 formhash", level="WARN")
    raise ValueError("未找到 formhash，请检查登录状态或网页结构。")

def fetch_continuous_days(base_url, cookies, headers, timeout):
    scraper = cloudscraper.create_scraper()
    sign_page = f"{base_url}/k_misign-sign.html"
    try:
        resp = scraper.get(sign_page, headers=headers, cookies=cookies, timeout=timeout)
        html = resp.text
        m = re.search(r'<input type="hidden" class="hidnum" id="lxdays" value="(\d+)">', html)
        if m:
            days = m.group(1)
            log(f"连续签到天数获取成功: {days}", level="INFO")
            return days
        else:
            log("未找到连续签到天数", level="WARN")
            return None
    except Exception as e:
        log(f"访问签到页失败: {e}", level="ERROR")
        return None

def sign_account(base_url, account_config, timeout, account_num, site_name):
    cookie_str = account_config["cookies"]
    custom_formhash = account_config.get("formhash", "")
    
    print(f"\n🎯 开始处理站点 '{site_name}' 的第 {account_num} 个账号...")
    if custom_formhash:
        print(f"📝 使用自定义 formhash: {mask_sensitive_data(custom_formhash)}")
    
    cookies = parse_cookie(cookie_str)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/114.0.0.0 Safari/537.36",
        "Referer": base_url + "/",
        "Origin": base_url,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive",
    }

    # 优先使用自定义 formhash，如果未设置则自动获取
    if custom_formhash:
        formhash = custom_formhash
        log(f"使用自定义 formhash: {mask_sensitive_data(formhash)}", level="INFO")
    else:
        try:
            formhash = fetch_formhash(base_url, cookies, headers, timeout)
        except Exception as e:
            msg = f"第 {account_num} 个账号 formhash 获取失败: {e}"
            log(msg, level="ERROR")
            return msg

    url = f"{base_url}/k_misign-sign.html?operation=qiandao&format=button&formhash={formhash}"
    log(f"发送签到请求", level="INFO")
    scraper = cloudscraper.create_scraper()
    try:
        resp = scraper.get(url, headers=headers, cookies=cookies, timeout=timeout)
        log(f"签到请求成功，响应长度: {len(resp.text)}", level="DEBUG")
    except Exception as e:
        msg = f"第 {account_num} 个账号请求失败: {e}"
        log(msg, level="ERROR")
        return msg

    text = resp.text.strip()
    if resp.status_code == 200:
        if text.startswith("<?xml") and "今日已签" in text:
            msg = "✅ 今日已签，明日再来~"
        elif "签到成功" in text and "已签到" in text:
            m = re.search(r"获得随机奖励\s*(.*?)。", text)
            reward = m.group(1) if m else "未知奖励"
            msg = f"🎉 签到成功，奖励：{reward}"
        else:
            msg = f"❓ 未知响应"
            log(f"未知签到响应内容: {text[:200]}", level="WARN")
    else:
        msg = f"❌ 签到失败，状态码：{resp.status_code}"
        log(msg, level="ERROR")

    # 获取连续签到天数
    days = fetch_continuous_days(base_url, cookies, headers, timeout)
    if days:
        msg += f" | 连续签到: {days} 天"
    else:
        log("未能获取连续签到天数", level="WARN")

    print(f"📝 站点 '{site_name}' 第 {account_num} 个账号结果: {msg}")
    log(msg, level="INFO")
    return msg

def sign_site(site_config):
    site_name = site_config["name"]
    base_url = site_config["url"]
    account_list = site_config["accounts"]
    options = site_config["options"]
    timeout = options.get("timeout", 15)
    
    print(f"\n{'='*60}")
    print(f"🏠 开始处理站点: {site_name}")
    print(f"🌐 论坛地址: {base_url}")
    print(f"📋 账号数量: {len(account_list)}")
    print(f"{'='*60}")
    
    results = []
    for idx, account_config in enumerate(account_list, 1):
        result = sign_account(base_url, account_config, timeout, idx, site_name)
        results.append(result)
        if options.get("rotate_accounts", True) and idx < len(account_list):
            print("⏳ 等待 2 秒后处理下一个账号...")
            time.sleep(2)
    
    # 统计本站点成功/失败情况
    success_count = sum(1 for r in results if "成功" in r or "已签" in r)
    fail_count = len(results) - success_count
    
    print(f"\n📊 站点 '{site_name}' 统计: 成功 {success_count}/{len(results)} | 失败 {fail_count}/{len(results)}")
    
    return results

def main():
    start_time = datetime.now()
    print("🚀 开始执行多站点论坛签到脚本...")
    
    try:
        current_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        config_path = os.path.join(current_dir, "config.yaml")
        sites_config, pushplus_config = load_config(config_path)
    except Exception as e:
        send_notification("❌ 配置错误", str(e))
        sys.exit(1)

    print(f"\n📋 共发现 {len(sites_config)} 个站点需要处理")
    
    all_results = {}
    total_accounts = 0
    
    for site_config in sites_config:
        site_name = site_config["name"]
        total_accounts += len(site_config["accounts"])
        
        try:
            results = sign_site(site_config)
            all_results[site_name] = {
                "results": results,
                "url": site_config["url"]
            }
        except Exception as e:
            error_msg = f"站点 '{site_name}' 处理异常: {e}"
            log(error_msg, level="ERROR")
            all_results[site_name] = {
                "results": [f"❌ 处理异常: {e}"],
                "url": site_config["url"],
                "error": True
            }
        
        if len(sites_config) > 1:
            print("\n⏳ 等待 3 秒后处理下一个站点...")
            time.sleep(3)

    execution_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "🎊 多站点最终签到结果汇总 ".ljust(70, "="))
    
    for site_name, site_data in all_results.items():
        results = site_data["results"]
        success_count = sum(1 for r in results if "成功" in r or "已签" in r)
        print(f"\n🏠 {site_name}: 成功 {success_count}/{len(results)}")
        for idx, res in enumerate(results, 1):
            print(f"   {idx}. {res}")
    
    print("=" * 70)
    
    # 发送 PushPlus 通知
    if pushplus_config.get("enabled", False) and pushplus_config.get("token"):
        # 格式化推送内容
        push_content, total_success, total_accounts = format_push_content(all_results)
        
        # 创建标题 - 根据成功/失败情况使用固定标题
        if total_success == total_accounts:
            title = "✅ Discuz 论坛签到成功"
        else:
            title = "❌ Discuz 论坛签到失败"
        
        # 发送推送
        push_success = pushplus_send_message(pushplus_config, title, push_content)
        if push_success:
            print("📤 PushPlus 推送发送成功")
        else:
            print("❌ PushPlus 推送发送失败")

if __name__ == "__main__":
    main()