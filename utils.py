import os
import requests
import json
import time
import qrcode
import io

# 保存cookie的文件
cookie_file = "cookie.json"


# 加载配置文件
def load_config(file_path="config.json"):
    """加载配置文件，并检查文件是否存在"""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"配置文件 {file_path} 不存在，请检查路径。")
    else:
        with open(file_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return config


config = load_config("config.json")


def is_login(session):
    try:
        with open(cookie_file, "r") as f:
            cookies = json.load(f)
            session.cookies.update(cookies)
    except Exception as e:
        print(f"加载 Cookie 失败: {e}")
        return False

    login_url = session.get(
        url=config["url"]["login_url"],
        headers=config["basic_headers"],
    ).json()

    if login_url["code"] == 0:
        res = f"Cookies 值有效, 用户 '{login_url['data']['uname']}' 已登录！"
        return res
    else:
        return False


def login_action():
    data = requests.get(
        url=config["url"]["get_qrcode"],
        headers=config["basic_headers"],
    ).json()
    if data["code"] == 0:
        url = data["data"]["url"]
        qr_terminal = QRCodeTerminal(url)
        qr_terminal.draw()
        poller = QRCodePoller(data["data"]["qrcode_key"])
        poller.run()
    else:
        print("未知错误")


class QRCodeTerminal:
    def __init__(self, data, version=None):
        self.data = data
        self.version = version

    def qr_terminal_str(self):
        qr = qrcode.QRCode(self.version)
        qr.add_data(self.data)
        qr.make()
        f = io.StringIO()
        qr.print_ascii(out=f, tty=False, invert=True)
        f.seek(0)
        output = f.read()
        return output

    def draw(self):
        output = self.qr_terminal_str()
        print(output)


class QRCodePoller:
    def __init__(self, qrcode_key):
        self.qrcode_key = qrcode_key

    def run(self):
        while True:
            response = requests.get(
                url=config["url"]["check_qrcode_scan"],
                params={"qrcode_key": self.qrcode_key},
                headers=config["basic_headers"],
            )
            res = response.json()
            res_code = res["data"]["code"]

            if res_code == 86101:
                print("未扫码，请扫描二维码。")
            elif res_code == 86090:
                print("二维码已扫码，等待确认...")
            elif res_code == 86038:
                print("二维码已失效，重新生成二维码。")
                self.regenerate_qrcode()
                break
            elif res_code == 0:
                print("登录成功！")
                self.save_cookies_as_json(response.headers)
                break
            else:
                print("未知状态，退出。")
                break

            time.sleep(2)

    def save_cookies_as_json(self, headers):
        cookies = headers.get("Set-Cookie")
        if cookies:
            cookies_dict = {}
            cookie_items = cookies.split(", ")

            for item in cookie_items:
                key_value = item.split(";", 1)[0]
                if "=" in key_value:
                    key, value = key_value.split("=", 1)
                    cookies_dict[key.strip()] = value.strip()

            with open(cookie_file, "w") as f:
                json.dump(cookies_dict, f, indent=4)

            print("Cookie 已保存为 JSON 文件。")
        else:
            print("未找到 Cookie 信息。")

    def regenerate_qrcode(self):
        response = requests.get(
            url=config["url"]["get_qrcode"],
            headers=config["basic_headers"],
        )
        data = response.json()
        if data["code"] == 0:
            url = data["data"]["url"]
            qr_terminal = QRCodeTerminal(url)
            qr_terminal.draw()
            self.qrcode_key = data["data"]["qrcode_key"]
            self.run()
        else:
            print("获取二维码失败")
