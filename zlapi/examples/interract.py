from zlapi import ZaloAPI
from zlapi.models import Message, MessageStyle, MultiMsgStyle
import json
import subprocess
import os

# Load configuration from config.json
with open('config.json', 'r') as config_file:
    config = json.load(config_file)

imei = config['imei']
cookies = config['cookies']
phone_number = config['phone_number']
password = config['password']

# Define styles
bold = MessageStyle(style="bold", length=4, offset=0, auto_format=False)
italic = MessageStyle(style="italic", length=6, offset=5, auto_format=False)
underline = MessageStyle(style="underline", length=9, offset=12, auto_format=False)
strike = MessageStyle(style="strike", length=6, offset=22, auto_format=False)
color = MessageStyle(style="color", color="#ff0000", length=5, offset=29, auto_format=False)
bigfont = MessageStyle(style="font", size="50", length=3, offset=35, auto_format=False)
smallfont = MessageStyle(style="font", size="10", length=5, offset=39, auto_format=False)
style = MultiMsgStyle([bold, italic, underline, strike, color, bigfont, smallfont])
smallfont = MessageStyle(style="font", size="500", length=5, offset=39, auto_format=False)
class InfoBot(ZaloAPI):
    def __init__(self, phone_number, password, imei, session_cookies):
        super().__init__(phone_number, password, imei=imei, session_cookies=session_cookies)

    def onMessage(self, mid, author_id, message, message_object, thread_id, thread_type):
        # Call parent class method directly without using super()
        ZaloAPI.onMessage(self, mid, author_id, message, message_object, thread_id, thread_type)
        
        # Ensure message content is accessed correctly
        content = message_object.content if message_object and hasattr(message_object, 'content') else ""
        
        # Check if the message is a command
        if content == "/info":
            user_info = self.fetchUserInfo(author_id)
            self.send(Message(text=str(user_info), styles=[style]), thread_id=thread_id, thread_type=thread_type)
        
        elif content == "/test":
            big_test_text = "Tmr Virus"
            self.send(Message(text=big_test_text, styles=[style]), thread_id=thread_id, thread_type=thread_type)
        
        elif isinstance(content, str) and content.startswith("sms"):
            user_id = author_id
            
            parts = content.split()
            if len(parts) == 1:
                self.send(Message(text='🚫 Vui lòng nhập số điện thoại.\n\nVí dụ: sms 0987654321', styles=[style]), thread_id=thread_id, thread_type=thread_type)
                return
            attack_phone_number = parts[1]
            if not attack_phone_number.isnumeric():
                self.send(Message(text='❌ Số điện thoại không hợp lệ!', styles=[style]), thread_id=thread_id, thread_type=thread_type)
                return
            if attack_phone_number in ['113', '911', '114', '115', '+84328774559', '0328774559']:
                self.send(Message(text="⛔ Số này không thể spam.", styles=[style]), thread_id=thread_id, thread_type=thread_type)
                return
            
            file_path = os.path.join(os.getcwd(), "test.py")
            process = subprocess.Popen(["python", file_path, attack_phone_number])
            
            masked_phone_number = f"{attack_phone_number[:3]}***{attack_phone_number[-3:]}"
            msg_content = f'''
🚀 Gửi Yêu Cầu Tấn Công Thành Công 🚀
📞 Số Tấn Công: {masked_phone_number}
Admin: Tmr Virus²⁰³
            '''
            self.send(Message(text=msg_content, styles=[style]), thread_id=thread_id, thread_type=thread_type)
        
        elif content == "/how":
            how_to_text = '''
📝 Hướng Dẫn Sử Dụng:
- Sử dụng lệnh sms {số điện thoại} để gửi tin nhắn SMS.
- Chỉ những người dùng được phép mới có quyền sử dụng lệnh này.\nVí dụ: sms 0987654321
            '''
            self.send(Message(text=how_to_text, styles=[style]), thread_id=thread_id, thread_type=thread_type)
        
        

# Initialize and listen for messages
client = InfoBot(phone_number, password, imei=imei, session_cookies=cookies)
client.listen()
