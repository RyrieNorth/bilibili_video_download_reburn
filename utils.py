import os
import sys
import platform
import requests
import json
from time import sleep
import qrcode

# 保存cookie的文件
cookie_file = "cookie.json"

# 加载配置文件
def load_config(file_path="config.json"):
    """加载配置文件，并检查文件是否存在"""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"配置文件 {file_path} 不存在，请检查路径。")
    
    with open(file_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config


try:
    config = load_config("config.json")
except FileNotFoundError as e:
    print(e)
    # 可以在这里添加其他处理代码，例如退出程序
    exit(1)


# 根据操作系统导入相应的库
if platform.system() == "Windows":
    from PyQt5.QtWidgets import (
        QApplication,
        QLabel,
        QVBoxLayout,
        QWidget,
        QMainWindow,
        QDesktopWidget,
    )
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtCore import Qt, QThread, pyqtSignal
    import io

    class QRCodePoller(QThread):
        status_signal = pyqtSignal(str)
        regenerate_signal = pyqtSignal()
        finish_signal = pyqtSignal()

        def __init__(self, qrcode_key):
            super().__init__()
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
                print(res["data"]['message'])

                if res_code == 86101:
                    self.status_signal.emit("未扫码，请扫描二维码。")
                elif res_code == 86090:
                    self.status_signal.emit("二维码已扫码，等待确认...")
                elif res_code == 86038:
                    self.status_signal.emit("二维码已失效，重新生成二维码。")
                    self.regenerate_signal.emit()
                    break
                elif res_code == 0:
                    self.status_signal.emit("登录成功！")
                    self.save_cookies_as_json(response.headers)
                    self.finish_signal.emit()
                    break
                else:
                    self.status_signal.emit("未知状态，退出。")
                    self.finish_signal.emit()
                    break

                sleep(2)  # 每2秒轮询一次

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

    class QRCodeApp(QMainWindow):
        def __init__(self):
            super().__init__()
            self.initUI()
            self.qrcode_key = None

        def initUI(self):
            self.setWindowTitle("Bilibili QR Code Login")
            self.resize(300, 300)
            self.center()

            self.central_widget = QWidget()
            self.setCentralWidget(self.central_widget)
            self.layout = QVBoxLayout(self.central_widget)

            self.qr_label = QLabel(self)
            self.qr_label.setAlignment(Qt.AlignCenter)
            self.layout.addWidget(self.qr_label)

            self.status_label = QLabel("状态: 请扫描二维码", self)
            self.status_label.setAlignment(Qt.AlignCenter)
            self.layout.addWidget(self.status_label)

            self.qrcode_key = self.generate_qrcode()

            if self.qrcode_key:
                self.start_polling()

        def is_login(self, session):
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
                print(f"Cookies 值有效, {login_url['data']['uname']}, 已登录！")
                return True
            else:
                print("Cookies 值已经失效，请重新扫码登录！")
                return False

        def center(self):
            screen = QDesktopWidget().screenGeometry()
            size = self.geometry()
            x = (screen.width() - size.width()) // 2
            y = (screen.height() - size.height()) // 2
            self.move(x, y)

        def generate_qrcode(self):
            response = requests.get(
                url=config["url"]["get_qrcode"],
                headers=config["basic_headers"],
            )
            data = response.json()
            if data["code"] == 0:
                qrcode_key = data["data"]["qrcode_key"]
                url = data["data"]["url"]

                img = qrcode.make(url)
                img = img.resize((200, 200))
                qpixmap = self.pil_to_pixmap(img)
                self.qr_label.setPixmap(qpixmap)
                return qrcode_key
            else:
                self.status_label.setText("状态: 获取二维码失败")
                return None

        def start_polling(self):
            self.poller = QRCodePoller(self.qrcode_key)
            self.poller.status_signal.connect(self.update_status)
            self.poller.regenerate_signal.connect(self.regenerate_qrcode)
            self.poller.finish_signal.connect(self.close_application)
            self.poller.start()

        def update_status(self, message):
            self.status_label.setText(f"状态: {message}")

        def regenerate_qrcode(self):
            self.qrcode_key = self.generate_qrcode()
            if self.qrcode_key:
                self.start_polling()

        def close_application(self):
            QApplication.quit()

        def pil_to_pixmap(self, img):
            byte_arr = io.BytesIO()
            img.save(byte_arr, format="PNG")
            qpixmap = QPixmap()
            qpixmap.loadFromData(byte_arr.getvalue())
            return qpixmap

elif platform.system() == "Linux":
    class QRCodeTerminal:
        def __init__(self, data, version=1):
            self.data = data
            self.version = version
            self.white_block = '\033[0;37;47m  '
            self.black_block = '\033[0;37;40m  '
            self.new_line = '\033[0m\n'

        def qr_terminal_str(self):
            qr = qrcode.QRCode(self.version)
            qr.add_data(self.data)
            qr.make()
            output = self.white_block * (qr.modules_count + 2) + self.new_line
            for row in qr.modules:
                output += self.white_block
                for module in row:
                    if module:
                        output += self.black_block
                    else:
                        output += self.white_block
                output += self.white_block + self.new_line
            output += self.white_block * (qr.modules_count + 2) + self.new_line
            return output

        def draw(self):
            output = self.qr_terminal_str()
            print(output)

    class QRCodePollerLinux:
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
                print(res["data"]['message'])


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

                sleep(2)

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
    if platform.system() == "Windows":
        app = QApplication(sys.argv)
        window = QRCodeApp()
        window.show()
        sys.exit(app.exec_())
    elif platform.system() == "Linux":
        data = requests.get(
            url=config["url"]["get_qrcode"],
            headers=config["basic_headers"],
        ).json()
        if data["code"] == 0:
            url = data["data"]["url"]
            qr_terminal = QRCodeTerminal(url)
            qr_terminal.draw()
            poller = QRCodePollerLinux(data["data"]["qrcode_key"])
            poller.run()
        else:
            print("获取二维码失败")